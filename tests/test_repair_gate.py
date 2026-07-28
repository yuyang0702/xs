import hashlib

from novel_flywheel.repair_gate import evaluate_candidate_gate
from novel_flywheel.revision import apply_patch_group


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_candidate_gate_reports_all_blockers_without_mutating_source() -> None:
    source = "父亲留下银锁。\n\n必须删除这句话。"
    candidate = source

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate),
            "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={
            "required_text": ["必须保留但不存在"],
            "forbidden_text": ["必须删除这句话"],
        },
        patch_results=[{"accepted": True}],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert result["passed"] is False
    assert "forbidden_text_remains" in {
        item["code"] for item in result["blocking"]
    }
    assert "required_text_missing" in {
        item["code"] for item in result["blocking"]
    }
    assert candidate == "父亲留下银锁。\n\n必须删除这句话。"


def test_candidate_gate_blocks_stale_source_and_analysis_hashes_together() -> None:
    result = evaluate_candidate_gate(
        source="原始正文。",
        candidate="候选正文。",
        source_hash=_hash("其他来源。"),
        analysis={
            "text_hash": _hash("其他候选。"),
            "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert [item["code"] for item in result["blocking"]] == [
        "source_hash_matches",
        "analysis_hash_matches",
        "plan_external_diff_absent",
    ]
    assert all(
        any("\u3400" <= character <= "\u9fff" for character in item["message"])
        for item in result["checks"]
    )
    assert result["review_mode_hint"] == "blocked"


def test_candidate_gate_accepts_empty_patch_evidence_only_when_text_is_unchanged() -> None:
    source = "没有需要修改的正文。"

    result = evaluate_candidate_gate(
        source=source,
        candidate=source,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(source), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    checks = {item["code"]: item for item in result["checks"]}
    assert checks["patch_groups_complete"]["passed"] is True
    assert checks["plan_external_diff_absent"]["passed"] is True


def test_candidate_gate_replays_real_patch_evidence_to_the_candidate() -> None:
    source = "父亲留下铜锁。"
    candidate = "父亲留下银锁。"
    patch_result = apply_patch_group(
        source,
        {"patches": [{
            "operation": "replace", "old_text": "铜锁", "new_text": "银锁",
        }]},
        _hash(source),
    )

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={"required_text": ["银锁"], "forbidden_text": ["铜锁"]},
        patch_results=[patch_result],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    checks = {item["code"]: item for item in result["checks"]}
    assert checks["patch_groups_complete"]["passed"] is True
    assert checks["plan_external_diff_absent"]["passed"] is True
    assert result["passed"] is True


def test_candidate_gate_rejects_accepted_boolean_without_patch_evidence() -> None:
    source = "正文没有变化。"

    result = evaluate_candidate_gate(
        source=source,
        candidate=source,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(source), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[{"accepted": True}],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert {item["code"] for item in result["blocking"]} == {
        "patch_groups_complete",
        "plan_external_diff_absent",
    }


def test_candidate_gate_blocks_diff_outside_replayed_patch_evidence() -> None:
    source = "父亲留下铜锁。"
    patched = "父亲留下银锁。"
    candidate = patched + "额外改动。"
    patch_result = apply_patch_group(
        source,
        {"patches": [{
            "operation": "replace", "old_text": "铜锁", "new_text": "银锁",
        }]},
        _hash(source),
    )

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[patch_result],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    checks = {item["code"]: item for item in result["checks"]}
    assert checks["patch_groups_complete"]["passed"] is True
    assert checks["plan_external_diff_absent"]["passed"] is False


def test_candidate_gate_rejects_patch_group_with_forged_diff_anchor() -> None:
    source = "父亲留下铜锁。"
    candidate = "父亲留下银锁。"
    forged = {
        "accepted": True,
        "text": candidate,
        "failures": [],
        "diffs": [{
            "patch": 1, "start": 0,
            "old_text": "不存在的锚点", "new_text": "银锁",
        }],
    }

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[forged],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert {
        item["code"] for item in result["blocking"]
        if item["code"].startswith("patch_")
        or item["code"] == "plan_external_diff_absent"
    } == {"patch_groups_complete", "plan_external_diff_absent"}


def test_candidate_gate_rejects_empty_patch_anchor_as_insufficient_evidence() -> None:
    source = "原始正文。"
    candidate = "伪造插入。" + source
    forged = {
        "accepted": True,
        "text": candidate,
        "failures": [],
        "diffs": [{
            "patch": 1, "start": 0, "old_text": "", "new_text": "伪造插入。",
        }],
    }

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[forged],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert {item["code"] for item in result["blocking"]} == {
        "patch_groups_complete", "plan_external_diff_absent",
    }


def test_candidate_gate_rejects_partial_group_even_with_replayable_diffs() -> None:
    source = "父亲留下铜锁。"
    candidate = "父亲留下银锁。"
    patch_result = apply_patch_group(
        source,
        {"patches": [{
            "operation": "replace", "old_text": "铜锁", "new_text": "银锁",
        }]},
        _hash(source),
    )
    partial = {**patch_result, "accepted": False}

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[partial],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    assert {item["code"] for item in result["blocking"]} == {
        "patch_groups_complete", "plan_external_diff_absent",
    }


def test_candidate_gate_blocks_removal_of_authoritative_locked_fact() -> None:
    source = "父亲留下银锁。"
    candidate = "父亲已经离开。"

    result = evaluate_candidate_gate(
        source=source,
        candidate=candidate,
        source_hash=_hash(source),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[],
        story_state={
            "locked_facts": [{"key": "keepsake", "value": "银锁"}],
            "issue_ledger": [{"issue_id": "runtime-only"}],
        },
        passage_locks=[],
        minimum_han=1,
        maximum_han=100,
    )

    check = next(
        item for item in result["checks"]
        if item["code"] == "locked_facts_preserved"
    )
    assert check["passed"] is False
    assert "keepsake" in check["message"]


def test_candidate_gate_blocks_conflicts_but_reports_allowed_passage_change() -> None:
    candidate = "Changed opening."
    locks = [
        {"key": "passage.missing", "value": {
            "id": "missing", "label": "ending", "mode": "exact",
            "excerpt": "Protected ending.", "normalized_excerpt": "protectedending",
            "paragraph_start": 2, "paragraph_end": 2, "active": True,
            "allow_next_change": False,
        }},
        {"key": "passage.allowed", "value": {
            "id": "allowed", "label": "opening", "mode": "exact",
            "excerpt": "Original opening.", "normalized_excerpt": "originalopening",
            "paragraph_start": 1, "paragraph_end": 1, "active": True,
            "allow_next_change": True,
        }},
    ]

    result = evaluate_candidate_gate(
        source=candidate,
        candidate=candidate,
        source_hash=_hash(candidate),
        analysis={
            "text_hash": _hash(candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[],
        story_state={"locked_facts": []},
        passage_locks=locks,
        minimum_han=0,
        maximum_han=100,
    )

    protection_checks = [
        item for item in result["checks"]
        if item["code"].startswith("passage_protection_")
    ]
    assert [(item["code"], item["passed"]) for item in protection_checks] == [
        ("passage_protection_missing", False),
        ("passage_protection_change_allowed", True),
    ]


def test_candidate_gate_uses_complete_analysis_and_effective_han_bounds() -> None:
    short_candidate = "# 标题不计入有效字数\n\n正"
    short_result = evaluate_candidate_gate(
        source=short_candidate,
        candidate=short_candidate,
        source_hash=_hash(short_candidate),
        analysis={
            "text_hash": _hash(short_candidate), "coverage": 0.5,
            "prose": {"blocking_count": 1},
        },
        contract={},
        patch_results=[],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=2,
        maximum_han=3,
    )
    long_candidate = "正文很多"
    long_result = evaluate_candidate_gate(
        source=long_candidate,
        candidate=long_candidate,
        source_hash=_hash(long_candidate),
        analysis={
            "text_hash": _hash(long_candidate), "coverage": 1.0,
            "prose": {"blocking_count": 0},
        },
        contract={},
        patch_results=[],
        story_state={"locked_facts": []},
        passage_locks=[],
        minimum_han=0,
        maximum_han=3,
    )

    assert {item["code"] for item in short_result["blocking"]} == {
        "analysis_coverage_complete",
        "local_prose_blockers_clear",
        "minimum_han_met",
    }
    assert [item["code"] for item in long_result["blocking"]] == [
        "maximum_han_not_exceeded",
    ]
