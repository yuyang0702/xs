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
from tools.canary.approval_dispatch import (
    materialize_signed_canary_approval, validate_registered_approval_document,
    validate_registered_signed_plan, validate_registered_signed_sources,
)
from tools.canary.approval_profiles import PA_PROFILE_ID, approval_profile
from tools.canary.approval_store import ApprovalConsumptionStore, CanaryApprovalReplay
from tools.canary.contracts import CanaryContractError
from tools.canary.pa_approval import (
    materialize_pa_authorization_patch_v1,
    validate_pa_final_approval_candidate_v1,
    validate_pa_signed_approval_v1,
)


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"
NOW = datetime(2026, 8, 15, 13, 30, tzinfo=timezone.utc)
COHORT = "pa-strict-tool-obs-1-20260815t133000z-test"


@pytest.fixture(scope="module")
def materialized(tmp_path_factory: pytest.TempPathFactory):
    import keyring

    monkeypatch = pytest.MonkeyPatch()
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
        output_root=tmp_path_factory.mktemp("pa-materialized") / "outputs",
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
    monkeypatch.undo()
    return result


@pytest.fixture(scope="module")
def signed_documents(materialized):
    patch = materialize_pa_authorization_patch_v1(
        materialized["authorization_patch_template"],
        named_approver="test_project_owner",
        approval_timestamp="2026-08-15T13:45:00Z",
    )
    signed = materialize_signed_canary_approval(
        PA_PROFILE_ID, materialized["approval_candidate"], patch,
        now=datetime(2026, 8, 15, 13, 45, tzinfo=timezone.utc),
    )
    return materialized["approval_candidate"], patch, signed


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
    assert materialized["index"]["contract_status"] == (
        "PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL_PROFILE_READY"
    )
    assert materialized["index"]["status"] == (
        "PA_STRICT_TOOL_OBS_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION"
    )


def test_candidate_patch_and_signed_documents_are_distinct(signed_documents) -> None:
    candidate, patch, signed = signed_documents
    assert len({candidate["schema"], patch["schema"], signed["schema"]}) == 3
    assert candidate["execution_authorized"] is False
    assert patch["execution_authorized"] is True
    assert signed["execution_authorized"] is True


def test_generic_signer_materializes_pa_signed_contract(signed_documents) -> None:
    assert signed_documents[2]["profile_id"] == PA_PROFILE_ID


def test_signed_sources_are_exactly_bound(signed_documents) -> None:
    candidate, patch, signed = signed_documents
    assert validate_registered_signed_sources(
        PA_PROFILE_ID, signed, candidate, patch,
        now=datetime(2026, 8, 15, 13, 45, tzinfo=timezone.utc),
    ) == signed


def test_signed_plan_is_exactly_bound(materialized, signed_documents) -> None:
    assert validate_registered_signed_plan(
        PA_PROFILE_ID, signed_documents[2], materialized["plan"],
        now=datetime(2026, 8, 15, 13, 45, tzinfo=timezone.utc),
    ) == signed_documents[2]


def test_registered_candidate_remains_non_executable(materialized) -> None:
    profile = approval_profile(PA_PROFILE_ID)
    _document, _identity, kind, _profile = validate_registered_approval_document(
        materialized["approval_candidate"], expected_profile_id=profile.profile_id,
        expected_scope=profile.approval_scope,
        expected_plan_sha256=materialized["plan"]["plan_sha256"],
        expected_launcher_sha256=materialized["plan"]["launcher_sha256"],
        enforce_time=False,
    )
    assert kind == "final_approval_candidate"


def test_registered_patch_is_never_an_executable_document(signed_documents, materialized) -> None:
    profile = approval_profile(PA_PROFILE_ID)
    with pytest.raises(CanaryContractError, match="authorization_patch_not_executable"):
        validate_registered_approval_document(
            signed_documents[1], expected_profile_id=profile.profile_id,
            expected_scope=profile.approval_scope,
            expected_plan_sha256=materialized["plan"]["plan_sha256"],
            expected_launcher_sha256=materialized["plan"]["launcher_sha256"],
        )


@pytest.mark.parametrize("field", [
    "approved_plan_sha256", "approved_launcher_sha256",
    "approved_workload_sha256", "approved_build_fingerprint",
    "target_filter_sha256", "observation_schema_sha256",
    "profile_definition_sha256", "source_candidate_sha256",
])
def test_signed_protected_field_tamper_is_rejected(signed_documents, field) -> None:
    signed = deepcopy(signed_documents[2])
    signed[field] = "0" * 64
    with pytest.raises(CanaryContractError):
        validate_pa_signed_approval_v1(
            signed, now=datetime(2026, 8, 15, 13, 45, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("field", [
    "authorize_credential_lookup", "authorize_provider_client_creation",
    "authorize_network", "authorize_paid_model_calls",
])
def test_candidate_authorization_tamper_is_rejected(materialized, field) -> None:
    candidate = deepcopy(materialized["approval_candidate"])
    candidate[field] = True
    with pytest.raises(CanaryContractError, match="external_authorization_present"):
        validate_pa_final_approval_candidate_v1(candidate)


def test_signed_ledger_is_single_use(tmp_path: Path, signed_documents) -> None:
    store = ApprovalConsumptionStore(tmp_path)
    signed = signed_documents[2]
    reservation = store.reserve(signed)
    assert reservation["payload"]["profile_id"] == PA_PROFILE_ID
    store.consume(signed, "a" * 64)
    with pytest.raises(CanaryApprovalReplay, match="already_consumed"):
        store.reserve(signed)


def test_ledger_rejects_candidate_execution(tmp_path: Path, materialized) -> None:
    with pytest.raises(CanaryApprovalReplay, match="candidate_not_executable"):
        ApprovalConsumptionStore(tmp_path).reserve(materialized["approval_candidate"])


def test_pa_profile_definition_is_immutable() -> None:
    with pytest.raises(Exception):
        approval_profile(PA_PROFILE_ID).profile_id = "mutated"


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(Exception, match="approval_profile_unknown"):
        approval_profile("unknown")


def test_cross_profile_declaration_is_rejected(materialized) -> None:
    candidate = deepcopy(materialized["approval_candidate"])
    candidate["profile_id"] = "c0b_smoke_1"
    with pytest.raises(CanaryContractError, match="approval_profile_unknown"):
        validate_registered_approval_document(
            candidate, expected_profile_id=PA_PROFILE_ID,
            expected_scope=approval_profile(PA_PROFILE_ID).approval_scope,
            expected_plan_sha256=materialized["plan"]["plan_sha256"],
            expected_launcher_sha256=materialized["plan"]["launcher_sha256"],
            enforce_time=False,
        )


def test_expired_signed_approval_is_rejected(signed_documents) -> None:
    with pytest.raises(CanaryContractError, match="outside_execution_window"):
        validate_pa_signed_approval_v1(
            signed_documents[2],
            now=datetime(2026, 8, 18, 13, 45, tzinfo=timezone.utc),
        )
