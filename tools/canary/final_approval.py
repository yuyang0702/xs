"""Materialize a disabled, hash-bound C0B-SMOKE-1 Approval candidate."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from typing import Any

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_closure import validate_c0b_approval_closure
from .artifact_hash import file_sha256
from .c0b_packet import prepare_c0b_smoke_packet
from .contracts import (
    SMOKE_APPROVAL_SCOPE,
    build_canary_experiment_plan_v1,
    build_c0b_smoke_1_final_approval_candidate_v2,
    build_c0b_smoke_1_user_authorization_patch_v2,
)
from .network_sentinel import FailClosedNetworkSentinel


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z",
    )


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _definition(domain: str, schema: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {"schema": schema, "version": 1, **payload}
    return {
        **body,
        "definition_sha256": domain_sha256(domain, body),
    }


def _budget_definitions() -> dict[str, dict[str, Any]]:
    call = _definition(
        "novel-flywheel-c0b-smoke-1-call-budget-v1",
        "C0BSmoke1CallBudgetV1", {
            "maximum_runs": 1, "expected_model_calls": 16,
            "maximum_model_calls_per_run": 48,
            "maximum_total_model_calls": 48,
            "maximum_output_tokens_per_call": 32_000,
            "first_terminal_stop": True, "resume_after_terminal": False,
        },
    )
    token = _definition(
        "novel-flywheel-c0b-smoke-1-token-budget-v1",
        "C0BSmoke1TokenBudgetV1", {
            "maximum_input_tokens": 1_000_000,
            "maximum_output_tokens": 1_000_000,
            "maximum_output_tokens_per_call": 32_000,
        },
    )
    monetary = _definition(
        "novel-flywheel-c0b-smoke-1-monetary-budget-v1",
        "C0BSmoke1MonetaryBudgetV1", {
            "maximum_usd_cost_microunits": 20_000_000,
            "maximum_cny_cost_microunits": 50_000_000,
            "currency_conversion": "none", "approved_fx_snapshot": None,
        },
    )
    elapsed = _definition(
        "novel-flywheel-c0b-smoke-1-elapsed-budget-v1",
        "C0BSmoke1ElapsedBudgetV1", {"maximum_elapsed_seconds": 7_200},
    )
    approved_body = {
        "maximum_model_calls_per_run": 48,
        "maximum_total_model_calls": 48,
        "maximum_input_tokens": 1_000_000,
        "maximum_output_tokens": 1_000_000,
        "maximum_usd_cost_microunits": 20_000_000,
        "maximum_cny_cost_microunits": 50_000_000,
        "maximum_elapsed_seconds": 7_200,
    }
    approved = {
        **approved_body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-approved-budget-v1", approved_body,
        ),
    }
    return {
        "call": call, "token": token, "monetary": monetary,
        "elapsed": elapsed, "approved": approved,
    }


def materialize_c0b_smoke_1_final_approval_v2(
    *, live_database_path: Path, live_project_root: Path,
    fixture_path: Path, output_root: Path, cohort_id: str,
    run_namespace: str, artifact_root_label: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate and validate a non-executable candidate; never reserve Approval."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current + timedelta(minutes=15)
    window_end = window_start + timedelta(hours=48)
    paths = {
        "plan": output_root / "c0b-smoke-1-final-plan-v2.json",
        "approval_candidate": output_root / "c0b-smoke-1-final-approval-candidate-v2.json",
        "user_authorization_patch": output_root / "c0b-smoke-1-user-authorization-patch-v2.json",
        "execution_command_preview": output_root / "c0b-smoke-1-execution-command-preview-v1.json",
        "packet": output_root / "c0b-smoke-1-final-packet-v2.json",
        "validation_receipt": output_root / "c0b-smoke-1-final-validate-only-receipt-v2.json",
        "index": output_root / "c0b-smoke-1-final-materialization-index-v2.json",
    }
    budgets = _budget_definitions()
    sentinel = FailClosedNetworkSentinel()
    with tempfile.TemporaryDirectory(prefix="novel-c0b-final-materialize-") as temporary:
        temporary_root = Path(temporary)
        with sentinel:
            base_plan, _base_approval, base_packet = prepare_c0b_smoke_packet(
                live_database_path=live_database_path,
                fixture_path=fixture_path,
                plan_path=temporary_root / "base-plan.json",
                approval_path=temporary_root / "base-approval.json",
                packet_path=temporary_root / "base-packet.json",
                cohort_id=cohort_id, run_namespace=run_namespace, now=current,
            )
        plan_payload = deepcopy(base_plan)
        plan_payload.pop("plan_sha256")
        plan_payload["workloads"][0]["maximum_model_calls"] = 48
        plan_payload["workloads"][0]["maximum_output_tokens"] = 1_000_000
        plan_payload["smoke_1_policy"] = {
            "approval_scope": SMOKE_APPROVAL_SCOPE,
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
            "budget_definition_hashes": {
                name: budgets[name]["definition_sha256"]
                for name in ("call", "token", "monetary", "elapsed")
            },
        }
        plan = build_canary_experiment_plan_v1(plan_payload)
        feature_hash = domain_sha256(
            "novel-flywheel-c0b-feature-flags-v1",
            plan["feature_flag_snapshot"],
        )
        stop_hash = domain_sha256(
            "novel-flywheel-c0b-stop-conditions-v1",
            plan["stop_conditions"],
        )
        workload = plan["workloads"][0]
        candidate = build_c0b_smoke_1_final_approval_candidate_v2({
            "approval_scope": SMOKE_APPROVAL_SCOPE,
            "approved_plan_sha256": plan["plan_sha256"],
            "approved_launcher_sha256": plan["launcher_sha256"],
            "approved_workload_sha256": workload["fixture_sha256"],
            "approved_workload_manifest_hash": plan["workload_manifest_hash"],
            "approved_build_fingerprint": plan["approved_build_fingerprint"],
            "approved_execution_config_fingerprint": plan[
                "approved_execution_config_fingerprint"
            ],
            "approved_runtime_execution_fingerprint": plan[
                "expected_runtime_execution_fingerprint"
            ],
            "runtime_mode": plan["runtime_mode"],
            "provider_descriptor_hash": plan[
                "provider_descriptor_definition_sha256"
            ],
            "model_role_binding_manifest_hash": plan[
                "role_binding_manifest_definition_sha256"
            ],
            "pricing_evidence_manifest_hash": plan["budgets"][
                "price_catalog_sha256"
            ],
            "feature_flag_snapshot_hash": feature_hash,
            "stop_condition_manifest_hash": stop_hash,
            "call_budget_definition_sha256": budgets["call"]["definition_sha256"],
            "token_budget_definition_sha256": budgets["token"]["definition_sha256"],
            "monetary_budget_definition_sha256": budgets["monetary"]["definition_sha256"],
            "elapsed_budget_definition_sha256": budgets["elapsed"]["definition_sha256"],
            "canary_root_identity_candidate": plan["isolation"]["stable_root_identity"],
            "approved_workload_id": "short-normal-v1",
            "maximum_runs": 1, "expected_model_calls": 16,
            "maximum_total_model_calls": 48,
            "maximum_input_tokens": 1_000_000,
            "maximum_output_tokens": 1_000_000,
            "maximum_output_tokens_per_call": 32_000,
            "maximum_usd_cost_microunits": 20_000_000,
            "maximum_cny_cost_microunits": 50_000_000,
            "maximum_elapsed_seconds": 7_200,
            "first_terminal_stop": True, "resume_after_terminal": False,
            "phase1b_enabled": False,
            "materialized_at": _utc(current),
            "execution_window": {
                "not_before": _utc(window_start), "not_after": _utc(window_end),
            },
            "approval_expiry": _utc(window_end),
            "single_use_cohort_id": cohort_id,
            "maximum_executions": 1, "usage_status": "unused",
            "consumed_evidence_sha256": None,
            "named_approver": "USER_CONFIRMATION_REQUIRED",
            "authorize_credential_lookup": False,
            "authorize_provider_client_creation": False,
            "authorize_network": False,
            "authorize_paid_model_calls": False,
            "authorized_actions": {
                "credential_lookup": False,
                "provider_client_creation": False,
                "network": False,
                "paid_model_calls": False,
                "fake_boundary": False,
            },
            "execution_authorized": False,
            "approved_budget": budgets["approved"],
        })
        patch = build_c0b_smoke_1_user_authorization_patch_v2({
            "approval_scope": SMOKE_APPROVAL_SCOPE,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "bound_launcher_sha256": plan["launcher_sha256"],
            "bound_workload_sha256": workload["fixture_sha256"],
            "bound_build_fingerprint": plan["approved_build_fingerprint"],
            "bound_execution_config_fingerprint": plan[
                "approved_execution_config_fingerprint"
            ],
            "bound_runtime_execution_fingerprint": plan[
                "expected_runtime_execution_fingerprint"
            ],
            "named_approver": "USER_CONFIRMATION_REQUIRED",
            "approval_timestamp": "USER_CONFIRMATION_REQUIRED",
            "approved_execution_window": candidate["execution_window"],
            "approval_expiry": candidate["approval_expiry"],
            "single_use_cohort_id": cohort_id,
            "authorize_credential_lookup": True,
            "authorize_provider_client_creation": True,
            "authorize_network": True,
            "authorize_paid_model_calls": True,
            "execution_authorized": True,
            "protected_fields_mutation_allowed": False,
        })
        label = artifact_root_label.rstrip("/")
        preview_body = {
            "schema": "C0BSmoke1ExecutionCommandPreviewV1", "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "bound_authorization_patch_sha256": patch[
                "authorization_patch_sha256"
            ],
            "bound_launcher_sha256": plan["launcher_sha256"],
            "bound_workload_sha256": workload["fixture_sha256"],
            "single_use_cohort_id": cohort_id,
            "plan_file": f"{label}/{paths['plan'].name}",
            "approval_candidate_file": f"{label}/{paths['approval_candidate'].name}",
            "user_authorization_patch_file": f"{label}/{paths['user_authorization_patch'].name}",
            "future_signed_approval_file": "${C0B_SMOKE_1_SIGNED_APPROVAL}",
            "canary_root": "${C0B_SMOKE_1_CANARY_ROOT}",
            "future_command_argv": [
                ".venv/Scripts/python.exe", "-m", "tools.canary.launcher",
                "--plan", f"{label}/{paths['plan'].name}",
                "--approval", "${C0B_SMOKE_1_SIGNED_APPROVAL}",
                "--approval-candidate", f"{label}/{paths['approval_candidate'].name}",
                "--authorization-patch", "${C0B_SMOKE_1_CONFIRMED_AUTHORIZATION_PATCH}",
                "--approved-plan-sha256", plan["plan_sha256"],
                "--real-run", "--workload-fixture",
                "tests/fixtures/canary/short-normal-v1.json",
                "--canary-root", "${C0B_SMOKE_1_CANARY_ROOT}",
                "--approval-ledger-root", "${C0B_SMOKE_1_APPROVAL_LEDGER_ROOT}",
                "--live-database", "data/app.db",
                "--live-project-root", "data/projects",
            ],
            "execution_authorized": False, "do_not_execute": True,
            "credential_material_included": False,
        }
        preview = {
            **preview_body,
            "preview_sha256": domain_sha256(
                "novel-flywheel-c0b-smoke-1-command-preview-v1", preview_body,
            ),
        }
        packet = deepcopy(base_packet)
        packet.pop("approval_draft_sha256", None)
        packet.update({
            "schema": "C0BSmoke1FinalApprovalPacketV2", "version": 2,
            "contract_status": "C0B_SMOKE_1_SIGNED_APPROVAL_CONTRACT_READY",
            "status": "C0B_SMOKE_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION",
            "plan_sha256": plan["plan_sha256"],
            "approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "authorization_patch_sha256": patch["authorization_patch_sha256"],
            "approval_budget": budgets["approved"],
            "budget_definitions": budgets,
            "feature_flag_snapshot_hash": feature_hash,
            "stop_condition_manifest_hash": stop_hash,
            "candidate_execution_window": candidate["execution_window"],
            "approval_expiry": candidate["approval_expiry"],
            "single_use_cohort_id": cohort_id,
            "execution_authorized": False,
        })
        for key, value in (
            ("plan", plan), ("approval_candidate", candidate),
            ("user_authorization_patch", patch),
            ("execution_command_preview", preview), ("packet", packet),
        ):
            _write(paths[key], value)
        ledger_root = temporary_root / "approval-ledger"
        ledger_root.mkdir()
        validation_receipt = validate_c0b_approval_closure(
            plan_path=paths["plan"], approval_path=paths["approval_candidate"],
            packet_path=paths["packet"], workload_fixture_path=fixture_path,
            live_database_path=live_database_path,
            live_project_root=live_project_root,
            canary_root=temporary_root / "future-canary-root",
            approval_ledger_root=ledger_root,
            cli_approved_plan_sha256=plan["plan_sha256"], now=current,
        )
        _write(paths["validation_receipt"], validation_receipt)
    if sentinel.network_call_count != 0:
        raise RuntimeError("materialization_network_call_observed")
    index_body = {
        "schema": "C0BSmoke1FinalMaterializationIndexV2", "version": 2,
        "contract_status": "C0B_SMOKE_1_SIGNED_APPROVAL_CONTRACT_READY",
        "status": "C0B_SMOKE_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION",
        "files": {
            path.name: file_sha256(path)
            for path in sorted(
                (item for item in paths.values() if item != paths["index"]),
                key=lambda item: item.name,
            )
        },
        "plan_sha256": plan["plan_sha256"],
        "approval_candidate_sha256": candidate["approval_candidate_sha256"],
        "launcher_sha256": plan["launcher_sha256"],
        "validation_receipt_sha256": validation_receipt[
            "validation_receipt_sha256"
        ],
        "external_action_counters": validation_receipt[
            "external_action_counters"
        ],
        "execution_performed": False,
    }
    index = {
        **index_body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-smoke-1-final-index-v2", index_body,
        ),
    }
    _write(paths["index"], index)
    return {
        "plan": plan, "approval_candidate": candidate,
        "user_authorization_patch": patch,
        "execution_command_preview": preview, "packet": packet,
        "validation_receipt": validation_receipt, "index": index,
        "paths": paths, "execution_performed": False,
        "network_call_count": sentinel.network_call_count,
    }


def _parse_utc_argument(value: str) -> datetime:
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("UTC value must end in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize an inert C0B-SMOKE-1 Final Approval Candidate V2",
    )
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-project-root", type=Path, required=True)
    parser.add_argument("--workload-fixture", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--run-namespace", required=True)
    parser.add_argument("--artifact-root-label", required=True)
    parser.add_argument("--materialized-at", type=_parse_utc_argument)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = materialize_c0b_smoke_1_final_approval_v2(
        live_database_path=args.live_database,
        live_project_root=args.live_project_root,
        fixture_path=args.workload_fixture,
        output_root=args.output_root,
        cohort_id=args.cohort_id,
        run_namespace=args.run_namespace,
        artifact_root_label=args.artifact_root_label,
        now=args.materialized_at,
    )
    summary = {
        "status": result["index"]["status"],
        "plan_sha256": result["plan"]["plan_sha256"],
        "approval_candidate_sha256": result["approval_candidate"][
            "approval_candidate_sha256"
        ],
        "validation_status": result["validation_receipt"]["overall_status"],
        "external_action_counters": result["validation_receipt"][
            "external_action_counters"
        ],
        "execution_performed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["validation_status"] == "exact" else 4


if __name__ == "__main__":
    raise SystemExit(main())
