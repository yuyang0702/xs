import pytest

from novel_flywheel.quality import (
    normalize_review,
    quality_gate,
    reader_sample,
    select_route,
)


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
    text = "".join(str(index % 10) for index in range(30000))

    sample = reader_sample(text, "short", limit=9000)

    assert len(sample) <= 9000
    assert all(label in sample for label in ("OPENING", "PAID CUTOFF", "CLIMAX", "ENDING"))
    assert text[:100] in sample
    assert text[-100:] in sample


def test_reader_sample_labels_long_chapter_checkpoints() -> None:
    sample = reader_sample("x" * 12000, "long", limit=6000)

    assert len(sample) <= 6000
    assert all(label in sample for label in ("OPENING", "MIDDLE", "ENDING"))
