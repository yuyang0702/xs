from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from novel_flywheel.models import ModelResult
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationInputAuthorityV1,
    normalize_event_realization_input_authority_v1,
)
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_skill_v2_single_dispatch as launcher


ROOT = Path(__file__).resolve().parents[2]
ROUTE_DATABASE = ROOT / "data/app.db"


def _bindings():
    workload, authority = base.load_fixture_binding(ROOT)
    contract = base.slice1_contract_binding(ROOT)
    route = base.resolve_route_binding(ROUTE_DATABASE)
    profile, context, runtime = launcher.build_skill_v2_profile(
        ROOT, workload["authority_input_sha256"],
    )
    model_input, comparison = launcher._model_input_pair(
        ROOT, authority, contract, route, profile, context,
    )
    return workload, authority, contract, route, profile, context, runtime, model_input, comparison


def test_a_arm_is_exact_sealed_pass() -> None:
    result = launcher.verify_a_arm_baseline(ROOT)
    assert result["status"] == "SEALED_PASS"
    assert result["artifact_sha256"] == launcher.A_ARTIFACT_SHA256
    assert result["current_skill_profile_sha256"] == launcher.A_CURRENT_SKILL_PROFILE_SHA256
    assert result["model_input_assembly_sha256"] == launcher.A_MODEL_INPUT_SHA256
    assert result["execution_manifest"]["entry_count"] == 15
    assert result["approval_reuse_allowed"] is False
    assert result["nonce_consumed"] is True


def test_skill_v2_source_of_truth_and_quality_are_exact() -> None:
    result = launcher.verify_skill_v2_source_of_truth(ROOT)
    assert result["profile_id"] == launcher.SKILL_PROFILE_ID
    assert result["profile_version"] == 1
    assert result["production_active"] is False
    assert result["offline_quality_status"] == "VALIDATED"
    assert result["bundle_status"] == "exact"
    assert result["shadow_manifest"]["entry_count"] == 17
    assert result["offline_quality_manifest"]["entry_count"] == 18


def test_skill_v2_profile_and_context_are_deterministic_safe_and_complete() -> None:
    _, _, _, _, profile, context, runtime, _, _ = _bindings()
    assert profile["profile_id"] == launcher.SKILL_PROFILE_ID
    assert profile["resolution_run_count"] == 2
    assert profile["resolution_deterministic"] is True
    assert profile["runtime_owned_responsibility_leak"] is False
    assert profile["authority_override_allowed"] is False
    assert profile["shadow_only"] is True
    assert profile["production_reachable"] is False
    assert runtime["receipt"]["dispatch_allowed"] is True
    assert runtime["receipt"]["rendered_context_sha256"] == launcher._sha_bytes(
        context.encode("utf-8")
    )
    assert len(context) <= 3000
    assert "write_story_state" not in context
    assert "write_canon" not in context


def test_ab_model_input_changes_only_skill_context() -> None:
    _, _, _, route, profile, _, _, model_input, comparison = _bindings()
    assert comparison["a_model_input"]["model_input_assembly_sha256"] == (
        launcher.A_MODEL_INPUT_SHA256
    )
    assert comparison["a_model_input"]["user_sha256"] == model_input["user_sha256"]
    assert comparison["a_system"] != comparison["b_system"]
    assert comparison["a_skill_context_sha256"] != comparison["b_skill_context_sha256"]
    assert model_input["skill_v2_profile_sha256"] == profile["canonical_profile_sha256"]
    assert model_input["route_selection_inputs_sha256"] == route["route_binding_sha256"]
    assert model_input["contract_sha256"] == comparison["a_model_input"]["contract_sha256"]
    assert model_input["validator_bundle_sha256"] == comparison["a_model_input"]["validator_bundle_sha256"]


def test_closed_world_profile_scope_cohort_and_roots() -> None:
    profile = launcher.packet_profile()
    assert profile["approval_scope"] == launcher.APPROVAL_SCOPE
    assert profile["cohort_id"] == launcher.COHORT_ID
    assert profile["ab_pair_id"] == launcher.AB_PAIR_ID
    assert profile["skill_profile_id"] == launcher.SKILL_PROFILE_ID
    assert profile["materialization_relative_root"] == launcher.MATERIALIZATION_RELATIVE_ROOT
    assert profile["execution_relative_root"] == launcher.EXECUTION_RELATIVE_ROOT
    assert profile["arbitrary_skill_profile_acceptance"] is False
    assert profile["arbitrary_scope_acceptance"] is False
    assert profile["arbitrary_cohort_acceptance"] is False
    assert launcher.APPROVAL_SCOPE != "SLICE1_PHASE_B_CURRENT_SKILL_AUDIT_SAFE_SINGLE_DISPATCH_V5_ONLY"


def test_single_dispatch_transport_guard_and_budget_are_unchanged() -> None:
    _, _, _, route, _, _, _, model_input, _ = _bindings()
    guard = launcher.transport_guard_contract(ROOT)
    accounting = launcher.legacy.attempt_accounting_contract(guard)
    budget = launcher._budget(route, model_input)
    assert guard["policy_definition_sha256"] == (
        "c5d6166cfd262d86e9a7efa854d8c27ff4274f50fee7061833361435d103735d"
    )
    assert guard["max_http_post_attempts"] == 1
    assert guard["max_real_provider_request_attempts"] == 1
    assert guard["sdk_retries_disabled_for_phase_b"] is True
    assert guard["transport_request_retries_disabled_for_phase_b"] is True
    assert guard["route_fallback_after_dispatch_allowed"] is False
    assert accounting["hard_max_model_logical_calls"] == 1
    assert accounting["hard_max_network_request_attempts"] == 1
    assert budget["hard_max_output_tokens_per_call"] == 4624
    assert budget["second_run_allowed"] is False
    assert budget["resume_allowed"] is False


def test_approval_template_is_disabled_and_a_approval_cannot_match() -> None:
    template = launcher._approval_template({"fixture": "f" * 64})
    assert template["execution_authorized"] is False
    assert template["named_approver"] is None
    assert template["signed_approval"] == "ABSENT"
    assert template["single_use_nonce"] is None
    assert template["usage_status"] == "unused"
    assert template["reservation_status"] == "unreserved"
    assert all(value == 0 for value in template["external_actions"].values())
    old = json.loads((ROOT / launcher.a_launcher.APPROVAL_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert old["approval_scope"] != launcher.APPROVAL_SCOPE
    assert old["cohort_id"] != launcher.COHORT_ID
    assert old["bound_hashes"] != template["bound_hashes"]


def test_quality_and_engineering_comparison_are_multidimensional() -> None:
    quality = launcher._quality_rubric()
    engineering = launcher._engineering_rubric()
    assert len(quality["dimensions"]) >= 18
    assert quality["literary_single_scalar_score"] == "DISALLOWED"
    assert quality["quality_regression_fails_b_arm"] is True
    assert quality["engineering_gain_overrides_meaningful_quality_regression"] is False
    assert len(engineering["metrics"]) >= 20
    assert engineering["unknown_remains_unknown"] is True
    assert engineering["provider_pricing_inferred"] is False


def test_synthetic_b_arm_full_success_tail_is_frozen_and_audit_safe(tmp_path: Path) -> None:
    _, authority_value = base.load_fixture_binding(ROOT)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value)
    )
    response = json.dumps({
        "title": "Synthetic B-arm realization",
        "narrative": (
            "The bounded actor chooses a costly course, meets clear resistance, "
            "and creates the required causal handoff without changing authority."
        ),
    })
    run_root = tmp_path / "run"
    run_root.mkdir()
    receipt = launcher.persist_success_tail_v1(
        result=ModelResult(text=response, receipt={"finish_reason": "end_turn"}),
        authority=authority,
        attempts={
            "model_logical_calls": 0,
            "real_provider_request_attempts": 0,
            "http_post_attempts": 0,
            "network_request_attempts": 0,
        },
        run_root=run_root,
    )
    assert receipt["local_terminal"] == "PASS"
    assert receipt["validator_status"] == "PASS"
    assert receipt["freeze_state"] == "FROZEN"
    assert receipt["audit_serialization"] == "PASS"
    assert receipt["artifact_persisted"] is True
    persisted = (run_root / "artifact/generated-event-realization-v1.json").read_text(
        encoding="utf-8"
    )
    assert launcher.COHORT_ID in persisted
    assert launcher.SKILL_ARM in persisted
    assert "raw_response" not in persisted


def test_credential_capable_imports_are_below_signed_preflight() -> None:
    source = inspect.getsource(launcher.execute_authorized_once)
    preflight_index = source.index("validate_signed_launch(")
    credential_import_index = source.index("from novel_flywheel.secrets import")
    assert preflight_index < credential_import_index
    assert "transport_policy=SingleDispatchTransportPolicyV1.phase_b()" in source
    assert source.count("gateway.complete_route(") == 1
    assert '"configured_fallback"' not in source


def test_canonical_packet_if_present_is_exact() -> None:
    packet_root = ROOT / launcher.MATERIALIZATION_RELATIVE_ROOT
    if not packet_root.exists():
        pytest.skip("materialization seal is created after the support commit")
    result = launcher.validate_materialized_packet(ROOT, packet_root, ROUTE_DATABASE)
    assert result["status"] == "exact"
    assert result["approval"]["execution_authorized"] is False
    assert result["comparison"]["primary_changed_variable"] == "SKILL_CONTEXT"
