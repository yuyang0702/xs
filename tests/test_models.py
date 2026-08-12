import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.models import ModelGateway, ModelRoutesExhaustedError
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputCapabilityError,
)


class FakeAdapter:
    async def complete(self, request):
        assert request.model == "actual-model"
        return ModelResponse(text="result", input_tokens=10, output_tokens=20, raw_request_id="req-1")


class StructuredRecordingAdapter:
    def __init__(self, *, tool: bool = False):
        self.requests = []
        self.tool = tool

    async def complete(self, request):
        self.requests.append(request)
        if self.tool:
            return ModelResponse(tool_calls=[ToolCall(
                id="artifact",
                name="planning_packet",
                arguments={"events": [{"event_id": "EV-BEAE4985"}]},
            )])
        return ModelResponse(text='{"events":[{"event_id":"EV-BEAE4985"}]}')


def test_routes_exhausted_names_errors_without_provider_detail() -> None:
    error = ModelRoutesExhaustedError(TimeoutError(), RuntimeError())

    assert str(error) == "primary and fallback model routes were exhausted"
    assert isinstance(error.primary_error, TimeoutError)
    assert isinstance(error.fallback_error, RuntimeError)


class FakeRegistry:
    def resolve(self, provider_id, model_id):
        assert (provider_id, model_id) == ("provider", "model")
        return ResolvedModel(provider_id, model_id, "actual-model", FakeAdapter())


class FailingAdapter:
    async def complete(self, request):
        raise RuntimeError("primary unavailable")


class SuccessfulFallbackAdapter:
    async def complete(self, request):
        return ModelResponse(text="fallback result", input_tokens=4, output_tokens=6)


class BudgetRecordingAdapter:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.budgets = []

    async def complete(self, request):
        self.budgets.append(request.max_output_tokens)
        if self.fail:
            raise RuntimeError("route unavailable")
        return ModelResponse(text="fallback result", input_tokens=4, output_tokens=6)


class FlakyConnectAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("All connection attempts failed")
        return ModelResponse(text="recovered", input_tokens=2, output_tokens=3)


class InterruptedThenCompleteAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="partial", input_tokens=2, output_tokens=3,
                provider_state={"transport_complete": False},
            )
        return ModelResponse(
            text="complete", input_tokens=2, output_tokens=4,
            finish_reason="stop",
            provider_state={"transport_complete": True},
        )


class FlakyToolConnectAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("peer closed connection without sending complete message body")
        return ModelResponse(text="recovered", input_tokens=2, output_tokens=3)


class CountingFailAdapter:
    def __init__(self, message="timed out"):
        self.calls = 0
        self.message = message

    async def complete(self, request):
        self.calls += 1
        raise RuntimeError(self.message)


class ConfiguredFallbackRegistry:
    def resolve(self, provider_id, model_id):
        if (provider_id, model_id) == ("primary-provider", "primary-model"):
            return ResolvedModel(provider_id, model_id, "primary", FailingAdapter())
        if (provider_id, model_id) == ("fallback-provider", "fallback-model"):
            return ResolvedModel(provider_id, model_id, "fallback", SuccessfulFallbackAdapter())
        raise AssertionError((provider_id, model_id))


class MissingPrimaryKeyRegistry:
    def resolve(self, provider_id, model_id):
        if (provider_id, model_id) == ("primary-provider", "primary-model"):
            raise ValueError("missing_api_key")
        if (provider_id, model_id) == ("fallback-provider", "fallback-model"):
            return ResolvedModel(provider_id, model_id, "fallback", SuccessfulFallbackAdapter())
        raise AssertionError((provider_id, model_id))


class MissingBothKeysRegistry:
    def resolve(self, provider_id, model_id):
        raise ValueError(f"missing_api_key: {provider_id}")


def fallback_receipt_fields(result):
    return {
        key: result.receipt[key]
        for key in ("fallback_used", "fallback_from_provider_id", "fallback_from_model_id")
    }


@pytest.mark.asyncio
async def test_gateway_uses_configured_fallback_for_plain_completion(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "polish", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )

    result = await ModelGateway(db, ConfiguredFallbackRegistry()).complete(
        "polish", "rules", "polish",
    )

    assert result.text == "fallback result"
    assert result.receipt["provider_id"] == "fallback-provider"
    assert fallback_receipt_fields(result) == {
        "fallback_used": True,
        "fallback_from_provider_id": "primary-provider",
        "fallback_from_model_id": "primary-model",
    }


@pytest.mark.asyncio
async def test_gateway_uses_distinct_primary_and_fallback_output_limits(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "polish", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    primary = BudgetRecordingAdapter(fail=True)
    fallback = BudgetRecordingAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            adapter = primary if provider_id == "primary-provider" else fallback
            return ResolvedModel(provider_id, model_id, model_id, adapter)

    result = await ModelGateway(db, Registry()).complete(
        "polish", "rules", "polish", max_output_tokens=6144,
        fallback_max_output_tokens=3072,
    )

    assert result.text == "fallback result"
    assert primary.budgets == [6144]
    assert fallback.budgets == [3072]


def planning_contract() -> StructuredArtifactContract:
    return StructuredArtifactContract(
        name="planning_packet",
        schema={
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"event_id": {"type": "string"}},
                        "required": ["event_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["events"],
            "additionalProperties": False,
        },
        runtime_authority={"segment": 5},
    )


@pytest.mark.asyncio
async def test_gateway_uses_only_explicit_route_structured_capability(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "gpt-brand", None, None)
    adapter = StructuredRecordingAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, "gpt-5-through-relay", adapter,
                {"structured_output": "auto"},
            )

    with pytest.raises(StructuredOutputCapabilityError):
        await ModelGateway(db, Registry()).complete_structured(
            "planning", "rules", "return an artifact", planning_contract(),
        )
    assert adapter.requests == []


@pytest.mark.asyncio
async def test_gateway_can_fallback_to_explicit_strict_schema_route(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-relay", "primary-model",
        "schema-relay", "schema-model",
    )
    primary = StructuredRecordingAdapter()
    fallback = StructuredRecordingAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            if provider_id == "primary-relay":
                return ResolvedModel(
                    provider_id, model_id, "claude-through-relay", primary,
                    {"structured_output": "plain_text"},
                )
            return ResolvedModel(
                provider_id, model_id, "gemini-through-relay", fallback,
                {"structured_output": "strict_json_schema"},
            )

    result = await ModelGateway(db, Registry()).complete_structured(
        "planning", "rules", "return an artifact", planning_contract(),
    )

    assert primary.requests == []
    assert fallback.requests[0].response_schema["strict"] is True
    assert result.receipt["fallback_used"] is True
    assert result.receipt["structured_output_capability"] == "strict_json_schema"


@pytest.mark.asyncio
async def test_explicit_route_keeps_schema_and_never_hides_route_selection(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-relay", "primary-model",
        "schema-relay", "schema-model",
    )
    primary = StructuredRecordingAdapter()
    fallback = StructuredRecordingAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            if provider_id == "primary-relay":
                return ResolvedModel(
                    provider_id, model_id, "primary", primary,
                    {"structured_output": "strict_json_schema"},
                )
            return ResolvedModel(
                provider_id, model_id, "fallback", fallback,
                {"structured_output": "strict_json_schema"},
            )

    result = await ModelGateway(db, Registry()).complete_route(
        "configured_fallback",
        "planning",
        "rules",
        "return an artifact",
        contract=planning_contract(),
    )

    assert primary.requests == []
    assert fallback.requests[0].response_schema["name"] == "planning_packet"
    assert result.receipt["configured_fallback_direct"] is True
    assert result.receipt["execution_mode"] == "strict_json_schema"


@pytest.mark.asyncio
async def test_gateway_projects_one_strict_tool_call_to_json_text(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "tool-model", None, None)
    adapter = StructuredRecordingAdapter(tool=True)

    class Registry:
        def resolve(self, provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, "claude-compatible", adapter,
                {"structured_output": "strict_tool"},
            )

    result = await ModelGateway(db, Registry()).complete_structured(
        "planning", "rules", "return an artifact", planning_contract(),
    )

    assert adapter.requests[0].required_tool == "planning_packet"
    assert '"EV-BEAE4985"' in result.text
    assert result.receipt["execution_mode"] == "strict_tool"


@pytest.mark.asyncio
async def test_structured_protocol_can_continue_to_another_probed_capable_route(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    for provider_id in ("plain-relay", "tool-relay", "schema-relay"):
        db.save_provider(
            provider_id=provider_id,
            name=provider_id,
            protocol="openai-chat",
            base_url=f"https://{provider_id}.invalid/v1",
            auth_type="bearer",
            timeout_seconds=30,
            extra_headers={},
        )
    db.save_model(
        model_id="plain-model", provider_id="plain-relay",
        display_name="plain", model_name="plain",
        capabilities={"structured_output": "plain_text"},
    )
    db.save_model(
        model_id="broken-tool-model", provider_id="tool-relay",
        display_name="broken tool", model_name="broken-tool",
        capabilities={"structured_output": "strict_tool"},
    )
    db.save_model(
        model_id="rescue-schema-model", provider_id="schema-relay",
        display_name="rescue schema", model_name="rescue-schema",
        capabilities={"structured_output": "strict_json_schema"},
    )
    db.save_role_binding(
        "planning", "plain-relay", "plain-model",
        "tool-relay", "broken-tool-model",
    )
    broken_tool = StructuredRecordingAdapter(tool=False)
    rescue_schema = StructuredRecordingAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            model = db.get_model(model_id)
            assert model is not None
            adapter = (
                broken_tool if model_id == "broken-tool-model"
                else rescue_schema
            )
            return ResolvedModel(
                provider_id, model_id, model["model_name"], adapter,
                model["capabilities"],
            )

    result = await ModelGateway(db, Registry()).complete_structured(
        "planning", "rules", "return an artifact", planning_contract(),
        allow_capability_roster=True,
    )

    assert result.receipt["provider_id"] == "schema-relay"
    assert result.receipt["model_id"] == "rescue-schema-model"
    assert result.receipt["capability_roster_fallback"] is True
    assert result.receipt["attempted_route_count"] == 3
    assert len(broken_tool.requests) == 1
    assert len(rescue_schema.requests) == 1


@pytest.mark.asyncio
async def test_gateway_uses_fallback_when_primary_key_is_missing(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )

    result = await ModelGateway(db, MissingPrimaryKeyRegistry()).complete(
        "planning", "rules", "plan",
    )

    assert result.text == "fallback result"
    assert result.receipt["provider_id"] == "fallback-provider"
    assert "code=model.route_failed" in result.receipt["primary_error"]
    assert "missing_api_key" not in result.receipt["primary_error"]
    assert fallback_receipt_fields(result) == {
        "fallback_used": True,
        "fallback_from_provider_id": "primary-provider",
        "fallback_from_model_id": "primary-model",
    }


@pytest.mark.asyncio
async def test_gateway_preserves_both_route_errors_when_primary_and_fallback_keys_are_missing(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )

    with pytest.raises(ModelRoutesExhaustedError) as caught:
        await ModelGateway(db, MissingBothKeysRegistry()).complete(
            "planning", "rules", "plan",
        )

    assert str(caught.value) == "primary and fallback model routes were exhausted"
    assert "primary-provider" not in str(caught.value)
    assert "fallback-provider" not in str(caught.value)
    assert "missing_api_key: primary-provider" in str(caught.value.primary_error)
    assert "missing_api_key: fallback-provider" in str(caught.value.fallback_error)


@pytest.mark.asyncio
async def test_gateway_primary_only_preserves_missing_key_error_without_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "polish", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    primary_error = ValueError("missing_api_key")

    class Registry:
        def __init__(self):
            self.resolve_calls = []

        def resolve(self, provider_id, model_id):
            self.resolve_calls.append((provider_id, model_id))
            if provider_id == "primary-provider":
                raise primary_error
            return ResolvedModel(
                provider_id, model_id, model_id, SuccessfulFallbackAdapter(),
            )

    registry = Registry()

    with pytest.raises(ValueError) as caught:
        await ModelGateway(db, registry).complete_primary(
            "polish", "rules", "polish",
        )

    assert caught.value is primary_error
    assert registry.resolve_calls == [("primary-provider", "primary-model")]


@pytest.mark.asyncio
async def test_gateway_retries_one_transient_connect_failure_before_fallback(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary-provider", "primary-model", "fallback-provider", "fallback-model")

    class Registry(ConfiguredFallbackRegistry):
        def __init__(self):
            self.primary_adapters = []

        def resolve(self, provider_id, model_id):
            if provider_id == "primary-provider":
                adapter = FlakyConnectAdapter()
                self.primary_adapters.append(adapter)
                return ResolvedModel(provider_id, model_id, "primary", adapter)
            return super().resolve(provider_id, model_id)

    registry = Registry()
    monkeypatch.setattr(ModelGateway, "CONNECT_RETRY_DELAY", 0)
    result = await ModelGateway(db, registry).complete("polish", "rules", "text")

    assert len(registry.primary_adapters) == 1
    assert registry.primary_adapters[0].calls == 2
    assert result.text == "recovered"
    assert result.receipt.get("fallback_used") is not True


@pytest.mark.asyncio
async def test_gateway_retries_nonterminal_response_without_accepting_partial_text(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("draft", "provider", "model", None, None)
    adapter = InterruptedThenCompleteAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            return ResolvedModel(provider_id, model_id, "actual-model", adapter)

    monkeypatch.setattr(ModelGateway, "CONNECT_RETRY_DELAY", 0)
    result = await ModelGateway(db, Registry()).complete(
        "draft", "rules", "text", max_output_tokens=4096,
    )

    assert adapter.calls == 2
    assert result.text == "complete"
    with db.connect() as connection:
        observations = [dict(row) for row in connection.execute(
            "SELECT * FROM model_output_observations ORDER BY id"
        )]
    assert [item["transport_complete"] for item in observations] == [0, 1]


@pytest.mark.asyncio
async def test_tool_gateway_retries_one_transient_read_failure_before_fallback(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("review", "primary-provider", "primary-model", "fallback-provider", "fallback-model")
    primary = FlakyToolConnectAdapter()

    class Registry(ConfiguredFallbackRegistry):
        def resolve(self, provider_id, model_id):
            if provider_id == "primary-provider":
                return ResolvedModel(provider_id, model_id, "primary", primary)
            return super().resolve(provider_id, model_id)

    monkeypatch.setattr(ModelGateway, "CONNECT_RETRY_DELAY", 0)
    result = await ModelGateway(db, Registry()).complete_with_tools(
        "review", "rules", "review", Toolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert primary.calls == 2
    assert result.text == "recovered"
    assert result.receipt.get("fallback_used") is not True


@pytest.mark.asyncio
async def test_gateway_retries_full_timeout_once_before_fallback(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary-provider", "primary-model", "fallback-provider", "fallback-model")
    primary = CountingFailAdapter("request timed out")

    class Registry(ConfiguredFallbackRegistry):
        def resolve(self, provider_id, model_id):
            if provider_id == "primary-provider":
                return ResolvedModel(provider_id, model_id, "primary", primary)
            return super().resolve(provider_id, model_id)

    monkeypatch.setattr(ModelGateway, "CONNECT_RETRY_DELAY", 0)
    result = await ModelGateway(db, Registry()).complete("polish", "rules", "text")

    assert primary.calls == 2
    assert result.receipt["fallback_used"] is True
    assert "code=model.route_failed" in result.receipt["primary_error"]
    assert "request timed out" not in result.receipt["primary_error"]


@pytest.mark.asyncio
async def test_gateway_can_call_configured_fallback_directly(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary-provider", "primary-model", "fallback-provider", "fallback-model")
    primary = CountingFailAdapter("must not be called")

    class Registry(ConfiguredFallbackRegistry):
        def resolve(self, provider_id, model_id):
            if provider_id == "primary-provider":
                return ResolvedModel(provider_id, model_id, "primary", primary)
            return super().resolve(provider_id, model_id)

    result = await ModelGateway(db, Registry()).complete_configured_fallback(
        "polish", "rules", "text",
    )

    assert primary.calls == 0
    assert result.text == "fallback result"
    assert result.receipt["configured_fallback_direct"] is True


@pytest.mark.asyncio
async def test_gateway_uses_configured_fallback_for_tool_completion(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )

    result = await ModelGateway(db, ConfiguredFallbackRegistry()).complete_with_tools(
        "planning", "rules", "plan", Toolbox(),
        fallback_context=lambda: "evidence", run_id="run-1",
    )

    assert result.text == "fallback result"
    assert result.receipt["provider_id"] == "fallback-provider"
    assert result.receipt["fallback_used"] is True


@pytest.mark.asyncio
async def test_tool_gateway_uses_fallback_when_primary_key_is_missing(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )

    result = await ModelGateway(db, MissingPrimaryKeyRegistry()).complete_with_tools(
        "planning", "rules", "plan", Toolbox(),
        fallback_context=lambda: "evidence", run_id="run-1",
    )

    assert result.text == "fallback result"
    assert result.receipt["provider_id"] == "fallback-provider"
    assert "code=model.route_failed" in result.receipt["primary_error"]
    assert "missing_api_key" not in result.receipt["primary_error"]
    assert fallback_receipt_fields(result) == {
        "fallback_used": True,
        "fallback_from_provider_id": "primary-provider",
        "fallback_from_model_id": "primary-model",
    }


@pytest.mark.asyncio
async def test_gateway_without_configured_fallback_preserves_primary_failure(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary-provider", "primary-model", None, None)

    with pytest.raises(RuntimeError, match="primary unavailable"):
        await ModelGateway(db, ConfiguredFallbackRegistry()).complete("polish", "rules", "polish")


@pytest.mark.asyncio
async def test_gateway_routes_role_and_returns_redacted_receipt(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("draft", "provider", "model", None, None)
    result = await ModelGateway(db, FakeRegistry()).complete("draft", "system rules", "write")
    assert result.text == "result"
    assert result.receipt["role"] == "draft"
    assert result.receipt["provider_id"] == "provider"
    assert result.receipt["model_id"] == "model"
    assert result.receipt["model_name"] == "actual-model"
    assert result.receipt["input_tokens"] == 10
    assert result.receipt["output_tokens"] == 20
    assert result.receipt["request_id"] == "req-1"
    assert result.receipt["finish_reason"] is None
    assert result.receipt["transport_complete"] is True
    assert result.receipt["execution_mode"] == "plain"
    assert len(result.receipt["route_fingerprint"]) == 64


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


class PrematureControlledAdapter:
    def __init__(self):
        self.calls = 0
        self.required_tools = []

    async def complete(self, request):
        self.calls += 1
        self.required_tools.append(request.required_tool)
        if self.calls == 1:
            return ModelResponse(text="done", input_tokens=3, output_tokens=1)
        assert "controlled task is not complete" in request.messages[-1].content
        return ModelResponse(tool_calls=[ToolCall(
            id="complete", name="complete_skill", arguments={"summary": "finished"},
        )])


class ForceUnsupportedThenToolAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if request.required_tool:
            raise ToolCapabilityError("tool_choice is not supported")
        if self.calls == 2:
            return ModelResponse(tool_calls=[ToolCall(
                id="search", name="search_chapters", arguments={"query": "all"},
            )])
        return ModelResponse(tool_calls=[ToolCall(
            id="complete", name="complete_skill", arguments={"summary": "finished"},
        )])


class ProposalThenRouteFailureAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(tool_calls=[ToolCall(
                id="proposal", name="create_file_proposal", arguments={},
            )])
        raise RuntimeError("primary route ended before complete_skill")


class RecoverableProposalToolbox:
    def __init__(self):
        self.ready = False

    def definitions(self):
        from novel_flywheel.domain.models import ToolDefinition
        return [
            ToolDefinition(name="create_file_proposal", description="Create", input_schema={"type": "object"}),
            ToolDefinition(name="complete_skill", description="Complete", input_schema={"type": "object"}),
        ]

    def execute(self, name, arguments):
        if name == "create_file_proposal":
            self.ready = True
            return {"status": "pending"}
        return {"status": "validating", "summary": "finished"}

    def finalize_after_route_error(self):
        return "Recovered complete proposals" if self.ready else None


class NeverCalledAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        raise AssertionError("fallback must not run")


class RepairContextToolbox(Toolbox):
    def __init__(self):
        self.prepared = []

    def prepare_fallback(self, error):
        self.prepared.append(str(error))
        return "保留已有候选，只补缺失项：世界设定索引"


class RepairContextAdapter:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        assert "保留已有候选，只补缺失项：世界设定索引" in request.messages[-1].content
        return ModelResponse(text="fallback repaired", input_tokens=2, output_tokens=3)


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
async def test_controlled_runtime_continues_after_premature_text_response(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "provider", "model", None, None)
    adapter = PrematureControlledAdapter()

    result = await ModelGateway(db, ToolRegistry(adapter)).complete_with_tools(
        "planning", "rules", "execute", MixedCompletingToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert adapter.calls == 2
    assert adapter.required_tools == ["search_chapters", None]
    assert result.text == "finished"
    assert result.receipt["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_controlled_runtime_retries_optional_tools_when_force_is_unsupported(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "provider", "model", None, None)
    adapter = ForceUnsupportedThenToolAdapter()

    result = await ModelGateway(db, ToolRegistry(adapter)).complete_with_tools(
        "planning", "rules", "execute", MixedCompletingToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert adapter.calls == 3
    assert result.text == "finished"
    assert result.receipt["tool_call_count"] == 2


@pytest.mark.asyncio
async def test_tool_gateway_uses_complete_local_proposals_before_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    primary = ProposalThenRouteFailureAdapter()
    fallback = NeverCalledAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            adapter = primary if provider_id == "primary-provider" else fallback
            return ResolvedModel(provider_id, model_id, model_id, adapter)

    result = await ModelGateway(db, Registry()).complete_with_tools(
        "planning", "rules", "execute", RecoverableProposalToolbox(),
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert result.text == "Recovered complete proposals"
    assert result.receipt["execution_mode"] == "native_tools"
    assert result.receipt["proposal_recovered"] is True
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_tool_gateway_passes_isolated_repair_context_to_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    toolbox = RepairContextToolbox()
    fallback = RepairContextAdapter()

    class Registry:
        def resolve(self, provider_id, model_id):
            adapter = FailingAdapter() if provider_id == "primary-provider" else fallback
            return ResolvedModel(provider_id, model_id, model_id, adapter)

    result = await ModelGateway(db, Registry()).complete_with_tools(
        "planning", "rules", "execute", toolbox,
        fallback_context=lambda: "fallback", run_id="run-1",
    )

    assert result.text == "fallback repaired"
    assert toolbox.prepared == ["primary unavailable"]
    assert result.receipt["fallback_used"] is True


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
    assert "code=model.route_failed" in result.receipt["fallback_reason"]
    assert "tools unsupported" not in result.receipt["fallback_reason"]
