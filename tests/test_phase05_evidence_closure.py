from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

# Test support modules intentionally live outside the production package.
_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.workflows import WorkflowService

from phase05_evidence_harness import (
    binding_matrix,
    inject_missing_event_types,
    maintenance_baseline,
    projection_matrix,
    saga_baseline,
    workflow_coverage,
)

# Reuse the repository's established deterministic paid-boundary replacements.
from test_workflows import (  # noqa: E402
    FakeGateway,
    SetupGateway,
    VolumeGateway,
    complete_checkpoint_plan,
    make_prompt_skills,
    save_test_complete_short_checkpoint,
)


class RecordingFakeGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({
            "role": role,
            "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
            "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
            "max_output_tokens": max_output_tokens,
        })
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


class ResumeGateway(RecordingFakeGateway):
    """Start at the first post-draft response for an exact checkpoint resume."""

    def __init__(self) -> None:
        super().__init__()
        next(self.responses)  # planning response replaced by checkpoint
        next(self.responses)  # draft response replaced by checkpoint


def _service(
    root: Path,
    *,
    mode: str,
    gateway,
    title: str,
) -> tuple[Database, ProjectStore, object, WorkflowService]:
    db = Database(root / "app.db")
    db.migrate()
    store = ProjectStore(db, root / "projects")
    project = store.create(ProjectCreate(
        title=title,
        mode=mode,
        genre="suspense" if mode == "short" else "fantasy",
        premise="Deterministic Phase 0.5 authority evidence.",
        target_words=6_000 if mode == "short" else 100_000,
    ))
    skill_root = root / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, gateway,
        SkillGate(db, SkillScanner([skill_root])),
    )
    return db, store, project, service


async def _run_short(root: Path, *, trace_enabled: bool) -> dict:
    gateway = RecordingFakeGateway()
    _db, _store, project, service = _service(
        root, mode="short", gateway=gateway, title="Phase 05 Short",
    )
    previous = os.environ.get("NOVEL_RELIABILITY_TRACE")
    os.environ["NOVEL_RELIABILITY_TRACE"] = "1" if trace_enabled else "0"
    try:
        result = await service.run_short(
            project.id, use_crewai=False, run_id="phase05-short",
        )
    finally:
        if previous is None:
            os.environ.pop("NOVEL_RELIABILITY_TRACE", None)
        else:
            os.environ["NOVEL_RELIABILITY_TRACE"] = previous
    formal = (project.path / "manuscript" / "story.md").read_bytes()
    state = StoryStateStore(service.db).get(project.id)
    assert state is not None
    return {
        "project": project,
        "service": service,
        "result": result,
        "gateway": gateway,
        "formal_sha256": hashlib.sha256(formal).hexdigest(),
        "story_state_revision": state.revision,
        "story_state_sha256": hashlib.sha256(json.dumps(
            state.data, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }


async def _run_long_setup(root: Path, *, title: str, run_id: str) -> dict:
    gateway = SetupGateway()
    _db, _store, project, service = _service(
        root, mode="long", gateway=gateway, title=title,
    )
    result = await service.run_long_setup(
        project.id, use_crewai=False, run_id=run_id,
    )
    return {"project": project, "service": service, "result": result}


async def _run_short_resume(root: Path) -> dict:
    gateway = ResumeGateway()
    db, store, project, service = _service(
        root, mode="short", gateway=gateway, title="Phase 05 Resume",
    )
    db.create_run(
        "phase05-resume-source", project.id, "short-story", status="failed",
    )
    outputs = project.path / "runs" / "phase05-resume-source" / "outputs"
    outputs.mkdir(parents=True)
    segment_count = service._short_segment_count(
        int(project.metadata["target_words"])
    )
    plan = complete_checkpoint_plan(segment_count)
    draft = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
        f"Checkpoint draft segment {number}."
        for number in range(1, segment_count + 1)
    )
    (outputs / "planning.md").write_text(plan, encoding="utf-8")
    (outputs / "draft.md").write_text(draft, encoding="utf-8")
    state = StoryStateStore(db).ensure(project.id, project.path)
    constraints = store.load_constraints(project.id)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, constraints, segment_count,
    )
    save_test_complete_short_checkpoint(
        service, project, outputs, context, constraints,
    )
    result = await service.run_short(
        project.id, use_crewai=False, run_id="phase05-resume-target",
    )
    return {"project": project, "service": service, "result": result}


async def _run_long_chapters(
    root: Path, *, chapter_count: int,
) -> dict:
    prepared = await _run_long_setup(
        root, title=f"Phase 05 Long {chapter_count}",
        run_id="phase05-long-setup-preparation",
    )
    project = prepared["project"]
    setup_service = prepared["service"]
    run_ids = []
    for number in range(1, chapter_count + 1):
        service = WorkflowService(
            setup_service.db, setup_service.projects, VolumeGateway(),
            setup_service.skills,
        )
        run_id = f"phase05-long-chapter-{number}"
        await service.run_chapter(
            project.id, f"Deterministic chapter goal {number}",
            use_crewai=False, run_id=run_id,
        )
        run_ids.append(run_id)
    return {
        "project": project,
        "service": setup_service,
        "run_ids": run_ids,
    }


@pytest.mark.asyncio
async def test_phase05_production_shaped_evidence_closure(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    short = await _run_short(tmp_path / "short", trace_enabled=True)
    short_repeat = await _run_short(
        tmp_path / "short-repeat", trace_enabled=True,
    )
    short_disabled = await _run_short(
        tmp_path / "short-disabled", trace_enabled=False,
    )
    long_setup = await _run_long_setup(
        tmp_path / "long-setup", title="Phase 05 Long Setup",
        run_id="phase05-long-setup",
    )
    long_chapter = await _run_long_chapters(
        tmp_path / "long-chapter", chapter_count=1,
    )
    long_multi = await _run_long_chapters(
        tmp_path / "long-multi", chapter_count=2,
    )
    short_resume = await _run_short_resume(tmp_path / "short-resume")

    workflows = {
        "short": (short["project"], [short["result"]["id"]]),
        "long_setup": (
            long_setup["project"], [long_setup["result"]["id"]],
        ),
        "long_chapter": (
            long_chapter["project"], long_chapter["run_ids"],
        ),
        "long_multi_chapter": (
            long_multi["project"], long_multi["run_ids"],
        ),
    }
    coverage = {}
    synthetic = {}
    for name, (project, run_ids) in workflows.items():
        synthetic[name] = inject_missing_event_types(
            project.path,
            correlation_id=run_ids[0],
            workflow_name=name,
            run_ids=run_ids,
        )
        coverage[name] = workflow_coverage(project.path, run_ids)
        assert coverage[name]["covered"] == 8
        assert coverage[name]["coverage_gaps"] == []

    chapter_projection = projection_matrix(
        long_chapter["project"].path, long_chapter["run_ids"],
    )
    context_read = next(
        row for row in chapter_projection
        if row["event_type"] == "projection_read"
        and row["projection"] == "StoryMemory.context"
    )
    assert context_read["requested_authority_revision"] == 1
    assert context_read["actual_source_revision"] == 1
    assert context_read["source_authority_hash"]
    assert context_read["projection_hash"]
    assert context_read["source_artifact"] == "ProjectMutationJournalV1"
    assert context_read["source_artifact_hash"]
    # Real current behavior: StoryState.ensure imports the setup canon into a
    # revision-1 row without incrementing the revision.  Provenance is closed,
    # but the authority hash therefore proves this projection is stale.
    assert context_read["freshness"] == "stale"

    bindings = binding_matrix(
        short["project"].path, [short["result"]["id"]],
    )
    resume_bindings = binding_matrix(
        short_resume["project"].path,
        [short_resume["result"]["id"]],
    )
    assert any(
        str(row["artifact_type"]).startswith("draft-")
        and row["binding_status"] == "exact"
        for row in bindings
    )
    assert any(
        row["artifact_type"] == "review.md"
        and row["reviewed_object_hash"]
        for row in bindings
    )
    assert any(
        str(row["policy"]).startswith("draft_")
        and row["reviewed_object_hash"]
        for row in bindings
    )
    assert any(
        row["artifact_type"] == "ShortCheckpoint"
        and row["validator_set"]
        for row in bindings
    )
    assert any(row["artifact_type"] == "repair_output" for row in bindings)
    assert any(
        row["binding_status"] == "reused"
        and row["input_object_hash"] == row["actual_input_object_hash"]
        and row["output_object_hash"]
        for row in resume_bindings
    )

    maintenance = maintenance_baseline(
        short["project"].path, short["result"]["id"],
    )
    maintenance_repeat = maintenance_baseline(
        short_repeat["project"].path, short_repeat["result"]["id"],
    )
    assert maintenance["decisions"]
    assert maintenance["repeatability_sha256"] == (
        maintenance_repeat["repeatability_sha256"]
    )
    saga = saga_baseline(short["project"].path, short["result"]["id"])
    saga_repeat = saga_baseline(
        short_repeat["project"].path, short_repeat["result"]["id"],
    )
    assert saga["commit_result"] == "committed"
    assert saga["repeatability_sha256"] == saga_repeat["repeatability_sha256"]

    assert short["formal_sha256"] == short_disabled["formal_sha256"]
    assert short["story_state_revision"] == short_disabled[
        "story_state_revision"
    ]
    assert short["story_state_sha256"] == short_disabled[
        "story_state_sha256"
    ]
    assert [
        (item["role"], item["max_output_tokens"])
        for item in short["gateway"].calls
    ] == [
        (item["role"], item["max_output_tokens"])
        for item in short_disabled["gateway"].calls
    ]
    assert len(short["gateway"].calls) == len(short_disabled["gateway"].calls)
    assert not trace_file_for_project(short_disabled["project"].path).exists()

    report = {
        "schema": "Phase05GoNoGoEvidenceReportV1",
        "coverage": coverage,
        "synthetic_event_types": synthetic,
        "projection_provenance_matrix": chapter_projection,
        "artifact_binding_matrix": [*bindings, *resume_bindings],
        "maintenance_baseline": maintenance,
        "maintenance_repeatability_sha256": maintenance_repeat[
            "repeatability_sha256"
        ],
        "saga_baseline": saga,
        "saga_repeatability_sha256": saga_repeat[
            "repeatability_sha256"
        ],
        "parity": {
            "formal_sha256": short["formal_sha256"],
            "story_state_revision": short["story_state_revision"],
            "story_state_sha256": short["story_state_sha256"],
            "ordered_offline_calls_sha256": hashlib.sha256(json.dumps(
                short["gateway"].calls, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "ordered_offline_call_delta": 0,
            "paid_llm_call_delta": 0,
        },
        "reader_coverage_gaps": {
            name: read_trace(
                trace_file_for_project(project.path)
            ).coverage_gaps
            for name, (project, _run_ids) in workflows.items()
        },
    }
    output = os.environ.get("NOVEL_PHASE05_EVIDENCE_REPORT")
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
