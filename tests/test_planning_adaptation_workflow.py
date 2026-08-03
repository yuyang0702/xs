from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.outlines import narrative_outline_event_contracts
from novel_flywheel.planning_adaptation import (
    INVARIANT_FIELDS,
    LEGACY_PLANNING_ADAPTATION_VERSION,
    planning_adaptation_evidence_candidates,
    planning_adaptation_segment_authority_sha256,
    planning_adaptation_whole_authority_sha256,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.workflows import WorkflowService


def make_service(tmp_path: Path) -> tuple[WorkflowService, object, Path, dict, list[dict]]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Adaptive planning", mode="short", genre="suspense",
        premise="A clerk uncovers missing inventory.", target_words=5000,
    ))
    service = WorkflowService(db, store, SimpleNamespace(), SimpleNamespace())
    run_id = "adaptation-run"
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    outline = (
        "## 第二幕\n\n"
        "### 第三章\n"
        "- **发现异常**：花穗亲眼撞见刘管事从库房向外搬运箱子，随后亲自核实。\n"
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)
    return service, project, run_path, state, contracts


def plan_for(event_id: str, event: str) -> str:
    return (
        "### 第 1 段：库房异动\n\n"
        f"事件ID：{event_id}\n\n"
        "大纲依据：发现异常\n\n"
        "段首承接：花穗正在调查账目缺口。\n\n"
        f"本段事件：{event}\n\n"
        "段末交接：花穗取得可以继续查账的可靠证据。"
    )


def two_segment_plan(first_id: str, second_id: str, *, repaired: bool) -> str:
    second_entry = (
        "花穗已经取得可靠证据，准备与裴砚行核对账册。"
        if repaired else "花穗尚未取得证据，却直接开始公开对质。"
    )
    return (
        "### 第 1 段：发现\n\n"
        f"事件ID：{first_id}\n\n"
        "大纲依据：发现异常\n\n"
        "段首承接：花穗正在调查账目缺口。\n\n"
        "本段事件：小厮报信后，花穗亲自核验库房异常。\n\n"
        "段末交接：花穗已经取得可靠证据，准备与裴砚行核对账册。\n\n"
        "### 第 2 段：对质\n\n"
        f"事件ID：{second_id}\n\n"
        "大纲依据：形成证据链\n\n"
        f"段首承接：{second_entry}\n\n"
        "本段事件：裴砚行核对账册后，二人提交证据并推动公开对质。\n\n"
        "段末交接：账目问题被确认，后续追查转向幕后经手人。"
    )


def three_segment_plan(
    event_ids: list[str], *, third_opening: str = "第二项结果成立，第三项行动可以开始。",
    third_event: str = "主角完成第三项正式行动。",
) -> str:
    return "\n\n".join([
        (
            "### 第 1 段：第一项\n\n"
            f"事件ID：{event_ids[0]}\n\n"
            "大纲依据：第一项\n\n"
            "段首承接：故事入口状态已经明确。\n\n"
            "本段事件：主角完成第一项正式行动。\n\n"
            "段末交接：第一项结果成立，第二项行动可以开始。"
        ),
        (
            "### 第 2 段：第二项\n\n"
            f"事件ID：{event_ids[1]}\n\n"
            "大纲依据：第二项\n\n"
            "段首承接：第一项结果成立，第二项行动可以开始。\n\n"
            "本段事件：主角完成第二项正式行动。\n\n"
            "段末交接：第二项结果成立，第三项行动可以开始。"
        ),
        (
            "### 第 3 段：第三项\n\n"
            f"事件ID：{event_ids[2]}\n\n"
            "大纲依据：第三项\n\n"
            f"段首承接：{third_opening}\n\n"
            f"本段事件：{third_event}\n\n"
            "段末交接：第三项结果成立，故事进入收束状态。"
        ),
    ])
def adaptation_receipt(prompt: str, *, structural: bool) -> str:
    authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
    planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
    segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
    event_ids = json.loads(
        prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
            "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
        )[0]
    )
    candidate_text = prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1].split(
        "\n\nRECEIPT PROTOCOL ISSUES:", 1,
    )[0]
    candidates = json.loads(candidate_text)
    evidence_id = next(
        key for key, value in candidates.items() if "本段事件" in value
    )
    invariants = {field: True for field in INVARIANT_FIELDS}
    dimensions = ["trigger_method"]
    classification = "equivalent"
    reason = "报信只是入口，花穗仍亲自核实并主导查证。"
    if structural:
        classification = "structural"
        dimensions = ["primary_actor_agency", "knowledge_state"]
        invariants["primary_actor_agency"] = False
        invariants["knowledge_state"] = False
        reason = "规划把花穗的亲自发现和核实改成了小厮直接确认。"
    return json.dumps({
        "authority_sha256": authority,
        "planning_sha256": planning,
        "segment": segment,
        "event_reviews": [{
            "event_id": event_ids[0],
            "classification": classification,
            "changed_dimensions": dimensions,
            "invariants": invariants,
            "plan_evidence_ids": [evidence_id],
            "reason": reason,
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": reason,
    }, ensure_ascii=False)


def whole_adaptation_receipt(prompt: str, *, valid: bool = True) -> str:
    authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
    planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
    segments = json.loads(
        prompt.split("EXPECTED SEGMENTS:\n", 1)[1].split("\n\nEXPECTED EVENT IDS", 1)[0]
    )
    event_ids = json.loads(
        prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\nFORMAL EVENT CONTRACTS", 1)[0]
    )
    return json.dumps({
        "authority_sha256": authority,
        "planning_sha256": planning,
        "segment_numbers": segments,
        "event_ids": event_ids,
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": valid,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [] if valid else [segments[0]],
        "affected_event_ids": [] if valid else [event_ids[0]],
        "reason": "" if valid else "段末证据与下一段入口不一致。",
        "summary": "整篇因果、状态、视角和结局保持。",
    }, ensure_ascii=False)


def adaptation_receipt_with_invalid_invariants(
    prompt: str, invalid: set[str],
) -> str:
    payload = json.loads(adaptation_receipt(prompt, structural=False))
    review = payload["event_reviews"][0]
    review["invariants"] = {
        field: field not in invalid for field in INVARIANT_FIELDS
    }
    review["changed_dimensions"] = sorted(invalid) or ["trigger_method"]
    review["classification"] = "structural" if invalid else "equivalent"
    review["reason"] = (
        "候选仍改变了这些正式不变量：" + "、".join(sorted(invalid))
        if invalid else "候选保留了全部正式不变量。"
    )
    payload["summary"] = review["reason"]
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_structural_plan_drift_is_targeted_then_authorized_as_equivalent(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "小厮报信后直接确认刘管事正在倒卖，花穗据此准备告发。")
    calls: list[tuple[str, str]] = []

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls.append((stage, prompt))
        if stage == "review":
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
                return whole_adaptation_receipt(prompt)
            return adaptation_receipt(
                prompt, structural="亲自到库房复核" not in prompt,
            )
        assert "SHORT_PLAN_EQUIVALENCE_TARGETED_REPAIR_V2" in prompt
        return plan_for(
            event_id,
            "小厮先报信，花穗追问时间与路线后亲自到库房复核，确认异常再继续查账。",
        )

    service._stage = fake_stage
    plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert "亲自到库房复核" in plan
    assert artifact and artifact["status"] == "ready"
    assert artifact["semantic_repairs"] == 1
    assert artifact["segments"][0]["event_reviews"][0]["classification"] == "equivalent"
    assert [stage for stage, _prompt in calls] == [
        "review", "planning", "review", "review",
    ]
    events = service.db.list_run_events("adaptation-run")
    assert any(item["event_type"] == "planning_adaptation_review_started" for item in events)
    assert any(item["event_type"] == "planning_adaptation_targeted_repair" for item in events)
    assert any(item["event_type"] == "planning_adaptation_ready" for item in events)


@pytest.mark.asyncio
async def test_receipt_protocol_failure_retries_receipt_without_mutating_plan(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "花穗亲自核实库房异常。")
    calls: list[str] = []

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        calls.append(stage)
        assert stage == "review"
        valid = json.loads(adaptation_receipt(prompt, structural=False))
        valid["event_reviews"][0]["plan_evidence_ids"] = ["PLAN-01-MISSING"]
        return json.dumps(valid, ensure_ascii=False)

    service._stage = fake_stage
    with pytest.raises(ValueError, match="审核回执未通过"):
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 1,
        )

    assert calls == ["review", "review", "review"]
    artifact = json.loads(
        (run_path / "outputs" / "planning-adaptations.json").read_text(
            encoding="utf-8",
        )
    )
    assert artifact["status"] == "failed"
    assert artifact["planning_sha256"] == hashlib.sha256(
        original.encode("utf-8"),
    ).hexdigest()
    assert artifact["semantic_repairs"] == 0


@pytest.mark.asyncio
async def test_failed_run_revalidates_unknown_dimension_receipt_locally_then_continues(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    plan = plan_for(event_id, "花穗在细节试探后仍亲自核实库房异常。")
    outline_sha = hashlib.sha256(
        state["outline"]["content"].encode("utf-8"),
    ).hexdigest()
    plan_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    evidence_id = next(
        key for key, value in candidates.items() if "本段事件" in value
    )
    raw_receipt = {
        "authority_sha256": planning_adaptation_segment_authority_sha256(
            outline_sha256=outline_sha,
            planning_sha256=plan_sha,
            segment=1,
            event_contracts=contracts,
            plan_segment=plan,
            previous_handoff="opening",
            next_entry="ending",
        ),
        "planning_sha256": plan_sha,
        "segment": 1,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "presentation",
            "changed_dimensions": [
                "scene_presentation", "secondary_action", "心理呈现",
            ],
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "plan_evidence_ids": [evidence_id],
            "reason": "只增加表现和心理细节，人物主动性与事件结果保持。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "正式事件的功能、执行者、因果和后续状态保持。",
    }
    (run_path / "outputs" / "review-plan-adaptation-segment-01-initial-3.md").write_text(
        json.dumps(raw_receipt, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    calls: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        calls.append(prompt)
        assert "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt
        return whole_adaptation_receipt(prompt)

    service._stage = fake_stage
    accepted_plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        plan, [], 1,
    )

    assert accepted_plan == plan
    assert changed is False
    assert artifact and artifact["status"] == "ready"
    assert len(calls) == 1
    review = artifact["segments"][0]["event_reviews"][0]
    assert review["classification"] == "equivalent"
    assert review["unrecognized_dimensions"] == [
        "scene_presentation", "secondary_action", "心理呈现",
    ]
    assert any(
        item["event_type"] == "planning_adaptation_receipt_revalidated"
        for item in service.db.list_run_events("adaptation-run")
    )


def test_failed_adaptation_resume_reuses_exact_plan_before_any_planning_call(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    plan = plan_for(contracts[0]["id"], "花穗亲自核实库房异常。")
    plan_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    outline_sha = hashlib.sha256(
        state["outline"]["content"].encode("utf-8"),
    ).hexdigest()
    (run_path / "outputs" / "planning.md").write_text(plan, encoding="utf-8")
    artifact_path = run_path / "outputs" / "planning-adaptations.json"
    artifact = {
        "version": 1,
        "status": "failed",
        "outline_sha256": outline_sha,
        "planning_sha256": plan_sha,
        "segment_count": 1,
        "segments": [],
        "whole_story_receipt": {},
        "issues": [{"code": "changed_dimensions"}],
    }
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False), encoding="utf-8",
    )

    resumed = service._resumable_current_planning_adaptation_plan(
        run_path, project, state, 1, "current-context",
    )

    assert resumed == (plan, None, True)
    artifact["generation_context_sha256"] = "old-context"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False), encoding="utf-8",
    )
    assert service._resumable_current_planning_adaptation_plan(
        run_path, project, state, 1, "current-context",
    ) is None


@pytest.mark.asyncio
async def test_whole_story_handoff_failure_repairs_only_affected_segment(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    outline = (
        "## 第二幕\n\n"
        "### 第三章\n"
        "- **发现异常**：花穗亲眼发现库房异常并取得可以继续查账的可靠证据。\n"
        "- **形成证据链**：裴砚行核对账册，二人提交证据并推动公开对质。\n"
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)
    first_id, second_id = [item["id"] for item in contracts]
    original = two_segment_plan(first_id, second_id, repaired=False)
    whole_calls = 0
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal whole_calls, planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review" and "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            whole_calls += 1
            value = json.loads(whole_adaptation_receipt(prompt, valid=whole_calls > 1))
            if whole_calls == 1:
                value["affected_segments"] = [2]
                value["affected_event_ids"] = [second_id]
            return json.dumps(value, ensure_ascii=False)
        if stage == "review":
            return adaptation_receipt(prompt, structural=False)
        planning_calls += 1
        assert "EXPECTED SEGMENT: 2" in prompt
        return (
            "### 第 2 段：对质\n\n"
            f"事件ID：{second_id}\n\n"
            "大纲依据：形成证据链\n\n"
            "段首承接：花穗已经取得可靠证据，准备与裴砚行核对账册。\n\n"
            "本段事件：裴砚行核对账册后，二人提交证据并推动公开对质。\n\n"
            "段末交接：账目问题被确认，后续追查转向幕后经手人。"
        )

    service._stage = fake_stage
    plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 2,
    )

    assert changed is True
    assert "花穗已经取得可靠证据" in service._short_plan_segments(plan, 2)[1]
    assert artifact and artifact["status"] == "ready"
    assert artifact["whole_story_receipt"]["adjacent_handoffs_preserved"] is True
    assert whole_calls == 2
    assert planning_calls == 1


@pytest.mark.asyncio
async def test_whole_story_protocol_failure_retries_receipt_without_mutating_plan(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "花穗亲自核实库房异常。")
    whole_calls = 0
    stages: list[str] = []

    async def fake_stage(*args, **kwargs):
        nonlocal whole_calls
        stage = args[3]
        prompt = args[5]
        stages.append(stage)
        assert stage == "review"
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" not in prompt:
            return adaptation_receipt(prompt, structural=False)
        whole_calls += 1
        value = json.loads(whole_adaptation_receipt(prompt))
        if whole_calls == 1:
            value["affected_segments"] = [1]
            value["affected_event_ids"] = [event_id]
        return json.dumps(value, ensure_ascii=False)

    service._stage = fake_stage
    plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert plan == original
    assert changed is False
    assert artifact and artifact["status"] == "ready"
    assert artifact["protocol_repairs"] == 1
    assert whole_calls == 2
    assert stages == ["review", "review", "review"]


@pytest.mark.asyncio
async def test_whole_story_multiple_affected_segments_receive_the_full_issue(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    outline = (
        "## 第二幕\n\n"
        "### 第三章\n"
        "- **发现异常**：花穗亲自发现库房异常并取得可靠证据。\n"
        "- **核对账册**：裴砚行与花穗核对账册并锁定经手人。\n"
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)
    first_id, second_id = [item["id"] for item in contracts]
    original = two_segment_plan(first_id, second_id, repaired=False)
    whole_calls = 0
    planning_prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        nonlocal whole_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review" and "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            whole_calls += 1
            value = json.loads(whole_adaptation_receipt(prompt, valid=whole_calls > 1))
            if whole_calls == 1:
                value["affected_segments"] = [1, 2]
                value["affected_event_ids"] = [first_id, second_id]
                value["reason"] = "第一段出口与第二段入口共同冲突，需要成对修正。"
            return json.dumps(value, ensure_ascii=False)
        if stage == "review":
            return adaptation_receipt(prompt, structural=False)
        planning_prompts.append(prompt)
        segment = int(prompt.split("EXPECTED SEGMENT: ", 1)[1].splitlines()[0])
        assert "第一段出口与第二段入口共同冲突，需要成对修正。" in prompt
        if segment == 1:
            return (
                "### 第 1 段：发现\n\n"
                f"事件ID：{first_id}\n\n"
                "大纲依据：发现异常\n\n"
                "段首承接：花穗正在调查账目缺口。\n\n"
                "本段事件：花穗亲自核验库房异常并取得可靠证据。\n\n"
                "段末交接：花穗已取得证据，准备与裴砚行核对账册。"
            )
        return (
            "### 第 2 段：核账\n\n"
            f"事件ID：{second_id}\n\n"
            "大纲依据：核对账册\n\n"
            "段首承接：花穗已取得证据，准备与裴砚行核对账册。\n\n"
            "本段事件：裴砚行与花穗核对账册并锁定经手人。\n\n"
            "段末交接：账目问题被确认，追查转向幕后经手人。"
        )

    service._stage = fake_stage
    plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 2,
    )

    assert changed is True
    assert artifact and artifact["status"] == "ready"
    assert [
        int(prompt.split("EXPECTED SEGMENT: ", 1)[1].splitlines()[0])
        for prompt in planning_prompts
    ] == [1, 2]
    assert "准备与裴砚行核对账册" in service._short_plan_segments(plan, 2)[0]
    assert "准备与裴砚行核对账册" in service._short_plan_segments(plan, 2)[1]


@pytest.mark.asyncio
async def test_v2_receipts_reuse_unaffected_segments_and_only_invalidate_neighbor_boundary(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    outline = (
        "## 第二幕\n\n### 第三章\n"
        "- **第一项**：主角完成第一项正式行动。\n"
        "- **第二项**：主角完成第二项正式行动。\n"
        "- **第三项**：主角完成第三项正式行动。\n"
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)
    event_ids = [item["id"] for item in contracts]
    original = three_segment_plan(event_ids)

    async def initial_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        return adaptation_receipt(prompt, structural=False)

    service._stage = initial_stage
    accepted, artifact, _changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 3, generation_context_sha256="context-v2",
    )
    assert accepted == original
    assert artifact and service._planning_adaptation_artifact_valid(
        artifact, state, original, [], 3, "context-v2",
    )
    stale_context = {**artifact, "generation_context_sha256": "old-context"}
    assert not service._planning_adaptation_artifact_valid(
        stale_context, state, original, [], 3, "context-v2",
    )

    segment_calls: list[int] = []
    whole_calls = 0

    async def changed_stage(*args, **kwargs):
        nonlocal whole_calls
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            whole_calls += 1
            return whole_adaptation_receipt(prompt)
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        segment_calls.append(segment)
        return adaptation_receipt(prompt, structural=False)

    service._stage = changed_stage
    body_only = three_segment_plan(
        event_ids, third_event="主角以新的场景表现完成第三项正式行动。",
    )
    _receipts, _whole, issues, _retries = await service._review_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        body_only, [], 3, suffix="body-only",
        generation_context_sha256="context-v2",
    )
    assert issues == []
    assert segment_calls == [3]
    assert whole_calls == 1

    segment_calls.clear()
    whole_calls = 0
    boundary_changed = three_segment_plan(
        event_ids,
        third_opening="第二项结果虽成立，但人物位置变化后第三项行动才可开始。",
        third_event="主角以新的场景表现完成第三项正式行动。",
    )
    _receipts, _whole, issues, _retries = await service._review_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        boundary_changed, [], 3, suffix="boundary-changed",
        generation_context_sha256="context-v2",
    )
    assert issues == []
    assert segment_calls == [2, 3]
    assert whole_calls == 1


@pytest.mark.asyncio
async def test_incomplete_targeted_repair_falls_back_to_complete_segment_rebuild(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "小厮报信后直接确认刘管事有罪。")
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review" and "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        if stage == "review":
            return adaptation_receipt(
                prompt, structural="亲自核验" not in prompt,
            )
        planning_calls += 1
        if "SHORT_PLAN_EQUIVALENCE_TARGETED_REPAIR_V2" in prompt:
            return "只返回了一句不完整修正"
        assert "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in prompt
        return plan_for(
            event_id,
            "小厮报信后，花穗追问细节并亲自核验库房异常，再决定继续查账。",
        )

    service._stage = fake_stage
    plan, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert "亲自核验" in plan
    assert artifact and artifact["status"] == "ready"
    assert artifact["semantic_repairs"] == 3
    assert planning_calls == 3
    events = service.db.list_run_events("adaptation-run")
    assert any(item["event_type"] == "planning_adaptation_segment_rebuild" for item in events)


@pytest.mark.asyncio
async def test_recovery_monotonically_reduces_seven_issues_to_one_then_zero(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "初始候选仍有多项结构偏移。")
    first = plan_for(event_id, "第一轮只剩视角问题。")
    final = plan_for(event_id, "第二轮保留第一人称并完成亲自核验。")
    invalid_sets = [
        {
            "event_function", "primary_actor_agency", "causal_dependencies",
            "entry_state", "exit_state", "knowledge_state", "viewpoint",
        },
        {"viewpoint"},
        set(),
    ]
    review_calls = 0
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal review_calls, planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review" and "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        if stage == "review":
            invalid = invalid_sets[review_calls]
            review_calls += 1
            return adaptation_receipt_with_invalid_invariants(prompt, invalid)
        planning_calls += 1
        return first if planning_calls == 1 else final

    service._stage = fake_stage
    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert accepted == final
    assert artifact and artifact["status"] == "ready"
    assert artifact["semantic_repairs"] == 2
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert [item["accepted"] for item in recovery["candidates"]] == [True, True]
    assert len(recovery["candidates"][0]["comparison"]["resolved_issue_keys"]) == 6
    assert recovery["best_issue_keys"] == []


@pytest.mark.asyncio
async def test_candidate_with_new_hard_issue_is_rejected_and_best_plan_is_restored(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "原规划只改变了主要执行者。")
    regressed = plan_for(event_id, "候选修正执行者，却提前改变结局承诺。")
    final = plan_for(event_id, "花穗亲自核验，结局承诺保持不变。")
    invalid_sets = [
        {"primary_actor_agency"},
        {"promise_ending"},
        set(),
    ]
    review_calls = 0
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal review_calls, planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review" and "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        if stage == "review":
            invalid = invalid_sets[review_calls]
            review_calls += 1
            return adaptation_receipt_with_invalid_invariants(prompt, invalid)
        planning_calls += 1
        if planning_calls == 1:
            return regressed
        assert "提前改变结局承诺" not in prompt
        assert "原规划只改变了主要执行者" in prompt
        return final

    service._stage = fake_stage
    accepted, artifact, _changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert accepted == final
    assert artifact and artifact["status"] == "ready"
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert [item["accepted"] for item in recovery["candidates"]] == [False, True]
    assert recovery["candidates"][0]["comparison"]["reason"] == "introduced_hard_issue"
    assert any(
        item["event_type"] == "planning_candidate_rejected_regression"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_initial_review_connection_failure_preserves_plan_for_next_task(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    original = plan_for(contracts[0]["id"], "花穗亲自核验库房异常。")

    async def fake_stage(*args, **kwargs):
        raise ConnectionError("temporary review connection failure")

    service._stage = fake_stage
    with pytest.raises(ConnectionError, match="temporary review"):
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 1, generation_context_sha256="context-v2",
        )

    assert (run_path / "outputs" / "planning-best.md").read_text(
        encoding="utf-8",
    ) == original
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert recovery["status"] == "review_pending"
    assert service._resumable_current_planning_adaptation_plan(
        run_path, project, state, 1, "context-v2",
    ) == (original, None, False)


@pytest.mark.asyncio
async def test_candidate_review_failure_never_promotes_unreviewed_plan(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "原规划改变了主要执行者。")
    unreviewed = plan_for(event_id, "尚未完成审核的修正候选。")
    segment_reviews = 0

    async def fake_stage(*args, **kwargs):
        nonlocal segment_reviews
        stage = args[3]
        prompt = args[5]
        if stage == "planning":
            return unreviewed
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            raise AssertionError("whole review must not start for an unreviewed segment")
        segment_reviews += 1
        if segment_reviews == 1:
            return adaptation_receipt_with_invalid_invariants(
                prompt, {"primary_actor_agency"},
            )
        raise ConnectionError("candidate review interrupted")

    service._stage = fake_stage
    with pytest.raises(ConnectionError, match="candidate review"):
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 1,
        )

    assert (run_path / "outputs" / "planning-best.md").read_text(
        encoding="utf-8",
    ) == original
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert recovery["best_issues"][0]["invalid_invariants"] == [
        "primary_actor_agency",
    ]
    assert recovery["candidates"] == []


def test_legacy_failed_run_reconstructs_targeted_segments_before_review(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    labels = ["收到密信", "夜探库房", "核对账册", "试探管事", "公开对质", "兑现承诺"]
    actions = [
        "花穗收到带有旧印记的密信，决定先核验来源而不惊动旁人。",
        "花穗趁夜进入库房检查封条，记录箱笼数量与搬运痕迹。",
        "裴砚行与花穗逐页核对账册，找出日期和签押不一致的条目。",
        "二人分别试探管事的口供，让对方在货物流向上暴露矛盾。",
        "花穗携带完整证据公开对质，迫使幕后经手人承认调包安排。",
        "真相公开后花穗兑现先前承诺，并保留继续追查上游势力的线索。",
    ]
    outline = "## 第二幕\n\n### 第三章\n" + "\n".join(
        f"- **{label}**：{action}" for label, action in zip(labels, actions, strict=True)
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)

    def block(number: int, event: str) -> str:
        contract = contracts[number - 1]
        label = labels[number - 1]
        action = actions[number - 1]
        return (
            f"### 第 {number} 段：{label}\n\n"
            f"事件ID：{contract['id']}\n\n"
            f"大纲依据：{label}\n\n"
            f"段首承接：第{number}段开始时，人物位置、知情范围与上一段结果均已明确。\n\n"
            f"本段事件：{action}{event}\n\n"
            f"段末交接：{label}的直接结果已经成立，并留下只供下一段继续处理的具体状态。"
        )

    original = "\n\n".join(
        block(number, f"原始第{number}段。") for number in range(1, 7)
    )
    assert service._short_plan_issues(project, state, original, 6) == []
    outputs = run_path / "outputs"
    (outputs / "planning.md").write_text(original, encoding="utf-8")
    (outputs / "planning-adaptations.json").write_text(
        json.dumps({
            "version": 1,
            "status": "failed",
            "outline_sha256": hashlib.sha256(outline.encode("utf-8")).hexdigest(),
            "planning_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "segment_count": 6,
            "segments": [],
            "whole_story_receipt": {},
            "issues": [{"code": "planning_structural_drift", "segment": 5}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    for number in (1, 3, 4, 5, 6):
        (outputs / f"planning-adaptation-segment-{number:02d}.md").write_text(
            block(number, f"定向修正后的第{number}段。"), encoding="utf-8",
        )

    resumed = service._resumable_current_planning_adaptation_plan(
        run_path, project, state, 6, "current-context",
    )

    assert resumed is not None
    recovered, causal_chain, legacy_context = resumed
    assert causal_chain is None
    assert legacy_context is True
    assert "定向修正后的第5段" in recovered
    assert "原始第2段" in recovered
    assert "planning-adaptation-full-rebuild" not in recovered


def test_execution_authority_binds_adaptation_and_uses_authorized_realization(
    tmp_path,
) -> None:
    service, project, _run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    plan = plan_for(
        event_id,
        "小厮先报信，花穗追问后亲自到库房复核，确认异常。",
    )
    plan_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    outline_sha = hashlib.sha256(
        state["outline"]["content"].encode("utf-8"),
    ).hexdigest()
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    evidence_id = next(
        key for key, value in candidates.items() if "本段事件" in value
    )
    receipt = {
        "authority_sha256": planning_adaptation_segment_authority_sha256(
            outline_sha256=outline_sha,
            planning_sha256=plan_sha,
            segment=1,
            event_contracts=contracts,
            plan_segment=plan,
            version=LEGACY_PLANNING_ADAPTATION_VERSION,
        ),
        "planning_sha256": plan_sha,
        "segment": 1,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "changed_dimensions": ["trigger_method"],
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "plan_evidence_ids": [evidence_id],
            "plan_evidence": [candidates[evidence_id]],
            "reason": "入口变化但人物主动性和结果保持。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "人物主动性、事件功能和后续状态保持。",
    }
    whole_authority = planning_adaptation_whole_authority_sha256(
        outline_sha256=outline_sha,
        planning_sha256=plan_sha,
        segment_receipts=[receipt],
        version=LEGACY_PLANNING_ADAPTATION_VERSION,
    )
    artifact = {
        "version": 1,
        "status": "ready",
        "outline_sha256": outline_sha,
        "planning_sha256": plan_sha,
        "segment_count": 1,
        "segments": [receipt],
        "whole_story_receipt": {
            "authority_sha256": whole_authority,
            "planning_sha256": plan_sha,
            "segment_numbers": [1],
            "event_ids": [event_id],
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
            "summary": "整篇因果、状态与结局保持。",
        },
        "protocol_repairs": 0,
        "semantic_repairs": 0,
        "issues": [],
    }
    chain = {"core_goal": "查清缺口", "ending": "证据成立"}

    hashes, authority, events = service._short_execution_authority(
        project, 1, state, "constraints", plan, chain, [], 1, artifact,
    )
    legacy_hashes, _legacy_authority, _legacy_events = service._short_execution_authority(
        project, 1, state, "constraints", plan, chain, [], 1,
    )

    assert hashes["authority_sha256"] != legacy_hashes["authority_sha256"]
    assert events[0]["source"] == "accepted_plan_adaptation"
    assert "小厮先报信" in events[0]["evidence"]
    assert events[0]["formal_evidence"] == contracts[0]["evidence"]
    assert "AUTHORIZED PLAN ADAPTATIONS" in authority

    invalid = {**artifact, "whole_story_receipt": {}}
    with pytest.raises(ValueError, match="规划等价展开回执"):
        service._short_execution_authority(
            project, 1, state, "constraints", plan, chain, [], 1, invalid,
        )
    contradictory = {**artifact, "issues": [{"code": "unresolved"}]}
    with pytest.raises(ValueError, match="规划等价展开回执"):
        service._short_execution_authority(
            project, 1, state, "constraints", plan, chain, [], 1,
            contradictory,
        )
