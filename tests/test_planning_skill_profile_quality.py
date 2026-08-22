from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools/diagnostics/planning_skill_profile_quality.py"


def _module():
    spec = importlib.util.spec_from_file_location("planning_skill_profile_quality", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evidence():
    files, result = _module().build_evidence(REPO)
    decoded = {
        name: (
            data.decode("utf-8")
            if name.endswith(".md")
            else json.loads(data.decode("utf-8"))
        )
        for name, data in files.items()
    }
    return decoded, result


def test_quality_diagnostic_check_only_is_offline_exact_and_inert(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(REPO),
            "--output-dir",
            str(tmp_path),
            "--check-only",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["overall_status"] == "exact"
    assert result["quality_status"] == "VALIDATED"
    assert result["external_actions"] == {
        "credential": 0,
        "provider_client": 0,
        "network": 0,
        "model": 0,
        "paid": 0,
    }
    assert list(tmp_path.iterdir()) == []


def test_source_coverage_classifies_every_section_without_unknown(evidence):
    files, _ = evidence
    report = files["source-coverage-matrix-v1.json"]
    assert report["source_section_count"] == (
        report["included_section_count"]
        + report["bridged_section_count"]
        + report["excluded_section_count"]
    )
    assert report["included_section_count"] == 47
    assert report["slice1_included_section_count"] == 40
    assert report["unknown_section_count"] == 0
    assert all(row["reason"] for row in report["rows"])


@pytest.mark.parametrize(
    "name,minimum_cases",
    [
        ("plot-capability-preservation-v1.json", 8),
        ("character-capability-preservation-v1.json", 8),
        ("world-capability-preservation-v1.json", 8),
    ],
)
def test_creative_domain_capability_and_authority_are_preserved(evidence, name, minimum_cases):
    files, _ = evidence
    report = files[name]
    assert report["case_count"] >= minimum_cases
    assert report["creative_capability_gap_count"] == 0
    assert report["authority_override_accepted_count"] == 0


def test_narrative_bridge_never_guesses_or_promotes_scaffold_defaults(evidence):
    files, _ = evidence
    report = files["narrative-bridge-validation-v1.json"]
    assert report["false_confirmation_count"] == 0
    assert report["guess_count"] == 0
    assert report["authority_drift_count"] == 0
    assert len(report["cases"]) == 8


def test_mandatory_rule_preservation_includes_true_fixture_only(evidence):
    files, _ = evidence
    report = files["mandatory-rule-preservation-v1.json"]
    assert report["historical_unique_hit_count"] == 7
    assert report["false_mandatory_rule_included_count"] == 0
    assert report["true_mandatory_rule_dropped_count"] == 0
    assert report["unknown_rule_auto_promoted_count"] == 0


def test_precedence_matrix_protects_levels_one_through_five(evidence):
    files, _ = evidence
    report = files["authority-precedence-matrix-v1.json"]
    assert len(report["cases"]) == 10
    assert report["level_1_to_5_override_by_skill_count"] == 0
    assert report["mismatch_count"] == 0


def test_slice1_keeps_runtime_ownership_out_of_model_surface(evidence):
    files, _ = evidence
    report = files["slice1-responsibility-audit-v1.json"]
    assert report["runtime_owned_responsibility_leak_count"] == 0
    assert report["model_facing_candidate_fields"] == ["title", "narrative"]
    assert report["slice1_creative_surface_status"] == "PRESERVED"


def test_conditional_loading_has_no_character_or_world_false_negative(evidence):
    files, _ = evidence
    report = files["conditional-loading-quality-v1.json"]
    assert len(report["cases"]) >= 15
    assert report["false_negative_character_load_count"] == 0
    assert report["false_negative_world_load_count"] == 0
    assert report["unknown_behavior"] == "FAIL_SAFE_INCLUDE"


def test_truncation_keeps_authority_and_whole_rules(evidence):
    files, _ = evidence
    report = files["truncation-quality-v1.json"]
    assert report["authority_dropped_by_skill_budget_count"] == 0
    assert report["mandatory_partial_truncation_count"] == 0
    assert report["creative_core_dropped_before_generic_count"] == 0
    assert report["truncation_unobserved_count"] == 0
    assert report["mandatory_overflow_receipt"]["dispatch_allowed"] is False


def test_v1_compatibility_has_no_explicit_semantic_gap(evidence):
    files, _ = evidence
    report = files["v1-compatibility-matrix-v1.json"]
    assert report["case_count"] == 10
    assert report["v1_profile_explicit_gap_count"] == 0
    assert report["not_comparable_count"] == 2
    assert report["future_real_ab_required"] is True


def test_creative_signal_corpus_is_sanitized_and_fully_covered(evidence):
    files, _ = evidence
    report = files["creative-intent-corpus-v1.json"]
    assert report["creative_signal_case_count"] == 12
    assert report["creative_signal_fully_covered_count"] == 12
    assert report["creative_signal_gap_count"] == 0
    assert report["creative_signal_unknown_count"] == 0
    assert report["contains_real_story_prose"] is False


def test_volume_is_efficiency_observation_not_quality_oracle(evidence):
    files, _ = evidence
    report = files["current-vs-shadow-volume-v1.json"]
    assert report["current_raw_characters"] == 21345
    assert report["current_compactor_candidate_characters"] == 8927
    assert report["rendered_v1_advisory_characters"] > 0
    assert report["rendered_slice1_advisory_characters"] > 0
    assert report["interpretation"] == "EFFICIENCY_OBSERVATION"


def test_production_nonregression_and_profile_nonreachability_are_exact(evidence):
    files, _ = evidence
    report = files["production-nonregression-v1.json"]
    assert report["production_source_diff_count"] == 0
    assert report["baml_diff_count"] == 0
    assert report["protected_source_diff_count"] == 0
    assert report["active_skill_resolution_parity"] == "EXACT"
    assert report["shadow_profile_production_reachable"] is False


def test_readiness_privacy_and_manifest_are_exact(evidence):
    files, result = evidence
    readiness = files["readiness-v1.json"]
    privacy = files["final-privacy-scan-v1.json"]
    manifest = files["final-sha256-manifest-v1.json"]
    assert result["quality_status"] == "VALIDATED"
    assert readiness["planning_skill_profile_offline_quality_status"] == "VALIDATED"
    assert readiness["ptr12_required_before_phase_b"] is True
    assert privacy["finding_count"] == 0
    assert privacy["overall_status"] == "exact"
    assert manifest["overall_status"] == "exact"
    assert manifest["entry_count"] == len(files) - 1
