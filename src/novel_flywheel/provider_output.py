from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Mapping, Sequence

from novel_flywheel.domain.models import ModelResponse, ProviderOutputShapeV1


KNOWN_PROVIDER_OUTPUT_BLOCK_TYPES = frozenset({
    "text",
    "output_text",
    "tool_use",
    "tool_call",
    "function_call",
    "reasoning",
    "thinking",
    "redacted_thinking",
    "message",
})
REASONING_BLOCK_TYPES = frozenset({
    "reasoning", "thinking", "redacted_thinking",
})
TEXT_BLOCK_TYPES = frozenset({"text", "output_text"})
TOOL_BLOCK_TYPES = frozenset({"tool_use", "tool_call", "function_call"})
MAX_RAW_BLOCK_SEQUENCE = 128
MAX_UNKNOWN_BLOCK_HASHES = 32


def _sha256(domain: str, value: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _controlled_block_type(value: object) -> tuple[str, str | None]:
    normalized = str(value or "unknown").strip().casefold() or "unknown"
    if normalized in KNOWN_PROVIDER_OUTPUT_BLOCK_TYPES:
        return normalized, None
    return "unknown", _sha256("r1-ptr12-unknown-block-type-v1", normalized)


def _controlled_raw_finish(value: object) -> tuple[str, str | None]:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return "missing", None
    controlled = {
        "stop", "end_turn", "length", "max_tokens", "max_output_tokens",
        "completed", "incomplete", "failed", "cancelled",
    }
    if normalized in controlled:
        return normalized, None
    return "unknown", _sha256("r1-ptr12-finish-reason-v1", normalized)


def capture_provider_raw_shape_v1(
    *,
    protocol: str,
    body: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    requested_output_cap: int | None,
) -> None:
    """Deposit one bounded, content-free snapshot before adapter normalization."""

    try:
        from novel_flywheel.model_diagnostics import (
            ptr12_observer_enabled, record_ptr12_raw_shape,
        )
        if not ptr12_observer_enabled():
            return
        block_types: list[object] = []
        visible_chars: int | None = 0
        finish_reason: object = None
        output_tokens: int | None = None
        transport_complete: bool | None = None
        reasoning_usage: int | None = None
        final_usage: int | None = None
        observation_point = "transport_body_pre_normalization"
        response_class = "response_body"
        capture_completeness = "exact"
        if body is not None:
            if protocol == "anthropic":
                content = body.get("content")
                content = content if isinstance(content, list) else []
                block_types = [
                    part.get("type") for part in content if isinstance(part, dict)
                ]
                visible_chars = sum(
                    len(part.get("text")) for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                    and part.get("type") == "text"
                )
                finish_reason = body.get("stop_reason")
                usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                output_tokens = usage.get("output_tokens")
                transport_complete = finish_reason is not None
            elif protocol == "openai-chat":
                choices = body.get("choices")
                choices = choices if isinstance(choices, list) else []
                choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
                raw_content = message.get("content")
                raw_tools = message.get("tool_calls")
                raw_tools = raw_tools if isinstance(raw_tools, list) else []
                content_parts = raw_content if isinstance(raw_content, list) else []
                block_types = [
                    part.get("type") for part in content_parts if isinstance(part, dict)
                ]
                if isinstance(raw_content, str):
                    block_types += ["text"] if raw_content else []
                    visible_chars = len(raw_content)
                else:
                    visible_chars = sum(
                        len(part.get("text")) for part in content_parts
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
                block_types += ["tool_call"] * len(raw_tools)
                reasoning_values = [
                    message.get(key) for key in ("reasoning", "reasoning_content", "thinking")
                    if message.get(key) is not None
                ]
                block_types += ["reasoning"] * len(reasoning_values)
                finish_reason = choice.get("finish_reason")
                usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                output_tokens = usage.get("completion_tokens")
                details = usage.get("completion_tokens_details")
                details = details if isinstance(details, dict) else {}
                reasoning_usage = details.get("reasoning_tokens")
                transport_complete = finish_reason is not None
            elif protocol == "openai-responses":
                output = body.get("output")
                output = output if isinstance(output, list) else []
                nested = [
                    part for item in output if isinstance(item, dict)
                    for part in (item.get("content") or []) if isinstance(part, dict)
                ]
                block_types = [
                    item.get("type") for item in output if isinstance(item, dict)
                ] + [part.get("type") for part in nested]
                visible_chars = sum(
                    len(part.get("text")) for part in nested
                    if isinstance(part.get("text"), str)
                    and part.get("type") in TEXT_BLOCK_TYPES
                )
                finish_reason = body.get("status")
                incomplete = body.get("incomplete_details")
                incomplete = incomplete if isinstance(incomplete, dict) else {}
                if finish_reason == "incomplete" and incomplete.get("reason"):
                    finish_reason = incomplete.get("reason")
                usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                output_tokens = usage.get("output_tokens")
                details = usage.get("output_tokens_details")
                details = details if isinstance(details, dict) else {}
                reasoning_usage = details.get("reasoning_tokens")
                transport_complete = body.get("status") in {
                    "completed", "incomplete", "failed", "cancelled",
                }
            else:
                capture_completeness = "unavailable"
                visible_chars = None
        else:
            observation_point = "stream_event_shape_pre_aggregation"
            response_class = "stream_event_sequence"
            capture_completeness = "partial"
            chat_tool_keys: set[tuple[int, int]] = set()
            responses_block_keys: set[tuple[str, int, int]] = set()
            for event in events:
                if not isinstance(event, Mapping):
                    continue
                kind = str(event.get("type") or "")
                if protocol == "anthropic":
                    if kind == "content_block_start":
                        block = event.get("content_block")
                        block = block if isinstance(block, Mapping) else {}
                        block_types.append(block.get("type"))
                        if block.get("type") == "text" and isinstance(block.get("text"), str):
                            visible_chars = (visible_chars or 0) + len(block["text"])
                    elif kind == "content_block_delta":
                        delta = event.get("delta")
                        delta = delta if isinstance(delta, Mapping) else {}
                        if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                            visible_chars = (visible_chars or 0) + len(delta["text"])
                    elif kind == "message_delta":
                        delta = event.get("delta")
                        delta = delta if isinstance(delta, Mapping) else {}
                        finish_reason = delta.get("stop_reason") or finish_reason
                        usage = event.get("usage") if isinstance(event.get("usage"), Mapping) else {}
                        output_tokens = usage.get("output_tokens", output_tokens)
                elif protocol == "openai-chat":
                    for choice_ordinal, choice in enumerate(event.get("choices") or []):
                        if not isinstance(choice, Mapping):
                            continue
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta") if isinstance(choice.get("delta"), Mapping) else {}
                        if isinstance(delta.get("content"), str) and delta.get("content"):
                            if "text" not in block_types:
                                block_types.append("text")
                            visible_chars = (visible_chars or 0) + len(delta["content"])
                        if any(delta.get(key) is not None for key in ("reasoning", "reasoning_content", "thinking")):
                            if "reasoning" not in block_types:
                                block_types.append("reasoning")
                        for call in delta.get("tool_calls") or []:
                            if not isinstance(call, Mapping):
                                continue
                            call_index = call.get("index")
                            key = (
                                choice_ordinal,
                                call_index
                                if isinstance(call_index, int) and call_index >= 0
                                else len(chat_tool_keys),
                            )
                            if key not in chat_tool_keys:
                                chat_tool_keys.add(key)
                                block_types.append("tool_call")
                    usage = event.get("usage") if isinstance(event.get("usage"), Mapping) else {}
                    output_tokens = usage.get("completion_tokens", output_tokens)
                elif protocol == "openai-responses":
                    if kind in {"response.output_item.added", "response.content_part.added"}:
                        item = event.get("item") or event.get("part") or {}
                        if isinstance(item, Mapping):
                            output_index = event.get("output_index")
                            content_index = event.get("content_index")
                            key = (
                                kind,
                                output_index if isinstance(output_index, int) else 0,
                                content_index if isinstance(content_index, int) else 0,
                            )
                            if key not in responses_block_keys:
                                responses_block_keys.add(key)
                                block_types.append(item.get("type"))
                    if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                        if "output_text" not in block_types:
                            block_types.append("output_text")
                        visible_chars = (visible_chars or 0) + len(event["delta"])
                    if kind in {"response.completed", "response.incomplete", "response.failed"}:
                        response = event.get("response") if isinstance(event.get("response"), Mapping) else {}
                        finish_reason = response.get("status") or finish_reason
                        usage = response.get("usage") if isinstance(response.get("usage"), Mapping) else {}
                        output_tokens = usage.get("output_tokens", output_tokens)
            transport_complete = finish_reason is not None
        controlled: list[str] = []
        unknown_hashes: list[str] = []
        for value in block_types:
            block_type, unknown_hash = _controlled_block_type(value)
            controlled.append(block_type)
            if unknown_hash is not None and len(unknown_hashes) < MAX_UNKNOWN_BLOCK_HASHES:
                unknown_hashes.append(unknown_hash)
        sequence_omitted = len(controlled) > MAX_RAW_BLOCK_SEQUENCE
        bounded = controlled[:MAX_RAW_BLOCK_SEQUENCE]
        if sequence_omitted:
            capture_completeness = "partial"
        finish_class, finish_hash = _controlled_raw_finish(finish_reason)
        multiset = dict(sorted(Counter(controlled).items()))
        snapshot = {
            "observation_point": observation_point,
            "provider_protocol": protocol if protocol in {
                "anthropic", "openai-chat", "openai-responses",
            } else "unknown",
            "raw_response_class": response_class,
            "unknown_response_class_sha256": None,
            "raw_block_count": len(controlled),
            "raw_block_type_sequence": tuple(bounded),
            "raw_block_type_sequence_sha256": _sha256(
                "r1-ptr12-block-sequence-v1", controlled,
            ),
            "raw_block_type_multiset": multiset,
            "sequence_omitted_after_limit": sequence_omitted,
            "reasoning_block_count": sum(item in REASONING_BLOCK_TYPES for item in controlled),
            "text_or_final_block_count": sum(item in TEXT_BLOCK_TYPES for item in controlled),
            "tool_block_count": sum(item in TOOL_BLOCK_TYPES for item in controlled),
            "unknown_block_count": sum(item == "unknown" for item in controlled),
            "unknown_block_type_hashes": tuple(unknown_hashes),
            "raw_visible_char_count": visible_chars,
            "raw_visible_chars_zero": visible_chars == 0 if visible_chars is not None else None,
            "raw_final_text_present": (
                any(item in TEXT_BLOCK_TYPES for item in controlled)
                if capture_completeness != "unavailable" else None
            ),
            "raw_tool_call_present": (
                any(item in TOOL_BLOCK_TYPES for item in controlled)
                if capture_completeness != "unavailable" else None
            ),
            "finish_reason_raw_class": finish_class,
            "finish_reason_unknown_sha256": finish_hash,
            "output_token_count": output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None,
            "requested_output_cap": requested_output_cap,
            "effective_output_cap": requested_output_cap,
            "provider_accepted_cap_status": "UNKNOWN",
            "provider_exposed_reasoning_usage_status": (
                "KNOWN" if isinstance(reasoning_usage, int) else "NOT_EXPOSED"
            ),
            "provider_exposed_reasoning_usage": reasoning_usage if isinstance(reasoning_usage, int) else None,
            "provider_exposed_final_usage_status": (
                "KNOWN" if isinstance(final_usage, int) else "NOT_EXPOSED"
            ),
            "provider_exposed_final_usage": final_usage if isinstance(final_usage, int) else None,
            "transport_complete": transport_complete,
            "capture_completeness": capture_completeness,
            "content_omitted": True,
            "reasoning_content_omitted": True,
            "tool_arguments_omitted": True,
        }
        snapshot["raw_shape_fingerprint"] = _sha256(
            "r1-ptr12-raw-shape-v1", snapshot,
        )
        record_ptr12_raw_shape(snapshot)
    except Exception:
        return


def build_provider_output_shape(
    *,
    provider_family: str,
    protocol: str,
    finish_reason: object,
    output_tokens: int,
    block_types: Sequence[object],
    text_values: Sequence[object],
    reasoning_block_count: int,
    transport_complete: bool,
    normalized_text: str,
    normalized_tool_call_count: int,
) -> ProviderOutputShapeV1:
    """Build one provider-neutral shape without retaining provider content."""

    controlled: list[str] = []
    unknown_hashes: list[str] = []
    for value in block_types:
        normalized = str(value or "unknown").strip().casefold() or "unknown"
        if normalized in KNOWN_PROVIDER_OUTPUT_BLOCK_TYPES:
            controlled.append(normalized)
        else:
            controlled.append("unknown")
            unknown_hashes.append(_sha256(
                "provider-output-unknown-block-type-v1", normalized,
            ))
    visible_characters = sum(
        len(value) for value in text_values if isinstance(value, str)
    )
    tool_count = sum(value in TOOL_BLOCK_TYPES for value in controlled)
    text_count = sum(value in TEXT_BLOCK_TYPES for value in controlled)
    derived_reasoning_count = sum(
        value in REASONING_BLOCK_TYPES for value in controlled
    )
    normalized_finish = str(finish_reason or "").strip().casefold() or None
    projection_status = (
        "exact"
        if len(normalized_text) == visible_characters
        and normalized_tool_call_count == tool_count
        else "changed"
    )
    body = {
        "schema": "ProviderOutputShapeV1",
        "version": 1,
        "provider_family": str(provider_family),
        "protocol": str(protocol),
        "finish_reason": normalized_finish,
        "output_tokens": max(0, int(output_tokens or 0)),
        "content_block_count": len(controlled),
        "content_block_type_sequence": tuple(controlled),
        "unknown_block_type_sha256s": tuple(unknown_hashes),
        "text_block_count": text_count,
        "provider_visible_text_chars": visible_characters,
        "tool_call_count": tool_count,
        "reasoning_block_count": max(
            derived_reasoning_count, max(0, int(reasoning_block_count or 0)),
        ),
        "unknown_block_count": len(unknown_hashes),
        "transport_complete": bool(transport_complete),
        "normalized_visible_text_chars": len(normalized_text),
        "normalized_tool_call_count": max(0, int(normalized_tool_call_count)),
        "adapter_projection_status": projection_status,
        "raw_text_omitted": True,
        "raw_tool_arguments_omitted": True,
        "raw_provider_content_omitted": True,
        "raw_headers_omitted": True,
    }
    body["shape_sha256"] = _sha256("provider-output-shape-v1", body)
    return ProviderOutputShapeV1.model_validate(body)


def provider_output_shape_from_response(
    adapter: object,
    response: ModelResponse,
) -> ProviderOutputShapeV1 | None:
    """Project retained raw adapter state into one safe shared Runtime shape."""

    if response.output_shape is not None:
        return response.output_shape
    family = str(getattr(adapter, "DIAGNOSTIC_ADAPTER_ID", "") or "")
    state = response.provider_state or {}
    block_types: list[object]
    text_values: list[object]
    reasoning_count: int
    protocol: str
    if family == "anthropic":
        protocol = "anthropic"
        content = state.get("content")
        content = content if isinstance(content, list) else []
        block_types = [
            part.get("type") for part in content if isinstance(part, dict)
        ]
        text_values = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        reasoning_count = sum(
            part.get("type") in REASONING_BLOCK_TYPES
            for part in content if isinstance(part, dict)
        )
    elif family == "openai_chat":
        protocol = "openai-chat"
        message = state.get("assistant")
        message = message if isinstance(message, dict) else {}
        raw_content = message.get("content")
        raw_tools = message.get("tool_calls")
        raw_tools = raw_tools if isinstance(raw_tools, list) else []
        chat_blocks = raw_content if isinstance(raw_content, list) else []
        reasoning_count = sum(
            bool(message.get(key))
            for key in ("reasoning", "reasoning_content", "thinking")
        )
        block_types = (
            [
                str(part.get("type") or "unknown")
                for part in chat_blocks if isinstance(part, dict)
            ]
            + (["text"] if isinstance(raw_content, str) and raw_content else [])
            + ["tool_call"] * len(raw_tools)
            + ["reasoning"] * reasoning_count
        )
        text_values = (
            [raw_content]
            if isinstance(raw_content, str) and raw_content else []
        ) + [
            part.get("text")
            for part in chat_blocks
            if isinstance(part, dict)
            and part.get("type") in TEXT_BLOCK_TYPES
        ]
    elif family == "openai_responses":
        protocol = "openai-responses"
        output = state.get("output")
        output = output if isinstance(output, list) else []
        nested_content = [
            part
            for item in output if isinstance(item, dict)
            for part in (item.get("content") or []) if isinstance(part, dict)
        ]
        block_types = (
            [item.get("type") for item in output if isinstance(item, dict)]
            + [part.get("type") for part in nested_content]
        )
        text_values = [
            part.get("text")
            for part in nested_content
            if part.get("type") in TEXT_BLOCK_TYPES
        ]
        reasoning_count = sum(
            item.get("type") in REASONING_BLOCK_TYPES
            for item in output if isinstance(item, dict)
        )
    else:
        return None
    try:
        return build_provider_output_shape(
            provider_family=family,
            protocol=protocol,
            finish_reason=response.finish_reason,
            output_tokens=response.output_tokens,
            block_types=block_types,
            text_values=text_values,
            reasoning_block_count=reasoning_count,
            transport_complete=state.get("transport_complete", True) is not False,
            normalized_text=response.text,
            normalized_tool_call_count=len(response.tool_calls),
        )
    except (TypeError, ValueError):
        # Shape observation cannot replace the adapter's existing behavior.
        return None
