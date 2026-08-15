"""Hash-bound contracts for the non-production controlled Canary launcher.

This module is deliberately orchestration-only.  It imports the existing
Runtime fingerprint canonicalization primitive and never resolves a provider,
credential, project, or model.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


PLAN_SCHEMA = "CanaryExperimentPlanV1"
APPROVAL_SCHEMA = "CanaryPlanApprovalV1"
SMOKE_APPROVAL_CANDIDATE_SCHEMA = "C0BSmoke1FinalApprovalCandidateV2"
SMOKE_AUTHORIZATION_PATCH_SCHEMA_V1 = "C0BSmoke1UserAuthorizationPatchV1"
SMOKE_AUTHORIZATION_PATCH_SCHEMA = "C0BSmoke1UserAuthorizationPatchV2"
SMOKE_SIGNED_APPROVAL_SCHEMA = "C0BSmoke1SignedApprovalV1"
SMOKE_APPROVAL_SCOPE = "C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1"
PLAN_DOMAIN = "novel-flywheel-canary-experiment-plan-v1"
APPROVAL_DOMAIN = "novel-flywheel-canary-plan-approval-v1"
SMOKE_APPROVAL_CANDIDATE_DOMAIN = "novel-flywheel-c0b-smoke-1-final-approval-candidate-v2"
SMOKE_AUTHORIZATION_PATCH_DOMAIN_V1 = "novel-flywheel-c0b-smoke-1-user-authorization-patch-v1"
SMOKE_AUTHORIZATION_PATCH_DOMAIN = "novel-flywheel-c0b-smoke-1-user-authorization-patch-v2"
SMOKE_SIGNED_APPROVAL_DOMAIN = "novel-flywheel-c0b-smoke-1-signed-approval-v1"
PLAN_MODES = frozenset({
    "c0a_fake_dry_run", "c0b_real_path_reachability",
    "c0c_statistical_exposure", "pa_strict_tool_observation",
})
RUNTIME_MODES = frozenset({"git_workspace", "packaged"})
APPROVAL_SCOPES = frozenset({
    "C0A_FAKE_DRY_RUN", "C0B_REAL_PROVIDER_PATH_REACHABILITY",
    "C0C_STATISTICAL_EXPOSURE",
})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_FORBIDDEN_EXACT_KEYS = frozenset({
    "api_key", "credential", "credentials", "secret", "secrets",
    "raw_environment", "raw_environment_values", "prompt", "prompts",
    "prose", "story_text", "novel_text", "absolute_path",
})


class CanaryContractError(ValueError):
    """Stable fail-closed contract validation error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise CanaryContractError(reason_code)


def _require_fields(value: Mapping[str, Any], fields: set[str], prefix: str) -> None:
    missing = sorted(fields.difference(value))
    _require(not missing, f"{prefix}_fields_missing")


def _require_hash(value: Any, reason_code: str) -> None:
    _require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, reason_code)


def _parse_utc(value: Any, reason_code: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), reason_code)
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CanaryContractError(reason_code) from exc
    _require(result.tzinfo is not None, reason_code)
    return result.astimezone(timezone.utc)


def _scan_forbidden_material(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            _require(isinstance(raw_key, str), "contract_key_not_string")
            key = raw_key.casefold()
            _require(key not in _FORBIDDEN_EXACT_KEYS, "forbidden_material_field")
            _scan_forbidden_material(child, f"{path}.{raw_key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_forbidden_material(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        _require(not _WINDOWS_ABSOLUTE.match(value), "absolute_path_forbidden")
        _require(not value.startswith(("\\\\", "file://", "/home/", "/Users/")),
                 "absolute_path_forbidden")


def _body_without_digest(value: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    body = deepcopy(dict(value))
    body.pop(digest_field, None)
    return body


def _plan_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(PLAN_DOMAIN, _body_without_digest(value, "plan_sha256"))


def _approval_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        APPROVAL_DOMAIN, _body_without_digest(value, "approval_sha256"),
    )


def _smoke_candidate_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        SMOKE_APPROVAL_CANDIDATE_DOMAIN,
        _body_without_digest(value, "approval_candidate_sha256"),
    )


def _smoke_patch_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        SMOKE_AUTHORIZATION_PATCH_DOMAIN,
        _body_without_digest(value, "authorization_patch_sha256"),
    )


def _smoke_patch_v1_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        SMOKE_AUTHORIZATION_PATCH_DOMAIN_V1,
        _body_without_digest(value, "authorization_patch_sha256"),
    )


def _smoke_signed_approval_digest(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        SMOKE_SIGNED_APPROVAL_DOMAIN,
        _body_without_digest(value, "signed_approval_sha256"),
    )


def build_canary_experiment_plan_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    plan = {
        "schema": PLAN_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    plan["plan_sha256"] = _plan_digest(plan)
    validate_canary_experiment_plan_v1(plan)
    return plan


def validate_canary_experiment_plan_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "plan_not_object")
    _require_fields(value, {
        "schema", "version", "canonicalization_version", "canary_mode",
        "runtime_mode", "approved_build_fingerprint",
        "approved_execution_config_fingerprint",
        "expected_runtime_execution_fingerprint",
        "runtime_fingerprint_policy_version", "launcher_sha256",
        "workload_manifest_hash", "workloads",
        "provider_descriptor_definition_sha256",
        "role_binding_manifest_definition_sha256", "approved_routes",
        "feature_flag_snapshot",
        "isolation", "budgets", "stop_conditions", "report_policy",
        "approved_dependency_manifest", "plan_sha256",
    }, "plan")
    _require(value["schema"] == PLAN_SCHEMA and value["version"] == 1,
             "plan_schema_unsupported")
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "plan_canonicalization_unsupported")
    _require(value["canary_mode"] in PLAN_MODES, "canary_mode_unsupported")
    _require(value["runtime_mode"] in RUNTIME_MODES, "runtime_mode_unsupported")
    for field in (
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "expected_runtime_execution_fingerprint", "launcher_sha256",
        "workload_manifest_hash", "provider_descriptor_definition_sha256",
        "role_binding_manifest_definition_sha256", "plan_sha256",
    ):
        _require_hash(value[field], f"{field}_invalid")
    routes = value["approved_routes"]
    _require(isinstance(routes, list) and routes, "approved_routes_invalid")
    seen_roles: set[str] = set()
    for route in routes:
        _require(isinstance(route, Mapping), "approved_route_invalid")
        _require_fields(route, {
            "role", "allowed_stages", "primary", "fallback",
        }, "approved_route")
        role = route["role"]
        _require(isinstance(role, str) and role and role not in seen_roles,
                 "approved_route_role_invalid")
        seen_roles.add(role)
        _require(isinstance(route["allowed_stages"], list)
                 and route["allowed_stages"]
                 and all(isinstance(stage, str) and stage
                         for stage in route["allowed_stages"]),
                 "approved_route_stages_invalid")
        for kind in ("primary", "fallback"):
            descriptor = route[kind]
            if descriptor is None:
                continue
            _require(isinstance(descriptor, Mapping),
                     f"approved_route_{kind}_invalid")
            _require_fields(descriptor, {
                "provider_descriptor_hash", "model_binding_hash", "protocol",
            }, f"approved_route_{kind}")
            _require_hash(descriptor["provider_descriptor_hash"],
                          f"approved_route_{kind}_provider_hash_invalid")
            _require_hash(descriptor["model_binding_hash"],
                          f"approved_route_{kind}_model_hash_invalid")
            _require(isinstance(descriptor["protocol"], str)
                     and descriptor["protocol"],
                     f"approved_route_{kind}_protocol_invalid")
    flags = value["feature_flag_snapshot"]
    _require(isinstance(flags, Mapping), "feature_flag_snapshot_invalid")
    _require(flags.get("NOVEL_SHORT_CANONICAL_V2") is False,
             "phase1b_environment_flag_enabled")
    _require(flags.get("project_short_canonical_v2") is False,
             "phase1b_project_flag_enabled")
    _require(isinstance(flags.get("NOVEL_RELIABILITY_TRACE"), bool),
             "trace_flag_invalid")
    _require(isinstance(flags.get("NOVEL_CANONICAL_SHADOW_V1"), bool),
             "shadow_flag_invalid")
    workloads = value["workloads"]
    _require(isinstance(workloads, list) and workloads, "workloads_invalid")
    for workload in workloads:
        _require(isinstance(workload, Mapping), "workload_invalid")
        _require_fields(workload, {
            "workload_id", "fixture_sha256", "weight",
            "prompt_policy_manifest_sha256", "expected_stage_reachability",
            "maximum_model_calls", "estimated_input_tokens",
            "maximum_output_tokens", "success_definition",
            "controlled_outcomes", "terminal_outcomes",
        }, "workload")
        _require_hash(workload["fixture_sha256"], "fixture_sha256_invalid")
        _require_hash(workload["prompt_policy_manifest_sha256"],
                      "prompt_policy_manifest_sha256_invalid")
        for field in ("weight", "maximum_model_calls", "estimated_input_tokens",
                      "maximum_output_tokens"):
            _require(type(workload[field]) is int and workload[field] >= 0,
                     f"workload_{field}_invalid")
    budgets = value["budgets"]
    _require(isinstance(budgets, Mapping), "budgets_invalid")
    _require_fields(budgets, {
        "maximum_runs", "maximum_model_calls_per_run",
        "maximum_total_model_calls", "maximum_input_tokens",
        "maximum_output_tokens", "pricing_status", "currency",
        "maximum_estimated_cost_microunits", "maximum_elapsed_seconds",
        "gate_wait_timeout_seconds",
    }, "budgets")
    for field in (
        "maximum_runs", "maximum_model_calls_per_run",
        "maximum_total_model_calls", "maximum_input_tokens",
        "maximum_output_tokens", "maximum_estimated_cost_microunits",
        "maximum_elapsed_seconds", "gate_wait_timeout_seconds",
    ):
        _require(type(budgets[field]) is int and budgets[field] >= 0,
                 f"budget_{field}_invalid")
    _require(budgets["maximum_total_model_calls"] >= budgets["maximum_model_calls_per_run"],
             "total_call_budget_below_per_run")
    if value["canary_mode"] in {
        "c0b_real_path_reachability", "pa_strict_tool_observation",
    }:
        _require_fields(budgets, {
            "monetary_budget", "price_catalog_sha256",
            "call_topology_sha256", "elapsed_budget_sha256",
            "worst_case_chargeable",
        }, "c0b_budget")
        monetary = budgets["monetary_budget"]
        _require(isinstance(monetary, Mapping), "monetary_budget_invalid")
        _require_fields(monetary, {
            "schema", "maximum_usd_cost_microunits",
            "maximum_cny_cost_microunits", "approved_fx_snapshot",
        }, "monetary_budget")
        _require(monetary["schema"] == "CanaryMonetaryBudgetV1",
                 "monetary_budget_schema_invalid")
        for field in (
            "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
        ):
            _require(type(monetary[field]) is int and monetary[field] >= 0,
                     f"{field}_invalid")
        _require(monetary["approved_fx_snapshot"] is None,
                 "unapproved_fx_snapshot")
        for field in (
            "price_catalog_sha256", "call_topology_sha256",
            "elapsed_budget_sha256",
        ):
            _require_hash(budgets[field], f"{field}_invalid")
        _require(budgets["worst_case_chargeable"] is True,
                 "failed_call_billing_not_conservative")
    _require(isinstance(value["stop_conditions"], list)
             and all(isinstance(item, str) and item for item in value["stop_conditions"]),
             "stop_conditions_invalid")
    _require(isinstance(value["approved_dependency_manifest"], Mapping),
             "dependency_manifest_invalid")
    if value["canary_mode"] == "pa_strict_tool_observation":
        from .approval_profiles import PA_PROFILE_ID, approval_profile

        profile = approval_profile(PA_PROFILE_ID)
        policy = value.get("pa_strict_tool_observation_policy")
        _require(isinstance(policy, Mapping), "approval_profile_scope_mismatch")
        _require(policy.get("profile_id") == profile.profile_id,
                 "approval_profile_scope_mismatch")
        _require(policy.get("approval_scope") == profile.approval_scope,
                 "approval_profile_scope_mismatch")
        _require(policy.get("profile_definition_sha256")
                 == profile.profile_definition_sha256,
                 "approval_profile_hash_mismatch")
        _require(value["feature_flag_snapshot"] == profile.required_flags(),
                 "execution_feature_flags_changed")
        _require(policy.get("target") == profile.target_filter(),
                 "target_filter_mismatch")
        _require(tuple(value["stop_conditions"])
                 == profile.stop_condition_policy,
                 "stop_condition_manifest_mismatch")
        _require(all(item.get("workload_id") in profile.allowed_workload_ids
                     for item in value["workloads"]),
                 "workload_not_allowed_by_profile")
        profile_budget = profile.budget()
        _require(all(
            value["budgets"].get(name) == expected
            for name, expected in profile_budget.items()
            if name in value["budgets"]
        ), "budget_profile_mismatch")
    _scan_forbidden_material(value)
    _require(value["plan_sha256"] == _plan_digest(value), "plan_hash_mismatch")
    return deepcopy(dict(value))


def build_canary_plan_approval_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    approval = {
        "schema": APPROVAL_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    approval["approval_sha256"] = _approval_digest(approval)
    validate_canary_plan_approval_v1(approval, enforce_time=False)
    return approval


def validate_canary_plan_approval_v1(
    value: Mapping[str, Any], *, expected_scope: str | None = None,
    expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None,
    now: datetime | None = None, enforce_time: bool = True,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "approval_not_object")
    _require_fields(value, {
        "schema", "version", "canonicalization_version", "approval_scope",
        "approved_plan_sha256", "approved_launcher_sha256",
        "single_use_cohort_id", "approval_expiry", "execution_window",
        "maximum_executions", "usage_status", "consumed_evidence_sha256",
        "authorized_actions", "approval_sha256",
    }, "approval")
    _require(value["schema"] == APPROVAL_SCHEMA and value["version"] == 1,
             "approval_schema_unsupported")
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "approval_canonicalization_unsupported")
    _require(value["approval_scope"] != SMOKE_APPROVAL_SCOPE,
             "approval_scope_mismatch")
    _require(value["approval_scope"] in APPROVAL_SCOPES, "approval_scope_unsupported")
    _require_hash(value["approved_plan_sha256"], "approved_plan_sha256_invalid")
    _require_hash(value["approved_launcher_sha256"], "approved_launcher_sha256_invalid")
    _require(isinstance(value["single_use_cohort_id"], str)
             and re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}",
                              value["single_use_cohort_id"]) is not None,
             "single_use_cohort_id_invalid")
    _require(type(value["maximum_executions"]) is int
             and value["maximum_executions"] >= 1,
             "maximum_executions_invalid")
    _require(value["usage_status"] in {"unused", "used"}, "usage_status_invalid")
    if value["usage_status"] == "unused":
        _require(value["consumed_evidence_sha256"] is None,
                 "unused_approval_has_evidence")
    else:
        _require_hash(value["consumed_evidence_sha256"],
                      "consumed_evidence_sha256_invalid")
    window = value["execution_window"]
    _require(isinstance(window, Mapping), "execution_window_invalid")
    _require_fields(window, {"not_before", "not_after"}, "execution_window")
    not_before = _parse_utc(window["not_before"], "execution_window_invalid")
    not_after = _parse_utc(window["not_after"], "execution_window_invalid")
    expiry = _parse_utc(value["approval_expiry"], "approval_expiry_invalid")
    _require(not_before <= not_after <= expiry, "approval_window_invalid")
    _require(isinstance(value["authorized_actions"], Mapping),
             "authorized_actions_invalid")
    approved_budget = value.get("approved_budget")
    if approved_budget is not None:
        _require(isinstance(approved_budget, Mapping), "approved_budget_invalid")
        _require_fields(approved_budget, {
            "maximum_model_calls_per_run", "maximum_total_model_calls",
            "maximum_input_tokens", "maximum_output_tokens",
            "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
            "maximum_elapsed_seconds", "definition_sha256",
        }, "approved_budget")
        for field in (
            "maximum_model_calls_per_run", "maximum_total_model_calls",
            "maximum_input_tokens", "maximum_output_tokens",
            "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
            "maximum_elapsed_seconds",
        ):
            _require(type(approved_budget[field]) is int and approved_budget[field] >= 0,
                     f"approved_budget_{field}_invalid")
        _require_hash(approved_budget["definition_sha256"],
                      "approved_budget_definition_sha256_invalid")
        expected_budget_hash = domain_sha256(
            "novel-flywheel-c0b-approved-budget-v1", {
                key: approved_budget[key] for key in approved_budget
                if key != "definition_sha256"
            },
        )
        _require(approved_budget["definition_sha256"] == expected_budget_hash,
                 "approved_budget_definition_hash_mismatch")
        _require(
            approved_budget["maximum_total_model_calls"]
            >= approved_budget["maximum_model_calls_per_run"],
            "approved_budget_total_below_per_run",
        )
    _scan_forbidden_material(value)
    _require(value["approval_sha256"] == _approval_digest(value),
             "approval_hash_mismatch")
    if expected_scope is not None:
        _require(value["approval_scope"] == expected_scope, "approval_scope_mismatch")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "approval_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "approval_launcher_mismatch")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(current <= expiry, "approval_expired")
        _require(not_before <= current <= not_after, "approval_outside_execution_window")
        _require(value["usage_status"] == "unused", "approval_already_used")
    return deepcopy(dict(value))


def build_c0b_smoke_1_final_approval_candidate_v2(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = {
        "schema": SMOKE_APPROVAL_CANDIDATE_SCHEMA,
        "version": 2,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    candidate["approval_candidate_sha256"] = _smoke_candidate_digest(candidate)
    return validate_c0b_smoke_1_final_approval_candidate_v2(
        candidate, enforce_time=False,
    )


def validate_c0b_smoke_1_final_approval_candidate_v2(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None,
    now: datetime | None = None, enforce_time: bool = True,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "approval_candidate_not_object")
    _require_fields(value, {
        "schema", "version", "canonicalization_version", "approval_scope",
        "approved_plan_sha256", "approved_launcher_sha256",
        "approved_workload_sha256", "approved_workload_manifest_hash",
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "approved_runtime_execution_fingerprint", "runtime_mode",
        "provider_descriptor_hash", "model_role_binding_manifest_hash",
        "pricing_evidence_manifest_hash", "feature_flag_snapshot_hash",
        "stop_condition_manifest_hash", "call_budget_definition_sha256",
        "token_budget_definition_sha256", "monetary_budget_definition_sha256",
        "elapsed_budget_definition_sha256", "canary_root_identity_candidate",
        "approved_workload_id", "maximum_runs", "expected_model_calls",
        "maximum_total_model_calls", "maximum_input_tokens",
        "maximum_output_tokens", "maximum_output_tokens_per_call",
        "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
        "maximum_elapsed_seconds", "first_terminal_stop",
        "resume_after_terminal", "phase1b_enabled", "execution_window",
        "materialized_at", "approval_expiry", "single_use_cohort_id", "maximum_executions",
        "usage_status", "consumed_evidence_sha256", "named_approver",
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls",
        "authorized_actions", "execution_authorized", "approved_budget",
        "approval_candidate_sha256",
    }, "approval_candidate")
    _require(
        value["schema"] == SMOKE_APPROVAL_CANDIDATE_SCHEMA
        and value["version"] == 2,
        "approval_candidate_schema_unsupported",
    )
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "approval_candidate_canonicalization_unsupported")
    _require(value["approval_scope"] == SMOKE_APPROVAL_SCOPE,
             "approval_candidate_scope_mismatch")
    for field in (
        "approved_plan_sha256", "approved_launcher_sha256",
        "approved_workload_sha256", "approved_workload_manifest_hash",
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "approved_runtime_execution_fingerprint", "provider_descriptor_hash",
        "model_role_binding_manifest_hash", "pricing_evidence_manifest_hash",
        "feature_flag_snapshot_hash", "stop_condition_manifest_hash",
        "call_budget_definition_sha256", "token_budget_definition_sha256",
        "monetary_budget_definition_sha256", "elapsed_budget_definition_sha256",
        "canary_root_identity_candidate", "approval_candidate_sha256",
    ):
        _require_hash(value[field], f"{field}_invalid")
    _require(value["runtime_mode"] == "git_workspace", "runtime_mode_not_git_workspace")
    _require(value["approved_workload_id"] == "short-normal-v1",
             "smoke_workload_id_mismatch")
    expected_numbers = {
        "maximum_runs": 1, "expected_model_calls": 16,
        "maximum_total_model_calls": 48,
        "maximum_input_tokens": 1_000_000,
        "maximum_output_tokens": 1_000_000,
        "maximum_output_tokens_per_call": 32_000,
        "maximum_usd_cost_microunits": 20_000_000,
        "maximum_cny_cost_microunits": 50_000_000,
        "maximum_elapsed_seconds": 7_200, "maximum_executions": 1,
    }
    for field, expected in expected_numbers.items():
        _require(value[field] == expected, f"smoke_{field}_mismatch")
    _require(value["first_terminal_stop"] is True,
             "smoke_first_terminal_stop_not_enabled")
    _require(value["resume_after_terminal"] is False,
             "smoke_resume_after_terminal_enabled")
    _require(value["phase1b_enabled"] is False, "phase1b_enabled")
    _require(value["usage_status"] == "unused"
             and value["consumed_evidence_sha256"] is None,
             "approval_candidate_not_unused")
    _require(value["named_approver"] == "USER_CONFIRMATION_REQUIRED",
             "approval_candidate_named_approver_not_placeholder")
    _require(value["execution_authorized"] is False,
             "approval_candidate_execution_authorized")
    _require(all(value[name] is False for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls",
    )), "approval_candidate_external_action_enabled")
    actions = value["authorized_actions"]
    _require(isinstance(actions, Mapping), "authorized_actions_invalid")
    _require(all(actions.get(name) is False for name in (
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls", "fake_boundary",
    )), "approval_candidate_external_action_enabled")
    _require(isinstance(value["single_use_cohort_id"], str)
             and re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}",
                              value["single_use_cohort_id"]) is not None,
             "single_use_cohort_id_invalid")
    window = value["execution_window"]
    _require(isinstance(window, Mapping), "execution_window_invalid")
    _require_fields(window, {"not_before", "not_after"}, "execution_window")
    not_before = _parse_utc(window["not_before"], "execution_window_invalid")
    not_after = _parse_utc(window["not_after"], "execution_window_invalid")
    materialized_at = _parse_utc(
        value["materialized_at"], "approval_candidate_materialized_at_invalid",
    )
    expiry = _parse_utc(value["approval_expiry"], "approval_expiry_invalid")
    _require(
        not_before >= materialized_at + timedelta(minutes=15)
        and not_after - not_before == timedelta(hours=48)
        and expiry == not_after,
             "approval_candidate_window_invalid")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(current < expiry, "approval_expired")
    budget = value["approved_budget"]
    _require(isinstance(budget, Mapping), "approved_budget_invalid")
    _require_fields(budget, {
        "maximum_model_calls_per_run", "maximum_total_model_calls",
        "maximum_input_tokens", "maximum_output_tokens",
        "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
        "maximum_elapsed_seconds", "definition_sha256",
    }, "approved_budget")
    expected_budget = {
        "maximum_model_calls_per_run": 48,
        "maximum_total_model_calls": 48,
        "maximum_input_tokens": 1_000_000,
        "maximum_output_tokens": 1_000_000,
        "maximum_usd_cost_microunits": 20_000_000,
        "maximum_cny_cost_microunits": 50_000_000,
        "maximum_elapsed_seconds": 7_200,
    }
    _require({key: budget.get(key) for key in expected_budget} == expected_budget,
             "approved_budget_smoke_limits_mismatch")
    _require_hash(budget["definition_sha256"],
                  "approved_budget_definition_sha256_invalid")
    _require(budget["definition_sha256"] == domain_sha256(
        "novel-flywheel-c0b-approved-budget-v1", expected_budget,
    ), "approved_budget_definition_hash_mismatch")
    _require(value["approval_candidate_sha256"] == _smoke_candidate_digest(value),
             "approval_candidate_hash_mismatch")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "approval_candidate_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "approval_candidate_launcher_mismatch")
    _scan_forbidden_material(value)
    return deepcopy(dict(value))


def build_c0b_smoke_1_user_authorization_patch_v1(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    patch = {
        "schema": SMOKE_AUTHORIZATION_PATCH_SCHEMA_V1,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    patch["authorization_patch_sha256"] = _smoke_patch_v1_digest(patch)
    return validate_c0b_smoke_1_user_authorization_patch_v1(patch)


def validate_c0b_smoke_1_user_authorization_patch_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "authorization_patch_not_object")
    exact_fields = {
        "schema", "version", "canonicalization_version",
        "bound_plan_sha256", "bound_approval_candidate_sha256",
        "bound_launcher_sha256", "bound_workload_sha256",
        "bound_build_fingerprint", "bound_execution_config_fingerprint",
        "bound_runtime_execution_fingerprint", "named_approver",
        "approval_timestamp", "approved_execution_window", "approval_expiry",
        "single_use_cohort_id_confirmation", "authorize_credential_lookup",
        "authorize_provider_client_creation", "authorize_network",
        "authorize_paid_model_calls", "execution_authorized",
        "protected_fields_mutation_allowed", "authorization_patch_sha256",
    }
    _require_fields(value, exact_fields, "authorization_patch")
    _require(set(value) == exact_fields, "authorization_patch_fields_unexpected")
    _require(value["schema"] == SMOKE_AUTHORIZATION_PATCH_SCHEMA_V1
             and value["version"] == 1,
             "authorization_patch_schema_unsupported")
    for field in (
        "bound_plan_sha256", "bound_approval_candidate_sha256",
        "bound_launcher_sha256", "bound_workload_sha256",
        "bound_build_fingerprint", "bound_execution_config_fingerprint",
        "bound_runtime_execution_fingerprint", "authorization_patch_sha256",
    ):
        _require_hash(value[field], f"{field}_invalid")
    _require(value["named_approver"] == "USER_CONFIRMATION_REQUIRED"
             and value["approval_timestamp"] == "USER_CONFIRMATION_REQUIRED",
             "authorization_patch_user_confirmation_missing")
    _require(all(value[name] is True for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls", "execution_authorized",
    )), "authorization_patch_action_not_requested")
    _require(value["protected_fields_mutation_allowed"] is False,
             "authorization_patch_protected_mutation_enabled")
    _require(value["authorization_patch_sha256"] == _smoke_patch_v1_digest(value),
             "authorization_patch_hash_mismatch")
    _scan_forbidden_material(value)
    return deepcopy(dict(value))


_SMOKE_PATCH_V2_FIELDS = {
    "schema", "version", "canonicalization_version", "approval_scope",
    "bound_plan_sha256", "bound_approval_candidate_sha256",
    "bound_launcher_sha256", "bound_workload_sha256",
    "bound_build_fingerprint", "bound_execution_config_fingerprint",
    "bound_runtime_execution_fingerprint", "named_approver",
    "approval_timestamp", "approved_execution_window", "approval_expiry",
    "single_use_cohort_id", "authorize_credential_lookup",
    "authorize_provider_client_creation", "authorize_network",
    "authorize_paid_model_calls", "execution_authorized",
    "protected_fields_mutation_allowed", "authorization_patch_sha256",
}


def build_c0b_smoke_1_user_authorization_patch_v2(
    payload: Mapping[str, Any], *, require_confirmation: bool = False,
) -> dict[str, Any]:
    patch = {
        "schema": SMOKE_AUTHORIZATION_PATCH_SCHEMA,
        "version": 2,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    patch["authorization_patch_sha256"] = _smoke_patch_digest(patch)
    return validate_c0b_smoke_1_user_authorization_patch_v2(
        patch, require_confirmation=require_confirmation,
    )


def validate_c0b_smoke_1_user_authorization_patch_v2(
    value: Mapping[str, Any], *, require_confirmation: bool = False,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "authorization_patch_not_object")
    _require_fields(value, _SMOKE_PATCH_V2_FIELDS, "authorization_patch")
    _require(set(value) == _SMOKE_PATCH_V2_FIELDS,
             "authorization_patch_fields_unexpected")
    _require(value["schema"] == SMOKE_AUTHORIZATION_PATCH_SCHEMA
             and value["version"] == 2,
             "authorization_patch_schema_unsupported")
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "authorization_patch_canonicalization_unsupported")
    _require(value["approval_scope"] == SMOKE_APPROVAL_SCOPE,
             "approval_scope_mismatch")
    for field in (
        "bound_plan_sha256", "bound_approval_candidate_sha256",
        "bound_launcher_sha256", "bound_workload_sha256",
        "bound_build_fingerprint", "bound_execution_config_fingerprint",
        "bound_runtime_execution_fingerprint", "authorization_patch_sha256",
    ):
        _require_hash(value[field], f"{field}_invalid")
    _require(isinstance(value["single_use_cohort_id"], str)
             and re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}",
                              value["single_use_cohort_id"]) is not None,
             "single_use_cohort_id_invalid")
    window = value["approved_execution_window"]
    _require(isinstance(window, Mapping)
             and set(window) == {"not_before", "not_after"},
             "execution_window_invalid")
    not_before = _parse_utc(window["not_before"], "execution_window_invalid")
    not_after = _parse_utc(window["not_after"], "execution_window_invalid")
    expiry = _parse_utc(value["approval_expiry"], "approval_expiry_invalid")
    _require(not_before <= not_after == expiry, "approval_window_invalid")
    placeholder = "USER_CONFIRMATION_REQUIRED"
    if require_confirmation:
        _require(isinstance(value["named_approver"], str)
                 and bool(value["named_approver"].strip())
                 and value["named_approver"] != placeholder,
                 "signed_approval_named_approver_invalid")
        _parse_utc(value["approval_timestamp"], "approval_timestamp_invalid")
    else:
        both_placeholder = (
            value["named_approver"] == placeholder
            and value["approval_timestamp"] == placeholder
        )
        both_confirmed = (
            isinstance(value["named_approver"], str)
            and bool(value["named_approver"].strip())
            and value["named_approver"] != placeholder
            and isinstance(value["approval_timestamp"], str)
            and value["approval_timestamp"].endswith("Z")
        )
        _require(both_placeholder or both_confirmed,
                 "authorization_patch_user_confirmation_invalid")
        if both_confirmed:
            _parse_utc(value["approval_timestamp"], "approval_timestamp_invalid")
    _require(all(value[name] is True for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls", "execution_authorized",
    )), "authorization_patch_action_not_requested")
    _require(value["protected_fields_mutation_allowed"] is False,
             "authorization_patch_protected_mutation_enabled")
    _require(value["authorization_patch_sha256"] == _smoke_patch_digest(value),
             "authorization_patch_hash_mismatch")
    _scan_forbidden_material(value)
    return deepcopy(dict(value))


_SIGNED_ADDITIONAL_FIELDS = {
    "approval_timestamp", "approval_method", "source_candidate_sha256",
    "source_authorization_patch_sha256", "signed_approval_sha256",
}


def build_c0b_smoke_1_signed_approval_v1(
    payload: Mapping[str, Any], *, now: datetime | None = None,
    validate_source_independent: bool = False,
) -> dict[str, Any]:
    approval = {
        "schema": SMOKE_SIGNED_APPROVAL_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    approval["signed_approval_sha256"] = _smoke_signed_approval_digest(approval)
    return validate_c0b_smoke_1_signed_approval_v1(
        approval, now=now,
        validate_source_independent=validate_source_independent,
    )


def validate_c0b_smoke_1_signed_approval_v1(
    value: Mapping[str, Any], *, expected_plan_sha256: str | None = None,
    expected_launcher_sha256: str | None = None,
    now: datetime | None = None, enforce_time: bool = True,
    validate_source_independent: bool = False,
) -> dict[str, Any]:
    del validate_source_independent  # Source binding is checked by the source validator.
    _require(isinstance(value, Mapping), "signed_approval_not_object")
    expected_fields = {
        "schema", "version", "canonicalization_version", "approval_scope",
        "approved_plan_sha256", "approved_launcher_sha256",
        "approved_workload_sha256", "approved_workload_manifest_hash",
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "approved_runtime_execution_fingerprint", "runtime_mode",
        "provider_descriptor_hash", "model_role_binding_manifest_hash",
        "pricing_evidence_manifest_hash", "feature_flag_snapshot_hash",
        "stop_condition_manifest_hash", "call_budget_definition_sha256",
        "token_budget_definition_sha256", "monetary_budget_definition_sha256",
        "elapsed_budget_definition_sha256", "canary_root_identity_candidate",
        "approved_workload_id", "maximum_runs", "expected_model_calls",
        "maximum_total_model_calls", "maximum_input_tokens",
        "maximum_output_tokens", "maximum_output_tokens_per_call",
        "maximum_usd_cost_microunits", "maximum_cny_cost_microunits",
        "maximum_elapsed_seconds", "first_terminal_stop",
        "resume_after_terminal", "phase1b_enabled", "execution_window",
        "materialized_at", "approval_expiry", "single_use_cohort_id",
        "maximum_executions", "usage_status", "consumed_evidence_sha256",
        "named_approver", "authorize_credential_lookup",
        "authorize_provider_client_creation", "authorize_network",
        "authorize_paid_model_calls", "authorized_actions",
        "execution_authorized", "approved_budget",
        *_SIGNED_ADDITIONAL_FIELDS,
    }
    _require_fields(value, expected_fields, "signed_approval")
    _require(set(value) == expected_fields, "signed_approval_fields_unexpected")
    _require(value["schema"] == SMOKE_SIGNED_APPROVAL_SCHEMA
             and value["version"] == 1, "signed_approval_schema_unsupported")
    _require(value["canonicalization_version"] == CANONICALIZATION_VERSION,
             "signed_approval_canonicalization_unsupported")
    _require(value["approval_scope"] == SMOKE_APPROVAL_SCOPE,
             "approval_scope_mismatch")
    _require(value["approval_method"] == "manual_user_confirmation",
             "signed_approval_method_invalid")
    _require(isinstance(value["named_approver"], str)
             and bool(value["named_approver"].strip())
             and value["named_approver"] != "USER_CONFIRMATION_REQUIRED",
             "signed_approval_named_approver_invalid")
    approval_time = _parse_utc(value["approval_timestamp"],
                               "approval_timestamp_invalid")
    for field in (
        "approved_plan_sha256", "approved_launcher_sha256",
        "approved_workload_sha256", "approved_workload_manifest_hash",
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "approved_runtime_execution_fingerprint", "provider_descriptor_hash",
        "model_role_binding_manifest_hash", "pricing_evidence_manifest_hash",
        "feature_flag_snapshot_hash", "stop_condition_manifest_hash",
        "call_budget_definition_sha256", "token_budget_definition_sha256",
        "monetary_budget_definition_sha256", "elapsed_budget_definition_sha256",
        "canary_root_identity_candidate", "source_candidate_sha256",
        "source_authorization_patch_sha256", "signed_approval_sha256",
    ):
        _require_hash(value[field], f"{field}_invalid")
    window = value["execution_window"]
    _require(isinstance(window, Mapping)
             and set(window) == {"not_before", "not_after"},
             "execution_window_invalid")
    not_before = _parse_utc(window["not_before"], "execution_window_invalid")
    not_after = _parse_utc(window["not_after"], "execution_window_invalid")
    expiry = _parse_utc(value["approval_expiry"], "approval_expiry_invalid")
    _require(not_before <= approval_time <= not_after == expiry,
             "approval_timestamp_outside_execution_window")
    _require(value["usage_status"] == "unused"
             and value["consumed_evidence_sha256"] is None,
             "signed_approval_not_unused")
    _require(value["maximum_executions"] == 1,
             "signed_approval_maximum_executions_invalid")
    _require(value["execution_authorized"] is True
             and all(value[name] is True for name in (
                 "authorize_credential_lookup",
                 "authorize_provider_client_creation", "authorize_network",
                 "authorize_paid_model_calls",
             )), "signed_approval_authorization_missing")
    actions = value["authorized_actions"]
    _require(isinstance(actions, Mapping)
             and set(actions) == {
                 "credential_lookup", "provider_client_creation", "network",
                 "paid_model_calls", "fake_boundary",
             }, "authorized_actions_invalid")
    _require(all(actions[name] is True for name in (
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls",
    )) and actions["fake_boundary"] is False,
             "signed_approval_authorization_missing")
    _require(value["signed_approval_sha256"] == _smoke_signed_approval_digest(value),
             "signed_approval_hash_mismatch")
    if expected_plan_sha256 is not None:
        _require(value["approved_plan_sha256"] == expected_plan_sha256,
                 "signed_approval_plan_mismatch")
    if expected_launcher_sha256 is not None:
        _require(value["approved_launcher_sha256"] == expected_launcher_sha256,
                 "signed_approval_launcher_mismatch")
    if enforce_time:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require(current <= expiry, "approval_expired")
        _require(not_before <= current <= not_after,
                 "approval_outside_execution_window")
    _scan_forbidden_material(value)
    return deepcopy(dict(value))


def materialize_signed_smoke_approval_v1(
    candidate: Mapping[str, Any], patch: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_candidate = validate_c0b_smoke_1_final_approval_candidate_v2(
        candidate, now=current,
    )
    source_patch = validate_c0b_smoke_1_user_authorization_patch_v2(
        patch, require_confirmation=True,
    )
    bindings = {
        "approval_scope": "approval_scope",
        "bound_plan_sha256": "approved_plan_sha256",
        "bound_approval_candidate_sha256": "approval_candidate_sha256",
        "bound_launcher_sha256": "approved_launcher_sha256",
        "bound_workload_sha256": "approved_workload_sha256",
        "bound_build_fingerprint": "approved_build_fingerprint",
        "bound_execution_config_fingerprint": "approved_execution_config_fingerprint",
        "bound_runtime_execution_fingerprint": "approved_runtime_execution_fingerprint",
        "approved_execution_window": "execution_window",
        "approval_expiry": "approval_expiry",
        "single_use_cohort_id": "single_use_cohort_id",
    }
    for patch_field, candidate_field in bindings.items():
        _require(source_patch[patch_field] == source_candidate[candidate_field],
                 "signed_approval_source_binding_mismatch")
    body = deepcopy(source_candidate)
    body.pop("approval_candidate_sha256")
    body.update({
        "schema": SMOKE_SIGNED_APPROVAL_SCHEMA,
        "version": 1,
        "named_approver": source_patch["named_approver"],
        "approval_timestamp": source_patch["approval_timestamp"],
        "approval_method": "manual_user_confirmation",
        "source_candidate_sha256": source_candidate["approval_candidate_sha256"],
        "source_authorization_patch_sha256": source_patch["authorization_patch_sha256"],
        "authorize_credential_lookup": True,
        "authorize_provider_client_creation": True,
        "authorize_network": True,
        "authorize_paid_model_calls": True,
        "authorized_actions": {
            "credential_lookup": True,
            "provider_client_creation": True,
            "network": True,
            "paid_model_calls": True,
            "fake_boundary": False,
        },
        "execution_authorized": True,
    })
    return build_c0b_smoke_1_signed_approval_v1(body, now=current)


def validate_signed_smoke_approval_sources_v1(
    signed_approval: Mapping[str, Any], candidate: Mapping[str, Any],
    patch: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    signed = validate_c0b_smoke_1_signed_approval_v1(
        signed_approval, now=current,
    )
    expected = materialize_signed_smoke_approval_v1(
        candidate, patch, now=current,
    )
    _require(signed["source_candidate_sha256"]
             == expected["source_candidate_sha256"],
             "signed_approval_candidate_source_mismatch")
    _require(signed["source_authorization_patch_sha256"]
             == expected["source_authorization_patch_sha256"],
             "signed_approval_patch_source_mismatch")
    protected = set(expected).difference({
        "signed_approval_sha256",
    })
    _require(all(signed.get(field) == expected.get(field) for field in protected),
             "signed_approval_protected_fields_mismatch")
    return signed


def validate_signed_smoke_approval_plan_v1(
    signed_approval: Mapping[str, Any], plan: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind a Signed Smoke Approval to the exact immutable Plan policy."""
    source_plan = validate_canary_experiment_plan_v1(plan)
    signed = validate_c0b_smoke_1_signed_approval_v1(
        signed_approval, expected_plan_sha256=source_plan["plan_sha256"],
        expected_launcher_sha256=source_plan["launcher_sha256"], now=now,
    )
    workloads = source_plan["workloads"]
    _require(len(workloads) == 1, "signed_approval_workload_plan_mismatch")
    workload = workloads[0]
    policy = source_plan.get("smoke_1_policy")
    _require(isinstance(policy, Mapping), "signed_approval_smoke_policy_missing")
    bindings = {
        "approved_workload_sha256": workload["fixture_sha256"],
        "approved_workload_id": workload["workload_id"],
        "approved_workload_manifest_hash": source_plan["workload_manifest_hash"],
        "approved_build_fingerprint": source_plan["approved_build_fingerprint"],
        "approved_execution_config_fingerprint": source_plan[
            "approved_execution_config_fingerprint"
        ],
        "approved_runtime_execution_fingerprint": source_plan[
            "expected_runtime_execution_fingerprint"
        ],
        "runtime_mode": source_plan["runtime_mode"],
        "provider_descriptor_hash": source_plan[
            "provider_descriptor_definition_sha256"
        ],
        "model_role_binding_manifest_hash": source_plan[
            "role_binding_manifest_definition_sha256"
        ],
        "pricing_evidence_manifest_hash": source_plan["budgets"][
            "price_catalog_sha256"
        ],
        "feature_flag_snapshot_hash": domain_sha256(
            "novel-flywheel-c0b-feature-flags-v1",
            source_plan["feature_flag_snapshot"],
        ),
        "stop_condition_manifest_hash": domain_sha256(
            "novel-flywheel-c0b-stop-conditions-v1",
            source_plan["stop_conditions"],
        ),
        "canary_root_identity_candidate": source_plan["isolation"][
            "stable_root_identity"
        ],
        "call_budget_definition_sha256": policy["budget_definition_hashes"]["call"],
        "token_budget_definition_sha256": policy["budget_definition_hashes"]["token"],
        "monetary_budget_definition_sha256": policy["budget_definition_hashes"]["monetary"],
        "elapsed_budget_definition_sha256": policy["budget_definition_hashes"]["elapsed"],
        "expected_model_calls": policy["expected_model_calls"],
        "maximum_total_model_calls": policy["maximum_total_model_calls"],
        "maximum_input_tokens": policy["maximum_input_tokens"],
        "maximum_output_tokens": policy["maximum_output_tokens"],
        "maximum_output_tokens_per_call": policy["maximum_output_tokens_per_call"],
        "maximum_usd_cost_microunits": policy["maximum_usd_cost_microunits"],
        "maximum_cny_cost_microunits": policy["maximum_cny_cost_microunits"],
        "maximum_elapsed_seconds": policy["maximum_elapsed_seconds"],
        "first_terminal_stop": policy["first_terminal_stop"],
        "resume_after_terminal": policy["resume_after_terminal"],
        "phase1b_enabled": False,
    }
    _require(all(signed.get(field) == expected for field, expected in bindings.items()),
             "signed_approval_plan_binding_mismatch")
    return signed


def validate_canary_approval_document(
    value: Mapping[str, Any], *, expected_scope: str,
    expected_plan_sha256: str, expected_launcher_sha256: str,
    now: datetime | None = None, enforce_time: bool = True,
) -> tuple[dict[str, Any], str, str]:
    """Validate an executable Approval or a non-executable Smoke candidate."""
    schema = value.get("schema")
    if schema == SMOKE_APPROVAL_CANDIDATE_SCHEMA:
        candidate = validate_c0b_smoke_1_final_approval_candidate_v2(
            value, expected_plan_sha256=expected_plan_sha256,
            expected_launcher_sha256=expected_launcher_sha256,
            now=now, enforce_time=enforce_time,
        )
        _require(expected_scope == SMOKE_APPROVAL_SCOPE,
                 "approval_candidate_scope_mismatch")
        return candidate, candidate["approval_candidate_sha256"], "final_approval_candidate"
    if schema in {SMOKE_AUTHORIZATION_PATCH_SCHEMA,
                  SMOKE_AUTHORIZATION_PATCH_SCHEMA_V1}:
        if schema == SMOKE_AUTHORIZATION_PATCH_SCHEMA:
            validate_c0b_smoke_1_user_authorization_patch_v2(value)
        else:
            validate_c0b_smoke_1_user_authorization_patch_v1(value)
        raise CanaryContractError("authorization_patch_not_executable")
    if schema == SMOKE_SIGNED_APPROVAL_SCHEMA:
        _require(expected_scope == SMOKE_APPROVAL_SCOPE, "approval_scope_mismatch")
        signed = validate_c0b_smoke_1_signed_approval_v1(
            value, expected_plan_sha256=expected_plan_sha256,
            expected_launcher_sha256=expected_launcher_sha256,
            now=now, enforce_time=enforce_time,
        )
        return signed, signed["signed_approval_sha256"], "signed_smoke_approval"
    _require(schema == APPROVAL_SCHEMA, "approval_schema_mismatch")
    approval = validate_canary_plan_approval_v1(
        value, expected_scope=expected_scope,
        expected_plan_sha256=expected_plan_sha256,
        expected_launcher_sha256=expected_launcher_sha256,
        now=now, enforce_time=enforce_time,
    )
    return approval, approval["approval_sha256"], "executable_approval"
