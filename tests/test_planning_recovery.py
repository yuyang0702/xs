from __future__ import annotations

import json

from novel_flywheel.planning_recovery import (
    new_planning_recovery_state,
    planning_candidate_comparison,
    planning_issue_keys,
    planning_issue_segments,
    read_planning_recovery,
    record_planning_candidate,
    write_planning_recovery,
)


def issue(
    code: str, *, segment: int = 1, event_id: str = "EV-ONE",
    invalid_invariants: list[str] | None = None, message: str = "",
) -> dict:
    return {
        "code": code,
        "segment": segment,
        "event_id": event_id,
        "invalid_invariants": invalid_invariants or [],
        "message": message,
    }


def test_issue_identity_is_stable_when_reviewer_wording_changes() -> None:
    first = issue(
        "planning_structural_drift",
        invalid_invariants=["primary_actor_agency", "knowledge_state"],
        message="人物主动性和知情状态改变。",
    )
    second = issue(
        "planning_structural_drift",
        invalid_invariants=["knowledge_state", "primary_actor_agency"],
        message="换一种说法描述同一个问题。",
    )

    assert planning_issue_keys([first]) == planning_issue_keys([second])


def test_candidate_advances_only_on_strict_subset_without_new_issue() -> None:
    previous = [
        issue("planning_structural_drift", invalid_invariants=[name])
        for name in (
            "event_function", "primary_actor_agency", "causal_dependencies",
            "entry_state", "exit_state", "knowledge_state", "viewpoint",
        )
    ]
    reduced = [
        issue("planning_structural_drift", invalid_invariants=["viewpoint"]),
    ]
    regressed = reduced + [
        issue(
            "planning_structural_drift", segment=2, event_id="EV-TWO",
            invalid_invariants=["promise_ending"],
        ),
    ]

    comparison = planning_candidate_comparison(previous, reduced)
    assert comparison["improved"] is True
    assert len(comparison["resolved_issue_keys"]) == 6
    assert comparison["introduced_issue_keys"] == []

    rejected = planning_candidate_comparison(reduced, regressed)
    assert rejected["improved"] is False
    assert rejected["reason"] == "introduced_hard_issue"


def test_cross_segment_issue_repairs_every_owned_segment() -> None:
    segments = {
        1: ["EV-ONE"],
        2: ["EV-CROSS"],
        3: ["EV-CROSS"],
        4: ["EV-FOUR"],
    }
    issues = [{
        "code": "planning_whole_story_drift",
        "affected_segments": [1],
        "affected_event_ids": ["ev-cross"],
    }]

    assert planning_issue_segments(issues, segments) == {1, 2, 3}


def test_recovery_pair_rejects_tampered_best_plan(tmp_path) -> None:
    plan = "  ### 第 1 段：有效规划\n"
    state = new_planning_recovery_state(
        outline_sha256="a" * 64,
        generation_context_sha256="b" * 64,
        segment_count=1,
        plan=plan,
        issues=[issue("planning_structural_drift")],
    )
    improved = "### 第 1 段：更好的规划"
    comparison = planning_candidate_comparison(
        state["best_issues"], [],
    )
    state = record_planning_candidate(
        state, plan=improved, issues=[], comparison=comparison,
        source="targeted-1", accepted=True,
    )
    write_planning_recovery(tmp_path, state, improved)

    recovered = read_planning_recovery(tmp_path)
    assert recovered == (state, improved)

    (tmp_path / "planning-best.md").write_text(
        improved + "\n被篡改", encoding="utf-8",
    )
    assert read_planning_recovery(tmp_path) is None

    persisted = json.loads(
        (tmp_path / "planning-recovery-state.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "running"
