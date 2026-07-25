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
