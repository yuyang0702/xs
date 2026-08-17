"""Versioned approval contracts for planning_repair_observation_1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_CANDIDATE_SCHEMA,
    PLANNING_REPAIR_OBSERVATION_PATCH_SCHEMA,
    PLANNING_REPAIR_OBSERVATION_PATCH_TEMPLATE_SCHEMA,
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
    PLANNING_REPAIR_OBSERVATION_SIGNED_SCHEMA,
    approval_profile,
)
from .contracts import CanaryContractError, _require, _require_hash


CANDIDATE_DOMAIN = "novel-flywheel-planning-repair-observation-candidate-v1"
TEMPLATE_DOMAIN = "novel-flywheel-planning-repair-observation-template-v1"
PATCH_DOMAIN = "novel-flywheel-planning-repair-observation-patch-v1"
SIGNED_DOMAIN = "novel-flywheel-planning-repair-observation-signed-v1"

AUTHORIZATION_FIELDS = (
    "authorize_credential_lookup", "authorize_provider_client_creation",
    "authorize_network", "authorize_paid_model_calls",
)

CANDIDATE_FIELDS = {
    "schema", "version", "canonicalization_version", "profile_id",
    "profile_definition_sha256", "status", "approval_scope",
    "approved_plan_sha256", "approved_launcher_sha256",
    "approved_workload_sha256", "approved_workload_manifest_hash",
    "approved_workload_id", "approved_build_fingerprint",
    "approved_execution_config_fingerprint",
    "approved_runtime_execution_fingerprint", "runtime_mode",
    "provider_descriptor_hash", "model_role_binding_manifest_hash",
    "pricing_evidence_manifest_hash", "feature_flag_snapshot_hash",
    "prompt_policy_manifest_sha256", "target_filter_sha256",
    "instrumentation_definition_bundle_sha256",
    "observation_goal_definition_sha256",
    "domain_validator_policy_sha256",
    "production_repair_budget_policy_sha256",
    "call_budget_definition_sha256", "token_budget_definition_sha256",
    "monetary_budget_definition_sha256",
    "elapsed_budget_definition_sha256", "budget_definition_sha256",
    "stop_condition_manifest_hash", "canary_root_identity_candidate",
    "approval_ledger_identity", "single_use_cohort_id",
    "maximum_executions", "usage_status", "consumed_evidence_sha256",
    "materialized_at", "execution_window", "approval_expiry",
    "named_approver", *AUTHORIZATION_FIELDS, "authorized_actions",
    "execution_authorized", "phase1b_enabled", "maximum_runs",
    "expected_model_calls", "maximum_model_calls_per_run",
    "maximum_total_model_calls", "maximum_input_tokens",
    "maximum_output_tokens", "maximum_output_tokens_per_call",
    "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
    "maximum_elapsed_seconds", "first_terminal_stop",
    "resume_after_terminal", "second_run_allowed",
    "signed_approval_materialized", "execution_performed",
    "approved_budget", "approval_candidate_sha256",
}

TEMPLATE_FIELDS = {
    "schema", "version", "canonicalization_version", "profile_id",
    "profile_definition_sha256", "template_status", "approval_scope",
    "bound_plan_sha256", "bound_approval_candidate_sha256",
    "bound_launcher_sha256", "bound_workload_sha256",
    "bound_build_fingerprint", "bound_execution_config_fingerprint",
    "bound_runtime_execution_fingerprint", "bound_target_filter_sha256",
    "bound_instrumentation_definition_bundle_sha256",
    "bound_observation_goal_definition_sha256", "single_use_cohort_id",
    "approved_execution_window_confirmation", "approval_expiry_confirmation",
    "single_use_cohort_confirmation", "named_approver",
    "approval_timestamp", "requested_authorizations",
    "execution_authorized", "protected_fields_mutation_allowed",
    "signed_approval_materialization_allowed",
    "authorization_patch_template_sha256",
}

PATCH_FIELDS = (
    TEMPLATE_FIELDS.difference({
        "template_status", "requested_authorizations",
        "signed_approval_materialization_allowed",
        "authorization_patch_template_sha256",
    })
    | set(AUTHORIZATION_FIELDS)
    | {"source_template_sha256", "authorization_patch_sha256"}
)

SIGNED_FIELDS = (
    CANDIDATE_FIELDS.difference({
        "approval_candidate_sha256", "status",
        "signed_approval_materialized", "execution_performed",
    })
    | {
        "source_candidate_sha256", "source_authorization_patch_sha256",
        "approval_timestamp", "approval_method", "signed_approval_sha256",
    }
)


def _without_digest(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    body = deepcopy(dict(value))
    body.pop(field, None)
    return body


def _sealed(
    domain: str, value: Mapping[str, Any], digest_field: str,
) -> dict[str, Any]:
    body = deepcopy(dict(value))
    body[digest_field] = domain_sha256(domain, body)
    return body


def _parse_utc(value: Any, reason: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), reason)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(
            timezone.utc
        )
    except ValueError as exc:
        raise CanaryContractError(reason) from exc


def _window(value: Mapping[str, Any]) -> tuple[datetime, datetime]:
    window = value.get("execution_window") or value.get(
        "approved_execution_window_confirmation"
    )
    expiry = value.get("approval_expiry") or value.get(
        "approval_expiry_confirmation"
    )
    _require(
        isinstance(window, Mapping)
        and set(window) == {"not_before", "not_after"},
        "approval_execution_window_invalid",
    )
    start = _parse_utc(window["not_before"], "approval_execution_window_invalid")
    end = _parse_utc(window["not_after"], "approval_execution_window_invalid")
    _require(
        start <= end == _parse_utc(expiry, "approval_expiry_invalid"),
        "approval_execution_window_invalid",
    )
    return start, end


def _profile(value: Mapping[str, Any]) -> None:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    _require(value.get("profile_id") == profile.profile_id,
             "approval_profile_unknown")
    _require(
        value.get("profile_definition_sha256")
        == profile.profile_definition_sha256,
        "approval_profile_hash_mismatch",
    )
    _require(value.get("approval_scope") == profile.approval_scope,
             "approval_profile_scope_mismatch")


def _hash_fields(value: Mapping[str, Any], names: set[str]) -> None:
    for name in names:
        _require_hash(value.get(name), f"{name}_invalid")


def build_planning_repair_observation_candidate_v1(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    value = _sealed(CANDIDATE_DOMAIN, {
        "schema": profile.candidate_schema,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profile_id": profile.profile_id,
        "profile_definition_sha256": profile.profile_definition_sha256,
        **deepcopy(dict(payload)),
    }, "approval_candidate_sha256")
    return validate_planning_repair_observation_candidate_v1(value)


def validate_planning_repair_observation_candidate_v1(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None,
    now: datetime | None = None, enforce_time: bool = False,
) -> dict[str, Any]:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    _require(isinstance(value, Mapping), "approval_candidate_not_object")
    _require(set(value) == CANDIDATE_FIELDS,
             "approval_candidate_fields_unexpected")
    _require(
        value["schema"] == profile.candidate_schema and value["version"] == 1,
        "approval_schema_mismatch",
    )
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "approval_candidate_canonicalization_unsupported")
    _profile(value)
    _hash_fields(value, {
        name for name in CANDIDATE_FIELDS
        if name.endswith(("sha256", "_hash", "_fingerprint"))
    }.difference({"consumed_evidence_sha256"}))
    _require(value["status"] == "waiting_for_final_user_authorization",
             "approval_candidate_status_invalid")
    _require(value["named_approver"] == "USER_CONFIRMATION_REQUIRED",
             "approval_candidate_named_approver_invalid")
    _require(value["usage_status"] == "unused"
             and value["maximum_executions"] == 1
             and value["consumed_evidence_sha256"] is None,
             "approval_candidate_usage_invalid")
    _require(all(value[name] is False for name in (
        *AUTHORIZATION_FIELDS, "execution_authorized", "phase1b_enabled",
        "resume_after_terminal", "second_run_allowed",
        "signed_approval_materialized", "execution_performed",
    )), "approval_candidate_external_authorization_present")
    actions = value["authorized_actions"]
    _require(
        isinstance(actions, Mapping)
        and set(actions) == {
            "credential_lookup", "provider_client_creation", "network",
            "paid_model_calls", "fake_boundary",
        }
        and all(item is False for item in actions.values()),
        "approval_candidate_external_authorization_present",
    )
    _require(all(value.get(name) == expected
                 for name, expected in profile.budget().items()),
             "approval_candidate_budget_invalid")
    _require(value["first_terminal_stop"] is True,
             "approval_candidate_stop_policy_invalid")
    _require(value["approved_workload_id"] in profile.allowed_workload_ids,
             "approval_candidate_workload_invalid")
    start, end = _window(value)
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "approval_candidate_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "approval_candidate_launcher_mismatch")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(current <= end, "approval_expired")
    _require(value["approval_candidate_sha256"] == domain_sha256(
        CANDIDATE_DOMAIN, _without_digest(value, "approval_candidate_sha256")
    ), "approval_candidate_hash_mismatch")
    del start
    return deepcopy(dict(value))


def build_planning_repair_observation_patch_template_v1(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    source = validate_planning_repair_observation_candidate_v1(candidate)
    body = {
        "schema": PLANNING_REPAIR_OBSERVATION_PATCH_TEMPLATE_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profile_id": source["profile_id"],
        "profile_definition_sha256": source["profile_definition_sha256"],
        "template_status": "not_authorization_user_confirmation_required",
        "approval_scope": source["approval_scope"],
        "bound_plan_sha256": source["approved_plan_sha256"],
        "bound_approval_candidate_sha256": source["approval_candidate_sha256"],
        "bound_launcher_sha256": source["approved_launcher_sha256"],
        "bound_workload_sha256": source["approved_workload_sha256"],
        "bound_build_fingerprint": source["approved_build_fingerprint"],
        "bound_execution_config_fingerprint": source[
            "approved_execution_config_fingerprint"
        ],
        "bound_runtime_execution_fingerprint": source[
            "approved_runtime_execution_fingerprint"
        ],
        "bound_target_filter_sha256": source["target_filter_sha256"],
        "bound_instrumentation_definition_bundle_sha256": source[
            "instrumentation_definition_bundle_sha256"
        ],
        "bound_observation_goal_definition_sha256": source[
            "observation_goal_definition_sha256"
        ],
        "single_use_cohort_id": source["single_use_cohort_id"],
        "approved_execution_window_confirmation": source["execution_window"],
        "approval_expiry_confirmation": source["approval_expiry"],
        "single_use_cohort_confirmation": source["single_use_cohort_id"],
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
        "signed_approval_materialization_allowed": False,
    }
    return validate_planning_repair_observation_patch_template_v1(
        _sealed(TEMPLATE_DOMAIN, body, "authorization_patch_template_sha256")
    )


def validate_planning_repair_observation_patch_template_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "authorization_patch_not_object")
    _require(set(value) == TEMPLATE_FIELDS,
             "authorization_patch_template_fields_unexpected")
    _require(
        value["schema"] == PLANNING_REPAIR_OBSERVATION_PATCH_TEMPLATE_SCHEMA
        and value["version"] == 1,
        "approval_schema_mismatch",
    )
    _profile(value)
    _require(value["template_status"]
             == "not_authorization_user_confirmation_required",
             "authorization_patch_template_status_invalid")
    _require(value["named_approver"] == "USER_CONFIRMATION_REQUIRED"
             and value["approval_timestamp"] == "USER_CONFIRMATION_REQUIRED",
             "authorization_patch_template_authority_present")
    _require(value["execution_authorized"] is False
             and value["protected_fields_mutation_allowed"] is False
             and value["signed_approval_materialization_allowed"] is False,
             "authorization_patch_not_executable")
    _hash_fields(value, {
        name for name in TEMPLATE_FIELDS
        if name.endswith(("sha256", "_fingerprint"))
    })
    _require(value["authorization_patch_template_sha256"] == domain_sha256(
        TEMPLATE_DOMAIN,
        _without_digest(value, "authorization_patch_template_sha256"),
    ), "authorization_patch_hash_mismatch")
    return deepcopy(dict(value))


def materialize_planning_repair_observation_patch_v1(
    template: Mapping[str, Any], *, named_approver: str,
    approval_timestamp: str,
) -> dict[str, Any]:
    source = validate_planning_repair_observation_patch_template_v1(template)
    body = {
        key: deepcopy(item) for key, item in source.items()
        if key not in {
            "schema", "template_status", "requested_authorizations",
            "signed_approval_materialization_allowed",
            "authorization_patch_template_sha256", "named_approver",
            "approval_timestamp",
        }
    }
    body.update({
        "schema": PLANNING_REPAIR_OBSERVATION_PATCH_SCHEMA,
        "named_approver": named_approver,
        "approval_timestamp": approval_timestamp,
        **{name: True for name in AUTHORIZATION_FIELDS},
        "execution_authorized": True,
        "source_template_sha256": source[
            "authorization_patch_template_sha256"
        ],
    })
    return validate_planning_repair_observation_patch_v1(
        _sealed(PATCH_DOMAIN, body, "authorization_patch_sha256")
    )


def validate_planning_repair_observation_patch_v1(
    value: Mapping[str, Any], *, now: datetime | None = None,
    enforce_time: bool = False,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "authorization_patch_not_object")
    _require(set(value) == PATCH_FIELDS, "authorization_patch_fields_unexpected")
    _require(value["schema"] == PLANNING_REPAIR_OBSERVATION_PATCH_SCHEMA,
             "approval_schema_mismatch")
    _profile(value)
    _hash_fields(value, {
        name for name in PATCH_FIELDS
        if name.endswith(("sha256", "_fingerprint"))
    })
    _require(isinstance(value["named_approver"], str)
             and value["named_approver"].strip()
             and value["named_approver"] != "USER_CONFIRMATION_REQUIRED",
             "signed_approval_named_approver_invalid")
    start, end = _window(value)
    approval_time = _parse_utc(
        value["approval_timestamp"], "approval_timestamp_invalid"
    )
    _require(start <= approval_time <= end,
             "approval_timestamp_outside_execution_window")
    _require(value["single_use_cohort_confirmation"]
             == value["single_use_cohort_id"],
             "signed_approval_source_binding_mismatch")
    _require(all(value[name] is True for name in (
        *AUTHORIZATION_FIELDS, "execution_authorized",
    )), "signed_approval_authorization_missing")
    _require(value["protected_fields_mutation_allowed"] is False,
             "authorization_patch_protected_mutation_forbidden")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(start <= current <= end, "approval_outside_execution_window")
    _require(value["authorization_patch_sha256"] == domain_sha256(
        PATCH_DOMAIN, _without_digest(value, "authorization_patch_sha256")
    ), "authorization_patch_hash_mismatch")
    return deepcopy(dict(value))


def materialize_planning_repair_observation_signed_approval_v1(
    candidate: Mapping[str, Any], patch: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    source = validate_planning_repair_observation_candidate_v1(candidate)
    authorization = validate_planning_repair_observation_patch_v1(
        patch, now=now, enforce_time=True,
    )
    bindings = {
        "profile_id": "profile_id",
        "profile_definition_sha256": "profile_definition_sha256",
        "approval_scope": "approval_scope",
        "bound_plan_sha256": "approved_plan_sha256",
        "bound_approval_candidate_sha256": "approval_candidate_sha256",
        "bound_launcher_sha256": "approved_launcher_sha256",
        "bound_workload_sha256": "approved_workload_sha256",
        "bound_build_fingerprint": "approved_build_fingerprint",
        "bound_execution_config_fingerprint": (
            "approved_execution_config_fingerprint"
        ),
        "bound_runtime_execution_fingerprint": (
            "approved_runtime_execution_fingerprint"
        ),
        "bound_target_filter_sha256": "target_filter_sha256",
        "bound_instrumentation_definition_bundle_sha256": (
            "instrumentation_definition_bundle_sha256"
        ),
        "bound_observation_goal_definition_sha256": (
            "observation_goal_definition_sha256"
        ),
        "single_use_cohort_id": "single_use_cohort_id",
        "single_use_cohort_confirmation": "single_use_cohort_id",
    }
    _require(all(authorization[left] == source[right]
                 for left, right in bindings.items()),
             "signed_approval_source_binding_mismatch")
    body = {
        key: deepcopy(item) for key, item in source.items()
        if key not in {
            "approval_candidate_sha256", "status",
            "signed_approval_materialized", "execution_performed",
        }
    }
    body.update({
        "schema": PLANNING_REPAIR_OBSERVATION_SIGNED_SCHEMA,
        "source_candidate_sha256": source["approval_candidate_sha256"],
        "source_authorization_patch_sha256": authorization[
            "authorization_patch_sha256"
        ],
        "named_approver": authorization["named_approver"],
        "approval_timestamp": authorization["approval_timestamp"],
        "approval_method": "manual_user_confirmation",
        **{name: True for name in AUTHORIZATION_FIELDS},
        "authorized_actions": {
            "credential_lookup": True, "provider_client_creation": True,
            "network": True, "paid_model_calls": True,
            "fake_boundary": False,
        },
        "execution_authorized": True,
    })
    return validate_planning_repair_observation_signed_approval_v1(
        _sealed(SIGNED_DOMAIN, body, "signed_approval_sha256"), now=now,
    )


def validate_planning_repair_observation_signed_approval_v1(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None,
    now: datetime | None = None, enforce_time: bool = True,
) -> dict[str, Any]:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    _require(isinstance(value, Mapping), "signed_approval_not_object")
    _require(set(value) == SIGNED_FIELDS, "signed_approval_fields_unexpected")
    _require(value["schema"] == profile.signed_approval_schema,
             "approval_schema_mismatch")
    _profile(value)
    _hash_fields(value, {
        name for name in SIGNED_FIELDS
        if name.endswith(("sha256", "_hash", "_fingerprint"))
    }.difference({"consumed_evidence_sha256"}))
    _require(value["usage_status"] == "unused"
             and value["maximum_executions"] == 1
             and value["consumed_evidence_sha256"] is None,
             "signed_approval_not_unused")
    _require(value["approval_method"] == "manual_user_confirmation",
             "signed_approval_method_invalid")
    start, end = _window(value)
    approval_time = _parse_utc(
        value["approval_timestamp"], "approval_timestamp_invalid"
    )
    _require(start <= approval_time <= end,
             "approval_timestamp_outside_execution_window")
    _require(all(value[name] is True for name in (
        *AUTHORIZATION_FIELDS, "execution_authorized",
    )), "signed_approval_authorization_missing")
    _require(all(value.get(name) == expected
                 for name, expected in profile.budget().items()),
             "signed_approval_budget_invalid")
    _require(value["phase1b_enabled"] is False
             and value["resume_after_terminal"] is False
             and value["second_run_allowed"] is False,
             "signed_approval_behavior_policy_invalid")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "signed_approval_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "signed_approval_launcher_mismatch")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(start <= current <= end, "approval_outside_execution_window")
    _require(value["signed_approval_sha256"] == domain_sha256(
        SIGNED_DOMAIN, _without_digest(value, "signed_approval_sha256")
    ), "signed_approval_hash_mismatch")
    return deepcopy(dict(value))


def validate_planning_repair_observation_signed_sources_v1(
    signed: Mapping[str, Any], candidate: Mapping[str, Any],
    patch: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    value = validate_planning_repair_observation_signed_approval_v1(
        signed, now=now,
    )
    expected = materialize_planning_repair_observation_signed_approval_v1(
        candidate, patch, now=now,
    )
    _require(value == expected, "signed_approval_protected_fields_mismatch")
    return value


def validate_planning_repair_observation_signed_plan_v1(
    signed: Mapping[str, Any], plan: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    from .contracts import validate_canary_experiment_plan_v1

    source_plan = validate_canary_experiment_plan_v1(plan)
    value = validate_planning_repair_observation_signed_approval_v1(
        signed,
        expected_plan_sha256=source_plan["plan_sha256"],
        expected_launcher_sha256=source_plan["launcher_sha256"],
        now=now,
    )
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    policy = source_plan.get("planning_repair_observation_policy")
    _require(source_plan["canary_mode"] == profile.canary_mode
             and isinstance(policy, Mapping),
             "approval_profile_scope_mismatch")
    expected = {
        "profile_id": profile.profile_id,
        "profile_definition_sha256": profile.profile_definition_sha256,
        "approval_scope": profile.approval_scope,
        "approved_workload_sha256": source_plan["workloads"][0][
            "fixture_sha256"
        ],
        "approved_workload_manifest_hash": source_plan["workload_manifest_hash"],
        "approved_workload_id": source_plan["workloads"][0]["workload_id"],
        "approved_build_fingerprint": source_plan["approved_build_fingerprint"],
        "approved_execution_config_fingerprint": source_plan[
            "approved_execution_config_fingerprint"
        ],
        "approved_runtime_execution_fingerprint": source_plan[
            "expected_runtime_execution_fingerprint"
        ],
        "provider_descriptor_hash": source_plan[
            "provider_descriptor_definition_sha256"
        ],
        "model_role_binding_manifest_hash": source_plan[
            "role_binding_manifest_definition_sha256"
        ],
        "target_filter_sha256": policy["target_filter_sha256"],
        "instrumentation_definition_bundle_sha256": policy[
            "instrumentation_definition_bundle_sha256"
        ],
        "observation_goal_definition_sha256": policy[
            "observation_goal_definition_sha256"
        ],
    }
    _require(all(value.get(name) == item for name, item in expected.items()),
             "signed_approval_plan_binding_mismatch")
    _require(source_plan["feature_flag_snapshot"] == profile.required_flags(),
             "execution_feature_flags_changed")
    _require(tuple(source_plan["stop_conditions"])
             == profile.stop_condition_policy,
             "stop_condition_manifest_mismatch")
    return value

