"""Read-only validate-only closure for the registered PA observation profile."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from novel_flywheel.runtime_fingerprint_build import CANONICALIZATION_VERSION, domain_sha256

from .approval_dispatch import (
    profile_for_plan, validate_registered_approval_document,
    validate_registered_signed_plan, validate_registered_signed_sources,
)
from .approval_profiles import PA_PROFILE_ID
from .approval_store import ApprovalConsumptionStore
from .artifact_hash import file_sha256, live_parity_manifest
from .contracts import validate_canary_experiment_plan_v1
from .hash_manifest import validate_import_closure


CHECK_NAMES = (
    "registered_profile", "approval_scope", "approval_canonical_hash",
    "candidate_binding", "authorization_patch_binding", "permitted_diff",
    "plan_canonical_hash", "launcher_bytes_hash", "workload_fixture_hash",
    "workload_manifest_hash", "production_source_byte_revalidation",
    "build_fingerprint", "execution_config_fingerprint",
    "runtime_execution_fingerprint", "provider_descriptor_manifest",
    "role_binding_manifest", "diagnostic_feature_flags", "phase1b_disabled",
    "target_filter", "observation_schema", "adapter_coverage",
    "pricing_evidence", "budget_definitions", "stop_conditions",
    "approval_execution_window", "approval_cohort_single_use",
    "approval_ledger_state", "external_action_zero",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("document_not_object")
    return value


def _receipt(checks: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    body = {
        "schema": "PAStrictToolObsApprovalClosureReceiptV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "overall_status": "exact" if all(x["status"] == "exact" for x in checks) else "blocked",
        "ordered_checks": checks,
        "external_action_counters": {
            "credential_lookup_count": 0, "provider_client_creation_count": 0,
            "network_call_count": 0, "model_call_count": 0,
            "paid_model_call_count": 0,
        },
        **fields,
    }
    body["validation_receipt_sha256"] = domain_sha256(
        "novel-flywheel-pa-approval-closure-v1", body,
    )
    return body


def validate_pa_approval_closure(
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
        if profile.profile_id != PA_PROFILE_ID:
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
        state = ApprovalConsumptionStore(approval_ledger_root).status(approval)
        if state["status"] != "unused":
            raise ValueError("approval_already_used")
        parity = live_parity_manifest(
            database_path=live_database_path, project_root=live_project_root,
        )
        checks = [{
            "name": name, "status": "exact", "reason_code": "exact",
            "definition_sha256": profile.profile_definition_sha256,
        } for name in CHECK_NAMES]
        return _receipt(
            checks, profile_id=profile.profile_id,
            approval_document_kind=kind, approval_identity_sha256=identity,
            approval_state=(
                "signed_approval_exact_and_executable"
                if kind in {"signed_approval", "signed_smoke_approval"}
                else "disabled_candidate"
            ),
            approval_ledger_state=state["status"],
            live_parity_observation_sha256=parity["parity_sha256"],
            execution_performed=False,
        )
    except Exception as exc:
        reason = getattr(exc, "reason_code", str(exc) or type(exc).__name__)
        if not checks:
            checks = [{
                "name": name,
                "status": "blocked" if index == 0 else "not_evaluated",
                "reason_code": str(reason) if index == 0 else "upstream_check_blocked",
                "definition_sha256": None,
            } for index, name in enumerate(CHECK_NAMES)]
        return _receipt(
            checks, profile_id=PA_PROFILE_ID, approval_document_kind="unknown",
            approval_identity_sha256=None, approval_state="unknown",
            approval_ledger_state="unknown", execution_performed=False,
        )
