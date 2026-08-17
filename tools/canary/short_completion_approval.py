"""Strict Candidate/Patch/Signed contracts for short_completion_1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_profiles import (
    SHORT_COMPLETION_CANDIDATE_SCHEMA,
    SHORT_COMPLETION_PATCH_SCHEMA,
    SHORT_COMPLETION_PATCH_TEMPLATE_SCHEMA,
    SHORT_COMPLETION_PROFILE_ID,
    SHORT_COMPLETION_SIGNED_SCHEMA,
    approval_profile,
)
from .contracts import CanaryContractError
from .short_completion import completion_contract_bundle_v1


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_DOMAIN = "novel-flywheel-short-completion-candidate-v1"
_TEMPLATE_DOMAIN = "novel-flywheel-short-completion-patch-template-v1"
_PATCH_DOMAIN = "novel-flywheel-short-completion-patch-v1"
_SIGNED_DOMAIN = "novel-flywheel-short-completion-signed-approval-v1"

_BOUND_HASH_FIELDS = {
    "approved_plan_sha256", "approved_launcher_sha256",
    "approved_workload_sha256", "approved_workload_manifest_hash",
    "approved_build_fingerprint", "approved_execution_config_fingerprint",
    "approved_runtime_execution_fingerprint", "provider_descriptor_hash",
    "model_role_binding_manifest_hash", "pricing_evidence_manifest_hash",
    "feature_flag_snapshot_hash", "call_budget_definition_sha256",
    "token_budget_definition_sha256", "monetary_budget_definition_sha256",
    "elapsed_budget_definition_sha256", "stop_condition_manifest_hash",
    "prompt_policy_manifest_sha256", "canary_root_identity",
    "draft_validator_policy_sha256", "mixed_script_policy_sha256",
    "final_review_definition_sha256", "maintenance_definition_sha256",
    "final_artifact_policy_sha256", "final_checkpoint_policy_sha256",
    "completion_goal_definition_sha256",
}
_R1_D3_BOUND_HASH_FIELD = "r1_d3_production_mirror_readiness_sha256"
_PTR3_BOUND_HASH_FIELD = "ptr3_readiness_sha256"
_R1_D3_CONTROL_FIELD = "execution_collection_profile_id"
_CONTROL_FIELDS = {
    "approved_workload_id", "runtime_mode", "maximum_runs",
    "expected_model_calls", "maximum_total_model_calls",
    "maximum_input_tokens", "maximum_output_tokens",
    "maximum_output_tokens_per_call", "maximum_usd_cost_microunits",
    "maximum_cny_cost_microunits", "maximum_elapsed_seconds",
    "first_terminal_stop", "resume_after_terminal", "second_run_allowed",
    "phase1b_enabled", "execution_window", "approval_expiry",
    "single_use_cohort_id", "maximum_executions", "usage_status",
    "consumed_evidence_sha256", "named_approver", "authorized_actions",
    "execution_authorized",
}
_CANDIDATE_FIELDS = {
    "schema", "version", "canonicalization_version", "profile_id",
    "profile_definition_sha256", "approval_scope", *_BOUND_HASH_FIELDS,
    *_CONTROL_FIELDS, "status", "approval_candidate_sha256",
}
_R1_D3_CANDIDATE_FIELDS = _CANDIDATE_FIELDS | {
    _R1_D3_BOUND_HASH_FIELD, _PTR3_BOUND_HASH_FIELD, _R1_D3_CONTROL_FIELD,
}
_PATCH_BOUND_FIELDS = {
    "bound_plan_sha256", "bound_approval_candidate_sha256",
    "bound_launcher_sha256", "bound_workload_sha256",
    "bound_build_fingerprint", "bound_execution_config_fingerprint",
    "bound_runtime_execution_fingerprint", "single_use_cohort_id",
}
_TEMPLATE_FIELDS = {
    "schema", "version", "canonicalization_version", "profile_id",
    "profile_definition_sha256", "approval_scope", *_PATCH_BOUND_FIELDS,
    "execution_window_confirmation", "approval_expiry_confirmation",
    "cohort_confirmation", "named_approver", "approval_timestamp",
    "requested_authorizations", "execution_authorized",
    "protected_fields_mutation_allowed", "template_status",
    "authorization_patch_template_sha256",
}
_PATCH_FIELDS = _TEMPLATE_FIELDS.difference({
    "template_status", "requested_authorizations",
    "authorization_patch_template_sha256",
}) | {
    "authorize_credential_lookup", "authorize_provider_client_creation",
    "authorize_network", "authorize_paid_model_calls",
    "source_template_sha256", "authorization_patch_sha256",
}
_SIGNED_FIELDS = _CANDIDATE_FIELDS.difference({
    "schema", "version", "status", "approval_candidate_sha256",
}) | {
    "schema", "version", "source_candidate_sha256",
    "source_authorization_patch_sha256", "approval_timestamp",
    "signed_approval_sha256",
}
_R1_D3_SIGNED_FIELDS = _SIGNED_FIELDS | {
    _R1_D3_BOUND_HASH_FIELD, _PTR3_BOUND_HASH_FIELD, _R1_D3_CONTROL_FIELD,
}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CanaryContractError(reason)


def _sealed(domain: str, value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result[field] = domain_sha256(domain, result)
    return result


def _check_seal(domain: str, value: Mapping[str, Any], field: str) -> None:
    body = deepcopy(dict(value))
    digest = body.pop(field, None)
    _require(digest == domain_sha256(domain, body), f"{field}_mismatch")


def _parse_utc(value: Any) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), "approval_time_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise CanaryContractError("approval_time_invalid") from exc


def _validate_profile(value: Mapping[str, Any]) -> None:
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    _require(value.get("profile_id") == profile.profile_id,
             "approval_profile_unknown")
    _require(value.get("profile_definition_sha256") ==
             profile.profile_definition_sha256,
             "approval_profile_hash_mismatch")
    _require(value.get("approval_scope") == profile.approval_scope,
             "approval_profile_scope_mismatch")


def _validate_policy_bindings(value: Mapping[str, Any]) -> None:
    definitions = completion_contract_bundle_v1()
    expected = {
        "stop_condition_manifest_hash": definitions["stop_conditions"]["definition_sha256"],
        "draft_validator_policy_sha256": definitions["draft_validator_policy"]["definition_sha256"],
        "mixed_script_policy_sha256": definitions["mixed_script_policy"]["definition_sha256"],
        "final_review_definition_sha256": definitions["final_review"]["definition_sha256"],
        "maintenance_definition_sha256": definitions["maintenance"]["definition_sha256"],
        "final_artifact_policy_sha256": definitions["final_artifact"]["definition_sha256"],
        "final_checkpoint_policy_sha256": definitions["final_checkpoint"]["definition_sha256"],
        "completion_goal_definition_sha256": definitions["completion_goal"]["definition_sha256"],
    }
    for field, digest in expected.items():
        _require(value.get(field) == digest, f"{field}_mismatch")


def build_short_completion_candidate_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    value = _sealed(_CANDIDATE_DOMAIN, {
        "schema": SHORT_COMPLETION_CANDIDATE_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profile_id": profile.profile_id,
        "profile_definition_sha256": profile.profile_definition_sha256,
        **deepcopy(dict(payload)),
    }, "approval_candidate_sha256")
    return validate_short_completion_candidate_v1(value)


def validate_short_completion_candidate_v1(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None, now: datetime | None = None,
    enforce_time: bool = False,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and frozenset(value) in {
                 frozenset(_CANDIDATE_FIELDS),
                 frozenset(_R1_D3_CANDIDATE_FIELDS),
             },
             "approval_candidate_fields_unexpected")
    _require(value["schema"] == SHORT_COMPLETION_CANDIDATE_SCHEMA and
             value["version"] == 1, "approval_schema_mismatch")
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "approval_candidate_canonicalization_unsupported")
    _validate_profile(value)
    for field in _BOUND_HASH_FIELDS | {"profile_definition_sha256"}:
        _require(isinstance(value.get(field), str) and
                 _HEX64.fullmatch(str(value[field])) is not None,
                 f"{field}_invalid")
    if _R1_D3_BOUND_HASH_FIELD in value:
        from .fingerprint_profiles import PRODUCTION_MIRROR_SHORT_PROFILE_ID

        _require(
            isinstance(value.get(_R1_D3_BOUND_HASH_FIELD), str)
            and _HEX64.fullmatch(str(value[_R1_D3_BOUND_HASH_FIELD])) is not None,
            f"{_R1_D3_BOUND_HASH_FIELD}_invalid",
        )
        _require(
            value.get(_R1_D3_CONTROL_FIELD) == PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "target_execution_collection_profile_mismatch",
        )
        _require(
            isinstance(value.get(_PTR3_BOUND_HASH_FIELD), str)
            and _HEX64.fullmatch(str(value[_PTR3_BOUND_HASH_FIELD])) is not None,
            f"{_PTR3_BOUND_HASH_FIELD}_invalid",
        )
    _validate_policy_bindings(value)
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    for field, expected in profile.budget().items():
        if field in value:
            _require(value[field] == expected, "approval_candidate_budget_invalid")
    _require(value["approved_workload_id"] in profile.allowed_workload_ids,
             "approval_candidate_workload_invalid")
    _require(value["runtime_mode"] == "git_workspace", "runtime_mode_invalid")
    _require(value["first_terminal_stop"] is True and
             value["resume_after_terminal"] is False and
             value["second_run_allowed"] is False,
             "approval_candidate_stop_policy_invalid")
    _require(value["phase1b_enabled"] is False, "phase1b_enabled")
    _require(value["maximum_executions"] == 1 and
             value["usage_status"] == "unused" and
             value["consumed_evidence_sha256"] is None,
             "approval_candidate_usage_invalid")
    _require(value["named_approver"] == "USER_CONFIRMATION_REQUIRED" and
             value["execution_authorized"] is False and
             value["status"] == "waiting_for_final_user_authorization",
             "approval_candidate_external_authorization_present")
    actions = value["authorized_actions"]
    _require(isinstance(actions, Mapping) and set(actions) == {
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls", "fake_boundary",
    } and all(item is False for item in actions.values()),
             "approval_candidate_external_authorization_present")
    window = value["execution_window"]
    _require(isinstance(window, Mapping) and set(window) == {"not_before", "not_after"},
             "approval_execution_window_invalid")
    start, end, expiry = (_parse_utc(window["not_before"]),
                          _parse_utc(window["not_after"]),
                          _parse_utc(value["approval_expiry"]))
    _require(start <= end == expiry, "approval_execution_window_invalid")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "approval_candidate_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "approval_candidate_launcher_mismatch")
    if enforce_time:
        _require((now or datetime.now(timezone.utc)) <= expiry, "approval_expired")
    _check_seal(_CANDIDATE_DOMAIN, value, "approval_candidate_sha256")
    return deepcopy(dict(value))


def build_short_completion_patch_template_v1(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    source = validate_short_completion_candidate_v1(candidate)
    value = _sealed(_TEMPLATE_DOMAIN, {
        "schema": SHORT_COMPLETION_PATCH_TEMPLATE_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profile_id": source["profile_id"],
        "profile_definition_sha256": source["profile_definition_sha256"],
        "approval_scope": source["approval_scope"],
        "bound_plan_sha256": source["approved_plan_sha256"],
        "bound_approval_candidate_sha256": source["approval_candidate_sha256"],
        "bound_launcher_sha256": source["approved_launcher_sha256"],
        "bound_workload_sha256": source["approved_workload_sha256"],
        "bound_build_fingerprint": source["approved_build_fingerprint"],
        "bound_execution_config_fingerprint": source["approved_execution_config_fingerprint"],
        "bound_runtime_execution_fingerprint": source["approved_runtime_execution_fingerprint"],
        "single_use_cohort_id": source["single_use_cohort_id"],
        "execution_window_confirmation": source["execution_window"],
        "approval_expiry_confirmation": source["approval_expiry"],
        "cohort_confirmation": source["single_use_cohort_id"],
        "named_approver": "USER_CONFIRMATION_REQUIRED",
        "approval_timestamp": "USER_CONFIRMATION_REQUIRED",
        "requested_authorizations": {
            "credential_lookup": "USER_CONFIRMATION_REQUIRED",
            "provider_client_creation": "USER_CONFIRMATION_REQUIRED",
            "network": "USER_CONFIRMATION_REQUIRED",
            "paid_model_calls": "USER_CONFIRMATION_REQUIRED",
        },
        "execution_authorized": False,
        "protected_fields_mutation_allowed": False,
        "template_status": "not_authorization_user_confirmation_required",
    }, "authorization_patch_template_sha256")
    return validate_short_completion_patch_template_v1(value)


def validate_short_completion_patch_template_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and set(value) == _TEMPLATE_FIELDS,
             "authorization_patch_template_fields_unexpected")
    _require(value["schema"] == SHORT_COMPLETION_PATCH_TEMPLATE_SCHEMA,
             "approval_schema_mismatch")
    _validate_profile(value)
    _require(value["template_status"] == "not_authorization_user_confirmation_required" and
             value["named_approver"] == "USER_CONFIRMATION_REQUIRED" and
             value["approval_timestamp"] == "USER_CONFIRMATION_REQUIRED" and
             value["execution_authorized"] is False and
             value["protected_fields_mutation_allowed"] is False,
             "authorization_patch_not_executable")
    _check_seal(_TEMPLATE_DOMAIN, value, "authorization_patch_template_sha256")
    return deepcopy(dict(value))


def materialize_short_completion_patch_v1(
    template: Mapping[str, Any], *, named_approver: str,
    approval_timestamp: str,
) -> dict[str, Any]:
    source = validate_short_completion_patch_template_v1(template)
    _require(named_approver not in {"", "USER_CONFIRMATION_REQUIRED"},
             "named_approver_invalid")
    _parse_utc(approval_timestamp)
    body = {key: deepcopy(value) for key, value in source.items() if key not in {
        "schema", "template_status", "requested_authorizations",
        "named_approver", "approval_timestamp", "execution_authorized",
        "authorization_patch_template_sha256",
    }}
    body.update({
        "schema": SHORT_COMPLETION_PATCH_SCHEMA,
        "named_approver": named_approver,
        "approval_timestamp": approval_timestamp,
        "authorize_credential_lookup": True,
        "authorize_provider_client_creation": True,
        "authorize_network": True,
        "authorize_paid_model_calls": True,
        "execution_authorized": True,
        "source_template_sha256": source["authorization_patch_template_sha256"],
    })
    value = _sealed(_PATCH_DOMAIN, body, "authorization_patch_sha256")
    return validate_short_completion_patch_v1(value)


def validate_short_completion_patch_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and set(value) == _PATCH_FIELDS,
             "authorization_patch_fields_unexpected")
    _require(value["schema"] == SHORT_COMPLETION_PATCH_SCHEMA,
             "approval_schema_mismatch")
    _validate_profile(value)
    _require(value["execution_authorized"] is True and
             value["protected_fields_mutation_allowed"] is False and
             all(value[name] is True for name in (
                 "authorize_credential_lookup", "authorize_provider_client_creation",
                 "authorize_network", "authorize_paid_model_calls",
             )), "authorization_patch_not_executable")
    _require(value["cohort_confirmation"] == value["single_use_cohort_id"],
             "authorization_patch_cohort_mismatch")
    _check_seal(_PATCH_DOMAIN, value, "authorization_patch_sha256")
    return deepcopy(dict(value))


def materialize_short_completion_signed_approval_v1(
    candidate: Mapping[str, Any], patch: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    source = validate_short_completion_candidate_v1(candidate)
    authorization = validate_short_completion_patch_v1(patch)
    pairs = {
        "bound_plan_sha256": "approved_plan_sha256",
        "bound_approval_candidate_sha256": "approval_candidate_sha256",
        "bound_launcher_sha256": "approved_launcher_sha256",
        "bound_workload_sha256": "approved_workload_sha256",
        "bound_build_fingerprint": "approved_build_fingerprint",
        "bound_execution_config_fingerprint": "approved_execution_config_fingerprint",
        "bound_runtime_execution_fingerprint": "approved_runtime_execution_fingerprint",
    }
    for patch_field, candidate_field in pairs.items():
        _require(authorization[patch_field] == source[candidate_field],
                 "authorization_patch_binding_mismatch")
    _require(authorization["single_use_cohort_id"] == source["single_use_cohort_id"] and
             authorization["execution_window_confirmation"] == source["execution_window"] and
             authorization["approval_expiry_confirmation"] == source["approval_expiry"],
             "authorization_patch_binding_mismatch")
    body = {key: deepcopy(value) for key, value in source.items() if key not in {
        "schema", "version", "status", "approval_candidate_sha256",
        "named_approver", "authorized_actions", "execution_authorized",
    }}
    body.update({
        "schema": SHORT_COMPLETION_SIGNED_SCHEMA,
        "version": 1,
        "named_approver": authorization["named_approver"],
        "authorized_actions": {
            "credential_lookup": True, "provider_client_creation": True,
            "network": True, "paid_model_calls": True, "fake_boundary": False,
        },
        "execution_authorized": True,
        "source_candidate_sha256": source["approval_candidate_sha256"],
        "source_authorization_patch_sha256": authorization["authorization_patch_sha256"],
        "approval_timestamp": authorization["approval_timestamp"],
    })
    value = _sealed(_SIGNED_DOMAIN, body, "signed_approval_sha256")
    return validate_short_completion_signed_approval_v1(value, now=now)


def validate_short_completion_signed_approval_v1(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None, now: datetime | None = None,
    enforce_time: bool = False,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and frozenset(value) in {
                 frozenset(_SIGNED_FIELDS), frozenset(_R1_D3_SIGNED_FIELDS),
             },
             "signed_approval_fields_unexpected")
    _require(value["schema"] == SHORT_COMPLETION_SIGNED_SCHEMA and
             value["version"] == 1, "approval_schema_mismatch")
    _validate_profile(value)
    _validate_policy_bindings(value)
    if _R1_D3_BOUND_HASH_FIELD in value:
        from .fingerprint_profiles import PRODUCTION_MIRROR_SHORT_PROFILE_ID

        _require(
            isinstance(value.get(_R1_D3_BOUND_HASH_FIELD), str)
            and _HEX64.fullmatch(str(value[_R1_D3_BOUND_HASH_FIELD])) is not None,
            f"{_R1_D3_BOUND_HASH_FIELD}_invalid",
        )
        _require(
            value.get(_R1_D3_CONTROL_FIELD) == PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "target_execution_collection_profile_mismatch",
        )
    _require(value["execution_authorized"] is True and
             value["phase1b_enabled"] is False,
             "signed_approval_not_executable")
    actions = value["authorized_actions"]
    _require(all(actions.get(name) is True for name in (
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls",
    )) and actions.get("fake_boundary") is False,
             "signed_approval_not_executable")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "signed_approval_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "signed_approval_launcher_mismatch")
    if enforce_time:
        current = now or datetime.now(timezone.utc)
        window = value["execution_window"]
        _require(_parse_utc(window["not_before"]) <= current <=
                 _parse_utc(window["not_after"]), "approval_outside_execution_window")
    _check_seal(_SIGNED_DOMAIN, value, "signed_approval_sha256")
    return deepcopy(dict(value))


def validate_short_completion_signed_sources_v1(
    signed: Mapping[str, Any], candidate: Mapping[str, Any],
    patch: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    expected = materialize_short_completion_signed_approval_v1(
        candidate, patch, now=now,
    )
    value = validate_short_completion_signed_approval_v1(signed, now=now)
    _require(value == expected, "signed_approval_source_binding_mismatch")
    return value


def validate_short_completion_signed_plan_v1(
    signed: Mapping[str, Any], plan: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    value = validate_short_completion_signed_approval_v1(signed, now=now)
    _require(value["approved_plan_sha256"] == plan.get("plan_sha256"),
             "signed_approval_plan_mismatch")
    policy = plan.get("short_completion_policy")
    _require(isinstance(policy, Mapping), "approval_profile_scope_mismatch")
    for field in (
        "stop_condition_manifest_hash", "draft_validator_policy_sha256",
        "mixed_script_policy_sha256", "final_review_definition_sha256",
        "maintenance_definition_sha256", "final_artifact_policy_sha256",
        "final_checkpoint_policy_sha256", "completion_goal_definition_sha256",
    ):
        _require(value[field] == policy.get(field), f"{field}_mismatch")
    readiness_hash = policy.get(_R1_D3_BOUND_HASH_FIELD)
    if readiness_hash is not None:
        _require(
            value.get(_R1_D3_BOUND_HASH_FIELD) == readiness_hash,
            "r1_d3_production_mirror_readiness_mismatch",
        )
        _require(
            value.get(_R1_D3_CONTROL_FIELD)
            == policy.get(_R1_D3_CONTROL_FIELD),
            "target_execution_collection_profile_mismatch",
        )
    else:
        _require(_R1_D3_BOUND_HASH_FIELD not in value,
                 "r1_d3_production_mirror_readiness_unapproved")
    return value
