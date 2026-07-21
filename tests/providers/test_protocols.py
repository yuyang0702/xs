import httpx
import pytest
import respx

from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.anthropic import AnthropicAdapter
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

