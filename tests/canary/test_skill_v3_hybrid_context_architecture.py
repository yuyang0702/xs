from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.diagnostics.design_skill_v3_hybrid_context_architecture import (
    DECISION,
    DEMANDS,
    NEXT_GATE,
    REQUIRED_FILES,
    build_artifacts,
    canonical_evidence_bytes,
    validate_artifacts,
    write_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]


def _read(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_hybrid_design_materializes_exact_required_evidence(tmp_path: Path) -> None:
    artifacts = build_artifacts(
        ROOT,
        focused="TEST",
        related="TEST",
        strict_l3="PASS; warnings=0; blockers=0",
    )
    assert set(artifacts) == set(REQUIRED_FILES)
    evidence = write_artifacts(tmp_path, artifacts)
    receipt = validate_artifacts(evidence)
    assert receipt["status"] == "PASS"
    assert receipt["file_count"] == 27
    assert receipt["manifest_entry_count"] == 26


def test_baseline_and_reference_are_protected_not_replaced(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    baseline = _read(evidence, "baseline-foundation-invariant-v1.json")
    reference = _read(evidence, "reference-guidance-preservation-v1.json")
    assert baseline["baseline_foundation_sha256"] == (
        "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc"
    )
    assert baseline["baseline_foundation_char_count"] == 2925
    assert baseline["baseline_foundation_token_estimate"] == 732
    assert baseline["baseline_foundation_not_replaced"] == "YES"
    assert baseline["baseline_foundation_not_truncated_to_make_room_for_supplement"] == "YES"
    assert reference["reference_guidance_not_displaced_by_hybrid_supplement"] == "YES"
    assert reference["raw_ref_model_visible"] == "NO"
    assert reference["no_new_shared_budget_confound"] == "YES"


def test_all_root_causes_and_demands_are_covered(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    matrix = _read(evidence, "root-cause-to-requirements-v1.json")
    replay = _read(evidence, "cross-demand-anti-overfit-replay-spec-v1.json")
    assert matrix["required_finding_count"] == 9
    assert matrix["covered_finding_count"] == 9
    assert matrix["coverage_status"] == "PASS"
    assert set(replay["demands"]) == set(DEMANDS)
    assert replay["no_pair_specific_rules"] is True
    assert replay["no_anonymous_sample_specific_rules"] is True
    assert replay["no_current_prose_memorization"] is True
    assert replay["unknown_demand"] == "FAIL_CLOSED_NO_TREATMENT_DISPATCH"


def test_selection_is_verbatim_deterministic_and_closure_is_all_or_nothing(
    tmp_path: Path,
) -> None:
    first = build_artifacts(ROOT)
    second = build_artifacts(ROOT)
    for name in (
        "supplement-demand-model-v1.json",
        "semantic-dependency-model-v1.json",
        "capacity-study-v1.json",
        "render-order-salience-v1.json",
    ):
        assert hashlib.sha256(first[name]).digest() == hashlib.sha256(second[name]).digest()
    evidence = write_artifacts(tmp_path, first)
    dependency = _read(evidence, "semantic-dependency-model-v1.json")
    granularity = _read(evidence, "section-packet-granularity-v1.json")
    capacity = _read(evidence, "capacity-study-v1.json")
    assert dependency["arbitrary_truncation_after_closure"] is False
    assert "render no supplement" in dependency["fail_closed_policy"]
    assert granularity["original_wording_preserved"] == "YES"
    assert granularity["no_creative_paraphrase"] == "YES"
    for row in capacity["rows"]:
        assert row["capacity_status"] == "PASS"
        assert row["truncation_occurred"] is False
        assert row["shedding_occurred"] is False
        assert row["headroom_to_local_precheck_limit"] > 16000


def test_low_actionability_cannot_dominate_or_satisfy_coverage(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    model = _read(evidence, "actionability-model-v1.json")
    capacity = _read(evidence, "capacity-study-v1.json")
    low = model["classes"]["LOW_ACTIONABILITY"]
    assert low["admission"] == "DEPENDENCY_ONLY; never a seed and never sole coverage"
    assert model["admission_policy"]["low_actionability"] == (
        "dependency-only; cannot count as feature coverage"
    )
    assert model["taxonomy_domination_allowed"] is False
    assert len(model["section_classifications"]) == 18
    for supplement in capacity["demand_supplements"].values():
        distribution = supplement["actionability_distribution"]
        assert distribution["LOW_ACTIONABILITY"] <= (
            distribution["HIGH_ACTIONABILITY"]
            + distribution["MEDIUM_ACTIONABILITY"]
        )
        assert supplement["low_actionability_dependency_only"] is True


def test_wrong_layer_scope_is_not_broadly_relaxed(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    granularity = _read(evidence, "section-packet-granularity-v1.json")
    index_v2 = granularity["index_v2_requirement"]
    assert "hash-bound" in index_v2["voice_section"]
    assert "remain excluded" in index_v2["mixed_operational_parents"]
    assert granularity["wrong_layer_authority_content_allowed"] == "NO"


def test_precedence_receipts_and_disabled_identity_are_complete(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    precedence = _read(evidence, "precedence-policy-v1.json")
    receipt = _read(evidence, "provenance-observability-schema-v1.json")
    implementation = _read(evidence, "implementation-plan-v1.json")
    decision = _read(evidence, "architecture-decision-v1.json")
    assert precedence["supplement_can_override_authority"] == "NO"
    assert precedence["supplement_can_override_explicit_task_contract"] == "NO"
    assert precedence["supplement_can_mutate_storystate"] == "NO"
    assert receipt["field_count"] == 21
    assert receipt["exact_bytes_reconstruction"]
    assert implementation["implementation_in_this_gate"] is False
    assert implementation["when_disabled"]["production_prompt_bytes_unchanged"] == "YES"
    assert implementation["when_disabled"]["production_model_input_identity"] == "YES"
    assert decision["hybrid_architecture_decision"] == DECISION
    assert decision["exact_next_gate"] == NEXT_GATE
    assert decision["real_campaign_justified_now"] == "NO"


def test_privacy_and_manifest_are_exact(tmp_path: Path) -> None:
    evidence = write_artifacts(tmp_path, build_artifacts(ROOT))
    privacy = _read(evidence, "privacy-scan-v1.json")
    manifest = _read(evidence, "sha256-manifest-v1.json")
    assert privacy["status"] == "PASS"
    assert privacy["total_matches"] == 0
    assert manifest["status"] == "EXACT"
    assert manifest["entry_hash_mode"] == "UTF8_CANONICAL_LF_V1"
    assert manifest["definition"]["entry_count"] == 26
    for entry in manifest["definition"]["entries"]:
        payload = canonical_evidence_bytes((evidence / entry["path"]).read_bytes())
        assert len(payload) == entry["bytes"]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
