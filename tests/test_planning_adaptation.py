from __future__ import annotations

import hashlib

from novel_flywheel.planning_adaptation import (
    INVARIANT_FIELDS,
    effective_event_contracts,
    normalize_planning_adaptation_receipt,
    normalize_planning_adaptation_whole_receipt,
    planning_adaptation_evidence_candidates,
    planning_adaptation_issues_are_protocol_only,
    planning_adaptation_receipt_issues,
    planning_adaptation_segment_authority_sha256,
    planning_adaptation_whole_authority_sha256,
    planning_adaptation_whole_receipt_issues,
)


EVENT_ID = "EV-221A4437"


def formal_contract() -> dict:
    return {
        "id": EVENT_ID,
        "order": 1,
        "label": "发现异常",
        "section": "第二幕",
        "source": "formal_outline",
        "evidence": "花穗撞见刘管事从库房向外搬运箱子。",
    }


def invariant_payload(value: object = True) -> dict:
    return {field: value for field in INVARIANT_FIELDS}


def receipt_for(
    plan: str, *, classification: str = "equivalent",
    changed_dimensions: list[str] | None = None,
    invariants: dict | None = None,
) -> tuple[dict, dict[str, str], str, str]:
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    evidence_id = next(iter(candidates))
    planning_sha256 = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    authority_sha256 = planning_adaptation_segment_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256=planning_sha256,
        segment=1,
        event_contracts=[formal_contract()],
        plan_segment=plan,
    )
    receipt = {
        "authority_sha256": authority_sha256,
        "planning_sha256": planning_sha256,
        "segment": 1,
        "event_reviews": [{
            "event_id": EVENT_ID,
            "classification": classification,
            "changed_dimensions": changed_dimensions or ["trigger_method"],
            "invariants": invariants or invariant_payload(),
            "plan_evidence_ids": [evidence_id],
            "reason": "发现入口变化，但花穗仍完成核实并主导后续查证。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "事件功能、主要执行者与后续状态保持。",
    }
    return receipt, candidates, authority_sha256, planning_sha256


def test_equivalent_trigger_change_is_authorized_without_literal_copy() -> None:
    plan = (
        "### 第 1 段：查账\n\n"
        "事件ID：EV-221A4437\n\n"
        "本段事件：小厮先报信，花穗追问后亲自到库房试探并核实异常。\n\n"
        "段末交接：花穗掌握可继续查证的异常。"
    )
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(plan)
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_evidence_candidates_prefer_bounded_fields_over_the_whole_segment() -> None:
    plan = (
        "### 第 1 段：连续事件\n\n"
        "事件ID：EV-221A4437、EV-334B5548\n\n"
        "段首承接：花穗已发现账目缺口。\n\n"
        "本段事件：花穗先核验库房，随后与裴砚行核对账册。\n\n"
        "段末交接：二人锁定经手人。"
    )

    candidates = planning_adaptation_evidence_candidates(plan, 1)

    assert plan not in candidates.values()
    assert "本段事件：花穗先核验库房，随后与裴砚行核对账册。" in candidates.values()


def test_chinese_aliases_and_string_booleans_normalize_at_one_boundary() -> None:
    plan = "### 第 1 段：接管\n\n事件ID：EV-221A4437\n\n本段事件：系统先报警，舰长核验后接管气闸。"
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(plan)
    item = receipt["event_reviews"][0]
    item["event_id"] = "ＥＶ－２２１Ａ４４３７"
    item["classification"] = "等价展开"
    item["changed_dimensions"] = "触发方式，场景展开"
    item["plan_evidence_id"] = item.pop("plan_evidence_ids")[0]
    item["invariants"] = {
        "事件功能": "是",
        "人物主动性": "通过",
        "因果依赖": "true",
        "入口状态": "1",
        "出口状态": "是",
        "知情状态": "保留",
        "关系状态": "yes",
        "视角": "是",
        "时间顺序": "true",
        "伏笔与结局": "通过",
    }
    receipt["segment_order_preserved"] = "是"
    receipt["formal_direction_preserved"] = "true"
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    assert normalized["event_reviews"][0]["event_id"] == EVENT_ID
    assert normalized["event_reviews"][0]["classification"] == "equivalent"
    assert normalized["event_reviews"][0]["changed_dimensions"] == [
        "trigger_method", "scene_realization",
    ]
    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_primary_actor_or_knowledge_change_is_structural_drift() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：小厮直接确认刘管事有罪。"
    invariants = invariant_payload()
    invariants["primary_actor_agency"] = False
    invariants["knowledge_state"] = False
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan,
        changed_dimensions=["supporting_actor", "primary_actor_agency", "knowledge_state"],
        invariants=invariants,
    )
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    issues = planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    )

    structural = next(item for item in issues if item["code"] == "planning_structural_drift")
    assert structural["invalid_invariants"] == [
        "primary_actor_agency", "knowledge_state",
    ]
    assert not planning_adaptation_issues_are_protocol_only(issues)


def test_unknown_evidence_id_is_protocol_failure_and_keeps_plan_out_of_semantic_repair() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：花穗核实库房异常。"
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(plan)
    receipt["event_reviews"][0]["plan_evidence_ids"] = ["PLAN-01-MISSING"]
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    issues = planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    )

    assert {item["code"] for item in issues} == {"evidence_binding"}
    assert planning_adaptation_issues_are_protocol_only(issues)


def test_missing_equivalent_reason_is_receipt_only_failure() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：花穗亲自核实库房异常。"
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(plan)
    receipt["event_reviews"][0]["reason"] = ""
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    issues = planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    )

    assert [item["code"] for item in issues] == ["adaptation_reason"]
    assert planning_adaptation_issues_are_protocol_only(issues)


def test_effective_contract_uses_authorized_plan_evidence_and_retains_formal_source() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：小厮报信后，花穗亲自核验。"
    receipt, candidates, _authority_sha256, planning_sha256 = receipt_for(plan)
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    artifact = {
        "version": 1,
        "status": "ready",
        "outline_sha256": "a" * 64,
        "planning_sha256": planning_sha256,
        "segment_count": 1,
        "segments": [normalized],
    }

    effective = effective_event_contracts([formal_contract()], artifact)[0]

    assert effective["source"] == "accepted_plan_adaptation"
    assert effective["formal_evidence"] == formal_contract()["evidence"]
    assert "小厮报信" in effective["evidence"]
    assert effective["adaptation"]["classification"] == "equivalent"


def test_effective_contract_merges_same_event_evidence_across_continuous_segments() -> None:
    first = {
        "event_reviews": [{
            "event_id": EVENT_ID,
            "classification": "presentation",
            "changed_dimensions": ["dialogue"],
            "invariants": invariant_payload(),
            "plan_evidence": ["第一段先让花穗听见报信，并决定亲自核验。"],
            "reason": "补充报信场景。",
        }],
    }
    second = {
        "event_reviews": [{
            "event_id": EVENT_ID,
            "classification": "equivalent",
            "changed_dimensions": ["evidence_method"],
            "invariants": invariant_payload(),
            "plan_evidence": ["第二段由花穗进入库房复核账箱，完成同一事件。"],
            "reason": "把核验过程展开到连续下一段。",
        }],
    }
    artifact = {
        "version": 1,
        "status": "ready",
        "outline_sha256": "a" * 64,
        "planning_sha256": "b" * 64,
        "segment_count": 2,
        "segments": [first, second],
    }

    effective = effective_event_contracts([formal_contract()], artifact)[0]

    assert effective["evidence"] == (
        "第一段先让花穗听见报信，并决定亲自核验。\n\n"
        "第二段由花穗进入库房复核账箱，完成同一事件。"
    )
    assert effective["adaptation"]["classification"] == "equivalent"
    assert effective["adaptation"]["changed_dimensions"] == [
        "dialogue", "evidence_method",
    ]
    assert effective["adaptation"]["reason"] == (
        "补充报信场景。；把核验过程展开到连续下一段。"
    )


def test_cross_genre_environment_actor_and_nonlinear_time_remain_supported() -> None:
    plan = (
        "### 第 1 段：气闸回声\n\n事件ID：EV-221A4437\n\n"
        "本段事件：倒叙中，舰载系统先报警，舰长复核日志后关闭气闸。"
    )
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan,
        changed_dimensions=["trigger_method", "scene_realization"],
    )
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_whole_story_gate_rejects_adjacent_handoff_regression() -> None:
    segment_receipts = [{"segment": 1, "summary": "ok"}, {"segment": 2, "summary": "ok"}]
    authority = planning_adaptation_whole_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment_receipts=segment_receipts,
    )
    receipt = normalize_planning_adaptation_whole_receipt({
        "authority_sha256": authority,
        "planning_sha256": "b" * 64,
        "segment_numbers": ["１", "２"],
        "event_ids": ["ｅｖ－２２１ａ４４３７"],
        "causal_order_preserved": "是",
        "adjacent_handoffs_preserved": "否",
        "knowledge_progression_preserved": "是",
        "relationship_progression_preserved": "是",
        "viewpoint_timeline_preserved": "是",
        "promises_ending_preserved": "是",
        "formal_direction_preserved": "是",
        "affected_segments": "２",
        "affected_event_ids": "ＥＶ－２２１Ａ４４３７",
        "reason": "第二段入口没有继承第一段出口。",
        "summary": "发现一个跨段衔接问题。",
    })
    issues = planning_adaptation_whole_receipt_issues(
        receipt,
        authority_sha256=authority,
        planning_sha256="b" * 64,
        segment_count=2,
        expected_event_ids=[EVENT_ID],
    )

    assert len(issues) == 1
    assert issues[0]["code"] == "planning_whole_story_drift"
    assert issues[0]["affected_segments"] == [2]


def test_whole_story_gate_requires_actionable_scope_for_a_reported_drift() -> None:
    segment_receipts = [{"segment": 1, "summary": "ok"}, {"segment": 2, "summary": "ok"}]
    authority = planning_adaptation_whole_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment_receipts=segment_receipts,
    )
    receipt = normalize_planning_adaptation_whole_receipt({
        "authority_sha256": authority,
        "planning_sha256": "b" * 64,
        "segment_numbers": "１，２",
        "event_ids": [EVENT_ID],
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": False,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [],
        "affected_event_ids": [],
        "reason": "第二段没有承接第一段出口。",
        "summary": "发现跨段问题，但回执遗漏了修正范围。",
    })

    issues = planning_adaptation_whole_receipt_issues(
        receipt,
        authority_sha256=authority,
        planning_sha256="b" * 64,
        segment_count=2,
        expected_event_ids=[EVENT_ID],
    )

    assert {item["code"] for item in issues} == {
        "whole_affected_scope", "planning_whole_story_drift",
    }
    assert planning_adaptation_issues_are_protocol_only(
        [item for item in issues if item["code"] == "whole_affected_scope"]
    )


def test_whole_story_gate_requires_a_reason_before_semantic_repair() -> None:
    segment_receipts = [{"segment": 1, "summary": "ok"}, {"segment": 2, "summary": "ok"}]
    authority = planning_adaptation_whole_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment_receipts=segment_receipts,
    )
    receipt = normalize_planning_adaptation_whole_receipt({
        "authority_sha256": authority,
        "planning_sha256": "b" * 64,
        "segment_numbers": [1, 2],
        "event_ids": [EVENT_ID],
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": False,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [2],
        "affected_event_ids": [EVENT_ID],
        "reason": "",
        "summary": "发现跨段衔接问题。",
    })

    issues = planning_adaptation_whole_receipt_issues(
        receipt,
        authority_sha256=authority,
        planning_sha256="b" * 64,
        segment_count=2,
        expected_event_ids=[EVENT_ID],
    )

    assert {item["code"] for item in issues} == {
        "whole_reason", "planning_whole_story_drift",
    }
    assert planning_adaptation_issues_are_protocol_only(
        [item for item in issues if item["code"] == "whole_reason"]
    )


def test_whole_story_gate_rejects_spurious_scope_when_everything_passes() -> None:
    segment_receipts = [{"segment": 1, "summary": "ok"}, {"segment": 2, "summary": "ok"}]
    authority = planning_adaptation_whole_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment_receipts=segment_receipts,
    )
    receipt = normalize_planning_adaptation_whole_receipt({
        "authority_sha256": authority,
        "planning_sha256": "b" * 64,
        "segment_numbers": [1, 2],
        "event_ids": [EVENT_ID],
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": True,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [2],
        "affected_event_ids": [EVENT_ID],
        "reason": "",
        "summary": "整篇通过。",
    })

    issues = planning_adaptation_whole_receipt_issues(
        receipt,
        authority_sha256=authority,
        planning_sha256="b" * 64,
        segment_count=2,
        expected_event_ids=[EVENT_ID],
    )

    assert [item["code"] for item in issues] == ["whole_affected_scope"]
