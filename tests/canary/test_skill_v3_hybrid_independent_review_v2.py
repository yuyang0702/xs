from __future__ import annotations

import json
from pathlib import Path

from novel_flywheel.hybrid_skill_context import (
    HybridSkillContextCompilerV1,
    HybridSkillSectionIndexV2,
)
from tools.diagnostics.materialize_skill_v3_hybrid_independent_review_v2 import (
    DEMANDS,
    INDEX_V1,
    INDEX_V2,
    NEXT_GATE_PASS,
    OUTPUT,
    PLANNING_SKILL_IDS,
    REQUIRED_FILES,
    _failure_rows,
    _production_baseline,
    _request,
    build_artifacts,
    validate_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]


def _read_artifact(artifacts: dict[str, bytes], name: str) -> dict:
    return json.loads(artifacts[name].decode("utf-8"))


def test_current_production_compactor_baseline_is_the_exact_hybrid_prefix() -> None:
    index = HybridSkillSectionIndexV2.load(
        ROOT / INDEX_V2, ROOT / INDEX_V1, ROOT,
    )
    full, baseline, resolved = _production_baseline(ROOT)
    assert len(full) == 21345
    assert len(baseline) == 8927
    assert (
        __import__("hashlib").sha256(baseline.encode("utf-8")).hexdigest()
        == "c7916de36e67f380f2e10f30f169bcdbe04440cc8bd01bbf2626d26a7cdf49b7"
    )
    request = _request(index, resolved, baseline, "character-heavy")
    result = HybridSkillContextCompilerV1(index).materialize(request)
    offset = len(request.protected_non_skill_prefix)
    assert result.final_hybrid_advisory[
        offset:offset + len(baseline)
    ].encode("utf-8") == baseline.encode("utf-8")
    assert request.resolved_skill_ids == PLANNING_SKILL_IDS


def test_all_required_failures_are_exercised_with_hash_only_receipts() -> None:
    index = HybridSkillSectionIndexV2.load(
        ROOT / INDEX_V2, ROOT / INDEX_V1, ROOT,
    )
    _full, baseline, resolved = _production_baseline(ROOT)
    request = _request(index, resolved, baseline, "character-heavy")
    rows = _failure_rows(ROOT, index, request)
    assert len(rows) == 13
    assert all(row["FAILURE_OBSERVABLE"] == "YES" for row in rows)
    assert all(row["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES" for row in rows)
    assert all(row["NO_EXTERNAL_CALL"] == "YES" for row in rows)
    assert all(
        row["NO_EXCEPTION_SWALLOWED_WITHOUT_RECEIPT"] == "YES"
        for row in rows
    )
    assert all(len(row["FAILURE_RECEIPT_SHA256"]) == 64 for row in rows)


def test_source_first_review_passes_all_readiness_gates_in_memory() -> None:
    artifacts = build_artifacts(
        ROOT,
        focused="in-memory focused pass",
        related="in-memory related pass",
        full_suite="in-memory full-suite receipt",
        strict_l3="PASS",
        new_review_regressions=0,
        new_owning_regressions=0,
    )
    decision = _read_artifact(artifacts, "pilot-readiness-decision-v1.json")
    capacity = _read_artifact(
        artifacts, "independent-capacity-recompute-v1.json",
    )
    dependency = _read_artifact(
        artifacts, "semantic-dependency-review-v1.json",
    )
    anti_overfit = _read_artifact(artifacts, "anti-overfit-review-v1.json")
    assert decision["INDEPENDENT_REVIEW_BLOCKER_COUNT"] == 0
    assert decision["SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW"] == "PASS"
    assert decision["NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX"] == "YES"
    assert decision["PILOT_EXECUTION_AUTHORIZED"] == "NO"
    assert decision["EXACT_NEXT_GATE"] == NEXT_GATE_PASS
    assert [row["DEMAND_CLASS"] for row in capacity["rows"]] == list(DEMANDS)
    assert capacity["ALL_FIVE_DEMAND_CAPACITY"] == "PASS"
    assert dependency["KNOWN_SEMANTIC_DEPENDENCY_GAPS_CLOSED"] == "4/4"
    assert dependency["status"] == "PASS"
    assert anti_overfit["status"] == "PASS"


def test_prospective_contract_is_non_executable_and_single_variable() -> None:
    artifacts = build_artifacts(
        ROOT,
        focused="pass",
        related="pass",
        full_suite="pass",
        strict_l3="PASS",
        new_review_regressions=0,
        new_owning_regressions=0,
    )
    contract = _read_artifact(
        artifacts, "prospective-experiment-contract-v1.json",
    )
    stop_loss = _read_artifact(artifacts, "stop-loss-policy-v1.json")
    assert contract["executable"] is False
    assert contract["PRIMARY_CHANGED_VARIABLE"] == (
        "SKILL_CONTEXT_TREATMENT_LAYER_ONLY"
    )
    assert contract["matched_pair_count"] == 3
    assert contract["sample_count"] == 6
    assert contract["max_requests_per_sample"] == 1
    assert contract["executable_approval_created"] is False
    assert contract["real_nonce_created"] is False
    assert stop_loss[
        "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE"
    ] is True


def test_materialized_evidence_file_set_and_manifest_are_exact() -> None:
    receipt = validate_artifacts(ROOT / OUTPUT)
    assert receipt["status"] == "EXACT"
    assert receipt["file_count"] == len(REQUIRED_FILES)
    assert receipt["entry_count"] == len(REQUIRED_FILES) - 1
