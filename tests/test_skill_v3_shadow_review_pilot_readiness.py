from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.selective_skill_compiler import SkillSectionIndexV1
from tools.diagnostics.materialize_skill_v3_shadow_evidence import scenario_records
from tools.diagnostics.review_skill_v3_shadow_pilot_readiness import (
    EVIDENCE,
    SHADOW,
    STRATEGY,
    verify_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sealed_shadow_and_strategy_manifests_are_exact() -> None:
    assert verify_manifest(SHADOW)["status"] == "EXACT"
    assert verify_manifest(STRATEGY)["status"] == "EXACT"


def test_section_identity_is_unique_and_source_bound() -> None:
    index = SkillSectionIndexV1.load(
        ROOT / "vendor/novel-skills/skill-section-index-v1.json", ROOT,
    )
    assert len(index.skill_ids) == 11
    assert len(index.sections) == 413
    assert len({item.section_id for item in index.sections}) == 413


@pytest.mark.parametrize(
    ("demand", "expected_sha"),
    [
        ("character-heavy", "c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd"),
        ("world-heavy", "dc980e981d70fef74d886dae0a04e0c11460020e6e6f147fa1f2f6e54db89c04"),
        ("conflict-pacing-heavy", "e4220b3b3fba69609bf419170f8661f55fe733a7518ce626ab1599a20cc2381e"),
        ("setup-payoff-heavy", "c02f3e19cabe5c7d8a47fb6b9fdb5f785316df6d88afe025c1c095b0e56b4af6"),
        ("mixed", "2d88f401bb4ea70cecd0002382db6648d1055eeaeb5ec1cc78f459925963a2a7"),
    ],
)
def test_five_scenario_selector_provenance_and_capacity_replay(
    demand: str, expected_sha: str,
) -> None:
    records, compiler = scenario_records()
    record = records[demand]
    sealed = _json(SHADOW / f"scenario-{demand}-v1.json")
    assert record["selected_section_ids"] == sealed["selected_section_ids"]
    assert record["rendered_context_sha256"] == expected_sha
    assert record["capacity_status"] == "PASS"
    assert record["receipt"]["overflow_decision"] == "NONE"
    assert compiler.reconstruct(
        # materialize_skill_v3_shadow_evidence stores the exact to_dict receipt;
        # its own independent reconstruction is recorded in the review root.
        compiler.materialize(
            __import__("novel_flywheel.selective_skill_compiler", fromlist=["SelectionInputV1"]).SelectionInputV1(
                resolved_skill_ids=tuple(record["receipt"]["selected_skill_ids"]),
                resolved_skill_source_hashes=tuple(
                    (name, compiler.index.skill_source_sha256[name])
                    for name in record["receipt"]["selected_skill_ids"]
                ),
                stage="planning",
                substage="event_realization",
                task_contract_id=record["receipt"]["task_contract_id"],
                task_contract_schema_sha256=record["receipt"]["task_contract_schema_sha256"],
                creative_demand_class=demand,
                authority_fact_hashes=tuple(record["receipt"]["authority_fact_hashes"].items()),
            ),
            __import__("novel_flywheel.selective_skill_compiler", fromlist=["BudgetInputV1"]).BudgetInputV1(
                safe_context_window_tokens=32768,
                output_reserve_tokens=4624,
                non_skill_input_tokens=record["fixture_token_estimate"],
                wrapper_and_estimator_margin_tokens=1024,
            ),
            task_case=demand,
        ).receipt
    )


def test_review_characterizes_silent_fail_open_as_readiness_failure() -> None:
    review = _json(EVIDENCE / "shadow-fail-open-review-v1.json")
    assert review["shadow_failure_can_block_production"] is False
    assert review["shadow_failure_observable"] is False
    assert review["shadow_failure_evidence_bounded"] is True
    assert review["status"] == "FAIL"
    matrix = _json(EVIDENCE / "pilot-readiness-matrix-v1.json")
    assert matrix["matrix"]["SHADOW_FAIL_OPEN"] == "FAIL"
    assert matrix["overall"] == "NO"


def test_disabled_pilot_artifacts_are_withheld_and_non_executable() -> None:
    plan = _json(EVIDENCE / "real-pilot-plan-v1.json")
    packet = _json(EVIDENCE / "pilot-packet-template-v1.json")
    assert plan["materialized"] is False
    assert plan["execution_authorized"] is False
    assert plan["signed_approval_present"] is False
    assert plan["nonce_reserved"] is False
    assert packet["materialized"] is False
    assert packet["execution_authorized"] is False
    assert packet["real_execution_enabled"] is False


def test_multi_sample_policy_is_exact_and_never_collapses_to_one_sample() -> None:
    binding = _json(EVIDENCE / "multi-sample-policy-binding-v1.json")
    assert binding["pilot_creative_demand_class"] == "character-heavy"
    assert binding["samples_per_a_arm"] == 3
    assert binding["samples_per_b_arm"] == 3
    assert binding["max_total_real_requests"] == 6
    assert binding["single_sample_prompt_hill_climbing_deprecated"] is True
    reuse = _json(EVIDENCE / "historical-sample-reuse-decision-v1.json")
    assert reuse["historical_a_sample_reuse_allowed"] == "NO"
    assert reuse["historical_b_sample_reuse_allowed"] == "NO"


def test_cache_invalidation_matrix_is_six_of_six() -> None:
    review = _json(EVIDENCE / "cache-invalidation-review-v1.json")
    assert review["pass_count"] == review["case_count"] == 6
    assert {row["case"] for row in review["matrix"]} == {
        "source_skill_content_change",
        "section_index_selected_content_change",
        "stage_change",
        "demand_class_change",
        "task_contract_selector_input_change",
        "resolver_version_change",
    }


def test_review_manifest_covers_every_artifact_exactly() -> None:
    result = verify_manifest(EVIDENCE)
    assert result["status"] == "EXACT"
    manifest = _json(EVIDENCE / "sha256-manifest-v1.json")
    assert manifest["entry_count"] >= 31
    assert len(manifest["entries"]) == manifest["entry_count"]
    assert hashlib.sha256(
        (EVIDENCE / "final-report-v1.md").read_bytes()
    ).hexdigest() in {entry["sha256"] for entry in manifest["entries"]}


def test_privacy_and_external_action_counters_remain_zero() -> None:
    privacy = _json(EVIDENCE / "privacy-scan-v1.json")
    receipt = _json(EVIDENCE / "test-receipt-v1.json")
    assert privacy["status"] == "PASS"
    assert privacy["privacy_match_count"] == 0
    for key in (
        "credential_lookup_count",
        "real_provider_client_creation_count",
        "real_provider_request_attempts",
        "http_post_attempts",
        "network_calls",
        "model_calls",
        "paid_calls",
    ):
        assert receipt[key] == 0
