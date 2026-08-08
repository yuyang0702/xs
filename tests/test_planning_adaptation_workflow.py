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
    PLANNING_ADAPTATION_VERSION,
    PREVIOUS_PLANNING_ADAPTATION_VERSION,
    planning_adaptation_evidence_candidates,
    planning_adaptation_segment_authority_sha256,
    planning_adaptation_segment_packet_authority_sha256,
    planning_adaptation_whole_authority_sha256,
    planning_event_obligation_issues,
)
from novel_flywheel.planning_recovery import (
    new_planning_recovery_state,
    planning_candidate_comparison,
    record_planning_candidate,
    write_planning_recovery,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.workflows import (
    ContextCapacityPreflightError,
    GeneratedArtifactShapeError,
    PlanningRecoveryUnavailableError,
    StageText,
    WorkflowService,
)


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
        evidence_quote = candidates[evidence_id]
        reason = f"{evidence_quote}；规划把花穗的亲自发现和核实改成了小厮直接确认。"
    else:
        evidence_quote = ""
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
            "plan_evidence_quote": evidence_quote,
            "reason": reason,
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": reason,
    }, ensure_ascii=False)


def test_capacity_packet_authority_is_bound_to_parent_segment_and_event_scope() -> None:
    parent = planning_adaptation_segment_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=1,
        event_contracts=[{"id": "EV-1"}, {"id": "EV-2"}],
        plan_segment="segment",
    )
    first = planning_adaptation_segment_packet_authority_sha256(
        segment_authority_sha256=parent, segment=1, event_ids=["EV-1"],
    )
    second = planning_adaptation_segment_packet_authority_sha256(
        segment_authority_sha256=parent, segment=1, event_ids=["EV-2"],
    )
    assert first != second
    assert first != planning_adaptation_segment_packet_authority_sha256(
        segment_authority_sha256="c" * 64, segment=1, event_ids=["EV-1"],
    )


def whole_adaptation_receipt(prompt: str, *, valid: bool = True) -> str:
    authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
    planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
    segments = json.loads(
        prompt.split("EXPECTED SEGMENTS:\n", 1)[1].splitlines()[0]
    )
    event_ids = json.loads(
        prompt.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
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


def hierarchy_adaptation_receipt(
    prompt: str, *, invalid_field: str = "",
) -> str:
    source_sha256 = prompt.split("SOURCE SHA256: ", 1)[1].splitlines()[0]
    segments = json.loads(
        prompt.split("EXPECTED SEGMENTS: ", 1)[1].splitlines()[0]
    )
    event_ids = json.loads(
        prompt.split("EXPECTED EVENT IDS: ", 1)[1].splitlines()[0]
    )
    values = {
        field: field != invalid_field
        for field in (
            "causal_order_preserved", "adjacent_handoffs_preserved",
            "knowledge_progression_preserved", "relationship_progression_preserved",
            "viewpoint_timeline_preserved", "promises_ending_preserved",
            "formal_direction_preserved",
        )
    }
    return json.dumps({
        "source_sha256": source_sha256,
        "segment_numbers": segments,
        "event_ids": event_ids,
        **values,
        "affected_segments": [segments[0]] if invalid_field else [],
        "affected_event_ids": [event_ids[0]] if invalid_field else [],
        "entry_state": "输入范围从上一个已验证状态开始。",
        "exit_state": "输入范围在当前末尾形成可继续使用的状态。",
        "knowledge_state": "人物知情范围按正式事件顺序推进。",
        "relationship_state": "人物关系没有越过正式事件授权。",
        "viewpoint_timeline": "视角与时间顺序保持连续。",
        "open_promises": ["尚未到期的承诺保持开放。"],
        "resolved_promises": [],
        "reason": "下层发现跨段因果偏移。" if invalid_field else "",
        "summary": "当前范围已完成无损审核。",
    }, ensure_ascii=False)


def test_planning_receipt_completeness_accepts_semantic_failure_but_not_truncation(
    tmp_path,
) -> None:
    service, _project, _run_path, _state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"].upper()
    segment_text = plan_for(event_id, "小厮确认异常，花穗没有亲自核验。")
    candidates = planning_adaptation_evidence_candidates(segment_text, 1)
    evidence_id = next(
        key for key, value in candidates.items() if "本段事件" in value
    )
    authority = "a" * 64
    planning = hashlib.sha256(segment_text.encode("utf-8")).hexdigest()
    invariants = {field: True for field in INVARIANT_FIELDS}
    invariants["primary_actor_agency"] = False
    evidence_quote = candidates[evidence_id]
    receipt = json.dumps({
        "authority_sha256": authority,
        "planning_sha256": planning,
        "segment": 1,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "structural",
            "changed_dimensions": ["primary_actor_agency"],
            "invariants": invariants,
            "plan_evidence_ids": [evidence_id],
            "plan_evidence_quote": evidence_quote,
            "reason": f"{evidence_quote}；当前规划改变了正式事件的主要执行者。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "回执完整，但发现主要执行者偏移。",
    }, ensure_ascii=False)

    check = lambda value: service._planning_adaptation_segment_receipt_complete(
        value,
        authority_sha256=authority,
        planning_sha256=planning,
        authority_version=PLANNING_ADAPTATION_VERSION,
        segment=1,
        expected_event_ids=[event_id],
        evidence_candidates=candidates,
        authority_event_ids=[event_id],
        plan_segment=segment_text,
        previous_handoff="opening",
        next_entry="ending",
    )

    assert check(receipt)
    assert not check(receipt[:-1])


def test_hierarchy_receipt_completeness_accepts_semantic_failure_but_not_truncation(
    tmp_path,
) -> None:
    service, _project, _run_path, _state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"].upper()
    prompt = (
        "SOURCE SHA256: " + "b" * 64 + "\n"
        "EXPECTED SEGMENTS: [1]\n"
        f"EXPECTED EVENT IDS: {json.dumps([event_id])}\n"
    )
    receipt = hierarchy_adaptation_receipt(
        prompt, invalid_field="causal_order_preserved",
    )
    check = lambda value: service._planning_hierarchy_receipt_complete(
        value,
        source_sha256="b" * 64,
        expected_segments=[1],
        expected_event_ids=[event_id],
    )

    assert check(receipt)
    assert not check(receipt[:-1])
    # The reduction path uses the same closed protocol while preserving lower
    # failures; proving it with inherited evidence covers that fourth boundary.
    inherited = [json.loads(receipt)]
    assert service._planning_hierarchy_receipt_complete(
        receipt,
        source_sha256="b" * 64,
        expected_segments=[1],
        expected_event_ids=[event_id],
        inherited=inherited,
    )


def test_whole_receipt_completeness_accepts_semantic_failure_but_not_truncation(
    tmp_path,
) -> None:
    service, _project, _run_path, _state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    prompt = (
        "EXPECTED AUTHORITY SHA256: " + "c" * 64 + "\n"
        "EXPECTED PLANNING SHA256: " + "d" * 64 + "\n"
        "EXPECTED SEGMENTS:\n[1]\n\n"
        f"EXPECTED EVENT IDS:\n{json.dumps([event_id])}\n"
    )
    receipt = whole_adaptation_receipt(prompt, valid=False)
    check = lambda value: service._planning_adaptation_whole_receipt_complete(
        value,
        authority_sha256="c" * 64,
        planning_sha256="d" * 64,
        authority_version=PLANNING_ADAPTATION_VERSION,
        segment_count=1,
        expected_event_ids=[event_id],
    )

    assert check(receipt)
    assert not check(receipt[:-1])


def test_planning_route_capacity_uses_smallest_configured_route_and_unknown_32k(
    tmp_path,
) -> None:
    service, _project, _run_path, _state, _contracts = make_service(tmp_path)
    for provider_id in ("large-provider", "small-provider"):
        service.db.save_provider(
            provider_id=provider_id,
            name=provider_id,
            protocol="openai",
            base_url="https://example.test",
            auth_type="bearer",
            timeout_seconds=180,
            extra_headers={},
        )
    service.db.save_model(
        model_id="large-review",
        provider_id="large-provider",
        display_name="Large review",
        model_name="large-review",
        context_window=131_072,
        max_output_tokens=16_384,
    )
    service.db.save_model(
        model_id="small-review",
        provider_id="small-provider",
        display_name="Small review",
        model_name="small-review",
        context_window=8_192,
        max_output_tokens=4_096,
    )
    service.db.save_role_binding(
        "review", "large-provider", "large-review",
        "small-provider", "small-review",
    )

    assert service._route_safe_context_window("review") == 131_072
    assert service._route_safe_context_window(
        "review", include_configured_fallback=True,
    ) == 8_192

    service.db.save_model(
        model_id="unknown-primary",
        provider_id="large-provider",
        display_name="Unknown primary",
        model_name="unknown-primary",
        context_window=None,
        max_output_tokens=None,
    )
    service.db.save_model(
        model_id="unknown-fallback",
        provider_id="small-provider",
        display_name="Unknown fallback",
        model_name="unknown-fallback",
        context_window=None,
        max_output_tokens=None,
    )
    service.db.save_role_binding(
        "planning", "large-provider", "unknown-primary",
        "small-provider", "unknown-fallback",
    )
    assert service._route_safe_context_window(
        "planning", include_configured_fallback=True,
    ) == 32_768


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
    if invalid:
        evidence_id = review["plan_evidence_ids"][0]
        candidates = json.loads(
            prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1].split(
                "\n\nRECEIPT PROTOCOL ISSUES:", 1,
            )[0]
        )
        review["plan_evidence_quote"] = candidates[evidence_id]
    review["reason"] = (
        review["plan_evidence_quote"] + "；候选仍改变了这些正式不变量："
        + "、".join(sorted(invalid))
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
async def test_production_composite_event_is_prechecked_rebuilt_and_fully_reviewed(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    outline = (
        "## 人物设定\n"
        "### 女主（花穗）\n"
        "### 男主（裴砚行）\n"
        "### 重要配角\n"
        "- **沈老夫人**：沈家主母\n"
        "- **沈大小姐**：名门闺秀\n\n"
        "## 章节规划\n"
        "### 第1章·入府\n- **入府试探**：花穗进入沈府接受审视。\n"
        "### 第2章·扎根\n- **建立人情**：花穗帮助下人建立人情网。\n"
        "### 第3章·查账\n- **查清旧账**：花穗亲自核对旧账。\n"
        "### 第4章·危机\n- **反制下毒**：花穗识破下毒并保护证据。\n"
        "### 第5章·选择\n- **众人的反应**：\n"
        "  - 沈老夫人认可花穗的担当。\n"
        "  - 沈大小姐站出来替花穗说话。\n"
        "  - 花穗追问裴砚行，他回应并公开承诺两人还有往后。\n"
        "### 第6章·扎根\n- **正式认下**：沈老夫人宣布正式认下花穗。\n"
    )
    state = {"outline": {"content": outline}}
    contracts = narrative_outline_event_contracts(outline)
    assert len(contracts) == 6
    reaction_id = next(
        item["id"] for item in contracts if item["label"] == "众人的反应"
    )

    segments: list[str] = []
    for segment, contract in enumerate(contracts, 1):
        event_id = str(contract["id"]).upper()
        event_text = {
            1: "花穗进入沈府接受众人审视。",
            2: "花穗帮助下人建立人情网。",
            3: "花穗亲自核对旧账并保留证据。",
            4: "花穗识破下毒并保护证据。",
            5: (
                f"4. **沈大小姐与沈老夫人的反应**（{event_id}）。"
                "沈老夫人认可花穗，沈大小姐也站出来替花穗说话。\n\n"
                "5. **花穗主动问裴砚行**。花穗追问裴砚行，"
                "裴砚行回应并承诺两人还有往后。"
            ),
            6: "沈老夫人宣布正式认下花穗。",
        }[segment]
        event_body = event_text if segment == 5 else f"{event_id}。{event_text}"
        segments.append(
            f"### 第 {segment} 段：正式段 {segment}\n\n"
            f"事件ID：{event_id}\n\n"
            f"大纲依据：{contract['label']}\n\n"
            f"段首承接：第 {segment} 段入口状态保持。\n\n"
            f"本段事件：{event_body}\n\n"
            f"段末交接：第 {segment} 段出口状态保持。"
        )
    original = "\n\n".join(segments)
    seeded_issue = {
        "code": "planning_structural_drift",
        "segment": 5,
        "event_id": reaction_id.upper(),
        "invalid_invariants": ["timeline_order"],
        "reason": "已知问题：不得提前消费下一事件的正式收认。",
    }
    recovery_state = new_planning_recovery_state(
        outline_sha256=hashlib.sha256(outline.encode("utf-8")).hexdigest(),
        generation_context_sha256="",
        segment_count=6,
        plan=original,
        issues=[seeded_issue],
    )
    write_planning_recovery(
        run_path / "outputs", recovery_state, original,
    )
    review_calls = 0
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal review_calls, planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "planning":
            planning_calls += 1
            assert "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in prompt
            assert "FORMAL EVENT COMPLETION CHECKLIST" in prompt
            assert "裴砚行" in prompt and "花穗" in prompt
            assert '"reaction"' in prompt and '"commitment"' in prompt
            assert seeded_issue["reason"] in prompt
            return (
                "### 第 5 段：正式段 5\n\n"
                f"事件ID：{reaction_id.upper()}\n\n"
                "大纲依据：众人的反应\n\n"
                "段首承接：第 5 段入口状态保持。\n\n"
                f"本段事件：{reaction_id.upper()}。沈老夫人认可花穗的担当，"
                "沈大小姐站出来替花穗说话；花穗追问裴砚行，"
                "裴砚行当众回应并承诺两人往后仍会并肩。\n\n"
                "段末交接：第 5 段出口状态保持。"
            )
        review_calls += 1
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        return adaptation_receipt(prompt, structural=False)

    service._stage = fake_stage
    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 6,
    )

    assert changed is True
    assert artifact and artifact["status"] == "ready"
    assert planning_calls == 0
    assert review_calls == 7
    accepted_segments = service._short_plan_segments(accepted, 6)
    original_segments = service._short_plan_segments(original, 6)
    assert [
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in accepted_segments[:4] + accepted_segments[5:]
    ] == [
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in original_segments[:4] + original_segments[5:]
    ]
    assert "裴砚行回应并承诺两人还有往后" in accepted_segments[4]
    events = service.db.list_run_events("adaptation-run")
    assert any(
        item["event_type"] == "planning_event_obligation_completed_locally"
        for item in events
    )
    assert not any(
        item["event_type"] == "planning_adaptation_targeted_repair"
        for item in events
    )
    assert not any(
        item["event_type"] == "planning_adaptation_segment_rebuild"
        for item in events
    )


@pytest.mark.asyncio
async def test_stale_negative_review_retries_receipt_without_planning_mutation(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        "花穗目送对方离开，不知道自己的反问是否被记住。",
    )
    segment_review_calls = 0
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal segment_review_calls, planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "planning":
            planning_calls += 1
            raise AssertionError("receipt protocol repair must not mutate planning")
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
            return whole_adaptation_receipt(prompt)
        segment_review_calls += 1
        if segment_review_calls == 1:
            payload = json.loads(adaptation_receipt(prompt, structural=False))
            review = payload["event_reviews"][0]
            review["classification"] = "structural"
            review["changed_dimensions"] = ["knowledge_state"]
            review["invariants"]["knowledge_state"] = False
            review["plan_evidence_quote"] = "却把花穗那句话记在心里"
            review["reason"] = "却把花穗那句话记在心里，说明对方已经认可花穗。"
            payload["summary"] = review["reason"]
            return json.dumps(payload, ensure_ascii=False)
        return adaptation_receipt(prompt, structural=False)

    service._stage = fake_stage
    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert accepted == original
    assert changed is False
    assert artifact and artifact["status"] == "ready"
    assert segment_review_calls == 2
    assert planning_calls == 0
    assert artifact["protocol_repairs"] == 1


@pytest.mark.asyncio
async def test_targeted_planning_patch_declares_bounded_capacity_contract(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    current_event = "小厮直接确认刘管事正在倒卖，花穗据此准备告发。"
    repaired_event = "小厮先报信，花穗亲自复核后再决定告发。"
    original = plan_for(event_id, current_event) + (
        "\n\n附加场景素材：" + "不属于本次授权锚点的既有描写。" * 800
    )
    candidates = planning_adaptation_evidence_candidates(original, 1)
    anchor_id = next(
        key for key, value in candidates.items() if current_event in value
    )
    issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": event_id,
        "invalid_invariants": ["primary_actor_agency", "knowledge_state"],
        "plan_evidence_ids": [anchor_id],
        "reason": "The plan lets the messenger complete the protagonist's discovery.",
    }]
    calls: list[dict] = []

    async def fake_stage(*args, **kwargs):
        calls.append(kwargs)
        prompt = args[5]
        assert kwargs["route_capacity_guard"] is True
        assert kwargs["bounded_protocol_output"] is True
        assert kwargs["compact_input"] is True
        assert kwargs["story_skeleton_override"]
        assert kwargs["expected_output_characters"] < len(original) // 2
        authority = prompt.split(
            "EXPECTED PATCH AUTHORITY SHA256: ", 1,
        )[1].splitlines()[0]
        anchors = json.loads(
            prompt.split("AUTHORIZED ORIGINAL ANCHORS:\n", 1)[1].split(
                "\n\nFORMAL EVENT CONTRACTS:", 1,
            )[0]
        )
        anchor = anchors[0]
        return json.dumps({
            "authority_sha256": authority,
            "segment": 1,
            "replacements": [{
                "evidence_id": anchor["evidence_id"],
                "source_sha256": anchor["source_sha256"],
                "replacement": anchor["text"].replace(
                    current_event, repaired_event,
                ),
            }],
            "summary": "Restore protagonist agency without changing event ownership.",
        }, ensure_ascii=False)

    service._stage = fake_stage
    candidate = await service._repair_short_plan_adaptation_segments(
        "adaptation-run", run_path, project, "constraints", state, original,
        [], 1, issues, mode="targeted", attempt=1,
    )

    assert repaired_event in candidate
    assert current_event not in candidate
    assert service._short_plan_event_ids(candidate) == [event_id.upper()]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_segment_rebuild_protocol_rewrap_stays_inside_same_semantic_attempt(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original_event = (
        f"1. **发现异常**（{event_id}）：花穗亲眼看见刘管事搬箱，"
        "随后亲自核实账目和库房记录。"
    )
    repaired_event = (
        f"1. **发现异常**（{event_id}）：花穗亲眼看见刘管事搬箱，"
        "她没有让报信者替自己判断，而是亲自核实账目、箱号和库房记录，"
        "最终取得可以继续追查的可靠证据。"
    )
    original = plan_for(event_id, original_event)
    issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": event_id,
        "invalid_invariants": ["primary_actor_agency"],
        "message": "当前计划把核实动作交给了报信者。",
    }]
    calls: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        calls.append(prompt.splitlines()[0])
        if prompt.startswith("SHORT_PLAN_CANONICAL_REWRAP_V1"):
            assert json.loads(
                prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                    "\n\nCURRENT AUTHORITY", 1,
                )[0]
            ) == [event_id.upper()]
            return plan_for(event_id, repaired_event).replace(
                "花穗正在调查账目缺口。", "错误入口状态。",
            ).replace(
                "花穗取得可以继续查账的可靠证据。", "错误出口状态。",
            )
        return (
            "<future-provider-envelope>\n"
            "<entry>花穗正在调查账目缺口。</entry>\n"
            f"<owned-event identity=\"{event_id}\">{repaired_event}</owned-event>\n"
            "<exit>花穗取得可以继续查账的可靠证据。</exit>\n"
            "</future-provider-envelope>"
        )

    service._stage = fake_stage
    candidate = await service._repair_short_plan_adaptation_segments(
        "adaptation-run", run_path, project, "constraints", state, original,
        contracts, 1, issues, mode="rebuild", attempt=1,
    )

    assert repaired_event in candidate
    assert "错误入口状态" not in candidate
    assert "错误出口状态" not in candidate
    assert len(calls) == 2
    assert calls[1] == "SHORT_PLAN_CANONICAL_REWRAP_V1"
    assert any(
        item["event_type"] == "planning_packet_protocol_retry"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_segment_rebuild_protocol_exhaustion_is_not_structure_drift(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        f"1. **发现异常**（{event_id}）：花穗亲自核实库房记录并取得证据。",
    )
    issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": event_id,
        "invalid_invariants": ["primary_actor_agency"],
        "message": "当前计划需要修复人物主动性。",
    }]
    calls = 0

    async def fake_stage(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "<unknown-machine-wrapper>still ambiguous</unknown-machine-wrapper>"

    service._stage = fake_stage
    with pytest.raises(
        GeneratedArtifactShapeError,
        match="planning packet protocol recovery exhausted",
    ) as caught:
        await service._repair_short_plan_adaptation_segments(
            "adaptation-run", run_path, project, "constraints", state, original,
            contracts, 1, issues, mode="rebuild", attempt=1,
        )

    assert calls == 2
    assert caught.value.issues[0]["code"] == "planning_packet_protocol_exhausted"
    assert any(
        item["event_type"] == "planning_packet_protocol_exhausted"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_protocol_exhaustion_does_not_consume_later_semantic_repair_budget(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        f"1. **发现异常**（{event_id}）：花穗亲自核实库房记录并取得证据。",
    )
    issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": event_id,
        "invalid_invariants": ["primary_actor_agency"],
        "message": "当前计划需要修复人物主动性。",
    }]
    repair_calls = 0

    async def fake_review(*_args, **_kwargs):
        return [], {}, issues, 0

    async def fake_repair(*_args, **_kwargs):
        nonlocal repair_calls
        repair_calls += 1
        if repair_calls == 1:
            raise GeneratedArtifactShapeError(
                "planning packet protocol recovery exhausted without one "
                "unambiguous canonical segment",
                issues=[{
                    "code": "planning_packet_protocol_exhausted",
                    "message": "protocol envelope remained ambiguous",
                }],
            )
        return original.replace(
            "花穗亲自核实库房记录并取得证据。",
            "花穗亲自核实库房记录、箱号和经手人证词并取得可靠证据。",
        )

    review_calls = 0

    async def fake_review(*_args, **_kwargs):
        nonlocal review_calls
        review_calls += 1
        return (
            [], {}, issues, 0
        ) if review_calls == 1 else ([{"event_reviews": []}], {}, [], 0)

    service._review_short_plan_adaptations = fake_review
    service._repair_short_plan_adaptation_segments = fake_repair
    repaired, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert "箱号和经手人证词" in repaired
    assert artifact["semantic_repairs"] == 1
    assert artifact["candidate_generation_attempts"] == 1
    assert repair_calls == 2
    rejected = [
        item for item in service.db.list_run_events("adaptation-run")
        if item["event_type"] == "planning_candidate_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0]["metadata"]["failure_class"] == "normal_invalid_output"


@pytest.mark.asyncio
async def test_unique_formal_obligation_is_completed_locally_before_model_rebuild(
    tmp_path, monkeypatch,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_obligation_protocol_recovery_12b59c6e.json").read_text(
             encoding="utf-8",
         )
    )
    state = {"outline": {"content": "formal outline authority"}}
    formal_events = [{
        "id": event_id,
        "label": event_id,
        "evidence": f"Formal evidence for {event_id}.",
    } for event_id in fixture["expected_event_ids"]]
    monkeypatch.setattr(
        "novel_flywheel.workflows.narrative_outline_event_contracts",
        lambda _content: formal_events,
    )
    monkeypatch.setattr(
        "novel_flywheel.workflows.narrative_outline_event_obligations",
        lambda _content: fixture["obligation_checklists"],
    )

    async def fake_review(
        _run_id, _run_path, _project, _constraints, _state, candidate,
        *_args, **_kwargs,
    ):
        assert fixture["required_excerpt"] in candidate
        assert "匿名信仍未交出" in candidate
        return [{"event_reviews": []}], {}, [], 0

    async def forbidden_stage(*_args, **_kwargs):
        raise AssertionError("deterministic obligation completion must not call a model")

    service._review_short_plan_adaptations = fake_review
    service._stage = forbidden_stage

    single_segment = fixture["current_segment"].replace("### 第 5 段", "### 第 1 段", 1)
    repaired, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        single_segment, formal_events, 1,
    )

    assert changed is True
    assert artifact["status"] == "ready"
    assert artifact["semantic_repairs"] == 0
    assert fixture["required_excerpt"] in repaired
    assert any(
        event["event_type"] == "planning_event_obligation_completed_locally"
        for event in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_semantic_body_collapse_does_not_trigger_protocol_rewrap(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        (
            f"1. **发现异常**（{event_id}）：花穗亲眼看见刘管事搬箱，"
            "随后亲自核实账目、箱号、库房记录和经手人证词，"
            "最终取得可以继续追查的可靠证据。"
        ),
    )
    issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": event_id,
        "message": "当前计划需要修复人物主动性。",
    }]
    calls = 0

    async def fake_stage(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return plan_for(event_id, f"1. **发现异常**（{event_id}）：花穗核实。")

    service._stage = fake_stage
    with pytest.raises(GeneratedArtifactShapeError) as caught:
        await service._repair_short_plan_adaptation_segments(
            "adaptation-run", run_path, project, "constraints", state, original,
            contracts, 1, issues, mode="rebuild", attempt=1,
        )

    assert calls == 1
    assert any(
        item["code"] == "event_body_collapsed"
        for item in caught.value.issues
    )
    assert not any(
        item["event_type"] == "planning_packet_protocol_retry"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.parametrize("obligation_variant", [
    (
        "沈老夫人认可花穗，沈大小姐维护花穗；花穗追问裴砚行，"
        "裴砚行当众回应并给出往后承诺。"
    ),
    (
        "花穗把问题抛给裴砚行，裴砚行没有回避，公开确认二人的关系；"
        "沈大小姐替花穗说话，沈老夫人也表示认可花穗。"
    ),
    (
        "“我认她。”沈老夫人说。沈大小姐随即维护花穗；"
        "花穗追问后，裴砚行正面回应，公开承诺由此成立。"
    ),
    (
        "沈大小姐挡在花穗身前，沈老夫人认可花穗的担当。"
        "花穗转向裴砚行求证，裴砚行当众作答并承诺共同面对。"
    ),
    (
        "裴砚行先回应花穗并明确今后的关系，花穗确认他的选择；"
        "随后沈大小姐维护花穗，沈老夫人正式认可花穗。"
    ),
    (
        "沈老夫人认可花穗，沈大小姐维护花穗；花穗问，裴砚行答，"
        "二人的公开关系承诺落定。"
    ),
])
@pytest.mark.asyncio
async def test_segment_rebuild_capacity_split_repairs_event_owned_packets_and_merges(
    tmp_path, monkeypatch, obligation_variant: str,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures"
         / "planning_event_obligation_incomplete_9946d29b.json")
        .read_text(encoding="utf-8")
    )
    event_ids = fixture["segment_event_ids"]
    formal_events = [{
        "id": event_id,
        "label": f"formal event {index}",
        "evidence": f"The protagonist completes formal event {index} in order.",
    } for index, event_id in enumerate(event_ids, 1)]
    state = {"outline": {"content": "production-shaped outline authority"}}
    obligation_checklists = {
        event_ids[2]: {
            "event_id": event_ids[2],
            "label": "众人的反应",
            "required_participants": [
                "沈老夫人", "沈大小姐", "花穗", "裴砚行",
            ],
            "identity_stable_participants": [
                "沈老夫人", "沈大小姐", "花穗", "裴砚行",
            ],
            "obligations": [{
                "id": f"{event_ids[2]}-B01",
                "kinds": ["reaction", "commitment", "outcome"],
                "required_participants": [
                    "沈老夫人", "沈大小姐", "花穗", "裴砚行",
                ],
                "source_excerpt": "；".join(fixture["formal_requirements"]),
            }],
        },
    }
    monkeypatch.setattr(
        "novel_flywheel.workflows.narrative_outline_event_obligations",
        lambda _content: obligation_checklists,
    )
    original = (
        "### 第 1 段：公开承认\n\n"
        f"事件ID：{'、'.join(event_ids)}\n\n"
        "大纲依据：身份公开与关系承诺。\n\n"
        "段首承接：核验人员进入正厅。\n\n"
        "本段事件：\n"
        + "\n".join(
            f"{index}. **旧事件 {index}**（{event_id}）："
            f"当前规划完成第 {index} 项动作、回应与结果。"
            for index, event_id in enumerate(event_ids, 1)
        )
        + "\n\n段末交接：众人完成公开承认并进入新的关系状态。"
    )
    issues = [{
        "code": "planning_required_participant_missing",
        "segment": 1,
        "event_id": event_ids[2],
        "invalid_invariants": ["primary_actor_agency", "relationship_state"],
        "message": "The third composite event omitted one required responder.",
    }]
    packet_calls: list[list[str]] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        if prompt.startswith("SHORT_PLAN_CANONICAL_REWRAP_V1"):
            owned = json.loads(
                prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                    "\n\nCURRENT AUTHORITY", 1,
                )[0]
            )
            return (
                "### 第 1 段：公开承认\n\n"
                f"事件ID：{owned[0]}\n\n"
                "大纲依据：身份公开与关系承诺。\n\n"
                "段首承接：核验人员进入正厅。\n\n"
                f"本段事件：1. **修复事件**（{owned[0]}）："
                "花穗完成正式动作，相关人物作出回应并形成可核对结果。\n\n"
                "段末交接：当前事件完成并交给下一事件。"
            )
        if "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_PACKET_V1" not in prompt:
            splitter = kwargs.get("capacity_splitter")
            assert splitter is not None
            return await splitter({
                "pressure": fixture["capacity_preflight"]["topology"],
                "estimated_input_tokens": fixture["capacity_preflight"][
                    "required_tokens"
                ] - 3_860,
                "authority_input_tokens": 21_400,
                "output_reserve": 3_860,
                "context_window": fixture["capacity_preflight"]["context_window"],
            })

        owned = json.loads(
            prompt.split("EXPECTED PACKET EVENT IDS:\n", 1)[1].split(
                "\n\nPARENT SEGMENT EVENT IDS:", 1,
            )[0]
        )
        if len(owned) > 1:
            splitter = kwargs.get("capacity_splitter")
            assert splitter is not None
            split = await splitter({
                "pressure": "split",
                "estimated_input_tokens": 24_100,
                "authority_input_tokens": 21_200,
                "output_reserve": 2_900,
                "context_window": 32_768,
            })
            return StageText(split, {"execution_mode": "capacity_split"})
        projection = prompt.split(
            "CURRENT EVENT-OWNED PLAN PROJECTION:\n", 1,
        )[1].split("\n\nPreserve event function", 1)[0]
        assert owned[0] in projection
        assert all(
            sibling not in projection for sibling in event_ids
            if sibling not in owned
        )
        packet_calls.append(owned)
        if owned[0] == event_ids[0]:
            return json.dumps({
                "segment_id": 1,
                "packet_event_ids": owned,
                "plan_projection": {
                    "segment_label": "第 1 段：公开承认",
                    "entry_handoff": "核验人员进入正厅。",
                    "future_event_rows": [{
                        "event_id": owned[0],
                        "label": "修复事件",
                        "description": (
                            "花穗完成正式动作，相关人物作出回应并形成可核对结果。"
                        ),
                        "critical_path": {
                            "event_function": "完成当前正式事件并交给下一事件。",
                            "agency": "花穗保持主要执行者身份。",
                        },
                    }],
                    "exit_handoff": "首个事件完成并交给下一事件。",
                },
            }, ensure_ascii=False)
        if owned[0] == event_ids[1]:
            return (
                "<provider-plan-capsule>\n"
                "<entry>核验人员进入正厅。</entry>\n"
                f"<owned identity=\"{owned[0]}\">"
                "花穗完成正式动作，相关人物作出回应并形成可核对结果。"
                "</owned>\n"
                "<exit>当前事件完成并交给下一事件。</exit>\n"
                "</provider-plan-capsule>"
            )
        if owned[0] == event_ids[2]:
            return (
                "# 第 1 段：公开承认\n\n"
                f"**事件ID**：{owned[0]}\n\n"
                "**大纲依据**：身份公开与关系承诺。\n\n"
                "## 段首承接\n\n> 核验人员进入正厅。\n\n"
                "## 本段事件\n\n"
                f"### 1. 修复事件（{owned[0]}）\n\n"
                f"{obligation_variant}\n\n"
                "## 段末交接\n\n> 当前事件完成并交给下一事件。\n\n"
                "## 诊断附录\n\n这部分不得进入段末交接。"
            )
        if owned[0] == event_ids[3]:
            return json.dumps({
                "segment_index": 1,
                "event_ids": owned,
                "plan_blocks": [{
                    "event_id": owned[0],
                    "narrative_summary": (
                        "花穗完成正式动作，相关人物作出回应并形成可核对结果。"
                    ),
                    "causal_entry": {
                        "immediate_trigger": "上一事件已经形成可核对结果。",
                    },
                    "narrative_body": {
                        "primary_action": "花穗继续完成当前正式事件。",
                        "result": "相关人物回应并确认结果。",
                    },
                    "causal_exit": {
                        "handoff_to_next_segment": (
                            "众人完成公开承认并进入新的关系状态。"
                        ),
                    },
                    "structural_compliance": {
                        "entry_state": "上一事件已经形成可核对结果。",
                        "exit_state": "众人完成公开承认并进入新的关系状态。",
                    },
                }],
            }, ensure_ascii=False)
        body = "\n".join(
            f"{index}. **修复事件**（{event_id}）："
            + (
                obligation_variant if event_id == event_ids[2]
                else "花穗完成正式动作，相关人物作出回应并形成可核对结果。"
            )
            for index, event_id in enumerate(owned, 1)
        )
        heading = "### 第 1 段：公开承认"
        return (
            f"{heading}\n\n"
            f"事件ID：{'、'.join(owned)}\n\n"
            "大纲依据：身份公开与关系承诺。\n\n"
            "段首承接：核验人员进入正厅。\n\n"
            f"本段事件：\n{body}\n\n"
            "段末交接：众人完成公开承认并进入新的关系状态。"
        )

    service._stage = fake_stage
    repaired = await service._repair_short_plan_adaptation_segments(
        "adaptation-run", run_path, project, "constraints", state, original,
        formal_events, 1, issues, mode="rebuild", attempt=1,
    )

    assert service._short_plan_event_ids(repaired) == event_ids
    assert sorted(event_id for packet in packet_calls for event_id in packet) == sorted(
        event_ids
    )
    assert packet_calls == [[event_id] for event_id in event_ids]
    assert all("修复事件" in repaired for _event_id in event_ids)
    assert all(name in repaired for name in fixture["observed_missing"])
    assert planning_event_obligation_issues(
        repaired, event_ids, obligation_checklists,
    ) == []
    assert "段末交接：众人完成公开承认并进入新的关系状态。" in repaired

    first_packet_calls = list(packet_calls)
    repaired_again = await service._repair_short_plan_adaptation_segments(
        "adaptation-run", run_path, project, "constraints", state, original,
        formal_events, 1, issues, mode="rebuild", attempt=1,
    )
    assert repaired_again == repaired
    assert packet_calls == first_packet_calls
    assert any(
        event["event_type"] == "planning_repair_packet_checkpoint_reused"
        for event in service.db.list_run_events("adaptation-run")
    )
    assert any(
        event["event_type"] == "planning_packet_protocol_recovered"
        for event in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_production_shape_collapsed_event_patch_is_rejected_then_recovers(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original_event = (
        f"3. **井边嗑瓜子**（{event_id}）。沈蕙兰撞见花穗和洗衣婆子聊天，"
        "双方当场争论门风，花穗用市井逻辑反问，洗衣婆子们的反应推动沈蕙兰重新观察她。"
    )
    repaired_event = original_event.replace(
        "洗衣婆子们的反应推动沈蕙兰重新观察她",
        "花穗只看见沈蕙兰拂袖而去，无法知道她心里如何评价",
    )
    original = (
        "### 第 1 段：井边冲突\n\n"
        f"事件ID：{event_id}\n\n"
        "大纲依据：发现异常\n\n"
        "段首承接：花穗进入后院。\n\n"
        f"本段事件：\n{original_event}\n\n"
        "段末交接：裴砚行开始重新观察花穗。"
    )
    planning_calls = 0
    repair_anchor_ids_seen: list[str] = []

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review":
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
                return whole_adaptation_receipt(prompt)
            authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
            planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
            segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
            candidates = json.loads(
                prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1].split(
                    "\n\nRECEIPT PROTOCOL ISSUES:", 1,
                )[0]
            )
            evidence_id = max(
                (
                    (key, value) for key, value in candidates.items()
                    if "3. **井边嗑瓜子**" in value and event_id in value
                ),
                key=lambda item: len(item[1]),
            )[0]
            invalid = repaired_event not in prompt
            invariants = {field: True for field in INVARIANT_FIELDS}
            if invalid:
                invariants["viewpoint"] = False
            evidence_quote = candidates[evidence_id] if invalid else ""
            return json.dumps({
                "authority_sha256": authority,
                "planning_sha256": planning,
                "segment": segment,
                "event_reviews": [{
                    "event_id": event_id,
                    "classification": "structural" if invalid else "equivalent",
                        "changed_dimensions": ["viewpoint"] if invalid else [],
                    "invariants": invariants,
                    "plan_evidence_ids": [evidence_id],
                    "plan_evidence_quote": evidence_quote,
                    "reason": (
                        f"{evidence_quote}；末尾越过第一人称认知。"
                        if invalid else "已恢复限知表达。"
                    ),
                }],
                "segment_order_preserved": True,
                "formal_direction_preserved": True,
                "summary": "当前正式事件已完成审核。",
            }, ensure_ascii=False)

        planning_calls += 1
        if "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in prompt:
            return original.replace(original_event, repaired_event)
        authority = prompt.split(
            "EXPECTED PATCH AUTHORITY SHA256: ", 1,
        )[1].splitlines()[0]
        anchors = json.loads(
            prompt.split("AUTHORIZED ORIGINAL ANCHORS:\n", 1)[1].split(
                "\n\nFORMAL EVENT CONTRACTS:", 1,
            )[0]
        )
        anchor = next(
            item for item in anchors
            if original_event in item.get("text", "")
        )
        repair_anchor_ids_seen.append(anchor["evidence_id"])
        replacement = anchor["text"].replace(
            original_event,
            (
                f"3. **井边嗑瓜子**（{event_id}）。沈蕙兰拂袖而去。"
                if planning_calls == 1 else repaired_event
            ),
        )
        return json.dumps({
            "authority_sha256": authority,
            "segment": 1,
            "replacements": [{
                "evidence_id": anchor["evidence_id"],
                "source_sha256": anchor["source_sha256"],
                "replacement": replacement,
            }],
                "summary": "只修复越过叙述者认知的末尾。",
            }, ensure_ascii=False)

    service._stage = fake_stage
    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert repaired_event in accepted
    assert "沈蕙兰拂袖而去。\n\n段末交接" not in accepted
    assert artifact["status"] == "ready"
    assert planning_calls == 2
    assert repair_anchor_ids_seen == ["PLAN-01-E005", "PLAN-01-E005"]
    rejected = [
        item for item in service.db.list_run_events("adaptation-run")
        if item["event_type"] == "planning_candidate_rejected"
    ]
    assert rejected
    assert "formal event set or required segment fields" in (
        rejected[0]["metadata"]["error"]
    )


@pytest.mark.asyncio
async def test_targeted_planning_recovery_continues_after_preflight_rejection(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        "小厮直接确认刘管事正在倒卖，花穗据此准备告发。",
    )
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review":
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
                return whole_adaptation_receipt(prompt)
            return adaptation_receipt(
                prompt, structural="亲自到库房复核" not in prompt,
            )
        planning_calls += 1
        if planning_calls == 1:
            raise ContextCapacityPreflightError(
                pressure="split",
                estimated_input_tokens=20_407,
                authority_input_tokens=18_514,
                output_reserve=12_288,
                context_window=32_768,
            )
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
    assert planning_calls == 2
    rejected = [
        item for item in service.db.list_run_events("adaptation-run")
        if item["event_type"] == "planning_candidate_rejected"
    ]
    assert rejected
    assert rejected[0]["metadata"]["reason"] == "candidate_generation_failed"


@pytest.mark.asyncio
async def test_planning_recovery_reports_route_unavailable_separately_from_semantic_drift(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(
        event_id,
        "the planning candidate changes the confirmed actor and causal result",
    )
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review":
            return adaptation_receipt(prompt, structural=True)
        planning_calls += 1
        raise ValueError("missing_api_key: planning-primary")

    service._stage = fake_stage
    with pytest.raises(PlanningRecoveryUnavailableError) as caught:
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 1,
        )

    assert planning_calls == 4
    assert caught.value.execution_failures
    assert all(
        item["failure_class"] == "provider_rejection"
        for item in caught.value.execution_failures
    )
    assert any(
        item["event_type"] == "planning_adaptation_unavailable"
        for item in service.db.list_run_events("adaptation-run")
    )
    artifact = json.loads(
        (run_path / "outputs" / "planning-adaptations.json").read_text(
            encoding="utf-8",
        )
    )
    assert artifact["status"] == "failed"
    assert artifact["execution_failures"]


@pytest.mark.asyncio
async def test_historical_route_failure_does_not_poison_current_protocol_exhaustion(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "花穗亲自核验库房异常，准备继续追查。")
    outline_content = state["outline"]["content"]
    seeded = new_planning_recovery_state(
        outline_sha256=hashlib.sha256(outline_content.encode("utf-8")).hexdigest(),
        generation_context_sha256="",
        segment_count=1,
        plan=original,
        issues=[],
    )
    seeded["execution_failures"] = [{
        "failure_class": "provider_rejection",
        "error": "missing_api_key from an earlier run",
    }]
    write_planning_recovery(run_path / "outputs", seeded, original)

    async def fake_stage(*args, **kwargs):
        stage = args[3]
        prompt = args[5]
        if stage == "review":
            return adaptation_receipt(prompt, structural=True)
        return "not a planning packet"

    service._stage = fake_stage
    with pytest.raises(
        GeneratedArtifactShapeError,
        match="planning packet protocol recovery exhausted",
    ) as caught:
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 1,
        )

    assert not isinstance(caught.value, PlanningRecoveryUnavailableError)
    events = service.db.list_run_events("adaptation-run")
    assert not any(
        item["event_type"] == "planning_adaptation_unavailable"
        for item in events
    )
    assert not any(
        item["event_type"] == "planning_adaptation_failed"
        for item in events
    )
    assert any(
        item["event_type"] == "planning_packet_protocol_exhausted"
        for item in events
    )


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


def test_ready_v2_artifact_remains_readable_after_v3_upgrade(tmp_path) -> None:
    service, _project, _run_path, state, contracts = make_service(tmp_path)
    plan = plan_for(contracts[0]["id"], "花穗亲自核验库房异常。")
    planning_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    outline_sha = hashlib.sha256(
        state["outline"]["content"].encode("utf-8"),
    ).hexdigest()
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    evidence_id = next(
        key for key, value in candidates.items() if "本段事件" in value
    )
    authority = planning_adaptation_segment_authority_sha256(
        outline_sha256=outline_sha,
        planning_sha256=planning_sha,
        segment=1,
        event_contracts=contracts,
        plan_segment=plan,
        previous_handoff="opening",
        next_entry="ending",
        generation_context_sha256="context-v2",
        version=PREVIOUS_PLANNING_ADAPTATION_VERSION,
    )
    receipt = {
        "authority_sha256": authority,
        "planning_sha256": planning_sha,
        "segment": 1,
        "event_reviews": [{
            "event_id": contracts[0]["id"],
            "classification": "equivalent",
            "changed_dimensions": ["dialogue"],
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "plan_evidence_ids": [evidence_id],
            "plan_evidence": [candidates[evidence_id]],
            "reason": "仅调整场景呈现。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "正式事件保持不变。",
    }
    whole_authority = planning_adaptation_whole_authority_sha256(
        outline_sha256=outline_sha,
        planning_sha256=planning_sha,
        segment_receipts=[receipt],
        version=PREVIOUS_PLANNING_ADAPTATION_VERSION,
    )
    artifact = {
        "version": PREVIOUS_PLANNING_ADAPTATION_VERSION,
        "status": "ready",
        "outline_sha256": outline_sha,
        "planning_sha256": planning_sha,
        "segment_count": 1,
        "generation_context_sha256": "context-v2",
        "segments": [receipt],
        "whole_story_receipt": {
            "authority_sha256": whole_authority,
            "planning_sha256": planning_sha,
            "segment_numbers": [1],
            "event_ids": [contracts[0]["id"]],
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
            "summary": "整篇结构保持不变。",
        },
        "issues": [],
    }

    assert service._planning_adaptation_artifact_valid(
        artifact, state, plan, [], 1, "context-v2",
    )


def test_cross_task_resume_copies_complete_rejected_candidate_ledger(tmp_path) -> None:
    service, project, old_run_path, state, contracts = make_service(tmp_path)
    plan = plan_for(contracts[0]["id"], "花穗亲自核验库房异常。")
    outline_sha = hashlib.sha256(
        state["outline"]["content"].encode("utf-8"),
    ).hexdigest()
    initial_issues = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": contracts[0]["id"],
        "invalid_invariants": ["primary_actor_agency"],
        "message": "原候选改变主要执行者",
    }]
    regressed = [{
        "code": "planning_structural_drift",
        "segment": 1,
        "event_id": contracts[0]["id"],
        "invalid_invariants": ["promise_ending"],
        "message": "被拒候选提前消费结局",
    }]
    recovery = new_planning_recovery_state(
        outline_sha256=outline_sha,
        generation_context_sha256="context-v3",
        segment_count=1,
        plan=plan,
        issues=initial_issues,
    )
    comparison = planning_candidate_comparison(initial_issues, regressed)
    recovery = record_planning_candidate(
        recovery, plan="rejected candidate", issues=regressed,
        comparison=comparison, source="targeted-2", accepted=False,
    )
    write_planning_recovery(old_run_path / "outputs", recovery, plan)
    service.db.update_run("adaptation-run", "failed", error="recoverable")
    service.db.create_run("resume-run", project.id, "short-story", status="running")
    new_run_path = project.path / "runs" / "resume-run"
    (new_run_path / "outputs").mkdir(parents=True)

    resumed = service._resumable_current_planning_adaptation_plan(
        new_run_path, project, state, 1, "context-v3",
    )

    assert resumed == (plan, None, False)
    copied = json.loads(
        (new_run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    assert copied["candidates"][0]["introduced_issues"][0]["message"] == (
        "被拒候选提前消费结局"
    )


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
async def test_v3_receipts_reuse_unaffected_segments_and_leave_boundary_to_whole_review(
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
    stale_boundary = json.loads(json.dumps(artifact, ensure_ascii=False))
    stale_boundary["segments"][0]["boundary_sha256"] = "0" * 64
    assert not service._planning_adaptation_artifact_valid(
        stale_boundary, state, original, [], 3, "context-v2",
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
    assert segment_calls == [3]
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
    assert artifact["semantic_repairs"] == 1
    assert artifact["candidate_generation_attempts"] == 2
    assert planning_calls == 3
    events = service.db.list_run_events("adaptation-run")
    assert any(item["event_type"] == "planning_adaptation_segment_rebuild" for item in events)


@pytest.mark.asyncio
async def test_rejected_rebuild_gets_one_bounded_retry_from_latest_best_segment(
    tmp_path,
) -> None:
    service, project, run_path, state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    original = plan_for(event_id, "候选仍把执行者和知情顺序写错。")
    planning_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal planning_calls
        stage = args[3]
        prompt = args[5]
        if stage == "review":
            if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt:
                return whole_adaptation_receipt(prompt)
            if "REBUILD-RETRY-GOOD" in prompt:
                return adaptation_receipt_with_invalid_invariants(prompt, set())
            if "REBUILD-RETRY-BAD" in prompt:
                return adaptation_receipt_with_invalid_invariants(
                    prompt, {"event_function", "promise_ending"},
                )
            return adaptation_receipt_with_invalid_invariants(
                prompt, {"event_function"},
            )
        planning_calls += 1
        if "SHORT_PLAN_EQUIVALENCE_TARGETED_REPAIR_V2" in prompt:
            return "只返回不完整的定向修正"
        assert "SHORT_PLAN_EQUIVALENCE_SEGMENT_REBUILD_V2" in prompt
        if planning_calls == 3:
            return plan_for(
                event_id, "第一轮重建修掉旧问题但留下新的结局问题。"
            ) + "\n\nREBUILD-RETRY-BAD"
        assert planning_calls == 4
        assert "REJECTED CANDIDATE NO-REGRESSION FEEDBACK" in prompt
        return plan_for(
            event_id, "第二轮重建保留正式执行者、因果和结局边界。"
        ) + "\n\nREBUILD-RETRY-GOOD"

    service._stage = fake_stage
    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 1,
    )

    assert changed is True
    assert artifact and artifact["status"] == "ready"
    assert "第二轮重建" in accepted
    assert planning_calls == 4
    recovery = json.loads((
        run_path / "outputs" / "planning-recovery-state.json"
    ).read_text(encoding="utf-8"))
    rebuilds = [
        item for item in recovery["candidates"]
        if item["source"].startswith("rebuild-")
    ]
    assert [item["accepted"] for item in rebuilds] == [False, True]
    assert any(
        item["comparison"]["reason"] == "introduced_hard_issue"
        for item in rebuilds
    )


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
        assert "REJECTED CANDIDATE NO-REGRESSION FEEDBACK" in prompt
        assert "提前改变结局承诺" in prompt
        current_best = prompt.rsplit("CURRENT PLAN SEGMENT:\n", 1)[1]
        assert "提前改变结局承诺" not in current_best
        assert "原规划只改变了主要执行者" in current_best
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
async def test_recovery_accepts_fixed_segment_then_repairs_newly_seen_latent_segment(
    tmp_path, monkeypatch,
) -> None:
    fixture = json.loads((
        Path(__file__).parent / "fixtures" /
        "planning_latent_issue_attribution_62859567.json"
    ).read_text(encoding="utf-8"))
    service, project, run_path, state, _contracts = make_service(tmp_path)
    event_ids = ["EV-LATENT-1", "EV-5306BA80", "EV-221A4437"]
    original = three_segment_plan(event_ids)
    segment_two = service._short_plan_segments(original, 3)[1]
    original = service._replace_short_plan_segment(
        original, 3, 2, segment_two + "\n\nRECOVERY-MARKER: pending-2",
    )
    segment_three = service._short_plan_segments(original, 3)[2]
    original = service._replace_short_plan_segment(
        original, 3, 3, segment_three + "\n\nRECOVERY-MARKER: latent-3",
    )
    contracts = [
        {"id": event_id, "order": index, "evidence": f"evidence-{index}"}
        for index, event_id in enumerate(event_ids, 1)
    ]
    review_calls = 0

    async def review(*args, **kwargs):
        nonlocal review_calls
        review_calls += 1
        candidate = args[5]
        blocks = service._short_plan_segments(candidate, 3)
        if review_calls == 1:
            assert "pending-2" in blocks[1]
            return ([{"segment": number} for number in range(1, 4)], {}, [{
                "code": "planning_structural_drift",
                "segment": 2,
                "event_id": event_ids[1],
                "invalid_invariants": ["viewpoint"],
            }], 0)
        if "latent-3" in blocks[2]:
            assert "fixed-2" in blocks[1]
            return ([{"segment": number} for number in range(1, 4)], {}, [{
                "code": "planning_structural_drift",
                "segment": 3,
                "event_id": event_ids[2],
                "invalid_invariants": ["causal_dependencies"],
            }], 0)
        return ([{"segment": number} for number in range(1, 4)], {}, [], 0)

    repair_calls: list[tuple[int, ...]] = []
    accepted_segment_two = ""

    async def repair(*args, target_segments=None, **kwargs):
        nonlocal accepted_segment_two
        candidate = args[5]
        targets = tuple(target_segments or ())
        repair_calls.append(targets)
        for segment in targets:
            block = service._short_plan_segments(candidate, 3)[segment - 1]
            if segment == 2:
                replacement = block.replace("pending-2", "fixed-2")
                accepted_segment_two = replacement
            else:
                replacement = block.replace("latent-3", "fixed-3")
            candidate = service._replace_short_plan_segment(
                candidate, 3, segment, replacement,
            )
        return candidate

    monkeypatch.setattr(service, "_planning_adaptation_contracts", lambda *args: contracts)
    monkeypatch.setattr(service, "_review_short_plan_adaptations", review)
    monkeypatch.setattr(service, "_repair_short_plan_adaptation_segments", repair)
    monkeypatch.setattr(service, "_short_plan_issues", lambda *args: [])

    accepted, artifact, changed = await service._ensure_short_plan_adaptations(
        "adaptation-run", run_path, project, "constraints", state,
        original, [], 3,
    )

    assert changed is True
    assert artifact and artifact["status"] == "ready"
    assert repair_calls == [
        (segment,) for segment in fixture["expected_recovery_units"]
    ]
    final_segments = service._short_plan_segments(accepted, 3)
    assert final_segments[1] == accepted_segment_two
    assert "fixed-3" in final_segments[2]
    recovery = json.loads((
        run_path / "outputs" / "planning-recovery-state.json"
    ).read_text(encoding="utf-8"))
    first_accept = next(
        item for item in recovery["candidates"] if item["accepted"]
    )
    assert first_accept["comparison"]["changed_segments"] == [2]
    assert first_accept["comparison"]["latent_baseline_issue_keys"] == [
        "planning:segment-03:EV-221A4437:invariant:causal_dependencies",
    ]
    assert any(
        item["event_type"] == "planning_latent_issues_discovered"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_multi_segment_recovery_keeps_independent_improvements_when_one_segment_regresses(
    tmp_path, monkeypatch,
) -> None:
    service, project, run_path, state, _contracts = make_service(tmp_path)
    event_ids = ["EV-GRANULAR-1", "EV-GRANULAR-2", "EV-GRANULAR-3"]
    original = three_segment_plan(event_ids)
    for segment in range(1, 4):
        block = service._short_plan_segments(original, 3)[segment - 1]
        original = service._replace_short_plan_segment(
            original, 3, segment, block + f"\n\nRECOVERY-MARKER: pending-{segment}",
        )
    contracts = [
        {"id": event_id, "order": index, "evidence": f"evidence-{index}"}
        for index, event_id in enumerate(event_ids, 1)
    ]

    def issues_for(candidate: str) -> list[dict]:
        values: list[dict] = []
        for segment in range(1, 4):
            block = service._short_plan_segments(candidate, 3)[segment - 1]
            if f"pending-{segment}" in block:
                values.append({
                    "code": "planning_structural_drift",
                    "segment": segment,
                    "event_id": event_ids[segment - 1],
                    "invalid_invariants": ["primary_actor_agency"],
                })
            if segment == 2 and "regressed-2" in block:
                values.append({
                    "code": "planning_structural_drift",
                    "segment": 2,
                    "event_id": event_ids[1],
                    "invalid_invariants": ["promise_ending"],
                })
        return values

    async def review(*args, **kwargs):
        candidate = args[5]
        return ([{"segment": number} for number in range(1, 4)], {}, issues_for(candidate), 0)

    repair_calls: list[tuple[int, ...]] = []

    async def repair(*args, target_segments=None, **kwargs):
        candidate = args[5]
        segments = tuple(target_segments or (1, 2, 3))
        repair_calls.append(segments)
        for segment in segments:
            block = service._short_plan_segments(candidate, 3)[segment - 1]
            replacement = (
                block.replace("pending-2", "regressed-2")
                if segment == 2 else
                block.replace(f"pending-{segment}", f"fixed-{segment}")
            )
            candidate = service._replace_short_plan_segment(
                candidate, 3, segment, replacement,
            )
        return candidate

    monkeypatch.setattr(service, "_planning_adaptation_contracts", lambda *args: contracts)
    monkeypatch.setattr(service, "_review_short_plan_adaptations", review)
    monkeypatch.setattr(service, "_repair_short_plan_adaptation_segments", repair)
    monkeypatch.setattr(service, "_short_plan_issues", lambda *args: [])

    with pytest.raises(ValueError):
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 3,
        )

    retained = (run_path / "outputs" / "planning-best.md").read_text(
        encoding="utf-8",
    )
    assert "fixed-1" in retained
    assert "pending-2" in retained
    assert "regressed-2" not in retained
    assert "fixed-3" in retained
    assert repair_calls[:3] == [(1,), (2,), (3,)]
    recovery = json.loads(
        (run_path / "outputs" / "planning-recovery-state.json").read_text(
            encoding="utf-8",
        )
    )
    accepted_segments = [
        item["comparison"].get("candidate_segment")
        for item in recovery["candidates"] if item["accepted"]
    ]
    assert accepted_segments[:2] == [1, 3]


@pytest.mark.asyncio
async def test_production_41_to_13_recovery_retains_segments_2_3_and_6(
    tmp_path, monkeypatch,
) -> None:
    fixture = json.loads((
        Path(__file__).parent / "fixtures" / "planning_granularity_d7b275.json"
    ).read_text(encoding="utf-8"))
    service, project, run_path, state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-GRANULAR-{index}" for index in range(1, 7)]
    original = "\n\n".join(
        (
            f"### 第 {index} 段：恢复段 {index}\n\n"
            f"事件ID：{event_id}\n\n"
            f"大纲依据：第 {index} 项正式事件\n\n"
            + (
                "段首承接：故事入口状态明确。\n\n"
                if index == 1 else
                f"段首承接：第 {index - 1} 项结果成立。\n\n"
            )
            + f"本段事件：主角完成第 {index} 项正式行动。\n\n"
            + (
                "段末交接：故事进入稳定结局。"
                if index == 6 else
                f"段末交接：第 {index} 项结果成立。"
            )
        )
        for index, event_id in enumerate(event_ids, 1)
    )
    affected_segments = sorted({
        int(key.rsplit("-", 1)[1])
        for key in fixture["resolved_by_segment"]
    })
    for segment in affected_segments:
        block = service._short_plan_segments(original, 6)[segment - 1]
        original = service._replace_short_plan_segment(
            original, 6, segment,
            block + f"\n\nRECOVERY-MARKER: pending-{segment}",
        )
    contracts = [
        {"id": event_id, "order": index, "evidence": f"evidence-{index}"}
        for index, event_id in enumerate(event_ids, 1)
    ]

    def count_for(mapping: dict, segment: int) -> int:
        return int(mapping.get(f"segment-{segment:02d}") or 0)

    initial_by_segment = {
        segment: [
            {
                "code": "planning_structural_drift",
                "segment": segment,
                "event_id": event_ids[segment - 1],
                "invalid_invariants": [f"initial-{segment:02d}-{number:02d}"],
            }
            for number in range(
                1,
                count_for(fixture["resolved_by_segment"], segment)
                + count_for(fixture["retained_by_segment"], segment)
                + 1,
            )
        ]
        for segment in affected_segments
    }

    def issues_for(candidate: str) -> list[dict]:
        values: list[dict] = []
        for segment in affected_segments:
            block = service._short_plan_segments(candidate, 6)[segment - 1]
            if f"pending-{segment}" in block:
                values.extend(initial_by_segment[segment])
            elif f"regressed-{segment}" in block:
                retained_count = count_for(
                    fixture["retained_by_segment"], segment,
                )
                values.extend(initial_by_segment[segment][-retained_count:])
                values.extend({
                    "code": "planning_structural_drift",
                    "segment": segment,
                    "event_id": event_ids[segment - 1],
                    "invalid_invariants": [
                        f"introduced-{segment:02d}-{number:02d}"
                    ],
                } for number in range(
                    1,
                    count_for(fixture["introduced_by_segment"], segment) + 1,
                ))
        return values

    async def review(*args, **kwargs):
        candidate = args[5]
        return ([{"segment": number} for number in range(1, 7)], {}, issues_for(candidate), 0)

    resolve_remaining = False
    repair_calls: list[tuple[int, ...]] = []

    async def repair(*args, target_segments=None, **kwargs):
        candidate = args[5]
        targets = tuple(target_segments or affected_segments)
        if args[0] == "adaptation-run":
            repair_calls.append(targets)
        for segment in targets:
            block = service._short_plan_segments(candidate, 6)[segment - 1]
            marker = (
                f"fixed-{segment}"
                if (
                    segment in fixture["expected_retained_segments"]
                    or resolve_remaining
                ) else
                f"regressed-{segment}"
            )
            candidate = service._replace_short_plan_segment(
                candidate, 6, segment,
                block.replace(f"pending-{segment}", marker),
            )
        return candidate

    monkeypatch.setattr(service, "_planning_adaptation_contracts", lambda *args: contracts)
    monkeypatch.setattr(service, "_review_short_plan_adaptations", review)
    monkeypatch.setattr(service, "_repair_short_plan_adaptation_segments", repair)
    monkeypatch.setattr(service, "_short_plan_issues", lambda *args: [])

    batch_candidate = await repair(
        "run", run_path, project, "constraints", state, original, [], 6,
        issues_for(original), target_segments=affected_segments,
    )
    comparison = planning_candidate_comparison(
        issues_for(original), issues_for(batch_candidate),
    )
    assert len(comparison["previous_issue_keys"]) == fixture["previous_count"]
    assert len(comparison["candidate_issue_keys"]) == fixture["candidate_count"]
    assert len(comparison["resolved_issue_keys"]) == fixture["resolved_count"]
    assert len(comparison["introduced_issue_keys"]) == fixture["introduced_count"]
    assert len(comparison["retained_issue_keys"]) == fixture["retained_count"]
    assert comparison["reason"] == fixture["rejection_reason"]

    with pytest.raises(ValueError):
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            original, [], 6,
        )

    retained = (run_path / "outputs" / "planning-best.md").read_text(
        encoding="utf-8",
    )
    for segment in fixture["expected_retained_segments"]:
        assert f"fixed-{segment}" in retained
    for segment in fixture["remaining_repair_segments"]:
        assert f"pending-{segment}" in retained
        assert f"regressed-{segment}" not in retained
    recovery = json.loads((
        run_path / "outputs" / "planning-recovery-state.json"
    ).read_text(encoding="utf-8"))
    accepted_segments = [
        item["comparison"].get("candidate_segment")
        for item in recovery["candidates"] if item["accepted"]
    ]
    assert accepted_segments == fixture["expected_retained_segments"]

    resolve_remaining = True
    repair_calls.clear()
    resumed_plan, resumed_artifact, changed = (
        await service._ensure_short_plan_adaptations(
            "adaptation-run", run_path, project, "constraints", state,
            retained, [], 6,
        )
    )
    assert changed is True
    assert resumed_artifact and resumed_artifact["status"] == "ready"
    assert all(
        f"fixed-{segment}" in resumed_plan for segment in affected_segments
    )
    assert repair_calls == [(4,), (5,)]


def test_recovery_feedback_is_segment_scoped_and_token_bounded() -> None:
    feedback = [{
        "source": "targeted-2",
        "planning_sha256": "a" * 64,
        "introduced_issue_keys": [],
        "issues": [{
            "code": "planning_structural_drift",
            "segment": segment,
            "event_id": f"EV-{segment}",
            "invalid_invariants": ["promise_ending"],
            "plan_evidence_ids": [f"PLAN-{segment:02d}-E001"],
            "plan_evidence": ["被拒候选原文" * 2000],
            "reason": "该候选提前消费后续结局承诺。",
        } for segment in range(1, 7)],
        "introduced_issues": [{
            "code": "planning_structural_drift",
            "segment": segment,
            "event_id": f"EV-{segment}",
            "invalid_invariants": ["promise_ending"],
            "plan_evidence_ids": [f"PLAN-{segment:02d}-E001"],
            "plan_evidence": ["被拒候选原文" * 2000],
            "reason": "该候选提前消费后续结局承诺。",
        } for segment in range(1, 7)],
        "comparison": {"reason": "introduced_hard_issue"},
    }]

    projected = WorkflowService._planning_recovery_feedback_for_segment(
        feedback,
        segment=4,
        segment_event_ids={number: [f"EV-{number}"] for number in range(1, 7)},
        token_budget=100,
    )

    assert len(projected) == 1
    assert projected[0]["projection"] == "structured_issue_manifest"
    assert projected[0]["issues"] == [{
        "code": "planning_structural_drift",
        "segment": 4,
        "event_id": "EV-4",
        "invalid_invariants": ["promise_ending"],
        "plan_evidence_ids": ["PLAN-04-E001"],
    }]
    assert projected[0]["full_record_sha256"]


def test_generated_packet_failure_feedback_survives_into_next_repair_scope() -> None:
    repair_issue = {
        "code": "planning_packet_field_missing",
        "message": "规划修复分包缺少完整字段：['handoff']",
        "segment": 5,
        "event_ids": ["EV-15C208EE", "EV-126EE846"],
        "fields": ["handoff"],
        "blocking": True,
    }
    recovery_state = {
        "candidates": [{
            "source": "rebuild-1-segments-05",
            "planning_sha256": "a" * 64,
            "issue_keys": ["existing-semantic-issue"],
            "introduced_issue_keys": [],
            "issues": [{
                "code": "planning_structural_drift",
                "segment": 5,
            }],
            "introduced_issues": [],
            "accepted": False,
            "comparison": {
                "reason": "candidate_generation_failed",
                "repair_feedback": [repair_issue],
            },
        }, {
            "source": "transport-only",
            "accepted": False,
            "comparison": {"reason": "candidate_generation_failed"},
        }],
    }

    feedback = WorkflowService._planning_recovery_candidate_feedback(
        recovery_state,
    )
    projected = WorkflowService._planning_recovery_feedback_for_segment(
        feedback,
        segment=5,
        segment_event_ids={
            5: ["EV-15C208EE", "EV-126EE846"],
        },
    )

    assert len(feedback) == 1
    assert feedback[0]["issues"] == [repair_issue]
    assert feedback[0]["introduced_issues"] == [repair_issue]
    assert len(projected) == 1
    assert projected[0]["issues"][0]["code"] == (
        "planning_packet_field_missing"
    )
    assert projected[0]["issues"][0]["fields"] == ["handoff"]


def test_whole_plan_context_reduction_keeps_complete_event_and_boundary_coverage(
    tmp_path,
) -> None:
    service, _project, _run_path, _state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-{number:08x}" for number in range(1, 4)]
    plan = three_segment_plan(event_ids)
    contracts = [{
        "id": event_id,
        "order": number,
        "label": f"事件 {number}",
        "evidence": "正式大纲证据" * 3000,
    } for number, event_id in enumerate(event_ids, 1)]
    receipts = [{
        "segment": number,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "changed_dimensions": ["dialogue"],
            "plan_evidence_ids": [f"PLAN-{number:02d}-E001"],
            "plan_evidence": ["当前规划证据" * 3000],
            "reason": "仅调整场景呈现。",
        }],
    } for number, event_id in enumerate(event_ids, 1)]

    context, mode, token_count = service._planning_adaptation_whole_context(
        plan=plan,
        formal_contracts=contracts,
        segment_receipts=receipts,
        segment_count=3,
        token_limit=2500,
    )

    assert mode == "hierarchical_required"
    assert token_count < 2500
    assert all(event_id in context for event_id in event_ids)
    assert "opening_sha256" in context
    assert "handoff_sha256" in context
    assert "正式大纲证据" not in context
    assert "当前规划证据" not in context


@pytest.mark.asyncio
async def test_long_whole_plan_uses_lossless_overlapping_hierarchical_review(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-{number:08X}" for number in range(1, 7)]
    plan = three_segment_plan(event_ids[:3]) + "\n\n" + "\n\n".join([
        (
            f"### 第 {number} 段：第{number}项\n\n"
            f"事件ID：{event_ids[number - 1]}\n\n"
            f"大纲依据：第{number}项\n\n"
            f"段首承接：第{number - 1}项结果成立。\n\n"
            f"本段事件：主角完成第{number}项正式行动。\n\n"
            f"段末交接：第{number}项结果成立。"
        ) for number in range(4, 7)
    ])
    contracts = [{
        "id": event_id,
        "order": number,
        "label": f"事件 {number}",
        "evidence": f"正式事件 {number} 的完整依据：" + "因果证据" * 70,
    } for number, event_id in enumerate(event_ids, 1)]
    receipts = [{
        "segment": number,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "changed_dimensions": ["dialogue"],
            "plan_evidence_ids": [f"PLAN-{number:02d}-E001"],
            "plan_evidence": [f"第 {number} 段精确规划原文：" + "场景证据" * 70],
            "reason": "仅扩展表现。",
        }],
    } for number, event_id in enumerate(event_ids, 1)]
    prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        prompts.append(prompt)
        if "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt \
                or "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in prompt:
            return hierarchy_adaptation_receipt(prompt)
        return whole_adaptation_receipt(prompt)

    service._provider_context_window = lambda *_args, **_kwargs: 5_000
    service._stage = fake_stage
    planning_sha256 = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    receipt, issues, _retries = await service._review_short_plan_adaptation_whole(
        "adaptation-run", run_path, project, "constraints",
        outline_sha256="a" * 64,
        planning_sha256=planning_sha256,
        formal_contracts=contracts,
        plan=plan,
        segment_receipts=receipts,
        segment_count=6,
        suffix="long",
        authority_version=PLANNING_ADAPTATION_VERSION,
    )

    regional_prompts = [
        prompt for prompt in prompts
        if "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt
    ]
    whole_prompts = [
        prompt for prompt in prompts
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt
    ]
    assert issues == []
    assert receipt["formal_direction_preserved"] is True
    assert len(regional_prompts) >= 2
    assert len(whole_prompts) == 1
    assert prompts.index(regional_prompts[0]) < prompts.index(whole_prompts[0])
    assert "HASH-BOUND HIERARCHICAL WHOLE-PLAN EVIDENCE" in whole_prompts[0]
    assert "HASH-BOUND COMPLETE COVERAGE MANIFEST" not in whole_prompts[0]
    regional_events: set[str] = set()
    for prompt in regional_prompts:
        source = json.loads(
            prompt.split("ORDERED LOSSLESS REVIEW UNITS:\n", 1)[1]
        )
        for unit in source:
            assert unit["formal_contracts"]
            assert unit["event_reviews"]
            assert all(review["plan_evidence"] for review in unit["event_reviews"])
            regional_events.update(unit["event_ids"])
    assert regional_events == set(event_ids)


@pytest.mark.asyncio
async def test_hierarchical_review_resumes_completed_packets_across_runs(
    tmp_path,
) -> None:
    service, project, first_run_path, _state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-{number:08X}" for number in range(1, 7)]
    plan = three_segment_plan(event_ids[:3]) + "\n\n" + "\n\n".join([
        (
            f"### 第 {number} 段：第{number}项\n\n"
            f"事件ID：{event_ids[number - 1]}\n\n"
            f"大纲依据：第{number}项\n\n"
            f"段首承接：第{number - 1}项结果成立。\n\n"
            f"本段事件：主角完成第{number}项正式行动。\n\n"
            f"段末交接：第{number}项结果成立。"
        ) for number in range(4, 7)
    ])
    contracts = [{
        "id": event_id,
        "order": number,
        "label": f"事件 {number}",
        "evidence": f"正式事件 {number} 的完整依据：" + "因果证据" * 70,
    } for number, event_id in enumerate(event_ids, 1)]
    receipts = [{
        "segment": number,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "changed_dimensions": ["dialogue"],
            "plan_evidence_ids": [f"PLAN-{number:02d}-E001"],
            "plan_evidence": [f"第 {number} 段精确规划原文：" + "场景证据" * 70],
            "reason": "仅扩展表现。",
        }],
    } for number, event_id in enumerate(event_ids, 1)]
    first_regional_sources: list[str] = []

    async def interrupted_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt:
            source = prompt.split("SOURCE SHA256: ", 1)[1].splitlines()[0]
            first_regional_sources.append(source)
            if len(first_regional_sources) == 2:
                raise ConnectionError("regional packet interrupted")
            return hierarchy_adaptation_receipt(prompt)
        return hierarchy_adaptation_receipt(prompt)

    service._stage = interrupted_stage
    with pytest.raises(ConnectionError, match="regional packet interrupted"):
        await service._planning_adaptation_hierarchical_context(
            "adaptation-run", first_run_path, project, "constraints",
            plan=plan,
            formal_contracts=contracts,
            segment_receipts=receipts,
            segment_count=6,
            token_limit=2_000,
            suffix="interrupted",
        )
    assert len(first_regional_sources) == 2
    completed_source = first_regional_sources[0]
    assert list((first_run_path / "outputs" / "pah").glob("r-*.json"))

    second_run_id = "adaptation-resume"
    service.db.create_run(
        second_run_id, project.id, "short-story", status="running",
    )
    second_run_path = project.path / "runs" / second_run_id
    (second_run_path / "outputs").mkdir(parents=True)
    (second_run_path / "receipts").mkdir()
    resumed_regional_sources: list[str] = []

    async def resumed_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt:
            resumed_regional_sources.append(
                prompt.split("SOURCE SHA256: ", 1)[1].splitlines()[0]
            )
        return hierarchy_adaptation_receipt(prompt)

    service._stage = resumed_stage
    context, metadata, _retries = await service._planning_adaptation_hierarchical_context(
        second_run_id, second_run_path, project, "constraints",
        plan=plan,
        formal_contracts=contracts,
        segment_receipts=receipts,
        segment_count=6,
        token_limit=2_000,
        suffix="resumed",
    )

    assert completed_source not in resumed_regional_sources
    assert metadata["covered_segments"] == [1, 2, 3, 4, 5, 6]
    assert "HASH-BOUND HIERARCHICAL WHOLE-PLAN EVIDENCE" in context
    assert any(
        event["event_type"] == "planning_adaptation_hierarchy_checkpoint_reused"
        for event in service.db.list_run_events(second_run_id)
    )


@pytest.mark.asyncio
async def test_hierarchical_review_accepts_adjacent_shared_formal_event(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-{number:08X}" for number in range(1, 4)]
    plan = "\n\n".join([
        (
            "### 第 1 段：事件一前半\n\n"
            f"事件ID：{event_ids[0]}\n\n大纲依据：事件一\n\n"
            "段首承接：故事开始。\n\n本段事件：主角开始执行事件一。\n\n"
            "段末交接：事件一尚未完成，交给下一段继续。"
        ),
        (
            "### 第 2 段：事件一后半与事件二\n\n"
            f"事件ID：{event_ids[0]}、{event_ids[1]}\n\n大纲依据：事件一、事件二\n\n"
            "段首承接：事件一仍在进行。\n\n本段事件：主角完成事件一并推进事件二。\n\n"
            "段末交接：事件二结果成立。"
        ),
        (
            "### 第 3 段：事件三\n\n"
            f"事件ID：{event_ids[2]}\n\n大纲依据：事件三\n\n"
            "段首承接：事件二结果成立。\n\n本段事件：主角完成事件三。\n\n"
            "段末交接：正式结局成立。"
        ),
    ])
    contracts = [{
        "id": event_id,
        "order": number,
        "label": f"事件 {number}",
        "evidence": f"正式事件 {number} 完整依据：" + "因果证据" * 80,
    } for number, event_id in enumerate(event_ids, 1)]
    owned = [[event_ids[0]], [event_ids[0], event_ids[1]], [event_ids[2]]]
    receipts = [
        {
            "segment": segment,
            "event_reviews": [{
                "event_id": event_id,
                "classification": "equivalent",
                "invariants": {field: True for field in INVARIANT_FIELDS},
                "changed_dimensions": ["scene_realization"],
                "plan_evidence_ids": [f"PLAN-{segment:02d}-E001"],
                "plan_evidence": [
                    f"第 {segment} 段事件 {event_id} 精确规划证据：" + "场景证据" * 80
                ],
                "reason": "相邻分段连续完成同一正式事件，未改变事件顺序。",
            } for event_id in event_group],
        }
        for segment, event_group in enumerate(owned, 1)
    ]
    prompts: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        prompts.append(prompt)
        if (
            "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt
            or "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in prompt
        ):
            return hierarchy_adaptation_receipt(prompt)
        return whole_adaptation_receipt(prompt)

    service._provider_context_window = lambda *_args, **_kwargs: 4_000
    service._stage = fake_stage
    receipt, issues, _retries = await service._review_short_plan_adaptation_whole(
        "adaptation-run", run_path, project, "constraints",
        outline_sha256="a" * 64,
        planning_sha256=hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        formal_contracts=contracts,
        plan=plan,
        segment_receipts=receipts,
        segment_count=3,
        suffix="shared-event",
    )

    assert issues == []
    assert receipt["formal_direction_preserved"] is True
    assert any(
        "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt for prompt in prompts
    )
    assert WorkflowService._planning_hierarchy_event_coverage_valid(
        owned, event_ids,
    )
    assert not WorkflowService._planning_hierarchy_event_coverage_valid(
        [[event_ids[0]], [event_ids[1]], [event_ids[0], event_ids[2]]],
        event_ids,
    )


@pytest.mark.asyncio
async def test_hierarchical_review_cannot_wash_out_lower_level_failure(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    event_ids = [f"EV-{number:08X}" for number in range(1, 4)]
    plan = three_segment_plan(event_ids)
    contracts = [{
        "id": event_id,
        "order": number,
        "label": f"事件 {number}",
        "evidence": "完整正式依据" * 80,
    } for number, event_id in enumerate(event_ids, 1)]
    receipts = [{
        "segment": number,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "changed_dimensions": ["dialogue"],
            "plan_evidence_ids": [f"PLAN-{number:02d}-E001"],
            "plan_evidence": ["完整规划证据" * 80],
            "reason": "仅扩展表现。",
        }],
    } for number, event_id in enumerate(event_ids, 1)]
    regional_calls = 0

    async def fake_stage(*args, **kwargs):
        nonlocal regional_calls
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in prompt:
            regional_calls += 1
            return hierarchy_adaptation_receipt(
                prompt,
                invalid_field="causal_order_preserved" if regional_calls == 1 else "",
            )
        if "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in prompt:
            return hierarchy_adaptation_receipt(prompt)
        return whole_adaptation_receipt(prompt)

    service._provider_context_window = lambda *_args, **_kwargs: 5_000
    service._stage = fake_stage
    receipt, issues, _retries = await service._review_short_plan_adaptation_whole(
        "adaptation-run", run_path, project, "constraints",
        outline_sha256="a" * 64,
        planning_sha256=hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        formal_contracts=contracts,
        plan=plan,
        segment_receipts=receipts,
        segment_count=3,
        suffix="lower-failure",
    )

    assert regional_calls >= 1
    assert receipt["causal_order_preserved"] is False
    assert any(item["code"] == "planning_whole_story_drift" for item in issues)


@pytest.mark.asyncio
async def test_hierarchical_review_stops_when_one_event_is_indivisible(
    tmp_path,
) -> None:
    service, project, run_path, _state, contracts = make_service(tmp_path)
    event_id = contracts[0]["id"]
    plan = plan_for(event_id, "花穗亲自核验库房异常。")
    receipts = [{
        "segment": 1,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "changed_dimensions": ["dialogue"],
            "plan_evidence_ids": ["PLAN-01-E001"],
            "plan_evidence": ["不可拆的精确规划证据" * 4_000],
            "reason": "仅扩展表现。",
        }],
    }]

    async def unexpected_stage(*_args, **_kwargs):
        raise AssertionError("不可拆事件超过安全线时不应调用模型")

    service._stage = unexpected_stage
    with pytest.raises(ValueError, match="单个事件超过"):
        await service._planning_adaptation_hierarchical_context(
            "adaptation-run", run_path, project, "constraints",
            plan=plan,
            formal_contracts=[{
                **contracts[0],
                "evidence": "不可拆的完整正式合同" * 4_000,
            }],
            segment_receipts=receipts,
            segment_count=1,
            token_limit=2_000,
            suffix="indivisible",
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


@pytest.mark.asyncio
async def test_capacity_split_reviews_event_owned_packets_and_merges_full_coverage(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_capacity_dd0d6d2d.json")
        .read_text(encoding="utf-8")
    )
    event_contracts = [
        {"id": f"EV-{index}", "evidence": f"formal evidence {index}"}
        for index in range(1, fixture["affected_segment_event_count"] + 1)
    ]
    plan_segment = "\n\n".join(
        f"### 段落 {index}\n\n事件ID：EV-{index}\n\n本段事件：事件 {index} 展开。"
        for index in range(1, fixture["affected_segment_event_count"] + 1)
    )
    calls: list[list[str]] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        event_ids = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
            )[0]
        )
        calls.append(event_ids)
        if kwargs.get("capacity_splitter") is not None:
            return await kwargs["capacity_splitter"]({
                "pressure": "split",
                "estimated_input_tokens": fixture["estimated_input_tokens"],
                "authority_input_tokens": 23_000,
                "output_reserve": fixture["output_reserve_tokens"],
                "context_window": fixture["context_window"],
            })
        if len(event_ids) > 1:
            raise ContextCapacityPreflightError(
                pressure="split",
                estimated_input_tokens=24_000,
                authority_input_tokens=23_000,
                output_reserve=7_000,
                context_window=32_768,
            )
        authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
        planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        candidates = json.loads(
            prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1]
        )
        evidence_id = next(iter(candidates))
        return json.dumps({
            "authority_sha256": authority,
            "planning_sha256": planning,
            "segment": segment,
            "event_reviews": [{
                "event_id": event_id,
                "classification": "equivalent",
                "changed_dimensions": ["dialogue"],
                "invariants": {field: True for field in INVARIANT_FIELDS},
                "plan_evidence_ids": [evidence_id],
                "reason": "仅展开表达。",
            } for event_id in event_ids],
            "segment_order_preserved": True,
            "formal_direction_preserved": True,
            "summary": "分包审核完成。",
        }, ensure_ascii=False)

    service._stage = fake_stage
    parent_authority = planning_adaptation_segment_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=1,
        event_contracts=event_contracts,
        plan_segment=plan_segment,
        generation_context_sha256="context",
    )
    merged, segment_issues, _segment_retries = (
        await service._review_short_plan_adaptation_segment(
            "adaptation-run", run_path, project, "constraints",
            outline_sha256="a" * 64,
            planning_sha256="b" * 64,
            segment=1,
            event_contracts=event_contracts,
            plan_segment=plan_segment,
            suffix="production-shaped",
            previous_handoff="opening",
            next_entry="ending",
            generation_context_sha256="context",
            authority_version=PLANNING_ADAPTATION_VERSION,
            authority_event_ids=[item["id"] for item in event_contracts],
        )
    )

    assert segment_issues == []
    assert [item["event_id"] for item in merged["event_reviews"]] == [
        item["id"] for item in event_contracts
    ]
    assert merged["authority_sha256"] == parent_authority
    assert len(merged["event_reviews"]) == fixture["affected_segment_event_count"]
    assert merged["capacity_split"]["packets"]
    assert all(len(item) == 1 for item in calls if len(item) == 1)
    assert any(len(item) > 1 for item in calls)
    assert any(
        item["event_type"] == "planning_adaptation_capacity_split_completed"
        for item in service.db.list_run_events("adaptation-run")
    )

    async def whole_stage(*args, **kwargs):
        prompt = args[5]
        assert "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in prompt
        return whole_adaptation_receipt(prompt)

    service._stage = whole_stage
    whole, whole_issues, _retries = (
        await service._review_short_plan_adaptation_whole(
            "adaptation-run", run_path, project, "constraints",
            outline_sha256="a" * 64,
            planning_sha256="b" * 64,
            formal_contracts=event_contracts,
            plan=plan_segment,
            segment_receipts=[merged],
            segment_count=1,
            suffix="production-shaped",
        )
    )
    assert whole_issues == []
    assert whole["event_ids"] == [item["id"] for item in event_contracts]


@pytest.mark.asyncio
async def test_capacity_split_projects_singleton_and_recovers_by_invariant_facets(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_capacity_e86225d9.json")
        .read_text(encoding="utf-8")
    )
    event_contracts = [
        {"id": f"EV-{index}", "evidence": f"formal evidence {index}"}
        for index in range(1, fixture["affected_segment_event_count"] + 1)
    ]
    plan_segment = "\n\n".join(
        f"### Event {index}\n\nEvent ID: EV-{index}\n\n"
        f"Plan realization: event {index} advances its owned state."
        for index in range(1, fixture["affected_segment_event_count"] + 1)
    )
    full_segment_characters = len(plan_segment)
    singleton_prompt_characters: list[int] = []
    facet_names: list[str] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_EVENT_FACET_REVIEW_V1" in prompt:
            facet = prompt.split("FACET: ", 1)[1].splitlines()[0]
            facet_names.append(facet)
            invariant_names = json.loads(
                prompt.split("EXPECTED INVARIANTS:\n", 1)[1].split("\n\n", 1)[0]
            )
            evidence = json.loads(
                prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1].split(
                    "\n\nRequired fields:", 1,
                )[0]
            )
            event_id = prompt.split("EVENT ID: ", 1)[1].splitlines()[0]
            return json.dumps({
                "authority_sha256": prompt.split(
                    "EXPECTED FACET AUTHORITY SHA256: ", 1,
                )[1].splitlines()[0],
                "planning_sha256": "b" * 64,
                "authority_version": PLANNING_ADAPTATION_VERSION,
                "segment": 1,
                "event_id": event_id,
                "facet": facet,
                "invariants": {name: True for name in invariant_names},
                "changed_dimensions": ["dialogue"] if facet == "function" else [],
                "plan_evidence_ids": [next(iter(evidence))],
                "reason": "The exact event realization preserves this facet.",
            })

        event_ids = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
            )[0]
        )
        if kwargs.get("capacity_splitter") is not None:
            return await kwargs["capacity_splitter"]({
                "pressure": "split",
                "estimated_input_tokens": fixture["initial_input_tokens"],
                "authority_input_tokens": 21_578,
                "output_reserve": 7_394,
                "context_window": fixture["context_window"],
            })
        if len(event_ids) > 1:
            raise ContextCapacityPreflightError(
                pressure="split", estimated_input_tokens=24_000,
                authority_input_tokens=21_000, output_reserve=7_000,
                context_window=32_768,
            )
        projected = prompt.split(
            "CURRENT ACCEPTED PLAN SEGMENT:\n", 1,
        )[1].split("\n\nPREVIOUS ACCEPTED HANDOFF:", 1)[0]
        singleton_prompt_characters.append(len(projected))
        raise ContextCapacityPreflightError(
            pressure="compact",
            estimated_input_tokens=fixture["singleton_input_tokens"],
            authority_input_tokens=fixture["singleton_authority_tokens"],
            output_reserve=fixture["singleton_output_reserve_tokens"],
            context_window=fixture["context_window"],
        )

    service._stage = fake_stage
    receipt, issues, _retries = await service._review_short_plan_adaptation_segment(
        "adaptation-run", run_path, project, "constraints",
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=1,
        event_contracts=event_contracts,
        plan_segment=plan_segment,
        suffix="singleton-production-shape",
        previous_handoff="opening",
        next_entry="ending",
        generation_context_sha256="context",
        authority_version=PLANNING_ADAPTATION_VERSION,
        authority_event_ids=[item["id"] for item in event_contracts],
    )

    assert issues == []
    assert [item["event_id"] for item in receipt["event_reviews"]] == [
        item["id"] for item in event_contracts
    ]
    assert set(facet_names) == {"function", "state", "continuity"}
    assert singleton_prompt_characters
    assert max(singleton_prompt_characters) < full_segment_characters / 2
    assert receipt["capacity_split"]["singleton_facet_recoveries"] == len(
        event_contracts
    )


@pytest.mark.asyncio
async def test_singleton_facet_overflow_reviews_complete_overlapping_windows(
    tmp_path,
) -> None:
    service, project, run_path, _state, _contracts = make_service(tmp_path)
    paragraphs = [
        (
            f"Event ID: EV-1\nWindow evidence {index}: "
            + (f"detail-{index}-" * 320)
        )
        for index in range(1, 7)
    ]
    plan_segment = "\n\n".join(paragraphs)
    event_contract = {"id": "EV-1", "evidence": "formal event evidence"}
    evidence_candidates = planning_adaptation_evidence_candidates(plan_segment, 1)
    reviewed_ranges: list[tuple[str, int, int]] = []

    async def fake_stage(*args, **kwargs):
        prompt = args[5]
        if "SHORT_PLAN_ADAPTATION_EVENT_FACET_REVIEW_V1" in prompt:
            return await kwargs["capacity_splitter"]({
                "pressure": "split",
                "estimated_input_tokens": 31_000,
                "authority_input_tokens": 29_000,
                "output_reserve": 900,
                "context_window": 32_768,
            })
        assert "SHORT_PLAN_ADAPTATION_EVENT_FACET_WINDOW_REVIEW_V1" in prompt
        facet = prompt.split("FACET: ", 1)[1].splitlines()[0]
        invariant_names = json.loads(
            prompt.split("EXPECTED INVARIANTS:\n", 1)[1].split("\n\n", 1)[0]
        )
        window_index = int(prompt.split("WINDOW INDEX: ", 1)[1].splitlines()[0])
        start, end = (
            int(value)
            for value in prompt.split("WINDOW RANGE: ", 1)[1].splitlines()[0].split(":")
        )
        reviewed_ranges.append((facet, start, end))
        candidates = json.loads(
            prompt.split("WINDOW EVIDENCE CANDIDATES:\n", 1)[1].split(
                "\n\nEXACT PLAN WINDOW:", 1,
            )[0]
        )
        return json.dumps({
            "authority_sha256": prompt.split(
                "EXPECTED WINDOW AUTHORITY SHA256: ", 1,
            )[1].splitlines()[0],
            "planning_sha256": "b" * 64,
            "authority_version": PLANNING_ADAPTATION_VERSION,
            "segment": 1,
            "event_id": "EV-1",
            "facet": facet,
            "window_index": window_index,
            "start": start,
            "end": end,
            "text_sha256": prompt.split(
                "WINDOW TEXT SHA256: ", 1,
            )[1].splitlines()[0],
            "invariants": {name: True for name in invariant_names},
            "changed_dimensions": ["dialogue"] if window_index == 1 else [],
            "plan_evidence_ids": list(candidates)[:1],
            "reason": "This exact window preserves the requested invariants.",
        }, ensure_ascii=False)

    service._stage = fake_stage
    packet_authority = planning_adaptation_segment_packet_authority_sha256(
        segment_authority_sha256="a" * 64,
        segment=1,
        event_ids=["EV-1"],
        version=PLANNING_ADAPTATION_VERSION,
    )
    receipt, issues, _retries = (
        await service._review_short_plan_adaptation_event_facets(
            "adaptation-run", run_path, project, "constraints",
            planning_sha256="b" * 64,
            segment=1,
            event_contract=event_contract,
            plan_segment=plan_segment,
            evidence_candidates=evidence_candidates,
            packet_authority_sha256=packet_authority,
            previous_handoff="opening",
            next_entry="ending",
            authority_version=PLANNING_ADAPTATION_VERSION,
            authority_event_ids=["EV-1"],
            story_skeleton_override=service._stage_story_skeleton(
                project, "constraints", run_path, owner_event_ids=["EV-1"],
            ),
        )
    )

    assert issues == []
    assert receipt["event_reviews"][0]["invariants"] == {
        field: True for field in INVARIANT_FIELDS
    }
    for facet in ("function", "state", "continuity"):
        ranges = [(start, end) for name, start, end in reviewed_ranges if name == facet]
        assert len(ranges) > 1
        assert ranges[0][0] == 0
        assert ranges[-1][1] == len(plan_segment)
        assert all(current_start <= previous_end for (
            _previous_start, previous_end
        ), (current_start, _current_end) in zip(ranges, ranges[1:]))
    assert list((run_path / "outputs" / "pap").glob("facet-window-*.json"))
    assert any(
        item["event_type"] == "planning_adaptation_facet_windows_completed"
        for item in service.db.list_run_events("adaptation-run")
    )


@pytest.mark.asyncio
async def test_singleton_facet_windows_resume_after_transport_interruption(
    tmp_path,
) -> None:
    service, project, first_run_path, _state, _contracts = make_service(tmp_path)
    plan_segment = "\n\n".join(
        f"Event ID: EV-1\nEvidence {index}: " + (f"detail-{index}-" * 420)
        for index in range(1, 5)
    )
    candidates = planning_adaptation_evidence_candidates(plan_segment, 1)

    def window_receipt(prompt: str) -> str:
        facet = prompt.split("FACET: ", 1)[1].splitlines()[0]
        invariant_names = json.loads(
            prompt.split("EXPECTED INVARIANTS:\n", 1)[1].split("\n\n", 1)[0]
        )
        start, end = (
            int(value)
            for value in prompt.split("WINDOW RANGE: ", 1)[1].splitlines()[0].split(":")
        )
        evidence = json.loads(
            prompt.split("WINDOW EVIDENCE CANDIDATES:\n", 1)[1].split(
                "\n\nEXACT PLAN WINDOW:", 1,
            )[0]
        )
        return json.dumps({
            "authority_sha256": prompt.split(
                "EXPECTED WINDOW AUTHORITY SHA256: ", 1,
            )[1].splitlines()[0],
            "planning_sha256": "b" * 64,
            "authority_version": PLANNING_ADAPTATION_VERSION,
            "segment": 1,
            "event_id": "EV-1",
            "facet": facet,
            "window_index": int(prompt.split(
                "WINDOW INDEX: ", 1,
            )[1].splitlines()[0]),
            "start": start,
            "end": end,
            "text_sha256": prompt.split(
                "WINDOW TEXT SHA256: ", 1,
            )[1].splitlines()[0],
            "invariants": {name: True for name in invariant_names},
            "changed_dimensions": [],
            "plan_evidence_ids": list(evidence)[:1],
            "reason": "The bound window preserves this facet.",
        })

    first_calls: list[int] = []

    async def interrupted_stage(*args, **_kwargs):
        prompt = args[5]
        window_index = int(prompt.split("WINDOW INDEX: ", 1)[1].splitlines()[0])
        first_calls.append(window_index)
        if window_index == 2:
            raise ConnectionError("facet window transport interrupted")
        return window_receipt(prompt)

    service._stage = interrupted_stage
    with pytest.raises(ConnectionError, match="facet window transport interrupted"):
        await service._review_short_plan_adaptation_facet_windows(
            "adaptation-run", first_run_path, project, "constraints",
            planning_sha256="b" * 64,
            segment=1,
            event_contract={"id": "EV-1", "evidence": "formal event"},
            plan_segment=plan_segment,
            evidence_candidates=candidates,
            facet_authority_sha256="f" * 64,
            event_id="EV-1",
            facet="function",
            invariant_fields=(
                "event_function", "primary_actor_agency", "causal_dependencies",
            ),
            authority_version=PLANNING_ADAPTATION_VERSION,
        )
    assert first_calls[:2] == [1, 2]

    second_run_id = "adaptation-facet-window-resume"
    service.db.create_run(
        second_run_id, project.id, "short-story", status="running",
    )
    second_run_path = project.path / "runs" / second_run_id
    (second_run_path / "outputs").mkdir(parents=True)
    (second_run_path / "receipts").mkdir()
    resumed_calls: list[int] = []

    async def resumed_stage(*args, **_kwargs):
        prompt = args[5]
        resumed_calls.append(int(
            prompt.split("WINDOW INDEX: ", 1)[1].splitlines()[0]
        ))
        return window_receipt(prompt)

    service._stage = resumed_stage
    merged = json.loads(await service._review_short_plan_adaptation_facet_windows(
        second_run_id, second_run_path, project, "constraints",
        planning_sha256="b" * 64,
        segment=1,
        event_contract={"id": "EV-1", "evidence": "formal event"},
        plan_segment=plan_segment,
        evidence_candidates=candidates,
        facet_authority_sha256="f" * 64,
        event_id="EV-1",
        facet="function",
        invariant_fields=(
            "event_function", "primary_actor_agency", "causal_dependencies",
        ),
        authority_version=PLANNING_ADAPTATION_VERSION,
    ))

    assert 1 not in resumed_calls
    assert all(merged["invariants"].values())
    assert any(
        item["event_type"]
        == "planning_adaptation_facet_window_checkpoint_reused"
        for item in service.db.list_run_events(second_run_id)
    )


@pytest.mark.asyncio
async def test_capacity_split_reuses_completed_packets_after_interruption(
    tmp_path,
) -> None:
    service, project, first_run_path, _state, _contracts = make_service(tmp_path)
    event_contracts = [
        {"id": f"EV-{index}", "evidence": f"formal evidence {index}"}
        for index in range(1, 5)
    ]
    plan_segment = "\n\n".join(
        f"### 段落 {index}\n\n事件ID：EV-{index}\n\n本段事件：事件 {index} 展开。"
        for index in range(1, 5)
    )
    parent_authority = planning_adaptation_segment_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=1,
        event_contracts=event_contracts,
        plan_segment=plan_segment,
    )

    def receipt_for(prompt: str) -> str:
        event_ids = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
            )[0]
        )
        authority = prompt.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
        planning = prompt.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
        segment = int(prompt.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        candidates = json.loads(
            prompt.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1]
        )
        evidence_id = next(iter(candidates))
        return json.dumps({
            "authority_sha256": authority,
            "planning_sha256": planning,
            "segment": segment,
            "event_reviews": [{
                "event_id": event_id,
                "classification": "equivalent",
                "changed_dimensions": ["dialogue"],
                "invariants": {field: True for field in INVARIANT_FIELDS},
                "plan_evidence_ids": [evidence_id],
                "reason": "仅展开表达。",
            } for event_id in event_ids],
            "segment_order_preserved": True,
            "formal_direction_preserved": True,
            "summary": "分包审核完成。",
        }, ensure_ascii=False)

    first_singles: list[str] = []

    async def interrupted_stage(*args, **kwargs):
        prompt = args[5]
        event_ids = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
            )[0]
        )
        if len(event_ids) > 1:
            raise ContextCapacityPreflightError(
                pressure="split", estimated_input_tokens=24_000,
                authority_input_tokens=23_000, output_reserve=7_000,
                context_window=32_768,
            )
        first_singles.append(event_ids[0])
        if len(first_singles) == 2:
            raise ConnectionError("packet transport interrupted")
        return receipt_for(prompt)

    service._stage = interrupted_stage
    with pytest.raises(ConnectionError, match="packet transport interrupted"):
        await service._review_short_plan_adaptation_capacity_split(
            "adaptation-run", first_run_path, project, "constraints",
            outline_sha256="a" * 64,
            planning_sha256="b" * 64,
            segment=1,
            event_contracts=event_contracts,
            plan_segment=plan_segment,
            suffix="interrupted",
            previous_handoff="opening",
            next_entry="ending",
            generation_context_sha256="context",
            authority_version=PLANNING_ADAPTATION_VERSION,
            authority_event_ids=[item["id"] for item in event_contracts],
            segment_authority_sha256=parent_authority,
            details={"pressure": "split"},
        )
    assert list((first_run_path / "outputs" / "pap").glob("*.json"))

    second_run_id = "adaptation-resume-capacity"
    service.db.create_run(
        second_run_id, project.id, "short-story", status="running",
    )
    second_run_path = project.path / "runs" / second_run_id
    (second_run_path / "outputs").mkdir(parents=True)
    (second_run_path / "receipts").mkdir()
    resumed_singles: list[str] = []

    async def resumed_stage(*args, **kwargs):
        prompt = args[5]
        event_ids = json.loads(
            prompt.split("EXPECTED EVENT IDS:\n", 1)[1].split(
                "\n\nALLOWED DEPENDENCY EVENT IDS", 1,
            )[0]
        )
        if len(event_ids) > 1:
            raise ContextCapacityPreflightError(
                pressure="split", estimated_input_tokens=24_000,
                authority_input_tokens=23_000, output_reserve=7_000,
                context_window=32_768,
            )
        resumed_singles.append(event_ids[0])
        return receipt_for(prompt)

    service._stage = resumed_stage
    merged_raw = await service._review_short_plan_adaptation_capacity_split(
        second_run_id, second_run_path, project, "constraints",
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=1,
        event_contracts=event_contracts,
        plan_segment=plan_segment,
        suffix="resumed",
        previous_handoff="opening",
        next_entry="ending",
        generation_context_sha256="context",
        authority_version=PLANNING_ADAPTATION_VERSION,
        authority_event_ids=[item["id"] for item in event_contracts],
        segment_authority_sha256=parent_authority,
        details={"pressure": "split"},
    )

    merged = json.loads(merged_raw)
    assert [item["event_id"] for item in merged["event_reviews"]] == [
        item["id"] for item in event_contracts
    ]
    assert first_singles[0] not in resumed_singles
    assert any(
        item["event_type"] == "planning_adaptation_packet_checkpoint_reused"
        for item in service.db.list_run_events(second_run_id)
    )
