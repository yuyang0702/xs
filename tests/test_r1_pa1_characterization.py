from __future__ import annotations

import json
from pathlib import Path

from novel_flywheel.context_policy import expanded_output_budget


FIXTURES = Path(__file__).parent / "fixtures"
R1_PA0 = FIXTURES / "r1_pa0_planning_adaptation_receipt_evidence_v1.json"
SHAPES = FIXTURES / "r1_pa1_strict_tool_shape_cases_v1.json"
BUDGET = FIXTURES / "r1_pa1_budget_characterization_v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_r1_pa1_shape_matrix_contains_every_approved_characterization() -> None:
    fixture = _load(SHAPES)
    case_ids = {item["case_id"] for item in fixture["cases"]}

    assert case_ids == {
        "zero_tool_calls", "one_correct", "one_wrong",
        "multiple_one_correct", "multiple_correct", "multiple_wrong",
        "arguments_missing", "arguments_object", "arguments_string",
        "arguments_malformed_json", "arguments_array", "mixed_text_tool",
        "partial_tool_call", "finish_max_tokens", "finish_stop",
        "adapter_drops_tool", "adapter_duplicates_tool",
    }
    assert len(fixture["cases"]) == 17
    assert fixture["target"] == {
        "stage": "review",
        "boundary": "planning_adaptation_whole_receipt",
        "contract_id": "planning_adaptation_whole",
        "contract_version": 1,
        "role": "review",
        "route_kind": "configured_fallback",
        "strict_tool_route": True,
    }


def test_r1_pa1_budget_characterization_is_bound_to_sealed_r1_pa0_evidence() -> None:
    evidence = _load(R1_PA0)
    fixture = _load(BUDGET)
    whole_primary = [
        item["requested_output_tokens"]
        for item in evidence["calls"]
        if item["stage"] == "planning_adaptation_whole"
        and item["route"] == "primary"
    ]

    assert fixture["source_evidence_canonical_sha256"] == (
        evidence["evidence_canonical_sha256"]
    )
    assert whole_primary == fixture["actual_primary_request_sequence"]
    assert whole_primary == [1276, 1276, 1276]
    assert fixture["retained_expansion_state"] is False
    assert fixture["counterfactual_sequence_is_fixture_data"] is False


def test_counterfactual_growth_is_derived_from_the_real_policy() -> None:
    actual = _load(BUDGET)["actual_primary_request_sequence"]
    retained = [actual[0]]
    for _ in actual[1:]:
        retained.append(expanded_output_budget(retained[-1]))

    assert retained[0] == actual[0]
    assert retained[1] == expanded_output_budget(actual[0])
    assert retained != actual


def test_r1_pa0_segment_and_whole_oracles_remain_sealed() -> None:
    evidence = _load(R1_PA0)["planning_adaptation"]

    assert evidence["segment_conversion_method"] == "exact_json"
    assert evidence["segment_domain_status"] == "valid"
    assert evidence["segment_raw_sha256"] == (
        evidence["last_legal_checkpoint_output_sha256"]
    )
    assert evidence["whole_fallback_exception_type"] == "RuntimeError"
    assert evidence["whole_fallback_exact_error"] == (
        "strict structured tool route returned no unique artifact"
    )
    assert evidence["whole_fallback_raw_status"] == "not_persisted_unverifiable"
