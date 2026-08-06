from __future__ import annotations

import json

import pytest

import novel_flywheel.planning_recovery as recovery_module

from novel_flywheel.planning_recovery import (
    merge_planning_issue_ledgers,
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


def test_candidate_attribution_keeps_latent_issue_on_unchanged_segment() -> None:
    previous = [issue(
        "planning_structural_drift", segment=2, event_id="EV-TWO",
        invalid_invariants=["viewpoint"],
    )]
    candidate = [issue(
        "planning_structural_drift", segment=3, event_id="EV-THREE",
        invalid_invariants=["causal_dependencies"],
    )]
    segment_event_ids = {
        1: ["EV-ONE"],
        2: ["EV-TWO"],
        3: ["EV-THREE"],
    }

    comparison = planning_candidate_comparison(
        previous, candidate,
        changed_segments={2},
        segment_event_ids=segment_event_ids,
    )
    merged = merge_planning_issue_ledgers(
        previous, candidate,
        changed_segments={2},
        segment_event_ids=segment_event_ids,
    )

    assert comparison["improved"] is True
    assert comparison["introduced_issue_keys"] == []
    assert comparison["resolved_issue_keys"] == [
        "planning:segment-02:EV-TWO:invariant:viewpoint",
    ]
    assert comparison["latent_baseline_issue_keys"] == [
        "planning:segment-03:EV-THREE:invariant:causal_dependencies",
    ]
    assert planning_issue_keys(merged) == planning_issue_keys(candidate)


def test_candidate_attribution_rejects_new_boundary_or_changed_scope_issue() -> None:
    previous = [issue(
        "planning_structural_drift", segment=2, event_id="EV-TWO",
        invalid_invariants=["viewpoint"],
    )]
    boundary = [{
        "code": "planning_whole_story_drift",
        "affected_segments": [2, 3],
        "affected_event_ids": ["EV-TWO", "EV-THREE"],
    }]
    segment_event_ids = {
        1: ["EV-ONE"],
        2: ["EV-TWO"],
        3: ["EV-THREE"],
    }

    comparison = planning_candidate_comparison(
        previous, boundary,
        changed_segments={2},
        segment_event_ids=segment_event_ids,
    )

    assert comparison["improved"] is False
    assert comparison["reason"] == "introduced_hard_issue"
    assert comparison["introduced_issue_keys"] == [
        "planning:whole:planning_whole_story_drift:segments-2,3:events-EV-THREE,EV-TWO",
    ]


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


def test_recovery_envelope_ignores_tampered_legacy_projection(tmp_path) -> None:
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
    assert read_planning_recovery(tmp_path) == (state, improved)

    envelope_path = tmp_path / "planning-recovery.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["pair_sha256"] = "0" * 64
    envelope_path.write_text(
        json.dumps(envelope, ensure_ascii=False), encoding="utf-8",
    )
    assert read_planning_recovery(tmp_path) is None

    persisted = json.loads(
        (tmp_path / "planning-recovery-state.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "running"


def test_recovery_envelope_survives_interruption_during_legacy_projection(
    tmp_path, monkeypatch,
) -> None:
    plan = "### 第 1 段：原子恢复规划"
    state = new_planning_recovery_state(
        outline_sha256="a" * 64,
        generation_context_sha256="b" * 64,
        segment_count=1,
        plan=plan,
        issues=[issue("planning_structural_drift")],
    )
    real_atomic_write = recovery_module.atomic_write
    calls = 0

    def interrupted_write(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("process exited before legacy projection")
        real_atomic_write(path, content)

    monkeypatch.setattr(recovery_module, "atomic_write", interrupted_write)
    with pytest.raises(OSError, match="legacy projection"):
        write_planning_recovery(tmp_path, state, plan)

    assert read_planning_recovery(tmp_path) == (state, plan)


def test_production_shaped_regressions_keep_four_issue_best_and_lossless_ledger() -> None:
    initial = [
        issue(
            "planning_structural_drift",
            segment=(index % 6) + 1,
            event_id=f"EV-{index:02d}",
            invalid_invariants=["event_function"],
            message=f"initial-{index}",
        ) for index in range(25)
    ]
    reduced = initial[:4]
    ten = reduced + [
        issue(
            "planning_structural_drift", segment=2,
            event_id=f"EV-NEW-{index:02d}",
            invalid_invariants=["promise_ending"],
            message=f"introduced-ten-{index}",
        ) for index in range(6)
    ]
    sixteen = reduced + [
        issue(
            "planning_structural_drift", segment=3,
            event_id=f"EV-REBUILD-{index:02d}",
            invalid_invariants=["knowledge_state"],
            message=f"introduced-sixteen-{index}",
        ) for index in range(12)
    ]
    state = new_planning_recovery_state(
        outline_sha256="a" * 64,
        generation_context_sha256="b" * 64,
        segment_count=6,
        plan="initial",
        issues=initial,
    )
    comparison = planning_candidate_comparison(initial, reduced)
    state = record_planning_candidate(
        state, plan="best-four", issues=reduced, comparison=comparison,
        source="targeted-1", accepted=True,
    )
    comparison = planning_candidate_comparison(reduced, ten)
    state = record_planning_candidate(
        state, plan="regressed-ten", issues=ten, comparison=comparison,
        source="targeted-2", accepted=False,
    )
    comparison = planning_candidate_comparison(reduced, sixteen)
    state = record_planning_candidate(
        state, plan="regressed-sixteen", issues=sixteen,
        comparison=comparison, source="rebuild-1", accepted=False,
    )

    assert len(state["best_issue_keys"]) == 4
    assert [item["accepted"] for item in state["candidates"]] == [
        True, False, False,
    ]
    assert len(state["candidates"][1]["issues"]) == 10
    assert len(state["candidates"][1]["introduced_issues"]) == 6
    assert len(state["candidates"][2]["issues"]) == 16
    assert len(state["candidates"][2]["introduced_issues"]) == 12
