from copy import deepcopy
from pathlib import Path

import pytest

from tools.canary.artifact_hash import file_sha256, tree_manifest
from tools.canary.c0b_packet import prepare_c0b_smoke_packet
from tools.canary.contracts import CanaryContractError, build_canary_experiment_plan_v1
from tools.canary.launcher import CanaryLauncherError, validate_packet


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"


def test_c0b_packet_preparation_is_inert_exact_and_real_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring

    monkeypatch.setattr(
        keyring, "get_password",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during packet preparation")
        ),
    )
    before_db = file_sha256(LIVE_DB)
    before_projects = tree_manifest(LIVE_PROJECTS)["tree_sha256"]
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    packet_path = tmp_path / "packet.json"
    plan, approval, packet = prepare_c0b_smoke_packet(
        live_database_path=LIVE_DB, fixture_path=FIXTURE,
        plan_path=plan_path, approval_path=approval_path,
        packet_path=packet_path, cohort_id="c0b-smoke-test-001",
        run_namespace="c0b-smoke-test-001",
    )
    assert packet["status"] == "C0B_SMOKE_1_READY_FOR_USER_APPROVAL"
    assert plan["budgets"]["maximum_total_model_calls"] == 144
    assert plan["budgets"]["monetary_budget"] == {
        "schema": "CanaryMonetaryBudgetV1",
        "maximum_usd_cost_microunits": 60_000_000,
        "maximum_cny_cost_microunits": 120_000_000,
        "approved_fx_snapshot": None,
    }
    assert all(value is False for value in approval["authorized_actions"].values())
    assert approval["named_approver"] is None
    validated = validate_packet(
        plan_path=plan_path, approval_path=approval_path,
        cli_approved_plan_sha256=plan["plan_sha256"],
    )
    assert validated["execution_authorized"] is False
    with pytest.raises(CanaryLauncherError, match="real_mode_final_authorization_missing"):
        validate_packet(
            plan_path=plan_path, approval_path=approval_path,
            cli_approved_plan_sha256=plan["plan_sha256"],
            execution_requested=True,
        )
    assert file_sha256(LIVE_DB) == before_db
    assert tree_manifest(LIVE_PROJECTS)["tree_sha256"] == before_projects


def test_phase1b_true_remains_a_contract_blocker(tmp_path: Path) -> None:
    plan, _approval, _packet = prepare_c0b_smoke_packet(
        live_database_path=LIVE_DB, fixture_path=FIXTURE,
        plan_path=tmp_path / "plan.json", approval_path=tmp_path / "approval.json",
        packet_path=tmp_path / "packet.json", cohort_id="c0b-smoke-test-002",
        run_namespace="c0b-smoke-test-002",
    )
    payload = deepcopy(plan)
    payload.pop("plan_sha256")
    payload["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] = True
    with pytest.raises(CanaryContractError, match="phase1b_environment_flag_enabled"):
        build_canary_experiment_plan_v1(payload)


def test_fake_plan_can_never_be_requested_as_real(tmp_path: Path) -> None:
    from tests.canary.test_launcher import packet

    plan_path, approval_path, plan = packet(tmp_path)
    with pytest.raises(CanaryLauncherError, match="fake_approval_cannot_execute_real_mode"):
        validate_packet(
            plan_path=plan_path, approval_path=approval_path,
            cli_approved_plan_sha256=plan["plan_sha256"],
            execution_requested=True,
        )
