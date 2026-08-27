from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.diagnostics.recheck_skill_v3_multi_sample_pilot_approval_readiness import (
    BASELINE_HEAD,
    BRANCH,
    CLOSURE_ROOT,
    DEFAULT_OUTPUT,
    EXTERNAL_ZERO,
    NEGATIVE_CASES,
    PARENT_EXPERIMENT_LOCK_SHA256,
    PILOT_ID,
    SEQUENCE,
    ReadinessError,
    build_artifacts,
    build_sample_locks,
    load_sealed_state,
    materialize,
    verify_sealed_manifest,
)


VALIDATION = {
    "focused_tests": "TEST",
    "adjacent_tests": "TEST",
    "full_suite": "TEST",
    "strict_l3": "PASS",
}


def test_parent_closure_plan_and_experiment_lock_are_exact() -> None:
    state = load_sealed_state()
    assert state["closure_manifest"]["status"] == "EXACT"
    assert state["plan"]["pilot_id"] == PILOT_ID
    assert state["plan"]["experiment_lock_sha256"] == PARENT_EXPERIMENT_LOCK_SHA256
    assert state["plan"]["execution_authorized"] is False
    assert state["plan"]["signed_approval_present"] is False
    assert state["plan"]["real_execution_nonce_reserved"] is False
    assert tuple(state["plan"]["sequential_execution_order"]) == SEQUENCE


def test_six_sample_locks_are_unique_and_only_skill_context_varies() -> None:
    state = load_sealed_state()
    locks = build_sample_locks(state)
    assert len(locks) == 6
    assert len({row["sample_id"] for row in locks}) == 6
    assert len({row["sample_lock_sha256"] for row in locks}) == 6
    non_skill_keys = (
        "authority_sha256", "task_sha256", "story_slice_sha256",
        "non_skill_prompt_sha256", "project_guidance_sha256",
        "reference_derived_provenance_sha256", "style_guidance_state",
        "output_contract_sha256", "validator_sha256", "ptr_policy_sha256",
        "model_route_policy_sha256", "model_binding_sha256",
        "provider_descriptor_sha256", "route_fingerprint", "client", "protocol",
        "sampling_policy_sha256", "output_cap",
    )
    for key in non_skill_keys:
        assert len({row[key] for row in locks}) == 1, key
    assert {row["skill_context_sha256"] for row in locks} == {
        "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc",
        "c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd",
    }


def test_capacity_is_exact_for_both_arms() -> None:
    artifacts = build_artifacts(VALIDATION)
    capacity = artifacts["capacity-recheck-v1.json"]
    assert capacity["status"] == "PASS"
    a, b = capacity["arms"]
    assert (a["skill_context_chars"], a["skill_context_token_estimate"]) == (2925, 732)
    assert (b["skill_context_chars"], b["skill_context_token_estimate"]) == (2556, 639)
    assert (a["headroom"], b["headroom"]) == (17488, 17581)
    assert capacity["no_silent_truncation"] is True


def test_negative_matrix_is_complete_and_external_action_free() -> None:
    artifacts = build_artifacts(VALIDATION)
    matrix = artifacts["negative-readiness-matrix-v1.json"]
    assert matrix["passed"] == matrix["total"] == len(NEGATIVE_CASES) == 32
    assert [row["case"] for row in matrix["rows"]] == list(NEGATIVE_CASES)
    assert all(row["status"] == "PASS" for row in matrix["rows"])
    assert all(row["reason_code"] == row["case"] for row in matrix["rows"])
    assert all(row["synthetic_attempt_only"] is True for row in matrix["rows"])
    assert all(row["external_actions"] == EXTERNAL_ZERO for row in matrix["rows"])
    assert matrix["real_boundary_reached"] == 0


def test_missing_skill_v3_launcher_yields_conditional_not_guess() -> None:
    artifacts = build_artifacts(VALIDATION)
    launcher = artifacts["launcher-binding-v1.json"]
    entry = artifacts["execution-entry-binding-v1.json"]
    dispatch = artifacts["single-dispatch-binding-v1.json"]
    readiness = artifacts["approval-readiness-matrix-v1.json"]
    assert launcher["sealed_skill_v3_launcher_count"] == 0
    assert launcher["status"] == entry["status"] == dispatch["status"] == "CONDITIONAL"
    assert readiness["overall"] == "CONDITIONAL"
    assert readiness["conditional_dimensions"] == [
        "EXECUTION_ENTRY", "LAUNCHER", "SINGLE_DISPATCH",
    ]


def test_all_six_readiness_objects_are_disabled_and_inert() -> None:
    artifacts = build_artifacts(VALIDATION)
    objects = [
        artifacts[f"sample-readiness-{slot.lower()}-v1.json"] for slot in SEQUENCE
    ]
    assert len(objects) == 6
    assert all(obj["execution_authorized"] is False for obj in objects)
    assert all(obj["signed_approval_present"] is False for obj in objects)
    assert all(obj["nonce_reserved"] is False for obj in objects)
    assert all(obj["nonce_consumed"] is False for obj in objects)
    assert all(obj["real_execution_enabled"] is False for obj in objects)
    assert all(obj["launcher"] == "NOT_SEALED_CONDITION" for obj in objects)


def test_offline_dry_run_privacy_and_production_isolation() -> None:
    artifacts = build_artifacts(VALIDATION)
    dry = artifacts["offline-six-sample-dry-run-v1.json"]
    privacy = artifacts["privacy-scan-v1.json"]
    production = artifacts["production-isolation-v1.json"]
    assert dry["sample_readiness_load_pass"] == "6/6"
    assert dry["real_boundary_reached"] == 0
    assert all(dry[key] == 0 for key in EXTERNAL_ZERO)
    assert privacy["status"] == "PASS" and privacy["privacy_match_count"] == 0
    assert privacy["scanned_artifact_count"] == 37
    assert production["production_behavior_diff"] == 0
    assert production["production_model_input_identity"] == "PASS"
    assert production["baml_src_diff"] == 0


def test_materialization_is_complete_manifest_bound_and_single_use(tmp_path: Path) -> None:
    output = tmp_path / "readiness"
    result = materialize(output, VALIDATION)
    assert result["overall"] == "CONDITIONAL"
    assert result["manifest"]["status"] == "EXACT"
    assert result["manifest"]["entry_count"] == 38
    assert len(list(output.iterdir())) == 39
    with pytest.raises(ReadinessError, match="READINESS_EVIDENCE_ROOT_ALREADY_EXISTS"):
        materialize(output, VALIDATION)


def test_repository_materialization_manifest_is_exact_when_present() -> None:
    if not DEFAULT_OUTPUT.exists():
        pytest.skip("final evidence is materialized after test receipts are known")
    result = verify_sealed_manifest(DEFAULT_OUTPUT)
    assert result["status"] == "EXACT"
    assert result["entry_count"] == 38
    report = (DEFAULT_OUTPUT / "final-report-v1.md").read_text(encoding="utf-8")
    assert "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READY=CONDITIONAL" in report
    assert "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS_CONDITION_CLOSURE" in report


def test_baseline_constants_are_frozen() -> None:
    assert BRANCH == "r1-ptr3/planning-repair-finding-propagation-20260817"
    assert BASELINE_HEAD == "3e317192fe98601789d76d1751b9f3073f3a797c"
    assert verify_sealed_manifest(CLOSURE_ROOT)["status"] == "EXACT"
