from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.execution_manifest import (
    StateAssertion,
    execution_manifest_sha256,
    parse_execution_manifest,
    state_assertions_sha256,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.workflows import WorkflowService


EVENT_ID = "EV-8E4BBA17"


def manifest_body(segment: int, *, conflicting_owner: bool = False) -> dict:
    if segment == 1:
        action = "沈老夫人派人外出核实花穗身份"
        preconditions = ["裴砚行提出核实身份"]
        postconditions = ["核实身份的人已经出发"]
        evidence = "沈老夫人派人外出核实花穗身份"
        entry_state = [{"state": "裴砚行正在沈府核实花穗身份"}]
        exit_state = [{
            "state": "核实身份的人已经出发",
            "produced_by": f"{EVENT_ID}/01",
        }]
    else:
        action = "花穗发现二十两在她入府前已经支出"
        preconditions = ["核实身份的人已经出发"]
        postconditions = ["花穗确认误认是人为安排"]
        evidence = "花穗发现二十两在她入府前已经支出"
        entry_state = [{
            "state": "核实身份的人已经出发",
            "inherited_from": "segment-01",
        }]
        exit_state = [{
            "state": "花穗确认误认是人为安排",
            "produced_by": f"{EVENT_ID}/01",
        }]
    owner = segment + 1 if conflicting_owner else segment
    return {
        "beats": [{
            "beat_id": f"{EVENT_ID}/01",
            "source_event_id": EVENT_ID,
            "order": 1,
            "presentation_order": 1,
            "action": action,
            "preconditions": preconditions,
            "postconditions": postconditions,
            "owner_segment": owner,
            "source_evidence": evidence,
        }],
        "segments": [{
            "segment": segment,
            "beat_ids": [] if conflicting_owner else [f"{EVENT_ID}/01"],
            "entry_state": entry_state,
            "exit_state": exit_state,
            "previous_exit_sha256": "",
            "prohibited_future_beat_ids": [],
        }],
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


def test_execution_authority_preserves_accepted_plan_event_ids_without_outline(
    tmp_path,
) -> None:
    service, project, _run_path, _state = make_service(tmp_path)
    plan = (
        "### 第 1 段：抵达\n事件ID：EV-00000001\n段末交接：进入空间站\n\n"
        "### 第 2 段：接管\n事件ID：EV-00000002\n段末交接：系统封锁气闸"
    )

    _hashes, _authority, events = service._short_execution_authority(
        project, 1, {"outline": {"content": ""}}, "constraints", plan,
        {"core_goal": "解除封锁", "ending": "乘员恢复控制"}, [], 2,
    )

    assert [item["id"] for item in events] == [
        "EV-00000001", "EV-00000002",
    ]
    assert all(item["source"] == "accepted_plan_fallback" for item in events)


@pytest.mark.asyncio
async def test_execution_manifest_repairs_owner_conflict_before_draft(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)
    first_segment_calls = 0
    calls = []

    async def fake_stage(*args, **kwargs):
        nonlocal first_segment_calls
        stage = args[3]
        prompt = args[5]
        calls.append((stage, prompt))
        if stage == "review":
            return receipt_for_prompt(prompt)
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        if segment == 1:
            first_segment_calls += 1
        return json.dumps(manifest_body(
            segment, conflicting_owner=segment == 1 and first_segment_calls == 1,
        ), ensure_ascii=False)

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
    assert manifest.version == saved["version"] == 4
    assert manifest.repair_attempts == saved["repair_attempts"] == 1
    assert saved["status"] == "ready"
    assert saved["semantic_receipt"]["formal_plot_unchanged"] is True
    assert [stage for stage, _prompt in calls] == [
        "planning", "planning", "review", "planning", "review",
    ]
    events = service.db.list_run_events("manifest-run")
    assert any(
        item["event_type"] == "planning_manifest_fragment_repair"
        for item in events
    )
    assert any(item["event_type"] == "planning_manifest_ready" for item in events)


@pytest.mark.asyncio
async def test_execution_manifest_stops_after_two_failed_repairs(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)

    async def always_conflicting(*args, **kwargs):
        assert args[3] == "planning"
        prompt = args[5]
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        return json.dumps(
            manifest_body(segment, conflicting_owner=True), ensure_ascii=False,
        )

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
        if item["event_type"] == "planning_manifest_fragment_repair"
    ]) == 2


@pytest.mark.asyncio
async def test_semantic_failure_gets_independent_minimal_repair_budget(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)
    review_calls = 0
    stages = []

    async def fake_stage(*args, **kwargs):
        nonlocal review_calls
        stage = args[3]
        prompt = args[5]
        stages.append(stage)
        if stage == "planning":
            segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
            return json.dumps(manifest_body(segment), ensure_ascii=False)
        review_calls += 1
        receipt = json.loads(receipt_for_prompt(prompt))
        if review_calls == 1:
            receipt["beat_receipts"][0]["actor_action_valid"] = False
        return json.dumps(receipt, ensure_ascii=False)

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

    assert manifest.repair_attempts == 1
    assert stages == [
        "planning", "review", "planning", "review", "planning", "review",
    ]


@pytest.mark.asyncio
async def test_semantic_failure_stops_after_minimal_and_full_segment_rebuild(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)
    calls = {"planning": 0, "review": 0}

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls[stage] += 1
        if stage == "planning":
            segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
            return json.dumps(manifest_body(segment), ensure_ascii=False)
        receipt = json.loads(receipt_for_prompt(prompt))
        receipt["beat_receipts"][0]["actor_action_valid"] = False
        return json.dumps(receipt, ensure_ascii=False)

    service._stage = fake_stage
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

    saved = json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(
            encoding="utf-8",
        )
    )
    assert calls == {"planning": 3, "review": 3}
    assert saved["repair_budgets"]["semantic_repairs"] == 2
    assert saved["repair_budgets"]["schema_repairs"] == 0
    assert saved["repair_budgets"]["integrity_repairs"] == 0


@pytest.mark.asyncio
async def test_formatted_receipt_evidence_is_bound_without_manifest_rebuild(
    tmp_path,
) -> None:
    service, project, run_path, state = make_service(tmp_path)
    calls = {"planning": 0, "review": 0}

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls[stage] += 1
        if stage == "planning":
            return json.dumps(manifest_body(1), ensure_ascii=False)
        receipt = json.loads(receipt_for_prompt(prompt))
        receipt["beat_receipts"][0]["evidence"] = "审核模型复述的节拍证据"
        receipt["segment_receipts"][0].update({
            "evidence": "段末交接：\n- 核实身份的人已经出发",
        })
        return json.dumps(receipt, ensure_ascii=False)

    service._stage = fake_stage
    manifest = await service._ensure_short_execution_manifest(
        "manifest-run", run_path, project, "constraints", 7, state,
        "### 第 1 段：核实\n**段末交接**：核实身份的人已经出发",
        {"core_goal": "查清误认", "ending": "核实身份的人已经出发"},
        [{
            "id": EVENT_ID, "order": 1, "label": "误认身份被核实",
            "section": "第一章", "kind": "narrative",
        }],
        1,
    )

    assert manifest.status == "ready"
    assert calls == {"planning": 1, "review": 1}
    assert manifest.semantic_receipt["beat_receipts"][0]["evidence"] == (
        "沈老夫人派人外出核实花穗身份"
    )
    assert manifest.semantic_receipt["segment_receipts"][0]["evidence"] == (
        "**段末交接**：核实身份的人已经出发"
    )
    assert not any(
        item["event_type"] == "planning_manifest_fragment_repair"
        for item in service.db.list_run_events("manifest-run")
    )


@pytest.mark.asyncio
async def test_unbound_receipt_exhaustion_preserves_content_without_rebuild(
    tmp_path,
) -> None:
    service, project, run_path, state = make_service(tmp_path)
    calls = {"planning": 0, "review": 0}

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls[stage] += 1
        if stage == "planning":
            segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
            return json.dumps(manifest_body(segment), ensure_ascii=False)
        receipt = json.loads(receipt_for_prompt(prompt))
        if receipt["segment_receipts"][0]["segment"] == 2:
            receipt["segment_receipts"][0].update({
                "evidence": "权威资料中不存在的边界证据",
            })
        return json.dumps(receipt, ensure_ascii=False)

    service._stage = fake_stage
    with pytest.raises(ValueError, match="审核回执未通过"):
        await service._ensure_short_execution_manifest(
            "manifest-run", run_path, project, "constraints", 7, state,
            (
                "### 第 1 段：核实\n**段末交接**：核实身份的人已经出发\n\n"
                "### 第 2 段：账房\n**段末交接**：花穗确认误认是人为安排"
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
    assert calls == {"planning": 2, "review": 4}
    assert saved["content_status"] == "content_valid"
    assert saved["receipt_status"] == "failed"
    assert saved["repair_budgets"]["semantic_repairs"] == 0
    assert len(saved["beats"]) == 2
    assert [item["segment"] for item in saved["segments"]] == [1, 2]
    events = service.db.list_run_events("manifest-run")
    assert len([
        item for item in events
        if item["event_type"] == "planning_manifest_receipt_protocol_retry"
    ]) == 2
    assert any(
        item["event_type"] == "planning_manifest_receipt_failed"
        for item in events
    )
    assert not any(
        item["event_type"] == "planning_manifest_fragment_repair"
        for item in events
    )


@pytest.mark.asyncio
async def test_semantic_repair_reentering_schema_failure_recovers_before_ready(
    tmp_path,
) -> None:
    service, project, run_path, state = make_service(tmp_path)
    calls = {"planning": 0, "review": 0}
    initial_review_failed = False

    async def fake_stage(*args, **kwargs):
        nonlocal initial_review_failed
        stage = args[3]
        prompt = args[5]
        calls[stage] += 1
        if stage == "review":
            receipt = json.loads(receipt_for_prompt(prompt))
            if not initial_review_failed:
                initial_review_failed = True
                receipt["beat_receipts"][0]["actor_action_valid"] = False
            return json.dumps(receipt, ensure_ascii=False)

        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        body = manifest_body(segment)
        if (
            segment == 1
            and "SEMANTIC REPAIR DIRECTIVE:" in prompt
            and "LOCAL REPAIR ISSUES" not in prompt
        ):
            body["segments"][0]["exit_state"][0]["produced_by"] = (
                "narrative_overview"
            )
        return json.dumps(body, ensure_ascii=False)

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
    assert manifest.status == saved["status"] == "ready"
    assert saved["version"] == 4
    assert saved["repair_attempts"] == 2
    assert saved["segments"][0]["exit_state"][0]["produced_by"] == [
        f"{EVENT_ID}/01",
    ]
    assert calls == {"planning": 4, "review": 3}
    events = service.db.list_run_events("manifest-run")
    assert any(
        item["event_type"] == "planning_manifest_fragment_repair"
        and item["metadata"].get("repair_mode") == "minimal_patch"
        and item["metadata"].get("schema_repairs") == 1
        for item in events
    )
    assert any(item["event_type"] == "planning_manifest_ready" for item in events)


@pytest.mark.asyncio
async def test_runtime_binds_exact_previous_exit_when_model_paraphrases_handoff(
    tmp_path,
) -> None:
    service, project, run_path, state = make_service(tmp_path)
    calls = {"planning": 0, "review": 0}

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls[stage] += 1
        if stage == "review":
            return receipt_for_prompt(prompt)
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        body = manifest_body(segment)
        if segment == 2:
            body["segments"][0]["entry_state"] = [{
                "state": "调查人员已经动身去核对相关情况",
                "inherited_from": "segment-01",
            }]
        return json.dumps(body, ensure_ascii=False)

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

    first, second = manifest.segments
    assert {item.state for item in first.exit_state} <= {
        item.state for item in second.entry_state
    }
    assert second.previous_exit_sha256 == state_assertions_sha256(
        first.exit_state, version=4,
    )
    assert calls == {"planning": 2, "review": 2}
    events = service.db.list_run_events("manifest-run")
    handoff_events = [
        item for item in events
        if item["event_type"] == "planning_manifest_runtime_handoff_bound"
    ]
    assert len(handoff_events) == 1
    assert handoff_events[0]["metadata"]["added_state_count"] == 1
    assert "source_body_sha256" in handoff_events[0]["metadata"]
    assert "bound_body_sha256" in handoff_events[0]["metadata"]
    assert not any(
        item["event_type"] == "planning_manifest_fragment_repair"
        for item in events
    )


def test_runtime_handoff_binding_does_not_normalize_malformed_entry_state() -> None:
    previous_exit = (StateAssertion(
        state="上一段已经验收的出口状态",
        produced_by=(f"{EVENT_ID}/01",),
    ),)
    body = manifest_body(2)
    body["segments"][0]["entry_state"] = "not-a-list"

    bound, added = WorkflowService._bind_short_execution_fragment_handoff(
        body, previous_exit=previous_exit,
    )

    assert added == 0
    assert bound["segments"][0]["entry_state"] == "not-a-list"
    assert bound["segments"][0]["previous_exit_sha256"] == (
        state_assertions_sha256(previous_exit, version=4)
    )
    with pytest.raises(ValueError, match="entry_state must be a non-empty list"):
        parse_execution_manifest({
            **bound,
            "version": 4,
            "status": "fragment_ready",
            "authority_sha256": "a" * 64,
            "outline_sha256": "b" * 64,
            "planning_sha256": "c" * 64,
            "causal_chain_sha256": "d" * 64,
            "semantic_receipt": {},
        })


@pytest.mark.asyncio
async def test_draft_semantic_evidence_retry_keeps_prose_immutable(tmp_path) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    prose = "沈老夫人派人外出核实花穗身份，核实身份的人已经出发。"
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01",
        parent_task_id="manifest-run",
        depth=0,
        target_han=30,
        event_ids=(EVENT_ID,),
        scope="核实身份",
        entry_state="沈老夫人决定核实身份",
        exit_requirement="核实身份的人已经出发",
        execution_manifest_sha256="b" * 64,
        beat_ids=(f"{EVENT_ID}/01",),
        viewpoint="",
        prohibited_future_beat_ids=(),
    )
    calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        evidence = "沈老夫人派人外出核实花穗身份"
        exit_evidence = "核实身份的人已经出发"
        payload = {
            "authority_sha256": contract.authority_sha256,
            "execution_manifest_sha256": contract.execution_manifest_sha256,
            "task_id": contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
            "beat_receipts": [{
                "beat_id": f"{EVENT_ID}/01",
                "evidence": evidence,
                "actor_action_valid": True,
                "actor_action_evidence": evidence,
                "state_valid": True,
                "state_evidence": exit_evidence,
                "scene_order_valid": True,
                "scene_order_evidence": evidence,
            }],
            "outside_beat_ids": [],
            "future_beat_ids": [],
            "entry": {"satisfied": True, "evidence": evidence},
            "exit": {"satisfied": True, "evidence": exit_evidence},
            "causal_order_valid": True,
            "causal_order_evidence": evidence,
            "summary": "当前正文满足原子节拍合同。",
        }
        if calls == 1:
            payload["beat_receipts"][0]["actor_action_evidence"] = (
                "审核模型误写了正文中不存在的证据"
            )
        return json.dumps(payload, ensure_ascii=False)

    service._stage = fake_stage
    receipt = await service._verify_draft_semantic_node(
        "manifest-run", run_path, project, "constraints", contract, prose, [],
        suffix="-protocol", failure_stage="draft",
    )

    assert calls == 2
    assert receipt["prose_sha256"] == hashlib.sha256(prose.encode("utf-8")).hexdigest()
    events = service.db.list_run_events("manifest-run")
    assert any(
        item["event_type"] == "semantic_receipt_protocol_retry"
        for item in events
    )


@pytest.mark.asyncio
async def test_draft_semantic_unique_extract_alignment_avoids_model_retry(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    prose = (
        "沈老夫人派人外出核实花穗身份，核实身份的人已经出发。"
        "花穗留在前厅等待回报，没有提前追查后续账目。"
    )
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01",
        parent_task_id="manifest-run",
        depth=0,
        target_han=60,
        event_ids=(EVENT_ID,),
        scope="核实身份",
        entry_state="沈老夫人决定核实身份",
        exit_requirement="核实身份的人已经出发",
        execution_manifest_sha256="b" * 64,
        beat_ids=(f"{EVENT_ID}/01",),
        viewpoint="",
        prohibited_future_beat_ids=(),
    )
    calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        joined = "沈老夫人派人外出核实花穗身份……核实身份的人已经出发"
        return json.dumps({
            "authority_sha256": contract.authority_sha256,
            "execution_manifest_sha256": contract.execution_manifest_sha256,
            "task_id": contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
            "beat_receipts": [{
                "beat_id": f"{EVENT_ID}/01", "evidence": joined,
                "actor_action_valid": True, "actor_action_evidence": joined,
                "state_valid": True, "state_evidence": "核实身份的人已经出发",
                "scene_order_valid": True, "scene_order_evidence": joined,
            }],
            "outside_beat_ids": [], "future_beat_ids": [],
            "entry": {"satisfied": True, "evidence": joined},
            "exit": {"satisfied": True, "evidence": joined},
            "causal_order_valid": True, "causal_order_evidence": joined,
            "summary": "",
        }, ensure_ascii=False)

    service._stage = fake_stage
    receipt = await service._verify_draft_semantic_node(
        "manifest-run", run_path, project, "constraints", contract, prose, [],
        suffix="-local-alignment", failure_stage="draft",
    )

    assert calls == 1
    assert receipt["summary"]
    events = service.db.list_run_events("manifest-run")
    assert any(
        item["event_type"] == "semantic_receipt_evidence_aligned"
        for item in events
    )
    assert not any(
        item["event_type"] == "semantic_receipt_protocol_retry"
        for item in events
    )


@pytest.mark.asyncio
async def test_whole_draft_semantic_protocol_retry_keeps_draft_immutable(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = [
        "沈老夫人派人外出核实花穗身份，核实身份的人已经出发。",
        "花穗查到二十两早已支出，确认误认是人为安排。",
    ]
    draft = "\n\n".join(segments)
    authority_sha256 = "a" * 64
    event_ids = [EVENT_ID, "EV-8E4BBA18"]
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    segment_sha256 = [
        hashlib.sha256(segment.encode("utf-8")).hexdigest()
        for segment in segments
    ]
    calls = 0
    prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        prompts.append(args[5])
        if calls == 1:
            return "not json"
        return json.dumps({
            "authority_sha256": authority_sha256,
            "draft_sha256": draft_sha256,
            "segment_sha256": segment_sha256,
            "event_ids": event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": True,
            "evidence": [{
                "kind": "causal_transition",
                "excerpt": "核实身份的人已经出发",
            }, {
                "kind": "ending",
                "excerpt": "确认误认是人为安排",
            }],
            "summary": "整篇事件顺序、因果、连续性和结局均有正文证据。",
        }, ensure_ascii=False)

    service._stage = fake_stage
    receipt = await service._verify_whole_draft_semantics(
        "manifest-run", run_path, project, "constraints", authority_sha256,
        draft, segments, event_ids, [{}, {}], failure_stage="draft",
    )

    assert calls == 2
    assert receipt["draft_sha256"] == draft_sha256
    assert receipt["segment_sha256"] == segment_sha256
    assert draft in "\n".join(prompts)
    assert "WHOLE RECEIPT PROTOCOL ISSUES" in prompts[1]
    events = service.db.list_run_events("manifest-run")
    retry = next(
        item for item in events
        if item["event_type"] == "whole_semantic_receipt_protocol_retry"
    )
    assert retry["metadata"]["draft_sha256"] == draft_sha256


@pytest.mark.asyncio
async def test_whole_semantic_capacity_uses_adjacent_windows_and_reducer(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = [
        "花穗在前厅接过旧账本并核对第一枚印章。",
        "她沿着支出记录找到管事并确认银两已经支出。",
        "管事交出凭据，花穗据此确认误认是人为安排。",
    ]
    draft = "\n\n".join(segments)
    authority = "a" * 64
    event_ids = ["EV-00000001", "EV-00000002", "EV-00000003"]
    segment_receipts = []
    for index, (segment, event_id) in enumerate(zip(segments, event_ids), 1):
        segment_receipts.append({
            "prose_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
            "event_receipts": [{"event_id": event_id, "evidence": segment}],
            "entry": {"satisfied": True, "evidence": segment},
            "exit": {"satisfied": True, "evidence": segment},
            "causal_order_evidence": segment,
            "summary": f"segment {index} passed",
        })
    direct_calls = 0
    window_calls = 0
    reducer_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal direct_calls, window_calls, reducer_calls
        prompt = args[5]
        if prompt.startswith("DRAFT_WHOLE_SEMANTIC_VALIDATION"):
            direct_calls += 1
            return await kwargs["capacity_splitter"]({
                "trigger": "preflight", "pressure": "split",
            })
        if prompt.startswith("DRAFT_WHOLE_SEMANTIC_WINDOW_V1"):
            window_calls += 1
            numbers = json.loads(re.search(
                r"SEGMENT NUMBERS: (\[[^\n]+\])", prompt,
            ).group(1))
            hashes = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
            ).group(1))
            owned = json.loads(re.search(
                r"EVENT IDS: (\[[^\n]+\])", prompt,
            ).group(1))
            excerpt = segments[numbers[0] - 1]
            return json.dumps({
                "authority_sha256": authority,
                "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
                "segment_numbers": numbers, "segment_sha256": hashes,
                "event_ids": owned, "missing_event_ids": [],
                "duplicate_event_ids": [], "out_of_order_event_ids": [],
                "causal_order_valid": True, "continuity_valid": True,
                "commitment_flow_valid": True, "ending_valid": True,
                "evidence": [{"kind": "window", "excerpt": excerpt}],
                "summary": "Adjacent window passed.",
            }, ensure_ascii=False)
        assert prompt.startswith("DRAFT_WHOLE_SEMANTIC_REDUCE_V1")
        reducer_calls += 1
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "segment_sha256": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in segments
            ],
            "event_ids": event_ids, "missing_event_ids": [],
            "duplicate_event_ids": [], "out_of_order_event_ids": [],
            "causal_order_valid": True, "continuity_valid": True,
            "ending_valid": True, "commitments_valid": True,
            "evidence": [
                {"kind": "opening", "excerpt": segments[0]},
                {"kind": "ending", "excerpt": segments[-1]},
            ],
            "summary": "All windows reduce to one valid story.",
        }, ensure_ascii=False)

    service._stage = fake_stage
    receipt = await service._verify_whole_draft_semantics(
        "manifest-run", run_path, project, "constraints", authority,
        draft, segments, event_ids, segment_receipts,
    )

    assert receipt["event_ids"] == event_ids
    assert direct_calls == 1
    assert window_calls == 2
    assert reducer_calls == 1
    events = service.db.list_run_events("manifest-run")
    assert sum(
        item["event_type"] == "whole_semantic_window_ready"
        for item in events
    ) == 2
    assert any(
        item["event_type"] == "whole_semantic_capacity_reduced"
        for item in events
    )


@pytest.mark.asyncio
async def test_causal_chain_repair_reenters_json_and_semantic_validation(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    calls = 0
    valid_chain = {
        "core_goal": "查清误认",
        "cycles": [{
            "obstacle": "身份线索不足",
            "effort": "核实来历",
            "result": "找到支出记录",
            "state_change": "误认开始显露人为痕迹",
        }],
        "ending": {"surface_goal": "查清误认"},
        "covered_event_ids": [],
    }

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return "not json"
        return json.dumps(valid_chain, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        "manifest-run", run_path, project, "constraints", "# 已验收规划", [], None,
    )

    assert calls == 3
    assert chain == valid_chain
    assert json.loads(
        (run_path / "outputs" / "short-causal-chain.json").read_text(encoding="utf-8")
    ) == valid_chain
