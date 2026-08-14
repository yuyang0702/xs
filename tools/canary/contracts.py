"""Hash-bound contracts for the non-production controlled Canary launcher.

This module is deliberately orchestration-only.  It imports the existing
Runtime fingerprint canonicalization primitive and never resolves a provider,
credential, project, or model.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


PLAN_SCHEMA = "CanaryExperimentPlanV1"
APPROVAL_SCHEMA = "CanaryPlanApprovalV1"
PLAN_DOMAIN = "novel-flywheel-canary-experiment-plan-v1"
APPROVAL_DOMAIN = "novel-flywheel-canary-plan-approval-v1"
PLAN_MODES = frozenset({
    "c0a_fake_dry_run", "c0b_real_path_reachability",
    "c0c_statistical_exposure",
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
    _require(isinstance(value["stop_conditions"], list)
             and all(isinstance(item, str) and item for item in value["stop_conditions"]),
             "stop_conditions_invalid")
    _require(isinstance(value["approved_dependency_manifest"], Mapping),
             "dependency_manifest_invalid")
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
