import asyncio
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from novel_flywheel.db import Database
from novel_flywheel.context_policy import build_polish_authority_packet
from novel_flywheel.learning import LearningSystem
from novel_flywheel.models import ModelResult, ModelRoutesExhaustedError
from novel_flywheel.narrative_ledger import build_narrative_ledger
from novel_flywheel.outlines import outline_events
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.quality import issue_ledger, review_windows
from novel_flywheel.quality_profiles import score_review
from novel_flywheel.quality_records import load_quality_checkpoint, write_quality_checkpoint
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash
from novel_flywheel.revision import segment_map
from novel_flywheel.scene_continuity import LocationRef
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.workflows import (
    IncompleteModelOutputError,
    PolishTokenBudgetError,
    RevisionPlanError,
    StageText,
    TargetedGroupError,
    WorkflowService,
)


REQUIRED_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
}


def test_compact_polish_prompt_keeps_lossless_authority_and_one_source_copy() -> None:
    packet = build_polish_authority_packet(
        source="Only source prose.",
        event_ids=["EV-00000001"],
        previous_exit="Previous accepted exit.",
        next_entry="Next original entry.",
        locked_facts=["LOCKED-BEGIN-" + "x" * 3000 + "-LOCKED-END"],
        ending_constraints=["The confirmed ending remains unchanged."],
        promises=["The planted key must pay off."],
        narrative_state={"knowledge": "She has not opened the room."},
        style_rules=["Use short sentences only at the reveal."],
        protected_passages=[{"id": "lock-1", "text": "Protected sentence."}],
        allowed_scope={"segment": 1},
    )

    prompt = WorkflowService._compact_polish_prompt(
        authority_packet=packet,
        local_findings=[{"code": "rhythm"}],
        review_findings={"issues": []},
    )

    assert "LOCKED-END" in prompt
    assert "The planted key must pay off." in prompt
    assert "Protected sentence." in prompt
    assert prompt.count("Only source prose.") == 1
    assert prompt.rstrip().endswith("Only source prose.")


def test_incremental_workflow_public_types_are_explicit() -> None:
    hints = get_type_hints(WorkflowService._incremental_manuscript_review)

    assert hints["revision_source_hash"] == str | None
    assert hints["patch_groups"] == Sequence[dict]


def test_workflow_analysis_writes_hash_matching_artifact_and_reuses_it(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Analysis", mode="short", genre="suspense",
        premise="A door changes.", target_words=1000,
    ))
    store.set_optimized_local_review(project.id, True)
    calls = []
    nlp = SimpleNamespace(analyze=lambda text: calls.append(text) or {
        "backend": "ltp", "backend_version": "ltp-v2", "available": True,
        "result": {"cws": [[]], "pos": [[]], "ner": [[]], "srl": [[]], "dep": [[]]},
    })
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
        local_nlp=nlp,
    )
    run_path = project.path / "runs" / "analysis-run"
    report = service._analyze_manuscript(
        "林晚发现门锁变了。", run_path, project, "draft",
    )
    reused = service._analyze_manuscript(
        "林晚发现门锁变了。", run_path, project, "draft",
    )
    assert report["coverage"] == 1.0
    assert reused["text_hash"] == report["text_hash"]
    assert len(calls) == 1


def test_snapshot_recovery_failure_is_logged_without_replacing_primary_error(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Recovery log", mode="short", genre="suspense",
        premise="Keep the original failure.", target_words=1000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))
    run_id, _ = service._begin_run(project, "short-story", None)

    class BrokenSnapshot:
        @staticmethod
        def restore():
            raise OSError(22, "Invalid argument")

    service._restore_snapshot_after_failure(run_id, BrokenSnapshot())

    event = next(
        item for item in db.list_run_events(run_id)
        if item["event_type"] == "snapshot_restore_failed"
    )
    assert event["message"] == "项目文件恢复未完全完成，系统已保留最初的失败原因"
    assert "Invalid argument" in event["metadata"]["recovery_error"]


@pytest.mark.asyncio
async def test_incremental_review_uses_fewer_than_all_windows_for_middle_prose_change(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Incremental", mode="short", genre="suspense",
        premise="A long case.", target_words=50_000,
    ))
    parts = [f"场景{index}。" + chr(0x4e00 + index) * 4800 for index in range(10)]
    before = "\n\n".join(parts)
    after = before.replace("场景5。", "场景五。", 1)
    old = __import__("novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"]).analyze_manuscript(
        before, nlp_analyze=lambda text: {"backend": "ltp", "backend_version": "ltp-v2",
                                          "available": True, "result": {}},
    )
    current = __import__("novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"]).analyze_manuscript(
        after, nlp_analyze=lambda text: {"backend": "ltp", "backend_version": "ltp-v2",
                                         "available": True, "result": {}},
    )
    baseline = __import__("novel_flywheel.incremental_review", fromlist=["build_review_baseline"]).build_review_baseline(
        before, old, [], {"issues": [], "score": 80},
    )
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))
    prompts = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        prompts.append(prompt)
        if "ADJUDICATION" in prompt:
            return json.dumps({
                "dimensions": {"commercial": 80, "story": 80, "prose": 80},
                "hard_fail": False, "decision": "pass", "issues": [],
                "reconciliations": [],
            })
        return json.dumps({"summary": "局部证据", "events": [], "character_states": {},
                           "timeline": [], "promises": [], "issues": []})

    service._stage = fake_stage
    _, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        after, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=(),
    )
    assert audit["review_mode"] == "incremental"
    assert audit["reviewed_windows"] < audit["window_count"]
    assert audit["estimated_saved_input_characters"] > 0


def _ltp_analysis(text: str) -> dict:
    return __import__(
        "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
    ).analyze_manuscript(
        text, nlp_analyze=lambda value: {
            "backend": "ltp", "backend_version": "v",
            "available": True, "result": {},
        },
    )


async def _forbid_incremental_call(*args, **kwargs):
    raise AssertionError("incremental model call happened before local validation")


@pytest.mark.asyncio
async def test_incremental_review_missing_revision_source_falls_back_before_calls(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Missing source hash", mode="short", genre="suspense",
        premise="Strict review fails closed.", target_words=8000,
    ))
    before = "甲" * 1000
    current_text = "甲" * 500 + "乙" + "甲" * 499
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, _ltp_analysis(before), [], {"issues": []})
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)
    monkeypatch.setattr(service, "_final_review_json", _forbid_incremental_call)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, _ltp_analysis(current_text), baseline, {"issues": []},
        patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert audit["fallback_reasons"] == ["missing_revision_source_hash"]


@pytest.mark.asyncio
async def test_current_hash_precheck_runs_before_incremental_calls(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Precheck order", mode="short", genre="suspense",
        premise="Invalid evidence never reaches a model.", target_words=8000,
    ))
    before = "甲" * 1000
    current_text = "甲" * 500 + "乙" + "甲" * 499
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, _ltp_analysis(before), [], {"issues": []})
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)
    monkeypatch.setattr(service, "_final_review_json", _forbid_incremental_call)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, _ltp_analysis(before), baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert audit["fallback_reasons"] == ["current_analysis_hash_mismatch"]


@pytest.mark.asyncio
async def test_empty_scope_falls_back_before_incremental_calls(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Empty scope", mode="short", genre="suspense",
        premise="A changed manuscript needs evidence.", target_words=8000,
    ))
    before = "甲" * 1000
    current_text = "甲" * 500 + "乙" + "甲" * 499
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, _ltp_analysis(before), [], {"issues": []})
    current = {
        "text_hash": hashlib.sha256(current_text.encode("utf-8")).hexdigest(),
        "coverage": 1.0, "windows": [], "entities": [], "events": [],
        "units": {"scenes": [], "paragraphs": []},
        "narrative_ledger": {"relations": []}, "impact_index": {"relations": {}},
        "nlp": {"available": True}, "prose": {"blocking_count": 0},
    }
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)
    monkeypatch.setattr(service, "_final_review_json", _forbid_incremental_call)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert "empty_incremental_scope" in audit["fallback_reasons"]


@pytest.mark.asyncio
async def test_analysis_story_flag_forces_fallback_before_incremental_calls(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Promise change", mode="short", genre="suspense",
        premise="Promise changes require complete review.", target_words=8000,
    ))
    parts = [f"段落{index}。" + chr(0x4e00 + index) * 4800 for index in range(10)]
    parts[4] = "段落4。我发誓一定找到真相。" + chr(0x4e00 + 4) * 4785
    before = "\n\n".join(parts)
    current_text = before.replace("我发誓一定找到真相", "我打算以后寻找线索", 1)
    old = _ltp_analysis(before)
    current = _ltp_analysis(current_text)
    assert old["narrative_ledger"]["promises"]
    assert not current["narrative_ledger"]["promises"]
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, old, [], {"issues": []})
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)
    monkeypatch.setattr(service, "_final_review_json", _forbid_incremental_call)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert "promise_changed" in audit["fallback_reasons"]


@pytest.mark.asyncio
async def test_claimed_mechanical_group_with_extra_change_falls_back_before_calls(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Mechanical coverage", mode="short", genre="suspense",
        premise="Metadata cannot hide prose changes.", target_words=8000,
    ))
    before = "父 亲留下银锁。" + "甲" * 1000
    current_text = "父亲留下银锁。他烧掉证据。" + "甲" * 1000
    old = __import__(
        "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
    ).analyze_manuscript(before, nlp_analyze=None)
    current = __import__(
        "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
    ).analyze_manuscript(current_text, nlp_analyze=None)
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, old, [], {"issues": []})
    group = {"kind": "mechanical", "accepted": True, "patches": [{
        "operation": "replace", "old_text": "父 亲", "new_text": "父亲",
    }]}
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)
    monkeypatch.setattr(service, "_final_review_json", _forbid_incremental_call)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=[group],
    )

    assert audit["review_mode"] == "full_fallback"
    assert "unverified_mechanical_changes" in audit["fallback_reasons"]


@pytest.mark.asyncio
async def test_verified_mechanical_patch_group_uses_incremental_review_without_ltp(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Verified mechanical", mode="short", genre="suspense",
        premise="Only a covered spacing repair changed.", target_words=50_000,
    ))
    parts = [f"场景{index}。" + chr(0x4e00 + index) * 4800 for index in range(10)]
    parts[4] = "场景4。父 亲留下银锁。" + chr(0x4e00 + 4) * 4788
    before = "\n\n".join(parts)
    current_text = before.replace("父 亲", "父亲", 1)
    analyze = __import__(
        "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
    ).analyze_manuscript
    old = analyze(before, nlp_analyze=None)
    current = analyze(current_text, nlp_analyze=None)
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(before, old, [], {"issues": [], "score": 80})
    group = {"kind": "mechanical", "accepted": True, "patches": [{
        "operation": "replace", "old_text": "父 亲", "new_text": "父亲",
    }]}
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def fake_stage(*args, **kwargs):
        if "ADJUDICATION" in args[5]:
            return json.dumps({
                "dimensions": {"commercial": 80, "story": 80, "prose": 80},
                "hard_fail": False, "decision": "pass", "issues": [],
                "reconciliations": [],
            })
        return json.dumps({
            "summary": "局部证据", "events": [], "character_states": {},
            "timeline": [], "promises": [], "issues": [],
        })

    service._stage = fake_stage

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=[group],
    )

    assert audit["review_mode"] == "incremental"
    assert audit["reviewed_windows"] < audit["window_count"]


@pytest.mark.asyncio
async def test_incremental_review_falls_back_for_stale_baseline_analysis_hash(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Stale baseline analysis", mode="short", genre="suspense",
        premise="The saved analysis must match its source.", target_words=8000,
    ))
    before = "原始正文"
    baseline = __import__(
        "novel_flywheel.incremental_review", fromlist=["build_review_baseline"],
    ).build_review_baseline(
        before,
        __import__(
            "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
        ).analyze_manuscript("另一份正文", nlp_analyze=None),
        [], {"issues": [], "score": 80},
    )
    current_text = "返修后的正文"
    current = __import__(
        "novel_flywheel.manuscript_analysis", fromlist=["analyze_manuscript"],
    ).analyze_manuscript(current_text, nlp_analyze=None)
    service = WorkflowService(db, store, FakeGateway(), SkillGate(db, SkillScanner([])))

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        current_text, current, baseline, {"issues": []},
        revision_source_hash=baseline["manuscript_hash"], patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert audit["fallback_reasons"] == ["baseline_analysis_hash_mismatch"]


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
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            return ModelResult(json.dumps({
                "core_goal": "完成正式规划中的目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成正式结局", "covered_event_ids": [],
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
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


def make_polish_recovery_service(tmp_path, gateway, run_id="polish-recovery"):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary", "primary-model", "backup", "backup-model")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Polish recovery", mode="short", genre="suspense",
        premise="An editor recovers one failed segment.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    return db, project, service, run_path


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
        "planning", "planning", "draft", "review", "review", "polish",
        "final_review", "maintenance",
    ]
    assert (project.path / "manuscript" / "story.md").read_text(encoding="utf-8") == "# Final Story\nHuman, polished prose."
    assert (project.path / "chapters" / "chapter-01.md").is_file()
    assert json.loads((project.path / "memory" / "canon.json").read_text(encoding="utf-8"))["facts"]
    run_path = project.path / "runs" / result["id"]
    assert (run_path / "outputs" / "planning.md").is_file()
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()
    execution_index = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(encoding="utf-8")
    )
    assert execution_index["status"] == "ready"
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
async def test_short_flywheel_extracts_causal_chain_without_replacing_outline(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Revive Friend", mode="short", genre="suspense",
        premise="复活死去的朋友。", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class CausalGateway:
        def __init__(self) -> None:
            self.roles = []
            self.systems = []
            self.users = []
            self.responses = iter([
                "# Story Plan\n主角调查死亡现场。\n\nSHORT_CAUSAL_CHAIN_JSON_START\n"
                '{"core_goal":{"content":"复活死去的朋友"},"cycles":[{"obstacle":"缺少灵魂媒介","effort":"调查死亡现场","result":"找到残缺记忆","state_change":"确认灵魂仍在"},{"obstacle":"仪式需要交换生命","effort":"寻找规则漏洞","result":"朋友暂时复活","state_change":"目标表面达成"}],"reversal":{"content":"朋友主动死亡是为了封印","prior_evidence":["死亡记录被销毁"]},"ending":{"surface_goal":"无法永久复活","inner_goal":"主角放下愧疚"}}'
                "\nSHORT_CAUSAL_CHAIN_JSON_END",
                "正文草稿",
                json.dumps({"score": 86, "hard_fail": False, "issues": []}),
                json.dumps({"score": 84, "hard_fail": False, "issues": []}),
                "正文终稿",
                json.dumps({"score": 92, "hard_fail": False, "issues": []}),
                json.dumps({"facts": ["主角放下愧疚"]}),
            ])

        async def complete(self, role, system, user, **kwargs):
            self.roles.append(role)
            self.systems.append(system)
            self.users.append(user)
            return ModelResult(next(self.responses), {"role": role, "model_name": f"fake-{role}"})

    gateway = CausalGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    artifact = (project.path / "learning" / "short_causal_chain.json").read_text(encoding="utf-8")
    assert "复活死去的朋友" in artifact
    planning = project.path / "runs" / result["id"] / "outputs" / "planning.md"
    assert "SHORT_CAUSAL_CHAIN_JSON_START" not in planning.read_text(encoding="utf-8")
    assert "SHORT_CAUSAL_CHAIN_JSON_START" in gateway.users[0]
    assert '"opening"' in gateway.users[0]
    assert '"question_chain"' in gateway.users[0]
    assert '"relationship_arc"' in gateway.users[0]
    assert '"next_question"' in gateway.users[0]
    assert any("Short Story Causal Chain" in system and "复活死去的朋友" in system
               for system in gateway.systems[1:])
    final_prompts = [user for role, user in zip(gateway.roles, gateway.users) if role == "final_review"]
    assert any("CAUSAL CHAIN CHECKS" in prompt for prompt in final_prompts)
    assert any("opening pressure" in prompt and "relationship progression" in prompt
               and "ending cost" in prompt for prompt in final_prompts)


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
    assert "Book Bible" in (project.path / "memory" / "book-plan.md").read_text(encoding="utf-8")
    assert not (project.path / "outline.md").exists()


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
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            return ModelResult(json.dumps({
                "core_goal": "完成正式规划中的目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成正式结局", "covered_event_ids": [],
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
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
        return ModelResult(f"第{number}段" + chr(0x4e00 + number) * 2500, {
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

    plan = "\n\n".join(
        f"### 段 {index}：事件{index}\n事件ID：EV-{index:08x}\n大纲依据：事件{index}\n"
        f"本段只负责事件{index}，完成结果{index}并留下下一段问题。" + "细节" * 40
        for index in range(1, 9)
    )
    draft = await service._draft_short_in_segments(
        "segmented", run_path, project, "constraints", plan,
    )

    assert WorkflowService._short_segment_count(20000) == 8
    assert gateway.roles == ["draft"] * 8
    assert all("不要提问" in call["user"] for call in gateway.calls)
    assert len(WorkflowService._split_segments(draft)) == 8
    assert (run_path / "outputs" / "draft.md").read_text(encoding="utf-8") == draft
    assignments = json.loads(
        (run_path / "outputs" / "segment-events.json").read_text(encoding="utf-8"),
    )["segments"]
    assert assignments[0]["event_ids"] == ["EV-00000001"]
    assert assignments[-1]["event_ids"] == ["EV-00000008"]


def test_short_plan_and_segment_gates_preserve_event_ownership_and_handoffs() -> None:
    plan = "\n\n".join(
        f"### 段 {index}：事件{index}\n"
        f"段首承接：人物在地点{index}，接着上段动作，关系和已知信息不变。\n"
        f"本段事件：只负责事件{index}，完成状态变化。\n"
        f"段末交接：人物留在地点{index}，继续行动，关系变化并知道线索{index}。"
        + "细节" * 30
        for index in range(1, 4)
    )
    segments = WorkflowService._short_plan_segments(plan, 3)
    assert len(segments) == 3
    assert "事件2" not in segments[0]
    assert WorkflowService._short_plan_handoff(segments[0]).startswith("人物留在地点1")

    missing_handoff_plan = plan.replace("段末交接", "结尾状态", 1)
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, missing_handoff_plan, 3,
    )
    assert any("无法确认剧情分工与前后衔接" in item for item in issues)


@pytest.mark.asyncio
async def test_truncated_draft_segment_is_split_into_internal_subtasks(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Adaptive draft", mode="short", genre="suspense",
        premise="A route truncates one owned segment.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            if len(self.calls) <= 2:
                return ModelResult("未完成", {
                    "role": role, "model_name": "limited",
                    "finish_reason": "max_tokens",
                    "requested_max_output_tokens": max_output_tokens,
                })
            character = "甲" if "内部子任务 1/2" in user else "乙"
            return ModelResult(character * 500, {
                "role": role, "model_name": "limited", "finish_reason": "stop",
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("adaptive", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "adaptive"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "adaptive", run_path, project, "constraints", "写完本段事件",
        suffix="-part-01", target=1000, previous_parts=[],
    )

    assert text == "甲" * 500 + "\n\n" + "乙" * 500
    assert len(gateway.calls) == 4
    split = next(
        item for item in db.list_run_events("adaptive")
        if item["event_type"] == "draft_task_split"
    )
    assert split["metadata"]["subtasks"] == 2


@pytest.mark.asyncio
async def test_normal_finish_underlength_splits_semantically(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Normally short draft", mode="short", genre="suspense",
        premise="A model stops normally before developing the scene.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            if len(self.calls) == 1:
                return ModelResult("摘要" * 80, {
                    "role": role, "model_name": "early-stop", "finish_reason": "stop",
                    "transport_complete": True,
                })
            character = "甲" if "内部子任务 1/2" in user else "乙"
            return ModelResult(character * 500, {
                "role": role, "model_name": "early-stop", "finish_reason": "stop",
                "transport_complete": True,
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("normal-short", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "normal-short"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "normal-short", run_path, project, "constraints", "写完本段事件",
        suffix="-part-04", target=1000, previous_parts=[],
        event_ids=[
            "EV-00000001", "EV-00000002", "EV-00000003", "EV-00000004",
        ],
    )

    assert text == "甲" * 500 + "\n\n" + "乙" * 500
    assert len(gateway.calls) == 3
    assert "EV-00000001、EV-00000002" in gateway.calls[1]
    assert "EV-00000003、EV-00000004" in gateway.calls[2]
    split = next(
        item for item in db.list_run_events("normal-short")
        if item["event_type"] == "draft_task_split"
    )
    assert split["metadata"]["reason"] == "normal_finish_underlength"
    assert split["metadata"]["han_characters"] == 160
    assert split["metadata"]["issue_codes"] == ["underlength"]
    assert split["metadata"]["event_ids"] == [
        "EV-00000001", "EV-00000002", "EV-00000003", "EV-00000004",
    ]


@pytest.mark.asyncio
async def test_normal_finish_non_han_text_does_not_use_han_length_split(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="English draft", mode="short", genre="suspense",
        premise="A project whose prose is not measured by Han character count.",
        target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            return ModelResult("# Draft\n\nAn English scene returned normally.", {
                "role": role, "model_name": "english", "finish_reason": "stop",
                "transport_complete": True,
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("english", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "english"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "english", run_path, project, "constraints", "Write the scene.",
        suffix="-part-01", target=1000, previous_parts=[],
    )

    assert text == "# Draft\n\nAn English scene returned normally."
    assert len(gateway.calls) == 1
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("english")
    )


@pytest.mark.asyncio
async def test_underlength_without_terminal_evidence_is_not_classified_as_normal_finish(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Unknown terminal", mode="short", genre="suspense",
        premise="A legacy route omits terminal metadata.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            return ModelResult("正文草稿", {
                "role": role, "model_name": "legacy-without-terminal-state",
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("unknown-terminal", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "unknown-terminal"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "unknown-terminal", run_path, project, "constraints", "写完本段事件",
        suffix="-part-01", target=1000, previous_parts=[],
    )

    assert text == "正文草稿"
    assert len(gateway.calls) == 1
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("unknown-terminal")
    )


@pytest.mark.asyncio
async def test_short_planning_batches_are_internal_and_checkpointed(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Batched plan", mode="short", genre="suspense",
        premise="A long plan is split safely.", target_words=10000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("batched-plan", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "batched-plan"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    calls = []

    async def fake_stage(*args, **kwargs):
        user = args[5]
        calls.append(user)
        match = __import__("re").search(r"第 (\d+) 段到第 (\d+) 段", user)
        assert match
        start, end = map(int, match.groups())
        return "\n\n".join(
            f"### 第 {number} 段：事件{number}\n"
            f"事件ID：EV-{number:08x}\n大纲依据：事件{number}\n"
            f"段首承接：承接状态{number}\n本段事件：推进事件{number}\n"
            f"段末交接：留下状态{number}\n" + chr(0x4e00 + number) * 100
            for number in range(start, end + 1)
        )

    service._stage = fake_stage
    plan = await service._plan_short_in_batches(
        "batched-plan", run_path, project, "constraints", "brief", {}, 4,
    )

    assert len(calls) == 2
    assert len(service._short_plan_segments(plan, 4)) == 4
    assert len(list((run_path / "outputs" / "planning-checkpoints").glob("*.json"))) == 2

    async def should_not_call(*args, **kwargs):
        raise AssertionError("validated planning batch was not reused")

    service._stage = should_not_call
    assert await service._plan_short_in_batches(
        "batched-plan", run_path, project, "constraints", "brief", {}, 4,
    ) == plan


@pytest.mark.asyncio
async def test_invalid_causal_chain_keeps_execution_index_pending(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Pending causal chain", mode="short", genre="suspense",
        premise="Drafting waits for causal authority.", target_words=3000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("causal-pending", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "causal-pending"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    async def invalid_chain(*args, **kwargs):
        return json.dumps({"core_goal": "目标"}, ensure_ascii=False)

    service._stage = invalid_chain
    with pytest.raises(ValueError, match="因果链未通过"):
        await service._ensure_short_causal_chain(
            "causal-pending", run_path, project, "constraints",
            "# 已验收规划", [], None,
        )

    index = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(encoding="utf-8")
    )
    assert index["status"] == "causal_pending"
    assert not (run_path / "outputs" / "short-causal-chain.json").exists()


@pytest.mark.asyncio
async def test_new_run_reuses_validated_cross_run_draft_prefix(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Cross-run prefix", mode="short", genre="suspense",
        premise="A failed draft resumes without rewriting accepted scenes.",
        target_words=10000,
    ))
    state = StoryStateStore(db).ensure(project.id, project.path)
    constraints = store.load_constraints(project.id)
    plan = "\n\n".join(
        f"### 第 {number} 段：事件{number}\n"
        f"事件ID：EV-{number:08x}\n大纲依据：事件{number}\n"
        f"段首承接：承接状态{number}\n本段事件：推进事件{number}\n"
        f"段末交接：留下状态{number}\n" + chr(0x4e00 + number) * 100
        for number in range(1, 5)
    )
    assert not WorkflowService._short_plan_issues(project, state.data, plan, 4)
    chain = {
        "core_goal": "完成目标",
        "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
        "ending": "完成结局",
    }
    db.create_run("failed-prefix", project.id, "short-story", status="running")
    source_outputs = project.path / "runs" / "failed-prefix" / "outputs"
    source_outputs.mkdir(parents=True)
    atomic = __import__("novel_flywheel.storage", fromlist=["atomic_write"]).atomic_write
    atomic(source_outputs / "planning.md", plan)
    atomic(
        source_outputs / "short-causal-chain.json",
        json.dumps(chain, ensure_ascii=False, indent=2),
    )
    WorkflowService._write_short_execution_index(
        project.path / "runs" / "failed-prefix", project, state.revision,
        state.data, constraints, plan, chain, 4,
    )
    augmented_constraints = constraints + (
        "\n\n# Short Story Causal Chain\n\n"
        + __import__("novel_flywheel.causal_chain", fromlist=["compact_causal_chain"])
        .compact_causal_chain(chain)
    )
    authority_hash = hashlib.sha256(json.dumps({
        "plan": plan, "constraints": augmented_constraints,
        "target_words": 10000, "segment_count": 4,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    previous = ""
    for number, character in ((1, "甲"), (2, "乙")):
        text = character * 2500
        block = WorkflowService._short_plan_segments(plan, 4)[number - 1]
        atomic(
            source_outputs / "draft-checkpoints" / f"segment-{number:02d}.json",
            json.dumps({
                "version": 1, "authority_sha256": authority_hash,
                "previous_sha256": (
                    hashlib.sha256(previous.encode("utf-8")).hexdigest()
                    if previous else ""
                ),
                "segment_plan_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
                "assignment": {
                    "segment": number,
                    "event_ids": [f"EV-{number:08X}"],
                    "handoff": WorkflowService._short_plan_handoff(block),
                },
            }, ensure_ascii=False, indent=2),
        )
        previous = text
    db.update_run("failed-prefix", "failed", error="provider interrupted segment 3")

    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    assert service._find_short_partial_checkpoint(
        project, "resume-prefix", state.revision, state.data, constraints, 4,
    ) == source_outputs
    generated_segments = []

    async def fake_stage(run_id, run_path, current_project, stage, constraints, user, **kwargs):
        if stage == "review":
            raise RuntimeError("stop after resumed draft")
        assert stage == "draft"
        match = __import__("re").search(r"本次只写第 (\d+)/4 段", user)
        assert match
        number = int(match.group(1))
        generated_segments.append(number)
        return chr(0x4e00 + number + 10) * 2500

    service._stage = fake_stage
    with pytest.raises(RuntimeError, match="stop after resumed draft"):
        await service.run_short(
            project.id, use_crewai=False, run_id="resume-prefix",
        )

    assert generated_segments == [3, 4]
    resumed = project.path / "runs" / "resume-prefix" / "outputs" / "draft.md"
    parts = WorkflowService._split_segments(resumed.read_text(encoding="utf-8"))
    assert parts[:2] == ["甲" * 2500, "乙" * 2500]


@pytest.mark.parametrize("headings", [
    ["### 段 1：开端", "### 段 2：发展", "### 段 3：收束"],
    ["### 第1段：开端", "### 第2段：发展", "### 第3段：收束"],
    ["### 第 1 段：开端", "### 第 2 段：发展", "### 第 3 段：收束"],
    ["### **第一段** · 开端", "### **第二段** · 发展", "### **第三段** · 收束"],
    ["### 第１段：开端", "### 第２段：发展", "### 第３段：收束"],
    ["### Segment 1: Opening", "### Segment 2: Middle", "### Segment 3: Ending"],
    ["   ### 第一段：开端", "  ### 第二段：发展", " ### 第三段：收束"],
])
def test_short_plan_segments_accept_common_heading_formats(headings) -> None:
    plan = "\n\n".join(
        f"{heading}\n本段事件：事件{index}。" + chr(0x4e00 + index) * 100
        for index, heading in enumerate(headings, 1)
    ) + "\n\n## 附录\n不属于最后一个写作段。"

    segments = WorkflowService._short_plan_segments(plan, 3)

    assert len(segments) == 3
    assert "事件1" in segments[0]
    assert "事件3" in segments[-1]
    assert "附录" not in segments[-1]


def test_short_plan_segments_accept_chinese_number_twelve() -> None:
    numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
    plan = "\n\n".join(
        f"### 第{numeral}段：事件{index}\n本段事件：事件{index}。" + chr(0x4e00 + index) * 100
        for index, numeral in enumerate(numerals, 1)
    )

    segments = WorkflowService._short_plan_segments(plan, 12)

    assert len(segments) == 12
    assert "第十二段" in segments[-1]


def test_short_plan_scene_subheadings_do_not_split_numbered_segments() -> None:
    plan = "\n\n".join((
        "### 第一段：开端\n事件ID：EV-11111111\n大纲依据：开端\n"
        "段首承接：开始。\n本段事件：调查。\n#### 场景1：前院\n发现线索。\n"
        "#### Scene 2: Kitchen\n确认线索。\n段末交接：继续追查。\n" + "甲" * 100,
        "### 第二段：收束\n事件ID：EV-22222222\n大纲依据：结尾\n"
        "段首承接：继续追查。\n本段事件：揭晓。\n段末交接：结束。\n" + "乙" * 100,
    ))

    segments = WorkflowService._short_plan_segments(plan, 2)

    assert len(segments) == 2
    assert "#### 场景1" in segments[0]
    assert "#### Scene 2" in segments[0]
    assert "EV-22222222" not in segments[0]


def test_short_plan_fields_accept_markdown_and_ignore_appendix_event_ids() -> None:
    plan = "\n\n".join((
        "### 第一段 · 开端\n"
        "*事件 ID*：EV-11111111\n**大纲依据**：开端\n"
        "**段首承接**：故事开始。\n**本段事件**：发现异常。\n"
        "_段末交接_：\n人物留在前院。\n她已经知道账册存在。\n" + "甲" * 100,
        "### 第二段 · 收束\n"
        "**事件ID**：EV-22222222\n**大纲依据**：收束\n"
        "**段首承接**：人物从前院出发。\n**本段事件**：查明真相。\n"
        "**段末交接**：故事结束。\n" + "乙" * 100,
    )) + "\n\n## 各分段负责事件对照表\n| 第一段 | EV-11111111 |"
    state = {"outline": {"events": [
        {"id": "EV-11111111"}, {"id": "EV-22222222"},
    ]}}

    segments = WorkflowService._short_plan_segments(plan, 2)
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), state, plan, 2,
    )

    assert issues == []
    assert WorkflowService._short_plan_event_ids(segments[1]) == ["EV-22222222"]
    assert WorkflowService._short_plan_handoff(segments[0]) == (
        "人物留在前院。\n她已经知道账册存在。\n" + "甲" * 100
    )


def test_short_plan_gate_reports_all_repairable_field_problems_at_once() -> None:
    plan = (
        "### 第一段\n事件ID：EV-11111111\n本段事件：太短。\n"
        "\n### 第二段\n事件ID：EV-22222222\n本段事件：也太短。"
    )

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, plan, 2,
    )

    assert any("没有写清" in item for item in issues)
    assert any("缺少事件ID" in item for item in issues)


def test_single_short_plan_event_ids_fall_back_to_plan_text() -> None:
    plan = "单段短篇规划覆盖正式事件 EV-1234abcd，并直接完成全文。"

    assert WorkflowService._short_plan_event_ids(plan) == ["EV-1234ABCD"]


def test_short_plan_fields_normalize_width_without_rewriting_prose() -> None:
    segment = (
        "```markdown\n事件ID：EV-deadbeef\n```\n"
        "事件ＩＤ：ＥＶ－１２３４ａｂｃｄ\n段末交接：保留１２：｛原文｝"
    )

    assert WorkflowService._short_plan_event_ids(segment) == ["EV-1234ABCD"]
    assert WorkflowService._short_plan_handoff(segment) == "保留１２：｛原文｝"


def test_short_plan_gate_ignores_hidden_segment_heading_examples() -> None:
    plan = (
        "<!--\n### Segment 4: hidden\n-->\n"
        "```markdown\n### Segment 3: example\n```\n"
        "### Segment 1: Opening\n" + "opening detail " * 20 + "\n\n"
        "### Segment 2: Ending\n" + "ending detail " * 20
    )

    numbers = [
        number for _match, number in WorkflowService._short_plan_headings(plan)
        if number is not None
    ]
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, plan, 2,
    )

    assert numbers == [1, 2]
    assert not any("恰好按" in item for item in issues)


@pytest.mark.parametrize("numbers", ([1, 2, 3], [1, 1, 2], [2, 1]))
def test_short_plan_gate_rejects_extra_duplicate_or_reordered_segment_headings(
    numbers,
) -> None:
    plan = "\n\n".join(
        f"### Segment {number}: Part\n" + "story detail " * 20
        for number in numbers
    )

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, plan, 2,
    )

    assert any("恰好按第 1 至第 2 段各出现一次" in item for item in issues)


def test_short_plan_gate_rejects_unremoved_causal_chain_markers() -> None:
    plan = "\n\n".join((
        "### 第一段\n事件ID：EV-11111111\n大纲依据：开端\n段首承接：开始。\n"
        "本段事件：发现异常。\n段末交接：继续调查。\n" + "甲" * 100,
        "### 第二段\n事件ID：EV-22222222\n大纲依据：结尾\n段首承接：继续调查。\n"
        "本段事件：查明真相。\n段末交接：结束。\n" + "乙" * 100,
    )) + "\nSHORT_CAUSAL_CHAIN_JSON_START\n```json\n{broken}\n```"

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, plan, 2,
    )

    assert any("因果链" in item for item in issues)


def test_short_plan_requires_every_formal_outline_event_in_order() -> None:
    outline = "# 大纲\n\n## 开头\n发现异常。\n\n## 结尾\n兑现承诺。\n"
    events = outline_events(outline)
    plan = "\n\n".join((
        f"### 段 1：结尾\n事件ID：{events[1]['id']}\n大纲依据：结尾\n"
        "段首承接：这是开篇。\n本段事件：发现异常。\n段末交接：带着问题离开。" + "细节" * 30,
        f"### 段 2：开头\n事件ID：{events[0]['id']}\n大纲依据：开头\n"
        "段首承接：继续调查。\n本段事件：兑现承诺。\n段末交接：故事结束。" + "收束" * 30,
    ))
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline, "events": events}}, plan, 2,
    )

    reversal = next(item for item in issues if "顺序发生倒退" in item)
    assert "第 1 段" in reversal
    assert "第 2 段" in reversal
    assert "结尾" in reversal
    assert "开头" in reversal


def test_short_plan_order_ignores_structure_theme_and_writing_directives() -> None:
    outline = """# 大纲

## 一、故事核心设定
**总字数**：一万字

## 三、章节大纲
### 第一幕：误入高门
**开篇钩子**：花穗被错抬进府。
### 第1章·身份露馅
**冲突升级**：众人开始怀疑她。

## 四、主题与情感线
**核心母题**：出身不决定价值。

## 五、写作要点
**保持第一人称**：只写花穗所见。
"""
    events = outline_events(outline)
    by_label = {item["label"]: item["id"] for item in events}
    plan = "\n\n".join((
        "### 第一段：误入\n"
        f"事件ID：{by_label['开篇钩子']}、{by_label['保持第一人称']}\n"
        "大纲依据：开篇钩子\n段首承接：这是开篇。\n"
        "本段事件：花穗被错抬进府并决定留下查明原因。\n"
        "段末交接：花穗留在前厅，开始怀疑众人的说法。" + "细节" * 30,
        "### 第二段：露馅\n"
        f"事件ID：{by_label['第一幕：误入高门']}、"
        f"{by_label['第1章·身份露馅']}、{by_label['冲突升级']}\n"
        "大纲依据：冲突升级\n段首承接：花穗仍在前厅，众人开始盘问。\n"
        "本段事件：花穗的回答露出破绽，身份危机升级。\n"
        "段末交接：众人查明真相，故事结束。" + "收束" * 30,
    ))

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline, "events": events}}, plan, 2,
    )

    assert not any("不存在的事件 ID" in item for item in issues)
    assert not any("还没有分配" in item for item in issues)
    assert not any("顺序发生倒退" in item for item in issues)


def test_short_plan_gate_rebuilds_legacy_event_cache_from_outline_content() -> None:
    outline = """# Outline

**Opening beat**: The lead finds a letter.

<!-- **Hidden template beat**: Example only. -->

```markdown
**Fenced example beat**: Example only.
```

**Ending beat**: The lead answers the letter.
"""
    events = outline_events(outline)
    saved_events = [*events, {
        "id": "EV-DEADBEEF", "order": 99,
        "label": "Hidden template beat", "section": "",
    }]
    plan = "\n\n".join((
        f"### Segment 1: Opening\n{events[0]['id']}\n" + "a" * 100,
        f"### Segment 2: Ending\n{events[1]['id']}\n" + "b" * 100,
    ))

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline, "events": saved_events}}, plan, 2,
    )

    assert not any("EV-DEADBEEF" in issue for issue in issues)


def test_short_plan_rejects_unknown_id_when_outline_has_only_directives() -> None:
    outline = "# 大纲\n\n## 五、写作要点\n**保持第一人称**：只写主角所见。\n"
    events = outline_events(outline)
    plan = "\n\n".join((
        "### 第一段：开始\n事件ID：EV-deadbeef\n大纲依据：写作要求\n"
        "段首承接：这是开篇。\n本段事件：人物开始行动。\n"
        "段末交接：人物留在前厅。\n" + "细节" * 30,
        "### 第二段：结束\n事件ID：EV-deadbeef\n大纲依据：写作要求\n"
        "段首承接：人物仍在前厅。\n本段事件：人物解决问题。\n"
        "段末交接：故事结束。\n" + "收束" * 30,
    ))

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline, "events": events}}, plan, 2,
    )

    assert any("不存在的事件 ID" in item for item in issues)


def test_adjacent_segments_may_continue_the_same_formal_outline_event() -> None:
    outline = "# 大纲\n\n## 开头\n发现异常。\n\n## 结尾\n兑现承诺。\n"
    events = outline_events(outline)
    plan = "\n\n".join((
        f"### 段 1：开头上\n事件ID：{events[0]['id']}\n大纲依据：开头\n"
        "段首承接：这是开篇。\n本段事件：发现异常。\n段末交接：继续追查。" + "细节" * 30,
        f"### 段 2：开头下\n事件ID：{events[0]['id']}\n大纲依据：开头\n"
        "段首承接：继续追查。\n本段事件：查明原因。\n段末交接：准备收束。" + "推进" * 30,
        f"### 段 3：结尾\n事件ID：{events[1]['id']}\n大纲依据：结尾\n"
        "段首承接：准备收束。\n本段事件：兑现承诺。\n段末交接：故事结束。" + "收束" * 30,
    ))

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline, "events": events}}, plan, 3,
    )

    assert not any("事件" in item and ("倒退" in item or "没有分配" in item) for item in issues)

    catalog = {
        "容府厨房": LocationRef("容府厨房", "容府"),
        "容府大厅": LocationRef("容府大厅", "容府"),
        "沈府大厅": LocationRef("沈府大厅", "沈府"),
    }
    previous = ["苏荞在容府厨房关上门，继续等周嬷嬷回来。" * 8]
    abrupt = "沈府大厅里，方小满已经开始参加家宴。" + "众人沉默。" * 60
    issues = WorkflowService._draft_segment_issues(
        abrupt, 600, previous, catalog,
    )
    assert any("换了场景" in item for item in issues)

    bridged = "次日清晨，苏荞从厨房回到容府大厅。" + "她接着处理昨夜留下的问题。" * 50
    bridged_issues = WorkflowService._draft_segment_issues(
        bridged, 600, previous, catalog,
    )
    assert not any("换了场景" in item for item in bridged_issues)


def test_draft_findings_keep_underlength_blocking_without_guessing_unknown_locations() -> None:
    findings = WorkflowService._draft_segment_findings(
        "月面基地的灯亮了。" * 5,
        1000,
        ["她留在远航号。" * 20],
        {},
    )

    blocking_codes = {
        item["code"] for item in findings if item["blocking"]
    }
    assert "underlength" in blocking_codes
    assert "scene_transition_missing" not in blocking_codes


def test_draft_findings_make_same_root_location_change_nonblocking() -> None:
    catalog = {
        "教学楼": LocationRef("教学楼", "学校"),
        "地下车库": LocationRef("地下车库", "学校"),
    }

    findings = WorkflowService._draft_segment_findings(
        "地下车库里只剩一盏灯。" + "她屏住呼吸。" * 80,
        600,
        ["她站在教学楼门口。" * 40],
        catalog,
    )

    assert "scene_transition_uncertain" in {item["code"] for item in findings}
    assert not any(
        item["code"] == "scene_transition_uncertain" and item["blocking"]
        for item in findings
    )


@pytest.mark.asyncio
async def test_polish_stage_keeps_confirmed_outline_style_and_blueprint(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Confirmed context", mode="short", genre="mystery",
        premise="A sealed letter changes the case.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["polished"])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("confirmed-context", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "confirmed-context"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    constraints = "\n\n".join((
        "# General Notes\n" + "background filler\n" * 800,
        "# CONFIRMED STORY FACTS (take precedence over older project notes)\n"
        "- ending: The heroine leaves alone.",
        "# Confirmed Outline Event IDs\n- EV-a1b2c3d4: Open the sealed letter",
        "# Current Confirmed Outline\n## Opening\nThe letter arrives.\n\n"
        "## Ending\nThe heroine opens it and learns the truth.",
        "# Executable Prose Baseline\n"
        '{"sentence_rhythm":["Alternate long and short sentences."]}',
        "# Confirmed Creative Blueprint\n"
        '{"mechanisms":[{"name":"Delayed answer",'
        '"transfer_guidance":"Keep the letter unresolved until the final turn."}]}',
    ))

    await service._stage(
        "confirmed-context", run_path, project, "polish", constraints,
        "Polish EV-a1b2c3d4 without revealing the sealed letter early.",
    )

    system = gateway.calls[0]["system"]
    assert "The heroine leaves alone" in system
    assert "The heroine opens it and learns the truth" in system
    assert "Alternate long and short sentences" in system
    assert "Keep the letter unresolved until the final turn" in system
    assert "background filler" not in system
    loaded = next(
        item for item in db.list_run_events("confirmed-context")
        if item["event_type"] == "skills_loaded"
    )
    assert loaded["metadata"]["confirmed_context"] == [
        "已确认事实", "正式大纲", "基础文笔", "创作蓝图",
    ]


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
    checkpoints = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(checkpoint_root.glob("*.json"))
    ]
    assert len(checkpoints) == 2
    assert all(item["accepted"] is False for item in checkpoints)
    assert all(item["status"] == "preserved_source" for item in checkpoints)


@pytest.mark.asyncio
async def test_structural_polish_retries_invalid_primary_output_with_configured_fallback(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("polish", "primary", "claude", "backup", "ernie")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Fallback repair", mode="short", genre="suspense",
        premise="A witness changes the case.", target_words=10_000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return ModelResult("too short", {"model_name": "claude"})

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.routes.append("configured_fallback")
            return ModelResult("B" * 1000, {
                "model_name": "ernie", "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("fallback-repair", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "fallback-repair"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["A" * 1000, "C" * 1000])
    plan = {
        "global_facts": [],
        "checks": [{"kind": "forbidden_text", "value": "never present"}],
        "tasks": [{"segments": [1], "instruction": "Repair the first scene."}],
    }

    polished = await service._polish_short_segments(
        "fallback-repair", run_path, project, "constraints", manuscript, "{}",
        structural=True, prepared_revision_plan=plan,
    )

    assert WorkflowService._split_segments(polished) == ["B" * 1000, "C" * 1000]
    assert gateway.routes == ["primary", "configured_fallback"]
    assert any(
        event["event_type"] == "polish_validation_fallback"
        for event in db.list_run_events("fallback-repair")
    )


@pytest.mark.asyncio
async def test_failed_quality_report_keeps_evidence_without_formal_story(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Failed", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=6000,
    ))
    project = store.set_optimized_local_review(project.id, False)
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
async def test_resumed_quality_flow_keeps_previous_higher_scoring_candidate(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Resume the best", mode="short", genre="suspense",
        premise="A second revision scores lower than the first.", target_words=10_000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    previous = "previous higher-scoring candidate"
    (run_path / "outputs" / "best-candidate.md").write_text(previous, encoding="utf-8")
    (run_path / "outputs" / "quality-report.json").write_text(json.dumps({
        "best_score": 90,
        "best_attempt": 2,
        "status": "failed",
    }), encoding="utf-8")
    reviews = iter([
        quality_review(commercial=70, story=70, prose=70, decision="revise"),
        quality_review(commercial=65, story=65, prose=65, decision="revise"),
        quality_review(commercial=60, story=60, prose=60, decision="revise"),
    ])
    lower_candidate = "new lower-scoring candidate\n" * 300

    async def polish(*args, **kwargs):
        return lower_candidate

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    async def final_review(*args, **kwargs):
        return service._review(next(reviews)), {
            "coverage": 1.0,
            "windows": [],
            "review_mode": "full",
            "reviewed_windows": 1,
            "window_count": 1,
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {})

    with pytest.raises(RuntimeError, match="quality gate"):
        await service._quality_polish(
            run_id, run_path, project, "constraints", "resumed draft",
            service._review(quality_review()),
        )

    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    assert report["best_score"] == 90
    assert (run_path / "outputs" / "best-candidate.md").read_text(
        encoding="utf-8",
    ) == previous


@pytest.mark.asyncio
async def test_lower_conditional_pass_returns_matching_protected_best(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Keep the better pass", mode="short", genre="suspense",
        premise="A weaker revision still reaches the minimum gate.", target_words=10_000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    previous = "P" * 7000
    lower = "L" * 7000
    previous_review = service._review(quality_review(
        commercial=92, story=90, prose=88, decision="pass",
    ))
    (run_path / "outputs" / "best-candidate.md").write_text(previous, encoding="utf-8")
    (run_path / "outputs" / "quality-report.json").write_text(json.dumps({
        "best_score": previous_review["score"],
        "best_attempt": 1,
        "status": "passed",
        "terminal_reviewed_hash": hashlib.sha256(previous.encode("utf-8")).hexdigest(),
        "final_attempts": [{"attempt": 1, "review": previous_review}],
    }), encoding="utf-8")

    async def polish(*args, **kwargs):
        return lower

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    async def final_review(*args, **kwargs):
        return service._review(quality_review(
            commercial=78, story=78, prose=78, decision="revise",
        )), {
            "coverage": 1.0,
            "windows": [],
            "review_mode": "full",
            "reviewed_windows": 1,
            "window_count": 1,
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {})

    selected, report = await service._quality_polish(
        run_id, run_path, project, "constraints", "resumed draft",
        service._review(quality_review()),
    )

    assert selected == previous
    assert report["best_score"] == previous_review["score"]
    assert report["status"] == "passed"
    assert report["terminal_reviewed_hash"] == hashlib.sha256(
        previous.encode("utf-8"),
    ).hexdigest()


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

    assert gateway.roles == ["planning", "planning", "review"]
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
async def test_structural_patch_context_keeps_linked_local_evidence_and_full_neighbors(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Local patch context", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    previous = "PREVIOUS-FULL-START " + "P" * 1100 + " PREVIOUS-FULL-END"
    target = "TARGET linked evidence " + "T" * 900
    following = "NEXT-FULL-START " + "N" * 1100 + " NEXT-FULL-END"
    plan = {
        "global_facts": ["The promise is binding."],
        "checks": [
            {"kind": "required_text", "value": "linked evidence", "issue_ids": ["issue-1"]},
            {"kind": "forbidden_text", "value": "UNRELATED CHECK", "issue_ids": ["issue-2"]},
        ],
        "tasks": [{
            "segments": [2], "instruction": "Repair only the linked promise.",
            "issue_ids": ["issue-1"], "seven_step_position": "承：压力升级",
        }],
    }

    class Gateway:
        def __init__(self):
            self.users = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.users.append(user)
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "polisher", "input_tokens": 1000,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("local-context", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "local-context"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._polish_short_segments(
        "local-context", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join([previous, target, following]),
        "{}", structural=True, prepared_revision_plan=plan,
    )

    prompt = gateway.users[0]
    assert previous in prompt
    assert following in prompt
    assert '"issue_ids":["issue-1"]' in prompt
    assert "linked evidence" in prompt
    assert "UNRELATED CHECK" not in prompt
    assert "承：压力升级" in prompt
    assert '"scene_id"' not in prompt
    assert prompt.count(target) == 1


@pytest.mark.asyncio
async def test_structural_patch_context_requires_explicit_issue_id_intersection(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Explicit check links", mode="short", genre="suspense",
        premise="A witness corrects one claim.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    target = ("TARGET-CONTENT " * 80).strip()
    plan = {
        "checks": [
            {"kind": "forbidden_text", "value": "LINKED-SCALAR", "issue_ids": "task-alpha"},
            {"kind": "forbidden_text", "value": "LINKED-LIST", "issue_ids": ["task-alpha"]},
            {"kind": "forbidden_text", "value": "UNRELATED-SCALAR", "issue_ids": "task-beta"},
            {"kind": "forbidden_text", "value": "UNSCOPED-CHECK"},
        ],
        "tasks": [{
            "segments": [2], "instruction": "Repair only task alpha.",
            "issue_ids": "task-alpha",
        }],
    }

    class Gateway:
        def __init__(self):
            self.users = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.users.append(user)
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "polisher", "input_tokens": 1000,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("explicit-links", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "explicit-links"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._polish_short_segments(
        "explicit-links", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["Opening", target, "Ending"]),
        "{}", structural=True, prepared_revision_plan=plan,
    )

    prompt = gateway.users[0]
    assert "LINKED-SCALAR" in prompt
    assert "LINKED-LIST" in prompt
    assert "UNRELATED-SCALAR" not in prompt
    assert "UNSCOPED-CHECK" not in prompt


@pytest.mark.asyncio
async def test_structural_patch_context_uses_only_adjacent_boundary_paragraphs(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Boundary paragraphs", mode="short", genre="suspense",
        premise="A witness corrects one claim.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    previous = "PREVIOUS-FIRST\n\n   \n\nPREVIOUS-LAST"
    target = ("TARGET-ONLY " * 90).strip()
    following = "NEXT-FIRST\n\n\nNEXT-LAST"
    plan = {
        "checks": [{
            "kind": "forbidden_text", "value": "ABSENT-TEXT", "issue_ids": ["issue-1"],
        }],
        "tasks": [{
            "segments": [2], "instruction": "Repair only the target.",
            "issue_ids": ["issue-1"],
        }],
    }

    class Gateway:
        def __init__(self):
            self.users = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.users.append(user)
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "polisher", "input_tokens": 1000,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("boundary-context", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "boundary-context"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    await service._polish_short_segments(
        "boundary-context", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join([previous, target, following]),
        "{}", structural=True, prepared_revision_plan=plan,
    )

    prompt = gateway.users[0]
    assert "PREVIOUS-LAST" in prompt
    assert "NEXT-FIRST" in prompt
    assert "PREVIOUS-FIRST" not in prompt
    assert "NEXT-LAST" not in prompt
    assert prompt.count(target) == 1


@pytest.mark.asyncio
async def test_targeted_split_children_keep_local_context_and_chinese_events(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Targeted split", mode="short", genre="suspense",
        premise="A witness repairs a statement.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    target = "\n\n".join(f"Target paragraph {index}. " + "X" * 520 for index in range(4))
    plan = {
        "checks": [{
            "kind": "required_text", "value": "Target paragraph",
            "issue_ids": ["issue-split"],
        }],
        "tasks": [{
            "segments": [2], "instruction": "Repair this one issue.",
            "issue_ids": ["issue-split"], "seven_step_position": "转：证词反转",
        }],
    }

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            source = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            self.calls.append((user, source, max_output_tokens))
            if source == target:
                return ModelResult("", {
                    "model_name": "polisher", "output_tokens": max_output_tokens,
                    "finish_reason": "max_tokens",
                })
            return ModelResult(source, {"model_name": "polisher", "input_tokens": 100})

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("targeted-split", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "targeted-split"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._polish_short_segments(
        "targeted-split", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["Opening", target, "Ending"]),
        "{}", structural=True, prepared_revision_plan=plan,
    )

    child_prompts = [user for user, source, _budget in gateway.calls if source != target]
    assert target in result
    assert child_prompts
    assert all('"issue_ids":["issue-split"]' in prompt for prompt in child_prompts)
    assert all("COMPACT FULL STORY MAP" not in prompt for prompt in child_prompts)
    events = db.list_run_events("targeted-split")
    assert any("提高输出上限" in event["message"] for event in events)
    assert any("拆分当前片段" in event["message"] for event in events)


@pytest.mark.asyncio
async def test_targeted_route_failure_preserves_group_and_continues_next_group(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "polish", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Group isolation", mode="short", genre="suspense",
        premise="Two independent corrections.", target_words=9000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    failed_source = "FAIL bad fact. " * 90
    successful_source = "GOOD bad fact. " * 90
    parts = ["Opening", failed_source, "Bridge", successful_source, "Ending"]
    plan = {
        "checks": [{"kind": "forbidden_text", "value": "bad fact"}],
        "tasks": [
            {"segments": [2], "instruction": "Repair first.", "issue_ids": ["issue-a"]},
            {"segments": [4], "instruction": "Repair second.", "issue_ids": ["issue-b"]},
        ],
    }

    class Gateway:
        async def complete(self, role, system, user, max_output_tokens=None):
            source = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            if "FAIL" in source:
                raise RuntimeError("primary route failed")
            return ModelResult(source.replace("bad fact", "fixed fact"), {
                "model_name": "primary", "input_tokens": 100,
            })

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            source = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            if "FAIL" in source:
                raise RuntimeError("fallback route failed")
            return ModelResult(source.replace("bad fact", "fixed fact"), {
                "model_name": "fallback", "configured_fallback_direct": True,
            })

    service = WorkflowService(db, store, Gateway(), SkillGate(db, SkillScanner([skill_root])))
    db.create_run("group-isolation", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "group-isolation"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._polish_short_segments(
        "group-isolation", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts), "{}",
        structural=True, prepared_revision_plan=plan,
    )

    revised = WorkflowService._split_segments(result)
    assert revised[1] == failed_source.strip()
    assert "fixed fact" in revised[3]
    event = next(item for item in db.list_run_events("group-isolation")
                 if item["event_type"] == "targeted_group_failed")
    assert "首选和备用模型均失败" in event["message"]


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
    assert gateway.roles == ["planning", "planning", "review"]
    assert any(event["event_type"] == "model_fallback"
               for event in db.list_run_events("plan-fallback"))


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [
    '{"checks": [], "tasks": [',
    '{"checks": [], "tasks": []}\n{"checks": [], "tasks": []}',
], ids=["truncated", "ambiguous"])
async def test_invalid_json_retry_repairs_only_the_malformed_revision_plan(
    tmp_path, malformed,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Plan repair", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=12000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [{"segments": [2], "instruction": "Repair the canon conflict."}],
    })

    class RepairGateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append({
                "role": role, "user": user, "max_output_tokens": max_output_tokens,
            })
            return ModelResult(
                malformed if len(self.calls) == 1 else plan,
                {"model_name": "planner"},
            )

    gateway = RepairGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("plan-repair", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "plan-repair"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._plan_structural_revision(
        "plan-repair", run_path, project, "constraints",
        json.dumps({"issues": [{
            "category": "canon", "severity": "critical", "action": "Repair canon.",
        }]}),
        segment_map(["UNIQUE MANUSCRIPT MATERIAL " * 20] * 5), "-2",
    )

    assert result["target_segments"] == [2]
    assert [call["role"] for call in gateway.calls] == ["planning", "planning"]
    repair_prompt = gateway.calls[1]["user"]
    assert malformed in repair_prompt
    assert "repair_revision_plan_v1" in repair_prompt
    assert "COMPACT SEGMENT MAP" not in repair_prompt
    assert "UNIQUE MANUSCRIPT MATERIAL" not in repair_prompt


@pytest.mark.asyncio
async def test_oversized_revision_plan_is_deferred_instead_of_falling_back(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Batched plan", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=10000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [
            {"segments": [1], "instruction": "Repair the opening."},
            {"segments": [4], "instruction": "Repair the ending."},
            {"segments": [2], "instruction": "Repair the investigation."},
        ],
    })
    gateway = RecordingGateway([plan])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("batched-plan", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "batched-plan"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._plan_structural_revision(
        "batched-plan", run_path, project, "constraints",
        json.dumps({"issues": [{
            "category": "canon", "severity": "critical", "action": "Repair canon.",
        }]}),
        segment_map(["A" * 300] * 4), "-2",
    )

    assert result["target_segments"] == [1, 4]
    assert result["deferred_segments"] == [2]
    assert gateway.roles == ["planning"]
    deferred = next(item for item in db.list_run_events("batched-plan")
                    if item["event_type"] == "revision_plan_deferred")
    assert deferred["metadata"] == {
        "current_segments": [1, 4], "deferred_segments": [2],
    }


@pytest.mark.asyncio
async def test_structural_polish_executes_every_deferred_batch(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Complete batches", mode="short", genre="romance",
        premise="A relationship collapses.", target_words=10000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    plan = json.dumps({
        "checks": [
            {"kind": "forbidden_text", "value": "bad-one"},
            {"kind": "forbidden_text", "value": "bad-two"},
            {"kind": "forbidden_text", "value": "bad-four"},
        ],
        "tasks": [
            {"segments": [1], "instruction": "Repair scene one."},
            {"segments": [4], "instruction": "Repair scene four."},
            {"segments": [2], "instruction": "Repair scene two."},
        ],
    })
    parts = [
        "bad-one " * 100,
        "bad-two " * 100,
        "clean-three " * 80,
        "bad-four " * 100,
    ]
    gateway = RecordingGateway([
        plan,
        "fixed-one " * 100,
        "fixed-four " * 100,
        "fixed-two " * 100,
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("complete-batches", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "complete-batches"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    revised = await service._polish_short_segments(
        "complete-batches", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts),
        json.dumps({"issues": [{
            "category": "canon", "severity": "critical", "action": "Repair all facts.",
        }]}),
        suffix="-2", structural=True,
    )

    revised_parts = WorkflowService._split_segments(revised)
    assert "fixed-one" in revised_parts[0]
    assert "fixed-two" in revised_parts[1]
    assert revised_parts[2] == parts[2].strip()
    assert "fixed-four" in revised_parts[3]
    assert gateway.roles == ["planning", "polish", "polish", "polish"]
    continued = next(item for item in db.list_run_events("complete-batches")
                     if item["event_type"] == "revision_batch_continued")
    assert continued["metadata"] == {
        "completed_segments": [1, 4], "next_segments": [2], "remaining_segments": [],
    }


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


@pytest.mark.asyncio
async def test_quality_final_review_hides_internal_segment_markers(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Clean review", mode="short", genre="suspense",
        premise="A hidden fact surfaces.", target_words=10_000,
    ))
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    db.create_run("clean-review", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "clean-review"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    parts = [f"scene-{index}-" + "x" * 2100 for index in range(4)]
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)
    clean_manuscript = "\n\n".join(parts)
    reviewed = []

    async def unchanged_polish(*args, **kwargs):
        return manuscript

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    async def full_review(
        run_id, path, current_project, constraints, text, initial, suffix="", analysis=None,
    ):
        reviewed.append(text)
        return service._review(quality_review()), {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 1, "window_count": 1,
        }

    monkeypatch.setattr(service, "_polish_short_segments", unchanged_polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", full_review)

    polished, report = await service._quality_polish(
        "clean-review", run_path, project, "constraints", manuscript,
        service._review(quality_review()),
    )

    assert polished == manuscript
    assert reviewed == [clean_manuscript]
    assert report["terminal_reviewed_hash"] == hashlib.sha256(
        clean_manuscript.encode("utf-8")
    ).hexdigest()


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
async def test_ordinary_polish_receives_window_findings_and_actual_handoff(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Window context", mode="short", genre="suspense",
        premise="A key links two meetings.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.users = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.users.append(user)
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "polisher", "input_tokens": 500,
            })

    class LocalNlp:
        def __init__(self):
            self.calls = 0

        def analyze(self, text):
            self.calls += 1
            return {"available": False, "backend": "test", "backend_version": "test-v1"}

    gateway = Gateway()
    local_nlp = LocalNlp()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
        local_nlp=local_nlp,
    )
    db.create_run("window-context", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "window-context"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    first = (
        "她在旧宅的书桌下摸到铜钥匙，听见走廊尽头传来脚步声。"
        "她决定把铜钥匙藏进衣柜。"
    )
    second = (
        "渡船已经离开河岸，沈岚却没有出现，她只好沿着石阶继续寻找。"
        "她发现船票背面写着另一个地址。"
    )
    findings = json.dumps({"issues": [
        {"category": "continuity", "severity": "high",
         "evidence": "她决定把铜钥匙藏进衣柜。", "action": "说明钥匙藏放是否安全。"},
        {"category": "timeline", "severity": "high",
         "evidence": "渡船已经离开河岸。", "action": "核对渡船离岸的时间。"},
    ]}, ensure_ascii=False)

    await service._polish_short_segments(
        "window-context", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join([first, second]), findings,
    )

    assert len(gateway.users) == 2
    assert "说明钥匙藏放是否安全" in gateway.users[0]
    assert "核对渡船离岸的时间" not in gateway.users[0]
    assert "核对渡船离岸的时间" in gateway.users[1]
    assert "说明钥匙藏放是否安全" not in gateway.users[1]
    assert '"上一窗实际交接状态": "她决定把铜钥匙藏进衣柜。"' in gateway.users[1]
    assert "seven_step_position" not in gateway.users[0]
    assert "seven_step_position" not in gateway.users[1]
    assert (run_path / "outputs" / "analysis-polish-source.json").is_file()
    assert local_nlp.calls == 1


def test_polish_narrative_context_includes_a_linked_payoff() -> None:
    text = "我答应一定带她回家。\n\n后来我找到旧车票，终于带她回家。"
    ledger = build_narrative_ledger(text)
    second_start = text.index("后来")

    context = WorkflowService._polish_narrative_context(
        ledger, text[second_start:], second_start, len(text),
    )

    assert context["本窗关联的提问与兑现"]


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


def test_output_budget_uses_each_selected_route_model_ceiling(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="claude", provider_id="provider", display_name="Claude",
        model_name="custom-primary", max_output_tokens=6144,
    )
    db.save_model(
        model_id="backup", provider_id="provider", display_name="Backup",
        model_name="custom-fallback", max_output_tokens=3072,
    )
    db.save_role_binding("polish", "provider", "claude", "provider", "backup")
    service = WorkflowService.__new__(WorkflowService)
    service.db = db

    assert service._output_budget_for_call("polish", 2000, "polish", False) == 4524
    assert service._output_budget_for_call("polish", 2000, "polish", True) == 3072


def test_ordinary_stage_budgets_use_defaults_capped_by_selected_route_ceiling(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="model", provider_id="provider", display_name="Model",
        model_name="custom-model", max_output_tokens=6000,
    )
    for role in ("planning", "draft", "review", "polish"):
        db.save_role_binding(role, "provider", "model", None, None)
    service = WorkflowService.__new__(WorkflowService)
    service.db = db

    assert service._output_budget_for_call("planning", None, "planning", False) == 6000
    assert service._output_budget_for_call("draft", None, "draft", False) == 6000
    assert service._output_budget_for_call("review", None, "review", False) == 4096
    assert service._output_budget_for_call("polish", 2000, "polish", False) == 4524


def test_output_budget_keeps_stage_default_without_configured_model_ceiling(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="legacy", provider_id="provider", display_name="Legacy",
        model_name="claude-sonnet-5",
    )
    db.save_role_binding("polish", "provider", "legacy", None, None)
    service = WorkflowService.__new__(WorkflowService)
    service.db = db

    assert service._output_budget_for_call("polish", 2000, "polish", False) == 4524


@pytest.mark.asyncio
async def test_targeted_retry_at_provider_ceiling_does_not_repeat_same_request(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="polisher", provider_id="provider", display_name="Polisher",
        model_name="custom-polisher", max_output_tokens=8192,
    )
    db.save_role_binding("polish", "provider", "polisher", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Ceiling split", mode="short", genre="suspense",
        premise="A witness revisits the scene.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.budgets = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.budgets.append(max_output_tokens)
            return ModelResult("", {
                "model_name": "custom-polisher", "output_tokens": max_output_tokens,
                "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("ceiling-split", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "ceiling-split"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    with pytest.raises(IncompleteModelOutputError, match="remained incomplete"):
        await service._stage(
            "ceiling-split", run_path, project, "polish", "constraints",
            "MANUSCRIPT SEGMENT:\nSource prose.", allow_tools=False,
            targeted_retry=True,
        )

    assert gateway.budgets == [8192]


@pytest.mark.asyncio
async def test_targeted_retry_without_configured_ceiling_expands_to_quality_estimate(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Legacy ceiling", mode="short", genre="suspense",
        premise="A witness revisits the scene.", target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.budgets = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.budgets.append(max_output_tokens)
            return ModelResult("", {
                "model_name": "legacy", "output_tokens": max_output_tokens,
                "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    db.create_run("legacy-ceiling", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "legacy-ceiling"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    with pytest.raises(IncompleteModelOutputError, match="remained incomplete"):
        await service._stage(
            "legacy-ceiling", run_path, project, "polish", "constraints",
            "MANUSCRIPT SEGMENT:\n" + "A" * 1000, allow_tools=False,
            output_source_characters=1000, targeted_retry=True,
        )

    assert gateway.budgets == [1606, 2774]
    assert 8192 not in gateway.budgets


@pytest.mark.asyncio
async def test_polish_stage_adapts_large_rule_context_with_stage_default_budget(tmp_path) -> None:
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
    assert budget == 3124


def test_polish_segments_are_bounded_and_preserve_paragraph_order() -> None:
    paragraphs = [(f"段落{i}。" * 180) for i in range(1, 9)]
    text = "\n\n".join(paragraphs)

    parts = WorkflowService._split_polish_segments(text, target=1800, maximum=2400)

    assert len(parts) > 1
    assert max(map(len, parts)) <= 2400
    assert "".join("".join(parts).split()) == "".join("".join(text.split()).split())


@pytest.mark.asyncio
async def test_polish_output_limit_retries_primary_with_compact_prompt(tmp_path) -> None:
    source = "A continuous scene with fixed events and natural sentence rhythm. " * 20

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append({
                "prefer_configured_fallback": False,
                "prompt": user,
                "max_output_tokens": max_output_tokens,
            })
            if len(self.calls) == 1:
                return ModelResult("", {
                    "model_name": "claude", "input_tokens": 7000,
                    "output_tokens": max_output_tokens, "finish_reason": "max_tokens",
                })
            return ModelResult(source, {
                "model_name": "claude", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.calls.append({
                "prefer_configured_fallback": True,
                "prompt": user,
                "max_output_tokens": max_output_tokens,
            })
            return ModelResult(source, {"model_name": "backup"})

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert len(gateway.calls) == 2
    assert gateway.calls[1]["prefer_configured_fallback"] is False
    assert "只返回修改后的正文，不解释、不分析" in gateway.calls[1]["prompt"]
    assert "COMPACT FULL STORY MAP" not in gateway.calls[1]["prompt"]
    assert 8192 not in [call["max_output_tokens"] for call in gateway.calls]
    events = db.list_run_events("polish-recovery")
    assert any(event["event_type"] == "polish_compact_retry" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)
    assert not any(event["event_type"] == "polish_max_tokens_retry" for event in events)


@pytest.mark.asyncio
async def test_polish_nonempty_max_token_output_is_discarded_before_compact_retry(
    tmp_path,
) -> None:
    source = "A complete paragraph preserves every fixed event in natural prose. " * 18

    class Gateway:
        def __init__(self):
            self.primary_calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            raise AssertionError("ordinary polish must use the primary-only gateway path")

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            self.primary_calls += 1
            if self.primary_calls == 1:
                return ModelResult(source[: len(source) // 2], {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            return ModelResult(source, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            raise AssertionError("compact primary success must not call fallback")

    gateway = Gateway()
    _, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert gateway.primary_calls == 2
    assert not (run_path / "outputs" / "polish-part-01.md").exists()


@pytest.mark.asyncio
async def test_polish_empty_tool_use_output_enters_compact_recovery(tmp_path) -> None:
    source = "A complete segment preserves fixed events in naturally paced prose. " * 18

    class Gateway:
        def __init__(self):
            self.prompts = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.prompts.append(user)
            if len(self.prompts) == 1:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "tool_use",
                })
            return ModelResult(source, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert len(gateway.prompts) == 2
    assert "只返回修改后的正文，不解释、不分析" in gateway.prompts[1]
    assert not any(
        event["event_type"] == "polish_tool_use_retry"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_compact_primary_failure_uses_configured_fallback(tmp_path) -> None:
    source = "A witness revisits the scene and verifies every fixed event carefully. " * 18

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append((False, user))
            return ModelResult("", {
                "model_name": "primary", "output_tokens": max_output_tokens,
                "finish_reason": "max_tokens",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append((True, user))
            return ModelResult(source, {
                "model_name": "backup", "finish_reason": "end_turn",
                "configured_fallback_direct": True,
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert [route for route, _ in gateway.routes] == [False, False, True]
    assert "只返回修改后的正文，不解释、不分析" in gateway.routes[1][1]
    assert gateway.routes[1][1] == gateway.routes[2][1]
    events = db.list_run_events("polish-recovery")
    assert any(event["event_type"] == "polish_compact_fallback" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_text", ["", "source"])
async def test_polish_validation_fallback_max_tokens_preserves_source_without_retry(
    tmp_path, fallback_text,
) -> None:
    source = "A locally valid source segment keeps every established event in natural prose. " * 16

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append(("primary", max_output_tokens))
            return ModelResult("too short", {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append(("fallback", max_output_tokens))
            text = source if fallback_text else ""
            return ModelResult(text, {
                "model_name": "backup", "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert [route for route, _ in gateway.routes] == ["primary", "fallback"]
    assert not any(
        event["event_type"] == "polish_max_tokens_retry"
        for event in db.list_run_events("polish-recovery")
    )
    checkpoint = json.loads((
        run_path / "outputs" / "polish-checkpoints" / "initial" / "part-01.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["accepted"] is False


@pytest.mark.asyncio
async def test_polish_validation_fallback_fatal_error_stops_immediately(tmp_path) -> None:
    source = "A source segment keeps every established event in naturally paced prose. " * 16

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return ModelResult("too short", {"model_name": "primary"})

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append("fallback")
            raise RuntimeError("missing_api_key: backup")

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(RuntimeError, match="missing_api_key"):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints", source, "{}",
        )

    assert gateway.routes == ["primary", "fallback"]
    assert not any(
        event["event_type"] == "polish_segment_preserved"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_validation_fallback_transport_error_uses_safe_split(tmp_path) -> None:
    paragraphs = [(str(index) + "A" * 399) for index in range(4)]
    source = "\n\n".join(paragraphs)

    class Gateway:
        def __init__(self):
            self.routes = []
            self.primary_calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            self.primary_calls += 1
            if self.primary_calls == 1:
                return ModelResult("too short", {"model_name": "primary"})
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append("fallback")
            raise RuntimeError("524 Gateway Timeout")

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    assert gateway.routes == ["primary", "fallback", "primary", "primary"]
    assert any(
        event["event_type"] == "polish_segment_split"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_recovery_counts_all_returned_receipt_input_tokens(tmp_path) -> None:
    first = "A complete source segment preserves a stable event in natural prose. " * 16
    second = "A second source segment preserves another stable event in natural prose. " * 16

    class Gateway:
        def __init__(self):
            self.routes = []
            self.primary_calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            self.primary_calls += 1
            segment = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            if self.primary_calls <= 2:
                return ModelResult(segment * 2, {
                    "model_name": "primary", "input_tokens": 110,
                })
            return ModelResult(segment, {
                "model_name": "primary", "input_tokens": 110,
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append("fallback")
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "backup", "input_tokens": 110,
            })

    gateway = Gateway()
    _, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join((first, second))

    with pytest.raises(PolishTokenBudgetError, match="round"):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints", manuscript, "{}",
            round_cap_override=300,
        )

    assert gateway.routes == ["primary", "primary", "fallback"]


@pytest.mark.asyncio
async def test_polish_recovery_counts_empty_output_receipt_input_tokens(tmp_path) -> None:
    first = "A complete source segment preserves a stable event in natural prose. " * 16
    second = "A second source segment must be blocked by the round input cap. " * 16

    class Gateway:
        def __init__(self):
            self.routes = []

        @staticmethod
        def empty_result(model_name):
            return ModelResult("", {
                "model_name": model_name, "input_tokens": 110,
                "finish_reason": "end_turn",
            })

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return self.empty_result("primary")

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append("fallback")
            return self.empty_result("backup")

    gateway = Gateway()
    _, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(PolishTokenBudgetError, match="round"):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints",
            WorkflowService.SHORT_SEGMENT_SEPARATOR.join((first, second)), "{}",
            round_cap_override=300,
        )

    assert gateway.routes == ["primary", "primary", "fallback"]


@pytest.mark.asyncio
async def test_polish_compact_recovery_cancellation_propagates_without_preserving(
    tmp_path,
) -> None:
    parts = [
        "A first source segment preserves a stable event in natural prose. " * 16,
        "A second source segment must never be called after cancellation. " * 16,
    ]

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            if self.calls == 1:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            raise asyncio.CancelledError

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(asyncio.CancelledError):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints",
            WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts), "{}",
        )

    assert gateway.calls == 2
    assert not any(
        event["event_type"] == "polish_segment_preserved"
        for event in db.list_run_events("polish-recovery")
    )
    checkpoint_root = run_path / "outputs" / "polish-checkpoints" / "initial"
    assert not list(checkpoint_root.glob("*.json"))


@pytest.mark.asyncio
async def test_polish_full_success_resets_consecutive_output_error_count(tmp_path) -> None:
    parts = [
        f"Segment {index} preserves a distinct event in naturally paced prose. " * 15
        for index in range(1, 5)
    ]

    class Gateway:
        def __init__(self):
            self.prompts = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.prompts.append(user)
            call = len(self.prompts)
            if call in {1, 4}:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            segment_index = {2: 0, 3: 1, 5: 2, 6: 3}[call]
            return ModelResult(parts[segment_index], {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints",
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts), "{}",
    )

    assert len(gateway.prompts) == 6
    assert "只返回修改后的正文，不解释、不分析" not in gateway.prompts[5]
    assert not any(
        event["event_type"] == "polish_compact_circuit_opened"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_obviously_long_output_uses_compact_recovery(tmp_path) -> None:
    source = "A measured scene preserves every established fact without repetition. " * 18

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append((False, user))
            return ModelResult(source * 2 if len(self.routes) == 1 else source, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append((True, user))
            return ModelResult(source, {"model_name": "backup"})

    gateway = Gateway()
    _, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert [route for route, _ in gateway.routes] == [False, False]
    assert "只返回修改后的正文，不解释、不分析" in gateway.routes[1][1]


@pytest.mark.asyncio
async def test_polish_both_compact_routes_fail_preserves_source_and_continues(tmp_path) -> None:
    first = "The first segment keeps its established event and measured sentence rhythm. " * 16
    second = "The second segment continues independently with another established event. " * 16
    improved_second = second.replace("continues", "moves forward")

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append(False)
            if len(self.routes) <= 2:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            return ModelResult(improved_second, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append(True)
            return ModelResult("", {
                "model_name": "backup", "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join((first, second))

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", manuscript, "{}",
    )

    assert result == WorkflowService.SHORT_SEGMENT_SEPARATOR.join((
        first.strip(), improved_second.strip(),
    ))
    assert gateway.routes == [False, False, True, False]
    checkpoint = json.loads((
        run_path / "outputs" / "polish-checkpoints" / "initial" / "part-01.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["accepted"] is False
    assert checkpoint["status"] == "preserved_source"
    events = db.list_run_events("polish-recovery")
    assert any(event["event_type"] == "polish_segment_preserved" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)
    progress = [event for event in events if event["event_type"] == "polish_segment_progress"]
    assert progress[-1]["metadata"] == {
        "segment": 2, "total": 2, "completed": 2, "preserved": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "missing api key", "authentication failed", "invalid role binding",
])
async def test_polish_fatal_configuration_error_stops_immediately(tmp_path, message) -> None:
    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            raise RuntimeError(message)

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(RuntimeError, match=message):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints",
            "A complete source paragraph with fixed facts. " * 20, "{}",
        )

    assert gateway.calls == 1
    assert not any(
        event["event_type"] == "polish_segment_preserved"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_wrapped_fatal_configuration_error_stops_immediately(tmp_path) -> None:
    wrapped = ModelRoutesExhaustedError(
        RuntimeError("provider_not_found: primary"), RuntimeError("504 Gateway Timeout"),
    )

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            raise wrapped

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(ModelRoutesExhaustedError):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints",
            "\n\n".join(
                f"Paragraph {index} keeps fixed facts in valid prose. " * 9
                for index in range(4)
            ), "{}",
        )

    assert gateway.calls == 1
    assert not any(
        event["event_type"] in {"polish_segment_preserved", "polish_segment_split"}
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_structural_polish_does_not_enter_ordinary_compact_recovery(tmp_path) -> None:
    source = "A structural segment keeps every approved event in place. " * 16

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            return ModelResult("", {
                "model_name": "primary", "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    with pytest.raises(IncompleteModelOutputError, match="remained incomplete"):
        await service._polish_short_segments(
            "polish-recovery", run_path, project, "constraints", source, "{}",
            structural=True, targeted_context={
                "tasks": [], "checks": [], "global_facts": [],
                "previous_paragraph": "", "next_paragraph": "", "segment": 1,
            },
        )

    assert gateway.calls == 2
    assert not any(
        event["event_type"].startswith("polish_compact")
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_two_consecutive_output_errors_skip_full_prompt_for_later_segments(
    tmp_path,
) -> None:
    parts = [
        f"Segment {index} preserves a distinct event in a naturally paced paragraph. " * 15
        for index in range(1, 4)
    ]

    class Gateway:
        def __init__(self):
            self.prompts = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.prompts.append(user)
            if len(self.prompts) in {1, 3}:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            target = parts[min((len(self.prompts) - 1) // 2, 2)]
            return ModelResult(target, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)

    await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", manuscript, "{}",
    )

    assert len(gateway.prompts) == 5
    assert "只返回修改后的正文，不解释、不分析" in gateway.prompts[4]
    assert sum(
        event["event_type"] == "polish_compact_circuit_opened"
        for event in db.list_run_events("polish-recovery")
    ) == 1

    new_run_id = "new-polish-task"
    db.create_run(new_run_id, project.id, "short-story", status="running")
    new_run_path = project.path / "runs" / new_run_id
    (new_run_path / "outputs").mkdir(parents=True)
    (new_run_path / "receipts").mkdir()
    await service._polish_short_segments(
        new_run_id, new_run_path, project, "constraints", parts[0], "{}",
    )
    assert "只返回修改后的正文，不解释、不分析" not in gateway.prompts[5]


@pytest.mark.asyncio
async def test_polish_resume_reuses_accepted_segments_and_retries_preserved_segments(
    tmp_path,
) -> None:
    first = "The accepted segment contains a stable event in natural prose. " * 16
    second = "The preserved segment contains another stable event in natural prose. " * 16

    class Gateway:
        def __init__(self):
            self.routes = []
            self.resume = False

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append(False)
            if self.resume or len(self.routes) == 1:
                return ModelResult(first if len(self.routes) == 1 else second, {
                    "model_name": "primary", "finish_reason": "end_turn",
                })
            return ModelResult("", {
                "model_name": "primary", "finish_reason": "max_tokens",
            })

        async def complete_configured_fallback(self, role, system, user,
                                               max_output_tokens=None):
            self.routes.append(True)
            return ModelResult("", {
                "model_name": "backup", "finish_reason": "max_tokens",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join((first, second))

    first_result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", manuscript, "{}",
    )
    gateway.resume = True
    resumed_result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", manuscript, "{}",
    )

    expected = WorkflowService.SHORT_SEGMENT_SEPARATOR.join((
        first.strip(), second.strip(),
    ))
    assert first_result == resumed_result == expected
    assert gateway.routes == [False, False, False, True, False]
    reused = [
        event for event in db.list_run_events("polish-recovery")
        if event["event_type"] == "polish_checkpoint_reused"
    ]
    assert reused[-1]["metadata"]["segment"] == 1


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

    with pytest.raises(IncompleteModelOutputError, match="remained incomplete"):
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
async def test_rejected_rhythm_retry_is_retried_until_accepted(tmp_path) -> None:
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
    assert gateway.calls == 4


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

    assert calls_after_first == ["primary"] * 4
    assert gateway.routes == calls_after_first
    assert first == second
    assert len(list((run_path / "outputs" / "polish-checkpoints" / "initial").glob("*.json"))) == 4


@pytest.mark.asyncio
async def test_ordinary_polish_does_not_reuse_gateway_fallback_circuit(tmp_path) -> None:
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

    assert gateway.routes == ["primary", "primary"]
    assert not any(
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


def test_polish_checkpoint_loader_accepts_legacy_authorized_checkpoint(tmp_path) -> None:
    root = tmp_path / "checkpoints"
    root.mkdir()
    source = "legacy source"
    polished = "legacy polished"
    (root / "part-01.json").write_text(json.dumps({
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "polished": polished,
        "status": "accepted",
    }), encoding="utf-8")

    assert WorkflowService._load_polish_checkpoint(root, 1, source) == polished


def test_polish_checkpoint_loader_rejects_non_boolean_false_acceptance(tmp_path) -> None:
    root = tmp_path / "checkpoints"
    root.mkdir()
    source = "preserved source"
    (root / "part-01.json").write_text(json.dumps({
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "polished": source,
        "accepted": "false",
        "status": "preserved_source",
    }), encoding="utf-8")

    assert WorkflowService._load_polish_checkpoint(root, 1, source) is None


def test_polish_checkpoint_loader_rejects_source_hash_mismatch(tmp_path) -> None:
    root = tmp_path / "checkpoints"
    WorkflowService._save_polish_checkpoint(root, 1, "old source", "polished")

    assert WorkflowService._load_polish_checkpoint(root, 1, "new source") is None


def test_polish_checkpoint_rejects_changed_authority_hash(tmp_path) -> None:
    root = tmp_path / "checkpoints"
    WorkflowService._save_polish_checkpoint(
        root, 1, "source", "polished", authority_hash="authority-v1",
    )

    assert WorkflowService._load_polish_checkpoint(
        root, 1, "source", authority_hash="authority-v1",
    ) == "polished"
    assert WorkflowService._load_polish_checkpoint(
        root, 1, "source", authority_hash="authority-v2",
    ) is None


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
    state = StoryStateStore(db).ensure(project.id, project.path)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, store.load_constraints(project.id), 4,
    )
    service._save_short_checkpoint(outputs, context)

    checkpoint = service._find_short_checkpoint(project, run_id, 4, context)
    review = service._find_short_stage_output(project, run_id, "review.md")

    assert checkpoint == outputs
    assert review == outputs / "review.md"


@pytest.mark.parametrize(("status", "reusable"), [
    ("failed", True),
    ("cancelled", True),
    ("completed", False),
    ("running", False),
    ("queued", False),
])
def test_cross_run_short_checkpoint_requires_resumable_terminal_status(
    tmp_path, status, reusable,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title=f"Checkpoint {status}", mode="short", genre="suspense",
        premise="Explicit new runs must not reuse completed work.", target_words=10000,
    ))
    db.create_run("source-run", project.id, "short-story", status=status)
    outputs = project.path / "runs" / "source-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text("complete plan", encoding="utf-8")
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, store.load_constraints(project.id), 4,
    )
    service._save_short_checkpoint(outputs, context)

    checkpoint = service._find_short_checkpoint(
        project, "explicit-new-run", 4, context,
    )

    assert (checkpoint == outputs) is reusable


def test_short_checkpoint_without_context_fingerprint_is_rejected(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Legacy checkpoint", mode="short", genre="suspense",
        premise="An old draft must not cross contexts.", target_words=10000,
    ))
    db.create_run("legacy-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "legacy-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text("complete plan", encoding="utf-8")
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, store.load_constraints(project.id), 4,
    )

    assert service._find_short_checkpoint(project, "new-run", 4, context) is None


def test_short_checkpoint_rejects_changed_outline_with_same_event_ids(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Outline fingerprint", mode="short", genre="suspense",
        premise="The same beat receives changed facts.", target_words=10000,
    ))
    db.create_run("old-outline", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "old-outline" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text("complete plan", encoding="utf-8")
    draft = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
        ["one", "two", "three", "four"]
    )
    (outputs / "draft.md").write_text(draft, encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    old_state = {
        **state.data,
        "outline": {
            "content": "## 第一章：相遇\n花穗在旧地点发现账册。",
            "events": [{"id": "EV-SAME0001", "label": "相遇"}],
        },
    }
    old_context = service._short_checkpoint_context(
        project, state.revision, old_state, "same constraints", 4,
    )
    service._save_short_checkpoint(outputs, old_context)
    changed_state = {
        **old_state,
        "outline": {
            **old_state["outline"],
            "content": "## 第一章：相遇\n花穗在新地点发现密信。",
        },
    }
    changed_context = service._short_checkpoint_context(
        project, state.revision, changed_state, "same constraints", 4,
    )

    assert old_state["outline"]["events"] == changed_state["outline"]["events"]
    assert service._find_short_checkpoint(
        project, "new-run", 4, changed_context,
    ) is None


@pytest.mark.parametrize("change", ["constraints", "revision"])
def test_short_checkpoint_rejects_changed_generation_authority(tmp_path, change) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title=f"Changed {change}", mode="short", genre="suspense",
        premise="Generation authority changes.", target_words=10000,
    ))
    db.create_run("old-context", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "old-context" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text("complete plan", encoding="utf-8")
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    old_context = service._short_checkpoint_context(
        project, state.revision, state.data, "old constraints", 4,
    )
    service._save_short_checkpoint(outputs, old_context)
    current_context = service._short_checkpoint_context(
        project,
        state.revision + (change == "revision"),
        state.data,
        "new constraints" if change == "constraints" else "old constraints",
        4,
    )

    assert service._find_short_checkpoint(
        project, "new-run", 4, current_context,
    ) is None


def test_short_stage_output_does_not_cross_run_boundary(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Bound review", mode="short", genre="suspense",
        premise="A new draft needs its own review.", target_words=10000,
    ))
    db.create_run("older-run", project.id, "short-story", status="failed")
    older_outputs = project.path / "runs" / "older-run" / "outputs"
    older_outputs.mkdir(parents=True)
    (older_outputs / "review.md").write_text(quality_review(), encoding="utf-8")
    db.create_run("current-run", project.id, "short-story", status="running")
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())

    assert service._find_short_stage_output(project, "current-run", "review.md") is None
    assert service._find_short_stage_output(
        project, "older-run", "review.md",
    ) == older_outputs / "review.md"


@pytest.mark.asyncio
async def test_fresh_draft_does_not_reuse_same_run_review_without_checkpoint(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Fresh review", mode="short", genre="suspense",
        premise="A regenerated draft needs a fresh review.", target_words=10000,
    ))
    db.create_run("fresh-review", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "fresh-review" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "review.md").write_text(quality_review(), encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    numerals = ["一", "二", "三", "四"]
    plan = "\n\n".join(
        f"### 第{numeral}段：事件{index}\n事件ID：EV-{index:08x}\n"
        f"大纲依据：事件{index}\n段首承接：状态{index}。\n"
        f"本段事件：推进{index}。\n段末交接：结果{index}。\n"
        + chr(0x4e00 + index) * 120
        for index, numeral in enumerate(numerals, 1)
    )

    async def fake_stage(run_id, run_path, current_project, stage, constraints, user, **kwargs):
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            return json.dumps({
                "core_goal": "完成目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成结局", "covered_event_ids": [],
            }, ensure_ascii=False)
        if stage == "planning":
            return plan
        if stage == "review":
            raise RuntimeError("fresh review requested")
        raise AssertionError(f"unexpected stage: {stage}")

    async def fake_draft(*args):
        return WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
            ["甲" * 500, "乙" * 500, "丙" * 500, "丁" * 500]
        )

    async def stale_review_used(*args, **kwargs):
        raise RuntimeError("stale review reused")

    service._stage = fake_stage
    service._draft_short_in_segments = fake_draft
    service._analyze_manuscript = lambda *args, **kwargs: {}
    service._quality_polish = stale_review_used

    with pytest.raises(RuntimeError, match="fresh review requested"):
        await service.run_short(project.id, use_crewai=False, run_id="fresh-review")

    checkpoint = json.loads(
        (outputs / "short-checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["version"] == WorkflowService.SHORT_CHECKPOINT_VERSION
    assert checkpoint["draft_sha256"] == hashlib.sha256(
        (outputs / "draft.md").read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_planning_repair_becomes_checkpoint_plan_and_keeps_initial_causal_chain(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Repair plan", mode="short", genre="suspense",
        premise="A repaired plan remains resumable.", target_words=10000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    numerals = ["一", "二", "三", "四"]
    repaired = "\n\n".join(
        f"### 第{numeral}段：事件{index}\n"
        f"事件ID：EV-{index:08x}\n大纲依据：事件{index}\n"
        f"段首承接：承接状态{index}。\n本段事件：推进事件{index}。\n"
        f"段末交接：留下状态{index}。\n" + chr(0x4e00 + index) * 120
        for index, numeral in enumerate(numerals, 1)
    )
    prompts = []

    async def fake_stage(run_id, run_path, current_project, stage, constraints, user, **kwargs):
        prompts.append(user)
        return "没有分段标题的初稿" if len(prompts) == 1 else repaired

    extract_calls = 0

    def fake_extract(run_id, plan):
        nonlocal extract_calls
        extract_calls += 1
        return (plan, {
            "core_goal": "保留最初因果链",
            "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
            "ending": "完成结局",
        }) if extract_calls == 1 else (plan, None)

    saved_chains = []

    def fake_save(run_id, current_project, chain):
        saved_chains.append(chain)

    captured = {}

    async def stop_after_planning(run_id, run_path, current_project, constraints, plan):
        captured["constraints"] = constraints
        captured["plan"] = plan
        raise RuntimeError("stop after planning")

    service._stage = fake_stage
    service._extract_short_causal_chain = fake_extract
    service._save_short_causal_chain = fake_save
    service._draft_short_in_segments = stop_after_planning

    with pytest.raises(RuntimeError, match="stop after planning"):
        await service.run_short(project.id, use_crewai=False, run_id="repair-plan")

    saved = project.path / "runs" / "repair-plan" / "outputs" / "planning.md"
    assert saved.read_text(encoding="utf-8") == repaired
    assert captured["plan"] == repaired
    assert "保留最初因果链" in captured["constraints"]
    assert saved_chains == [{
        "core_goal": "保留最初因果链",
        "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
        "ending": "完成结局",
    }]
    assert "segment_heading_format" in prompts[0]
    assert "### 第 1 段" in prompts[1]


@pytest.mark.asyncio
async def test_failed_planning_repair_does_not_persist_causal_chain(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Rejected chain", mode="short", genre="suspense",
        premise="A rejected plan must stay isolated.", target_words=10000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    extract_calls = 0
    saved_chains = []

    async def fake_stage(*args, **kwargs):
        return "仍然没有分段标题"

    def fake_extract(run_id, plan):
        nonlocal extract_calls
        extract_calls += 1
        return plan, {"core_goal": f"未通过的因果链{extract_calls}"}

    def fake_save(run_id, current_project, chain):
        saved_chains.append(chain)

    service._stage = fake_stage
    service._extract_short_causal_chain = fake_extract
    service._save_short_causal_chain = fake_save

    with pytest.raises(ValueError, match="规划稿未通过"):
        await service.run_short(project.id, use_crewai=False, run_id="rejected-chain")

    assert extract_calls == 2
    assert saved_chains == []
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
    from novel_flywheel.quality import issue_ledger
    prior_issue = {"category": "prose", "severity": "medium", "action": "Remove repetition."}
    stable_issue_id = issue_ledger([prior_issue])[0]["issue_id"]
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [],
        "reconciliations": [{
                "issue_id": stable_issue_id, "status": "resolved",
            "severity": "medium", "evidence": "The repeated wording is gone.",
        }],
    })
    gateway = RecordingGateway([*evidence, final])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", manuscript,
            {"issues": [prior_issue]},
    )

    assert review["score"] > 80
    assert audit["reviewed_windows"] == count
    assert audit["coverage"] == 1.0
    assert gateway.roles == ["final_review"] * (count + 1)
    assert "planning" not in gateway.roles
    assert all("WINDOW " in call["user"] for call in gateway.calls[:-1])
    assert all("summary and issues only" in call["user"] for call in gateway.calls[:-1])
    assert all("events" not in call["user"] for call in gateway.calls[:-1])
    assert audit["detail_analysis"]["performed"] is False


@pytest.mark.asyncio
async def test_final_review_accepts_structured_window_summary(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Structured summary", mode="short", genre="suspense",
        premise="A closed room.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    evidence = json.dumps({
        "summary": {"setting": "castle", "survivors": 7},
        "events": [], "issues": [], "character_states": [], "timeline": [], "promises": [],
    })
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })
    gateway = RecordingGateway([evidence, final])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    _, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )

    saved = json.loads((run_path / "outputs" / "final-review-evidence.json").read_text(encoding="utf-8"))
    assert json.loads(saved["windows"][0]["summary"]) == {"setting": "castle", "survivors": 7}
    assert audit["reviewed_windows"] == 1


@pytest.mark.asyncio
async def test_final_review_recovers_issue_reconciliation_from_matching_issue_ids(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Reconciliation recovery", mode="short", genre="suspense",
        premise="A review returns a readable summary object.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    evidence = json.dumps({
        "summary": "The issue remains visible in the manuscript.",
        "events": [], "issues": [], "character_states": [], "timeline": [],
        "promises": [],
    })
    prior_issue = {
        "category": "prose", "severity": "medium",
        "evidence": "The sentence repeats.", "action": "Remove repetition.",
    }
    from novel_flywheel.quality import issue_ledger
    stable_issue_id = issue_ledger([prior_issue])[0]["issue_id"]
    reconciled_issue = {
        **prior_issue, "issue_id": stable_issue_id, "status": "unresolved",
    }
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "revise", "issues": [reconciled_issue],
        "reconciliations": {
            "cross_window_timeline": "The timeline is coherent.",
            "issue_status": "The listed prose issue remains unresolved.",
        },
    })
    gateway = RecordingGateway([evidence, final])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript",
        {"issues": [prior_issue]},
    )

    assert review["score"] == 86.5
    assert audit["reconciliations"] == [reconciled_issue]
    assert audit["reconciliation_summary"] == {
        "cross_window_timeline": "The timeline is coherent.",
        "issue_status": "The listed prose issue remains unresolved.",
    }
    assert "missing_issue_reconciliation" not in audit["gate_reasons"]
    assert gateway.roles == ["final_review", "final_review"]
    assert any(
        event["event_type"] == "final_review_reconciliation_recovered"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_final_review_retries_malformed_window_with_configured_fallback(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("final_review", "primary", "reviewer", "backup", "reviewer-2")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Review fallback", mode="short", genre="suspense",
        premise="A record is incomplete.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    evidence = json.dumps({
        "summary": "The fallback recovered the complete window.",
        "events": [], "issues": [], "character_states": [], "timeline": [],
        "promises": [],
    })
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })

    class Gateway:
        def __init__(self):
            self.routes = []
            self.primary_responses = iter(['{"summary":"truncated', final])

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            return ModelResult(next(self.primary_responses), {"model_name": "reviewer"})

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.routes.append("configured_fallback")
            return ModelResult(evidence, {
                "model_name": "reviewer-2", "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )

    assert review["score"] > 80
    assert audit["reviewed_windows"] == 1
    assert gateway.routes == ["primary", "configured_fallback", "primary"]
    assert any(
        event["event_type"] == "final_review_json_fallback"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_final_review_retries_empty_adjudication_with_configured_fallback(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("final_review", "primary", "reviewer", "backup", "reviewer-2")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Empty adjudication", mode="short", genre="suspense",
        premise="The final report is empty.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    evidence = json.dumps({
        "summary": "The manuscript window was reviewed.", "issues": [],
    })
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })

    class Gateway:
        def __init__(self):
            self.routes = []
            self.primary_responses = iter([evidence, ""])

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            text = next(self.primary_responses)
            return ModelResult(text, {
                "model_name": "reviewer", "input_tokens": 100,
                "output_tokens": 0 if not text else 100, "finish_reason": None,
            })

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.routes.append("configured_fallback")
            return ModelResult(final, {
                "model_name": "reviewer-2", "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )

    assert review["score"] > 80
    assert audit["reviewed_windows"] == 1
    assert gateway.routes == ["primary", "primary", "configured_fallback"]
    assert any(
        event["event_type"] == "final_review_json_fallback"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_final_review_recovers_compact_window_after_primary_and_fallback_truncate(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("final_review", "primary", "reviewer", "backup", "reviewer-2")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Compact recovery", mode="short", genre="suspense",
        premise="A report is truncated.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    compact = json.dumps({
        "summary": "窗口摘要已恢复。", "issues": [],
    }, ensure_ascii=False)
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })

    class Gateway:
        def __init__(self):
            self.routes = []
            self.calls = []
            self.primary_responses = iter(['{"summary":"truncated', compact, final])
            self.fallback_responses = iter(['{"summary":"also truncated'])

        async def complete(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            self.calls.append(user)
            return ModelResult(next(self.primary_responses), {"model_name": "reviewer"})

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.routes.append("configured_fallback")
            self.calls.append(user)
            return ModelResult(next(self.fallback_responses), {
                "model_name": "reviewer-2", "configured_fallback_direct": True,
            })

    gateway = Gateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )

    assert review["score"] > 80
    assert audit["windows"][0]["summary"] == "窗口摘要已恢复。"
    assert audit["windows"][0]["recovery_mode"] == "compact_recovery"
    assert audit["final_review_recovery"]["succeeded"] is True
    assert gateway.routes == ["primary", "configured_fallback", "primary", "primary"]
    assert "只允许两个字段：summary" in gateway.calls[2]
    assert any(
        event["event_type"] == "final_review_compact_recovery"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_final_review_detail_evidence_is_requested_separately(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Separate detail", mode="short", genre="suspense",
        premise="Events need a separate pass.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    base = json.dumps({"summary": "基础窗口摘要。", "issues": []}, ensure_ascii=False)
    detail = json.dumps({
        "events": [{"event": "发现线索"}],
        "promises": [{"promise": "兑现承诺"}],
        "character_states": [], "timeline": [],
    }, ensure_ascii=False)
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })
    gateway = RecordingGateway([base, detail, final])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))
    run_id, run_path = service._begin_run(project, "short-story", None)

    analysis = {
        "narrative_ledger": {
            "important_uncertainties": [{
                "start": 0, "text": "开头承诺尚未找到明确兑现位置",
            }],
        },
    }
    _, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
        analysis=analysis,
    )

    assert audit["detail_mode"] == "separate"
    assert audit["detail_analysis"] == {
        "performed": True,
        "window_count": 1,
        "message": "本地检查发现需要确认的伏笔或承诺，已单独复核 1 个正文窗口",
    }
    assert audit["windows"][0]["events"] == [{"event": "发现线索"}]
    assert "详细事件和伏笔" in gateway.calls[1]["user"]


@pytest.mark.asyncio
async def test_single_window_quality_review_recovers_truncated_json(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Single window recovery", mode="short", genre="suspense",
        premise="A compact final report is enough.", target_words=2000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    recovered = json.dumps({
        "dimensions": {"commercial": 86, "story": 84, "prose": 82},
        "hard_fail": False, "decision": "pass", "issues": [],
    }, ensure_ascii=False)
    gateway = RecordingGateway(['{"dimensions":', recovered])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "正文内容。" * 300

    async def polish(*args, **kwargs):
        return candidate

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0, "windows": review_windows(candidate),
        "nlp": {"available": True}, "prose": {"blocking_count": 0},
    })

    selected, report = await service._quality_polish(
        run_id, run_path, project, "constraints", candidate,
        service._review(quality_review()),
    )

    assert selected == candidate
    assert report["status"] == "passed"
    assert report["final_review_recovery"]["succeeded"] is True
    assert "终审结果精简恢复" in gateway.calls[1]["user"]


@pytest.mark.asyncio
async def test_polish_rejects_model_change_to_exact_protected_passage(tmp_path) -> None:
    from novel_flywheel.passage_protection import PassageProtectionService

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Protected paragraph", mode="short", genre="suspense",
        premise="A promise must survive editing.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    protected = "他把钥匙放在我手里，说这次一定会回来。" * 12
    source = protected + "\n\n" + "我站在门口等到天亮，始终没有离开。" * 12
    changed = protected.replace("钥匙", "信封") + "\n\n" + "我站在门口等到天亮，始终没有离开。" * 12
    PassageProtectionService(db).create(
        project.id, source, excerpt=protected, mode="exact", label="关键承诺",
    )
    service = WorkflowService(
        db, store, RecordingGateway([changed]),
        SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("protected-polish", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "protected-polish"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._polish_short_segments(
        "protected-polish", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    conflict = next(
        item for item in db.list_run_events("protected-polish")
        if item["event_type"] == "passage_protection_conflict"
    )
    assert conflict["message"] == "模型修改了受保护片段，已保留原文"
    assert conflict["metadata"]["labels"] == ["关键承诺"]


@pytest.mark.asyncio
async def test_zhihu_v2_full_review_requests_criteria_evidence_and_runtime_scores(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="V2 review", mode="short", genre="suspense",
        premise="A promise is tested.", target_words=8000,
    ))
    project = store.apply_platform_profile(project.id, "zhihu-salt-short")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    evidence = json.dumps({
        "summary": "人物作出选择并承担代价。", "events": [],
        "character_states": [], "timeline": [], "promises": [], "issues": [],
    }, ensure_ascii=False)
    criteria = {
        "opening_pull": 89, "sustained_motivation": 66,
        "escalation_density": 58, "climax_ending_payoff": 43,
        "platform_fit": 69, "causal_arc": 53, "character_agency": 62,
        "continuity_logic": 44, "promise_payoff": 49,
        "relationship_change": 58, "clarity": 70, "scene_dialogue": 55,
        "voice_emotion": 65, "rhythm": 60, "repetition_ai": 52,
    }
    final = json.dumps({
        "criteria": criteria,
        "criterion_evidence": {
            name: {"location": "正文", "excerpt": "证据", "effect": "说明评分"}
            for name in criteria
        },
        "hard_fail": False, "decision": "pass", "issues": [],
        "reconciliations": [],
    }, ensure_ascii=False)
    gateway = RecordingGateway([evidence, final])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, _audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "正文" * 450, {"issues": []},
    )

    adjudication = gateway.calls[-1]["user"]
    assert "opening_pull" in adjudication
    assert "criterion_evidence" in adjudication
    assert review["score"] == 58.84
    assert review["dimensions"] == {
        "commercial": 63.62, "story": 52.95, "prose": 61.05,
    }
    assert review["scoring_profile_id"] == "zhihu-short-v2"
    assert review["judge_signature"].endswith("fake-final_review")


@pytest.mark.parametrize(("failure", "report_status", "event_type", "message"), [
    (
        ValueError("终审返回缺少必要评分"),
        "final_review_rejected",
        "final_review_result_rejected",
        "终审模型已返回，但结果未通过系统校验，已保留最佳稿",
    ),
    (
        RuntimeError("provider unavailable"),
        "final_review_incomplete",
        "final_review_model_failed",
        "终审模型调用失败，已保留最佳稿",
    ),
])
@pytest.mark.asyncio
async def test_quality_flow_distinguishes_final_review_validation_from_model_failure(
    tmp_path, monkeypatch, failure, report_status, event_type, message,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Final review error", mode="short", genre="suspense",
        premise="A final review must explain its failure.", target_words=8000,
    ))
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "正文" * 3200

    async def polish(*args, **kwargs):
        return candidate

    async def reader(*args, **kwargs):
        return service._review(quality_review())

    async def final_review(*args, **kwargs):
        raise failure

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0, "windows": [], "nlp": {"available": True},
        "prose": {"blocking_count": 0},
    })

    with pytest.raises(RuntimeError, match=message):
        await service._quality_polish(
            run_id, run_path, project, "constraints", candidate,
            service._review(quality_review()),
        )

    event = next(
        item for item in db.list_run_events(run_id)
        if item["event_type"] == event_type
    )
    assert event["message"] == message
    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    assert report["status"] == report_status
    assert (run_path / "outputs" / "best-candidate.md").read_text(
        encoding="utf-8",
    ) == candidate


@pytest.mark.asyncio
async def test_v2_passing_candidate_writes_hash_bound_quality_checkpoint(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Checkpoint V2", mode="short", genre="suspense",
        premise="A candidate passes.", target_words=8000,
    ))
    project = store.apply_platform_profile(project.id, "zhihu-salt-short")
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "正文" * 3600
    review = score_review({
        "dimensions": {"commercial": 84, "story": 82, "prose": 75},
        "hard_fail": False, "decision": "pass", "issues": [],
        "judge_signature": "provider/final-model",
    }, "zhihu-short-v2")

    async def polish(*args, **kwargs):
        return candidate

    async def reader(*args, **kwargs):
        return review

    async def final_review(*args, **kwargs):
        return review, {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 2, "window_count": 2,
            "adjudication_receipt": {
                "provider_id": "provider", "model_id": "final-model",
            },
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0, "windows": [], "nlp": {"available": True},
        "prose": {"blocking_count": 0}, "text_hash": hashlib.sha256(
            candidate.encode("utf-8")
        ).hexdigest(),
    })

    selected, report = await service._quality_polish(
        run_id, run_path, project, "constraints", candidate, review,
    )

    checkpoint = load_quality_checkpoint(run_path)
    assert selected == candidate
    assert report["status"] == "passed"
    assert checkpoint is not None
    assert checkpoint["manuscript_hash"] == hashlib.sha256(
        candidate.encode("utf-8")
    ).hexdigest()
    assert checkpoint["scoring_profile_id"] == "zhihu-short-v2"
    assert checkpoint["judge_signature"] == "provider/final-model"


@pytest.mark.asyncio
async def test_incremental_review_falls_back_when_baseline_is_not_revision_source(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Baseline mismatch", mode="short", genre="suspense",
        premise="Do not compare the wrong texts.", target_words=8000,
    ))
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    baseline = {
        "manuscript": "旧基线", "manuscript_hash": hashlib.sha256(
            "旧基线".encode("utf-8")
        ).hexdigest(),
        "analysis": {}, "windows": [], "evidence": [], "issue_ledger": [],
        "review": {"issues": []}, "coverage": 1.0,
    }
    expected_hash = hashlib.sha256("实际返修来源".encode("utf-8")).hexdigest()

    async def full_review(*args, **kwargs):
        return {"score": 80}, {"review_mode": "full", "windows": []}

    monkeypatch.setattr(service, "_full_manuscript_review", full_review)

    _review, audit = await service._incremental_manuscript_review(
        "run", project.path / "runs" / "run", project, "constraints",
        "当前稿", {"windows": []}, baseline, {"issues": []},
        revision_source_hash=expected_hash, patch_groups=(),
    )

    assert audit["review_mode"] == "full_fallback"
    assert audit["fallback_reasons"] == ["baseline_source_mismatch"]


@pytest.mark.asyncio
async def test_v2_conditional_pass_remains_candidate_instead_of_formal_success(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Conditional V2", mode="short", genre="suspense",
        premise="A candidate needs one more repair.", target_words=8000,
    ))
    project = store.apply_platform_profile(project.id, "zhihu-salt-short")
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "正文" * 3600
    conditional = score_review({
        "dimensions": {"commercial": 79, "story": 75, "prose": 68},
        "hard_fail": False, "decision": "revise", "issues": [],
        "judge_signature": "provider/final-model",
    }, "zhihu-short-v2")

    async def polish(*args, **kwargs):
        return candidate

    async def reader(*args, **kwargs):
        return conditional

    async def final_review(*args, **kwargs):
        return conditional, {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 2, "window_count": 2,
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0, "windows": [], "nlp": {"available": True},
        "prose": {"blocking_count": 0}, "text_hash": hashlib.sha256(
            candidate.encode("utf-8")
        ).hexdigest(),
    })

    with pytest.raises(RuntimeError, match="quality gate"):
        await service._quality_polish(
            run_id, run_path, project, "constraints", candidate, conditional,
        )

    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    checkpoint = load_quality_checkpoint(run_path)
    assert report["status"] == "conditional_pass"
    assert checkpoint is not None
    assert checkpoint["outcome"] == "conditional_pass"


def _short_revision_service(
    tmp_path, issues, *, source=None, target_words=None,
    platform_profile_id=None,
):
    if source is None:
        filler = (
            "雨落在旧城的石阶上，林晚握着钥匙走进档案馆。"
            "值班员核对了登记簿，她沿着昏暗走廊寻找那份证词。"
            "窗外的钟声敲过三次，纸页上的墨迹仍然清晰。"
            "她把每个时间点重新排好，确认门锁和证物都没有变化。"
        ) * 9
        source = (
            filler + "林 晚核对记录，值 班员没有离开。"
            + "甲问题原句。" + filler + "乙问题原句。" + filler
        )
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Targeted repair", mode="short", genre="suspense",
        premise="Two independent local issues.",
        target_words=(
            effective_han_characters(source)
            if target_words is None else target_words
        ),
    ))
    if platform_profile_id is not None:
        project = store.apply_platform_profile(
            project.id, platform_profile_id,
        )
    state = StoryStateStore(db).ensure(project.id, project.path)
    gateway = FakeGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([])))
    quality_run = "quality-source"
    db.create_run(quality_run, project.id, "short-story", status="completed")
    quality_path = project.path / "runs" / quality_run
    outputs = quality_path / "outputs"
    outputs.mkdir(parents=True)
    best_path = outputs / "best-candidate.md"
    best_path.write_text(source, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    ledger = issue_ledger(issues)
    review = {
        "score": 82,
        "dimensions": {"commercial": 82, "story": 82, "prose": 82},
        "decision": "revise",
        "hard_fail": False,
        "issues": ledger,
    }
    write_quality_checkpoint(quality_path, {
        "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": digest,
        "score": 82,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
        "best_attempt": 1,
        "review": review,
        "issue_ledger": ledger,
        "outcome": "conditional_pass",
        "terminal_reviewed_hash": digest,
    })
    formal = project.path / "manuscript" / "story.md"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text("正式稿不得修改。", encoding="utf-8")
    return service, project, source, ledger, state


def _short_revision_patch(request, old_text, new_text):
    return json.dumps({
        "manuscript_hash": request["candidate_hash"],
        "groups": [{
            "group_id": request["group_id"],
            "issue_ids": [request["issue"]["issue_id"]],
            "kind": "semantic",
            "requires_user_confirmation": True,
            "patches": [{
                "operation": "replace",
                "old_text": old_text,
                "new_text": new_text,
            }],
        }],
    }, ensure_ascii=False)


@pytest.mark.asyncio
async def test_length_deficit_routes_to_draft_scene_patch_and_full_review(
    tmp_path, monkeypatch,
) -> None:
    sentence = "林晚沿走廊核对证词，确认时间和证物来源。"
    anchor = "档案员合上记录簿。"
    source = sentence * 388 + "值班记录仍然清楚。" + anchor
    scene = sentence * 111 + "线索。"
    assert effective_han_characters(source) == 7000
    assert effective_han_characters(scene) == 2000
    service, project, protected, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "length",
            "severity": "high",
            "evidence": anchor,
            "action": "补足平台最低有效汉字数。",
        }],
        source=source,
        target_words=10_000,
        platform_profile_id="zhihu-salt-short",
    )
    causal_chain = {
        "core_goal": "确认值班记录来源",
        "cycles": [{"result": "第一次核验受阻"}],
    }
    learning = LearningSystem(
        service.db, None, service.projects, service.gateway,
    )
    learning.save_artifact(
        project.id, "short_causal_chain", causal_chain,
    )
    issue_id = ledger[0]["issue_id"]
    calls = []
    plan = {
        "purpose": "增加证据核验受阻与人物选择代价",
        "target_han": 2000,
        "entry_state": "林晚拿到值班记录但尚未确认来源",
        "exit_state": "林晚确认记录来源并决定继续追查",
        "anchor": anchor,
        "operation": "insert_after",
        "requires_full_review": True,
        "time": "当夜",
        "evidence_source": "值班记录",
        "transition": "档案员离开后，林晚继续核验记录",
        "new_facts": [],
    }

    async def stage(*args, **kwargs):
        stage_name = args[3]
        request = json.loads(args[5])
        calls.append(stage_name)
        if stage_name == "revision_plan":
            assert request["current_han"] == 7000
            assert request["minimum_han"] == 9000
            assert request["deficit_han"] == 2000
            assert request["seven_step_causal_chain"] == causal_chain
            learning.save_artifact(
                project.id, "short_causal_chain",
                {"core_goal": "运行中被修改，不应进入冻结合同"},
            )
            return json.dumps({"scenes": [plan]}, ensure_ascii=False)
        if stage_name == "draft":
            assert request["seven_step_causal_chain"] == causal_chain
            return json.dumps({
                "text": scene,
                "entry_state": plan["entry_state"],
                "exit_state": plan["exit_state"],
                "time": plan["time"],
                "evidence_source": plan["evidence_source"],
                "transition": plan["transition"],
                "new_facts": plan["new_facts"],
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected stage: {stage_name}")

    quality_output = (
        project.path / "runs" / "quality-source" / "outputs"
    )
    best_path = quality_output / "best-candidate.md"
    quality_checkpoint = quality_output / "quality-checkpoint.json"
    formal_path = project.path / "manuscript" / "story.md"
    best_before = best_path.read_bytes()
    checkpoint_before = quality_checkpoint.read_bytes()
    formal_before = formal_path.read_bytes()
    monkeypatch.setattr(service, "_stage", stage)

    result = await service.run_short_revision(
        project.id, [issue_id], run_id="expand-length",
    )

    report = json.loads((
        project.path / "runs" / "expand-length"
        / "outputs" / "repair-report.json"
    ).read_text(encoding="utf-8"))
    assert calls[:2] == ["revision_plan", "draft"]
    assert "polish" not in calls
    assert "final_review" not in calls
    assert result["status"] == "waiting_confirmation"
    assert effective_han_characters(result["candidate"]) == 9000
    assert report["review_mode"] == "full"
    assert "scene_inserted" in report["full_review_reasons"]
    assert best_path.read_bytes() == best_before
    assert quality_checkpoint.read_bytes() == checkpoint_before
    assert formal_path.read_bytes() == formal_before
    assert protected == source


def _expansion_test_source(*, two_anchors: bool = False) -> tuple[str, list[str]]:
    sentence = "林晚沿走廊核对证词，确认时间和证物来源。"
    anchors = ["档案员合上记录簿。"]
    if two_anchors:
        anchors.append("管理员锁好侧门。")
        source = sentence * 388 + "夜。" + "".join(anchors)
    else:
        source = sentence * 388 + "值班记录仍然清楚。" + anchors[0]
    assert effective_han_characters(source) == 7000
    return source, anchors


def _expansion_scene_text(target_han: int) -> str:
    sentence = "林晚沿走廊核对证词，确认时间和证物来源。"
    count, remainder = divmod(target_han, 18)
    text = sentence * count + "线" * remainder + "。"
    assert effective_han_characters(text) == target_han
    return text


def _expansion_plan(anchor: str, target_han: int = 2000) -> dict:
    return {
        "purpose": "增加证据核验受阻与人物选择代价",
        "target_han": target_han,
        "entry_state": "林晚拿到值班记录但尚未确认来源",
        "exit_state": "林晚确认记录来源并决定继续追查",
        "anchor": anchor,
        "operation": "insert_after",
        "requires_full_review": True,
        "time": "当夜",
        "evidence_source": "值班记录",
        "transition": "档案员离开后，林晚继续核验记录",
        "new_facts": [],
    }


def _expansion_draft(plan: dict, text: str) -> dict:
    return {
        "text": text,
        "entry_state": plan["entry_state"],
        "exit_state": plan["exit_state"],
        "time": plan["time"],
        "evidence_source": plan["evidence_source"],
        "transition": plan["transition"],
        "new_facts": plan["new_facts"],
    }


def _expansion_service(tmp_path, *, two_anchors: bool = False):
    source, anchors = _expansion_test_source(two_anchors=two_anchors)
    service, project, protected, ledger, state = _short_revision_service(
        tmp_path, [{
            "category": "length",
            "severity": "high",
            "evidence": anchors[0],
            "action": "补足平台最低有效汉字数。",
        }],
        source=source,
        target_words=10_000,
        platform_profile_id="zhihu-salt-short",
    )
    return service, project, protected, ledger, state, anchors


def test_expansion_anchor_catalogue_is_bounded_unique_and_distributed() -> None:
    candidate = "".join(
        f"第{index:02d}处线索由不同证人核实，时间记录完整。"
        for index in range(60)
    )

    catalogue = WorkflowService._expansion_anchor_candidates(candidate)

    assert 3 <= len(catalogue) <= 24
    positions = [item["position"] for item in catalogue]
    assert positions == sorted(positions)
    assert positions[0] < len(candidate) * 0.1
    assert any(
        len(candidate) * 0.4 <= position <= len(candidate) * 0.6
        for position in positions
    )
    assert positions[-1] > len(candidate) * 0.9
    for item in catalogue:
        anchor = item["anchor"]
        position = item["position"]
        assert candidate.count(anchor) == 1
        assert candidate[position:position + len(anchor)] == anchor
        assert item["preview"] in candidate
        assert len(item["preview"]) <= 160


@pytest.mark.parametrize("invalid_case", [
    "missing_purpose",
    "missing_entry_state",
    "missing_exit_state",
    "missing_anchor",
    "duplicate_anchor",
    "uncatalogued_anchor",
    "object_new_fact",
    "blank_new_fact",
    "zero_target",
    "changed_total",
])
@pytest.mark.asyncio
async def test_expansion_plan_contract_rejection_stays_local(
    tmp_path, monkeypatch, invalid_case,
) -> None:
    service, project, _source, ledger, _state, anchors = _expansion_service(
        tmp_path,
    )
    plan = _expansion_plan(anchors[0])
    scenes = [plan]
    if invalid_case.startswith("missing_"):
        plan.pop(invalid_case.removeprefix("missing_"))
    elif invalid_case == "duplicate_anchor":
        plan["target_han"] = 1000
        scenes = [plan, dict(plan)]
    elif invalid_case == "uncatalogued_anchor":
        plan["anchor"] = "清楚。档案员"
    elif invalid_case == "object_new_fact":
        plan["new_facts"] = [{"fact": "门锁未被破坏"}]
    elif invalid_case == "blank_new_fact":
        plan["new_facts"] = ["   "]
    elif invalid_case == "zero_target":
        plan["target_han"] = 0
    elif invalid_case == "changed_total":
        plan["target_han"] = 1999
    calls = []

    async def stage(*args, **kwargs):
        calls.append(args[3])
        return json.dumps({"scenes": scenes}, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]],
        run_id=f"expand-invalid-{invalid_case}",
    )

    group = result["groups"][ledger[0]["issue_id"]]
    assert calls == ["revision_plan"]
    assert result["status"] == "waiting_local_fix"
    assert group["status"] == "rejected"
    assert group["failures"] == [{
        "patch": 0,
        "code": "expansion_contract_rejected",
    }]
    assert "final_review" not in calls


@pytest.mark.parametrize("invalid_case", [
    "too_short",
    "too_long",
    "state_mismatch",
])
@pytest.mark.asyncio
async def test_expansion_draft_rejection_stays_local_without_final_review(
    tmp_path, monkeypatch, invalid_case,
) -> None:
    service, project, _source, ledger, _state, anchors = _expansion_service(
        tmp_path,
    )
    plan = _expansion_plan(anchors[0])
    target = {
        "too_short": 1999,
        "too_long": 2201,
        "state_mismatch": 2000,
    }[invalid_case]
    draft = _expansion_draft(plan, _expansion_scene_text(target))
    if invalid_case == "state_mismatch":
        draft["exit_state"] = "人物状态与规划不一致"
    calls = []

    async def stage(*args, **kwargs):
        calls.append(args[3])
        if args[3] == "revision_plan":
            return json.dumps({"scenes": [plan]}, ensure_ascii=False)
        return json.dumps(draft, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]],
        run_id=f"expand-draft-{invalid_case}",
    )

    group = result["groups"][ledger[0]["issue_id"]]
    assert calls == ["revision_plan", "draft"]
    assert result["status"] == "waiting_local_fix"
    assert group["status"] == "rejected"
    assert group["failures"] == [{
        "patch": 0,
        "code": "expansion_draft_rejected",
    }]
    assert "final_review" not in calls


@pytest.mark.asyncio
async def test_non_length_issue_below_minimum_does_not_route_to_draft(
    tmp_path, monkeypatch,
) -> None:
    source, anchors = _expansion_test_source()
    service, project, _protected, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": anchors[0],
            "action": "澄清档案员为何离开。",
        }],
        source=source,
        target_words=10_000,
        platform_profile_id="zhihu-salt-short",
    )
    calls = []

    async def stage(*args, **kwargs):
        calls.append(args[3])
        request = json.loads(args[5])
        return _short_revision_patch(
            request, anchors[0], "档案员确认记录后合上簿册。",
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]],
        run_id="expand-non-length",
    )

    assert calls == ["revision_plan"]
    assert "draft" not in calls
    assert result["status"] == "waiting_local_fix"


@pytest.mark.asyncio
async def test_expansion_multiple_scenes_use_exact_local_deficit_and_unique_anchors(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state, anchors = _expansion_service(
        tmp_path, two_anchors=True,
    )
    planned_scenes = []
    calls = []

    async def stage(*args, **kwargs):
        request = json.loads(args[5])
        calls.append((args[3], request.get("scene_index")))
        if args[3] == "revision_plan":
            assert "anchor_candidates" in request
            selected = [
                item["anchor"] for item in request["anchor_candidates"][-2:]
            ]
            planned_scenes.extend([
                _expansion_plan(selected[0], 700),
                _expansion_plan(selected[1], 1300),
            ])
            planned_scenes[0]["new_facts"] = ["  档案门锁未被破坏  "]
            return json.dumps(
                {"scenes": planned_scenes}, ensure_ascii=False,
            )
        plan = request["contract"]
        return json.dumps(
            _expansion_draft(
                plan, _expansion_scene_text(plan["target_han"]),
            ),
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]],
        run_id="expand-multiple",
    )

    records = json.loads((
        project.path / "runs" / "expand-multiple"
        / "outputs" / "patch-groups.json"
    ).read_text(encoding="utf-8"))["groups"]
    contracts = records[0]["patch_group"]["expansion_contracts"]
    assert calls == [
        ("revision_plan", None), ("draft", 1), ("draft", 2),
    ]
    assert sum(item["target_han"] for item in contracts) == 2000
    assert len({item["anchor"] for item in contracts}) == 2
    assert [item["anchor"] for item in contracts] == anchors
    assert contracts[0]["new_facts"] == ["档案门锁未被破坏"]
    assert effective_han_characters(result["candidate"]) == 9000
    assert result["status"] == "waiting_confirmation"


@pytest.mark.parametrize("failure_kind", ["provider", "cancel"])
@pytest.mark.asyncio
async def test_expansion_resume_retries_only_unfinished_scene(
    tmp_path, monkeypatch, failure_kind,
) -> None:
    service, project, _source, ledger, _state, anchors = _expansion_service(
        tmp_path, two_anchors=True,
    )
    plans = [
        _expansion_plan(anchors[0], 1000),
        _expansion_plan(anchors[1], 1000),
    ]
    first_calls = []

    async def interrupted_stage(*args, **kwargs):
        request = json.loads(args[5])
        first_calls.append((args[3], request.get("scene_index")))
        if args[3] == "revision_plan":
            return json.dumps({"scenes": plans}, ensure_ascii=False)
        if request["scene_index"] == 1:
            return json.dumps(
                _expansion_draft(plans[0], _expansion_scene_text(1000)),
                ensure_ascii=False,
            )
        if failure_kind == "provider":
            raise TargetedGroupError("provider unavailable")
        raise asyncio.CancelledError

    run_id = f"expand-resume-{failure_kind}"
    monkeypatch.setattr(service, "_stage", interrupted_stage)
    if failure_kind == "provider":
        with pytest.raises(RuntimeError, match="返修组"):
            await service.run_short_revision(
                project.id, [ledger[0]["issue_id"]], run_id=run_id,
            )
    else:
        with pytest.raises(asyncio.CancelledError):
            await service.run_short_revision(
                project.id, [ledger[0]["issue_id"]], run_id=run_id,
            )
    records = json.loads((
        project.path / "runs" / run_id / "outputs" / "patch-groups.json"
    ).read_text(encoding="utf-8"))["groups"]
    assert records[0]["expansion_plan"][0]["status"] == "drafted"

    resumed_calls = []

    async def resume_stage(*args, **kwargs):
        request = json.loads(args[5])
        resumed_calls.append((args[3], request.get("scene_index")))
        if args[3] == "revision_plan" or request.get("scene_index") != 2:
            raise AssertionError("completed expansion work was repeated")
        return json.dumps(
            _expansion_draft(plans[1], _expansion_scene_text(1000)),
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_stage", resume_stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]], run_id=run_id,
    )

    assert first_calls == [
        ("revision_plan", None), ("draft", 1), ("draft", 2),
    ]
    assert resumed_calls == [("draft", 2)]
    assert result["status"] == "waiting_confirmation"


@pytest.mark.asyncio
async def test_short_revision_writes_contract_before_model_and_waits_without_final_review(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, state = _short_revision_service(tmp_path, [{
        "category": "logic_continuity",
        "severity": "medium",
        "evidence": "甲问题原句。",
        "action": "把甲问题改成清楚的证据说明",
    }])
    issue_id = ledger[0]["issue_id"]
    calls = []
    contract_bytes = None

    async def stage(*args, **kwargs):
        nonlocal contract_bytes
        stage_name, prompt = args[3], args[5]
        calls.append(stage_name)
        contract_path = (
            project.path / "runs" / "repair-contract-first"
            / "outputs" / "repair-contract.json"
        )
        assert contract_path.is_file()
        contract_bytes = contract_path.read_bytes()
        request = json.loads(prompt)
        return _short_revision_patch(
            request, "甲问题原句。", "甲问题说明。",
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-contract-first",
    )

    contract_path = (
        project.path / "runs" / result["id"] / "outputs" / "repair-contract.json"
    )
    assert result["status"] == "waiting_confirmation"
    assert calls == ["revision_plan"]
    assert "final_review" not in calls
    assert contract_path.read_bytes() == contract_bytes
    output = contract_path.parent
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    groups = json.loads((output / "patch-groups.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((output / "repair-checkpoint.json").read_text(
        encoding="utf-8",
    ))
    candidate = (output / "candidate.md").read_text(encoding="utf-8")
    assert checkpoint["contract_hash"] == repair_artifact_hash(contract)
    assert checkpoint["groups_hash"] == repair_artifact_hash(groups)
    assert checkpoint["candidate_hash"] == repair_artifact_hash(candidate)
    assert (project.path / "runs" / "quality-source" / "outputs"
            / "best-candidate.md").read_text(encoding="utf-8") == source
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == "正式稿不得修改。"
    assert StoryStateStore(service.db).get(project.id) == state


@pytest.mark.asyncio
async def test_short_revision_preserves_later_group_and_resumes_only_failed_group(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(tmp_path, [
        {
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "甲问题原句。",
            "action": "修复甲问题",
        },
        {
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "乙问题原句。",
            "action": "修复乙问题",
        },
    ])
    issue_by_evidence = {item["evidence"]: item["issue_id"] for item in ledger}
    issue_a = issue_by_evidence["甲问题原句。"]
    issue_b = issue_by_evidence["乙问题原句。"]
    first_calls = []

    async def fail_a_once(*args, **kwargs):
        request = json.loads(args[5])
        issue_id = request["issue"]["issue_id"]
        first_calls.append(issue_id)
        if issue_id == issue_a:
            raise TargetedGroupError("provider unavailable")
        return _short_revision_patch(
            request, "乙问题原句。", "乙问题说明。",
        )

    monkeypatch.setattr(service, "_stage", fail_a_once)
    with pytest.raises(RuntimeError, match="返修组"):
        await service.run_short_revision(
            project.id, [issue_a, issue_b], run_id="repair-resume",
        )

    output = project.path / "runs" / "repair-resume" / "outputs"
    checkpoint = json.loads((output / "repair-checkpoint.json").read_text(
        encoding="utf-8",
    ))
    groups = json.loads((output / "patch-groups.json").read_text(
        encoding="utf-8",
    ))
    candidate = (output / "candidate.md").read_text(encoding="utf-8")
    failed_group = next(
        item for item in groups["groups"] if item["group_id"] == issue_a
    )
    provider_event = next(
        item for item in service.db.list_run_events("repair-resume")
        if item["event_type"] == "short_revision_group_failed"
    )
    assert first_calls == [issue_a, issue_b]
    assert checkpoint["completed_groups"] == [issue_b]
    assert failed_group["patch_result"]["failures"] == [{
        "patch": 0,
        "code": "model_routes_failed",
    }]
    assert provider_event["metadata"] == {"group_id": issue_a}
    assert "provider unavailable" not in failed_group["message"]
    assert "provider unavailable" not in provider_event["message"]
    assert "乙问题说明。" in candidate
    assert service.db.get_run("repair-resume")["status"] == "failed"
    assert "completed" not in {
        item["event_type"] for item in service.db.list_run_events("repair-resume")
    }

    resumed_calls = []

    async def resume_a(*args, **kwargs):
        request = json.loads(args[5])
        issue_id = request["issue"]["issue_id"]
        resumed_calls.append(issue_id)
        assert issue_id == issue_a
        return _short_revision_patch(
            request, "甲问题原句。", "甲问题说明。",
        )

    monkeypatch.setattr(service, "_stage", resume_a)
    result = await service.run_short_revision(
        project.id, [issue_b, issue_a], run_id="repair-resume",
    )

    assert resumed_calls == [issue_a]
    assert result["status"] == "waiting_confirmation"
    assert "甲问题说明。" in result["candidate"]
    assert "乙问题说明。" in result["candidate"]


@pytest.mark.asyncio
async def test_short_revision_rejects_issue_ledger_not_bound_to_terminal_review_before_model(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(tmp_path, [{
        "category": "logic_continuity",
        "severity": "medium",
        "evidence": "甲问题原句。",
        "action": "修复甲问题",
    }])
    issue_id = ledger[0]["issue_id"]
    quality_path = project.path / "runs" / "quality-source"
    checkpoint = load_quality_checkpoint(quality_path)
    checkpoint["review"] = {
        **checkpoint["review"],
        "issues": issue_ledger([{
            "category": "style",
            "severity": "low",
            "evidence": "另一项问题。",
            "action": "处理另一项问题",
        }]),
    }
    write_quality_checkpoint(quality_path, checkpoint)
    calls = []

    async def forbidden_stage(*args, **kwargs):
        calls.append(args[3])
        raise AssertionError("model call must not happen")

    monkeypatch.setattr(service, "_stage", forbidden_stage)
    with pytest.raises(ValueError, match="终审"):
        await service.run_short_revision(
            project.id, [issue_id], run_id="repair-ledger-mismatch",
        )

    assert calls == []


@pytest.mark.asyncio
async def test_short_revision_rejects_invalid_selection_and_mode_before_model(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [],
    )
    calls = []

    async def forbidden_stage(*args, **kwargs):
        calls.append(args[3])
        raise AssertionError("model call must not happen")

    monkeypatch.setattr(service, "_stage", forbidden_stage)
    with pytest.raises(ValueError, match="至少选择"):
        await service.run_short_revision(project.id, [], run_id="repair-empty")
    with pytest.raises(ValueError, match="所选问题"):
        await service.run_short_revision(
            project.id, ["missing-issue"], run_id="repair-unknown",
        )
    long_project = service.projects.create(ProjectCreate(
        title="Long repair", mode="long", genre="suspense",
        premise="Long projects are not in this workflow.", target_words=1000,
    ))
    with pytest.raises(ValueError, match="只支持短篇"):
        await service.run_short_revision(
            long_project.id, ["missing-issue"], run_id="repair-long",
        )

    assert calls == []


@pytest.mark.asyncio
async def test_short_revision_failed_gate_makes_zero_final_review_calls(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, _state = _short_revision_service(tmp_path, [{
        "category": "logic_continuity",
        "severity": "medium",
        "evidence": "甲问题原句。",
        "action": "必须删除甲问题原句",
        "forbidden_text": ["甲问题原句。"],
    }])
    issue_id = ledger[0]["issue_id"]
    calls = []

    async def stage(*args, **kwargs):
        calls.append(args[3])
        request = json.loads(args[5])
        return _short_revision_patch(
            request, "乙问题原句。", "乙问题说明。",
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-gate-fail",
    )

    assert result["status"] == "waiting_local_fix"
    assert calls == ["revision_plan"]
    assert "final_review" not in calls
    assert result["gate"]["passed"] is False
    assert "甲问题原句。" in result["candidate"]
    assert (project.path / "runs" / "quality-source" / "outputs"
            / "best-candidate.md").read_text(encoding="utf-8") == source


@pytest.mark.asyncio
async def test_short_revision_mechanical_group_changes_only_selected_evidence(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "cjk_spacing",
            "severity": "low",
            "evidence": "林 晚",
            "action": "删除姓名中的多余空格",
        }],
    )
    calls = []

    async def forbidden_stage(*args, **kwargs):
        calls.append(args[3])
        raise AssertionError("mechanical repair must stay local")

    monkeypatch.setattr(service, "_stage", forbidden_stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]], run_id="repair-mechanical",
    )

    assert result["status"] == "waiting_confirmation"
    assert calls == []
    assert "林晚核对记录" in result["candidate"]
    assert "值 班员没有离开" in result["candidate"]


@pytest.mark.asyncio
async def test_short_revision_resume_rejects_stale_protected_best_before_model(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, _state = _short_revision_service(tmp_path, [{
        "category": "logic_continuity",
        "severity": "medium",
        "evidence": "甲问题原句。",
        "action": "修复甲问题",
    }])
    issue_id = ledger[0]["issue_id"]

    async def fail_stage(*args, **kwargs):
        raise TargetedGroupError("provider unavailable")

    monkeypatch.setattr(service, "_stage", fail_stage)
    with pytest.raises(RuntimeError, match="返修组"):
        await service.run_short_revision(
            project.id, [issue_id], run_id="repair-stale",
        )
    best = (
        project.path / "runs" / "quality-source"
        / "outputs" / "best-candidate.md"
    )
    best.write_text(source + "最佳稿已经变化。", encoding="utf-8")
    resume_calls = []

    async def forbidden_stage(*args, **kwargs):
        resume_calls.append(args[3])
        raise AssertionError("stale resume must not call a model")

    monkeypatch.setattr(service, "_stage", forbidden_stage)
    with pytest.raises(ValueError, match="受保护最佳稿"):
        await service.run_short_revision(
            project.id, [issue_id], run_id="repair-stale",
        )

    assert resume_calls == []


@pytest.mark.asyncio
async def test_short_revision_cancellation_keeps_completed_group_and_resumes_same_run(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(tmp_path, [
        {
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "甲问题原句。",
            "action": "修复甲问题",
        },
        {
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "乙问题原句。",
            "action": "修复乙问题",
        },
    ])
    issue_by_evidence = {item["evidence"]: item["issue_id"] for item in ledger}
    issue_a = issue_by_evidence["甲问题原句。"]
    issue_b = issue_by_evidence["乙问题原句。"]

    async def cancel_b(*args, **kwargs):
        request = json.loads(args[5])
        if request["group_id"] == issue_b:
            raise asyncio.CancelledError
        return _short_revision_patch(
            request, "甲问题原句。", "甲问题说明。",
        )

    monkeypatch.setattr(service, "_stage", cancel_b)
    with pytest.raises(asyncio.CancelledError):
        await service.run_short_revision(
            project.id, [issue_a, issue_b], run_id="repair-cancel",
        )
    output = project.path / "runs" / "repair-cancel" / "outputs"
    checkpoint = json.loads((output / "repair-checkpoint.json").read_text(
        encoding="utf-8",
    ))
    assert checkpoint["completed_groups"] == [issue_a]
    assert service.db.get_run("repair-cancel")["status"] == "cancelled"
    assert "甲问题说明。" in (output / "candidate.md").read_text(encoding="utf-8")
    resumed_calls = []

    async def finish_b(*args, **kwargs):
        request = json.loads(args[5])
        resumed_calls.append(request["group_id"])
        return _short_revision_patch(
            request, "乙问题原句。", "乙问题说明。",
        )

    monkeypatch.setattr(service, "_stage", finish_b)
    result = await service.run_short_revision(
        project.id, [issue_a, issue_b], run_id="repair-cancel",
    )

    assert resumed_calls == [issue_b]
    assert result["status"] == "waiting_confirmation"


@pytest.mark.asyncio
async def test_short_revision_checkpoint_failure_cannot_authorize_new_progress(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, state = _short_revision_service(tmp_path, [{
        "category": "logic_continuity",
        "severity": "medium",
        "evidence": "甲问题原句。",
        "action": "修复甲问题",
    }])
    issue_id = ledger[0]["issue_id"]

    async def stage(*args, **kwargs):
        request = json.loads(args[5])
        return _short_revision_patch(
            request, "甲问题原句。", "甲问题说明。",
        )

    original = RepairRunStore.write_checkpoint
    writes = 0

    def fail_second_checkpoint(store, value):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        return original(store, value)

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(RepairRunStore, "write_checkpoint", fail_second_checkpoint)
    with pytest.raises(OSError, match="disk full"):
        await service.run_short_revision(
            project.id, [issue_id], run_id="repair-checkpoint-fail",
        )

    run_path = project.path / "runs" / "repair-checkpoint-fail"
    with pytest.raises(ValueError):
        RepairRunStore(run_path).load_resume_state(
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )
    assert (project.path / "runs" / "quality-source" / "outputs"
            / "best-candidate.md").read_text(encoding="utf-8") == source
    assert StoryStateStore(service.db).get(project.id) == state


@pytest.mark.parametrize("model_output", [
    "not-json",
    json.dumps({"groups": []}),
])
@pytest.mark.asyncio
async def test_short_revision_marks_invalid_model_contract_as_local_rejection(
    tmp_path, monkeypatch, model_output,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "甲问题原句。",
            "action": "修复甲问题。",
        }],
    )
    issue_id = ledger[0]["issue_id"]

    async def invalid_contract(*args, **kwargs):
        return model_output

    monkeypatch.setattr(service, "_stage", invalid_contract)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id=f"repair-rejected-{len(model_output)}",
    )

    group = result["groups"][issue_id]
    events = service.db.list_run_events(result["id"])
    event_types = {item["event_type"] for item in events}
    rejected_event = next(
        item for item in events
        if item["event_type"] == "short_revision_group_rejected"
    )
    assert result["status"] == "waiting_local_fix"
    assert group["status"] == "rejected"
    assert group["message"] == "模型返回的修改格式未通过本地验收，当前修改组未应用"
    assert group["failures"] == [{
        "patch": 0,
        "code": "repair_contract_rejected",
    }]
    assert rejected_event["metadata"] == {
        "group_id": issue_id,
        "category": "contract_validation",
    }
    assert model_output not in rejected_event["message"]
    assert "short_revision_group_rejected" in event_types
    assert "short_revision_group_failed" not in event_types


@pytest.mark.asyncio
async def test_short_revision_propagates_unexpected_local_group_error(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [
            {
                "category": "logic_continuity",
                "severity": "medium",
                "evidence": "甲问题原句。",
                "action": "修复甲问题。",
            },
            {
                "category": "logic_continuity",
                "severity": "medium",
                "evidence": "乙问题原句。",
                "action": "修复乙问题。",
            },
        ],
    )
    calls = []

    async def valid_contract(*args, **kwargs):
        request = json.loads(args[5])
        calls.append(request["group_id"])
        return _short_revision_patch(
            request, request["target_excerpt"], "已修复的候选句。",
        )

    def explode_locally(*args, **kwargs):
        raise OSError("local validation exploded")

    monkeypatch.setattr(service, "_stage", valid_contract)
    monkeypatch.setattr(
        "novel_flywheel.workflows.normalize_repair_contract",
        explode_locally,
    )
    with pytest.raises(OSError, match="local validation exploded"):
        await service.run_short_revision(
            project.id,
            [item["issue_id"] for item in ledger],
            run_id="repair-local-error",
        )

    report = json.loads((
        project.path / "runs" / "repair-local-error"
        / "outputs" / "repair-report.json"
    ).read_text(encoding="utf-8"))
    events = service.db.list_run_events("repair-local-error")
    assert calls == [ledger[0]["issue_id"]]
    assert service.db.get_run("repair-local-error")["status"] == "failed"
    assert report["status"] == "failed"
    assert report["groups"][ledger[0]["issue_id"]]["message"] == (
        "当前修改组发生意外错误，运行已停止并保留安全检查点"
    )
    assert "short_revision_group_error" in {
        item["event_type"] for item in events
    }
    assert "short_revision_group_failed" not in {
        item["event_type"] for item in events
    }
    error_event = next(
        item for item in events
        if item["event_type"] == "short_revision_group_error"
    )
    assert error_event["metadata"] == {
        "group_id": ledger[0]["issue_id"],
        "category": "unexpected_local_error",
    }


@pytest.mark.asyncio
async def test_short_revision_reports_atomic_patch_rejection_separately(
    tmp_path, monkeypatch,
) -> None:
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "甲问题原句。",
            "action": "修复甲问题。",
        }],
    )
    issue_id = ledger[0]["issue_id"]

    async def valid_contract(*args, **kwargs):
        request = json.loads(args[5])
        return _short_revision_patch(
            request, request["target_excerpt"], "已修复的候选句。",
        )

    def reject_patch(manuscript, group, source_hash):
        return {
            "accepted": False,
            "text": manuscript,
            "failures": [{"patch": 1, "code": "old_text_not_unique"}],
            "diffs": [],
        }

    monkeypatch.setattr(service, "_stage", valid_contract)
    monkeypatch.setattr(
        "novel_flywheel.workflows.apply_patch_group",
        reject_patch,
    )
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-patch-rejected",
    )

    group = result["groups"][issue_id]
    rejected = [
        item for item in service.db.list_run_events(result["id"])
        if item["event_type"] == "short_revision_group_rejected"
    ]
    assert result["status"] == "waiting_local_fix"
    assert group["status"] == "rejected"
    assert group["message"] == "修改锚点未通过本地验收，当前修改组未应用"
    assert group["failures"] == [{
        "patch": 1,
        "code": "old_text_not_unique",
    }]
    assert rejected[-1]["metadata"] == {
        "group_id": issue_id,
        "category": "patch_validation",
    }
