from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

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


def _sha256(domain: str, value: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
