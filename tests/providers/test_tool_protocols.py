import httpx
import pytest
import respx

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter


TOOL = ToolDefinition(name="search_chapters", description="Search", input_schema={
    "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
})
REQUEST = ModelRequest(model="writer", messages=[Message(role="user", content="find")], tools=[TOOL])


@pytest.mark.asyncio
@respx.mock
async def test_openai_chat_normalizes_tool_call() -> None:
    route = respx.post("https://relay.test/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "id": "req", "choices": [{"message": {"content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "search_chapters", "arguments": "{\"query\":\"key\"}"}}]}, "finish_reason": "tool_calls"}],
    }))
    response = await OpenAIChatAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert route.calls.last.request.content.find(b'"tools"') > 0
    assert response.tool_calls[0].arguments == {"query": "key"}


@pytest.mark.asyncio
@respx.mock
async def test_openai_responses_normalizes_tool_call() -> None:
    respx.post("https://relay.test/v1/responses").mock(return_value=httpx.Response(200, json={
        "id": "resp", "status": "completed", "output": [{"type": "function_call", "call_id": "call-1", "name": "search_chapters", "arguments": "{\"query\":\"key\"}"}],
    }))
    response = await OpenAIResponsesAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert response.tool_calls[0].name == "search_chapters"


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_normalizes_tool_call() -> None:
    respx.post("https://relay.test/v1/messages").mock(return_value=httpx.Response(200, json={
        "id": "msg", "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "call-1", "name": "search_chapters", "input": {"query": "key"}}],
    }))
    response = await AnthropicAdapter("https://relay.test/v1", "secret").complete(REQUEST)
    assert response.tool_calls[0].arguments == {"query": "key"}
