from __future__ import annotations

import copy
import hashlib
import json

import pytest

from novel_flywheel.receipt_contracts import (
    FINAL_REVIEW_VERDICT_CONTRACT_VERSION,
    FinalReviewVerdictReceipt,
    validate_final_review_detail_receipt,
    validate_final_review_regional_receipt,
    validate_final_review_regional_runtime_envelope,
    validate_final_review_regional_semantic_body,
    validate_final_review_verdict_receipt,
    validate_final_review_window_receipt,
    validate_whole_story_obligation_catalog_v2,
)


ISSUE = {
    "category": "continuity",
    "severity": "high",
    "location": "chapter 2",
    "evidence": "The train arrives before it departs.",
    "effect": "The causal order is ambiguous.",
    "action": "Restore the established event order.",
}


def _whole_story_catalog() -> dict:
    payload = {
        "version": "whole-story-obligation-catalog-v2",
        "beat_ids": ["EV-00000001/01"],
        "source_event_ids": ["EV-00000001"],
        "execution_manifest_authority_sha256": "a" * 64,
        "execution_manifest_sha256": "b" * 64,
        "causal_chain_sha256": "c" * 64,
        "planning_ir_authority_sha256": "d" * 64,
        "planning_topology_sha256": "e" * 64,
        "beat_obligations": [{
            "obligation_id": "beat:EV-00000001/01",
            "kind": "atomic_beat_realization",
            "beat_id": "EV-00000001/01",
            "source_event_id": "EV-00000001",
            "action": "Return the sealed key.",
            "postconditions": ["The key is returned."],
            "knowledge_delta": ["The owner recognizes the key."],
            "relationship_delta": [],
        }],
        "event_obligations": [{
            "obligation_id": "event:EV-00000001",
            "kind": "planning_event_realization",
            "source_event_id": "EV-00000001",
            "beat_ids": ["EV-00000001/01"],
            "planning_bindings": [{
                "segment": 1,
                "planning_segment_sha256": "f" * 64,
                "handoff": "The key has reached its owner.",
            }],
        }],
        "global_obligations": {
            "core_goal": "Return the key.",
            "ending": "The key reaches its owner.",
        },
    }
    payload["catalog_sha256"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return payload


def _rehash_catalog(payload: dict) -> None:
    unsigned = {key: value for key, value in payload.items() if key != "catalog_sha256"}
    payload["catalog_sha256"] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def test_whole_story_obligation_catalog_is_one_strict_versioned_contract() -> None:
    catalog = _whole_story_catalog()
    assert validate_whole_story_obligation_catalog_v2(
        catalog, expected_beat_ids=["EV-00000001/01"],
        expected_manifest_sha256="b" * 64,
    )["catalog_sha256"] == catalog["catalog_sha256"]

    mutations = (
        lambda value: value["beat_obligations"][0].update(action=123),
        lambda value: value["beat_obligations"][0].update(postconditions=[{}]),
        lambda value: value["beat_obligations"][0].update(knowledge_delta=[42]),
        lambda value: value["event_obligations"][0]["planning_bindings"][0].update(
            handoff=123,
        ),
        lambda value: value["global_obligations"].update(ending=123),
    )
    for mutate in mutations:
        invalid = copy.deepcopy(catalog)
        mutate(invalid)
        _rehash_catalog(invalid)
        with pytest.raises(ValueError):
            validate_whole_story_obligation_catalog_v2(
                invalid, expected_beat_ids=["EV-00000001/01"],
                expected_manifest_sha256="b" * 64,
            )


def test_final_review_detail_accepts_documented_short_phrases_only() -> None:
    receipt = validate_final_review_detail_receipt({
        "events": ["The witness retracts the claim."],
        "promises": [{"promise": "The sealed letter remains unresolved."}],
        "character_states": ["The investigator now knows the route."],
        "timeline": ["The interview precedes the arrest."],
    })
    assert receipt["events"] == ["The witness retracts the claim."]
    with pytest.raises(ValueError, match="events.0"):
        validate_final_review_detail_receipt({
            "events": [42], "promises": [], "character_states": [],
            "timeline": [],
        })


def test_final_review_window_requires_typed_issue_collection() -> None:
    with pytest.raises(ValueError, match="issues"):
        validate_final_review_window_receipt({"summary": "complete"})
    with pytest.raises(ValueError, match="issues"):
        validate_final_review_window_receipt({
            "summary": "complete", "issues": "none",
        })
    with pytest.raises(ValueError, match="issues.0"):
        validate_final_review_window_receipt({
            "summary": "complete", "issues": ["not-an-object"],
        })


@pytest.mark.parametrize("control", ["issue_id", "status", "source"])
def test_descriptive_issue_rejects_model_owned_machine_control(control: str) -> None:
    with pytest.raises(ValueError, match=control):
        validate_final_review_window_receipt({
            "summary": "complete",
            "issues": [{**ISSUE, control: "model-value"}],
        })


def test_descriptive_issue_requires_actionable_facts() -> None:
    for field in ("category", "severity", "evidence", "action"):
        issue = dict(ISSUE)
        issue.pop(field)
        with pytest.raises(ValueError, match=field):
            validate_final_review_window_receipt({
                "summary": "complete", "issues": [issue],
            })


def test_final_review_window_adapts_structured_summary_unambiguously() -> None:
    receipt = validate_final_review_window_receipt({
        "summary": {"setting": "castle", "survivors": 7},
        "issues": [],
    })
    assert receipt["summary"] == '{"setting":"castle","survivors":7}'


def test_final_review_regional_rejects_unknown_machine_control() -> None:
    with pytest.raises(ValueError, match="skip_gate"):
        validate_final_review_regional_receipt({
            "summary": "complete", "issues": [], "covered_windows": [1],
            "source_sha256": "a" * 64, "source_issue_ids": [],
            "skip_gate": True,
        })


def test_regional_semantic_body_excludes_runtime_envelope() -> None:
    body = validate_final_review_regional_semantic_body({
        "summary": "The regional causal chain is coherent.", "issues": [ISSUE],
    })
    assert body["issues"] == [ISSUE]
    with pytest.raises(ValueError, match="covered_windows"):
        validate_final_review_regional_semantic_body({
            **body, "covered_windows": [1, 2],
        })

    envelope = validate_final_review_regional_runtime_envelope({
        "covered_windows": [1, 2], "source_sha256": "a" * 64,
        "source_issue_ids": ["runtime-issue-1"],
    })
    combined = validate_final_review_regional_receipt({**body, **envelope})
    assert combined["source_issue_ids"] == ["runtime-issue-1"]


def _verdict(**scores: object) -> dict:
    return {
        **scores,
        "hard_fail": False,
        "decision": "revise",
        "issues": [ISSUE],
        "reconciliations": [{
            "issue_id": "runtime-issue-1",
            "status": "unresolved",
            "severity": "high",
            "evidence": "The contradiction remains visible.",
        }],
    }


@pytest.mark.parametrize(
    "scores",
    [
        {"dimensions": {"commercial": 80, "story": 81, "prose": 82}},
        {"commercial": 80, "story": 81, "prose": 82},
        {"score": 81.5},
        {
            "criteria": {"opening_pull": 80, "causal_arc": 81},
            "criterion_evidence": {
                "opening_pull": {
                    "location": "opening", "excerpt": "A locked door opens.",
                    "effect": "It creates an immediate question.",
                },
                "causal_arc": {
                    "location": "ending", "excerpt": "The key is returned.",
                    "effect": "It completes the established causal chain.",
                },
            },
        },
    ],
)
def test_final_review_verdict_accepts_each_explicit_v1_topology(
    scores: dict,
) -> None:
    receipt = validate_final_review_verdict_receipt(_verdict(**scores))
    assert receipt["issues"] == [ISSUE]
    assert FinalReviewVerdictReceipt.contract_version == (
        FINAL_REVIEW_VERDICT_CONTRACT_VERSION
    )


def test_final_review_verdict_rejects_mixed_or_incomplete_score_topology() -> None:
    with pytest.raises(ValueError, match="score_topology"):
        validate_final_review_verdict_receipt(_verdict(
            dimensions={"commercial": 80, "story": 81, "prose": 82},
            score=81,
        ))
    with pytest.raises(ValueError, match="story"):
        validate_final_review_verdict_receipt(_verdict(
            commercial=80, prose=82,
        ))


def test_final_review_verdict_rejects_unknown_control_and_issue_identity() -> None:
    payload = _verdict(score=81)
    payload["skip_gate"] = True
    with pytest.raises(ValueError, match="skip_gate"):
        validate_final_review_verdict_receipt(payload)

    payload = _verdict(score=81)
    payload["issues"] = [{**ISSUE, "issue_id": "model-issued"}]
    with pytest.raises(ValueError, match="issue_id"):
        validate_final_review_verdict_receipt(payload)


def test_final_review_criteria_requires_exact_typed_evidence_keys() -> None:
    payload = _verdict(
        criteria={"opening_pull": 80},
        criterion_evidence={
            "causal_arc": {
                "location": "ending", "excerpt": "The key is returned.",
                "effect": "It completes the chain.",
            },
        },
    )
    with pytest.raises(ValueError, match="criterion_evidence"):
        validate_final_review_verdict_receipt(payload)


@pytest.mark.parametrize("invalid_score", [-1, 101, True, "80"])
def test_final_review_verdict_rejects_invalid_scores(invalid_score: object) -> None:
    with pytest.raises(ValueError, match="score"):
        validate_final_review_verdict_receipt(_verdict(score=invalid_score))
