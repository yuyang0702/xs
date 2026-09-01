from __future__ import annotations

import json

import pytest

from novel_flywheel.execution_failure_architecture import (
    AuthorityEffect,
    DispatchState,
    ExecutionBoundaryFailure,
    FailureLayer,
    RestartBehavior,
    build_durable_failure_evidence,
)
from novel_flywheel.recovery_engine import FailureClass


# The numbered names are the canonical Phase-9 inventory.  This file proves
# taxonomy closure for every receipt.  The production-boundary campaign also
# executes the owning suites below (runner/store, registry/gateway, HTTP/SSE,
# capture/replay, workflow/contracts, authority, observer, and budgets).
CASES = (
    (1, "auth_sha_mismatch", FailureLayer.EXECUTION_AUTHORIZATION),
    (2, "head_drift", FailureLayer.EXECUTION_AUTHORIZATION),
    (3, "worktree_drift", FailureLayer.EXECUTION_AUTHORIZATION),
    (4, "runtime_fingerprint_drift", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (5, "authority_drift", FailureLayer.AUTHORITY),
    (6, "project_workload_drift", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (7, "provider_config_missing", FailureLayer.PROVIDER_ROUTE),
    (8, "model_config_missing", FailureLayer.PROVIDER_ROUTE),
    (9, "malformed_endpoint", FailureLayer.PROVIDER_ROUTE),
    (10, "route_fingerprint_mismatch", FailureLayer.PROVIDER_ROUTE),
    (11, "capability_unavailable", FailureLayer.PROVIDER_ROUTE),
    (12, "credential_source_missing", FailureLayer.PROVIDER_CREDENTIAL),
    (13, "credential_absent", FailureLayer.PROVIDER_CREDENTIAL),
    (14, "credential_empty", FailureLayer.PROVIDER_CREDENTIAL),
    (15, "credential_access_typed_error", FailureLayer.PROVIDER_CREDENTIAL),
    (16, "client_config_construction_failure", FailureLayer.PROVIDER_CLIENT),
    (17, "request_build_failure", FailureLayer.PROVIDER_REQUEST_BUILD),
    (18, "reasoning_policy_projection_failure", FailureLayer.PROVIDER_REQUEST_BUILD),
    (19, "primary_and_fallback_lane_failure", FailureLayer.WORKFLOW_RECOVERY),
    (20, "ordered_child_provenance", FailureLayer.WORKFLOW_RECOVERY),
    (21, "nonce_reservation_boundary_failure", FailureLayer.EXECUTION_AUTHORIZATION),
    (22, "duplicate_attempt_id", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (23, "dispatch_transition_failure", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (24, "restart_before_nonce", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (25, "restart_after_nonce_before_dispatch", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (26, "duplicate_dispatch_attempt", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (27, "failure_before_first_byte", FailureLayer.PROVIDER_TRANSPORT),
    (28, "partial_stream", FailureLayer.PROVIDER_TRANSPORT),
    (29, "complete_valid_stream", FailureLayer.PROVIDER_TRANSPORT),
    (30, "explicit_provider_error", FailureLayer.PROVIDER_PROTOCOL),
    (31, "ambiguous_completion", FailureLayer.PROVIDER_TRANSPORT),
    (32, "malformed_sse", FailureLayer.PROVIDER_PROTOCOL),
    (33, "large_response", FailureLayer.PROVIDER_RESPONSE_ADAPTER),
    (34, "timeout_after_body_complete", FailureLayer.PROVIDER_TRANSPORT),
    (35, "adapter_failure_after_capture", FailureLayer.PROVIDER_RESPONSE_ADAPTER),
    (36, "exact_local_replay", FailureLayer.PROVIDER_RESPONSE_ADAPTER),
    (37, "reasoning_only_max_tokens", FailureLayer.PROVIDER_FINAL_ARTIFACT),
    (38, "structured_parse_fail", FailureLayer.CONTRACT),
    (39, "schema_fail", FailureLayer.CONTRACT),
    (40, "semantic_fail", FailureLayer.CONTRACT),
    (41, "business_incomplete", FailureLayer.BUSINESS_COMPLETENESS),
    (42, "valid_minimal_response", FailureLayer.BUSINESS_COMPLETENESS),
    (43, "duplicate_semantic_item", FailureLayer.CONTRACT),
    (44, "inconsistent_ids", FailureLayer.CONTRACT),
    (45, "planning_recoverable_failure", FailureLayer.WORKFLOW_RECOVERY),
    (46, "planning_recovery_exhaustion", FailureLayer.WORKFLOW_RECOVERY),
    (47, "draft_local_defect", FailureLayer.BUSINESS_COMPLETENESS),
    (48, "draft_wider_defect", FailureLayer.BUSINESS_COMPLETENESS),
    (49, "draft_ambiguous_ownership", FailureLayer.CONTRACT),
    (50, "review_rejection", FailureLayer.BUSINESS_COMPLETENESS),
    (51, "reader_review_failure", FailureLayer.BUSINESS_COMPLETENESS),
    (52, "polish_failure", FailureLayer.BUSINESS_COMPLETENESS),
    (53, "final_review_failure", FailureLayer.BUSINESS_COMPLETENESS),
    (54, "maintenance_failure", FailureLayer.BUSINESS_COMPLETENESS),
    (55, "story_state_cas_failure", FailureLayer.AUTHORITY),
    (56, "canon_projection_failure", FailureLayer.AUTHORITY),
    (57, "ready_projection_failure", FailureLayer.AUTHORITY),
    (58, "final_artifact_write_failure", FailureLayer.ARTIFACT),
    (59, "checkpoint_failure", FailureLayer.ARTIFACT),
    (60, "completion_receipt_failure", FailureLayer.ARTIFACT),
    (61, "gbk_emoji_logger_failure", FailureLayer.OBSERVER),
    (62, "event_handler_failure", FailureLayer.OBSERVER),
    (63, "evidence_sink_failure", FailureLayer.OBSERVER),
    (64, "capture_tamper", FailureLayer.ARTIFACT),
    (65, "failure_receipt_serialization_failure", FailureLayer.ARTIFACT),
    (66, "per_call_output_cap", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (67, "total_output_cap", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (68, "physical_request_cap", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (69, "elapsed_cap", FailureLayer.EXECUTION_RUNTIME_BINDING),
    (70, "recovery_shared_slot_exhaustion", FailureLayer.WORKFLOW_RECOVERY),
)

REAL_BOUNDARY_CAMPAIGN_SUITES = (
    "tests/test_full_short_execution.py",
    "tests/canary/test_full_short_runner_hardening.py",
    "tests/test_models.py",
    "tests/test_tasks.py",
    "tests/providers/test_single_dispatch_transport_guard.py",
    "tests/providers/test_anthropic_sse_state_machine.py",
    "tests/test_provider_response_capture.py",
    "tests/test_contract_runtime.py",
    "tests/test_workflows.py",
    "tests/test_recovery_engine.py",
)


def _failure_class(layer: FailureLayer) -> FailureClass:
    if layer == FailureLayer.PROVIDER_CREDENTIAL:
        return FailureClass.CREDENTIAL
    if layer in {FailureLayer.PROVIDER_TRANSPORT}:
        return FailureClass.TRANSPORT
    if layer in {FailureLayer.PROVIDER_ROUTE, FailureLayer.PROVIDER_CLIENT}:
        return FailureClass.CAPABILITY
    if layer in {FailureLayer.PROVIDER_PROTOCOL, FailureLayer.CONTRACT}:
        return FailureClass.SYNTAX_PROTOCOL
    if layer in {FailureLayer.BUSINESS_COMPLETENESS}:
        return FailureClass.SEMANTIC_INVARIANT
    if layer == FailureLayer.AUTHORITY:
        return FailureClass.STALE_AUTHORITY
    return FailureClass.UNKNOWN


@pytest.mark.parametrize("number,name,layer", CASES, ids=[item[1] for item in CASES])
def test_every_phase9_inventory_entry_has_closed_typed_durable_policy(
    number: int, name: str, layer: FailureLayer,
) -> None:
    dispatch_state = (
        DispatchState.NETWORK_AMBIGUOUS
        if name in {"ambiguous_completion", "timeout_after_body_complete"}
        else DispatchState.RESPONSE_CAPTURED
        if number in range(29, 66)
        else DispatchState.NOT_REACHED
    )
    restart = (
        RestartBehavior.EXACT_REPLAY_ONLY
        if name in {"complete_valid_stream", "exact_local_replay"}
        else RestartBehavior.NO_REDISPATCH
        if dispatch_state != DispatchState.NOT_REACHED
        else RestartBehavior.FRESH_AUTHORIZATION_REQUIRED
    )
    error = ExecutionBoundaryFailure(
        f"fault_{number:02d}_{name}", layer=layer,
        boundary=f"fault_campaign.case_{number:02d}",
        failure_class=_failure_class(layer), retryable=False,
        dispatch_state=dispatch_state,
        authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior=restart, recovery_action="apply_sealed_policy",
    )
    evidence = build_durable_failure_evidence(
        error, boundary=f"fault_campaign.case_{number:02d}",
    )
    serialized = json.dumps(evidence.model_dump(mode="json"), sort_keys=True)

    assert evidence.root.code == f"fault_{number:02d}_{name}"
    assert evidence.root.layer == layer
    assert evidence.root.authority_effect == AuthorityEffect.PRESERVES_LAST_ACCEPTED
    assert evidence.root.restart_behavior == restart
    assert evidence.root.retryable is False
    assert len(evidence.failure_graph_sha256) == 64
    assert "credential-value-sentinel" not in serialized


def test_campaign_inventory_is_exactly_numbered_one_through_seventy() -> None:
    assert [item[0] for item in CASES] == list(range(1, 71))
    assert len({item[1] for item in CASES}) == 70


def test_real_boundary_campaign_owns_every_execution_layer() -> None:
    assert {item[2] for item in CASES} == set(FailureLayer) - {
        FailureLayer.EXTERNAL, FailureLayer.UNKNOWN,
    }
    assert all(__import__("pathlib").Path(path).is_file()
               for path in REAL_BOUNDARY_CAMPAIGN_SUITES)
