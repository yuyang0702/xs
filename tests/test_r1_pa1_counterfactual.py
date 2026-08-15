from __future__ import annotations

import inspect
import json
from pathlib import Path

from novel_flywheel.context_policy import expanded_output_budget
from r1_pa1_counterfactual import simulate_retained_budget_counterfactual


FIXTURE = Path(__file__).parent / "fixtures" / "r1_pa1_budget_characterization_v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _invariants() -> dict:
    return {
        "prompt_system_sha256": "sealed_same_input",
        "prompt_user_sha256": "sealed_same_input",
        "contract_schema_version": "planning_adaptation_whole@1",
        "provider_binding_sha256": "sealed_same_input",
        "model_binding_sha256": "sealed_same_input",
        "route": "primary",
        "retry_fallback_policy": "unchanged",
        "attempt_count": 3,
        "expansion_policy": "context_policy.expanded_output_budget@1",
        "per_call_cap": "unchanged",
        "canary_cap": "not_present",
        "input_context": "unchanged",
        "stage_role": "review/review",
        "failure_trigger": "output_limit",
        "provider_calls_executed": 0,
    }


def test_counterfactual_retains_only_budget_across_outer_runtimes() -> None:
    source = _fixture()
    result = simulate_retained_budget_counterfactual(
        actual_request_sequence=source["actual_primary_request_sequence"],
        source_evidence_canonical_sha256=(
            source["source_evidence_canonical_sha256"]
        ),
        unchanged_invariants=_invariants(),
    )

    assert result.actual_request_sequence == (1276, 1276, 1276)
    assert result.retained_counterfactual_sequence == (
        1276,
        expanded_output_budget(1276),
        expanded_output_budget(expanded_output_budget(1276)),
    )
    assert result.first_divergence_attempt == 2
    assert result.changed_variable == (
        "retain_approved_expansion_across_outer_runtime_reconstruction"
    )
    assert result.whole_fallback_reachability == "unknown_counterfactual"
    assert result.invariant_before_sha256 == result.invariant_after_sha256
    assert set(result.unchanged_invariant_names) == set(_invariants())


def test_counterfactual_applies_existing_provider_or_context_cap() -> None:
    source = _fixture()
    result = simulate_retained_budget_counterfactual(
        actual_request_sequence=source["actual_primary_request_sequence"],
        source_evidence_canonical_sha256=(
            source["source_evidence_canonical_sha256"]
        ),
        declared_output_ceiling=2000,
        unchanged_invariants=_invariants(),
    )

    assert result.retained_counterfactual_sequence == (1276, 2000, 2000)
    assert result.target_before_cap_sequence == (
        None,
        expanded_output_budget(1276),
        expanded_output_budget(2000),
    )
    assert result.effective_after_cap_sequence == (1276, 2000, 2000)


def test_counterfactual_is_derived_and_contains_no_literal_growth_or_provider_path() -> None:
    source = inspect.getsource(simulate_retained_budget_counterfactual)

    assert "2552" not in source
    assert "5104" not in source
    assert "ModelGateway" not in source
    assert "provider" not in source.casefold()


def test_counterfactual_is_stable_for_same_semantic_inputs() -> None:
    fixture = _fixture()
    arguments = {
        "actual_request_sequence": fixture["actual_primary_request_sequence"],
        "source_evidence_canonical_sha256": (
            fixture["source_evidence_canonical_sha256"]
        ),
        "unchanged_invariants": _invariants(),
    }

    first = simulate_retained_budget_counterfactual(**arguments)
    second = simulate_retained_budget_counterfactual(**arguments)

    assert first == second
    assert first.result_sha256 == second.result_sha256
