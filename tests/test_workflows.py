import asyncio
import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import WorkflowService


REQUIRED_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
}


class FakeGateway:
    def __init__(self) -> None:
        self.roles = []
        self.responses = iter([
            "# Story Plan\nA complete causal plan.",
            "# Draft\nRough story.",
            json.dumps({"score": 86, "hard_fail": False, "issues": ["tighten prose"]}),
            json.dumps({"score": 84, "hard_fail": False, "issues": ["strengthen paid hook"]}),
            "# Final Story\nHuman, polished prose.",
            json.dumps({"score": 92, "hard_fail": False, "issues": []}),
            json.dumps({"facts": [{"subject": "hero", "fact": "survived"}]}),
        ])

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        assert "Skill instructions" in system
        return ModelResult(next(self.responses), {"role": role, "model_name": f"fake-{role}"})


class SetupGateway(FakeGateway):
    def __init__(self) -> None:
        self.roles = []
        self.responses = iter([
            "# Book Bible\nEnding, volumes, characters, world rules and chapter map.",
            json.dumps({"score": 90, "hard_fail": False, "issues": []}),
            json.dumps({"facts": [{"fact_key": "ending", "value": "the oath is fulfilled"}]}),
        ])


class VolumeGateway(FakeGateway):
    def __init__(self) -> None:
        self.roles = []
        self.responses = iter([
            "# Chapter Plan",
            "# Draft",
            json.dumps({"score": 90, "hard_fail": False, "issues": []}),
            json.dumps({"score": 88, "hard_fail": False, "issues": []}),
            "# Polished",
            json.dumps({"score": 92, "hard_fail": False, "issues": []}),
            json.dumps({"facts": [], "state": {"hero": {"location": "gate"}}}),
            json.dumps({"score": 88, "hard_fail": False, "issues": []}),
        ])


def make_prompt_skills(root) -> None:
    for name in REQUIRED_SKILLS:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nSkill instructions for {name}.", encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_short_flywheel_archives_all_stages_and_formal_story(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Night Train", mode="short", genre="suspense",
        premise="A passenger vanishes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = FakeGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert gateway.roles == [
        "planning", "draft", "review", "review", "polish", "final_review", "maintenance",
    ]
    assert (project.path / "manuscript" / "story.md").read_text(encoding="utf-8") == "# Final Story\nHuman, polished prose."
    assert (project.path / "chapters" / "chapter-01.md").is_file()
    assert json.loads((project.path / "memory" / "canon.json").read_text(encoding="utf-8"))["facts"]
    run_path = project.path / "runs" / result["id"]
    assert (run_path / "outputs" / "planning.md").is_file()
    assert (run_path / "outputs" / "final_review.md").is_file()
    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(encoding="utf-8"))
    assert report["route"]["enhanced"] is True
    assert report["reader_review"] is not None
    assert report["status"] == "passed"
    events = db.list_run_events(result["id"])
    assert any(item["event_type"] == "stage_started" and item["stage"] == "planning" for item in events)
    event_types = [item["event_type"] for item in events]
    assert "quality_route" in event_types
    assert "quality_assessed" in event_types
    assert "quality_escalated" in event_types
    assert any(item["event_type"] == "quality_gate" and item["severity"] == "success"
               for item in events)
    escalation = next(item for item in events if item["event_type"] == "quality_escalated")
    assert escalation["metadata"]["model_role"] == "review"
    assert escalation["metadata"]["fallback_used"] is True
    completed = next(item for item in events if item["event_type"] == "stage_completed")
    assert completed["metadata"]["model_name"].startswith("fake-")
    assert completed["metadata"]["skills"]


@pytest.mark.asyncio
async def test_short_flywheel_uses_managed_run_id_and_restores_on_cancel(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Cancel", mode="short", genre="suspense",
        premise="A passenger vanishes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class BlockingGateway:
        def __init__(self):
            self.started = asyncio.Event()

        async def complete(self, role, system, user, max_output_tokens=None):
            self.started.set()
            await asyncio.Event().wait()

    gateway = BlockingGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("managed-run", project.id, "short-story", status="queued")

    task = asyncio.create_task(service.run_short(
        project.id, use_crewai=False, run_id="managed-run",
    ))
    await gateway.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert db.get_run("managed-run")["status"] == "cancelled"
    assert not (project.path / "manuscript" / "story.md").exists()


@pytest.mark.asyncio
async def test_short_flywheel_rejects_long_project(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    with pytest.raises(ValueError, match="short"):
        await WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([]))).run_short(
            project.id, use_crewai=False,
        )


@pytest.mark.asyncio
async def test_long_chapter_uses_memory_and_writes_next_number(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = FakeGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_chapter(project.id, "The hero reaches the observatory", use_crewai=False)

    assert result["status"] == "completed"
    assert (project.path / "chapters" / "chapter-01.md").is_file()
    assert db.get_run(result["id"])["workflow"] == "long-chapter"


@pytest.mark.asyncio
async def test_long_setup_writes_book_bible_and_canon(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(db, store, SetupGateway(), SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_long_setup(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert "Book Bible" in (project.path / "outline.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_volume_boundary_runs_audit_and_persists_result(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    (project.path / "memory" / "volumes.json").write_text(json.dumps({"volumes": [{
        "number": 1, "start_chapter": 1, "end_chapter": 1, "goal": "Reach the gate",
    }]}), encoding="utf-8")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(db, store, VolumeGateway(), SkillGate(db, SkillScanner([skill_root])))

    await service.run_chapter(project.id, "Reach the gate", use_crewai=False)

    audit = json.loads((project.path / "memory" / "audits" / "volume-01.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"


class RecordingGateway:
    def __init__(self, responses) -> None:
        self.roles = []
        self.calls = []
        self.responses = iter(responses)

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        self.calls.append({"role": role, "system": system, "user": user})
        return ModelResult(next(self.responses), {"role": role, "model_name": f"fake-{role}"})


class ReaderFallbackGateway(RecordingGateway):
    async def complete(self, role, system, user, max_output_tokens=None):
        if role == "reader_review":
            self.roles.append(role)
            raise RuntimeError("reader provider unavailable")
        return await super().complete(role, system, user, max_output_tokens)


class SegmentGateway:
    def __init__(self):
        self.roles = []
        self.calls = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        self.calls.append({"role": role, "user": user})
        number = len(self.calls)
        return ModelResult(f"第{number}段" + "正文" * 1250, {
            "role": role, "model_name": f"fake-{role}",
        })


def quality_review(commercial=85, story=85, prose=85, *, hard_fail=False,
                   decision="pass", issues=None) -> str:
    return json.dumps({
        "dimensions": {"commercial": commercial, "story": story, "prose": prose},
        "hard_fail": hard_fail,
        "decision": decision,
        "issues": issues or [],
    })


@pytest.mark.asyncio
async def test_ordinary_chapter_allows_one_corrective_cycle(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    for number in range(1, 8):
        (project.path / "chapters" / f"chapter-{number:02d}.md").write_text(
            f"# Chapter {number}", encoding="utf-8",
        )
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), "# Polish 1",
        quality_review(commercial=70), "# Polish 2", quality_review(),
        json.dumps({"facts": [], "state": {}}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    await service.run_chapter(project.id, "An ordinary transition", use_crewai=False)

    assert gateway.roles.count("review") == 1
    assert gateway.roles.count("polish") == 2
    assert gateway.roles.count("final_review") == 2


@pytest.mark.asyncio
async def test_opening_chapter_allows_two_corrective_cycles(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A long tale.", target_words=100000,
    ))
    project.metadata["story_requirements"] = {
        "platform": "知乎盐选", "audience": "女性情感读者",
    }
    (project.path / "project.json").write_text(
        json.dumps(project.metadata, ensure_ascii=False), encoding="utf-8",
    )
    db.save_role_binding("reader_review", "provider", "model", None, None)
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(), "# Polish 1",
        quality_review(commercial=70), "# Polish 2",
        quality_review(story=65), "# Polish 3", quality_review(),
        json.dumps({"facts": [], "state": {}}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    await service.run_chapter(project.id, "Introduce the hero", use_crewai=False)

    assert gateway.roles.count("review") == 1
    assert gateway.roles.count("reader_review") == 1
    assert gateway.roles.count("polish") == 3
    assert gateway.roles.count("final_review") == 3
    reader_call = next(call for call in gateway.calls if "TARGET READER SIMULATION" in call["user"])
    assert reader_call["role"] == "reader_review"
    assert "知乎盐选" in reader_call["user"]
    assert "女性情感读者" in reader_call["user"]
    assert "reader_signals" in reader_call["user"]


@pytest.mark.asyncio
async def test_short_story_falls_back_to_review_when_reader_model_fails(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Fallback", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    db.save_role_binding("reader_review", "reader-provider", "reader-model", None, None)
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = ReaderFallbackGateway([
        "# Plan", "# Draft", quality_review(), "# Polish", quality_review(),
        json.dumps({"facts": []}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert gateway.roles.count("reader_review") == 1
    assert gateway.roles.count("review") == 1
    events = db.list_run_events(result["id"])
    fallback = next(item for item in events if item["event_type"] == "reader_fallback")
    assert fallback["severity"] == "warning"
    assert fallback["metadata"]["failed_role"] == "reader_review"


@pytest.mark.asyncio
async def test_large_short_story_draft_is_generated_in_bounded_segments(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Serial Short", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=20000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = SegmentGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("segmented", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "segmented"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    draft = await service._draft_short_in_segments(
        "segmented", run_path, project, "constraints", "approved plan",
    )

    assert WorkflowService._short_segment_count(20000) == 8
    assert gateway.roles == ["draft"] * 8
    assert all("不要提问" in call["user"] for call in gateway.calls)
    assert len(WorkflowService._split_segments(draft)) == 8
    assert (run_path / "outputs" / "draft.md").read_text(encoding="utf-8") == draft


@pytest.mark.asyncio
async def test_failed_quality_report_keeps_evidence_without_formal_story(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Failed", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    failed = quality_review(commercial=60, story=60, prose=60, decision="revise")
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(), "# Polish 1",
        failed, "# Polish 2", failed, "# Polish 3", failed,
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    with pytest.raises(RuntimeError, match="quality gate"):
        await service.run_short(project.id, use_crewai=False)

    run = db.list_runs(project.id)[0]
    report = json.loads((
        project.path / "runs" / run["id"] / "outputs" / "quality-report.json"
    ).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert len(report["final_attempts"]) == 3
    assert report["failure_reasons"]
    assert not (project.path / "manuscript" / "story.md").exists()
    events = db.list_run_events(run["id"])
    assert any(item["event_type"] == "quality_gate" and item["severity"] == "error"
               for item in events)
