from copy import deepcopy
from datetime import datetime, timezone
import hashlib

import pytest

from tools.canary.contracts import (
    CanaryContractError,
    build_canary_experiment_plan_v1,
    build_canary_plan_approval_v1,
    validate_canary_experiment_plan_v1,
    validate_canary_plan_approval_v1,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def plan_payload() -> dict:
    return {
        "canary_mode": "c0a_fake_dry_run",
        "runtime_mode": "git_workspace",
        "approved_build_fingerprint": h("build"),
        "approved_execution_config_fingerprint": h("config"),
        "expected_runtime_execution_fingerprint": h("execution"),
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v1",
        "launcher_sha256": h("launcher"),
        "workload_manifest_hash": h("workloads"),
        "workloads": [{
            "workload_id": "short-normal-v1",
            "fixture_sha256": h("fixture"),
            "weight": 1,
            "prompt_policy_manifest_sha256": h("prompt-policy"),
            "expected_stage_reachability": ["planning", "draft", "maintenance"],
            "maximum_model_calls": 20,
            "estimated_input_tokens": 400_000,
            "maximum_output_tokens": 150_000,
            "success_definition": "workflow_completed",
            "controlled_outcomes": ["waiting_user"],
            "terminal_outcomes": ["workflow_terminal"],
        }],
        "provider_descriptor_definition_sha256": h("provider"),
        "role_binding_manifest_definition_sha256": h("binding"),
        "feature_flag_snapshot": {
            "NOVEL_SHORT_CANONICAL_V2": False,
            "project_short_canonical_v2": False,
            "NOVEL_CANONICAL_SHADOW_V1": False,
            "NOVEL_RELIABILITY_TRACE": True,
        },
        "isolation": {
            "data_root_kind": "canary_ephemeral",
            "stable_root_identity": h("root"),
            "db_path_hash": h("db"),
            "project_root_hash": h("projects"),
            "run_namespace": "c0a-short-v1",
        },
        "budgets": {
            "maximum_runs": 1,
            "maximum_model_calls_per_run": 20,
            "maximum_total_model_calls": 20,
            "maximum_input_tokens": 400_000,
            "maximum_output_tokens": 150_000,
            "pricing_status": "not_applicable_fake",
            "currency": "NONE",
            "maximum_estimated_cost_microunits": 0,
            "maximum_elapsed_seconds": 3600,
            "gate_wait_timeout_seconds": 10,
        },
        "stop_conditions": ["first_terminal_failure", "fingerprint_mismatch"],
        "report_policy": {"raw_content_included": False, "hash_only": True},
        "approved_dependency_manifest": {
            "stdlib": True, "production_package": True, "third_party": [],
        },
    }


def approval_payload(plan: dict) -> dict:
    return {
        "approval_scope": "C0A_FAKE_DRY_RUN",
        "approved_plan_sha256": plan["plan_sha256"],
        "approved_launcher_sha256": plan["launcher_sha256"],
        "single_use_cohort_id": "c0a-fixture-001",
        "approval_expiry": "2030-01-02T00:00:00Z",
        "execution_window": {
            "not_before": "2030-01-01T00:00:00Z",
            "not_after": "2030-01-01T23:59:59Z",
        },
        "maximum_executions": 1,
        "usage_status": "unused",
        "consumed_evidence_sha256": None,
        "authorized_actions": {
            "credential_lookup": False,
            "provider_client_creation": False,
            "network": False,
            "paid_model_calls": False,
            "fake_boundary": True,
        },
    }


def test_plan_is_order_stable_and_exactly_hash_bound() -> None:
    payload = plan_payload()
    first = build_canary_experiment_plan_v1(payload)
    second = build_canary_experiment_plan_v1(dict(reversed(list(payload.items()))))
    assert first["plan_sha256"] == second["plan_sha256"]
    tampered = deepcopy(first)
    tampered["budgets"]["maximum_total_model_calls"] += 1
    with pytest.raises(CanaryContractError, match="plan_hash_mismatch"):
        validate_canary_experiment_plan_v1(tampered)


@pytest.mark.parametrize("field,value,code", [
    ("isolation", {"data_root": r"C:\\live\\data"}, "absolute_path_forbidden"),
    ("report_policy", {"prompt": "never persist me"}, "forbidden_material_field"),
])
def test_plan_rejects_private_or_machine_specific_material(field, value, code) -> None:
    payload = plan_payload()
    payload[field] = value
    with pytest.raises(CanaryContractError, match=code):
        build_canary_experiment_plan_v1(payload)


def test_plan_requires_phase1b_closed() -> None:
    payload = plan_payload()
    payload["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] = True
    with pytest.raises(CanaryContractError, match="phase1b_environment_flag_enabled"):
        build_canary_experiment_plan_v1(payload)


def test_approval_checks_scope_window_plan_launcher_and_usage() -> None:
    plan = build_canary_experiment_plan_v1(plan_payload())
    approval = build_canary_plan_approval_v1(approval_payload(plan))
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    validated = validate_canary_plan_approval_v1(
        approval, expected_scope="C0A_FAKE_DRY_RUN",
        expected_plan_sha256=plan["plan_sha256"],
        expected_launcher_sha256=plan["launcher_sha256"], now=now,
    )
    assert validated["usage_status"] == "unused"

    cases = [
        ({"approval_scope": "C0B_REAL_PROVIDER_PATH_REACHABILITY"}, "approval_scope_mismatch"),
        ({"approved_plan_sha256": h("other-plan")}, "approval_plan_mismatch"),
        ({"approved_launcher_sha256": h("other-launcher")}, "approval_launcher_mismatch"),
    ]
    for changes, code in cases:
        changed_payload = approval_payload(plan) | changes
        changed = build_canary_plan_approval_v1(changed_payload)
        with pytest.raises(CanaryContractError, match=code):
            validate_canary_plan_approval_v1(
                changed, expected_scope="C0A_FAKE_DRY_RUN",
                expected_plan_sha256=plan["plan_sha256"],
                expected_launcher_sha256=plan["launcher_sha256"], now=now,
            )

    with pytest.raises(CanaryContractError, match="approval_expired"):
        validate_canary_plan_approval_v1(
            approval, now=datetime(2030, 1, 3, tzinfo=timezone.utc),
        )


def test_used_approval_is_not_reusable() -> None:
    plan = build_canary_experiment_plan_v1(plan_payload())
    payload = approval_payload(plan) | {
        "usage_status": "used", "consumed_evidence_sha256": h("evidence"),
    }
    approval = build_canary_plan_approval_v1(payload)
    with pytest.raises(CanaryContractError, match="approval_already_used"):
        validate_canary_plan_approval_v1(
            approval, now=datetime(2030, 1, 1, 12, tzinfo=timezone.utc),
        )
