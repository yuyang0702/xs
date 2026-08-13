from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.contract_runtime import (
    ContractBusinessOutputIncompleteError,
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.models import ModelGateway
from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    registered_business_wire_schema,
)
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.providers.probe import CapabilityProbe, ProbeResult
from novel_flywheel.production_incidents import classify_production_failure
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.structured_artifacts import StructuredArtifactContract


class EmptyStrictToolThenPlainJsonAdapter:
    """Production shape: native tool mode returns {}, prompt JSON still works."""

    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            return ModelResponse(
                tool_calls=[ToolCall(
                    id="empty-artifact",
                    name=request.required_tool,
                    arguments={},
                )],
                input_tokens=80,
                output_tokens=17,
                finish_reason="tool_use",
            )
        return ModelResponse(
            text='{"message":"完整业务回执，已通过普通 JSON 协议恢复，并包含任务身份、关键证据、处理结论和后续动作"}',
            input_tokens=80,
            output_tokens=48,
            finish_reason="stop",
        )


class NativeToolRejectedThenPlainJsonAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            raise ToolCapabilityError("third-party route rejected tool_choice")
        return ModelResponse(
            text='{"message":"原生协议拒绝后已使用普通 JSON 完整恢复"}',
            input_tokens=50,
            output_tokens=45,
            finish_reason="stop",
        )


class AlwaysEmptyStructuredAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            return ModelResponse(tool_calls=[ToolCall(
                id="empty", name=request.required_tool, arguments={},
            )])
        return ModelResponse(text="{}", finish_reason="stop")


class ValidFallbackToolAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return ModelResponse(tool_calls=[ToolCall(
            id="valid", name=request.required_tool,
            arguments={"message": "独立备用路由返回了完整且可验证的业务回执"},
        )])


class OutputLimitedStrictThenPlainJsonAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            return ModelResponse(
                tool_calls=[ToolCall(
                    id="limited", name=request.required_tool, arguments={},
                )],
                input_tokens=90, output_tokens=32,
                finish_reason="max_tokens",
            )
        return ModelResponse(
            text='{"message":"输出受限后扩大预算并完成普通 JSON 恢复，已补齐任务身份、关键证据、处理结论和后续动作"}',
            input_tokens=90, output_tokens=50, finish_reason="stop",
        )


class InterruptedStrictThenCompleteAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                text="partial", input_tokens=30, output_tokens=10,
                provider_state={"transport_complete": False},
            )
        return ModelResponse(tool_calls=[ToolCall(
            id="valid", name=request.required_tool,
            arguments={"message": "传输中断后的同协议重试返回完整业务回执"},
        )])


class ShortButDomainValidThenCompleteAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            return ModelResponse(tool_calls=[ToolCall(
                id="short", name=request.required_tool,
                arguments={"message": "字段存在但业务内容明显过短"},
            )])
        return ModelResponse(text=json.dumps({
            "message": "完整业务证据" * 40,
        }, ensure_ascii=False))


class PartialRequiredThenCompleteAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.required_tool:
            return ModelResponse(tool_calls=[ToolCall(
                id="partial", name=request.required_tool,
                arguments={"message": "已有一个字段但仍缺少另一项必要业务证据"},
            )])
        return ModelResponse(text=json.dumps({
            "message": "普通 JSON 模式返回完整业务回执",
            "evidence": "已覆盖任务所要求的第二项必要证据",
        }, ensure_ascii=False))


def _message_contract() -> StructuredArtifactContract:
    return StructuredArtifactContract(
        name="interview_planning",
        version=1,
        schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "minLength": 12},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        runtime_authority={"task": "production-shaped-receipt"},
    )


async def test_empty_strict_tool_is_quarantined_and_same_route_recovers_in_plain_mode(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = EmptyStrictToolThenPlainJsonAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id,
                model_id,
                "third-party-compatible-model",
                adapter,
                {"structured_output": "strict_tool"},
                "a" * 64,
            )

    gateway = ModelGateway(db, Registry())
    contract = _message_contract()
    runtime = await execute_contract_runtime(
        gateway,
        role="planning",
        system="Return the complete business receipt.",
        user="The immutable task authority is already supplied.",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: (
                dict(value) if isinstance(value, dict) else None
            ),
            domain_validator=lambda payload: (
                payload
                if len(str(payload.get("message") or "")) >= 12
                else (_ for _ in ()).throw(ValueError("message incomplete"))
            ),
            retry_domain_failures=True,
        ),
        max_output_tokens=512,
        expected_output_characters=80,
        same_route_attempts=2,
        fallback_attempts=0,
    )

    assert runtime.payload["message"].startswith("完整业务回执")
    assert len(adapter.requests) == 2
    assert adapter.requests[0].required_tool == "interview_planning"
    assert adapter.requests[1].required_tool is None
    assert runtime.model_response.receipt["execution_mode"] == "plain"
    assert runtime.model_response.receipt["structured_mode_degraded"] is True

    strict_state = db.get_structured_route_qualification(
        provider_id="relay",
        model_id="model",
        route_fingerprint="a" * 64,
        execution_mode="strict_tool",
        contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    plain_state = db.get_structured_route_qualification(
        provider_id="relay",
        model_id="model",
        route_fingerprint="a" * 64,
        execution_mode="plain",
        contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    assert strict_state["status"] == "quarantined"
    assert strict_state["last_failure_reason"] == "empty_object"
    assert plain_state["status"] == "qualified"


def test_route_qualification_migration_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.migrate()

    assert "structured_route_qualifications" in db.table_names()


def test_route_identity_is_stable_across_probe_state_and_execution_mode(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="relay", name="relay", protocol="anthropic",
        base_url="https://relay.invalid/v1", auth_type="bearer",
        timeout_seconds=30, extra_headers={"X-Route": "stable"},
    )
    gateway = ModelGateway(db, object())
    before = ResolvedModel(
        "relay", "model", "third-party", object(),
        {"structured_output": "strict_tool", "capability_probe_status": "succeeded"},
    )
    after = ResolvedModel(
        "relay", "model", "third-party", object(),
        {"structured_output": "plain_text", "capability_probe_status": "stale"},
    )

    assert gateway._route_fingerprint(before, "strict_tool") == (
        gateway._route_fingerprint(after, "plain")
    )


async def test_native_protocol_rejection_degrades_before_replaying_business_task(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = NativeToolRejectedThenPlainJsonAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, "third-party", adapter,
                {"structured_output": "strict_tool"}, "b" * 64,
            )

    contract = _message_contract()
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            domain_validator=lambda payload: (
                payload if payload.get("message") else
                (_ for _ in ()).throw(ValueError("missing message"))
            ),
            retry_domain_failures=True,
        ),
        same_route_attempts=2, fallback_attempts=0,
    )

    assert result.model_response.receipt["execution_mode"] == "plain"
    assert len(adapter.requests) == 2
    assert adapter.requests[1].required_tool is None


async def test_primary_empty_native_and_plain_modes_use_independent_fallback(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "planning", "primary", "primary-model", "fallback", "fallback-model",
    )
    primary = AlwaysEmptyStructuredAdapter()
    fallback = ValidFallbackToolAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id,
                primary if provider_id == "primary" else fallback,
                {"structured_output": "strict_tool"},
                ("c" if provider_id == "primary" else "d") * 64,
            )

    contract = _message_contract()
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            domain_validator=lambda payload: (
                payload if payload.get("message") else
                (_ for _ in ()).throw(ValueError("missing message"))
            ),
            retry_domain_failures=True,
        ),
        same_route_attempts=2, fallback_attempts=1,
    )

    assert result.attempt.route == "configured_fallback"
    assert len(primary.requests) == 2
    assert len(fallback.requests) == 1
    assert result.payload["message"].startswith("独立备用路由")


async def test_all_empty_modes_raise_stable_business_incomplete_failure(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = AlwaysEmptyStructuredAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "e" * 64,
            )

    contract = _message_contract()
    with pytest.raises(
        ContractBusinessOutputIncompleteError,
    ) as caught:
        await execute_contract_runtime(
            ModelGateway(db, Registry()),
            role="planning", system="Return JSON", user="immutable task",
            execution_spec=ExecutableContractSpec(
                contract_name="interview_planning",
                structured_contract=contract,
                semantic_normalizer=lambda value: dict(value),
                domain_validator=lambda payload: (
                    payload if payload.get("message") else
                    (_ for _ in ()).throw(ValueError("missing message"))
                ),
                retry_domain_failures=True,
            ),
            same_route_attempts=2, fallback_attempts=0,
        )
    assert caught.value.reason == "empty_object"
    incident = classify_production_failure(
        str(caught.value), workflow="short-story", stage="review",
    )
    assert incident["incident_family"] == (
        "provider.structured_output_business_incomplete"
    )


async def test_output_limited_incomplete_native_mode_expands_and_recovers_plain(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = OutputLimitedStrictThenPlainJsonAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "1" * 64,
            )

    contract = _message_contract()
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            domain_validator=lambda payload: (
                payload if payload.get("message") else
                (_ for _ in ()).throw(ValueError("missing message"))
            ),
            retry_domain_failures=True,
        ),
        max_output_tokens=128, expected_output_characters=80,
        same_route_attempts=2, fallback_attempts=0,
    )

    assert result.model_response.receipt["execution_mode"] == "plain"
    assert adapter.requests[0].max_output_tokens == 128
    assert adapter.requests[1].max_output_tokens > 128


async def test_transport_interruption_retries_without_false_quarantine(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = InterruptedStrictThenCompleteAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "2" * 64,
            )

    contract = _message_contract()
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            domain_validator=lambda payload: payload,
        ),
        same_route_attempts=2, fallback_attempts=0,
    )

    assert len(adapter.requests) == 2
    assert result.model_response.receipt["execution_mode"] == "strict_tool"
    qualification = db.get_structured_route_qualification(
        provider_id="relay", model_id="model", route_fingerprint="2" * 64,
        execution_mode="strict_tool", contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    assert qualification["status"] == "qualified"


async def test_domain_valid_but_underfilled_output_is_recovered_before_acceptance(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = ShortButDomainValidThenCompleteAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "3" * 64,
            )

    contract = _message_contract()
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            # This intentionally weak validator proves that the shared Runtime
            # size gate runs before a caller can accidentally accept the shape.
            domain_validator=lambda payload: payload,
        ),
        expected_output_characters=400,
        same_route_attempts=2, fallback_attempts=0,
    )

    assert len(adapter.requests) == 2
    assert result.model_response.receipt["execution_mode"] == "plain"
    strict_state = db.get_structured_route_qualification(
        provider_id="relay", model_id="model", route_fingerprint="3" * 64,
        execution_mode="strict_tool", contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    assert strict_state["status"] == "quarantined"
    assert strict_state["last_failure_reason"] == "underfilled"


async def test_one_present_required_field_cannot_mask_partial_business_output(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "relay", "model", None, None)
    adapter = PartialRequiredThenCompleteAdapter()

    class Registry:
        @staticmethod
        def resolve(provider_id, model_id):
            return ResolvedModel(
                provider_id, model_id, model_id, adapter,
                {"structured_output": "strict_tool"}, "4" * 64,
            )

    contract = StructuredArtifactContract(
        name="interview_planning", version=1,
        schema={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["message", "evidence"],
            "additionalProperties": False,
        },
        runtime_authority={"task": "partial-required-regression"},
    )
    result = await execute_contract_runtime(
        ModelGateway(db, Registry()),
        role="planning", system="Return JSON", user="immutable task",
        execution_spec=ExecutableContractSpec(
            contract_name="interview_planning",
            structured_contract=contract,
            semantic_normalizer=lambda value: dict(value),
            domain_validator=lambda payload: payload,
        ),
        expected_output_characters=80,
        same_route_attempts=2, fallback_attempts=0,
    )

    assert result.payload["evidence"].startswith("已覆盖")
    strict_state = db.get_structured_route_qualification(
        provider_id="relay", model_id="model", route_fingerprint="4" * 64,
        execution_mode="strict_tool", contract_name="interview_planning",
        schema_sha256=contract.schema_sha256(),
    )
    assert strict_state["last_failure_reason"] == "required_fields_missing"


def test_production_fixture_is_sanitized_and_classifies_the_recurrence() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures"
        / "structured_business_output_empty_normal_finish_20260812.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    incident = classify_production_failure(
        fixture["terminal_message"],
        workflow=fixture["workflow"], stage=fixture["stage"],
    )
    assert incident["incident_family"] == fixture["incident_family"]
    serialized = fixture_path.read_text(encoding="utf-8").casefold()
    assert "api_key" not in serialized
    assert "provider_id" not in serialized


def test_protocol_only_reprobe_cannot_clear_business_quarantine(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(db, MemorySecretStore())
    client = TestClient(app)
    provider = client.post("/api/providers", json={
        "name": "relay",
        "protocol": "anthropic",
        "base_url": "https://relay.invalid/v1",
        "api_key": "secret",
    }).json()
    model = client.post(
        f"/api/providers/{provider['id']}/models",
        json={"display_name": "model", "model_name": "third-party"},
    ).json()
    resolved = app.state.registry.resolve(provider["id"], model["id"])
    db.save_structured_route_outcome(
        provider_id=provider["id"], model_id=model["id"],
        route_fingerprint=resolved.route_fingerprint,
        execution_mode="strict_tool", contract_name="interview_planning",
        schema_sha256="f" * 64, outcome="empty_object",
        failure_reason="empty_object",
    )

    async def protocol_only(_self, _model):
        return ProbeResult(
            chat=True,
            structured_output=False,
            tool_calling=True,
            forced_tool=True,
            structured_output_capability="plain_text",
            protocol_capability="strict_tool",
            qualification_status="protocol_only",
            verified_output_characters=0,
            qualification_schema_sha256="a" * 64,
        )

    monkeypatch.setattr(CapabilityProbe, "run", protocol_only)
    response = client.post(
        f"/api/providers/{provider['id']}/models/{model['id']}/probe",
    )

    assert response.status_code == 200
    stored_model = db.get_model(model["id"])
    assert stored_model["capabilities"]["structured_output"] == "plain_text"
    assert stored_model["capabilities"]["structured_output_qualification"] == (
        "protocol_only"
    )
    quarantine = db.get_structured_route_qualification(
        provider_id=provider["id"], model_id=model["id"],
        route_fingerprint=resolved.route_fingerprint,
        execution_mode="strict_tool", contract_name="interview_planning",
        schema_sha256="f" * 64,
    )
    assert quarantine["status"] == "quarantined"


def test_workflow_structured_contracts_have_business_anchored_wire_schemas() -> None:
    segment = registered_business_wire_schema(
        "planning_adaptation_segment",
        {"authority_sha256": "a" * 64},
    )
    assert segment["type"] == "object"
    assert segment["additionalProperties"] is False
    assert {
        "authority_sha256", "planning_sha256", "event_reviews", "summary",
    } <= set(segment["required"])
    assert segment != {"type": "object"}

    plan_variant = registered_business_wire_schema(
        "generated_narrative_artifact", {"deficit_han": 1200},
    )
    draft_variant = registered_business_wire_schema(
        "generated_narrative_artifact", {"scene_index": 1},
    )
    assert plan_variant["required"] == ["scenes"]
    assert "text" in draft_variant["required"]

    workflow_path = (
        Path(__file__).parents[1] / "src" / "novel_flywheel" / "workflows.py"
    )
    tree = ast.parse(workflow_path.read_text(encoding="utf-8"))
    literal_contracts = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name) else ""
        )
        if name != "_structured_stage_spec" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            literal_contracts.add(first.value)
    assert literal_contracts
    assert all(
        ARTIFACT_CONTRACT_REGISTRY[name].wire_required_fields
        or ARTIFACT_CONTRACT_REGISTRY[name].wire_variant_requirements
        for name in literal_contracts
    )


def test_authoritative_stage_wire_fields_match_the_real_domain_validators() -> None:
    expected = {
        "execution_manifest": {"beats", "segments"},
        "execution_manifest_receipt": {
            "authority_sha256", "manifest_sha256", "beat_receipts",
            "segment_receipts", "formal_plot_unchanged", "summary",
        },
        "draft_atomic_semantic_receipt": {
            "authority_sha256", "execution_manifest_sha256", "task_id",
            "prose_sha256", "beat_receipts", "entry", "exit",
            "outside_beat_ids", "future_beat_ids", "causal_order_valid",
            "causal_order_evidence", "summary",
        },
        "draft_segment_semantic_receipt": {
            "authority_sha256", "task_id", "prose_sha256", "event_receipts",
            "entry", "exit", "outside_event_ids", "causal_order_valid",
            "causal_order_evidence", "summary",
        },
        "draft_whole_semantic_receipt": {
            "authority_sha256", "draft_sha256", "segment_sha256", "event_ids",
            "missing_event_ids", "duplicate_event_ids", "out_of_order_event_ids",
            "causal_order_valid", "continuity_valid", "ending_valid",
            "commitments_valid", "evidence", "summary",
        },
        "draft_whole_window_receipt": {
            "authority_sha256", "draft_sha256", "segment_numbers",
            "segment_sha256", "event_ids", "missing_event_ids",
            "duplicate_event_ids", "out_of_order_event_ids",
            "causal_order_valid", "continuity_valid", "commitment_flow_valid",
            "ending_valid", "ending_evidence", "introduced_obligations",
            "resolved_within_window_obligations", "obligation_reconciliations",
            "evidence", "summary",
        },
        "draft_whole_reducer_receipt": {
            "authority_sha256", "draft_sha256", "segment_sha256", "event_ids",
            "missing_event_ids", "duplicate_event_ids", "out_of_order_event_ids",
            "causal_order_valid", "continuity_valid", "ending_valid",
            "commitments_valid", "evidence", "summary",
        },
        "final_review_window": {"summary", "issues"},
        "final_review_regional": {"summary", "issues"},
        "final_review_detail": {
            "events", "promises", "character_states", "timeline",
        },
        "reader_review": {
            "issues", "reader_signals",
        },
    }
    for contract_name, fields in expected.items():
        schema = registered_business_wire_schema(contract_name, {})
        assert set(schema["required"]) == fields
        assert fields <= set(schema["properties"])
        assert schema["additionalProperties"] is False
    reader_schema = registered_business_wire_schema("reader_review", {})
    assert {
        "dimensions", "score", "hard_fail", "decision",
    } <= set(reader_schema["properties"])

    manifest = registered_business_wire_schema("execution_manifest", {})
    assert "authority_sha256" not in manifest["required"]
    assert "segment" not in manifest["required"]
