from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary.artifact_hash import file_sha256, tree_manifest
from tools.canary.pa_strict_tool_obs import (
    APPROVAL_SCOPE,
    CANDIDATE_SCHEMA,
    FEATURE_FLAGS,
    FUTURE_SIGNED_APPROVAL_SCHEMA,
    PAStrictToolObsMaterializationError,
    STOP_CONDITIONS,
    TARGET,
    materialize_pa_strict_tool_obs_1,
    validate_candidate,
)


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"
NOW = datetime(2026, 8, 15, 13, 30, tzinfo=timezone.utc)
COHORT = "pa-strict-tool-obs-1-20260815t133000z-test"


@pytest.fixture()
def materialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import keyring

    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during PA materialization")
        ),
    )
    before = {
        "database": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    result = materialize_pa_strict_tool_obs_1(
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=tmp_path / "outputs",
        cohort_id=COHORT,
        run_namespace=COHORT,
        artifact_root_label="docs/superpowers/reports/pa-strict-tool-obs-1",
        now=NOW,
    )
    after = {
        "database": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    assert before == after
    return result


def test_plan_binds_exact_target_flags_route_and_dual_outcomes(materialized) -> None:
    plan = materialized["plan"]
    policy = plan["pa_strict_tool_observation_policy"]
    assert plan["canary_mode"] == "pa_strict_tool_observation"
    assert plan["feature_flag_snapshot"] == FEATURE_FLAGS
    assert policy["target"] == TARGET
    assert policy["observation_goal_success"] == "TARGET_STRICT_TOOL_SHAPE_OBSERVED"
    assert policy["target_not_reached_outcome"] == "TARGET_NOT_REACHED"
    assert policy["workflow_outcome_independent"] is True
    assert policy["missing_snapshot_zero_inference_allowed"] is False
    assert policy["second_run_allowed"] is False
    assert tuple(plan["stop_conditions"]) == STOP_CONDITIONS
    review = next(route for route in plan["approved_routes"] if route["role"] == "review")
    assert review["fallback"]["provider_descriptor_hash"]
    assert review["fallback"]["model_binding_hash"]


def test_candidate_is_single_use_exact_budget_and_inert(materialized) -> None:
    candidate = validate_candidate(materialized["approval_candidate"])
    assert candidate["schema"] == CANDIDATE_SCHEMA
    assert candidate["approval_scope"] == APPROVAL_SCOPE
    assert candidate["single_use_cohort_id"] == COHORT
    assert candidate["maximum_executions"] == 1
    assert candidate["usage_status"] == "unused"
    assert candidate["named_approver"] == "USER_CONFIRMATION_REQUIRED"
    assert candidate["maximum_runs"] == 1
    assert candidate["expected_model_calls"] == 11
    assert candidate["maximum_total_model_calls"] == 24
    assert candidate["maximum_input_tokens"] == 500_000
    assert candidate["maximum_output_tokens"] == 500_000
    assert candidate["maximum_output_tokens_per_call"] == 32_000
    assert candidate["maximum_usd_cost_microunits"] == 10_000_000
    assert candidate["maximum_cny_cost_microunits"] == 25_000_000
    assert candidate["maximum_elapsed_seconds"] == 7_200
    assert candidate["execution_window"] == {
        "not_before": "2026-08-15T13:45:00Z",
        "not_after": "2026-08-17T13:45:00Z",
    }
    assert candidate["approval_expiry"] == "2026-08-17T13:45:00Z"
    for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls",
        "execution_authorized", "phase1b_enabled",
        "signed_approval_materialized", "execution_performed",
    ):
        assert candidate[name] is False


def test_candidate_tampering_is_rejected(materialized) -> None:
    candidate = deepcopy(materialized["approval_candidate"])
    candidate["authorize_network"] = True
    with pytest.raises(
        PAStrictToolObsMaterializationError,
        match="candidate_external_authorization_present",
    ):
        validate_candidate(candidate)


def test_patch_is_only_template_and_preview_requires_future_signed_approval(materialized) -> None:
    patch = materialized["authorization_patch_template"]
    preview = materialized["execution_command_preview"]
    assert patch["template_status"] == "not_authorization_user_confirmation_required"
    assert patch["execution_authorized"] is False
    assert patch["signed_approval_materialization_allowed"] is False
    assert set(patch["requested_authorizations"].values()) == {
        "USER_CONFIRMATION_REQUIRED"
    }
    assert preview["future_signed_approval_schema"] == FUTURE_SIGNED_APPROVAL_SCHEMA
    assert preview["future_signed_approval_file"] == (
        "${PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL}"
    )
    assert preview["candidate_is_executable_approval"] is False
    assert preview["do_not_execute"] is True
    assert preview["execution_authorized"] is False


def test_validate_only_is_exact_with_zero_external_actions_and_parity(materialized) -> None:
    receipt = materialized["validation_receipt"]
    assert receipt["overall_status"] == "exact"
    assert len(receipt["ordered_checks"]) >= 28
    assert all(item["status"] == "exact" for item in receipt["ordered_checks"])
    assert set(receipt["external_action_counters"].values()) == {0}
    assert receipt["privacy"]["status"] == "exact"
    assert receipt["privacy"]["violation_count"] == 0
    assert receipt["parity"]["status"] == "exact"
    assert receipt["execution_performed"] is False


def test_materialized_documents_contain_no_fixture_business_content(materialized) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    private = [fixture["title"], fixture["premise"], fixture["outline"]]
    for key in (
        "plan", "approval_candidate", "authorization_patch_template",
        "execution_command_preview", "validation_receipt", "index",
    ):
        serialized = json.dumps(materialized[key], ensure_ascii=False, sort_keys=True)
        assert all(value not in serialized for value in private)
        assert "api_key" not in serialized.casefold()
        assert "bearer " not in serialized.casefold()


def test_no_signed_approval_or_canary_b_artifact_is_materialized(materialized) -> None:
    names = set(materialized["index"]["files"])
    assert not any("signed-approval" in name for name in names)
    assert not any("budget-counterfactual" in name for name in names)
    assert materialized["index"]["execution_performed"] is False
    assert materialized["index"]["status"] == (
        "PA_STRICT_TOOL_OBS_1_WAITING_FOR_FINAL_USER_AUTHORIZATION"
    )

