from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary.artifact_hash import file_sha256, tree_manifest
from tools.canary.final_approval import materialize_c0b_smoke_1_final_approval_v2
from tools.canary.contracts import (
    CanaryContractError,
    build_c0b_smoke_1_user_authorization_patch_v2,
    validate_c0b_smoke_1_final_approval_candidate_v2,
)
from tools.canary.launcher import CanaryLauncherError, validate_packet


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"


@pytest.fixture()
def materialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import keyring

    monkeypatch.setattr(
        keyring, "get_password",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during final Approval materialization")
        ),
    )
    before = {
        "db": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    result = materialize_c0b_smoke_1_final_approval_v2(
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=tmp_path / "outputs",
        cohort_id="c0b-smoke-1-v2-20260815t044500z-test",
        run_namespace="c0b-smoke-1-v2-20260815t044500z-test",
        now=datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc),
        artifact_root_label="docs/superpowers/reports",
    )
    after = {
        "db": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    assert before == after
    return result


def test_materialized_candidate_has_exact_scope_budget_window_and_false_actions(materialized) -> None:
    candidate = materialized["approval_candidate"]
    assert candidate["schema"] == "C0BSmoke1FinalApprovalCandidateV2"
    assert candidate["approval_scope"] == "C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1"
    assert candidate["runtime_mode"] == "git_workspace"
    assert candidate["approved_workload_id"] == "short-normal-v1"
    assert candidate["maximum_runs"] == 1
    assert candidate["expected_model_calls"] == 16
    assert candidate["maximum_total_model_calls"] == 48
    assert candidate["maximum_input_tokens"] == 1_000_000
    assert candidate["maximum_output_tokens"] == 1_000_000
    assert candidate["maximum_output_tokens_per_call"] == 32_000
    assert candidate["maximum_usd_cost_microunits"] == 20_000_000
    assert candidate["maximum_cny_cost_microunits"] == 50_000_000
    assert candidate["maximum_elapsed_seconds"] == 7_200
    assert candidate["first_terminal_stop"] is True
    assert candidate["resume_after_terminal"] is False
    assert candidate["phase1b_enabled"] is False
    assert candidate["materialized_at"] == "2026-08-15T04:30:00Z"
    assert candidate["execution_window"] == {
        "not_before": "2026-08-15T04:45:00Z",
        "not_after": "2026-08-17T04:45:00Z",
    }
    assert candidate["approval_expiry"] == "2026-08-17T04:45:00Z"
    assert candidate["named_approver"] == "USER_CONFIRMATION_REQUIRED"
    assert candidate["execution_authorized"] is False
    assert candidate["authorize_credential_lookup"] is False
    assert candidate["authorize_provider_client_creation"] is False
    assert candidate["authorize_network"] is False
    assert candidate["authorize_paid_model_calls"] is False
    assert all(value is False for value in candidate["authorized_actions"].values())
    assert len(candidate["approval_candidate_sha256"]) == 64


def test_user_authorization_patch_is_bound_and_contains_no_protected_mutation(materialized) -> None:
    candidate = materialized["approval_candidate"]
    patch = materialized["user_authorization_patch"]
    assert patch["schema"] == "C0BSmoke1UserAuthorizationPatchV2"
    assert patch["bound_approval_candidate_sha256"] == candidate["approval_candidate_sha256"]
    assert patch["bound_plan_sha256"] == candidate["approved_plan_sha256"]
    assert patch["named_approver"] == "USER_CONFIRMATION_REQUIRED"
    assert patch["approval_timestamp"] == "USER_CONFIRMATION_REQUIRED"
    assert patch["authorize_credential_lookup"] is True
    assert patch["authorize_provider_client_creation"] is True
    assert patch["authorize_network"] is True
    assert patch["authorize_paid_model_calls"] is True
    assert patch["execution_authorized"] is True
    assert patch["protected_fields_mutation_allowed"] is False
    assert patch["approved_execution_window"] == candidate["execution_window"]
    assert patch["approval_expiry"] == candidate["approval_expiry"]
    assert patch["single_use_cohort_id"] == candidate[
        "single_use_cohort_id"
    ]
    forbidden = {"route", "workload", "budgets", "stop_conditions", "feature_flags", "provider", "model", "launcher"}
    assert forbidden.isdisjoint({key.casefold() for key in patch})


def test_user_authorization_patch_rejects_extra_protected_fields(materialized) -> None:
    payload = dict(materialized["user_authorization_patch"])
    payload.pop("authorization_patch_sha256")
    payload.pop("schema")
    payload.pop("version")
    payload.pop("canonicalization_version")
    payload["route"] = "forbidden"
    with pytest.raises(
        CanaryContractError, match="authorization_patch_fields_unexpected",
    ):
        build_c0b_smoke_1_user_authorization_patch_v2(payload)


def test_complete_validate_only_receipt_is_exact_and_inert(materialized) -> None:
    receipt = materialized["validation_receipt"]
    assert receipt["schema"] == "C0BApprovalClosureValidationReceiptV1"
    assert receipt["overall_status"] == "exact"
    assert len(receipt["ordered_checks"]) == 25
    assert all(item["status"] == "exact" for item in receipt["ordered_checks"])
    assert set(receipt["external_action_counters"].values()) == {0}
    assert materialized["execution_performed"] is False


def test_launcher_validate_only_accepts_candidate_but_real_execution_does_not(materialized) -> None:
    plan = materialized["plan"]
    paths = materialized["paths"]
    validated = validate_packet(
        plan_path=paths["plan"], approval_path=paths["approval_candidate"],
        cli_approved_plan_sha256=plan["plan_sha256"],
    )
    assert validated["approval_document_kind"] == "final_approval_candidate"
    assert validated["execution_authorized"] is False
    with pytest.raises(CanaryLauncherError, match="approval_candidate_not_executable"):
        validate_packet(
            plan_path=paths["plan"], approval_path=paths["approval_candidate"],
            cli_approved_plan_sha256=plan["plan_sha256"],
            execution_requested=True,
        )


def test_execution_command_preview_is_hash_bound_non_executable_and_secret_free(materialized) -> None:
    preview = materialized["execution_command_preview"]
    serialized = json.dumps(preview, ensure_ascii=False).casefold()
    assert preview["schema"] == "C0BSmoke1ExecutionCommandPreviewV1"
    assert preview["do_not_execute"] is True
    assert preview["execution_authorized"] is False
    assert preview["bound_plan_sha256"] == materialized["plan"]["plan_sha256"]
    assert preview["bound_approval_candidate_sha256"] == materialized["approval_candidate"]["approval_candidate_sha256"]
    assert "api_key" not in serialized
    assert "credential=" not in serialized
    assert "--real-run" in preview["future_command_argv"]


def test_all_required_definition_hashes_are_present_and_distinct(materialized) -> None:
    candidate = materialized["approval_candidate"]
    names = (
        "call_budget_definition_sha256", "token_budget_definition_sha256",
        "monetary_budget_definition_sha256", "elapsed_budget_definition_sha256",
        "stop_condition_manifest_hash", "feature_flag_snapshot_hash",
        "pricing_evidence_manifest_hash",
    )
    values = [candidate[name] for name in names]
    assert all(len(value) == 64 for value in values)
    assert len(set(values[:4])) == 4
    receipt_hashes = materialized["validation_receipt"]["definition_hashes"]
    assert receipt_hashes["call_budget_definition"] == values[0]
    assert receipt_hashes["token_budget_definition"] == values[1]
    assert receipt_hashes["monetary_budget_definition"] == values[2]
    assert receipt_hashes["elapsed_budget_definition"] == values[3]


def test_candidate_remains_valid_inside_window_and_expires_at_end(materialized) -> None:
    candidate = materialized["approval_candidate"]
    assert validate_c0b_smoke_1_final_approval_candidate_v2(
        candidate,
        now=datetime(2026, 8, 16, 4, 45, tzinfo=timezone.utc),
    )["approval_candidate_sha256"] == candidate["approval_candidate_sha256"]
    with pytest.raises(CanaryContractError, match="approval_expired"):
        validate_c0b_smoke_1_final_approval_candidate_v2(
            candidate,
            now=datetime(2026, 8, 17, 4, 45, tzinfo=timezone.utc),
        )
