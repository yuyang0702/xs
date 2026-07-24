import pytest

from novel_flywheel.revision import (
    assess_polish_candidate,
    check_revision_constraints,
    compact_polish_findings,
    compact_review,
    normalize_revision_plan,
    normalize_chinese_prose,
    remove_consecutive_duplicate_blocks,
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

    assert mapped[0] == {"segment": 1, "scene_id": "scene-01", "characters": 206,
                         "opening": "A" * 20, "ending": "B" * 20}
    assert mapped[1]["scene_id"] == "scene-02"
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


def test_normalize_revision_plan_drops_mechanical_quote_checks() -> None:
    plan = normalize_revision_plan({
        "checks": [
            {"kind": "forbidden_text", "value": '"'},
            {"kind": "forbidden_text", "value": "forbidden event"},
        ],
        "tasks": [{"segments": [1], "instruction": "Repair the scene."}],
    }, segment_count=1)

    assert plan["checks"] == [{"kind": "forbidden_text", "value": "forbidden event"}]


def test_normalize_chinese_prose_repairs_safe_typography_only() -> None:
    text = (
        '他说："门我来修。"\n'
        "她 慢慢 点头！！！\n"
        "https://example.com/a  b\n"
        "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
    )

    normalized, repairs = normalize_chinese_prose(text)

    assert normalized == (
        "他说：“门我来修。”\n"
        "她慢慢点头！\n"
        "https://example.com/a  b\n"
        "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
    )
    assert repairs == ["ascii_dialogue_quotes", "cjk_spacing", "duplicate_punctuation"]


def test_polish_candidate_rejects_process_text_and_missing_locked_literal() -> None:
    rejected = assess_polish_candidate(
        "陈东推开门，叫了一声小雨。", "以下是润色版本：他推开门。",
        required_literals=["陈东", "小雨"],
    )

    assert rejected["accepted"] is False
    assert "production_text" in rejected["reasons"]
    assert "missing_literal:陈东" in rejected["reasons"]


def test_polish_candidate_accepts_local_improvement() -> None:
    accepted = assess_polish_candidate(
        "陈东轻轻地推开门。", "陈东推开门，门轴蹭过地面。",
        required_literals=["陈东"],
    )

    assert accepted["accepted"] is True
    assert accepted["reasons"] == []


def test_normalize_revision_plan_requires_at_least_one_actionable_task() -> None:
    with pytest.raises(ValueError, match="actionable task"):
        normalize_revision_plan({"tasks": []}, segment_count=3)


def test_structural_revision_plan_limits_targets_to_forty_percent() -> None:
    with pytest.raises(ValueError, match="40%"):
        normalize_revision_plan({
            "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
            "tasks": [{"segments": [1, 2, 3], "instruction": "Rewrite everything."}],
        }, segment_count=5, max_target_ratio=0.4, require_checks=True)


def test_structural_revision_plan_requires_deterministic_checks() -> None:
    with pytest.raises(ValueError, match="deterministic check"):
        normalize_revision_plan({
            "checks": [],
            "tasks": [{"segments": [2], "instruction": "Repair the contradiction."}],
        }, segment_count=5, max_target_ratio=0.4, require_checks=True)


def test_remove_consecutive_duplicate_blocks_keeps_single_copy() -> None:
    text = "Opening.\n\nClimax A.\n\nClimax B.\n\nClimax A.\n\nClimax B.\n\nEnding."

    cleaned, removals = remove_consecutive_duplicate_blocks(text)

    assert cleaned == "Opening.\n\nClimax A.\n\nClimax B.\n\nEnding."
    assert removals == 1


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


def test_polish_findings_prioritize_critical_issues_and_bound_evidence() -> None:
    findings = {
        "editorial": {
            "issues": [
                {"category": f"low-{index}", "severity": "low",
                 "evidence": "minor", "action": "Minor polish."}
                for index in range(12)
            ] + [{
                "category": "continuity", "severity": "critical",
                "evidence": "x" * 1000, "action": "Unify wedding timeline.",
            }],
        },
        "target_reader": {"reader_signals": {"would_pay": False}, "issues": []},
    }

    compacted = compact_polish_findings(findings, max_issues=8)

    assert compacted["issues"][0]["category"] == "continuity"
    assert len(compacted["issues"]) == 8
    assert len(compacted["issues"][0]["evidence"]) == 280
    assert compacted["reader_signals"] == {"would_pay": False}
