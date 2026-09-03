import json

import httpx
import pytest
import respx

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.full_short_execution import _expected_provider_payload_v1
from novel_flywheel.provider_output import provider_output_shape_from_response
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.http import ProviderResponseError
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter


REQUEST = ModelRequest(model="writer", messages=[Message(role="user", content="写作")])


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_adapter_normalizes_response() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "id": "req-1",
        "choices": [{"message": {"content": "正文"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }))
    result = await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert route.called
    assert (result.text, result.total_tokens) == ("正文", 33)


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_adapter_can_require_a_specific_tool() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "req-tool",
            "choices": [{"message": {"content": "", "tool_calls": []}}],
            "usage": {},
        }),
    )
    request = ModelRequest(
        model="writer",
        messages=[Message(role="user", content="Call probe_tool")],
        tools=[ToolDefinition(
            name="probe_tool", description="Probe", input_schema={"type": "object"},
        )],
        required_tool="probe_tool",
    )

    await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["tool_choice"] == {
        "type": "function", "function": {"name": "probe_tool"},
    }


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_adapter_sends_json_object_only_when_requested() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "req-json-object",
            "choices": [{
                "message": {"content": '{"ok":true}'},
                "finish_reason": "stop",
            }],
            "usage": {},
        }),
    )

    await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(
        REQUEST.model_copy(update={"response_format": "json_object"}),
    )

    payload = json.loads(route.calls.last.request.content)
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@respx.mock
async def test_moonshot_disables_thinking_for_forced_tools() -> None:
    route = respx.post("https://api.moonshot.cn/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "req-tool",
            "choices": [{"message": {"content": "", "tool_calls": []}}],
            "usage": {},
        }),
    )
    request = ModelRequest(
        model="kimi-k3",
        messages=[Message(role="user", content="Call probe_tool")],
        tools=[ToolDefinition(
            name="probe_tool", description="Probe", input_schema={"type": "object"},
        )],
        required_tool="probe_tool",
    )

    await OpenAIChatAdapter("https://api.moonshot.cn/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
@respx.mock
async def test_moonshot_disables_thinking_for_structured_output() -> None:
    route = respx.post("https://api.moonshot.cn/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "req-json",
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {},
        }),
    )
    request = ModelRequest(
        model="kimi-k3",
        messages=[Message(role="user", content="Return JSON")],
        response_schema={"name": "probe", "schema": {"type": "object"}},
    )

    await OpenAIChatAdapter("https://api.moonshot.cn/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("base_url", [
    "https://api.moonshot.cn/v1",
    "https://API.MOONSHOT.CN/v1",
    "https://relay.test/api.moonshot.cn/v1",
])
async def test_openai_chat_payload_matches_full_short_hostname_projection(
    base_url: str,
) -> None:
    route = respx.post(f"{base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "req-json-parity",
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {},
        }),
    )
    request = ModelRequest(
        model="kimi-k3",
        messages=[Message(role="user", content="Return JSON")],
        response_schema={"name": "probe", "schema": {"type": "object"}},
    )

    await OpenAIChatAdapter(base_url, "secret").complete(request)

    actual = json.loads(route.calls.last.request.content)
    expected = _expected_provider_payload_v1(
        "openai-chat", request, destination=base_url,
    )
    assert actual == expected


@pytest.mark.asyncio
@respx.mock
async def test_openai_responses_adapter_normalizes_response() -> None:
    respx.post("https://relay.test/v1/responses").mock(return_value=httpx.Response(200, json={
        "id": "resp-1", "output_text": "审核通过", "status": "completed",
        "usage": {"input_tokens": 7, "output_tokens": 9},
    }))
    result = await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert (result.text, result.total_tokens) == ("审核通过", 16)


@pytest.mark.asyncio
@respx.mock
async def test_openai_responses_adapter_can_require_a_specific_tool() -> None:
    route = respx.post("https://relay.test/v1/responses").mock(
        return_value=httpx.Response(200, json={
            "id": "resp-tool",
            "output": [{
                "type": "function_call",
                "call_id": "call-1",
                "name": "probe_tool",
                "arguments": "{}",
            }],
            "status": "completed",
            "usage": {},
        }),
    )
    request = ModelRequest(
        model="writer",
        messages=[Message(role="user", content="Call probe_tool")],
        tools=[ToolDefinition(
            name="probe_tool", description="Probe", input_schema={"type": "object"},
        )],
        required_tool="probe_tool",
    )

    result = await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["tool_choice"] == {"type": "function", "name": "probe_tool"}
    assert result.tool_calls[0].name == "probe_tool"


@pytest.mark.asyncio
@respx.mock
async def test_openai_responses_adapter_sends_json_object_format() -> None:
    route = respx.post("https://relay.test/v1/responses").mock(
        return_value=httpx.Response(200, json={
            "id": "resp-json-object",
            "output_text": '{"ok":true}',
            "status": "completed",
            "usage": {},
        }),
    )

    await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(
        REQUEST.model_copy(update={"response_format": "json_object"}),
    )

    payload = json.loads(route.calls.last.request.content)
    assert payload["text"] == {"format": {"type": "json_object"}}


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_normalizes_response() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(200, json={
        "id": "msg-1", "content": [{"type": "text", "text": "润色稿"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 24},
    }))
    result = await AnthropicAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert route.calls.last.request.headers["x-api-key"] == "secret"
    assert (result.text, result.total_tokens) == ("润色稿", 36)


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_root_base_url_adds_v1_and_uses_bearer_auth() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(200, json={
        "id": "msg-2", "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn", "usage": {},
    }))

    result = await AnthropicAdapter(
        "https://relay.test", "secret", auth_type="bearer",
    ).complete(REQUEST)

    assert route.calls.last.request.headers["authorization"] == "Bearer secret"
    assert "x-api-key" not in route.calls.last.request.headers
    assert result.text == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_sends_native_json_schema_when_configured() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(
        return_value=httpx.Response(200, json={
            "id": "msg-schema",
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "stop_reason": "end_turn",
            "usage": {},
        }),
    )
    request = REQUEST.model_copy(update={
        "response_schema": {
            "name": "probe",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        },
    })

    await AnthropicAdapter("https://relay.test/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": request.response_schema["schema"],
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_can_require_a_specific_tool() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(200, json={
        "id": "msg-tool",
        "content": [{"type": "tool_use", "id": "call-1", "name": "probe_tool", "input": {}}],
        "stop_reason": "tool_use",
        "usage": {},
    }))
    request = ModelRequest(
        model="writer",
        messages=[Message(role="user", content="Call probe_tool")],
        tools=[ToolDefinition(
            name="probe_tool", description="Probe", input_schema={"type": "object"},
        )],
        required_tool="probe_tool",
    )

    result = await AnthropicAdapter("https://relay.test/v1", "secret").complete(request)

    payload = json.loads(route.calls.last.request.content)
    assert payload["tool_choice"] == {"type": "tool", "name": "probe_tool"}
    assert result.tool_calls[0].name == "probe_tool"


@pytest.mark.asyncio
@respx.mock
async def test_provider_reports_non_json_endpoint_response() -> None:
    private_body = "<!doctype html><title>Relay website private marker</title>"
    respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(
        200, text=private_body,
        headers={"content-type": "text/html; charset=utf-8"},
    ))

    with pytest.raises(ProviderResponseError, match="text/html") as caught:
        await AnthropicAdapter("https://relay.test", "secret").complete(REQUEST)
    assert private_body not in str(caught.value)


@pytest.mark.asyncio
@respx.mock
async def test_provider_bounds_non_json_content_type_provenance() -> None:
    oversized_content_type = "text/html; relay=" + ("x" * 512)
    private_body = "private upstream response body"
    respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(
        200, text=private_body,
        headers={"content-type": oversized_content_type},
    ))

    with pytest.raises(ProviderResponseError) as caught:
        await AnthropicAdapter("https://relay.test", "secret").complete(REQUEST)

    message = str(caught.value)
    assert "content-type=text/html; relay=" in message
    assert private_body not in message
    assert oversized_content_type not in message
    assert len(message) < 256


@pytest.mark.asyncio
@respx.mock
async def test_provider_retries_one_transient_disconnect() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(side_effect=[
        httpx.RemoteProtocolError("server disconnected"),
        httpx.Response(200, json={
            "id": "msg-retry", "content": [{"type": "text", "text": "recovered"}],
            "stop_reason": "end_turn", "usage": {},
        }),
    ])

    result = await AnthropicAdapter("https://relay.test", "secret").complete(REQUEST)

    assert result.text == "recovered"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_provider_does_not_retry_read_timeout() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(
        side_effect=httpx.ReadTimeout("upstream response timed out"),
    )

    with pytest.raises(httpx.ReadTimeout, match="upstream response timed out"):
        await AnthropicAdapter("https://relay.test", "secret").complete(REQUEST)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_adapter_aggregates_stream() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"id":"req-stream","choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
            'data: {"id":"req-stream","choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
            'data: [DONE]\n\n'
        )),
    )

    result = await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert json.loads(route.calls.last.request.content)["stream"] is True
    assert (result.text, result.finish_reason, result.total_tokens) == ("Hello", "stop", 5)


@pytest.mark.parametrize("reasoning_key", [
    "reasoning", "reasoning_content", "thinking",
])
def test_openai_chat_exact_replay_preserves_reasoning_only_stream(
    reasoning_key: str,
) -> None:
    payload = (
        'data: {"id":"chat-reason","choices":[{"delta":{"'
        f'{reasoning_key}":"pri"}},"finish_reason":null}}]}}\n\n'
        'data: {"id":"chat-reason","choices":[{"delta":{"'
        f'{reasoning_key}":"vate"}},"finish_reason":null}}]}}\n\n'
        'data: {"id":"chat-reason","choices":[{"delta":{},'
        '"finish_reason":"stop"}],"usage":{"prompt_tokens":1,'
        '"completion_tokens":3}}\n\n'
        'data: [DONE]\n\n'
    ).encode("utf-8")

    result = OpenAIChatAdapter.replay_protocol_input_bytes_v1(
        payload, content_type="text/event-stream",
    )

    assert result.text == ""
    assert result.finish_reason == "stop"
    assert result.provider_state["assistant"][reasoning_key] == "private"
    assert result.output_shape is not None
    assert result.output_shape.reasoning_block_count == 1
    assert result.output_shape.content_block_count == 1
    assert result.output_shape.text_block_count == 0
    assert result.output_shape.provider_visible_text_chars == 0
    assert result.output_shape.adapter_projection_status == "exact"
    assert result.output_shape.transport_complete is True


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_aggregates_streamed_tool_call() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"type":"message_start","message":{"id":"msg-stream","usage":{"input_tokens":4}}}\n\n'
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"call-1","name":"probe_tool","input":{}}}\n\n'
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"ok\\":"}}\n\n'
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"true}"}}\n\n'
            'data: {"type":"content_block_stop","index":0}\n\n'
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":6}}\n\n'
            'data: {"type":"message_stop"}\n\n'
        )),
    )

    result = await AnthropicAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert json.loads(route.calls.last.request.content)["stream"] is True
    assert result.tool_calls[0].arguments == {"ok": True}
    assert (result.finish_reason, result.total_tokens) == ("tool_use", 10)


@pytest.mark.asyncio
@respx.mock
async def test_openai_responses_adapter_aggregates_stream() -> None:
    route = respx.post("https://relay.test/v1/responses").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"type":"response.created","response":{"id":"resp-stream"}}\n\n'
            'data: {"type":"response.output_text.delta","delta":"Review "}\n\n'
            'data: {"type":"response.output_text.delta","delta":"passed"}\n\n'
            'data: {"type":"response.completed","response":{"id":"resp-stream","status":"completed","usage":{"input_tokens":7,"output_tokens":2},"output":[]}}\n\n'
        )),
    )

    result = await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert json.loads(route.calls.last.request.content)["stream"] is True
    assert (result.text, result.finish_reason, result.total_tokens) == ("Review passed", "completed", 9)
    shape = provider_output_shape_from_response(OpenAIResponsesAdapter, result)
    assert shape is not None
    assert shape.text_block_count == 1
    assert shape.provider_visible_text_chars == len("Review passed")
    assert shape.normalized_visible_text_chars == len("Review passed")
    assert shape.adapter_projection_status == "exact"


def test_openai_responses_exact_replay_does_not_double_count_terminal_text() -> None:
    payload = (
        'data: {"type":"response.output_text.delta","delta":"Review "}\n\n'
        'data: {"type":"response.output_text.delta","delta":"passed"}\n\n'
        'data: {"type":"response.completed","response":{"id":"resp-stream",'
        '"status":"completed","output":[{"type":"message","content":['
        '{"type":"output_text","text":"Review passed"}]}]}}\n\n'
    ).encode("utf-8")

    result = OpenAIResponsesAdapter.replay_protocol_input_bytes_v1(
        payload, content_type="text/event-stream",
    )

    assert result.text == "Review passed"
    assert result.output_shape is not None
    assert result.output_shape.text_block_count == 1
    assert result.output_shape.provider_visible_text_chars == len("Review passed")
    assert result.output_shape.normalized_visible_text_chars == len("Review passed")
    assert result.output_shape.adapter_projection_status == "exact"


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_stream_aggregates_fragmented_tool_arguments() -> None:
    respx.post("https://relay.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"id":"req-tool","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"probe_tool","arguments":"{\\"ok\\":"}}]},"finish_reason":null}]}\n\n'
            'data: {"id":"req-tool","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"true}"}}]},"finish_reason":"tool_calls"}]}\n\n'
            'data: [DONE]\n\n'
        )),
    )

    result = await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert result.tool_calls[0].name == "probe_tool"
    assert result.tool_calls[0].arguments == {"ok": True}


@pytest.mark.asyncio
@respx.mock
async def test_stream_retries_without_stream_options_when_relay_rejects_it() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(side_effect=[
        httpx.Response(400, json={"error": {"message": "invalid stream_options parameter"}}),
        httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"id":"req-stream","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )),
    ])

    result = await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert result.text == "ok"
    assert route.call_count == 2
    assert "stream_options" not in json.loads(route.calls.last.request.content)


@pytest.mark.asyncio
@respx.mock
async def test_stream_falls_back_to_non_streaming_when_relay_rejects_stream() -> None:
    route = respx.post("https://relay.test/v1/responses").mock(side_effect=[
        httpx.Response(400, json={"error": {"message": "stream is not supported"}}),
        httpx.Response(200, json={
            "id": "resp-fallback", "output_text": "fallback", "status": "completed", "usage": {},
        }),
    ])

    result = await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(REQUEST)

    assert result.text == "fallback"
    assert route.call_count == 2
    assert json.loads(route.calls.last.request.content)["stream"] is False
