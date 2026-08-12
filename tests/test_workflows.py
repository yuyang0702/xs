import asyncio
import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from novel_flywheel.db import Database
from novel_flywheel.context_policy import (
    build_polish_authority_packet,
    classify_model_failure,
    classify_input_pressure,
)
from novel_flywheel.execution_manifest import (
    bind_previous_exit_hashes,
    execution_manifest_payload,
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.execution_authority import canonical_sha256
from novel_flywheel.learning import LearningSystem
from novel_flywheel.legacy_short_promotion import (
    recover_legacy_short_formal_promotions,
)
from novel_flywheel.material_audit_authority import (
    build_material_audit_packets,
    build_material_reference_authority,
)
from novel_flywheel.models import (
    ModelResult,
    ModelRoutesExhaustedError,
    TransportInterruptedError,
)
from novel_flywheel.narrative_ledger import build_narrative_ledger
from novel_flywheel.outlines import narrative_outline_event_contracts, outline_events
from novel_flywheel.planning_adaptation import (
    INVARIANT_FIELDS,
    planning_adaptation_evidence_candidates,
    planning_adaptation_segment_authority_sha256,
    planning_adaptation_whole_authority_sha256,
    planning_event_body_issues,
    planning_event_id_occurrences,
    remove_planning_event_ids,
)
from novel_flywheel.planning_compiler import (
    PLAN_FIELD_ALIASES,
    PlanningDocumentIR,
    PlanningSegmentIR,
    compile_planning_event_artifact,
    compile_planning_segment,
    compile_planning_segment_ir,
    render_planning_segment_ir,
)
from novel_flywheel.planning_recovery import (
    new_planning_recovery_state,
    planning_candidate_comparison,
    read_planning_recovery,
    record_planning_candidate,
    write_planning_recovery,
)
from novel_flywheel.planning_semantics import (
    planning_semantic_packet_ownership_v2,
)
from novel_flywheel.prompts import IMMUTABLE_RECEIPT_SYSTEM
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.quality import issue_ledger, review_windows
from novel_flywheel.quality_profiles import score_review
from novel_flywheel.quality_records import load_quality_checkpoint, write_quality_checkpoint
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash
from novel_flywheel.recovery_engine import protocol_receipt_attempts
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.revision import segment_map
from novel_flywheel.revision_operations import RevisionOperationError
from novel_flywheel.scene_continuity import LocationRef
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.workflows import (
    ContextCapacityPreflightError,
    DraftReceiptProtocolError,
    DraftSemanticValidationError,
    GeneratedArtifactShapeError,
    IncompleteModelOutputError,
    PolishTokenBudgetError,
    RevisionPlanError,
    StageText,
    TargetedGroupError,
    WorkflowService,
)
from novel_flywheel.draft_split import DraftTaskContract


REQUIRED_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
}


def planning_semantic_body_from_prompt(prompt: str) -> dict:
    """Build one schema-valid IR-first response from Runtime-visible authority."""

    match = re.search(r"Return exactly (\d+) contiguous segments", prompt)
    if match is None:
        raise AssertionError("planning semantic prompt did not declare segment count")
    segment_count = int(match.group(1))
    event_catalog = json.loads(
        prompt.split("FORMAL EVENT CATALOG:\n", 1)[1]
    )
    ownership = planning_semantic_packet_ownership_v2(
        segment_count=segment_count,
        formal_event_count=len(event_catalog),
    )
    segments = []
    for index, ordinals in enumerate(ownership, 1):
        segment = {
            "kind": (
                "terminal" if index == segment_count else "continuation"
            ),
            "segment": index,
            "title": f"Verified semantic segment {index}",
            "events": [{
                "formal_event_ordinal": ordinal,
                "narrative": (
                    f"The protagonist executes formal event {ordinal}, meets "
                    f"resistance, produces a causal result, and updates story state."
                ),
            } for ordinal in ordinals],
        }
        if index < segment_count:
            segment["exit_state"] = (
                f"Segment {index} leaves a verified state for its successor."
            )
        segments.append(segment)
    return {
        "version": 2,
        "initial_state": "The accepted story authority defines the opening state.",
        "segments": segments,
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


def test_workflow_analysis_cache_recomputes_when_reference_corpus_changes(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Corpus-bound analysis", mode="short", genre="suspense",
        premise="A reference changes.", target_words=1000,
    ))
    store.set_optimized_local_review(project.id, True)
    references = ReferenceLibrary(db, tmp_path / "references")
    source = references.import_text(
        title="Reference", text="门锁在雨夜被人更换。", source_type="paste",
        content_type="reference_work", project_id=project.id,
    )
    calls = []
    nlp = SimpleNamespace(analyze=lambda text: calls.append(text) or {
        "backend": "ltp", "backend_version": "ltp-v2", "available": True,
        "result": {"cws": [[]], "pos": [[]], "ner": [[]], "srl": [[]], "dep": [[]]},
    })
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
        local_nlp=nlp, references=references,
    )
    run_path = project.path / "runs" / "corpus-analysis"
    first = service._analyze_manuscript(
        "林晚发现门锁变了。", run_path, project, "draft",
    )
    reused = service._analyze_manuscript(
        "林晚发现门锁变了。", run_path, project, "draft",
    )
    references.add_version(source["id"], "门锁在清晨被人再次更换。")
    refreshed = service._analyze_manuscript(
        "林晚发现门锁变了。", run_path, project, "draft",
    )

    assert reused["reference_corpus_sha256"] == first["reference_corpus_sha256"]
    assert refreshed["reference_corpus_sha256"] != first["reference_corpus_sha256"]
    assert len(calls) == 2


def test_short_formal_promotion_rejects_stale_reference_corpus_authority(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Promotion corpus CAS", mode="short", genre="suspense",
        premise="A reference changes before promotion.", target_words=1000,
    ))
    references = ReferenceLibrary(db, tmp_path / "references")
    source = references.import_text(
        title="Reference", text="First reference version.", source_type="paste",
        content_type="reference_work", project_id=project.id,
    )
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
        references=references,
    )
    analyzed_corpus = references.reference_corpus_authority(project.id)["sha256"]

    assert service._assert_current_reference_corpus_authority(
        project, {"reference_corpus_sha256": analyzed_corpus},
    ) == analyzed_corpus

    references.add_version(source["id"], "Second reference version.")

    with pytest.raises(RuntimeError, match="Reference corpus changed"):
        service._assert_current_reference_corpus_authority(
            project, {"reference_corpus_sha256": analyzed_corpus},
        )


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
    assert event["metadata"]["failure_code"] == (
        "workflow.snapshot_restore_failed"
    )
    assert "Invalid argument" not in json.dumps(
        event["metadata"], ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_crewai_cleanup_error_does_not_mask_primary_workflow_error(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    from novel_flywheel.config import configure_runtime_environment

    configure_runtime_environment(db.path.parent, service.crewai_data_dir)
    from crewai.flow.flow import Flow

    async def cleanup_fails_after_pipeline(self):
        try:
            await self.execute()
        except ValueError:
            raise OSError(22, "Invalid argument")

    async def pipeline():
        raise ValueError("规划恢复尚未收敛，最佳候选和有效上游进度已保留")

    monkeypatch.setattr(Flow, "kickoff_async", cleanup_fails_after_pipeline)

    with pytest.raises(ValueError, match="规划恢复尚未收敛") as caught:
        await service._run_in_crewai(pipeline)

    assert isinstance(caught.value.__cause__, OSError)
    assert str(caught.value.__cause__) == "[Errno 22] Invalid argument"


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
            (
                "### 第 1 段：完成正式事件\n"
                "事件ID：EV-00000001\n"
                "大纲依据：主角完成当前正式目标并承担结果。\n"
                "段首承接：主角位于事件起点，当前关系与已知信息保持不变。\n"
                "本段事件：主角主动调查阻碍，作出选择并完成正式目标。\n"
                "段末交接：目标已经完成，代价与后续状态均已明确。"
            ),
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
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            # Discard the legacy planning fixture retained below for tests that
            # still exercise persisted Markdown migration directly.
            next(self.responses)
            return ModelResult(json.dumps({
                "version": 2,
                "initial_state": "The protagonist starts at the formal event boundary.",
                "segments": [{
                    "kind": "terminal", "segment": 1,
                    "title": "Complete the formal event",
                    "events": [{
                        "formal_event_ordinal": 1,
                        "narrative": (
                            "The protagonist actively investigates the obstacle, makes "
                            "the decisive choice, completes the formal goal, and accepts "
                            "the resulting cost without changing the confirmed ending."
                        ),
                    }],
                }],
            }), {"role": role, "model_name": f"fake-{role}"})
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return ModelResult(
                json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return ModelResult(
                execution_manifest_receipt_from_prompt(user),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return ModelResult(
                json.dumps(draft_semantic_receipt(contract, prose), ensure_ascii=False),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
            draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
            segments = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", user,
            ).group(1))
            events = json.loads(re.search(
                r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
            ).group(1))
            opening = user.split("OPENING EXCERPT: ", 1)[1].split(
                "\nENDING EXCERPT:", 1,
            )[0]
            ending = user.split("ENDING EXCERPT: ", 1)[1]
            return ModelResult(json.dumps({
                "authority_sha256": authority, "draft_sha256": draft_sha,
                "segment_sha256": segments, "event_ids": events,
                "missing_event_ids": [], "duplicate_event_ids": [],
                "out_of_order_event_ids": [], "causal_order_valid": True,
                "continuity_valid": True, "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"kind": "opening", "excerpt": opening[:12]},
                    {"kind": "ending", "excerpt": ending[-12:]},
                ],
                "summary": "全文节拍顺序、连续性和结局均已核对。",
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            covered_event_ids = list(dict.fromkeys(
                re.findall(r"EV-[0-9A-F]{8}", user.upper())
            ))
            return ModelResult(json.dumps({
                "core_goal": "完成正式规划中的目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成正式结局",
                "covered_event_ids": covered_event_ids,
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
        text = next(self.responses)
        if role == "final_review" and "AUTHORITATIVE REVIEW ISSUE LEDGER:" in user:
            payload = json.loads(text)
            ledger_text = user.split(
                "AUTHORITATIVE REVIEW ISSUE LEDGER:\n", 1,
            )[1].split("\n\n", 1)[0]
            ledger = json.loads(ledger_text)
            payload["reconciliations"] = [{
                "issue_id": item["issue_id"], "status": "resolved",
                "severity": item.get("severity", "medium"),
                "evidence": "Human, polished prose.",
            } for item in ledger]
            text = json.dumps(payload, ensure_ascii=False)
        return ModelResult(text, {"role": role, "model_name": f"fake-{role}"})

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


class ProductionSizedShortGateway:
    """Deterministic paid-boundary replacement for 13K/20K/30K acceptance."""

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.systems: list[str] = []
        self.packet_calls: list[dict] = []
        self.draft_segments: list[str] = []
        self.formal_event_count = 0

    @staticmethod
    def _result(role: str, text: str) -> ModelResult:
        return ModelResult(text, {
            "role": role, "provider_id": "offline", "model_id": "offline-model",
            "model_name": f"offline-{role}", "finish_reason": "stop",
            "input_tokens": 2400, "output_tokens": 1200,
        })

    @staticmethod
    def _planning_packet(user: str) -> str:
        contract = json.loads(
            user.split("PACKET CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
        )
        local_count = len(contract["global_event_ordinals"])
        segment = int(contract["global_segment"])
        return json.dumps({
            "version": 2,
            "initial_state": (
                f"第{segment}段开始时，调查员已承接前段证据、人物知识与关系状态。"
            ),
            "segments": [{
                "kind": "terminal", "segment": 1,
                "title": f"档案链第{segment}次转折",
                "events": [{
                    "formal_event_ordinal": ordinal,
                    "narrative": (
                        f"调查员主动核验本包第{ordinal}项档案，遭遇证人阻拦后调整关系策略，"
                        f"取得可复核结果，更新人物知识，并把因果压力交给第{segment}段后续行动。"
                    ),
                } for ordinal in range(1, local_count + 1)],
            }],
        }, ensure_ascii=False)

    @staticmethod
    def _plan_segment_receipt(user: str) -> str:
        authority = user.split(
            "EXPECTED AUTHORITY SHA256: ", 1,
        )[1].splitlines()[0]
        planning_sha = user.split(
            "EXPECTED PLANNING SHA256: ", 1,
        )[1].splitlines()[0]
        segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
        )
        candidates_text = user.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1]
        candidates_text = candidates_text.split(
            "\n\nCURRENT ACCEPTED PLAN SEGMENT:", 1,
        )[0].split("\n\nRECEIPT PROTOCOL ISSUES:", 1)[0]
        candidates = json.loads(candidates_text)
        evidence_ids = list(candidates)
        return json.dumps({
            "authority_sha256": authority,
            "planning_sha256": planning_sha,
            "segment": segment,
            "event_reviews": [{
                "event_id": event_id,
                "classification": "equivalent",
                "changed_dimensions": ["场景实现"],
                "invariants": {field: True for field in INVARIANT_FIELDS},
                "plan_evidence_ids": [
                    evidence_ids[min(index, len(evidence_ids) - 1)]
                ],
                "plan_evidence_quote": "",
                "reason": "当前计划保持正式事件功能、人物主动性与因果方向。",
            } for index, event_id in enumerate(expected)],
            "segment_order_preserved": True,
            "formal_direction_preserved": True,
            "summary": "当前分段完整保持正式事件权威。",
        }, ensure_ascii=False)

    @staticmethod
    def _plan_whole_receipt(user: str) -> str:
        authority = user.split(
            "EXPECTED AUTHORITY SHA256: ", 1,
        )[1].splitlines()[0]
        planning_sha = user.split(
            "EXPECTED PLANNING SHA256: ", 1,
        )[1].splitlines()[0]
        segments = json.loads(
            user.split("EXPECTED SEGMENTS:\n", 1)[1].splitlines()[0]
        )
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
        )
        return json.dumps({
            "authority_sha256": authority,
            "planning_sha256": planning_sha,
            "segment_numbers": segments,
            "event_ids": expected,
            "causal_order_preserved": True,
            "adjacent_handoffs_preserved": True,
            "knowledge_progression_preserved": True,
            "relationship_progression_preserved": True,
            "viewpoint_timeline_preserved": True,
            "promises_ending_preserved": True,
            "formal_direction_preserved": True,
            "affected_segments": [],
            "affected_event_ids": [],
            "reason": "",
            "summary": "整篇计划保持事件顺序、关系推进、承诺兑现与结局。",
        }, ensure_ascii=False)

    @staticmethod
    def _planning_repair_patch(user: str) -> str:
        """Return a bounded patch for Runtime-selected planning anchors.

        Production-shaped acceptance must exercise the same targeted repair
        contract used by real projects whose outline evidence is too terse to
        form an independently executable event body.  The test gateway does
        not choose the mutation scope: it only expands the exact anchors that
        Runtime already authorized and hash-bound in the prompt.
        """

        authority = user.split(
            "EXPECTED PATCH AUTHORITY SHA256: ", 1,
        )[1].splitlines()[0]
        segment = int(user.split("EXPECTED SEGMENT: ", 1)[1].splitlines()[0])
        anchors_source = user.split(
            "AUTHORIZED ORIGINAL ANCHORS:\n", 1,
        )[1]
        anchors, _end = json.JSONDecoder().raw_decode(anchors_source)
        replacements = []
        for anchor in anchors:
            source = str(anchor["text"])
            replacements.append({
                "evidence_id": str(anchor["evidence_id"]),
                "source_sha256": str(anchor["source_sha256"]),
                "replacement": (
                    source
                    + " The responsible character performs the stated action, "
                    "meets concrete resistance, obtains a verifiable result, "
                    "and passes the resulting state to the next owned event."
                ),
            })
        return json.dumps({
            "authority_sha256": authority,
            "segment": segment,
            "replacements": replacements,
            "summary": "Expanded only the Runtime-authorized incomplete event anchors.",
        }, ensure_ascii=False)

    @staticmethod
    def _planning_event_realizations(user: str) -> str:
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
        )
        return json.dumps({
            "events": [{
                "event_id": event_id,
                "narrative": (
                    "The responsible character performs the formal action, "
                    "meets a concrete response, obtains a verifiable result, and updates "
                    "the knowledge, relationship, and causal state owned by this event."
                ),
            } for event_id in expected],
        }, ensure_ascii=False)

    @staticmethod
    def _planning_targeted_segment(user: str) -> str:
        current = user.rsplit("CURRENT PLAN SEGMENT:\n", 1)[1]
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
        )
        issues_source = user.split("STRUCTURAL DRIFT ISSUES:\n", 1)[1]
        issues, _end = json.JSONDecoder().raw_decode(issues_source)
        target_ids = {
            str(item.get("event_id") or "").strip().upper()
            for item in issues if isinstance(item, dict)
        }
        contracts_source = user.split("FORMAL EVENT CONTRACTS:\n", 1)[1]
        contracts, _end = json.JSONDecoder().raw_decode(contracts_source)
        obligations_source = user.split(
            "FORMAL EVENT COMPLETION CHECKLIST:\n", 1,
        )[1]
        obligations, _end = json.JSONDecoder().raw_decode(obligations_source)
        contract_by_id = {
            str(item.get("id") or "").strip().upper(): item
            for item in contracts if isinstance(item, dict)
        }
        obligation_by_id = {
            str(item.get("event_id") or "").strip().upper(): item
            for item in obligations if isinstance(item, dict)
        }
        segment = int(user.split("EXPECTED SEGMENT: ", 1)[1].splitlines()[0])
        planning_ir = compile_planning_segment_ir(current, segment=segment)
        body = planning_ir.event_body
        occurrences = planning_event_id_occurrences(body)
        by_event = {}
        for index, (event_id, _start, marker_end) in enumerate(occurrences):
            end = occurrences[index + 1][1] if index + 1 < len(occurrences) else len(body)
            narrative = remove_planning_event_ids(
                body[marker_end:end], formal_only=True,
            ).strip(" \t\r\n:：.-、）)")
            if narrative:
                by_event[event_id] = narrative
        return json.dumps({
            "events": [{
                "event_id": event_id,
                "narrative": " ".join(dict.fromkeys(filter(None, [
                    by_event.get(event_id, ""),
                    str(contract_by_id.get(event_id, {}).get("evidence") or "")
                    if event_id in target_ids else "",
                    *(
                        [
                            str(item.get("source_excerpt") or "")
                            for item in obligation_by_id.get(event_id, {}).get(
                                "obligations", []
                            ) if isinstance(item, dict)
                        ] if event_id in target_ids else []
                    ),
                    (
                        "The responsible character performs the formal action, meets "
                        "a concrete response, obtains a verifiable result, and updates "
                        "the causal state owned by this event."
                        if event_id in target_ids else ""
                    ),
                ]))),
            } for event_id in expected],
        }, ensure_ascii=False)

    @staticmethod
    def _causal_chain(user: str) -> str:
        event_ids = list(dict.fromkeys(
            re.findall(r"EV-[0-9A-F]{8}", user.upper())
        ))
        return json.dumps({
            "core_goal": "调查员公开完整档案链并承担关系代价",
            "opening": {
                "pressure": "档案员失踪", "anomaly": "记录互相矛盾",
                "reader_question": "谁改写了档案", "future_promise": "底账将在天亮前公开",
            },
            "cycles": [{
                "obstacle": f"事件{index}的证据遭到阻拦",
                "effort": f"调查员核验事件{index}并争取证人",
                "result": f"事件{index}形成可复核结论",
                "state_change": f"人物知识与信任推进到状态{index}",
            } for index in range(1, max(2, len(event_ids) // 2) + 1)],
            "accidents": ["证人临时改口"],
            "reversal": {"content": "失踪者主动留下了矛盾索引"},
            "ending": {
                "surface_goal": "完整底账公开", "inner_goal": "调查员接受信任代价",
                "cost": "与旧同盟公开决裂",
            },
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": event_ids,
        }, ensure_ascii=False)

    def _causal_packet(self, user: str) -> str:
        contract = json.loads(
            user.split("PACKET CONTRACT:\n", 1)[1].splitlines()[0]
        )
        owned = [str(item).upper() for item in contract["owned_event_ids"]]
        owns_opening = user.split("OWNS OPENING: ", 1)[1].splitlines()[0] == "true"
        owns_ending = user.split("OWNS ENDING: ", 1)[1].splitlines()[0] == "true"
        return json.dumps({
            "core_goal": "公开完整底账" if owns_opening else "",
            "opening": {
                "pressure": "档案员失踪", "anomaly": "记录互相矛盾",
                "reader_question": "谁改写了档案", "future_promise": "底账将在天亮前公开",
            } if owns_opening else {},
            "cycles": [{
                "obstacle": f"{owned[0]}证据被阻拦",
                "effort": f"调查员核验{owned[0]}",
                "result": f"{owned[-1]}形成可复核结论",
                "state_change": f"知识推进到{owned[-1]}",
            }],
            "accidents": [], "reversal": {},
            "ending": {
                "surface_goal": "完整底账公开", "inner_goal": "接受关系代价",
                "cost": "与旧同盟决裂",
            } if owns_ending else "",
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": owned,
        }, ensure_ascii=False)

    def _draft_prose(self, user: str) -> str:
        contract = json.loads(
            user.split("CURRENT_TASK_CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
        )
        target = int(contract["target_han"])
        match = re.search(r"segment-(\d+)", str(contract["task_id"]))
        segment = int(match.group(1)) if match else len(contract.get("event_ids", []))
        actors = ("沈砚", "顾岚", "程未", "叶衡", "陆宁", "周桥")
        places = ("旧档案馆", "河堤仓库", "夜班车站", "市政听证室", "钟楼夹层")
        actions = ("核验签章", "比对时序", "追问见证", "封存副本", "公开底账", "修正关系判断")
        themes = (
            "雨水沿档案馆铜窗向下爬，失踪者留下的蓝线目录把第一轮调查引向封存柜。",
            "河堤仓库的潮气改变纸张卷曲方向，搬运记录与守夜人口供第一次正面冲突。",
            "夜班车站只亮着售票口的白灯，错位的时刻表迫使调查员重新排列见证顺序。",
            "市政听证室座次森严，公开质询让旧同盟无法继续用私下默契掩盖账目缺口。",
            "钟楼夹层积着多年灰尘，一枚新鞋印把关系判断从怀疑推进到有限信任。",
            "医院走廊的消毒水味压住低声争执，伤情记录证明证人改口并非单纯恐惧。",
            "凌晨印刷厂仍在震动，铅字排列暴露出伪造副本与原件之间不可逆的时间差。",
            "旧学校礼堂回声空旷，毕业名册让隐藏身份与失踪档案员的选择彼此扣合。",
            "山城索道悬在雾里，运输票据把零散地点压成一条可复核的行动路线。",
            "停用法院的木门受潮变形，封条纤维说明关键证物曾在判决之后被人替换。",
            "广播塔下风声尖利，录音底噪把匿名威胁与一场被忽略的公开会议连在一起。",
            "晨光越过河面落进档案大厅，全部索引终于汇成能公开、能追责的完整底账。",
        )
        paragraphs: list[str] = []
        turn = 1
        while effective_han_characters("\n\n".join(paragraphs)) < target:
            actor = actors[(segment + turn) % len(actors)]
            partner = actors[(segment + turn + 2) % len(actors)]
            place = places[(segment * 3 + turn) % len(places)]
            action = actions[(segment + turn * 2) % len(actions)]
            promise = (
                "沈砚与顾岚约定在天亮前公开底账，这项约定仍需后续证据兑现。"
                if segment == 1 and turn == 1 else ""
            )
            exit_requirement = contract.get("exit_requirement")
            terminal_scope = (
                isinstance(exit_requirement, dict)
                and exit_requirement.get("kind") == "terminal_closure"
            ) or "terminal" in str(exit_requirement).casefold() or segment == max(
                int(item["global_segment"]) for item in self.packet_calls
            )
            payoff = (
                "天亮前，沈砚公开完整底账，完成先前约定并确认失踪者安全归来。"
                if terminal_scope and turn == 1 else ""
            )
            paragraphs.append(
                themes[(segment - 1) % len(themes)]
                + f"第{segment}段第{turn}轮发生在{place}。{actor}先{action}，没有让{partner}"
                f"替自己完成决定；他依据编号{segment:02d}-{turn:03d}的纸张纤维、墨迹深浅"
                f"和门禁时间，排除一条看似合理的说法。{partner}从戒备转为有限合作，"
                f"人物知识由猜测推进为可复核事实，关系变化由现场行动直接支撑。{promise}{payoff}"
                f"这一轮留下的结果只服务当前正式事件，并把尚未完成的因果压力交给下一轮。"
            )
            turn += 1
        return "\n\n".join(paragraphs)

    @staticmethod
    def _whole_receipt(user: str) -> str:
        authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
        draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
        segment_hashes = json.loads(re.search(
            r"SEGMENT SHA256: (\[[^\n]+\])", user,
        ).group(1))
        expected = json.loads(re.search(
            r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
        ).group(1))
        opening = user.split("OPENING EXCERPT: ", 1)[1].split(
            "\nENDING EXCERPT:", 1,
        )[0]
        ending = user.split("ENDING EXCERPT: ", 1)[1]
        return json.dumps({
            "authority_sha256": authority, "draft_sha256": draft_sha,
            "segment_sha256": segment_hashes, "event_ids": expected,
            "missing_event_ids": [], "duplicate_event_ids": [],
            "out_of_order_event_ids": [], "causal_order_valid": True,
            "continuity_valid": True, "ending_valid": True,
            "commitments_valid": True,
            "evidence": [
                {"kind": "opening", "excerpt": opening[:20]},
                {"kind": "ending", "excerpt": ending[-20:]},
            ],
            "summary": "整篇正文保持事件顺序、知识关系推进、承诺兑现与确认结局。",
        }, ensure_ascii=False)

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        self.systems.append(system)
        if "IR_FIRST_SHORT_PLANNING_PACKET_V2" in user:
            contract = json.loads(
                user.split("PACKET CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
            )
            self.packet_calls.append(contract)
            self.formal_event_count = max(
                self.formal_event_count,
                max(contract["global_event_ordinals"]),
            )
            return self._result(role, self._planning_packet(user))
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            raise AssertionError("production-sized whole planning bypassed the splitter")
        if "SHORT_PLAN_ADAPTATION_REVIEW_V2" in user:
            return self._result(role, self._plan_segment_receipt(user))
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in user:
            return self._result(role, self._plan_whole_receipt(user))
        if "SHORT_PLAN_EVIDENCE_PATCH_V3" in user:
            return self._result(role, self._planning_repair_patch(user))
        if (
            "SHORT_PLAN_EQUIVALENCE_TARGETED_REPAIR_V2" in user
            or "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in user
        ):
            return self._result(role, self._planning_targeted_segment(user))
        if "SHORT_PLAN_EVENT_REALIZATION_RECOVERY_V3" in user:
            return self._result(role, self._planning_event_realizations(user))
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            return self._result(role, self._causal_chain(user))
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET_V2" in user:
            return self._result(role, self._causal_packet(user))
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return self._result(
                role, json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False),
            )
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return self._result(role, execution_manifest_receipt_from_prompt(user))
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return self._result(
                role, json.dumps(draft_semantic_receipt(contract, prose), ensure_ascii=False),
            )
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            return self._result(role, self._whole_receipt(user))
        if role == "draft":
            prose = self._draft_prose(user)
            self.draft_segments.append(prose)
            return self._result(role, prose)
        if role == "polish":
            source = user.rsplit("MANUSCRIPT SEGMENT:\n", 1)[1]
            return self._result(role, source)
        if role == "final_review" and "FULL MANUSCRIPT WINDOW SUMMARY" in user:
            return self._result(role, json.dumps({
                "summary": "当前窗口保持事件、人物知识、关系与时间线连续。",
                "issues": [],
            }, ensure_ascii=False))
        if role == "final_review" and "终审详细事件和伏笔单独分析" in user:
            return self._result(role, json.dumps({
                "events": ["正式事件依次完成"],
                "promises": ["天亮前公开底账的约定在结局兑现"],
                "character_states": ["调查员知识与关系逐段推进"],
                "timeline": ["全部分段按正式顺序展开"],
            }, ensure_ascii=False))
        if role == "final_review" and "REGIONAL EVIDENCE REDUCTION" in user:
            return self._result(role, json.dumps({
                "summary": "区域证据保持跨窗因果、关系与承诺连续。", "issues": [],
            }, ensure_ascii=False))
        if role == "final_review" and "FULL MANUSCRIPT FINAL ADJUDICATION" in user:
            ledger = json.loads(user.split(
                "AUTHORITATIVE REVIEW ISSUE LEDGER:\n", 1,
            )[1].split("\n\n", 1)[0])
            payload = json.loads(quality_review(93, 94, 92, issues=[]))
            payload["reconciliations"] = [{
                "issue_id": item["issue_id"], "status": "resolved",
                "severity": item.get("severity", "medium"),
                "evidence": "正文保持正式事件与结局。",
            } for item in ledger]
            return self._result(role, json.dumps(payload, ensure_ascii=False))
        if role == "review":
            return self._result(role, quality_review(91, 92, 90, issues=[]))
        if role == "maintenance":
            return self._result(role, json.dumps({
                "facts": [{
                    "fact_key": "ending.public_ledger",
                    "value": "调查员在天亮前公开完整底账并承担关系代价",
                }],
                "state": {"沈砚": {"knowledge": "已确认全部档案链"}},
                "world_rules": [], "timeline": ["底账在天亮前公开"],
            }, ensure_ascii=False))
        raise AssertionError(f"unexpected offline model call: {role}: {user[:160]}")

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


def expose_test_primary_route(gateway):
    """Make a test double explicitly own the primary route it is exercising."""

    if not hasattr(gateway, "complete_primary"):
        gateway.complete_primary = gateway.complete
    return gateway


def execution_manifest_body_from_prompt(user: str) -> dict:
    if (
        "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
        or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
    ):
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0]
        )
        segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        contracts = json.loads(
            user.split("CURRENT EVENT CONTRACTS:\n", 1)[1].split(
                "\n\nCURRENT ACCEPTED PLAN SEGMENT:\n", 1,
            )[0]
        )
        contract_by_id = {
            str(item["id"]).upper(): item for item in contracts
        }
        previous_exit = json.loads(
            user.split("PREVIOUS ACCEPTED EXIT STATE:\n", 1)[1].split(
                "\n\nVIEWPOINT AND TIMELINE AUTHORITY:\n", 1,
            )[0]
        )
        beats = []
        for index, source in enumerate(expected, 1):
            evidence_ids = [
                str(item.get("evidence_id") or "")
                for item in contract_by_id[source].get("evidence_catalog", [])
                if isinstance(item, dict) and str(item.get("evidence_id") or "")
            ]
            beats.append({
                "beat_id": f"{source}/01",
                "source_event_id": source,
                "order": index,
                "presentation_order": index,
                "action": f"执行当前正式段事件 {source}",
                "preconditions": ["承接当前段入口"],
                "postconditions": [f"完成 {source}"],
                "owner_segment": segment,
                "source_evidence_ids": evidence_ids,
            })
        entry_state = previous_exit or [{
            "state": "opening", "inherited_from": "opening",
        }]
        return {
            "beats": beats,
            "segments": [{
                "segment": segment,
                "beat_ids": [item["beat_id"] for item in beats],
                "entry_state": [
                    {
                        "state": item["state"],
                        "inherited_from": item.get("inherited_from")
                        or f"segment-{segment - 1:02d}",
                    }
                    for item in entry_state
                ],
                "exit_state": [{
                    "state": f"完成 {expected[-1]}",
                    "produced_by": beats[-1]["beat_id"],
                }],
                "previous_exit_sha256": "",
                "prohibited_future_beat_ids": [],
            }],
        }
    expected = json.loads(user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0])
    count = int(user.split("SEGMENT COUNT: ", 1)[1].splitlines()[0])
    total = max(len(expected), count)
    occurrences = {}
    beats = []
    per_segment = {number: [] for number in range(1, count + 1)}
    for index in range(total):
        source_index = min(len(expected) - 1, index * len(expected) // total)
        source = expected[source_index]
        occurrences[source] = occurrences.get(source, 0) + 1
        beat_id = f"{source}/{occurrences[source]:02d}"
        segment = min(count, index * count // total + 1)
        beats.append({
            "beat_id": beat_id, "source_event_id": source, "order": index + 1,
            "action": f"执行正式事件 {source}",
            "preconditions": ["承接上一原子节拍"],
            "postconditions": [source], "owner_segment": segment,
            "source_evidence": source,
        })
        per_segment[segment].append(beat_id)
    segments = []
    previous_state = ""
    all_ids = [item["beat_id"] for item in beats]
    for number in range(1, count + 1):
        owned = per_segment[number]
        exit_state = next(
            item["source_event_id"] for item in reversed(beats)
            if item["beat_id"] in owned
        )
        segments.append({
            "segment": number,
            "beat_ids": owned,
            "entry_state": [{
                "state": previous_state or "opening",
                "inherited_from": "opening" if number == 1 else f"segment-{number - 1:02d}",
            }],
            "exit_state": [{
                "state": exit_state, "produced_by": owned[-1],
            }],
            "previous_exit_sha256": "" if number == 1 else "a" * 64,
            "prohibited_future_beat_ids": [
                beat_id for beat_id in all_ids
                if beats[all_ids.index(beat_id)]["owner_segment"] > number
            ],
        })
        previous_state = exit_state
    return bind_previous_exit_hashes({"beats": beats, "segments": segments})


def execution_manifest_receipt_from_prompt(user: str) -> str:
    boundary_candidates = json.loads(
        user.split("BOUNDARY EVIDENCE CANDIDATES:\n", 1)[1].split(
            "\n\nEXECUTION MANIFEST:\n", 1,
        )[0]
    )
    raw = user.split("EXECUTION MANIFEST:\n", 1)[1].split(
        "\n\nAUTHORITY TEXT:\n", 1,
    )[0]
    manifest = parse_execution_manifest(json.loads(raw))
    return json.dumps({
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": [{
            "beat_id": beat.beat_id,
            **(
                {"evidence_ids": list(beat.source_evidence_ids)}
                if beat.source_evidence_ids else
                {"evidence": beat.source_evidence}
            ),
            "actor_action_valid": True,
        } for beat in manifest.beats],
        "segment_receipts": [{
            "segment": segment.segment, "boundary_valid": True,
            "evidence_id": next(reversed(boundary_candidates)),
        } for segment in manifest.segments],
        "formal_plot_unchanged": True,
        "summary": "执行索引与正式资料一致。",
    }, ensure_ascii=False)


def draft_semantic_receipt(contract: dict, prose: str) -> dict:
    evidence = prose[:12]
    order_evidence = prose if len(prose) <= 80 else prose[:80]
    atomic = bool(contract.get("beat_ids"))
    payload = {
        "authority_sha256": contract["authority_sha256"],
        "task_id": contract["task_id"],
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "entry": {"satisfied": True, "evidence": evidence},
        "exit": {"satisfied": True, "evidence": prose[-12:]},
        "causal_order_valid": True,
        "causal_order_evidence": order_evidence,
        "summary": "本段事件、状态、顺序和交接均已核对。",
    }
    if atomic:
        payload.update({
            "execution_manifest_sha256": contract["execution_manifest_sha256"],
            "beat_receipts": [{
                "beat_id": beat_id,
                "evidence": evidence,
                "actor_action_valid": True,
                "actor_action_evidence": evidence,
                "state_valid": True,
                "state_evidence": evidence,
                "scene_order_valid": True,
                "scene_order_evidence": order_evidence,
            } for beat_id in contract["beat_ids"]],
            "outside_beat_ids": [],
            "future_beat_ids": [],
            "viewpoint_valid": True,
            "viewpoint_evidence": evidence,
        })
    else:
        payload.update({
            "event_receipts": [{
                "event_id": event_id, "evidence": evidence,
            } for event_id in contract["event_ids"]],
            "outside_event_ids": [],
        })
    return payload


def write_test_execution_manifest(
    service: WorkflowService, project, run_path: Path, constraints: str,
    plan: str, segment_count: int, chain: dict | None = None,
    use_plan_event_ids: bool = True, state_override: dict | None = None,
    planning_adaptation: dict | None = None,
):
    state = service.story_states.ensure(project.id, project.path)
    authority_state = state_override if state_override is not None else state.data
    plan_event_ids = list(dict.fromkeys(
        event_id
        for block in service._short_plan_segments(plan, segment_count)
        for event_id in service._short_plan_event_ids(block)
    ))
    chain = {
        **(chain or {
            "core_goal": "完成测试规划",
            "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
            "ending": "完成测试结局",
        }),
        "covered_event_ids": plan_event_ids,
    }
    formal_events = [{
        "id": event_id, "order": index,
        "label": f"测试正式事件 {event_id}",
        "section": "测试规划", "kind": "narrative",
    } for index, event_id in enumerate(plan_event_ids, 1)] if use_plan_event_ids else []
    hashes, authority_text, events = service._short_execution_authority(
        project, state.revision, authority_state, constraints, plan, chain,
        formal_events, segment_count, planning_adaptation,
    )
    expected = [item["id"] for item in events]
    prompt = (
        "EXPECTED EVENT IDS:\n" + json.dumps(expected)
        + f"\n\nSEGMENT COUNT: {segment_count}\n"
    )
    payload = {
        **execution_manifest_body_from_prompt(prompt),
        "version": 3, "status": "ready", **hashes,
        "semantic_receipt": {}, "repair_attempts": 0,
    }
    evidence_by_event = {
        str(item["id"]): str(item.get("evidence") or item["id"])
        for item in events
    }
    for beat in payload["beats"]:
        beat["source_evidence"] = evidence_by_event[beat["source_event_id"]]
    manifest = parse_execution_manifest(payload)
    receipt = {
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": [{
            "beat_id": beat.beat_id, "evidence": beat.source_evidence,
            "actor_action_valid": True,
        } for beat in manifest.beats],
        "segment_receipts": [{
            "segment": segment.segment, "boundary_valid": True,
            "evidence": segment.exit_state[0].state,
        } for segment in manifest.segments],
        "formal_plot_unchanged": True,
        "summary": "测试执行索引与规划一致。",
    }
    manifest = replace(manifest, semantic_receipt=receipt)
    atomic = __import__(
        "novel_flywheel.storage", fromlist=["atomic_write"],
    ).atomic_write
    atomic(
        run_path / "outputs" / "short-execution-index.json",
        json.dumps(
            execution_manifest_payload(manifest), ensure_ascii=False, indent=2,
        ),
    )
    atomic(
        run_path / "outputs" / "short-causal-chain.json",
        json.dumps(chain, ensure_ascii=False, indent=2),
    )
    return manifest


def complete_checkpoint_plan(count: int = 4) -> str:
    """Build a real typed planning fixture; checkpoint tests must not mint IR."""

    return "\n\n".join(
        f"### 第 {number} 段：检查点事件 {number}\n"
        f"事件ID：EV-{number:08X}\n"
        f"大纲依据：检查点事件 {number} 的正式推进。\n"
        f"段首承接：承接第 {number} 段的既定入口状态。\n"
        f"本段事件：主角执行第 {number} 段行动，遇到阻碍并形成状态变化。\n"
        f"段末交接：第 {number} 段结果成立并交给下一段。"
        for number in range(1, count + 1)
    )


def complete_plan_for_event_groups(event_groups: Sequence[Sequence[str]]) -> str:
    """Build a typed planning fixture with explicit ownership and boundaries."""

    return "\n\n".join(
        (
            f"### 第 {segment} 段：验收事件组 {segment}\n"
            f"事件ID：{'、'.join(event_ids)}\n"
            f"大纲依据：第 {segment} 组正式事件按既定顺序推进。\n"
            + (
                "段首承接：故事入口状态已经建立。\n"
                if segment == 1 else
                f"段首承接：第 {segment - 1} 组结果已经成立。\n"
            )
            + "本段事件：\n"
            + "\n".join(
                f"{index}. {event_id} 的执行者完成受阻行动并形成可验证结果。"
                for index, event_id in enumerate(event_ids, 1)
            )
            + "\n"
            + (
                "段末交接：正式结局状态已经成立。"
                if segment == len(event_groups) else
                f"段末交接：第 {segment} 组结果成立并交给下一组。"
            )
        )
        for segment, raw_event_ids in enumerate(event_groups, 1)
        for event_ids in (list(raw_event_ids),)
    )


def test_execution_authority_multi_event_evidence_scales_linearly(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Linear authority", mode="short", genre="mystery",
        premise="Every accepted event retains one bounded realization.",
        target_words=10_000,
    ))
    service = WorkflowService(db, store, SimpleNamespace(), SimpleNamespace())
    sizes = []
    evidence_sizes = []
    for count in (8, 16, 32):
        event_ids = [f"EV-{index:08X}" for index in range(1, count + 1)]
        plan = complete_plan_for_event_groups([event_ids])
        formal_events = [{
            "id": event_id, "order": index,
            "label": f"Formal event label {index}",
        } for index, event_id in enumerate(event_ids, 1)]
        chain = {
            "core_goal": "Preserve the accepted event order.",
            "ending": "The final accepted state is established.",
            "covered_event_ids": event_ids,
        }

        _hashes, authority, events = service._short_execution_authority(
            project, 1, {"outline": {"content": "Formal outline authority."}},
            "constraints", plan, chain, formal_events, 1,
        )
        sizes.append(len(authority))
        evidence_sizes.append(sum(len(item["evidence"]) for item in events))

    assert sizes[1] < sizes[0] * 2.5
    assert sizes[2] < sizes[1] * 2.5
    assert evidence_sizes[1] < evidence_sizes[0] * 2.5
    assert evidence_sizes[2] < evidence_sizes[1] * 2.5


def save_test_complete_short_checkpoint(
    service: WorkflowService, project, outputs: Path, context: dict,
    constraints: str = "test constraints", state_override: dict | None = None,
    planning_adaptation: dict | None = None,
) -> None:
    plan = (outputs / "planning.md").read_text(encoding="utf-8")
    draft = (outputs / "draft.md").read_text(encoding="utf-8")
    chain = {
        "core_goal": "完成测试规划",
        "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
        "ending": "完成测试结局",
        "covered_event_ids": list(dict.fromkeys(
            event_id
            for block in service._short_plan_segments(
                plan, int(context["segment_count"]),
            )
            for event_id in service._short_plan_event_ids(block)
        )),
    }
    manifest = write_test_execution_manifest(
        service, project, outputs.parent, constraints, plan,
        int(context["segment_count"]), chain=chain, use_plan_event_ids=True,
        state_override=state_override,
        planning_adaptation=planning_adaptation,
    )
    manifest_hash = execution_manifest_sha256(manifest)
    integrity = {
        "version": 3, "status": "passed",
        "execution_manifest_sha256": manifest_hash,
        "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        "plan_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        "base_constraints_sha256": context["constraints_sha256"],
        "story_state_sha256": context["story_state_sha256"],
        "semantic_segment_receipts": [],
        "issues": [],
    }
    atomic = __import__(
        "novel_flywheel.storage", fromlist=["atomic_write"],
    ).atomic_write
    atomic(
        outputs / "short-causal-chain.json",
        json.dumps(chain, ensure_ascii=False, indent=2),
    )
    atomic(
        outputs / "draft-integrity.json",
        json.dumps(integrity, ensure_ascii=False, indent=2),
    )
    service._save_short_checkpoint(outputs, context)


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


class BlockedVolumeGateway(FakeGateway):
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
            json.dumps({
                "score": 40, "hard_fail": True,
                "issues": ["The volume promise is unresolved."],
            }),
        ])


def make_prompt_skills(root) -> None:
    for name in REQUIRED_SKILLS:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nSkill instructions for {name}.", encoding="utf-8",
        )


class ExplicitPrimaryGateway:
    """Test gateway whose generic method is explicitly the primary route."""

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens,
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
async def test_primary_only_review_retry_never_uses_hidden_fallback(tmp_path) -> None:
    class RouteIsolatedGateway:
        def __init__(self) -> None:
            self.primary_calls = 0
            self.complete_calls = 0
            self.fallback_calls = 0

        async def complete(self, *_args, **_kwargs):
            self.complete_calls += 1
            raise AssertionError("generic completion must not own a route-isolated retry")

        async def complete_primary(self, *_args, **kwargs):
            self.primary_calls += 1
            if self.primary_calls == 1:
                return ModelResult("", {
                    "finish_reason": "max_tokens",
                    "provider_id": "primary",
                    "model_id": "primary-model",
                    "model_name": "primary-model",
                    "input_tokens": 100,
                    "output_tokens": kwargs.get("max_output_tokens") or 1,
                })
            return ModelResult('{"ok":true}', {
                "finish_reason": "stop",
                "provider_id": "primary",
                "model_id": "primary-model",
                "model_name": "primary-model",
                "input_tokens": 100,
                "output_tokens": 8,
            })

        async def complete_configured_fallback(self, *_args, **_kwargs):
            self.fallback_calls += 1
            raise AssertionError("fallback must be selected only by the outer schedule")

    gateway = RouteIsolatedGateway()
    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="route-isolated-review",
    )
    db.save_role_binding(
        "review", "primary", "primary-model", "backup", "backup-model",
    )

    result = await service._stage(
        "route-isolated-review", run_path, project,
        "review", "constraints", "Return one bounded receipt.",
        suffix="-primary-route",
        allow_tools=False,
        primary_only=True,
        expected_output_characters=200,
        bounded_protocol_output=True,
        completion_check=lambda value: bool(value.strip()),
    )

    assert json.loads(result) == {"ok": True}
    assert gateway.primary_calls == 2
    assert gateway.complete_calls == 0
    assert gateway.fallback_calls == 0


@pytest.mark.asyncio
async def test_primary_only_fails_closed_without_primary_route_interface(tmp_path) -> None:
    class LegacyGenericGateway:
        def __init__(self) -> None:
            self.complete_calls = 0

        async def complete(self, *_args, **_kwargs):
            self.complete_calls += 1
            raise AssertionError("generic completion must never impersonate primary")

    gateway = LegacyGenericGateway()
    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="missing-primary-interface",
    )
    db.save_role_binding(
        "review", "primary", "primary-model", "backup", "backup-model",
    )

    with pytest.raises(RuntimeError, match="primary route interface unavailable"):
        await service._stage(
            "missing-primary-interface", run_path, project,
            "review", "constraints", "Return one bounded receipt.",
            allow_tools=False,
            primary_only=True,
            bounded_protocol_output=True,
        )

    assert gateway.complete_calls == 0


@pytest.mark.asyncio
async def test_primary_only_owns_tools_targeted_retry_and_polish_tool_retry(
    tmp_path,
) -> None:
    class RouteMatrixGateway:
        def __init__(self) -> None:
            self.primary_calls = 0
            self.generic_calls = 0
            self.tool_calls = 0
            self.fallback_calls = 0
            self.mode = "success"

        async def complete(self, *_args, **_kwargs):
            self.generic_calls += 1
            raise AssertionError("generic route escaped primary-only isolation")

        async def complete_with_tools(self, *_args, **_kwargs):
            self.tool_calls += 1
            raise AssertionError("tool route escaped primary-only isolation")

        async def complete_configured_fallback(self, *_args, **_kwargs):
            self.fallback_calls += 1
            raise AssertionError("fallback escaped primary-only isolation")

        async def complete_primary(self, *_args, **_kwargs):
            self.primary_calls += 1
            if self.mode == "fail":
                raise RuntimeError("primary transport interrupted")
            if self.mode == "tool-retry" and self.primary_calls == 3:
                return ModelResult("", {"finish_reason": "tool_use"})
            return ModelResult("polished prose", {"finish_reason": "stop"})

    gateway = RouteMatrixGateway()
    _db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="primary-route-matrix",
    )
    result = await service._stage(
        "primary-route-matrix", run_path, project,
        "review", "constraints", "bounded receipt", allow_tools=True,
        primary_only=True, bounded_protocol_output=True,
    )
    assert str(result) == "polished prose"

    gateway.mode = "fail"
    with pytest.raises(TargetedGroupError):
        await service._stage(
            "primary-route-matrix", run_path, project,
            "review", "constraints", "targeted receipt", allow_tools=False,
            primary_only=True, targeted_retry=True,
            bounded_protocol_output=True,
        )

    gateway.mode = "tool-retry"
    result = await service._stage(
        "primary-route-matrix", run_path, project,
        "polish", "constraints", "polish prose", allow_tools=False,
        primary_only=True, retry_polish_output_limit=True,
    )
    assert str(result) == "polished prose"
    assert gateway.generic_calls == 0
    assert gateway.tool_calls == 0
    assert gateway.fallback_calls == 0
    assert gateway.primary_calls == 4


@pytest.mark.asyncio
async def test_bounded_receipt_system_contract_replaces_quality_scorecard(
    tmp_path,
) -> None:
    class ContractCapturingGateway:
        def __init__(self) -> None:
            self.system = ""

        async def complete_configured_fallback(
            self, _role, system, _user, **_kwargs,
        ):
            self.system = system
            return ModelResult(json.dumps({
                "invariants": {
                    "event_function": True,
                    "primary_actor_agency": True,
                    "causal_dependencies": True,
                },
                "changed_dimensions": [],
                "plan_evidence_ids": ["E-1"],
                "reason": "The selected Runtime evidence preserves every invariant.",
            }), {
                "finish_reason": "stop",
                "input_tokens": 10,
                "output_tokens": 5,
            })

        async def complete_primary(self, *_args, **_kwargs):
            raise AssertionError("the configured fallback route owns this attempt")

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("generic completion must not own this route")

    gateway = ContractCapturingGateway()
    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="receipt-system-contract",
    )
    db.save_role_binding(
        "review", "primary", "review-model", "backup", "backup-review-model",
    )
    invariant_fields = (
        "event_function", "primary_actor_agency", "causal_dependencies",
    )
    evidence_candidates = {"E-1": "Known Runtime evidence phrase."}

    result = await service._stage(
        "receipt-system-contract", run_path, project,
        "review", "constraints", "Return the requested invariant receipt.",
        allow_tools=False,
        prefer_configured_fallback=True,
        defer_route_failure_audit=True,
        bounded_protocol_output=True,
        protocol_system_contract=IMMUTABLE_RECEIPT_SYSTEM,
        completion_check=lambda value: not (
            service._converted_planning_adaptation_facet_semantic_issues(
                value, run_path,
                invariant_fields=invariant_fields,
                evidence_candidates=evidence_candidates,
            )
        ),
    )

    assert service._converted_planning_adaptation_facet_semantic_issues(
        result, run_path,
        invariant_fields=invariant_fields,
        evidence_candidates=evidence_candidates,
    ) == []
    assert gateway.system.startswith(IMMUTABLE_RECEIPT_SYSTEM)
    assert "dimensions commercial/story/prose" not in gateway.system


@pytest.mark.asyncio
async def test_route_failure_passthrough_persists_only_typed_hash_audit(tmp_path) -> None:
    class RejectedGateway:
        async def complete_primary(self, *_args, **_kwargs):
            raise RuntimeError(
                "HTTP 403 Forbidden from secret-provider.example before terminal response"
            )

        async def complete_configured_fallback(self, *_args, **_kwargs):
            raise AssertionError("the outer schedule has not selected fallback yet")

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("generic completion must not own this route")

    gateway = RejectedGateway()
    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="route-failure-audit",
    )
    db.save_role_binding(
        "review", "primary", "primary-model", "backup", "backup-model",
    )
    attempt = protocol_receipt_attempts(
        same_route_attempts=1, configured_fallback_available=True,
    )[0]

    result, failure = await service._execute_protocol_receipt_attempt(
        "route-failure-audit",
        stage="review",
        boundary="test_protocol_boundary",
        attempt=attempt,
        unit_metadata={"authority_sha256": "a" * 64, "event_count": 1},
        operation=lambda: service._stage(
            "route-failure-audit", run_path, project,
            "review", "constraints", "Return one bounded receipt.",
            suffix="-rejected-primary",
            allow_tools=False,
            primary_only=True,
            defer_route_failure_audit=True,
            expected_output_characters=200,
            bounded_protocol_output=True,
        ),
    )

    assert result is None
    assert failure is not None
    assert failure.code == "protocol_route_provider_rejection"
    events = db.list_run_events("route-failure-audit")
    route_event = next(
        event for event in events
        if event["event_type"] == "protocol_receipt_route_failed"
    )
    assert len(route_event["metadata"]["error_sha256"]) == 64
    assert not any(event["event_type"] == "stage_failed" for event in events)
    persisted = json.dumps(events, ensure_ascii=False)
    assert "403" not in persisted
    assert "secret-provider" not in persisted


@pytest.mark.asyncio
async def test_explicit_transport_type_outranks_stale_capacity_context(tmp_path) -> None:
    class InterruptedGateway:
        async def complete_primary(self, *_args, **_kwargs):
            try:
                raise RuntimeError("HTTP 413 context_length_exceeded")
            except RuntimeError:
                raise TransportInterruptedError({
                    "finish_reason": "network_error",
                    "transport_complete": False,
                })

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("generic completion must not own this route")

    gateway = InterruptedGateway()
    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, gateway, run_id="typed-transport-audit",
    )
    db.save_role_binding("review", "primary", "review-model", None, None)
    attempt = protocol_receipt_attempts(
        same_route_attempts=2, configured_fallback_available=False,
    )[0]

    result, failure = await service._execute_protocol_receipt_attempt(
        "typed-transport-audit",
        stage="review",
        boundary="test_protocol_boundary",
        attempt=attempt,
        unit_metadata={"authority_sha256": "a" * 64},
        operation=lambda: service._stage(
            "typed-transport-audit", run_path, project,
            "review", "constraints", "Return one bounded receipt.",
            allow_tools=False,
            primary_only=True,
            defer_route_failure_audit=True,
            expected_output_characters=200,
            bounded_protocol_output=True,
        ),
    )

    assert result is None
    assert failure is not None
    assert failure.code == "protocol_route_transport_interrupted"
    route_event = next(
        event for event in db.list_run_events("typed-transport-audit")
        if event["event_type"] == "protocol_receipt_route_failed"
    )
    assert route_event["metadata"]["failure_class"] == "transport"
    assert route_event["metadata"]["failure_kind"] == "transport_interrupted"


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
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
    )

    journal = load_project_mutation_journal(
        project_mutation_journal_path(project.path, result["id"]),
    )
    assert journal.status == "committed"
    assert journal.story_state is not None
    assert not (project.path / journal.snapshot_path).exists()


@pytest.mark.asyncio
async def test_material_audit_durable_report_resumes_exact_story_state_commit(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.workflows as workflows_module
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
        recover_project_mutations,
    )

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Audit forward recovery", mode="short", genre="suspense",
        premise="The report and issue ledger commit together.",
        target_words=1000,
    ))
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("沈砚拒绝酒杯。" * 400, encoding="utf-8")
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )

    async def fake_stage(*args, **kwargs):
        return StageText(json.dumps({"issues": [{
            "category": "character_habit", "severity": "high",
            "evidence": "沈砚拒绝酒杯", "location": "开篇",
            "old_setting": "拒绝饮酒", "new_setting": "主动饮酒",
            "action": "保留正式人物习惯",
        }]}, ensure_ascii=False), {})

    service._stage = fake_stage
    real_complete = workflows_module.complete_project_mutation

    def interrupt_after_artifacts(*_args, **_kwargs):
        raise OSError("terminal DB write interrupted")

    monkeypatch.setattr(
        workflows_module, "complete_project_mutation",
        interrupt_after_artifacts,
    )
    with pytest.raises(OSError, match="terminal DB write interrupted"):
        await service.run_materials_audit(
            project.id, use_crewai=False, run_id="audit-forward-recovery",
        )

    journal_path = project_mutation_journal_path(
        project.path, "audit-forward-recovery",
    )
    pending = load_project_mutation_journal(journal_path)
    assert pending.status == "artifacts_committed"
    assert db.get_run("audit-forward-recovery")["status"] == "running"
    assert StoryStateStore(db).get(project.id).revision == 1

    monkeypatch.setattr(
        workflows_module, "complete_project_mutation", real_complete,
    )
    assert recover_project_mutations(
        store, workflow="materials-audit",
    ) == ["audit-forward-recovery"]
    assert db.get_run("audit-forward-recovery")["status"] == "completed"
    state = StoryStateStore(db).get(project.id)
    assert state.revision == 2
    assert state.data["issue_ledger"][0]["source"] == "materials_audit"
    assert load_project_mutation_journal(journal_path).status == "committed"


@pytest.mark.asyncio
async def test_material_audit_report_write_failure_rolls_back_without_state_drift(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.workflows as workflows_module
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
    )

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Audit rollback", mode="short", genre="suspense",
        premise="A failed report cannot advance story authority.",
        target_words=1000,
    ))
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("沈砚拒绝酒杯。" * 400, encoding="utf-8")
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )

    async def fake_stage(*args, **kwargs):
        return StageText('{"issues": []}', {})

    service._stage = fake_stage
    real_atomic_write = workflows_module.atomic_write

    def fail_report(path, text, *args, **kwargs):
        if Path(path).name == "conflict-report.json":
            raise OSError("private filesystem detail")
        return real_atomic_write(path, text, *args, **kwargs)

    monkeypatch.setattr(workflows_module, "atomic_write", fail_report)
    with pytest.raises(OSError, match="private filesystem detail"):
        await service.run_materials_audit(
            project.id, use_crewai=False, run_id="audit-rollback",
        )

    journal = load_project_mutation_journal(
        project_mutation_journal_path(project.path, "audit-rollback"),
    )
    assert journal.status == "rolled_back"
    assert not (project.path / journal.snapshot_path).exists()
    assert not (
        project.path / "runs" / "audit-rollback" / "outputs"
        / "conflict-report.json"
    ).exists()
    assert StoryStateStore(db).get(project.id).revision == 1
    run = db.get_run("audit-rollback")
    assert run["status"] == "failed"
    assert "private filesystem detail" not in str(run.get("error") or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("target_characters", [13_000, 20_000, 30_000])
async def test_material_audit_production_lengths_cover_full_reference_tail(
    tmp_path, target_characters,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title=f"Audit {target_characters}", mode="short", genre="suspense",
        premise="Every manuscript and reference span must be audited.",
        target_words=target_characters,
    ))
    paragraphs = []
    cursor = 0
    while cursor < target_characters:
        paragraph = f"第{len(paragraphs) + 1}段，人物推进线索并更新认知。"
        paragraphs.append(paragraph)
        cursor += len(paragraph)
    manuscript_text = "\n\n".join(paragraphs)
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text(manuscript_text, encoding="utf-8")
    reference_tail = "REFERENCE-TAIL-UNIQUE-65000"
    character_path = project.path / "characters" / "hero.md"
    character_path.write_text(
        ("人物已确认事实。\n\n" * 7_500) + reference_tail,
        encoding="utf-8",
    )
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    prompts = []

    async def fake_stage(*args, **kwargs):
        prompts.append(args[5])
        return StageText('{"issues": []}', {})

    service._stage = fake_stage
    result = await service.run_materials_audit(
        project.id, use_crewai=False,
    )

    assert result["status"] == "completed"
    assert any(reference_tail in prompt for prompt in prompts)
    assert StoryStateStore(db).get(project.id).revision == 1
    with db.connect() as connection:
        checkpoints = connection.execute(
            "SELECT * FROM workflow_node_checkpoints WHERE run_id=? "
            "AND node_key LIKE 'materials-audit-packet-%' "
            "AND status='validated'",
            (result["id"],),
        ).fetchall()
    assert len(checkpoints) == len(prompts)


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
        # The shared contract runtime owns two bounded same-route attempts;
        # fail both for the third packet so restart recovery is exercised.
        if first_calls in {3, 4}:
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
    source = manuscript.read_text(encoding="utf-8")
    target = service._material_audit_packet_target()
    expected_packets = build_material_audit_packets(
        build_material_reference_authority(
            project.path, target_characters=target,
        ),
        source,
        review_windows(
            source, target=target,
            overlap=min(400, max(0, target // 8)),
        ),
    )
    assert first_calls + resumed_calls - 2 == len(expected_packets)
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
        "planning", "planning", "planning", "review", "draft", "review",
        "review", "review", "review", "polish", "review", "review",
        "final_review", "maintenance",
    ]
    assert (project.path / "manuscript" / "story.md").read_text(encoding="utf-8") == "# Final Story\nHuman, polished prose."
    assert (project.path / "chapters" / "chapter-01.md").is_file()
    assert json.loads((project.path / "memory" / "canon.json").read_text(encoding="utf-8"))["facts"]
    run_path = project.path / "runs" / result["id"]
    promotion_journal = json.loads(
        (run_path / "outputs" / "project-mutation-journal.json").read_text(
            encoding="utf-8",
        )
    )
    assert promotion_journal["operation"] == "short-story"
    assert promotion_journal["status"] == "committed"
    assert {
        item["path"] for item in promotion_journal["artifacts"]
    } == {
        "manuscript/story.md", "chapters/chapter-01.md", "memory/canon.json",
    }
    assert not (run_path / "outputs" / "formal-promotion-journal.json").exists()
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
async def test_ir_first_canary_reaches_complete_formal_manuscript(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="IR Canary", mode="short", genre="mystery",
        premise="A passenger vanishes from a locked carriage.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class IrFirstGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self.responses = iter([
                "# Draft\nRough story.",
                json.dumps({"score": 86, "hard_fail": False, "issues": ["tighten prose"]}),
                json.dumps({"score": 84, "hard_fail": False, "issues": ["strengthen paid hook"]}),
                "# Final Story\nHuman, polished prose.",
                json.dumps({"score": 92, "hard_fail": False, "issues": []}),
                json.dumps({"facts": ["The passenger was found."]}),
            ])

        async def complete(self, role, system, user, max_output_tokens=None):
            if "IR_FIRST_SHORT_PLANNING_V2" in user:
                self.roles.append(role)
                self.systems.append(system)
                return ModelResult(json.dumps({
                    "version": 2,
                    "initial_state": "The investigator enters the locked carriage.",
                    "segments": [{
                        "kind": "terminal", "segment": 1,
                        "title": "The locked carriage",
                        "events": [{
                            "formal_event_ordinal": 1,
                            "narrative": (
                                "The investigator follows the physical evidence, resists "
                                "the conductor's deception, finds the passenger, and exposes "
                                "the method and cost of the disappearance."
                            ),
                        }],
                    }],
                }), {"role": role, "model_name": f"fake-{role}"})
            if "SHORT_PLAN_ADAPTATION_REVIEW_V2" in user:
                authority = user.split(
                    "EXPECTED AUTHORITY SHA256: ", 1,
                )[1].splitlines()[0]
                planning_sha = user.split(
                    "EXPECTED PLANNING SHA256: ", 1,
                )[1].splitlines()[0]
                segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
                expected = json.loads(
                    user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
                )
                candidates = json.loads(
                    user.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1].split(
                        "\n\nCURRENT ACCEPTED PLAN SEGMENT:", 1,
                    )[0]
                )
                evidence_id = next(iter(candidates))
                return ModelResult(json.dumps({
                    "authority_sha256": authority,
                    "planning_sha256": planning_sha,
                    "segment": segment,
                    "event_reviews": [{
                        "event_id": event_id,
                        "classification": "equivalent",
                        "changed_dimensions": ["scene realization"],
                        "invariants": {field: True for field in INVARIANT_FIELDS},
                        "plan_evidence_ids": [evidence_id],
                        "plan_evidence_quote": "",
                        "reason": "The segment preserves the formal event function.",
                    } for event_id in expected],
                    "segment_order_preserved": True,
                    "formal_direction_preserved": True,
                    "summary": "The semantic plan preserves the formal event.",
                }), {"role": role, "model_name": f"fake-{role}"})
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in user:
                authority = user.split(
                    "EXPECTED AUTHORITY SHA256: ", 1,
                )[1].splitlines()[0]
                planning_sha = user.split(
                    "EXPECTED PLANNING SHA256: ", 1,
                )[1].splitlines()[0]
                segments = json.loads(
                    user.split("EXPECTED SEGMENTS:\n", 1)[1].splitlines()[0]
                )
                expected = json.loads(
                    user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
                )
                return ModelResult(json.dumps({
                    "authority_sha256": authority,
                    "planning_sha256": planning_sha,
                    "segment_numbers": segments,
                    "event_ids": expected,
                    "causal_order_preserved": True,
                    "adjacent_handoffs_preserved": True,
                    "knowledge_progression_preserved": True,
                    "relationship_progression_preserved": True,
                    "viewpoint_timeline_preserved": True,
                    "promises_ending_preserved": True,
                    "formal_direction_preserved": True,
                    "affected_segments": [],
                    "affected_event_ids": [],
                    "reason": "",
                    "summary": "The whole plan preserves formal authority.",
                }), {"role": role, "model_name": f"fake-{role}"})
            return await super().complete(
                role, system, user, max_output_tokens=max_output_tokens,
            )

    gateway = IrFirstGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    outline = (
        "# Formal Outline\n\n## Vanishing\n\n"
        "The passenger searches the locked carriage and exposes the conductor."
    )
    state = service.story_states.ensure(project.id, project.path)
    candidate = service.story_states.create_candidate(
        project.id, None, state.revision, "outline",
        hashlib.sha256(outline.encode("utf-8")).hexdigest(),
    )
    service.story_states.commit(
        candidate.id, state.revision,
        {**state.data, "outline": {"content": outline, "events": []}},
    )
    result = await service.run_short(project.id, use_crewai=False)
    run_path = project.path / "runs" / result["id"]

    assert result["status"] == "completed"
    assert (run_path / "outputs" / "planning-semantic-v2.json").is_file()
    assert (run_path / "outputs" / "planning-exit-topology-v1.json").is_file()
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == "# Final Story\nHuman, polished prose."
    assert db.get_sealed_generation_unit(result["id"], "draft_segment", "1")
    assert any(
        item["event_type"] == "planning_ir_first_compiled"
        for item in db.list_run_events(result["id"])
    )


@pytest.mark.asyncio
async def test_ir_first_initial_capacity_preflight_uses_event_owned_semantic_packets(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://primary.invalid/v1", auth_type="bearer",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="planning-model", provider_id="primary",
        display_name="Planning", model_name="planning-model",
        context_window=6_144, max_output_tokens=None,
    )
    db.save_role_binding("planning", "primary", "planning-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Production-sized IR planning", mode="short", genre="mystery",
        premise="A missing archivist leaves a sequence of contradictory records.",
        target_words=13_000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class PacketOnlyGateway:
        def __init__(self) -> None:
            self.packet_calls: list[dict] = []
            self.packet_systems: list[str] = []
            self.failed_once = False
            self.noncanonical_once = False

        async def complete(self, role, system, user, max_output_tokens=None):
            if "IR_FIRST_SHORT_PLANNING_PACKET_V2" not in user:
                raise AssertionError(
                    "the over-capacity whole semantic request reached the provider"
                )
            contract = json.loads(
                user.split("PACKET CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
            )
            self.packet_calls.append(contract)
            self.packet_systems.append(system)
            local_count = len(contract["global_event_ordinals"])
            segment = contract["global_segment"]
            if segment == 1 and not self.noncanonical_once:
                self.noncanonical_once = True
                return ModelResult(json.dumps({
                    "segment": 1,
                    "segment_map": [{
                        "segment": 1,
                        "events": contract["global_event_ordinals"],
                    }],
                }), {
                    "finish_reason": "stop", "provider_id": "primary",
                    "model_id": "planning-model", "model_name": "planning-model",
                    "input_tokens": 2400, "output_tokens": 300,
                })
            if segment == 3 and not self.failed_once:
                self.failed_once = True
                raise RuntimeError("server disconnected before terminal response")
            return ModelResult(json.dumps({
                "version": 2,
                "initial_state": (
                    f"Segment {segment} opens from the accepted predecessor state."
                ),
                "segments": [{
                    "kind": "terminal", "segment": 1,
                    "title": f"Archive turn {segment}",
                    "events": [{
                        "formal_event_ordinal": ordinal,
                        "narrative": (
                            f"The investigator executes packet event {ordinal}, meets "
                            f"specific resistance, updates knowledge, and leaves a proved "
                            f"causal result for segment {segment}."
                        ),
                    } for ordinal in range(1, local_count + 1)],
                }],
            }), {
                "finish_reason": "stop", "provider_id": "primary",
                "model_id": "planning-model", "model_name": "planning-model",
                "input_tokens": 2400, "output_tokens": 900,
            })

    gateway = PacketOnlyGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "ir-first-initial-capacity"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    formal_events = [{
        "id": f"EV-{index:08X}",
        "label": f"Formal event {index}",
        "evidence": (
            f"The investigator follows record {index}, confronts witness {index}, "
            f"changes the trust ledger, and preserves clue {index} for the ending."
        ),
    } for index in range(1, 19)]
    production_facts = [{
        "key": f"archive.fact.{index:04d}",
        "value": (
            f"第{index}份档案记录人物{index % 17}在第{index % 23}个时间点的知识、"
            f"关系、承诺与限制；该记录只能由事件{index % 18 + 1}改变。"
        ),
    } for index in range(1, 901)]
    brief = json.dumps({
        **project.metadata,
        "formal_story_facts": production_facts,
        "formal_outline_events": formal_events,
        "generation_contract": {
            "target_total_words": 13_000,
            "segment_count": 6,
        },
    }, ensure_ascii=False, indent=2)
    state = service.story_states.ensure(project.id, project.path)

    plan = await service._plan_short_ir_first(
        run_id, run_path, project,
        "必须保持人物知识、关系、承诺、事件顺序与最终结局。",
        brief, state.data, formal_events, 6, 7_200,
    )

    assert plan.count("### Segment ") == 6
    assert all(event["id"] in plan for event in formal_events)
    called_segments = [
        item["global_segment"] for item in gateway.packet_calls
    ]
    assert called_segments == sorted(called_segments)
    assert set(called_segments) == set(range(1, 7))
    assert called_segments.count(1) >= 2
    assert any(
        "previous response could not be deterministically converted" in system.lower()
        for system in gateway.packet_systems
    )
    assert called_segments.count(3) >= 2
    unique_packets = {
        (
            item["global_segment"],
            tuple(item["global_event_ordinals"]),
        ): item
        for item in gateway.packet_calls
    }
    assert sum(
        len(item["global_event_ordinals"])
        for item in unique_packets.values()
    ) == len(formal_events)
    events = db.list_run_events(run_id)
    assert any(
        item["event_type"] == "stage_capacity_split_requested" for item in events
    )
    assert any(
        item["event_type"] == "stage_capacity_split_completed" for item in events
    )

    calls_before_resume = len(gateway.packet_calls)
    resumed = await service._plan_short_ir_first(
        run_id, run_path, project,
        "必须保持人物知识、关系、承诺、事件顺序与最终结局。",
        brief, state.data, formal_events, 6, 7_200,
    )
    assert resumed == plan
    assert len(gateway.packet_calls) == calls_before_resume
    assert any(
        item["event_type"] == "planning_semantic_packet_reused"
        for item in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("target_words", [13_000, 20_000, 30_000])
async def test_short_ir_first_production_length_matrix_reaches_formal_manuscript(
    tmp_path, target_words,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="offline", name="Offline", protocol="openai",
        base_url="https://offline.invalid/v1", auth_type="bearer",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="planning-small", provider_id="offline",
        display_name="Planning Small", model_name="planning-small",
        context_window=32_768, max_output_tokens=None,
    )
    db.save_model(
        model_id="offline-large", provider_id="offline",
        display_name="Offline Large", model_name="offline-large",
        context_window=262_144, max_output_tokens=32_768,
    )
    db.save_role_binding(
        "planning", "offline", "planning-small", None, None,
    )
    for role in (
        "review", "draft", "polish", "final_review", "maintenance",
        "reader_review", "revision_plan",
    ):
        db.save_role_binding(
            role, "offline", "offline-large", None, None,
        )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title=f"Production short {target_words}", mode="short", genre="mystery",
        premise="A missing archivist leaves a complete but contradictory evidence chain.",
        target_words=target_words,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = ProductionSizedShortGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    segment_count = service._short_segment_count(target_words)
    formal_events = []
    for event_index in range(1, segment_count * 2 + 1):
        evidence_units = [
            (
                f"事件{event_index}证据单元{unit}：沈砚在地点{(event_index + unit) % 11}"
                f"核验编号{event_index:02d}-{unit:02d}的签章与时间，顾岚依据现场行动"
                f"把信任状态推进到层级{(event_index * unit) % 19}，并保留结局所需线索。"
            )
            for unit in range(1, 13)
        ]
        formal_events.append({
            "id": f"EV-{event_index:08X}",
            "label": f"档案链正式事件 {event_index}",
            "evidence": "".join(evidence_units),
        })
    initial_state = service.story_states.ensure(project.id, project.path)
    outline_authority = json.dumps(formal_events, ensure_ascii=False)
    state_candidate = service.story_states.create_candidate(
        project.id, None, initial_state.revision, "outline",
        hashlib.sha256(outline_authority.encode("utf-8")).hexdigest(),
    )
    service.story_states.commit(
        state_candidate.id, initial_state.revision,
        {
            **initial_state.data,
            "outline": {"content": "", "events": formal_events},
            "ending": {
                "surface_goal": "天亮前公开完整底账并找到失踪档案员",
                "inner_goal": "调查员接受公开真相造成的关系代价",
                "cost": "与旧同盟公开决裂",
                "final_image": "晨光照在已公开的完整底账上",
            },
            "confirmed_facts": [{
                "fact_key": "archive.deadline",
                "value": "完整底账必须在天亮前公开",
            }],
        },
    )
    result = await service.run_short(project.id, use_crewai=False)
    run_path = project.path / "runs" / result["id"]
    formal = (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    )
    report = json.loads(
        (run_path / "outputs" / "quality-report.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "completed"
    assert target_words <= effective_han_characters(formal) <= int(
        target_words * 1.20
    )
    assert report["status"] == "passed"
    assert report["terminal_reviewed_hash"] == hashlib.sha256(
        formal.encode("utf-8")
    ).hexdigest()
    assert len(gateway.packet_calls) == segment_count
    assert len(gateway.draft_segments) == segment_count
    paragraphs = [item.strip() for item in formal.split("\n\n") if item.strip()]
    assert len(paragraphs) == len(set(paragraphs))
    assert "约定在天亮前公开底账" in formal
    assert "完成先前约定" in formal
    for artifact in (
        "planning-semantic-v2.json", "short-causal-chain.json",
        "short-execution-index.json", "draft.md", "polish.md",
        "final-review-evidence.json", "quality-report.json",
    ):
        assert (run_path / "outputs" / artifact).is_file(), artifact
    event_types = [
        item["event_type"] for item in db.list_run_events(result["id"])
    ]
    assert "stage_capacity_split_requested" in event_types
    assert "planning_semantic_packets_reduced" in event_types
    assert "draft_integrity_passed" in event_types
    assert "story_state_committed" in event_types


def test_new_short_project_uses_stable_project_brief_event_authority(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Brief authority", mode="short", genre="mystery",
        premise="A witness disappears after naming the wrong suspect.",
        target_words=13_000,
    ))
    state = StoryStateStore(db).ensure(project.id, project.path).data

    first = WorkflowService._short_formal_event_authority(project, state)
    second = WorkflowService._short_formal_event_authority(project, state)

    assert first == second
    assert len(first) == 1
    assert first[0]["id"].startswith("EV-")
    assert first[0]["source"] == "project_brief"
    assert first[0]["evidence"] == project.metadata["premise"]

    changed = replace(project, metadata={
        **project.metadata,
        "premise": "A witness returns with proof that changes the accusation.",
    })
    assert WorkflowService._short_formal_event_authority(
        changed, state,
    )[0]["id"] != first[0]["id"]


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
                "### 第 1 段：调查死亡现场\n"
                "事件ID：EV-00000001\n大纲依据：主角调查朋友死亡现场。\n"
                "段首承接：朋友已经死亡，主角仍在现场寻找复活线索。\n"
                "本段事件：主角调查死亡现场，找到残缺记忆并发现仪式代价。\n"
                "段末交接：主角放下愧疚，确认无法永久复活朋友。\n\n"
                "SHORT_CAUSAL_CHAIN_JSON_START\n"
                '{"core_goal":{"content":"复活死去的朋友"},"cycles":[{"obstacle":"缺少灵魂媒介","effort":"调查死亡现场","result":"找到残缺记忆","state_change":"确认灵魂仍在"},{"obstacle":"仪式需要交换生命","effort":"寻找规则漏洞","result":"朋友暂时复活","state_change":"目标表面达成"}],"reversal":{"content":"朋友主动死亡是为了封印","prior_evidence":["死亡记录被销毁"]},"ending":{"surface_goal":"无法永久复活","inner_goal":"主角放下愧疚"},"covered_event_ids":["EV-00000001"]}'
                "\nSHORT_CAUSAL_CHAIN_JSON_END",
                "正文草稿" * 1500,
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
            if "IR_FIRST_SHORT_PLANNING_V2" in user:
                # New production planning is typed IR.  Consume the retained
                # historical Markdown fixture, then return the same semantic
                # intent through the sole current contract.
                next(self.responses)
                return ModelResult(json.dumps({
                    "version": 2,
                    "initial_state": "The friend is dead at the scene.",
                    "segments": [{
                        "kind": "terminal", "segment": 1,
                        "title": "Investigate the death scene",
                        "events": [{
                            "formal_event_ordinal": 1,
                            "narrative": (
                                "The protagonist investigates the death scene, "
                                "finds the damaged memory, proves the ritual cost, "
                                "and accepts the confirmed final loss."
                            ),
                        }],
                    }],
                }), {
                    "role": role, "model_name": f"fake-{role}",
                })
            if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
                covered = list(dict.fromkeys(
                    re.findall(r"EV-[0-9A-F]{8}", user.upper())
                ))
                return ModelResult(json.dumps({
                    "core_goal": "Revive the dead friend",
                    "opening": {"pressure": "The friend is dead"},
                    "cycles": [{
                        "obstacle": "The soul medium is missing",
                        "effort": "Investigate the death scene",
                        "result": "Recover a damaged memory",
                        "state_change": "Prove the ritual cost",
                    }],
                    "accidents": [], "reversal": {},
                    "ending": {
                        "surface_goal": "Permanent revival is impossible",
                        "inner_goal": "The protagonist releases the guilt",
                        "cost": "Accept the loss",
                    },
                    "question_chain": [], "relationship_arc": [],
                    "covered_event_ids": covered,
                }), {
                    "role": role, "model_name": f"fake-{role}",
                })
            if (
                "SHORT_EXECUTION_MANIFEST_V2" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
            ):
                return ModelResult(
                    json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False),
                    {"role": role, "model_name": f"fake-{role}"},
                )
            if (
                "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
            ):
                return ModelResult(
                    execution_manifest_receipt_from_prompt(user),
                    {"role": role, "model_name": f"fake-{role}"},
                )
            if "DRAFT_SEMANTIC_VALIDATION" in user:
                contract = json.loads(re.search(
                    r"TASK CONTRACT: (\{[^\n]+\})", user,
                ).group(1))
                prose = user.split("PROSE:\n", 1)[1]
                return ModelResult(
                    json.dumps(
                        draft_semantic_receipt(contract, prose), ensure_ascii=False,
                    ),
                    {"role": role, "model_name": f"fake-{role}"},
                )
            if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
                authority = re.search(
                    r"AUTHORITY SHA256: ([0-9a-f]{64})", user,
                ).group(1)
                draft_sha = re.search(
                    r"DRAFT SHA256: ([0-9a-f]{64})", user,
                ).group(1)
                segment_hashes = json.loads(re.search(
                    r"SEGMENT SHA256: (\[[^\n]+\])", user,
                ).group(1))
                event_ids = json.loads(re.search(
                    r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
                ).group(1))
                opening = user.split("OPENING EXCERPT: ", 1)[1].split(
                    "\nENDING EXCERPT:", 1,
                )[0]
                ending = user.split("ENDING EXCERPT: ", 1)[1]
                return ModelResult(json.dumps({
                    "authority_sha256": authority, "draft_sha256": draft_sha,
                    "segment_sha256": segment_hashes, "event_ids": event_ids,
                    "missing_event_ids": [], "duplicate_event_ids": [],
                    "out_of_order_event_ids": [], "causal_order_valid": True,
                    "continuity_valid": True, "ending_valid": True,
                    "commitments_valid": True,
                    "evidence": [
                        {"kind": "opening", "excerpt": opening[:12]},
                        {"kind": "ending", "excerpt": ending[-12:]},
                    ],
                    "summary": "全文节拍顺序和结局均已核对。",
                }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
            return ModelResult(next(self.responses), {"role": role, "model_name": f"fake-{role}"})

        async def complete_primary(self, role, system, user, **kwargs):
            return await self.complete(role, system, user, **kwargs)

    gateway = CausalGateway()
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    artifact = (project.path / "learning" / "short_causal_chain.json").read_text(encoding="utf-8")
    assert "Revive the dead friend" in artifact
    planning = project.path / "runs" / result["id"] / "outputs" / "planning.md"
    assert "SHORT_CAUSAL_CHAIN_JSON_START" not in planning.read_text(encoding="utf-8")
    causal_prompt = next(
        item for item in gateway.users
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in item
    )
    assert "opening" in causal_prompt
    assert "question_chain" in causal_prompt
    assert "relationship_arc" in causal_prompt
    assert any("Short Story Causal Chain" in system and "Revive the dead friend" in system
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
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
    )

    journal = load_project_mutation_journal(
        project_mutation_journal_path(project.path, result["id"]),
    )
    assert journal.status == "committed"
    assert [effect.kind for effect in journal.memory_effects] == [
        "chapter_index",
    ]


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
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
    )

    journal = load_project_mutation_journal(
        project_mutation_journal_path(project.path, result["id"]),
    )
    assert journal.status == "committed"
    assert [effect.kind for effect in journal.memory_effects] == ["canon_fact"]
    with db.connect() as connection:
        fact = connection.execute(
            "SELECT value, source FROM canon_facts WHERE project_id=? "
            "AND fact_key='ending' AND confirmed=1",
            (project.id,),
        ).fetchone()
    assert dict(fact) == {
        "value": "the oath is fulfilled", "source": "book-setup",
    }


@pytest.mark.asyncio
async def test_long_setup_resumes_exact_memory_projection_after_artifact_stage(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.long_workflow as workflows_module
    from novel_flywheel.project_transactions import recover_project_mutations

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long recovery", mode="long", genre="fantasy",
        premise="A durable book setup resumes exactly once.",
        target_words=100000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, SetupGateway(), SkillGate(db, SkillScanner([skill_root])),
    )
    real_complete = workflows_module.complete_project_mutation

    def interrupt_after_artifacts(*_args, **_kwargs):
        raise OSError("terminal write interrupted")

    monkeypatch.setattr(
        workflows_module, "complete_project_mutation",
        interrupt_after_artifacts,
    )
    with pytest.raises(OSError, match="terminal write interrupted"):
        await service.run_long_setup(
            project.id, use_crewai=False, run_id="long-setup-recovery",
        )
    with db.connect() as connection:
        before = connection.execute(
            "SELECT value FROM canon_facts WHERE project_id=? "
            "AND fact_key='ending' AND confirmed=1",
            (project.id,),
        ).fetchone()
    assert before is None
    assert db.get_run("long-setup-recovery")["status"] == "running"

    monkeypatch.setattr(
        workflows_module, "complete_project_mutation", real_complete,
    )
    assert recover_project_mutations(
        store, workflow="long-setup",
    ) == ["long-setup-recovery"]
    assert db.get_run("long-setup-recovery")["status"] == "completed"
    with db.connect() as connection:
        facts = connection.execute(
            "SELECT value FROM canon_facts WHERE project_id=? "
            "AND fact_key='ending' AND confirmed=1",
            (project.id,),
        ).fetchall()
    assert [row["value"] for row in facts] == ["the oath is fulfilled"]


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


@pytest.mark.asyncio
async def test_blocked_volume_preserves_published_chapter_and_memory(
    tmp_path,
) -> None:
    """Freeze the existing post-publication volume-gate business behavior."""

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Blocked volume", mode="long", genre="fantasy",
        premise="A published volume remains available for repair.",
        target_words=100_000,
    ))
    (project.path / "memory" / "volumes.json").write_text(json.dumps({
        "volumes": [{
            "number": 1, "start_chapter": 1, "end_chapter": 1,
            "goal": "Reach the gate",
        }],
    }), encoding="utf-8")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, BlockedVolumeGateway(),
        SkillGate(db, SkillScanner([skill_root])),
    )

    with pytest.raises(RuntimeError, match="Volume audit blocked"):
        await service.run_chapter(
            project.id, "Reach the gate", use_crewai=False,
            run_id="blocked-volume",
        )

    assert (project.path / "chapters" / "chapter-01.md").is_file()
    assert (project.path / "memory" / "canon.json").is_file()
    audit = json.loads(
        (project.path / "memory" / "audits" / "volume-01.json").read_text(
            encoding="utf-8",
        )
    )
    assert audit["status"] == "blocked"
    assert db.get_run("blocked-volume")["status"] == "failed"
    with db.connect() as connection:
        indexed = connection.execute(
            "SELECT content FROM chapter_search WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchall()
        state = connection.execute(
            "SELECT state_json FROM chapter_states WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchone()
    assert len(indexed) == 1
    assert json.loads(state["state_json"])["hero"]["location"] == "gate"


@pytest.mark.asyncio
async def test_long_chapter_resumes_post_commit_volume_gate_without_regeneration(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.long_workflow as workflows_module
    from novel_flywheel.project_transactions import (
        load_project_mutation_journal,
        project_mutation_journal_path,
    )

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Volume resume", mode="long", genre="fantasy",
        premise="A staged chapter resumes only its pending volume audit.",
        target_words=100_000,
    ))
    (project.path / "memory" / "volumes.json").write_text(json.dumps({
        "volumes": [{
            "number": 1, "start_chapter": 1, "end_chapter": 1,
            "goal": "Reach the gate",
        }],
    }), encoding="utf-8")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = VolumeGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    real_commit = workflows_module.commit_project_mutation_authority

    def interrupt_before_memory_projection(*_args, **_kwargs):
        raise OSError("authority commit interrupted")

    monkeypatch.setattr(
        workflows_module, "commit_project_mutation_authority",
        interrupt_before_memory_projection,
    )
    with pytest.raises(OSError, match="authority commit interrupted"):
        await service.run_chapter(
            project.id, "Reach the gate", use_crewai=False,
            run_id="volume-resume",
        )

    journal_path = project_mutation_journal_path(
        project.path, "volume-resume",
    )
    assert load_project_mutation_journal(journal_path).status == (
        "artifacts_committed"
    )
    assert db.get_run("volume-resume")["status"] == "running"
    calls_before_resume = len(gateway.roles)

    monkeypatch.setattr(
        workflows_module, "commit_project_mutation_authority", real_commit,
    )
    result = await service.run_chapter(
        project.id, "Reach the gate", use_crewai=False,
        run_id="volume-resume",
    )

    assert result["status"] == "completed"
    assert len(gateway.roles) == calls_before_resume + 1
    assert gateway.roles[-1] == "final_review"
    assert load_project_mutation_journal(journal_path).status == "committed"
    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM chapter_search WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchone()["count"] == 1
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM chapter_states WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchone()["count"] == 1


@pytest.mark.asyncio
async def test_prepublication_chapter_failure_restores_files_and_memory(
    tmp_path,
) -> None:
    """A maintenance contract failure must remain pre-publication."""

    class InvalidMaintenanceGateway(VolumeGateway):
        def __init__(self) -> None:
            super().__init__()
            responses = list(self.responses)
            invalid = json.dumps({"state": {"hero": {"location": "gate"}}})
            responses[6:] = [invalid] * 4
            self.responses = iter(responses)

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Pre-publication failure", mode="long", genre="fantasy",
        premise="Invalid maintenance cannot publish the chapter.",
        target_words=100_000,
    ))
    canon_path = project.path / "memory" / "canon.json"
    canon_before = canon_path.read_bytes() if canon_path.is_file() else None
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, InvalidMaintenanceGateway(),
        SkillGate(db, SkillScanner([skill_root])),
    )

    with pytest.raises(ValueError, match="authoritative domain contract"):
        await service.run_chapter(
            project.id, "Reach the gate", use_crewai=False,
            run_id="invalid-maintenance",
        )

    assert not (project.path / "chapters" / "chapter-01.md").exists()
    assert (
        canon_path.read_bytes() if canon_path.is_file() else None
    ) == canon_before
    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM chapter_search WHERE project_id=?",
            (project.id,),
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM chapter_states WHERE project_id=?",
            (project.id,),
        ).fetchone()["count"] == 0


class RecordingGateway:
    def __init__(self, responses) -> None:
        self.roles = []
        self.calls = []
        self.responses = iter(responses)

    async def complete(self, role, system, user, max_output_tokens=None):
        self.roles.append(role)
        self.calls.append({"role": role, "system": system, "user": user})
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            legacy = next(self.responses)
            if str(legacy).strip() != "# Plan":
                return ModelResult(
                    str(legacy),
                    {"role": role, "model_name": f"fake-{role}"},
                )
            count_match = re.search(r"SEGMENT COUNT:\s*(\d+)", user)
            count = int(count_match.group(1)) if count_match else 1
            event_ids = list(dict.fromkeys(
                re.findall(r"EV-[0-9A-F]{8}", user.upper())
            ))
            event_count = max(1, len(event_ids))
            segments = []
            for index in range(count):
                ordinal = min(
                    event_count,
                    (index * event_count) // count + 1,
                )
                segments.append({
                    "kind": "terminal" if index + 1 == count else "continuation",
                    "segment": index + 1,
                    "title": f"验收事件组 {index + 1}",
                    "events": [{
                        "formal_event_ordinal": ordinal,
                        "narrative": (
                            "执行者完成当前正式事件中的受阻行动，形成可验证结果，"
                            "推进人物状态并保留既定因果与结局。"
                        ),
                    }],
                    **({
                        "exit_state": "当前事件已完成，人物位置、行动、关系和知识均可承接。",
                    } if index + 1 < count else {}),
                })
            return ModelResult(json.dumps({
                "version": 2,
                "initial_state": "故事在正式事件入口开始，人物与已知信息保持既定状态。",
                "segments": segments,
            }, ensure_ascii=False), {
                "role": role, "model_name": f"fake-{role}",
            })
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return ModelResult(
                json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return ModelResult(
                execution_manifest_receipt_from_prompt(user),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return ModelResult(
                json.dumps(draft_semantic_receipt(contract, prose), ensure_ascii=False),
                {"role": role, "model_name": f"fake-{role}"},
            )
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
            draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
            segments = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", user,
            ).group(1))
            events = json.loads(re.search(
                r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
            ).group(1))
            opening = user.split("OPENING EXCERPT: ", 1)[1].split(
                "\nENDING EXCERPT:", 1,
            )[0]
            ending = user.split("ENDING EXCERPT: ", 1)[1]
            return ModelResult(json.dumps({
                "authority_sha256": authority, "draft_sha256": draft_sha,
                "segment_sha256": segments, "event_ids": events,
                "missing_event_ids": [], "duplicate_event_ids": [],
                "out_of_order_event_ids": [], "causal_order_valid": True,
                "continuity_valid": True, "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"kind": "opening", "excerpt": opening[:12]},
                    {"kind": "ending", "excerpt": ending[-12:]},
                ],
                "summary": "全文节拍顺序、连续性和结局均已核对。",
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            covered_event_ids = list(dict.fromkeys(
                re.findall(r"EV-[0-9A-F]{8}", user.upper())
            ))
            return ModelResult(json.dumps({
                "core_goal": "完成正式规划中的目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成正式结局",
                "covered_event_ids": covered_event_ids,
            }, ensure_ascii=False), {"role": role, "model_name": f"fake-{role}"})
        text = next(self.responses)
        if role == "planning" and text.strip() == "# Plan" and '"segment_count"' in user:
            count_match = re.search(r'"segment_count"\s*:\s*(\d+)', user)
            count = int(count_match.group(1)) if count_match else 1
            event_ids = list(dict.fromkeys(
                re.findall(r"EV-[0-9A-F]{8}", user.upper())
            )) or [f"EV-{index:08X}" for index in range(1, count + 1)]
            groups = [
                [event_ids[min(index, len(event_ids) - 1)]]
                for index in range(count)
            ]
            text = complete_plan_for_event_groups(groups)
        return ModelResult(text, {"role": role, "model_name": f"fake-{role}"})

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


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
    with db.connect() as connection:
        checkpoint = connection.execute(
            "SELECT status, output_sha256 FROM workflow_node_checkpoints "
            "WHERE run_id=? AND node_key=?",
            ("fallback-log", "polish"),
        ).fetchone()
    assert checkpoint["status"] == "generated_complete"
    assert len(checkpoint["output_sha256"]) == 64


@pytest.mark.asyncio
async def test_stage_accepts_complete_output_limited_receipt_without_retry(tmp_path) -> None:
    payload = json.dumps({"status": "complete", "items": [1, 2, 3]})

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            return ModelResult(payload, {
                "role": role,
                "model_name": "limit-model",
                "finish_reason": "max_tokens",
            })

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Complete at limit", mode="short", genre="romance",
        premise="A complete receipt reaches validation.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "complete-at-limit"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    result = await service._stage(
        run_id, run_path, project, "review", "constraints", "receipt request",
        suffix="-complete-at-limit",
        allow_tools=False,
        completion_check=lambda value: value == payload,
    )

    assert result == payload
    assert result.receipt["completion_status"] == "complete_at_limit"
    assert gateway.calls == 1
    assert any(
        event["event_type"] == "output_limit_complete"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_stage_rejects_truncated_output_limited_receipt_without_commit(tmp_path) -> None:
    complete = json.dumps({"status": "complete", "items": [1, 2, 3]})
    partial = complete[:-1]

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            return ModelResult(partial, {
                "role": role,
                "model_name": "limit-model",
                "finish_reason": "max_tokens",
            })

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Truncated at limit", mode="short", genre="romance",
        premise="A partial receipt never becomes authority.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "truncated-at-limit"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    with pytest.raises(IncompleteModelOutputError):
        await service._stage(
            run_id, run_path, project, "review", "constraints", "receipt request",
            suffix="-truncated-at-limit",
            allow_tools=False,
            completion_check=lambda value: value == complete,
        )

    assert gateway.calls == 2
    assert not (
        run_path / "outputs" / "review-truncated-at-limit.md"
    ).exists()
    with db.connect() as connection:
        checkpoint = connection.execute(
            "SELECT status, output_sha256 FROM workflow_node_checkpoints "
            "WHERE run_id=? AND node_key=?",
            (run_id, "review-truncated-at-limit"),
        ).fetchone()
    assert checkpoint["status"] == "failed"
    assert checkpoint["output_sha256"] == ""


def test_interrupted_formal_promotion_rolls_back_when_story_state_not_committed(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Promotion rollback", mode="short", genre="romance",
        premise="Interrupted promotion restores authority.", target_words=6000,
    ))
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    run_id = "promotion-rollback"
    db.create_run(run_id, project.id, "short-story", status="failed")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    formal = [
        project.path / "manuscript" / "story.md",
        project.path / "chapters" / "chapter-01.md",
        project.path / "memory" / "canon.json",
    ]
    old_values = ["old story", "old chapter", '{"facts": []}']
    new_values = ["new story", "new chapter", '{"facts": [{"value": "new"}]}']
    for path, value in zip(formal, old_values, strict=True):
        atomic_write(path, value)
    state = service.story_states.ensure(project.id, project.path)
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / "promotion-rollback",
        formal,
    )
    candidate = service.story_states.create_candidate(
        project.id, run_id, state.revision, "polish",
        hashlib.sha256(new_values[0].encode("utf-8")).hexdigest(),
    )
    for path, value in zip(formal, new_values, strict=True):
        atomic_write(path, value)
    journal_path = run_path / "outputs" / "formal-promotion-journal.json"
    atomic_write(journal_path, json.dumps({
        "version": 1,
        "status": "files_written",
        "run_id": run_id,
        "candidate_id": candidate.id,
        "base_revision": state.revision,
        "target_revision": state.revision + 1,
        "snapshot_path": snapshot.snapshot_root.relative_to(project.path).as_posix(),
        "files": [{
            "path": path.relative_to(project.path).as_posix(),
            "new_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        } for path, value in zip(formal, new_values, strict=True)],
    }, ensure_ascii=False))

    recover_legacy_short_formal_promotions(db, service.story_states, project)

    assert [path.read_text(encoding="utf-8") for path in formal] == old_values
    assert service.story_states.get_candidate(candidate.id).status == "rejected"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] \
        == "rolled_back_recovered"
    assert not snapshot.snapshot_root.exists()


def test_interrupted_formal_promotion_finalizes_when_story_state_committed(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Promotion finalize", mode="short", genre="romance",
        premise="Committed promotion survives process exit.", target_words=6000,
    ))
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    run_id = "promotion-finalize"
    db.create_run(run_id, project.id, "short-story", status="failed")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    formal = [
        project.path / "manuscript" / "story.md",
        project.path / "chapters" / "chapter-01.md",
        project.path / "memory" / "canon.json",
    ]
    for path, value in zip(formal, ["old story", "old chapter", '{"facts": []}'], strict=True):
        atomic_write(path, value)
    state = service.story_states.ensure(project.id, project.path)
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / "promotion-finalize",
        formal,
    )
    new_values = ["new story", "new chapter", '{"facts": [{"value": "new"}]}']
    candidate = service.story_states.create_candidate(
        project.id, run_id, state.revision, "polish",
        hashlib.sha256(new_values[0].encode("utf-8")).hexdigest(),
    )
    for path, value in zip(formal, new_values, strict=True):
        atomic_write(path, value)
    committed = service.story_states.commit(
        candidate.id, state.revision,
        {**state.data, "manuscript_revision": 1},
    )
    journal_path = run_path / "outputs" / "formal-promotion-journal.json"
    atomic_write(journal_path, json.dumps({
        "version": 1,
        "status": "files_written",
        "run_id": run_id,
        "candidate_id": candidate.id,
        "base_revision": state.revision,
        "target_revision": committed.revision,
        "snapshot_path": snapshot.snapshot_root.relative_to(project.path).as_posix(),
        "files": [{
            "path": path.relative_to(project.path).as_posix(),
            "new_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        } for path, value in zip(formal, new_values, strict=True)],
    }, ensure_ascii=False))

    recover_legacy_short_formal_promotions(db, service.story_states, project)

    assert [path.read_text(encoding="utf-8") for path in formal] == new_values
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] \
        == "committed_recovered"
    assert not snapshot.snapshot_root.exists()


def test_interrupted_formal_promotion_repairs_files_when_story_state_committed(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Promotion repair", mode="short", genre="romance",
        premise="Committed promotion repairs partial formal files.", target_words=6000,
    ))
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    run_id = "promotion-repair"
    db.create_run(run_id, project.id, "short-story", status="failed")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    formal = [
        project.path / "manuscript" / "story.md",
        project.path / "chapters" / "chapter-01.md",
        project.path / "memory" / "canon.json",
    ]
    for path, value in zip(formal, ["old story", "old chapter", '{"facts": []}'], strict=True):
        atomic_write(path, value)
    state = service.story_states.ensure(project.id, project.path)
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / "promotion-repair",
        formal,
    )
    new_values = ["new story", "new chapter", '{"facts": [{"value": "new"}]}']
    candidate = service.story_states.create_candidate(
        project.id, run_id, state.revision, "polish",
        hashlib.sha256(new_values[0].encode("utf-8")).hexdigest(),
    )
    payload_root = run_path / "outputs" / "formal-promotion-payload"
    files = []
    for index, (path, value) in enumerate(zip(formal, new_values, strict=True)):
        atomic_write(path, value)
        recovery_path = payload_root / f"{index:02d}-{path.name}"
        atomic_write(recovery_path, value)
        files.append({
            "path": path.relative_to(project.path).as_posix(),
            "new_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "recovery_path": recovery_path.relative_to(project.path).as_posix(),
        })
    committed = service.story_states.commit(
        candidate.id, state.revision,
        {**state.data, "manuscript_revision": 1},
    )
    atomic_write(formal[1], "partial chapter")
    journal_path = run_path / "outputs" / "formal-promotion-journal.json"
    atomic_write(journal_path, json.dumps({
        "version": 1,
        "status": "files_written",
        "run_id": run_id,
        "candidate_id": candidate.id,
        "base_revision": state.revision,
        "target_revision": committed.revision,
        "snapshot_path": snapshot.snapshot_root.relative_to(project.path).as_posix(),
        "files": files,
    }, ensure_ascii=False))

    recover_legacy_short_formal_promotions(db, service.story_states, project)

    assert [path.read_text(encoding="utf-8") for path in formal] == new_values
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] \
        == "committed_repaired"
    assert not snapshot.snapshot_root.exists()


def test_interrupted_legacy_formal_promotion_preserves_evidence_on_hash_mismatch(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Legacy promotion mismatch", mode="short", genre="romance",
        premise="Legacy recovery must fail closed without losing evidence.",
        target_words=6000,
    ))
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    run_id = "promotion-legacy-mismatch"
    db.create_run(run_id, project.id, "short-story", status="failed")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    formal = [
        project.path / "manuscript" / "story.md",
        project.path / "chapters" / "chapter-01.md",
        project.path / "memory" / "canon.json",
    ]
    old_values = ["old story", "old chapter", '{"facts": []}']
    new_values = ["new story", "new chapter", '{"facts": [{"value": "new"}]}']
    for path, value in zip(formal, old_values, strict=True):
        atomic_write(path, value)
    state = service.story_states.ensure(project.id, project.path)
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / "promotion-legacy-mismatch",
        formal,
    )
    candidate = service.story_states.create_candidate(
        project.id, run_id, state.revision, "polish",
        hashlib.sha256(new_values[0].encode("utf-8")).hexdigest(),
    )
    for path, value in zip(formal, new_values, strict=True):
        atomic_write(path, value)
    committed = service.story_states.commit(
        candidate.id, state.revision,
        {**state.data, "manuscript_revision": 1},
    )
    atomic_write(formal[1], "partial chapter")
    journal_path = run_path / "outputs" / "formal-promotion-journal.json"
    atomic_write(journal_path, json.dumps({
        "version": 1,
        "status": "files_written",
        "run_id": run_id,
        "candidate_id": candidate.id,
        "base_revision": state.revision,
        "target_revision": committed.revision,
        "snapshot_path": snapshot.snapshot_root.relative_to(project.path).as_posix(),
        "files": [{
            "path": path.relative_to(project.path).as_posix(),
            "new_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        } for path, value in zip(formal, new_values, strict=True)],
    }, ensure_ascii=False))

    with pytest.raises(RuntimeError, match="缺少确定性恢复载荷"):
        recover_legacy_short_formal_promotions(
            db, service.story_states, project,
        )

    assert formal[1].read_text(encoding="utf-8") == "partial chapter"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] \
        == "files_written"
    assert snapshot.snapshot_root.exists()


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
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return ModelResult(json.dumps(
                draft_semantic_receipt(contract, prose), ensure_ascii=False,
            ), {
                "role": role, "model_name": f"fake-{role}", "finish_reason": "stop",
            })
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
            draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
            segments = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", user,
            ).group(1))
            events = json.loads(re.search(
                r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
            ).group(1))
            opening = user.split("OPENING EXCERPT: ", 1)[1].split("\nENDING EXCERPT:", 1)[0]
            ending = user.split("ENDING EXCERPT: ", 1)[1]
            return ModelResult(json.dumps({
                "authority_sha256": authority, "draft_sha256": draft_sha,
                "segment_sha256": segments, "event_ids": events,
                "missing_event_ids": [], "duplicate_event_ids": [],
                "out_of_order_event_ids": [], "causal_order_valid": True,
                "continuity_valid": True, "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"kind": "opening", "excerpt": opening[:12]},
                    {"kind": "ending", "excerpt": ending[-12:]},
                ],
                "summary": "全文事件顺序、连续性和结局均有分段证据。",
            }, ensure_ascii=False), {
                "role": role, "model_name": f"fake-{role}", "finish_reason": "stop",
            })
        number = sum(call["role"] == "draft" for call in self.calls)
        return ModelResult(f"第{number}段" + chr(0x4e00 + number) * 2500, {
            "role": role, "model_name": f"fake-{role}", "finish_reason": "stop",
        })

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


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
    assert gateway.roles.count("reader_review") == 2
    assert gateway.roles.count("review") == 6
    events = db.list_run_events(result["id"])
    fallback = next(item for item in events if item["event_type"] == "reader_fallback")
    assert fallback["severity"] == "warning"
    assert fallback["metadata"]["failed_role"] == "reader_review"


@pytest.mark.asyncio
async def test_short_story_retries_reader_review_without_trusting_semantic_rewrap(tmp_path) -> None:
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
        quality_review(), "# Polish", quality_review(),
        json.dumps({"facts": []}),
    ])
    service = WorkflowService(db, store, gateway, SkillGate(db, SkillScanner([skill_root])))

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    events = db.list_run_events(result["id"])
    assert not any(item["event_type"] == "reader_fallback" for item in events)
    repaired = next(item for item in events if item["event_type"] == "reader_review_repaired")
    assert repaired["metadata"]["strategy"] == "shared_same_task_contract_retry"


def test_whole_story_obligation_catalog_binds_beats_and_planning_events(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Catalog", mode="short", genre="science-fiction",
        premise="A reactor deadline exposes a lie.", target_words=10000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("catalog", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "catalog"
    (run_path / "outputs").mkdir(parents=True)
    plan = complete_plan_for_event_groups([
        ["EV-00000001"], ["EV-00000002"],
        ["EV-00000003"], ["EV-00000004"],
    ])
    service._persist_short_planning_ir(run_path, plan, 4)
    manifest = write_test_execution_manifest(
        service, project, run_path, "constraints", plan, 4,
    )
    beat_ids = [beat.beat_id for beat in manifest.beats]

    catalog = service._whole_story_obligation_catalog(run_path, beat_ids)

    assert catalog["version"] == "whole-story-obligation-catalog-v2"
    assert catalog["beat_ids"] == beat_ids
    assert catalog["source_event_ids"] == [
        "EV-00000001", "EV-00000002", "EV-00000003", "EV-00000004",
    ]
    first_beat = catalog["beat_obligations"][0]
    assert first_beat["beat_id"] == manifest.beats[0].beat_id
    assert first_beat["source_event_id"] == manifest.beats[0].source_event_id
    assert first_beat["action"] == manifest.beats[0].action
    assert first_beat["postconditions"] == list(manifest.beats[0].postconditions)
    first_event = catalog["event_obligations"][0]
    assert first_event["beat_ids"] == [manifest.beats[0].beat_id]
    assert first_event["planning_bindings"][0]["segment"] == 1
    assert first_event["planning_bindings"][0]["handoff"]
    assert catalog["catalog_sha256"] == canonical_sha256({
        key: value for key, value in catalog.items() if key != "catalog_sha256"
    })

    with pytest.raises(DraftReceiptProtocolError):
        service._whole_story_obligation_catalog(run_path, beat_ids[:-1])

    planning_path = run_path / "outputs" / "planning-ir.json"
    envelope = json.loads(planning_path.read_text(encoding="utf-8"))
    extra = dict(envelope["document"]["segments"][-1])
    extra.update({
        "segment": 5,
        "heading": "unexpected planning authority",
        "event_ids": ["EV-FFFFFFFF"],
        "source_sha256": "f" * 64,
    })
    envelope["document"]["segments"].append(extra)
    tampered_document = PlanningDocumentIR.model_validate(envelope["document"])
    envelope["authority_sha256"] = tampered_document.authority_sha256
    planning_path.write_text(
        json.dumps(envelope, ensure_ascii=False), encoding="utf-8",
    )
    with pytest.raises(DraftReceiptProtocolError):
        service._whole_story_obligation_catalog(run_path, beat_ids)


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

    plan = complete_plan_for_event_groups([
        [f"EV-{index:08X}"] for index in range(1, 9)
    ])
    base_constraints = (
        "confirmed constraints\n\n# Short Story Causal Chain\n\n"
        "a historical accepted chain is already part of the project authority"
    )
    constraints = (
        base_constraints
        + "\n\n# Short Story Causal Chain\n\ncurrent run causal authority"
    )
    base_constraints_sha256 = hashlib.sha256(
        base_constraints.encode("utf-8")
    ).hexdigest()
    manifest = write_test_execution_manifest(
        service, project, run_path, constraints, plan, 8,
    )
    draft = await service._draft_short_in_segments(
        "segmented", run_path, project, constraints, plan,
        base_constraints_sha256=base_constraints_sha256,
    )

    assert WorkflowService._short_segment_count(20000) == 8
    assert gateway.roles.count("draft") == 8
    assert gateway.roles.count("review") == 9
    assert all(
        "不要提问" in call["user"]
        for call in gateway.calls if call["role"] == "draft"
    )
    assert len(WorkflowService._split_segments(draft)) == 8
    assert (run_path / "outputs" / "draft.md").read_text(encoding="utf-8") == draft
    assignments = json.loads(
        (run_path / "outputs" / "segment-events.json").read_text(encoding="utf-8"),
    )["segments"]
    assert assignments[0]["event_ids"] == [manifest.segments[0].beat_ids[0]]
    assert assignments[-1]["event_ids"] == [manifest.segments[-1].beat_ids[0]]
    integrity = json.loads(
        (run_path / "outputs" / "draft-integrity.json").read_text(encoding="utf-8"),
    )
    assert integrity["status"] == "passed"
    assert integrity["authority_sha256"]
    assert integrity["plan_sha256"] == hashlib.sha256(plan.encode("utf-8")).hexdigest()
    assert integrity["constraints_sha256"] == hashlib.sha256(
        constraints.encode("utf-8")
    ).hexdigest()
    assert integrity["base_constraints_sha256"] == base_constraints_sha256
    assert integrity["story_state_sha256"]
    assert integrity["draft_sha256"] == hashlib.sha256(draft.encode("utf-8")).hexdigest()
    assert integrity["expected_event_ids"] == [
        beat_id for segment in manifest.segments for beat_id in segment.beat_ids
    ]
    assert integrity["accepted_event_ids"] == integrity["expected_event_ids"]
    assert len(integrity["segments"]) == 8
    assert all(item["text_sha256"] for item in integrity["segments"])
    assert len(integrity["semantic_segment_receipts"]) == 8
    assert integrity["whole_semantic_receipt"]["ending_valid"] is True


@pytest.mark.asyncio
async def test_draft_semantic_gate_rejects_a_clean_segment_that_omits_its_event(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Semantic omission", mode="short", genre="suspense",
        premise="Clean prose must still realize its formal event.", target_words=2500,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway(SegmentGateway):
        async def complete(self, role, system, user, max_output_tokens=None):
            result = await super().complete(role, system, user, max_output_tokens)
            if "DRAFT_SEMANTIC_VALIDATION" in user:
                payload = json.loads(result.text)
                payload["beat_receipts"][0]["actor_action_valid"] = False
                return ModelResult(json.dumps(payload, ensure_ascii=False), result.receipt)
            return result

    service = WorkflowService(
        db, store, Gateway(), SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("semantic-omission", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "semantic-omission"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    plan = (
        "### 第一段：账本出现\n事件ID：EV-00000001\n大纲依据：花穗取得账本\n"
        "段首承接：花穗进入前厅。\n本段事件：花穗取得账本。\n"
        "段末交接：花穗拿着账本离开前厅。\n" + "细节" * 60
    )
    write_test_execution_manifest(
        service, project, run_path, "constraints", plan, 1,
    )

    with pytest.raises(ValueError, match="语义完整性"):
        await service._draft_short_in_segments(
            "semantic-omission", run_path, project, "constraints", plan,
        )

    assert not (run_path / "outputs" / "draft.md").exists()
    assert not (run_path / "outputs" / "draft-checkpoints" / "segment-01.json").exists()


@pytest.mark.asyncio
async def test_draft_semantic_failure_rewrites_same_scope_and_accepts_second_version(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Semantic rewrite", mode="short", genre="suspense",
        premise="A segment needs one complete rewrite.", target_words=2500,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.drafts = 0
            self.reviews = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            if role == "draft":
                self.drafts += 1
                return ModelResult(
                    ("旧" if self.drafts == 1 else "新") * 2500,
                    {"model_name": "draft", "finish_reason": "stop"},
                )
            self.reviews += 1
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            receipt = draft_semantic_receipt(contract, prose)
            receipt["exit"]["satisfied"] = self.reviews > 1
            return ModelResult(
                json.dumps(receipt, ensure_ascii=False),
                {"model_name": "review", "finish_reason": "stop"},
            )

    gateway = expose_test_primary_route(Gateway())
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("semantic-rewrite", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "semantic-rewrite"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01", parent_task_id="", depth=0,
        target_han=2500, event_ids=("EV-00000001",),
        scope="只写核实身份", entry_state="花穗仍在前厅",
        exit_requirement="核实身份的人已经出发",
        execution_manifest_sha256="b" * 64,
        beat_ids=("EV-00000001/01",), viewpoint="third-limited",
    )
    receipts = []

    result = await service._draft_short_segment_task(
        "semantic-rewrite", run_path, project, "必须保持第三人称限知视角。",
        "当前段正式资料", suffix="-part-01", target=2500,
        previous_parts=[], event_ids=["EV-00000001/01"], contract=contract,
        semantic_all_event_ids=["EV-00000001/01"],
        semantic_receipt_sink=receipts,
    )

    assert result.startswith("新")
    assert gateway.drafts == gateway.reviews == 2
    assert len(receipts) == 1
    assert any(
        item["event_type"] == "draft_task_scope_retry"
        for item in db.list_run_events("semantic-rewrite")
    )


@pytest.mark.asyncio
async def test_second_split_child_never_starts_before_first_child_semantic_acceptance(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Sibling authority", mode="short", genre="suspense",
        premise="The second child needs a validated first-child exit.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append({"role": role, "user": user})
            if role == "draft":
                if "内部子任务 1/2" in user:
                    text = "甲" * 500
                elif "内部子任务 2/2" in user:
                    text = "乙" * 500
                else:
                    text = "短" * 100
                return ModelResult(text, {
                    "role": role, "model_name": "draft", "finish_reason": "stop",
                })
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", user,
            ).group(1))
            prose = user.split("PROSE:\n", 1)[1]
            evidence = prose[:12]
            return ModelResult(json.dumps({
                "authority_sha256": contract["authority_sha256"],
                "execution_manifest_sha256": contract[
                    "execution_manifest_sha256"
                ],
                "task_id": contract["task_id"],
                "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
                "beat_receipts": [{
                    "beat_id": beat_id,
                    "evidence": evidence,
                    "actor_action_valid": False,
                    "actor_action_evidence": evidence,
                    "state_valid": True,
                    "state_evidence": evidence,
                    "scene_order_valid": True,
                    "scene_order_evidence": evidence,
                } for beat_id in contract["beat_ids"]],
                "entry": {"satisfied": True, "evidence": evidence},
                "exit": {"satisfied": True, "evidence": prose[-12:]},
                "outside_beat_ids": [],
                "future_beat_ids": [],
                "viewpoint_valid": True,
                "viewpoint_evidence": evidence,
                "causal_order_valid": True,
                "causal_order_evidence": evidence,
                "summary": "第一子任务没有证明正式事件。",
            }, ensure_ascii=False), {
                "role": role, "model_name": "review", "finish_reason": "stop",
            })

    gateway = expose_test_primary_route(Gateway())
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("sibling-authority", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "sibling-authority"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    plan = (
        "### 第一段：两步调查\n事件ID：EV-00000001、EV-00000002\n"
        "大纲依据：取得账本并质问管事\n段首承接：花穗进入前厅。\n"
        "本段事件：花穗取得账本，随后质问管事。\n"
        "段末交接：花穗带着证据离开。\n" + "细节" * 60
    )
    write_test_execution_manifest(
        service, project, run_path, "constraints", plan, 1,
    )

    with pytest.raises(ValueError, match="语义完整性"):
        await service._draft_short_in_segments(
            "sibling-authority", run_path, project, "constraints", plan,
        )

    draft_prompts = [call["user"] for call in gateway.calls if call["role"] == "draft"]
    assert any("内部子任务 1/2" in prompt for prompt in draft_prompts)
    assert not any("内部子任务 2/2" in prompt for prompt in draft_prompts)


def test_single_segment_plan_cannot_bypass_the_typed_planning_contract() -> None:
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {},
        "# Accepted plan\nA complete-looking but untyped prose plan." + "x" * 120,
        1,
    )

    assert any("ID" in issue and "handoff" not in issue.lower() for issue in issues)


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
        event_ids=["EV-00000001", "EV-00000002"],
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
    assert [
        int(re.search(r"本次唯一字数目标：约 (\d+) 个正文汉字", call).group(1))
        for call in gateway.calls
    ] == [1000, 500, 500]
    assert all(
        len(re.findall(r"本次唯一字数目标：约 \d+ 个正文汉字", call)) == 1
        for call in gateway.calls
    )
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
    completed = next(
        item for item in db.list_run_events("normal-short")
        if item["event_type"] == "draft_task_split_completed"
    )
    assert completed["metadata"]["child_targets"] == [500, 500]
    assert completed["metadata"]["child_event_ids"] == [
        ["EV-00000001", "EV-00000002"],
        ["EV-00000003", "EV-00000004"],
    ]
    assert completed["metadata"]["combined_sha256"] == hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_single_event_underlength_retries_same_scope_instead_of_fake_split(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Indivisible event", mode="short", genre="suspense",
        premise="One event needs fuller development.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            count = 160 if len(self.calls) == 1 else 1000
            return ModelResult("甲" * count, {
                "role": role, "model_name": "scope-retry", "finish_reason": "stop",
                "transport_complete": True,
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("single-event", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "single-event"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "single-event", run_path, project, "constraints", "完成唯一事件",
        suffix="-part-01", target=1000, previous_parts=[],
        event_ids=["EV-00000001"],
    )

    assert text == "甲" * 1000
    assert len(gateway.calls) == 2
    assert all("EV-00000001" in call for call in gateway.calls)
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("single-event")
    )


@pytest.mark.asyncio
async def test_normal_overlength_leaf_is_retried_with_the_same_fresh_target(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Overlong leaf", mode="short", genre="suspense",
        premise="A provider follows a stale parent target.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            count = 1600 if len(self.calls) == 1 else 1000
            return ModelResult("乙" * count, {
                "role": role, "model_name": "stale-target", "finish_reason": "end_turn",
                "transport_complete": True,
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("overlong-leaf", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "overlong-leaf"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "overlong-leaf", run_path, project, "constraints", "完成本段事件",
        suffix="-part-02", target=1000, previous_parts=[],
        event_ids=["EV-00000001", "EV-00000002"],
    )

    assert text == "乙" * 1000
    assert len(gateway.calls) == 2
    assert all(
        re.findall(r"本次唯一字数目标：约 (\d+) 个正文汉字", call) == ["1000"]
        for call in gateway.calls
    )
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("overlong-leaf")
    )


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
            text = "正文草稿" if len(self.calls) == 1 else "甲" * 1000
            receipt = {
                "role": role, "model_name": "legacy-without-terminal-state",
            }
            if len(self.calls) > 1:
                receipt["finish_reason"] = "stop"
            return ModelResult(text, receipt)

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

    assert text == "甲" * 1000
    assert len(gateway.calls) == 2
    assert all("CURRENT_TASK_CONTRACT" in call for call in gateway.calls)
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("unknown-terminal")
    )


@pytest.mark.asyncio
async def test_zero_event_scope_retries_in_place_instead_of_creating_empty_children(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="No fake event split", mode="short", genre="suspense",
        premise="Legacy authority has no stable event IDs.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(user)
            if len(self.calls) == 1:
                return ModelResult("甲" * 100, {
                    "role": role, "model_name": "legacy", "finish_reason": "stop",
                })
            return ModelResult("甲" * 1000, {
                "role": role, "model_name": "legacy", "finish_reason": "stop",
            })

    gateway = Gateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("no-empty-split", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "no-empty-split"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    text = await service._draft_short_segment_task(
        "no-empty-split", run_path, project, "constraints", "写完本段事件",
        suffix="-part-01", target=1000, previous_parts=[], event_ids=[],
    )

    assert text == "甲" * 1000
    assert len(gateway.calls) == 2
    assert not any(
        item["event_type"] == "draft_task_split"
        for item in db.list_run_events("no-empty-split")
    )


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
    plan = complete_plan_for_event_groups([["EV-00000001"]])
    with pytest.raises(ValueError, match="因果链未通过"):
        await service._ensure_short_causal_chain(
            "causal-pending", run_path, project, "constraints",
            plan, [], None,
        )

    index = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(encoding="utf-8")
    )
    assert index["status"] == "causal_pending"
    assert not (run_path / "outputs" / "short-causal-chain.json").exists()


@pytest.mark.asyncio
async def test_causal_chain_capacity_split_merges_event_owned_packets_and_reuses_checkpoints(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Split causal chain", mode="short", genre="suspense",
        premise="A long plan needs an event-owned causal chain.", target_words=3000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("causal-split", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "causal-split"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = [f"EV-{index:08X}" for index in range(1, 5)]
    formal_events = [{
        "id": event_id,
        "label": f"正式事件 {index}",
        "evidence": f"花穗完成正式事件 {index} 并产生下一步状态。",
    } for index, event_id in enumerate(event_ids, 1)]
    plan = "\n\n".join(
        f"### 第 {index} 段：事件{index}\n事件ID：{event_id}\n"
        f"大纲依据：花穗完成正式事件 {index} 并产生下一步状态。\n"
        f"段首承接：花穗承接事件 {index} 的入口状态。\n"
        f"本段事件：花穗推进事件 {index}，遇到阻碍并形成结果。\n"
        f"段末交接：事件 {index} 的结果交给下一段。"
        for index, event_id in enumerate(event_ids, 1)
    )
    packet_calls: list[list[str]] = []
    packet_topology: list[tuple[bool, bool]] = []
    root_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal root_calls
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            root_calls += 1
            assert kwargs.get("route_capacity_guard") is True
            return await kwargs["capacity_splitter"]({
                "pressure": "split",
                "estimated_input_tokens": 25_000,
                "authority_input_tokens": 22_000,
                "output_reserve": 3_000,
                "context_window": 32_768,
            })
        expected = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nFORMAL EVENTS:", 1,
            )[0]
        )
        packet_calls.append(expected)
        packet_topology.append((
            prompt.split("OWNS OPENING: ", 1)[1].splitlines()[0] == "true",
            prompt.split("OWNS ENDING: ", 1)[1].splitlines()[0] == "true",
        ))
        packet_number = len(packet_calls)
        return json.dumps({
            "core_goal": "完成全部调查" if packet_number == 1 else "",
            "opening": {"pressure": "证据不足"} if packet_number == 1 else {},
            "cycles": [{
                "obstacle": f"阻碍{packet_number}",
                "effort": f"行动{packet_number}",
                "result": f"结果{packet_number}",
                "state_change": f"状态{packet_number}",
            }],
            "accidents": [],
            "reversal": {},
            "ending": "调查完成" if packet_number == 2 else "",
            "question_chain": [],
            "relationship_arc": [],
            "covered_event_ids": expected,
        }, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        "causal-split", run_path, project, "constraints", plan,
        [], None,
    )

    assert chain["covered_event_ids"] == event_ids
    assert len(chain["cycles"]) == 2
    assert packet_calls == [event_ids[:2], event_ids[2:]]
    assert packet_topology == [(True, False), (False, True)]
    # Two validated leaves plus one validated deterministic reduction checkpoint.
    assert len(list((run_path / "outputs" / "causal-chain-packets").glob("*.json"))) == 3

    packet_calls.clear()
    second = await service._ensure_short_causal_chain(
        "causal-split", run_path, project, "constraints", plan,
        [], None,
    )
    assert second == chain
    assert root_calls == 2
    assert packet_calls == []


@pytest.mark.asyncio
async def test_causal_chain_output_limit_recursively_splits_production_shaped_event_groups(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Recursive causal packets", mode="short", genre="family intrigue",
        premise="A six-segment plan must survive repeated provider output limits.",
        target_words=15000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("causal-recursive", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "causal-recursive"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    segment_sizes = [7, 4, 7, 3, 4, 4]
    event_ids = [f"EV-{index:08X}" for index in range(1, sum(segment_sizes) + 1)]
    formal_events = [{
        "id": event_id,
        "label": f"Formal event {index}",
        "evidence": f"The accepted outline assigns event {index} to this causal step.",
    } for index, event_id in enumerate(event_ids, 1)]
    event_groups: list[list[str]] = []
    offset = 0
    for size in segment_sizes:
        owned = event_ids[offset:offset + size]
        offset += size
        event_groups.append(owned)
    plan = complete_plan_for_event_groups(event_groups)
    packet_calls: list[list[str]] = []
    completed_packets: list[list[str]] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            return await kwargs["capacity_splitter"]({
                "trigger": "preflight",
                "pressure": "split",
                "estimated_input_tokens": 31_993,
                "authority_input_tokens": 31_512,
                "output_reserve": 4_667,
                "context_window": 32_768,
            })
        expected = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nFORMAL EVENTS:", 1,
            )[0]
        )
        packet_calls.append(expected)
        if len(expected) > 4:
            splitter = kwargs.get("capacity_splitter")
            if splitter is not None:
                return await splitter({
                    "trigger": "output_limit",
                    "pressure": "split",
                    "estimated_input_tokens": 8_000,
                    "authority_input_tokens": 7_000,
                    "output_reserve": 4_782,
                    "context_window": 32_768,
                })
            raise IncompleteModelOutputError(
                "planning",
                StageText("{\"cycles\":[", {
                    "finish_reason": "max_tokens",
                    "completion_status": "recoverable_partial",
                }),
            )
        completed_packets.append(expected)
        return json.dumps({
            "core_goal": "Resolve the accepted central conflict" if event_ids[0] in expected else "",
            "opening": {"pressure": "The false identity is exposed"}
            if event_ids[0] in expected else {},
            "cycles": [{
                "obstacle": f"Pressure around {expected[0]}",
                "effort": f"The owner acts through {expected[-1]}",
                "result": f"The state advances through {expected[-1]}",
                "state_change": f"Events {expected[0]} to {expected[-1]} are resolved",
            }],
            "accidents": [],
            "reversal": {},
            "ending": "The confirmed ending is reached" if event_ids[-1] in expected else "",
            "question_chain": [],
            "relationship_arc": [],
            "covered_event_ids": expected,
        }, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        "causal-recursive", run_path, project, "constraints", plan,
        formal_events, None,
    )

    assert chain["covered_event_ids"] == event_ids
    assert packet_calls
    assert [event_id for packet in completed_packets for event_id in packet] == event_ids
    assert max(len(packet) for packet in completed_packets) <= 4
    assert len(list(
        (run_path / "outputs" / "causal-chain-packets").glob("*.json")
    )) >= 8
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()


@pytest.mark.asyncio
async def test_causal_chain_normal_finish_invalid_output_converges_to_semantic_packets(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Normal invalid causal output", mode="short", genre="mystery",
        premise="A normal provider finish can still be structurally incomplete.",
        target_words=3000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_id = "causal-normal-invalid"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = [f"EV-{index:08X}" for index in range(1, 5)]
    events = [{
        "id": event_id, "label": f"Event {index}",
        "evidence": f"Accepted event {index}.",
    } for index, event_id in enumerate(event_ids, 1)]
    plan = complete_plan_for_event_groups([[event_id] for event_id in event_ids])
    root_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal root_calls
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            root_calls += 1
            return json.dumps({
                "core_goal": "Goal", "cycles": [],
                "covered_event_ids": event_ids[:-1],
            })
        expected = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nFORMAL EVENTS:", 1,
            )[0]
        )
        return json.dumps({
            "core_goal": "Goal" if event_ids[0] in expected else "",
            "opening": {"pressure": "Opening"} if event_ids[0] in expected else {},
            "cycles": [{
                "obstacle": "Obstacle", "effort": "Effort",
                "result": "Result", "state_change": "Changed",
            }],
            "accidents": [], "reversal": {},
            "ending": "Ending" if event_ids[-1] in expected else "",
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": expected,
        })

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints", plan, events, None,
    )

    assert root_calls == 2
    assert chain["covered_event_ids"] == event_ids
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()


@pytest.mark.asyncio
async def test_causal_chain_real_stage_recovers_repeated_output_limits_and_crosses_authority_boundary(
    tmp_path,
) -> None:
    segment_sizes = [7, 4, 7, 3, 4, 4]
    event_ids = [f"EV-{index:08X}" for index in range(1, sum(segment_sizes) + 1)]

    class OutputLimitedGateway:
        def __init__(self) -> None:
            self.primary_calls: list[list[str]] = []
            self.fallback_calls: list[list[str]] = []

        @staticmethod
        def response(expected: list[str], *, route: str) -> ModelResult:
            return ModelResult(json.dumps({
                "core_goal": "Resolve the accepted conflict" if event_ids[0] in expected else "",
                "opening": {"pressure": "The identity conflict surfaces"}
                if event_ids[0] in expected else {},
                "cycles": [{
                    "obstacle": f"Obstacle at {expected[0]}",
                    "effort": f"Action through {expected[-1]}",
                    "result": f"Result through {expected[-1]}",
                    "state_change": f"State changes through {expected[-1]}",
                }],
                "accidents": [], "reversal": {},
                "ending": "The confirmed ending holds" if event_ids[-1] in expected else "",
                "question_chain": [], "relationship_arc": [],
                "covered_event_ids": expected,
            }, ensure_ascii=False), {
                "finish_reason": "stop", "provider_id": route,
                "model_id": f"{route}-model", "model_name": f"{route}-model",
                "input_tokens": 1200, "output_tokens": 300,
            })

        @staticmethod
        def expected(user: str) -> list[str]:
            return json.loads(
                user.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                    "\n\nFORMAL EVENTS:", 1,
                )[0]
            )

        async def complete(self, role, system, user, max_output_tokens=None):
            if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
                raise RuntimeError("maximum context length exceeded at provider")
            return await self.complete_primary(
                role, system, user, max_output_tokens=max_output_tokens,
            )

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
                raise RuntimeError(
                    "maximum context length exceeded at provider"
                )
            expected = self.expected(user)
            self.primary_calls.append(expected)
            if len(expected) > 4:
                return ModelResult('{"cycles":[', {
                    "finish_reason": "max_tokens", "provider_id": "primary",
                    "model_id": "primary-model", "model_name": "primary-model",
                    "input_tokens": 8000, "output_tokens": max_output_tokens or 1,
                })
            return self.response(expected, route="primary")

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            expected = self.expected(user)
            self.fallback_calls.append(expected)
            return self.response(expected, route="fallback")

    db = Database(tmp_path / "app.db")
    db.migrate()
    for provider_id in ("primary", "fallback"):
        db.save_provider(
            provider_id=provider_id, name=provider_id.title(),
            protocol="openai", base_url=f"https://{provider_id}.invalid/v1",
            auth_type="bearer", timeout_seconds=30, extra_headers={},
        )
    db.save_model(
        model_id="primary-model", provider_id="primary",
        display_name="Primary", model_name="primary-model",
        context_window=32768, max_output_tokens=8192,
    )
    db.save_model(
        model_id="fallback-model", provider_id="fallback",
        display_name="Fallback", model_name="fallback-model",
        context_window=65536, max_output_tokens=16384,
    )
    db.save_role_binding(
        "planning", "primary", "primary-model", "fallback", "fallback-model",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Real stage causal recovery", mode="short", genre="family intrigue",
        premise="The real stage assembly must recover a production-shaped limit.",
        target_words=15000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = OutputLimitedGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("causal-real-stage", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "causal-real-stage"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    formal_events = [{
        "id": event_id,
        "label": f"Formal event {index}",
        "evidence": f"Accepted authority for event {index}.",
    } for index, event_id in enumerate(event_ids, 1)]
    offset = 0
    event_groups: list[list[str]] = []
    for size in segment_sizes:
        owned = event_ids[offset:offset + size]
        offset += size
        event_groups.append(owned)
    plan = complete_plan_for_event_groups(event_groups)

    chain = await service._ensure_short_causal_chain(
        "causal-real-stage", run_path, project, "constraints",
        plan, formal_events, None,
    )

    assert chain["covered_event_ids"] == event_ids
    assert any(len(call) > 4 for call in gateway.primary_calls)
    successful_ranges = [call for call in gateway.primary_calls if len(call) <= 4]
    assert [event_id for call in successful_ranges for event_id in call] == event_ids
    assert gateway.fallback_calls == []
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()
    index = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(
            encoding="utf-8"
        )
    )
    assert index["status"] == "causal_pending"
    state = StoryStateStore(db).ensure(project.id, project.path)
    service.gateway = FakeGateway()
    manifest = await service._ensure_short_execution_manifest(
        "causal-real-stage", run_path, project, "constraints",
        state.revision, state.data, plan, chain,
        formal_events, len(segment_sizes),
    )
    assert manifest.status == "ready"
    assert manifest.causal_chain_sha256 == hashlib.sha256(
        json.dumps(
            chain, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    events = db.list_run_events("causal-real-stage")
    assert any(item["event_type"] == "stage_capacity_split_requested" for item in events)
    assert any(item["event_type"] == "causal_chain_packet_reduced" for item in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["output_limit", "disconnect"])
async def test_indivisible_causal_packet_uses_configured_fallback_without_losing_authority(
    tmp_path, failure_mode,
) -> None:
    event_id = "EV-00000001"

    class LeafFallbackGateway:
        def __init__(self) -> None:
            self.primary_calls = 0
            self.fallback_calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            raise RuntimeError("maximum context length exceeded at provider")

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            self.primary_calls += 1
            if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
                raise RuntimeError(
                    "maximum context length exceeded at provider"
                )
            if failure_mode == "disconnect":
                raise RuntimeError("server disconnected before terminal response")
            return ModelResult('{"cycles":[', {
                "finish_reason": "max_tokens", "provider_id": "primary",
                "model_id": "primary-model", "model_name": "primary-model",
                "input_tokens": 2000, "output_tokens": max_output_tokens or 1,
            })

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.fallback_calls += 1
            expected = json.loads(
                user.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                    "\n\nFORMAL EVENTS:", 1,
                )[0]
            )
            return ModelResult(json.dumps({
                "core_goal": "Preserve the only formal goal",
                "opening": {"pressure": "The event starts"},
                "cycles": [{
                    "obstacle": "Obstacle", "effort": "Effort",
                    "result": "Result", "state_change": "Changed",
                }],
                "accidents": [], "reversal": {}, "ending": "Ending",
                "question_chain": [], "relationship_arc": [],
                "covered_event_ids": expected,
            }), {
                "finish_reason": "stop", "provider_id": "fallback",
                "model_id": "fallback-model", "model_name": "fallback-model",
                "input_tokens": 1200, "output_tokens": 200,
            })

    db = Database(tmp_path / "app.db")
    db.migrate()
    for provider_id in ("primary", "fallback"):
        db.save_provider(
            provider_id=provider_id, name=provider_id.title(),
            protocol="openai", base_url=f"https://{provider_id}.invalid/v1",
            auth_type="bearer", timeout_seconds=30, extra_headers={},
        )
        db.save_model(
            model_id=f"{provider_id}-model", provider_id=provider_id,
            display_name=provider_id.title(), model_name=f"{provider_id}-model",
            context_window=32768, max_output_tokens=8192,
        )
    db.save_role_binding(
        "planning", "primary", "primary-model", "fallback", "fallback-model",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title=f"Leaf fallback {failure_mode}", mode="short", genre="suspense",
        premise="An indivisible event must survive route failure.", target_words=2000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = LeafFallbackGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = f"causal-leaf-{failure_mode}"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    plan = (
        "### 第1段：Only segment\n事件ID：EV-00000001\n"
        "大纲依据：Accepted event.\n"
        "段首承接：Opening.\n本段事件：The only event happens.\n段末交接：Ending."
    )

    chain = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints", plan,
        [{"id": event_id, "label": "Only event", "evidence": "Accepted event."}],
        None,
    )

    assert chain["covered_event_ids"] == [event_id]
    assert gateway.primary_calls >= 1
    assert gateway.fallback_calls == 1
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()
    assert any(
        item["event_type"] == "causal_chain_packet_model_fallback"
        for item in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_production_shaped_causal_container_drift_is_converted_and_reduced(
    tmp_path,
) -> None:
    """Regression for steps/causal_cycles plus non-owned global leakage."""

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Container drift recovery", mode="short", genre="historical fantasy",
        premise="Two formal events must cross the planning boundary.",
        target_words=3000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_id = "causal-container-drift"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = ["EV-00000001", "EV-00000002"]
    formal_events = [
        {"id": event_id, "label": f"Event {index}", "evidence": "Accepted."}
        for index, event_id in enumerate(event_ids, 1)
    ]
    plan = complete_plan_for_event_groups([[event_id] for event_id in event_ids])

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            return await kwargs["capacity_splitter"]({
                "trigger": "production_protocol_drift", "pressure": "split",
            })
        expected = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nFORMAL EVENTS:", 1,
            )[0]
        )
        first = event_ids[0] in expected
        return json.dumps({
            "steps" if first else "causal_cycles": [{
                "obstacle": f"Obstacle {expected[0]}",
                "effort": "A genre-appropriate action",
                "result": "A causally linked result",
                "state_change": "The accepted state advances",
            }],
            "covered_event_ids": expected,
            "core_goal": "Goal" if first else "leaked non-owner goal",
            "opening": {"pressure": "Opening"} if first else {"leak": True},
            "ending": "leaked early ending" if first else "Accepted ending",
        }, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints", plan, formal_events, None,
    )

    assert chain["covered_event_ids"] == event_ids
    assert len(chain["cycles"]) == 2
    assert chain["core_goal"] == "Goal"
    assert chain["ending"] == "Accepted ending"
    audits = [json.loads(path.read_text(encoding="utf-8")) for path in (
        run_path / "receipts" / "artifact-conversions"
    ).glob("*.json")]
    assert sum(item["method"] == "baml_sap" for item in audits) >= 2
    assert any("$.ending" in item["quarantined_paths"] for item in audits)
    assert any("$.core_goal" in item["quarantined_paths"] for item in audits)


@pytest.mark.asyncio
async def test_unknown_causal_vocabulary_minimally_regenerates_only_its_receipt(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Minimal protocol regeneration", mode="short", genre="mystery",
        premise="One event must survive an unseen provider vocabulary.",
        target_words=2000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_id = "causal-unseen-vocabulary"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_id = "EV-00000001"
    packet_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal packet_calls
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            return await kwargs["capacity_splitter"]({
                "trigger": "protocol", "pressure": "minimal",
            })
        packet_calls += 1
        if packet_calls == 1:
            return json.dumps({
                "unseen_motion": [{
                    "barrier": "Locked", "attempt": "Search",
                    "outcome": "Found", "world_delta": "Changed",
                }],
                "authority_echo": [event_id],
            })
        return json.dumps({
            "cycles": [{
                "obstacle": "Locked", "effort": "Search",
                "result": "Found", "state_change": "Changed",
            }],
            "covered_event_ids": [event_id],
            "core_goal": "Resolve it", "opening": {"pressure": "Locked"},
            "ending": "Resolved",
        })

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints",
        "### Segment 1\n事件ID：EV-00000001\n大纲依据：Accepted event.\n"
        "段首承接：locked.\n本段事件：search.\n段末交接：found.",
        [{"id": event_id, "label": "Search", "evidence": "Accepted."}],
        None,
    )

    assert chain["covered_event_ids"] == [event_id]
    assert packet_calls == 2
    assert any(
        item["event_type"] == "causal_chain_packet_protocol_retry"
        for item in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_indivisible_causal_packet_preserves_both_credential_failures(
    tmp_path,
) -> None:
    event_id = "EV-00000001"

    class MissingCredentialGateway:
        async def complete(self, role, system, user, max_output_tokens=None):
            raise RuntimeError("maximum context length exceeded at provider")

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            raise ValueError("missing_api_key: planning-primary")

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            raise ValueError("missing_api_key: planning-fallback")

    db = Database(tmp_path / "app.db")
    db.migrate()
    for provider_id in ("primary", "fallback"):
        db.save_provider(
            provider_id=provider_id, name=provider_id.title(),
            protocol="openai", base_url=f"https://{provider_id}.invalid/v1",
            auth_type="bearer", timeout_seconds=30, extra_headers={},
        )
        db.save_model(
            model_id=f"{provider_id}-model", provider_id=provider_id,
            display_name=provider_id.title(), model_name=f"{provider_id}-model",
            context_window=32768, max_output_tokens=8192,
        )
    db.save_role_binding(
        "planning", "primary", "primary-model", "fallback", "fallback-model",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Causal credential provenance", mode="short", genre="suspense",
        premise="An indivisible event must retain its route failures.",
        target_words=2000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, MissingCredentialGateway(),
        SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "causal-leaf-missing-credentials"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    plan = (
        "### 第1段：Only segment\n事件ID：EV-00000001\n"
        "大纲依据：Accepted event.\n"
        "段首承接：Opening.\n本段事件：The only event happens.\n段末交接：Ending."
    )

    with pytest.raises(ModelRoutesExhaustedError) as caught:
        await service._ensure_short_causal_chain(
            run_id, run_path, project, "constraints", plan,
            [{"id": event_id, "label": "Only event", "evidence": "Accepted event."}],
            None,
        )

    assert str(caught.value.primary_error) == "missing_api_key: planning-primary"
    assert str(caught.value.fallback_error) == "missing_api_key: planning-fallback"
    assert str(caught.value) == "primary and fallback model routes were exhausted"
    assert "planning-primary" not in str(caught.value)
    assert "planning-fallback" not in str(caught.value)


@pytest.mark.asyncio
async def test_causal_packet_resume_keeps_valid_prefix_and_restores_corrupt_suffix_from_database(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Causal packet resume", mode="short", genre="suspense",
        premise="Accepted causal work survives interruption and corruption.",
        target_words=3000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_id = "causal-packet-resume"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = [f"EV-{index:08X}" for index in range(1, 5)]
    formal_events = [{
        "id": event_id, "label": f"Event {index}",
        "evidence": f"Accepted event {index}.",
    } for index, event_id in enumerate(event_ids, 1)]
    plan = complete_plan_for_event_groups([[event_id] for event_id in event_ids])
    packet_calls: list[tuple[str, ...]] = []
    interrupt_suffix = True

    async def fake_stage(*args, **kwargs):
        nonlocal interrupt_suffix
        prompt = args[5]
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET" not in prompt:
            return await kwargs["capacity_splitter"]({
                "trigger": "preflight", "pressure": "split",
            })
        expected = tuple(json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nFORMAL EVENTS:", 1,
            )[0]
        ))
        packet_calls.append(expected)
        if interrupt_suffix and expected == tuple(event_ids[2:]):
            interrupt_suffix = False
            raise asyncio.CancelledError()
        return json.dumps({
            "core_goal": "Goal" if event_ids[0] in expected else "",
            "opening": {"pressure": "Opening"} if event_ids[0] in expected else {},
            "cycles": [{
                "obstacle": f"Obstacle {expected[0]}",
                "effort": f"Effort {expected[-1]}",
                "result": f"Result {expected[-1]}",
                "state_change": f"Change {expected[-1]}",
            }],
            "accidents": [], "reversal": {},
            "ending": "Ending" if event_ids[-1] in expected else "",
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": list(expected),
        })

    service._stage = fake_stage
    with pytest.raises(asyncio.CancelledError):
        await service._ensure_short_causal_chain(
            run_id, run_path, project, "constraints", plan, formal_events, None,
        )
    assert packet_calls.count(tuple(event_ids[:2])) == 1
    assert not (run_path / "outputs" / "short-causal-chain.json").exists()

    chain = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints", plan, formal_events, None,
    )
    assert chain["covered_event_ids"] == event_ids
    assert packet_calls.count(tuple(event_ids[:2])) == 1
    assert packet_calls.count(tuple(event_ids[2:])) == 2

    suffix_checkpoint = next(
        path for path in (
            run_path / "outputs" / "causal-chain-packets"
        ).glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["contract"][
            "owned_event_ids"
        ] == event_ids[2:]
    )
    corrupted = json.loads(suffix_checkpoint.read_text(encoding="utf-8"))
    corrupted["payload"]["covered_event_ids"] = ["EV-CORRUPT"]
    suffix_checkpoint.write_text(json.dumps(corrupted), encoding="utf-8")

    third = await service._ensure_short_causal_chain(
        run_id, run_path, project, "constraints", plan, formal_events, None,
    )
    assert third["covered_event_ids"] == event_ids
    assert packet_calls.count(tuple(event_ids[:2])) == 1
    assert packet_calls.count(tuple(event_ids[2:])) == 2
    restored = json.loads(suffix_checkpoint.read_text(encoding="utf-8"))
    assert restored["payload"]["covered_event_ids"] == event_ids[2:]
    assert any(
        item["event_type"] == "causal_chain_packet_reused"
        and item["metadata"].get("source") == "database_mirror"
        for item in db.list_run_events(run_id)
    )


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
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    service._persist_short_planning_ir(
        project.path / "runs" / "failed-prefix", plan, 4,
    )
    planning_ir = service._require_short_planning_ir(
        project.path / "runs" / "failed-prefix", plan, 4,
    )
    manifest = write_test_execution_manifest(
        service, project, project.path / "runs" / "failed-prefix",
        constraints, plan, 4, chain=chain, use_plan_event_ids=False,
    )
    manifest_hash = execution_manifest_sha256(manifest)
    augmented_constraints = constraints + (
        "\n\n# Short Story Causal Chain\n\n"
        + __import__("novel_flywheel.causal_chain", fromlist=["compact_causal_chain"])
        .compact_causal_chain(chain)
    )
    authority_hash = hashlib.sha256(json.dumps({
        "planning_ir_sha256": planning_ir.authority_sha256,
        "constraints": augmented_constraints,
        "target_words": 10000, "segment_count": 4,
        "story_state_sha256": hashlib.sha256(json.dumps(
            state.data, ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest(),
        "execution_manifest_sha256": manifest_hash,
        "location_catalog": [],
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    previous = ""
    for number, character in ((1, "甲"), (2, "乙")):
        text = character * 2500
        block = render_planning_segment_ir(planning_ir.segments[number - 1])
        beat_ids = list(manifest.segments[number - 1].beat_ids)
        saved_receipt = draft_semantic_receipt({
            "authority_sha256": authority_hash,
            "execution_manifest_sha256": manifest_hash,
            "task_id": f"segment-{number:02d}",
            "beat_ids": beat_ids,
            "event_ids": list(dict.fromkeys(
                beat_id.split("/", 1)[0] for beat_id in beat_ids
            )),
        }, text)
        atomic(
            source_outputs / "draft-checkpoints" / f"segment-{number:02d}.json",
            json.dumps({
                "version": 3, "authority_sha256": authority_hash,
                "execution_manifest_sha256": manifest_hash,
                "previous_sha256": (
                    hashlib.sha256(previous.encode("utf-8")).hexdigest()
                    if previous else ""
                ),
                "segment_plan_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
                    "assignment": {
                        "segment": number,
                        "event_ids": beat_ids,
                    "source_event_ids": list(dict.fromkeys(
                        next(
                            beat.source_event_id for beat in manifest.beats
                            if beat.beat_id == beat_id
                        )
                        for beat_id in manifest.segments[number - 1].beat_ids
                    )),
                        "handoff": manifest.segments[number - 1].exit_state[0].state,
                    },
                    "semantic_receipt": saved_receipt,
                }, ensure_ascii=False, indent=2),
        )
        previous = text
    db.update_run("failed-prefix", "failed", error="provider interrupted segment 3")

    planning_ir_path = source_outputs / "planning-ir.json"
    planning_ir_text = planning_ir_path.read_text(encoding="utf-8")
    tampered_ir = json.loads(planning_ir_text)
    tampered_ir["document"]["segments"][0]["handoff"] = "tampered handoff"
    atomic(
        planning_ir_path,
        json.dumps(tampered_ir, ensure_ascii=False, indent=2),
    )
    assert service._find_short_partial_checkpoint(
        project, "resume-prefix", state.revision, state.data, constraints, 4,
    ) is None
    atomic(planning_ir_path, planning_ir_text)

    first_checkpoint_path = source_outputs / "draft-checkpoints" / "segment-01.json"
    first_checkpoint_text = first_checkpoint_path.read_text(encoding="utf-8")
    tampered = json.loads(first_checkpoint_text)
    tampered["execution_manifest_sha256"] = "f" * 64
    atomic(first_checkpoint_path, json.dumps(tampered, ensure_ascii=False, indent=2))
    assert service._find_short_partial_checkpoint(
        project, "resume-prefix", state.revision, state.data, constraints, 4,
    ) is None
    atomic(first_checkpoint_path, first_checkpoint_text)

    assert service._find_short_partial_checkpoint(
        project, "resume-prefix", state.revision, state.data, constraints, 4,
    ) == source_outputs

    causal_path = source_outputs / "short-causal-chain.json"
    causal_text = causal_path.read_text(encoding="utf-8")
    tampered_causal = json.loads(causal_text)
    tampered_causal["covered_event_ids"] = tampered_causal[
        "covered_event_ids"
    ][:-1]
    atomic(
        causal_path,
        json.dumps(tampered_causal, ensure_ascii=False, indent=2),
    )
    rejected_partial_restore = (
        project.path / "runs" / "tampered-prefix-restore" / "outputs"
    )
    with pytest.raises(ValueError):
        service._restore_short_partial_checkpoint(
            source_outputs, rejected_partial_restore, project,
            state.revision, state.data, constraints, 4,
        )
    assert (
        not rejected_partial_restore.exists()
        or not any(rejected_partial_restore.rglob("*"))
    )
    atomic(causal_path, causal_text)

    residual_partial = project.path / "runs" / "residual-prefix" / "outputs"
    residual_partial.mkdir(parents=True)
    for filename in (
        "planning-adaptations.json", "best-candidate.md",
        "quality-checkpoint.json", "draft.md", "draft-integrity.json",
        "short-checkpoint.json",
    ):
        (residual_partial / filename).write_text("stale", encoding="utf-8")
    (residual_partial / "draft-checkpoints").mkdir()
    (residual_partial / "draft-checkpoints" / "segment-99.json").write_text(
        "stale", encoding="utf-8",
    )
    service._restore_short_partial_checkpoint(
        source_outputs, residual_partial, project,
        state.revision, state.data, constraints, 4,
    )
    for filename in (
        "planning-adaptations.json", "best-candidate.md",
        "quality-checkpoint.json", "draft.md", "draft-integrity.json",
        "short-checkpoint.json",
    ):
        assert not (residual_partial / filename).exists()
    assert not (
        residual_partial / "draft-checkpoints" / "segment-99.json"
    ).exists()
    assert (
        residual_partial / "draft-checkpoints" / "segment-01.json"
    ).is_file()
    assert (
        residual_partial / "draft-checkpoints" / "segment-02.json"
    ).is_file()

    second_checkpoint_path = source_outputs / "draft-checkpoints" / "segment-02.json"
    second_checkpoint_text = second_checkpoint_path.read_text(encoding="utf-8")
    invalid_second = json.loads(second_checkpoint_text)
    invalid_second["semantic_receipt"]["beat_receipts"] = []
    atomic(
        second_checkpoint_path,
        json.dumps(invalid_second, ensure_ascii=False, indent=2),
    )
    assert service._find_short_partial_checkpoint(
        project, "resume-prefix", state.revision, state.data, constraints, 4,
    ) == source_outputs
    atomic(second_checkpoint_path, second_checkpoint_text)
    generated_segments = []

    async def fake_stage(run_id, run_path, current_project, stage, constraints, user, **kwargs):
        if stage == "review":
            if "DRAFT_SEMANTIC_VALIDATION" in user:
                contract = json.loads(re.search(
                    r"TASK CONTRACT: (\{[^\n]+\})", user,
                ).group(1))
                prose = user.split("PROSE:\n", 1)[1]
                return json.dumps(
                    draft_semantic_receipt(contract, prose), ensure_ascii=False,
                )
            if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
                opening = user.split("OPENING EXCERPT: ", 1)[1].split(
                    "\nENDING EXCERPT:", 1,
                )[0]
                ending = user.split("ENDING EXCERPT: ", 1)[1]
                return json.dumps({
                    "authority_sha256": re.search(
                        r"AUTHORITY SHA256: ([0-9a-f]{64})", user,
                    ).group(1),
                    "draft_sha256": re.search(
                        r"DRAFT SHA256: ([0-9a-f]{64})", user,
                    ).group(1),
                    "segment_sha256": json.loads(re.search(
                        r"SEGMENT SHA256: (\[[^\n]+\])", user,
                    ).group(1)),
                    "event_ids": json.loads(re.search(
                        r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
                    ).group(1)),
                    "missing_event_ids": [], "duplicate_event_ids": [],
                    "out_of_order_event_ids": [], "causal_order_valid": True,
                    "continuity_valid": True, "ending_valid": True,
                    "commitments_valid": True,
                    "evidence": [
                        {"kind": "opening", "excerpt": opening[:12]},
                        {"kind": "ending", "excerpt": ending[-12:]},
                    ],
                    "summary": "整篇顺序、连续性和结局均已核对。",
                }, ensure_ascii=False)
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
    ["**第 1 段：开端**", "**第 2 段：发展**", "**第 3 段：收束**"],
    [
        "<strong>Segment 1: Opening</strong>",
        "<strong>Segment 2: Middle</strong>",
        "<strong>Segment 3: Ending</strong>",
    ],
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


def test_short_plan_parser_accepts_production_bold_heading_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_bold_heading_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    plan = (
        fixture["packet_heading"] + "\n\n"
        + f"事件ID：{'、'.join(fixture['owned_event_ids'])}\n\n"
        + "大纲依据：身份公开与归属落定。\n\n"
        + "段首承接：核验人员已经返回。\n\n"
        + "本段事件：花穗坦白身份，众人回应并确认归属。\n\n"
        + "段末交接：匿名信仍待追查。"
    )

    block = WorkflowService._require_short_plan_segment(
        plan, fixture["expected_segment"], artifact="production packet",
    )

    assert WorkflowService._short_plan_event_ids(block) == fixture[
        "owned_event_ids"
    ]
    assert WorkflowService._short_plan_field(block, "event")


def test_short_plan_parser_normalizes_production_json_packet_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_json_shape_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    event_ids = fixture["expected_event_ids"]
    current = (
        "### 第 5 段：当众坦白，归属落定\n\n"
        f"事件ID：{'、'.join(event_ids)}\n\n"
        "大纲依据：身份危机公开并完成核心坦白。\n\n"
        "段首承接：核验人员已经返回。\n\n"
        "本段事件：\n"
        + "\n".join(
            f"{index}. **正式事件**（{event_id}）：保留当前事件权威。"
            for index, event_id in enumerate(event_ids, 1)
        )
        + "\n\n段末交接：众人即将回应花穗的坦白。"
    )

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(fixture["payload"], ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=event_ids,
        current=current,
        artifact="production JSON packet",
    )

    assert WorkflowService._short_plan_event_ids(block) == event_ids
    assert "身份危机的公开" in block
    assert "核心坦白" in block
    assert WorkflowService._short_plan_field(block, "opening") == fixture[
        "payload"
    ]["segment_entry_condition"]
    assert WorkflowService._short_plan_field(block, "handoff") == fixture[
        "payload"
    ]["segment_exit_condition"]


def test_short_plan_parser_accepts_event_array_and_segment_only_variants() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_event_array_and_segment_only_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    base_item = fixture["event_array"][0]
    array_variants = [
        json.dumps(fixture["event_array"], ensure_ascii=False),
        "```json\n" + json.dumps(fixture["event_array"], ensure_ascii=False) + "\n```",
        "<!--\r\n" + json.dumps(fixture["event_array"], ensure_ascii=False) + "\r\n-->",
        json.dumps([{
            "event_id": base_item["id"],
            "segment_order": base_item["segment"],
            "entry_state": base_item["entry_handoff"],
            "exit_state": base_item["exit_handoff"],
            "summary": "换一种表述但仍然覆盖同一事件。",
        }], ensure_ascii=False),
        json.dumps([{
            "id": base_item["id"],
            "segment": base_item["segment"],
            "entry_handoff": "入口换成更短的版本。",
            "exit_handoff": "出口换成更短的版本。",
            "beats": [{
                "function": "完成反应",
                "causal_trigger": "坦白已经发生。",
                "core_content": "人物作出可观察的回应。",
                "exit_state": "关系状态向前推进。",
            }],
            "obligations_covered": [{
                "how_covered": "用一个可核对动作兑现义务。",
            }],
        }], ensure_ascii=False),
    ]
    variants = array_variants + [fixture["segment_only_packet"]]

    for index, payload in enumerate(variants):
        block = WorkflowService._normalize_generated_short_plan_segment(
            payload,
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=fixture["current_segment"],
            artifact=f"event-array-variant-{index}",
        )
        assert WorkflowService._short_plan_event_ids(block) == fixture[
            "expected_event_ids"
        ]
        assert WorkflowService._short_plan_packet_contract_issues(
            block,
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            source=fixture["current_segment"],
        ) == []
        body = WorkflowService._short_plan_field(block, "event")
        assert body.count("EV-BEAE4985") == 1
        assert "EV-15C208EE" not in body


def test_short_plan_parser_recovers_production_beam_summary_without_collapsing_body() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = json.dumps(fixture["beam_plan_payload"], ensure_ascii=False)

    block = WorkflowService._normalize_generated_short_plan_segment(
        payload,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact="production beam summary packet",
    )

    source_body = WorkflowService._short_plan_field(
        fixture["current_segment"], "event",
    )
    recovered_body = WorkflowService._short_plan_field(block, "event")
    assert "沈老夫人站了起来" in recovered_body
    assert "不能当众哭" in recovered_body
    assert "结构化义务与边界" in recovered_body
    assert "不提前解决匿名信" in recovered_body
    assert len(recovered_body) >= len(source_body)
    assert recovered_body.count("EV-1522AB0E") == 1
    assert WorkflowService._short_plan_field(block, "opening") == (
        fixture["beam_plan_payload"]["handoff_in"]
    )
    assert WorkflowService._short_plan_field(block, "handoff") == (
        fixture["beam_plan_payload"]["handoff_out"]
    )
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
        obligation_checklists=fixture["obligation_checklists"],
    ) == []


@pytest.mark.parametrize("variant_index", range(6))
def test_short_plan_parser_accepts_beam_summary_presentation_variants(
    variant_index,
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    canonical = fixture["beam_plan_payload"]
    event_id = fixture["expected_event_ids"][0]
    details = canonical["beam_plan"][event_id]
    variants = [
        json.dumps(canonical, ensure_ascii=False),
        "```json\r\n" + json.dumps(canonical, ensure_ascii=False) + "\r\n```",
        json.dumps({
            "segment": 5,
            "packet_event_ids": event_id,
            "entry_handoff": canonical["handoff_in"],
            "beam_plan": {event_id: details},
            "exit_handoff": canonical["handoff_out"],
        }, ensure_ascii=False),
        json.dumps({
            "segment_order": "５",
            "event_ids": [event_id],
            "opening": canonical["handoff_in"],
            "beam_plan": {event_id: {
                "approach": "沈老夫人和花穗完成公开认亲，悬念留待后续。",
                "obligations_delivered": details["obligations_fulfilled"],
            }},
            "handoff": canonical["handoff_out"],
        }, ensure_ascii=False),
        json.dumps({
            "handoff_out": canonical["handoff_out"],
            "beam_plan": {event_id: {
                "causal_plan": "公开坦白触发沈老夫人认亲，花穗接受新归属。",
                "obligations_fulfilled": details["obligations_fulfilled"],
            }},
            "handoff_in": canonical["handoff_in"],
            "event_ids": [event_id],
            "segment_index": 5,
            "adjacent_checks": {"previous_handoff_aligned": True},
        }, ensure_ascii=False),
        "<!--\n" + json.dumps({
            "segment_label": "第 5 段",
            "event_ids": [event_id],
            "entry_state": canonical["handoff_in"],
            "beam_plan": {event_id: {
                "summary": "花穗以自己的名字获得承认，匿名信仍保持未解决。",
                "obligations_fulfilled": details["obligations_fulfilled"],
            }},
            "exit_state": canonical["handoff_out"],
        }, ensure_ascii=False) + "\n-->",
    ]

    block = WorkflowService._normalize_generated_short_plan_segment(
        variants[variant_index],
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact=f"beam-summary-variant-{variant_index}",
    )

    assert WorkflowService._short_plan_event_ids(block) == [event_id]
    assert "沈老夫人站了起来" in block
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
        obligation_checklists=fixture["obligation_checklists"],
    ) == []


def test_short_plan_parser_extracts_embedded_markdown_segment_from_json_wrapper() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    payload = {
        "segment_id": fixture["expected_segment"],
        "owned_event_ids": [event_id],
        "planning_segment": fixture["current_segment"],
    }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="embedded-markdown-packet",
    )

    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_parser_recovers_production_beat_timeline_packet_locally() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_obligation_protocol_recovery_12b59c6e.json").read_text(
             encoding="utf-8",
         )
    )

    block = WorkflowService._normalize_generated_short_plan_segment(
        fixture["raw_repair_packet"],
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact="production beat-timeline packet",
    )

    assert WorkflowService._short_plan_declared_event_ids(block) == fixture[
        "expected_event_ids"
    ]
    assert fixture["required_excerpt"] in block
    assert "尚未交信" in WorkflowService._short_plan_field(block, "handoff")
    assert "因果合规自查" not in WorkflowService._short_plan_field(block, "handoff")
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
        obligation_checklists=fixture["obligation_checklists"],
    ) == []


def test_short_plan_parser_accepts_continuation_heading_and_sub_event_alias() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    packet = fixture["current_segment"].replace(
        "### 第 5 段：", "### 第 5 段续：",
    ).replace("本段事件：", "本段子事件：")

    normalized = WorkflowService._normalize_generated_short_plan_segment(
        packet,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="continuation-heading-packet",
    )

    assert WorkflowService._short_plan_event_ids(normalized) == [event_id]
    assert WorkflowService._short_plan_packet_contract_issues(
        normalized,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_merge_keeps_singleton_event_ownership_closed_after_parent_merge() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    first_event = "EV-BEAE4985"
    second_event = fixture["expected_event_ids"][0]
    source = WorkflowService._render_short_plan_repair_packet(
        fixture["current_segment"],
        segment=5,
        event_ids=[first_event, second_event],
        event_body=(
            f"1. **Event A** ({first_event}): first event remains complete.\n\n"
            f"2. **Event B** ({second_event}): second event remains complete."
        ),
    )
    packet_without_body_id = WorkflowService._render_short_plan_repair_packet(
        source,
        segment=5,
        event_ids=[first_event],
        event_body="1. **Event A**: the singleton packet retained its full narrative body.",
    )
    packet_with_body_id = WorkflowService._render_short_plan_repair_packet(
        source,
        segment=5,
        event_ids=[second_event],
        event_body=(
            f"1. **Event B** ({second_event}): the second packet retained its full body."
        ),
    )

    merged = WorkflowService._merge_short_plan_repair_packets(
        source,
        segment=5,
        event_ids=[first_event, second_event],
        packets=[packet_without_body_id, packet_with_body_id],
    )

    assert WorkflowService._short_plan_packet_contract_issues(
        merged,
        segment=5,
        event_ids=[first_event, second_event],
        source=source,
    ) == []


def test_short_plan_merge_ignores_adjacent_event_ids_mentioned_inside_singleton_body() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    first_event = "EV-BEAE4985"
    second_event = fixture["expected_event_ids"][0]
    source = WorkflowService._render_short_plan_repair_packet(
        fixture["current_segment"],
        segment=5,
        event_ids=[first_event, second_event],
        event_body="1. **Event A**: first event remains complete.",
    )
    packet = WorkflowService._render_short_plan_repair_packet(
        source,
        segment=5,
        event_ids=[first_event],
        event_body=(
            "1. **Event A**: the current event remains complete; "
            f"the later handoff is recorded under {second_event}."
        ),
    )

    assert WorkflowService._short_plan_declared_event_ids(packet) == [first_event]
    assert WorkflowService._short_plan_event_ids(packet) == [first_event]


def test_short_plan_embedded_markdown_rejects_distinct_candidates() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    alternate = fixture["current_segment"] + "\n\nAdditional narrative detail."
    payload = {
        "segment_id": fixture["expected_segment"],
        "owned_event_ids": [event_id],
        "first": fixture["current_segment"],
        "second": alternate,
    }

    with pytest.raises(GeneratedArtifactShapeError) as captured:
        WorkflowService._normalize_generated_short_plan_segment(
            json.dumps(payload, ensure_ascii=False),
            segment=fixture["expected_segment"],
            event_ids=[event_id],
            current=fixture["current_segment"],
            artifact="ambiguous-embedded-markdown",
        )

    assert any(
        issue.get("code") == "planning_packet_embedded_markdown_ambiguous"
        for issue in captured.value.issues
    )


def test_short_plan_embedded_markdown_deduplicates_same_candidate_and_accepts_fence() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    payload = {
        "segment_id": fixture["expected_segment"],
        "owned_event_ids": [event_id],
        "duplicate_a": fixture["current_segment"],
        "duplicate_b": fixture["current_segment"],
        "fenced": f"```markdown\n{fixture['current_segment']}\n```",
    }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="deduplicated-embedded-markdown",
    )

    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_embedded_markdown_rejects_malformed_fence() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    payload = {
        "segment_id": fixture["expected_segment"],
        "owned_event_ids": [event_id],
        "malformed": f"```markdown\n{fixture['current_segment']}",
    }

    with pytest.raises(GeneratedArtifactShapeError):
        WorkflowService._normalize_generated_short_plan_segment(
            json.dumps(payload, ensure_ascii=False),
            segment=fixture["expected_segment"],
            event_ids=[event_id],
            current=fixture["current_segment"],
            artifact="malformed-embedded-markdown",
        )


@pytest.mark.parametrize("mutation", [
    "missing_owned_event", "missing_summary_body", "truncated_json",
    "multiple_payloads",
])
def test_short_plan_parser_rejects_unsafe_beam_summary_variants(mutation) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = fixture["invalid_variants"][mutation]
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GeneratedArtifactShapeError):
        WorkflowService._normalize_generated_short_plan_segment(
            payload,
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=fixture["current_segment"],
            artifact=f"unsafe-beam-summary-{mutation}",
        )


def test_short_plan_parser_rejects_beam_summary_when_retained_authority_is_stale() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    stale = fixture["current_segment"].replace(
        "事件ID：EV-1522AB0E", "事件ID：EV-DEADBEEF",
    )

    with pytest.raises(GeneratedArtifactShapeError) as captured:
        WorkflowService._normalize_generated_short_plan_segment(
            json.dumps(fixture["beam_plan_payload"], ensure_ascii=False),
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=stale,
            artifact="stale beam summary authority",
        )

    assert captured.value.issues[0]["code"] == (
        "planning_packet_summary_authority_missing"
    )


def test_short_plan_parser_keeps_complete_beam_realization_as_creative_candidate() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = json.loads(json.dumps(fixture["beam_plan_payload"]))
    event_id = fixture["expected_event_ids"][0]
    complete_realization = (
        "沈老夫人先逐项核对花穗查账、护人和坦白的行为，再当众说明认下的是"
        "她自己挣来的担当。花穗听见自己的名字被郑重叫出，没有借蕙芷的身份"
        "躲避，也没有把归属当成危机已经结束。下人们以花姑娘相称，沈老夫人"
        "正式确认义女身份，花穗压住眼泪并保留匿名信线索。"
    ) * 5
    payload["beam_plan"][event_id] = {
        "event_body": complete_realization,
        "obligations_fulfilled": payload["beam_plan"][event_id][
            "obligations_fulfilled"
        ],
    }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact="complete beam realization",
    )

    body = WorkflowService._short_plan_field(block, "event")
    assert complete_realization in body
    assert "这个称呼既承认她不是走失的蕙芷" not in body
    assert "结构化义务与边界" not in body
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
        obligation_checklists=fixture["obligation_checklists"],
    ) == []


@pytest.mark.parametrize("variant_index", [0, 1])
def test_short_plan_parser_recovers_open_world_production_wrappers(
    variant_index,
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    variant = fixture["production_variants"][variant_index]

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(variant["payload"], ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact=variant["name"],
    )

    assert WorkflowService._short_plan_event_ids(block) == fixture[
        "expected_event_ids"
    ]
    assert "沈老夫人" in WorkflowService._short_plan_field(block, "event")
    assert "匿名信" in WorkflowService._short_plan_field(block, "handoff")
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
    ) == []


@pytest.mark.parametrize("topology", [
    "unseen_nested_list",
    "unseen_event_mapping",
])
def test_short_plan_parser_accepts_unseen_container_names(topology) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    event = {
        "event_id": event_id,
        "description": "沈老夫人主动认下花穗，下人主动请命，匿名信保持悬置。",
        "story_evidence": {
            "movement": "花穗以自己的名字获得归属。",
            "continuity": "不提前揭开匿名信来源。",
            "operation": "救援队执行撤离行动；这是题材叙述，不是机器操作。",
        },
    }
    if topology == "unseen_nested_list":
        payload = {
            "segment": 5,
            "event_ids": [event_id],
            "orchid_vault": {
                "entry_handoff": "花穗坦白后等待发落。",
                "lantern_rows": [event],
                "exit_handoff": "花穗成为义女，匿名信继续悬置。",
            },
        }
    else:
        payload = {
            "segment": 5,
            "event_ids": [event_id],
            "glasshouse": [{
                "entry_handoff": "花穗坦白后等待发落。",
                "copper_index": {
                    event_id: {
                        key: value for key, value in event.items()
                        if key != "event_id"
                    },
                },
                "exit_handoff": "花穗成为义女，匿名信继续悬置。",
            }],
        }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact=topology,
    )

    assert WorkflowService._short_plan_event_ids(block) == [event_id]
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_parser_accepts_structured_entry_and_exit_state_objects() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    payload = [{
        "id": event_id,
        "label": "公开归属与承诺",
        "evidence": (
            "沈老夫人当众宣布以花穗本名认她为义女，下人们主动请命，"
            "花穗保留匿名信仍未查清的事实。"
        ),
        "plan": {
            "segment": 5,
            "entry_state": {
                "花穗": "已经坦白真实身份，等待沈老夫人发落。",
                "厅堂": "众人沉默，尚未形成正式归属。",
            },
            "exit_state": {
                "花穗": "以自己的名字成为沈府义女。",
                "匿名信": "来源仍未查清，留待后续追查。",
            },
            "obligation_coverages": [{
                "obligation_id": f"{event_id}-B01",
                "plan_detail": (
                    "沈老夫人主动宣布决定，下人们主动请命，花穗以真名获得归属。"
                ),
            }],
        },
    }]

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="production structured boundary state",
    )

    assert "已经坦白真实身份" in WorkflowService._short_plan_field(
        block, "opening",
    )
    assert "匿名信" in WorkflowService._short_plan_field(block, "handoff")
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_parser_recovers_runtime_owned_production_packet() -> None:
    """The latest production shape keeps control identity outside prose."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_structured_state_52023150.json").read_text(
             encoding="utf-8",
         )
    )
    expected = ["EV-BEAE4985", "EV-1522AB0E"]
    payload = {
        "segment_number": 5,
        "segment_label": "当众坦白，归属落定（下）",
        "packet_event_ids": expected,
        "entry_boundary": (
            "花穗已经当众坦白真实身份，厅中众人等待回应与最终裁断。"
        ),
        "events": [
            {
                "event_id": expected[0],
                "kind": "planning",
                "plan": {
                    "identity": {
                        "primary": {
                            "actor": "花穗",
                            "state": "站得笔直，等待沈蕙兰、沈老夫人与裴砚行回应。",
                        },
                        "participants": [{
                            "name": "裴砚行",
                            "action": (
                                "被花穗当众点名后不躲不闪，以往后如何讲规矩作答，"
                                "给出公开且明确的关系承诺。"
                            ),
                        }],
                    },
                    "dependencies": {
                        "causal_chain": [
                            "沈蕙兰先公开认可花穗的担当。",
                            "沈老夫人把判断从血脉转向花穗自己挣来的担当。",
                            "花穗主动追问裴砚行，他用往后二字完成公开回应。",
                        ],
                    },
                    "relationship_delta": {
                        "裴砚行-花穗": "从共同查案推进为当众给出往后的承诺。",
                    },
                },
            },
            {
                "event_id": expected[1],
                "kind": "planning",
                "plan": {
                    "identity": {
                        "primary": {
                            "actor": "沈老夫人",
                            "state": "站起来宣布最终决定，语气不容置疑。",
                        },
                        "participants": [{
                            "name": "花穗",
                            "action": (
                                "听见自己以花穗本名成为沈府义女，下人们主动跪地请命，"
                                "她强忍眼泪并决定留下。"
                            ),
                        }],
                    },
                    "dependencies": {
                        "causal_chain": [
                            "前一事件完成众人的公开回应。",
                            "沈老夫人宣布花穗以本名成为沈府义女。",
                            "下人集体请命让归属获得公开的人心基础。",
                        ],
                    },
                    "retained_doubt": "匿名信来源仍未查清，不能提前关闭后续悬念。",
                },
            },
        ],
        "exit_boundary": (
            "花穗以本名成为沈府义女，公开关系承诺成立，匿名信仍待追查。"
        ),
    }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=5,
        event_ids=expected,
        current=fixture["current_segment"],
        artifact="latest production runtime-owned packet",
    )

    assert WorkflowService._short_plan_declared_event_ids(block) == expected
    assert "往后" in WorkflowService._short_plan_field(block, "event")
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=5,
        event_ids=expected,
        source=fixture["current_segment"],
    ) == []


def test_short_plan_parser_accepts_segment_plan_heading_with_trailing_identity() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    packet = fixture["current_segment"].replace(
        "### 第 5 段：当众坦白，归属落定",
        f"# 段规划：第5段／{event_id}",
        1,
    )

    normalized = WorkflowService._normalize_generated_short_plan_segment(
        packet,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="production reversed segment heading",
    )

    assert WorkflowService._short_plan_event_ids(normalized) == [event_id]
    assert WorkflowService._short_plan_packet_contract_issues(
        normalized,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=fixture["current_segment"],
    ) == []


def test_short_plan_parser_reads_multi_event_ownership_from_event_titles_only() -> None:
    first = "EV-15C208EE"
    second = "EV-126EE846"
    neighbour = "EV-BEAE4985"
    source = (
        "### 第 5 段：公开坦白\n\n"
        f"事件ID：{first}、{second}\n\n"
        "大纲依据：身份核验与主动坦白。\n\n"
        "段首承接：核验人员返回，花穗必须作出选择。\n\n"
        "本段事件：\n"
        f"1. **核验结果公布**（{first}）。结果不能证明花穗就是蕙芷。\n\n"
        f"2. **花穗主动坦白**（{second}）。花穗以自己的意志说出真相。\n\n"
        "段末交接：花穗等待众人回应。"
    )
    packet = (
        "# 第5段 规划\n\n"
        "## 段首承接\n核验人员返回，花穗必须作出选择。\n\n"
        "## 本段事件\n\n"
        f"### 第一拍：核验结果公布（{first}）\n"
        "结果不能证明花穗就是蕙芷，厅中等待她自己选择。\n\n"
        f"### 第二拍：花穗主动坦白（{second}）\n"
        "花穗主动说出真实身份和最初动机，没有让他人替她作答。\n\n"
        "## 段末交接\n花穗等待众人回应。\n\n"
        f"> 下一事件 {neighbour} 将负责众人的公开回应。"
    )

    normalized = WorkflowService._normalize_generated_short_plan_segment(
        packet,
        segment=5,
        event_ids=[first, second],
        current=source,
        artifact="production multi-event title ownership",
    )

    assert WorkflowService._short_plan_declared_event_ids(normalized) == [
        first, second,
    ]
    assert neighbour not in WorkflowService._short_plan_declared_event_ids(
        normalized,
    )
    assert WorkflowService._short_plan_packet_contract_issues(
        normalized,
        segment=5,
        event_ids=[first, second],
        source=source,
    ) == []


def test_short_plan_production_packets_normalize_and_merge_losslessly() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_structured_state_52023150.json").read_text(
             encoding="utf-8",
         )
    )
    normalized_packets: list[str] = []
    for packet in fixture["packets"][:2]:
        value = packet.get("text")
        if value is None:
            value = json.dumps(packet["payload"], ensure_ascii=False)
        normalized = WorkflowService._normalize_generated_short_plan_segment(
            value,
            segment=fixture["expected_segment"],
            event_ids=packet["event_ids"],
            current=fixture["current_segment"],
            artifact=packet["name"],
        )
        assert WorkflowService._short_plan_packet_contract_issues(
            normalized,
            segment=fixture["expected_segment"],
            event_ids=packet["event_ids"],
            source=fixture["current_segment"],
        ) == []
        normalized_packets.append(normalized)

    merged = WorkflowService._merge_short_plan_repair_packets(
        fixture["current_segment"],
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        packets=normalized_packets,
    )

    assert WorkflowService._short_plan_declared_event_ids(merged) == fixture[
        "expected_event_ids"
    ]
    assert WorkflowService._short_plan_packet_contract_issues(
        merged,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
    ) == []

    neighbour_packet = fixture["packets"][2]
    normalized_neighbour = WorkflowService._normalize_generated_short_plan_segment(
        neighbour_packet["text"],
        segment=fixture["expected_segment"],
        event_ids=neighbour_packet["event_ids"],
        current=fixture["current_segment"],
        artifact=neighbour_packet["name"],
    )
    assert WorkflowService._short_plan_declared_event_ids(
        normalized_neighbour,
    ) == neighbour_packet["event_ids"]


def test_short_plan_parser_uses_complete_body_from_unseen_wrapper() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    realization = (
        "沈老夫人先说明花穗护人、查账与坦白都是自己挣来的担当，再当众宣布"
        "沈府以花穗本名认她为义女。下人们主动请命并称她花姑娘，花穗忍住"
        "眼泪，也没有忘记匿名信仍待追查。"
    ) * 6
    payload = {
        "segment": 5,
        "event_ids": [event_id],
        "future_capsule": {
            "entry_handoff": "花穗坦白后等待发落。",
            "payload_rows": [{
                "event_id": event_id,
                "event_body": realization,
            }],
            "exit_handoff": "花穗成为义女，匿名信继续悬置。",
        },
    }

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(payload, ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=fixture["current_segment"],
        artifact="complete unseen wrapper",
    )

    body = WorkflowService._short_plan_field(block, "event")
    assert realization in body
    assert "结构化义务与边界" not in body


@pytest.mark.parametrize("mutation", [
    "duplicate_candidates",
    "reordered_nested_events",
    "unknown_machine_control",
])
def test_short_plan_parser_rejects_unsafe_open_world_shapes(mutation) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    if mutation == "duplicate_candidates":
        event_ids = [event_id]
        payload = {
            "segment": 5,
            "event_ids": event_ids,
            "entry_handoff": "入口",
            "unknown_rows": [
                {"event_id": event_id, "summary": "候选一。"},
                {"event_id": event_id, "summary": "相互冲突的候选二。"},
            ],
            "exit_handoff": "出口",
        }
    elif mutation == "reordered_nested_events":
        event_ids = ["EV-1522AB0E", "EV-BEAE4985"]
        payload = {
            "segment": 5,
            "event_ids": event_ids,
            "entry_handoff": "入口",
            "unknown_rows": [
                {"event_id": event_ids[1], "summary": "第二事件。"},
                {"event_id": event_ids[0], "summary": "第一事件。"},
            ],
            "exit_handoff": "出口",
        }
    else:
        event_ids = [event_id]
        payload = {
            "segment": 5,
            "event_ids": event_ids,
            "entry_handoff": "入口",
            "unknown_rows": [{
                "event_id": event_id,
                "summary": "内容完整但包含未知机器操作。",
                "mutation": {"replace": "accepted plan"},
            }],
            "exit_handoff": "出口",
        }

    with pytest.raises(GeneratedArtifactShapeError):
        WorkflowService._normalize_generated_short_plan_segment(
            json.dumps(payload, ensure_ascii=False),
            segment=fixture["expected_segment"],
            event_ids=event_ids,
            current=fixture["current_segment"],
            artifact=f"unsafe-open-world-{mutation}",
        )


def test_short_plan_beam_summary_retention_uses_packet_event_granularity() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_beam_summary_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    event_id = fixture["expected_event_ids"][0]
    sibling_one = "EV-15C208EE"
    sibling_two = "EV-126EE846"
    full_segment = fixture["current_segment"].replace(
        f"事件ID：{event_id}",
        f"事件ID：{sibling_one}、{sibling_two}、{event_id}",
    ).replace(
        "本段事件：\n",
        "本段事件：\n"
        f"1. **身份核验**（{sibling_one}）。" + "核验过程保持完整。" * 80 + "\n\n"
        f"2. **公开坦白**（{sibling_two}）。" + "坦白过程保持完整。" * 80 + "\n\n",
        1,
    )

    block = WorkflowService._normalize_generated_short_plan_segment(
        json.dumps(fixture["beam_plan_payload"], ensure_ascii=False),
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        current=full_segment,
        artifact="full-segment beam summary packet",
    )

    body = WorkflowService._short_plan_field(block, "event")
    assert "沈老夫人站了起来" in body
    assert "结构化义务与边界" in body
    assert "核验过程保持完整" not in body
    assert "坦白过程保持完整" not in body
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=[event_id],
        source=full_segment,
        obligation_checklists=fixture["obligation_checklists"],
    ) == []


@pytest.mark.parametrize("mutation", [
    "reordered_events", "missing_exit", "conflicting_segment", "multiple_payloads",
])
def test_short_plan_parser_rejects_ambiguous_event_array_variants(mutation) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_event_array_and_segment_only_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = fixture["invalid_variants"][mutation]
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GeneratedArtifactShapeError):
        WorkflowService._normalize_generated_short_plan_segment(
            payload,
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=fixture["current_segment"],
            artifact=f"invalid-event-array-{mutation}",
        )


@pytest.mark.parametrize("variant_index", [0, 1])
def test_short_plan_parser_normalizes_production_markdown_field_variants(
    variant_index,
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_markdown_fields_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    variant = fixture["valid_variants"][variant_index]

    block = WorkflowService._normalize_generated_short_plan_segment(
        variant["payload"],
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact=variant["name"],
    )

    assert WorkflowService._short_plan_event_ids(block) == fixture[
        "expected_event_ids"
    ]
    assert all(
        WorkflowService._short_plan_field(block, field)
        for field in WorkflowService.SHORT_PLAN_FIELD_ALIASES
    )
    assert WorkflowService._short_plan_field(block, "outline") == (
        WorkflowService._short_plan_field(
            fixture["current_segment"], "outline",
        )
    )
    assert "诊断附录" not in WorkflowService._short_plan_field(
        block, "handoff",
    )
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
    ) == []


def test_runtime_owned_event_ir_keeps_nested_narrative_headings_out_of_plan_control() -> None:
    """Replay the 9677db production topology through the Runtime write path."""

    event_ids = ["EV-11111111", "EV-22222222", "EV-33333333"]
    current = (
        "### 第 5 段：既有最佳规划\n\n"
        f"事件ID：{'、'.join(event_ids)}\n\n"
        "大纲依据：正式大纲中的三个连续事件。\n\n"
        "段首承接：主角带着上一段取得的证据进入当前场景。\n\n"
        "本段事件：\n"
        "1. **正式事件**（EV-11111111）：旧事件正文。\n\n"
        "2. **正式事件**（EV-22222222）：旧事件正文。\n\n"
        "3. **正式事件**（EV-33333333）：旧事件正文。\n\n"
        "段末交接：三项行动完成，证据和人物状态交给下一段。"
    )
    payload = json.dumps({"events": [
        {
            "event_id": event_ids[0],
            "narrative": (
                "**触发与承接**\n主角核对入口状态后采取行动。\n\n"
                "**出口状态**\n第一项行动完成，人物认知发生可验证变化。"
            ),
        },
        {
            "event_id": event_ids[1],
            "narrative": (
                "**人物反应**\n同伴根据新证据作出回应。\n\n"
                "**出口状态**\n第二项行动完成，关系状态自然推进。"
            ),
        },
        {
            "event_id": event_ids[2],
            "narrative": (
                "**事件主干**\n威胁升级，主角保存证据并调整策略。\n\n"
                "**出口状态与段末交接**\n这里只是事件自由正文的小标题。\n\n"
                "**段末交接（写死）**\n这仍属于第三个事件的创作正文，不是机器控制字段。"
            ),
        },
    ]}, ensure_ascii=False)

    normalized = WorkflowService._normalize_runtime_owned_short_plan_payload(
        payload,
        segment=5,
        event_ids=event_ids,
        current=current,
        artifact="production-shaped nested narrative headings",
    )

    body = WorkflowService._short_plan_field(normalized, "event")
    assert all(event_id in body for event_id in event_ids)
    assert "段末交接（写死）" in body
    assert WorkflowService._short_plan_field(normalized, "handoff") == (
        "三项行动完成，证据和人物状态交给下一段。"
    )
    assert planning_event_body_issues(normalized, event_ids) == []


@pytest.mark.parametrize("packet_index", [0, 1])
def test_short_plan_parser_recovers_unicode_protocol_production_packets(
    packet_index,
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_unicode_protocol_9fc0898b.json").read_text(
             encoding="utf-8",
         )
    )
    packet = fixture["packets"][packet_index]

    normalized = WorkflowService._normalize_generated_short_plan_segment(
        packet["payload"],
        segment=fixture["expected_segment"],
        event_ids=packet["event_ids"],
        current=packet["current_segment"],
        artifact=packet["name"],
    )

    assert WorkflowService._short_plan_declared_event_ids(normalized) == packet[
        "event_ids"
    ]
    assert WorkflowService._short_plan_packet_contract_issues(
        normalized,
        segment=fixture["expected_segment"],
        event_ids=packet["event_ids"],
        source=packet["current_segment"],
    ) == []
    assert "EV-1522AB0E" not in WorkflowService._short_plan_declared_event_ids(
        normalized,
    )


@pytest.mark.parametrize("heading", [
    "# 第5段计划：任意创作标题",
    "# SEGMENT\u202f5 PACKET REBUILD — arbitrary suffix",
    "# 段规划：第5段／provider wrapper",
    "# Planning Segment 5 · provider wrapper",
])
def test_short_plan_root_heading_uses_segment_identity_not_fixed_suffix(
    heading,
) -> None:
    packet = (
        heading + "\n\n"
        "事件ID：EV-BEAE4985\n\n"
        "大纲依据：保持正式事件不变。\n\n"
        "段首承接：上一事件已经结束。\n\n"
        "本段事件：花穗主动追问，裴砚行公开回应。\n\n"
        "段末交接：关系承诺成立。"
    )

    block = WorkflowService._require_short_plan_segment(
        packet, 5, artifact="open suffix packet",
    )

    assert WorkflowService._short_plan_event_ids(block) == ["EV-BEAE4985"]


def test_short_plan_nested_self_check_heading_does_not_duplicate_segment() -> None:
    packet = (
        "# 第5段计划：当众回应\n\n"
        "事件ID：EV-BEAE4985\n\n"
        "大纲依据：保持正式事件不变。\n\n"
        "段首承接：上一事件已经结束。\n\n"
        "本段事件：花穗主动追问，裴砚行公开回应。\n\n"
        "## 第5段自检：只核对视角\n\n"
        "这里不是第二个正式段。\n\n"
        "段末交接：关系承诺成立。"
    )

    headings = [
        number for _match, number in WorkflowService._short_plan_headings(packet)
        if number is not None
    ]

    assert headings == [5]


def test_short_plan_root_heading_rejects_multiple_distinct_segment_identities() -> None:
    packet = (
        "# 第5段计划并入第6段：冲突包装\n\n"
        "事件ID：EV-BEAE4985\n\n"
        "大纲依据：保持正式事件不变。\n\n"
        "段首承接：上一事件已经结束。\n\n"
        "本段事件：花穗主动追问，裴砚行公开回应。\n\n"
        "段末交接：关系承诺成立。"
    )

    with pytest.raises(GeneratedArtifactShapeError, match="segment identity"):
        WorkflowService._require_short_plan_segment(
            packet, 5, artifact="conflicting identity packet",
        )


@pytest.mark.asyncio
async def test_planning_protocol_rewrap_uses_real_stage_and_recovers_output_limit(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="planning-model", provider_id="provider",
        display_name="Planning", model_name="planning-model",
        context_window=32_768, max_output_tokens=8_192,
    )
    db.save_role_binding("planning", "provider", "planning-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Protocol recovery", mode="short", genre="suspense",
        premise="A complete plan arrives in an unknown wrapper.", target_words=5000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    event_id = "EV-BEAE4985"
    current = (
        "### 第 5 段：公开回应\n\n"
        f"事件ID：{event_id}\n\n"
        "大纲依据：花穗主动追问并得到公开回应。\n\n"
        "段首承接：花穗已经坦白真实身份。\n\n"
        f"本段事件：1. **公开回应**（{event_id}）："
        "花穗主动追问，裴砚行当众回应并给出往后承诺。\n\n"
        "段末交接：关系承诺成立，匿名信仍待追查。"
    )
    canonical = json.dumps({"events": [{
        "event_id": event_id,
        "narrative": (
            "花穗主动追问裴砚行为何沉默；裴砚行没有回避，"
            "当众回应并给出往后承诺。"
        ),
    }]}, ensure_ascii=False)

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[int | None] = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append(max_output_tokens)
            assert role == "planning"
            assert user.startswith("SHORT_PLAN_CANONICAL_REWRAP_V1")
            assert "CURRENT AUTHORITY (IMMUTABLE)" in user
            if len(self.calls) == 1:
                return ModelResult(
                    '{"events":[{"event_id":"EV-BEAE4985",',
                    {
                        "finish_reason": "max_tokens",
                        "model_id": "planning-model",
                        "model_name": "planning-model",
                    },
                )
            return ModelResult(
                canonical,
                {
                    "finish_reason": "end_turn",
                    "model_id": "planning-model",
                    "model_name": "planning-model",
                },
            )

    gateway = expose_test_primary_route(Gateway())
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "planning-protocol-output-limit"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    raw = (
        "<future-plan-envelope>\n"
        "<entry>花穗已经坦白真实身份。</entry>\n"
        f"<event identity=\"{event_id}\">"
        "花穗主动追问裴砚行为何沉默；裴砚行没有回避，当众回应并给出往后承诺。"
        "</event>\n"
        "<exit>关系承诺成立，匿名信仍待追查。</exit>\n"
        "</future-plan-envelope>"
    )

    normalized = await service._normalize_generated_short_plan_segment_with_protocol_retry(
        run_id, run_path, project, "必须保持正式剧情方向。", raw,
        segment=5,
        event_ids=[event_id],
        current=current,
        artifact="integration protocol packet",
        suffix="-integration",
    )

    assert "裴砚行没有回避" in normalized
    assert len(gateway.calls) == 2
    assert gateway.calls[1] > gateway.calls[0]
    assert service._short_plan_packet_contract_issues(
        normalized,
        segment=5,
        event_ids=[event_id],
        source=current,
    ) == []
    events = db.list_run_events(run_id)
    assert any(item["event_type"] == "output_limit_expanded" for item in events)
    assert any(
        item["event_type"] == "planning_packet_protocol_recovered"
        for item in events
    )


def test_short_plan_markdown_packet_reports_exact_missing_field_feedback() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_markdown_fields_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )

    with pytest.raises(GeneratedArtifactShapeError) as captured:
        WorkflowService._normalize_generated_short_plan_segment(
            fixture["invalid_variant"],
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=fixture["current_segment"],
            artifact="production Markdown packet",
        )

    assert captured.value.issues == [{
        "code": "planning_packet_field_missing",
        "message": (
            "production Markdown packet lacks complete plan fields: "
            "['handoff']"
        ),
        "segment": fixture["expected_segment"],
        "event_ids": fixture["expected_event_ids"],
        "fields": ["handoff"],
        "blocking": True,
    }]


def test_short_plan_markdown_packet_rejects_repeated_heading_owned_field() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_markdown_fields_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = fixture["valid_variants"][1]["payload"].replace(
        "## 段末交接",
        "## 段首承接\n\n重复入口不得被猜测。\n\n## 段末交接",
        1,
    )

    with pytest.raises(GeneratedArtifactShapeError) as captured:
        WorkflowService._normalize_generated_short_plan_segment(
            payload,
            segment=fixture["expected_segment"],
            event_ids=fixture["expected_event_ids"],
            current=fixture["current_segment"],
            artifact="ambiguous Markdown packet",
        )

    assert any(
        issue["code"] == "planning_packet_field_ambiguous"
        and issue["fields"] == ["opening"]
        for issue in captured.value.issues
    )


def test_canonical_short_plan_packet_does_not_promote_trailing_appendix() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_markdown_fields_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    payload = (
        fixture["current_segment"]
        + "\n\n## 诊断附录\n\n这部分不是正式规划字段。"
    )

    block = WorkflowService._normalize_generated_short_plan_segment(
        payload,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        current=fixture["current_segment"],
        artifact="canonical packet with appendix",
    )

    assert "诊断附录" not in block
    assert "不是正式规划字段" not in block
    assert WorkflowService._short_plan_packet_contract_issues(
        block,
        segment=fixture["expected_segment"],
        event_ids=fixture["expected_event_ids"],
        source=fixture["current_segment"],
    ) == []


@pytest.mark.parametrize("mutation", [
    "reordered_events",
    "conflicting_segment",
    "missing_narrative",
])
def test_short_plan_json_packet_rejects_ambiguous_authority(mutation) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_json_shape_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    event_ids = fixture["expected_event_ids"]
    payload = fixture["payload"]
    if mutation == "reordered_events":
        payload["events_owned"] = list(reversed(payload["events_owned"]))
    elif mutation == "conflicting_segment":
        payload["segment_order"] = 4
    else:
        payload["events_owned"][0]["narrative_summary"] = ""
    current = (
        "### 第 5 段：当众坦白，归属落定\n\n"
        f"事件ID：{'、'.join(event_ids)}\n\n"
        "大纲依据：身份危机公开并完成核心坦白。\n\n"
        "段首承接：核验人员已经返回。\n\n"
        "本段事件：正式事件保持不变。\n\n"
        "段末交接：众人即将回应花穗的坦白。"
    )

    with pytest.raises(GeneratedArtifactShapeError):
        WorkflowService._normalize_generated_short_plan_segment(
            json.dumps(payload, ensure_ascii=False),
            segment=fixture["expected_segment"],
            event_ids=event_ids,
            current=current,
            artifact="invalid JSON packet",
        )


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


def test_production_short_plan_field_tables_cross_the_local_gate() -> None:
    """Regression for production run 4e79a0f402ad49a486a0122dafe24bc4."""
    plan = "\n\n".join((
        "### 第 1 段：假扮千金，熬过审视\n\n"
        "| 字段 | 内容 |\n|---|---|\n"
        "| **事件ID** | EV-11111111 |\n"
        "| **大纲依据** | 开篇钩子、目标驱动、初入沈府 |\n"
        "| **段首承接** | 无——全篇开端，花穗身无分文。 |\n"
        "| **本段事件** | 花穗被错认为沈家三小姐，为赏银决定冒充三天；"
        "入府后遭到审视，又发现接人的银两在她入府前已经支出。 |\n"
        "| **段末交接** | 花穗决定查清真相，身份核验人员正在路上。 |\n\n"
        "**场景原子节拍：**\n\n1. 花穗进入沈府并发现异常。" + "甲" * 100,
        "### 第 2 段：查清真相\n\n"
        "| 字段 | 内容 |\n|---|---|\n"
        "| **事件ID** | EV-22222222 |\n"
        "| **大纲依据** | 主动调查、关系推进、真相揭晓 |\n"
        "| **段首承接** | 花穗已经决定调查，身份核验仍在进行。 |\n"
        "| **本段事件** | 花穗借助府中人情网查清账目，并在公开对质中"
        "揭开幕后安排，保持自己的行动主体性。 |\n"
        "| **段末交接** | 真相已经公开，人物关系和确认结局保持一致。 |\n\n"
        "**场景原子节拍：**\n\n1. 花穗完成调查并作出选择。" + "乙" * 100,
    ))

    segments = WorkflowService._short_plan_segments(plan, 2)
    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), {}, plan, 2,
    )

    assert len(segments) == 2
    assert WorkflowService._short_plan_field(segments[0], "event_id") == (
        "EV-11111111"
    )
    assert "花穗被错认为" in WorkflowService._short_plan_field(
        segments[0], "event",
    )
    assert issues == []


@pytest.mark.parametrize(("event_label", "causal_label"), (
    ("本段事件", "本段因果链"),
    ("Narrative progression", "Causal chain"),
))
def test_short_plan_event_role_ignores_separate_causal_companion(
    event_label: str, causal_label: str,
) -> None:
    block = (
        "### 第 1 段：测试\n\n"
        "| 字段 | 内容 |\n|---|---|\n"
        "| 事件ID | EV-11111111 |\n"
        "| 大纲依据 | 已确认事件 |\n"
        "| 段首承接 | 主角尚未行动。 |\n"
        f"| {event_label} | EV-11111111 主角采取行动并取得明确结果。 |\n"
        "| 段末交接 | 主角已取得结果。 |\n\n"
        f"**{causal_label}**：前因触发行动，行动产生结果。"
    )

    event = WorkflowService._short_plan_field(block, "event")

    assert "EV-11111111 主角采取行动并取得明确结果" in event
    assert "前因触发行动" not in event


def test_short_plan_event_role_keeps_two_realizations_ambiguous() -> None:
    block = (
        "**本段事件**：EV-11111111 主角采取第一种行动。\n\n"
        "**剧情推进**：EV-11111111 主角采取互相冲突的第二种行动。"
    )

    assert WorkflowService._short_plan_field(block, "event") == ""


def test_causal_companion_plan_crosses_complete_local_gate_unchanged() -> None:
    def block(segment: int, event_id: str, fill: str) -> str:
        return (
            f"### 第 {segment} 段：测试\n\n"
            "| 字段 | 内容 |\n|---|---|\n"
            f"| 事件ID | {event_id} |\n"
            "| 大纲依据 | 已确认事件 |\n"
            "| 段首承接 | 主角保持上一段已确认状态。 |\n"
            f"| 本段事件 | {event_id} 主角采取行动并取得明确结果。{fill} |\n"
            "| 段末交接 | 主角已取得结果并进入下一状态。 |\n\n"
            "**本段因果链**：前因触发行动，行动产生结果。"
        )

    plan = "\n\n".join((
        block(1, "EV-11111111", "甲" * 90),
        block(2, "EV-22222222", "乙" * 90),
    ))
    state = {"outline": {"events": [
        {"id": "EV-11111111"}, {"id": "EV-22222222"},
    ]}}

    assert WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}), state, plan, 2,
    ) == []
    assert plan.count("**本段因果链**") == 2


def test_short_plan_gate_does_not_promote_nested_section_headings_to_events() -> None:
    outline = (
        "## 第 1 段：开端\n\n"
        "- **发现线索**：主角发现账册。\n\n"
        "## 第 2 段：收束\n\n"
        "- **查明真相**：主角核对账册并作出选择。"
    )
    contracts = narrative_outline_event_contracts(outline)
    assert [item["label"] for item in contracts] == ["发现线索", "查明真相"]
    plan = "\n\n".join((
        "### 第 1 段：开端\n"
        f"事件ID：{contracts[0]['id']}\n"
        "大纲依据：发现线索\n"
        "段首承接：主角尚未看见账册。\n"
        "本段事件：主角主动找到并打开账册。\n"
        "段末交接：主角已经知道账册存在。\n" + "甲" * 100,
        "### 第 2 段：收束\n"
        f"事件ID：{contracts[1]['id']}\n"
        "大纲依据：查明真相\n"
        "段首承接：主角带着账册继续核对。\n"
        "本段事件：主角查明真相并作出选择。\n"
        "段末交接：故事按既定结局结束。\n" + "乙" * 100,
    ))

    issues = WorkflowService._short_plan_issues(
        SimpleNamespace(path=Path("."), metadata={}),
        {"outline": {"content": outline}},
        plan,
        2,
    )

    assert issues == []


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


def test_local_planning_recovery_merges_only_the_segment_needed_for_improvement(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Monotonic local plan", mode="short", genre="suspense",
        premise="A local repair must not damage unrelated segments.",
        target_words=10000,
    ))

    def block(number: int, *, handoff: bool = True, suffix: str = "原稿") -> str:
        tail = f"段末交接：状态{number}已经成立。\n" if handoff else ""
        return (
            f"### 第 {number} 段：事件{number}\n"
            f"事件ID：EV-{number:08x}\n"
            f"大纲依据：事件{number}\n"
            f"段首承接：人物承接状态{number}。\n"
            f"本段事件：人物推进事件{number}。\n"
            f"{tail}{suffix}" + chr(0x4e00 + number) * 100
        )

    original_segments = [block(number) for number in range(1, 5)]
    original_segments[1] = block(2, handoff=False)
    best = "\n\n".join(original_segments)
    candidate_segments = [
        block(1, suffix="候选擅自重写"),
        block(2, suffix="只需采用的修正"),
        block(3, suffix="候选擅自重写"),
        block(4, handoff=False, suffix="候选引入的新问题"),
    ]
    candidate = "\n\n".join(candidate_segments)

    selected, issues, comparison = (
        WorkflowService._select_monotonic_short_plan_candidate(
            project, {}, best, candidate, 4,
        )
    )

    selected_segments = WorkflowService._short_plan_segments(selected, 4)
    assert issues == []
    assert comparison["improved"] is True
    assert comparison["selected_segments"] == [2]
    assert selected_segments[0] == original_segments[0]
    assert "只需采用的修正" in selected_segments[1]
    assert selected_segments[2] == original_segments[2]
    assert selected_segments[3] == original_segments[3]


def test_local_planning_recovery_accepts_scoped_ownership_progress_with_unmodified_control_issue(
    tmp_path,
) -> None:
    """A later-stage local repair must not be blocked by another segment's syntax issue."""

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Mixed-stage local plan", mode="short", genre="suspense",
        premise="One event repair must survive an unrelated missing handoff.",
        target_words=15000,
    ))
    event_ids = [
        "EV-10000001", "EV-10000002", "EV-20000001",
        "EV-30000001", "EV-40000001", "EV-50000001",
        "EV-60000001",
    ]

    def segment_ir(
        number: int, owned: tuple[str, ...], *, repaired: bool = True,
    ) -> str:
        body = (
            "\n\n".join(
                f"{event_id}: the actor meets resistance, acts, and leaves a verifiable result."
                for event_id in owned
            )
            if repaired else
            "The segment contains useful creative material but no event-owned realization."
        )
        return render_planning_segment_ir(PlanningSegmentIR(
            segment=number,
            heading=f"### Segment {number}: production-shaped planning unit",
            event_ids=owned,
            outline=f"Confirmed outline basis for segment {number}.",
            opening=f"Entry state for segment {number} remains unchanged.",
            event_body=body,
            handoff=f"Exit state for segment {number} remains unchanged.",
            source_sha256=f"{number:064x}",
        ))

    best_segments = [
        segment_ir(1, tuple(event_ids[:2]), repaired=False),
        *(
            segment_ir(number, (event_ids[number],))
            for number in range(2, 6)
        ),
        segment_ir(6, (event_ids[6],)),
    ]
    terminal = compile_planning_segment(best_segments[5]).values("handoff")[0]
    best_segments[5] = (
        best_segments[5][:terminal.span.start]
        + best_segments[5][terminal.span.end:]
    )
    best = "\n\n".join(best_segments)
    candidate_segments = list(best_segments)
    candidate_segments[0] = segment_ir(1, tuple(event_ids[:2]))
    candidate = "\n\n".join(candidate_segments)
    state = {"outline": {"events": [
        {"id": event_id, "label": event_id, "kind": "narrative"}
        for event_id in event_ids
    ]}}

    selected, issues, comparison = (
        WorkflowService._select_monotonic_short_plan_candidate(
            project, state, best, candidate, 6,
        )
    )

    selected_segments = WorkflowService._short_plan_segments(selected, 6)
    assert comparison["improved"] is True
    assert comparison["selected_segments"] == [1]
    assert comparison["previous_stage"] == "ownership"
    assert comparison["latent_baseline_issue_keys"] == [
        "planning:segment-06:local_required_fields",
    ]
    assert not any(
        key.startswith("planning:segment-01:")
        for key in comparison["candidate_issue_keys"]
    )
    assert any("planning:segment-06:local_required_fields" == key
               for key in comparison["candidate_issue_keys"])
    assert selected_segments[0] == candidate_segments[0]
    assert selected_segments[1:] == WorkflowService._short_plan_segments(
        best, 6,
    )[1:]
    assert issues


@pytest.mark.asyncio
async def test_local_planning_recovery_resumes_the_lowest_issue_candidate(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Resumable local plan", mode="short", genre="suspense",
        premise="An interrupted local repair resumes from the best candidate.",
        target_words=10000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("local-resume", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "local-resume"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()

    def block(number: int, *, handoff: bool) -> str:
        tail = f"段末交接：状态{number}已经成立。\n" if handoff else ""
        return (
            f"### 第 {number} 段：事件{number}\n"
            f"事件ID：EV-{number:08x}\n大纲依据：事件{number}\n"
            f"段首承接：人物承接状态{number}。\n"
            f"本段事件：人物推进事件{number}。\n{tail}"
            + chr(0x4e00 + number) * 110
        )

    initial = "\n\n".join(
        block(number, handoff=number not in {2, 3}) for number in range(1, 5)
    )
    partial = "\n\n".join(
        block(number, handoff=number != 3) for number in range(1, 5)
    )
    complete = "\n\n".join(
        block(number, handoff=True) for number in range(1, 5)
    )
    calls = 0

    async def interrupted_ir_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return partial
        raise ConnectionError("local planning repair interrupted")

    service._plan_short_ir_first = interrupted_ir_first
    with pytest.raises(ConnectionError, match="interrupted"):
        await service._recover_short_plan_local_gate(
            "local-resume", run_path, project, "constraints", "brief", {},
            initial, 4, 4800, generation_context_sha256="context-v2",
        )

    resumed = service._resumable_current_planning_adaptation_plan(
        run_path, project, {}, 4, "context-v2",
    )
    assert resumed == (partial, None, False)

    async def completing_ir_first(*args, **kwargs):
        return complete

    service._plan_short_ir_first = completing_ir_first
    accepted = await service._recover_short_plan_local_gate(
        "local-resume", run_path, project, "constraints", "brief", {},
        partial, 4, 4800, generation_context_sha256="context-v2",
    )

    assert accepted == complete
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert [item["accepted"] for item in recovery["candidates"]] == [True, True]
    assert recovery["status"] == "local_ready"


@pytest.mark.asyncio
async def test_table_plan_repairs_event_ownership_per_segment_without_whole_rewrite(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Table ownership recovery", mode="short", genre="suspense",
        premise="A field-table plan must recover by segment.", target_words=6000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    db.create_run("table-recovery", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "table-recovery"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = ["EV-11111111", "EV-22222222", "EV-33333333"]
    state = {"outline": {"events": [
        {"id": event_id, "label": f"正式事件{index}"}
        for index, event_id in enumerate(event_ids, 1)
    ]}}

    def table_block(number: int, owned: list[str], fill: str) -> str:
        return (
            f"### 第 {number} 段：规划段{number}\n\n"
            "| 字段 | 内容 |\n|---|---|\n"
            f"| **事件ID** | {', '.join(owned)} |\n"
            f"| **大纲依据** | 正式段{number} |\n"
            f"| **段首承接** | 第{number}段入口状态保持。 |\n"
            f"| **本段事件** | 第{number}段已有完整创作素材，但缺少逐事件机器绑定。 |\n"
            f"| **段末交接** | 第{number}段出口状态保持。 |\n\n"
            f"**场景原子节拍：**\n\n{fill}" + chr(0x4e00 + number) * 120
        )

    original = "\n\n".join((
        table_block(1, event_ids[:2], "人物调查并取得线索。"),
        table_block(2, event_ids[2:], "人物公开真相并作出选择。"),
    ))
    prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        prompts.append(prompt)
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in prompt:
            return json.dumps({
                "core_goal": "按已验收规划完成调查并公开真相",
                "opening": {"pressure": "线索有限", "anomaly": "身份有误"},
                "cycles": [
                    {
                        "obstacle": "调查受阻", "effort": "主角核对线索",
                        "result": "取得第一项结果", "state_change": "掌握新信息",
                    },
                    {
                        "obstacle": "对手阻挠", "effort": "主角公开证据",
                        "result": "真相得到确认", "state_change": "关系与目标改变",
                    },
                ],
                "accidents": [], "reversal": {},
                "ending": "主角完成选择并保留后续行动入口",
                "question_chain": "线索如何指向真相",
                "relationship_arc": "合作建立",
                "covered_event_ids": event_ids,
            }, ensure_ascii=False)
        match = re.search(
            r"EXPECTED EVENT IDS:\n(?P<ids>\[[^\n]+\])", prompt,
        )
        assert match is not None
        owned = json.loads(match.group("ids"))
        return json.dumps({"events": [
            {
                "event_id": event_id,
                "narrative": (
                    f"人物主动完成 {event_id} 的行动，遭遇阻力后取得结果，"
                    "并保持既定入口、出口、视角和人物关系。"
                ),
            }
            for event_id in owned
        ]}, ensure_ascii=False)

    service._stage = fake_stage
    recovered = await service._recover_short_plan_local_gate(
        "table-recovery", run_path, project, "constraints", "brief", state,
        original, 2, 5000, generation_context_sha256="table-context",
    )

    recovered_segments = WorkflowService._short_plan_segments(recovered, 2)
    # Segment 2 owns only one event and already has an independently
    # executable body, so the ownership validator must leave it byte-identical.
    assert len(prompts) == 1
    assert all("SHORT_PLAN_EVENT_REALIZATION_RECOVERY_V3" in item for item in prompts)
    assert all("LOCAL RECOVERY ATTEMPT" not in item for item in prompts)
    assert WorkflowService._short_plan_issues(project, state, recovered, 2) == []
    assert "第1段入口状态保持" in recovered_segments[0]
    assert "第2段出口状态保持" in recovered_segments[1]
    assert "EV-11111111" in WorkflowService._short_plan_field(
        recovered_segments[0], "event",
    )
    assert recovered_segments[1] == WorkflowService._short_plan_segments(
        original, 2,
    )[1]
    causal_chain = await service._ensure_short_causal_chain(
        "table-recovery", run_path, project, "constraints", recovered,
        state["outline"]["events"], None,
    )
    assert causal_chain["covered_event_ids"] == event_ids
    assert (run_path / "outputs" / "short-causal-chain.json").is_file()


@pytest.mark.asyncio
async def test_planning_adaptation_repair_returns_only_event_realizations_and_preserves_controls(
    tmp_path,
) -> None:
    """A semantic repair must not let the model rewrite Runtime-owned controls."""

    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="IR-only planning repair", mode="short", genre="mystery",
        premise="A formal event needs an executable realization.", target_words=13_000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_path = project.path / "runs" / "ir-only-planning-repair"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_id = "EV-A1B2C3D4"
    current = render_planning_segment_ir(PlanningSegmentIR(
        segment=1,
        heading="### Segment 1: Confirm the sealed record",
        event_ids=(event_id,),
        outline="The investigator must authenticate the sealed record.",
        opening="The record is sealed and its origin remains disputed.",
        event_body=f"{event_id}\nThe investigator notices the record.",
        handoff="The authenticated record establishes the confirmed ending state.",
        source_sha256="1" * 64,
    ))
    formal_events = [{
        "id": event_id,
        "order": 1,
        "label": "Authenticate the sealed record",
        "evidence": (
            "The investigator actively authenticates the sealed record, overcomes a "
            "challenge to its origin, obtains a verifiable result, and accepts the cost."
        ),
        "kind": "narrative",
    }]
    state = {"outline": {"events": formal_events}}
    prompts: list[str] = []

    async def event_only_stage(*args, **kwargs):
        prompt = args[5]
        prompts.append(prompt)
        expected = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
        )
        return json.dumps({"events": [{
            "event_id": owned,
            "narrative": (
                "The investigator actively performs the formal authentication, meets "
                "a concrete challenge, obtains a verifiable result, and updates the "
                "knowledge, relationship, and causal state owned by this event."
            ),
        } for owned in expected]}, ensure_ascii=False)

    service._stage = event_only_stage
    repaired = await service._repair_short_plan_adaptation_segments(
        "ir-only-planning-repair", run_path, project, "constraints", state,
        current, formal_events, 1,
        issues=[{
            "code": "event_realization_incomplete",
            "segment": 1,
            "event_id": event_id,
            "message": "The formal event lacks executable resistance and result.",
        }],
        mode="targeted",
    )

    assert len(prompts) == 1
    assert "SHORT_PLAN_EVENT_REALIZATION_REPAIR_V3" in prompts[0]
    assert "Return exactly one JSON object with one field named events" in prompts[0]
    assert WorkflowService._short_plan_segments(repaired, 1)[0].splitlines()[0] == (
        WorkflowService._short_plan_segments(current, 1)[0].splitlines()[0]
    )
    for field in ("event_id", "outline", "opening", "handoff"):
        assert WorkflowService._short_plan_field(repaired, field) == (
            WorkflowService._short_plan_field(current, field)
        )
    assert "obtains a verifiable result" in WorkflowService._short_plan_field(
        repaired, "event",
    )


def test_real_terminal_events_only_shape_binds_typed_closure_without_retry() -> None:
    outline = (
        "# Outline\n\n## Opening beat\nThe lead receives a sealed letter.\n\n"
        "## Ending beat\nThe lead answers the letter, accepts the cost, and keeps one clue open.\n"
    )
    formal_events = narrative_outline_event_contracts(outline)
    assert len(formal_events) == 2
    opening_2 = "The final segment starts with the letter opened and the cost visible."

    def segment_ir(number: int, event: dict, *, opening: str, handoff: str) -> str:
        event_id = str(event["id"]).upper()
        return render_planning_segment_ir(PlanningSegmentIR(
            segment=number,
            heading=f"### Segment {number}: Beat",
            event_ids=(event_id,),
            outline=str(event["label"]),
            opening=opening,
            event_body=(
                f"1. Formal event ({event_id}): The protagonist acts against "
                "resistance, obtains a concrete result, and changes the story state."
            ),
            handoff=handoff,
            source_sha256="0" * 64,
        ))

    first = segment_ir(
        1, formal_events[0], opening="The opening pressure begins.",
        handoff=opening_2,
    )
    final_with_legacy_handoff = segment_ir(
        2, formal_events[1], opening=opening_2,
        handoff="legacy placeholder that the provider omitted",
    )
    marker = "\n\n" + PLAN_FIELD_ALIASES["handoff"][0]
    assert marker in final_with_legacy_handoff
    final_without_next_handoff = final_with_legacy_handoff.split(marker, 1)[0]
    source_plan = first + "\n\n" + final_without_next_handoff
    state = {"outline": {"content": outline, "events": formal_events}}

    normalized_plan, audit = WorkflowService._normalize_short_plan_terminal_boundary(
        source_plan, state=state, segment_count=2,
    )

    assert audit is not None and audit["converted"] is True
    normalized_segments = WorkflowService._short_plan_segments(normalized_plan, 2)
    terminal_handoff = WorkflowService._short_plan_field(
        normalized_segments[-1], "handoff",
    )
    assert terminal_handoff == formal_events[-1]["evidence"]
    assert audit["terminal_event_ids"] == [str(formal_events[-1]["id"]).upper()]

    terminal_event_id = str(formal_events[-1]["id"]).upper()
    events_only = json.dumps({"events": [{
        "event_id": terminal_event_id,
        "narrative": (
            "The protagonist answers the letter under pressure, accepts the exact cost, "
            "and deliberately retains the authorized open clue for later consequences."
        ),
    }]})
    repaired = WorkflowService._normalize_runtime_owned_short_plan_payload(
        events_only,
        segment=2,
        event_ids=[terminal_event_id],
        current=normalized_segments[-1],
        artifact="real terminal events-only replay",
    )
    assert planning_event_body_issues(repaired, [terminal_event_id]) == []
    assert WorkflowService._short_plan_field(repaired, "handoff") == terminal_handoff

    nonterminal_without_handoff = first.split(marker, 1)[0]
    unprovable_plan = nonterminal_without_handoff + "\n\n" + final_with_legacy_handoff
    unchanged, unprovable_audit = (
        WorkflowService._normalize_short_plan_terminal_boundary(
            unprovable_plan, state=state, segment_count=2,
        )
    )
    assert unchanged == unprovable_plan
    assert unprovable_audit is None


@pytest.mark.asyncio
async def test_event_ownership_exhaustion_preserves_plan_without_whole_rewrite(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Ownership budget", mode="short", genre="mystery",
        premise="Local recovery must retain the protected plan.", target_words=6000,
    ))
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    run_id = "ownership-budget"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    event_ids = ["EV-11111111", "EV-22222222", "EV-33333333"]
    state = {"outline": {"events": [
        {"id": event_id, "label": event_id} for event_id in event_ids
    ]}}
    def table_block(number: int, owned: list[str]) -> str:
        return (
            f"### 第 {number} 段：规划段{number}\n\n"
            "| 字段 | 内容 |\n|---|---|\n"
            f"| 事件ID | {', '.join(owned)} |\n"
            f"| 大纲依据 | 正式段{number} |\n"
            f"| 段首承接 | 第{number}段入口状态保持。 |\n"
            f"| 本段事件 | 第{number}段已有完整创作素材，但缺少逐事件机器绑定。 |\n"
            f"| 段末交接 | 第{number}段出口状态保持。 |\n\n"
            "场景节拍：" + "人物持续行动、遭遇阻力、取得结果并形成下一步。" * 40
        )

    original = "\n\n".join((
        table_block(1, event_ids[:2]), table_block(2, event_ids[2:]),
    ))
    calls: list[int] = []

    async def fail_segment(*args, **kwargs):
        calls.append(int(kwargs["attempt"]))
        raise GeneratedArtifactShapeError("invalid event realization")

    async def forbid_whole_stage(*args, **kwargs):
        raise AssertionError("whole-plan fallback must not run")

    service._repair_short_plan_local_event_segment = fail_segment
    service._stage = forbid_whole_stage

    with pytest.raises(GeneratedArtifactShapeError, match="分段恢复尚未收敛"):
        await service._recover_short_plan_local_gate(
            run_id, run_path, project, "constraints", "brief", state,
            original, 2, 5000, generation_context_sha256="ownership-context",
        )

    assert calls == [1, 2]
    recovery = read_planning_recovery(run_path / "outputs")
    assert recovery is not None and recovery[1] == original
    event = next(
        item for item in db.list_run_events(run_id)
        if item["event_type"] == "planning_event_ownership_recovery_exhausted"
    )
    assert event["metadata"]["whole_plan_fallback_used"] is False


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
    assert "Skill instructions and story authority" in gateway.calls[1]["system"]
    assert "MANDATORY_NARRATIVE_RULES" in gateway.calls[1]["system"]
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
async def test_structural_polish_hard_reject_preserves_source_without_rewrite_retry(
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

        async def complete_primary(
            self, role, system, user, max_output_tokens=None,
        ):
            return await self.complete(
                role, system, user,
                max_output_tokens=max_output_tokens,
            )

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

    assert WorkflowService._split_segments(polished) == ["A" * 1000, "C" * 1000]
    assert gateway.routes == ["primary"]
    assert not any(
        event["event_type"] in {"polish_validation_fallback", "polish_targeted_repair"}
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
    service._save_quality_checkpoint(
        run_path, previous, previous_review, 1, "passed",
    )

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
async def test_current_pass_is_not_replaced_by_higher_scoring_conditional_history(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Eligibility before score", mode="short", genre="suspense",
        premise="A fully passing candidate must beat a conditional draft.",
        target_words=8_000,
    ))
    project = store.apply_platform_profile(project.id, "zhihu-salt-short")
    service = WorkflowService(
        db, store, RecordingGateway([]), SkillGate(db, SkillScanner([])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    historical = "\u5386\u53f2\u6761\u4ef6\u901a\u8fc7\u5019\u9009\u3002" * 900
    current = "\u5f53\u524d\u5b8c\u6574\u901a\u8fc7\u5019\u9009\u3002" * 900
    historical_review = score_review({
        "dimensions": {"commercial": 95, "story": 95, "prose": 67},
        "hard_fail": False, "decision": "revise", "issues": [],
        "judge_signature": "provider/final-model",
    }, "zhihu-short-v2")
    current_review = score_review({
        "dimensions": {"commercial": 80, "story": 80, "prose": 80},
        "hard_fail": False, "decision": "pass", "issues": [],
        "judge_signature": "provider/final-model",
    }, "zhihu-short-v2")
    service._save_quality_checkpoint(
        run_path, historical, historical_review, 1, "conditional_pass",
    )

    async def polish(*args, **kwargs):
        return current

    async def reader(*args, **kwargs):
        return current_review

    async def final_review(*args, **kwargs):
        return current_review, {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 1, "window_count": 1,
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0,
        "prose": {"blocking_count": 0},
        "text_hash": hashlib.sha256(current.encode("utf-8")).hexdigest(),
    })

    selected, report = await service._quality_polish(
        run_id, run_path, project, "constraints", current, current_review,
    )

    assert selected == current
    assert report["status"] == "passed"
    assert report["terminal_reviewed_hash"] == hashlib.sha256(
        current.encode("utf-8"),
    ).hexdigest()
    checkpoint = load_quality_checkpoint(run_path)
    assert checkpoint is not None
    assert checkpoint["outcome"] == "passed"
    assert checkpoint["manuscript_hash"] == report["terminal_reviewed_hash"]


@pytest.mark.asyncio
async def test_short_story_stops_on_safe_conditional_pass(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Conditional", mode="short", genre="romance",
        premise="A relationship changes.", target_words=6000,
    ))
    store.set_optimized_local_review(project.id, False)
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    conditional = quality_review(
        commercial=75, story=75, prose=75, decision="revise",
        issues=[{
            "category": "prose",
            "severity": "medium",
            "evidence": "One paragraph is less concise than the surrounding prose.",
            "action": "Tighten one paragraph.",
        }],
    )
    service = WorkflowService(
        db, store, RecordingGateway([]),
        SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "conditional manuscript " * 500
    conditional_review = service._review(conditional)

    async def polish(*args, **kwargs):
        return candidate

    async def reader(*args, **kwargs):
        return conditional_review

    async def final_review(*args, **kwargs):
        return conditional_review, {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 1, "window_count": 1,
        }

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(service, "_reader_review", reader)
    monkeypatch.setattr(service, "_full_manuscript_review", final_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {})

    with pytest.raises(RuntimeError, match="requires a full pass"):
        await service._quality_polish(
            run_id, run_path, project, "constraints", candidate,
            service._review(quality_review()),
        )

    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    assert report["status"] == "conditional_pass"
    assert report["final_attempts"][0]["outcome"] == "conditional_pass"
    checkpoint = load_quality_checkpoint(run_path)
    assert checkpoint is not None
    assert checkpoint["outcome"] == "conditional_pass"
    event = next(
        item for item in db.list_run_events(run_id)
        if item["event_type"] == "quality_conditional_pass"
    )
    assert event["severity"] == "warning"
    assert "还不能设为正式稿" in event["message"]


@pytest.mark.asyncio
async def test_short_story_recovers_once_when_reference_corpus_changes_before_promotion(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Corpus retry", mode="short", genre="suspense",
        premise="A stable publication retry.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(),
        "# Publishable candidate", quality_review(),
        json.dumps({"facts": [], "state": {}}),
        json.dumps({"facts": [], "state": {}}),
    ])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    checks = 0

    def one_stale_check(_project, _analysis):
        nonlocal checks
        checks += 1
        if checks == 1:
            raise RuntimeError("Reference corpus changed after originality analysis")
        return "stable-corpus"

    monkeypatch.setattr(
        service, "_assert_current_reference_corpus_authority", one_stale_check,
    )

    result = await service.run_short(project.id, use_crewai=False)

    assert result["status"] == "completed"
    assert checks == 2
    assert gateway.roles.count("maintenance") == 2
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == "# Publishable candidate"
    event = next(
        item for item in db.list_run_events(result["id"])
        if item["event_type"] == "reference_corpus_changed_before_promotion"
    )
    assert event["metadata"]["attempt"] == 1


@pytest.mark.asyncio
async def test_short_story_stops_without_formal_write_when_corpus_never_stabilizes(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Corpus churn", mode="short", genre="suspense",
        premise="The reference corpus keeps changing.", target_words=6000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(),
        "# Publishable candidate", quality_review(),
        json.dumps({"facts": [], "state": {}}),
        json.dumps({"facts": [], "state": {}}),
    ])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    formal = project.path / "manuscript" / "story.md"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text("protected formal manuscript", encoding="utf-8")

    def always_stale(_project, _analysis):
        raise RuntimeError("Reference corpus changed after originality analysis")

    monkeypatch.setattr(
        service, "_assert_current_reference_corpus_authority", always_stale,
    )

    with pytest.raises(RuntimeError, match="did not stabilize"):
        await service.run_short(project.id, use_crewai=False)

    assert formal.read_text(encoding="utf-8") == "protected formal manuscript"
    assert gateway.roles.count("maintenance") == 2


@pytest.mark.asyncio
async def test_stale_story_state_never_rolls_back_a_newer_formal_promotion(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="StoryState CAS", mode="short", genre="suspense",
        premise="Another writer commits first.", target_words=6000,
    ))
    initial_state = StoryStateStore(db).ensure(project.id, project.path)
    formal = project.path / "manuscript" / "story.md"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text("old formal manuscript", encoding="utf-8")
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([
        "# Plan", "# Draft", quality_review(), quality_review(),
        "# Stale candidate", quality_review(),
        json.dumps({"facts": [], "state": {}}),
    ])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    original_get = service.story_states.get
    ready_for_concurrent_commit = False
    concurrent_commit_done = False

    def corpus_is_stable(_project, _analysis):
        nonlocal ready_for_concurrent_commit
        ready_for_concurrent_commit = True
        return "stable-corpus"

    def concurrent_story_state(project_id):
        nonlocal concurrent_commit_done
        if ready_for_concurrent_commit and not concurrent_commit_done:
            concurrent_commit_done = True
            formal.write_text("newer formal manuscript", encoding="utf-8")
            with db.connect() as connection:
                connection.execute(
                    "UPDATE story_states SET revision=revision+1 WHERE project_id=?",
                    (project_id,),
                )
        return original_get(project_id)

    monkeypatch.setattr(
        service, "_assert_current_reference_corpus_authority", corpus_is_stable,
    )
    monkeypatch.setattr(service.story_states, "get", concurrent_story_state)

    with pytest.raises(RuntimeError, match="StoryState changed"):
        await service.run_short(project.id, use_crewai=False)

    assert concurrent_commit_done is True
    assert formal.read_text(encoding="utf-8") == "newer formal manuscript"
    current = original_get(project.id)
    assert current is not None
    assert current.revision == initial_state.revision + 1


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

    assert 2 <= gateway.roles.count("planning") <= 3
    assert 1 <= gateway.roles.count("review") <= 2
    assert "polish" not in gateway.roles
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
    assert any(event["event_type"] == "polish_output_limit_retry" for event in events)
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
    assert repair_prompt == gateway.calls[0]["user"]
    assert malformed not in repair_prompt
    assert "COMPACT SEGMENT MAP" in repair_prompt
    assert "UNIQUE MANUSCRIPT MATERIAL" in repair_prompt


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

    gateway = expose_test_primary_route(Gateway())
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
async def test_transport_failure_retries_without_splitting_or_draft_fallback(tmp_path) -> None:
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

    gateway = expose_test_primary_route(Gateway())
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
    events = db.list_run_events("split-retry")
    assert any(event["event_type"] == "polish_transport_retry" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)


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

    gateway = expose_test_primary_route(Gateway())
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
    assert service._output_budget_for_call(
        "planning", None, "polish", False,
        expected_output_characters=1600,
        bounded_protocol_output=True,
    ) == service._output_budget_for_call(
        "planning", None, "polish", True,
        expected_output_characters=1600,
        bounded_protocol_output=True,
    )
    assert service._output_budget_for_call(
        "planning", None, "polish", False,
        expected_output_characters=1600,
        scoped_creative_output=True,
    ) == 4624
    assert service._output_budget_for_call(
        "planning", None, "polish", True,
        expected_output_characters=1600,
        scoped_creative_output=True,
    ) == 3072


@pytest.mark.asyncio
async def test_stage_context_pressure_invokes_semantic_splitter_before_provider(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="review-model", provider_id="provider", display_name="Review",
        model_name="review-model",
    )
    db.save_role_binding("review", "provider", "review-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Capacity split", mode="short", genre="suspense",
        premise="A review packet approaches the route capacity.", target_words=5000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["provider must not be called"])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("capacity-split", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "capacity-split"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    split_details = []

    async def splitter(details):
        split_details.append(details)
        return '{"status":"complete"}'

    result = await service._stage(
        "capacity-split", run_path, project, "review",
        "MUST preserve the confirmed plot direction.",
        "正式事件审核材料。" * 12_000,
        allow_tools=False,
        route_capacity_guard=True,
        capacity_splitter=splitter,
    )

    assert result == '{"status":"complete"}'
    assert split_details and split_details[0]["context_window"] == 32_768
    assert gateway.calls == []
    events = db.list_run_events("capacity-split")
    assert any(item["event_type"] == "stage_capacity_split_requested" for item in events)
    assert any(item["event_type"] == "stage_capacity_split_completed" for item in events)
    assert not any(item["event_type"] == "stage_failed" for item in events)


@pytest.mark.asyncio
async def test_nonlayered_maintenance_preflight_splits_before_small_routes(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="maintenance-model", provider_id="provider",
        display_name="Maintenance", model_name="maintenance-model",
        context_window=2048, max_output_tokens=768,
    )
    db.save_role_binding(
        "maintenance", "provider", "maintenance-model", None, None,
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Maintenance preflight", mode="short", genre="science fiction",
        premise="Every middle fact must reach StoryState.", target_words=5000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["provider must not be called"])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run(
        "maintenance-preflight", project.id, "short-story", status="running",
    )
    run_path = project.path / "runs" / "maintenance-preflight"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    split_details: list[dict] = []

    async def splitter(details):
        split_details.append(details)
        return '{"status":"complete"}'

    result = await service._stage(
        "maintenance-preflight", run_path, project, "maintenance",
        "Preserve every confirmed fact.", "中段事实不可省略。" * 5000,
        allow_tools=False,
        route_capacity_guard=True,
        capacity_splitter=splitter,
        bounded_protocol_output=True,
    )

    assert result == '{"status":"complete"}'
    assert result.receipt["execution_mode"] == "capacity_split"
    assert split_details[0]["trigger"] == "preflight"
    assert split_details[0]["context_window"] == 2048
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_bounded_protocol_stage_sheds_only_advisory_context_before_split(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="review-model", provider_id="provider", display_name="Review",
        model_name="review-model", context_window=32_768,
    )
    db.save_role_binding("review", "provider", "review-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Advisory shed", mode="short", genre="suspense",
        premise="A protocol retry sits just above the safe context line.",
        target_words=5000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway(["{\"status\":\"complete\"}"])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("advisory-shed", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "advisory-shed"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    pressures = iter(["compact", "full"])

    monkeypatch.setattr(
        "novel_flywheel.workflows.classify_input_pressure",
        lambda **_kwargs: next(pressures),
    )

    result = await service._stage(
        "advisory-shed", run_path, project, "review",
        "MUST preserve every confirmed story invariant.",
        "Return one bounded protocol object.", allow_tools=False,
        route_capacity_guard=True, bounded_protocol_output=True,
        expected_output_characters=800,
    )

    assert result == '{"status":"complete"}'
    assert len(gateway.calls) == 1
    assert "[advisory]" not in gateway.calls[0]["system"]
    event = next(
        item for item in db.list_run_events("advisory-shed")
        if item["event_type"] == "stage_advisory_context_shed"
    )
    assert event["metadata"]["remaining_pressure"] == "full"
    assert event["metadata"]["after_required_tokens"] <= (
        event["metadata"]["before_required_tokens"]
    )


@pytest.mark.parametrize("provider_error", [
    RuntimeError("HTTP 413 context_length_exceeded: prompt is too long"),
    ModelRoutesExhaustedError(
        RuntimeError("maximum context length exceeded"),
        RuntimeError("status code 413 request too large"),
    ),
])
@pytest.mark.asyncio
async def test_stage_provider_context_overflow_invokes_same_semantic_splitter(
    tmp_path, provider_error: Exception,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="review-model", provider_id="provider", display_name="Review",
        model_name="review-model", context_window=131_072,
    )
    db.save_role_binding("review", "provider", "review-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Provider capacity split", mode="short", genre="suspense",
        premise="The provider reports a smaller hidden context window.",
        target_words=5000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class OverflowGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            raise provider_error

    gateway = OverflowGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run("provider-capacity", project.id, "short-story", status="running")
    run_path = project.path / "runs" / "provider-capacity"
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    split_details: list[dict] = []

    async def splitter(details):
        split_details.append(details)
        return '{"status":"complete"}'

    result = await service._stage(
        "provider-capacity", run_path, project, "review",
        "MUST preserve the confirmed plot direction.",
        "A compact review request that fits declared metadata.",
        allow_tools=False,
        route_capacity_guard=True,
        capacity_splitter=splitter,
        completion_check=lambda value: json.loads(value)["status"] == "complete",
    )

    assert result == '{"status":"complete"}'
    assert result.receipt["trigger"] == "provider"
    assert gateway.calls == 1
    assert split_details[0]["trigger"] == "provider"
    assert split_details[0]["provider_error"] == "input_context_overflow"
    events = db.list_run_events("provider-capacity")
    requested = next(
        item for item in events
        if item["event_type"] == "stage_capacity_split_requested"
    )
    assert requested["metadata"]["trigger"] == "provider"
    assert any(
        item["event_type"] == "stage_capacity_split_completed"
        for item in events
    )


@pytest.mark.asyncio
async def test_capacity_split_failure_does_not_inherit_stale_provider_context(
    tmp_path,
) -> None:
    class OverflowGateway:
        async def complete(self, *_args, **_kwargs):
            raise RuntimeError("HTTP 413 context_length_exceeded")

    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, OverflowGateway(), run_id="detached-capacity-error",
    )
    db.save_role_binding("review", "primary", "review-model", None, None)

    async def splitter(_details):
        raise ValueError("evidence_quote_unbound")

    with pytest.raises(ValueError) as captured:
        await service._stage(
            "detached-capacity-error", run_path, project, "review",
            "MUST preserve the confirmed plot direction.",
            "A compact review request that fits declared metadata.",
            allow_tools=False,
            route_capacity_guard=True,
            capacity_splitter=splitter,
        )

    assert str(captured.value) == "evidence_quote_unbound"
    assert captured.value.__context__ is None
    assert classify_model_failure(captured.value) == "normal_invalid_output"


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

    assert gateway.budgets[0] == 1606
    assert gateway.budgets[1] == gateway.budgets[0] * 2
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
async def test_polish_output_limit_expands_same_prompt_then_splits(tmp_path) -> None:
    paragraphs = [f"段落{index}保留独立事件。" + chr(64 + index) * 430 for index in range(1, 5)]
    source = "\n\n".join(paragraphs)

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((user, max_output_tokens))
            if len(self.calls) <= 2:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                    "output_tokens": max_output_tokens,
                })
            return ModelResult(user.split("MANUSCRIPT SEGMENT:\n", 1)[1], {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    assert gateway.calls[0][0] == gateway.calls[1][0]
    assert gateway.calls[1][1] > gateway.calls[0][1]
    events = db.list_run_events("polish-recovery")
    output_retry = [
        event for event in events if event["event_type"] == "polish_output_limit_retry"
    ]
    assert len(output_retry) == 1
    assert output_retry[0]["metadata"]["failure_class"] == "output_limit"
    assert any(event["event_type"] == "polish_segment_split" for event in events)
    assert not any(event["event_type"] == "polish_compact_retry" for event in events)


@pytest.mark.asyncio
async def test_explicit_input_overflow_compacts_without_losing_authority(tmp_path) -> None:
    source = "她核对账本里的名字，仍不知道密室位置。" * 35

    class Gateway:
        def __init__(self):
            self.prompts = []

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            self.prompts.append(user)
            if len(self.prompts) == 1:
                raise RuntimeError("maximum context length exceeded")
            return ModelResult(source, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

        async def complete(self, *args, **kwargs):
            raise AssertionError("ordinary polish should keep the selected primary route")

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    assert len(gateway.prompts) == 2
    assert all(prompt.count(source) == 1 for prompt in gateway.prompts)
    for field in ("MINIMUM NARRATIVE AUTHORITY", "LOCKED FACTS", "ALLOWED SCOPE"):
        assert all(field in prompt for prompt in gateway.prompts)
    events = db.list_run_events("polish-recovery")
    compact_retry = next(
        event for event in events if event["event_type"] == "polish_input_compact_retry"
    )
    assert compact_retry["metadata"]["failure_class"] == "input_context_overflow"
    assert not any(event["event_type"] == "polish_segment_split" for event in events)


@pytest.mark.asyncio
async def test_known_context_window_preflights_full_input_before_provider_call(tmp_path) -> None:
    source = "A complete source segment preserves every event. " * 20

    class Gateway:
        def __init__(self):
            self.prompts = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.prompts.append(user)
            return ModelResult(source, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://example.test", auth_type="bearer", timeout_seconds=180,
        extra_headers={},
    )
    db.save_model(
        model_id="primary-model", provider_id="primary", display_name="Primary",
        model_name="primary-model", context_window=6000, max_output_tokens=4000,
    )
    packet = build_polish_authority_packet(source=source)
    compact_prompt = WorkflowService._compact_polish_prompt(
        authority_packet=packet, local_findings=[],
    )
    full_prompt = "DISCARDABLE ADVISORY:\n" + "x" * 20_000 + "\n\n" + compact_prompt

    result = await service._ordinary_polish_segment(
        "polish-recovery", run_path, project, "constraints", source,
        full_prompt, compact_prompt, "-preflight", 700, 1800, False,
        {"segment": 1, "total": 1},
    )

    assert result[0] == source
    assert result[2] is True
    assert gateway.prompts == [compact_prompt]
    assert any(
        event["event_type"] == "polish_input_compact_retry"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_transport_retries_same_route_then_configured_fallback_without_split(
    tmp_path,
) -> None:
    source = "A complete scene preserves every event and stable transition. " * 20

    class Gateway:
        def __init__(self):
            self.routes = []

        async def complete_primary(self, role, system, user, max_output_tokens=None):
            self.routes.append("primary")
            raise RuntimeError("ConnectError: connection reset")

        async def complete_configured_fallback(
            self, role, system, user, max_output_tokens=None,
        ):
            self.routes.append("fallback")
            return ModelResult(source, {
                "model_name": "backup", "configured_fallback_direct": True,
                "finish_reason": "end_turn",
            })

    gateway = Gateway()
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert gateway.routes == ["primary", "primary", "fallback"]
    events = db.list_run_events("polish-recovery")
    transport_retry = next(
        event for event in events if event["event_type"] == "polish_transport_retry"
    )
    assert transport_retry["metadata"]["failure_class"] == "transport_interrupted"
    fallback = next(
        event for event in events if event["event_type"] == "polish_configured_fallback"
    )
    assert fallback["metadata"]["failure_class"] == "transport_interrupted"
    assert not any(event["event_type"] == "polish_segment_split" for event in events)


@pytest.mark.asyncio
async def test_one_failed_split_child_preserves_entire_parent(tmp_path) -> None:
    paragraphs = [(f"Paragraph {index} keeps its distinct event. " * 11).strip()
                  for index in range(4)]
    source = "\n\n".join(paragraphs)

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            segment = user.split("MANUSCRIPT SEGMENT:\n", 1)[1]
            if self.calls <= 2:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            if self.calls == 3:
                return ModelResult(segment.replace("keeps", "retains", 1), {
                    "model_name": "primary", "finish_reason": "end_turn",
                })
            return ModelResult("too short", {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    checkpoint = json.loads((
        run_path / "outputs" / "polish-checkpoints" / "initial" / "part-01.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["accepted"] is False
    assert any(
        event["event_type"] == "polish_split_child_rejected"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_split_children_must_pass_merged_parent_validation(tmp_path) -> None:
    left = "\n\n".join((f"Left event {index} remains distinct. " * 11).strip()
                        for index in range(2))
    right = "\n\n".join((f"Right event {index} remains distinct. " * 11).strip()
                         for index in range(2))
    source = left + "\n\n" + right

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            if self.calls <= 2:
                return ModelResult("", {
                    "model_name": "primary", "finish_reason": "max_tokens",
                })
            return ModelResult(left, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    assert any(
        event["event_type"] == "polish_split_parent_rejected"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_output_limit_retries_primary_with_larger_budget(tmp_path) -> None:
    source = "A continuous scene with fixed events and natural sentence rhythm. " * 20

    class Gateway(ExplicitPrimaryGateway):
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
    assert gateway.calls[1]["prompt"] == gateway.calls[0]["prompt"]
    assert gateway.calls[1]["max_output_tokens"] > gateway.calls[0]["max_output_tokens"]
    events = db.list_run_events("polish-recovery")
    assert any(event["event_type"] == "polish_output_limit_retry" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)
    assert not any(event["event_type"] == "polish_compact_retry" for event in events)


@pytest.mark.asyncio
async def test_polish_nonempty_max_token_output_is_discarded_before_same_prompt_retry(
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
    assert (run_path / "outputs" / "polish-part-01.md").read_text(
        encoding="utf-8"
    ) == source


@pytest.mark.asyncio
async def test_polish_empty_tool_use_output_retries_without_compacting_input(tmp_path) -> None:
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

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == source.strip()
    assert len(gateway.prompts) == 2
    assert gateway.prompts[1] == gateway.prompts[0]
    assert any(
        event["event_type"] == "polish_tool_use_retry"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_output_limit_without_safe_split_preserves_parent(tmp_path) -> None:
    source = "A witness revisits the scene and verifies every fixed event carefully. " * 18

    class Gateway(ExplicitPrimaryGateway):
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
    assert [route for route, _ in gateway.routes] == [False, False]
    assert gateway.routes[1][1] == gateway.routes[0][1]
    events = db.list_run_events("polish-recovery")
    assert any(event["event_type"] == "polish_capacity_preserved" for event in events)
    assert not any(event["event_type"] == "polish_segment_split" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_text", ["", "source"])
async def test_polish_validation_fallback_max_tokens_expands_then_preserves_source(
    tmp_path, fallback_text,
) -> None:
    source = "A locally valid source segment keeps every established event in natural prose. " * 16

    class Gateway(ExplicitPrimaryGateway):
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
    assert [route for route, _ in gateway.routes] == ["primary", "fallback", "fallback"]
    assert any(
        event["event_type"] == "polish_output_limit_retry"
        for event in db.list_run_events("polish-recovery")
    )
    checkpoint = json.loads((
        run_path / "outputs" / "polish-checkpoints" / "initial" / "part-01.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["accepted"] is False


@pytest.mark.asyncio
async def test_polish_validation_fallback_fatal_error_stops_immediately(tmp_path) -> None:
    source = "A source segment keeps every established event in naturally paced prose. " * 16

    class Gateway(ExplicitPrimaryGateway):
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
async def test_polish_validation_fallback_transport_error_preserves_without_split(tmp_path) -> None:
    paragraphs = [(str(index) + "A" * 399) for index in range(4)]
    source = "\n\n".join(paragraphs)

    class Gateway(ExplicitPrimaryGateway):
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
    assert gateway.routes == ["primary", "fallback"]
    assert not any(
        event["event_type"] == "polish_segment_split"
        for event in db.list_run_events("polish-recovery")
    )


@pytest.mark.asyncio
async def test_polish_recovery_counts_all_returned_receipt_input_tokens(tmp_path) -> None:
    first = "A complete source segment preserves a stable event in natural prose. " * 16
    second = "A second source segment preserves another stable event in natural prose. " * 16

    class Gateway(ExplicitPrimaryGateway):
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
            round_cap_override=200,
        )

    assert gateway.routes == ["primary", "fallback"]


def test_polish_recovery_counts_empty_output_exception_receipt_tokens() -> None:
    error = RuntimeError("polish model returned empty output")
    error.receipt = {"input_tokens": 110, "finish_reason": "end_turn"}

    assert WorkflowService._polish_input_tokens(error) == 110


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

    gateway = expose_test_primary_route(Gateway())
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

    gateway = expose_test_primary_route(Gateway())
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
async def test_polish_obviously_long_output_uses_same_prompt_fallback(tmp_path) -> None:
    source = "A measured scene preserves every established fact without repetition. " * 18

    class Gateway(ExplicitPrimaryGateway):
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
    assert [route for route, _ in gateway.routes] == [False, True]
    assert gateway.routes[1][1] == gateway.routes[0][1]


@pytest.mark.asyncio
async def test_polish_unsplittable_output_limit_preserves_source_and_continues(tmp_path) -> None:
    first = "The first segment keeps its established event and measured sentence rhythm. " * 16
    second = "The second segment continues independently with another established event. " * 16
    improved_second = second.replace("continues", "moves forward")

    class Gateway(ExplicitPrimaryGateway):
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
    assert gateway.routes == [False, False, False]
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

    gateway = expose_test_primary_route(Gateway())
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

    gateway = expose_test_primary_route(Gateway())
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
async def test_polish_two_consecutive_output_errors_keep_full_prompt_for_later_segments(
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

    gateway = expose_test_primary_route(Gateway())
    db, project, service, run_path = make_polish_recovery_service(tmp_path, gateway)
    manuscript = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)

    await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", manuscript, "{}",
    )

    assert len(gateway.prompts) == 5
    assert "只返回修改后的正文，不解释、不分析" not in gateway.prompts[4]
    assert not any(
        event["event_type"] == "polish_compact_circuit_opened"
        for event in db.list_run_events("polish-recovery")
    )

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

    class Gateway(ExplicitPrimaryGateway):
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
    assert gateway.routes == [False, False, False, False]
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

        async def complete_primary(
            self, role, system, user, max_output_tokens=None,
        ):
            return await self.complete(
                role, system, user,
                max_output_tokens=max_output_tokens,
            )

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
            self.prompts = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            self.prompts.append(user)
            text = source if self.calls == 1 else "她听清了：侯府三小姐林知晚，那些词忽然都有了陌生的分量。"
            return ModelResult(text, {"model_name": "claude", "finish_reason": "end_turn"})

    gateway = expose_test_primary_route(Gateway())
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
    events = db.list_run_events("retry-rhythm")
    assert any(event["event_type"] == "polish_rhythm_retry" for event in events)
    targeted_event = next(
        event for event in events if event["event_type"] == "polish_targeted_repair"
    )
    assert targeted_event["metadata"]["policy_source_ids"] == ["style-profile"]
    assert targeted_event["metadata"]["raw_metrics"]["source"]
    assert targeted_event["metadata"]["raw_metrics"]["candidate"]
    assert targeted_event["metadata"]["baseline"]
    assert targeted_event["metadata"]["authority_hash"]
    assert "TARGETED LOCAL PROSE REPAIR" in gateway.prompts[1]
    assert "MINIMUM NARRATIVE AUTHORITY" in gateway.prompts[1]
    assert gateway.prompts[1].count(source) == 1


@pytest.mark.asyncio
async def test_project_style_allowance_records_exact_rule_source_and_metrics(tmp_path) -> None:
    source = "A measured sentence carries the action forward with enough context. " * 8
    candidate = (
        "Door opened. Name matched. Debt was real. She understood. "
        + "A measured sentence carries the action forward with enough context. " * 6
    )

    class Gateway:
        async def complete(self, role, system, user, max_output_tokens=None):
            return ModelResult(candidate, {
                "model_name": "primary", "finish_reason": "end_turn",
            })

    db, project, service, run_path = make_polish_recovery_service(
        tmp_path, expose_test_primary_route(Gateway()),
    )
    (project.path / "style-profile.md").write_text(
        "# 文风\n\n- 信息揭示时允许短句形成局部落点。\n",
        encoding="utf-8",
    )
    service._polish_narrative_context = lambda *args, **kwargs: {
        "reveals": ["identity"],
    }

    result = await service._polish_short_segments(
        "polish-recovery", run_path, project, "constraints", source, "{}",
    )

    assert result == candidate.strip()
    event = next(
        item for item in db.list_run_events("polish-recovery")
        if item["event_type"] == "polish_style_allowance"
    )
    assert event["metadata"]["policy_source_ids"] == ["style-profile"]
    assert event["metadata"]["style_allowances"][0]["authorized_beats"] == [
        "information_reveal"
    ]
    assert event["metadata"]["raw_metrics"]["source"]
    assert event["metadata"]["raw_metrics"]["candidate"]
    assert event["metadata"]["authority_hash"]


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

    gateway = expose_test_primary_route(Gateway())
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

        async def complete_primary(self, role, system, user, max_output_tokens=None):
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

    class Gateway(ExplicitPrimaryGateway):
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
    (outputs / "polish-integrity.json").write_text(json.dumps({
        "status": "passed",
        "draft_sha256": hashlib.sha256(best.encode("utf-8")).hexdigest(),
    }), encoding="utf-8")
    WorkflowService._save_quality_checkpoint(
        outputs.parent, best, {"score": 90, "issues": []}, 1, "passed",
    )

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
    plan = complete_checkpoint_plan()
    (outputs / "planning.md").write_text(plan, encoding="utf-8")
    draft = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["part one", "part two", "part three", "part four"])
    (outputs / "draft.md").write_text(draft, encoding="utf-8")
    (outputs / "review.md").write_text(quality_review(), encoding="utf-8")
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, store.load_constraints(project.id), 4,
    )
    save_test_complete_short_checkpoint(
        service, project, outputs, context, store.load_constraints(project.id),
    )
    stale_best = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
        ["stale best one", "stale best two", "stale best three", "stale best four"]
    )
    base_integrity = json.loads(
        (outputs / "draft-integrity.json").read_text(encoding="utf-8")
    )
    stale_best_integrity = {
        **base_integrity,
        "draft_sha256": hashlib.sha256(stale_best.encode("utf-8")).hexdigest(),
        "execution_manifest_sha256": "f" * 64,
    }
    (outputs / "polish-integrity.json").write_text(
        json.dumps(stale_best_integrity, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    WorkflowService._save_quality_checkpoint(
        outputs.parent, stale_best, {"score": 90, "issues": []}, 1, "passed",
    )

    checkpoint = service._find_short_checkpoint(project, run_id, 4, context)
    review = service._find_short_stage_output(project, run_id, "review.md")

    assert checkpoint == outputs
    assert review == outputs / "review.md"
    planning_ir_text = (outputs / "planning-ir.json").read_text(
        encoding="utf-8",
    )
    checkpoint_manifest = json.loads(
        (outputs / "short-checkpoint.json").read_text(encoding="utf-8"),
    )
    assert checkpoint_manifest["planning_ir_schema"] == "planning-document-ir-v1"
    assert checkpoint_manifest["execution_authority_mode"] == "planning-ir-v1"
    assert checkpoint_manifest["planning_ir_artifact_sha256"] == hashlib.sha256(
        planning_ir_text.encode("utf-8"),
    ).hexdigest()

    restored = project.path / "runs" / "new-run" / "outputs"
    restored.mkdir(parents=True)
    for filename in (
        "planning-adaptations.json", "best-candidate.md",
        "quality-checkpoint.json",
    ):
        (restored / filename).write_text("stale", encoding="utf-8")
    (restored / "draft-checkpoints").mkdir()
    (restored / "draft-checkpoints" / "segment-99.json").write_text(
        "stale", encoding="utf-8",
    )
    plan, restored_draft, source, causal_chain = service._restore_short_checkpoint(
        outputs, restored, context,
    )
    assert (plan, restored_draft, source) == (
        complete_checkpoint_plan(), draft, "draft.md",
    )
    assert causal_chain["core_goal"] == "完成测试规划"
    for filename in (
        "planning-ir.json", "short-causal-chain.json", "short-execution-index.json",
        "draft-integrity.json", "short-checkpoint.json",
    ):
        assert (restored / filename).is_file()
    assert (restored / "planning-ir.json").read_text(
        encoding="utf-8",
    ) == planning_ir_text
    for filename in (
        "planning-adaptations.json", "best-candidate.md",
        "quality-checkpoint.json",
    ):
        assert not (restored / filename).exists()
    assert not (restored / "draft-checkpoints" / "segment-99.json").exists()

    original_draft = (outputs / "draft.md").read_text(encoding="utf-8")
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
            ["tampered one", "part two", "part three", "part four"]
        ),
        encoding="utf-8",
    )
    rejected_restore = project.path / "runs" / "tampered-restore" / "outputs"
    with pytest.raises(ValueError):
        service._restore_short_checkpoint(outputs, rejected_restore, context)
    assert not rejected_restore.exists() or not any(rejected_restore.rglob("*"))
    (outputs / "draft.md").write_text(original_draft, encoding="utf-8")

    extra_adaptation = outputs / "planning-adaptations.json"
    extra_adaptation.write_text(
        json.dumps({"status": "ready"}, ensure_ascii=False), encoding="utf-8",
    )
    assert service._find_short_checkpoint(project, run_id, 4, context) is None
    extra_adaptation.unlink()

    planning_ir = json.loads(planning_ir_text)
    planning_ir["document"]["segments"][0]["handoff"] = "tampered handoff"
    (outputs / "planning-ir.json").write_text(
        json.dumps(planning_ir, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    assert service._find_short_checkpoint(project, run_id, 4, context) is None


def test_short_checkpoint_binds_and_restores_planning_adaptation(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Adapted checkpoint", mode="short", genre="suspense",
        premise="An authorized planning adaptation survives resume.", target_words=10000,
    ))
    db.create_run("adapted-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "adapted-run" / "outputs"
    outputs.mkdir(parents=True)
    outline = (
        "## 第二幕\n\n"
        "- **发现异常**：花穗发现库房账目异常。\n"
        "- **核验线索**：花穗亲自核验账册与库房。\n"
        "- **锁定经手人**：花穗与裴砚行锁定经手人。\n"
        "- **形成证据链**：二人形成证据链并准备公开。\n"
    )
    authority_state = {
        **StoryStateStore(db).ensure(project.id, project.path).data,
        "outline": {"content": outline},
    }
    contracts = narrative_outline_event_contracts(outline)
    plan = "\n\n".join(
        f"### 第 {number} 段：{contract['label']}\n\n"
        f"事件ID：{contract['id']}\n\n"
        f"大纲依据：{contract['label']}\n\n"
        f"段首承接：进入第 {number} 段前的已确认状态。\n\n"
        f"本段事件：以当前场景完整推进{contract['label']}。\n\n"
        f"段末交接：第 {number} 段结果已成立并交给下一段。"
        for number, contract in enumerate(contracts, 1)
    )
    (outputs / "planning.md").write_text(plan, encoding="utf-8")
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    constraints = store.load_constraints(project.id)
    context = service._short_checkpoint_context(
        project, state.revision, authority_state, constraints, 4,
    )
    outline_sha = hashlib.sha256(outline.encode("utf-8")).hexdigest()
    plan_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    plan_segments = service._short_plan_segments(plan, 4)
    segment_receipts = []
    for number, (contract, plan_segment) in enumerate(
        zip(contracts, plan_segments, strict=True), 1,
    ):
        candidates = planning_adaptation_evidence_candidates(plan_segment, number)
        evidence_id = next(
            key for key, value in candidates.items() if "本段事件" in value
        )
        segment_receipts.append({
            "authority_sha256": planning_adaptation_segment_authority_sha256(
                outline_sha256=outline_sha,
                planning_sha256=plan_sha,
                segment=number,
                event_contracts=[contract],
                plan_segment=plan_segment,
                version=1,
            ),
            "planning_sha256": plan_sha,
            "segment": number,
            "event_reviews": [{
                "event_id": contract["id"],
                "classification": "presentation",
                "changed_dimensions": ["scene_realization"],
                "invariants": {field: True for field in INVARIANT_FIELDS},
                "plan_evidence_ids": [evidence_id],
                "plan_evidence": [candidates[evidence_id]],
                "reason": "只展开场景表现，正式事件结果保持。",
            }],
            "segment_order_preserved": True,
            "formal_direction_preserved": True,
            "summary": "当前段保持正式剧情功能。",
        })
    whole_authority = planning_adaptation_whole_authority_sha256(
        outline_sha256=outline_sha,
        planning_sha256=plan_sha,
        segment_receipts=segment_receipts,
        version=1,
    )
    adaptation = {
        "version": 1,
        "status": "ready",
        "outline_sha256": context["outline_sha256"],
        "planning_sha256": plan_sha,
        "segment_count": 4,
        "segments": segment_receipts,
        "whole_story_receipt": {
            "authority_sha256": whole_authority,
            "planning_sha256": plan_sha,
            "segment_numbers": [1, 2, 3, 4],
            "event_ids": [contract["id"] for contract in contracts],
            "causal_order_preserved": True,
            "adjacent_handoffs_preserved": True,
            "knowledge_progression_preserved": True,
            "relationship_progression_preserved": True,
            "viewpoint_timeline_preserved": True,
            "promises_ending_preserved": True,
            "formal_direction_preserved": True,
            "affected_segments": [],
            "affected_event_ids": [],
            "reason": "",
            "summary": "整篇规划保持因果、状态和结局。",
        },
        "protocol_repairs": 0,
        "semantic_repairs": 0,
        "issues": [],
    }
    adaptation_path = outputs / "planning-adaptations.json"
    original_adaptation = json.dumps(adaptation, ensure_ascii=False, indent=2)
    adaptation_path.write_text(original_adaptation, encoding="utf-8")
    save_test_complete_short_checkpoint(
        service, project, outputs, context, constraints,
        state_override=authority_state, planning_adaptation=adaptation,
    )

    assert service._find_short_checkpoint(
        project, "new-run", 4, context,
    ) == outputs

    adaptation_path.unlink()
    assert service._find_short_checkpoint(
        project, "new-run", 4, context,
    ) is None

    adaptation_path.write_text(original_adaptation, encoding="utf-8")
    tampered = dict(adaptation)
    tampered["semantic_repairs"] = 1
    adaptation_path.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    assert service._find_short_checkpoint(
        project, "new-run", 4, context,
    ) is None

    adaptation_path.write_text(original_adaptation, encoding="utf-8")
    restored = project.path / "runs" / "restored-run" / "outputs"
    service._restore_short_checkpoint(outputs, restored, context)
    assert (restored / "planning-adaptations.json").read_text(
        encoding="utf-8",
    ) == original_adaptation


def test_short_checkpoint_rejects_tampered_manifest_receipt(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Tampered receipt", mode="short", genre="suspense",
        premise="A stale receipt must not resume.", target_words=10000,
    ))
    db.create_run("source-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "source-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "planning.md").write_text(
        complete_checkpoint_plan(), encoding="utf-8",
    )
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    constraints = store.load_constraints(project.id)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, constraints, 4,
    )
    save_test_complete_short_checkpoint(service, project, outputs, context, constraints)
    index_path = outputs / "short-execution-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["semantic_receipt"]["beat_receipts"] = []
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    assert service._find_short_checkpoint(project, "new-run", 4, context) is None


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
    (outputs / "planning.md").write_text(
        complete_checkpoint_plan(), encoding="utf-8",
    )
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    context = service._short_checkpoint_context(
        project, state.revision, state.data, store.load_constraints(project.id), 4,
    )
    save_test_complete_short_checkpoint(
        service, project, outputs, context, store.load_constraints(project.id),
    )

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
    (outputs / "planning.md").write_text(
        complete_checkpoint_plan(), encoding="utf-8",
    )
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
    (outputs / "planning.md").write_text(
        complete_checkpoint_plan(), encoding="utf-8",
    )
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
    save_test_complete_short_checkpoint(
        service, project, outputs, old_context, "same constraints",
        state_override=old_state,
    )
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
    (outputs / "planning.md").write_text(
        complete_checkpoint_plan(), encoding="utf-8",
    )
    (outputs / "draft.md").write_text(
        WorkflowService.SHORT_SEGMENT_SEPARATOR.join(["one", "two", "three", "four"]),
        encoding="utf-8",
    )
    service = WorkflowService(db, store, FakeGateway(), SimpleNamespace())
    state = StoryStateStore(db).ensure(project.id, project.path)
    old_context = service._short_checkpoint_context(
        project, state.revision, state.data, "old constraints", 4,
    )
    save_test_complete_short_checkpoint(
        service, project, outputs, old_context, "old constraints",
    )
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
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False)
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return execution_manifest_receipt_from_prompt(user)
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            covered_event_ids = list(dict.fromkeys(
                re.findall(r"EV-[0-9A-F]{8}", user.upper())
            ))
            return json.dumps({
                "core_goal": "完成目标",
                "cycles": [{"obstacle": "阻碍", "effort": "行动", "result": "推进"}],
                "ending": "完成结局", "covered_event_ids": covered_event_ids,
            }, ensure_ascii=False)
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            return json.dumps(
                planning_semantic_body_from_prompt(user), ensure_ascii=False,
            )
        if stage == "planning":
            raise AssertionError(f"unexpected planning prompt: {user[:120]}")
        if stage == "review":
            raise RuntimeError("fresh review requested")
        raise AssertionError(f"unexpected stage: {stage}")

    async def fake_draft(run_id, run_path, *args, **kwargs):
        draft = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(
            ["甲" * 500, "乙" * 500, "丙" * 500, "丁" * 500]
        )
        manifest = parse_execution_manifest(json.loads(
            (run_path / "outputs" / "short-execution-index.json").read_text(
                encoding="utf-8",
            )
        ))
        current_project, current_constraints, current_plan = args[:3]
        current_state = service.story_states.ensure(
            current_project.id, current_project.path,
        ).data
        (run_path / "outputs" / "draft-integrity.json").write_text(
            json.dumps({
                "version": 3, "status": "passed",
                "execution_manifest_sha256": execution_manifest_sha256(manifest),
                "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
                "plan_sha256": hashlib.sha256(
                    current_plan.encode("utf-8"),
                ).hexdigest(),
                "base_constraints_sha256": kwargs["base_constraints_sha256"],
                "story_state_sha256": hashlib.sha256(json.dumps(
                    current_state, ensure_ascii=False, sort_keys=True, default=str,
                ).encode("utf-8")).hexdigest(),
                "semantic_segment_receipts": [],
                "issues": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        return draft

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
async def test_planning_repair_becomes_checkpoint_plan_and_regenerates_causal_chain(
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
    prompts = []

    async def fake_stage(run_id, run_path, current_project, stage, constraints, user, **kwargs):
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False)
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return execution_manifest_receipt_from_prompt(user)
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            causal_events = json.loads(
                user.split("正式大纲事件：\n", 1)[1].split("\n\n", 1)[0]
            )
            return json.dumps({
                "core_goal": "按修正后的规划重建因果链",
                "cycles": [{
                    "obstacle": "阻碍", "effort": "行动", "result": "推进",
                    "state_change": "修正后的规划状态成立",
                }],
                "ending": "完成结局",
                "covered_event_ids": [item["id"] for item in causal_events],
            }, ensure_ascii=False)
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            prompts.append(user)
            return json.dumps(
                planning_semantic_body_from_prompt(user), ensure_ascii=False,
            )
        raise AssertionError(f"unexpected planning prompt: {user[:120]}")

    saved_chains = []

    def fake_save(run_id, current_project, chain):
        saved_chains.append(chain)

    captured = {}

    async def stop_after_planning(
        run_id, run_path, current_project, constraints, plan, **kwargs,
    ):
        captured["constraints"] = constraints
        captured["plan"] = plan
        captured["base_constraints_sha256"] = kwargs["base_constraints_sha256"]
        raise RuntimeError("stop after planning")

    service._stage = fake_stage
    service._save_short_causal_chain = fake_save
    service._draft_short_in_segments = stop_after_planning

    with pytest.raises(RuntimeError, match="stop after planning"):
        await service.run_short(project.id, use_crewai=False, run_id="repair-plan")

    saved = project.path / "runs" / "repair-plan" / "outputs" / "planning.md"
    accepted_plan = saved.read_text(encoding="utf-8")
    assert captured["plan"] == accepted_plan
    assert accepted_plan.count("### Segment ") == 4
    assert re.fullmatch(r"[0-9a-f]{64}", captured["base_constraints_sha256"])
    assert "按修正后的规划重建因果链" in captured["constraints"]
    assert len(saved_chains) == 1
    assert saved_chains[0]["core_goal"] == "按修正后的规划重建因果链"
    assert saved_chains[0]["covered_event_ids"] == list(dict.fromkeys(
        re.findall(r"EV-[0-9A-F]{8}", accepted_plan.upper())
    ))
    assert len(prompts) == 1
    assert "IR_FIRST_SHORT_PLANNING_V2" in prompts[0]


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

    with pytest.raises(ValueError, match="structurally truncated"):
        await service.run_short(project.id, use_crewai=False, run_id="rejected-chain")

    assert extract_calls == 0
    assert saved_chains == []


@pytest.mark.asyncio
async def test_planning_second_monotonic_repair_recovers_after_no_progress_candidate(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://primary.invalid/v1", auth_type="bearer",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="planning-model", provider_id="primary",
        display_name="Planning", model_name="planning-model",
        context_window=32_768, max_output_tokens=8_192,
    )
    db.save_role_binding("planning", "primary", "planning-model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Rebuild plan", mode="short", genre="suspense",
        premise="A second monotonic repair recovers the plan.", target_words=10000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class ContractRetryGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_primary(
            self, role, system, user, max_output_tokens=None,
        ):
            self.calls += 1
            payload = (
                {
                    "version": 2,
                    "initial_state": "The opening authority remains accepted.",
                    "segments": [],
                }
                if self.calls == 1
                else planning_semantic_body_from_prompt(user)
            )
            return ModelResult(json.dumps(payload), {
                "finish_reason": "stop", "provider_id": "primary",
                "model_id": "planning-model", "model_name": "planning-model",
                "input_tokens": 1200, "output_tokens": 700,
            })

    gateway = ContractRetryGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id = "planning-contract-retry"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    formal_events = [{
        "id": f"EV-{index:08X}",
        "label": f"Formal event {index}",
        "evidence": f"Formal event {index} changes the accepted story state.",
    } for index in range(1, 5)]
    state = service.story_states.ensure(project.id, project.path)
    brief = json.dumps({
        **project.metadata,
        "formal_outline_events": formal_events,
        "generation_contract": {"segment_count": 4},
    }, ensure_ascii=False)

    plan = await service._plan_short_ir_first(
        run_id, run_path, project, "Preserve every formal event.", brief,
        state.data, formal_events, 4, 4_800,
    )

    assert gateway.calls == 2
    assert plan.count("### Segment ") == 4
    assert all(item["id"] in plan for item in formal_events)
    audit_files = list(
        (run_path / "outputs" / "conversion-audits").glob("*.json")
    )
    assert len(audit_files) >= 2
    audit_methods = {
        json.loads(path.read_text(encoding="utf-8"))["method"]
        for path in audit_files
    }
    assert {"rejected", "exact_json"} <= audit_methods


@pytest.mark.asyncio
async def test_production_shaped_planning_recovery_reaches_formal_manuscript(
    tmp_path,
) -> None:
    """Replay the six-segment duplicate-clue incident through final promotion."""
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="冒牌千金恢复回放", mode="short", genre="古言",
        premise="花穗被误认进沈府后查清旧账与身份谜团。", target_words=13_000,
        pov="first", tone="诙谐幽默",
    ))
    narrator_file = project.path / "characters" / "hua-sui.md"
    narrator_file.parent.mkdir(parents=True, exist_ok=True)
    narrator_file.write_text(
        "---\nname: 花穗\nrole: protagonist\n---\n\n本回放的第一人称叙述者。\n",
        encoding="utf-8",
    )
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    repository = Path(__file__).resolve().parents[1]
    stable_fixture = json.loads(
        (repository / "tests" / "fixtures" / "planning_recovery_204415.json")
        .read_text(encoding="utf-8")
    )
    capacity_fixture = json.loads(
        (repository / "tests" / "fixtures" / "context_capacity_d785dd5c.json")
        .read_text(encoding="utf-8")
    )
    fixture_segments = stable_fixture["segments"]
    assert capacity_fixture["segment_count"] == len(fixture_segments) == 6
    assert capacity_fixture["formal_event_count"] == 29
    assert capacity_fixture["affected_segment_count"] == 5
    assert capacity_fixture["hard_issue_key_count"] == 41
    fallback_outline = "\n\n".join(
        f"## 第 {number} 段：{segment['title']}\n\n"
        + "\n".join(
            f"- **{label}**：{segment['body']}"
            for label in segment["events"]
        )
        for number, segment in enumerate(fixture_segments, 1)
    )
    production_project = next(
        (repository / "data" / "projects").glob("*-1a0269"), None,
    )
    production_outline = (
        production_project / "plot" / "outline.md"
        if production_project is not None else None
    )
    production_plan = (
        production_project / "runs" / "204415160b8f42fdb6d609851f1b81b9"
        / "outputs" / "planning-best.md"
        if production_project is not None else None
    )
    using_exact_production_artifact = bool(
        os.environ.get("NOVEL_RECOVERY_PRODUCTION_FIXTURE") == "1"
        and production_outline is not None
        and production_plan is not None
        and production_outline.is_file()
        and production_plan.is_file()
    )
    outline = (
        production_outline.read_text(encoding="utf-8")
        if using_exact_production_artifact and production_outline is not None
        else fallback_outline
    )
    state_store = StoryStateStore(db)
    initial_state = state_store.ensure(project.id, project.path)
    state_data = {**initial_state.data, "outline": {"content": outline}}
    with db.connect() as connection:
        serialized = json.dumps(state_data, ensure_ascii=False)
        connection.execute(
            "UPDATE story_states SET state_json=? WHERE project_id=?",
            (serialized, project.id),
        )
        connection.execute(
            "UPDATE story_state_history SET state_json=? "
            "WHERE project_id=? AND revision=?",
            (serialized, project.id, initial_state.revision),
        )
    state = state_store.get(project.id)
    assert state is not None
    contracts = narrative_outline_event_contracts(outline)
    assert len(contracts) == 29
    event_ids = [item["id"] for item in contracts]

    if using_exact_production_artifact and production_plan is not None:
        original_plan = production_plan.read_text(encoding="utf-8")
    else:
        event_offset = 0

        def plan_block(number: int, segment: dict) -> str:
            nonlocal event_offset
            owned = contracts[
                event_offset:event_offset + len(segment["events"])
            ]
            event_offset += len(owned)
            event_bodies = "\n".join(
                f"- {item['id']}：{label}：{segment['body']}"
                for item, label in zip(owned, segment["events"], strict=True)
            )
            return (
                f"### 第 {number} 段：{segment['title']}\n\n"
                "事件ID：" + "、".join(item["id"] for item in owned) + "\n\n"
                f"大纲依据：{segment['title']}\n\n"
                f"段首承接：{segment['opening']}\n\n"
                f"本段事件：\n{event_bodies}\n\n"
                f"段末交接：{segment['handoff']}\n\n"
                + (f"第{number}段场景细化" * 35)
            )

        original_plan = "\n\n".join(
            plan_block(number, segment)
            for number, segment in enumerate(fixture_segments, 1)
        )
        assert event_offset == len(contracts)
    assert WorkflowService._short_segment_count(13_000) == 6
    original_segments = WorkflowService._short_plan_segments(original_plan, 6)
    assert len(original_segments) == 6
    segment_event_ids = [
        WorkflowService._short_plan_event_ids(segment)
        for segment in original_segments
    ]

    class RecoveryGateway:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.patch_feedback_seen = False
            self.revision_started = False

        @staticmethod
        def result(role: str, text: str) -> ModelResult:
            return ModelResult(text, {
                "role": role, "model_name": f"offline-{role}",
                "finish_reason": "stop",
            })

        @staticmethod
        def whole_draft_receipt(user: str) -> str:
            authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
            draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
            segment_hashes = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", user,
            ).group(1))
            expected = json.loads(re.search(
                r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
            ).group(1))
            opening = user.split("OPENING EXCERPT: ", 1)[1].split(
                "\nENDING EXCERPT:", 1,
            )[0]
            ending = user.split("ENDING EXCERPT: ", 1)[1]
            return json.dumps({
                "authority_sha256": authority,
                "draft_sha256": draft_sha,
                "segment_sha256": segment_hashes,
                "event_ids": expected,
                "missing_event_ids": [],
                "duplicate_event_ids": [],
                "out_of_order_event_ids": [],
                "causal_order_valid": True,
                "continuity_valid": True,
                "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"kind": "opening", "excerpt": opening[:12]},
                    {"kind": "ending", "excerpt": ending[-12:]},
                ],
                "summary": "六段正文的事件顺序、状态交接和结局承诺均已核对。",
            }, ensure_ascii=False)

        @staticmethod
        def draft_prose(user: str) -> str:
            contract = json.loads(
                user.split("CURRENT_TASK_CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
            )
            segment = int(contract["task_id"].split("-")[1])
            target = int(contract["target_han"])
            motifs = [
                "轿帘外的叫卖声一路远去，我捏着仅剩的铜钱，把二十两赏银和镇口铺面的租钱来回盘算。进了沈府，我先看见满桌规矩，再从账房窗下听见那笔银子早已支出。",
                "灶房的冷饭结成硬块，我把剩菜倒进大锅，叫粗使丫头先暖了手再说话。井边的闲谈、月钱的缺口和夜里的脚步慢慢连成一张人情网，裴砚行也终于肯蹲下来听。",
                "库房后门的车辙还湿着，我顺着私账上的签押找到刘管事和冯管事。老仆提起三小姐走失那日，我没有替她补全记忆，只把已经听清的线索收好；匿名信随后压在枕下。",
                "羹汤入口前先飘来一丝异味，我没有再查一遍已经查完的旧账，也没有重新盘问说过话的老仆。我只盯住今日经手汤碗的人，当面逼出破绽，再让裴砚行沿下毒链追查。",
                "核验的人站在正厅中央，我把匿名信放到案上，也把花穗这个名字说得清清楚楚。老夫人的茶盏久久没有落下，大小姐嘴硬却红了眼，众人的接纳来自我做过的事。",
                "义学屋顶换上新瓦，我从旧日啃烧饼的街角走回沈府。老槐树下那壶浊酒呛得裴砚行直咳，我没有急着许诺，只把匿名信留在袖中，决定和他继续追查。",
            ]
            continuations = [
                "我沿着来路逐项核对车夫、赏银和账房的说法，把初进高门时看见的规矩与疑点分开记下。谁想用身份压我，我便追问钱从哪里来、又由谁提前支出；裴砚行只能提供旁证，不能替我作出判断。",
                "我守着灶火听完粗使丫头的难处，再从饭食、月钱和差事里辨认谁肯说真话。每一次帮忙都换来一条可复核的消息，我也把裴砚行的态度变化留在行动之后，不让关系推进抢走调查主线。",
                "我沿库房后门、车辙和私账签押逐层核实，把刘管事、冯管事与老仆提供的线索分别落定。匿名信出现以前的证据归入已知状态，威胁出现以后才进入新的风险，让下一段不必重复消费旧调查。",
                "我只盯住今日的汤碗、气味和经手顺序，从眼前异常逼出下毒者的破绽。旧账与老仆线索已经完成，不再被当成新发现；裴砚行沿我确认的下毒链追查幕后，人物主动性和因果次序都不交换。",
                "我在正厅亲口说明冒名入府的缘由，把匿名信和此前行动一并摆到众人面前。老夫人、大小姐和裴砚行的反应都由已经发生的选择支撑，接纳的是花穗这个人，而不是一个被强行补回来的身份。",
                "我把义学修缮、沈府新生活和未解匿名信放在同一条收束线上。老槐树下的玩笑让关系继续靠近，却不替代我自己的选择；我决定留下并继续追查，使结局闭合当下目标，同时保留真实的后续入口。",
            ]
            paragraphs: list[str] = []
            index = 1
            while effective_han_characters("\n\n".join(paragraphs)) < target:
                paragraphs.append(
                    (motifs[segment - 1] if index == 1 else "")
                    + f"这是本段第{index}轮推进。"
                    + continuations[segment - 1]
                    + "我把这一轮新增的行动、证据和知情状态记牢，确认入口已经被推进到新的出口，才让下一步自然接续。"
                )
                index += 1
            return "\n\n".join(paragraphs)

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append({
                "role": role,
                "user": user,
                "max_output_tokens": max_output_tokens,
            })
            if "SHORT_PLAN_CANONICAL_REWRAP_V1" in user:
                expected = json.loads(
                    user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0]
                )
                raw_packet = user.split(
                    "RAW GENERATED PACKET TO REWRAP:\n", 1,
                )[1]
                return self.result(role, json.dumps({"events": [{
                    "event_id": event_id,
                    "narrative": WorkflowService._short_plan_event_owned_body(
                        raw_packet, [event_id],
                    ),
                } for event_id in expected]}, ensure_ascii=False))
            if role == "revision_plan" and user.lstrip().startswith("{"):
                request = json.loads(user)
                if request.get("schema") == "targeted-repair-group-v1":
                    self.revision_started = True
                    group_id = request["group_id"]
                    old_text = request["target_excerpt"]
                    new_text = old_text.replace("一路远去", "渐渐远去")
                    assert old_text != new_text
                    return self.result(
                        role,
                        _short_revision_patch(request, old_text, new_text),
                    )
            if "SHORT_PLAN_LOCAL_RECOVERY_V2" in user:
                # The production recovery path now performs a deterministic
                # local-recovery call before the older evidence/adaptation
                # calls.  Keep this fixture honest: the first attempt makes no
                # progress, while the second removes only the duplicated
                # clues from the affected segment and preserves every other
                # segment byte-for-byte.
                attempt = int(
                    user.split("LOCAL RECOVERY ATTEMPT: ", 1)[1].splitlines()[0]
                )
                current = user.split("当前最佳规划稿：\n", 1)[1]
                if attempt == 1:
                    return self.result(role, current)
                repaired = current.replace(
                    "又确认冯管事经手旧账",
                    "沿用已确认的账目结论",
                ).replace(
                    "暗中继续追查",
                    "只盯住眼下的毒羹风险",
                ).replace(
                    "老仆口中关于三小姐的线索",
                    "已记录的旧线索",
                )
                return self.result(role, repaired)
            if "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in user:
                # Rebuild is a planning-event-realization contract. Runtime,
                # not the model, owns the Markdown envelope and its controls.
                payload = json.loads(
                    ProductionSizedShortGateway._planning_targeted_segment(user)
                )
                for event in payload["events"]:
                    event["narrative"] = event["narrative"].replace(
                        "又确认冯管事经手旧账",
                        "沿用已确认的账目结论",
                    ).replace(
                        "暗中继续追查",
                        "只盯住眼下的毒羹风险",
                    ).replace(
                        "老仆口中关于三小姐的线索",
                        "已记录的旧线索",
                    )
                return self.result(role, json.dumps(
                    payload, ensure_ascii=False,
                ))
            if "SHORT_PLAN_ADAPTATION_REVIEW_V2" in user:
                authority = user.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
                planning_sha = user.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
                segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
                expected = json.loads(
                    user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
                )
                candidates_text = user.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1]
                candidates_text = candidates_text.split(
                    "\n\nRECEIPT PROTOCOL ISSUES:", 1,
                )[0]
                candidates = json.loads(candidates_text)
                default_evidence_id = next(
                    key for key, value in candidates.items() if "本段事件" in value
                )
                current = user.split("CURRENT ACCEPTED PLAN SEGMENT:\n", 1)[1].split(
                    "\n\nPREVIOUS ACCEPTED HANDOFF:", 1,
                )[0]
                structural = segment == 4 and (
                    "又确认冯管事经手旧账" in current
                    or (
                        "暗中继续追查" in current
                        and "老仆口中关于三小姐的线索" in current
                    )
                )
                ordered_evidence_ids = [
                    key for key in candidates if key != default_evidence_id
                ] or [default_evidence_id]
                structural_evidence_ids = [
                    key for key, value in candidates.items()
                    if (
                        "暗中继续追查" in value
                        or "老仆口中关于三小姐的线索" in value
                    )
                ] or [default_evidence_id]
                event_reviews = []
                for index, event_id in enumerate(expected):
                    event_is_structural = structural and index == 0
                    invariants = {field: True for field in INVARIANT_FIELDS}
                    if event_is_structural:
                        for field in (
                            "entry_state", "knowledge_state", "promise_ending",
                        ):
                            invariants[field] = False
                    evidence_ids = (
                        structural_evidence_ids
                        if event_is_structural else
                        [ordered_evidence_ids[min(index, len(ordered_evidence_ids) - 1)]]
                    )
                    evidence_quote = (
                        candidates[evidence_ids[0]] if event_is_structural else ""
                    )
                    event_reviews.append({
                        "event_id": event_id,
                        "classification": (
                            "structural" if event_is_structural else "equivalent"
                        ),
                        "changed_dimensions": (
                            ["入口知情状态", "既有节拍重复执行"]
                            if event_is_structural else ["场景呈现"]
                        ),
                        "invariants": invariants,
                        "plan_evidence_ids": evidence_ids,
                        "plan_evidence_quote": evidence_quote,
                        "reason": (
                            evidence_quote
                            + "；本段重新消费了前段已经完成的冯管事旧账与老仆线索。"
                            if event_is_structural else
                            "当前规划保留正式事件功能与人物主动性。"
                        ),
                    })
                return self.result(role, json.dumps({
                    "authority_sha256": authority,
                    "planning_sha256": planning_sha,
                    "segment": segment,
                    "event_reviews": event_reviews,
                    "segment_order_preserved": True,
                    "formal_direction_preserved": not structural,
                    "summary": "已逐项核对当前正式段。",
                }, ensure_ascii=False))
            if (
                "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in user
                or "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in user
            ):
                source_sha256 = re.search(
                    r"SOURCE SHA256: ([0-9a-f]{64})", user,
                ).group(1)
                segments = json.loads(re.search(
                    r"EXPECTED SEGMENTS: (\[[^\n]+\])", user,
                ).group(1))
                expected = json.loads(re.search(
                    r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
                ).group(1))
                return self.result(role, json.dumps({
                    "source_sha256": source_sha256,
                    "segment_numbers": segments,
                    "event_ids": expected,
                    "causal_order_preserved": True,
                    "adjacent_handoffs_preserved": True,
                    "knowledge_progression_preserved": True,
                    "relationship_progression_preserved": True,
                    "viewpoint_timeline_preserved": True,
                    "promises_ending_preserved": True,
                    "formal_direction_preserved": True,
                    "affected_segments": [],
                    "affected_event_ids": [],
                    "entry_state": "当前区域从已确认入口状态开始。",
                    "exit_state": "当前区域按正式顺序交接到下一范围。",
                    "knowledge_state": "人物知情状态按正式事件逐步推进。",
                    "relationship_state": "关系变化由当前范围内行动支撑。",
                    "viewpoint_timeline": "第一人称视角和展示顺序保持不变。",
                    "open_promises": ["匿名信来源与真千金去向仍待追查"],
                    "resolved_promises": [],
                    "reason": "",
                    "summary": "当前连续范围保留正式因果、人物主动性与交接。",
                }, ensure_ascii=False))
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in user:
                authority = user.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
                planning_sha = user.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
                segments = json.loads(
                    user.split("EXPECTED SEGMENTS:\n", 1)[1].splitlines()[0]
                )
                expected = json.loads(
                    user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
                )
                return self.result(role, json.dumps({
                    "authority_sha256": authority,
                    "planning_sha256": planning_sha,
                    "segment_numbers": segments,
                    "event_ids": expected,
                    "causal_order_preserved": True,
                    "adjacent_handoffs_preserved": True,
                    "knowledge_progression_preserved": True,
                    "relationship_progression_preserved": True,
                    "viewpoint_timeline_preserved": True,
                    "promises_ending_preserved": True,
                    "formal_direction_preserved": True,
                    "affected_segments": [],
                    "affected_event_ids": [],
                    "reason": "",
                    "summary": "整篇因果、交接、视角与结局保持不变。",
                }, ensure_ascii=False))
            if "SHORT_PLAN_EVIDENCE_PATCH_V3" in user:
                self.patch_feedback_seen = (
                    "REJECTED CANDIDATE NO-REGRESSION FEEDBACK" in user
                    and "被拒候选改坏主要执行者" in user
                )
                authority = user.split(
                    "EXPECTED PATCH AUTHORITY SHA256: ", 1,
                )[1].splitlines()[0]
                segment = int(user.split("EXPECTED SEGMENT: ", 1)[1].splitlines()[0])
                anchors = json.loads(
                    user.split("AUTHORIZED ORIGINAL ANCHORS:\n", 1)[1].split(
                        "\n\nFORMAL EVENT CONTRACTS:", 1,
                    )[0]
                )
                replacements = []
                for anchor in anchors:
                    source = anchor["text"]
                    if "暗中继续追查" in source:
                        replacement = (
                            "1. **当前风险聚焦**：花穗不再重查已经确认的旧账，"
                            "只根据匿名信锁定眼下的饮食与接触风险，等待威胁方暴露新动作。"
                        )
                    elif "老仆口中关于三小姐的线索" in source:
                        replacement = (
                            "2. **保留既有线索**：花穗保留此前取得的老仆线索，"
                            "不重复取证、不提前处理身份核验，只把注意力放在当前威胁。"
                        )
                    else:
                        replacement = source.replace(
                            "；随后又确认冯管事经手旧账，再向老仆套出三小姐走失当日后门有人出入",
                            "",
                        )
                    # V3 is a complete Runtime-selected anchor ledger. An
                    # unchanged value is an explicit no-op, not an omitted
                    # authority unit.
                    replacements.append({
                        "evidence_id": anchor["evidence_id"],
                        "source_sha256": anchor["source_sha256"],
                        "replacement": replacement,
                    })
                return self.result(role, json.dumps({
                    "authority_sha256": authority,
                    "segment": segment,
                    "replacements": replacements,
                    "summary": "删除已由前段完成的旧账和老仆线索，只保留下毒事件。",
                }, ensure_ascii=False))
            if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
                formal_events = json.loads(
                    user.split("正式大纲事件：\n", 1)[1].split(
                        "\n\n已验收规划：", 1,
                    )[0]
                )
                covered = [str(item["id"]).upper() for item in formal_events]
                return self.result(role, json.dumps({
                    "core_goal": "花穗查清误认背后的危险并以自己的名字留下。",
                    "opening": {
                        "pressure": "花穗身无余钱",
                        "anomaly": "二十两提前支出",
                        "reader_question": "谁安排了这场误认",
                        "future_promise": "查账会逼出真正威胁",
                    },
                    "cycles": [
                        {"obstacle": "高门规矩隔绝消息", "effort": "建立人情网", "result": "获得耳目", "state_change": "从孤立变为可调查", "escalation": "查到账目异常", "next_question": "旧账由谁经手"},
                        {"obstacle": "旧账牵出府中蛀虫", "effort": "公开查账", "result": "收到匿名威胁", "state_change": "调查者成为目标", "escalation": "饮食被下毒", "next_question": "谁要灭口"},
                        {"obstacle": "身份与安全同时崩塌", "effort": "揪出下毒者并坦白身份", "result": "以花穗之名获接纳", "state_change": "从投机者变为守护者", "escalation": "主动承担未解旧谜", "next_question": "匿名信源头何在"},
                    ],
                    "accidents": ["误接入府", "匿名信", "毒羹"],
                    "reversal": {"content": "坦白假身份反而补全信任", "prior_evidence": ["护下人", "查旧账", "直面毒羹"]},
                    "ending": {"surface_goal": "以自己的名字留下", "inner_goal": "承认自己值得被接纳", "cost": "继续承担旧谜风险"},
                    "question_chain": "二十两异常到旧账、匿名信、毒羹，再到未解真相。",
                    "relationship_arc": "审视、合作、保护、接纳与开放承诺。",
                    "covered_event_ids": covered,
                }, ensure_ascii=False))
            if (
                "SHORT_EXECUTION_MANIFEST_V2" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
            ):
                return self.result(
                    role,
                    json.dumps(execution_manifest_body_from_prompt(user), ensure_ascii=False),
                )
            if (
                "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
                or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
            ):
                return self.result(role, execution_manifest_receipt_from_prompt(user))
            if "DRAFT_SEMANTIC_VALIDATION" in user:
                contract = json.loads(re.search(
                    r"TASK CONTRACT: (\{[^\n]+\})", user,
                ).group(1))
                prose = user.split("PROSE:\n", 1)[1]
                return self.result(
                    role,
                    json.dumps(draft_semantic_receipt(contract, prose), ensure_ascii=False),
                )
            if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
                return self.result(role, self.whole_draft_receipt(user))
            if role == "draft":
                return self.result(role, self.draft_prose(user))
            if role == "polish":
                source = user.rsplit("MANUSCRIPT SEGMENT:\n", 1)[1]
                return self.result(role, source)
            if "TARGET READER SIMULATION" in user:
                return self.result(role, quality_review(90, 91, 89, issues=[]))
            if role == "review":
                return self.result(role, quality_review(88, 89, 86, issues=[{
                    "category": "prose", "severity": "medium",
                    "evidence": "轿帘外的叫卖声一路远去",
                    "action": "精炼开头节奏但保留事件、视角和人物行动",
                }]))
            if role == "final_review" and "FULL MANUSCRIPT WINDOW SUMMARY" in user:
                if not self.revision_started:
                    assert formal.read_text(encoding="utf-8") == "正式旧稿不得在终审前覆盖。"
                return self.result(role, json.dumps({
                    "summary": "本窗口保持第一人称、正式事件顺序和相邻状态交接。",
                    "issues": [],
                }, ensure_ascii=False))
            if role == "final_review" and "终审详细事件和伏笔单独分析" in user:
                if not self.revision_started:
                    assert formal.read_text(encoding="utf-8") == "正式旧稿不得在终审前覆盖。"
                return self.result(role, json.dumps({
                    "events": ["花穗依次完成当前正式事件"],
                    "promises": ["匿名信来源与真千金去向仍保留"],
                    "character_states": ["花穗保持第一人称主动执行"],
                    "timeline": ["六个正式分段按规划顺序展开"],
                }, ensure_ascii=False))
            if role == "final_review" and "REGIONAL EVIDENCE REDUCTION" in user:
                covered = json.loads(re.search(
                    r"COVERED WINDOWS: (\[[^\n]+\])", user,
                ).group(1))
                source_sha256 = re.search(
                    r"SOURCE SHA256: ([0-9a-f]{64})", user,
                ).group(1)
                source_issue_ids = json.loads(re.search(
                    r"SOURCE ISSUE IDS: (\[[^\n]*\])", user,
                ).group(1))
                return self.result(role, json.dumps({
                    "summary": "相邻窗口的事件、知情状态、关系与结局承诺连续。",
                    "issues": [],
                }, ensure_ascii=False))
            if role == "final_review" and "FULL MANUSCRIPT FINAL ADJUDICATION" in user:
                if not self.revision_started:
                    assert formal.read_text(encoding="utf-8") == "正式旧稿不得在终审前覆盖。"
                ledger = json.loads(
                    user.split(
                        "AUTHORITATIVE REVIEW ISSUE LEDGER:\n", 1,
                    )[1].split("\n\n", 1)[0]
                )
                payload = json.loads(quality_review(
                    97 if self.revision_started else 93,
                    97 if self.revision_started else 94,
                    96 if self.revision_started else 92,
                    issues=[],
                ))
                payload["reconciliations"] = [{
                    "issue_id": item["issue_id"],
                    "status": "resolved",
                    "severity": item.get("severity", "medium"),
                    "evidence": "精修稿已消除重复句式且保留全部正式事件。",
                } for item in ledger]
                return self.result(
                    role, json.dumps(payload, ensure_ascii=False),
                )
            if role == "maintenance":
                return self.result(role, json.dumps({
                    "facts": [{"fact_key": "identity", "value": "花穗以自己的名字留在沈府"}],
                    "state": {"花穗": {"location": "沈府", "status": "义女"}},
                }, ensure_ascii=False))
            raise AssertionError(f"unexpected offline model call: {role}: {user[:120]}")

        async def complete_primary(
            self, role, system, user, max_output_tokens=None,
        ):
            return await self.complete(
                role, system, user, max_output_tokens=max_output_tokens,
            )

    gateway = RecoveryGateway()
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    original_stage = service._stage
    capacity_simulation = {
        "segment_split": 0,
        "singleton_facets": 0,
        "facet_windows": 0,
    }

    async def production_capacity_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_EVENT_FACET_WINDOW_REVIEW_V1" in prompt:
            capacity_simulation["facet_windows"] += 1
            facet = prompt.split("FACET: ", 1)[1].splitlines()[0]
            invariants = json.loads(
                prompt.split("EXPECTED INVARIANTS:\n", 1)[1].split("\n\n", 1)[0]
            )
            candidates = json.loads(
                prompt.split("WINDOW EVIDENCE CANDIDATES:\n", 1)[1].split(
                    "\n\nEXACT PLAN WINDOW:", 1,
                )[0]
            )
            start, end = (
                int(value)
                for value in prompt.split(
                    "WINDOW RANGE: ", 1,
                )[1].splitlines()[0].split(":")
            )
            return json.dumps({
                "authority_sha256": prompt.split(
                    "EXPECTED WINDOW AUTHORITY SHA256: ", 1,
                )[1].splitlines()[0],
                "planning_sha256": prompt.split(
                    "EXPECTED PLANNING SHA256: ", 1,
                )[1].splitlines()[0],
                "authority_version": int(prompt.split(
                    "EXPECTED AUTHORITY VERSION: ", 1,
                )[1].splitlines()[0]),
                "segment": int(prompt.split(
                    "CURRENT SEGMENT: ", 1,
                )[1].splitlines()[0]),
                "event_id": prompt.split("EVENT ID: ", 1)[1].splitlines()[0],
                "facet": facet,
                "window_index": int(prompt.split(
                    "WINDOW INDEX: ", 1,
                )[1].splitlines()[0]),
                "start": start,
                "end": end,
                "text_sha256": prompt.split(
                    "WINDOW TEXT SHA256: ", 1,
                )[1].splitlines()[0],
                "invariants": {field: True for field in invariants},
                "changed_dimensions": ["场景呈现"] if facet == "function" else [],
                "plan_evidence_ids": list(candidates)[:1],
                "reason": "当前完整窗口保留正式事件不变量。",
            }, ensure_ascii=False)
        if "SHORT_PLAN_ADAPTATION_EVENT_FACET_REVIEW_V1" in prompt:
            capacity_simulation["singleton_facets"] += 1
            return await kwargs["capacity_splitter"]({
                "pressure": "split",
                "estimated_input_tokens": 23_146,
                "authority_input_tokens": 20_581,
                "output_reserve": 900,
                "context_window": 32_768,
            })
        if "SHORT_PLAN_ADAPTATION_REVIEW_V2" in prompt:
            segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
            if segment == 2:
                if kwargs.get("capacity_splitter") is not None:
                    capacity_simulation["segment_split"] += 1
                    return await kwargs["capacity_splitter"]({
                        "pressure": "split",
                        "estimated_input_tokens": 24_143,
                        "authority_input_tokens": 21_578,
                        "output_reserve": 900,
                        "context_window": 32_768,
                    })
                raise ContextCapacityPreflightError(
                    pressure="split",
                    estimated_input_tokens=23_146,
                    authority_input_tokens=20_581,
                    output_reserve=900,
                    context_window=32_768,
                )
        return await original_stage(*args, **kwargs)

    service._stage = production_capacity_stage
    constraints = store.load_constraints(project.id)
    checkpoint_context = service._short_checkpoint_context(
        project, state.revision, state.data, constraints, 6,
    )
    best_issue = [{
        "code": "planning_structural_drift",
        "segment": 4,
        "event_id": segment_event_ids[3][0],
        "invalid_invariants": ["entry_state", "knowledge_state", "promise_ending"],
        "message": "第4段重复消费前段已经完成的旧账与老仆线索",
    }]
    rejected_issue = [{
        "code": "planning_structural_drift",
        "segment": 4,
        "event_id": segment_event_ids[3][0],
        "invalid_invariants": ["primary_actor_agency"],
        "message": "被拒候选让裴砚行替花穗识破毒羹",
        "reason": "被拒候选改坏主要执行者",
    }]
    recovery = new_planning_recovery_state(
        outline_sha256=hashlib.sha256(outline.encode("utf-8")).hexdigest(),
        generation_context_sha256=checkpoint_context["generation_context_sha256"],
        segment_count=6,
        plan=original_plan,
        issues=best_issue,
    )
    rejected_plan = original_plan.replace(
        "3. **闻出毒味**",
        "3. **裴砚行替花穗闻出毒味**",
        1,
    )
    recovery = record_planning_candidate(
        recovery,
        plan=rejected_plan,
        issues=rejected_issue,
        comparison=planning_candidate_comparison(best_issue, rejected_issue),
        source="targeted-2",
        accepted=False,
    )
    recovery["status"] = "recoverable_failed"
    db.create_run("production-shape-failure", project.id, "short-story", status="failed")
    old_outputs = project.path / "runs" / "production-shape-failure" / "outputs"
    old_outputs.mkdir(parents=True)
    write_planning_recovery(old_outputs, recovery, original_plan)

    formal = project.path / "manuscript" / "story.md"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text("正式旧稿不得在终审前覆盖。", encoding="utf-8")

    result = await service.run_short(
        project.id, use_crewai=False, run_id="production-recovery-e2e",
    )

    assert result["status"] == "completed"
    assert capacity_simulation["segment_split"] >= 1
    assert capacity_simulation["singleton_facets"] >= len(segment_event_ids[1]) * 3
    assert capacity_simulation["facet_windows"] >= capacity_simulation[
        "singleton_facets"
    ]
    assert gateway.patch_feedback_seen is True
    patch_calls = [
        call for call in gateway.calls
        if "SHORT_PLAN_EVIDENCE_PATCH_V3" in call["user"]
    ]
    assert patch_calls
    assert all(
        0 < call["max_output_tokens"] < capacity_fixture["output_reserve_tokens"]
        for call in patch_calls
    )
    assert all(classify_input_pressure(
        full_input_tokens=capacity_fixture["estimated_input_tokens"],
        authority_input_tokens=capacity_fixture["authority_input_tokens"],
        output_reserve=call["max_output_tokens"],
        context_window=capacity_fixture["context_window"],
    ) == "full" for call in patch_calls)
    run_path = project.path / "runs" / result["id"]
    repaired_plan = (run_path / "outputs" / "planning.md").read_text(encoding="utf-8")
    planning_ir = json.loads(
        (run_path / "outputs" / "planning-ir.json").read_text(encoding="utf-8")
    )
    assert planning_ir["schema"] == "planning-document-ir-v1"
    assert planning_ir["document"]["plan_sha256"] == hashlib.sha256(
        repaired_plan.encode("utf-8"),
    ).hexdigest()
    assert [
        event_id
        for segment in planning_ir["document"]["segments"]
        for event_id in segment["event_ids"]
    ] == [item.upper() for item in event_ids]
    before_segments = service._short_plan_segments(original_plan, 6)
    after_segments = service._short_plan_segments(repaired_plan, 6)
    assert [after_segments[index] == before_segments[index] for index in range(6)] == [
        True, True, True, False, True, True,
    ]
    assert "暗中继续追查" not in after_segments[3]
    assert "老仆口中关于三小姐的线索" not in after_segments[3]
    assert "闻出毒味" in after_segments[3]
    assert "裴砚行替花穗闻出毒味" not in repaired_plan
    saved_recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert saved_recovery["status"] == "ready"
    assert any(not item["accepted"] for item in saved_recovery["candidates"])
    assert any(item["accepted"] for item in saved_recovery["candidates"])
    causal_chain = json.loads(
        (run_path / "outputs" / "short-causal-chain.json").read_text(encoding="utf-8")
    )
    assert causal_chain["covered_event_ids"] == [item.upper() for item in event_ids]
    execution = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(encoding="utf-8")
    )
    assert execution["status"] == "ready"
    draft = (run_path / "outputs" / "draft.md").read_text(encoding="utf-8")
    assert len(service._split_segments(draft)) == 6
    assert all("我" in segment for segment in service._split_segments(draft))
    integrity = json.loads(
        (run_path / "outputs" / "draft-integrity.json").read_text(encoding="utf-8")
    )
    assert integrity["status"] == "passed"
    report = json.loads(
        (run_path / "outputs" / "quality-report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "passed"
    assert report["terminal_review"]["issues"]
    assert all(
        item.get("status") == "resolved"
        for item in report["terminal_review"]["issues"]
    )
    assert report["final_review_evidence"]["reconciliations"][0]["status"] == "resolved"
    final_text = formal.read_text(encoding="utf-8")
    assert final_text != "正式旧稿不得在终审前覆盖。"
    assert final_text == "\n\n".join(service._split_segments(
        (run_path / "outputs" / "polish.md").read_text(encoding="utf-8")
    ))
    committed_state = state_store.get(project.id)
    assert committed_state is not None
    assert committed_state.revision == state.revision + 1
    assert committed_state.data["confirmed_facts"][0]["value"] == "花穗以自己的名字留在沈府"

    protected = service._protected_short_revision_source(project)
    assert "semantic_authority" in protected
    assert len(protected["semantic_authority"]["source_segments"]) == 6
    semantic_calls_before_revision = sum(
        "DRAFT_SEMANTIC_VALIDATION" in call["user"]
        for call in gateway.calls
    )
    whole_calls_before_revision = sum(
        "DRAFT_WHOLE_SEMANTIC_VALIDATION" in call["user"]
        for call in gateway.calls
    )
    issue_id = protected["issue_ledger"][0]["issue_id"]
    revision = await service.run_short_revision(
        project.id, [issue_id], run_id="production-recovery-revision",
    )
    assert revision["status"] == "waiting_confirmation"
    assert "轿帘外的叫卖声渐渐远去" in revision["candidate"]
    assert "轿帘外的叫卖声一路远去" not in revision["candidate"]
    service.decide_short_revision_group(
        revision["id"], issue_id, "adopted", revision["candidate_hash"],
    )
    finalized_revision = await service.finalize_short_revision(revision["id"])

    assert finalized_revision["status"] == "completed"
    revision_run_path = project.path / "runs" / revision["id"]
    revision_candidate = (
        revision_run_path / "outputs" / "candidate.md"
    ).read_text(encoding="utf-8")
    assert WorkflowService.SHORT_SEGMENT_SEPARATOR not in revision_candidate
    assert "我" in revision_candidate
    assert sum(
        "DRAFT_SEMANTIC_VALIDATION" in call["user"]
        for call in gateway.calls
    ) > semantic_calls_before_revision
    assert sum(
        "DRAFT_WHOLE_SEMANTIC_VALIDATION" in call["user"]
        for call in gateway.calls
    ) > whole_calls_before_revision
    revision_checkpoint = load_quality_checkpoint(revision_run_path)
    assert revision_checkpoint is not None
    assert revision_checkpoint["terminal_reviewed_hash"] \
        == revision_checkpoint["manuscript_hash"]
    revision_integrity = json.loads((
        revision_run_path / revision_checkpoint["narrative_integrity"]["path"]
    ).read_text(encoding="utf-8"))
    assert revision_integrity["status"] == "passed"
    assert revision_integrity["changed_segments"] == [1]
    assert len(revision_integrity["segments"]) == 6
    assert len(revision_integrity["publication_segment_lengths"]) == 6
    assert revision_integrity["draft_sha256"] == hashlib.sha256(
        revision_candidate.encode("utf-8")
    ).hexdigest()
    assert revision_integrity["publication_sha256"] \
        == revision_integrity["draft_sha256"]
    assert revision_integrity["whole_semantic_receipt"]
    # A targeted/manual revision promotes a new protected best candidate; it
    # must not silently bypass the separate formal-manuscript promotion path.
    assert formal.read_text(encoding="utf-8") == final_text


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
    assert review["issue_reconciliation_complete"] is True
    assert review["issues"][0]["issue_id"] == stable_issue_id
    assert review["issues"][0]["status"] == "resolved"
    assert review["issues"][0]["reconciliation_evidence"] == (
        "The repeated wording is gone."
    )
    assert review["issues"][0]["reconciled_at"]
    assert audit["reviewed_windows"] == count
    assert audit["coverage"] == 1.0
    manuscript_hash = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    assert all(
        item["manuscript_sha256"] == manuscript_hash for item in audit["windows"]
    )
    assert all(
        item["window_sha256"] == hashlib.sha256(
            manuscript[item["start"]:item["end"]].encode("utf-8")
        ).hexdigest()
        for item in audit["windows"]
    )
    assert gateway.roles == ["final_review"] * (count + 1)
    assert "planning" not in gateway.roles
    assert all("WINDOW " in call["user"] for call in gateway.calls[:-1])
    assert all("summary and issues only" in call["user"] for call in gateway.calls[:-1])
    assert all("events" not in call["user"] for call in gateway.calls[:-1])
    assert audit["detail_analysis"]["performed"] is False


@pytest.mark.asyncio
async def test_final_review_reduces_all_evidence_hierarchically_before_global_adjudication(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Hierarchical review", mode="short", genre="suspense",
        premise="Every window must reach the global verdict.", target_words=20000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    manuscript = "\n\n".join("甲" * 4500 for _ in range(4))

    class Gateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append({"role": role, "user": user})
            if "FULL MANUSCRIPT WINDOW SUMMARY" in user:
                return ModelResult(json.dumps({
                    "summary": "窗" * 220, "issues": [],
                }, ensure_ascii=False), {
                    "role": role, "model_name": "reviewer", "finish_reason": "stop",
                })
            if "REGIONAL EVIDENCE REDUCTION" in user:
                covered = json.loads(re.search(
                    r"COVERED WINDOWS: (\[[^\n]+\])", user,
                ).group(1))
                source_sha256 = re.search(
                    r"SOURCE SHA256: ([0-9a-f]{64})", user,
                ).group(1)
                source_issue_ids = json.loads(re.search(
                    r"SOURCE ISSUE IDS: (\[[^\n]*\])", user,
                ).group(1))
                return ModelResult(json.dumps({
                    "summary": "区域证据已完整归并", "issues": [],
                }, ensure_ascii=False), {
                    "role": role, "model_name": "reviewer", "finish_reason": "stop",
                })
            return ModelResult(json.dumps({
                "dimensions": {"commercial": 88, "story": 87, "prose": 86},
                "decision": "pass", "issues": [], "reconciliations": [],
            }, ensure_ascii=False), {
                "role": role, "model_name": "reviewer", "finish_reason": "stop",
            })

    gateway = expose_test_primary_route(Gateway())
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    monkeypatch.setattr(
        service, "_final_review_adjudication_token_limit", lambda *_: 700,
        raising=False,
    )
    run_id, run_path = service._begin_run(project, "short-story", None)

    review, audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", manuscript, {"issues": []},
    )

    window_count = len(review_windows(manuscript))
    hierarchy = audit["adjudication_hierarchy"]
    assert review["decision"] == "pass"
    assert hierarchy["performed"] is True
    assert hierarchy["covered_windows"] == list(range(1, window_count + 1))
    assert hierarchy["levels"]
    regional_calls = [
        call for call in gateway.calls if "REGIONAL EVIDENCE REDUCTION" in call["user"]
    ]
    assert len(regional_calls) >= 2
    regional_call_count = len(regional_calls)
    final_call = next(
        call for call in reversed(gateway.calls)
        if "FULL MANUSCRIPT FINAL ADJUDICATION" in call["user"]
    )
    assert "区域证据已完整归并" in final_call["user"]

    await service._full_manuscript_review(
        run_id, run_path, project, "constraints", manuscript, {"issues": []},
    )
    assert sum(
        "REGIONAL EVIDENCE REDUCTION" in call["user"]
        for call in gateway.calls
    ) == regional_call_count
    assert any(
        event["event_type"] == "final_review_hierarchy_batch_reused"
        for event in db.list_run_events(run_id)
    )


@pytest.mark.asyncio
async def test_hierarchical_review_carries_source_issues_even_when_reducer_drops_them(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Lossless hierarchy", mode="short", genre="suspense",
        premise="No source issue may disappear during reduction.", target_words=20000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)

    class Gateway:
        async def complete(self, role, system, user, max_output_tokens=None):
            covered = json.loads(re.search(
                r"COVERED WINDOWS: (\[[^\n]+\])", user,
            ).group(1))
            source_sha256 = re.search(
                r"SOURCE SHA256: ([0-9a-f]{64})", user,
            ).group(1)
            source_issue_ids = json.loads(re.search(
                r"SOURCE ISSUE IDS: (\[[^\n]*\])", user,
            ).group(1))
            return ModelResult(json.dumps({
                "summary": "归并器没有复述问题正文。", "issues": [],
            }, ensure_ascii=False), {
                "role": role, "model_name": "reviewer", "finish_reason": "stop",
            })

    service = WorkflowService(
        db, store, expose_test_primary_route(Gateway()),
        SkillGate(db, SkillScanner([skill_root])),
    )
    monkeypatch.setattr(
        service, "_final_review_adjudication_token_limit", lambda *_: 700,
        raising=False,
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    source_issue = issue_ledger([{
        "issue_id": "source-issue-1", "category": "timeline", "severity": "high",
        "evidence": "第二窗日期早于第一窗。", "action": "核对日期。",
    }], source="window-1")[0]
    second_evidence = {
        **source_issue,
        "evidence": "第三窗再次显示日期倒退。",
        "location": "第三窗结尾",
    }
    evidence = [{
        "window": index, "covered_windows": [index], "summary": "窗" * 180,
        "issues": (
            [source_issue] if index == 1
            else [second_evidence] if index == 3
            else []
        ),
    } for index in range(1, 5)]

    reduced, audit = await service._hierarchical_final_review_evidence(
        run_id, run_path, project, "constraints", evidence, "",
    )

    reduced_issue_ids = {
        issue["issue_id"] for item in reduced for issue in item.get("issues", [])
    }
    assert "source-issue-1" in reduced_issue_ids
    assert audit["covered_windows"] == [1, 2, 3, 4]
    carried = next(
        issue for item in reduced for issue in item.get("issues", [])
        if issue["issue_id"] == "source-issue-1"
    )
    assert {item["evidence"] for item in carried["evidence_records"]} == {
        "第二窗日期早于第一窗。", "第三窗再次显示日期倒退。",
    }


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
        "issue_id": stable_issue_id, "status": "unresolved",
        "severity": "medium", "evidence": "The sentence still repeats.",
    }
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "revise", "issues": [],
        "reconciliations": [reconciled_issue],
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
    assert "missing_issue_reconciliation" not in audit["gate_reasons"]
    assert gateway.roles == ["final_review", "final_review"]
    assert not any(
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

        async def complete_primary(self, role, system, user, max_output_tokens=None):
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
async def test_final_review_context_capacity_uses_configured_fallback(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "final_review", "primary", "reviewer", "backup", "reviewer-2",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Review capacity fallback", mode="short", genre="suspense",
        premise="A complete window exceeds only the primary route.", target_words=1000,
    ))
    service = WorkflowService(
        db, store,
        SimpleNamespace(complete_configured_fallback=lambda *_args, **_kwargs: None),
        SimpleNamespace(),
    )
    run_id = "final-capacity"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    calls = []

    async def fake_stage(*args, **kwargs):
        calls.append("fallback" if kwargs.get("prefer_configured_fallback") else "primary")
        if not kwargs.get("prefer_configured_fallback"):
            raise ContextCapacityPreflightError(
                pressure="split", estimated_input_tokens=40_000,
                authority_input_tokens=36_000, output_reserve=2_000,
                context_window=32_768,
            )
        return json.dumps({"summary": "备用路由完成窗口核对。", "issues": []}, ensure_ascii=False)

    service._stage = fake_stage
    _raw, payload = await service._final_review_json(
        run_id, run_path, project, "constraints", "window prompt",
        suffix="-capacity", recovery_kind="window",
    )

    assert payload["summary"] == "备用路由完成窗口核对。"
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_final_review_transport_interruption_uses_configured_fallback(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "final_review", "primary", "reviewer", "backup", "reviewer-2",
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Review transport fallback", mode="short", genre="suspense",
        premise="A route disconnects during a receipt.", target_words=1000,
    ))
    service = WorkflowService(
        db, store,
        SimpleNamespace(complete_configured_fallback=lambda *_args, **_kwargs: None),
        SimpleNamespace(),
    )
    run_id = "final-transport"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    calls = []

    async def fake_stage(*args, **kwargs):
        fallback = kwargs.get("prefer_configured_fallback") is True
        calls.append("fallback" if fallback else "primary")
        if not fallback:
            raise TransportInterruptedError({
                "provider_id": "primary", "model_id": "reviewer",
                "error_type": "disconnect",
            })
        return json.dumps({
            "summary": "The fallback completed the immutable window review.",
            "issues": [],
        })

    service._stage = fake_stage
    _raw, payload = await service._final_review_json(
        run_id, run_path, project, "constraints", "window prompt",
        suffix="-transport", recovery_kind="window",
    )

    assert payload["summary"].startswith("The fallback")
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_full_review_reuses_validated_windows_after_interruption(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Review window resume", mode="short", genre="suspense",
        premise="Validated windows survive a later interruption.", target_words=1000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    window = json.dumps({"summary": "窗口已完成。", "issues": []}, ensure_ascii=False)
    final = json.dumps({
        "dimensions": {"commercial": 88, "story": 86, "prose": 84},
        "decision": "pass", "issues": [], "reconciliations": [],
    })
    gateway = RecordingGateway([window, final, final])
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)

    first, _audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )
    second, second_audit = await service._full_manuscript_review(
        run_id, run_path, project, "constraints", "short manuscript", {"issues": []},
    )

    assert first["score"] == second["score"]
    assert len(gateway.calls) == 3
    assert second_audit["reviewed_windows"] == 1
    assert any(
        event["event_type"] == "final_review_window_reused"
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

        async def complete_primary(self, role, system, user, max_output_tokens=None):
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

        async def complete_primary(self, role, system, user, max_output_tokens=None):
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
async def test_short_direct_review_cannot_erase_a_prior_issue_by_omission(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Atomic direct review", mode="short", genre="suspense",
        premise="A short candidate still needs issue reconciliation.", target_words=2000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    final = quality_review(commercial=92, story=92, prose=92, issues=[])
    service = WorkflowService(
        db, store, RecordingGateway([final]),
        SkillGate(db, SkillScanner([skill_root])),
    )
    run_id, run_path = service._begin_run(project, "short-story", None)
    candidate = "正文内容。" * 300
    prior = service._review(quality_review(issues=[{
        "category": "story", "severity": "high",
        "evidence": "人物尚未作出选择。", "action": "补足人物选择。",
    }]))

    async def polish(*args, **kwargs):
        return candidate

    monkeypatch.setattr(service, "_polish_short_segments", polish)
    monkeypatch.setattr(
        "novel_flywheel.workflows.select_route",
        lambda *args, **kwargs: {
            "enhanced": False, "max_corrections": 0, "reasons": ["test"],
        },
    )
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args: {
        "coverage": 1.0, "windows": review_windows(candidate),
        "nlp": {"available": True}, "prose": {"blocking_count": 0},
    })

    with pytest.raises(RuntimeError, match="quality gate"):
        await service._quality_polish(
            run_id, run_path, project, "constraints", candidate, prior,
        )

    report = json.loads((run_path / "outputs" / "quality-report.json").read_text(
        encoding="utf-8",
    ))
    terminal = report["final_attempts"][0]["review"]
    assert terminal["issue_reconciliation_complete"] is False
    assert terminal["issues"][0]["action"] == "补足人物选择。"
    assert "missing_issue_reconciliation" in terminal["evidence_gate_reasons"]
    assert load_quality_checkpoint(run_path) is None


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


def _attach_short_revision_semantic_authority(
    service: WorkflowService, project, source: str,
) -> tuple[object, dict]:
    quality_path = project.path / "runs" / "quality-source"
    plan = (
        "### 第一段：核对证词\n事件ID：EV-00000001\n"
        "大纲依据：林晚核对证词。\n段首承接：林晚已经进入档案馆。\n"
        "本段事件：林晚核对证词并确认时间。\n"
        "段末交接：林晚带着确认结果离开档案馆。\n" + "细节" * 60
    )
    manifest = write_test_execution_manifest(
        service, project, quality_path, "constraints", plan, 1,
    )
    service._persist_short_planning_ir(quality_path, plan, 1)
    obligation_catalog = service._whole_story_obligation_catalog(
        quality_path, list(manifest.segments[0].beat_ids),
    )
    integrity = {
        "version": 4,
        "status": "passed",
        "authority_sha256": manifest.authority_sha256,
        "execution_manifest_sha256": execution_manifest_sha256(manifest),
        "draft_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "publication_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "publication_segment_lengths": [len(source)],
        "segments": [{
            "segment": 1,
            "event_ids": list(manifest.segments[0].beat_ids),
            "handoff": "；".join(
                item.state for item in manifest.segments[0].exit_state
            ),
            "han_characters": effective_han_characters(source),
            "previous_sha256": "",
            "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }],
        "semantic_segment_receipts": [],
        "whole_story_obligation_catalog": obligation_catalog,
        "issues": [],
    }
    contract = service._manifest_segment_contract(
        project, manifest, integrity, manifest.segments[0], source, 1,
    )
    integrity["semantic_segment_receipts"] = [
        draft_semantic_receipt(asdict(contract), source),
    ]
    beat_ids = list(manifest.segments[0].beat_ids)
    integrity["whole_semantic_receipt"] = {
        "authority_sha256": manifest.authority_sha256,
        "draft_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "segment_sha256": [
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
        ],
        "event_ids": beat_ids,
        "missing_event_ids": [],
        "duplicate_event_ids": [],
        "out_of_order_event_ids": [],
        "causal_order_valid": True,
        "continuity_valid": True,
        "ending_valid": True,
        "commitments_valid": True,
        "evidence": [{"kind": "whole", "excerpt": source[:12]}],
        "summary": "验收前全文语义完整。",
    }
    integrity_path = quality_path / "outputs" / "polish-integrity.json"
    integrity_path.write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (quality_path / "outputs" / "draft-integrity.json").write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    checkpoint = load_quality_checkpoint(quality_path)
    checkpoint["narrative_integrity"] = {
        "path": "outputs/polish-integrity.json",
        "sha256": hashlib.sha256(integrity_path.read_bytes()).hexdigest(),
    }
    write_quality_checkpoint(quality_path, checkpoint)
    return manifest, integrity


def _attach_multi_segment_polish_semantic_authority(
    service: WorkflowService, project, source_parts: list[str],
) -> tuple[object, dict]:
    quality_path = project.path / "runs" / "quality-source"
    plan = "\n\n".join(
        (
            f"### 第 {index} 段：测试段 {index}\n"
            f"事件ID：EV-{index:08X}\n"
            f"大纲依据：完成第 {index} 项测试事件。\n"
            + (
                "段首承接：故事入口状态已经明确。\n"
                if index == 1 else
                f"段首承接：第 {index - 1} 项结果已经成立。\n"
            )
            + f"本段事件：主角完成第 {index} 项测试事件。\n"
            + (
                "段末交接：故事进入稳定结局。\n"
                if index == len(source_parts) else
                f"段末交接：第 {index} 项结果成立，可以继续下一项。\n"
            )
            + "测试细节" * 40
        )
        for index in range(1, len(source_parts) + 1)
    )
    manifest = write_test_execution_manifest(
        service, project, quality_path, "constraints", plan, len(source_parts),
    )
    service._persist_short_planning_ir(
        quality_path, plan, len(source_parts),
    )
    obligation_catalog = service._whole_story_obligation_catalog(
        quality_path,
        [beat_id for segment in manifest.segments for beat_id in segment.beat_ids],
    )
    source = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(source_parts)
    integrity = {
        "version": 4,
        "status": "passed",
        "authority_sha256": manifest.authority_sha256,
        "execution_manifest_sha256": execution_manifest_sha256(manifest),
        "draft_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "publication_sha256": hashlib.sha256(
            "\n\n".join(source_parts).encode("utf-8"),
        ).hexdigest(),
        "publication_segment_lengths": [len(part) for part in source_parts],
        "segments": [],
        "semantic_segment_receipts": [],
        "whole_story_obligation_catalog": obligation_catalog,
        "issues": [],
    }
    previous_hash = ""
    for index, (part, manifest_segment) in enumerate(
        zip(source_parts, manifest.segments, strict=True), 1,
    ):
        text_hash = hashlib.sha256(part.encode("utf-8")).hexdigest()
        integrity["segments"].append({
            "segment": index,
            "event_ids": list(manifest_segment.beat_ids),
            "handoff": "；".join(
                item.state for item in manifest_segment.exit_state
            ),
            "han_characters": effective_han_characters(part),
            "previous_sha256": previous_hash,
            "text_sha256": text_hash,
        })
        contract = service._manifest_segment_contract(
            project, manifest, integrity, manifest_segment, part, index,
        )
        integrity["semantic_segment_receipts"].append(
            draft_semantic_receipt(asdict(contract), part)
        )
        previous_hash = text_hash
    beat_ids = [
        beat_id for segment in manifest.segments for beat_id in segment.beat_ids
    ]
    integrity["whole_semantic_receipt"] = {
        "authority_sha256": manifest.authority_sha256,
        "draft_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "segment_sha256": [
            hashlib.sha256(part.encode("utf-8")).hexdigest()
            for part in source_parts
        ],
        "event_ids": beat_ids,
        "missing_event_ids": [],
        "duplicate_event_ids": [],
        "out_of_order_event_ids": [],
        "causal_order_valid": True,
        "continuity_valid": True,
        "ending_valid": True,
        "commitments_valid": True,
        "evidence": [{"kind": "whole", "excerpt": source_parts[0][:12]}],
        "summary": "验收前三段正文语义完整。",
    }
    (quality_path / "outputs" / "draft-integrity.json").write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return manifest, integrity


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


def test_short_revision_target_range_keeps_accepted_source_admissible() -> None:
    project = SimpleNamespace(metadata={"target_words": 13_000})

    assert WorkflowService._short_revision_target_range(
        project, source_han=13_703,
    ) == (13_000, 13_703)
    assert WorkflowService._short_revision_target_range(
        project, source_han=12_000,
    ) == (12_000, 13_000)
    assert WorkflowService._short_revision_target_range(
        project, source_han=13_000,
    ) == (13_000, 13_000)


def test_publication_segments_recover_without_exposing_internal_marker(
    tmp_path,
) -> None:
    parts = ["第一段正文。", "第二段正文。"]
    publication = "\n\n".join(parts)
    segmented = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(parts)
    integrity = {
        "draft_sha256": hashlib.sha256(segmented.encode("utf-8")).hexdigest(),
        "publication_sha256": hashlib.sha256(
            publication.encode("utf-8"),
        ).hexdigest(),
        "publication_segment_lengths": [len(part) for part in parts],
        "segments": [
            {
                "segment": index,
                "text_sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(),
            }
            for index, part in enumerate(parts, 1)
        ],
    }

    recovered = WorkflowService._integrity_publication_segments(
        tmp_path, integrity, publication,
    )

    assert recovered == (parts, segmented)
    assert WorkflowService.SHORT_SEGMENT_SEPARATOR not in publication


def test_publication_segments_reject_stale_hash_and_cross_boundary_change(
    tmp_path,
) -> None:
    parts = ["第一段正文。", "第二段正文。"]
    publication = "\n\n".join(parts)
    integrity = {
        "draft_sha256": hashlib.sha256(publication.encode("utf-8")).hexdigest(),
        "publication_sha256": "0" * 64,
        "publication_segment_lengths": [len(part) for part in parts],
        "segments": [
            {
                "segment": index,
                "text_sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(),
            }
            for index, part in enumerate(parts, 1)
        ],
    }

    assert WorkflowService._integrity_publication_segments(
        tmp_path, integrity, publication,
    ) is None
    with pytest.raises(DraftSemanticValidationError):
        WorkflowService._candidate_segments_from_clean_source(
            publication, publication.replace("\n\n", "\n", 1), parts,
        )


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
    assert calls == ["revision_plan", "revision_plan"]
    assert result["status"] == "waiting_local_fix"
    assert group["status"] == "rejected"
    assert group["failures"] == [{
        "patch": 0,
        "code": "expansion_contract_rejected",
    }]
    assert "final_review" not in calls


@pytest.mark.asyncio
async def test_expansion_plan_protocol_retry_recovers_alias_without_changing_authority(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, _state, anchors = _expansion_service(
        tmp_path,
    )
    valid_plan = _expansion_plan(anchors[0])
    valid_plan["operation"] = "在后插入"
    calls = []

    async def stage(*args, **kwargs):
        request = json.loads(args[5])
        calls.append(args[3])
        if args[3] == "revision_plan":
            if calls.count("revision_plan") == 1:
                invalid = dict(valid_plan)
                invalid.pop("purpose")
                return json.dumps({"scenes": [invalid]}, ensure_ascii=False)
            assert request["candidate_hash"] == hashlib.sha256(
                source.encode("utf-8"),
            ).hexdigest()
            assert "protocol_repair" in request
            return json.dumps({"scenes": [valid_plan]}, ensure_ascii=False)
        return json.dumps(
            _expansion_draft(valid_plan, _expansion_scene_text(2000)),
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [ledger[0]["issue_id"]],
        run_id="expand-protocol-recovery",
    )

    assert calls == ["revision_plan", "revision_plan", "draft"]
    assert result["status"] == "waiting_confirmation"
    assert result["candidate"].startswith(source)
    records = json.loads((
        project.path / "runs" / "expand-protocol-recovery"
        / "outputs" / "patch-groups.json"
    ).read_text(encoding="utf-8"))["groups"]
    scene = records[0]["patch_group"]["expansion_contracts"][0]
    assert scene["operation"] == "insert_after"
    assert scene["raw_operation"] == "在后插入"
    assert any(
        item["event_type"] == "short_expansion_contract_retry"
        for item in service.db.list_run_events("expand-protocol-recovery")
    )


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
async def test_non_length_issue_below_minimum_stays_targeted_and_admissible(
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
    assert result["status"] == "waiting_confirmation"
    assert "档案员确认记录后合上簿册。" in result["candidate"]


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
async def test_short_revision_repairs_atomic_drift_before_user_confirmation(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间。" * 30
        + "甲问题原句。"
        + "她确认记录无误，带着结果离开。" * 20
    )
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "high",
            "evidence": "甲问题原句。",
            "action": "说明林晚如何完成核对",
        }], source=source,
    )
    _attach_short_revision_semantic_authority(service, project, source)
    issue_id = ledger[0]["issue_id"]
    calls = []
    semantic_repair_calls = 0

    async def stage(*args, **kwargs):
        nonlocal semantic_repair_calls
        stage_name, prompt = args[3], args[5]
        calls.append((stage_name, prompt))
        if stage_name == "revision_plan":
            request = json.loads(prompt)
            if request["schema"] == "targeted-repair-group-v1":
                return _short_revision_patch(
                    request, "甲问题原句。", "花穗来核对。",
                )
            assert request["schema"] == "targeted-atomic-semantic-repair-v1"
            assert request["semantic_failures"]
            semantic_repair_calls += 1
            return _short_revision_patch(
                request, "甲问题原句。",
                "林晚来核对。\ufffd" if semantic_repair_calls == 1 else "林晚来核对。",
            )
        assert stage_name == "review"
        contract = json.loads(re.search(
            r"TASK CONTRACT: (\{[^\n]+\})", prompt,
        ).group(1))
        prose = prompt.split("PROSE:\n", 1)[1]
        receipt = draft_semantic_receipt(contract, prose)
        if "花穗来核对" in prose:
            receipt["beat_receipts"][0]["actor_action_valid"] = False
        return json.dumps(receipt, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-atomic-drift",
    )

    assert result["status"] == "waiting_confirmation"
    assert "林晚来核对。" in result["candidate"]
    assert "花穗来核对。" not in result["candidate"]
    assert "\ufffd" not in result["candidate"]
    assert semantic_repair_calls == 2
    assert [stage_name for stage_name, _ in calls] == [
        "revision_plan", "review", "revision_plan", "review",
        "revision_plan", "review",
    ]
    assert any(
        event["event_type"] == "short_revision_semantic_repaired"
        for event in service.db.list_run_events("repair-atomic-drift")
    )


@pytest.mark.asyncio
async def test_short_revision_semantic_repair_cannot_expand_beyond_original_anchor(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间。" * 30
        + "甲问题原句。"
        + "她确认记录无误，带着结果离开。" * 20
    )
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "high",
            "evidence": "甲问题原句。",
            "action": "说明林晚如何完成核对",
        }], source=source,
    )
    _attach_short_revision_semantic_authority(service, project, source)
    issue_id = ledger[0]["issue_id"]
    semantic_repair_calls = 0
    review_calls = 0

    async def stage(*args, **kwargs):
        nonlocal semantic_repair_calls, review_calls
        stage_name, prompt = args[3], args[5]
        if stage_name == "revision_plan":
            request = json.loads(prompt)
            if request["schema"] == "targeted-repair-group-v1":
                return _short_revision_patch(
                    request, "甲问题原句。", "花穗来核对。",
                )
            semantic_repair_calls += 1
            if semantic_repair_calls == 1:
                return _short_revision_patch(
                    request, "她确认记录无误", "她忽然烧掉记录",
                )
            return _short_revision_patch(
                request, "甲问题原句。", "林晚来核对。",
            )
        review_calls += 1
        contract = json.loads(re.search(
            r"TASK CONTRACT: (\{[^\n]+\})", prompt,
        ).group(1))
        prose = prompt.split("PROSE:\n", 1)[1]
        receipt = draft_semantic_receipt(contract, prose)
        if "花穗来核对" in prose:
            receipt["beat_receipts"][0]["actor_action_valid"] = False
        return json.dumps(receipt, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-atomic-scope",
    )

    assert result["status"] == "waiting_confirmation"
    assert "林晚来核对。" in result["candidate"]
    assert "她忽然烧掉记录" not in result["candidate"]
    assert semantic_repair_calls == 2
    assert review_calls == 2


@pytest.mark.asyncio
async def test_short_revision_whole_semantic_failure_isolates_conflicting_group(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间。" * 30
        + "甲问题原句。"
        + "她确认记录无误，带着结果离开。" * 20
    )
    service, project, _source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "high",
            "evidence": "甲问题原句。",
            "action": "说明林晚如何完成核对",
        }], source=source,
    )
    _manifest, source_integrity = _attach_short_revision_semantic_authority(
        service, project, source,
    )
    issue_id = ledger[0]["issue_id"]

    async def stage(*args, **kwargs):
        prompt = args[5]
        if args[3] == "revision_plan":
            request = json.loads(prompt)
            return _short_revision_patch(
                request, "甲问题原句。", "林晚来核对。",
            )
        contract = json.loads(re.search(
            r"TASK CONTRACT: (\{[^\n]+\})", prompt,
        ).group(1))
        prose = prompt.split("PROSE:\n", 1)[1]
        return json.dumps(
            draft_semantic_receipt(contract, prose), ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_stage", stage)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-whole-semantic",
    )
    service.decide_short_revision_group(
        result["id"], issue_id, "adopted", result["candidate_hash"],
    )
    final_review_calls = []

    async def fail_changed_candidate(
        run_id, run_path, current_project, constraints, accepted_source,
        candidate, semantic_authority, **kwargs,
    ):
        assert kwargs["verify_whole"] is True
        if candidate != accepted_source:
            raise DraftSemanticValidationError("whole-story", [{
                "code": "causal_order",
                "message": "合并后事件顺序发生倒退",
            }])
        return {
            **source_integrity,
            "version": 5,
            "status": "passed",
            "source_draft_sha256": hashlib.sha256(
                accepted_source.encode("utf-8"),
            ).hexdigest(),
            "draft_sha256": hashlib.sha256(
                candidate.encode("utf-8"),
            ).hexdigest(),
            "changed_segments": [],
            "issues": [],
        }

    async def successful_final_review(*args, **kwargs):
        final_review_calls.append(True)
        return ({
            "score": 95,
            "dimensions": {"commercial": 95, "story": 95, "prose": 95},
            "hard_fail": False,
            "decision": "pass",
            "issues": [],
            "scoring_profile_id": "legacy-v1",
            "judge_signature": "fake/reviewer",
        }, {"review_mode": "full", "fallback_reasons": []})

    monkeypatch.setattr(
        service, "_verify_atomic_candidate_semantics", fail_changed_candidate,
    )
    monkeypatch.setattr(
        service, "_incremental_manuscript_review", successful_final_review,
    )
    finalized = await service.finalize_short_revision(result["id"])

    assert finalized["status"] == "completed"
    assert final_review_calls == [True]
    assert (
        project.path / "runs" / result["id"] / "outputs" / "candidate.md"
    ).read_text(encoding="utf-8") == source
    assert any(
        event["event_type"] == "short_revision_semantic_subset_restored"
        for event in service.db.list_run_events(result["id"])
    )
    checkpoint = load_quality_checkpoint(project.path / "runs" / result["id"])
    assert checkpoint is not None
    unresolved = {
        item["issue_id"] for item in checkpoint["issue_ledger"]
        if item.get("status") != "resolved"
    }
    assert issue_id in unresolved


@pytest.mark.asyncio
async def test_short_revision_semantic_subset_keeps_non_adjacent_safe_groups(
    tmp_path, monkeypatch,
) -> None:
    source = "甲原文。乙原文。丙原文。"
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source, target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    adopted_records = [
        {
            "group_id": "group-1",
            "issue_ids": ["issue-1"],
            "patch_group": {
                "patches": [{
                    "operation": "replace",
                    "old_text": "甲原文。",
                    "new_text": "甲安全修改。",
                }],
            },
        },
        {
            "group_id": "group-2",
            "issue_ids": ["issue-2"],
            "patch_group": {
                "patches": [{
                    "operation": "replace",
                    "old_text": "乙原文。",
                    "new_text": "乙冲突修改。",
                }],
            },
        },
        {
            "group_id": "group-3",
            "issue_ids": ["issue-3"],
            "patch_group": {
                "patches": [{
                    "operation": "replace",
                    "old_text": "丙原文。",
                    "new_text": "丙安全修改。",
                }],
            },
        },
    ]

    async def semantic_gate(
        _run_id, _run_path, _project, _constraints, accepted_source,
        candidate, _semantic_authority, **kwargs,
    ):
        assert accepted_source == source
        if "乙冲突修改。" in candidate:
            raise DraftSemanticValidationError("whole", [{
                "code": "causal_order",
                "message": "第二组破坏整篇因果",
            }])
        return {
            "status": "passed",
            "draft_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        }

    monkeypatch.setattr(
        service, "_verify_atomic_candidate_semantics", semantic_gate,
    )
    recovered = await service._recover_short_revision_semantic_subset(
        "quality-source", run_path, project, "constraints", source,
        {"test": "authority"}, adopted_records,
        [{"code": "causal_order", "message": "组合冲突"}],
    )

    assert recovered["candidate"] == "甲安全修改。乙原文。丙安全修改。"
    assert [item["group_id"] for item in recovered["records"]] == [
        "group-1", "group-3",
    ]
    assert recovered["rejected_issue_ids"] == {"issue-2"}
    assert adopted_records[1]["status"] == "rejected_after_final_semantic_gate"


@pytest.mark.asyncio
async def test_polish_semantic_drift_is_repaired_before_source_fallback(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间。" * 30
        + "她确认记录无误，带着结果离开。" * 20
    )
    rejected = source.replace("林晚逐页核对", "错误执行者逐页核对", 1)
    repaired = source.replace("逐页核对", "仔细核对", 1)
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source,
    )
    manifest, _integrity = _attach_short_revision_semantic_authority(
        service, project, source,
    )
    run_path = project.path / "runs" / "quality-source"
    calls = []
    semantic_repair_calls = 0
    original_assessment = __import__(
        "novel_flywheel.workflows", fromlist=["assess_polish_candidate"],
    ).assess_polish_candidate

    def accept_semantic_test_candidate(*args, **kwargs):
        assessment = original_assessment(*args, **kwargs)
        if len(args) > 1 and args[1] == rejected:
            assessment["accepted"] = True
            assessment["reasons"] = []
            assessment["hard_reasons"] = []
        return assessment

    async def stage(*args, **kwargs):
        nonlocal semantic_repair_calls
        stage_name, prompt = args[3], args[5]
        calls.append((stage_name, prompt))
        if "ATOMIC_SEMANTIC_PROSE_REPAIR" in prompt:
            semantic_repair_calls += 1
            if semantic_repair_calls == 1:
                return repaired + "\ufffd"
            return repaired
        if "DRAFT_SEMANTIC_VALIDATION" in prompt:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", prompt,
            ).group(1))
            prose = prompt.split("PROSE:\n", 1)[1]
            receipt = draft_semantic_receipt(contract, prose)
            if "错误执行者" in prose:
                receipt["beat_receipts"][0]["actor_action_valid"] = False
            return json.dumps(receipt, ensure_ascii=False)
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in prompt:
            authority = re.search(
                r"AUTHORITY SHA256: ([0-9a-f]{64})", prompt,
            ).group(1)
            draft_sha = re.search(
                r"DRAFT SHA256: ([0-9a-f]{64})", prompt,
            ).group(1)
            segment_sha = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
            ).group(1))
            beat_ids = list(manifest.segments[0].beat_ids)
            opening = prompt.split(
                "OPENING EXCERPT: ", 1,
            )[1].split("\nENDING EXCERPT:", 1)[0]
            ending = prompt.split("ENDING EXCERPT: ", 1)[1]
            return json.dumps({
                "authority_sha256": authority,
                "draft_sha256": draft_sha,
                "segment_sha256": segment_sha,
                "event_ids": beat_ids,
                "missing_event_ids": [],
                "duplicate_event_ids": [],
                "out_of_order_event_ids": [],
                "causal_order_valid": True,
                "continuity_valid": True,
                "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"excerpt": opening[:12]},
                    {"excerpt": ending[-12:]},
                ],
                "summary": "返修后整篇连续。",
            }, ensure_ascii=False)
        assert stage_name == "polish"
        return rejected

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(
        "novel_flywheel.workflows.assess_polish_candidate",
        accept_semantic_test_candidate,
    )
    result = await service._polish_short_segments(
        "quality-source", run_path, project, "constraints", source, "{}",
    )

    assert result == repaired
    assert semantic_repair_calls == 2
    assert any(
        event["event_type"] == "polish_semantic_repaired"
        for event in service.db.list_run_events("quality-source")
    )
    assert not any(
        event["event_type"] == "polish_segment_preserved"
        for event in service.db.list_run_events("quality-source")
    )


@pytest.mark.asyncio
async def test_polish_chains_semantic_authority_from_prior_polish(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "\u6797\u665a\u5728\u6863\u6848\u9986\u6838\u5bf9\u6bcf\u4e00\u6761\u65f6\u95f4\u8bb0\u5f55\u3002" * 30
        + "\u5979\u786e\u8ba4\u8bb0\u5f55\u65e0\u8bef\uff0c\u5e26\u7740\u7ed3\u679c\u79bb\u5f00\u3002" * 20
    ).strip()
    first_polish = source.replace(
        "\u6838\u5bf9\u6bcf\u4e00\u6761", "\u4ed4\u7ec6\u6838\u5bf9\u6bcf\u4e00\u6761", 1,
    )
    second_polish = first_polish.replace(
        "\u5e26\u7740\u7ed3\u679c", "\u5e26\u7740\u5b8c\u6574\u7ed3\u679c", 1,
    )
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source, target_words=500,
    )
    manifest, integrity = _attach_short_revision_semantic_authority(
        service, project, source,
    )
    run_path = project.path / "runs" / "quality-source"
    chained = json.loads(json.dumps(integrity, ensure_ascii=False))
    first_hash = hashlib.sha256(first_polish.encode("utf-8")).hexdigest()
    chained.update({
        "source_draft_sha256": hashlib.sha256(
            source.encode("utf-8"),
        ).hexdigest(),
        "draft_sha256": first_hash,
        "publication_sha256": first_hash,
        "publication_segment_lengths": [len(first_polish)],
    })
    chained["segments"][0]["text_sha256"] = first_hash
    chained["segments"][0]["han_characters"] = effective_han_characters(
        first_polish,
    )
    contract = service._manifest_segment_contract(
        project, manifest, chained, manifest.segments[0], first_polish, 1,
    )
    chained["semantic_segment_receipts"] = [
        draft_semantic_receipt(asdict(contract), first_polish),
    ]
    (run_path / "outputs" / "polish-integrity.json").write_text(
        json.dumps(chained, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    original_assessment = __import__(
        "novel_flywheel.workflows", fromlist=["assess_polish_candidate"],
    ).assess_polish_candidate

    def accept_second_polish(*args, **kwargs):
        assessment = original_assessment(*args, **kwargs)
        if len(args) > 1 and args[1] == second_polish:
            assessment["accepted"] = True
            assessment["reasons"] = []
            assessment["hard_reasons"] = []
        return assessment

    async def stage(*args, **kwargs):
        assert args[3] == "polish"
        return second_polish

    calls = {"segment": 0, "whole": 0}

    async def segment_semantics(*args, **kwargs):
        calls["segment"] += 1
        return draft_semantic_receipt(asdict(args[4]), args[5])

    async def whole_semantics(*args, **kwargs):
        calls["whole"] += 1
        return {"status": "passed"}

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(service, "_verify_draft_semantic_node", segment_semantics)
    monkeypatch.setattr(service, "_verify_whole_draft_semantics", whole_semantics)
    monkeypatch.setattr(
        "novel_flywheel.workflows.assess_polish_candidate",
        accept_second_polish,
    )

    result = await service._polish_short_segments(
        "quality-source", run_path, project, "constraints", first_polish, "{}",
        suffix="-chained",
    )

    next_integrity = json.loads(
        (run_path / "outputs" / "polish-integrity-chained.json").read_text(
            encoding="utf-8",
        ),
    )
    assert result == second_polish
    assert calls == {"segment": 1, "whole": 1}
    assert next_integrity["source_draft_sha256"] == first_hash
    assert next_integrity["draft_sha256"] == hashlib.sha256(
        second_polish.encode("utf-8"),
    ).hexdigest()


@pytest.mark.asyncio
async def test_post_mutation_quality_failure_preserves_protected_best(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, _ledger, _state = _short_revision_service(
        tmp_path, [], target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    passing = service._review(quality_review())
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    protected_report = {
        "status": "passed",
        "terminal_review_complete": True,
        "terminal_reviewed_hash": source_hash,
    }
    service._save_quality_checkpoint(run_path, source, passing, 1, "passed")
    service._write_quality_report(run_path, protected_report)
    best_before = (run_path / "outputs" / "best-candidate.md").read_bytes()
    checkpoint_before = (
        run_path / "outputs" / "quality-checkpoint.json"
    ).read_bytes()
    report_before = (run_path / "outputs" / "quality-report.json").read_bytes()
    mutated = source.replace("Two independent local issues.", "mutated", 1)
    if mutated == source:
        mutated = source + "\n\n\u8fd9\u662f\u672a\u901a\u8fc7\u7ec8\u5ba1\u7684\u6539\u5199\u3002"

    async def failed_review(*args, **kwargs):
        return service._review(quality_review(
            commercial=40, story=40, prose=40, decision="rewrite",
        )), {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 1, "window_count": 1,
        }

    monkeypatch.setattr(service, "_full_manuscript_review", failed_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args, **kwargs: {})

    with pytest.raises(RuntimeError, match="Post-mutation manuscript"):
        await service._close_post_quality_mutation(
            "quality-source", run_path, project, "constraints", mutated,
            passing, protected_report, suffix="-originality", max_corrections=0,
        )

    assert (run_path / "outputs" / "best-candidate.md").read_bytes() == best_before
    assert (
        run_path / "outputs" / "quality-checkpoint.json"
    ).read_bytes() == checkpoint_before
    assert (run_path / "outputs" / "quality-report.json").read_bytes() == report_before
    rejected = list((run_path / "outputs").glob("post-mutation-rejected-*.md"))
    failures = list((run_path / "outputs").glob(
        "post-mutation-quality-failure-*.json",
    ))
    assert len(rejected) == len(failures) == 1
    assert rejected[0].read_text(encoding="utf-8") == mutated


@pytest.mark.asyncio
async def test_post_mutation_quality_pass_binds_exact_publication_hash(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, _ledger, _state = _short_revision_service(
        tmp_path, [], target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    passing = service._review(quality_review())
    mutated = source + "\n\n\u5979\u53ea\u6539\u5199\u4e86\u4e0e\u53c2\u8003\u6587\u672c\u8fd1\u4f3c\u7684\u8868\u8fbe\u3002"
    calls = 0

    async def passed_review(*args, **kwargs):
        nonlocal calls
        calls += 1
        return passing, {
            "coverage": 1.0, "windows": [], "review_mode": "full",
            "reviewed_windows": 1, "window_count": 1,
        }

    monkeypatch.setattr(service, "_full_manuscript_review", passed_review)
    monkeypatch.setattr(service, "_analyze_manuscript", lambda *args, **kwargs: {})

    selected, report = await service._close_post_quality_mutation(
        "quality-source", run_path, project, "constraints", mutated,
        passing, {"status": "passed"}, suffix="-originality",
        max_corrections=0,
    )

    publication = "\n\n".join(service._split_segments(selected))
    digest = hashlib.sha256(publication.encode("utf-8")).hexdigest()
    checkpoint = load_quality_checkpoint(run_path)
    assert calls == 1
    assert report["status"] == "passed"
    assert report["terminal_reviewed_hash"] == digest
    assert checkpoint is not None
    assert checkpoint["outcome"] == "passed"
    assert checkpoint["manuscript_hash"] == digest
    service._require_short_formal_quality_authority(run_path, report, publication)


def test_maintenance_authority_is_incremental_and_conflicts_fail_closed() -> None:
    state = {
        "confirmed_facts": [{
            "key": "character.hero.identity",
            "value": "\u5979\u5df2\u786e\u8ba4\u81ea\u5df1\u7684\u771f\u5b9e\u8eab\u4efd\u3002",
            "source": "earlier-run",
        }],
        "locked_facts": [],
        "character_states": {"hero": {"knowledge": "identity-confirmed"}},
        "world_rules": ["\u8eab\u4efd\u8bb0\u5f55\u4e0d\u53ef\u4f2a\u9020\u3002"],
        "timeline_events": ["\u5979\u627e\u5230\u4e86\u6863\u6848\u3002"],
    }
    candidate = {
        "facts": [{
            "key": "character.hero.choice",
            "value": "\u5979\u9009\u62e9\u7559\u4e0b\u5e76\u516c\u5f00\u540d\u5b57\u3002",
        }],
        "state": {
            "hero": {"trust": "earned"},
            "ally": {"trust": "earned"},
        },
        "world_rules": ["\u516c\u5f00\u627f\u8bfa\u5fc5\u987b\u7559\u6863\u3002"],
        "timeline": ["\u5979\u5728\u4f17\u4eba\u9762\u524d\u4f5c\u51fa\u9009\u62e9\u3002"],
    }

    canon, confirmed = WorkflowService._merge_short_maintenance_authority(
        state, candidate, run_id="new-run",
    )

    assert [item["key"] for item in confirmed] == [
        "character.hero.identity", "character.hero.choice",
    ]
    assert canon["facts"] == confirmed
    assert canon["state"] == {
        "hero": {"knowledge": "identity-confirmed", "trust": "earned"},
        "ally": {"trust": "earned"},
    }
    assert len(canon["world_rules"]) == 2
    assert len(canon["timeline"]) == 2

    with pytest.raises(ValueError, match="conflicts with protected fact"):
        WorkflowService._merge_short_maintenance_authority(
            state, {
                **candidate,
                "facts": [{
                    "key": "character.hero.identity",
                    "value": "\u5979\u4ece\u672a\u627e\u5230\u771f\u5b9e\u8eab\u4efd\u3002",
                }],
            },
            run_id="conflicting-run",
        )

    with pytest.raises(ValueError, match="state conflicts"):
        WorkflowService._merge_short_maintenance_authority(
            state, {
                **candidate,
                "facts": [],
                "state": {"hero": {"knowledge": "identity-denied"}},
            },
            run_id="state-conflict",
            manuscript_text="The manuscript contains no supported transition.",
        )

    with pytest.raises(ValueError, match="world_rules must be an array"):
        WorkflowService._merge_short_maintenance_authority(
            state, {
                "facts": [], "state": {},
                "world_rules": "magic has a cost",
                "timeline": {"event": "the hero pays"},
            },
            run_id="wrong-shape",
        )

    safe, duplicate_conflicts = WorkflowService._partition_short_maintenance_proposal(
        state,
        {
            "facts": [
                {"key": "new.fact", "value": "first"},
                {"key": "new.fact", "value": "second"},
            ],
            "state": {}, "world_rules": [], "timeline": [],
        },
        run_id="duplicate-conflict",
    )
    assert safe["facts"] == [{"key": "new.fact", "value": "first"}]
    assert len(duplicate_conflicts) == 1
    assert duplicate_conflicts[0]["fact_key"] == "new.fact"

    transitioned, _ = WorkflowService._merge_short_maintenance_authority(
        state, {
            **candidate,
            "facts": [],
            "state": {"hero": {
                "knowledge": "identity-shared", "trust": "earned",
            }},
            "state_transitions": [{
                "character": "hero",
                "field": "knowledge",
                "from": "identity-confirmed",
                "to": "identity-shared",
                "evidence": "She tells the ally her confirmed identity.",
            }],
        },
        run_id="state-transition",
        manuscript_text="She tells the ally her confirmed identity.",
    )
    assert transitioned["state"]["hero"] == {
        "knowledge": "identity-shared", "trust": "earned",
    }


@pytest.mark.asyncio
async def test_maintenance_authority_conflict_uses_one_bounded_repair(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, _ledger, _state = _short_revision_service(
        tmp_path, [], target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    state = {
        "confirmed_facts": [{
            "key": "character.hero.identity",
            "value": "confirmed identity",
        }],
        "locked_facts": [],
    }
    responses = [
        {"facts": [
            {
                "key": "character.hero.identity", "value": "conflicting identity",
            },
            {
                "key": "character.hero.choice", "value": "stays by choice",
            },
        ], "world_rules": "magic has a cost",
           "timeline": {"event": "the hero pays"}},
        {"facts": []},
    ]
    prompts: list[str] = []

    async def maintenance_stage(*args, **kwargs):
        prompts.append(args[5])
        return json.dumps(responses[len(prompts) - 1])

    monkeypatch.setattr(service, "_stage_with_role_fallback", maintenance_stage)

    canon, confirmed = await service._close_short_maintenance_authority(
        "quality-source", run_path, project, "constraints", source, state,
    )

    assert len(prompts) == 2
    assert "maintenance-authority-repair-v1" in prompts[1]
    repair_envelope = json.loads(prompts[1])
    assert repair_envelope["authoritative_manuscript"]["text"] == source
    assert repair_envelope["authoritative_manuscript"]["sha256"] == hashlib.sha256(
        source.encode("utf-8"),
    ).hexdigest()
    assert repair_envelope["preserved_proposal"]["facts"] == [{
        "key": "character.hero.choice", "value": "stays by choice",
    }]
    assert [item["key"] for item in confirmed] == [
        "character.hero.identity", "character.hero.choice",
    ]
    assert canon["facts"] == confirmed
    assert canon["world_rules"] == ["magic has a cost"]
    assert canon["timeline"] == [{"event": "the hero pays"}]
    adapter_audits = list((run_path / "receipts").glob(
        "maintenance-adapter-*.json",
    ))
    assert len(adapter_audits) == 1
    assert json.loads(adapter_audits[0].read_text(
        encoding="utf-8",
    ))["schema"] == "maintenance-contract-adapter-audit-v1"


@pytest.mark.asyncio
async def test_maintenance_state_transition_repair_receives_exact_prose_authority(
    tmp_path, monkeypatch,
) -> None:
    manuscript = "她当众把确认过的身份告诉盟友，并交出档案副本。"
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=manuscript, target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    state = {
        "confirmed_facts": [],
        "locked_facts": [],
        "character_states": {"hero": {"knowledge": "identity-confirmed"}},
    }
    responses = [
        {
            "facts": [],
            "state": {"hero": {"knowledge": "identity-shared"}},
            "state_transitions": [{
                "character": "hero",
                "field": "knowledge",
                "from": "identity-confirmed",
                "to": "identity-shared",
                "evidence": "她向盟友说明了自己的真实身份。",
            }],
        },
        {
            "facts": [],
            "state": {"hero": {"knowledge": "identity-shared"}},
            "state_transitions": [{
                "character": "hero",
                "field": "knowledge",
                "from": "identity-confirmed",
                "to": "identity-shared",
                "evidence": manuscript,
            }],
        },
    ]
    prompts: list[str] = []

    async def maintenance_stage(*args, **kwargs):
        prompts.append(args[5])
        if len(prompts) == 2:
            authority = json.loads(prompts[-1])["authoritative_manuscript"]
            assert authority["text"] == manuscript
            assert authority["sha256"] == hashlib.sha256(
                manuscript.encode("utf-8"),
            ).hexdigest()
        return json.dumps(responses[len(prompts) - 1], ensure_ascii=False)

    monkeypatch.setattr(service, "_stage_with_role_fallback", maintenance_stage)

    canon, _confirmed = await service._close_short_maintenance_authority(
        "quality-source", run_path, project, "constraints", manuscript, state,
    )

    assert len(prompts) == 2
    assert canon["state"]["hero"]["knowledge"] == "identity-shared"
    assert canon["state_transitions"][0]["evidence"] == manuscript


@pytest.mark.asyncio
async def test_maintenance_capacity_windows_cover_middle_facts_and_reduce_deterministically(
    tmp_path, monkeypatch,
) -> None:
    markers = [
        "首段事实：她收起蓝色钥匙。",
        "中段事实：她把钥匙交给守门人。",
        "尾段事实：守门人公开了档案。",
    ]
    manuscript = "\n\n".join(
        marker + (f"第{index}段环境保持一致。" * 45)
        for index, marker in enumerate(markers, 1)
    )
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=manuscript, target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    calls: list[dict] = []
    recursive_splits = 0

    async def capacity_stage(*args, **kwargs):
        nonlocal recursive_splits
        prompt = args[5]
        if prompt == manuscript:
            result = await kwargs["capacity_splitter"]({
                "trigger": "preflight", "pressure": "split",
                "context_window": 1800, "output_reserve": 1000,
            })
            return StageText(result, {"execution_mode": "capacity_split"})
        request = json.loads(prompt)
        assert request["schema"] == "maintenance-window-request-v1"
        window_text = request["window_text"]
        if len(window_text) > 250:
            recursive_splits += 1
            result = await kwargs["capacity_splitter"]({
                "trigger": "provider", "pressure": "split",
                "context_window": 900, "output_reserve": 500,
            })
            return StageText(result, {"execution_mode": "capacity_split"})
        calls.append(request)
        facts = [
            {
                "key": f"story.fact.{index}",
                "value": marker,
                "evidence": marker,
            }
            for index, marker in enumerate(markers, 1)
            if marker in window_text
        ]
        return json.dumps({
            "version": "maintenance-window-receipt-v1",
            "facts": facts,
            "state_deltas": [],
            "state_transitions": [],
            "world_rules": [],
            "timeline": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage_with_role_fallback", capacity_stage)

    canon, confirmed = await service._close_short_maintenance_authority(
        "quality-source", run_path, project, "constraints", manuscript,
        {"confirmed_facts": [], "locked_facts": []},
    )

    assert len(calls) >= 3
    assert recursive_splits >= 1
    assert all(len(call["window_text"]) <= 250 for call in calls)
    assert [item["key"] for item in confirmed] == [
        "story.fact.1", "story.fact.2", "story.fact.3",
    ]
    assert canon["facts"] == confirmed
    assert any(markers[1] in call["window_text"] for call in calls)
    reduction_paths = list((run_path / "receipts").glob(
        "maintenance-reduction-*.json",
    ))
    assert len(reduction_paths) == 1
    reduction = json.loads(reduction_paths[0].read_text(encoding="utf-8"))
    assert reduction["coverage_spans"][0][0] == 0
    assert max(end for _start, end in reduction["coverage_spans"]) == len(manuscript)

    first_window_call_count = len(calls)
    resumed_canon, resumed_confirmed = await service._close_short_maintenance_authority(
        "quality-source", run_path, project, "constraints", manuscript,
        {"confirmed_facts": [], "locked_facts": []},
    )
    assert resumed_canon == canon
    assert resumed_confirmed == confirmed
    assert len(calls) == first_window_call_count
    assert any(
        event["event_type"] == "maintenance_window_checkpoint_reused"
        for event in service.db.list_run_events("quality-source")
    )


@pytest.mark.asyncio
async def test_maintenance_window_compacts_fixed_context_before_recursive_split(
    tmp_path,
) -> None:
    """A smallest semantic window must not inherit an unsplittable prompt layer."""

    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="offline", name="Offline", protocol="openai",
        base_url="https://offline.invalid/v1", auth_type="bearer",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="maintenance-small", provider_id="offline",
        display_name="Maintenance Small", model_name="maintenance-small",
        context_window=8_192, max_output_tokens=2_048,
    )
    db.save_role_binding(
        "maintenance", "offline", "maintenance-small", None, None,
    )
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Maintenance fixed context", mode="short", genre="mystery",
        premise="A clerk verifies one surviving fact.", target_words=13_000,
    ))
    skill_root = tmp_path / "skills"
    make_prompt_skills(skill_root)
    gateway = RecordingGateway([json.dumps({
        "version": "maintenance-window-receipt-v1",
        "facts": [], "state_deltas": [], "state_transitions": [],
        "world_rules": [], "timeline": [],
    })])
    service = WorkflowService(
        db, store, expose_test_primary_route(gateway),
        SkillGate(db, SkillScanner([skill_root])),
    )
    project_constraints = project.path / "constraints.md"
    project_constraints.write_text(
        "# Project Constraints\n\n## Must Include\n" + "\n".join(
            f"Advisory archive note {index}: preserve verified authority."
            for index in range(4_000)
        ) + "\n\n## Must Avoid\nNone\n",
        encoding="utf-8",
    )
    run_id = "maintenance-fixed-context"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    splitter_calls = 0

    async def reject_split(_details):
        nonlocal splitter_calls
        splitter_calls += 1
        raise AssertionError("bounded fixed context should fit before splitting prose")

    raw = await service._stage(
        run_id, run_path, project, "maintenance",
        service.projects.load_constraints(project.id),
        json.dumps({
            "schema": "maintenance-window-request-v1",
            "window_text": "One exact sentence.",
        }),
        allow_tools=False,
        route_capacity_guard=True,
        capacity_splitter=reject_split,
        completion_check=lambda value: bool(str(value).strip()),
        bounded_protocol_output=True,
        compact_input=True,
    )

    assert splitter_calls == 0
    assert json.loads(str(raw))["version"] == "maintenance-window-receipt-v1"
    assert len(gateway.calls) == 1
    assert len(gateway.calls[0]["system"]) < 20_000


@pytest.mark.asyncio
async def test_maintenance_capacity_reduces_ordered_state_chain_and_repairs_fact_fork(
    tmp_path, monkeypatch,
) -> None:
    first_state = "她先把身份状态改为已告知。"
    second_state = "随后她把身份状态改为已公开。"
    first_fact = "档案结论是版本甲。"
    conflicting_fact = "档案结论被误写成版本乙。"
    manuscript = "\n\n".join([
        first_state + first_fact + ("首段继续。" * 70),
        "中间状态保持。" + ("中段继续。" * 70),
        second_state + conflicting_fact + ("尾段继续。" * 70),
    ])
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=manuscript, target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"
    repair_calls = 0

    async def capacity_stage(*args, **kwargs):
        nonlocal repair_calls
        prompt = args[5]
        if prompt == manuscript:
            result = await kwargs["capacity_splitter"]({
                "trigger": "preflight", "pressure": "split",
                "context_window": 1800, "output_reserve": 1000,
            })
            return StageText(result, {"execution_mode": "capacity_split"})
        request = json.loads(prompt)
        window_text = request["window_text"]
        repair = request.get("repair")
        if repair:
            repair_calls += 1
            return json.dumps({
                "version": "maintenance-window-receipt-v1",
                "facts": [], "state_deltas": [], "state_transitions": [],
                "world_rules": [], "timeline": [],
            })
        entry = request["entry_authority"]
        knowledge = ((entry.get("character_states") or {}).get("hero") or {}).get(
            "knowledge"
        )
        transitions = []
        if first_state in window_text and knowledge == "hidden":
            transitions.append({
                "character": "hero", "field": "knowledge",
                "from": "hidden", "to": "shared", "evidence": first_state,
            })
        if second_state in window_text and knowledge == "shared":
            transitions.append({
                "character": "hero", "field": "knowledge",
                "from": "shared", "to": "public", "evidence": second_state,
            })
        facts = []
        if first_fact in window_text:
            facts.append({
                "key": "archive.version", "value": "A", "evidence": first_fact,
            })
        if conflicting_fact in window_text:
            facts.append({
                "key": "archive.version", "value": "B",
                "evidence": conflicting_fact,
            })
        return json.dumps({
            "version": "maintenance-window-receipt-v1",
            "facts": facts, "state_deltas": [],
            "state_transitions": transitions,
            "world_rules": [], "timeline": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage_with_role_fallback", capacity_stage)
    state = {
        "confirmed_facts": [], "locked_facts": [],
        "character_states": {"hero": {"knowledge": "hidden", "alive": True}},
    }

    canon, confirmed = await service._close_short_maintenance_authority(
        "quality-source", run_path, project, "constraints", manuscript, state,
    )

    assert repair_calls >= 1
    assert [(item["key"], item["value"]) for item in confirmed] == [
        ("archive.version", "A"),
    ]
    assert canon["state"]["hero"] == {"knowledge": "public", "alive": True}
    reduction = json.loads(next((run_path / "receipts").glob(
        "maintenance-reduction-*.json",
    )).read_text(encoding="utf-8"))
    accepted_values = [
        unit["value"]
        for envelope in reduction["window_envelopes"]
        for unit in envelope["receipt"]["facts"]
    ]
    assert accepted_values == ["A"]
    assert any(
        audit.get("rejected_receipt_sha256")
        for envelope in reduction["window_envelopes"]
        for audit in envelope["adapter_audit"]
    )


@pytest.mark.asyncio
async def test_model_cannot_forge_runtime_maintenance_reduction(
    tmp_path, monkeypatch,
) -> None:
    manuscript = "她保留了最终确认的身份。"
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=manuscript, target_words=500,
    )
    run_path = project.path / "runs" / "quality-source"

    async def forged_stage(*args, **kwargs):
        return json.dumps({
            "version": "maintenance-reduction-v1",
            "manuscript_sha256": hashlib.sha256(
                manuscript.encode("utf-8"),
            ).hexdigest(),
            "source_state_sha256": "0" * 64,
            "window_envelopes": [],
            "window_receipt_sha256": [],
            "coverage_spans": [[0, len(manuscript)]],
            "canon": {"facts": [{"key": "forged", "value": "accepted"}]},
            "confirmed_facts": [],
            "reduction_sha256": "0" * 64,
        })

    monkeypatch.setattr(service, "_stage_with_role_fallback", forged_stage)

    with pytest.raises(ValueError, match="model output cannot claim"):
        await service._close_short_maintenance_authority(
            "quality-source", run_path, project, "constraints", manuscript,
            {"confirmed_facts": [], "locked_facts": []},
        )


@pytest.mark.asyncio
async def test_polish_whole_semantic_failure_restores_accepted_complete_draft(
    tmp_path, monkeypatch,
) -> None:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间。" * 30
        + "她确认记录无误，带着结果离开。" * 20
    )
    polished_candidate = source.replace("逐页核对", "逐页细查", 1)
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source,
    )
    _attach_short_revision_semantic_authority(service, project, source)
    run_path = project.path / "runs" / "quality-source"
    original_assessment = __import__(
        "novel_flywheel.workflows", fromlist=["assess_polish_candidate"],
    ).assess_polish_candidate

    def accept_polished_candidate(*args, **kwargs):
        assessment = original_assessment(*args, **kwargs)
        if len(args) > 1 and args[1] == polished_candidate:
            assessment["accepted"] = True
            assessment["reasons"] = []
            assessment["hard_reasons"] = []
        return assessment

    async def stage(*args, **kwargs):
        prompt = args[5]
        if "DRAFT_SEMANTIC_VALIDATION" in prompt:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", prompt,
            ).group(1))
            prose = prompt.split("PROSE:\n", 1)[1]
            return json.dumps(
                draft_semantic_receipt(contract, prose), ensure_ascii=False,
            )
        assert args[3] == "polish"
        return polished_candidate

    async def fail_candidate_whole(*args, **kwargs):
        raise RuntimeError("provider transport interrupted during whole polish review")

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(
        service, "_verify_whole_draft_semantics", fail_candidate_whole,
    )
    monkeypatch.setattr(
        "novel_flywheel.workflows.assess_polish_candidate",
        accept_polished_candidate,
    )

    result = await service._polish_short_segments(
        "quality-source", run_path, project, "constraints", source, "{}",
    )

    assert result == source
    events = service.db.list_run_events("quality-source")
    restored = next(
        event for event in events
        if event["event_type"] == "polish_whole_semantic_preserved"
    )
    assert restored["metadata"]["rejected_draft_sha256"] == hashlib.sha256(
        polished_candidate.encode("utf-8"),
    ).hexdigest()


@pytest.mark.asyncio
async def test_polish_whole_semantic_failure_keeps_independent_safe_segments(
    tmp_path, monkeypatch,
) -> None:
    source_parts = [
        "林晚在档案馆核对第一份证词，确认时间后留下清楚记录。" * 12,
        "林晚沿着第二条线索追查，保持既定知情范围和人物关系。" * 12,
        "林晚在结尾提交第三份证据，让此前承诺得到完整兑现。" * 12,
    ]
    polished_parts = [
        source_parts[0].replace("核对", "细查", 1),
        source_parts[1].replace("保持", "错误改写", 1),
        source_parts[2].replace("提交", "郑重提交", 1),
    ]
    source = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(source_parts)
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source,
    )
    manifest, _integrity = _attach_multi_segment_polish_semantic_authority(
        service, project, source_parts,
    )
    run_path = project.path / "runs" / "quality-source"
    original_assessment = __import__(
        "novel_flywheel.workflows", fromlist=["assess_polish_candidate"],
    ).assess_polish_candidate

    def accept_polished_candidate(*args, **kwargs):
        assessment = original_assessment(*args, **kwargs)
        if len(args) > 1 and args[1] in polished_parts:
            assessment["accepted"] = True
            assessment["reasons"] = []
            assessment["hard_reasons"] = []
        return assessment

    async def stage(*args, **kwargs):
        prompt = args[5]
        if "DRAFT_SEMANTIC_VALIDATION" in prompt:
            contract = json.loads(re.search(
                r"TASK CONTRACT: (\{[^\n]+\})", prompt,
            ).group(1))
            prose = prompt.split("PROSE:\n", 1)[1]
            return json.dumps(
                draft_semantic_receipt(contract, prose), ensure_ascii=False,
            )
        assert args[3] == "polish"
        prose = prompt.rsplit("MANUSCRIPT SEGMENT:\n", 1)[1]
        return polished_parts[source_parts.index(prose)]

    whole_trials: list[tuple[bool, bool, bool]] = []

    async def whole_semantics(
        _run_id, _run_path, _project, _constraints, authority_sha256,
        draft, segments, expected_event_ids, segment_receipts, **kwargs,
    ):
        state = tuple(
            segment == polished_parts[index]
            for index, segment in enumerate(segments)
        )
        whole_trials.append(state)
        if state[1]:
            raise ValueError("第二段润色与整篇因果冲突")
        return {
            "authority_sha256": authority_sha256,
            "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "segment_sha256": [
                hashlib.sha256(segment.encode("utf-8")).hexdigest()
                for segment in segments
            ],
            "event_ids": expected_event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": True,
            "evidence": [{"excerpt": draft[:12]}],
            "summary": "保留组合通过整篇语义核对。",
        }

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(service, "_verify_whole_draft_semantics", whole_semantics)
    monkeypatch.setattr(
        "novel_flywheel.workflows.assess_polish_candidate",
        accept_polished_candidate,
    )

    result = await service._polish_short_segments(
        "quality-source", run_path, project, "constraints", source, "{}",
    )

    assert service._split_segments(result) == [
        polished_parts[0], source_parts[1], polished_parts[2],
    ]
    assert whole_trials[0] == (True, True, True)
    assert (True, False, True) in whole_trials
    restored = next(
        event for event in service.db.list_run_events("quality-source")
        if event["event_type"] == "polish_semantic_subset_restored"
    )
    assert restored["metadata"]["retained_segments"] == [1, 3]
    assert restored["metadata"]["rejected_segments"] == [2]
    checkpoint = json.loads((
        run_path / "outputs" / "polish-checkpoints" / "initial" / "part-02.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["accepted"] is False
    assert checkpoint["status"] == "whole_semantic_conflict_preserved"


@pytest.mark.asyncio
async def test_polish_subset_recovery_handles_multiple_conflicts_linearly(
    tmp_path, monkeypatch,
) -> None:
    source_parts = [
        f"第{index}段原文保持正式事件、人物状态和交接。" * 14
        for index in range(1, 5)
    ]
    candidate_parts = [
        part.replace("原文", f"润色{index}", 1)
        for index, part in enumerate(source_parts, 1)
    ]
    source = WorkflowService.SHORT_SEGMENT_SEPARATOR.join(source_parts)
    service, project, _source, _ledger, _state = _short_revision_service(
        tmp_path, [], source=source,
    )
    manifest, integrity = _attach_multi_segment_polish_semantic_authority(
        service, project, source_parts,
    )
    run_path = project.path / "runs" / "quality-source"
    candidate_receipts = []
    for index, (candidate, manifest_segment) in enumerate(
        zip(candidate_parts, manifest.segments, strict=True), 1,
    ):
        contract = service._manifest_segment_contract(
            project, manifest, integrity, manifest_segment, candidate, index,
        )
        candidate_receipts.append(
            draft_semantic_receipt(asdict(contract), candidate)
        )
    trials: list[tuple[bool, bool, bool, bool]] = []

    async def whole_semantics(
        _run_id, _run_path, _project, _constraints, authority_sha256,
        draft, segments, expected_event_ids, segment_receipts, **kwargs,
    ):
        state = tuple(
            segment == candidate_parts[index]
            for index, segment in enumerate(segments)
        )
        trials.append(state)
        if state[1] or state[3]:
            raise ValueError("第二或第四段与整篇因果冲突")
        return {
            "authority_sha256": authority_sha256,
            "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "segment_sha256": [
                hashlib.sha256(segment.encode("utf-8")).hexdigest()
                for segment in segments
            ],
            "event_ids": expected_event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": True,
            "evidence": [{"excerpt": draft[:12]}],
            "summary": "安全润色组合通过。",
        }

    monkeypatch.setattr(service, "_verify_whole_draft_semantics", whole_semantics)
    recovered = await service._recover_polish_semantic_subset(
        "quality-source", run_path, project, "constraints",
        source, source_parts, candidate_parts, manifest, integrity,
        candidate_receipts, integrity["semantic_segment_receipts"],
        integrity["whole_semantic_receipt"],
        [beat_id for segment in manifest.segments for beat_id in segment.beat_ids],
    )

    assert recovered["retained_segments"] == [1, 3]
    assert recovered["rejected_segments"] == [2, 4]
    assert recovered["parts"] == [
        candidate_parts[0], source_parts[1], candidate_parts[2], source_parts[3],
    ]
    assert (True, False, True, False) in trials
    assert len(trials) <= len(source_parts) * 2


@pytest.mark.asyncio
async def test_structural_revision_check_failure_restores_pre_revision_candidate(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Structural restore", mode="short", genre="suspense",
        premise="A clue must remain explicit.", target_words=2000,
    ))
    service = WorkflowService(
        db, store, FakeGateway(), SkillGate(db, SkillScanner([])),
    )
    run_id = "structural-restore"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    source = WorkflowService.SHORT_SEGMENT_SEPARATOR.join([
        "林晚检查档案。" * 80 + "必须保留的关键线索。",
        "林晚带着结论离开。" * 80,
    ])
    changed = source.replace("必须保留的关键线索。", "", 1)
    plan = {
        "global_facts": [],
        "checks": [{
            "kind": "required_text",
            "value": "必须保留的关键线索",
            "issue_ids": ["issue-1"],
        }],
        "tasks": [{
            "segments": [1],
            "instruction": "补强关键线索",
            "issue_ids": ["issue-1"],
        }],
    }
    original_assessment = __import__(
        "novel_flywheel.workflows", fromlist=["assess_polish_candidate"],
    ).assess_polish_candidate

    def accept_changed(*args, **kwargs):
        assessment = original_assessment(*args, **kwargs)
        assessment["accepted"] = True
        assessment["reasons"] = []
        assessment["hard_reasons"] = []
        return assessment

    async def stage(*args, **kwargs):
        assert args[3] == "polish"
        return changed.split(WorkflowService.SHORT_SEGMENT_SEPARATOR)[0]

    monkeypatch.setattr(service, "_stage", stage)
    monkeypatch.setattr(
        "novel_flywheel.workflows.assess_polish_candidate", accept_changed,
    )

    result = await service._polish_short_segments(
        run_id, run_path, project, "constraints", source, "{}",
        structural=True, prepared_revision_plan=plan,
    )

    assert result == source
    assert any(
        event["event_type"] == "revision_checks_preserved"
        for event in db.list_run_events(run_id)
    )


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
    assert rejected_event["metadata"]["group_id"] == issue_id
    assert rejected_event["metadata"]["category"] == "contract_validation"
    assert rejected_event["metadata"]["error"]
    assert model_output not in rejected_event["message"]
    assert "short_revision_contract_retry" in event_types
    assert "short_revision_group_rejected" in event_types
    assert "short_revision_group_failed" not in event_types


@pytest.mark.asyncio
async def test_short_revision_contract_retry_recovers_control_aliases_only(
    tmp_path, monkeypatch,
) -> None:
    service, project, source, ledger, _state = _short_revision_service(
        tmp_path, [{
            "category": "logic_continuity",
            "severity": "medium",
            "evidence": "甲问题原句。",
            "action": "修复甲问题。",
        }],
    )
    issue_id = ledger[0]["issue_id"]
    calls = 0

    async def contract(*args, **kwargs):
        nonlocal calls
        calls += 1
        request = json.loads(args[5])
        if calls == 1:
            return json.dumps({"groups": []})
        assert "protocol_repair" in request
        value = json.loads(_short_revision_patch(
            request, "甲问题原句。", "甲问题说明。",
        ))
        value["groups"][0]["kind"] = "语义修复"
        value["groups"][0]["patches"][0]["operation"] = "替换"
        return json.dumps(value, ensure_ascii=False)

    monkeypatch.setattr(service, "_stage", contract)
    result = await service.run_short_revision(
        project.id, [issue_id], run_id="repair-contract-recovery",
    )

    assert calls == 2
    assert result["status"] == "waiting_confirmation"
    assert result["candidate"] == source.replace("甲问题原句。", "甲问题说明。")
    records = json.loads((
        project.path / "runs" / "repair-contract-recovery"
        / "outputs" / "patch-groups.json"
    ).read_text(encoding="utf-8"))["groups"]
    group = records[0]["patch_group"]
    assert group["kind"] == "semantic"
    assert group["raw_kind"] == "语义修复"
    assert group["patches"][0]["operation"] == "replace"
    assert group["patches"][0]["raw_operation"] == "替换"


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
