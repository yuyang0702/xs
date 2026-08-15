from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.model_diagnostics import (
    BUDGET_LINEAGE_FLAG,
    DIAGNOSTIC_CANONICALIZATION_VERSION,
    STRICT_TOOL_FLAG,
    ModelDiagnosticContextV1,
    PlanningAdaptationOutputBudgetLineageV1,
    ProviderToolShapeSnapshotV1,
    StrictToolShapeObservationV1,
    adapter_manifest_sha256,
    attach_exception_snapshot,
    domain_sha256,
    exception_snapshot,
    is_strict_tool_target,
    sealed_payload,
    tool_call_shape,
)
from novel_flywheel.reliability_trace import BestEffortTraceSink
from novel_flywheel.runtime_fingerprint import FEATURE_FLAG_ENVIRONMENT_ALLOWLIST


HEX = "a" * 64


def provider_snapshot(*, count: int | None = 1, status: str = "snapshot_exact") -> dict:
    payload = {
        "schema": "ProviderToolShapeSnapshotV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "adapter_id": "anthropic",
        "adapter_version": 1,
        "adapter_manifest_sha256": adapter_manifest_sha256("anthropic", 1),
        "snapshot_status": status,
        "raw_content_block_count": count,
        "raw_tool_call_count": count,
        "raw_text_present": False,
        "raw_tool_use_present": bool(count),
        "tool_calls": [],
        "overflow_tool_call_count": 0,
    }
    return sealed_payload(
        payload, hash_field="snapshot_sha256", domain="r1-pa1-provider-snapshot-v1",
    )


def strict_observation(*, snapshot: dict | None = None, failure: str | None = None) -> dict:
    payload = {
        "schema": "StrictToolShapeObservationV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "shape_correlation_sha256": HEX,
        "run_sha256": HEX,
        "stage": "review",
        "boundary": "planning_adaptation_whole_receipt",
        "role": "review",
        "route_kind": "configured_fallback",
        "provider_alias": "controlled_provider",
        "model_alias": "controlled_model",
        "outer_retry_id": "outer-abc",
        "contract_runtime_instance_id": "runtime-abc",
        "attempt_id": "inner-abc",
        "parent_attempt_id": None,
        "expected_tool_contract": "planning_adaptation_whole",
        "expected_tool_contract_version": 1,
        "requested_expected_tool_id": "planning_adaptation_whole",
        "request_declared_tool_count": 1,
        "request_tool_manifest_sha256": HEX,
        "expected_tool_schema_sha256": HEX,
        "tool_choice_policy": "forced_exact_tool",
        "request_protocol": "anthropic",
        "adapter_version": 1,
        "adapter_manifest_sha256": adapter_manifest_sha256("anthropic", 1),
        "expected_tool_call_count": 1,
        "provider_shape": snapshot or provider_snapshot(),
        "normalized_tool_call_count": 1,
        "normalized_unique_tool_identity_count": 1,
        "normalized_tool_calls": [],
        "normalized_tool_call_id_hashes": [],
        "duplicate_call_id_count": 0,
        "duplicate_identity_count": 0,
        "adapter_projection_status": "exact",
        "gateway_matching_count": 1,
        "exact_expected_tool_match_count": 1,
        "observed_unique_tool_identity_count": 1,
        "unknown_tool_name_count": 0,
        "observed_registered_tool_ids": ["planning_adaptation_whole"],
        "unknown_tool_name_hashes": [],
        "content_block_count": 1,
        "text_content_present": False,
        "tool_use_content_present": True,
        "tool_arguments_present": True,
        "response_sha256": HEX,
        "finish_reason": "tool_use",
        "request_max_output_tokens": 1276,
        "strict_tool_decision": (
            "reject_current_uniqueness_rule" if failure else "accept_unique_expected"
        ),
        "strict_tool_failure_code": failure,
        "observation_status": "exact",
        "target_status": "target",
    }
    return sealed_payload(
        payload, hash_field="observation_sha256", domain="r1-pa1-strict-observation-v1",
    )


def test_strict_tool_schema_binds_request_provider_adapter_and_gateway_layers() -> None:
    value = StrictToolShapeObservationV1.model_validate(strict_observation())

    assert value.request_declared_tool_count == 1
    assert value.provider_shape.raw_tool_call_count == 1
    assert value.normalized_tool_call_count == 1
    assert value.gateway_matching_count == 1
    assert value.adapter_manifest_sha256 == value.provider_shape.adapter_manifest_sha256


def test_missing_snapshot_cannot_be_called_zero_tool_calls() -> None:
    snapshot = provider_snapshot(count=None, status="snapshot_unavailable")
    with pytest.raises(ValidationError, match="zero tool calls require"):
        StrictToolShapeObservationV1.model_validate(
            strict_observation(snapshot=snapshot, failure="zero_tool_calls")
        )


def test_exception_snapshot_attachment_preserves_original_exception_object() -> None:
    exc = ValueError("same-message")
    before = (type(exc), str(exc), exc.__cause__, exc.__context__)
    snapshot = ProviderToolShapeSnapshotV1.model_validate(provider_snapshot())

    attach_exception_snapshot(exc, snapshot)

    assert exception_snapshot(exc) is snapshot
    assert (type(exc), str(exc), exc.__cause__, exc.__context__) == before


def test_diagnostic_context_uses_stable_logical_identity_and_target_filter(tmp_path) -> None:
    context = ModelDiagnosticContextV1(
        project_root=tmp_path,
        run_id="run-controlled",
        stage="review",
        boundary="planning_adaptation_whole_receipt",
        role="review",
        route_kind="configured_fallback",
        contract_id="planning_adaptation_whole",
        contract_version=1,
        outer_retry_ordinal=2,
    )
    duplicate = ModelDiagnosticContextV1(**context.__dict__)

    assert context.runtime_instance_id == duplicate.runtime_instance_id
    assert "0x" not in context.runtime_instance_id
    assert is_strict_tool_target(context) is True
    assert is_strict_tool_target(ModelDiagnosticContextV1(
        **{**context.__dict__, "boundary": "planning_adaptation_segment"}
    )) is False


def test_diagnostic_events_are_additive_to_phase0_envelope() -> None:
    strict = strict_observation()
    envelope = ReliabilityTraceEnvelopeV1.model_validate({
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": "event-diagnostic-0001",
        "correlation_id": "correlation",
        "event_type": "diagnostic_strict_tool_shape",
        "source_component": "ModelGateway",
        "source_writer": "StrictToolObserver",
        "observation_status": "confirmed",
        "payload": strict,
    })

    assert envelope.event_type == "diagnostic_strict_tool_shape"


def test_best_effort_sink_rejects_private_fields_without_raising(tmp_path) -> None:
    strict = strict_observation()
    strict["prompt"] = "forbidden"
    envelope = ReliabilityTraceEnvelopeV1.model_construct(
        schema_name="ReliabilityTraceEnvelopeV1",
        event_id="event-diagnostic-0002",
        correlation_id="correlation",
        sequence=1,
        event_type="diagnostic_strict_tool_shape",
        source_component="ModelGateway",
        source_writer="StrictToolObserver",
        semantic_domain="unknown",
        observation_status="confirmed",
        payload=strict,
    )
    sink = BestEffortTraceSink(tmp_path / "trace.jsonl", enabled=True)

    assert sink.emit(envelope) is False
    assert sink.metrics.dropped == 1
    assert not sink.path.exists()


def test_budget_lineage_schema_records_cap_before_and_after_values() -> None:
    payload = {
        "schema": "PlanningAdaptationOutputBudgetLineageV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "lineage_event": "expansion_decided",
        "run_sha256": HEX,
        "stage": "review",
        "boundary": "planning_adaptation_whole_receipt",
        "role": "review",
        "contract_id": "planning_adaptation_whole",
        "contract_version": 1,
        "outer_retry_id": "outer-abc",
        "contract_runtime_instance_id": "runtime-abc",
        "inner_attempt_id": "inner-abc",
        "original_requested_output_budget": 1276,
        "current_requested_output_budget": 1276,
        "previous_attempt_budget": 1276,
        "expansion_policy": "context_policy.expanded_output_budget",
        "expansion_policy_version": 1,
        "expansion_trigger": "output_limit",
        "expansion_requested": True,
        "expansion_target": 2552,
        "expansion_target_before_cap": 2552,
        "effective_budget_after_policy": 2552,
        "effective_budget_after_provider_cap": 2552,
        "effective_budget_after_canary_cap": 2552,
        "expansion_applied": False,
        "retained_expansion_state": False,
        "runtime_reconstructed": False,
        "retry_owner": "contract_runtime_inner",
        "route_kind": "primary",
        "finish_reason": "max_tokens",
        "typed_failure": "output_limit",
        "cap_applied": False,
        "cap_source": "none",
        "provider_limit_status": "unknown",
        "request_parameter_name": "max_output_tokens",
        "prompt_system_sha256": HEX,
        "prompt_user_sha256": HEX,
        "contract_sha256": HEX,
        "provider_binding_sha256": HEX,
        "model_binding_sha256": HEX,
    }
    sealed = sealed_payload(
        payload, hash_field="lineage_receipt_sha256", domain="r1-pa1-budget-lineage-v1",
    )
    value = PlanningAdaptationOutputBudgetLineageV1.model_validate(sealed)

    assert value.expansion_target_before_cap == 2552
    assert value.effective_budget_after_provider_cap == 2552
    assert value.expansion_applied is False


def test_diagnostic_flags_are_registered_and_default_off(monkeypatch) -> None:
    monkeypatch.delenv(STRICT_TOOL_FLAG, raising=False)
    monkeypatch.delenv(BUDGET_LINEAGE_FLAG, raising=False)

    assert STRICT_TOOL_FLAG in FEATURE_FLAG_ENVIRONMENT_ALLOWLIST
    assert BUDGET_LINEAGE_FLAG in FEATURE_FLAG_ENVIRONMENT_ALLOWLIST
    assert os.environ.get(STRICT_TOOL_FLAG, "0") == "0"
    assert os.environ.get(BUDGET_LINEAGE_FLAG, "0") == "0"


def test_tool_call_shape_never_retains_unknown_name_or_arguments() -> None:
    shape = tool_call_shape(
        ordinal=0,
        name="private-unknown-name",
        call_id="provider-call-id",
        arguments={"private": "value"},
        arguments_present=True,
        expected_registered_tool="planning_adaptation_whole",
    )
    serialized = shape.model_dump_json()

    assert "private-unknown-name" not in serialized
    assert "provider-call-id" not in serialized
    assert '"value"' not in serialized
    assert shape.unknown_tool_name_sha256 == domain_sha256(
        "r1-pa1-unknown-tool-name-v1", "private-unknown-name"
    )
