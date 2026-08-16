from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.short_canonical_promotion import make_maintenance_inventory

from tools.canary.short_completion import COMPLETION_GOAL
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
    reviewed = run / "outputs" / "best-candidate.md"
    formal.parent.mkdir(parents=True)
    reviewed.parent.mkdir(parents=True)
    formal.write_text(manuscript, encoding="utf-8")
    reviewed.write_text(manuscript, encoding="utf-8")
    _write_json(run / "outputs" / "draft-integrity.json", {
        "status": "passed", "publication_sha256": digest,
    })
    _write_json(run / "outputs" / "quality-report.json", {
        "status": "passed", "terminal_review_complete": True,
        "terminal_reviewed_hash": digest,
    })
    _write_json(run / "outputs" / "quality-checkpoint.json", {
        "version": 1, "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": digest, "terminal_reviewed_hash": digest,
        "outcome": "passed", "score": 9.0,
    })
    inventory = make_maintenance_inventory(
        source_mode="normal", source_artifact_hash=digest,
        base_authority_revision=1, base_authority_hash=digest, units=[],
    )
    _write_json(
        run / "receipts" / "maintenance-inventory-initial.json",
        inventory.model_dump(mode="json", by_alias=True),
    )
    _write_json(run / "outputs" / "project-mutation-journal.json", {
        "version": 1, "status": "committed",
        "operation": "short_formal_promotion", "run_id": "run-1",
        "project_id": "project-1", "snapshot_path": "snapshots/run-1",
        "source_authority_sha256": digest,
        "expected_story_state_revision": 1,
        "managed_paths": ["manuscript/story.md"],
        "artifacts": [{"path": "manuscript/story.md", "sha256": digest}],
        "story_state": None, "post_commit_gate": None,
        "memory_effects": [], "learning_artifact_invalidations": [],
    })
    return {"project": project, "run": run, "digest": digest}


def _verify(fixture: dict, *, status: str = "completed", parity: str = "exact") -> dict:
    return verify_short_completion_v1(
        project_root=fixture["project"], run_root=fixture["run"],
        run_identity="run-1", workload_sha256="a" * 64,
        workflow_final_status=status, live_parity_status=parity,
    )


def test_exact_final_review_maintenance_artifact_and_checkpoint_pass(tmp_path: Path) -> None:
    receipt = _verify(_fixture(tmp_path))
    assert receipt["completion_goal_outcome"] == COMPLETION_GOAL
    assert receipt["final_review"]["binding_status"] == "exact"
    assert receipt["maintenance"]["closure_status"] == "exact"
    assert "sanitized final manuscript" not in json.dumps(receipt)


@pytest.mark.parametrize("mutation,outcome", [
    ("review_rejected", "WORKFLOW_COMPLETED_FINAL_REVIEW_NOT_ACCEPTED"),
    ("review_missing", "VERIFICATION_INSUFFICIENT"),
    ("review_stale", "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"),
    ("maintenance_missing", "WORKFLOW_COMPLETED_MAINTENANCE_INCOMPLETE"),
    ("maintenance_invalid", "WORKFLOW_COMPLETED_MAINTENANCE_INCOMPLETE"),
    ("artifact_unbound", "WORKFLOW_COMPLETED_FINAL_ARTIFACT_UNBOUND"),
    ("checkpoint_stale", "WORKFLOW_COMPLETED_CHECKPOINT_UNCLOSED"),
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
    assert _verify(fx)["completion_goal_outcome"] == outcome


def test_old_review_cannot_prove_revised_formal_manuscript(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    (fx["project"] / "manuscript/story.md").write_text(
        "revised manuscript", encoding="utf-8",
    )
    assert _verify(fx)["completion_goal_outcome"] == (
        "WORKFLOW_COMPLETED_FINAL_REVIEW_BINDING_INVALID"
    )


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
