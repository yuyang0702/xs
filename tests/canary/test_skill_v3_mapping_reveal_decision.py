from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.diagnostics import skill_v3_mapping_reveal_decision as reveal


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def documents() -> dict[str, bytes]:
    return reveal.build_artifacts(
        REPO,
        focused_tests="TEST_FIXTURE",
        related_tests="TEST_FIXTURE",
        full_suite="TEST_FIXTURE",
        strict_l3="PASS; warnings=0; blockers=0",
        new_owning_source_regression_count=0,
    )


def _json(documents: dict[str, bytes], name: str) -> dict:
    return json.loads(documents[name].decode("utf-8"))


def test_mapping_is_complete_one_to_one_and_parent_manifests_are_exact(documents: dict[str, bytes]) -> None:
    mapping = _json(documents, "anonymous-to-sample-mapping-v1.json")
    assert mapping["status"] == "EXACT"
    assert len(mapping["rows"]) == 6
    assert len({row["anonymous_sample_id"] for row in mapping["rows"]}) == 6
    assert len({row["prospective_sample_id"] for row in mapping["rows"]}) == 6
    assert {row["sample_slot"] for row in mapping["rows"]} == {"A1", "B1", "A2", "B2", "A3", "B3"}
    binding = _json(documents, "mapping-manifest-binding-v1.json")
    assert binding["manifest"]["status"] == "EXACT"
    assert binding["one_to_one_mapping"] is True


def test_blind_side_translation_is_pair_specific_and_not_arm_assumed(documents: dict[str, bytes]) -> None:
    binding = _json(documents, "blind-side-to-experiment-arm-v1.json")
    assert binding["global_blind_side_to_experiment_arm_mapping"] == "NOT_DEFINED_BY_DESIGN"
    rows = {row["anonymous_pair_id"]: row for row in binding["pairs"]}
    assert (rows["blind-pair-1"]["blind_side_a_experiment_arm"], rows["blind-pair-1"]["blind_side_b_experiment_arm"]) == ("B", "A")
    assert (rows["blind-pair-2"]["blind_side_a_experiment_arm"], rows["blind-pair-2"]["blind_side_b_experiment_arm"]) == ("A", "B")
    assert (rows["blind-pair-3"]["blind_side_a_experiment_arm"], rows["blind-pair-3"]["blind_side_b_experiment_arm"]) == ("B", "A")
    assert reveal.relation_to_experiment_result("B_BETTER", "B", "A") == "BASELINE_BETTER"
    assert reveal.relation_to_experiment_result("B_BETTER", "A", "B") == "SELECTIVE_VERBATIM_BETTER"


def test_frozen_blind_counts_and_freezes_are_immutable(documents: dict[str, bytes]) -> None:
    freeze = _json(documents, "blind-freeze-binding-v1.json")
    assert freeze["evaluator_1_freeze_sha256"] == reveal.EVALUATOR_1_FREEZE_SHA256
    assert freeze["evaluator_2_freeze_sha256"] == reveal.EVALUATOR_2_FREEZE_SHA256
    assert freeze["combined_literary_freeze_sha256"] == reveal.COMBINED_LITERARY_FREEZE_SHA256
    assert freeze["mapping_revealed_in_blind_evidence"] is False
    assert freeze["mapping_contamination"] == 0
    frozen = _json(documents, "frozen-blind-result-binding-v1.json")
    for row in frozen["rows"]:
        assert (
            row["blind_side_a_better"],
            row["blind_side_b_better"],
            row["tie_or_equivalent"],
        ) == reveal.EXPECTED_BLIND_COUNTS[row["dimension"]]
        assert row["blind_result"] == "BLIND_SIDE_B_BETTER"
    assert frozen["new_literary_scoring_performed"] is False


def test_mapped_dimension_results_apply_prospective_rule_without_scalar_average(documents: dict[str, bytes]) -> None:
    mapped = _json(documents, "mapped-literary-dimension-results-v1.json")
    results = {row["dimension"]: row for row in mapped["rows"]}
    for dimension in (
        "character_agency",
        "causal_coherence",
        "subtext_support",
        "specificity",
        "scene_pressure",
        "setup_payoff_integrity",
    ):
        assert results[dimension]["mapped_experiment_result"] == "BASELINE_BETTER"
    assert results["voice_readiness"]["mapped_experiment_result"] == "INCONCLUSIVE"
    assert results["anti_template_risk"]["mapped_experiment_result"] == "INCONCLUSIVE"
    assert results["voice_readiness"]["mapped_experiment_counts"] == {
        "SELECTIVE_VERBATIM_BETTER": 3,
        "BASELINE_BETTER": 3,
        "EQUIVALENT": 0,
        "INCONCLUSIVE": 0,
    }
    assert results["anti_template_risk"]["mapped_experiment_counts"] == {
        "SELECTIVE_VERBATIM_BETTER": 3,
        "BASELINE_BETTER": 2,
        "EQUIVALENT": 1,
        "INCONCLUSIVE": 0,
    }
    assert mapped["scalar_average_created"] is False


def test_narrative_non_inferiority_and_pilot_disposition_are_no_go_quality(documents: dict[str, bytes]) -> None:
    decision = _json(documents, "narrative-non-inferiority-v1.json")
    assert decision["narrative_non_inferior"] == "NO"
    assert decision["selective_critical_better_count"] == 0
    assert decision["selective_critical_equivalent_count"] == 0
    assert decision["selective_critical_regression_count"] == 3
    assert decision["selective_critical_inconclusive_count"] == 0
    assert decision["selective_noncritical_regression_count"] == 3
    assert decision["selective_noncritical_inconclusive_count"] == 2
    disposition = _json(documents, "pilot-disposition-v1.json")
    assert disposition["final_pilot_disposition"] == reveal.FINAL_DISPOSITION
    assert disposition["exact_next_gate"] == reveal.NEXT_GATE


def test_campaign_engineering_binding_and_non_inferiority_are_exact(documents: dict[str, bytes]) -> None:
    campaign = _json(documents, "campaign-engineering-binding-v1.json")
    assert campaign["total_samples"] == campaign["sealed_valid"] == campaign["total_real_provider_requests"] == 6
    assert campaign["sealed_invalid"] == 0
    assert campaign["per_sample_provider_attempts"] == 1
    for key in (
        "total_retry",
        "total_transport_retry",
        "total_fallback",
        "total_route_switch",
        "total_resume_dispatch",
        "total_second_dispatch",
        "alternate_destination_count",
        "cross_origin_redirect_count",
    ):
        assert campaign[key] == 0
    assert campaign["destination"] == "https://lingsuan.org:443/v1/messages"
    assert campaign["story_state_canon_ready_mutations"] == [0, 0, 0]
    engineering = _json(documents, "engineering-non-inferiority-v1.json")
    assert engineering["engineering_non_inferior"] == "YES"
    assert not any(engineering["regressions"].values())


def test_engineering_comparison_preserves_token_and_cost_observability_limits(documents: dict[str, bytes]) -> None:
    comparison = _json(documents, "engineering-comparison-v1.json")
    assert comparison["arms"]["A_BASELINE_CONTROL"]["sealed_valid"] == 3
    assert comparison["arms"]["B_SELECTIVE_VERBATIM"]["sealed_valid"] == 3
    assert comparison["b_minus_a_skill_context_chars"] == -369
    assert comparison["b_minus_a_skill_context_token_estimate"] == -93
    assert comparison["b_minus_a_headroom"] == 93
    assert comparison["token_comparison_sufficient"] == "NO"
    assert comparison["cost_comparison_sufficient"] == "NO"
    assert comparison["a1_output_tokens_observed"] == 649
    assert comparison["a1_finish_reason_observed"] == "end_turn"
    assert comparison["most_other_token_and_finish_fields_retained"] is False


def test_manifest_and_privacy_cover_every_generated_evidence_file(documents: dict[str, bytes]) -> None:
    privacy = _json(documents, "privacy-scan-v1.json")
    assert privacy["status"] == "PASS"
    assert privacy["total_matches"] == 0
    manifest = _json(documents, "sha256-manifest-v1.json")
    definition = manifest["definition"]
    covered = {entry["path"] for entry in definition["entries"]}
    assert covered == set(documents) - {"sha256-manifest-v1.json"}
    assert definition["entry_count"] == len(covered) == 21
    for entry in definition["entries"]:
        content = documents[entry["path"]]
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    canonical = (json.dumps(definition, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert manifest["definition_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_architectural_interpretation_is_bounded(documents: dict[str, bytes]) -> None:
    interpretation = _json(documents, "architectural-interpretation-v1.json")
    assert interpretation["selective_verbatim_met_character_heavy_narrative_non_inferiority"] is False
    assert interpretation["selective_verbatim_met_engineering_non_inferiority"] is True
    assert interpretation["one_character_heavy_multi_sample_pass_does_not_prove_generalized_skill_v3_non_inferiority"] is True
    assert interpretation["production_cutover_authorized"] is False
