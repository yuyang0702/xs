import pytest

from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.providers.probe import CapabilityProbe


class ProbeAdapter:
    def __init__(self, tool_calling=True):
        self.calls = 0
        self.tool_calling = tool_calling

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(text="连接正常")
        if self.calls == 2:
            return ModelResponse(text='{"ok":true}')
        if self.tool_calling:
            return ModelResponse(tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})])
        return ModelResponse(text="tools unavailable")


@pytest.mark.asyncio
async def test_probe_reports_chat_json_and_tool_calling_separately() -> None:
    result = await CapabilityProbe(ProbeAdapter()).run("model")
    assert result.model_dump() == {
        "chat": True, "structured_output": True, "tool_calling": True, "error": None,
    }


@pytest.mark.asyncio
async def test_probe_can_report_partial_support() -> None:
    result = await CapabilityProbe(ProbeAdapter(tool_calling=False)).run("model")
    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is False
