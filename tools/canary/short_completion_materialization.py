"""Offline-only materialization for the short_completion_1 profile."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_profiles import SHORT_COMPLETION_PROFILE_ID, approval_profile
from .approval_store import initialize_approval_ledger_v1
from .artifact_hash import file_sha256, live_parity_manifest
from .c0b_packet import prepare_c0b_smoke_packet
from .contracts import build_canary_experiment_plan_v1
from .fingerprint_profiles import (
    PRODUCTION_MIRROR_SHORT_PROFILE_ID,
    fingerprint_collection_profile_definitions_v1,
)
from .ptr3_readiness import (
    build_ptr3_readiness_v1,
    build_r1_d3_successor_readiness_v1,
)
from .network_sentinel import FailClosedNetworkSentinel
from .short_completion import COMPLETION_GOAL, completion_contract_bundle_v1
from .short_completion_approval import (
    build_short_completion_candidate_v1,
    build_short_completion_patch_template_v1,
)
from .short_completion_closure import validate_short_completion_approval_closure


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


def _definition(schema: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {"schema": schema, "version": 1, **payload}
    return {
        **body,
        "definition_sha256": domain_sha256(
            f"novel-flywheel-short-completion:{schema}", body,
        ),
    }


def short_completion_budget_definitions_v1() -> dict[str, dict[str, Any]]:
    call = _definition("ShortCompletionCallBudgetV1", {
        "maximum_runs": 1, "expected_model_calls": 16,
        "maximum_model_calls_per_run": 48,
        "maximum_total_model_calls": 48,
        "maximum_output_tokens_per_call": 32_000,
        "first_terminal_stop": True, "resume_after_terminal": False,
        "second_run_allowed": False,
    })
    token = _definition("ShortCompletionTokenBudgetV1", {
        "maximum_input_tokens": 1_000_000,
        "maximum_output_tokens": 1_000_000,
        "maximum_output_tokens_per_call": 32_000,
    })
    monetary = _definition("ShortCompletionMonetaryBudgetV1", {
        "maximum_usd_cost_microunits": 20_000_000,
        "maximum_cny_cost_microunits": 50_000_000,
        "approved_fx_snapshot": None,
    })
    elapsed = _definition("ShortCompletionElapsedBudgetV1", {
        "maximum_elapsed_seconds": 7_200,
    })
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
    return {"call": call, "token": token, "monetary": monetary,
            "elapsed": elapsed, "approved": approved}


def materialize_short_completion_1(
    *, live_database_path: Path, live_project_root: Path,
    fixture_path: Path, output_root: Path, cohort_id: str,
    run_namespace: str, artifact_root_label: str,
    approval_ledger_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize inert documents only; never sign, reserve, or execute."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current + timedelta(minutes=15)
    window_end = window_start + timedelta(hours=48)
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    definitions = completion_contract_bundle_v1()
    budget_definitions = short_completion_budget_definitions_v1()
    paths = {
        "plan": output_root / "short-completion-1-final-plan-v1.json",
        "candidate": output_root / "short-completion-1-final-approval-candidate-v1.json",
        "patch_template": output_root / "short-completion-1-authorization-patch-template-v1.json",
        "validate_receipt": output_root / "short-completion-1-validate-only-receipt-v1.json",
        "preview": output_root / "short-completion-1-execution-preview-v1.json",
        "definitions": output_root / "short-completion-1-definitions-v1.json",
        "index": output_root / "short-completion-1-materialization-index-v1.json",
        "ledger_readiness": output_root / "short-completion-1-ledger-operational-readiness-v1.json",
        "semantic_rehearsal": output_root / "short-completion-1-pre-launch-semantic-rehearsal-v1.json",
        "r1_d3_readiness": output_root / "short-completion-1-r1-d3-production-mirror-readiness-v1.json",
        "ptr3_readiness": output_root / "short-completion-1-ptr3-readiness-v1.json",
    }
    before = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )
    sentinel = FailClosedNetworkSentinel()
    with tempfile.TemporaryDirectory(prefix="novel-short-completion-materialize-") as temporary:
        temporary_root = Path(temporary)
        with sentinel:
            base_plan, _approval, _packet = prepare_c0b_smoke_packet(
                live_database_path=live_database_path,
                fixture_path=fixture_path,
                plan_path=temporary_root / "base-plan.json",
                approval_path=temporary_root / "base-approval.json",
                packet_path=temporary_root / "base-packet.json",
                cohort_id=cohort_id, run_namespace=run_namespace, now=current,
                feature_flags=profile.required_flags(),
            )
        payload = deepcopy(base_plan)
        payload.pop("plan_sha256")
        payload["canary_mode"] = "short_completion"
        payload["feature_flag_snapshot"] = profile.required_flags()
        payload["workloads"][0].update({
            "maximum_model_calls": 48,
            "maximum_output_tokens": 1_000_000,
            "success_definition": COMPLETION_GOAL,
            "controlled_outcomes": [],
            "terminal_outcomes": ["workflow_terminal"],
        })
        payload["budgets"].update({
            "maximum_runs": 1,
            "expected_model_calls": 16,
            "maximum_model_calls_per_run": 48,
            "maximum_total_model_calls": 48,
            "maximum_input_tokens": 1_000_000,
            "maximum_output_tokens": 1_000_000,
            "maximum_output_tokens_per_call": 32_000,
            "maximum_elapsed_seconds": 7_200,
            "monetary_budget": {
                "schema": "CanaryMonetaryBudgetV1",
                "maximum_usd_cost_microunits": 20_000_000,
                "maximum_cny_cost_microunits": 50_000_000,
                "approved_fx_snapshot": None,
            },
        })
        payload["stop_conditions"] = list(profile.stop_condition_policy)
        repo_root = Path(__file__).resolve().parents[2]
        planning_validator_sha256 = domain_sha256(
            "ptr3-planning-domain-validator-v1",
            {
                "planning_adaptation_source": file_sha256(
                    repo_root / "src/novel_flywheel/planning_adaptation.py"
                ),
                "validator_id": "planning_repair_patch.normalize.v1",
            },
        )
        ptr3_readiness = build_ptr3_readiness_v1(
            repo_root=repo_root, production_plan=payload,
            planning_domain_validator_sha256=planning_validator_sha256,
        )
        readiness = build_r1_d3_successor_readiness_v1(
            repo_root=Path(__file__).resolve().parents[2],
            production_plan=payload,
            draft_validator_sha256=definitions["draft_validator_policy"][
                "definition_sha256"
            ],
            mixed_script_sha256=definitions["mixed_script_policy"][
                "definition_sha256"
            ],
        )
        policy = {
            "profile_id": profile.profile_id,
            "approval_scope": profile.approval_scope,
            "profile_definition_sha256": profile.profile_definition_sha256,
            "completion_goal": COMPLETION_GOAL,
            "stop_condition_manifest_hash": definitions["stop_conditions"]["definition_sha256"],
            "draft_validator_policy_sha256": definitions["draft_validator_policy"]["definition_sha256"],
            "mixed_script_policy_sha256": definitions["mixed_script_policy"]["definition_sha256"],
            "final_review_definition_sha256": definitions["final_review"]["definition_sha256"],
            "maintenance_definition_sha256": definitions["maintenance"]["definition_sha256"],
            "final_artifact_policy_sha256": definitions["final_artifact"]["definition_sha256"],
            "final_checkpoint_policy_sha256": definitions["final_checkpoint"]["definition_sha256"],
            "completion_goal_definition_sha256": definitions["completion_goal"]["definition_sha256"],
            "second_run_allowed": False,
            "execution_collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "r1_d3_production_mirror_readiness_sha256": readiness[
                "definition_sha256"
            ],
            "r1_d3_production_mirror_readiness": readiness,
            "ptr3_readiness_sha256": ptr3_readiness["definition_sha256"],
            "ptr3_readiness": ptr3_readiness,
        }
        payload["short_completion_policy"] = policy
        plan = build_canary_experiment_plan_v1(payload)
        ledger_root = approval_ledger_root or (
            output_root.parent / f"approval-ledger-{cohort_id}"
        )
        ledger_readiness = initialize_approval_ledger_v1(
            ledger_root,
            ledger_identity=plan["isolation"]["approval_ledger_identity"],
        )
        workload = plan["workloads"][0]
        feature_hash = domain_sha256(
            "novel-flywheel-short-completion-feature-flags-v1",
            plan["feature_flag_snapshot"],
        )
        candidate = build_short_completion_candidate_v1({
            "approval_scope": profile.approval_scope,
            "approved_plan_sha256": plan["plan_sha256"],
            "approved_launcher_sha256": plan["launcher_sha256"],
            "approved_workload_sha256": workload["fixture_sha256"],
            "approved_workload_manifest_hash": plan["workload_manifest_hash"],
            "approved_build_fingerprint": plan["approved_build_fingerprint"],
            "approved_execution_config_fingerprint": plan["approved_execution_config_fingerprint"],
            "approved_runtime_execution_fingerprint": plan["expected_runtime_execution_fingerprint"],
            "provider_descriptor_hash": plan["provider_descriptor_definition_sha256"],
            "model_role_binding_manifest_hash": plan["role_binding_manifest_definition_sha256"],
            "pricing_evidence_manifest_hash": plan["budgets"]["price_catalog_sha256"],
            "feature_flag_snapshot_hash": feature_hash,
            "prompt_policy_manifest_sha256": workload["prompt_policy_manifest_sha256"],
            "canary_root_identity": plan["isolation"]["stable_root_identity"],
            "call_budget_definition_sha256": budget_definitions["call"]["definition_sha256"],
            "token_budget_definition_sha256": budget_definitions["token"]["definition_sha256"],
            "monetary_budget_definition_sha256": budget_definitions["monetary"]["definition_sha256"],
            "elapsed_budget_definition_sha256": budget_definitions["elapsed"]["definition_sha256"],
            **{key: policy[key] for key in (
                "stop_condition_manifest_hash", "draft_validator_policy_sha256",
                "mixed_script_policy_sha256", "final_review_definition_sha256",
                "maintenance_definition_sha256", "final_artifact_policy_sha256",
                "final_checkpoint_policy_sha256", "completion_goal_definition_sha256",
            )},
            "execution_collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "r1_d3_production_mirror_readiness_sha256": readiness[
                "definition_sha256"
            ],
            "ptr3_readiness_sha256": ptr3_readiness["definition_sha256"],
            "approved_workload_id": workload["workload_id"],
            "runtime_mode": plan["runtime_mode"],
            "maximum_runs": 1, "expected_model_calls": 16,
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
                "not_before": _utc(window_start), "not_after": _utc(window_end),
            },
            "approval_expiry": _utc(window_end),
            "single_use_cohort_id": cohort_id,
            "maximum_executions": 1, "usage_status": "unused",
            "consumed_evidence_sha256": None,
            "named_approver": "USER_CONFIRMATION_REQUIRED",
            "authorized_actions": {
                "credential_lookup": False, "provider_client_creation": False,
                "network": False, "paid_model_calls": False,
                "fake_boundary": False,
            },
            "execution_authorized": False,
            "status": "waiting_for_final_user_authorization",
        })
        patch_template = build_short_completion_patch_template_v1(candidate)
        label = artifact_root_label.rstrip("/")
        preview_body = {
            "schema": "ShortCompletionExecutionPreviewV1", "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "profile_id": profile.profile_id,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_candidate_sha256": candidate["approval_candidate_sha256"],
            "bound_patch_template_sha256": patch_template["authorization_patch_template_sha256"],
            "execution_collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "r1_d3_production_mirror_readiness_sha256": readiness[
                "definition_sha256"
            ],
            "ptr3_readiness_sha256": ptr3_readiness["definition_sha256"],
            "future_signed_approval_schema": profile.signed_approval_schema,
            "future_signed_approval_file": "${SHORT_COMPLETION_SIGNED_APPROVAL}",
            "plan_file": f"{label}/{paths['plan'].name}",
            "candidate_file": f"{label}/{paths['candidate'].name}",
            "patch_template_file": f"{label}/{paths['patch_template'].name}",
            "future_command_argv": [
                ".venv/Scripts/python.exe", "-m", "tools.canary.launcher",
                "--plan", f"{label}/{paths['plan'].name}",
                "--approval", "${SHORT_COMPLETION_SIGNED_APPROVAL}",
                "--approval-candidate", f"{label}/{paths['candidate'].name}",
                "--authorization-patch", "${SHORT_COMPLETION_CONFIRMED_PATCH}",
                "--approved-plan-sha256", plan["plan_sha256"], "--real-run",
                "--workload-fixture", "tests/fixtures/canary/short-normal-v1.json",
                "--canary-root", "${SHORT_COMPLETION_CANARY_ROOT}",
                "--approval-ledger-root", "${SHORT_COMPLETION_APPROVAL_LEDGER}",
                "--live-database", "data/app.db",
                "--live-project-root", "data/projects",
            ],
            "execution_authorized": False, "do_not_execute": True,
        }
        preview = {**preview_body, "preview_sha256": domain_sha256(
            "novel-flywheel-short-completion-preview-v1", preview_body,
        )}
        definitions_document = {
            "schema": "ShortCompletionDefinitionBundleV1", "version": 1,
            "definitions": definitions, "budgets": budget_definitions,
            "fingerprint_collection_profiles": (
                fingerprint_collection_profile_definitions_v1()
            ),
            "r1_d3_production_mirror_readiness": readiness,
            "ptr3_readiness": ptr3_readiness,
        }
        definitions_document["bundle_sha256"] = domain_sha256(
            "novel-flywheel-short-completion-definition-bundle-v1",
            definitions_document,
        )
        for key, value in (("plan", plan), ("candidate", candidate),
                           ("patch_template", patch_template),
                           ("preview", preview),
                           ("definitions", definitions_document)):
            _write(paths[key], value)
        _write(paths["r1_d3_readiness"], readiness)
        _write(paths["ptr3_readiness"], ptr3_readiness)
        _write(paths["ledger_readiness"], ledger_readiness)
        rehearsal_output = temporary_root / "semantic-rehearsal.json"
        rehearsal_root = temporary_root / "semantic-rehearsal-root"
        completed = subprocess.run(
            [
                sys.executable, "-m", "tools.canary.semantic_rehearsal",
                "--plan", str(paths["plan"]),
                "--fixture", str(fixture_path),
                "--live-database", str(live_database_path),
                "--isolated-root", str(rehearsal_root),
                "--output", str(rehearsal_output),
            ],
            cwd=Path(__file__).resolve().parents[2],
            check=False, capture_output=True, text=True, timeout=120,
        )
        if completed.returncode != 0 or not rehearsal_output.is_file():
            raise RuntimeError("prelaunch_semantic_rehearsal_failed")
        semantic_rehearsal = json.loads(
            rehearsal_output.read_text(encoding="utf-8")
        )
        _write(paths["semantic_rehearsal"], semantic_rehearsal)
        validation = validate_short_completion_approval_closure(
            plan_path=paths["plan"], approval_path=paths["candidate"],
            source_candidate_path=None, source_authorization_patch_path=None,
            packet_path=None, workload_fixture_path=fixture_path,
            live_database_path=live_database_path,
            live_project_root=live_project_root,
            canary_root=temporary_root / "future-canary-root",
            approval_ledger_root=ledger_root,
            cli_approved_plan_sha256=plan["plan_sha256"], now=current,
        )
        _write(paths["validate_receipt"], validation)
    after = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )
    if before["parity_sha256"] != after["parity_sha256"]:
        raise RuntimeError("materialization_live_parity_changed")
    if sentinel.network_call_count:
        raise RuntimeError("materialization_network_call_observed")
    index_body = {
        "schema": "ShortCompletionMaterializationIndexV1", "version": 1,
        "contract_status": "SHORT_COMPLETION_APPROVAL_PROFILE_READY",
        "status": "SHORT_COMPLETION_CANARY_WAITING_FOR_FINAL_USER_AUTHORIZATION",
        "files": {path.name: file_sha256(path) for path in sorted(
            (item for key, item in paths.items() if key != "index"),
            key=lambda item: item.name,
        )},
        "plan_sha256": plan["plan_sha256"],
        "approval_candidate_sha256": candidate["approval_candidate_sha256"],
        "launcher_sha256": plan["launcher_sha256"],
        "single_use_cohort_id": cohort_id,
        "execution_window": candidate["execution_window"],
        "validation_receipt_sha256": validation["validation_receipt_sha256"],
        "external_action_counters": validation["external_action_counters"],
        "approval_ledger_identity": plan["isolation"]["approval_ledger_identity"],
        "approval_ledger_initial_entry_count": ledger_readiness["initial_entry_count"],
        "approval_ledger_operational_readiness": ledger_readiness["status"],
        "prelaunch_semantic_rehearsal_sha256": semantic_rehearsal["receipt_sha256"],
        "prelaunch_semantic_rehearsal_status": semantic_rehearsal["status"],
        "r1_d3_production_mirror_readiness_sha256": readiness[
            "definition_sha256"
        ],
        "ptr3_readiness_sha256": ptr3_readiness["definition_sha256"],
        "execution_collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
        "live_parity_before_sha256": before["parity_sha256"],
        "live_parity_after_sha256": after["parity_sha256"],
        "signed_approval_materialized": False,
        "execution_performed": False,
    }
    index = {**index_body, "definition_sha256": domain_sha256(
        "novel-flywheel-short-completion-materialization-index-v1", index_body,
    )}
    _write(paths["index"], index)
    return {
        "plan": plan, "approval_candidate": candidate,
        "authorization_patch_template": patch_template,
        "validation_receipt": validation, "execution_preview": preview,
        "definitions": definitions_document, "index": index, "paths": paths,
        "ledger_readiness": ledger_readiness,
        "semantic_rehearsal": semantic_rehearsal,
        "r1_d3_production_mirror_readiness": readiness,
        "ptr3_readiness": ptr3_readiness,
        "approval_ledger_root": ledger_root,
        "network_call_count": sentinel.network_call_count,
        "execution_performed": False,
    }
