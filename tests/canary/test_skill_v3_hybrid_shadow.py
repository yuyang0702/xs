from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from novel_flywheel.hybrid_skill_context import (
    HybridDependencyEdgeV1,
    HybridSkillContextCompilerV1,
    HybridSkillContextShadowObserverV1,
    HybridSkillSectionIndexV2,
)
from tools.diagnostics.materialize_skill_v3_hybrid_shadow_evidence import (
    NEXT_GATE,
    OUTPUT,
    REQUIRED_FILES,
    _canonical_sha,
    _json_bytes,
    _replace_index,
    build_artifacts,
    request_for,
    validate_artifacts,
    write_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]
INDEX_V1 = ROOT / "vendor/novel-skills/skill-section-index-v1.json"
INDEX_V2 = ROOT / "vendor/novel-skills/skill-section-index-v2.json"


def _index() -> HybridSkillSectionIndexV2:
    return HybridSkillSectionIndexV2.load(INDEX_V2, INDEX_V1, ROOT)


def _artifacts() -> dict[str, bytes]:
    return build_artifacts(
        ROOT,
        implementation_commits=("9361b47", "coverage-pending"),
        focused="offline focused pass",
        related="offline related pass",
        full_suite="historical non-green classified",
        strict_l3="PASS warnings=0 blockers=0",
        new_regression_count=0,
    )


def test_evidence_materializer_covers_exact_required_root_and_readiness() -> None:
    artifacts = _artifacts()
    assert set(artifacts) == set(REQUIRED_FILES)
    readiness = json.loads(artifacts["offline-readiness-v1.json"])
    assert readiness["SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_IMPLEMENTED"] == "YES"
    assert readiness["SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_OFFLINE_VALIDATED"] == "YES"
    assert readiness["BASELINE_FOUNDATION_PRESERVED"] == "YES"
    assert readiness["REFERENCE_GUIDANCE_PRESERVED"] == "YES"
    assert readiness["PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED"] == "YES"
    assert readiness["EXACT_NEXT_GATE"] == NEXT_GATE


def test_five_demand_replay_is_capacity_safe_and_not_sample_specific() -> None:
    replay = json.loads(_artifacts()["cross-demand-replay-v1.json"])
    assert len(replay["rows"]) == 5
    assert all(row["SHADOW_RESULT"] == "PASS" for row in replay["rows"])
    assert all(row["CAPACITY"] == "PASS" for row in replay["rows"])
    assert all(row["WRONG_LAYER_COUNT"] == 0 for row in replay["rows"])
    assert all(row["VERBATIM_MISMATCH"] == 0 for row in replay["rows"])
    assert replay["NO_PAIR_SPECIFIC_RULES"] == "YES"
    assert replay["NO_ANONYMOUS_SAMPLE_SPECIFIC_RULES"] == "YES"
    assert replay["NO_BLIND_PROSE_MEMORIZATION"] == "YES"
    assert replay["NO_RUBRIC_HACKS"] == "YES"


def test_character_forensic_and_semantic_atom_replay_close_mechanism_only() -> None:
    artifacts = _artifacts()
    forensic = json.loads(artifacts["character-heavy-forensic-replay-v1.json"])
    atoms = json.loads(artifacts["semantic-atom-coverage-replay-v1.json"])
    assert forensic["CHARACTER_HEAVY_FORENSIC_REPLAY_PASS"] == "YES"
    assert forensic["diagnosed_selective_replacement_mechanism_removed"] is True
    assert forensic["literary_pass_claimed"] is False
    assert atoms["MISSING_REGRESSION_RELEVANT_BASELINE_ATOM_COUNT"] == 0
    assert set(atoms["REGRESSION_RELEVANT_BASELINE_ATOMS"]) <= set(
        atoms["HYBRID_BASELINE_RETAINED_ATOMS"]
    )


def test_negative_injections_are_bounded_hash_only_and_external_zero() -> None:
    failures = json.loads(_artifacts()["shadow-failure-observability-v1.json"])
    names = {row["case"] for row in failures["rows"]}
    assert names == {
        "malformed_skill_section_identity", "missing_dependency_target",
        "dependency_cycle", "ownership_violation", "verbatim_mismatch",
        "baseline_identity_mismatch", "reference_guidance_identity_mismatch",
        "capacity_overflow", "unresolved_contradiction",
        "receipt_serialization_failure", "unexpected_compiler_exception",
    }
    assert failures["FAILURE_OBSERVABILITY_PASS"] == "YES"
    assert all(row["production_model_input_unchanged"] == "YES" for row in failures["rows"])
    assert all(row["no_external_call"] == "YES" for row in failures["rows"])
    assert all(row["raw_content_persisted"] == "NO" for row in failures["rows"])


def test_declared_same_owner_cycle_is_rendered_once_deterministically() -> None:
    index = _index()
    left = "sv3-13580b3cdbef263e"
    right = "sv3-faecc1466817d8aa"
    policies = dict(index.section_policies)
    policies[left] = replace(policies[left], cycle_group_id="character-core")
    policies[right] = replace(policies[right], cycle_group_id="character-core")
    edges = []
    for edge in index.dependency_edges:
        if edge.from_section_id == left and edge.to_section_id == right:
            edges.append(replace(edge, cycle_allowed=True))
        else:
            edges.append(edge)
    edges.append(HybridDependencyEdgeV1(
        right, left, "QUALIFIER_DEPENDENCY", "cycle-test",
        "declared same-owner semantic SCC", True,
    ))
    cycle_index = _replace_index(index, policies=policies, edges=edges)
    request, _ = request_for(ROOT, cycle_index, "character-heavy")
    first = HybridSkillContextCompilerV1(cycle_index).materialize(request)
    second = HybridSkillContextCompilerV1(cycle_index).materialize(request)
    assert first.receipt == second.receipt
    assert first.receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"]["cycle_groups"] == ["character-core"]
    assert len(first.receipt["SUPPLEMENT_SECTION_IDS"]) == len(set(first.receipt["SUPPLEMENT_SECTION_IDS"]))


def test_verbatim_mutation_is_detected_before_receipt_acceptance() -> None:
    index = copy.deepcopy(_index())
    section_id = "sv3-10e4ba0c5b7509b4"
    original = index.source_index.by_id[section_id]
    mutated = replace(original, source_text=original.source_text + "mutated\n")
    index.source_index.by_id[section_id] = mutated
    request, _ = request_for(ROOT, index, "character-heavy")
    projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index)
    )(request)
    assert projection["FAILURE_CODE"] == "VERBATIM_MISMATCH"
    assert projection["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES"


def test_malformed_index_identity_fails_after_valid_definition_rehash(tmp_path: Path) -> None:
    payload = json.loads(INDEX_V2.read_text(encoding="utf-8"))
    row = payload["section_policies"].pop("sv3-10e4ba0c5b7509b4")
    payload["section_policies"]["missing-section"] = row
    payload.pop("index_definition_sha256")
    payload["index_definition_sha256"] = _canonical_sha(payload)
    target = tmp_path / "index-v2.json"
    target.write_bytes(_json_bytes(payload))
    with pytest.raises(ValueError, match="MALFORMED_SKILL_SECTION_IDENTITY"):
        HybridSkillSectionIndexV2.load(target, INDEX_V1, ROOT)


def test_materialized_manifest_detects_tamper(tmp_path: Path) -> None:
    root = write_artifacts(tmp_path, _artifacts())
    exact = validate_artifacts(root)
    assert exact["status"] == "EXACT"
    target = root / "capacity-results-v1.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="MATERIALIZED_EVIDENCE_DRIFT"):
        validate_artifacts(root)


def test_privacy_and_external_boundary_are_exact() -> None:
    artifacts = _artifacts()
    privacy = json.loads(artifacts["privacy-scan-v1.json"])
    baseline = json.loads(artifacts["baseline-binding-v1.json"])
    assert privacy["status"] == "PASS"
    assert privacy["raw_prompt_count"] == 0
    assert privacy["raw_story_count"] == 0
    assert privacy["raw_skill_text_in_receipts_count"] == 0
    assert all(
        value == 0 or value == "NO"
        for value in baseline["external_actions"].values()
    )
