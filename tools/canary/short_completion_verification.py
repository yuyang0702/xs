"""Deterministic hash-only verification for a completed Short Canary run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.quality_records import load_quality_checkpoint
from novel_flywheel.maintenance_authority import MaintenanceReductionV1
from novel_flywheel.project_transactions import ProjectMutationJournalV1
from novel_flywheel.short_canonical_promotion import MaintenanceProposalInventoryV1
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .artifact_hash import file_sha256
from .short_completion import (
    COMPLETION_GOAL,
    FINAL_REVIEW_CONTRACT_ID,
    FINAL_REVIEW_CONTRACT_VERSION,
    completion_contract_bundle_v1,
)


SCHEMA = "ShortCompletionVerificationV1"


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _text_hash(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _draft_validation(run_root: Path, manuscript_sha256: str | None) -> tuple[str, str | None]:
    candidates = [
        run_root / "outputs" / "draft-integrity.json",
        *sorted((run_root / "outputs").glob("polish-integrity*.json")),
    ]
    for path in reversed(candidates):
        value = _read_object(path)
        if value is None:
            continue
        if value.get("status") == "passed" and manuscript_sha256 in {
            value.get("publication_sha256"), value.get("draft_sha256"),
        }:
            return "passed_exact", file_sha256(path)
    return "unverifiable_or_not_passed", None


def _maintenance_receipt(run_root: Path) -> tuple[bool, str, str | None]:
    paths = sorted((run_root / "receipts").glob("maintenance-inventory-*.json"))
    paths += sorted((run_root / "receipts").glob("maintenance-reduction-*.json"))
    valid: list[dict[str, str]] = []
    for path in paths:
        value = _read_object(path)
        if not value:
            continue
        schema = value.get("schema")
        try:
            if schema == "MaintenanceProposalInventoryV1":
                MaintenanceProposalInventoryV1.model_validate_json(
                    json.dumps(value, ensure_ascii=False)
                )
                kind = schema
            else:
                MaintenanceReductionV1.model_validate_json(
                    json.dumps(value, ensure_ascii=False)
                )
                kind = "MaintenanceReductionV1"
        except (ValueError, TypeError):
            continue
        valid.append({"kind": kind,
                      "sha256": file_sha256(path)})
    if not valid:
        return False, "missing_or_invalid", None
    return True, "passed", domain_sha256(
        "novel-flywheel-short-maintenance-receipts-v1", valid,
    )


def _journal_binding(
    run_root: Path, manuscript_sha256: str | None,
) -> tuple[str, str | None]:
    path = run_root / "outputs" / "project-mutation-journal.json"
    raw = _read_object(path)
    try:
        journal = ProjectMutationJournalV1.model_validate_json(
            json.dumps(raw, ensure_ascii=False)
        )
    except (ValueError, TypeError):
        return "unbound", None
    if journal.status != "committed":
        return "unbound", file_sha256(path)
    bound = any(
        item.path == "manuscript/story.md"
        and item.sha256 == manuscript_sha256
        for item in journal.artifacts
    )
    return ("exact" if bound else "unbound"), file_sha256(path)


def verify_short_completion_v1(
    *, project_root: Path, run_root: Path, run_identity: str,
    workload_sha256: str, workflow_final_status: str,
    live_parity_status: str,
) -> dict[str, Any]:
    """Observe the existing production artifacts; never mutate or infer gaps."""

    definitions = completion_contract_bundle_v1()
    manuscript_path = project_root / "manuscript" / "story.md"
    manuscript_sha256 = _text_hash(manuscript_path)
    draft_status, draft_receipt_sha256 = _draft_validation(
        run_root, manuscript_sha256,
    )

    report_path = run_root / "outputs" / "quality-report.json"
    report = _read_object(report_path)
    report_receipt_sha256 = file_sha256(report_path) if report is not None else None
    reviewed_sha256 = report.get("terminal_reviewed_hash") if report else None
    verdict = report.get("status") if report else "missing"
    review_accepted = bool(
        report is not None
        and verdict == "passed"
        and report.get("terminal_review_complete") is True
    )
    review_binding = (
        "exact" if review_accepted and manuscript_sha256 is not None
        and reviewed_sha256 == manuscript_sha256
        else "invalid" if report is not None else "unknown"
    )

    maintenance_executed, maintenance_validation, maintenance_hash = (
        _maintenance_receipt(run_root)
    )
    artifact_binding, journal_sha256 = _journal_binding(
        run_root, manuscript_sha256,
    )
    maintenance_closure = (
        "exact" if maintenance_executed and maintenance_validation == "passed"
        and artifact_binding == "exact" else "incomplete"
    )

    checkpoint_path = run_root / "outputs" / "quality-checkpoint.json"
    checkpoint = load_quality_checkpoint(run_root)
    checkpoint_sha256 = (
        file_sha256(checkpoint_path) if checkpoint_path.is_file() else None
    )
    checkpoint_binding = (
        "exact" if isinstance(checkpoint, dict)
        and checkpoint.get("outcome") == "passed"
        and checkpoint.get("manuscript_hash") == manuscript_sha256
        and checkpoint.get("terminal_reviewed_hash") == manuscript_sha256
        else "invalid" if checkpoint_path.is_file() else "unknown"
    )
    checkpoint_closure = "exact" if checkpoint_binding == "exact" else "unclosed"

    terminal = workflow_final_status not in {"completed", "WORKFLOW_COMPLETED"}
    unresolved_terminal_status = "present" if terminal else "none"
    if terminal:
        outcome = "WORKFLOW_TERMINAL"
    elif report is None or manuscript_sha256 is None:
        outcome = "VERIFICATION_INSUFFICIENT"
    elif not review_accepted:
        outcome = "WORKFLOW_COMPLETED_FINAL_REVIEW_NOT_ACCEPTED"
    elif review_binding != "exact":
        outcome = "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"
    elif draft_status != "passed_exact":
        outcome = "VERIFICATION_INSUFFICIENT"
    elif not maintenance_executed or maintenance_validation != "passed":
        outcome = "WORKFLOW_COMPLETED_MAINTENANCE_INCOMPLETE"
    elif artifact_binding != "exact":
        outcome = "WORKFLOW_COMPLETED_FINAL_ARTIFACT_UNBOUND"
    elif checkpoint_closure != "exact":
        outcome = "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"
    elif live_parity_status != "exact":
        outcome = "VERIFICATION_INSUFFICIENT"
    else:
        outcome = COMPLETION_GOAL

    body = {
        "schema": SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "run_identity_sha256": domain_sha256(
            "novel-flywheel-short-completion-run-identity-v1", run_identity,
        ),
        "workload_sha256": workload_sha256,
        "workflow_final_status": workflow_final_status,
        "final_manuscript_sha256": manuscript_sha256,
        "final_manuscript_binding_status": review_binding,
        "draft_validation": {
            "validator_policy_sha256": definitions["draft_validator_policy"]["definition_sha256"],
            "mixed_script_policy_sha256": definitions["mixed_script_policy"]["definition_sha256"],
            "final_status": draft_status,
            "receipt_sha256": draft_receipt_sha256,
        },
        "final_review": {
            "contract_id": FINAL_REVIEW_CONTRACT_ID,
            "contract_version": FINAL_REVIEW_CONTRACT_VERSION,
            "completion_definition_sha256": definitions["final_review"]["definition_sha256"],
            "receipt_sha256": report_receipt_sha256,
            "reviewed_manuscript_sha256": reviewed_sha256,
            "current_final_manuscript_sha256": manuscript_sha256,
            "binding_status": review_binding,
            "verdict": verdict,
            "accepted_status": "accepted" if review_accepted else "not_accepted",
        },
        "maintenance": {
            "completion_definition_sha256": definitions["maintenance"]["definition_sha256"],
            "executed": maintenance_executed,
            "artifact_receipt_sha256": maintenance_hash,
            "validation_status": maintenance_validation,
            "closure_status": maintenance_closure,
            "project_mutation_journal_sha256": journal_sha256,
        },
        "final_artifact": {
            "policy_sha256": definitions["final_artifact"]["definition_sha256"],
            "artifact_kind": "formal_short_manuscript",
            "artifact_sha256": manuscript_sha256,
            "binding_status": artifact_binding,
        },
        "final_checkpoint": {
            "policy_sha256": definitions["final_checkpoint"]["definition_sha256"],
            "checkpoint_sha256": checkpoint_sha256,
            "binding_status": checkpoint_binding,
            "closure_status": checkpoint_closure,
        },
        "unresolved_terminal_status": unresolved_terminal_status,
        "live_parity_status": live_parity_status,
        "completion_goal_definition_sha256": definitions["completion_goal"]["definition_sha256"],
        "completion_goal_outcome": outcome,
        "raw_content_included": False,
    }
    return {
        **body,
        "verification_receipt_sha256": domain_sha256(
            "novel-flywheel-short-completion-verification-v1", body,
        ),
    }
