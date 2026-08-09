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


class UnsupportedForcedToolProbeAdapter(ThinkingProbeAdapter):
    error = "tool_choice is not supported by this provider"


class IgnoredForcedToolProbeAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(text="ok")
        if self.calls == 2:
            return ModelResponse(text='{"ok":true}')
        if request.required_tool:
            return ModelResponse(text="I cannot call tools")
        return ModelResponse(tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})])


class OptionalToolOnlyProbeAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(text="ok")
        if self.calls == 2:
            return ModelResponse(text='{"ok":true,"unexpected":"schema ignored"}')
        if request.required_tool:
            raise ToolCapabilityError(
                "Thinking mode does not support this tool_choice"
            )
        return ModelResponse(
            tool_calls=[ToolCall(id="probe", name="probe_tool", arguments={})],
        )


@pytest.mark.asyncio
async def test_probe_reports_chat_json_and_tool_calling_separately() -> None:
    adapter = ProbeAdapter()
    result = await CapabilityProbe(adapter).run("model")
    assert result.model_dump() == {
        "chat": True,
        "structured_output": True,
        "tool_calling": True,
        "forced_tool": True,
        "structured_output_capability": "strict_json_schema",
        "json_object": True,
        "error": None,
        "diagnostic_code": None,
    }
    assert adapter.requests[2].required_tool == "probe_tool"


@pytest.mark.asyncio
async def test_probe_can_report_partial_support() -> None:
    result = await CapabilityProbe(ProbeAdapter(tool_calling=False)).run("model")
    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is False
    assert result.error == "工具检测：供应商没有返回测试工具调用"


@pytest.mark.asyncio
async def test_probe_retries_without_forced_tool_choice_for_thinking_models() -> None:
    adapter = ThinkingProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert result.forced_tool is False
    assert adapter.requests[-1].tools
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_probe_retries_kimi_without_forced_tool_choice() -> None:
    adapter = KimiThinkingProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert result.forced_tool is False
    assert adapter.requests[-1].tools
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_probe_retries_when_provider_rejects_forced_tool_choice() -> None:
    adapter = UnsupportedForcedToolProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert result.forced_tool is False
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_probe_retries_when_provider_ignores_forced_tool_choice() -> None:
    adapter = IgnoredForcedToolProbeAdapter()

    result = await CapabilityProbe(adapter).run("model")

    assert result.tool_calling is True
    assert result.forced_tool is False
    assert adapter.requests[-1].required_tool is None


@pytest.mark.asyncio
async def test_optional_tool_support_is_not_misclassified_as_strict_tool() -> None:
    result = await CapabilityProbe(OptionalToolOnlyProbeAdapter()).run("model")

    assert result.chat is True
    assert result.tool_calling is True
    assert result.forced_tool is False
    assert result.structured_output is False
    assert result.structured_output_capability == "plain_text"


@pytest.mark.asyncio
async def test_probe_includes_actionable_error_message() -> None:
    result = await CapabilityProbe(FailingProbeAdapter()).run("model")

    assert result.error == "RuntimeError: endpoint returned text/html"
    assert result.diagnostic_code == "connection_failed"


@pytest.mark.parametrize(("message", "code"), [
    ("404 Not Found", "route_endpoint_not_found"),
    ("401 Unauthorized", "credentials_rejected"),
    ("429 rate limit", "rate_limited"),
    ("request timed out", "timeout"),
])
def test_probe_classifies_route_diagnostics_without_declaring_model_absent(
    message: str, code: str,
) -> None:
    assert CapabilityProbe._diagnostic_code(RuntimeError(message)) == code


@pytest.mark.asyncio
async def test_probe_treats_successful_empty_chat_as_connected_and_accepts_fenced_json() -> None:
    result = await CapabilityProbe(EmptyChatProbeAdapter()).run("model")

    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is True


def test_probe_json_parser_accepts_wrappers_and_rejects_ambiguous_objects() -> None:
    assert CapabilityProbe._parse_json(
        'Result:\n<!-- presentation note -->\n```JSON\n{"ok": true}\n```'
    ) == {"ok": True}

    with pytest.raises(ValueError, match="multiple JSON objects"):
        CapabilityProbe._parse_json('{"ok": false}\n{"ok": true}')
