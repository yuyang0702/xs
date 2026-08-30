from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.quality import review_windows
from novel_flywheel.maintenance_authority import (
    MAINTENANCE_WINDOW_RECEIPT_VERSION,
    adapt_maintenance_window_payload,
    build_maintenance_reduction,
    build_maintenance_window_contracts,
)
from novel_flywheel.short_canonical_promotion import make_maintenance_inventory

from tools.canary.short_completion import COMPLETION_GOAL
import tools.canary.short_completion_verification as completion_verification
from tools.canary.short_completion_verification import verify_short_completion_v1
from tools.canary.launcher import real_result_exit_code


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> dict:
    project = tmp_path / "project"
    run = project / "runs" / "run-1"
    manuscript = "sanitized final manuscript"
    digest = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    formal = project / "manuscript" / "story.md"
    chapter = project / "chapters" / "chapter-01.md"
    canon = project / "memory" / "canon.json"
    reviewed = run / "outputs" / "best-candidate.md"
    formal.parent.mkdir(parents=True)
    reviewed.parent.mkdir(parents=True)
    formal.write_text(manuscript, encoding="utf-8")
    chapter.parent.mkdir(parents=True)
    chapter.write_text(manuscript, encoding="utf-8")
    canon.parent.mkdir(parents=True)
    live_state = {
        "confirmed_facts": [], "character_states": {}, "world_rules": [],
        "timeline_events": [],
    }
    live_state_sha256 = hashlib.sha256(json.dumps(
        live_state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    canon.write_text(json.dumps({
        "facts": [], "state": {}, "world_rules": [], "timeline": [],
    }, ensure_ascii=False), encoding="utf-8")
    _write_json(project / "project.json", {"id": "project-1"})
    reviewed.write_text(manuscript, encoding="utf-8")
    (run / "outputs" / "draft.md").write_text(manuscript, encoding="utf-8")
    _write_json(run / "outputs" / "draft-integrity.json", {
        "status": "passed", "publication_sha256": digest,
    })
    authority_body = {
        "schema": "SelectedStyleReferenceProvenanceV1", "version": 1,
        "project_binding_sha256": hashlib.sha256(json.dumps({
            "schema": "StyleReferenceProjectBindingV1", "version": 1,
            "project_id": "project-1",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "selection_status": "not_requested", "selection_scope": "not_requested",
        "style_profile_state": "not_requested", "style_profile_sha256": "",
        "prose_baseline_state": "missing", "prose_baseline_sha256": "",
        "quality_reference_group_id": "", "quality_reference_group_version": 0,
        "quality_reference_group_state": "not_requested",
        "quality_reference_identities": [],
        "quality_reference_identity_set_sha256": hashlib.sha256(b"[]").hexdigest(),
        "reference_evidence_status": "none",
        "claim_policy": {
            "allowed": "uses_selected_style_guidance", "exact_imitation": "forbidden",
            "author_equivalence": "forbidden",
            "unsupported_stylistic_equivalence": "forbidden",
        },
    }
    authority = {**authority_body, "authority_sha256": hashlib.sha256(json.dumps(
        authority_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()}
    _write_json(run / "outputs" / "style-reference-authority-v1.json", authority)
    terminal_review_body = {
        "score": 92, "hard_fail": False, "decision": "pass",
        "issues": [], "reconciliations": [], "request_full_review": False,
    }
    adjudication_text = json.dumps(terminal_review_body, ensure_ascii=False)
    adjudication_artifact = {
        "path": "outputs/final_review-adjudication.md",
        "sha256": hashlib.sha256(adjudication_text.encode("utf-8")).hexdigest(),
    }
    fidelity_body = {
        "schema": "FinalReviewStyleReferenceReceiptV1", "version": 1,
        "status": "not_requested",
        "selected_authority_sha256": authority["authority_sha256"],
        "model_free_text_claim_authority": "none",
        "model_free_text_review_sha256": hashlib.sha256(json.dumps(
            terminal_review_body, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest(),
        "claim": None,
    }
    fidelity = {**fidelity_body, "receipt_sha256": hashlib.sha256(json.dumps(
        fidelity_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()}
    expected_windows = review_windows(manuscript)
    windows = [{
        "window": item["index"], "start": item["start"], "end": item["end"],
        "manuscript_sha256": digest,
        "window_sha256": hashlib.sha256(item["text"].encode()).hexdigest(),
        "summary": "complete review window", "issues": [],
    } for item in expected_windows]
    audit = {
        "coverage": 1.0, "window_count": len(windows),
        "reviewed_windows": len(windows), "prior_issue_ids": [],
        "reconciliations": [], "windows": windows,
        "adjudication_artifact": adjudication_artifact,
        "adjudication_receipt": {
            "accepted_stage_artifact": adjudication_artifact,
        },
    }
    _write_json(run / "outputs" / "final-review-evidence.json", {
        "windows": windows, "audit": audit,
    })
    _write_json(run / "outputs" / "quality-report.json", {
        "status": "passed", "terminal_review_complete": True,
        "terminal_reviewed_hash": digest,
        "best_attempt": 1,
        "best_score": 92,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/final-model",
        "terminal_review": {
            **terminal_review_body,
            "scoring_profile_id": "zhihu-short-v2",
            "judge_signature": "provider/final-model",
            "style_reference_fidelity": fidelity,
        },
        "final_review_evidence": audit,
    })
    (run / "outputs" / "final_review-adjudication.md").write_text(
        adjudication_text, encoding="utf-8",
    )
    review_text = "{}"
    (run / "outputs" / "review.md").write_text(review_text, encoding="utf-8")
    review_binding_body = {
        "schema": "ShortInitialReviewBindingV1", "version": 1,
        "review_sha256": hashlib.sha256(review_text.encode()).hexdigest(),
        "reviewed_draft_sha256": digest,
        "generation_context_sha256": "a" * 64,
        "style_reference_authority_sha256": authority["authority_sha256"],
    }
    _write_json(run / "outputs" / "review-binding-v1.json", {
        **review_binding_body,
        "binding_sha256": hashlib.sha256(json.dumps(
            review_binding_body, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest(),
    })
    _write_json(run / "outputs" / "short-checkpoint.json", {
        "generation_context_sha256": "a" * 64,
    })
    polish_integrity_path = run / "outputs" / "polish-integrity.json"
    _write_json(polish_integrity_path, {
        "status": "passed", "publication_sha256": digest, "issues": [],
        "segments": [{"segment": 1, "text_sha256": digest}],
        "accepted_event_ids": ["EV-00000001/01"],
    })
    _write_json(run / "outputs" / "quality-checkpoint.json", {
        "version": 1, "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": digest, "terminal_reviewed_hash": digest,
        "outcome": "passed", "score": 92, "best_attempt": 1,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/final-model",
        "review": {
            **terminal_review_body,
            "scoring_profile_id": "zhihu-short-v2",
            "judge_signature": "provider/final-model",
            "style_reference_fidelity": fidelity,
        },
        "issue_ledger": [],
        "narrative_integrity": {
            "path": "outputs/polish-integrity.json",
            "sha256": hashlib.sha256(polish_integrity_path.read_bytes()).hexdigest(),
        },
    })
    inventory = make_maintenance_inventory(
        source_mode="normal", source_artifact_hash=digest,
        base_authority_revision=1, base_authority_hash="e" * 64, units=[],
    )
    _write_json(
        run / "receipts" / "maintenance-inventory-initial.json",
        inventory.model_dump(mode="json", by_alias=True),
    )
    maintenance_contract = build_maintenance_window_contracts(
        manuscript, entry_state_sha256="f" * 64, target_characters=400,
    )[0]
    maintenance_envelope = adapt_maintenance_window_payload({
        "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
        "facts": [], "state_deltas": [], "state_transitions": [],
        "world_rules": [], "timeline": [],
    }, contract=maintenance_contract, manuscript=manuscript)
    maintenance_reduction = build_maintenance_reduction(
        manuscript=manuscript, source_state_sha256="f" * 64,
        envelopes=[maintenance_envelope],
        canon={"facts": [], "state": {}}, confirmed_facts=[],
    )
    _write_json(
        run / "receipts" / "maintenance-reduction-final.json",
        maintenance_reduction.model_dump(mode="json", by_alias=True),
    )
    _write_json(run / "outputs" / "project-mutation-journal.json", {
        "version": 1, "status": "committed",
        "operation": "short-story", "run_id": "run-1",
        "project_id": "project-1", "snapshot_path": "snapshots/run-1",
        "source_authority_sha256": digest,
        "expected_story_state_revision": 1,
        "managed_paths": [
            "manuscript/story.md", "chapters/chapter-01.md", "memory/canon.json",
        ],
        "artifacts": [
            {"path": "manuscript/story.md", "sha256": digest},
            {"path": "chapters/chapter-01.md", "sha256": digest},
            {"path": "memory/canon.json", "sha256": hashlib.sha256(
                canon.read_bytes(),
            ).hexdigest()},
        ],
        "story_state": {
            "candidate_id": "candidate-1", "expected_revision": 1,
            "target_revision": 2,
            "state_sha256": live_state_sha256, "data": live_state,
        }, "post_commit_gate": None,
        "memory_effects": [], "learning_artifact_invalidations": [],
    })
    return {
        "project": project, "run": run, "digest": digest,
        "live_state": live_state, "live_state_sha256": live_state_sha256,
    }


def _verify(fixture: dict, *, status: str = "completed", parity: str = "exact") -> dict:
    return verify_short_completion_v1(
        project_root=fixture["project"], run_root=fixture["run"],
        run_identity="run-1", workload_sha256="a" * 64,
        workflow_final_status=status, live_parity_status=parity,
        live_story_state_revision=2,
        live_story_state_sha256=fixture["live_state_sha256"],
        live_story_state_data=fixture["live_state"],
        expected_base_story_state_revision=1,
        expected_base_story_state_sha256="e" * 64,
        expected_maintenance_source_state_sha256="f" * 64,
        short_canonical_v2_enabled=False,
    )


@pytest.fixture(autouse=True)
def _unit_isolates_terminal_from_checkpoint_authority(monkeypatch) -> None:
    """Checkpoint graph truth is exercised by the real-workflow integration.

    These small tests isolate review, maintenance, artifact, and checkpoint
    classification without minting a test-only Planning authority graph.
    """

    monkeypatch.setattr(
        completion_verification, "_short_authority_chain",
        lambda *_args, **_kwargs: (True, "9" * 64),
    )


def test_exact_final_review_maintenance_artifact_and_checkpoint_pass(tmp_path: Path) -> None:
    receipt = _verify(_fixture(tmp_path))
    assert receipt["completion_goal_outcome"] == COMPLETION_GOAL
    assert receipt["final_review"]["binding_status"] == "exact"
    assert receipt["maintenance"]["closure_status"] == "exact"
    assert "sanitized final manuscript" not in json.dumps(receipt)


def test_suffixed_repair_adjudication_is_the_terminal_review_authority(
    tmp_path: Path,
) -> None:
    fx = _fixture(tmp_path)
    outputs = fx["run"] / "outputs"
    original = outputs / "final_review-adjudication.md"
    repaired = outputs / "final_review-2-adjudication.md"
    original.rename(repaired)
    artifact = {
        "path": "outputs/final_review-2-adjudication.md",
        "sha256": hashlib.sha256(repaired.read_bytes()).hexdigest(),
    }
    report = json.loads((outputs / "quality-report.json").read_text())
    report["final_review_evidence"]["adjudication_artifact"] = artifact
    report["final_review_evidence"]["adjudication_receipt"][
        "accepted_stage_artifact"
    ] = artifact
    _write_json(outputs / "quality-report.json", report)
    _write_json(outputs / "final-review-evidence.json", {
        "windows": report["final_review_evidence"]["windows"],
        "audit": report["final_review_evidence"],
    })

    assert _verify(fx)["completion_goal_outcome"] == COMPLETION_GOAL


@pytest.mark.parametrize("mutation,outcome", [
    ("review_rejected", "WORKFLOW_COMPLETED_FINAL_REVIEW_NOT_ACCEPTED"),
    ("review_missing", "VERIFICATION_INSUFFICIENT"),
    ("review_stale", "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"),
    ("maintenance_missing", "WORKFLOW_COMPLETED_MAINTENANCE_INCOMPLETE"),
    ("maintenance_invalid", "WORKFLOW_COMPLETED_MAINTENANCE_INCOMPLETE"),
    ("artifact_unbound", "WORKFLOW_COMPLETED_FINAL_ARTIFACT_UNBOUND"),
    ("checkpoint_stale", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_review_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_score_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_profile_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_judge_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_ledger_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_path_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_best_attempt_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("checkpoint_best_attempt_bool", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("report_best_attempt_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("report_best_attempt_bool", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("report_best_score_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("report_profile_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
    ("report_judge_drift", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
])
def test_completion_failures_are_typed(
    tmp_path: Path, mutation: str, outcome: str,
) -> None:
    fx = _fixture(tmp_path)
    if mutation == "review_rejected":
        report = json.loads((fx["run"] / "outputs/quality-report.json").read_text())
        report["status"] = "failed"
        _write_json(fx["run"] / "outputs/quality-report.json", report)
    elif mutation == "review_missing":
        (fx["run"] / "outputs/quality-report.json").unlink()
    elif mutation == "review_stale":
        report = json.loads((fx["run"] / "outputs/quality-report.json").read_text())
        report["terminal_reviewed_hash"] = "b" * 64
        _write_json(fx["run"] / "outputs/quality-report.json", report)
    elif mutation.startswith("report_"):
        report = json.loads((fx["run"] / "outputs/quality-report.json").read_text())
        field = {
            "report_best_attempt_drift": "best_attempt",
            "report_best_attempt_bool": "best_attempt",
            "report_best_score_drift": "best_score",
            "report_profile_drift": "scoring_profile_id",
            "report_judge_drift": "judge_signature",
        }[mutation]
        report[field] = {
            "best_attempt": (
                True if mutation == "report_best_attempt_bool" else 999
            ),
            "best_score": 1,
            "scoring_profile_id": "other-profile",
            "judge_signature": "other/judge",
        }[field]
        _write_json(fx["run"] / "outputs/quality-report.json", report)
    elif mutation == "maintenance_missing":
        (fx["run"] / "receipts/maintenance-inventory-initial.json").unlink()
    elif mutation == "maintenance_invalid":
        _write_json(fx["run"] / "receipts/maintenance-inventory-initial.json", [])
    elif mutation == "artifact_unbound":
        journal = json.loads((fx["run"] / "outputs/project-mutation-journal.json").read_text())
        journal["artifacts"][0]["sha256"] = "b" * 64
        _write_json(fx["run"] / "outputs/project-mutation-journal.json", journal)
    elif mutation == "checkpoint_stale":
        checkpoint = json.loads((fx["run"] / "outputs/quality-checkpoint.json").read_text())
        checkpoint["manuscript_hash"] = "b" * 64
        _write_json(fx["run"] / "outputs/quality-checkpoint.json", checkpoint)
    elif mutation.startswith("checkpoint_"):
        checkpoint = json.loads((fx["run"] / "outputs/quality-checkpoint.json").read_text())
        if mutation == "checkpoint_path_drift":
            duplicate = fx["run"] / "outputs/checkpoint-alternate.md"
            duplicate.write_bytes(
                (fx["run"] / "outputs/best-candidate.md").read_bytes()
            )
        field = {
            "checkpoint_review_drift": "review",
            "checkpoint_score_drift": "score",
            "checkpoint_profile_drift": "scoring_profile_id",
            "checkpoint_judge_drift": "judge_signature",
            "checkpoint_ledger_drift": "issue_ledger",
            "checkpoint_path_drift": "manuscript_path",
            "checkpoint_best_attempt_drift": "best_attempt",
            "checkpoint_best_attempt_bool": "best_attempt",
        }[mutation]
        checkpoint[field] = {
            "review": {**checkpoint["review"], "decision": "fail"},
            "score": 9.0,
            "scoring_profile_id": "other-profile",
            "judge_signature": "other/judge",
            "issue_ledger": [{"issue_id": "unbound"}],
            "manuscript_path": "outputs/checkpoint-alternate.md",
            "best_attempt": (
                True if mutation == "checkpoint_best_attempt_bool" else 999
            ),
        }[field]
        _write_json(fx["run"] / "outputs/quality-checkpoint.json", checkpoint)
    assert _verify(fx)["completion_goal_outcome"] == outcome


def test_old_review_cannot_prove_revised_formal_manuscript(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    (fx["project"] / "manuscript/story.md").write_text(
        "revised manuscript", encoding="utf-8",
    )
    assert _verify(fx)["completion_goal_outcome"] == (
        "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"
    )


def test_checkpoint_content_binding_uses_canonical_text_across_crlf(
    tmp_path: Path,
) -> None:
    fx = _fixture(tmp_path)
    manuscript = "first line\n\nsecond line"
    digest = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    path = fx["run"] / "outputs/best-candidate.md"
    path.write_bytes(manuscript.replace("\n", "\r\n").encode("utf-8"))

    assert completion_verification._text_hash(path) == digest
    assert hashlib.sha256(path.read_bytes()).hexdigest() != digest


def test_workflow_terminal_and_isolation_unknown_never_succeed(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    assert _verify(fx, status="failed")["completion_goal_outcome"] == "WORKFLOW_TERMINAL"
    assert _verify(fx, parity="unknown")["completion_goal_outcome"] == (
        "VERIFICATION_INSUFFICIENT"
    )


def test_workflow_completed_is_not_success_without_completion_goal() -> None:
    assert real_result_exit_code({
        "outcome": "WORKFLOW_COMPLETED",
        "short_completion_goal_outcome": (
            "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"
        ),
    }) == 4
    assert real_result_exit_code({
        "outcome": "WORKFLOW_COMPLETED",
        "short_completion_goal_outcome": COMPLETION_GOAL,
    }) == 0
    assert real_result_exit_code({"outcome": "WORKFLOW_COMPLETED"}) == 0
