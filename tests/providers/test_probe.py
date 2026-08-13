import json

import pytest

from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.providers.probe import CapabilityProbe


def business_payload() -> dict:
    return CapabilityProbe._business_payload()


class ProbeAdapter:
    def __init__(self, tool_calling=True):
        self.calls = 0
        self.requests = []
        self.tool_calling = tool_calling

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is not None:
            return ModelResponse(text=json.dumps(
                business_payload(), ensure_ascii=False,
            ))
        if request.tools:
            if self.tool_calling:
                return ModelResponse(tool_calls=[ToolCall(
                    id="probe", name="probe_tool", arguments=business_payload(),
                )])
            return ModelResponse(text="tools unavailable")
        if request.response_format == "json_object":
            return ModelResponse(text=json.dumps(
                business_payload(), ensure_ascii=False,
            ))
        return ModelResponse(text="连接正常")


class FailingProbeAdapter:
    async def complete(self, request):
        raise RuntimeError("endpoint returned text/html")


class EmptyChatProbeAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is None and not request.tools:
            return ModelResponse(text="")
        if request.response_schema is not None:
            return ModelResponse(text=(
                "```json\n"
                + json.dumps(business_payload(), ensure_ascii=False)
                + "\n```"
            ))
        return ModelResponse(tool_calls=[ToolCall(
            id="probe", name="probe_tool", arguments=business_payload(),
        )])


class ThinkingProbeAdapter(ProbeAdapter):
    error = "Thinking mode does not support this tool_choice"

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is not None:
            return ModelResponse(text=json.dumps(
                business_payload(), ensure_ascii=False,
            ))
        if not request.tools:
            return ModelResponse(text="ok")
        if request.required_tool:
            raise ToolCapabilityError(self.error)
        return ModelResponse(tool_calls=[ToolCall(
            id="probe", name="probe_tool", arguments=business_payload(),
        )])


class KimiThinkingProbeAdapter(ThinkingProbeAdapter):
    error = "tool_choice 'specified' is incompatible with thinking enabled"


class UnsupportedForcedToolProbeAdapter(ThinkingProbeAdapter):
    error = "tool_choice is not supported by this provider"


class IgnoredForcedToolProbeAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is not None:
            return ModelResponse(text=json.dumps(
                business_payload(), ensure_ascii=False,
            ))
        if not request.tools:
            return ModelResponse(text="ok")
        if request.required_tool:
            return ModelResponse(text="I cannot call tools")
        return ModelResponse(tool_calls=[ToolCall(
            id="probe", name="probe_tool", arguments=business_payload(),
        )])


class OptionalToolOnlyProbeAdapter(ProbeAdapter):
    """Accepts parameters but only returns a tiny/ignored schema payload."""

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is not None:
            return ModelResponse(text='{"ok":true,"unexpected":"schema ignored"}')
        if not request.tools:
            return ModelResponse(text="ok")
        if request.required_tool:
            raise ToolCapabilityError(
                "Thinking mode does not support this tool_choice"
            )
        return ModelResponse(tool_calls=[ToolCall(
            id="probe", name="probe_tool", arguments=business_payload(),
        )])


class EmptyForcedToolArgumentsAdapter(ProbeAdapter):
    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.response_schema is not None:
            return ModelResponse(text="{}")
        if request.tools:
            return ModelResponse(tool_calls=[ToolCall(
                id="probe", name="probe_tool", arguments={},
            )])
        return ModelResponse(text="ok")


@pytest.mark.asyncio
async def test_probe_reports_business_json_and_tool_calling_separately() -> None:
    adapter = ProbeAdapter()
    result = await CapabilityProbe(adapter).run("model")

    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is True
    assert result.forced_tool is True
    assert result.structured_output_capability == "strict_json_schema"
    assert result.protocol_capability == "strict_json_schema"
    assert result.qualification_status == "business_qualified"
    assert result.verified_output_characters > 1200
    assert len(result.qualification_schema_sha256) == 64
    assert result.json_object is True
    assert result.error is None
    assert result.diagnostic_code is None
    assert adapter.requests[2].required_tool == "probe_tool"
    assert adapter.requests[1].max_output_tokens == 2048


@pytest.mark.asyncio
async def test_probe_can_report_partial_tool_support_after_business_qualification() -> None:
    result = await CapabilityProbe(ProbeAdapter(tool_calling=False)).run("model")
    assert result.chat is True
    assert result.structured_output is True
    assert result.qualification_status == "business_qualified"
    assert result.tool_calling is False
    assert result.error is not None


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
async def test_optional_tool_support_is_not_misclassified_as_business_strict() -> None:
    result = await CapabilityProbe(OptionalToolOnlyProbeAdapter()).run("model")
    assert result.chat is True
    assert result.tool_calling is True
    assert result.forced_tool is False
    assert result.structured_output is False
    assert result.structured_output_capability == "plain_text"
    assert result.qualification_status == "protocol_only"
    assert result.verified_output_characters == 0


@pytest.mark.asyncio
async def test_empty_forced_tool_arguments_never_receive_business_qualification() -> None:
    result = await CapabilityProbe(EmptyForcedToolArgumentsAdapter()).run("model")
    assert result.chat is True
    assert result.forced_tool is True
    assert result.protocol_capability in {"strict_json_schema", "strict_tool"}
    assert result.structured_output_capability == "plain_text"
    assert result.qualification_status == "protocol_only"
    assert result.verified_output_characters == 0


@pytest.mark.asyncio
async def test_probe_includes_actionable_error_message() -> None:
    result = await CapabilityProbe(FailingProbeAdapter()).run("model")
    assert result.error is not None
    assert "provider.probe_failed" in result.error
    assert "endpoint returned text/html" not in result.error
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
async def test_probe_accepts_fenced_business_json_and_empty_chat() -> None:
    result = await CapabilityProbe(EmptyChatProbeAdapter()).run("model")
    assert result.chat is True
    assert result.structured_output is True
    assert result.tool_calling is True
    assert result.qualification_status == "business_qualified"


def test_probe_json_parser_accepts_wrappers_and_rejects_ambiguous_objects() -> None:
    assert CapabilityProbe._parse_json(
        'Result:\n<!-- presentation note -->\n```JSON\n{"ok": true}\n```'
    ) == {"ok": True}

    with pytest.raises(ValueError, match="multiple JSON objects"):
        CapabilityProbe._parse_json('{"ok": false}\n{"ok": true}')
