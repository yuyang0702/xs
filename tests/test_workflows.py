import asyncio
import json
from types import SimpleNamespace

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
    assert gateway.roles == ["planning", "polish", "polish"]
    for call in gateway.calls[1:]:
        assert "The public ceremony is a wedding." in call["user"]
        assert "NEXT ORIGINAL START" in call["user"]
    events = db.list_run_events("targeted")
    planned = next(item for item in events if item["event_type"] == "revision_planned")
    assert planned["metadata"]["target_segments"] == [2]
    checks = json.loads((run_path / "outputs" / "revision-checks-2.json").read_text(
        encoding="utf-8",
    ))
    assert checks == {"failures": []}


def test_stage_output_budgets_cover_each_model_role() -> None:
    assert WorkflowService._stage_output_budget("planning") == 12288
    assert WorkflowService._stage_output_budget("draft") == 8192
    assert WorkflowService._stage_output_budget("review") == 4096
    assert WorkflowService._stage_output_budget("revision_plan") == 8192
    assert WorkflowService._stage_output_budget("polish") == 8192
    assert WorkflowService._stage_output_budget("final_review") == 8192
    assert WorkflowService._stage_output_budget("maintenance") == 8192


def test_polish_segments_are_bounded_and_preserve_paragraph_order() -> None:
    paragraphs = [(f"段落{i}。" * 180) for i in range(1, 9)]
    text = "\n\n".join(paragraphs)

    parts = WorkflowService._split_polish_segments(text, target=1800, maximum=2400)

    assert len(parts) > 1
    assert max(map(len, parts)) <= 2400
    assert "".join("".join(parts).split()) == "".join("".join(text.split()).split())


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
