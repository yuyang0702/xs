import hashlib

import pytest
from jsonschema import Draft202012Validator

from novel_flywheel.generated_artifacts import registered_business_wire_schema
from novel_flywheel.workflows import (
    validate_reader_review_business_complete_v1,
    validate_short_maintenance_business_complete_v2,
)


def _review() -> dict:
    return {
        "dimensions": {"commercial": 90, "story": 91, "prose": 92},
        "hard_fail": False,
        "decision": "pass",
        "issues": [],
    }


def test_full_short_final_review_rejects_legacy_score_only_shell() -> None:
    schema = registered_business_wire_schema("full_short_final_review", {})
    sparse = {"score": 92, "issues": []}

    errors = list(Draft202012Validator(schema).iter_errors(sparse))

    assert errors
    # The wire layer admits the two typed Full Short score topologies:
    # legacy dimensions and zhihu-v2 criteria/evidence. The typed verdict
    # validator then requires exactly one complete topology.
    assert set(schema["required"]) == {"issues"}
    assert "score" not in schema["properties"]
    assert {"dimensions", "criteria", "criterion_evidence"} <= set(
        schema["properties"]
    )
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("dimensions"),
        lambda value: value.pop("hard_fail"),
        lambda value: value.pop("decision"),
        lambda value: value["reader_signals"].pop("would_pay"),
        lambda value: value["reader_signals"].update({"would_continue": "yes"}),
    ],
)
def test_reader_review_rejects_structured_but_business_incomplete(
    mutation,
) -> None:
    payload = {
        **_review(),
        "reader_signals": {
            "would_continue": True,
            "would_pay": True,
            "abandonment_point": "none",
            "payoff_felt": True,
        },
    }
    mutation(payload)

    with pytest.raises(ValueError):
        validate_reader_review_business_complete_v1(payload)


def test_reader_review_complete_contract_normalizes_score() -> None:
    payload = {
        **_review(),
        "reader_signals": {
            "would_continue": True,
            "would_pay": True,
            "abandonment_point": "none",
            "payoff_felt": True,
        },
    }

    result = validate_reader_review_business_complete_v1(payload)

    assert result["decision"] == "pass"
    assert result["score"] > 0


@pytest.mark.parametrize(
    "payload",
    [
        {"facts": [], "state": {}},
        {
            "facts": [], "state": {},
            "coverage": {"manuscript_sha256": "0" * 64, "complete": False},
            "disposition": "no_change", "no_change_reason": "checked",
        },
        {
            "facts": [], "state": {},
            "coverage": {"manuscript_sha256": "1" * 64, "complete": True},
            "disposition": "changes", "no_change_reason": "not applicable",
        },
        {
            "facts": ["delta"], "state": {},
            "coverage": {"manuscript_sha256": "1" * 64, "complete": True},
            "disposition": "no_change", "no_change_reason": "checked",
        },
    ],
)
def test_maintenance_rejects_structured_but_business_incomplete(payload) -> None:
    with pytest.raises(ValueError):
        validate_short_maintenance_business_complete_v2(
            payload, expected_manuscript_sha256="1" * 64,
        )


def test_maintenance_accepts_explicit_complete_no_change_proof() -> None:
    manuscript = "complete authoritative manuscript"
    digest = hashlib.sha256(manuscript.encode()).hexdigest()
    payload = {
        "facts": [], "state": {},
        "coverage": {"manuscript_sha256": digest, "complete": True},
        "disposition": "no_change",
        "no_change_reason": "Full manuscript inspection found no durable delta.",
    }

    assert validate_short_maintenance_business_complete_v2(
        payload, expected_manuscript_sha256=digest,
    ) == payload


def test_maintenance_accepts_exact_typed_state_transition() -> None:
    digest = hashlib.sha256(b"manuscript").hexdigest()
    payload = {
        "facts": [],
        "state": {"hero": {"knowledge": {"published": True}}},
        "state_transitions": [{
            "character": "hero",
            "field": "knowledge.published",
            "from": False,
            "to": True,
            "evidence": "The hero publishes the ledger.",
        }],
        "coverage": {"manuscript_sha256": digest, "complete": True},
        "disposition": "changes",
        "no_change_reason": "not_applicable_changes_present",
    }

    assert validate_short_maintenance_business_complete_v2(
        payload, expected_manuscript_sha256=digest,
    ) == payload


def test_planning_contract_keeps_business_required_fields_model_visible() -> None:
    schema = registered_business_wire_schema("planning_semantic_v2", {})

    assert {"initial_state", "segments"} <= set(schema["required"])
