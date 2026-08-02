from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.execution_manifest import (
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.workflows import WorkflowService


EVENT_ID = "EV-8E4BBA17"


def manifest_body(*, conflicting_owner: bool) -> dict:
    dispatch_owner = 2 if conflicting_owner else 1
    segment_one_beats = [] if conflicting_owner else [f"{EVENT_ID}/01"]
    segment_two_beats = (
        [f"{EVENT_ID}/01", f"{EVENT_ID}/02"]
        if conflicting_owner else [f"{EVENT_ID}/02"]
    )
    return {
        "beats": [
            {
                "beat_id": f"{EVENT_ID}/01",
                "source_event_id": EVENT_ID,
                "order": 1,
                "action": "沈老夫人派人外出核实花穗身份",
                "preconditions": ["裴砚行提出核实身份"],
                "postconditions": ["核实身份的人已经出发"],
                "owner_segment": dispatch_owner,
                "source_evidence": "沈老夫人派人外出核实花穗身份",
            },
            {
                "beat_id": f"{EVENT_ID}/02",
                "source_event_id": EVENT_ID,
                "order": 2,
                "action": "花穗发现二十两在她入府前已经支出",
                "preconditions": ["核实身份的人已经出发"],
                "postconditions": ["花穗确认误认是人为安排"],
                "owner_segment": 2,
                "source_evidence": "花穗发现二十两在她入府前已经支出",
            },
        ],
        "segments": [
            {
                "segment": 1,
                "beat_ids": segment_one_beats,
                "entry_state": [{"state": "裴砚行正在沈府核实花穗身份"}],
                "exit_state": [{
                    "state": "核实身份的人已经出发",
                    "produced_by": f"{EVENT_ID}/01",
                }],
                "previous_exit_sha256": "",
                "prohibited_future_beat_ids": [f"{EVENT_ID}/02"],
            },
            {
                "segment": 2,
                "beat_ids": segment_two_beats,
                "entry_state": [{
                    "state": "核实身份的人已经出发",
                    "inherited_from": "segment-01",
                }],
                "exit_state": [{
                    "state": "花穗确认误认是人为安排",
                    "produced_by": f"{EVENT_ID}/02",
                }],
                "previous_exit_sha256": "a" * 64,
                "prohibited_future_beat_ids": [],
            },
        ],
    }


def make_service(tmp_path: Path) -> tuple[WorkflowService, object, Path, dict]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Atomic manifest", mode="short", genre="suspense",
        premise="A mistaken identity is investigated.", target_words=6000,
    ))
    service = WorkflowService(db, store, SimpleNamespace(), SimpleNamespace())
    run_id = "manifest-run"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    state = {
        "outline": {
            "content": (
                "沈老夫人派人外出核实花穗身份。\n"
                "花穗发现二十两在她入府前已经支出。"
            ),
        },
    }
    return service, project, run_path, state


def receipt_for_prompt(prompt: str) -> str:
    raw_manifest = prompt.split("EXECUTION MANIFEST:\n", 1)[1].split(
        "\n\nAUTHORITY TEXT:\n", 1,
    )[0]
    manifest = parse_execution_manifest(json.loads(raw_manifest))
    receipt = {
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": [{
            "beat_id": beat.beat_id,
            "evidence": beat.source_evidence,
            "actor_action_valid": True,
        } for beat in manifest.beats],
        "segment_receipts": [{
            "segment": segment.segment,
            "boundary_valid": True,
            "evidence": segment.exit_state[0].state,
        } for segment in manifest.segments],
        "formal_plot_unchanged": True,
        "summary": "事件动作、所有权和相邻边界均符合正式资料。",
    }
    return json.dumps(receipt, ensure_ascii=False)


@pytest.mark.asyncio
async def test_execution_manifest_repairs_owner_conflict_before_draft(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)
    planning = iter([
        json.dumps(manifest_body(conflicting_owner=True), ensure_ascii=False),
        json.dumps(manifest_body(conflicting_owner=False), ensure_ascii=False),
    ])
    calls = []

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls.append((stage, prompt))
        if stage == "review":
            return receipt_for_prompt(prompt)
        return next(planning)

    service._stage = fake_stage
    manifest = await service._ensure_short_execution_manifest(
        "manifest-run", run_path, project, "constraints", 7, state,
        (
            "### 第 1 段：核实\n段末交接：核实身份的人已经出发\n\n"
            "### 第 2 段：账房\n段末交接：花穗确认误认是人为安排"
        ),
        {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排"},
        [{
            "id": EVENT_ID, "order": 1, "label": "误认身份被核实",
            "section": "第一章", "kind": "narrative",
        }],
        2,
    )

    saved = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(
            encoding="utf-8",
        )
    )
    assert manifest.version == saved["version"] == 2
    assert manifest.repair_attempts == saved["repair_attempts"] == 1
    assert saved["status"] == "ready"
    assert saved["semantic_receipt"]["formal_plot_unchanged"] is True
    assert [stage for stage, _prompt in calls] == ["planning", "planning", "review"]
    events = service.db.list_run_events("manifest-run")
    assert any(item["event_type"] == "planning_manifest_conflict" for item in events)
    assert any(item["event_type"] == "planning_manifest_ready" for item in events)


@pytest.mark.asyncio
async def test_execution_manifest_stops_after_two_failed_repairs(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)

    async def always_conflicting(*args, **kwargs):
        assert args[3] == "planning"
        return json.dumps(manifest_body(conflicting_owner=True), ensure_ascii=False)

    service._stage = always_conflicting
    outline_before = json.dumps(state["outline"], ensure_ascii=False, sort_keys=True)

    with pytest.raises(ValueError, match="执行索引未通过"):
        await service._ensure_short_execution_manifest(
            "manifest-run", run_path, project, "constraints", 7, state,
            (
                "### 第 1 段：核实\n段末交接：核实身份的人已经出发\n\n"
                "### 第 2 段：账房\n段末交接：花穗确认误认是人为安排"
            ),
            {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排"},
            [{
                "id": EVENT_ID, "order": 1, "label": "误认身份被核实",
                "section": "第一章", "kind": "narrative",
            }],
            2,
        )

    assert json.dumps(state["outline"], ensure_ascii=False, sort_keys=True) == outline_before
    saved = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(
            encoding="utf-8",
        )
    )
    assert saved["status"] == "failed"
    assert saved["repair_attempts"] == 2
    assert not saved.get("semantic_receipt")
    assert len([
        item for item in service.db.list_run_events("manifest-run")
        if item["event_type"] == "planning_manifest_repair"
    ]) == 2
