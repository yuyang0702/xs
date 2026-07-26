import pytest

from novel_flywheel.quality import (
    normalize_review,
    quality_gate,
    quality_outcome,
    reader_sample,
    review_windows,
    issue_ledger,
    apply_evidence_gate,
    select_route,
)


def test_issue_ledger_ids_are_stable_when_issue_order_changes() -> None:
    first = {"category": "story", "severity": "major", "evidence": "门没有锁。", "action": "补足开门条件"}
    second = {"category": "ending", "severity": "medium", "evidence": "承诺未兑现。", "action": "回应开篇问题"}

    original = issue_ledger([first, second])
    reordered = issue_ledger([second, first])

    assert original[0]["issue_id"] == reordered[1]["issue_id"]
    assert original[1]["issue_id"] == reordered[0]["issue_id"]
    assert original[0]["status"] == "open"
    assert original[0]["repair_goal"] == "补足开门条件"
    assert original[0]["source"] == "final_review"


def test_review_windows_cover_full_text_with_overlap() -> None:
    text = "\n\n".join(f"paragraph-{index}-" + "x" * 700 for index in range(18))

    windows = review_windows(text, target=5000, overlap=400)

    assert len(windows) >= 3
    assert windows[0]["start"] == 0
    assert windows[-1]["end"] == len(text)
    assert all(item["text"] == text[item["start"]:item["end"]] for item in windows)
    assert all(current["start"] < previous["end"]
               for previous, current in zip(windows, windows[1:]))


def test_evidence_gate_requires_prior_issue_reconciliation() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 92, "story": 92, "prose": 92},
        "decision": "pass", "issues": [],
    })

    gated, reasons = apply_evidence_gate(review, {
        "coverage": 1.0,
        "window_count": 4,
        "reviewed_windows": 4,
        "prior_issue_ids": ["initial-001"],
        "reconciliations": [],
        "evidence_count": 4,
    })

    assert gated["score"] <= 74
    assert gated["decision"] == "revise"
    assert "missing_issue_reconciliation" in reasons


def test_evidence_gate_caps_unresolved_major_issue() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 95, "story": 95, "prose": 95},
        "decision": "pass", "issues": [],
    })

    gated, reasons = apply_evidence_gate(review, {
        "coverage": 1.0, "window_count": 3, "reviewed_windows": 3,
        "prior_issue_ids": ["initial-001"], "evidence_count": 3,
        "reconciliations": [{
            "issue_id": "initial-001", "status": "unresolved",
            "severity": "major", "evidence": "The timeline still contradicts chapter one.",
        }],
    })

    assert gated["score"] <= 74
    assert "unresolved_major_issue" in reasons


def test_normalize_review_computes_weighted_score() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 90, "story": 80, "prose": 70},
        "hard_fail": False,
        "decision": "pass",
        "issues": [],
    })

    assert review["score"] == 82.5


def test_quality_gate_enforces_overall_dimensions_and_hard_fail() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 74, "story": 95, "prose": 95},
        "hard_fail": True,
        "issues": [],
    })

    passed, reasons = quality_gate(review)

    assert not passed
    assert reasons == ["commercial_below_75", "hard_fail"]


def test_quality_gate_accepts_near_threshold_explicit_pass() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 82, "story": 78, "prose": 75},
        "hard_fail": False,
        "decision": "pass",
        "issues": [],
    })

    passed, reasons = quality_gate(review)

    assert review["score"] == 79.2
    assert passed
    assert reasons == []


def test_quality_gate_accepts_near_threshold_minor_revision() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 86, "story": 71, "prose": 78},
        "hard_fail": False,
        "decision": "revise",
        "issues": [{"severity": "medium", "action": "tighten one scene"}],
    })

    passed, reasons = quality_gate(review)

    assert review["score"] == 79.15
    assert passed
    assert reasons == []


def test_quality_outcome_distinguishes_full_and_conditional_pass() -> None:
    full = normalize_review({
        "dimensions": {"commercial": 90, "story": 80, "prose": 70},
        "hard_fail": False, "decision": "pass", "issues": [],
    })
    conditional = normalize_review({
        "dimensions": {"commercial": 75, "story": 75, "prose": 75},
        "hard_fail": False, "decision": "revise",
        "issues": [{"severity": "medium", "action": "tighten one paragraph"}],
    })

    assert quality_outcome(full) == ("passed", [])
    assert quality_outcome(conditional) == ("conditional_pass", [])


def test_quality_outcome_rejects_score_below_75() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 75, "story": 75, "prose": 70},
        "hard_fail": False, "decision": "revise", "issues": [],
    })

    outcome, reasons = quality_outcome(review)

    assert review["score"] == 74.0
    assert outcome == "failed"
    assert reasons == ["overall_below_75"]


@pytest.mark.parametrize("blocker", ["critical", "rewrite", "hard_fail"])
def test_quality_outcome_keeps_safety_blockers(blocker) -> None:
    review = normalize_review({
        "dimensions": {"commercial": 78, "story": 75, "prose": 75},
        "hard_fail": blocker == "hard_fail",
        "decision": "rewrite" if blocker == "rewrite" else "revise",
        "issues": ([{"severity": "critical", "action": "repair unsafe event"}]
                   if blocker == "critical" else []),
    })

    outcome, reasons = quality_outcome(review)

    assert outcome == "failed"
    assert blocker in reasons


def test_style_critical_is_downgraded_to_targeted_revision() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 80, "story": 78, "prose": 76},
        "hard_fail": True,
        "decision": "revise",
        "issues": [{"category": "prose", "severity": "critical", "action": "删除主题总结"}],
    })

    outcome, reasons = quality_outcome(review)

    assert review["hard_fail"] is False
    assert review["issues"][0]["severity_class"] == "targeted_revision"
    assert outcome == "conditional_pass"
    assert reasons == []


def test_manuscript_corruption_remains_blocking() -> None:
    review = normalize_review({
        "dimensions": {"commercial": 85, "story": 80, "prose": 80},
        "hard_fail": False,
        "decision": "revise",
        "issues": [{"category": "production_text", "severity": "critical", "action": "删除编辑说明"}],
    })

    outcome, reasons = quality_outcome(review)

    assert review["hard_fail"] is True
    assert review["issues"][0]["severity_class"] == "blocking"
    assert outcome == "failed"
    assert "hard_fail" in reasons


def test_normalize_review_accepts_legacy_score() -> None:
    review = normalize_review({"score": 86, "hard_fail": False, "issues": ["tighten prose"]})

    assert review["dimensions"] == {"commercial": 86.0, "story": 86.0, "prose": 86.0}
    assert review["issues"] == [{
        "category": "general", "severity": "medium",
        "evidence": "", "action": "tighten prose",
    }]


def test_normalize_review_accepts_flat_dimension_fields() -> None:
    review = normalize_review({
        "commercial": 76, "story": 61, "prose": 70,
        "hard_fail": True, "decision": "rewrite", "issues": [],
    })

    assert review["dimensions"] == {"commercial": 76.0, "story": 61.0, "prose": 70.0}
    assert review["score"] == 69.55


@pytest.mark.parametrize("score", [-1, 101, "high"])
def test_normalize_review_rejects_invalid_dimension(score) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        normalize_review({
            "dimensions": {"commercial": score, "story": 80, "prose": 80},
            "issues": [],
        })


def test_normalize_review_rejects_invalid_issue_shape() -> None:
    with pytest.raises(ValueError, match="issue"):
        normalize_review({
            "score": 80,
            "issues": [{"category": "commercial", "action": ["not", "text"]}],
        })


def test_route_selects_enhanced_only_for_risky_or_key_content() -> None:
    assert select_route("short", None, "", False)["reasons"] == ["short_story"]
    assert select_route("long", 2, "ordinary", False)["reasons"] == ["opening_chapter"]
    assert select_route("long", 8, "进入付费点", False)["reasons"] == ["key_goal"]
    assert select_route("long", 8, "ordinary", True)["reasons"] == ["volume_end"]

    ordinary = select_route("long", 8, "ordinary", False)
    assert ordinary == {
        "enhanced": False, "max_corrections": 1, "reasons": ["ordinary_chapter"],
    }

    severe = normalize_review({
        "dimensions": {"commercial": 55, "story": 80, "prose": 80}, "issues": [],
    })
    escalated = select_route("long", 8, "ordinary", False, severe)
    assert escalated["enhanced"]
    assert escalated["max_corrections"] == 2
    assert escalated["reasons"] == ["severe_first_review"]


def test_reader_sample_is_bounded_and_labels_short_checkpoints() -> None:
    marker = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"
    text = marker.join("".join(str(index % 10) for index in range(7500)) for _ in range(4))

    sample = reader_sample(text, "short", limit=9000)

    assert len(sample) <= 9000
    assert all(label in sample for label in ("OPENING", "PAID REGION", "CLIMAX", "ENDING"))
    assert text[:100] in sample
    assert text[-100:] in sample
    assert "NOVEL_FLYWHEEL_SEGMENT" not in sample
    assert "boundaries are not manuscript or paywall boundaries" in sample


def test_reader_sample_aligns_excerpt_edges_to_paragraphs() -> None:
    text = "\n\n".join(f"第{index}段开头。" + "内容" * 300 + "本段结束。" for index in range(30))

    sample = reader_sample(text, "short", limit=6000)

    excerpts = sample.split("--- ")[1:]
    for excerpt in excerpts:
        body = excerpt.split(" ---\n", 1)[1].strip()
        assert body.startswith("第")
        assert body.endswith("本段结束。")


def test_reader_sample_labels_long_chapter_checkpoints() -> None:
    sample = reader_sample("x" * 12000, "long", limit=6000)

    assert len(sample) <= 6000
    assert all(label in sample for label in ("OPENING", "MIDDLE", "ENDING"))
