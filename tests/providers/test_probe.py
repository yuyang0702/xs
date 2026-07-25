import pytest

from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.providers.probe import CapabilityProbe


class ProbeAdapter:
    def __init__(self, tool_calling=True):
        self.calls = 0
        self.requests = []
        self.tool_calling = tool_calling

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(text="连接正常")
        if self.calls == 2:
            assert request.response_schema is not None
            return ModelResponse(text='{"ok":true}')
        if self.tool_calling:
            return ModelResponse(tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})])
        return ModelResponse(text="tools unavailable")


class FailingProbeAdapter:
    async def complete(self, request):
        raise RuntimeError("endpoint returned text/html")


class EmptyChatProbeAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(text="")
        if self.calls == 2:
            return ModelResponse(text='```json\n{"ok": true}\n```')
        return ModelResponse(tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})])


class ThinkingProbeAdapter(ProbeAdapter):
    error = "Thinking mode does not support this tool_choice"

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(text="ok")
        if self.calls == 2:
            return ModelResponse(text='{"ok":true}')
        if request.required_tool:
            raise ToolCapabilityError(self.error)
        return ModelResponse(tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})])


class KimiThinkingProbeAdapter(ThinkingProbeAdapter):
    error = "tool_choice 'specified' is incompatible with thinking enabled"


@pytest.mark.asyncio
async def test_probe_reports_chat_json_and_tool_calling_separately() -> None:
    adapter = ProbeAdapter()
    result = await CapabilityProbe(adapter).run("model")
    assert result.model_dump() == {
        "chat": True, "structured_output": True, "tool_calling": True, "error": None,
    }
    assert adapter.requests[2].required_tool == "probe_tool"


@pytest.mark.asyncio
async def test_probe_can_report_partial_support() -> None:
    result = await CapabilityProbe(ProbeAdapter(tool_calling=False)).run("model")
    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is False
    assert result.error == "tools: provider returned no probe_tool call"


@pytest.mark.asyncio
async def test_probe_retries_without_forced_tool_choice_for_thinking_models() -> None:
    adapter = ThinkingProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert adapter.requests[-1].tools
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_probe_retries_kimi_without_forced_tool_choice() -> None:
    adapter = KimiThinkingProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert adapter.requests[-1].tools
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_probe_includes_actionable_error_message() -> None:
    result = await CapabilityProbe(FailingProbeAdapter()).run("model")

    assert result.error == "RuntimeError: endpoint returned text/html"


@pytest.mark.asyncio
async def test_probe_treats_successful_empty_chat_as_connected_and_accepts_fenced_json() -> None:
    result = await CapabilityProbe(EmptyChatProbeAdapter()).run("model")

    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is True
