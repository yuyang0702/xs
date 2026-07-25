import hashlib

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
