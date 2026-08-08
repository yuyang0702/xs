import json

import httpx
import pytest
import respx

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
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
    respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(
        200, text="<!doctype html><title>Relay website</title>",
        headers={"content-type": "text/html; charset=utf-8"},
    ))

    with pytest.raises(ProviderResponseError, match="text/html"):
        await AnthropicAdapter("https://relay.test", "secret").complete(REQUEST)


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


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_aggregates_streamed_tool_call() -> None:
    route = respx.post("https://relay.test/v1/messages").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
            'data: {"type":"message_start","message":{"id":"msg-stream","usage":{"input_tokens":4}}}\n\n'
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"call-1","name":"probe_tool","input":{}}}\n\n'
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"ok\\":"}}\n\n'
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"true}"}}\n\n'
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
