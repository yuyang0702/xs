"""Deterministic hash-only verification for a completed Short Canary run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from novel_flywheel.quality_records import load_quality_checkpoint
from novel_flywheel.maintenance_authority import MaintenanceReductionV1
from novel_flywheel.maintenance_authority import validate_maintenance_reduction
from novel_flywheel.project_transactions import ProjectMutationJournalV1
from novel_flywheel.quality import issue_ledger, review_windows
from novel_flywheel.receipt_contracts import (
    validate_final_review_verdict_receipt,
)
from novel_flywheel.short_canonical_promotion import (
    MaintenanceProposalInventoryV1,
    SHORT_CANONICAL_GATE_NAME,
    ShortCanonicalCommitReceiptV1,
)
from novel_flywheel.style_context import (
    validate_frozen_style_reference_authority,
    validate_style_reference_context_receipt,
)
from novel_flywheel.workflows import WorkflowService
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


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _maintenance_receipt(
    run_root: Path, *, manuscript: str, manuscript_sha256: str | None,
    expected_base_revision: int | None,
    expected_base_authority_sha256: str,
    expected_maintenance_source_state_sha256: str,
) -> tuple[bool, str, str | None]:
    paths = sorted((run_root / "receipts").glob("maintenance-inventory-*.json"))
    paths += sorted((run_root / "receipts").glob("maintenance-reduction-*.json"))
    valid: list[dict[str, str]] = []
    inventory_modes: set[str] = set()
    invalid_present = False
    for path in paths:
        value = _read_object(path)
        if not value:
            continue
        schema = value.get("schema")
        try:
            if schema == "MaintenanceProposalInventoryV1":
                inventory = MaintenanceProposalInventoryV1.model_validate_json(
                    json.dumps(value, ensure_ascii=False)
                )
                if (
                    inventory.complete is not True
                    or inventory.coverage_gaps
                    or inventory.source_artifact_hash != manuscript_sha256
                    or expected_base_revision is not None
                    and inventory.base_authority_revision
                    != expected_base_revision
                    or inventory.base_authority_hash
                    != expected_base_authority_sha256
                ):
                    invalid_present = True
                    continue
                inventory_modes.add(inventory.source_mode)
                kind = schema
            else:
                reduction = validate_maintenance_reduction(
                    value,
                    manuscript=manuscript,
                    source_state_sha256=(
                        expected_maintenance_source_state_sha256
                    ),
                )
                if reduction.manuscript_sha256 != manuscript_sha256:
                    invalid_present = True
                    continue
                kind = "MaintenanceReductionV1"
        except (ValueError, TypeError):
            invalid_present = True
            continue
        valid.append({"kind": kind,
                      "sha256": file_sha256(path)})
    valid_kinds = {item["kind"] for item in valid}
    normal_receipt = _read_object(run_root / "receipts" / "maintenance.json")
    try:
        normal_output = json.loads(
            (run_root / "outputs" / "maintenance.md").read_text(
                encoding="utf-8",
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        normal_output = None
    normal_lane_exact = bool(
        "normal" in inventory_modes
        and isinstance(normal_output, dict)
        and isinstance(normal_receipt, Mapping)
        and isinstance(normal_receipt.get("model"), Mapping)
        and normal_receipt["model"].get("role") == "maintenance"
    )
    reduction_lane_exact = "MaintenanceReductionV1" in valid_kinds
    if (
        invalid_present
        or "MaintenanceProposalInventoryV1" not in valid_kinds
        or not (normal_lane_exact or reduction_lane_exact)
    ):
        return False, "missing_or_invalid", None
    return True, "passed", domain_sha256(
        "novel-flywheel-short-maintenance-receipts-v1", valid,
    )


def _journal_binding(
    project_root: Path, run_root: Path, manuscript_sha256: str | None,
    *, run_identity: str, live_story_state_revision: int,
    live_story_state_sha256: str,
    live_story_state_data: Mapping[str, Any],
    expected_base_story_state_revision: int,
    short_canonical_v2_enabled: bool,
) -> tuple[str, str | None, ProjectMutationJournalV1 | None, str]:
    path = run_root / "outputs" / "project-mutation-journal.json"
    raw = _read_object(path)
    try:
        journal = ProjectMutationJournalV1.model_validate_json(
            json.dumps(raw, ensure_ascii=False)
        )
    except (ValueError, TypeError):
        return "unbound", None, None, "invalid_or_missing"
    journal_sha256 = file_sha256(path)
    try:
        project_document = _read_object(project_root / "project.json") or {}
        project_id = str(project_document.get("id") or "")
        required_paths = {
            "manuscript/story.md", "chapters/chapter-01.md", "memory/canon.json",
        }
        artifact_by_path = {item.path: item for item in journal.artifacts}
        exact_files = all(
            (project_root / relative).is_file()
            and artifact_by_path[relative].sha256
            == file_sha256(project_root / relative)
            for relative in required_paths
        )
        story_state = journal.story_state
        bound = bool(
            journal.status == "committed"
            and journal.operation == "short-story"
            and journal.run_id == run_identity
            and project_id
            and journal.project_id == project_id
            and set(journal.managed_paths) == required_paths
            and set(artifact_by_path) == required_paths
            and exact_files
            and story_state is not None
            and story_state.expected_revision
            == journal.expected_story_state_revision
            and journal.expected_story_state_revision
            == expected_base_story_state_revision
            and story_state.target_revision
            == journal.expected_story_state_revision + 1
            and story_state.target_revision == live_story_state_revision
            and story_state.state_sha256 == live_story_state_sha256
            and story_state.data == dict(live_story_state_data)
        )
        canon = _read_object(project_root / "memory" / "canon.json")
        bound = bool(
            bound
            and isinstance(canon, Mapping)
            and WorkflowService._short_canonical_live_authority_exact(
                canon, live_story_state_data,
                journal.post_commit_gate.payload
                if journal.post_commit_gate is not None else {},
            )
        )
    except (KeyError, OSError, TypeError, ValueError):
        bound = False
    ready_binding = "invalid"
    if bound and short_canonical_v2_enabled:
        if journal.post_commit_gate is None:
            bound = False
            return "unbound", journal_sha256, None, ready_binding
        gate = journal.post_commit_gate
        # ``receipt_path`` is sealed project-relative by the mutation journal;
        # joining it to ``run_root`` would duplicate ``runs/<run-id>`` and
        # incorrectly reject the production canonical-v2 lane after commit.
        receipt_path = (
            project_root / str(gate.receipt_path or "")
            if gate.receipt_path else None
        )
        try:
            receipt = ShortCanonicalCommitReceiptV1.model_validate_json(
                receipt_path.read_text(encoding="utf-8") if receipt_path else "",
            )
            bound = bool(
                gate.name == SHORT_CANONICAL_GATE_NAME
                and gate.status == "passed"
                and receipt_path is not None
                and file_sha256(receipt_path) == gate.receipt_sha256
                and receipt.journal_saga_id == run_identity
                and journal.story_state is not None
                and receipt.target_revision
                == journal.story_state.target_revision
                and receipt.target_authority_hash
                == journal.story_state.state_sha256
                and receipt.source_artifact_hash == manuscript_sha256
            )
        except (OSError, UnicodeError, ValueError, TypeError):
            bound = False
        ready_binding = "exact" if bound else "invalid"
    elif bound and journal.post_commit_gate is None:
        # The legacy lane is valid only when the exact live runtime binding
        # proves the canonical feature is disabled.  Absence alone is never
        # interpreted as READY authority.
        ready_binding = "legacy_lane_exact"
    elif bound:
        bound = False
    return (
        "exact" if bound else "unbound",
        journal_sha256,
        journal if bound else None,
        ready_binding,
    )


def _terminal_quality_evidence(
    run_root: Path, report: Mapping[str, Any] | None,
    manuscript: str, manuscript_sha256: str | None,
) -> tuple[bool, str, str | None]:
    """Validate mandatory review/style evidence, not just three status fields."""

    if not isinstance(report, Mapping) or manuscript_sha256 is None:
        return False, "missing_or_invalid", None
    terminal_review = report.get("terminal_review")
    audit = report.get("final_review_evidence")
    if not isinstance(terminal_review, Mapping) or not isinstance(audit, Mapping):
        return False, "missing_or_invalid", None
    windows = audit.get("windows")
    reconciliations = audit.get("reconciliations")
    prior_issue_ids = audit.get("prior_issue_ids")
    if (
        audit.get("coverage") != 1.0
        or type(audit.get("window_count")) is not int
        or type(audit.get("reviewed_windows")) is not int
        or audit["window_count"] < 1
        or audit["reviewed_windows"] != audit["window_count"]
        or not isinstance(windows, list)
        or len(windows) != audit["window_count"]
        or not isinstance(reconciliations, list)
        or not isinstance(prior_issue_ids, list)
    ):
        return False, "missing_or_invalid", None
    expected_windows = review_windows(manuscript)
    if len(expected_windows) != len(windows):
        return False, "missing_or_invalid", None
    for actual_window, expected_window in zip(
        windows, expected_windows, strict=True,
    ):
        expected_text = expected_window["text"]
        if (
            not isinstance(actual_window, Mapping)
            or actual_window.get("window") != expected_window["index"]
            or actual_window.get("start") != expected_window["start"]
            or actual_window.get("end") != expected_window["end"]
            or actual_window.get("manuscript_sha256") != manuscript_sha256
            or actual_window.get("window_sha256")
            != hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
            or not str(actual_window.get("summary") or "").strip()
            or not isinstance(actual_window.get("issues"), list)
        ):
            return False, "missing_or_invalid", None

    # The separately persisted evidence artifact is mandatory and must be the
    # exact artifact embedded in the terminal report.  A report-local object
    # cannot self-authorize review coverage.
    evidence_artifact = None
    for path in sorted((run_root / "outputs").glob("final-review-evidence*.json")):
        candidate = _read_object(path)
        if (
            isinstance(candidate, Mapping)
            and candidate.get("windows") == windows
            and candidate.get("audit") == dict(audit)
        ):
            evidence_artifact = path
            break
    if evidence_artifact is None:
        return False, "missing_or_invalid", None
    reconciled = {
        str(item.get("issue_id")) for item in reconciliations
        if isinstance(item, Mapping)
        and item.get("status") in {"resolved", "preserved"}
    }
    if any(str(issue_id) not in reconciled for issue_id in prior_issue_ids):
        return False, "missing_or_invalid", None

    authority_path = run_root / "outputs" / "style-reference-authority-v1.json"
    context_path = run_root / "outputs" / "style-reference-context-final_review-v1.json"
    try:
        authority = _read_object(authority_path)
        if authority is None:
            raise ValueError("missing style authority")
        authority = validate_frozen_style_reference_authority(authority, authority)
        fidelity = terminal_review.get("style_reference_fidelity")
        if not isinstance(fidelity, Mapping):
            raise ValueError("missing style fidelity")
        fidelity_body = dict(fidelity)
        fidelity_hash = fidelity_body.pop("receipt_sha256", None)
        if fidelity_hash != _canonical_sha256(fidelity_body):
            raise ValueError("stale style fidelity")
        normalized_terminal_review = dict(terminal_review)
        normalized_terminal_review.pop("style_reference_fidelity", None)
        adjudication_artifact = audit.get("adjudication_artifact")
        adjudication_receipt = audit.get("adjudication_receipt")
        if (
            not isinstance(adjudication_artifact, Mapping)
            or set(adjudication_artifact) != {"path", "sha256"}
            or not isinstance(adjudication_receipt, Mapping)
            or adjudication_receipt.get("accepted_stage_artifact")
            != dict(adjudication_artifact)
        ):
            raise ValueError("terminal adjudication artifact is unbound")
        relative_verdict = str(adjudication_artifact.get("path") or "")
        if re.fullmatch(
            r"outputs/final_review(?:-[A-Za-z0-9._-]+)?\.md",
            relative_verdict,
        ) is None:
            raise ValueError("terminal adjudication artifact path is invalid")
        verdict_path = (run_root / relative_verdict).resolve()
        if (
            not verdict_path.is_relative_to(run_root.resolve())
            or not verdict_path.is_file()
            or file_sha256(verdict_path)
            != adjudication_artifact.get("sha256")
        ):
            raise ValueError("terminal adjudication artifact is stale")
        raw_terminal_review = json.loads(verdict_path.read_text(encoding="utf-8"))
        typed_terminal_review = validate_final_review_verdict_receipt(
            raw_terminal_review,
        )
        for field in (
            "hard_fail", "decision", "issues", "reconciliations",
            "request_full_review", "dimensions", "criteria",
            "criterion_evidence", "commercial", "story", "prose", "score",
        ):
            if (
                field in typed_terminal_review
                and normalized_terminal_review.get(field)
                != typed_terminal_review[field]
            ):
                raise ValueError("normalized terminal verdict drift")
        if fidelity.get("model_free_text_review_sha256") != _canonical_sha256(
            typed_terminal_review,
        ):
            raise ValueError("style fidelity is not bound to terminal verdict")
        if fidelity.get("selected_authority_sha256") != authority["authority_sha256"]:
            raise ValueError("wrong style authority")
        if authority.get("selection_status") == "selected":
            context = _read_object(context_path)
            if context is None:
                raise ValueError("missing final review style context")
            context = validate_style_reference_context_receipt(
                context,
                frozen_authority=authority,
                stage="final_review",
                require_contract_attempt=True,
                expected_model_input_sha256=str(context.get("model_input_sha256") or ""),
                expected_model_system_sha256=str(context.get("model_system_sha256") or ""),
                expected_context_packet_sha256=str(
                    context.get("context_packet_sha256") or "",
                ),
                expected_contract_attempt_index=context.get("contract_attempt_index"),
                expected_contract_attempt_route=context.get("contract_attempt_route"),
            )
            if (
                fidelity.get("rendered_context_sha256")
                != context["context_sha256"]
                or fidelity.get("reviewed_input_sha256")
                != context["model_input_sha256"]
            ):
                raise ValueError("style fidelity attempt binding mismatch")
        elif fidelity.get("status") != "not_requested":
            raise ValueError("unrequested style claimed")
        review_binding = _read_object(
            run_root / "outputs" / "review-binding-v1.json",
        )
        review_text_hash = _text_hash(run_root / "outputs" / "review.md")
        if (
            not isinstance(review_binding, Mapping)
            or review_binding.get("schema") != "ShortInitialReviewBindingV1"
            or review_binding.get("review_sha256") != review_text_hash
            or review_binding.get("reviewed_draft_sha256")
            != _text_hash(run_root / "outputs" / "draft.md")
            or review_binding.get("style_reference_authority_sha256")
            != authority["authority_sha256"]
        ):
            raise ValueError("initial editorial review is unbound")
        short_checkpoint = _read_object(
            run_root / "outputs" / "short-checkpoint.json",
        )
        if (
            not isinstance(short_checkpoint, Mapping)
            or review_binding.get("generation_context_sha256")
            != short_checkpoint.get("generation_context_sha256")
        ):
            raise ValueError("initial editorial review generation authority is stale")
        binding_body = dict(review_binding)
        binding_digest = binding_body.pop("binding_sha256", None)
        if binding_digest != _canonical_sha256(binding_body):
            raise ValueError("initial editorial review binding is stale")
        polish_integrities = [
            value for value in (
                _read_object(path) for path in sorted(
                    (run_root / "outputs").glob("polish-integrity*.json"),
                )
            ) if value is not None
        ]
        if not any(
            value.get("status") == "passed"
            and value.get("publication_sha256") == manuscript_sha256
            and value.get("issues") == []
            and isinstance(value.get("segments"), list)
            and bool(value["segments"])
            and isinstance(value.get("accepted_event_ids"), list)
            and bool(value["accepted_event_ids"])
            for value in polish_integrities
        ):
            raise ValueError("polish integrity is missing")
    except (OSError, UnicodeError, ValueError, TypeError):
        return False, "missing_or_invalid", None
    evidence = {
        "authority_sha256": authority["authority_sha256"],
        "fidelity_receipt_sha256": fidelity["receipt_sha256"],
        "typed_verdict_sha256": _canonical_sha256(typed_terminal_review),
        "audit_sha256": _canonical_sha256(dict(audit)),
        "initial_review_binding_sha256": review_binding.get("binding_sha256"),
        "evidence_artifact_sha256": file_sha256(evidence_artifact),
    }
    return True, "exact", domain_sha256(
        "novel-flywheel-short-terminal-quality-evidence-v1", evidence,
    )


def _short_authority_chain(
    run_root: Path, manuscript: str, manuscript_sha256: str | None,
    *, workflow_service: WorkflowService | None, project: Any | None,
) -> tuple[bool, str | None]:
    """Re-prove the persisted Planning→Draft→polish authority graph."""

    outputs = run_root / "outputs"
    checkpoint = _read_object(outputs / "short-checkpoint.json")
    if not isinstance(checkpoint, Mapping):
        return False, None
    context_fields = (
        "version", "project_id", "outline_sha256", "constraints_sha256",
        "story_state_revision", "story_state_sha256", "target_words",
        "segment_count", "style_reference_authority_sha256",
        "generation_context_sha256",
    )
    try:
        context = {field: checkpoint[field] for field in context_fields}
        WorkflowService._load_validated_short_checkpoint_bundle(
            outputs, int(context["segment_count"]), context,
        )
    except (KeyError, OSError, UnicodeError, TypeError, ValueError):
        return False, None

    # The terminal publication may be a later polish.  Its own integrity must
    # carry exact per-segment and whole-draft semantic receipts, not merely a
    # convenient publication hash.
    terminal_integrity = None
    for path in sorted(outputs.glob("polish-integrity*.json")):
        candidate = _read_object(path)
        if (
            isinstance(candidate, Mapping)
            and candidate.get("status") == "passed"
            and candidate.get("publication_sha256") == manuscript_sha256
            and candidate.get("issues") == []
        ):
            terminal_integrity = (path, candidate)
    if terminal_integrity is None:
        return False, None
    integrity_path, integrity = terminal_integrity
    segments = integrity.get("segments")
    segment_receipts = integrity.get("semantic_segment_receipts")
    accepted = integrity.get("accepted_event_ids")
    whole = integrity.get("whole_semantic_receipt")
    if (
        not isinstance(segments, list) or not segments
        or not isinstance(segment_receipts, list)
        or len(segment_receipts) != len(segments)
        or not all(isinstance(item, Mapping) and bool(item) for item in segment_receipts)
        or not isinstance(accepted, list) or not accepted
        or not isinstance(whole, Mapping) or not whole
        or integrity.get("execution_manifest_sha256")
        != checkpoint.get("execution_manifest_sha256")
    ):
        return False, None
    if workflow_service is None or project is None:
        return False, None
    semantic_authority = workflow_service._quality_semantic_authority(
        project, run_root,
        {"narrative_integrity": {
            "path": str(integrity_path.relative_to(run_root)).replace("\\", "/"),
            "sha256": file_sha256(integrity_path),
        }},
        manuscript,
    )
    if semantic_authority is None:
        return False, None

    adaptation = _read_object(outputs / "planning-adaptations.json")
    if adaptation is not None and (
        adaptation.get("status") != "ready"
        or adaptation.get("planning_sha256") != checkpoint.get("planning_sha256")
        or adaptation.get("segment_count") != checkpoint.get("segment_count")
    ):
        return False, None
    evidence = {
        "short_checkpoint_sha256": file_sha256(
            outputs / "short-checkpoint.json",
        ),
        "planning_ir_sha256": file_sha256(outputs / "planning-ir.json"),
        "causal_chain_sha256": file_sha256(
            outputs / "short-causal-chain.json",
        ),
        "execution_manifest_sha256": file_sha256(
            outputs / "short-execution-index.json",
        ),
        "draft_integrity_sha256": file_sha256(
            outputs / "draft-integrity.json",
        ),
        "terminal_integrity_sha256": file_sha256(integrity_path),
        "planning_adaptation_sha256": (
            file_sha256(outputs / "planning-adaptations.json")
            if adaptation is not None else None
        ),
    }
    return True, domain_sha256(
        "novel-flywheel-short-authority-chain-v1", evidence,
    )


def verify_short_completion_v1(
    *, project_root: Path, run_root: Path, run_identity: str,
    workload_sha256: str, workflow_final_status: str,
    live_parity_status: str, live_story_state_revision: int,
    live_story_state_sha256: str,
    live_story_state_data: Mapping[str, Any],
    expected_base_story_state_revision: int,
    expected_base_story_state_sha256: str,
    expected_maintenance_source_state_sha256: str,
    short_canonical_v2_enabled: bool,
    workflow_service: WorkflowService | None = None,
    project: Any | None = None,
) -> dict[str, Any]:
    """Observe the existing production artifacts; never mutate or infer gaps."""

    definitions = completion_contract_bundle_v1()
    manuscript_path = project_root / "manuscript" / "story.md"
    try:
        manuscript = manuscript_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        manuscript = ""
    manuscript_sha256 = (
        hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
        if manuscript.strip() else None
    )
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

    artifact_binding, journal_sha256, journal, ready_binding = _journal_binding(
        project_root, run_root, manuscript_sha256,
        run_identity=run_identity,
        live_story_state_revision=live_story_state_revision,
        live_story_state_sha256=live_story_state_sha256,
        live_story_state_data=live_story_state_data,
        expected_base_story_state_revision=expected_base_story_state_revision,
        short_canonical_v2_enabled=short_canonical_v2_enabled,
    )
    maintenance_executed, maintenance_validation, maintenance_hash = (
        _maintenance_receipt(
            run_root,
            manuscript=manuscript,
            manuscript_sha256=manuscript_sha256,
            expected_base_revision=(
                journal.expected_story_state_revision if journal else None
            ),
            expected_base_authority_sha256=(
                expected_base_story_state_sha256
            ),
            expected_maintenance_source_state_sha256=(
                expected_maintenance_source_state_sha256
            ),
        )
    )
    quality_evidence_exact, quality_evidence_status, quality_evidence_sha256 = (
        _terminal_quality_evidence(
            run_root, report, manuscript, manuscript_sha256,
        )
    )
    authority_chain_exact, authority_chain_sha256 = _short_authority_chain(
        run_root, manuscript, manuscript_sha256,
        workflow_service=workflow_service, project=project,
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
    terminal_review = report.get("terminal_review") if report else None
    terminal_review_exact = isinstance(terminal_review, dict)
    expected_issue_ledger = (
        issue_ledger(terminal_review.get("issues", []))
        if terminal_review_exact else None
    )
    checkpoint_binding = (
        "exact" if isinstance(checkpoint, dict)
        and terminal_review_exact
        and checkpoint.get("outcome") == "passed"
        and checkpoint.get("manuscript_path") == "outputs/best-candidate.md"
        and (run_root / "outputs" / "best-candidate.md").is_file()
        and _text_hash(run_root / "outputs" / "best-candidate.md")
        == manuscript_sha256
        and checkpoint.get("manuscript_hash") == manuscript_sha256
        and checkpoint.get("terminal_reviewed_hash") == manuscript_sha256
        and checkpoint.get("best_attempt") == report.get("best_attempt")
        and checkpoint.get("review") == terminal_review
        and checkpoint.get("score") == terminal_review.get("score")
        and checkpoint.get("scoring_profile_id")
        == terminal_review.get("scoring_profile_id")
        and checkpoint.get("judge_signature")
        == terminal_review.get("judge_signature")
        and checkpoint.get("issue_ledger") == expected_issue_ledger
        and isinstance(checkpoint.get("narrative_integrity"), dict)
        and (
            run_root / str(checkpoint["narrative_integrity"].get("path") or "")
        ).is_file()
        and file_sha256(
            run_root / str(checkpoint["narrative_integrity"].get("path") or "")
        ) == checkpoint["narrative_integrity"].get("sha256")
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
    elif not authority_chain_exact:
        outcome = "WORKFLOW_COMPLETED_AUTHORITY_CHAIN_INCOMPLETE"
    elif not quality_evidence_exact:
        outcome = "WORKFLOW_COMPLETED_FINAL_REVIEW_EVIDENCE_INCOMPLETE"
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
        "planning_draft_authority": {
            "binding_status": "exact" if authority_chain_exact else "invalid",
            "authority_chain_sha256": authority_chain_sha256,
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
            "evidence_status": quality_evidence_status,
            "evidence_sha256": quality_evidence_sha256,
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
            "ready_authority_binding_status": ready_binding,
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
