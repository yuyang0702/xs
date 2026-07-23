import pytest

from novel_flywheel.revision import (
    check_revision_constraints,
    compact_review,
    normalize_revision_plan,
    segment_map,
)


def test_compact_review_keeps_every_issue_without_arbitrary_truncation() -> None:
    review = {
        "dimensions": {"commercial": 60, "story": 50, "prose": 70},
        "score": 58,
        "hard_fail": True,
        "decision": "rewrite",
        "issues": [
            {"category": f"issue-{index}", "severity": "high",
             "evidence": f"evidence-{index}", "action": f"action-{index}"}
            for index in range(20)
        ],
    }

    brief = compact_review(review)

    assert len(brief["issues"]) == 20
    assert brief["issues"][-1]["action"] == "action-19"


def test_segment_map_includes_both_ends_of_every_segment() -> None:
    mapped = segment_map(["A" * 100 + "middle" + "B" * 100, "second"], width=20)

    assert mapped[0] == {"segment": 1, "characters": 206,
                         "opening": "A" * 20, "ending": "B" * 20}
    assert mapped[1]["opening"] == "second"
    assert mapped[1]["ending"] == "second"


def test_normalize_revision_plan_rejects_unknown_segments_and_keeps_valid_tasks() -> None:
    plan = normalize_revision_plan({
        "global_facts": ["The ceremony is a wedding."],
        "checks": [
            {"kind": "forbidden_text", "value": "engagement banquet"},
            {"kind": "required_text", "value": "wedding"},
        ],
        "tasks": [
            {"segments": [1, 3, 99], "instruction": "Unify the ceremony."},
            {"segments": [], "instruction": "Ignore this."},
        ],
    }, segment_count=3)

    assert plan["tasks"] == [{"segments": [1, 3], "instruction": "Unify the ceremony."}]
    assert plan["target_segments"] == [1, 3]


def test_normalize_revision_plan_requires_at_least_one_actionable_task() -> None:
    with pytest.raises(ValueError, match="actionable task"):
        normalize_revision_plan({"tasks": []}, segment_count=3)


def test_revision_checks_report_required_and_forbidden_text() -> None:
    failures = check_revision_constraints("This is the wedding.", {
        "checks": [
            {"kind": "required_text", "value": "lawyer escrow"},
            {"kind": "forbidden_text", "value": "engagement banquet"},
            {"kind": "forbidden_text", "value": "wedding"},
        ],
    })

    assert failures == [
        "required text missing: lawyer escrow",
        "forbidden text remains: wedding",
    ]
