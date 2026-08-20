from __future__ import annotations

import json

import pytest

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1,
    bind_diagnostic_context,
    exception_snapshot,
    reset_bound_diagnostic_context,
)
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter
from novel_flywheel.provider_output import provider_output_shape_from_response


TOOL = ToolDefinition(
    name="planning_adaptation_whole",
    description="controlled diagnostic contract",
    input_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
)
REQUEST = ModelRequest(
    model="controlled-model",
    messages=[Message(role="user", content="controlled-input")],
    tools=[TOOL],
    required_tool=TOOL.name,
    max_output_tokens=1276,
)


def snapshot(response):
    return response.provider_state["_r1_pa1_tool_shape_snapshot"]


def target_context(tmp_path):
    return ModelDiagnosticContextV1(
        project_root=tmp_path,
        run_id="controlled-run",
        stage="review",
        boundary="planning_adaptation_whole_receipt",
        role="review",
        route_kind="configured_fallback",
        contract_id="planning_adaptation_whole",
        contract_version=1,
        outer_retry_ordinal=1,
    )


async def complete_with_target_context(adapter, tmp_path):
    token = bind_diagnostic_context(target_context(tmp_path))
    try:
        return await adapter.complete(REQUEST)
    finally:
        reset_bound_diagnostic_context(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_kind", ["openai_chat", "openai_responses", "anthropic"])
async def test_production_adapters_capture_exact_raw_shape_without_values(
    adapter_kind, monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    if adapter_kind == "openai_chat":
        adapter = OpenAIChatAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "private-call-id",
                        "type": "function",
                        "function": {
                            "name": TOOL.name,
                            "arguments": json.dumps({"private_argument": "private-value"}),
                        },
                    }],
                },
                "finish_reason": "stop",
            }],
            "usage": {},
        }
    elif adapter_kind == "openai_responses":
        adapter = OpenAIResponsesAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "status": "completed",
            "output": [{
                "type": "function_call",
                "call_id": "private-call-id",
                "name": TOOL.name,
                "arguments": json.dumps({"private_argument": "private-value"}),
            }],
            "usage": {},
        }
    else:
        adapter = AnthropicAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "stop_reason": "tool_use",
            "content": [{
                "type": "tool_use",
                "id": "private-call-id",
                "name": TOOL.name,
                "input": {"private_argument": "private-value"},
            }],
            "usage": {},
        }

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    response = await complete_with_target_context(adapter, tmp_path)
    value = snapshot(response)
    output_shape = provider_output_shape_from_response(adapter, response)
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)

    assert value["snapshot_status"] == "snapshot_exact"
    assert value["raw_tool_call_count"] == 1
    assert value["tool_calls"][0]["argument_sha256"]
    assert value["tool_calls"][0]["tool_call_id_sha256"]
    assert "private-request-id" not in serialized
    assert "private-call-id" not in serialized
    assert "private_argument" not in serialized
    assert "private-value" not in serialized
    assert TOOL.name not in serialized
    assert output_shape.tool_call_count == 1
    assert output_shape.text_block_count == 0
    assert output_shape.adapter_projection_status == "exact"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_kind", ["openai_chat", "openai_responses"])
async def test_json_argument_parse_exception_keeps_type_message_and_snapshot(
    adapter_kind, monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    malformed = "{malformed"
    if adapter_kind == "openai_chat":
        adapter = OpenAIChatAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "request",
            "choices": [{
                "message": {"content": None, "tool_calls": [{
                    "id": "call", "function": {
                        "name": TOOL.name, "arguments": malformed,
                    },
                }]},
                "finish_reason": "stop",
            }],
        }
    else:
        adapter = OpenAIResponsesAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "request", "status": "completed",
            "output": [{
                "type": "function_call", "call_id": "call",
                "name": TOOL.name, "arguments": malformed,
            }],
        }

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    expected_message = None
    try:
        json.loads(malformed)
    except json.JSONDecodeError as reference:
        expected_message = str(reference)

    with pytest.raises(json.JSONDecodeError) as caught:
        await complete_with_target_context(adapter, tmp_path)

    assert str(caught.value) == expected_message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    attached = exception_snapshot(caught.value)
    assert attached is not None
    assert attached.snapshot_status == "adapter_exception_with_snapshot"
    assert attached.tool_calls[0].argument_json_parse_status == "malformed"


@pytest.mark.asyncio
async def test_anthropic_native_array_is_observed_before_original_validation_error(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    adapter = AnthropicAdapter("https://relay.invalid/v1", "secret")
    body = {
        "id": "request", "stop_reason": "tool_use",
        "content": [{
            "type": "tool_use", "id": "call", "name": TOOL.name,
            "input": ["not-an-object"],
        }],
        "usage": {},
    }

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    with pytest.raises(Exception) as caught:
        await complete_with_target_context(adapter, tmp_path)

    attached = exception_snapshot(caught.value)
    assert attached is not None
    assert attached.snapshot_status == "adapter_exception_with_snapshot"
    assert attached.tool_calls[0].argument_shape == "array"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_kind", ["openai_chat", "openai_responses", "anthropic"])
async def test_production_adapters_emit_reasoning_only_output_shape(
    adapter_kind, monkeypatch,
) -> None:
    if adapter_kind == "openai_chat":
        adapter = OpenAIChatAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "choices": [{
                "message": {"content": None, "reasoning_content": "private"},
                "finish_reason": "max_tokens",
            }],
            "usage": {"completion_tokens": 16000},
        }
    elif adapter_kind == "openai_responses":
        adapter = OpenAIResponsesAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning", "summary": [{"text": "private"}]}],
            "usage": {"output_tokens": 16000},
        }
    else:
        adapter = AnthropicAdapter("https://relay.invalid/v1", "secret")
        body = {
            "id": "private-request-id",
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "private"}],
            "usage": {"output_tokens": 16000},
        }

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    response = await adapter.complete(REQUEST)
    shape = provider_output_shape_from_response(adapter, response)
    serialized = shape.model_dump_json()

    assert response.text == ""
    assert response.tool_calls == []
    assert shape.finish_reason == "max_tokens"
    assert shape.reasoning_block_count == 1
    assert shape.text_block_count == 0
    assert shape.tool_call_count == 0
    assert shape.provider_visible_text_chars == 0
    assert shape.normalized_visible_text_chars == 0
    assert shape.unknown_block_count == 0
    assert shape.adapter_projection_status == "exact"
    assert "private-request-id" not in serialized
    assert "private" not in serialized
