from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tools.canary.approval_profiles import (
    SHORT_COMPLETION_PROFILE_ID,
    approval_profile,
    approval_profile_for_scope,
    approval_profile_registry_v1,
)
from tools.canary.short_completion import (
    COMPLETION_GOAL,
    completion_contract_bundle_v1,
)
from tools.canary.short_completion_approval import (
    build_short_completion_candidate_v1,
    build_short_completion_patch_template_v1,
    materialize_short_completion_patch_v1,
    materialize_short_completion_signed_approval_v1,
    validate_short_completion_candidate_v1,
    validate_short_completion_signed_approval_v1,
)
from tools.canary.contracts import CanaryContractError


NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
HEX = "1" * 64


def _candidate_payload() -> dict:
    bundle = completion_contract_bundle_v1()
    return {
        "approval_scope": "SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY",
        "approved_plan_sha256": HEX,
        "approved_launcher_sha256": HEX,
        "approved_workload_sha256": HEX,
        "approved_workload_manifest_hash": HEX,
        "approved_build_fingerprint": HEX,
        "approved_execution_config_fingerprint": HEX,
        "approved_runtime_execution_fingerprint": HEX,
        "provider_descriptor_hash": HEX,
        "model_role_binding_manifest_hash": HEX,
        "pricing_evidence_manifest_hash": HEX,
        "feature_flag_snapshot_hash": HEX,
        "call_budget_definition_sha256": HEX,
        "token_budget_definition_sha256": HEX,
        "monetary_budget_definition_sha256": HEX,
        "elapsed_budget_definition_sha256": HEX,
        "prompt_policy_manifest_sha256": HEX,
        "canary_root_identity": HEX,
        "stop_condition_manifest_hash": bundle["stop_conditions"]["definition_sha256"],
        "draft_validator_policy_sha256": bundle["draft_validator_policy"]["definition_sha256"],
        "mixed_script_policy_sha256": bundle["mixed_script_policy"]["definition_sha256"],
        "final_review_definition_sha256": bundle["final_review"]["definition_sha256"],
        "maintenance_definition_sha256": bundle["maintenance"]["definition_sha256"],
        "final_artifact_policy_sha256": bundle["final_artifact"]["definition_sha256"],
        "final_checkpoint_policy_sha256": bundle["final_checkpoint"]["definition_sha256"],
        "completion_goal_definition_sha256": bundle["completion_goal"]["definition_sha256"],
        "approved_workload_id": "short-normal-v1",
        "runtime_mode": "git_workspace",
        "maximum_runs": 1,
        "expected_model_calls": 16,
        "maximum_total_model_calls": 48,
        "maximum_input_tokens": 1_000_000,
        "maximum_output_tokens": 1_000_000,
        "maximum_output_tokens_per_call": 32_000,
        "maximum_usd_cost_microunits": 20_000_000,
        "maximum_cny_cost_microunits": 50_000_000,
        "maximum_elapsed_seconds": 7_200,
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
        "phase1b_enabled": False,
        "execution_window": {
            "not_before": "2026-08-16T10:00:00Z",
            "not_after": "2026-08-17T10:00:00Z",
        },
        "approval_expiry": "2026-08-17T10:00:00Z",
        "single_use_cohort_id": "short-completion-1-test-cohort",
        "maximum_executions": 1,
        "usage_status": "unused",
        "consumed_evidence_sha256": None,
        "named_approver": "USER_CONFIRMATION_REQUIRED",
        "authorized_actions": {
            "credential_lookup": False,
            "provider_client_creation": False,
            "network": False,
            "paid_model_calls": False,
            "fake_boundary": False,
        },
        "execution_authorized": False,
        "status": "waiting_for_final_user_authorization",
    }


def test_registry_is_closed_world_with_exact_three_profiles() -> None:
    assert tuple(approval_profile_registry_v1()) == (
        "c0b_smoke_1", "pa_strict_tool_obs_1", "short_completion_1",
    )
    assert approval_profile(SHORT_COMPLETION_PROFILE_ID).approval_scope == (
        "SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY"
    )
    with pytest.raises(Exception, match="approval_profile_unknown"):
        approval_profile_for_scope("SHORT_COMPLETION_WILDCARD")


def test_completion_definitions_are_hash_bound_and_goal_exact() -> None:
    bundle = completion_contract_bundle_v1()
    assert bundle["completion_goal"]["goal"] == COMPLETION_GOAL
    assert all(item["definition_sha256"] for item in bundle.values())


def test_candidate_is_inert_and_patch_is_not_executable() -> None:
    candidate = build_short_completion_candidate_v1(_candidate_payload())
    assert validate_short_completion_candidate_v1(candidate) == candidate
    assert candidate["execution_authorized"] is False
    assert set(candidate["authorized_actions"].values()) == {False}
    patch = build_short_completion_patch_template_v1(candidate)
    assert patch["execution_authorized"] is False
    assert patch["named_approver"] == "USER_CONFIRMATION_REQUIRED"


def test_confirmed_patch_can_materialize_exact_signed_fixture() -> None:
    candidate = build_short_completion_candidate_v1(_candidate_payload())
    template = build_short_completion_patch_template_v1(candidate)
    patch = materialize_short_completion_patch_v1(
        template, named_approver="test_owner",
        approval_timestamp="2026-08-16T10:05:00Z",
    )
    signed = materialize_short_completion_signed_approval_v1(
        candidate, patch, now=NOW,
    )
    assert validate_short_completion_signed_approval_v1(
        signed, expected_plan_sha256=HEX,
        expected_launcher_sha256=HEX, now=NOW,
    ) == signed
    assert signed["execution_authorized"] is True


@pytest.mark.parametrize("field", [
    "final_review_definition_sha256",
    "maintenance_definition_sha256",
    "draft_validator_policy_sha256",
    "mixed_script_policy_sha256",
    "stop_condition_manifest_hash",
])
def test_policy_drift_is_rejected(field: str) -> None:
    candidate = build_short_completion_candidate_v1(_candidate_payload())
    changed = deepcopy(candidate)
    changed[field] = "2" * 64
    with pytest.raises(CanaryContractError):
        validate_short_completion_candidate_v1(changed)
