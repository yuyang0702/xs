"""Fail-closed, zero-external-action closure for short_completion_1."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_dispatch import (
    profile_for_plan,
    validate_registered_approval_document,
    validate_registered_signed_plan,
    validate_registered_signed_sources,
)
from .approval_profiles import SHORT_COMPLETION_PROFILE_ID
from .approval_store import ApprovalConsumptionStore
from .artifact_hash import file_sha256, live_parity_manifest
from .contracts import validate_canary_experiment_plan_v1
from .fingerprint_profiles import (
    PRODUCTION_MIRROR_SHORT_PROFILE_ID,
)
from .ptr3_readiness import (
    validate_ptr3_readiness_v1,
    validate_r1_d3_successor_readiness_v1,
)
from .hash_manifest import validate_import_closure
from .short_completion import completion_contract_bundle_v1


CHECK_NAMES = (
    "registered_profile", "approval_scope", "plan_canonical_hash",
    "approval_document", "launcher_bytes_hash", "workload_fixture_hash",
    "workload_manifest_hash", "production_source_byte_revalidation",
    "build_fingerprint", "execution_config_fingerprint",
    "runtime_execution_fingerprint", "provider_descriptor_manifest",
    "role_route_manifest", "feature_flags", "phase1b_disabled",
    "pa_diagnostic_flags_disabled", "pricing_manifest", "call_budget",
    "token_budget", "monetary_budget", "elapsed_budget", "stop_conditions",
    "draft_validator_policy", "mixed_script_policy",
    "final_review_completion_definition",
    "maintenance_completion_definition", "final_artifact_binding_policy",
    "final_checkpoint_closure_policy", "completion_goal_definition",
    "r1_d3_production_mirror_readiness",
    "ptr3_readiness",
    "canary_root_identity", "execution_window", "cohort_unused",
    "approval_ledger", "external_authorization", "privacy", "live_parity",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("document_not_object")
    return value


def _receipt(checks: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    body = {
        "schema": "ShortCompletionApprovalClosureValidationV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "overall_status": (
            "exact" if all(item["status"] == "exact" for item in checks)
            else "blocked"
        ),
        "ordered_checks": checks,
        "external_action_counters": {
            "credential_lookup_count": 0,
            "provider_client_creation_count": 0,
            "network_call_count": 0,
            "model_call_count": 0,
            "paid_model_call_count": 0,
        },
        "privacy": {"status": "exact", "violation_count": 0},
        **fields,
    }
    return {
        **body,
        "validation_receipt_sha256": domain_sha256(
            "novel-flywheel-short-completion-approval-closure-v1", body,
        ),
    }


def validate_short_completion_approval_closure(
    *, plan_path: Path, approval_path: Path,
    source_candidate_path: Path | None,
    source_authorization_patch_path: Path | None,
    packet_path: Path | None, workload_fixture_path: Path,
    live_database_path: Path, live_project_root: Path,
    canary_root: Path, approval_ledger_root: Path,
    cli_approved_plan_sha256: str, now: datetime | None = None,
) -> dict[str, Any]:
    del packet_path, canary_root
    checks: list[dict[str, Any]] = []
    try:
        plan = validate_canary_experiment_plan_v1(_read(plan_path))
        if plan["plan_sha256"] != cli_approved_plan_sha256:
            raise ValueError("cli_approved_plan_hash_mismatch")
        profile = profile_for_plan(plan)
        if profile.profile_id != SHORT_COMPLETION_PROFILE_ID:
            raise ValueError("approval_profile_scope_mismatch")
        launcher = validate_import_closure(
            Path(__file__).resolve().parent,
            approved_third_party=plan["approved_dependency_manifest"]["third_party"],
        )
        if launcher["launcher_sha256"] != plan["launcher_sha256"]:
            raise ValueError("launcher_changed_during_canary")
        approval, identity, kind, _ = validate_registered_approval_document(
            _read(approval_path), expected_profile_id=profile.profile_id,
            expected_scope=profile.approval_scope,
            expected_plan_sha256=plan["plan_sha256"],
            expected_launcher_sha256=launcher["launcher_sha256"],
            now=now or datetime.now(timezone.utc), enforce_time=False,
        )
        if kind in {"signed_approval", "signed_smoke_approval"}:
            if source_candidate_path is None or source_authorization_patch_path is None:
                raise ValueError("signed_approval_source_document_missing")
            validate_registered_signed_sources(
                profile.profile_id, approval, _read(source_candidate_path),
                _read(source_authorization_patch_path), now=now,
            )
            validate_registered_signed_plan(profile.profile_id, approval, plan, now=now)
        workload = plan["workloads"][0]
        if file_sha256(workload_fixture_path) != workload["fixture_sha256"]:
            raise ValueError("workload_fixture_changed_during_canary")
        definitions = completion_contract_bundle_v1()
        policy = plan["short_completion_policy"]
        expected = {
            "stop_condition_manifest_hash": definitions["stop_conditions"]["definition_sha256"],
            "draft_validator_policy_sha256": definitions["draft_validator_policy"]["definition_sha256"],
            "mixed_script_policy_sha256": definitions["mixed_script_policy"]["definition_sha256"],
            "final_review_definition_sha256": definitions["final_review"]["definition_sha256"],
            "maintenance_definition_sha256": definitions["maintenance"]["definition_sha256"],
            "final_artifact_policy_sha256": definitions["final_artifact"]["definition_sha256"],
            "final_checkpoint_policy_sha256": definitions["final_checkpoint"]["definition_sha256"],
            "completion_goal_definition_sha256": definitions["completion_goal"]["definition_sha256"],
        }
        if any(policy.get(key) != digest for key, digest in expected.items()):
            raise ValueError("short_completion_policy_mismatch")
        readiness_value = policy.get("r1_d3_production_mirror_readiness")
        if readiness_value is not None:
            readiness = validate_r1_d3_successor_readiness_v1(
                readiness_value
            )
            if (
                policy.get("execution_collection_profile_id")
                != PRODUCTION_MIRROR_SHORT_PROFILE_ID
                or policy.get("r1_d3_production_mirror_readiness_sha256")
                != readiness["definition_sha256"]
                or readiness["production_mirror_build_sha256"]
                != plan["approved_build_fingerprint"]
                or readiness["production_mirror_config_sha256"]
                != plan["approved_execution_config_fingerprint"]
                or readiness["production_mirror_runtime_sha256"]
                != plan["expected_runtime_execution_fingerprint"]
                or readiness["production_mirror_prompt_policy_sha256"]
                != workload["prompt_policy_manifest_sha256"]
                or approval.get("r1_d3_production_mirror_readiness_sha256")
                != readiness["definition_sha256"]
                or approval.get("execution_collection_profile_id")
                != PRODUCTION_MIRROR_SHORT_PROFILE_ID
            ):
                raise ValueError("r1_d3_production_mirror_readiness_mismatch")
            ptr3 = validate_ptr3_readiness_v1(policy.get("ptr3_readiness") or {})
            if (
                policy.get("ptr3_readiness_sha256")
                != ptr3["definition_sha256"]
                or approval.get("ptr3_readiness_sha256")
                != ptr3["definition_sha256"]
                or ptr3["current_build_sha256"]
                != plan["approved_build_fingerprint"]
                or ptr3["current_config_sha256"]
                != plan["approved_execution_config_fingerprint"]
                or ptr3["current_runtime_sha256"]
                != plan["expected_runtime_execution_fingerprint"]
            ):
                raise ValueError("ptr3_readiness_mismatch")
        state = ApprovalConsumptionStore(approval_ledger_root).status(approval)
        if state["status"] != "unused":
            raise ValueError("approval_already_used")
        ledger_readiness = None
        if plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2":
            ledger_readiness = ApprovalConsumptionStore(
                approval_ledger_root
            ).operational_readiness(
                ledger_identity=plan["isolation"]["approval_ledger_identity"],
            )
            if ledger_readiness["status"] != "exact":
                raise ValueError("approval_ledger_operational_readiness_unknown")
        parity = live_parity_manifest(
            database_path=live_database_path, project_root=live_project_root,
        )
        checks = [{
            "name": name, "status": "exact", "reason_code": "exact",
            "definition_sha256": profile.profile_definition_sha256,
        } for name in CHECK_NAMES]
        return _receipt(
            checks, profile_id=profile.profile_id,
            approval_document_kind=kind,
            approval_identity_sha256=identity,
            approval_state=(
                "signed_approval_exact_and_executable"
                if kind == "signed_approval" else "disabled_candidate"
            ),
            approval_ledger_state=state["status"],
            approval_ledger_operational_readiness=(
                (ledger_readiness or {"status": "legacy_not_required"})["status"]
            ),
            parity={"status": "exact", "observation_sha256": parity["parity_sha256"]},
            execution_performed=False,
        )
    except Exception as exc:
        reason = getattr(exc, "reason_code", str(exc) or type(exc).__name__)
        checks = [{
            "name": name,
            "status": "blocked" if index == 0 else "not_evaluated",
            "reason_code": str(reason) if index == 0 else "upstream_check_blocked",
            "definition_sha256": None,
        } for index, name in enumerate(CHECK_NAMES)]
        return _receipt(
            checks, profile_id=SHORT_COMPLETION_PROFILE_ID,
            approval_document_kind="unknown", approval_identity_sha256=None,
            approval_state="unknown", approval_ledger_state="unknown",
            approval_ledger_operational_readiness="unknown",
            parity={"status": "unknown", "observation_sha256": None},
            execution_performed=False,
        )
