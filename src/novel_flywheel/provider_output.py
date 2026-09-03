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
MAX_BLOCKS_INSPECTED = 128
MAX_BLOCKS_TOUCHED = 128
MAX_CONTROLLED_DETAILS = 128
MAX_UNKNOWN_DETAILS = 32
MAX_HASH_INPUT_BYTES = 512
_MAX_TYPE_TOKEN_CODEPOINTS = 64


def _sha256(domain: str, value: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_type_token_fingerprint(domain: str, value: object) -> str:
    """Hash one fixed-size type token without invoking user-defined coercion."""

    if type(value) is str:
        prefix = value[:_MAX_TYPE_TOKEN_CODEPOINTS].encode(
            "utf-8", errors="replace",
        )[:256]
        descriptor = (
            b"bounded-type-token-fingerprint|"
            + domain.encode("ascii", errors="ignore")[:96]
            + b"|str|"
            + str(len(value)).encode("ascii")[:24]
            + b"|"
            + prefix
        )
    else:
        descriptor = (
            b"bounded-type-token-fingerprint|"
            + domain.encode("ascii", errors="ignore")[:96]
            + b"|non-string"
        )
    return hashlib.sha256(descriptor[:MAX_HASH_INPUT_BYTES]).hexdigest()


def _bounded_normalized_token(value: object) -> str | None:
    if type(value) is not str or len(value) > _MAX_TYPE_TOKEN_CODEPOINTS:
        return None
    return value.strip().casefold()


def _controlled_block_type(
    value: object, *, fingerprint_unknown: bool = True,
) -> tuple[str, str | None]:
    normalized = _bounded_normalized_token(value)
    if normalized in KNOWN_PROVIDER_OUTPUT_BLOCK_TYPES:
        return normalized, None
    return (
        "unknown",
        _bounded_type_token_fingerprint(
            "r1-ptr12-unknown-block-type-v1", value,
        ) if fingerprint_unknown else None,
    )


def _controlled_raw_finish(value: object) -> tuple[str, str | None]:
    if value is None or (type(value) is str and not value):
        return "missing", None
    normalized = _bounded_normalized_token(value)
    controlled = {
        "stop", "end_turn", "length", "max_tokens", "max_output_tokens",
        "completed", "incomplete", "failed", "cancelled",
    }
    if normalized in controlled:
        return normalized, None
    return "unknown", _bounded_type_token_fingerprint(
        "r1-ptr12-finish-reason-v1", value,
    )


class _BoundedRawShapeCapture:
    """One shared work budget for attacker-controlled provider topology."""

    def __init__(self) -> None:
        self.touched = 0
        self.raw_count = 0
        self.controlled: list[str] = []
        self.unknown_hashes: list[str] = []
        self.tail_unknown = False
        self.limit_reached = False

    def touch(self) -> bool:
        if self.touched >= MAX_BLOCKS_TOUCHED:
            self.tail_unknown = True
            self.limit_reached = True
            return False
        self.touched += 1
        return True

    @property
    def exhausted(self) -> bool:
        return self.limit_reached

    def observe(self, value: object, *, count_raw: bool = True) -> None:
        if count_raw:
            self.raw_count += 1
        if len(self.controlled) >= min(
            MAX_BLOCKS_INSPECTED, MAX_CONTROLLED_DETAILS,
        ):
            self.tail_unknown = True
            self.limit_reached = True
            return
        fingerprint_unknown = len(self.unknown_hashes) < MAX_UNKNOWN_DETAILS
        controlled, unknown_hash = _controlled_block_type(
            value, fingerprint_unknown=fingerprint_unknown,
        )
        self.controlled.append(controlled)
        if unknown_hash is not None:
            self.unknown_hashes.append(unknown_hash)

    def observe_repeated(self, value: str, count: int) -> None:
        safe_count = count if type(count) is int and count > 0 else 0
        self.raw_count += safe_count
        remaining = min(
            safe_count,
            MAX_BLOCKS_INSPECTED - len(self.controlled),
            MAX_CONTROLLED_DETAILS - len(self.controlled),
            MAX_BLOCKS_TOUCHED - self.touched,
        )
        for _index in range(remaining):
            if not self.touch():
                break
            self.observe(value, count_raw=False)
        if remaining < safe_count:
            self.tail_unknown = True
            self.limit_reached = True


def _exact_dict(value: object) -> dict[str, Any] | None:
    return value if type(value) is dict else None


def _exact_sequence(value: object) -> list[Any] | tuple[Any, ...] | None:
    return value if type(value) in {list, tuple} else None


def _safe_nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _formal_reasoning_usage(
    usage: dict[str, Any], *, details_key: str,
) -> tuple[str, int | None]:
    """Read only an explicitly exposed reasoning-usage field."""

    if details_key not in usage:
        return "NOT_EXPOSED", None
    details = _exact_dict(usage.get(details_key))
    if details is None:
        return "UNKNOWN", None
    if "reasoning_tokens" not in details:
        return "NOT_EXPOSED", None
    value = _safe_nonnegative_int(details.get("reasoning_tokens"))
    if value is None:
        return "UNKNOWN", None
    return "KNOWN", value


def _safe_text_length(value: object) -> int | None:
    return len(value) if type(value) is str else None


def capture_provider_raw_shape_v1(
    *,
    protocol: str,
    body: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    requested_output_cap: int | None,
    effective_output_cap: int | None = None,
) -> None:
    """Deposit one bounded, content-free snapshot before adapter normalization."""

    try:
        from novel_flywheel.model_diagnostics import (
            ptr12_observer_enabled, record_ptr12_raw_shape,
        )
        if not ptr12_observer_enabled():
            return
        safe_protocol = (
            protocol
            if type(protocol) is str and protocol in {
                "anthropic", "openai-chat", "openai-responses",
            }
            else "unknown"
        )
        safe_requested_output_cap = (
            requested_output_cap
            if type(requested_output_cap) is int and requested_output_cap >= 1
            else None
        )
        safe_effective_output_cap = (
            effective_output_cap
            if type(effective_output_cap) is int and effective_output_cap >= 1
            else safe_requested_output_cap
        )
        capture = _BoundedRawShapeCapture()
        visible_chars: int | None = 0
        finish_reason: object = None
        output_tokens: int | None = None
        transport_complete: bool | None = None
        reasoning_usage: int | None = None
        reasoning_usage_status = "NOT_EXPOSED"
        final_usage: int | None = None
        observation_point = "transport_body_pre_normalization"
        response_class = "response_body"
        capture_completeness = "exact"
        if body is not None and type(body) is not dict:
            capture_completeness = "unavailable"
            visible_chars = None
            transport_complete = None
        elif body is not None:
            if safe_protocol == "anthropic":
                content = body.get("content")
                content = _exact_sequence(content)
                if content is None:
                    capture_completeness = "unavailable"
                    visible_chars = None
                    content = ()
                capture.raw_count = len(content)
                for index in range(min(len(content), MAX_BLOCKS_TOUCHED)):
                    if not capture.touch():
                        break
                    part = _exact_dict(content[index])
                    value = part.get("type") if part is not None else None
                    capture.observe(value, count_raw=False)
                    if (
                        part is not None
                        and _bounded_normalized_token(value) == "text"
                    ):
                        text_length = _safe_text_length(part.get("text"))
                        if text_length is not None and visible_chars is not None:
                            visible_chars += text_length
                if len(content) > capture.touched:
                    capture.tail_unknown = True
                finish_reason = body.get("stop_reason")
                usage = _exact_dict(body.get("usage")) or {}
                output_tokens = _safe_nonnegative_int(usage.get("output_tokens"))
                transport_complete = finish_reason is not None
            elif safe_protocol == "openai-chat":
                choices = body.get("choices")
                choices = _exact_sequence(choices)
                choice = (
                    _exact_dict(choices[0])
                    if choices and capture.touch() else None
                ) or {}
                if choices is None:
                    capture_completeness = "unavailable"
                elif len(choices) > 1:
                    capture.tail_unknown = True
                message = _exact_dict(choice.get("message")) or {}
                raw_content = message.get("content")
                raw_tools = message.get("tool_calls")
                raw_tools = _exact_sequence(raw_tools) or ()
                content_parts = _exact_sequence(raw_content) or ()
                capture.raw_count += len(content_parts)
                for index in range(len(content_parts)):
                    if not capture.touch():
                        break
                    part = _exact_dict(content_parts[index])
                    value = part.get("type") if part is not None else None
                    capture.observe(value, count_raw=False)
                    if part is not None:
                        text_length = _safe_text_length(part.get("text"))
                        if text_length is not None and visible_chars is not None:
                            visible_chars += text_length
                if type(raw_content) is str:
                    if raw_content:
                        capture.observe_repeated("text", 1)
                    visible_chars = len(raw_content)
                elif raw_content is not None and not content_parts:
                    capture.tail_unknown = True
                    visible_chars = None
                capture.observe_repeated("tool_call", len(raw_tools))
                reasoning_count = sum(
                    message.get(key) is not None
                    for key in ("reasoning", "reasoning_content", "thinking")
                )
                capture.observe_repeated("reasoning", reasoning_count)
                finish_reason = choice.get("finish_reason")
                usage = _exact_dict(body.get("usage")) or {}
                output_tokens = _safe_nonnegative_int(usage.get("completion_tokens"))
                reasoning_usage_status, reasoning_usage = _formal_reasoning_usage(
                    usage, details_key="completion_tokens_details",
                )
                transport_complete = finish_reason is not None
            elif safe_protocol == "openai-responses":
                output = body.get("output")
                output = _exact_sequence(output)
                if output is None:
                    capture_completeness = "unavailable"
                    visible_chars = None
                    output = ()
                capture.raw_count = len(output)
                for output_index in range(len(output)):
                    if capture.exhausted or not capture.touch():
                        break
                    item = _exact_dict(output[output_index])
                    capture.observe(
                        item.get("type") if item is not None else None,
                        count_raw=False,
                    )
                    if item is None:
                        capture.tail_unknown = True
                        continue
                    raw_nested = item.get("content")
                    if raw_nested is None:
                        continue
                    nested = _exact_sequence(raw_nested)
                    if nested is None:
                        capture.tail_unknown = True
                        continue
                    capture.raw_count += len(nested)
                    for part_index in range(len(nested)):
                        if capture.exhausted or not capture.touch():
                            break
                        part = _exact_dict(nested[part_index])
                        value = part.get("type") if part is not None else None
                        capture.observe(value, count_raw=False)
                        if (
                            part is not None
                            and _bounded_normalized_token(value)
                            in TEXT_BLOCK_TYPES
                        ):
                            text_length = _safe_text_length(part.get("text"))
                            if text_length is not None and visible_chars is not None:
                                visible_chars += text_length
                    if capture.exhausted:
                        break
                finish_reason = body.get("status")
                incomplete = body.get("incomplete_details")
                incomplete = _exact_dict(incomplete) or {}
                incomplete_reason = incomplete.get("reason")
                if (
                    _bounded_normalized_token(finish_reason) == "incomplete"
                    and incomplete_reason is not None
                ):
                    finish_reason = incomplete_reason
                usage = _exact_dict(body.get("usage")) or {}
                output_tokens = _safe_nonnegative_int(usage.get("output_tokens"))
                reasoning_usage_status, reasoning_usage = _formal_reasoning_usage(
                    usage, details_key="output_tokens_details",
                )
                transport_complete = _bounded_normalized_token(
                    body.get("status"),
                ) in {
                    "completed", "incomplete", "failed", "cancelled",
                }
            else:
                capture_completeness = "unavailable"
                visible_chars = None
        else:
            observation_point = "stream_event_shape_pre_aggregation"
            response_class = "stream_event_sequence"
            capture_completeness = "partial"
            safe_events = _exact_sequence(events)
            if safe_events is None:
                safe_events = ()
                capture_completeness = "unavailable"
                visible_chars = None
            chat_tool_keys: list[tuple[int, int]] = []
            responses_block_keys: list[tuple[str, int, int]] = []
            for event_index in range(len(safe_events)):
                if capture.exhausted or not capture.touch():
                    break
                event = _exact_dict(safe_events[event_index])
                if event is None:
                    capture.tail_unknown = True
                    continue
                kind = _bounded_normalized_token(event.get("type")) or ""
                if safe_protocol == "anthropic":
                    if kind == "content_block_start":
                        block = event.get("content_block")
                        block = _exact_dict(block) or {}
                        capture.observe(block.get("type"))
                        if _bounded_normalized_token(block.get("type")) == "text":
                            text_length = _safe_text_length(block.get("text"))
                            if text_length is not None and visible_chars is not None:
                                visible_chars += text_length
                    elif kind == "content_block_delta":
                        delta = event.get("delta")
                        delta = _exact_dict(delta) or {}
                        if delta.get("type") == "text_delta":
                            text_length = _safe_text_length(delta.get("text"))
                            if text_length is not None and visible_chars is not None:
                                visible_chars += text_length
                    elif kind == "message_delta":
                        delta = event.get("delta")
                        delta = _exact_dict(delta) or {}
                        stop_reason = delta.get("stop_reason")
                        if stop_reason is not None:
                            finish_reason = stop_reason
                        usage = _exact_dict(event.get("usage")) or {}
                        output_tokens = _safe_nonnegative_int(
                            usage.get("output_tokens"),
                        ) or output_tokens
                elif safe_protocol == "openai-chat":
                    choices = _exact_sequence(event.get("choices")) or ()
                    for choice_ordinal in range(len(choices)):
                        if capture.exhausted or not capture.touch():
                            break
                        choice = _exact_dict(choices[choice_ordinal])
                        if choice is None:
                            continue
                        choice_finish = choice.get("finish_reason")
                        if choice_finish is not None:
                            finish_reason = choice_finish
                        delta = _exact_dict(choice.get("delta")) or {}
                        text_length = _safe_text_length(delta.get("content"))
                        if text_length:
                            if "text" not in capture.controlled:
                                capture.observe("text")
                            if visible_chars is not None:
                                visible_chars += text_length
                        if any(delta.get(key) is not None for key in ("reasoning", "reasoning_content", "thinking")):
                            if "reasoning" not in capture.controlled:
                                capture.observe("reasoning")
                        calls = _exact_sequence(delta.get("tool_calls")) or ()
                        for call_ordinal in range(len(calls)):
                            if capture.exhausted or not capture.touch():
                                break
                            call = _exact_dict(calls[call_ordinal])
                            if call is None:
                                continue
                            call_index = call.get("index")
                            key = (
                                choice_ordinal,
                                call_index
                                if type(call_index) is int and call_index >= 0
                                else call_ordinal,
                            )
                            if key not in chat_tool_keys:
                                chat_tool_keys.append(key)
                                capture.observe("tool_call")
                        if capture.exhausted:
                            break
                    usage = _exact_dict(event.get("usage")) or {}
                    output_tokens = _safe_nonnegative_int(
                        usage.get("completion_tokens"),
                    ) or output_tokens
                    status, value = _formal_reasoning_usage(
                        usage, details_key="completion_tokens_details",
                    )
                    if status != "NOT_EXPOSED":
                        reasoning_usage_status = status
                        reasoning_usage = value
                    if capture.exhausted:
                        break
                elif safe_protocol == "openai-responses":
                    if kind in {"response.output_item.added", "response.content_part.added"}:
                        item = event.get("item")
                        if item is None:
                            item = event.get("part")
                        item = _exact_dict(item)
                        if item is not None:
                            output_index = event.get("output_index")
                            content_index = event.get("content_index")
                            key = (
                                kind,
                                output_index if type(output_index) is int else 0,
                                content_index if type(content_index) is int else 0,
                            )
                            if key not in responses_block_keys:
                                responses_block_keys.append(key)
                                capture.observe(item.get("type"))
                    text_length = _safe_text_length(event.get("delta"))
                    if kind == "response.output_text.delta" and text_length is not None:
                        if "output_text" not in capture.controlled:
                            capture.observe("output_text")
                        if visible_chars is not None:
                            visible_chars += text_length
                    if kind in {"response.completed", "response.incomplete", "response.failed"}:
                        response = _exact_dict(event.get("response")) or {}
                        response_status = response.get("status")
                        if response_status is not None:
                            finish_reason = response_status
                        usage = _exact_dict(response.get("usage")) or {}
                        output_tokens = _safe_nonnegative_int(
                            usage.get("output_tokens"),
                        ) or output_tokens
                        status, value = _formal_reasoning_usage(
                            usage, details_key="output_tokens_details",
                        )
                        if status != "NOT_EXPOSED":
                            reasoning_usage_status = status
                            reasoning_usage = value
            if len(safe_events) > capture.touched:
                capture.tail_unknown = True
            transport_complete = finish_reason is not None
        sequence_omitted = capture.limit_reached or (
            capture.raw_count > len(capture.controlled)
        )
        if capture.tail_unknown and capture_completeness != "unavailable":
            capture_completeness = "partial"
        finish_class, finish_hash = _controlled_raw_finish(finish_reason)
        multiset = dict(sorted(Counter(capture.controlled).items()))
        reasoning_count = sum(
            item in REASONING_BLOCK_TYPES for item in capture.controlled
        )
        text_count = sum(item in TEXT_BLOCK_TYPES for item in capture.controlled)
        tool_count = sum(item in TOOL_BLOCK_TYPES for item in capture.controlled)
        unknown_count = sum(item == "unknown" for item in capture.controlled)
        tail_unknown = capture.tail_unknown or capture_completeness == "unavailable"
        visible_count = (
            None if tail_unknown and not visible_chars else visible_chars
        )
        snapshot = {
            "observation_point": observation_point,
            "provider_protocol": safe_protocol,
            "raw_response_class": response_class,
            "unknown_response_class_sha256": None,
            "raw_block_count": capture.raw_count,
            "raw_block_type_sequence": tuple(capture.controlled),
            "raw_block_type_sequence_sha256": _sha256(
                "r1-ptr12-block-sequence-v1", capture.controlled,
            ),
            "raw_block_type_multiset": multiset,
            "sequence_omitted_after_limit": sequence_omitted,
            "reasoning_block_count": reasoning_count,
            "text_or_final_block_count": text_count,
            "tool_block_count": tool_count,
            "unknown_block_count": unknown_count,
            "unknown_block_type_hashes": tuple(capture.unknown_hashes),
            "raw_visible_char_count": visible_count,
            "raw_visible_chars_zero": (
                False if visible_chars else None if tail_unknown else True
            ),
            "raw_final_text_present": (
                True if text_count else None if tail_unknown else False
            ),
            "raw_tool_call_present": (
                True if tool_count else None if tail_unknown else False
            ),
            "finish_reason_raw_class": finish_class,
            "finish_reason_unknown_sha256": finish_hash,
            "output_token_count": output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else None,
            "requested_output_cap": safe_requested_output_cap,
            "effective_output_cap": safe_effective_output_cap,
            "provider_accepted_cap_status": "UNKNOWN",
            "provider_exposed_reasoning_usage_status": reasoning_usage_status,
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
        streamed_text = state.get("streamed_text")
        streamed_text = streamed_text if isinstance(streamed_text, str) else ""
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
        if streamed_text and not any(
            isinstance(value, str) and value for value in text_values
        ):
            block_types.append("output_text")
            text_values.append(streamed_text)
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
