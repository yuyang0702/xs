from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.canary.approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
    approval_profile,
)
from tools.canary.approval_dispatch import (
    materialize_signed_canary_approval,
    validate_registered_approval_document,
    validate_registered_signed_plan,
    validate_registered_signed_sources,
)
from tools.canary.artifact_hash import file_sha256, tree_manifest
from tools.canary.planning_repair_observation import (
    FEATURE_FLAGS,
    materialize_planning_repair_observation_1,
)
from tools.canary.planning_repair_approval import (
    materialize_planning_repair_observation_patch_v1,
)
from tools.canary.contracts import CanaryContractError


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"
NOW = datetime(2026, 8, 17, 13, 30, tzinfo=timezone.utc)
COHORT = "planning-repair-observation-1-20260817t133000z-test"


@pytest.fixture(scope="module")
def materialized(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("ptr2-materialized")
    before = {
        "database": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    result = materialize_planning_repair_observation_1(
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=output / "reports",
        approval_ledger_root=output / "ledger",
        cohort_id=COHORT,
        run_namespace=COHORT,
        artifact_root_label="docs/superpowers/reports/r1-ptr2",
        now=NOW,
    )
    after = {
        "database": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    assert before == after
    return result


def test_profile_is_distinct_narrow_and_diagnostic_only() -> None:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    assert profile.approval_scope == (
        "PLANNING_REPAIR_SINGLE_REAL_PROVIDER_OBSERVATION_CANARY"
    )
    assert profile.required_flags() == FEATURE_FLAGS
    assert profile.budget()["maximum_total_model_calls"] == 16
    assert profile.budget()["maximum_input_tokens"] == 500_000
    assert profile.budget()["maximum_output_tokens"] == 500_000
    assert profile.budget()["maximum_output_tokens_per_call"] == 32_000
    assert profile.budget()["maximum_usd_cost_microunits"] == 10_000_000
    assert profile.budget()["maximum_cny_cost_microunits"] == 20_000_000
    assert profile.budget()["maximum_elapsed_seconds"] == 3_600
    assert profile.required_flags()[
        "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1"
    ] is True
    assert profile.required_flags()["NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"] is False
    assert profile.required_flags()["NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"] is False


def test_materialized_candidate_is_disabled_single_use_and_exact(materialized) -> None:
    candidate = materialized["approval_candidate"]
    receipt = materialized["validation_receipt"]
    assert candidate["profile_id"] == PLANNING_REPAIR_OBSERVATION_PROFILE_ID
    assert candidate["execution_authorized"] is False
    assert candidate["named_approver"] == "USER_CONFIRMATION_REQUIRED"
    assert candidate["usage_status"] == "unused"
    assert candidate["maximum_executions"] == 1
    assert candidate["single_use_cohort_id"] == COHORT
    assert candidate["signed_approval_materialized"] is False
    assert candidate["execution_performed"] is False
    assert receipt["overall_status"] == "exact"
    assert set(receipt["external_action_counters"].values()) == {0}
    assert receipt["execution_performed"] is False


def test_plan_binds_four_observers_and_goal_stop(materialized) -> None:
    plan = materialized["plan"]
    policy = plan["planning_repair_observation_policy"]
    assert plan["feature_flag_snapshot"] == FEATURE_FLAGS
    assert set(policy["instrumentation_definition_sha256s"]) == {
        "domain_validation",
        "finding_propagation",
        "provider_content_block_shape",
        "output_limit",
    }
    assert policy["synthetic_target_injection_allowed"] is False
    assert policy["production_retry_fallback_mutation_allowed"] is False
    assert policy["target_not_exercised_outcome"] == (
        "PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED"
    )
    assert "planning_repair_primary_evidence_captured_safe_stop" in (
        plan["stop_conditions"]
    )


def test_rehearsal_is_independent_fake_only_and_semantically_exact(materialized) -> None:
    receipt = materialized["semantic_rehearsal"]
    assert receipt["status"] == "exact"
    assert receipt["process_isolation"] == "independent_subprocess"
    assert receipt["observer_coverage"] == {
        "domain_validation": "typed",
        "finding_propagation": "typed",
        "provider_content_block_shape": "typed",
        "output_limit": "typed",
    }
    assert receipt["model_request_semantic_status"] == "unchanged"
    assert receipt["retry_fallback_status"] == "unchanged"
    assert receipt["production_output_budget_status"] == "unchanged"
    assert receipt["terminal_behavior_status"] == "unchanged"
    counters = receipt["external_action_counters"]
    assert counters["fake_boundary_count"] == 1
    assert all(counters[name] == 0 for name in (
        "credential_lookup_count", "provider_client_creation_count",
        "network_call_count", "model_call_count", "paid_model_call_count",
    ))


def test_packet_has_no_signed_or_confirmed_authorization(materialized) -> None:
    assert materialized["signed_approval"] is None
    assert materialized["confirmed_authorization_patch"] is None
    assert materialized["ledger_readiness"]["initial_entry_count"] == 0
    assert materialized["ledger_readiness"]["cohort_status"] == "unused"
    assert materialized["ledger_readiness"]["approval_status"] == "unreserved"
    assert materialized["index"]["status"] == (
        "R1_PTR2_REAL_OBSERVATION_WAITING_FOR_FINAL_USER_AUTHORIZATION"
    )
    assert materialized["index"]["contract_status"] == (
        "R1_PTR2_OBSERVATION_APPROVAL_PACKET_READY"
    )


def test_future_manual_authorization_path_is_profile_bound(materialized) -> None:
    patch = materialize_planning_repair_observation_patch_v1(
        materialized["authorization_patch_template"],
        named_approver="test_project_owner",
        approval_timestamp="2026-08-17T13:45:00Z",
    )
    signed = materialize_signed_canary_approval(
        PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
        materialized["approval_candidate"], patch,
        now=datetime(2026, 8, 17, 13, 45, tzinfo=timezone.utc),
    )
    validate_registered_signed_sources(
        PLANNING_REPAIR_OBSERVATION_PROFILE_ID, signed,
        materialized["approval_candidate"], patch,
        now=datetime(2026, 8, 17, 13, 45, tzinfo=timezone.utc),
    )
    validate_registered_signed_plan(
        PLANNING_REPAIR_OBSERVATION_PROFILE_ID, signed,
        materialized["plan"],
        now=datetime(2026, 8, 17, 13, 45, tzinfo=timezone.utc),
    )
    with pytest.raises(CanaryContractError, match="authorization_patch_not_executable"):
        validate_registered_approval_document(
            materialized["authorization_patch_template"],
            expected_profile_id=PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
            expected_scope=approval_profile(
                PLANNING_REPAIR_OBSERVATION_PROFILE_ID
            ).approval_scope,
            expected_plan_sha256=materialized["plan"]["plan_sha256"],
            expected_launcher_sha256=materialized["plan"]["launcher_sha256"],
            enforce_time=False,
        )
