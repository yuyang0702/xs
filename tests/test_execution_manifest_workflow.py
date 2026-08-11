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
    AtomicBeat,
    SegmentBeatContract,
    ShortExecutionManifest,
    StateAssertion,
    execution_manifest_payload,
    execution_manifest_sha256,
    future_beat_guards,
    parse_execution_manifest,
    state_assertions_sha256,
)
from novel_flywheel.planning_compiler import PlanningDocumentIR, PlanningSegmentIR
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.workflows import (
    DraftReceiptProtocolError,
    DraftSemanticValidationError,
    WorkflowService,
)


EVENT_ID = "EV-8E4BBA17"


def complete_manifest_plan(count: int = 2) -> str:
    segments = (
        ("核实", "误认身份被核实", "裴砚行正在沈府核实花穗身份",
         "沈老夫人派人外出核实花穗身份", "核实身份的人已经出发"),
        ("账房", "误认安排被证据揭示", "核实身份的人已经出发",
         "花穗发现二十两在她入府前已经支出", "花穗确认误认是人为安排"),
    )
    return "\n\n".join(
        f"### 第 {number} 段：{heading}\n"
        f"事件ID：{EVENT_ID}\n大纲依据：{outline}\n"
        f"段首承接：{opening}\n本段事件：{event}\n段末交接：{handoff}"
        for number, (heading, outline, opening, event, handoff)
        in enumerate(segments[:count], 1)
    )


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


def install_whole_obligation_authority(
    run_path: Path, source_event_ids: list[str],
) -> tuple[list[str], dict]:
    """Install the same two-level Runtime authority used by production drafting."""

    beats = tuple(
        AtomicBeat(
            beat_id=f"{event_id}/01", source_event_id=event_id,
            order=index, presentation_order=index,
            action=f"realize {event_id}", preconditions=(),
            postconditions=(f"{event_id} is complete",),
            owner_segment=index, source_evidence=f"evidence {event_id}",
            knowledge_delta=(f"knowledge {event_id}",),
            relationship_delta=(f"relationship {event_id}",),
        )
        for index, event_id in enumerate(source_event_ids, 1)
    )
    guards = future_beat_guards(
        beats, tuple(range(1, len(source_event_ids) + 1)),
    )
    segments = tuple(
        SegmentBeatContract(
            segment=index, beat_ids=(beat.beat_id,),
            entry_state=(StateAssertion(state=f"entry {index}", inherited_from="seed"),),
            exit_state=(StateAssertion(
                state=f"exit {index}", produced_by=(beat.beat_id,),
            ),),
            previous_exit_sha256="", future_beat_guard=guards[index],
        )
        for index, beat in enumerate(beats, 1)
    )
    planning_plan_sha256 = "e" * 64
    causal_chain = {
        "core_goal": "realize all atomic beats",
        "ending": "all obligations receive an adjudicated outcome",
        "covered_event_ids": source_event_ids,
    }
    causal_chain_sha256 = hashlib.sha256(json.dumps(
        causal_chain, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    manifest = ShortExecutionManifest(
        version=5, status="ready", authority_sha256="a" * 64,
        outline_sha256="b" * 64, planning_sha256=planning_plan_sha256,
        causal_chain_sha256=causal_chain_sha256, beats=beats, segments=segments,
        semantic_receipt={},
    )
    planning_ir = PlanningDocumentIR(
        plan_sha256=planning_plan_sha256,
        segments=tuple(
            PlanningSegmentIR(
                segment=index, heading=f"segment {index}",
                event_ids=(event_id,), outline=f"outline {event_id}",
                opening=f"opening {event_id}", event_body=f"body {event_id}",
                handoff=f"handoff {event_id}", source_sha256="f" * 64,
            )
            for index, event_id in enumerate(source_event_ids, 1)
        ),
    )
    outputs = run_path / "outputs"
    (outputs / "short-execution-index.json").write_text(
        json.dumps(execution_manifest_payload(manifest), ensure_ascii=False),
        encoding="utf-8",
    )
    (outputs / "planning-ir.json").write_text(json.dumps({
        "schema": "planning-document-ir-v1",
        "authority_sha256": planning_ir.authority_sha256,
        "document": planning_ir.model_dump(mode="json"),
    }, ensure_ascii=False), encoding="utf-8")
    (outputs / "short-causal-chain.json").write_text(
        json.dumps(causal_chain), encoding="utf-8",
    )
    beat_ids = [beat.beat_id for beat in beats]
    return beat_ids, WorkflowService._whole_story_obligation_catalog(
        run_path, beat_ids,
    )


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
            **(
                {"evidence_ids": list(beat.source_evidence_ids)}
                if beat.source_evidence_ids else
                {"evidence": beat.source_evidence}
            ),
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
        "### 第 1 段：抵达\n事件ID：EV-00000001\n"
        "大纲依据：飞船抵达空间站。\n段首承接：飞船进入近地轨道。\n"
        "本段事件：乘员完成对接并进入空间站。\n段末交接：进入空间站\n\n"
        "### 第 2 段：接管\n事件ID：EV-00000002\n"
        "大纲依据：乘员尝试接管系统。\n段首承接：乘员已经进入空间站。\n"
        "本段事件：乘员接管系统时触发防御响应。\n段末交接：系统封锁气闸"
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
        complete_manifest_plan(),
        {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排", "covered_event_ids": [EVENT_ID]},
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
    assert manifest.version == saved["version"] == 6
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
            complete_manifest_plan(),
            {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排", "covered_event_ids": [EVENT_ID]},
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
        complete_manifest_plan(),
        {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排", "covered_event_ids": [EVENT_ID]},
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
            complete_manifest_plan(),
            {"core_goal": "查清误认", "ending": "花穗确认误认是人为安排", "covered_event_ids": [EVENT_ID]},
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
        complete_manifest_plan(1),
        {"core_goal": "查清误认", "ending": "核实身份的人已经出发", "covered_event_ids": [EVENT_ID]},
        [{
            "id": EVENT_ID, "order": 1, "label": "误认身份被核实",
            "section": "第一章", "kind": "narrative",
        }],
        1,
    )

    assert manifest.status == "ready"
    assert calls == {"planning": 1, "review": 1}
    assert manifest.semantic_receipt["beat_receipts"][0]["evidence_ids"] == list(
        manifest.beats[0].source_evidence_ids
    )
    assert manifest.semantic_receipt["segment_receipts"][0]["evidence"] == (
        "核实身份的人已经出发"
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
            complete_manifest_plan(),
            {
                "core_goal": "查清误认",
                "ending": "花穗确认误认是人为安排",
                "covered_event_ids": [EVENT_ID],
            },
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
        complete_manifest_plan(),
        {
            "core_goal": "查清误认",
            "ending": "花穗确认误认是人为安排",
            "covered_event_ids": [EVENT_ID],
        },
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
    assert saved["version"] == 6
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
async def test_execution_manifest_runtime_binds_model_evidence_without_retry(
    tmp_path,
) -> None:
    service, project, run_path, state = make_service(tmp_path)
    stages: list[str] = []

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        stages.append(stage)
        if stage == "review":
            return receipt_for_prompt(prompt)
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        body = manifest_body(segment)
        return json.dumps(body, ensure_ascii=False)

    service._stage = fake_stage
    manifest = await service._ensure_short_execution_manifest(
        "manifest-run", run_path, project, "constraints", 7, state,
        complete_manifest_plan(),
        {
            "core_goal": "查清误认",
            "ending": "花穗确认误认是人为安排",
            "covered_event_ids": [EVENT_ID],
        },
        [{
            "id": EVENT_ID,
            "order": 1,
            "label": "误认身份被核实",
            "section": "第一章",
            "kind": "narrative",
        }],
        2,
    )

    assert manifest.status == "ready"
    assert stages == ["planning", "review", "planning", "review"]
    adapter_events = [
        item for item in service.db.list_run_events("manifest-run")
        if item["event_type"] == "contract_adapter_applied"
        and item["metadata"].get("adapter_name")
        == "execution_manifest_evidence_reference"
    ]
    assert len(adapter_events) == 2
    assert all(item["metadata"]["binding_count"] == 1 for item in adapter_events)


@pytest.mark.asyncio
async def test_ambiguous_execution_evidence_retries_only_reference_protocol(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        body = manifest_body(1)
        if calls == 1:
            body["beats"][0]["source_evidence"] = "shared exact excerpt"
        else:
            body["beats"][0]["source_evidence_ids"] = ["PLAN-E001"]
        return json.dumps(body, ensure_ascii=False)

    service._stage = fake_stage
    fragment, repairs, issues, _body = (
        await service._generate_short_execution_fragment(
            "manifest-run", run_path, project, "constraints",
            {
                "authority_sha256": "a" * 64,
                "outline_sha256": "b" * 64,
                "planning_sha256": "c" * 64,
                "causal_chain_sha256": "d" * 64,
            },
            1,
            [{
                "id": EVENT_ID,
                "evidence": "shared exact excerpt\n\nshared exact excerpt",
                "evidence_catalog": [
                    {"evidence_id": "PLAN-E001", "text": "shared exact excerpt"},
                    {"evidence_id": "PLAN-E002", "text": "shared exact excerpt"},
                ],
            }],
            complete_manifest_plan(1),
            {"covered_event_ids": [EVENT_ID]},
            (), "", {},
        )
    )

    assert fragment is not None
    assert issues == []
    assert calls == 2
    assert repairs == {"schema_repairs": 1, "integrity_repairs": 0}
    assert fragment.beats[0].source_evidence_ids == ("PLAN-E001",)
    assert any(
        item["event_type"] == "planning_manifest_fragment_repair"
        and item["metadata"]["issues"][0]["code"]
        == "source_evidence_authority_conflict"
        for item in service.db.list_run_events("manifest-run")
    )


@pytest.mark.asyncio
async def test_manifest_protocol_retry_cannot_reopen_passed_semantics(tmp_path) -> None:
    service, project, run_path, state = make_service(tmp_path)
    planning_calls = 0
    review_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls, review_calls
        stage = args[3]
        prompt = args[5]
        if stage == "planning":
            planning_calls += 1
            return json.dumps(manifest_body(1), ensure_ascii=False)
        review_calls += 1
        receipt = json.loads(receipt_for_prompt(prompt))
        if review_calls == 1:
            receipt["segment_receipts"].append(
                dict(receipt["segment_receipts"][0])
            )
        else:
            receipt["beat_receipts"][0]["actor_action_valid"] = False
            receipt["beat_receipts"][0]["field_verdicts"] = {"actor": False}
            receipt["beat_receipts"][0]["invalid_fields"] = ["actor"]
        return json.dumps(receipt, ensure_ascii=False)

    service._stage = fake_stage
    manifest = await service._ensure_short_execution_manifest(
        "manifest-run", run_path, project, "constraints", 7, state,
        complete_manifest_plan(1),
        {
            "core_goal": "查清误认", "ending": "核实身份的人已经出发",
            "covered_event_ids": [EVENT_ID],
        },
        [{
            "id": EVENT_ID, "order": 1, "label": "误认身份被核实",
            "section": "第一章", "kind": "narrative",
        }],
        1,
    )

    assert manifest.status == "ready"
    assert planning_calls == 1
    assert review_calls == 2
    assert manifest.semantic_receipt["beat_receipts"][0][
        "actor_action_valid"
    ] is True
    events = service.db.list_run_events("manifest-run")
    assert any(
        item["event_type"] == "receipt_semantic_drift_contained"
        and item["metadata"]["boundary"] == "execution_manifest_receipt"
        for item in events
    )


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
        complete_manifest_plan(),
        {
            "core_goal": "查清误认",
            "ending": "花穗确认误认是人为安排",
            "covered_event_ids": [EVENT_ID],
        },
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
        first.exit_state, version=5,
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
            state_assertions_sha256(previous_exit, version=6)
    )
    bound["beats"][0]["source_evidence_ids"] = ["E-1"]
    with pytest.raises(ValueError, match="entry_state must be a non-empty list"):
            parse_execution_manifest({
                **bound,
                "version": 6,
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
        else:
            payload["beat_receipts"][0]["actor_action_valid"] = False
            payload["entry"]["satisfied"] = False
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
    assert any(
        item["event_type"] == "receipt_semantic_drift_contained"
        and item["metadata"]["boundary"] == "draft_semantic_receipt"
        for item in events
    )


@pytest.mark.asyncio
async def test_draft_receipt_protocol_exhaustion_never_becomes_prose_rewrite(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    prose = "The investigator checks the sealed ledger and preserves the original evidence."
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-immutable",
        parent_task_id="manifest-run",
        depth=0,
        target_han=40,
        event_ids=(EVENT_ID,),
        scope="verify the ledger",
        entry_state="the ledger is sealed",
        exit_requirement="the evidence is preserved",
        execution_manifest_sha256="b" * 64,
        beat_ids=(f"{EVENT_ID}/01",),
        viewpoint="",
    )
    prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompts.append(args[5])
        return "not-json"

    service._stage = fake_stage
    with pytest.raises(DraftReceiptProtocolError):
        await service._verify_draft_semantic_node(
            "manifest-run", run_path, project, "constraints", contract,
            prose, [], suffix="-protocol-exhausted", failure_stage="draft",
        )

    assert len(prompts) == 2
    assert all(prose in prompt for prompt in prompts)
    assert any(
        item["event_type"] == "semantic_receipt_protocol_exhausted"
        for item in service.db.list_run_events("manifest-run")
    )


@pytest.mark.asyncio
async def test_draft_receipt_protocol_uses_configured_fallback_without_rewriting(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    service.db.save_role_binding(
        "review", "primary", "reviewer", "backup", "reviewer-2",
    )
    service.gateway.complete_configured_fallback = lambda *_args, **_kwargs: None
    prose = "The investigator checks the sealed ledger and preserves the evidence."
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-fallback",
        parent_task_id="manifest-run",
        depth=0,
        target_han=40,
        event_ids=(EVENT_ID,),
        scope="check ledger",
        entry_state="the investigator checks the sealed ledger",
        exit_requirement="preserves the evidence",
        execution_manifest_sha256="b" * 64,
        beat_ids=(f"{EVENT_ID}/01",),
        viewpoint="",
    )
    routes: list[bool] = []

    async def fake_stage(*args, **kwargs):
        fallback = bool(kwargs.get("prefer_configured_fallback"))
        routes.append(fallback)
        if not fallback:
            return "not-json"
        evidence = "The investigator checks the sealed ledger"
        exit_evidence = "preserves the evidence"
        return json.dumps({
            "authority_sha256": contract.authority_sha256,
            "execution_manifest_sha256": contract.execution_manifest_sha256,
            "task_id": contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
            "beat_receipts": [{
                "beat_id": f"{EVENT_ID}/01", "evidence": evidence,
                "actor_action_valid": True, "actor_action_evidence": evidence,
                "state_valid": True, "state_evidence": exit_evidence,
                "scene_order_valid": True, "scene_order_evidence": evidence,
            }],
            "outside_beat_ids": [], "future_beat_ids": [],
            "entry": {"satisfied": True, "evidence": evidence},
            "exit": {"satisfied": True, "evidence": exit_evidence},
            "causal_order_valid": True,
            "causal_order_evidence": evidence,
            "summary": "The immutable prose satisfies the beat contract.",
        })

    service._stage = fake_stage
    receipt = await service._verify_draft_semantic_node(
        "manifest-run", run_path, project, "constraints", contract,
        prose, [], suffix="-protocol-fallback", failure_stage="draft",
    )

    assert routes == [False, False, True]
    assert receipt["prose_sha256"] == hashlib.sha256(
        prose.encode("utf-8"),
    ).hexdigest()
    assert any(
        item["event_type"] == "protocol_receipt_model_fallback"
        for item in service.db.list_run_events("manifest-run")
    )


@pytest.mark.asyncio
async def test_route_failure_history_does_not_mask_fallback_semantic_rejection(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    service.db.save_role_binding(
        "review", "primary", "reviewer", "backup", "reviewer-2",
    )
    service.gateway.complete_configured_fallback = lambda *_args, **_kwargs: None
    prose = "The investigator opens the sealed ledger but loses the causal trail."
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-semantic-negative",
        parent_task_id="manifest-run",
        depth=0,
        target_han=40,
        event_ids=(EVENT_ID,),
        scope="open the sealed ledger",
        entry_state="the ledger is sealed",
        exit_requirement="the causal trail remains provable",
    )
    routes: list[bool] = []

    async def fake_stage(*args, **kwargs):
        fallback = bool(kwargs.get("prefer_configured_fallback"))
        routes.append(fallback)
        if not fallback:
            raise RuntimeError("primary transport interrupted")
        excerpt = "The investigator opens the sealed ledger"
        return json.dumps({
            "authority_sha256": contract.authority_sha256,
            "task_id": contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
            "event_receipts": [{"event_id": EVENT_ID, "evidence": excerpt}],
            "outside_event_ids": [],
            "entry": {"satisfied": True, "evidence": excerpt},
            "exit": {"satisfied": True, "evidence": excerpt},
            "causal_order_valid": False,
            "causal_order_evidence": excerpt,
            "summary": "The causal trail is not preserved.",
        })

    service._stage = fake_stage
    with pytest.raises(DraftSemanticValidationError):
        await service._verify_draft_semantic_node(
            "manifest-run", run_path, project, "constraints", contract,
            prose, [], suffix="-semantic-negative", failure_stage="draft",
        )

    assert routes == [False, False, True]


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
    event_ids, _catalog = install_whole_obligation_authority(
        run_path, [EVENT_ID, "EV-8E4BBA18"],
    )
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
        payload = {
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
        }
        if calls == 1:
            payload["draft_sha256"] = "0" * 64
        else:
            payload["ending_valid"] = False
            payload["commitments_valid"] = False
        return json.dumps(payload, ensure_ascii=False)

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
    assert any(
        item["event_type"] == "receipt_semantic_drift_contained"
        and item["metadata"]["boundary"] == "whole_draft_semantic_receipt"
        for item in events
    )


@pytest.mark.asyncio
async def test_whole_semantic_direct_negative_is_typed_semantic_failure(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = ["第一段建立承诺。", "第二段没有兑现承诺。"]
    draft = "\n\n".join(segments)
    authority = "a" * 64
    event_ids, _catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002"],
    )

    async def negative_stage(*_args, **_kwargs):
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "segment_sha256": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in segments
            ],
            "event_ids": event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": False,
            "evidence": [{"kind": "opening", "excerpt": segments[0]}],
            "summary": "The commitment remains unresolved.",
        }, ensure_ascii=False)

    service._stage = negative_stage
    with pytest.raises(DraftSemanticValidationError) as captured:
        await service._verify_whole_draft_semantics(
            "manifest-run", run_path, project, "constraints", authority,
            draft, segments, event_ids,
            [{
                "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
            } for segment, event_id in zip(segments, event_ids, strict=True)],
        )

    assert any(
        issue.get("code") == "commitments_valid"
        for issue in captured.value.issues
    )


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
    event_ids, _catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002", "EV-00000003"],
    )
    segment_receipts = []
    for index, (segment, event_id) in enumerate(zip(segments, event_ids), 1):
        segment_receipts.append({
            "prose_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
            "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
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
                "ending_evidence": segments[numbers[-1] - 1],
                "introduced_obligations": [],
                "resolved_within_window_obligations": [],
                "obligation_reconciliations": [],
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

    second = await service._verify_whole_draft_semantics(
        "manifest-run", run_path, project, "constraints", authority,
        draft, segments, event_ids, segment_receipts,
    )
    assert second["event_ids"] == event_ids
    assert direct_calls == 2
    assert window_calls == 2
    assert reducer_calls == 1
    assert sum(
        item["event_type"] == "whole_semantic_window_reused"
        for item in service.db.list_run_events("manifest-run")
    ) == 2


@pytest.mark.asyncio
async def test_whole_semantic_capacity_carries_typed_obligation_to_payoff(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = [
        "Before dawn, Lin promises to return the sealed key.",
        "At noon, she crosses the flooded archive with the key.",
        "At dusk, Lin returns the sealed key to its owner.",
    ]
    draft = "\n\n".join(segments)
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    authority = "a" * 64
    event_ids, catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002", "EV-00000003"],
    )
    evidence = [{
        "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
    } for segment, event_id in zip(segments, event_ids, strict=True)]
    seen_open_ledgers: list[list[dict]] = []

    async def stage(*args, **_kwargs):
        prompt = args[5]
        if prompt.startswith("DRAFT_WHOLE_SEMANTIC_WINDOW_V1"):
            numbers = json.loads(re.search(
                r"SEGMENT NUMBERS: (\[[^\n]+\])", prompt,
            ).group(1))
            hashes = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
            ).group(1))
            owned = json.loads(re.search(
                r"EVENT IDS: (\[[^\n]+\])", prompt,
            ).group(1))
            ledger = json.loads(re.search(
                r"OPEN OBLIGATION LEDGER: (.*?)\nWINDOW PROSE:", prompt,
            ).group(1))
            seen_open_ledgers.append(ledger)
            introduced = []
            reconciliations = []
            if numbers == [1, 2]:
                introduced = [{
                    "kind": "promise",
                    "description": "Lin must return the sealed key.",
                    "evidence": segments[0],
                }]
            else:
                reconciliations = [{
                    "obligation_id": ledger[0]["obligation_id"],
                    "status": "discharged",
                    "evidence": segments[2],
                }]
            return json.dumps({
                "authority_sha256": authority,
                "draft_sha256": draft_sha256,
                "segment_numbers": numbers,
                "segment_sha256": hashes,
                "event_ids": owned,
                "missing_event_ids": [],
                "duplicate_event_ids": [],
                "out_of_order_event_ids": [],
                "causal_order_valid": True,
                "continuity_valid": True,
                "commitment_flow_valid": True,
                "ending_valid": True,
                "ending_evidence": segments[numbers[-1] - 1],
                "introduced_obligations": introduced,
                "resolved_within_window_obligations": [],
                "obligation_reconciliations": reconciliations,
                "evidence": [{"kind": "window", "excerpt": segments[numbers[0] - 1]}],
                "summary": "The local obligation inventory is complete.",
            })
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": draft_sha256,
            "segment_sha256": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in segments
            ],
            "event_ids": event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": True,
            "evidence": [{"kind": "payoff", "excerpt": segments[2]}],
            "summary": "The carried key promise is discharged.",
        })

    service._stage = stage
    result = await service._verify_whole_draft_semantics_capacity_split(
        "manifest-run", run_path, project, "constraints", authority,
        draft, segments, event_ids, evidence,
        json.dumps({"authority_sha256": authority}),
        obligation_catalog=catalog,
        details={"trigger": "preflight"}, failure_stage="draft",
    )

    assert json.loads(result)["commitments_valid"] is True
    assert seen_open_ledgers[0] == []
    assert seen_open_ledgers[1][0]["description"] == (
        "Lin must return the sealed key."
    )


@pytest.mark.asyncio
async def test_protocol_executor_preserves_capacity_split_semantic_verdict(
    tmp_path,
) -> None:
    service, _project, _run_path, _state = make_service(tmp_path)
    attempt = service._protocol_receipt_attempt_plan(
        "review", same_route_attempts=1,
    )[0]

    async def semantic_rejection():
        raise DraftSemanticValidationError(
            "whole-window-1-2",
            [{"code": "continuity_valid", "message": "真实连续性冲突"}],
        )

    with pytest.raises(DraftSemanticValidationError):
        await service._execute_protocol_receipt_attempt(
            "manifest-run", stage="review",
            boundary="whole_draft_semantic_receipt",
            attempt=attempt,
            unit_metadata={"draft_sha256": "a" * 64},
            operation=semantic_rejection,
            capacity_can_use_fallback=True,
        )


@pytest.mark.asyncio
async def test_whole_semantic_capacity_protocol_failure_never_becomes_prose_failure(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = ["第一段正文保持不变。", "第二段正文也保持不变。"]
    draft = "\n\n".join(segments)
    authority = "a" * 64
    event_ids, catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002"],
    )
    evidence = [{
        "beat_receipts": [{
            "beat_id": event_id, "evidence": segment,
        }],
    } for event_id, segment in zip(event_ids, segments, strict=True)]
    calls = 0

    async def malformed_stage(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "not json"

    service._stage = malformed_stage
    with pytest.raises(DraftReceiptProtocolError):
        await service._verify_whole_draft_semantics_capacity_split(
            "manifest-run", run_path, project, "constraints", authority,
            draft, segments, event_ids, evidence,
            json.dumps({"authority_sha256": authority}),
            obligation_catalog=catalog,
            details={"trigger": "preflight"}, failure_stage="draft",
        )

    assert calls == 2


@pytest.mark.asyncio
async def test_whole_semantic_capacity_semantic_rejection_does_not_retry_protocol(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = ["第一段正文保持不变。", "第二段正文也保持不变。"]
    draft = "\n\n".join(segments)
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    authority = "a" * 64
    event_ids, catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002"],
    )
    evidence = [{
        "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
    } for segment, event_id in zip(segments, event_ids, strict=True)]
    calls = 0

    async def rejected_stage(*args, **_kwargs):
        nonlocal calls
        calls += 1
        prompt = args[5]
        numbers = json.loads(re.search(
            r"SEGMENT NUMBERS: (\[[^\n]+\])", prompt,
        ).group(1))
        hashes = json.loads(re.search(
            r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
        ).group(1))
        owned = json.loads(re.search(
            r"EVENT IDS: (\[[^\n]+\])", prompt,
        ).group(1))
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": draft_sha256,
            "segment_numbers": numbers,
            "segment_sha256": hashes,
            "event_ids": owned,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": False,
            "commitment_flow_valid": True,
            "introduced_obligations": [],
            "resolved_within_window_obligations": [],
            "obligation_reconciliations": [],
            "ending_valid": True,
            "ending_evidence": segments[numbers[-1] - 1],
            "evidence": [{"kind": "window", "excerpt": segments[0]}],
            "summary": "发现真实的连续性冲突。",
        }, ensure_ascii=False)

    service._stage = rejected_stage
    with pytest.raises(DraftSemanticValidationError):
        await service._verify_whole_draft_semantics_capacity_split(
            "manifest-run", run_path, project, "constraints", authority,
            draft, segments, event_ids, evidence,
            json.dumps({"authority_sha256": authority}),
            obligation_catalog=catalog,
            details={"trigger": "preflight"}, failure_stage="draft",
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_whole_semantic_capacity_never_forges_global_commitment_success(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = [
        "我一定会让死去的朋友回来。仪式已经开始。",
        "风停在空屋门前，故事到这里结束。",
    ]
    draft = "\n\n".join(segments)
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    authority = "a" * 64
    event_ids, catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002"],
    )
    evidence = [{
        "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
    } for segment, event_id in zip(segments, event_ids, strict=True)]

    async def locally_positive_window(*args, **_kwargs):
        prompt = args[5]
        numbers = json.loads(re.search(
            r"SEGMENT NUMBERS: (\[[^\n]+\])", prompt,
        ).group(1))
        hashes = json.loads(re.search(
            r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
        ).group(1))
        owned = json.loads(re.search(
            r"EVENT IDS: (\[[^\n]+\])", prompt,
        ).group(1))
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": draft_sha256,
            "segment_numbers": numbers,
            "segment_sha256": hashes,
            "event_ids": owned,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "commitment_flow_valid": True,
            "introduced_obligations": [],
            "resolved_within_window_obligations": [],
            "obligation_reconciliations": [],
            "ending_valid": True,
            "ending_evidence": segments[numbers[-1] - 1],
            "evidence": [{"kind": "window", "excerpt": segments[0]}],
            "summary": "The adjacent window appears locally coherent.",
        }, ensure_ascii=False)

    service._stage = locally_positive_window
    with pytest.raises(DraftSemanticValidationError) as captured:
        await service._verify_whole_draft_semantics_capacity_split(
            "manifest-run", run_path, project, "constraints", authority,
            draft, segments, event_ids, evidence,
            json.dumps({"authority_sha256": authority}),
            obligation_catalog=catalog,
            details={"trigger": "preflight"}, failure_stage="draft",
        )

    assert any(
        issue.get("code") == "commitments_valid"
        and issue.get("promise_ids")
        for issue in captured.value.issues
    )


@pytest.mark.asyncio
async def test_whole_semantic_capacity_global_reducer_catches_unseen_obligation(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    segments = [
        "黎明前反应堆将熔毁，控制室已经拉响警报。",
        "故事在正午结束，却没有说明反应堆的结局。",
    ]
    draft = "\n\n".join(segments)
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    authority = "a" * 64
    event_ids, catalog = install_whole_obligation_authority(
        run_path, ["EV-00000001", "EV-00000002"],
    )
    evidence = [{
        "beat_receipts": [{"beat_id": event_id, "evidence": segment}],
    } for segment, event_id in zip(segments, event_ids, strict=True)]
    reducer_calls = 0

    async def stage(*args, **_kwargs):
        nonlocal reducer_calls
        prompt = args[5]
        if prompt.startswith("DRAFT_WHOLE_SEMANTIC_WINDOW_V1"):
            numbers = json.loads(re.search(
                r"SEGMENT NUMBERS: (\[[^\n]+\])", prompt,
            ).group(1))
            hashes = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", prompt,
            ).group(1))
            owned = json.loads(re.search(
                r"EVENT IDS: (\[[^\n]+\])", prompt,
            ).group(1))
            return json.dumps({
                "authority_sha256": authority,
                "draft_sha256": draft_sha256,
                "segment_numbers": numbers,
                "segment_sha256": hashes,
                "event_ids": owned,
                "missing_event_ids": [],
                "duplicate_event_ids": [],
                "out_of_order_event_ids": [],
                "causal_order_valid": True,
                "continuity_valid": True,
                "commitment_flow_valid": True,
                "introduced_obligations": [],
                "resolved_within_window_obligations": [],
                "obligation_reconciliations": [],
                "ending_valid": True,
                "ending_evidence": segments[numbers[-1] - 1],
                "evidence": [{"kind": "window", "excerpt": segments[0]}],
                "summary": "The adjacent boundary is locally coherent.",
            }, ensure_ascii=False)
        assert prompt.startswith("DRAFT_WHOLE_SEMANTIC_REDUCE_V1")
        reducer_calls += 1
        return json.dumps({
            "authority_sha256": authority,
            "draft_sha256": draft_sha256,
            "segment_sha256": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in segments
            ],
            "event_ids": event_ids,
            "missing_event_ids": [],
            "duplicate_event_ids": [],
            "out_of_order_event_ids": [],
            "causal_order_valid": True,
            "continuity_valid": True,
            "ending_valid": True,
            "commitments_valid": False,
            "evidence": [{"kind": "opening", "excerpt": segments[0]}],
            "summary": "The reactor commitment remains unresolved.",
        }, ensure_ascii=False)

    service._stage = stage
    with pytest.raises(DraftSemanticValidationError) as captured:
        await service._verify_whole_draft_semantics_capacity_split(
            "manifest-run", run_path, project, "constraints", authority,
            draft, segments, event_ids, evidence,
            json.dumps({"authority_sha256": authority}),
            obligation_catalog=catalog,
            details={"trigger": "preflight"}, failure_stage="draft",
        )

    assert reducer_calls == 1
    assert any(
        issue.get("code") == "commitments_valid"
        for issue in captured.value.issues
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
        "covered_event_ids": [EVENT_ID],
    }

    async def fake_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return "not json"
        return json.dumps(valid_chain, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        "manifest-run", run_path, project, "constraints",
        complete_manifest_plan(1), [], None,
    )

    assert calls == 3
    assert chain["covered_event_ids"] == [EVENT_ID]
    assert chain["cycles"] == valid_chain["cycles"]
    assert json.loads(
        (run_path / "outputs" / "short-causal-chain.json").read_text(encoding="utf-8")
    ) == chain


@pytest.mark.asyncio
async def test_causal_chain_rejects_embedded_candidate_missing_ir_coverage(
    tmp_path,
) -> None:
    service, project, run_path, _state = make_service(tmp_path)
    calls = 0
    incomplete_candidate = {
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
        return json.dumps({
            **incomplete_candidate,
            "covered_event_ids": [EVENT_ID],
        }, ensure_ascii=False)

    service._stage = fake_stage
    chain = await service._ensure_short_causal_chain(
        "manifest-run", run_path, project, "constraints",
        complete_manifest_plan(1), [], incomplete_candidate,
    )

    assert calls == 1
    assert chain["covered_event_ids"] == [EVENT_ID]
