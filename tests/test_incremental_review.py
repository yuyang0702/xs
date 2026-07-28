import hashlib

import pytest

import novel_flywheel.incremental_review as incremental_review
from novel_flywheel.incremental_review import (
    apply_incremental_gate,
    build_review_baseline,
    diff_manuscripts,
    requires_full_review,
    select_review_scope,
)
from novel_flywheel.manuscript_analysis import analyze_manuscript


def _analysis(text, entities=()):
    report = analyze_manuscript(text, nlp_analyze=None)
    report["nlp"]["available"] = True
    report["entities"] = [
        {"text": name, "window": window, "type": "Nh", "start": 0, "end": len(name)}
        for name, window in entities
    ]
    return report


def test_small_change_selects_changed_adjacent_and_shared_entity_windows():
    before = "\n\n".join([("林晚进入仓库。" + "甲" * 4800), ("周衡等待。" + "乙" * 4800),
                           ("林晚打开木盒。" + "丙" * 4800), ("次日离开。" + "丁" * 4800)])
    after = before.replace("进入仓库", "走进仓库", 1)
    old = _analysis(before, [("林晚", 1), ("林晚", 3)])
    new = _analysis(after, [("林晚", 1), ("林晚", 3)])
    baseline = build_review_baseline(before, old, [], {"issues": []})
    changes = diff_manuscripts(before, after, old, new)
    scope = select_review_scope(baseline, new, changes)
    assert {1, 2, 3}.issubset(scope["selected_windows"])
    assert "changed" in scope["reasons"]["1"]
    assert "shared_entity:林晚" in scope["reasons"]["3"]


def test_structural_or_degraded_changes_require_full_review():
    required, reasons = requires_full_review(
        {"selected_ratio": 0.2, "ambiguous": []},
        {"changed_ratio": 0.08, "event_order_changed": True},
        {"nlp": {"available": False}, "prose": {"blocking_count": 0}},
    )
    assert required
    assert "event_order_changed" in reasons
    assert "ltp_unavailable" in reasons


def test_incremental_gate_rejects_stale_hash_and_missing_reconciliation():
    text = "正文"
    analysis = _analysis(text)
    baseline = {
        "manuscript_hash": hashlib.sha256(text.encode()).hexdigest(),
        "issue_ledger": [{"issue_id": "initial-001"}],
        "coverage": 1.0,
    }
    review, reasons = apply_incremental_gate(
        {"hard_fail": False}, baseline,
        {"coverage": 1.0, "reviewed_windows": [1], "selected_windows": [1]},
        {**analysis, "text_hash": "stale"}, [],
    )
    assert review["hard_fail"] is True
    assert "stale_analysis" in reasons
    assert "missing_issue_reconciliation" in reasons


def test_incremental_gate_rejects_valid_but_stale_analysis_hash() -> None:
    current = "已经修改的正文"
    analysis = _analysis("旧正文")
    baseline = {"coverage": 1.0, "issue_ledger": []}

    review, reasons = apply_incremental_gate(
        {"hard_fail": False}, baseline, {"coverage": 1.0}, analysis,
        current_manuscript=current, reconciliations=[],
    )

    assert review["hard_fail"] is True
    assert "current_analysis_hash_mismatch" in reasons


def test_incremental_gate_rejects_empty_scope_for_changed_manuscript() -> None:
    before = "原正文"
    current = "修改后的正文"
    baseline = {
        "coverage": 1.0,
        "issue_ledger": [],
        "manuscript_hash": hashlib.sha256(before.encode("utf-8")).hexdigest(),
    }

    review, reasons = apply_incremental_gate(
        {"hard_fail": False}, baseline,
        {"coverage": 1.0, "selected_windows": [], "reasons": {}},
        _analysis(current), current_manuscript=current, reconciliations=[],
    )

    assert review["hard_fail"] is True
    assert "empty_incremental_scope" in reasons


def test_incremental_gate_rejects_selected_window_without_reason() -> None:
    current = "修改后的正文"

    review, reasons = apply_incremental_gate(
        {"hard_fail": False}, {"coverage": 1.0, "issue_ledger": []},
        {"coverage": 1.0, "selected_windows": [2], "reasons": {}},
        _analysis(current), current_manuscript=current, reconciliations=[],
    )

    assert review["hard_fail"] is True
    assert "unexplained_review_window" in reasons


def test_incremental_gate_rejects_invalid_and_unresolved_reconciliation_states():
    text = "正文"
    analysis = _analysis(text)
    baseline = {
        "manuscript_hash": hashlib.sha256(text.encode()).hexdigest(),
        "issue_ledger": [
            {"issue_id": "issue-a", "severity": "major"},
            {"issue_id": "issue-b", "severity": "medium"},
        ],
        "coverage": 1.0,
    }

    review, reasons = apply_incremental_gate(
        {"hard_fail": False, "decision": "pass"}, baseline,
        {"coverage": 1.0, "reviewed_windows": [1], "selected_windows": [1]},
        analysis, [
            {"issue_id": "issue-a", "status": "uncertain"},
            {"issue_id": "issue-b", "status": "maybe"},
        ],
    )

    assert review["hard_fail"] is True
    assert "invalid_issue_reconciliation" in reasons
    assert "unresolved_major_issue" in reasons


def test_changed_narrative_relation_selects_both_linked_windows():
    windows = [
        {"index": 1, "start": 0, "end": 100, "text": "a"},
        {"index": 2, "start": 100, "end": 200, "text": "b"},
        {"index": 3, "start": 200, "end": 300, "text": "c"},
    ]
    current = {
        "windows": windows, "entities": [], "events": [],
        "narrative_ledger": {"relations": [{
            "id": "relation-1", "from_start": 20, "to_start": 240, "to_end": 250,
        }]},
    }
    scope = select_review_scope(
        {"windows": windows}, current,
        {"changed_windows": [1], "changed_entities": [], "changed_events": [],
         "changed_narrative_relations": ["relation-1"]},
    )

    assert scope["selected_windows"] == [1, 2, 3]
    assert "narrative_relation:relation-1" in scope["reasons"]["3"]


def test_changed_relation_uses_impact_index_endpoints() -> None:
    windows = [
        {"index": index, "start": (index - 1) * 100, "end": index * 100,
         "text": str(index)}
        for index in range(1, 5)
    ]
    current = {
        "windows": windows, "entities": [], "events": [],
        "narrative_ledger": {"relations": []},
        "impact_index": {"relations": {"relation-1": [
            {"start": 20, "end": 30, "endpoint": "from"},
            {"start": 340, "end": 350, "endpoint": "to"},
        ]}},
    }

    scope = select_review_scope(
        {"windows": windows}, current,
        {"changed_windows": [1], "changed_entities": [], "changed_events": [],
         "changed_narrative_relations": ["relation-1"]},
    )

    assert 4 in scope["selected_windows"]
    assert "narrative_relation:relation-1" in scope["reasons"]["4"]


def test_review_baseline_records_the_exact_revision_source_hash():
    source = "受保护最佳稿"
    baseline = build_review_baseline(source, _analysis(source), [], {"issues": []})

    assert baseline["manuscript_hash"] == hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("flag", [
    "scene_inserted", "scene_deleted", "scene_moved", "scene_merged",
    "opening_promise_changed", "climax_changed", "ending_changed",
    "event_order_changed", "timeline_changed", "causal_relations_changed",
    "seven_step_structure_changed", "principal_goal_changed",
    "key_choice_changed", "life_death_changed", "identity_changed",
    "relationship_changed", "knowledge_state_changed", "key_evidence_changed",
    "setup_changed", "promise_changed", "question_changed", "payoff_changed",
    "locked_fact_changed", "world_rule_changed", "protected_passage_changed",
])
def test_semantic_structure_flags_force_full_review(flag: str) -> None:
    required, reasons = requires_full_review(
        {"selected_ratio": 0.1, "ambiguous": [], "selected_windows": [2]},
        {"changed_ratio": 0.01, flag: True},
        {"nlp": {"available": True}, "prose": {"blocking_count": 0}},
    )

    assert required is True
    assert flag in reasons


def test_unavailable_ltp_allows_only_mechanical_patch_groups() -> None:
    scope = {"selected_ratio": 0.1, "ambiguous": [], "selected_windows": [1]}
    changes = {"changed_ratio": 0.01}
    analysis = {"nlp": {"available": False}, "prose": {"blocking_count": 0}}

    semantic_required, semantic_reasons = requires_full_review(
        scope, changes, analysis, patch_groups=[{"mechanical": False}],
    )
    mechanical_required, mechanical_reasons = requires_full_review(
        scope, changes, analysis, patch_groups=[{"mechanical": True}],
    )

    assert semantic_required is True
    assert "ltp_unavailable" in semantic_reasons
    assert mechanical_required is False
    assert "ltp_unavailable" not in mechanical_reasons


def test_partially_applied_patch_group_forces_full_review() -> None:
    required, reasons = requires_full_review(
        {"selected_ratio": 0.1, "ambiguous": [], "selected_windows": [1]},
        {"changed_ratio": 0.01},
        {"nlp": {"available": True}, "prose": {"blocking_count": 0}},
        patch_groups=[{"mechanical": True, "partially_applied": True}],
    )

    assert required is True
    assert "partially_applied_groups" in reasons


def test_long_diff_never_runs_character_matcher_across_whole_manuscript(
    monkeypatch,
) -> None:
    paragraphs = [f"段落{index}。" + chr(0x4e00 + index) * 1200 for index in range(8)]
    before = "# 第一章\n\n" + "\n\n".join(paragraphs[:4])
    before += "\n\n# 第二章\n\n" + "\n\n".join(paragraphs[4:])
    after = before.replace("段落5。", "段落五。", 1)
    old = _analysis(before)
    current = _analysis(after)
    real_matcher = incremental_review.SequenceMatcher
    compared_sizes = []

    def recording_matcher(*args, **kwargs):
        left = args[1]
        right = args[2]
        compared_sizes.append((len(left), len(right)))
        return real_matcher(*args, **kwargs)

    monkeypatch.setattr(incremental_review, "SequenceMatcher", recording_matcher)

    changes = diff_manuscripts(before, after, old, current, mode="long")

    assert changes["ranges"]
    assert max(max(pair) for pair in compared_sizes) < len(before) // 2
