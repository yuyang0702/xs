import asyncio
import json
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.quality import review_windows
from novel_flywheel.revision import segment_map
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.workflows import PolishTokenBudgetError, RevisionPlanError, StageText, WorkflowService


REQUIRED_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
}


class FakeGateway:
    def __init__(self) -> None:
        self.roles = []
        self.systems = []
        self.responses = iter([
            "# Story Plan\nA complete causal plan.",
            "# Draft\nRough story.",
            json.dumps({"score": 86, "hard_fail": False, "issues": ["tighten prose"]}),
            json.dumps({"score": 84, "hard_fail": False, "issues": ["strengthen paid hook"]}),
            "# Final Story\nHuman, polished prose.",
            json.dumps({"score": 92, "hard_fail": False, "issues": []}),
            json.dumps({"facts": ["The hero survived."]}),
        ])

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        self.systems.append(system)
        assert "Skill instructions" in system
        return ModelResult(next(self.responses), {"role": role, "model_name": f"fake-{role}"})


class SetupGateway(FakeGateway):
    def __init__(self) -> None:
        self.roles = []
        self.systems = []
        self.responses = iter([
            "# Book Bible\nEnding, volumes, characters, world rules and chapter map.",
            json.dumps({"score": 90, "hard_fail": False, "issues": []}),
            json.dumps({"facts": [{"fact_key": "ending", "value": "the oath is fulfilled"}]}),
        ])


class VolumeGateway(FakeGateway):
    def __init__(self) -> None:
        self.roles = []
        self.systems = []
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
async def test_material_audit_records_evidenced_conflicts(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Audit", mode="short", genre="suspense",
        premise="A contradiction.", target_words=1000,
    ))
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("沈砚端起酒杯，一饮而尽。" * 400, encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def fake_stage(*args, **kwargs):
        return json.dumps({"issues": [{
            "category": "character_habit", "severity": "high",
            "evidence": "沈砚一饮而尽", "location": "开篇",
            "old_setting": "饮酒", "new_setting": "从不饮酒", "action": "修订动作",
        }]}, ensure_ascii=False)

    service._stage = fake_stage
    result = await service.run_materials_audit(project.id, use_crewai=False)

    assert result["status"] == "completed"
    state = StoryStateStore(db).get(project.id)
    assert state is not None
    assert state.data["issue_ledger"][0]["source"] == "materials_audit"


@pytest.mark.asyncio
async def test_material_audit_reuses_fallback_after_first_window_timeout(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Audit circuit", mode="short", genre="suspense",
        premise="A long contradiction.", target_words=5000,
    ))
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("沈砚沿着长廊检查每一扇门。" * 1200, encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))
    routes = []

    async def fake_stage(*args, **kwargs):
        routes.append(kwargs.get("prefer_configured_fallback", False))
        receipt = {"fallback_used": True} if len(routes) == 1 else {
            "configured_fallback_direct": True,
        }
        return StageText('{"issues": []}', receipt)

    service._stage = fake_stage
    result = await service.run_materials_audit(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert len(routes) > 1
    assert routes == [False, *([True] * (len(routes) - 1))]
    events = db.list_run_events(result["id"])
    assert sum(event["event_type"] == "materials_audit_circuit_opened"
               for event in events) == 1


@pytest.mark.asyncio
async def test_material_audit_resume_reuses_completed_window_checkpoints(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Audit resume", mode="short", genre="suspense",
        premise="Resume a long audit.", target_words=5000,
    ))
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("沈砚沿着长廊检查每一扇门。" * 1200, encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))
    first_calls = 0

    async def interrupted_stage(*args, **kwargs):
        nonlocal first_calls
        first_calls += 1
        if first_calls == 3:
            raise RuntimeError("Server disconnected without sending a response")
        return StageText('{"issues": []}', {})

    service._stage = interrupted_stage
    with pytest.raises(RuntimeError, match="Server disconnected"):
        await service.run_materials_audit(
            project.id, use_crewai=False, run_id="resumable-audit",
        )

    resumed_calls = 0

    async def resumed_stage(*args, **kwargs):
        nonlocal resumed_calls
        resumed_calls += 1
        return StageText('{"issues": []}', {})

    service._stage = resumed_stage
    result = await service.run_materials_audit(
        project.id, use_crewai=False, run_id="resumable-audit",
    )

    assert result["status"] == "completed"
    assert first_calls + resumed_calls - 1 == len(review_windows(manuscript.read_text(encoding="utf-8")))
    events = db.list_run_events("resumable-audit")
    assert sum(event["event_type"] == "materials_audit_checkpoint_reused"
               for event in events) == 2


@pytest.mark.asyncio
async def test_material_repair_preserves_candidate_until_publication(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Repair", mode="short", genre="suspense",
        premise="Repair a contradiction.", target_words=1000,
    ))
    formal = project.path / "manuscript" / "story.md"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text("原始正文。" * 1200, encoding="utf-8")
    db.create_run("audit", project.id, "materials-audit", status="completed")
    audit_output = project.path / "runs" / "audit" / "outputs"
    audit_output.mkdir(parents=True)
    (audit_output / "conflict-report.json").write_text(json.dumps({
        "issues": [{"category": "character", "severity": "high", "evidence": "冲突"}],
    }, ensure_ascii=False), encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def fake_polish(*args, **kwargs):
        return "修订候选。" * 1200

    async def fake_review(*args, **kwargs):
        return ({
            "score": 90, "dimensions": {"commercial": 90, "story": 90, "prose": 90},
            "hard_fail": False, "decision": "pass", "issues": [],
        }, {"coverage": 1.0})

    service._polish_short_segments = fake_polish
    service._full_manuscript_review = fake_review
    result = await service.run_materials_repair(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert formal.read_text(encoding="utf-8").startswith("原始正文")
    candidate = project.path / "runs" / result["id"] / "outputs" / "best-candidate.md"
    assert candidate.read_text(encoding="utf-8").startswith("修订候选")


def test_post_write_maintenance_uses_project_id_and_restores_story_title(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="中文书名", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    original = (project.path / "story.md").read_text(encoding="utf-8")

    class RecordingSkills:
        def __init__(self) -> None:
            self.titles = []

        def skills(self, project_root):
            return {"story-maintenance": SimpleNamespace(executable=True)}

        def run_required(self, stage, required, commands, cwd, project_root):
            story = (project.path / "story.md").read_text(encoding="utf-8")
            self.titles.append(next(
                line.removeprefix("title: ") for line in story.splitlines()
                if line.startswith("title: ")
            ))

    skills = RecordingSkills()
    service = WorkflowService(db, store, FakeGateway(), skills)

    service._post_write_maintenance("run", project)

    assert skills.titles == [project.id, project.id, project.id]
    assert (project.path / "story.md").read_text(encoding="utf-8") == original


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
    state = StoryStateStore(db).get(project.id)
    assert state is not None
    assert state.revision == 2
    assert state.data["manuscript_revision"] == 1
    assert state.data["confirmed_facts"][0]["value"] == "The hero survived."
    assert any(item["event_type"] == "story_state_committed" for item in events)


@pytest.mark.asyncio
async def test_draft_uses_style_profile_only_when_project_enables_it(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Voice", mode="short", genre="suspense",
        premise="A passenger vanishes.", target_words=6000,
    ))
    project.metadata["style_sample_scope"] = "draft_and_polish"
    (project.path / "project.json").write_text(
        json.dumps(project.metadata, ensure_ascii=False), encoding="utf-8",
    )
    (project.path / "style-profile.md").write_text("# 风格\n\n动作推动情绪。", encoding="utf-8")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = FakeGateway()

    await WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    ).run_short(project.id, use_crewai=False)

    draft_system = gateway.systems[gateway.roles.index("draft")]
    assert "PROJECT STYLE PROFILE" in draft_system
    assert "动作推动情绪" in draft_system


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
    assert StoryStateStore(db).get(project.id).revision == 1


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


class ExplicitFallbackGateway:
    async def complete(self, role, system, user, max_output_tokens=None):
        return ModelResult("fallback output", {
            "role": role,
            "provider_id": "backup-provider",
            "model_id": "backup-model",
            "model_name": "backup-name",
            "fallback_used": True,
            "fallback_from_provider_id": "primary-provider",
            "fallback_from_model_id": "primary-model",
        })


@pytest.mark.asyncio
async def test_stage_logs_explicit_model_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Fallback log", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, ExplicitFallbackGateway(), SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("fallback-log", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "fallback-log"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._stage(
        "fallback-log", run_path, project, "polish", "constraints", "text",
        allow_tools=False,
    )

    event = next(
        item for item in db.list_run_events("fallback-log")
        if item["event_type"] == "model_fallback"
    )
    assert event["metadata"]["fallback_type"] == "configured"
    assert event["metadata"]["provider_id"] == "backup-provider"
    assert event["metadata"]["model_id"] == "backup-model"
    assert "primary_error" in event["metadata"]


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
async def test_short_story_repairs_reader_review_with_single_quoted_field_boundary(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Reader repair", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    db.save_role_binding("reader_review", "reader-provider", "reader-model", None, None)
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    malformed_reader_review = """{
      "commercial": 82,
      "story": 80,
      "prose": 78,
      "hard_fail": false,
      "decision": "revise",
      "issues": [{
        "category": "continuity",
        "severity": "medium",
        "evidence": "The clue lacks a source.', 'action': "Add a visible source."
      }],
      "reader_signals": {
        "would_continue": true,
        "would_pay": true,
        "abandonment_point": "none",
        "payoff_felt": true
      }
    }"""
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), malformed_reader_review,
        "# Polish", quality_review(), json.dumps({"facts": []}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    events = db.list_run_events(result["id"])
    assert not any(item["event_type"] == "reader_fallback" for item in events)
    repaired = next(item for item in events if item["event_type"] == "reader_review_repaired")
    assert repaired["metadata"]["strategy"] == "conservative_json_repair"


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
async def test_polish_stage_sends_compact_skill_prompt_only(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Compact", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    (skill_root / "humanizer-zh" / "SKILL.md").write_text(
        "---\nname: humanizer-zh\n---\n# Humanizer\n## Hard Rules\n"
        "- Never flatten character voice.\n## Examples\n改写前：REMOVE_THIS_EXAMPLE\n",
        encoding="utf-8",
    )
    better = skill_root / "better-writing"
    better.mkdir()
    (better / "SKILL.md").write_text(
        "---\nname: better-writing\n---\n# Better Writing\n- Preserve irregular human voice.\n",
        encoding="utf-8",
    )
    (better / "scripts").mkdir()
    (better / "scripts" / "validate.py").write_text("raise SystemExit(9)", encoding="utf-8")
    gateway = RecordingGateway(["polished", "drafted"])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("compact", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "compact"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._stage("compact", run_path, project, "polish", "constraints", "text")
    await service._stage("compact", run_path, project, "draft", "constraints", "text")

    assert "Never flatten character voice" in gateway.calls[0]["system"]
    assert "Preserve irregular human voice" in gateway.calls[0]["system"]
    assert "REMOVE_THIS_EXAMPLE" not in gateway.calls[0]["system"]
    assert "Skill instructions for chapter-writing" in gateway.calls[1]["system"]
    assert "Preserve irregular human voice" in gateway.calls[1]["system"]
    receipts = db.list_skill_receipts()
    assert sum(item["skill_name"] == "better-writing" for item in receipts) == 2


@pytest.mark.asyncio
async def test_segment_polish_rejects_truncated_output_and_keeps_original(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Protected", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=20000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    original = "原文" * 1000
    gateway = RecordingGateway(["太短", "仍然太短"])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("protected", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "protected"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    polished = await service._polish_short_segments(
        "protected", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join([original, original]), "{}",
    )

    assert WorkflowService._split_segments(polished) == [original, original]
    events = db.list_run_events("protected")
    assert sum(item["event_type"] == "polish_output_rejected" for item in events) == 2
    checkpoint_root = run_path / "outputs" / "polish-checkpoints" / "initial"
    assert not list(checkpoint_root.glob("*.json"))


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
        quality_review(commercial=70, story=70, prose=70, decision="revise"),
        "# Polish 2", failed, "# Polish 3",
        quality_review(commercial=65, story=65, prose=65, decision="revise"),
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
    assert report["best_attempt"] == 1
    assert report["best_score"] == 70
    assert (project.path / "runs" / run["id"] / "outputs" / "best-candidate.md").read_text(
        encoding="utf-8",
    ) == "# Polish 1"
    assert not (project.path / "manuscript" / "story.md").exists()
    events = db.list_run_events(run["id"])
    assert any(item["event_type"] == "quality_gate" and item["severity"] == "error"
               for item in events)
    corrective_calls = [call for call in gateway.calls if call["role"] == "polish"][1:]
    assert all("replace or remove implausible events" in call["user"] for call in corrective_calls)


@pytest.mark.asyncio
async def test_short_story_stops_on_safe_conditional_pass(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Conditional", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    conditional = quality_review(
        commercial=75, story=75, prose=75, decision="revise",
        issues=[{"severity": "medium", "action": "Tighten one paragraph."}],
    )
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(),
        "# Publishable candidate", conditional,
        json.dumps({"facts": []}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert gateway.roles.count("polish") == 1
    assert gateway.roles.count("final_review") == 1
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == "# Publishable candidate"
    report = json.loads((
        project.path / "runs" / result["id"] / "outputs" / "quality-report.json"
    ).read_text(encoding="utf-8"))
    assert report["status"] == "conditional_pass"
    assert report["final_attempts"][0]["outcome"] == "conditional_pass"
    event = next(
        item for item in db.list_run_events(result["id"])
        if item["event_type"] == "quality_gate"
    )
    assert event["severity"] == "success"
    assert event["metadata"]["outcome"] == "conditional_pass"
    assert "条件通过" in event["message"]


@pytest.mark.asyncio
async def test_structural_revision_plans_and_only_rewrites_target_segments(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Targeted", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "global_facts": ["The public ceremony is a wedding."],
        "checks": [
            {"kind": "forbidden_text", "value": "engagement banquet"},
            {"kind": "forbidden_text", "value": '"'},
        ],
        "tasks": [{"segments": [2], "instruction": "Unify the ceremony timeline."}],
    })
    gateway = RecordingGateway([
        plan,
        'Revised middle at the wedding. "修好了。" ' * 55,
        'The wedding continues correctly. "继续。" ' * 55,
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("targeted", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "targeted"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    parts = ["Opening " * 150, "Middle engagement banquet " * 100, "Ending " * 150]
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)
    findings = json.dumps({
        "dimensions": {"commercial": 70, "story": 50, "prose": 70},
        "score": 62,
        "hard_fail": True,
        "decision": "rewrite",
        "issues": [{
            "category": "continuity", "severity": "critical",
            "evidence": "Wedding and engagement banquet conflict.",
            "action": "Use one ceremony timeline.",
        }],
    })

    revised = await service._polish_short_segments(
        "targeted", run_path, project, "constraints", manuscript, findings,
        suffix="-2", structural=True,
    )

    revised_parts = WorkflowService._split_segments(revised)
    assert revised_parts[0] == parts[0].strip()
    assert revised_parts[2] == parts[2].strip()
    assert "Revised middle" in revised_parts[1]
    assert '"修好了。"' not in revised_parts[1]
    assert "“修好了。”" in revised_parts[1]
    assert gateway.roles == ["planning", "polish"]
    for call in gateway.calls[1:]:
        assert "The public ceremony is a wedding." in call["user"]
        assert "NEXT ORIGINAL START" in call["user"]
        assert "Return between" in call["user"]
    events = db.list_run_events("targeted")
    planned = next(item for item in events if item["event_type"] == "revision_planned")
    assert planned["metadata"]["target_segments"] == [2]
    checks = json.loads((run_path / "outputs" / "revision-checks-2.json").read_text(
        encoding="utf-8",
    ))
    assert checks == {"failures": []}


@pytest.mark.asyncio
async def test_invalid_structural_plan_stops_without_rewriting_segments(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Blocked", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["not valid json"])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("blocked", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "blocked"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["A" * 500] * 5)

    with pytest.raises(RevisionPlanError, match="Structural revision plan"):
        await service._polish_short_segments(
            "blocked", run_path, project, "constraints", manuscript,
            json.dumps({"issues": [{"severity": "critical", "action": "Repair canon."}]}),
            suffix="-2", structural=True,
        )

    assert gateway.roles == ["planning", "review"]
    event = next(item for item in db.list_run_events("blocked")
                 if item["event_type"] == "revision_plan_blocked")
    assert event["severity"] == "error"
    assert not (run_path / "outputs" / "polish-2.md").exists()


@pytest.mark.asyncio
async def test_structural_revision_sends_each_target_scene_once(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Whole scene", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [{"segments": [2], "instruction": "Repair the wrong fact."}],
    })

    class WholeSceneGateway:
        def __init__(self):
            self.roles = []
            self.polish_inputs = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.roles.append(role)
            if role == "planning":
                return ModelResult(plan, {"model_name": "planner"})
            source = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            self.polish_inputs.append(source)
            return ModelResult(source.replace("wrong fact", "correct fact"), {
                "model_name": "polisher", "input_tokens": 1000,
            })

    gateway = WholeSceneGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("whole-scene", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "whole-scene"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    target = ("wrong fact. " * 375).strip()
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join([
        "Opening " * 100, target, "Ending " * 100,
    ])

    revised = await service._polish_short_segments(
        "whole-scene", run_path, project, "constraints", manuscript,
        json.dumps({"issues": [{
            "category": "canon", "severity": "critical", "action": "Repair canon.",
        }]}), suffix="-2", structural=True,
    )

    assert gateway.roles == ["planning", "polish"]
    assert gateway.polish_inputs == [target]
    assert "wrong fact" not in revised
    polish_call = next(call for call in db.list_run_events("whole-scene")
                       if call["event_type"] == "polish_segment_route")
    assert polish_call["metadata"]["characters"] == len(target)


@pytest.mark.asyncio
async def test_structural_compression_in_gray_zone_reaches_final_review(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Gray zone", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    source = "A" * 1000
    candidate = "B" * 550
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "A" * 20}],
        "tasks": [{"segments": [2], "instruction": "Compress and remove repetition."}],
    })
    gateway = RecordingGateway([plan, candidate])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("gray-zone", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "gray-zone"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    revised = await service._polish_short_segments(
        "gray-zone", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["Opening", source, "Ending"]),
        json.dumps({"issues": [{
            "category": "ending", "severity": "critical", "action": "Compress it.",
        }]}), suffix="-2", structural=True,
    )

    assert WorkflowService._split_segments(revised) == ["Opening", candidate, "Ending"]
    event = next(item for item in db.list_run_events("gray-zone")
                 if item["event_type"] == "polish_conditional_length")
    assert event["metadata"]["ratio"] == 0.55
    assert event["metadata"]["review_required"] is True


@pytest.mark.asyncio
async def test_truncated_revision_plan_falls_back_to_review_role(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Plan fallback", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [{"segments": [2], "instruction": "Repair the canon conflict."}],
    })

    class TruncatedPlanGateway(RecordingGateway):
        async def complete(self, role, system, user, max_output_tokens=None):
            self.roles.append(role)
            self.calls.append({"role": role, "system": system, "user": user})
            if role == "planning":
                return ModelResult("", {
                    "model_name": "deepseek-v4-pro", "input_tokens": 5615,
                    "output_tokens": 8192, "finish_reason": "max_tokens",
                })
            return ModelResult(plan, {"model_name": "review-model"})

    gateway = TruncatedPlanGateway([])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("plan-fallback", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "plan-fallback"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._plan_structural_revision(
        "plan-fallback", run_path, project, "constraints",
        json.dumps({"issues": [{
            "category": "canon", "severity": "critical", "action": "Repair canon.",
        }]}),
        segment_map(["A" * 300] * 5), "-2",
    )

    assert result["target_segments"] == [2]
    assert gateway.roles == ["planning", "review"]
    assert any(event["event_type"] == "model_fallback"
               for event in db.list_run_events("plan-fallback"))


@pytest.mark.asyncio
async def test_structural_polish_stops_at_round_input_budget(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Budget", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [{"segments": [1, 2], "instruction": "Repair the contradiction."}],
    })

    class BudgetGateway(RecordingGateway):
        async def complete(self, role, system, user, max_output_tokens=None):
            result = await super().complete(role, system, user, max_output_tokens)
            if role == "polish":
                result.receipt["input_tokens"] = 60000
            return result

    gateway = BudgetGateway([plan, "A" * 500])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("budget", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "budget"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["A" * 500] * 5)

    with pytest.raises(PolishTokenBudgetError, match="round"):
        await service._polish_short_segments(
            "budget", run_path, project, "constraints", manuscript,
            json.dumps({"issues": [{"severity": "critical", "action": "Repair."}]}),
            suffix="-2", structural=True,
        )

    assert gateway.roles == ["planning", "polish"]
    assert any(item["event_type"] == "token_budget_exhausted"
               for item in db.list_run_events("budget"))


@pytest.mark.asyncio
async def test_prior_polish_usage_does_not_block_a_new_bounded_round(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Total budget", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["A" * 500])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("total-budget", project.id, "short-story", status="running")
    db.add_run_event(
        "total-budget", "success", "stage_completed", "prior polish",
        stage="polish", metadata={"input_tokens": 220000},
    )
    run_path = project.path / "runs" / "total-budget"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._polish_short_segments(
        "total-budget", run_path, project, "constraints", "A" * 500, "{}",
    )

    assert result == "A" * 500
    assert gateway.roles == ["polish"]


@pytest.mark.asyncio
async def test_quality_flow_preserves_best_candidate_when_polish_is_blocked(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Preserved", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("preserved", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "preserved"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    async def blocked(*args, **kwargs):
        raise PolishTokenBudgetError("Polish total input token budget exhausted")

    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_polish_short_segments", blocked)
    draft = "The best available draft."

    with pytest.raises(RuntimeError, match="preserved best candidate"):
        await service._quality_polish(
            "preserved", run_path, project, "constraints", draft,
            service._review(quality_review(commercial=60, story=60, prose=60)),
        )

    assert (run_path / "outputs" / "best-candidate.md").read_text(
        encoding="utf-8",
    ) == draft
    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    assert report["status"] == "halted"
    assert report["halt_reason"] == "token_budget_exhausted"


def test_stage_output_budgets_cover_each_model_role() -> None:
    assert WorkflowService._stage_output_budget("planning") == 12288
    assert WorkflowService._stage_output_budget("draft") == 8192
    assert WorkflowService._stage_output_budget("review") == 4096
    assert WorkflowService._stage_output_budget("revision_plan") == 8192
    assert WorkflowService._stage_output_budget("polish") == 8192
    assert WorkflowService._stage_output_budget("final_review") == 8192
    assert WorkflowService._stage_output_budget("maintenance") == 4096


def test_initial_polish_input_cap_scales_with_smaller_segment_count() -> None:
    assert WorkflowService._polish_round_input_cap(False, 5) == 120_000
    assert WorkflowService._polish_round_input_cap(False, 15) == 300_000
    assert WorkflowService._polish_round_input_cap(True, 15) == 60_000


def test_polish_splitter_merges_tiny_trailing_chunk() -> None:
    text = "A" * 1400 + "\n\n" + "B" * 300

    chunks = WorkflowService._split_polish_segments(text)

    assert [len(chunk) for chunk in chunks] == [1702]


def test_default_polish_segments_stay_below_adaptive_maximum() -> None:
    text = "\n\n".join(f"paragraph-{index}-" + "x" * 430 for index in range(8))

    chunks = WorkflowService._split_polish_segments(text)

    assert len(chunks) > 1
    assert max(map(len, chunks)) <= 1800


@pytest.mark.asyncio
async def test_recoverable_polish_failure_splits_segment_without_draft_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Split retry", mode="short", genre="romance",
        premise="Two people reconcile.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.roles = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.roles.append(role)
            if len(self.roles) == 1:
                raise RuntimeError("524 Gateway Timeout")
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "claude-sonnet-5", "input_tokens": 2000,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("split-retry", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "split-retry"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = "\n\n".join((f"Paragraph {index}. " * 35) for index in range(6))

    result = await service._polish_short_segments(
        "split-retry", run_path, project, "constraints", manuscript, "{}",
    )

    assert result == "\n\n".join(item.strip() for item in manuscript.split("\n\n"))
    assert gateway.roles and set(gateway.roles) == {"polish"}
    assert any(event["event_type"] == "polish_segment_split"
               for event in db.list_run_events("split-retry"))


@pytest.mark.asyncio
async def test_nonrecoverable_polish_failure_does_not_call_draft(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="No fallback", mode="short", genre="romance",
        premise="Two people reconcile.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.roles = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.roles.append(role)
            raise RuntimeError("401 invalid api key")

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("no-fallback", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "no-fallback"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    with pytest.raises(RuntimeError, match="401"):
        await service._polish_short_segments(
            "no-fallback", run_path, project, "constraints", "Paragraph. " * 80, "{}",
        )

    assert gateway.roles == ["polish"]


def test_claude_primary_polish_uses_full_budget_while_other_routes_stay_dynamic(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="claude", provider_id="provider", display_name="Claude",
        model_name="claude-sonnet-5",
    )
    db.save_model(
        model_id="backup", provider_id="provider", display_name="Backup",
        model_name="ernie-5.0",
    )
    db.save_role_binding("polish", "provider", "claude", "provider", "backup")
    service = WorkflowService.__new__(WorkflowService)
    service.db = db

    assert service._output_budget_for_call("polish", 2000, "polish", False) == 8192
    assert service._output_budget_for_call("polish", 2000, "polish", True) < 8192

    db.save_model(
        model_id="claude-backup", provider_id="provider", display_name="Claude Backup",
        model_name="claude-sonnet-5",
    )
    db.save_role_binding("polish", "provider", "claude", "provider", "claude-backup")
    assert service._output_budget_for_call("polish", 2000, "polish", True) == 8192

    db.save_role_binding("polish", "provider", "backup", None, None)
    assert service._output_budget_for_call("polish", 2000, "polish", False) < 8192


@pytest.mark.asyncio
async def test_polish_stage_adapts_large_rule_context_without_lowering_output_budget(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="claude", provider_id="provider", display_name="Claude",
        model_name="claude-sonnet-5",
    )
    db.save_role_binding("polish", "provider", "claude", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Bounded input", mode="short", genre="romance",
        premise="Two people reconcile.", target_words=3000,
    ))
    (project.path / "constraints.md").write_text(
        "\n".join(f"- Must preserve rule {index}: " + "x" * 180 for index in range(120)),
        encoding="utf-8",
    )
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((system, user, max_output_tokens))
            return ModelResult("Polished prose.", {"model_name": "claude-sonnet-5"})

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("bounded-input", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "bounded-input"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._stage(
        "bounded-input", run_path, project, "polish", "Must preserve the ending.",
        "MANUSCRIPT SEGMENT:\nSource prose.", allow_tools=False,
        output_source_characters=1200,
    )

    system, user, budget = gateway.calls[0]
    from novel_flywheel.context_policy import estimate_input_tokens
    assert estimate_input_tokens(system + user) <= 12000
    assert budget == 8192


def test_polish_segments_are_bounded_and_preserve_paragraph_order() -> None:
    paragraphs = [(f"段落{i}。" * 180) for i in range(1, 9)]
    text = "\n\n".join(paragraphs)

    parts = WorkflowService._split_polish_segments(text, target=1800, maximum=2400)

    assert len(parts) > 1
    assert max(map(len, parts)) <= 2400
    assert "".join("".join(parts).split()) == "".join("".join(text.split()).split())


@pytest.mark.asyncio
async def test_polish_retries_empty_max_token_response_once_with_full_budget(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Retry polish", mode="short", genre="comedy",
        premise="A cat goes to work.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.budgets = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.budgets.append(max_output_tokens)
            if len(self.budgets) == 1:
                return ModelResult("", {
                    "model_name": "claude", "input_tokens": 7000,
                    "output_tokens": max_output_tokens, "finish_reason": "max_tokens",
                })
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "claude", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("retry-polish", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "retry-polish"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = "A continuous scene with fixed events. " * 60

    result = await service._polish_short_segments(
        "retry-polish", run_path, project, "constraints", manuscript, "{}",
    )

    assert result == manuscript.strip()
    assert gateway.budgets[0] < 8192
    assert gateway.budgets == [gateway.budgets[0], 8192]
    assert any(
        event["event_type"] == "polish_max_tokens_retry"
        for event in db.list_run_events("retry-polish")
    )


@pytest.mark.asyncio
async def test_polish_splits_segment_when_full_budget_retry_also_hits_limit(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Split max tokens", mode="short", genre="suspense",
        premise="A witness revisits the scene.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            if self.calls <= 2:
                return ModelResult("", {
                    "model_name": "claude-sonnet-5", "input_tokens": 8330,
                    "output_tokens": max_output_tokens, "finish_reason": "max_tokens",
                })
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "claude-sonnet-5", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("split-max-tokens", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "split-max-tokens"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = "\n\n".join((f"Paragraph {index}. " * 45) for index in range(4))

    result = await service._polish_short_segments(
        "split-max-tokens", run_path, project, "constraints", manuscript, "{}",
    )

    assert result == "\n\n".join(item.strip() for item in manuscript.split("\n\n"))
    assert gateway.calls >= 4
    assert any(event["event_type"] == "polish_segment_split"
               for event in db.list_run_events("split-max-tokens"))


@pytest.mark.asyncio
async def test_review_retries_empty_max_token_response_then_uses_review_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Retry review", mode="short", genre="suspense",
        premise="An editor checks a draft.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.primary_budgets = []
            self.fallback_budgets = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.primary_budgets.append(max_output_tokens)
            return ModelResult("", {
                "model_name": "claude-sonnet-5", "input_tokens": 6490,
                "output_tokens": max_output_tokens, "finish_reason": "max_tokens",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.fallback_budgets.append(max_output_tokens)
            return ModelResult(quality_review(), {
                "model_name": "review-fallback", "finish_reason": "end_turn",
                "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("retry-review", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "retry-review"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._stage(
        "retry-review", run_path, project, "review", "constraints", "draft",
        allow_tools=False,
    )

    assert result == quality_review()
    assert gateway.primary_budgets == [4096, 8192]
    assert gateway.fallback_budgets == [8192]
    events = db.list_run_events("retry-review")
    assert any(event["event_type"] == "review_max_tokens_retry" for event in events)
    assert any(event["event_type"] == "review_configured_fallback" for event in events)


@pytest.mark.asyncio
async def test_review_marks_incomplete_when_primary_and_fallback_are_empty(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Incomplete review", mode="short", genre="suspense",
        premise="Both review routes fail.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        async def complete(self, role, system, user, max_output_tokens=None):
            return ModelResult("", {
                "model_name": "primary", "output_tokens": max_output_tokens,
                "finish_reason": "max_tokens",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            return ModelResult("", {
                "model_name": "fallback", "output_tokens": max_output_tokens,
                "finish_reason": "max_tokens", "configured_fallback_direct": True,
            })

    service = WorkflowService(db, store, Gateway(), SkillGate(db, SkillScanner([skill_root])))
    db.create_run("incomplete-review", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "incomplete-review"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    with pytest.raises(RuntimeError, match="review model returned empty output"):
        await service._stage(
            "incomplete-review", run_path, project, "review", "constraints", "draft",
            allow_tools=False,
        )

    assert not (run_path / "outputs" / "review.md").exists()
    assert any(
        event["event_type"] == "review_incomplete"
        for event in db.list_run_events("incomplete-review")
    )


@pytest.mark.asyncio
async def test_polish_retries_empty_fixed_budget_max_token_response(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Fixed retry", mode="short", genre="comedy",
        premise="A cat goes to work.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            if self.calls == 1:
                return ModelResult("", {
                    "model_name": "claude-sonnet-5", "input_tokens": 8298,
                    "output_tokens": 8192, "finish_reason": "max_tokens",
                })
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "claude-sonnet-5", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("fixed-retry", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "fixed-retry"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._stage(
        "fixed-retry", run_path, project, "polish", "constraints",
        "MANUSCRIPT SEGMENT:\nA continuous scene.", allow_tools=False,
    )

    assert result == "A continuous scene."
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_polish_retries_unexpected_tool_use_without_tools(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Retry tool use", mode="short", genre="comedy",
        premise="A cat goes to work.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.calls.append((system, user, max_output_tokens))
            if len(self.calls) == 1:
                return ModelResult("", {
                    "model_name": "claude", "input_tokens": 2,
                    "output_tokens": 335, "finish_reason": "tool_use",
                })
            return ModelResult("Polished prose.", {
                "model_name": "claude", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("retry-tool-use", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "retry-tool-use"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._stage(
        "retry-tool-use", run_path, project, "polish", "constraints", "source",
        allow_tools=False, prefer_configured_fallback=True,
    )

    assert result == "Polished prose."
    assert len(gateway.calls) == 2
    assert gateway.calls[0][2] == gateway.calls[1][2]
    assert "No tools are available" in gateway.calls[1][0]
    assert any(
        event["event_type"] == "polish_tool_use_retry"
        for event in db.list_run_events("retry-tool-use")
    )


@pytest.mark.asyncio
async def test_polish_retries_when_existing_short_sentence_run_is_not_improved(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Retry rhythm", mode="short", genre="historical",
        premise="A traveler wakes in another era.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    source = "她听清了。侯府。三小姐。林知晚。那些词忽然都有了陌生的分量。"

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            text = source if self.calls == 1 else "她听清了：侯府三小姐林知晚，那些词忽然都有了陌生的分量。"
            return ModelResult(text, {"model_name": "claude", "finish_reason": "end_turn"})

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("retry-rhythm", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "retry-rhythm"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._polish_short_segments(
        "retry-rhythm", run_path, project, "constraints", source, "{}",
    )

    assert gateway.calls == 2
    assert result == "她听清了：侯府三小姐林知晚，那些词忽然都有了陌生的分量。"
    assert any(event["event_type"] == "polish_rhythm_retry"
               for event in db.list_run_events("retry-rhythm"))


@pytest.mark.asyncio
async def test_rejected_rhythm_retry_is_not_repeated_for_same_source_and_route(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary-provider", "primary-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Bounded rhythm", mode="short", genre="historical",
        premise="A traveler enters a hall.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    source = "门开了。他进来。灯亮了。雨停了。风起了。长廊尽头传来脚步声。"

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            return ModelResult(source, {"model_name": "claude", "finish_reason": "end_turn"})

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("bounded-rhythm", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "bounded-rhythm"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    first = await service._polish_short_segments(
        "bounded-rhythm", run_path, project, "constraints", source, "{}",
    )
    second = await service._polish_short_segments(
        "bounded-rhythm", run_path, project, "constraints", source, "{}",
    )

    assert first == second == source
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_initial_polish_routes_ordinary_segments_to_configured_fallback_and_reuses_checkpoints(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary", "claude", "backup", "ernie")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Adaptive", mode="short", genre="comedy",
        premise="A cat goes to work.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class AdaptiveGateway:
        def __init__(self):
            self.routes = []

        @staticmethod
        def manuscript(user):
            return user.split("MANUSCRIPT SEGMENT:\n", 1)[1]

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return ModelResult(self.manuscript(user), {"model_name": "claude"})

        async def complete_configured_fallback(self, role, system, user, max_output_tokens=None):
            self.routes.append("configured_fallback")
            return ModelResult(self.manuscript(user), {
                "model_name": "ernie", "configured_fallback_direct": True,
            })

    gateway = AdaptiveGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("adaptive", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "adaptive"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    parts = [f"这是第{i}段连续叙事没有机械短句" * 80 for i in range(1, 5)]
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)

    first = await service._polish_short_segments(
        "adaptive", run_path, project, "constraints", manuscript, "{}",
    )
    calls_after_first = list(gateway.routes)
    second = await service._polish_short_segments(
        "adaptive", run_path, project, "constraints", manuscript, "{}",
    )

    assert calls_after_first == ["primary", "configured_fallback", "configured_fallback", "primary"]
    assert gateway.routes == calls_after_first
    assert first == second
    assert len(list((run_path / "outputs" / "polish-checkpoints" / "initial").glob("*.json"))) == 4


@pytest.mark.asyncio
async def test_single_segment_reuses_open_polish_circuit_across_correction_passes(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary", "claude", "backup", "ernie")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Single segment", mode="short", genre="comedy",
        premise="A cat goes to work.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.routes = []

        @staticmethod
        def manuscript(user):
            marker = "MANUSCRIPT SEGMENT:\n" if "MANUSCRIPT SEGMENT:\n" in user else "MANUSCRIPT:\n"
            return user.split(marker, 1)[1].split("\n\nSTRUCTURED FINDINGS:", 1)[0]

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return ModelResult(self.manuscript(user), {
                "model_name": "ernie", "fallback_used": True,
            })

        async def complete_configured_fallback(self, role, system, user, max_output_tokens=None):
            self.routes.append("configured_fallback")
            return ModelResult(self.manuscript(user), {
                "model_name": "ernie", "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("single", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "single"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = "这是一段自然连续而且包含足够上下文信息的短篇正文。" * 30

    await service._polish_short_segments("single", run_path, project, "constraints", manuscript, "{}")
    await service._polish_short_segments(
        "single", run_path, project, "constraints", manuscript, "{}", suffix="-2",
    )

    assert gateway.routes == ["primary", "configured_fallback"]
    assert any(
        event["event_type"] == "polish_circuit_opened"
        for event in db.list_run_events("single")
    )


def test_failed_short_story_resumes_from_best_candidate(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    separator = WorkflowService.SHORT_SEGMENT_SEPARATOR
    original = separator.join(["original one", "original two"])
    best = separator.join(["improved one", "improved two"])
    (outputs / "draft.md").write_text(original, encoding="utf-8")
    (outputs / "best-candidate.md").write_text(best, encoding="utf-8")

    text, source = WorkflowService._short_checkpoint_manuscript(outputs, 2)

    assert text == best
    assert source == "best-candidate.md"


def test_short_story_checkpoint_ignores_incomplete_best_candidate(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    separator = WorkflowService.SHORT_SEGMENT_SEPARATOR
    original = separator.join(["original one", "original two"])
    (outputs / "draft.md").write_text(original, encoding="utf-8")
    (outputs / "best-candidate.md").write_text("truncated", encoding="utf-8")

    text, source = WorkflowService._short_checkpoint_manuscript(outputs, 2)

    assert text == original
    assert source == "draft.md"


def test_polish_resume_reports_first_missing_checkpoint(tmp_path) -> None:
    parts = ["one", "two", "three", "four"]
    root = tmp_path / "checkpoints"
    WorkflowService._save_polish_checkpoint(root, 2, parts[1], "polished two")
    WorkflowService._save_polish_checkpoint(root, 4, parts[3], "polished four")

    assert WorkflowService._polish_checkpoint_progress(root, parts) == (2, 1)


def test_initial_short_story_planning_skips_empty_memory_tools() -> None:
    assert WorkflowService._planning_uses_tools(SimpleNamespace(revision=1)) is False
    assert WorkflowService._planning_uses_tools(SimpleNamespace(revision=2)) is True


def test_resume_prefers_complete_outputs_from_same_run(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Resume", mode="short", genre="suspense",
        premise="A failed polish resumes.", target_words=10000,
    ))
    run_id = "same-run"
    db.create_run(run_id, project.id, "short-story", status="failed")
    outputs = project.path / "runs" / run_id / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text("complete plan", encoding="utf-8")
    draft = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["part one", "part two", "part three", "part four"])
    (outputs / "draft.md").write_text(draft, encoding="utf-8")
    (outputs / "review.md").write_text(quality_review(), encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())

    checkpoint = service._find_short_checkpoint(project, run_id, 4)
    review = service._find_short_stage_output(project, run_id, "review.md")

    assert checkpoint == outputs
    assert review == outputs / "review.md"
@pytest.mark.asyncio
async def test_long_manuscript_final_review_audits_every_window_without_planning(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Whole review", mode="short", genre="romance",
        premise="A relationship changes.", target_words=20000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    manuscript = "\n\n".join(f"scene-{index}-" + "x" * 900 for index in range(18))
    from novel_flywheel.quality import review_windows
    count = len(review_windows(manuscript))
    evidence = [json.dumps({
        "summary": f"window {index}", "events": [], "issues": [],
        "character_states": [], "timeline": [], "promises": [],
    }) for index in range(1, count + 1)]
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [],
        "reconciliations": [{
            "issue_id": "initial-001", "status": "resolved",
            "severity": "medium", "evidence": "The repeated wording is gone.",
        }],
    })
    gateway = RecordingGateway([*evidence, final])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", manuscript,
        {"issues": [{"category": "prose", "severity": "medium", "action": "Remove repetition."}]},
    )

    assert review["score"] > 80
    assert audit["reviewed_windows"] == count
    assert audit["coverage"] == 1.0
    assert gateway.roles == ["final_review"] * (count + 1)
    assert "planning" not in gateway.roles
    assert all("WINDOW " in call["user"] for call in gateway.calls[:-1])
