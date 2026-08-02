import hashlib
import re

import pytest

from novel_flywheel.draft_split import (
    DraftTaskContract,
    exact_event_partition,
    render_draft_task_prompt,
    residual_target,
    target_bounds,
    validate_semantic_receipt,
    validate_whole_draft_receipt,
)


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
