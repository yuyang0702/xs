from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from novel_flywheel.planning_adaptation import (
    apply_planning_repair_patch,
    normalize_planning_repair_patch,
)
from novel_flywheel.workflows import WorkflowService
from tools.diagnostics.r1_ptr0_planning_targeted_repair import build_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((
    ROOT
    / "tests/fixtures/reliability/r1_ptr0/"
    "planning-targeted-repair-characterization-v1.json"
).read_text(encoding="utf-8"))
EVIDENCE_ROOT = ROOT / "docs/superpowers/reports/sc-r1d3-final-1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def private_report() -> dict:
    canary_root = os.environ.get("NOVEL_R1_PTR0_PRIVATE_CANARY_ROOT")
    ledger_root = os.environ.get("NOVEL_R1_PTR0_PRIVATE_LEDGER_ROOT")
    if not canary_root or not ledger_root:
        pytest.skip("private sealed R1-PTR0 evidence is operator-supplied")
    return build_report(EVIDENCE_ROOT, Path(canary_root), Path(ledger_root))


def test_characterization_fixture_is_hash_only_and_private_safe() -> None:
    serialized = json.dumps(FIXTURE, ensure_ascii=False)
    assert FIXTURE["raw_content_included"] is False
    assert FIXTURE["prompt_content_included"] is False
    assert FIXTURE["tool_arguments_included"] is False
    assert FIXTURE["absolute_paths_included"] is False
    assert "AppData" not in serialized
    assert "api_key" not in serialized.casefold()


def test_parent_manifest_and_all_entries_are_exact() -> None:
    manifest = json.loads((
        EVIDENCE_ROOT / "sc-r1d3-final-1-sha256-manifest-v1.json"
    ).read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == FIXTURE["parent"]["manifest_sha256"]
    assert all(
        _sha256(EVIDENCE_ROOT / item["path"]) == item["sha256"]
        for item in manifest["entries"]
    )


def test_parent_evidence_and_consumed_cohort_are_exact(private_report) -> None:
    assert private_report["parent_gate"]["status"] == "exact"
    assert private_report["parent_gate"]["evidence_canonical_sha256"] == (
        FIXTURE["parent"]["evidence_sha256"]
    )
    assert private_report["parent_gate"]["checks"]["cohort_consumed"] is True


def test_all_ten_boundaries_match_sealed_characterization(private_report) -> None:
    actual = private_report["timeline"]
    assert len(actual) == len(FIXTURE["calls"]) == 10
    for observed, expected in zip(actual, FIXTURE["calls"], strict=True):
        for source, target in (
            ("ordinal", "ordinal"),
            ("substage", "substage"),
            ("role", "role"),
            ("route_kind", "route_kind"),
            ("execution_mode", "execution_mode"),
            ("effective_provider_output_budget", "budget"),
            ("observed_output_tokens", "output_tokens"),
            ("observed_visible_characters", "visible_characters"),
            ("finish_reason", "finish_reason"),
            ("response_sha256", "response_sha256"),
        ):
            assert observed[source] == expected[target]


def test_call_1_to_6_contains_no_masked_terminal_domain_failure(
    private_report,
) -> None:
    assert private_report["first_divergent_node"][
        "masked_earlier_domain_or_contract_failure_call_1_to_6"
    ] is False
    assert private_report["first_divergent_node"]["ordinal"] == 7


def test_call_7_exact_domain_failure_replay_is_blocked_by_missing_payload(
    private_report,
) -> None:
    closure = private_report["call_7_8_domain_closure"]
    assert closure["call_7_conversion"] == "exact_json_semantic_valid"
    assert closure["call_7_domain_finding_status"] == (
        "unverifiable_not_persisted"
    )
    assert "call_7_tool_arguments_or_normalized_payload" in closure[
        "missing_evidence"
    ]


def test_call_8_exact_domain_failure_replay_is_blocked_by_missing_payload(
    private_report,
) -> None:
    closure = private_report["call_7_8_domain_closure"]
    assert closure["call_8_conversion"] == "exact_json_semantic_valid"
    assert closure["call_8_domain_finding_status"] == (
        "unverifiable_not_persisted"
    )
    assert "call_8_tool_arguments_or_normalized_payload" in closure[
        "missing_evidence"
    ]


def test_call_7_to_8_precise_set_diff_remains_unknown_not_fabricated(
    private_report,
) -> None:
    diff = private_report["call_7_8_domain_closure"][
        "call_7_to_8_exact_set_diff"
    ]
    assert set(diff.values()) == {"unknown"}
    generic = private_report["call_7_8_domain_closure"][
        "call_7_to_8_generic_set_diff"
    ]
    assert generic == {
        "persisted_count": 2,
        "removed_count": 0,
        "introduced_count": 0,
        "transformed_count": 0,
    }


def test_domain_retry_received_no_call_7_specific_finding(private_report) -> None:
    closure = private_report["call_7_8_domain_closure"]
    assert closure["system_prompt_hash_equal"] is True
    assert closure["user_prompt_hash_equal"] is True
    assert closure["call_7_specific_domain_finding_passed_to_call_8"] is False
    assert private_report["finding_and_scope_classification"][
        "targeted_repair_finding_propagation"
    ] == "partial"


def test_authoritative_domain_wrapper_collapses_specific_reason_to_generic() -> None:
    spec = WorkflowService._structured_stage_spec(
        "planning_repair_patch",
        completion_check=lambda _value: False,
        runtime_authority={"patch_authority_sha256": "a" * 64},
    )
    with pytest.raises(
        ValueError,
        match="planning_repair_patch failed its authoritative domain contract",
    ):
        spec.domain_validator({
            "authority_sha256": "b" * 64,
            "segment": 1,
            "replacements": [{}],
            "summary": "x",
        })


def test_repair_scope_is_exact_field_anchor_patch_not_whole_object(
    private_report,
) -> None:
    classification = private_report["finding_and_scope_classification"]
    assert classification["targeted_repair_scope"] == "field"
    assert classification["whole_object_regeneration"] is False
    assert private_report["call_7_8_domain_closure"]["authorized_anchor_count"] == 2


def test_minimal_field_patch_counterfactual_applies_locally() -> None:
    authority = "a" * 64
    current = "before|unchanged"
    evidence = {"anchor": "before"}
    patch = normalize_planning_repair_patch(
        {
            "authority_sha256": authority,
            "segment": 1,
            "replacements": [{
                "evidence_id": "anchor",
                "replacement": "after",
            }],
            "summary": "",
        },
        authority_sha256=authority,
        segment=1,
        evidence_candidates=evidence,
        allowed_anchor_ids=["anchor"],
        current_segment=current,
    )
    assert apply_planning_repair_patch(current, patch, evidence) == (
        "after|unchanged"
    )


@pytest.mark.parametrize("ordinal,budget", [(9, 1977), (10, 3954)])
def test_call_9_10_truncation_shape_is_exact(
    private_report, ordinal: int, budget: int,
) -> None:
    call = private_report["timeline"][ordinal - 1]
    assert call["execution_mode"] == "plain"
    assert call["finish_reason"] == "max_tokens"
    assert call["observed_output_tokens"] == budget
    assert call["observed_visible_characters"] == 0
    assert call["parser_result"] == "not_reached_no_visible_artifact"
    assert call["schema_result"] == call["domain_validation_result"] == (
        "not_reached"
    )


def test_output_budget_expansion_reached_provider_boundary(private_report) -> None:
    output = private_report["call_9_10_output_limit"]
    assert output["output_budget_expansion_effective"] is True
    assert output["call_9_budget"] == 1977
    assert output["call_10_budget"] == 3954
    assert output["expansion_multiplier"] == 2
    assert output["expansion_absolute_delta"] == 1977
    assert output["call_10_hit_exact_requested_ceiling"] is True


def test_minimal_schema_and_domain_valid_sizes_are_far_below_budgets(
    private_report,
) -> None:
    size = private_report["minimal_size_counterfactual"]
    expected = FIXTURE["size_counterfactual"]
    assert size["minimal_schema_valid"]["estimated_tokens"] == expected[
        "minimal_schema_valid_tokens"
    ]
    assert size["minimal_domain_valid"]["estimated_tokens"] == expected[
        "minimal_domain_valid_tokens"
    ]
    assert size["current_required_compact_domain_valid"][
        "estimated_tokens"
    ] == expected["current_required_compact_domain_valid_tokens"]
    assert size["current_required_compact_domain_valid"][
        "estimated_tokens"
    ] < expected["call_9_budget"] / 20


def test_budget_only_4x_counterfactual_does_not_claim_domain_success(
    private_report,
) -> None:
    counterfactual = private_report["budget_counterfactual"]
    assert counterfactual["call_9_2x_observed_result"] == (
        "still_max_tokens_zero_visible_characters"
    )
    assert counterfactual["call_9_4x_length_only_status"] == (
        "possible_but_unproven"
    )
    assert counterfactual["domain_validity_at_4x"] == "unknown"


def test_fallback_stays_patch_scoped_but_loses_domain_findings(
    private_report,
) -> None:
    output = private_report["call_9_10_output_limit"]
    assert output["fallback_scope"] == "targeted_patch"
    assert output["fallback_finding_propagation"] == "partial"
    assert output["call_7_8_domain_findings_passed_to_fallback"] is False
    assert output["call_9_to_10_prompt_delta"] == (
        "generic_protocol_regeneration_system_only"
    )


def test_generic_vs_exact_finding_request_shapes_are_materially_different() -> None:
    generic = {"code": "domain_invalid", "action": "regenerate"}
    exact = {
        "code": "source_sha256_mismatch",
        "field_path": "replacements[0].source_sha256",
        "invariant": "equals_authorized_anchor_sha256",
        "repair_scope": "replacements[0]",
    }
    assert "field_path" not in generic and "invariant" not in generic
    assert {"field_path", "invariant", "repair_scope"}.issubset(exact)
    assert len(json.dumps(exact, sort_keys=True)) > len(
        json.dumps(generic, sort_keys=True)
    )


def test_provider_hidden_cap_is_not_inferred_without_evidence(private_report) -> None:
    output = private_report["call_9_10_output_limit"]
    assert output["provider_configured_output_cap"] is None
    assert output["provider_hidden_cap_evidence_status"] == (
        "unknown_above_3954_disproved_at_or_below_1977"
    )


def test_replay_performs_no_network_provider_model_or_paid_actions(
    monkeypatch, private_report,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in R1-PTR0")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert private_report["external_actions_during_replay"] == {
        "model_calls": 0,
        "provider_calls": 0,
        "network_calls": 0,
        "paid_calls": 0,
        "canary_runs": 0,
    }


def test_live_parity_remains_exact_in_parent_evidence() -> None:
    parity = json.loads((
        EVIDENCE_ROOT / "short-completion-r1d3-final-live-parity-v1.json"
    ).read_text(encoding="utf-8"))
    expected = FIXTURE["parent"]["live_parity_sha256"]
    assert parity["status"] == "exact"
    assert parity["before_sha256"] == parity["after_sha256"] == expected


def test_root_cause_gate_remains_not_closed_without_exact_payloads(
    private_report,
) -> None:
    assert private_report["root_cause_gate"] == FIXTURE["gate"]
    assert private_report["primary_root_cause"] == (
        "unresolved_exact_call_7_domain_rejection"
    )
    assert private_report["strongest_primary_contributor"] == (
        "planning.targeted_repair_finding_not_propagated"
    )
    assert private_report["terminal_amplifier"] == (
        "other:planning.fallback_plain_mode_zero_visible_output_limit"
    )
