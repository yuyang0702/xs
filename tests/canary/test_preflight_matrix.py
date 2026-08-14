from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tools.canary.contracts import (
    build_canary_experiment_plan_v1,
    build_canary_plan_approval_v1,
)
from tools.canary.gate import BoundaryRequest
from tools.canary.preflight import CanaryPreflightBlocked, ExactBoundaryVerifier

from .test_contracts import approval_payload, h, plan_payload


def fixture() -> tuple[dict, dict, dict, BoundaryRequest]:
    plan = build_canary_experiment_plan_v1(plan_payload())
    approval = build_canary_plan_approval_v1(approval_payload(plan))
    execution = plan["expected_runtime_execution_fingerprint"]
    snapshot = {
        "plan": plan,
        "approval": approval,
        "launcher_sha256": plan["launcher_sha256"],
        "workload_manifest_hash": plan["workload_manifest_hash"],
        "workload_fixture_hashes": {
            item["workload_id"]: item["fixture_sha256"] for item in plan["workloads"]
        },
        "provider_descriptor_definition_sha256": (
            plan["provider_descriptor_definition_sha256"]
        ),
        "role_binding_manifest_definition_sha256": (
            plan["role_binding_manifest_definition_sha256"]
        ),
        "feature_flag_snapshot": deepcopy(plan["feature_flag_snapshot"]),
        "build_fingerprint": plan["approved_build_fingerprint"],
        "execution_config_fingerprint": plan["approved_execution_config_fingerprint"],
        "runtime_execution_fingerprint": execution,
        "origin_binding": {
            "binding_status": "exact",
            "runtime_execution_fingerprint": execution,
        },
        "executor_binding": {
            "binding_status": "exact",
            "build_fingerprint_sha256": plan["approved_build_fingerprint"],
            "execution_config_fingerprint_sha256": (
                plan["approved_execution_config_fingerprint"]
            ),
            "origin_runtime_execution_fingerprint": execution,
        },
        "current_source_revalidation": {
            "source_changed_after_process_start": False,
            "comparison_status": "exact",
            "runtime_build_status": "verified_git_workspace",
            "production_source_clean": True,
        },
        "sidecar_validation": {
            "valid": True, "validation_status": "exact", "reason_codes": [],
        },
        "contradictory_binding": False,
        "canary_root_validation": {"validation_status": "exact"},
    }
    request = BoundaryRequest(
        stage="planning", role="planning", ordinal=1, route_kind="primary",
        provider_descriptor_hash=h("planning-provider"),
        model_binding_hash=h("planning-model"), protocol="anthropic",
        contract_sha256=None, system_sha256=h("system"), user_sha256=h("user"),
        input_tokens=10, output_tokens=20, retry_fallback_reason=None,
        run_id_hash=h("run"),
    )
    return plan, approval, snapshot, request


def verifier(snapshot: dict, plan: dict, approval: dict) -> ExactBoundaryVerifier:
    return ExactBoundaryVerifier(
        snapshot_supplier=lambda: snapshot,
        cli_approved_plan_sha256=plan["plan_sha256"],
        initial_plan_sha256=plan["plan_sha256"],
        initial_approval_sha256=approval["approval_sha256"],
        initial_launcher_sha256=plan["launcher_sha256"],
        initial_workload_manifest_hash=plan["workload_manifest_hash"],
        now=datetime(2030, 1, 1, 12, tzinfo=timezone.utc),
    )


def test_exact_approved_boundary_calls_existing_runtime_preflight() -> None:
    plan, approval, snapshot, request = fixture()
    result = verifier(snapshot, plan, approval)(request)
    assert result["status"] == "exact"
    assert len(result["runtime_validation_receipt_sha256"]) == 64


@pytest.mark.parametrize("mutation,reason", [
    (lambda s: s.update(build_fingerprint=h("changed")), "build_changed_during_canary"),
    (lambda s: s.update(execution_config_fingerprint=h("changed")), "execution_config_changed_during_canary"),
    (lambda s: s.update(runtime_execution_fingerprint=h("changed")), "runtime_execution_changed_during_canary"),
    (lambda s: s.update(launcher_sha256=h("changed")), "launcher_changed_during_canary"),
    (lambda s: s.update(workload_manifest_hash=h("changed")), "workload_changed_during_canary"),
    (lambda s: s["workload_fixture_hashes"].update({"short-normal-v1": h("changed")}), "workload_fixture_changed_during_canary"),
    (lambda s: s.update(provider_descriptor_definition_sha256=h("changed")), "provider_descriptor_mismatch"),
    (lambda s: s.update(role_binding_manifest_definition_sha256=h("changed")), "role_binding_manifest_mismatch"),
    (lambda s: s["feature_flag_snapshot"].update({"NOVEL_SHORT_CANONICAL_V2": True}), "execution_feature_flags_changed"),
    (lambda s: s.update(origin_binding=None), "origin_binding_missing"),
    (lambda s: s["executor_binding"].update({"origin_runtime_execution_fingerprint": h("changed")}), "origin_executor_binding_mismatch"),
    (lambda s: s.update(sidecar_validation={"valid": False, "validation_status": "invalid"}), "sidecar_definition_not_exact"),
    (lambda s: s["current_source_revalidation"].update({"source_changed_after_process_start": True}), "source_changed_after_process_start"),
    (lambda s: s["current_source_revalidation"].update({"production_source_clean": False}), "production_source_not_clean"),
    (lambda s: s.update(canary_root_validation={"validation_status": "invalid"}), "canary_root_identity_mismatch"),
])
def test_each_mutable_boundary_blocks_before_provider(mutation, reason) -> None:
    plan, approval, snapshot, request = fixture()
    mutation(snapshot)
    with pytest.raises(CanaryPreflightBlocked, match=reason):
        verifier(snapshot, plan, approval)(request)


def test_plan_and_approval_changes_invalidate_initial_authority() -> None:
    plan, approval, snapshot, request = fixture()
    changed_plan_payload = plan_payload()
    changed_plan_payload["budgets"]["maximum_elapsed_seconds"] += 1
    snapshot["plan"] = build_canary_experiment_plan_v1(changed_plan_payload)
    with pytest.raises(CanaryPreflightBlocked, match="plan_hash_unapproved"):
        verifier(snapshot, plan, approval)(request)

    plan, approval, snapshot, request = fixture()
    changed_approval_payload = approval_payload(plan)
    changed_approval_payload["maximum_executions"] = 2
    snapshot["approval"] = build_canary_plan_approval_v1(changed_approval_payload)
    with pytest.raises(CanaryPreflightBlocked, match="approval_changed_during_canary"):
        verifier(snapshot, plan, approval)(request)
