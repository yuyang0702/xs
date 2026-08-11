import hashlib
import re

import pytest

from novel_flywheel.draft_split import (
    DraftTaskContract,
    align_semantic_receipt_evidence,
    align_whole_draft_receipt_evidence,
    exact_event_partition,
    render_draft_task_prompt,
    residual_target,
    semantic_receipt_issues,
    target_bounds,
    validate_semantic_receipt,
    validate_whole_draft_receipt,
)
from novel_flywheel.execution_manifest import FutureBeatGuard


def _contract(**changes) -> DraftTaskContract:
    values = {
        "authority_sha256": "a" * 64,
        "task_id": "segment-02/sub-1",
        "parent_task_id": "segment-02",
        "depth": 1,
        "target_han": 541,
        "event_ids": ("EV-00000001", "EV-00000002"),
        "scope": "只完成线索发现与当场质问",
        "entry_state": "花穗仍在沈府前厅，尚未知道账本来源",
        "exit_requirement": "花穗拿到账本，但尚未拆穿身份",
        "previous_sibling_sha256": "",
    }
    values.update(changes)
    return DraftTaskContract(**values)


def test_rendered_child_prompt_has_one_fresh_target_and_exact_current_contract() -> None:
    prompt = render_draft_task_prompt("正式大纲与整篇约束", _contract())

    assert re.findall(r"本次唯一字数目标：约 (\d+) 个正文汉字", prompt) == ["541"]
    assert "本次允许完整场景范围：243-784 个正文汉字" in prompt
    assert '"event_ids":["EV-00000001","EV-00000002"]' in prompt
    assert '"parent_task_id":"segment-02"' in prompt
    assert "花穗仍在沈府前厅" in prompt
    assert "花穗拿到账本" in prompt


def test_rendered_child_prompt_keeps_the_bound_first_person_narrator() -> None:
    prompt = render_draft_task_prompt(
        "规划材料仍以花穗称呼主角。",
        _contract(
            narrative_mode="first_person_limited",
            narrator_character_id="hua-sui",
            narrator_name="花穗",
            self_reference="我",
        ),
    )

    assert "叙述者是花穗（hua-sui）" in prompt
    assert "花穗自身必须使用“我”叙述" in prompt
    assert "规划中的第三人称人物名只表示事件权威" in prompt


def test_rendered_child_prompt_rejects_authority_with_inherited_numeric_target() -> None:
    with pytest.raises(ValueError, match="stale numeric target"):
        render_draft_task_prompt(
            "正式大纲。目标约 2167 个正文汉字。",
            _contract(target_han=541),
        )


def test_exact_event_partition_rejects_omission_duplication_and_reordering() -> None:
    parent = ("EV-1", "EV-2", "EV-3", "EV-4")

    assert exact_event_partition(parent, ("EV-1", "EV-2"), ("EV-3", "EV-4"))
    assert not exact_event_partition(parent, ("EV-1",), ("EV-3", "EV-4"))
    assert not exact_event_partition(parent, ("EV-1", "EV-2"), ("EV-2", "EV-4"))
    assert not exact_event_partition(parent, ("EV-2", "EV-1"), ("EV-3", "EV-4"))


def test_residual_target_uses_accepted_first_child_length_without_truncation() -> None:
    assert residual_target(1083, accepted_first_han=620) == 463
    assert residual_target(1083, accepted_first_han=900) == 400


def test_contract_requires_hash_and_nonempty_owned_scope() -> None:
    with pytest.raises(ValueError, match="authority_sha256"):
        _contract(authority_sha256="bad")
    with pytest.raises(ValueError, match="event_ids"):
        _contract(event_ids=("EV-1", "EV-1"))
    with pytest.raises(ValueError, match="target_han"):
        _contract(target_han=0)
    with pytest.raises(ValueError, match="depth"):
        _contract(depth=3)


def test_target_bounds_are_the_single_length_policy_for_every_task_level() -> None:
    assert target_bounds(1000) == (450, 1450)
    with pytest.raises(ValueError, match="target"):
        target_bounds(0)


def test_previous_sibling_hash_can_bind_the_second_child_to_accepted_text() -> None:
    accepted = "前半段已经验收"
    digest = hashlib.sha256(accepted.encode("utf-8")).hexdigest()

    prompt = render_draft_task_prompt(
        "正式大纲与整篇约束",
        _contract(
            task_id="segment-02/sub-2",
            previous_sibling_sha256=digest,
            entry_state=accepted,
        ),
    )

    assert digest in prompt
    assert accepted in prompt


def test_semantic_receipt_must_bind_exact_prose_and_prove_every_owned_event() -> None:
    prose = "花穗在前厅接过账本。她核对印章后，当面质问管事。"
    contract = _contract(event_ids=("EV-00000001", "EV-00000002"))
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "event_receipts": [
            {"event_id": "EV-00000001", "evidence": "花穗在前厅接过账本"},
            {"event_id": "EV-00000002", "evidence": "当面质问管事"},
        ],
        "entry": {"satisfied": True, "evidence": "花穗在前厅"},
        "exit": {"satisfied": True, "evidence": "当面质问管事"},
        "outside_event_ids": [],
        "causal_order_valid": True,
        "causal_order_evidence": "花穗在前厅接过账本。她核对印章后，当面质问管事",
        "summary": "花穗取得账本并由核验推进到质问。",
    }

    validated = validate_semantic_receipt(contract, prose, receipt)

    assert validated["prose_sha256"] == receipt["prose_sha256"]
    broken = {**receipt, "event_receipts": receipt["event_receipts"][:1]}
    with pytest.raises(ValueError, match="event"):
        validate_semantic_receipt(contract, prose, broken)
    with pytest.raises(ValueError, match="outside"):
        validate_semantic_receipt(
            contract, prose, {**receipt, "outside_event_ids": ["EV-99999999"]},
        )
    with pytest.raises(ValueError, match="exit"):
        validate_semantic_receipt(
            contract, prose,
            {**receipt, "exit": {"satisfied": False, "evidence": "当面质问管事"}},
        )
    with pytest.raises(ValueError, match="causal"):
        validate_semantic_receipt(
            contract, prose, {**receipt, "causal_order_valid": False},
        )


def test_atomic_beat_receipt_rejects_future_beat_and_wrong_viewpoint() -> None:
    prose = "我看着沈老夫人派人出府核实身份，转身守在账房外。"
    contract = _contract(
        event_ids=("EV-8E4BBA17",),
        beat_ids=("EV-8E4BBA17/01",),
        execution_manifest_sha256="b" * 64,
        viewpoint="first-person",
        future_beat_guard=FutureBeatGuard(
            order_floor=2, count=1, scope_sha256="c" * 64,
        ),
    )
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "execution_manifest_sha256": contract.execution_manifest_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "beat_receipts": [{
            "beat_id": "EV-8E4BBA17/01", "evidence": "沈老夫人派人出府核实身份",
            "actor_action_valid": True,
            "actor_action_evidence": "沈老夫人派人出府核实身份",
            "state_valid": True,
            "state_evidence": "我看着沈老夫人派人出府核实身份",
            "scene_order_valid": True,
            "scene_order_evidence": "沈老夫人派人出府核实身份，转身守在账房外",
        }],
        "entry": {"satisfied": True, "evidence": "我看着沈老夫人"},
        "exit": {"satisfied": True, "evidence": "转身守在账房外"},
        "outside_beat_ids": [],
        "future_beat_ids": [],
        "viewpoint_valid": True,
        "viewpoint_evidence": "我看着沈老夫人",
        "causal_order_valid": True,
        "causal_order_evidence": "沈老夫人派人出府核实身份，转身守在账房外",
        "summary": "本段只执行派人核实这一原子节拍。",
    }

    assert validate_semantic_receipt(contract, prose, receipt)["beat_receipts"]
    with pytest.raises(ValueError, match="future beat"):
        validate_semantic_receipt(
            contract, prose, {**receipt, "future_beat_ids": ["EV-8E4BBA17/02"]},
        )
    with pytest.raises(ValueError, match="viewpoint"):
        validate_semantic_receipt(
            contract, prose, {**receipt, "viewpoint_valid": False},
        )


def test_semantic_receipt_reports_all_independent_contract_failures() -> None:
    prose = "我看着沈老夫人派人出府。"
    contract = _contract(
        event_ids=("EV-8E4BBA17",), beat_ids=("EV-8E4BBA17/01",),
        execution_manifest_sha256="b" * 64, viewpoint="first-person",
    )
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "execution_manifest_sha256": contract.execution_manifest_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "beat_receipts": [{
            "beat_id": "EV-8E4BBA17/01",
            "evidence": prose,
            "actor_action_valid": False,
            "actor_action_evidence": prose,
            "state_valid": False,
            "state_evidence": prose,
            "scene_order_valid": False,
            "scene_order_evidence": prose,
        }],
        "entry": {"satisfied": False, "evidence": prose},
        "exit": {"satisfied": False, "evidence": prose},
        "outside_beat_ids": ["EV-99999999/01"],
        "future_beat_ids": ["EV-8E4BBA17/02"],
        "viewpoint_valid": False,
        "viewpoint_evidence": prose,
        "causal_order_valid": False,
        "causal_order_evidence": prose,
        "summary": "完整回执明确否定各项语义结论。",
    }

    codes = {item["code"] for item in semantic_receipt_issues(contract, prose, receipt)}

    assert {
        "actor_action", "state_continuity", "scene_order",
        "entry_state", "exit_state", "outside_beat",
        "future_beat", "viewpoint", "causal_order",
    } <= codes


def test_semantic_receipt_missing_verdict_is_protocol_shape_failure() -> None:
    prose = "我看着沈老夫人派人出府。"
    contract = _contract(
        event_ids=("EV-8E4BBA17",), beat_ids=("EV-8E4BBA17/01",),
        execution_manifest_sha256="b" * 64, viewpoint="first-person",
    )
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "execution_manifest_sha256": contract.execution_manifest_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
    }

    assert {
        item["code"] for item in semantic_receipt_issues(contract, prose, receipt)
    } == {"receipt_shape"}


def test_semantic_receipt_aligns_unique_extracts_without_changing_verdicts() -> None:
    prose = (
        "我在前厅接过沈老夫人递来的旧账本，逐页核对朱砂印。"
        "确认印章与支出记录一致后，我当面请管事说明银两去向。"
    )
    contract = _contract(
        event_ids=("EV-00000001",), beat_ids=("EV-00000001/01",),
        execution_manifest_sha256="b" * 64, viewpoint="first-person",
    )
    joined = "我在前厅接过沈老夫人递来的旧账本……逐页核对朱砂印"
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "execution_manifest_sha256": contract.execution_manifest_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "beat_receipts": [{
            "beat_id": "EV-00000001/01", "evidence": joined,
            "actor_action_valid": True, "actor_action_evidence": joined,
            "state_valid": True, "state_evidence": "逐页核对朱砂印",
            "scene_order_valid": True, "scene_order_evidence": joined,
        }],
        "entry": {"satisfied": True, "evidence": joined},
        "exit": {
            "satisfied": True,
            "evidence": "确认印章与支出记录一致后……请管事说明银两去向",
        },
        "outside_beat_ids": [], "future_beat_ids": [],
        "viewpoint_valid": True, "viewpoint_evidence": joined,
        "causal_order_valid": True,
        "causal_order_evidence": (
            "逐页核对朱砂印……确认印章与支出记录一致后，我当面请管事说明银两去向"
        ),
        "summary": "",
    }

    aligned, repaired_paths = align_semantic_receipt_evidence(
        contract, prose, receipt,
    )

    assert receipt["summary"] == ""
    assert "summary" in repaired_paths
    assert repaired_paths
    assert validate_semantic_receipt(contract, prose, aligned)["beat_receipts"]


def test_semantic_receipt_does_not_align_ambiguous_or_weak_extracts() -> None:
    repeated = "这是一段会重复出现的关键证据"
    prose = f"{repeated}。中间发生别的事情。{repeated}。"
    contract = _contract(event_ids=("EV-00000001",))
    receipt = {
        "authority_sha256": contract.authority_sha256,
        "task_id": contract.task_id,
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "event_receipts": [{
            "event_id": "EV-00000001",
            "evidence": repeated + "……审核补充说明",
        }],
        "entry": {"satisfied": True, "evidence": repeated},
        "exit": {"satisfied": True, "evidence": repeated},
        "outside_event_ids": [], "causal_order_valid": True,
        "causal_order_evidence": repeated, "summary": "不能猜测绑定位置。",
    }

    aligned, repaired_paths = align_semantic_receipt_evidence(
        contract, prose, receipt,
    )

    assert repaired_paths == []
    assert any(
        item["code"] == "event_evidence"
        for item in semantic_receipt_issues(contract, prose, aligned)
    )


def test_whole_receipt_uses_the_same_unique_extract_alignment() -> None:
    segments = [
        "我在前厅接过沈老夫人递来的旧账本。",
        "确认印章与支出记录一致后，我请管事说明银两去向。",
    ]
    draft = "\n\n".join(segments)
    authority = "b" * 64
    event_ids = ["EV-00000001", "EV-00000002"]
    receipt = {
        "authority_sha256": authority,
        "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        "segment_sha256": [
            hashlib.sha256(item.encode("utf-8")).hexdigest() for item in segments
        ],
        "event_ids": event_ids,
        "missing_event_ids": [], "duplicate_event_ids": [],
        "out_of_order_event_ids": [], "causal_order_valid": True,
        "continuity_valid": True, "ending_valid": True,
        "commitments_valid": True,
        "evidence": [{
            "kind": "causal",
            "excerpt": "接过沈老夫人递来的旧账本……确认印章与支出记录一致后",
        }],
        "summary": "",
    }

    aligned, repaired_paths = align_whole_draft_receipt_evidence(
        authority, draft, segments, event_ids, receipt,
    )

    assert "summary" in repaired_paths
    assert validate_whole_draft_receipt(
        authority, draft, segments, event_ids, aligned,
    )["evidence"]


def test_whole_draft_receipt_requires_exact_segment_and_event_manifests() -> None:
    segments = ["花穗拿到账本。", "裴砚行确认印章，真相落定。"]
    draft = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n".join(segments)
    authority = "b" * 64
    receipt = {
        "authority_sha256": authority,
        "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        "segment_sha256": [
            hashlib.sha256(item.encode("utf-8")).hexdigest() for item in segments
        ],
        "event_ids": ["EV-00000001", "EV-00000002"],
        "missing_event_ids": [], "duplicate_event_ids": [], "out_of_order_event_ids": [],
        "causal_order_valid": True, "continuity_valid": True,
        "ending_valid": True, "commitments_valid": True,
        "evidence": [
            {"kind": "opening", "excerpt": "花穗拿到账本"},
            {"kind": "ending", "excerpt": "真相落定"},
        ],
        "summary": "账本线索按顺序推进并在结尾兑现。",
    }

    validate_whole_draft_receipt(
        authority, draft, segments, ["EV-00000001", "EV-00000002"], receipt,
    )

    with pytest.raises(ValueError, match="segment"):
        validate_whole_draft_receipt(
            authority, draft, segments, ["EV-00000001", "EV-00000002"],
            {**receipt, "segment_sha256": receipt["segment_sha256"][:1]},
        )
