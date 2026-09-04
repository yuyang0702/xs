from __future__ import annotations

import copy
import hashlib
import json

import pytest

from novel_flywheel.full_short_campaign_authorization import (
    FullShortCampaignAuthorizationError,
    canonical_json_bytes,
    render_full_short_one_round_budget_unblocked_execution_authorization_v1,
    validate_full_short_one_round_budget_unblocked_execution_authorization_v1,
)
from novel_flywheel.full_short_execution import (
    FullShortExecutionPolicyV1,
    LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    RESPONSE_CAPTURE_POLICY_V1,
    TRANSPORT_RECOVERY_POLICY_SHA256,
    TRANSPORT_RECOVERY_POLICY_V1,
    render_full_short_canonical_authorization_v1,
)
from novel_flywheel.full_short_probe_campaign import (
    CampaignLimits,
    ProbeCase,
    ProbeRouteIdentity,
    build_probe_campaign_plan,
)


KEY = b"offline-campaign-verification-key-v1"


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash(value: object) -> str:
    return _hash_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _egress() -> dict:
    return {
        "allowed": [
            "system_context", "task_contract", "authority", "story_slice",
            "current_baseline_skill_context", "output_contract",
            "provider_request_metadata",
        ],
        "forbidden": [
            "credentials", "unrelated_project_data", "raw_provider_evidence",
            "retired_skill_v3_hybrid_context",
        ],
    }


def _full_short_dependencies():
    routes = [{
        "role": "planning", "lane": "primary",
        "provider_name": "provider", "provider_operator": "operator",
        "provider_id_sha256": _hash_bytes(b"provider"),
        "model_id_sha256": _hash_bytes(b"model-id"),
        "model_name": "offline", "protocol": "anthropic",
        "route_fingerprint": "9" * 64,
        "destination": "https://unit.test:443/v1/messages",
        "max_output_tokens": 4096,
        "route_context_capability_limit_tokens": 32768,
        "route_context_capability_source": "model_configuration",
    }]
    logical_plan = [{
        "ordinal": 1, "stage_id": "planning",
        "logical_stage_base_id": "planning", "logical_stage_id": "planning",
        "role": "planning", "route_lane": "primary",
        "contract_name": "unstructured_text", "contract_version": 1,
        "contract_schema_sha256": _hash({}),
        "contract_runtime_input_required": False,
        "requested_output_tokens": 128,
    }]
    policy = FullShortExecutionPolicyV1(
        execution_head="a" * 40,
        branch="test",
        run_id="campaign-auth-test",
        project_id_sha256=(
            "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720"
        ),
        workload_sha256="c" * 64,
        runtime_authority_sha256="d" * 64,
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_hash(routes),
        destination_manifest_sha256=_hash([routes[0]["destination"]]),
        egress_policy_sha256=_hash(_egress()),
        store_root_sha256="0" * 64,
        capture_attestation_public_key="1" * 64,
        capture_attestation_public_key_sha256=_hash_bytes(bytes.fromhex("1" * 64)),
        required_stage_roles=("planning",),
        logical_stage_plan=tuple(logical_plan),
        expected_stage_calls=1,
        hard_max_provider_requests=4,
        hard_max_http_posts=4,
        hard_max_network_attempts=4,
        per_call_output_token_hard_cap=4096,
        total_output_token_hard_cap=4096,
        maximum_elapsed_seconds=3600,
    ).document()
    architecture_fields = (
        "failure_architecture_identity", "recovery_policy_registry",
        "recovery_policy_registry_sha256", "predispatch_state_machine",
        "predispatch_state_machine_sha256", "nonce_reservation_policy",
        "nonce_reservation_policy_sha256", "observer_isolation_policy",
        "observer_isolation_policy_sha256", "durable_failure_evidence_policy",
        "durable_failure_evidence_policy_sha256", "capacity_policy_registry_sha256",
    )
    public = {
        "routes": routes,
        "destinations": [routes[0]["destination"]],
        "egress_policy": _egress(),
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "capture_attestation_scheme": policy["capture_attestation_scheme"],
        "capture_attestation_public_key": policy["capture_attestation_public_key"],
        "capture_attestation_public_key_sha256": policy[
            "capture_attestation_public_key_sha256"
        ],
        "logical_stage_plan": policy["logical_stage_plan"],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": TRANSPORT_RECOVERY_POLICY_SHA256,
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": "0" * 64,
        **{field: policy[field] for field in architecture_fields},
    }
    raw = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public,
    )
    return policy, public, raw, routes


def _authorization():
    policy, public, canonical_full_short, routes = _full_short_dependencies()
    cases = []
    runtime_cases = []
    # The authoritative 111 blocked ordinals are sparse within 183 physical
    # shapes.  This fixture preserves that topology instead of inventing 1..111.
    source_shapes = [value for value in range(1, 184) if value % 5 != 0][:111]
    cursor = 1
    estimates = (30_458, 32_380, 16_321, 18_140, 18_429, 21_136, 18_549, 31_320)
    for ordinal, size in enumerate((14, 14, 14, 14, 14, 14, 14, 13), 1):
        destination = f"https://probe-{ordinal}.invalid/v1/messages"
        runtime_case = ProbeCase(
            ordinal=ordinal,
            case_id=f"probe-{ordinal:02d}",
            route=ProbeRouteIdentity(
                provider=f"provider-{ordinal}", operator=f"operator-{ordinal}",
                destination_sha256=_hash_bytes(destination.encode()),
                protocol="synthetic-v1", model=f"model-{ordinal}",
                route_fingerprint=_hash_bytes(f"route-{ordinal}".encode()),
            ),
            fixture_sha256=_hash_bytes(f"fixture-{ordinal}".encode()),
            input_envelope_sha256=_hash_bytes(f"input-{ordinal}".encode()),
            estimated_input_tokens=estimates[ordinal - 1],
            wire_requested_output_cap=2048,
            blocked_shape_ordinals=tuple(source_shapes[cursor - 1:cursor - 1 + size]),
        )
        cursor += size
        runtime_cases.append(runtime_case)
        cases.append({
            "ordinal": runtime_case.ordinal,
            "case_id": runtime_case.case_id,
            "case_sha256": runtime_case.case_sha256,
            "route": {
                **runtime_case.route.__dict__,
                "destination": destination,
            },
            "fixture_sha256": runtime_case.fixture_sha256,
            "input_envelope_sha256": runtime_case.input_envelope_sha256,
            "request_family_sha256": _hash_bytes(
                f"family-{ordinal}".encode()
            ),
            "request_sha256": _hash_bytes(f"request-{ordinal}".encode()),
            "estimated_input_tokens": runtime_case.estimated_input_tokens,
            "wire_requested_output_cap": runtime_case.wire_requested_output_cap,
            "blocked_shape_ordinals": list(runtime_case.blocked_shape_ordinals),
        })
    probe_plan = build_probe_campaign_plan(
        runtime_cases, source_blocked_shape_ordinals=source_shapes,
    )
    promotion = {
        "identity": "EXACT_SIGNED_WORKLOAD_LOWER_BOUND_ONLY",
        "accept_verified_safe_lower_bound": True,
        "accept_verified_workload_shape": True,
        "accept_verified_request_output_shape": True,
        "theoretical_maximum_inference_allowed": False,
        "arbitrary_external_json_allowed": False,
        "upstream_model_name_inheritance_allowed": False,
        "exact_authorization_hash_required": True,
        "exact_frozen_head_required": True,
        "exact_current_route_required": True,
        "post_freeze_git_write_allowed": False,
    }
    route_graph = [{
        "ordinal": 1, "role": "planning", "lane": "primary",
        "provider": "provider", "operator": "operator",
        "destination": routes[0]["destination"], "protocol": "anthropic",
        "model": "offline", "route_fingerprint": "9" * 64,
    }]
    identity = lambda name, digest: {"identity": name, "sha256": digest}
    authorization = {
        "schema": "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1",
        "version": 1,
        "authorization_source": {
            "identity": "FULL_SHORT_END_TO_END_ONE_ROUND_INPUT_BUDGET_UNBLOCK_EXECUTE_MASTER",
            "sha256": "29ab6557dc7ebdf687b86ee47f55472aa01e406166d0cfde87641630bd22791e",
        },
        "frozen_execution": {
            "final_execution_head": "a" * 40, "branch": "test",
            "worktree": "CLEAN", "no_git_write_after_final_head_freeze": True,
        },
        "probe_campaign": {
            "schema": "FullShortEightProbeCampaignV1",
            "plan_sha256": probe_plan.plan_sha256,
            "cases": cases,
            "source_blocked_shape_ordinals": source_shapes,
            "blocked_shape_coverage_count": 111,
            "uncovered_blocked_shape_count": 0,
            "limits": {
                "provider_requests": 144, "http_post_attempts": 144,
                "network_requests": 144, "input_tokens": 4_000_000,
                "generated_output_tokens": 2_000_000,
                "output_tokens_per_request": 32_000, "elapsed_seconds": 36_000,
            },
            "sequential": True, "maximum_physical_requests_per_case": 1,
            "retry_allowed": False, "fallback_allowed": False,
            "route_switch_allowed": False,
            "stop_on_first_dispatched_failure": True,
            "exact_response_capture_required": True,
            "raw_novel_content_egress_count": 0,
            "real_project_content_egress_count": 0,
        },
        "external_workload_evidence": {
            "schema": "ExternalWorkloadEvidenceV1",
            "verification_key": {
                "key_id": "campaign-key-v1", "algorithm": "HMAC-SHA256",
                "key_sha256": _hash_bytes(KEY),
            },
            "promotion_policy": promotion,
            "promotion_policy_sha256": _hash(promotion),
        },
        "exact_ready_target": {
            "project_id": "2ad716f3c0d1",
            "project_id_sha256": "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720",
            "ready_authority_sha256": "2" * 64,
            "required_status": "READY",
        },
        "production_bindings": {
            "route_model_graph": route_graph,
            "route_model_graph_sha256": _hash(route_graph),
            "route_manifest": identity("CURRENT_PRODUCTION_ROUTE_MANIFEST", policy["route_manifest_sha256"]),
            "destination_manifest": identity("CURRENT_PRODUCTION_DESTINATION_MANIFEST", policy["destination_manifest_sha256"]),
            "runtime_kernel": identity("CURRENT_RUNTIME_KERNEL", policy["runtime_authority_sha256"]),
            "baseline_skill": identity("CURRENT_BASELINE_SKILL", policy["style_reference_authority_sha256"]),
            "segmentation_windowing_policy": identity("CURRENT_SEGMENTATION_WINDOWING_POLICY", "3" * 64),
            "capacity_admission_policy": identity("CURRENT_CAPACITY_ADMISSION_POLICY", policy["capacity_policy_registry_sha256"]),
            "transport_recovery_policy": identity("EXACT_REPLAY_ONLY", policy["transport_recovery_policy_sha256"]),
            "logical_stage_recovery_policy": identity("TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY", policy["logical_stage_recovery_policy_sha256"]),
            "authority_gates": identity("CURRENT_STORYSTATE_CANON_READY_AUTHORITY_GATES", "4" * 64),
            "response_capture_policy": identity("CURRENT_EXACT_RESPONSE_CAPTURE_POLICY", policy["response_capture_policy_sha256"]),
            "response_replay_policy": identity("CURRENT_EXACT_RESPONSE_REPLAY_POLICY", "5" * 64),
            "full_short_canonical_authorization_schema": "FullShortCanonicalAuthorizationV1",
            "post_probe_authorization_derivation": {
                "identity": "FROZEN_HEAD_VERIFIED_EXTERNAL_EVIDENCE_DERIVATION_ONLY",
                "exact_outer_authorization_sha256_required": True,
                "exact_frozen_head_required": True,
                "exact_verified_evidence_packages_required": True,
                "exact_production_route_graph_required": True,
                "exact_ready_target_required": True,
                "canonical_runtime_validator_required": True,
                "external_non_git_storage_required": True,
                "arbitrary_nested_authorization_allowed": False,
                "derivation_count_maximum": 1,
            },
        },
        "budgets": {
            "budget_recalculation_source": identity("docs/budget.json", "6" * 64),
            "authoritative_attempt_matrix_source": identity("docs/matrix.json", "7" * 64),
            "probe_family_derivation_source": identity("docs/probe.json", "8" * 64),
            "maximum_typed_business_recovery_path_physical_calls": 96,
            "maximum_typed_business_recovery_path_provider_wire_input": 2_373_076,
            "exact_probe_fixture_input_tokens": 186_733,
            "plan_derived_margin_numerator": 120,
            "plan_derived_margin_denominator": 100,
            "old_absolute_max_input_tokens": 2_000_000,
            "old_campaign_input_lower_bound": 2_388_221,
            "restored_deduplicated_call_input": 16_037,
            "exact_pre_dispatch_estimated_input_tokens": 2_559_809,
            "plan_derived_max_input_tokens": 3_071_771,
            "new_absolute_max_input_tokens": 4_000_000,
            "absolute_max_provider_requests": 144,
            "absolute_max_http_post_attempts": 144,
            "absolute_max_network_requests": 144,
            "absolute_max_generated_output_tokens": 2_000_000,
            "absolute_max_output_tokens_per_provider_request": 32_000,
            "absolute_max_elapsed_seconds": 36_000,
            "usd_hard_cap_if_reliably_meterable": 60,
            "cny_hard_cap_if_reliably_meterable": 120,
            "budget_gate": "PASS",
        },
        "scope": {
            "single_campaign": True, "reusable": False,
            "maximum_real_full_short_executions": 1,
            "long_execution_allowed": False, "route_change_allowed": False,
            "model_change_allowed": False, "baseline_skill_change_allowed": False,
            "skill_v3_production_cutover": False,
            "hybrid_production_cutover": False,
            "selective_production_cutover": False,
            "planning_v2_production_cutover": False,
            "whole_run_retry_allowed": False,
        },
        "execution_authorized": True,
        "named_approver": "USER_PREAUTHORIZED_BY_THIS_MASTER",
        "usage_status": "unused",
        "campaign_usage": {
            "probe_phase_status": "unused",
            "full_short_phase_status": "unused", "provider_requests": 0,
            "http_post_attempts": 0, "network_requests": 0, "model_calls": 0,
            "paid_calls": 0, "input_tokens": 0,
            "generated_output_tokens": 0, "real_full_short_executions": 0,
            "nonces_created": 0,
        },
    }
    return authorization, policy, public


def _render():
    authorization, policy, public = _authorization()
    raw = render_full_short_one_round_budget_unblocked_execution_authorization_v1(
        authorization, full_short_policy=policy,
        full_short_public_bindings=public,
        verification_keys={"campaign-key-v1": KEY},
    )
    return authorization, policy, public, raw


def test_canonical_authorization_binds_master_plan_production_and_unused_scope() -> None:
    expected, policy, public, raw = _render()
    validated = validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
        raw, expected=expected, full_short_policy=policy,
        full_short_public_bindings=public,
        verification_keys={"campaign-key-v1": KEY},
    )
    assert validated["authorization_source"]["sha256"] == (
        "29ab6557dc7ebdf687b86ee47f55472aa01e406166d0cfde87641630bd22791e"
    )
    assert [item["ordinal"] for item in validated["probe_campaign"]["cases"]] == list(range(1, 9))
    assert validated["probe_campaign"]["source_blocked_shape_ordinals"][-1] > 111
    assert validated["budgets"]["plan_derived_max_input_tokens"] == 3_071_771
    assert validated["budgets"]["new_absolute_max_input_tokens"] == 4_000_000
    assert validated["execution_authorized"] is True
    assert validated["named_approver"] == "USER_PREAUTHORIZED_BY_THIS_MASTER"
    assert validated["usage_status"] == "unused"
    assert validated["scope"]["maximum_real_full_short_executions"] == 1
    assert len(validated["authorization_sha256"]) == 64


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_extra_or_missing_fields_are_rejected(change: str) -> None:
    expected, policy, public, _raw = _render()
    changed = copy.deepcopy(expected)
    if change == "extra":
        changed["campaign_usage"]["comment"] = "not allowed"
    else:
        del changed["named_approver"]
    raw = canonical_json_bytes(changed)
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            raw, expected=expected, full_short_policy=policy,
            full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )


def test_noncanonical_bytes_and_exact_binding_drift_are_rejected() -> None:
    expected, policy, public, raw = _render()
    with pytest.raises(FullShortCampaignAuthorizationError, match="NONCANONICAL"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            raw + b"\n", expected=expected, full_short_policy=policy,
            full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )
    drifted = copy.deepcopy(expected)
    drifted["exact_ready_target"]["ready_authority_sha256"] = "7" * 64
    with pytest.raises(FullShortCampaignAuthorizationError, match="EXACT_BINDING_DRIFT"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            canonical_json_bytes(drifted), expected=expected,
            full_short_policy=policy, full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )


def test_plan_route_and_nested_full_short_drift_fail_closed() -> None:
    expected, policy, public, _raw = _render()
    changed = copy.deepcopy(expected)
    changed["probe_campaign"]["cases"][0]["estimated_input_tokens"] += 1
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            canonical_json_bytes(changed), expected=expected,
            full_short_policy=policy, full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )

    wrong_policy = copy.deepcopy(policy)
    wrong_policy["execution_head"] = "b" * 40
    with pytest.raises(FullShortCampaignAuthorizationError, match="FULL_SHORT_CANONICAL"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            _render()[3], expected=expected, full_short_policy=wrong_policy,
            full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )


def test_reuse_wrong_key_and_over_cap_usage_are_rejected() -> None:
    expected, policy, public, raw = _render()
    digest = _hash_bytes(raw)
    common = dict(
        raw=raw, expected=expected, full_short_policy=policy,
        full_short_public_bindings=public,
        verification_keys={"campaign-key-v1": KEY},
    )
    with pytest.raises(FullShortCampaignAuthorizationError, match="REUSE_FORBIDDEN"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            **common, consumed_authorization_sha256s={digest},
        )
    with pytest.raises(FullShortCampaignAuthorizationError, match="KEY_IDENTITY_DRIFT"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            **{**common, "verification_keys": {"campaign-key-v1": b"x" * 32}},
        )
    usage = {
        "provider_requests": 145, "http_post_attempts": 0,
        "network_requests": 0, "model_calls": 0, "paid_calls": 0,
        "input_tokens": 0, "generated_output_tokens": 0,
        "real_full_short_executions": 0,
    }
    with pytest.raises(FullShortCampaignAuthorizationError, match="PROVIDER_REQUESTS_CAP"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            **common, actual_usage=usage,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("budgets", "plan_derived_max_input_tokens"), 4_000_001),
        (("scope", "maximum_real_full_short_executions"), 2),
        (("scope", "long_execution_allowed"), True),
        (("scope", "route_change_allowed"), True),
        (("scope", "model_change_allowed"), True),
        (("scope", "baseline_skill_change_allowed"), True),
        (("scope", "hybrid_production_cutover"), True),
        (("scope", "selective_production_cutover"), True),
        ((None, "execution_authorized"), False),
        ((None, "named_approver"), "somebody-else"),
        ((None, "usage_status"), "used"),
    ],
)
def test_closed_world_caps_cutovers_approval_and_usage_cannot_drift(path, value) -> None:
    expected, policy, public, _raw = _render()
    changed = copy.deepcopy(expected)
    if path[0] is None:
        changed[path[1]] = value
    else:
        changed[path[0]][path[1]] = value
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
            canonical_json_bytes(changed), expected=expected,
            full_short_policy=policy, full_short_public_bindings=public,
            verification_keys={"campaign-key-v1": KEY},
        )
