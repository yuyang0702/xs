import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.models import ModelGateway
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.providers.http import ToolCapabilityError


class FakeAdapter:
    async def complete(self, request):
        assert request.model == "actual-model"
        return ModelResponse(text="result", input_tokens=10, output_tokens=20, raw_request_id="req-1")


class FakeRegistry:
    def resolve(self, provider_id, model_id):
        assert (provider_id, model_id) == ("provider", "model")
        return ResolvedModel(provider_id, model_id, "actual-model", FakeAdapter())


@pytest.mark.asyncio
async def test_gateway_routes_role_and_returns_redacted_receipt(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("draft", "provider", "model", None, None)
    result = await ModelGateway(db, FakeRegistry()).complete("draft", "system rules", "write")
    assert result.text == "result"
    assert result.receipt == {
        "role": "draft", "provider_id": "provider", "model_id": "model",
        "model_name": "actual-model", "input_tokens": 10, "output_tokens": 20,
        "request_id": "req-1", "finish_reason": None,
    }


@pytest.mark.asyncio
async def test_gateway_rejects_unbound_role_before_model_call(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    with pytest.raises(LookupError, match="review"):
        await ModelGateway(db, FakeRegistry()).complete("review", "rules", "review")


class ToolAdapter:
    def __init__(self, unsupported=False):
        self.calls = 0
        self.unsupported = unsupported

    async def complete(self, request):
        self.calls += 1
        if self.unsupported and request.tools:
            raise ToolCapabilityError("tools unsupported")
        if request.tools and self.calls == 1:
            return ModelResponse(tool_calls=[ToolCall(id="1", name="search_chapters", arguments={"query": "key"})])
        return ModelResponse(text="approved", input_tokens=3, output_tokens=2)


class ToolRegistry:
    def __init__(self, adapter, tool_support="auto"):
        self.adapter = adapter
        self.tool_support = tool_support

    def resolve(self, provider_id, model_id):
        return ResolvedModel(provider_id, model_id, "actual-model", self.adapter, {"tool_support": self.tool_support})


class Toolbox:
    def definitions(self):
        from novel_flywheel.domain.models import ToolDefinition
        return [ToolDefinition(name="search_chapters", description="Search", input_schema={"type": "object"})]

    def execute(self, name, arguments):
        return {"items": [{"excerpt": "key evidence"}]}


class CorrectingToolAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(tool_calls=[ToolCall(
                id="bad-call", name="search_chapters", arguments={"query": "bad"},
            )])
        assert "query is not allowed" in request.messages[-1].content
        return ModelResponse(text="corrected", input_tokens=3, output_tokens=2)


class RejectingToolbox(Toolbox):
    def execute(self, name, arguments):
        raise ValueError("query is not allowed")


class FinalRoundAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls < 8:
            return ModelResponse(tool_calls=[ToolCall(
                id=str(self.calls), name="search_chapters", arguments={"query": str(self.calls)},
            )])
        assert "FINAL TOOL ROUND" in request.messages[-1].content
        return ModelResponse(tool_calls=[ToolCall(
            id="complete", name="complete_skill", arguments={"summary": "finished"},
        )])


class MixedCompletingToolbox(Toolbox):
    def definitions(self):
        from novel_flywheel.domain.models import ToolDefinition
        return [
            ToolDefinition(name="search_chapters", description="Search", input_schema={"type": "object"}),
            ToolDefinition(name="complete_skill", description="Complete", input_schema={"type": "object"}),
        ]

    def execute(self, name, arguments):
        if name == "complete_skill":
            return {"status": "validating", "summary": arguments["summary"]}
        return {"items": []}


class AutoFinalizingToolbox(Toolbox):
    def finalize_on_tool_limit(self):
        return "Generated proposals are ready for local validation"


class NeverCompletingAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return ModelResponse(tool_calls=[ToolCall(
            id=str(self.calls), name="search_chapters", arguments={"query": str(self.calls)},
        )])


class ReadUntilForcedAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if request.tools:
            return ModelResponse(tool_calls=[ToolCall(
                id=str(self.calls), name="search_chapters", arguments={"query": "all"},
            )])
        assert "FINAL RESPONSE" in request.messages[-1].content
        return ModelResponse(text="# Complete draft", input_tokens=5, output_tokens=120)


@pytest.mark.asyncio
async def test_gateway_runs_tools_and_returns_execution_receipt(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("review", "provider", "model", None, None)
    result = await ModelGateway(db, ToolRegistry(ToolAdapter())).complete_with_tools(
        "review", "rules", "review", Toolbox(), fallback_context=lambda: "fallback", run_id="run-1",
    )
    assert result.text == "approved"
    assert result.receipt["execution_mode"] == "native_tools"
    assert result.receipt["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_gateway_returns_recoverable_tool_errors_to_model(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("review", "provider", "model", None, None)

    result = await ModelGateway(db, ToolRegistry(CorrectingToolAdapter())).complete_with_tools(
        "review", "rules", "review", RejectingToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert result.text == "corrected"
    assert result.receipt["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_gateway_prompts_final_round_and_stops_on_complete_skill(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "provider", "model", None, None)
    adapter = FinalRoundAdapter()

    result = await ModelGateway(db, ToolRegistry(adapter)).complete_with_tools(
        "planning", "rules", "execute", MixedCompletingToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert adapter.calls == 8
    assert result.text == "finished"
    assert result.receipt["tool_call_count"] == 8


@pytest.mark.asyncio
async def test_gateway_allows_toolbox_to_finalize_safely_at_round_limit(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "provider", "model", None, None)
    adapter = NeverCompletingAdapter()

    result = await ModelGateway(db, ToolRegistry(adapter)).complete_with_tools(
        "planning", "rules", "execute", AutoFinalizingToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert adapter.calls == 8
    assert result.text == "Generated proposals are ready for local validation"
    assert result.receipt["tool_call_count"] == 8


@pytest.mark.asyncio
async def test_gateway_forces_read_only_toolbox_to_answer_after_three_read_rounds(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("draft", "provider", "model", None, None)
    adapter = ReadUntilForcedAdapter()

    result = await ModelGateway(db, ToolRegistry(adapter)).complete_with_tools(
        "draft", "rules", "write the story", Toolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert adapter.calls == 4
    assert result.text == "# Complete draft"
    assert result.receipt["tool_call_count"] == 3


@pytest.mark.asyncio
async def test_gateway_falls_back_only_for_tool_capability_error(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("review", "provider", "model", None, None)
    result = await ModelGateway(db, ToolRegistry(ToolAdapter(unsupported=True))).complete_with_tools(
        "review", "rules", "review", Toolbox(), fallback_context=lambda: "EVIDENCE", run_id="run-1",
    )
    assert result.receipt["execution_mode"] == "degraded_prompt_mode"
    assert result.receipt["fallback_reason"] == "tools unsupported"
