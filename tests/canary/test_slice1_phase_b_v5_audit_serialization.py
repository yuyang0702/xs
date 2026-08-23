from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ProviderOutputShapeV1
from novel_flywheel.generated_artifacts import ArtifactConversionAudit
from novel_flywheel.models import ModelGateway
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    normalize_event_realization_input_authority_v1,
)
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputRequirement,
)
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_v4_single_dispatch as v4
import tools.canary.slice1_phase_b_v5_single_dispatch as launcher


ROOT = Path(__file__).resolve().parents[2]
V4_SOURCE_SHA256 = "14f85ab316d620ad453955ed316aca9924bbe777b0c3417829c6596fdbf648a8"


class _StaticReasoningAndTextAdapter:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = 0

    async def complete(self, _request):
        self.calls += 1
        return self.response


class _StaticRegistry:
    def __init__(self, adapter: _StaticReasoningAndTextAdapter) -> None:
        self.adapter = adapter

    def resolve(self, provider_id: str, model_id: str) -> ResolvedModel:
        return ResolvedModel(
            provider_id,
            model_id,
            model_id,
            self.adapter,
            {"structured_output": "strict_json_schema"},
            "7" * 64,
        )


def _audit() -> ArtifactConversionAudit:
    return ArtifactConversionAudit(
        contract_name="planning_event_realization_shadow_v1",
        contract_version=1,
        raw_sha256="1" * 64,
        canonical_sha256="2" * 64,
        method="exact_json",
        transformations=("extract_json", "validate_candidate"),
        quarantined_paths=("$.unused",),
        candidate_count=1,
        semantic_valid=True,
        failure_code="",
    )


def test_exact_pydantic_audit_serializer_preserves_fields_and_is_deterministic() -> None:
    first = launcher.serialize_artifact_conversion_audit_v1(_audit())
    second = launcher.serialize_artifact_conversion_audit_v1(_audit())

    assert tuple(first) == launcher.ARTIFACT_CONVERSION_AUDIT_FIELDS
    assert set(first) == set(ArtifactConversionAudit.model_fields)
    assert first["transformations"] == ["extract_json", "validate_candidate"]
    assert first["quarantined_paths"] == ["$.unused"]
    assert json.loads(json.dumps(first, sort_keys=True)) == first
    assert launcher._canonical_bytes(first) == launcher._canonical_bytes(second)
    assert launcher._domain_sha("audit-test-v1", first) == launcher._domain_sha(
        "audit-test-v1", second
    )


def test_exact_pydantic_audit_serializer_preserves_defaults() -> None:
    audit = ArtifactConversionAudit(
        contract_name="planning_event_realization_shadow_v1",
        contract_version=1,
        raw_sha256="3" * 64,
        method="rejected",
    )
    payload = launcher.serialize_artifact_conversion_audit_v1(audit)

    assert payload["canonical_sha256"] == ""
    assert payload["transformations"] == []
    assert payload["quarantined_paths"] == []
    assert payload["candidate_count"] == 0
    assert payload["semantic_valid"] is False
    assert payload["failure_code"] == ""


def test_exact_pydantic_audit_serializer_rejects_wrong_boundary_type() -> None:
    with pytest.raises(launcher.Slice1PhaseBV5LauncherError) as caught:
        launcher.serialize_artifact_conversion_audit_v1({})  # type: ignore[arg-type]
    assert caught.value.reason_code == "artifact_conversion_audit_type_mismatch"


@pytest.mark.asyncio
async def test_reasoning_visible_final_runs_complete_v5_local_success_tail(
    tmp_path: Path,
) -> None:
    synthetic_final = json.dumps(
        {
            "title": "Synthetic crossing",
            "narrative": (
                "The synthetic actor makes a clear choice, meets resistance, "
                "and preserves the required consequence for the next event."
            ),
        }
    )
    shape = ProviderOutputShapeV1(
        provider_family="deterministic_fake",
        protocol="offline",
        finish_reason="end_turn",
        output_tokens=120,
        content_block_count=2,
        content_block_type_sequence=("thinking", "text"),
        text_block_count=1,
        provider_visible_text_chars=len(synthetic_final),
        tool_call_count=0,
        reasoning_block_count=1,
        unknown_block_count=0,
        transport_complete=True,
        normalized_visible_text_chars=len(synthetic_final),
        normalized_tool_call_count=0,
        adapter_projection_status="exact",
        shape_sha256="8" * 64,
    )
    response = ModelResponse(
        text=synthetic_final,
        finish_reason="end_turn",
        output_tokens=120,
        provider_state={
            "content": (
                {"type": "thinking", "thinking": "synthetic reasoning"},
                {"type": "text", "text": synthetic_final},
            ),
            "transport_complete": True,
        },
        output_shape=shape,
    )
    adapter = _StaticReasoningAndTextAdapter(response)
    database = Database(tmp_path / "app.db")
    database.migrate()
    database.save_role_binding("planning", "primary", "model", None, None)
    gateway = ModelGateway(database, _StaticRegistry(adapter))
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"synthetic_topology_only": True},
    )

    result = await gateway.complete_route(
        "primary",
        "planning",
        "synthetic system",
        "synthetic user",
        max_output_tokens=4624,
        contract=contract,
        structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
    )
    _, authority_value = base.load_fixture_binding(ROOT)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value)
    )
    run_root = tmp_path / "success-tail"
    run_root.mkdir()
    receipt = launcher.persist_success_tail_v1(
        result=result,
        authority=authority,
        attempts={
            "model_logical_calls": 0,
            "http_post_attempts": 0,
            "real_provider_request_attempts": 0,
            "network_request_attempts": 0,
        },
        run_root=run_root,
    )

    assert adapter.calls == 1
    assert response.output_shape is not None
    assert response.output_shape.reasoning_block_count == 1
    assert response.output_shape.provider_visible_text_chars > 0
    assert receipt["local_terminal"] == "PASS"
    assert receipt["validator_status"] == "PASS"
    assert receipt["freeze_state"] == "FROZEN"
    assert receipt["audit_serialization"] == "PASS"
    assert receipt["write_json_reached"] is True
    assert receipt["artifact_persisted"] is True
    assert receipt["quality_capture"]["semantic_valid"] is True
    assert receipt["engineering_metrics"]["artifact_count"] == 1
    assert (run_root / "artifact/generated-event-realization-v1.json").is_file()
    assert (run_root / "evidence/local-success-receipt-v1.json").is_file()
    persisted = (run_root / "artifact/generated-event-realization-v1.json").read_text(
        encoding="utf-8"
    )
    assert "synthetic reasoning" not in persisted
    assert "raw_response" not in persisted
    source = inspect.getsource(launcher.execute_authorized_once)
    assert "persist_success_tail_v1" in source
    assert "asdict(conversion)" not in source


def test_v4_launcher_and_sealed_packet_remain_byte_exact() -> None:
    v4_path = ROOT / "tools/canary/slice1_phase_b_v4_single_dispatch.py"
    assert hashlib.sha256(v4_path.read_bytes()).hexdigest() == V4_SOURCE_SHA256
    packet_root = ROOT / v4.MATERIALIZATION_RELATIVE_ROOT
    manifest = v4._verify_manifest(ROOT, packet_root)
    assert manifest["overall_status"] == "exact"


def test_v5_profile_scope_roots_and_transport_are_closed_world() -> None:
    profile = launcher.packet_profile()
    assert profile["approval_scope"] == launcher.APPROVAL_SCOPE
    assert profile["cohort_id"] == launcher.COHORT_ID
    assert profile["materialization_relative_root"] == (
        launcher.MATERIALIZATION_RELATIVE_ROOT
    )
    assert profile["execution_relative_root"] == launcher.EXECUTION_RELATIVE_ROOT
    assert profile["arbitrary_scope_acceptance"] is False
    assert profile["arbitrary_cohort_acceptance"] is False
    guard = launcher.transport_guard_contract(ROOT)
    assert guard["max_http_post_attempts"] == 1
    assert guard["max_real_provider_request_attempts"] == 1
    assert guard["application_second_dispatch_allowed"] is False
