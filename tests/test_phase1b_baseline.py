from __future__ import annotations

import json
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "canonical"


def test_phase1b_baseline_is_bound_to_accepted_phase1a_head() -> None:
    baseline = json.loads(
        (FIXTURES / "phase1b-baseline-v1.json").read_text(encoding="utf-8")
    )
    assert baseline["schema"] == "Phase1BBaselineV1"
    assert baseline["baseline_head"] == (
        "7e692151e155299a480a6977fb7f307d513bdd43"
    )
    assert baseline["full_suite"] == {
        "passed": 2303,
        "skipped": 1,
        "strict_xfailed": 5,
        "failed": 0,
    }
    assert baseline["protected"]["model_call_delta"] == 0
    assert baseline["protected"]["prompt_delta"] == 0
    assert baseline["protected"]["strict_xfail_count"] == 5


def test_phase1b_replay_corpus_has_balanced_predecision_shapes() -> None:
    corpus = json.loads(
        (FIXTURES / "phase1b-replay-corpus-v1.json").read_text(encoding="utf-8")
    )
    samples = corpus["samples"]
    assert corpus["privacy"] == "sanitized-structural-fixture-no-real-prose"
    assert len(samples) == 24
    assert len({sample["id"] for sample in samples}) == len(samples)
    assert {sample["mode"] for sample in samples} == {"normal", "window"}
    by_family_mode = {
        (sample["family"], sample["mode"]) for sample in samples
    }
    assert all(
        (family, mode) in by_family_mode
        for family in {
            "location", "knowledge", "relationship", "evidence_gap",
            "evidence_ambiguous", "identity_ambiguous", "stale_expected",
            "legacy_only", "unsupported_reserved",
        }
        for mode in {"normal", "window"}
    )
    assert {sample["legacy"] for sample in samples} == {
        "accepted", "rejected",
    }
    assert all(sample["source"] and isinstance(sample["proposal"], dict)
               for sample in samples)
    assert any(
        fact.get("semantic_domain") == "future_normative"
        for sample in samples
        for fact in sample["proposal"].get("facts", [])
        if isinstance(fact, dict)
    )
    assert any(
        sample["state"].get("confirmed_facts")
        for sample in samples
    )
    assert any(
        sample["state"].get("character_states", {}).get(
            "Aster", {},
        ).get("location") == "North Gate"
        and sample["proposal"].get("facts")
        for sample in samples
    )
