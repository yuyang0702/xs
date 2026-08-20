from __future__ import annotations

import json

import pytest

from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    FinalArtifactCapabilityExhaustedError,
    execute_contract_runtime,
)
from novel_flywheel.db import Database
from novel_flywheel.domain.models import (
    ModelResponse,
    ProviderOutputShapeV1,
    ToolCall,
)
from novel_flywheel.models import (
    FinalArtifactRouteQuarantinedError,
    ModelGateway,
    ReasoningOnlyFinalArtifactUnavailableError,
)
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    normalize_planning_semantic_v2_payload,
    planning_semantic_schema_v2,
)
from novel_flywheel.production_incidents import classify_production_failure
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.structured_artifacts import StructuredArtifactContract


def _shape(
    *block_types: str,
    text_blocks: int = 0,
    visible_chars: int = 0,
    tool_calls: int = 0,
    reasoning_blocks: int = 0,
    unknown_blocks: int = 0,
    normalized_visible_chars: int | None = None,
    normalized_tool_calls: int | None = None,
    finish_reason: str = "max_tokens",
    projection_status: str = "exact",
) -> ProviderOutputShapeV1:
    return ProviderOutputShapeV1(
        provider_family="deterministic_fake",
        protocol="offline",
        finish_reason=finish_reason,
        output_tokens=16000 if finish_reason == "max_tokens" else 120,
        content_block_count=len(block_types),
        content_block_type_sequence=block_types,
        unknown_block_type_sha256s=("b" * 64,) * unknown_blocks,
        text_block_count=text_blocks,
        provider_visible_text_chars=visible_chars,
        tool_call_count=tool_calls,
        reasoning_block_count=reasoning_blocks,
        unknown_block_count=unknown_blocks,
        transport_complete=True,
        normalized_visible_text_chars=(
            visible_chars
            if normalized_visible_chars is None
            else normalized_visible_chars
        ),
        normalized_tool_call_count=(
            tool_calls if normalized_tool_calls is None else normalized_tool_calls
        ),
        adapter_projection_status=projection_status,
        shape_sha256="a" * 64,
    )


class StaticAdapter:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return self.response


class RouteRegistry:
    def __init__(self, primary: StaticAdapter, fallback: StaticAdapter | None = None):
        self.primary = primary
        self.fallback = fallback

    def resolve(self, provider_id, model_id):
        adapter = self.primary if provider_id == "primary" else self.fallback
        assert adapter is not None
        return ResolvedModel(
            provider_id,
            model_id,
            model_id,
            adapter,
            {"structured_output": "strict_json_schema"},
            ("1" if provider_id == "primary" else "2") * 64,
        )


def _contract() -> StructuredArtifactContract:
    return StructuredArtifactContract(
        name="interview_planning",
        version=1,
        schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        runtime_authority={"task": "final-artifact-guard-offline"},
    )


def _spec(contract: StructuredArtifactContract) -> ExecutableContractSpec:
    return ExecutableContractSpec(
        contract_name="interview_planning",
        structured_contract=contract,
        semantic_normalizer=lambda value: dict(value),
        domain_validator=lambda payload: (
            payload
            if len(str(payload.get("message") or "")) >= 12
            else (_ for _ in ()).throw(ValueError("message incomplete"))
        ),
    )


def _gateway(tmp_path, primary_response, fallback_response=None):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning",
        "primary",
        "primary-model",
        "fallback" if fallback_response is not None else None,
        "fallback-model" if fallback_response is not None else None,
    )
    primary = StaticAdapter(primary_response)
    fallback = StaticAdapter(fallback_response) if fallback_response is not None else None
    return db, ModelGateway(db, RouteRegistry(primary, fallback)), primary, fallback


def _reasoning_only_response() -> ModelResponse:
    return ModelResponse(
        text="",
        finish_reason="max_tokens",
        output_tokens=16000,
        raw_request_id="private-provider-request-id",
        provider_state={
            "transport_complete": True,
            "raw_finish_reason": "private-provider-finish-value",
        },
        output_shape=_shape("reasoning", reasoning_blocks=1),
    )


def _valid_text_response() -> ModelResponse:
    text = '{"message":"独立合法路由返回完整且可验证的最终业务产物"}'
    return ModelResponse(
        text=text,
        finish_reason="stop",
        output_tokens=120,
        provider_state={"transport_complete": True},
        output_shape=_shape(
            "text",
            text_blocks=1,
            visible_chars=len(text),
            finish_reason="stop",
        ),
    )


@pytest.mark.asyncio
async def test_reasoning_only_max_tokens_is_typed_before_parser_and_remembered(
    tmp_path,
) -> None:
    db, gateway, primary, _ = _gateway(tmp_path, _reasoning_only_response())
    contract = _contract()

    with pytest.raises(ReasoningOnlyFinalArtifactUnavailableError) as caught:
        await gateway.complete_route(
            "primary",
            "planning",
            "unchanged system",
            "unchanged user",
            contract=contract,
            max_output_tokens=16000,
        )

    assert primary.calls == 1
    assert caught.value.failure_kind == "final_artifact_unavailable"
    assert caught.value.receipt["provider_output_shape"]["reasoning_block_count"] == 1
    qualification = db.get_structured_route_qualification(
        provider_id="primary",
        model_id="primary-model",
        route_fingerprint="1" * 64,
        execution_mode="final_artifact",
        contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    assert qualification["status"] == "quarantined"
    assert qualification["last_failure_reason"] == "reasoning_only_max_tokens"


@pytest.mark.asyncio
async def test_normal_text_output_does_not_trigger_guard(tmp_path) -> None:
    _, gateway, primary, _ = _gateway(tmp_path, _valid_text_response())

    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )

    assert result.text.startswith("{")
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_normal_tool_output_does_not_trigger_guard(tmp_path) -> None:
    tool_response = ModelResponse(
        tool_calls=[ToolCall(
            id="call-1",
            name="interview_planning",
            arguments={"message": "合法工具产物包含完整且可验证的业务内容"},
        )],
        finish_reason="tool_use",
        output_shape=_shape(
            "tool_call", tool_calls=1, finish_reason="tool_use",
        ),
    )
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "primary", "model", None, None)
    adapter = StaticAdapter(tool_response)

    class ToolRegistry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "3" * 64,
            )

    result = await ModelGateway(db, ToolRegistry()).complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert "合法工具产物" in result.text
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_reasoning_with_visible_text_is_not_misclassified(tmp_path) -> None:
    response = _valid_text_response().model_copy(update={
        "output_shape": _shape(
            "reasoning", "text", text_blocks=1,
            visible_chars=len(_valid_text_response().text), reasoning_blocks=1,
            finish_reason="max_tokens",
        ),
        "finish_reason": "max_tokens",
    })
    _, gateway, primary, _ = _gateway(tmp_path, response)
    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert result.text
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_reasoning_with_tool_artifact_is_not_misclassified(tmp_path) -> None:
    tool_response = ModelResponse(
        tool_calls=[ToolCall(
            id="call-1",
            name="interview_planning",
            arguments={"message": "reasoning 后仍产生完整且可验证的工具产物"},
        )],
        finish_reason="max_tokens",
        output_shape=_shape(
            "reasoning", "tool_call",
            tool_calls=1, reasoning_blocks=1,
        ),
    )
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "primary", "model", None, None)
    adapter = StaticAdapter(tool_response)

    class ToolRegistry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "4" * 64,
            )

    result = await ModelGateway(db, ToolRegistry()).complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert "reasoning 后仍产生" in result.text
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_multiple_text_blocks_do_not_trigger_guard(tmp_path) -> None:
    response = _valid_text_response()
    response = response.model_copy(update={
        "output_shape": _shape(
            "text", "text",
            text_blocks=2,
            visible_chars=len(response.text),
            finish_reason="stop",
        ),
    })
    _, gateway, primary, _ = _gateway(tmp_path, response)
    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert result.text == response.text
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_adapter_projection_loss_is_not_reasoning_only(tmp_path) -> None:
    response = ModelResponse(
        text="",
        finish_reason="max_tokens",
        output_shape=_shape(
            "reasoning", "text",
            reasoning_blocks=1,
            text_blocks=1,
            visible_chars=14,
            normalized_visible_chars=0,
            projection_status="changed",
        ),
    )
    _, gateway, primary, _ = _gateway(tmp_path, response)
    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert result.text == ""
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_empty_provider_response_is_not_reasoning_only(tmp_path) -> None:
    response = ModelResponse(
        text="",
        finish_reason="max_tokens",
        output_shape=_shape(),
    )
    _, gateway, primary, _ = _gateway(tmp_path, response)
    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert result.text == ""
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_unknown_block_shape_is_not_misclassified(tmp_path) -> None:
    response = ModelResponse(
        text="",
        finish_reason="max_tokens",
        output_shape=_shape(
            "reasoning", "unknown", reasoning_blocks=1, unknown_blocks=1,
        ),
    )
    _, gateway, primary, _ = _gateway(tmp_path, response)
    result = await gateway.complete_route(
        "primary", "planning", "system", "user", contract=_contract(),
    )
    assert result.text == ""
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_negative_capability_prevents_second_provider_dispatch(tmp_path) -> None:
    _, gateway, primary, _ = _gateway(tmp_path, _reasoning_only_response())
    contract = _contract()
    with pytest.raises(ReasoningOnlyFinalArtifactUnavailableError):
        await gateway.complete_route(
            "primary", "planning", "system", "user", contract=contract,
        )
    with pytest.raises(FinalArtifactRouteQuarantinedError):
        await gateway.complete_route(
            "primary", "planning", "system", "user", contract=contract,
        )
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_same_fingerprint_is_not_retried_and_no_route_fails_typed(
    tmp_path,
) -> None:
    _, gateway, primary, _ = _gateway(tmp_path, _reasoning_only_response())
    observations = []
    with pytest.raises(FinalArtifactCapabilityExhaustedError) as caught:
        await execute_contract_runtime(
            gateway,
            role="planning",
            system="system",
            user="user",
            execution_spec=_spec(_contract()),
            max_output_tokens=16000,
            same_route_attempts=2,
            fallback_attempts=0,
            attempt_observer=observations.append,
        )
    assert primary.calls == 1
    assert caught.value.receipt["route_fingerprint"] == "1" * 64
    assert sum(item["model_call_delta"] for item in observations) == 1
    incident = classify_production_failure(
        str(caught.value), workflow="short-story", stage="planning",
    )
    assert incident["incident_family"] == (
        "provider.reasoning_only_final_artifact_unavailable"
    )


@pytest.mark.asyncio
async def test_existing_distinct_fallback_recovers_through_domain_boundary(
    tmp_path,
) -> None:
    _, gateway, primary, fallback = _gateway(
        tmp_path, _reasoning_only_response(), _valid_text_response(),
    )
    result = await execute_contract_runtime(
        gateway,
        role="planning",
        system="system",
        user="user",
        execution_spec=_spec(_contract()),
        max_output_tokens=16000,
        same_route_attempts=2,
        fallback_attempts=1,
    )
    assert result.attempt.route == "configured_fallback"
    assert result.domain_value["message"].startswith("独立合法路由")
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_normal_primary_route_does_not_touch_fallback(tmp_path) -> None:
    _, gateway, primary, fallback = _gateway(
        tmp_path, _valid_text_response(), _valid_text_response(),
    )
    result = await execute_contract_runtime(
        gateway,
        role="planning",
        system="system",
        user="user",
        execution_spec=_spec(_contract()),
        same_route_attempts=2,
        fallback_attempts=1,
    )
    assert result.attempt.route == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_typed_failure_receipt_is_hash_shape_count_only(tmp_path) -> None:
    _, gateway, _, _ = _gateway(tmp_path, _reasoning_only_response())
    with pytest.raises(ReasoningOnlyFinalArtifactUnavailableError) as caught:
        await gateway.complete_route(
            "primary",
            "planning",
            "RAW PROMPT MUST NOT PERSIST",
            "RAW STORY MUST NOT PERSIST",
            contract=_contract(),
        )
    serialized = json.dumps(caught.value.receipt, ensure_ascii=False)
    assert "RAW PROMPT MUST NOT PERSIST" not in serialized
    assert "RAW STORY MUST NOT PERSIST" not in serialized
    assert '"raw_provider_content":' not in serialized
    assert '"tool_arguments":' not in serialized
    assert "private-provider-request-id" not in serialized
    assert "private-provider-finish-value" not in serialized
    assert caught.value.receipt["request_id_sha256"]
    assert caught.value.receipt["provider_output_shape"]["shape_sha256"]


def test_negative_capability_state_upsert_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    values = {
        "provider_id": "provider",
        "model_id": "model",
        "route_fingerprint": "f" * 64,
        "execution_mode": "final_artifact",
        "contract_name": "interview_planning",
        "schema_sha256": "e" * 64,
        "outcome": "reasoning_only_output_limit",
        "failure_reason": "reasoning_only_max_tokens",
    }

    first = db.save_structured_route_outcome(**values)
    second = db.save_structured_route_outcome(**values)

    assert first["status"] == "quarantined"
    assert second["status"] == "quarantined"
    assert second["consecutive_failures"] == 2
    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM structured_route_qualifications "
            "WHERE provider_id=? AND model_id=? AND route_fingerprint=? "
            "AND execution_mode=? AND contract_name=? AND schema_sha256=?",
            (
                values["provider_id"], values["model_id"],
                values["route_fingerprint"], values["execution_mode"],
                values["contract_name"], values["schema_sha256"],
            ),
        ).fetchone()[0]
    assert count == 1


@pytest.mark.asyncio
async def test_production_shaped_planning_semantic_v2_recovers_on_distinct_route(
    tmp_path, monkeypatch,
) -> None:
    primary_adapter = AnthropicAdapter("https://primary.invalid/v1", "secret")
    fallback_adapter = OpenAIChatAdapter("https://fallback.invalid/v1", "secret")
    semantic_payload = {
        "version": 2,
        "initial_state": "调查尚未开始，既有事实和人物状态保持稳定。",
        "segments": [{
            "kind": "terminal",
            "segment": 1,
            "title": "查清线索",
            "events": [{
                "formal_event_ordinal": 1,
                "narrative": "主角核对证据并完成行动，结果明确闭合了当前事件。",
            }],
        }],
    }

    async def primary_post_stream(*_args, **_kwargs):
        return [], {
            "id": "private-primary-request",
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "private"}],
            "usage": {"output_tokens": 16000},
        }

    async def fallback_post_stream(*_args, **_kwargs):
        return [], {
            "id": "private-fallback-request",
            "choices": [{
                "message": {
                    "content": json.dumps(semantic_payload, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }],
            "usage": {"completion_tokens": 180},
        }

    monkeypatch.setattr(primary_adapter, "post_stream", primary_post_stream)
    monkeypatch.setattr(fallback_adapter, "post_stream", fallback_post_stream)

    class ProductionAdapterRegistry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id,
                model_id,
                model_id,
                primary_adapter if provider_id == "primary" else fallback_adapter,
                {"structured_output": "strict_json_schema"},
                ("7" if provider_id == "primary" else "8") * 64,
            )

    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary", "primary-model",
        "fallback", "fallback-model",
    )
    contract = StructuredArtifactContract(
        name="planning_semantic_v2",
        version=2,
        schema=planning_semantic_schema_v2(),
        runtime_authority={"fixture": "sanitized-production-shaped-boundary-12"},
    )
    result = await execute_contract_runtime(
        ModelGateway(db, ProductionAdapterRegistry()),
        role="planning",
        system="unchanged structured planning system",
        user="sanitized immutable planning authority",
        execution_spec=ExecutableContractSpec(
            contract_name="planning_semantic_v2",
            structured_contract=contract,
            semantic_normalizer=normalize_planning_semantic_v2_payload,
            domain_validator=PlanningSemanticDraftV2.model_validate,
        ),
        max_output_tokens=16000,
        same_route_attempts=2,
        fallback_attempts=1,
    )

    assert result.attempt.route == "configured_fallback"
    assert isinstance(result.domain_value, PlanningSemanticDraftV2)
    assert result.domain_value.segments[0].events[0].formal_event_ordinal == 1
    primary_state = db.get_structured_route_qualification(
        provider_id="primary",
        model_id="primary-model",
        route_fingerprint="7" * 64,
        execution_mode="final_artifact",
        contract_name="planning_semantic_v2",
        schema_sha256=contract.schema_sha256(),
    )
    assert primary_state["status"] == "quarantined"
