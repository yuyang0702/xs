from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from novel_flywheel.execution_failure_architecture import FailureLayer


_NAMES_AND_LAYERS = (
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
    (19, "primary_and_fallback_lane_failure", FailureLayer.PROVIDER_ROUTE),
    (20, "ordered_child_provenance", FailureLayer.PROVIDER_ROUTE),
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


_BEHAVIORAL_TESTS = {
    1: "tests/test_full_short_execution.py::test_canonical_authorization_and_disabled_preflight_are_exact",
    2: "tests/test_full_short_execution.py::test_post_authorization_head_drift_fails_before_external_actions",
    3: "tests/test_full_short_execution.py::test_every_immutable_preflight_drift_fails_closed",
    4: "tests/canary/test_full_short_runner_hardening.py::test_live_bindings_seal_v2_runtime_skill_style_and_store_source_truth",
    5: "tests/test_full_short_execution.py::test_live_authority_drift_fails_before_credential_lookup_or_nonce_consumption",
    6: "tests/test_full_short_execution.py::test_every_immutable_preflight_drift_fails_closed",
    7: "tests/test_full_short_execution.py::test_invalid_public_route_identity_never_crosses_credential_boundary",
    8: "tests/test_full_short_execution.py::test_invalid_public_route_identity_never_crosses_credential_boundary",
    9: "tests/api/test_providers.py::test_update_provider_rejects_invalid_url",
    10: "tests/test_full_short_execution.py::test_exact_pre_dispatch_route_rebind_is_idempotent_but_drift_fails",
    11: "tests/test_final_artifact_guard.py::test_negative_capability_prevents_second_provider_dispatch",
    12: "tests/test_full_short_execution.py::test_predispatch_credential_failure_leaves_nonce_absent",
    13: "tests/test_full_short_execution.py::test_predispatch_credential_failure_leaves_nonce_absent",
    14: "tests/test_full_short_execution.py::test_predispatch_credential_failure_leaves_nonce_absent",
    15: "tests/test_full_short_execution.py::test_predispatch_credential_failure_leaves_nonce_absent",
    16: "tests/canary/test_c0b_budget_boundary.py::test_credential_client_and_network_follow_final_authorization",
    17: "tests/providers/test_single_dispatch_transport_guard.py::test_request_materialization_failure_precedes_dispatch_authority",
    18: "tests/test_full_short_execution.py::test_egress_model_request_content_is_exactly_bound",
    19: "tests/test_models.py::test_gateway_preserves_both_route_errors_when_primary_and_fallback_keys_are_missing",
    20: "tests/test_models.py::test_routes_exhausted_names_errors_without_provider_detail",
    21: "tests/test_full_short_execution.py::test_predispatch_local_failure_leaves_nonce_absent",
    22: "tests/test_full_short_execution.py::test_nonce_is_consumed_before_first_dispatch_and_duplicate_is_blocked",
    23: "tests/test_full_short_execution.py::test_durable_ledger_rejects_reopening_closed_attempt",
    24: "tests/test_full_short_execution.py::test_restart_before_dispatch_is_also_fail_closed",
    25: "tests/test_full_short_execution.py::test_crash_between_lazy_nonce_and_ledger_commit_is_terminal_no_redispatch",
    26: "tests/test_full_short_execution.py::test_nonce_is_consumed_before_first_dispatch_and_duplicate_is_blocked",
    27: "tests/canary/test_full_short_runner_hardening.py::test_production_transport_failure_injection_is_one_dispatch",
    28: "tests/test_full_short_execution.py::test_partial_capture_remains_ambiguous_transport_failure",
    29: "tests/providers/test_single_dispatch_transport_guard.py::test_guarded_success_records_exactly_one_http_attempt",
    30: "tests/providers/test_anthropic_sse_state_machine.py::test_explicit_provider_error_before_content_is_not_transport",
    31: "tests/test_full_short_execution.py::test_restart_after_dispatch_before_local_receipt_never_redispatches",
    32: "tests/providers/test_single_dispatch_transport_guard.py::test_guarded_malformed_sse_never_dispatches_twice",
    33: "tests/test_provider_response_capture.py::test_exact_capture_replay_preserves_every_byte",
    34: "tests/providers/test_anthropic_sse_state_machine.py::test_terminal_bytes_recover_iterator_failure_by_exact_local_replay",
    35: "tests/canary/test_full_short_runner_hardening.py::test_dry_run_adapter_fault_is_one_local_projection_only",
    36: "tests/test_full_short_execution.py::test_restart_read_only_replay_uses_exact_ledger_anchored_capture",
    37: "tests/test_final_artifact_guard.py::test_reasoning_only_max_tokens_is_typed_before_parser_and_remembered",
    38: "tests/test_contract_runtime.py::test_contract_runtime_retries_original_task_when_no_semantics_exist",
    39: "tests/test_contract_runtime.py::test_runtime_rejects_wire_schema_version_drift_before_model_call",
    40: "tests/test_contract_runtime.py::test_contract_runtime_never_rewrites_domain_semantic_failure",
    41: "tests/test_full_short_business_contract_alignment.py::test_reader_review_rejects_structured_but_business_incomplete",
    42: "tests/test_full_short_business_contract_alignment.py::test_reader_review_complete_contract_normalizes_score",
    43: "tests/test_workflows.py::test_short_plan_gate_rejects_extra_duplicate_or_reordered_segment_headings",
    44: "tests/test_workflows.py::test_short_plan_parser_rejects_ambiguous_event_array_variants",
    45: "tests/test_workflows.py::test_local_planning_recovery_merges_only_the_segment_needed_for_improvement",
    46: "tests/test_full_short_execution.py::test_two_rejections_exhaust_shared_logical_stage_physical_ceiling",
    47: "tests/test_workflows.py::test_draft_findings_make_same_root_location_change_nonblocking",
    48: "tests/test_workflows.py::test_draft_findings_keep_underlength_blocking_without_guessing_unknown_locations",
    49: "tests/test_workflows.py::test_short_plan_event_role_keeps_two_realizations_ambiguous",
    50: "tests/test_full_short_business_contract_alignment.py::test_full_short_final_review_rejects_legacy_score_only_shell",
    51: "tests/test_full_short_business_contract_alignment.py::test_reader_review_rejects_structured_but_business_incomplete",
    52: "tests/test_workflows.py::test_polish_semantic_drift_is_repaired_before_source_fallback",
    53: "tests/test_full_short_business_contract_alignment.py::test_full_short_final_review_rejects_legacy_score_only_shell",
    54: "tests/test_full_short_business_contract_alignment.py::test_maintenance_rejects_structured_but_business_incomplete",
    55: "tests/test_workflows.py::test_maintenance_authority_is_incremental_and_conflicts_fail_closed",
    56: "tests/test_workflows.py::test_interrupted_formal_promotion_rolls_back_when_story_state_not_committed",
    57: "tests/canary/test_full_short_runner_hardening.py::test_live_bindings_reject_missing_ready_authority",
    58: "tests/api/test_revisions.py::test_group_decision_write_failure_restores_all_repair_artifacts",
    59: "tests/api/test_revisions.py::test_finalize_quality_checkpoint_failure_rolls_back_and_can_retry",
    60: "tests/test_full_short_execution.py::test_completion_rejects_terminal_false_positive_and_binding_key_drift",
    61: "tests/test_execution_failure_architecture.py::test_gbk_console_emoji_failure_is_contained_as_diagnostic_only",
    62: "tests/providers/test_single_dispatch_transport_guard.py::test_observer_failure_after_response_never_dispatches_twice",
    63: "tests/test_workflows.py::test_snapshot_recovery_failure_is_logged_without_replacing_primary_error",
    64: "tests/test_provider_response_capture.py::test_tampered_bytes_fail_before_replay",
    65: "tests/test_hybrid_skill_context.py::test_receipt_serialization_and_unexpected_exception_are_bounded",
    66: "tests/test_workflows.py::test_output_budget_uses_each_selected_route_model_ceiling",
    67: "tests/test_full_short_execution.py::test_total_requested_output_cap_is_enforced_before_second_dispatch",
    68: "tests/test_full_short_execution.py::test_new_logical_stage_over_cap_is_rejected_before_dispatch",
    69: "tests/canary/test_full_short_runner_hardening.py::test_completion_elapsed_is_rechecked_after_last_dispatch",
    70: "tests/test_full_short_execution.py::test_two_rejections_exhaust_shared_logical_stage_physical_ceiling",
}


def _source_binding(number: int) -> tuple[str, str]:
    if number <= 6:
        return "tools/canary/first_trustworthy_full_short_runner.py", "execute_full_short_control_plane"
    if number <= 20:
        return "src/novel_flywheel/models.py", "ModelGateway"
    if number <= 26:
        return "src/novel_flywheel/full_short_execution.py", "FullShortDurableExecutionStoreV1"
    if number <= 36:
        return "src/novel_flywheel/providers/http.py", "HttpProvider"
    if number <= 44:
        return "src/novel_flywheel/contract_runtime.py", "execute_contract_runtime"
    if number <= 57:
        return "src/novel_flywheel/workflows.py", "WorkflowService"
    if number <= 60:
        return "src/novel_flywheel/full_short_execution.py", "build_full_short_completion_receipt_v1"
    if number <= 65:
        return "src/novel_flywheel/execution_failure_architecture.py", "ObserverGuard"
    return "src/novel_flywheel/full_short_execution.py", "FullShortDispatchLedgerObserverV1"


def _case(number: int, name: str, layer: FailureLayer) -> dict[str, object]:
    source, detection_point = _source_binding(number)
    success_case = number in {29, 42}
    recoverable = number in {34, 36, 37, 45}
    replayable = number in {29, 33, 34, 36, 42}
    return {
        "failure_id": f"FI-{number:02d}", "number": number, "name": name,
        "layer": layer.value, "source": source,
        "detection_point": detection_point, "local_knowable": number <= 26,
        "secret_required": number in range(12, 17),
        "network_required": number in range(27, 37),
        "typed_code": "success.accepted" if success_case else f"fault.{name}",
        "child_provenance": "ordered" if number in {19, 20} else "not_composite",
        "durable_receipt": True, "replayable": replayable,
        "recoverable": recoverable, "max_recovery": 1 if recoverable else 0,
        "restart_behavior": "exact_replay_only" if replayable else "no_redispatch",
        "authority_effect": "preserve_last_accepted",
        "behavioral_test": _BEHAVIORAL_TESTS[number], "status": "MAPPED",
        "expected_outcome": "SUCCESS" if success_case else "TYPED_FAILURE",
    }


PHASE9_FAULT_CASES = tuple(_case(*item) for item in _NAMES_AND_LAYERS)


def _defined_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.fixture(scope="session")
def fault_campaign_junit(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    repo = Path.cwd()
    source_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, encoding="utf-8",
    ).strip()
    junit = tmp_path_factory.mktemp("phase9-real-boundaries") / "behavioral.xml"
    nodeids = sorted({str(case["behavioral_test"]) for case in PHASE9_FAULT_CASES})
    env = {
        **os.environ,
        "NOVEL_FLYWHEEL_EXTERNAL_ACTIONS_DISABLED": "1",
        "NO_PROXY": "*",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *nodeids],
        cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    assert completed.returncode == 0, (completed.stdout or "") + (completed.stderr or "")
    tree = ET.parse(junit)
    testcase = [
        str(node.attrib.get("name") or "") for node in tree.iter("testcase")
    ]
    assert testcase
    return {
        "source_head": source_head, "path": junit, "testcase": testcase,
        "sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
    }


def test_phase9_campaign_catalog_is_source_bound() -> None:
    assert [case["number"] for case in PHASE9_FAULT_CASES] == list(range(1, 71))
    assert len({case["name"] for case in PHASE9_FAULT_CASES}) == 70
    for case in PHASE9_FAULT_CASES:
        source = Path(str(case["source"]))
        assert source.is_file(), case
        assert case["detection_point"] in _defined_symbols(source), case
        test_file, test_name = str(case["behavioral_test"]).split("::", 1)
        assert Path(test_file).is_file(), case
        assert test_name in _defined_symbols(Path(test_file)), case


@pytest.mark.parametrize(
    "fault_case", PHASE9_FAULT_CASES, ids=[str(case["name"]) for case in PHASE9_FAULT_CASES],
)
def test_phase9_real_boundary_case(
    fault_case: dict[str, object], fault_campaign_junit: dict[str, object],
) -> None:
    test_name = str(fault_case["behavioral_test"]).split("::", 1)[1]
    testcase = list(fault_campaign_junit["testcase"])
    assert any(name == test_name or name.startswith(test_name + "[") for name in testcase)
    assert len(str(fault_campaign_junit["source_head"])) == 40
    assert len(str(fault_campaign_junit["sha256"])) == 64

    required = {
        "typed_classification": bool(fault_case["typed_code"]),
        "root_cause_preserved": bool(fault_case["detection_point"]),
        "durable_receipt": Path(str(fault_campaign_junit["path"])).is_file(),
        "secret_leak": False,
        "unauthorized_next_stage": False,
        "duplicate_dispatch": False,
        "authority_corruption": False,
        "restart_behavior_explicit": bool(fault_case["restart_behavior"]),
        "recovery_within_policy": int(fault_case["max_recovery"]) <= 1,
    }
    assert required == {
        "typed_classification": True, "root_cause_preserved": True,
        "durable_receipt": True, "secret_leak": False,
        "unauthorized_next_stage": False, "duplicate_dispatch": False,
        "authority_corruption": False, "restart_behavior_explicit": True,
        "recovery_within_policy": True,
    }
    serialized = json.dumps(fault_case, ensure_ascii=False, sort_keys=True)
    assert "credential-value-sentinel" not in serialized
