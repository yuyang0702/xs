"""Materialize the inert PA-STRICT-TOOL-OBS-1 final approval package.

This module is Canary control-plane only.  It reads non-secret production route
metadata, copies that metadata into a temporary database, blocks network entry
points, and never resolves credentials or constructs a provider client.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator, Mapping

from novel_flywheel.model_diagnostics import (
    StrictToolShapeObservationV1,
    adapter_manifest_sha256,
)
from novel_flywheel.runtime_fingerprint import collect_build_fingerprint
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .artifact_hash import file_sha256, live_parity_manifest, parity_equal
from .approval_profiles import (
    PA_CANDIDATE_SCHEMA, PA_PATCH_TEMPLATE_SCHEMA, PA_PROFILE_ID, PA_SCOPE,
    PA_SIGNED_SCHEMA, approval_profile,
)
from .c0b_packet import prepare_c0b_smoke_packet
from .contracts import CanaryContractError, build_canary_experiment_plan_v1
from .network_sentinel import FailClosedNetworkSentinel
from .pa_approval import (
    build_pa_authorization_patch_template_v2,
    build_pa_final_approval_candidate_v1,
    validate_pa_final_approval_candidate_v1,
)


CANARY_ID = "PA-STRICT-TOOL-OBS-1"
APPROVAL_SCOPE = PA_SCOPE
CANDIDATE_SCHEMA = PA_CANDIDATE_SCHEMA
PATCH_SCHEMA = PA_PATCH_TEMPLATE_SCHEMA
PREVIEW_SCHEMA = "PAStrictToolObs1ExecutionCommandPreviewV1"
RECEIPT_SCHEMA = "PAStrictToolObs1ValidateOnlyReceiptV1"
INDEX_SCHEMA = "PAStrictToolObs1MaterializationIndexV1"
FUTURE_SIGNED_APPROVAL_SCHEMA = PA_SIGNED_SCHEMA

CANDIDATE_DOMAIN = "novel-flywheel-pa-strict-tool-obs-1-candidate-v1"
PATCH_DOMAIN = "novel-flywheel-pa-strict-tool-obs-1-patch-template-v1"
PREVIEW_DOMAIN = "novel-flywheel-pa-strict-tool-obs-1-preview-v1"
RECEIPT_DOMAIN = "novel-flywheel-pa-strict-tool-obs-1-validate-receipt-v1"
INDEX_DOMAIN = "novel-flywheel-pa-strict-tool-obs-1-index-v1"

TARGET = {
    "stage": "review",
    "boundary": "planning_adaptation_whole_receipt",
    "contract_id": "planning_adaptation_whole",
    "contract_version": 1,
    "role": "review",
    "route_kind": "configured_fallback",
    "strict_tool_route": True,
    "target_selection_method": "exact_metadata_tuple_not_prompt_text",
    "non_target_policy": "excluded_not_target_count_only",
}

FEATURE_FLAGS = {
    "NOVEL_SHORT_CANONICAL_V2": False,
    "project_short_canonical_v2": False,
    "NOVEL_CANONICAL_SHADOW_V1": False,
    "NOVEL_RELIABILITY_TRACE": True,
    "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1": True,
    "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1": False,
}

STOP_CONDITIONS = (
    "target_strict_tool_shape_exact_captured",
    "first_workflow_terminal",
    "fingerprint_mismatch",
    "production_source_dirty_or_changed",
    "route_mismatch",
    "observation_privacy_violation",
    "observation_unavailable_at_target_boundary",
    "budget_exhausted",
    "controlled_provider_capability_outcome",
    "approval_expired",
    "live_isolation_violation",
)

EXTERNAL_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|^/home/|^/Users/|^\\\\)")
_FORBIDDEN_PRIVACY_KEYS = {
    "api_key", "authorization_header", "headers", "prompt", "prompts",
    "prose", "novel_text", "story_text", "raw_arguments", "raw_response",
    "full_response", "provider_request_id", "absolute_path", "project_name",
    "entity_name",
}


class PAStrictToolObsMaterializationError(ValueError):
    """Stable failure for an inert materialization contract violation."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise PAStrictToolObsMaterializationError(reason_code)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z",
    )


def _parse_utc(value: str) -> datetime:
    _require(value.endswith("Z"), "utc_timestamp_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(
            timezone.utc,
        )
    except ValueError as exc:
        raise PAStrictToolObsMaterializationError(
            "utc_timestamp_invalid",
        ) from exc


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _definition(domain: str, schema: str, payload: Any) -> dict[str, Any]:
    body = {"schema": schema, "version": 1, "payload": deepcopy(payload)}
    return {**body, "definition_sha256": domain_sha256(domain, body)}


def _sealed(
    domain: str, body: Mapping[str, Any], digest_field: str,
) -> dict[str, Any]:
    value = deepcopy(dict(body))
    value[digest_field] = domain_sha256(domain, value)
    return value


@contextmanager
def _diagnostic_environment() -> Iterator[None]:
    values = {
        "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1": "1",
        "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1": "0",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def _budget_definitions() -> dict[str, dict[str, Any]]:
    return {
        "call": _definition(
            "novel-flywheel-pa-strict-tool-obs-1-call-budget-v1",
            "PAStrictToolObs1CallBudgetV1", {
                "maximum_runs": 1,
                "expected_model_calls": 11,
                "maximum_model_calls_per_run": 24,
                "maximum_total_model_calls": 24,
                "maximum_output_tokens_per_call": 32_000,
                "first_terminal_stop": True,
                "resume_after_terminal": False,
                "second_run_allowed": False,
            },
        ),
        "token": _definition(
            "novel-flywheel-pa-strict-tool-obs-1-token-budget-v1",
            "PAStrictToolObs1TokenBudgetV1", {
                "maximum_input_tokens": 500_000,
                "maximum_output_tokens": 500_000,
                "maximum_output_tokens_per_call": 32_000,
                "runtime_output_budget_mutation_allowed": False,
            },
        ),
        "monetary": _definition(
            "novel-flywheel-pa-strict-tool-obs-1-monetary-budget-v1",
            "PAStrictToolObs1MonetaryBudgetV1", {
                "maximum_usd_cost_microunits": 10_000_000,
                "maximum_cny_cost_microunits": 25_000_000,
                "currency_conversion": "none",
                "approved_fx_snapshot": None,
            },
        ),
        "elapsed": _definition(
            "novel-flywheel-pa-strict-tool-obs-1-elapsed-budget-v1",
            "PAStrictToolObs1ElapsedBudgetV1", {
                "maximum_elapsed_seconds": 7_200,
            },
        ),
    }


def _observation_schema_definition() -> dict[str, Any]:
    schema = StrictToolShapeObservationV1.model_json_schema(by_alias=True)
    return _definition(
        "novel-flywheel-pa-strict-tool-observation-schema-v1",
        "PAStrictToolObservationSchemaDefinitionV1", {
            "schema_name": "StrictToolShapeObservationV1",
            "schema_version": 1,
            "schema_sha256": domain_sha256(
                "novel-flywheel-strict-tool-shape-observation-json-schema-v1",
                schema,
            ),
            "raw_content_allowed": False,
            "missing_snapshot_zero_inference_allowed": False,
            "three_layer_correlation_required": True,
        },
    )


def _adapter_coverage_definition() -> dict[str, Any]:
    adapters = [
        {
            "adapter_id": adapter_id,
            "adapter_version": 1,
            "adapter_manifest_sha256": adapter_manifest_sha256(adapter_id, 1),
            "provider_raw_snapshot": "covered",
            "adapter_normalized_projection": "covered",
            "gateway_decision_correlation": "covered",
        }
        for adapter_id in ("anthropic", "openai_chat", "openai_responses")
    ]
    return _definition(
        "novel-flywheel-pa-strict-tool-adapter-coverage-v1",
        "PAStrictToolAdapterCoverageV1", adapters,
    )


def _production_source_clean() -> tuple[bool | None, str]:
    build, children = collect_build_fingerprint()
    refs = build["payload"]["child_definitions"]
    ref = refs.get("git_provenance")
    if not isinstance(ref, Mapping):
        return None, build["payload"]["build_fingerprint_sha256"]
    match = next((
        item for item in children
        if item.get("schema") == ref.get("schema")
        and item.get("definition_sha256") == ref.get("definition_sha256")
    ), None)
    if not isinstance(match, Mapping):
        return None, build["payload"]["build_fingerprint_sha256"]
    return (
        not bool(match["payload"].get("production_source_dirty")),
        build["payload"]["build_fingerprint_sha256"],
    )


def _privacy_scan(
    documents: Mapping[str, Mapping[str, Any]], *, fixture: Mapping[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    private_literals = [
        str(fixture.get(name) or "")
        for name in ("title", "premise", "outline")
    ]

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = str(raw_key).casefold()
                if key in _FORBIDDEN_PRIVACY_KEYS:
                    violations.append(f"forbidden_key:{path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            if _ABSOLUTE_PATH.search(value):
                violations.append(f"absolute_path:{path}")
            lowered = value.casefold()
            if "bearer " in lowered or "api-key" in lowered:
                violations.append(f"credential_or_header:{path}")
            if any(literal and literal in value for literal in private_literals):
                violations.append(f"fixture_business_content:{path}")

    for name, document in documents.items():
        walk(document, name)
    body = {
        "status": "exact" if not violations else "blocked",
        "policy": "hash_shape_count_only_v1",
        "documents_scanned": sorted(documents),
        "violation_count": len(violations),
        "violation_codes": sorted(set(violations)),
    }
    return {
        **body,
        "privacy_scan_sha256": domain_sha256(
            "novel-flywheel-pa-strict-tool-privacy-scan-v1", body,
        ),
    }


def _base_plan(
    *, live_database_path: Path, fixture_path: Path,
    cohort_id: str, run_namespace: str, now: datetime, temporary_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with _diagnostic_environment():
        base_plan, _approval, packet = prepare_c0b_smoke_packet(
            live_database_path=live_database_path,
            fixture_path=fixture_path,
            plan_path=temporary_root / "base-plan.json",
            approval_path=temporary_root / "base-approval.json",
            packet_path=temporary_root / "base-packet.json",
            cohort_id=cohort_id,
            run_namespace=run_namespace,
            now=now,
        )
    return base_plan, packet


def _build_plan(
    base_plan: Mapping[str, Any], *, target: Mapping[str, Any],
    schema_definition: Mapping[str, Any],
    adapter_coverage: Mapping[str, Any], budgets: Mapping[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(dict(base_plan))
    payload.pop("plan_sha256", None)
    profile = approval_profile(PA_PROFILE_ID)
    payload["canary_mode"] = profile.canary_mode
    payload["feature_flag_snapshot"] = deepcopy(FEATURE_FLAGS)
    payload["workloads"][0].update({
        "maximum_model_calls": 24,
        "maximum_output_tokens": 500_000,
        "success_definition": "TARGET_STRICT_TOOL_SHAPE_OBSERVED",
        "controlled_outcomes": [
            "TARGET_STRICT_TOOL_SHAPE_OBSERVED",
            "TARGET_NOT_REACHED",
            "CONTROLLED_PROVIDER_CAPABILITY_OUTCOME",
        ],
        "terminal_outcomes": ["workflow_terminal"],
    })
    elapsed_hash = budgets["elapsed"]["definition_sha256"]
    current_topology_hash = payload["budgets"]["call_topology_sha256"]
    payload["budgets"] = {
        "maximum_runs": 1,
        "maximum_model_calls_per_run": 24,
        "maximum_total_model_calls": 24,
        "maximum_input_tokens": 500_000,
        "maximum_output_tokens": 500_000,
        "pricing_status": "verified_identity_price_bounded_capability_unknown",
        "currency": "MULTI_CURRENCY_NO_FX",
        "maximum_estimated_cost_microunits": 0,
        "maximum_elapsed_seconds": 7_200,
        "gate_wait_timeout_seconds": 120,
        "monetary_budget": {
            "schema": "CanaryMonetaryBudgetV1",
            "maximum_usd_cost_microunits": 10_000_000,
            "maximum_cny_cost_microunits": 25_000_000,
            "approved_fx_snapshot": None,
        },
        "price_catalog_sha256": base_plan["budgets"]["price_catalog_sha256"],
        "call_topology_sha256": current_topology_hash,
        "elapsed_budget_sha256": elapsed_hash,
        "worst_case_chargeable": True,
    }
    payload["stop_conditions"] = list(STOP_CONDITIONS)
    payload["report_policy"] = {
        "raw_content_included": False,
        "hash_only": True,
        "shape_and_count_metadata_allowed": True,
        "machine_specific_paths_included": False,
        "full_provider_request_id_included": False,
    }
    payload["pa_strict_tool_observation_policy"] = {
        "canary_id": CANARY_ID,
        "profile_id": profile.profile_id,
        "profile_definition_sha256": profile.profile_definition_sha256,
        "approval_scope": profile.approval_scope,
        "target": deepcopy(target),
        "target_filter_sha256": domain_sha256(
            "novel-flywheel-pa-strict-tool-target-filter-v1", target,
        ),
        "observation_schema_sha256": schema_definition["payload"][
            "schema_sha256"
        ],
        "observation_schema_definition_sha256": schema_definition[
            "definition_sha256"
        ],
        "adapter_coverage_definition_sha256": adapter_coverage[
            "definition_sha256"
        ],
        "observation_goal_success": "TARGET_STRICT_TOOL_SHAPE_OBSERVED",
        "target_not_reached_outcome": "TARGET_NOT_REACHED",
        "workflow_outcome_independent": True,
        "request_provider_adapter_gateway_correlation_required": True,
        "missing_snapshot_zero_inference_allowed": False,
        "maximum_runs": 1,
        "second_run_allowed": False,
        "runtime_behavior_mutation_allowed": False,
        "budget_definition_hashes": {
            name: definition["definition_sha256"]
            for name, definition in budgets.items()
        },
    }
    return build_canary_experiment_plan_v1(payload)


def _build_candidate(
    *, plan: Mapping[str, Any], materialized_at: datetime,
    window_start: datetime, window_end: datetime, cohort_id: str,
    definitions: Mapping[str, Any],
) -> dict[str, Any]:
    policy = plan["pa_strict_tool_observation_policy"]
    workload = plan["workloads"][0]
    profile = approval_profile(PA_PROFILE_ID)
    budget_hashes = policy["budget_definition_hashes"]
    approved_budget = {
        **profile.budget(),
        "definition_sha256": definitions["budget_manifest"][
            "definition_sha256"
        ],
    }
    body = {
        "status": "waiting_for_final_user_authorization",
        "approval_scope": profile.approval_scope,
        "approved_plan_sha256": plan["plan_sha256"],
        "approved_launcher_sha256": plan["launcher_sha256"],
        "approved_workload_sha256": workload["fixture_sha256"],
        "approved_workload_manifest_hash": plan["workload_manifest_hash"],
        "approved_workload_id": workload["workload_id"],
        "approved_build_fingerprint": plan["approved_build_fingerprint"],
        "approved_execution_config_fingerprint": plan[
            "approved_execution_config_fingerprint"
        ],
        "approved_runtime_execution_fingerprint": plan[
            "expected_runtime_execution_fingerprint"
        ],
        "runtime_mode": plan["runtime_mode"],
        "provider_descriptor_hash": plan[
            "provider_descriptor_definition_sha256"
        ],
        "model_role_binding_manifest_hash": plan[
            "role_binding_manifest_definition_sha256"
        ],
        "pricing_evidence_manifest_hash": plan["budgets"][
            "price_catalog_sha256"
        ],
        "feature_flag_snapshot_hash": definitions["feature"][
            "definition_sha256"
        ],
        "target_filter_sha256": policy["target_filter_sha256"],
        "observation_schema_sha256": policy["observation_schema_sha256"],
        "observation_schema_definition_sha256": policy[
            "observation_schema_definition_sha256"
        ],
        "adapter_coverage_definition_sha256": policy[
            "adapter_coverage_definition_sha256"
        ],
        "call_budget_definition_sha256": budget_hashes["call"],
        "token_budget_definition_sha256": budget_hashes["token"],
        "monetary_budget_definition_sha256": budget_hashes["monetary"],
        "elapsed_budget_definition_sha256": budget_hashes["elapsed"],
        "budget_definition_sha256": definitions["budget_manifest"][
            "definition_sha256"
        ],
        "stop_condition_manifest_hash": definitions["stop"][
            "definition_sha256"
        ],
        "canary_root_identity_candidate": plan["isolation"][
            "stable_root_identity"
        ],
        "single_use_cohort_id": cohort_id,
        "maximum_executions": 1,
        "usage_status": "unused",
        "consumed_evidence_sha256": None,
        "materialized_at": _utc(materialized_at),
        "execution_window": {
            "not_before": _utc(window_start),
            "not_after": _utc(window_end),
        },
        "approval_expiry": _utc(window_end),
        "named_approver": "USER_CONFIRMATION_REQUIRED",
        "authorize_credential_lookup": False,
        "authorize_provider_client_creation": False,
        "authorize_network": False,
        "authorize_paid_model_calls": False,
        "authorized_actions": {
            "credential_lookup": False,
            "provider_client_creation": False,
            "network": False,
            "paid_model_calls": False,
            "fake_boundary": False,
        },
        "execution_authorized": False,
        "phase1b_enabled": False,
        "maximum_runs": 1,
        "expected_model_calls": 11,
        "maximum_model_calls_per_run": 24,
        "maximum_total_model_calls": 24,
        "maximum_input_tokens": 500_000,
        "maximum_output_tokens": 500_000,
        "maximum_output_tokens_per_call": 32_000,
        "maximum_usd_cost_microunits": 10_000_000,
        "maximum_cny_cost_microunits": 25_000_000,
        "maximum_elapsed_seconds": 7_200,
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
        "signed_approval_materialized": False,
        "execution_performed": False,
        "approved_budget": approved_budget,
    }
    return build_pa_final_approval_candidate_v1(body)


def validate_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_pa_final_approval_candidate_v1(candidate)
    except CanaryContractError as exc:
        reason = exc.reason_code
        if reason.startswith("approval_candidate_"):
            reason = reason.removeprefix("approval_")
        raise PAStrictToolObsMaterializationError(reason) from exc


def _build_patch_template(
    *, plan: Mapping[str, Any], candidate: Mapping[str, Any],
) -> dict[str, Any]:
    del plan
    return build_pa_authorization_patch_template_v2(candidate)


def _build_preview(
    *, plan: Mapping[str, Any], candidate: Mapping[str, Any],
    patch: Mapping[str, Any], artifact_root_label: str,
    paths: Mapping[str, Path],
) -> dict[str, Any]:
    label = artifact_root_label.rstrip("/")
    body = {
        "schema": PREVIEW_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "bound_plan_sha256": plan["plan_sha256"],
        "bound_approval_candidate_sha256": candidate[
            "approval_candidate_sha256"
        ],
        "bound_authorization_patch_template_sha256": patch[
            "authorization_patch_template_sha256"
        ],
        "bound_launcher_sha256": plan["launcher_sha256"],
        "bound_workload_sha256": candidate["approved_workload_sha256"],
        "single_use_cohort_id": candidate["single_use_cohort_id"],
        "future_signed_approval_schema": FUTURE_SIGNED_APPROVAL_SCHEMA,
        "future_signed_approval_file": "${PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL}",
        "future_confirmed_authorization_patch_file": (
            "${PA_STRICT_TOOL_OBS_1_CONFIRMED_AUTHORIZATION_PATCH}"
        ),
        "plan_file": f"{label}/{paths['plan'].name}",
        "approval_candidate_file": f"{label}/{paths['candidate'].name}",
        "authorization_patch_template_file": f"{label}/{paths['patch'].name}",
        "canary_root": "${PA_STRICT_TOOL_OBS_1_CANARY_ROOT}",
        "approval_ledger_root": "${PA_STRICT_TOOL_OBS_1_APPROVAL_LEDGER_ROOT}",
        "future_command_argv": [
            ".venv/Scripts/python.exe", "-m", "tools.canary.launcher",
            "--plan", f"{label}/{paths['plan'].name}",
            "--approval", "${PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL}",
            "--approved-plan-sha256", plan["plan_sha256"],
            "--real-run", "--workload-fixture",
            "tests/fixtures/canary/short-normal-v1.json",
            "--canary-root", "${PA_STRICT_TOOL_OBS_1_CANARY_ROOT}",
            "--approval-ledger-root",
            "${PA_STRICT_TOOL_OBS_1_APPROVAL_LEDGER_ROOT}",
        ],
        "execution_authorized": False,
        "do_not_execute": True,
        "candidate_is_executable_approval": False,
        "signed_approval_materialized": False,
        "credential_material_included": False,
    }
    return _sealed(PREVIEW_DOMAIN, body, "preview_sha256")


def _check(name: str, exact: bool, reason: str, digest: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "exact" if exact else "blocked",
        "reason_code": None if exact else reason,
        "definition_sha256": digest,
    }


def _validate_only(
    *, plan: Mapping[str, Any], candidate: Mapping[str, Any],
    patch: Mapping[str, Any], preview: Mapping[str, Any],
    definitions: Mapping[str, Any], fixture_path: Path,
    live_database_path: Path, cohort_id: str, run_namespace: str,
    now: datetime, temporary_root: Path, privacy: Mapping[str, Any],
    parity_before: Mapping[str, Any], parity_after: Mapping[str, Any],
    network_count: int,
) -> dict[str, Any]:
    regenerated, packet = _base_plan(
        live_database_path=live_database_path,
        fixture_path=fixture_path,
        cohort_id=cohort_id,
        run_namespace=run_namespace,
        now=now,
        temporary_root=temporary_root / "revalidation",
    )
    regenerated_plan = _build_plan(
        regenerated,
        target=TARGET,
        schema_definition=definitions["schema"],
        adapter_coverage=definitions["adapter"],
        budgets=definitions["budgets"],
    )
    source_clean, current_build = _production_source_clean()
    policy = plan["pa_strict_tool_observation_policy"]
    candidate_valid = True
    try:
        validate_candidate(candidate)
    except Exception:
        candidate_valid = False
    window = candidate["execution_window"]
    external_false = all(candidate[name] is False for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls",
        "execution_authorized",
    ))
    checks = [
        _check("plan_canonical_hash", regenerated_plan["plan_sha256"] == plan["plan_sha256"], "plan_hash_mismatch", plan["plan_sha256"]),
        _check("approval_candidate_canonical_hash", candidate_valid, "candidate_invalid", candidate["approval_candidate_sha256"]),
        _check("authorization_patch_template_binding", patch["bound_approval_candidate_sha256"] == candidate["approval_candidate_sha256"] and patch["execution_authorized"] is False, "patch_template_binding_invalid", patch["authorization_patch_template_sha256"]),
        _check("execution_preview_future_signed_approval_binding", preview["future_signed_approval_schema"] == FUTURE_SIGNED_APPROVAL_SCHEMA and preview["do_not_execute"] is True and preview["execution_authorized"] is False, "preview_binding_invalid", preview["preview_sha256"]),
        _check("launcher_bytes_hash", regenerated_plan["launcher_sha256"] == plan["launcher_sha256"], "launcher_hash_mismatch", plan["launcher_sha256"]),
        _check("workload_bytes_hash", file_sha256(fixture_path) == candidate["approved_workload_sha256"], "workload_hash_mismatch", candidate["approved_workload_sha256"]),
        _check("production_source_clean", source_clean is True, "production_source_dirty_or_unknown", current_build),
        _check("build_fingerprint", current_build == plan["approved_build_fingerprint"] == packet["build_fingerprint"], "build_fingerprint_mismatch", current_build),
        _check("execution_config_fingerprint", regenerated_plan["approved_execution_config_fingerprint"] == plan["approved_execution_config_fingerprint"], "execution_config_fingerprint_mismatch", plan["approved_execution_config_fingerprint"]),
        _check("runtime_execution_fingerprint", regenerated_plan["expected_runtime_execution_fingerprint"] == plan["expected_runtime_execution_fingerprint"], "runtime_execution_fingerprint_mismatch", plan["expected_runtime_execution_fingerprint"]),
        _check("diagnostic_feature_flags", plan["feature_flag_snapshot"] == FEATURE_FLAGS and candidate["feature_flag_snapshot_hash"] == definitions["feature"]["definition_sha256"], "feature_flag_snapshot_mismatch", definitions["feature"]["definition_sha256"]),
        _check("phase1b_disabled", plan["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] is False and plan["feature_flag_snapshot"]["project_short_canonical_v2"] is False, "phase1b_enabled"),
        _check("exact_target_filter", policy["target"] == TARGET and policy["target_filter_sha256"] == domain_sha256("novel-flywheel-pa-strict-tool-target-filter-v1", TARGET), "target_filter_mismatch", policy["target_filter_sha256"]),
        _check("strict_tool_observation_schema", policy["observation_schema_sha256"] == definitions["schema"]["payload"]["schema_sha256"], "observation_schema_mismatch", policy["observation_schema_sha256"]),
        _check("provider_snapshot_adapter_coverage", policy["adapter_coverage_definition_sha256"] == definitions["adapter"]["definition_sha256"] and all(item["provider_raw_snapshot"] == "covered" for item in definitions["adapter"]["payload"]), "adapter_coverage_mismatch", definitions["adapter"]["definition_sha256"]),
        _check("provider_descriptor_manifest", regenerated_plan["provider_descriptor_definition_sha256"] == plan["provider_descriptor_definition_sha256"], "provider_descriptor_mismatch", plan["provider_descriptor_definition_sha256"]),
        _check("role_route_binding_manifest", regenerated_plan["role_binding_manifest_definition_sha256"] == plan["role_binding_manifest_definition_sha256"], "route_manifest_mismatch", plan["role_binding_manifest_definition_sha256"]),
        _check("pricing_evidence_manifest", regenerated_plan["budgets"]["price_catalog_sha256"] == plan["budgets"]["price_catalog_sha256"], "pricing_manifest_mismatch", plan["budgets"]["price_catalog_sha256"]),
        _check("budget_definition", candidate["budget_definition_sha256"] == definitions["budget_manifest"]["definition_sha256"] and candidate["maximum_total_model_calls"] == 24 and candidate["maximum_input_tokens"] == 500_000 and candidate["maximum_output_tokens"] == 500_000, "budget_definition_mismatch", candidate["budget_definition_sha256"]),
        _check("stop_condition_manifest", tuple(plan["stop_conditions"]) == STOP_CONDITIONS and candidate["stop_condition_manifest_hash"] == definitions["stop"]["definition_sha256"], "stop_condition_mismatch", definitions["stop"]["definition_sha256"]),
        _check("canary_root_absent", not (temporary_root / "future-canary-root").exists(), "canary_root_not_absent", plan["isolation"]["stable_root_identity"]),
        _check("cohort_unused", candidate["usage_status"] == "unused" and candidate["consumed_evidence_sha256"] is None and not (temporary_root / "approval-ledger" / cohort_id).exists(), "cohort_not_unused"),
        _check("execution_window_future", now < _parse_utc(window["not_before"]) < _parse_utc(window["not_after"]) <= _parse_utc(candidate["approval_expiry"]), "execution_window_invalid"),
        _check("external_actions_disabled", external_false, "external_action_authorized", domain_sha256("novel-flywheel-pa-strict-tool-external-actions-v1", external_false)),
        _check("signed_approval_absent", candidate["signed_approval_materialized"] is False and preview["signed_approval_materialized"] is False, "signed_approval_present"),
        _check("privacy_scan", privacy["status"] == "exact", "privacy_violation", privacy["privacy_scan_sha256"]),
        _check("live_artifact_parity", parity_equal(dict(parity_before), dict(parity_after)), "live_parity_mismatch", parity_after["parity_sha256"]),
        _check("network_sentinel", network_count == 0, "network_call_observed"),
    ]
    counters = {**EXTERNAL_COUNTERS, "network_call_count": network_count}
    body = {
        "schema": RECEIPT_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "overall_status": "exact" if all(item["status"] == "exact" for item in checks) else "blocked",
        "ordered_checks": checks,
        "external_action_counters": counters,
        "privacy": deepcopy(dict(privacy)),
        "parity": {
            "status": "exact" if parity_equal(dict(parity_before), dict(parity_after)) else "changed",
            "before_sha256": parity_before["parity_sha256"],
            "after_sha256": parity_after["parity_sha256"],
        },
        "approval_state": "disabled_candidate_no_signed_approval",
        "execution_performed": False,
        "validated_at": _utc(now),
    }
    return _sealed(RECEIPT_DOMAIN, body, "validation_receipt_sha256")


def materialize_pa_strict_tool_obs_1(
    *, live_database_path: Path, live_project_root: Path,
    fixture_path: Path, output_root: Path, cohort_id: str,
    run_namespace: str, artifact_root_label: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize and validate an inert package; never create authorization."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current + timedelta(minutes=15)
    window_end = window_start + timedelta(hours=48)
    _require(
        re.fullmatch(r"pa-strict-tool-obs-1-[a-z0-9._-]{8,80}", cohort_id)
        is not None,
        "single_use_cohort_id_invalid",
    )
    _require(run_namespace == cohort_id, "run_namespace_must_match_cohort")
    paths = {
        "plan": output_root / "pa-strict-tool-obs-1-plan-v1.json",
        "candidate": output_root / "pa-strict-tool-obs-1-final-approval-candidate-v1.json",
        "patch": output_root / "pa-strict-tool-obs-1-user-authorization-patch-template-v1.json",
        "preview": output_root / "pa-strict-tool-obs-1-execution-command-preview-v1.json",
        "receipt": output_root / "pa-strict-tool-obs-1-validate-only-receipt-v1.json",
        "index": output_root / "pa-strict-tool-obs-1-materialization-index-v1.json",
    }
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    before = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )
    sentinel = FailClosedNetworkSentinel()
    with tempfile.TemporaryDirectory(prefix="novel-pa-strict-tool-materialize-") as temporary:
        temporary_root = Path(temporary)
        with sentinel:
            base_plan, _base_packet = _base_plan(
                live_database_path=live_database_path,
                fixture_path=fixture_path,
                cohort_id=cohort_id,
                run_namespace=run_namespace,
                now=current,
                temporary_root=temporary_root / "base",
            )
        budgets = _budget_definitions()
        definitions: dict[str, Any] = {
            "budgets": budgets,
            "feature": _definition(
                "novel-flywheel-pa-strict-tool-feature-flags-v1",
                "PAStrictToolObs1FeatureFlagSnapshotV1", FEATURE_FLAGS,
            ),
            "target": _definition(
                "novel-flywheel-pa-strict-tool-target-filter-v1",
                "PAStrictToolObs1TargetFilterV1", TARGET,
            ),
            "schema": _observation_schema_definition(),
            "adapter": _adapter_coverage_definition(),
            "stop": _definition(
                "novel-flywheel-pa-strict-tool-stop-conditions-v1",
                "PAStrictToolObs1StopConditionManifestV1",
                list(STOP_CONDITIONS),
            ),
        }
        definitions["budget_manifest"] = _definition(
            "novel-flywheel-pa-strict-tool-budget-manifest-v1",
            "PAStrictToolObs1BudgetManifestV1", {
                name: value["definition_sha256"]
                for name, value in budgets.items()
            },
        )
        plan = _build_plan(
            base_plan,
            target=TARGET,
            schema_definition=definitions["schema"],
            adapter_coverage=definitions["adapter"],
            budgets=budgets,
        )
        candidate = _build_candidate(
            plan=plan,
            materialized_at=current,
            window_start=window_start,
            window_end=window_end,
            cohort_id=cohort_id,
            definitions=definitions,
        )
        validate_candidate(candidate)
        patch = _build_patch_template(plan=plan, candidate=candidate)
        preview = _build_preview(
            plan=plan,
            candidate=candidate,
            patch=patch,
            artifact_root_label=artifact_root_label,
            paths=paths,
        )
        documents = {
            "plan": plan,
            "candidate": candidate,
            "patch": patch,
            "preview": preview,
        }
        privacy = _privacy_scan(documents, fixture=fixture)
        for name, document in documents.items():
            _write(paths[name], document)
        after = live_parity_manifest(
            database_path=live_database_path, project_root=live_project_root,
        )
        with sentinel:
            receipt = _validate_only(
                plan=plan,
                candidate=candidate,
                patch=patch,
                preview=preview,
                definitions=definitions,
                fixture_path=fixture_path,
                live_database_path=live_database_path,
                cohort_id=cohort_id,
                run_namespace=run_namespace,
                now=current,
                temporary_root=temporary_root,
                privacy=privacy,
                parity_before=before,
                parity_after=after,
                network_count=sentinel.network_call_count,
            )
        _write(paths["receipt"], receipt)
    _require(sentinel.network_call_count == 0, "materialization_network_observed")
    _require(receipt["overall_status"] == "exact", "validate_only_blocked")
    index_body = {
        "schema": INDEX_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "contract_status": "PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL_PROFILE_READY",
        "status": "PA_STRICT_TOOL_OBS_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION",
        "files": {
            path.name: file_sha256(path)
            for key, path in sorted(paths.items()) if key != "index"
        },
        "plan_sha256": plan["plan_sha256"],
        "approval_candidate_sha256": candidate["approval_candidate_sha256"],
        "launcher_sha256": plan["launcher_sha256"],
        "workload_sha256": candidate["approved_workload_sha256"],
        "validation_receipt_sha256": receipt["validation_receipt_sha256"],
        "single_use_cohort_id": cohort_id,
        "external_action_counters": receipt["external_action_counters"],
        "privacy_status": receipt["privacy"]["status"],
        "parity_status": receipt["parity"]["status"],
        "signed_approval_materialized": False,
        "execution_performed": False,
    }
    index = _sealed(INDEX_DOMAIN, index_body, "definition_sha256")
    _write(paths["index"], index)
    return {
        "plan": plan,
        "approval_candidate": candidate,
        "authorization_patch_template": patch,
        "execution_command_preview": preview,
        "validation_receipt": receipt,
        "index": index,
        "paths": paths,
        "execution_performed": False,
    }


def _parse_utc_argument(value: str) -> datetime:
    try:
        return _parse_utc(value)
    except PAStrictToolObsMaterializationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize inert PA-STRICT-TOOL-OBS-1 approval evidence",
    )
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-project-root", type=Path, required=True)
    parser.add_argument("--workload-fixture", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--run-namespace", required=True)
    parser.add_argument("--artifact-root-label", required=True)
    parser.add_argument("--materialized-at", type=_parse_utc_argument)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = materialize_pa_strict_tool_obs_1(
        live_database_path=args.live_database,
        live_project_root=args.live_project_root,
        fixture_path=args.workload_fixture,
        output_root=args.output_root,
        cohort_id=args.cohort_id,
        run_namespace=args.run_namespace,
        artifact_root_label=args.artifact_root_label,
        now=args.materialized_at,
    )
    summary = {
        "status": result["index"]["status"],
        "plan_sha256": result["plan"]["plan_sha256"],
        "approval_candidate_sha256": result["approval_candidate"][
            "approval_candidate_sha256"
        ],
        "validation_status": result["validation_receipt"]["overall_status"],
        "external_action_counters": result["validation_receipt"][
            "external_action_counters"
        ],
        "execution_performed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["validation_status"] == "exact" else 4


if __name__ == "__main__":
    raise SystemExit(main())
