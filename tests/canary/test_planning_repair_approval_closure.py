from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from novel_flywheel.runtime_fingerprint_build import domain_sha256
import tools.canary.planning_repair_closure as closure

from tools.canary.approval_dispatch import (
    materialize_signed_canary_approval,
)
from tools.canary.approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
)
from tools.canary.planning_repair_approval import (
    materialize_planning_repair_observation_patch_v1,
)
from tools.canary.planning_repair_observation import (
    materialize_planning_repair_observation_1,
)
from tools.canary.launcher import CanaryLauncherError, _validate_registered_closure


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


ZERO_ACTIONS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}


@pytest.fixture(scope="module")
def signed_packet(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp_path = tmp_path_factory.mktemp("planning-repair-closure")
    approval_now = datetime.now(timezone.utc).replace(microsecond=0)
    materialized_at = approval_now - timedelta(minutes=16)
    output = tmp_path / "packet"
    ledger = tmp_path / "ledger"
    cohort = "planning-repair-observation-1-20260817t060000z-test"
    materialized = materialize_planning_repair_observation_1(
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=output,
        approval_ledger_root=ledger,
        cohort_id=cohort,
        run_namespace=cohort,
        artifact_root_label="reports/r1-ptr2-v1-test",
        now=materialized_at,
    )
    approval_time = approval_now.isoformat().replace("+00:00", "Z")
    patch = materialize_planning_repair_observation_patch_v1(
        materialized["authorization_patch_template"],
        named_approver="test_project_owner",
        approval_timestamp=approval_time,
    )
    signed = materialize_signed_canary_approval(
        PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
        materialized["approval_candidate"],
        patch,
        now=datetime.fromisoformat(approval_time.replace("Z", "+00:00")),
    )
    patch_path = output / "confirmed-patch.json"
    signed_path = output / "signed-approval.json"
    _write(patch_path, patch)
    _write(signed_path, signed)
    return {
        "root": tmp_path,
        "output": output,
        "ledger": ledger,
        "materialized": materialized,
        "patch_path": patch_path,
        "signed_path": signed_path,
        "approval_now": approval_now,
        "cohort": cohort,
    }


def _closure_kwargs(packet: dict, *, root: Path | None = None) -> dict:
    materialized = packet["materialized"]
    output = root or packet["output"]
    return {
        "plan_path": output / materialized["paths"]["plan"].name,
        "approval_path": output / packet["signed_path"].name,
        "source_candidate_path": output / materialized["paths"]["candidate"].name,
        "source_authorization_patch_path": output / packet["patch_path"].name,
        "packet_path": output / materialized["paths"]["index"].name,
        "workload_fixture_path": FIXTURE,
        "live_database_path": LIVE_DB,
        "live_project_root": LIVE_PROJECTS,
        "canary_root": packet["root"] / "future-canary-root",
        "approval_ledger_root": packet["ledger"],
        "cli_approved_plan_sha256": materialized["plan"]["plan_sha256"],
        "now": packet["approval_now"],
    }


def _launcher_command(packet: dict) -> list[str]:
    materialized = packet["materialized"]
    return [
        sys.executable,
        "-m",
        "tools.canary.launcher",
        "--plan",
        str(materialized["paths"]["plan"]),
        "--approval",
        str(packet["signed_path"]),
        "--approval-candidate",
        str(materialized["paths"]["candidate"]),
        "--authorization-patch",
        str(packet["patch_path"]),
        "--approved-plan-sha256",
        materialized["plan"]["plan_sha256"],
        "--validate-only",
        "--approval-packet",
        str(materialized["paths"]["index"]),
        "--workload-fixture",
        str(FIXTURE),
        "--canary-root",
        str(packet["root"] / "future-canary-root"),
        "--approval-ledger-root",
        str(packet["ledger"]),
        "--live-database",
        str(LIVE_DB),
        "--live-project-root",
        str(LIVE_PROJECTS),
    ]


def test_registered_planning_repair_signed_validate_only_is_exact(
    signed_packet: dict,
) -> None:
    packet = signed_packet
    materialized = packet["materialized"]

    completed = subprocess.run(
        _launcher_command(packet),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 0, result
    assert result["overall_status"] == "exact"
    assert result["approval_state"] == "signed_approval_exact_and_executable"
    assert result["external_action_counters"] == ZERO_ACTIONS
    assert result["execution_performed"] is False
    assert not (packet["root"] / "future-canary-root").exists()


NEGATIVE_CASES = (
    "candidate_hash_tamper",
    "candidate_profile_mismatch",
    "patch_protected_field_tamper",
    "signed_binding_tamper",
    "plan_mismatch",
    "malformed_plan_profile",
    "launcher_mismatch",
    "build_mismatch",
    "config_mismatch",
    "runtime_mismatch",
    "prompt_request_mismatch",
    "route_model_mismatch",
    "domain_validator_mismatch",
    "target_filter_mismatch",
    "observation_goal_mismatch",
    "instrumentation_definition_mismatch",
    "diagnostic_flag_false",
    "unexpected_diagnostic_flag_true",
    "retry_fallback_mismatch",
    "production_budget_policy_mismatch",
    "outer_budget_increase",
    "window_expired",
    "window_not_started",
    "cohort_consumed",
    "ledger_reserved_or_nonempty",
    "privacy_violation",
    "live_parity_mismatch",
    "handler_version_mismatch",
)


@pytest.mark.parametrize("case", NEGATIVE_CASES)
def test_planning_repair_closure_tamper_matrix_blocks_without_external_actions(
    case: str,
    signed_packet: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = signed_packet
    copied = tmp_path / "packet"
    shutil.copytree(packet["output"], copied)
    kwargs = _closure_kwargs(packet, root=copied)

    plan_path = kwargs["plan_path"]
    candidate_path = kwargs["source_candidate_path"]
    patch_path = kwargs["source_authorization_patch_path"]
    signed_path = kwargs["approval_path"]
    index_path = kwargs["packet_path"]

    if case in {"candidate_hash_tamper", "candidate_profile_mismatch"}:
        value = json.loads(candidate_path.read_text(encoding="utf-8"))
        if case == "candidate_hash_tamper":
            value["approved_workload_id"] = "tampered"
        else:
            value["profile_id"] = "short_completion_1"
        _write(candidate_path, value)
    elif case == "patch_protected_field_tamper":
        value = json.loads(patch_path.read_text(encoding="utf-8"))
        value["bound_plan_sha256"] = "0" * 64
        _write(patch_path, value)
    elif case == "signed_binding_tamper":
        value = json.loads(signed_path.read_text(encoding="utf-8"))
        value["source_candidate_sha256"] = "0" * 64
        _write(signed_path, value)
    elif case == "plan_mismatch":
        kwargs["cli_approved_plan_sha256"] = "0" * 64
    elif case == "malformed_plan_profile":
        value = json.loads(plan_path.read_text(encoding="utf-8"))
        value["canary_mode"] = "malformed_profile"
        _write(plan_path, value)
    elif case == "launcher_mismatch":
        value = json.loads(plan_path.read_text(encoding="utf-8"))
        value["launcher_sha256"] = "0" * 64
        _write(plan_path, value)
    elif case in {
        "build_mismatch", "config_mismatch", "runtime_mismatch",
        "prompt_request_mismatch", "route_model_mismatch",
    }:
        original = closure._prepare_base

        def drifted_base(**values):
            fresh = original(**values)
            field = {
                "build_mismatch": "approved_build_fingerprint",
                "config_mismatch": "approved_execution_config_fingerprint",
                "runtime_mismatch": "expected_runtime_execution_fingerprint",
                "route_model_mismatch": "role_binding_manifest_definition_sha256",
            }.get(case)
            if field is not None:
                fresh[field] = "0" * 64
            else:
                fresh["workloads"][0]["prompt_policy_manifest_sha256"] = "0" * 64
            return fresh

        monkeypatch.setattr(closure, "_prepare_base", drifted_base)
    elif case in {
        "domain_validator_mismatch", "observation_goal_mismatch",
        "instrumentation_definition_mismatch",
        "production_budget_policy_mismatch",
    }:
        original = closure._definitions

        def drifted_definitions():
            values = original()
            target = {
                "domain_validator_mismatch": "validator",
                "observation_goal_mismatch": "goal",
                "production_budget_policy_mismatch": "production_budget",
            }.get(case)
            if target is not None:
                values[target]["definition_sha256"] = "0" * 64
            else:
                values["instrumentation"]["definitions"][
                    "domain_validation"
                ]["definition_sha256"] = "0" * 64
            return values

        monkeypatch.setattr(closure, "_definitions", drifted_definitions)
    elif case == "target_filter_mismatch":
        monkeypatch.setattr(closure, "TARGET", {**closure.TARGET, "stage": "draft"})
    elif case == "diagnostic_flag_false":
        monkeypatch.setattr(closure, "FEATURE_FLAGS", {
            **closure.FEATURE_FLAGS,
            "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1": False,
        })
    elif case == "unexpected_diagnostic_flag_true":
        monkeypatch.setattr(closure, "FEATURE_FLAGS", {
            **closure.FEATURE_FLAGS,
            "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1": True,
        })
    elif case in {"retry_fallback_mismatch", "outer_budget_increase"}:
        value = json.loads(plan_path.read_text(encoding="utf-8"))
        if case == "retry_fallback_mismatch":
            value["planning_repair_observation_policy"][
                "production_retry_fallback_mutation_allowed"
            ] = True
        else:
            value["budgets"]["maximum_total_model_calls"] += 1
        _write(plan_path, value)
    elif case in {"window_expired", "window_not_started"}:
        signed = json.loads(signed_path.read_text(encoding="utf-8"))
        key = "not_after" if case == "window_expired" else "not_before"
        moment = datetime.fromisoformat(
            signed["execution_window"][key].replace("Z", "+00:00")
        )
        kwargs["now"] = moment + (
            timedelta(seconds=1) if case == "window_expired"
            else -timedelta(seconds=1)
        )
    elif case in {"cohort_consumed", "ledger_reserved_or_nonempty"}:
        ledger = tmp_path / "ledger"
        shutil.copytree(packet["ledger"], ledger)
        suffix = "consumed" if case == "cohort_consumed" else "reserved"
        (ledger / f"{packet['cohort']}.{suffix}.json").write_text(
            "{}\n", encoding="utf-8",
        )
        kwargs["approval_ledger_root"] = ledger
    elif case == "privacy_violation":
        monkeypatch.setattr(closure, "_privacy_scan", lambda *_args, **_kwargs: {
            "status": "blocked",
            "privacy_scan_sha256": "0" * 64,
        })
    elif case == "live_parity_mismatch":
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["live_parity_sha256"] = "0" * 64
        body = {key: value for key, value in index.items()
                if key != "definition_sha256"}
        index["definition_sha256"] = domain_sha256(
            "novel-flywheel-r1-ptr2-materialization-index-v1", body,
        )
        _write(index_path, index)
    elif case == "handler_version_mismatch":
        original = closure.planning_repair_observation_closure_definition_v1

        def drifted_closure_definition():
            value = original()
            value["definition_sha256"] = "0" * 64
            return value

        monkeypatch.setattr(
            closure,
            "planning_repair_observation_closure_definition_v1",
            drifted_closure_definition,
        )
    else:  # pragma: no cover - the closed matrix must stay exhaustive.
        raise AssertionError(case)

    result = closure.validate_planning_repair_observation_closure(**kwargs)
    assert result["overall_status"] == "blocked", case
    assert result["external_action_counters"] == ZERO_ACTIONS
    assert result["execution_performed"] is False
    assert not kwargs["canary_root"].exists()


@pytest.mark.parametrize("profile_name", [
    "unknown_profile",
    "missing_closure_profile_v1",
    "planning_repair_observation_closure_v2",
])
def test_unknown_missing_or_versioned_closure_profile_remains_fail_closed(
    profile_name: str,
) -> None:
    with pytest.raises(
        CanaryLauncherError,
        match="validate_only_profile_not_supported",
    ):
        _validate_registered_closure(profile_name)
