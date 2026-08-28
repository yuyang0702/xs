from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.diagnostics import skill_v3_multi_sample_quality_root_cause as root_cause


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def documents() -> dict[str, bytes]:
    return root_cause.build_artifacts(
        REPO,
        focused_tests="TEST_FIXTURE",
        related_tests="TEST_FIXTURE",
        full_suite="TEST_FIXTURE",
        strict_l3="PASS; warnings=0; blockers=0",
        new_owning_source_regression_count=0,
    )


def _json(documents: dict[str, bytes], name: str) -> dict:
    return json.loads(documents[name].decode("utf-8"))


def test_methodology_remains_exact_and_causally_interpretable(documents: dict[str, bytes]) -> None:
    methodology = _json(documents, "methodology-validity-recheck-v1.json")
    assert methodology["status"] == "EXACT"
    assert methodology["total_real_samples"] == methodology["valid_real_samples"] == 6
    assert methodology["evaluators"] == 2
    assert methodology["batches"] == 3
    assert methodology["required_evaluator_by_batch_votes"] == 6
    assert methodology["observed_evaluator_by_batch_votes"] == 6
    assert methodology["mapping_contamination"] == 0
    assert methodology["blind_policy_drift"] == 0
    assert methodology["primary_changed_variable"] == "SKILL_CONTEXT"
    assert methodology["uncontrolled_variable_count"] == 0
    assert methodology["advisory_truncation"] == "NO"
    assert methodology["advisory_shedding"] == "NO"
    assert methodology["causally_interpretable"] is True
    assert len(methodology["parent_manifests"]) == 9
    assert all(item["status"] == "EXACT" for item in methodology["parent_manifests"])


def test_a_b_contexts_are_reconstructed_from_current_exact_source(documents: dict[str, bytes]) -> None:
    reconstruction = _json(documents, "exact-a-b-skill-context-reconstruction-v1.json")
    assert reconstruction["status"] == "EXACT"
    arm_a = reconstruction["arm_a"]
    arm_b = reconstruction["arm_b"]
    assert arm_a["a_rendered_skill_context_sha256"] == root_cause.EXPECTED_A_CONTEXT_SHA256
    assert arm_a["a_rendered_skill_context_char_count"] == 2925
    assert len(arm_a["a_hard_rule_extract"]) == 8
    assert len(arm_a["a_rendered_order"]) == 20
    assert arm_a["a_compaction_policy_version"] == "T5_COMPRESSED_PROFILE+T6_DEMAND_AWARE_V2"
    assert arm_a["a_advisory_truncation"] is False
    assert arm_a["a_advisory_shedding"] is False
    assert arm_b["b_rendered_skill_context_sha256"] == root_cause.EXPECTED_B_CONTEXT_SHA256
    assert arm_b["b_rendered_skill_context_char_count"] == 2556
    assert tuple(arm_b["b_selected_section_ids"]) == root_cause.EXPECTED_SELECTED_SECTION_IDS
    assert arm_b["b_dependency_closure"]["status"] == "PASS"
    assert arm_b["b_shared_core_exceptions"] == []


def test_selected_and_unselected_section_identities_are_complete(documents: dict[str, bytes]) -> None:
    audit = _json(documents, "unselected-candidate-section-audit-v1.json")
    assert audit["candidate_count"] == 104
    assert audit["eligible_count"] == 49
    assert audit["selected_count"] == 9
    assert audit["regression_relevant_unselected_section_count"] == 13
    assert tuple(audit["regression_relevant_unselected_section_ids"]) == root_cause.REGRESSION_RELEVANT_UNSELECTED_IDS
    assert audit["regression_relevant_ownership_filtered_section_count"] == 5
    assert tuple(audit["regression_relevant_ownership_filtered_section_ids"]) == root_cause.REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS
    rows = {row["candidate_section_id"]: row for row in audit["rows"]}
    assert all(rows[section_id]["eligible"] and not rows[section_id]["selected"] for section_id in root_cause.REGRESSION_RELEVANT_UNSELECTED_IDS)
    assert all(not rows[section_id]["eligible"] for section_id in root_cause.REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS)


def test_semantic_atom_and_dimension_delta_bind_actionability_not_count_only(documents: dict[str, bytes]) -> None:
    inventory = _json(documents, "semantic-atom-inventory-v1.json")
    assert inventory["atom_count"] == 36
    assert inventory["a_present_atom_count"] == 28
    assert inventory["b_present_atom_count"] == 9
    assert inventory["raw_atom_count_is_not_causal_proof"] is True
    rows = {row["atom_id"]: row for row in inventory["rows"]}
    assert rows["atom-opposed-tactics-costly-choice"]["present_in_a"] is True
    assert rows["atom-opposed-tactics-costly-choice"]["present_in_b"] is False
    assert rows["atom-social-relationship-taxonomy"]["actionability"] == "LOW"
    delta = _json(documents, "dimension-coverage-delta-v1.json")
    assert delta["atom_counts_are_not_used_alone_as_causal_proof"] is True
    by_dimension = {row["dimension"]: row for row in delta["rows"]}
    for dimension in root_cause.REGRESSION_DIMENSIONS:
        assert by_dimension[dimension]["a_only_high_actionability_atoms"]
        assert by_dimension[dimension]["dependency_atoms_missing_from_b"]


def test_dependency_graph_is_formally_closed_but_semantically_incomplete(documents: dict[str, bytes]) -> None:
    audit = _json(documents, "section-boundary-dependency-audit-v1.json")
    assert audit["formal_dependency_missing_count"] == 0
    assert audit["semantic_dependency_missing_count"] == 4
    assert audit["section_granularity_too_coarse_count"] == 2
    assert audit["section_granularity_too_fine_count"] == 1
    selector = _json(documents, "selector-recall-audit-v1.json")
    assert selector["status"] == "UNDER_RECALL_PROVEN"
    assert selector["selector_over_indexed_explicit_character_labels"] is True
    assert selector["selector_missed_cross_cutting_scene_causality_subtext_pressure_specificity_setup_payoff"] is True


def test_selector_replay_preserves_exact_character_heavy_result(documents: dict[str, bytes]) -> None:
    contexts = root_cause.reconstruct_contexts(REPO)
    replayed = contexts["compiler"].select(contexts["request"])
    assert tuple(item.section_id for item in replayed) == root_cause.EXPECTED_SELECTED_SECTION_IDS
    rendered = contexts["compiler"].render(replayed)
    assert rendered.sha256 == root_cause.EXPECTED_B_CONTEXT_SHA256
    assert rendered.chars == 2556


def test_baseline_reconstruction_has_broader_actionable_semantic_diversity(documents: dict[str, bytes]) -> None:
    forensic = _json(documents, "baseline-compactor-forensics-v1.json")
    assert forensic["baseline_compactor_semantic_recall_higher_than_selective_selector"] == "SUPPORTED"
    assert forensic["mechanism_truth"].startswith("A is T5/T6 deterministic rewritten")
    assert forensic["high_actionability_atoms_preserved"] > 20
    ordering = _json(documents, "context-ordering-salience-audit-v1.json")
    assert ordering["classifications"]["LOSS_OF_REINFORCEMENT"] == "SUPPORTED"
    assert ordering["causal_rank"] == "SECONDARY_NOT_PRIMARY"


def test_failure_matrix_and_variance_preserve_sealed_counts(documents: dict[str, bytes]) -> None:
    matrix = _json(documents, "mapped-literary-failure-matrix-v1.json")
    assert matrix["critical_counts"] == {"better":0,"equivalent":0,"regression":3,"inconclusive":0}
    assert matrix["noncritical_counts"] == {"better":0,"equivalent":0,"regression":3,"inconclusive":2}
    assert matrix["critical_regression_dimensions"] == ["character_agency", "causal_coherence", "setup_payoff_integrity"]
    assert matrix["noncritical_regression_dimensions"] == ["subtext_support", "specificity", "scene_pressure"]
    assert matrix["voice_readiness"] == "INCONCLUSIVE_SELECTIVE_3_BASELINE_3"
    assert matrix["anti_template_risk"] == "INCONCLUSIVE_SELECTIVE_3_BASELINE_2_TIE_1"
    variance = _json(documents, "variance-analysis-v1.json")
    assert variance["variance_is_primary_root_cause"] == "NO"
    assert variance["critical_regressions_erased_by_variance"] is False


def test_primary_root_and_architecture_disposition_are_bounded(documents: dict[str, bytes]) -> None:
    primary = _json(documents, "primary-root-cause-v1.json")
    assert primary["primary_root_cause"] == root_cause.PRIMARY_ROOT_CAUSE
    assert primary["confidence"] == "HIGH"
    architecture = _json(documents, "architecture-disposition-v1.json")
    assert architecture["selective_verbatim_architecture_disposition"] == root_cause.ARCHITECTURE_DISPOSITION
    assert architecture["is_3000_char_compressed_profile_restart_recommended"] == "NO"
    assert architecture["is_more_single_sample_prompt_hill_climbing_recommended"] == "NO"
    assert architecture["exact_next_gate"] == root_cause.NEXT_GATE
    next_experiment = _json(documents, "next-experiment-readiness-v1.json")
    assert next_experiment["new_real_campaign_justified_after_fix"] == "CONDITIONAL"
    assert next_experiment["approval_created"] is False
    assert next_experiment["nonce_created"] is False


def test_privacy_and_manifest_cover_exact_output_contract(documents: dict[str, bytes]) -> None:
    assert set(documents) == set(root_cause.OUTPUT_FILES)
    privacy = _json(documents, "privacy-scan-v1.json")
    assert privacy["status"] == "PASS"
    assert privacy["total_matches"] == 0
    manifest = _json(documents, "sha256-manifest-v1.json")
    definition = manifest["definition"]
    covered = {entry["path"] for entry in definition["entries"]}
    assert covered == set(documents) - {"sha256-manifest-v1.json"}
    assert definition["entry_count"] == 24
    for entry in definition["entries"]:
        content = documents[entry["path"]]
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    canonical = (json.dumps(definition, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert manifest["definition_sha256"] == hashlib.sha256(canonical).hexdigest()
