from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.planning_adaptation import (
    INVARIANT_FIELDS,
    LEGACY_PLANNING_ADAPTATION_VERSION,
    PLANNING_ADAPTATION_VERSION,
    PREVIOUS_PLANNING_ADAPTATION_VERSION,
    apply_planning_repair_patch,
    effective_event_contracts,
    normalize_planning_adaptation_receipt,
    normalize_planning_adaptation_whole_receipt,
    planning_adaptation_evidence_candidates,
    planning_adaptation_issues_are_protocol_only,
    planning_adaptation_receipt_issues,
    planning_event_body_issues,
    planning_event_body_retention_issues,
    planning_event_obligation_issues,
    repair_planning_event_obligation_ownership,
    planning_semantic_evidence_spans,
    planning_adaptation_segment_authority_sha256,
    planning_adaptation_whole_authority_sha256,
    planning_adaptation_whole_receipt_issues,
    planning_repair_anchor_ids,
    planning_repair_patch_from_segment,
    planning_repair_patch_authority_sha256,
    normalize_planning_repair_patch,
)


@pytest.mark.parametrize("event_text", [
    "沈老夫人宣布认下花穗；沈大小姐站出来替花穗说话。",
    "沈大小姐维护花穗，沈老夫人随后认可她；花穗只得到旁人的回答。",
])
def test_planning_event_obligation_issues_catch_missing_required_responder(
    event_text: str,
) -> None:
    segment = (
        "### 第 5 段：选择与承认\n\n"
        "事件ID：EV-BEAE4985\n\n"
        f"本段事件：{event_text}\n"
    )
    checklist = {
        "EV-BEAE4985": {
            "label": "众人的反应",
            "required_participants": ["沈老夫人", "花穗", "沈大小姐", "裴砚行"],
            "obligations": [{
                "id": "EV-BEAE4985-B03",
                "kinds": ["reaction", "commitment"],
                "required_participants": ["花穗", "裴砚行"],
                "source_excerpt": "花穗追问裴砚行，他当众承诺会护着她。",
            }],
        },
    }

    issues = planning_event_obligation_issues(
        segment, ["EV-BEAE4985"], checklist,
    )

    assert len(issues) == 1
    assert issues[0]["code"] == "planning_required_participant_missing"
    assert issues[0]["event_id"] == "EV-BEAE4985"
    assert issues[0]["missing_participants"] == ["裴砚行"]
    assert set(issues[0]["invalid_invariants"]) == {
        "event_function", "primary_actor_agency", "exit_state",
        "relationship_state", "promise_ending",
    }


@pytest.mark.parametrize("event_text", [
    (
        "沈老夫人宣布认下花穗；沈大小姐站出来替花穗说话；"
        "花穗追问裴砚行，他当众承诺会护着她。"
    ),
    (
        "花穗先问裴砚行是否愿意把话说清，裴砚行正面回应并许下往后承诺；"
        "沈大小姐维护花穗，沈老夫人最终认可花穗。"
    ),
    (
        "“我认她。”沈老夫人点明花穗；沈大小姐随即维护花穗。"
        "面对花穗的追问，裴砚行公开回应，两人的关系承诺由此成立。"
    ),
    (
        "沈大小姐挡到花穗身前，沈老夫人也认可花穗的担当。"
        "花穗转身追问裴砚行，裴砚行没有回避，当众给出共同面对的承诺。"
    ),
    (
        "裴砚行先回应花穗并明确二人今后的关系；花穗确认他的选择后，"
        "沈大小姐维护花穗，沈老夫人正式表示认可。"
    ),
    (
        "沈老夫人认可花穗，沈大小姐维护花穗；花穗问，裴砚行答，"
        "公开承诺落定。"
    ),
])
def test_planning_event_obligation_issues_allow_complete_multi_participant_event(
    event_text: str,
) -> None:
    segment = (
        "### 第 5 段：选择与承认\n\n"
        "事件ID：EV-BEAE4985\n\n"
        f"本段事件：{event_text}\n"
    )
    checklist = {
        "EV-BEAE4985": {
            "label": "众人的反应",
            "required_participants": ["沈老夫人", "沈大小姐", "花穗", "裴砚行"],
            "obligations": [{
                "id": "EV-BEAE4985-B03",
                "kinds": ["reaction", "commitment"],
                "required_participants": ["花穗", "裴砚行"],
                "source_excerpt": "花穗追问裴砚行，他当众承诺会护着她。",
            }],
        },
    }

    assert planning_event_obligation_issues(
        segment, ["EV-BEAE4985"], checklist,
    ) == []


def test_planning_event_obligation_does_not_borrow_an_unowned_numbered_item() -> None:
    segment = (
        "### 第 5 段：选择与承认\n\n"
        "事件ID：EV-BEAE4985、EV-1522AB0E\n\n"
        "本段事件：\n\n"
        "4. **沈蕙兰与沈老夫人的反应**（EV-BEAE4985）。"
        "沈大小姐维护花穗，沈老夫人认可花穗。\n\n"
        "5. **花穗主动问裴砚行**。花穗追问裴砚行，"
        "裴砚行回应并给出往后承诺。\n\n"
        "6. **正式认下**（EV-1522AB0E）。沈老夫人宣布认下花穗。\n\n"
        "段末交接：花穗成为沈府义女。"
    )
    checklist = {
        "EV-BEAE4985": {
            "label": "众人的反应",
            "required_participants": ["沈老夫人", "沈大小姐", "花穗", "裴砚行"],
            "obligations": [{
                "id": "EV-BEAE4985-B03",
                "kinds": ["action", "reaction", "commitment"],
                "required_participants": ["花穗", "裴砚行"],
                "source_excerpt": "花穗追问裴砚行，他回应并给出往后承诺。",
            }],
        },
    }

    issues = planning_event_obligation_issues(
        segment, ["EV-BEAE4985", "EV-1522AB0E"], checklist,
    )

    assert len(issues) == 1
    assert issues[0]["event_id"] == "EV-BEAE4985"
    assert issues[0]["missing_participants"] == ["裴砚行"]


def test_planning_event_obligation_repair_merges_unique_continuation_item() -> None:
    segment = (
        "### 第 5 段：选择与承认\n\n"
        "事件ID：EV-15C208EE、EV-126EE846、EV-BEAE4985、EV-1522AB0E\n\n"
        "本段事件：\n\n"
        "4. **沈蕙兰与沈老夫人的反应**（EV-BEAE4985）。"
        "沈大小姐替花穗说话，沈老夫人认可花穗。\n\n"
        "5. **花穗主动问裴砚行**。花穗追问裴砚行，"
        "裴砚行回应并给出往后承诺。\n\n"
        "6. **正式认下**（EV-1522AB0E）。沈老夫人宣布认下花穗。\n\n"
        "段末交接：花穗成为沈府义女。"
    )
    checklist = {
        "EV-BEAE4985": {
            "required_participants": ["沈老夫人", "沈大小姐", "花穗", "裴砚行"],
            "identity_stable_participants": ["花穗", "裴砚行"],
            "obligations": [{
                "id": "EV-BEAE4985-B03",
                "required_participants": ["花穗", "裴砚行"],
                "kinds": ["reaction", "commitment"],
            }],
        },
    }

    repaired, repairs = repair_planning_event_obligation_ownership(
        segment, ["EV-BEAE4985", "EV-1522AB0E"], checklist,
    )

    assert repairs[0]["repair"] == "merge_unlabelled_continuation_into_prior_event"
    assert "5. **花穗主动问裴砚行**" not in repaired
    assert "**花穗主动问裴砚行**" in repaired
    assert planning_event_obligation_issues(
        repaired, ["EV-BEAE4985", "EV-1522AB0E"], checklist,
    ) == []


def test_semantic_evidence_anchors_keep_the_event_block_but_isolate_the_bad_clause() -> None:
    segment = (
        "### 第 2 段：野路子破规矩\n\n"
        "事件ID：EV-5306BA80\n\n"
        "本段事件：\n"
        "3. **井边嗑瓜子**（EV-5306BA80）。沈蕙兰撞见花穗蹲在井边和洗衣婆子一起嗑瓜子，"
        "气得发抖。花穗抬头反问，洗衣婆子们忍着笑。沈蕙兰拂袖而去，却把花穗那句话记在心里。\n\n"
        "段末交接：裴砚行开始重新观察花穗。"
    )

    spans = planning_semantic_evidence_spans(segment, 2)
    bad = next(item for item in spans if item["text"] == "却把花穗那句话记在心里。")

    assert bad["parent_event_id"] == "EV-5306BA80"
    assert bad["kind"] == "semantic_clause"
    assert segment[bad["start"]:bad["end"]] == bad["text"]
    assert len(bad["text"]) < len(next(
        item["text"] for item in spans if item["kind"] == "event_block"
    ))


def test_event_id_in_header_does_not_hide_a_missing_event_body() -> None:
    collapsed = (
        "### 第 2 段：野路子破规矩\n\n"
        "事件ID：EV-5306BA80\n\n"
        "大纲依据：井边嗑瓜子\n\n"
        "段首承接：花穗进入后院。\n\n"
        "本段事件：。\n\n"
        "段末交接：裴砚行开始重新观察花穗。"
    )

    issues = planning_event_body_issues(collapsed, ["EV-5306BA80"])

    assert {item["code"] for item in issues} == {"event_body_missing"}
    assert issues[0]["event_id"] == "EV-5306BA80"


def test_adjacent_event_ids_may_share_one_complete_body() -> None:
    segment = (
        "### 第 6 段：扎根新家\n\n"
        "事件ID：EV-A42514C2、EV-CBFB58B0\n\n"
        "本段事件：\n"
        "2. **老槐树下定情**（EV-A42514C2、EV-CBFB58B0）。"
        "裴砚行在老槐树下正式求娶，花穗递给他一壶浊酒，两人以玩笑确认关系并约定继续追查。\n\n"
        "段末交接：花穗选择留在沈府。"
    )

    issues = planning_event_body_issues(
        segment, ["EV-A42514C2", "EV-CBFB58B0"],
    )

    assert issues == []


def test_three_adjacent_event_ids_may_share_one_complete_body() -> None:
    segment = (
        "### 第 6 段：扎根新家\n\n"
        "事件ID：EV-A42514C2、EV-CBFB58B0、EV-E8D90A75\n\n"
        "本段事件：\n"
        "2. **关系与收束**（EV-A42514C2、EV-CBFB58B0、EV-E8D90A75）。"
        "裴砚行求娶，花穗用浊酒回应，两人约定追查旧案，随后花穗确认自己会以真名留在沈府。\n\n"
        "段末交接：故事完整收束。"
    )

    issues = planning_event_body_issues(
        segment, ["EV-A42514C2", "EV-CBFB58B0", "EV-E8D90A75"],
    )

    assert issues == []


def test_separate_event_id_still_requires_its_own_body() -> None:
    segment = (
        "### 第 6 段：扎根新家\n\n"
        "事件ID：EV-A42514C2、EV-CBFB58B0\n\n"
        "本段事件：\n"
        "1. EV-A42514C2。\n"
        "2. EV-CBFB58B0：花穗用浊酒回应求娶，两人约定继续追查旧案。\n\n"
        "段末交接：花穗选择留下。"
    )

    issues = planning_event_body_issues(
        segment, ["EV-A42514C2", "EV-CBFB58B0"],
    )

    assert any(
        item["code"] == "event_body_incomplete"
        and item["event_id"] == "EV-A42514C2"
        for item in issues
    )


def test_event_repair_cannot_replace_a_complete_event_with_one_exit_sentence() -> None:
    source = (
        "### 第 2 段：野路子破规矩\n\n"
        "事件ID：EV-5306BA80\n\n"
        "本段事件：\n"
        "3. **井边嗑瓜子**（EV-5306BA80）。沈蕙兰撞见花穗和洗衣婆子聊天，"
        "双方当场争论门风，花穗用市井逻辑反问，洗衣婆子们的反应推动沈蕙兰重新观察她。\n\n"
        "段末交接：裴砚行开始重新观察花穗。"
    )
    collapsed = source.replace(
        "3. **井边嗑瓜子**（EV-5306BA80）。沈蕙兰撞见花穗和洗衣婆子聊天，"
        "双方当场争论门风，花穗用市井逻辑反问，洗衣婆子们的反应推动沈蕙兰重新观察她。",
        "沈蕙兰拂袖而去。",
    )

    issues = planning_event_body_retention_issues(
        source, collapsed, ["EV-5306BA80"],
    )

    assert {item["code"] for item in issues} == {"event_body_collapsed"}


def test_missing_event_body_is_structural_not_an_impossible_evidence_protocol_retry() -> None:
    event_id = "EV-5306BA80"
    segment = (
        "### 第 2 段：野路子破规矩\n\n"
        f"事件ID：{event_id}\n\n"
        "本段事件：。\n\n"
        "段末交接：裴砚行开始重新观察花穗。"
    )
    receipt = {
        "authority_sha256": "a" * 64,
        "planning_sha256": "b" * 64,
        "segment": 2,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "structural",
            "changed_dimensions": ["event_function"],
            "invariants": {
                field: field != "event_function" for field in INVARIANT_FIELDS
            },
            "plan_evidence_ids": [],
            "plan_evidence": [],
            "reason": "当前事件正文已经缺失。",
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "事件正文需要恢复。",
    }

    issues = planning_adaptation_receipt_issues(
        receipt,
        authority_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=2,
        expected_event_ids=[event_id],
        evidence_candidates=planning_adaptation_evidence_candidates(segment, 2),
        plan_segment=segment,
    )
    codes = {item["code"] for item in issues}

    assert "event_body_missing" in codes
    assert "planning_structural_drift" in codes
    assert "evidence_binding" not in codes


def test_production_stale_review_quote_is_protocol_only_until_bound_to_current_plan() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_review_evidence_semantic_mismatch_13ab5b72.json")
        .read_text(encoding="utf-8")
    )
    event_id = fixture["event_id"]
    segment = fixture["current_plan_segment"]
    candidates = planning_adaptation_evidence_candidates(segment, 2)
    evidence_id = next(
        key for key, value in candidates.items()
        if fixture["selected_current_quote"] in value
    )
    invariants = invariant_payload()
    invariants["knowledge_state"] = False
    invariants["relationship_state"] = False
    receipt = {
        "authority_sha256": "a" * 64,
        "planning_sha256": "b" * 64,
        "segment": 2,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "structural",
            "changed_dimensions": ["knowledge_state", "relationship_state"],
            "invariants": invariants,
            "plan_evidence_ids": [evidence_id],
            "plan_evidence_quote": fixture["stale_rejected_quote"],
            "reason": fixture["stale_reason"],
        }],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": fixture["stale_reason"],
    }
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    stale_issues = planning_adaptation_receipt_issues(
        normalized,
        authority_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=2,
        expected_event_ids=[event_id],
        evidence_candidates=candidates,
        plan_segment=segment,
    )

    assert {item["code"] for item in stale_issues} == {"evidence_binding"}
    assert planning_adaptation_issues_are_protocol_only(stale_issues)

    current_quote = fixture["selected_current_quote"]
    receipt["event_reviews"][0]["plan_evidence_quote"] = current_quote
    receipt["event_reviews"][0]["reason"] = (
        f"{current_quote}；该句仍可能把不可确认的知情状态写成事实。"
    )
    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    current_issues = planning_adaptation_receipt_issues(
        normalized,
        authority_sha256="a" * 64,
        planning_sha256="b" * 64,
        segment=2,
        expected_event_ids=[event_id],
        evidence_candidates=candidates,
        plan_segment=segment,
    )

    structural = next(
        item for item in current_issues
        if item["code"] == "planning_structural_drift"
    )
    anchors = planning_repair_anchor_ids([structural], candidates)
    assert structural["plan_evidence_quote"] == current_quote
    assert len(anchors) == 1
    assert current_quote in candidates[anchors[0]]
    assert len(candidates[anchors[0]]) < len(candidates[evidence_id])


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
    evidence_id = next(
        (
            key for key, value in candidates.items()
            if "本段事件" in value
        ),
        next(iter(candidates)),
    )
    planning_sha256 = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    authority_sha256 = planning_adaptation_segment_authority_sha256(
        outline_sha256="a" * 64,
        planning_sha256=planning_sha256,
        segment=1,
        event_contracts=[formal_contract()],
        plan_segment=plan,
    )
    negative = any(
        value is False for value in (invariants or {}).values()
    )
    evidence_quote = candidates[evidence_id] if negative else ""
    reason = "发现入口变化，但花穗仍完成核实并主导后续查证。"
    if evidence_quote:
        reason = f"{evidence_quote}；该原文体现正式不变量发生偏移。"
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
            "plan_evidence_quote": evidence_quote,
            "reason": reason,
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


@pytest.mark.parametrize("dimensions", [
    ["触发方式", "局部证据取得方式"],
    ["局部顺序", "场景表现", "次要动作", "心理呈现"],
    ["trigger", "description", "secondary_action"],
    ["description", "dialogue", "causal_explanation"],
    ["evidence_acquisition"],
])
def test_production_shaped_free_dimension_names_never_own_blocking_power(
    dimensions,
) -> None:
    plan = (
        "### 第 1 段：宴席试探\n\n事件ID：EV-221A4437\n\n"
        "本段事件：花穗在宴席上应对试探，仍亲自决定下一步行动。"
    )
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan, classification="模型自定义的局部展开", changed_dimensions=dimensions,
    )

    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    review = normalized["event_reviews"][0]
    assert review["classification"] == "equivalent"
    assert review["classification_source"] == "runtime_invariants"
    assert review["raw_changed_dimensions"] == dimensions
    assert set(review["unrecognized_dimensions"]).issubset(set(dimensions))
    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_unknown_model_classification_is_derived_from_invariants_and_description() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：花穗亲自核账。"
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan,
        classification="局部戏剧化但方向不变",
        changed_dimensions=["心理呈现"],
    )

    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    review = normalized["event_reviews"][0]

    assert review["raw_classification"] == "局部戏剧化但方向不变"
    assert review["model_classification"] == "局部戏剧化但方向不变"
    assert review["classification"] == "equivalent"
    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_descriptor_invariant_conflict_retries_only_the_receipt() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：花穗亲自核账。"
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan,
        classification="equivalent",
        changed_dimensions=["primary_actor_agency"],
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

    assert [item["code"] for item in issues] == ["adaptation_receipt_conflict"]
    assert planning_adaptation_issues_are_protocol_only(issues)


def test_soft_noncausal_order_is_authorized_without_rewriting_plan() -> None:
    plan = "### 第 1 段：交错展示\n\n事件ID：EV-221A4437\n\n本段事件：先展示结果，再回切到同场景的核验过程。"
    invariants = invariant_payload()
    invariants["timeline_order"] = False
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan, changed_dimensions=["micro_order"], invariants=invariants,
    )
    review = receipt["event_reviews"][0]
    review["order_dependency"] = "soft"
    review["dependency_event_ids"] = []

    normalized = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )

    assert normalized["event_reviews"][0]["soft_order_authorized"] is True
    assert planning_adaptation_receipt_issues(
        normalized,
        authority_sha256=authority_sha256,
        planning_sha256=planning_sha256,
        segment=1,
        expected_event_ids=[EVENT_ID],
        evidence_candidates=candidates,
    ) == []


def test_unknown_order_dependency_retries_receipt_without_rewriting_plan() -> None:
    plan = "### 第 1 段：倒叙\n\n事件ID：EV-221A4437\n\n本段事件：倒叙展示核验。"
    invariants = invariant_payload()
    invariants["timeline_order"] = False
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan, changed_dimensions=["timeline_order"], invariants=invariants,
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

    assert [item["code"] for item in issues] == [
        "adaptation_order_uncertain",
    ]
    assert planning_adaptation_issues_are_protocol_only(issues)


def test_hard_cross_segment_dependency_uses_full_outline_authority() -> None:
    plan = "### 第 2 段：后果\n\n事件ID：EV-221A4437\n\n本段事件：结果被错误地放到原因之前。"
    invariants = invariant_payload()
    invariants["timeline_order"] = False
    receipt, candidates, authority_sha256, planning_sha256 = receipt_for(
        plan, changed_dimensions=["timeline_order"], invariants=invariants,
    )
    review = receipt["event_reviews"][0]
    review["order_dependency"] = "hard"
    review["dependency_event_ids"] = ["ev-previous1"]
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
        authority_event_ids=["EV-PREVIOUS1", EVENT_ID],
    )

    assert [item["code"] for item in issues] == ["planning_structural_drift"]
    assert issues[0]["invalid_invariants"] == ["timeline_order"]


def test_v2_segment_authority_reuses_unaffected_segment_but_binds_boundaries() -> None:
    values = {
        "outline_sha256": "a" * 64,
        "segment": 2,
        "event_contracts": [formal_contract()],
        "plan_segment": "### 第 2 段：核验",
        "previous_handoff": "第一段出口",
        "next_entry": "第三段入口",
        "generation_context_sha256": "c" * 64,
    }
    first = planning_adaptation_segment_authority_sha256(
        planning_sha256="1" * 64,
        version=PREVIOUS_PLANNING_ADAPTATION_VERSION, **values,
    )
    unrelated_plan_changed = planning_adaptation_segment_authority_sha256(
        planning_sha256="2" * 64,
        version=PREVIOUS_PLANNING_ADAPTATION_VERSION, **values,
    )
    adjacent_boundary_changed = planning_adaptation_segment_authority_sha256(
        planning_sha256="2" * 64,
        version=PREVIOUS_PLANNING_ADAPTATION_VERSION,
        **{**values, "previous_handoff": "改变后的第一段出口"},
    )
    legacy_first = planning_adaptation_segment_authority_sha256(
        planning_sha256="1" * 64,
        version=LEGACY_PLANNING_ADAPTATION_VERSION,
        **values,
    )
    legacy_changed = planning_adaptation_segment_authority_sha256(
        planning_sha256="2" * 64,
        version=LEGACY_PLANNING_ADAPTATION_VERSION,
        **values,
    )

    assert first == unrelated_plan_changed
    assert first != adjacent_boundary_changed
    assert legacy_first != legacy_changed


def test_v3_segment_authority_leaves_neighbor_boundaries_to_whole_review() -> None:
    values = {
        "outline_sha256": "a" * 64,
        "planning_sha256": "1" * 64,
        "segment": 2,
        "event_contracts": [formal_contract()],
        "plan_segment": "### 第 2 段：核验",
        "previous_handoff": "第一段出口",
        "next_entry": "第三段入口",
        "generation_context_sha256": "c" * 64,
        "version": PLANNING_ADAPTATION_VERSION,
    }
    first = planning_adaptation_segment_authority_sha256(**values)
    changed = planning_adaptation_segment_authority_sha256(
        **{**values, "previous_handoff": "改变后的第一段出口"},
    )

    assert first == changed


def test_evidence_patch_changes_only_authorized_anchor() -> None:
    plan = (
        "### 第 1 段：核验\n\n"
        "事件ID：EV-221A4437\n\n"
        "段首承接：花穗正在查账。\n\n"
        "本段事件：小厮替花穗完成全部核验。\n\n"
        "段末交接：花穗取得证据。"
    )
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    anchor_id = next(
        key for key, value in candidates.items() if "小厮替花穗" in value
    )
    issues = [{"plan_evidence_ids": [anchor_id]}]
    assert planning_repair_anchor_ids(issues, candidates) == [anchor_id]
    authority = planning_repair_patch_authority_sha256(
        planning_sha256="b" * 64,
        segment=1,
        issue_keys=["planning:segment-01:primary_actor_agency"],
        anchor_ids=[anchor_id],
    )
    patch = normalize_planning_repair_patch({
        "authority_sha256": authority,
        "segment": 1,
        "replacements": [{
            "evidence_id": anchor_id,
            "replacement": "本段事件：花穗亲自核验，小厮只负责报信。",
        }],
        "summary": "恢复正式执行者",
    }, authority_sha256=authority, segment=1,
        evidence_candidates=candidates, allowed_anchor_ids=[anchor_id],
        current_segment=plan)

    repaired = apply_planning_repair_patch(plan, patch, candidates)

    assert "花穗亲自核验" in repaired
    assert "段首承接：花穗正在查账。" in repaired
    assert "段末交接：花穗取得证据。" in repaired


def test_evidence_patch_rejects_unrelated_anchor() -> None:
    plan = (
        "### 第 1 段：核验\n\n事件ID：EV-221A4437\n\n"
        "段首承接：花穗开始检查账目缺口。\n\n"
        "本段事件：花穗亲自进入库房核验异常。\n\n"
        "段末交接：花穗取得继续追查的可靠证据。"
    )
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    allowed = next(iter(candidates))
    unrelated = next(key for key in candidates if key != allowed)
    authority = planning_repair_patch_authority_sha256(
        planning_sha256="b" * 64, segment=1,
        issue_keys=["planning:segment-01:test"], anchor_ids=[allowed],
    )

    with pytest.raises(ValueError):
        normalize_planning_repair_patch({
            "authority_sha256": authority,
            "segment": 1,
            "replacements": [{
                "evidence_id": unrelated,
                "replacement": "越界修改",
            }],
        }, authority_sha256=authority, segment=1,
            evidence_candidates=candidates, allowed_anchor_ids=[allowed],
            current_segment=plan)


def test_legacy_full_segment_response_is_narrowed_to_authorized_anchor() -> None:
    plan = (
        "### 第 1 段：核验\n\n事件ID：EV-221A4437\n\n"
        "段首承接：花穗开始检查账目缺口。\n\n"
        "本段事件：小厮替花穗完成全部核验。\n\n"
        "段末交接：花穗取得继续追查的可靠证据。"
    )
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    anchor_id = next(
        key for key, value in candidates.items() if "小厮替花穗" in value
    )
    authority = planning_repair_patch_authority_sha256(
        planning_sha256="b" * 64, segment=1,
        issue_keys=["planning:segment-01:primary_actor_agency"],
        anchor_ids=[anchor_id],
    )
    candidate = plan.replace(
        candidates[anchor_id],
        "本段事件：花穗亲自核验，小厮只负责报信。",
    )

    patch = planning_repair_patch_from_segment(
        candidate,
        authority_sha256=authority,
        segment=1,
        evidence_candidates=candidates,
        allowed_anchor_ids=[anchor_id],
        current_segment=plan,
    )

    assert apply_planning_repair_patch(plan, patch, candidates) == candidate


@pytest.mark.parametrize("outside_change", [
    ("### 第 1 段：核验", "### 第 1 段：改题"),
    ("事件ID：EV-221A4437", "事件ID：EV-FFFFFFFF"),
    ("段末交接：花穗取得继续追查的可靠证据。", "段末交接：提前公开真相。"),
])
def test_legacy_full_segment_response_rejects_changes_outside_authorized_anchor(
    outside_change: tuple[str, str],
) -> None:
    plan = (
        "### 第 1 段：核验\n\n事件ID：EV-221A4437\n\n"
        "段首承接：花穗开始检查账目缺口。\n\n"
        "本段事件：小厮替花穗完成全部核验。\n\n"
        "段末交接：花穗取得继续追查的可靠证据。"
    )
    candidates = planning_adaptation_evidence_candidates(plan, 1)
    anchor_id = next(
        key for key, value in candidates.items() if "小厮替花穗" in value
    )
    authority = planning_repair_patch_authority_sha256(
        planning_sha256="b" * 64, segment=1,
        issue_keys=["planning:segment-01:primary_actor_agency"],
        anchor_ids=[anchor_id],
    )
    candidate = plan.replace(
        candidates[anchor_id],
        "本段事件：花穗亲自核验，小厮只负责报信。",
    ).replace(*outside_change)

    with pytest.raises(ValueError, match="授权锚点以外"):
        planning_repair_patch_from_segment(
            candidate,
            authority_sha256=authority,
            segment=1,
            evidence_candidates=candidates,
            allowed_anchor_ids=[anchor_id],
            current_segment=plan,
        )


def test_receipt_normalization_is_idempotent_with_unknown_unicode_metadata() -> None:
    plan = "### 第 1 段：查账\n\n事件ID：EV-221A4437\n\n本段事件：花穗亲自核账。"
    receipt, candidates, _authority_sha256, _planning_sha256 = receipt_for(
        plan,
        classification="✨局部呈现✨",
        changed_dimensions=["心理呈现", "证据取得方式", "🧭转场感"],
    )

    first = normalize_planning_adaptation_receipt(
        receipt, evidence_candidates=candidates,
    )
    second = normalize_planning_adaptation_receipt(
        first, evidence_candidates=candidates,
    )

    assert second == first


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
