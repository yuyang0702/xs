from types import SimpleNamespace

from novel_flywheel.quality_profiles import (
    compare_quality_candidates,
    profile_for_project,
    quality_outcome_for_profile,
    score_review,
)


def test_zhihu_short_profile_aggregates_literal_criteria_into_40_40_20_score() -> None:
    review = {
        "criteria": {
            "opening_pull": 100,
            "sustained_motivation": 100,
            "escalation_density": 100,
            "climax_ending_payoff": 100,
            "platform_fit": 100,
            "causal_arc": 50,
            "character_agency": 50,
            "continuity_logic": 50,
            "promise_payoff": 50,
            "relationship_change": 50,
            "clarity": 0,
            "scene_dialogue": 0,
            "voice_emotion": 0,
            "rhythm": 0,
            "repetition_ai": 0,
        },
        "issues": [],
        "hard_fail": False,
        "decision": "pass",
    }

    scored = score_review(review, "zhihu-short-v2")

    assert scored["dimensions"] == {
        "commercial": 100.0,
        "story": 50.0,
        "prose": 0.0,
    }
    assert scored["score"] == 60.0
    assert scored["scoring_profile_id"] == "zhihu-short-v2"


def test_zhihu_short_profile_uses_parent_dimensions_for_legacy_model_output() -> None:
    scored = score_review({
        "dimensions": {"commercial": 90, "story": 80, "prose": 70},
        "issues": [], "hard_fail": False, "decision": "pass",
    }, "zhihu-short-v2")

    assert scored["score"] == 82.0
    assert scored["criteria_complete"] is False


def test_profile_for_project_only_enables_v2_for_zhihu_short() -> None:
    zhihu = SimpleNamespace(
        mode="short", metadata={"platform_profile_id": "zhihu-salt-short"},
    )
    ordinary = SimpleNamespace(mode="short", metadata={})
    long = SimpleNamespace(
        mode="long", metadata={"platform_profile_id": "zhihu-salt-short"},
    )

    assert profile_for_project(zhihu) == "zhihu-short-v2"
    assert profile_for_project(ordinary) == "legacy-v1"
    assert profile_for_project(long) == "legacy-v1"


def test_v2_outcome_separates_full_conditional_and_unresolved_major() -> None:
    passed = score_review({
        "dimensions": {"commercial": 88, "story": 82, "prose": 72},
        "issues": [], "hard_fail": False, "decision": "pass",
    }, "zhihu-short-v2")
    conditional = score_review({
        "dimensions": {"commercial": 79, "story": 75, "prose": 68},
        "issues": [], "hard_fail": False, "decision": "revise",
    }, "zhihu-short-v2")
    blocked = {
        **passed,
        "issues": [{
            "issue_id": "story-1", "severity": "major", "status": "unresolved",
            "evidence": "The causal gap remains.",
        }],
    }

    assert quality_outcome_for_profile(passed, "zhihu-short-v2") == ("passed", [])
    assert quality_outcome_for_profile(conditional, "zhihu-short-v2") == (
        "conditional_pass", [],
    )
    assert quality_outcome_for_profile(blocked, "zhihu-short-v2") == (
        "failed", ["unresolved_major_issue"],
    )


def test_candidate_needs_two_point_gain_without_dimension_regression() -> None:
    best = {
        "score": 80.0,
        "dimensions": {"commercial": 80, "story": 80, "prose": 80},
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "final-review/model-a",
        "issues": [],
    }
    too_close = {
        **best, "score": 81.9,
        "dimensions": {"commercial": 82, "story": 81, "prose": 80},
    }
    regression = {
        **best, "score": 83,
        "dimensions": {"commercial": 90, "story": 76, "prose": 80},
    }
    improved = {
        **best, "score": 82,
        "dimensions": {"commercial": 84, "story": 80, "prose": 80},
    }

    assert compare_quality_candidates(best, too_close)["promote"] is False
    assert "score_gain_below_2" in compare_quality_candidates(best, too_close)["reasons"]
    assert compare_quality_candidates(best, regression)["promote"] is False
    assert "dimension_regression:story" in compare_quality_candidates(best, regression)["reasons"]
    assert compare_quality_candidates(best, improved)["promote"] is True


def test_candidates_from_different_profiles_or_judges_are_not_comparable() -> None:
    best = {
        "score": 80,
        "dimensions": {"commercial": 80, "story": 80, "prose": 80},
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "model-a",
        "issues": [],
    }
    other_profile = {
        **best, "score": 90, "scoring_profile_id": "zhihu-short-v2",
    }
    other_judge = {
        **best, "score": 90, "judge_signature": "model-b",
    }

    assert compare_quality_candidates(best, other_profile) == {
        "promote": False,
        "comparable": False,
        "score_delta": 10.0,
        "dimension_deltas": {"commercial": 0.0, "story": 0.0, "prose": 0.0},
        "reasons": ["different_scoring_profile"],
    }
    assert compare_quality_candidates(best, other_judge)["reasons"] == [
        "different_judge",
    ]


def test_new_unresolved_major_issue_blocks_promotion() -> None:
    best = {
        "score": 80,
        "dimensions": {"commercial": 80, "story": 80, "prose": 80},
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "model-a",
        "issues": [],
    }
    candidate = {
        **best,
        "score": 84,
        "dimensions": {"commercial": 85, "story": 82, "prose": 80},
        "issues": [{
            "issue_id": "new-major", "severity": "high", "status": "unresolved",
        }],
    }

    result = compare_quality_candidates(best, candidate)

    assert result["promote"] is False
    assert "new_unresolved_major_issue" in result["reasons"]


def test_normalized_targeted_high_issue_still_blocks_v2_pass() -> None:
    review = score_review({
        "dimensions": {"commercial": 85, "story": 85, "prose": 80},
        "hard_fail": False, "decision": "revise",
        "issues": [{
            "issue_id": "story-high", "severity": "high",
            "severity_class": "targeted_revision", "status": "unresolved",
        }],
    }, "zhihu-short-v2")

    assert quality_outcome_for_profile(review, "zhihu-short-v2") == (
        "failed", ["unresolved_major_issue"],
    )
