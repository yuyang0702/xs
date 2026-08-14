from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary.contracts import (
    build_canary_experiment_plan_v1,
    build_canary_plan_approval_v1,
)
from tools.canary.hash_manifest import validate_import_closure
from tools.canary.launcher import CanaryLauncherError, validate_packet

from .test_contracts import approval_payload, plan_payload


def packet(tmp_path: Path) -> tuple[Path, Path, dict]:
    payload = plan_payload()
    payload["launcher_sha256"] = validate_import_closure(
        Path(__file__).parents[2] / "tools" / "canary",
    )["launcher_sha256"]
    plan = build_canary_experiment_plan_v1(payload)
    approval_data = approval_payload(plan)
    approval_data["execution_window"] = {
        "not_before": "2020-01-01T00:00:00Z",
        "not_after": "2029-12-31T23:59:59Z",
    }
    approval = build_canary_plan_approval_v1(approval_data)
    plan_path = tmp_path / "plan.json"
    approval_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    return plan_path, approval_path, plan


def test_launcher_validates_plan_approval_cli_and_current_manifest(tmp_path: Path) -> None:
    plan_path, approval_path, plan = packet(tmp_path)
    result = validate_packet(
        plan_path=plan_path, approval_path=approval_path,
        cli_approved_plan_sha256=plan["plan_sha256"],
    )
    assert result["status"] == "exact"


def test_launcher_rejects_cli_hash_and_real_mode(tmp_path: Path) -> None:
    plan_path, approval_path, plan = packet(tmp_path)
    with pytest.raises(CanaryLauncherError, match="cli_approved_plan_hash_mismatch"):
        validate_packet(
            plan_path=plan_path, approval_path=approval_path,
            cli_approved_plan_sha256="0" * 64,
        )

    payload = plan_payload()
    payload["canary_mode"] = "c0b_real_path_reachability"
    payload["budgets"].update({
        "monetary_budget": {
            "schema": "CanaryMonetaryBudgetV1",
            "maximum_usd_cost_microunits": 1,
            "maximum_cny_cost_microunits": 1,
            "approved_fx_snapshot": None,
        },
        "price_catalog_sha256": "1" * 64,
        "call_topology_sha256": "2" * 64,
        "elapsed_budget_sha256": "3" * 64,
        "worst_case_chargeable": True,
    })
    payload["launcher_sha256"] = validate_import_closure(
        Path(__file__).parents[2] / "tools" / "canary",
    )["launcher_sha256"]
    real_plan = build_canary_experiment_plan_v1(payload)
    real_approval_data = approval_payload(real_plan)
    real_approval_data["approval_scope"] = "C0B_REAL_PROVIDER_PATH_REACHABILITY"
    real_approval_data["authorized_actions"]["fake_boundary"] = False
    real_approval_data["execution_window"] = {
        "not_before": "2020-01-01T00:00:00Z",
        "not_after": "2029-12-31T23:59:59Z",
    }
    real_approval = build_canary_plan_approval_v1(real_approval_data)
    plan_path.write_text(json.dumps(real_plan), encoding="utf-8")
    approval_path.write_text(json.dumps(real_approval), encoding="utf-8")
    real_result = validate_packet(
            plan_path=plan_path, approval_path=approval_path,
            cli_approved_plan_sha256=real_plan["plan_sha256"],
        )
    assert real_result["canary_mode"] == "c0b_real_path_reachability"
    with pytest.raises(CanaryLauncherError, match="real_mode_final_authorization_missing"):
        validate_packet(
            plan_path=plan_path, approval_path=approval_path,
            cli_approved_plan_sha256=real_plan["plan_sha256"],
            execution_requested=True,
        )
