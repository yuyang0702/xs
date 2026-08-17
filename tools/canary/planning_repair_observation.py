"""Offline-only R1-PTR2 Planning repair observation packet materializer."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from novel_flywheel.planning_adaptation import (
    planning_repair_patch_diagnostic_policy_sha256,
)
from novel_flywheel.planning_repair_diagnostics import (
    PlanningRepairDomainValidationSnapshotV1,
    PlanningRepairFindingPropagationSnapshotV1,
    PlanningRepairOutputLimitObservationV1,
    ProviderContentBlockShapeSnapshotV1,
)
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
    approval_profile,
)
from .approval_store import initialize_approval_ledger_v1
from .artifact_hash import file_sha256, live_parity_manifest, parity_equal
from .c0b_packet import prepare_c0b_smoke_packet
from .contracts import build_canary_experiment_plan_v1
from .environment import c0a_environment
from .network_sentinel import FailClosedNetworkSentinel
from .pa_strict_tool_obs import _privacy_scan, _production_source_clean
from .planning_repair_approval import (
    build_planning_repair_observation_candidate_v1,
    build_planning_repair_observation_patch_template_v1,
    validate_planning_repair_observation_candidate_v1,
)


CANARY_ID = "R1-PTR2-PLANNING-REPAIR-OBSERVATION-1"
PROFILE_ID = PLANNING_REPAIR_OBSERVATION_PROFILE_ID
PROFILE = approval_profile(PROFILE_ID)
APPROVAL_SCOPE = PROFILE.approval_scope

FEATURE_FLAGS = PROFILE.required_flags()
TARGET = PROFILE.target_filter()
STOP_CONDITIONS = PROFILE.stop_condition_policy

EXTERNAL_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}

_COHORT = re.compile(
    r"planning-repair-observation-1-[a-z0-9._-]{8,96}"
)


class PlanningRepairObservationMaterializationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PlanningRepairObservationMaterializationError(reason)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _definition(
    domain: str, schema: str, payload: Any,
) -> dict[str, Any]:
    body = {
        "schema": schema, "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload": deepcopy(payload),
    }
    return {**body, "definition_sha256": domain_sha256(domain, body)}


def _sealed(
    domain: str, body: Mapping[str, Any], digest_field: str,
) -> dict[str, Any]:
    value = deepcopy(dict(body))
    value[digest_field] = domain_sha256(domain, value)
    return value


def _budget_definitions() -> dict[str, dict[str, Any]]:
    budget = PROFILE.budget()
    call = _definition(
        "novel-flywheel-r1-ptr2-call-budget-v1",
        "PlanningRepairObservationCallBudgetV1", {
            "maximum_runs": budget["maximum_runs"],
            "expected_model_calls": budget["expected_model_calls"],
            "maximum_model_calls_per_run": budget[
                "maximum_model_calls_per_run"
            ],
            "maximum_total_model_calls": budget["maximum_total_model_calls"],
            "maximum_output_tokens_per_call": budget[
                "maximum_output_tokens_per_call"
            ],
            "first_terminal_stop": True,
            "resume_after_terminal": False,
            "second_run_allowed": False,
        },
    )
    token = _definition(
        "novel-flywheel-r1-ptr2-token-budget-v1",
        "PlanningRepairObservationTokenBudgetV1", {
            "maximum_input_tokens": budget["maximum_input_tokens"],
            "maximum_output_tokens": budget["maximum_output_tokens"],
            "maximum_output_tokens_per_call": budget[
                "maximum_output_tokens_per_call"
            ],
            "production_per_attempt_budget_mutation_allowed": False,
        },
    )
    monetary = _definition(
        "novel-flywheel-r1-ptr2-monetary-budget-v1",
        "PlanningRepairObservationMonetaryBudgetV1", {
            "maximum_usd_cost_microunits": budget[
                "maximum_usd_cost_microunits"
            ],
            "maximum_cny_cost_microunits": budget[
                "maximum_cny_cost_microunits"
            ],
            "approved_fx_snapshot": None,
        },
    )
    elapsed = _definition(
        "novel-flywheel-r1-ptr2-elapsed-budget-v1",
        "PlanningRepairObservationElapsedBudgetV1", {
            "maximum_elapsed_seconds": budget["maximum_elapsed_seconds"],
        },
    )
    manifest = _definition(
        "novel-flywheel-r1-ptr2-budget-manifest-v1",
        "PlanningRepairObservationBudgetManifestV1", {
            "canary_outer_caps": {
                name: value for name, value in budget.items()
            },
            "definition_sha256s": {
                "call": call["definition_sha256"],
                "token": token["definition_sha256"],
                "monetary": monetary["definition_sha256"],
                "elapsed": elapsed["definition_sha256"],
            },
            "production_internal_repair_policy_changed": False,
        },
    )
    return {
        "call": call, "token": token, "monetary": monetary,
        "elapsed": elapsed, "manifest": manifest,
    }


def _instrumentation_definitions() -> dict[str, Any]:
    models = {
        "domain_validation": PlanningRepairDomainValidationSnapshotV1,
        "finding_propagation": PlanningRepairFindingPropagationSnapshotV1,
        "provider_content_block_shape": ProviderContentBlockShapeSnapshotV1,
        "output_limit": PlanningRepairOutputLimitObservationV1,
    }
    definitions = {
        name: _definition(
            f"novel-flywheel-r1-ptr2-{name}-schema-v1",
            f"PlanningRepairObservation{name.title().replace('_', '')}DefinitionV1",
            {
                "schema_name": model.__name__,
                "json_schema_sha256": domain_sha256(
                    f"novel-flywheel-r1-ptr2-{name}-json-schema-v1",
                    model.model_json_schema(by_alias=True),
                ),
                "raw_prompt_allowed": False,
                "raw_story_allowed": False,
                "raw_normalized_payload_allowed": False,
                "raw_tool_arguments_allowed": False,
                "raw_provider_response_allowed": False,
            },
        )
        for name, model in models.items()
    }
    bundle = _definition(
        "novel-flywheel-r1-ptr2-instrumentation-bundle-v1",
        "PlanningRepairInstrumentationDefinitionBundleV1", {
            "feature_flag": "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1",
            "feature_flag_value": True,
            "fail_open": True,
            "hash_shape_count_only": True,
            "definitions": {
                name: value["definition_sha256"]
                for name, value in definitions.items()
            },
        },
    )
    return {"definitions": definitions, "bundle": bundle}


def _goal_definition() -> dict[str, Any]:
    return _definition(
        "novel-flywheel-r1-ptr2-observation-goal-v1",
        "PlanningRepairObservationGoalDefinitionV1", {
            "primary_evidence": [
                "first_real_planning_repair_domain_failure",
                "next_targeted_repair_finding_propagation",
            ],
            "terminal_amplifier_if_naturally_reached": [
                "first_plain_fallback_provider_content_block_shape",
                "first_planning_repair_output_limit",
            ],
            "synthetic_target_injection_allowed": False,
            "prompt_or_route_mutation_allowed": False,
            "safe_stop": {
                "primary_plus_amplifier": "before_next_provider_dispatch",
                "primary_without_amplifier": "before_next_major_stage_dispatch",
                "target_not_exercised": "before_next_major_stage_dispatch",
                "first_terminal": "preserve_typed_root_cause",
            },
            "stop_outcome": "CANARY_OBSERVATION_GOAL_REACHED_STOPPED",
            "not_exercised_outcome": (
                "PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED"
            ),
        },
    )


def _definitions() -> dict[str, Any]:
    from .planning_repair_closure import (
        planning_repair_observation_closure_definition_v1,
    )

    budgets = _budget_definitions()
    instrumentation = _instrumentation_definitions()
    goal = _goal_definition()
    closure = planning_repair_observation_closure_definition_v1()
    feature = _definition(
        "novel-flywheel-r1-ptr2-feature-flags-v1",
        "PlanningRepairObservationFeatureFlagSnapshotV1", FEATURE_FLAGS,
    )
    target = _definition(
        "novel-flywheel-r1-ptr2-target-filter-v1",
        "PlanningRepairObservationTargetFilterV1", TARGET,
    )
    stop = _definition(
        "novel-flywheel-r1-ptr2-stop-conditions-v1",
        "PlanningRepairObservationStopConditionManifestV1",
        list(STOP_CONDITIONS),
    )
    validator = _definition(
        "novel-flywheel-r1-ptr2-domain-validator-policy-v1",
        "PlanningRepairDomainValidatorPolicyBindingV1", {
            "validator_id": "planning_repair_patch.normalize.v1",
            "diagnostic_policy_sha256": (
                planning_repair_patch_diagnostic_policy_sha256()
            ),
            "decision_semantics_changed": False,
        },
    )
    production_budget = _definition(
        "novel-flywheel-r1-ptr2-production-repair-budget-parity-v1",
        "PlanningRepairProductionBudgetParityV1", {
            "characterization_sequence": [1977, 1977, 1977, 3954],
            "source": "r1_ptr1_production_shaped_offline_parity",
            "runtime_policy_modified_by_canary": False,
            "counterfactual_enabled": False,
        },
    )
    prompt = _definition(
        "novel-flywheel-r1-ptr2-prompt-request-parity-v1",
        "PlanningRepairPromptRequestParityBindingV1", {
            "r1_ptr1_request_manifest_sha256": (
                "7f4d224c1c81e98e0b1b95b217414b8678b08ab8ca949cb399837236e363b852"
            ),
            "diagnostic_flag_request_semantic_delta": False,
            "raw_prompt_included": False,
        },
    )
    return {
        "budgets": budgets, "instrumentation": instrumentation,
        "goal": goal, "closure": closure,
        "feature": feature, "target": target,
        "stop": stop, "validator": validator,
        "production_budget": production_budget, "prompt": prompt,
    }


def _prepare_base(
    *, live_database_path: Path, fixture_path: Path, cohort_id: str,
    run_namespace: str, now: datetime, temporary_root: Path,
) -> dict[str, Any]:
    with c0a_environment(
        temporary_root / "environment", feature_flags=FEATURE_FLAGS,
    ):
        plan, _approval, _packet = prepare_c0b_smoke_packet(
            live_database_path=live_database_path,
            fixture_path=fixture_path,
            plan_path=temporary_root / "base-plan.json",
            approval_path=temporary_root / "base-approval.json",
            packet_path=temporary_root / "base-packet.json",
            cohort_id=cohort_id, run_namespace=run_namespace, now=now,
            feature_flags=FEATURE_FLAGS,
        )
    return plan


def _build_plan(
    base: Mapping[str, Any], definitions: Mapping[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(dict(base))
    payload.pop("plan_sha256", None)
    budget = PROFILE.budget()
    payload["canary_mode"] = PROFILE.canary_mode
    payload["runtime_fingerprint_policy_version"] = "runtime-fingerprint-v2"
    payload["feature_flag_snapshot"] = deepcopy(FEATURE_FLAGS)
    payload["workloads"][0].update({
        "maximum_model_calls": budget["maximum_total_model_calls"],
        "maximum_output_tokens": budget["maximum_output_tokens"],
        "success_definition": "PRIMARY_EVIDENCE_CAPTURED",
        "controlled_outcomes": list(PROFILE.observation_goal_outcomes),
        "terminal_outcomes": ["workflow_terminal"],
    })
    payload["budgets"].update({
        "maximum_runs": budget["maximum_runs"],
        "expected_model_calls": budget["expected_model_calls"],
        "maximum_model_calls_per_run": budget[
            "maximum_model_calls_per_run"
        ],
        "maximum_total_model_calls": budget["maximum_total_model_calls"],
        "maximum_input_tokens": budget["maximum_input_tokens"],
        "maximum_output_tokens": budget["maximum_output_tokens"],
        "maximum_output_tokens_per_call": budget[
            "maximum_output_tokens_per_call"
        ],
        "maximum_elapsed_seconds": budget["maximum_elapsed_seconds"],
        "monetary_budget": {
            "schema": "CanaryMonetaryBudgetV1",
            "maximum_usd_cost_microunits": budget[
                "maximum_usd_cost_microunits"
            ],
            "maximum_cny_cost_microunits": budget[
                "maximum_cny_cost_microunits"
            ],
            "approved_fx_snapshot": None,
        },
        "elapsed_budget_sha256": definitions["budgets"]["elapsed"][
            "definition_sha256"
        ],
    })
    payload["stop_conditions"] = list(STOP_CONDITIONS)
    payload["report_policy"] = {
        "raw_content_included": False,
        "hash_only": True,
        "shape_and_count_metadata_allowed": True,
        "machine_specific_paths_included": False,
        "full_provider_request_id_included": False,
    }
    instrumentation = definitions["instrumentation"]
    payload["planning_repair_observation_policy"] = {
        "canary_id": CANARY_ID,
        "profile_id": PROFILE.profile_id,
        "profile_definition_sha256": PROFILE.profile_definition_sha256,
        "approval_scope": PROFILE.approval_scope,
        "target": deepcopy(TARGET),
        "target_filter_sha256": definitions["target"]["definition_sha256"],
        "instrumentation_definition_sha256s": {
            name: value["definition_sha256"]
            for name, value in instrumentation["definitions"].items()
        },
        "instrumentation_definition_bundle_sha256": instrumentation[
            "bundle"
        ]["definition_sha256"],
        "observation_goal_definition_sha256": definitions["goal"][
            "definition_sha256"
        ],
        "validate_only_closure_definition_sha256": definitions["closure"][
            "definition_sha256"
        ],
        "domain_validator_policy_sha256": definitions["validator"][
            "definition_sha256"
        ],
        "production_repair_budget_policy_sha256": definitions[
            "production_budget"
        ]["definition_sha256"],
        "prompt_request_parity_definition_sha256": definitions["prompt"][
            "definition_sha256"
        ],
        "budget_definition_hashes": {
            name: definitions["budgets"][name]["definition_sha256"]
            for name in ("call", "token", "monetary", "elapsed")
        },
        "synthetic_target_injection_allowed": False,
        "production_retry_fallback_mutation_allowed": False,
        "production_output_budget_mutation_allowed": False,
        "target_not_exercised_outcome": (
            "PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED"
        ),
        "second_run_allowed": False,
    }
    return build_canary_experiment_plan_v1(payload)


def _build_candidate(
    *, plan: Mapping[str, Any], definitions: Mapping[str, Any],
    cohort_id: str, current: datetime, window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    policy = plan["planning_repair_observation_policy"]
    workload = plan["workloads"][0]
    budget = PROFILE.budget()
    approved_budget = {
        **budget,
        "definition_sha256": definitions["budgets"]["manifest"][
            "definition_sha256"
        ],
    }
    return build_planning_repair_observation_candidate_v1({
        "status": "waiting_for_final_user_authorization",
        "approval_scope": PROFILE.approval_scope,
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
        "prompt_policy_manifest_sha256": workload[
            "prompt_policy_manifest_sha256"
        ],
        "target_filter_sha256": policy["target_filter_sha256"],
        "instrumentation_definition_bundle_sha256": policy[
            "instrumentation_definition_bundle_sha256"
        ],
        "observation_goal_definition_sha256": policy[
            "observation_goal_definition_sha256"
        ],
        "domain_validator_policy_sha256": policy[
            "domain_validator_policy_sha256"
        ],
        "production_repair_budget_policy_sha256": policy[
            "production_repair_budget_policy_sha256"
        ],
        "call_budget_definition_sha256": policy["budget_definition_hashes"][
            "call"
        ],
        "token_budget_definition_sha256": policy["budget_definition_hashes"][
            "token"
        ],
        "monetary_budget_definition_sha256": policy[
            "budget_definition_hashes"
        ]["monetary"],
        "elapsed_budget_definition_sha256": policy[
            "budget_definition_hashes"
        ]["elapsed"],
        "budget_definition_sha256": approved_budget["definition_sha256"],
        "stop_condition_manifest_hash": definitions["stop"][
            "definition_sha256"
        ],
        "canary_root_identity_candidate": plan["isolation"][
            "stable_root_identity"
        ],
        "approval_ledger_identity": plan["isolation"][
            "approval_ledger_identity"
        ],
        "single_use_cohort_id": cohort_id,
        "maximum_executions": 1,
        "usage_status": "unused",
        "consumed_evidence_sha256": None,
        "materialized_at": _utc(current),
        "execution_window": {
            "not_before": _utc(window_start), "not_after": _utc(window_end),
        },
        "approval_expiry": _utc(window_end),
        "named_approver": "USER_CONFIRMATION_REQUIRED",
        "authorize_credential_lookup": False,
        "authorize_provider_client_creation": False,
        "authorize_network": False,
        "authorize_paid_model_calls": False,
        "authorized_actions": {
            "credential_lookup": False, "provider_client_creation": False,
            "network": False, "paid_model_calls": False,
            "fake_boundary": False,
        },
        "execution_authorized": False,
        "phase1b_enabled": False,
        **budget,
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
        "signed_approval_materialized": False,
        "execution_performed": False,
        "approved_budget": approved_budget,
    })


def _preview(
    *, plan: Mapping[str, Any], candidate: Mapping[str, Any],
    template: Mapping[str, Any], paths: Mapping[str, Path],
    artifact_root_label: str,
) -> dict[str, Any]:
    label = artifact_root_label.rstrip("/")
    body = {
        "schema": "PlanningRepairObservationExecutionPreviewV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profile_id": PROFILE.profile_id,
        "approval_scope": PROFILE.approval_scope,
        "bound_plan_sha256": plan["plan_sha256"],
        "bound_candidate_sha256": candidate["approval_candidate_sha256"],
        "bound_patch_template_sha256": template[
            "authorization_patch_template_sha256"
        ],
        "future_signed_approval_schema": PROFILE.signed_approval_schema,
        "future_signed_approval_file": (
            "${PLANNING_REPAIR_OBSERVATION_SIGNED_APPROVAL}"
        ),
        "future_confirmed_authorization_patch_file": (
            "${PLANNING_REPAIR_OBSERVATION_CONFIRMED_PATCH}"
        ),
        "plan_file": f"{label}/{paths['plan'].name}",
        "candidate_file": f"{label}/{paths['candidate'].name}",
        "patch_template_file": f"{label}/{paths['patch_template'].name}",
        "future_command_argv": [
            ".venv/Scripts/python.exe", "-m", "tools.canary.launcher",
            "--plan", f"{label}/{paths['plan'].name}",
            "--approval", "${PLANNING_REPAIR_OBSERVATION_SIGNED_APPROVAL}",
            "--approval-candidate", f"{label}/{paths['candidate'].name}",
            "--authorization-patch",
            "${PLANNING_REPAIR_OBSERVATION_CONFIRMED_PATCH}",
            "--approved-plan-sha256", plan["plan_sha256"], "--real-run",
            "--workload-fixture", "tests/fixtures/canary/short-normal-v1.json",
            "--canary-root", "${PLANNING_REPAIR_OBSERVATION_CANARY_ROOT}",
            "--approval-ledger-root",
            "${PLANNING_REPAIR_OBSERVATION_APPROVAL_LEDGER}",
            "--live-database", "data/app.db",
            "--live-project-root", "data/projects",
        ],
        "execution_authorized": False,
        "do_not_execute": True,
        "signed_approval_materialized": False,
        "credential_material_included": False,
    }
    return _sealed(
        "novel-flywheel-r1-ptr2-execution-preview-v1", body,
        "preview_sha256",
    )


def _check(
    name: str, exact: bool, reason: str,
    digest: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "exact" if exact else "blocked",
        "reason_code": None if exact else reason,
        "definition_sha256": digest,
    }


def _validate_only(
    *, plan: Mapping[str, Any], candidate: Mapping[str, Any],
    template: Mapping[str, Any], preview: Mapping[str, Any],
    definitions: Mapping[str, Any], rehearsal: Mapping[str, Any],
    ledger: Mapping[str, Any], privacy: Mapping[str, Any],
    parity_before: Mapping[str, Any], parity_after: Mapping[str, Any],
    fixture_path: Path, network_count: int,
) -> dict[str, Any]:
    policy = plan["planning_repair_observation_policy"]
    source_clean, current_build = _production_source_clean()
    try:
        validate_planning_repair_observation_candidate_v1(
            candidate,
            expected_plan_sha256=plan["plan_sha256"],
            expected_launcher_sha256=plan["launcher_sha256"],
        )
        candidate_valid = True
    except Exception:
        candidate_valid = False
    checks = [
        _check("profile_scope", plan["canary_mode"] == PROFILE.canary_mode
               and policy["approval_scope"] == PROFILE.approval_scope,
               "approval_profile_scope_mismatch",
               PROFILE.profile_definition_sha256),
        _check("validate_only_closure",
               policy.get("validate_only_closure_definition_sha256")
               == definitions["closure"]["definition_sha256"],
               "validate_only_closure_definition_mismatch",
               definitions["closure"]["definition_sha256"]),
        _check("candidate_contract", candidate_valid,
               "approval_candidate_invalid",
               candidate["approval_candidate_sha256"]),
        _check("candidate_disabled", candidate["execution_authorized"] is False
               and candidate["named_approver"] == "USER_CONFIRMATION_REQUIRED",
               "candidate_authorized"),
        _check("patch_template_disabled", template["execution_authorized"] is False
               and template["signed_approval_materialization_allowed"] is False,
               "patch_template_authorized",
               template["authorization_patch_template_sha256"]),
        _check("preview_disabled", preview["do_not_execute"] is True
               and preview["execution_authorized"] is False,
               "preview_authorized", preview["preview_sha256"]),
        _check("current_build", current_build == plan["approved_build_fingerprint"],
               "build_fingerprint_mismatch", current_build),
        _check("production_source_clean", source_clean is True,
               "production_source_dirty_or_unknown", current_build),
        _check("runtime_fingerprint_v2",
               plan["runtime_fingerprint_policy_version"]
               == "runtime-fingerprint-v2",
               "runtime_fingerprint_policy_mismatch"),
        _check("execution_config_semantic",
               rehearsal["materialization_semantic_sha256"]
               == rehearsal["subprocess_semantic_sha256"]
               == plan["approved_execution_config_fingerprint"],
               "execution_config_fingerprint_mismatch"),
        _check("runtime_execution",
               rehearsal["materialization_runtime_execution_sha256"]
               == rehearsal["subprocess_runtime_execution_sha256"]
               == plan["expected_runtime_execution_fingerprint"],
               "runtime_execution_fingerprint_mismatch"),
        _check("feature_flags", plan["feature_flag_snapshot"] == FEATURE_FLAGS,
               "feature_flag_snapshot_mismatch",
               definitions["feature"]["definition_sha256"]),
        _check("phase1b_disabled",
               plan["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] is False
               and plan["feature_flag_snapshot"]["project_short_canonical_v2"] is False,
               "phase1b_enabled"),
        _check("planning_repair_diagnostic_enabled",
               plan["feature_flag_snapshot"][
                   "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1"
               ] is True, "diagnostic_feature_flag_disabled"),
        _check("strict_tool_observation_disabled",
               plan["feature_flag_snapshot"][
                   "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"
               ] is False, "unapproved_diagnostic_enabled"),
        _check("budget_counterfactual_disabled",
               plan["feature_flag_snapshot"][
                   "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"
               ] is False, "budget_counterfactual_enabled"),
        _check("prompt_request_semantics",
               rehearsal["model_request_semantic_status"] == "unchanged",
               "prompt_request_semantic_delta",
               definitions["prompt"]["definition_sha256"]),
        _check("route_model_provider",
               bool(plan["provider_descriptor_definition_sha256"])
               and bool(plan["role_binding_manifest_definition_sha256"]),
               "route_model_provider_identity_missing",
               plan["role_binding_manifest_definition_sha256"]),
        _check("target_filter", policy["target"] == TARGET
               and policy["synthetic_target_injection_allowed"] is False,
               "target_filter_mismatch",
               policy["target_filter_sha256"]),
        _check("four_instrumentation_definitions",
               set(policy["instrumentation_definition_sha256s"])
               == {"domain_validation", "finding_propagation",
                   "provider_content_block_shape", "output_limit"},
               "instrumentation_definition_mismatch",
               policy["instrumentation_definition_bundle_sha256"]),
        _check("observer_rehearsal",
               set(rehearsal["observer_coverage"].values()) == {"typed"},
               "observer_rehearsal_incomplete",
               rehearsal["receipt_sha256"]),
        _check("domain_validator_policy",
               candidate["domain_validator_policy_sha256"]
               == definitions["validator"]["definition_sha256"],
               "domain_validator_policy_mismatch",
               definitions["validator"]["definition_sha256"]),
        _check("production_repair_budget_unchanged",
               rehearsal["production_output_budget_status"] == "unchanged"
               and policy["production_output_budget_mutation_allowed"] is False,
               "production_repair_budget_changed",
               definitions["production_budget"]["definition_sha256"]),
        _check("retry_fallback_unchanged",
               rehearsal["retry_fallback_status"] == "unchanged"
               and policy["production_retry_fallback_mutation_allowed"] is False,
               "retry_fallback_changed"),
        _check("goal_stop_definition",
               policy["observation_goal_definition_sha256"]
               == definitions["goal"]["definition_sha256"],
               "goal_stop_definition_mismatch",
               definitions["goal"]["definition_sha256"]),
        _check("outer_budget_caps",
               all(candidate[name] == value
                   for name, value in PROFILE.budget().items()),
               "outer_budget_cap_mismatch",
               definitions["budgets"]["manifest"]["definition_sha256"]),
        _check("stop_conditions",
               tuple(plan["stop_conditions"]) == STOP_CONDITIONS,
               "stop_condition_manifest_mismatch",
               definitions["stop"]["definition_sha256"]),
        _check("workload", file_sha256(fixture_path)
               == candidate["approved_workload_sha256"]
               and candidate["approved_workload_id"] == "short-normal-v1",
               "workload_identity_mismatch",
               candidate["approved_workload_sha256"]),
        _check("ledger", ledger["status"] == "exact"
               and ledger["initial_entry_count"] == 0
               and ledger["cohort_status"] == "unused"
               and ledger["approval_status"] == "unreserved",
               "approval_ledger_not_ready",
               ledger["identity_definition_sha256"]),
        _check("cohort_unused", candidate["usage_status"] == "unused"
               and candidate["consumed_evidence_sha256"] is None,
               "cohort_not_unused"),
        _check("privacy", privacy["status"] == "exact",
               "privacy_violation", privacy["privacy_scan_sha256"]),
        _check("live_parity",
               parity_equal(dict(parity_before), dict(parity_after)),
               "live_parity_mismatch", parity_after["parity_sha256"]),
        _check("zero_external_actions", network_count == 0
               and all(value == 0 for value in EXTERNAL_COUNTERS.values()),
               "external_action_observed"),
        _check("signed_approval_absent",
               candidate["signed_approval_materialized"] is False,
               "signed_approval_present"),
        _check("execution_not_performed",
               candidate["execution_performed"] is False,
               "execution_performed"),
    ]
    body = {
        "schema": "PlanningRepairObservationValidateOnlyReceiptV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "overall_status": (
            "exact" if all(item["status"] == "exact" for item in checks)
            else "blocked"
        ),
        "ordered_checks": checks,
        "external_action_counters": {
            **EXTERNAL_COUNTERS, "network_call_count": network_count,
        },
        "privacy": deepcopy(dict(privacy)),
        "parity": {
            "status": (
                "exact" if parity_equal(
                    dict(parity_before), dict(parity_after)
                ) else "changed"
            ),
            "before_sha256": parity_before["parity_sha256"],
            "after_sha256": parity_after["parity_sha256"],
        },
        "approval_state": "disabled_candidate_no_signed_approval",
        "execution_performed": False,
    }
    return _sealed(
        "novel-flywheel-r1-ptr2-validate-only-receipt-v1", body,
        "validation_receipt_sha256",
    )


def materialize_planning_repair_observation_1(
    *, live_database_path: Path, live_project_root: Path,
    fixture_path: Path, output_root: Path, approval_ledger_root: Path,
    cohort_id: str, run_namespace: str, artifact_root_label: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize disabled evidence only; never sign, reserve, or execute."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_start = current + timedelta(minutes=15)
    window_end = window_start + timedelta(hours=48)
    _require(_COHORT.fullmatch(cohort_id) is not None,
             "single_use_cohort_id_invalid")
    _require(run_namespace == cohort_id, "run_namespace_must_match_cohort")
    paths = {
        "plan": output_root / "r1-ptr2-observation-plan-v1.json",
        "candidate": output_root / "r1-ptr2-final-approval-candidate-v1.json",
        "patch_template": output_root / "r1-ptr2-authorization-patch-template-v1.json",
        "preview": output_root / "r1-ptr2-execution-preview-v1.json",
        "validation": output_root / "r1-ptr2-validate-only-receipt-v1.json",
        "index": output_root / "r1-ptr2-materialization-index-v1.json",
        "goal": output_root / "r1-ptr2-observation-goal-definition-v1.json",
        "instrumentation": output_root / "r1-ptr2-instrumentation-definition-bundle-v1.json",
        "ledger": output_root / "r1-ptr2-ledger-operational-readiness-v1.json",
        "rehearsal": output_root / "r1-ptr2-pre-launch-semantic-rehearsal-v1.json",
        "closure_rehearsal": output_root / "r1-ptr2-signed-closure-rehearsal-v1.json",
        "definitions": output_root / "r1-ptr2-definition-bundle-v1.json",
    }
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    before = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )
    sentinel = FailClosedNetworkSentinel()
    with tempfile.TemporaryDirectory(
        prefix="novel-r1-ptr2-materialize-"
    ) as temporary:
        temporary_root = Path(temporary)
        with sentinel:
            base = _prepare_base(
                live_database_path=live_database_path,
                fixture_path=fixture_path, cohort_id=cohort_id,
                run_namespace=run_namespace, now=current,
                temporary_root=temporary_root / "base",
            )
        definitions = _definitions()
        plan = _build_plan(base, definitions)
        ledger = initialize_approval_ledger_v1(
            approval_ledger_root,
            ledger_identity=plan["isolation"]["approval_ledger_identity"],
        )
        candidate = _build_candidate(
            plan=plan, definitions=definitions, cohort_id=cohort_id,
            current=current, window_start=window_start,
            window_end=window_end,
        )
        template = build_planning_repair_observation_patch_template_v1(
            candidate
        )
        preview = _preview(
            plan=plan, candidate=candidate, template=template, paths=paths,
            artifact_root_label=artifact_root_label,
        )
        definition_bundle = _sealed(
            "novel-flywheel-r1-ptr2-definition-bundle-v1", {
                "schema": "R1PTR2DefinitionBundleV1", "version": 1,
                "canonicalization_version": CANONICALIZATION_VERSION,
                "feature": definitions["feature"],
                "closure": definitions["closure"],
                "target": definitions["target"],
                "stop": definitions["stop"],
                "validator": definitions["validator"],
                "prompt_request_parity": definitions["prompt"],
                "production_repair_budget_parity": definitions[
                    "production_budget"
                ],
                "budgets": definitions["budgets"],
            }, "bundle_sha256",
        )
        for key, value in (
            ("plan", plan), ("candidate", candidate),
            ("patch_template", template), ("preview", preview),
            ("goal", definitions["goal"]),
            ("instrumentation", definitions["instrumentation"]["bundle"]),
            ("ledger", ledger), ("definitions", definition_bundle),
        ):
            _write(paths[key], value)
        rehearsal_output = temporary_root / "rehearsal.json"
        completed = subprocess.run(
            [
                sys.executable, "-m", "tools.canary.planning_repair_rehearsal",
                "--plan", str(paths["plan"]), "--fixture", str(fixture_path),
                "--live-database", str(live_database_path),
                "--isolated-root", str(temporary_root / "rehearsal-root"),
                "--output", str(rehearsal_output),
            ],
            cwd=Path(__file__).resolve().parents[2],
            check=False, capture_output=True, text=True, timeout=120,
        )
        _require(completed.returncode == 0 and rehearsal_output.is_file(),
                 "prelaunch_semantic_rehearsal_failed")
        rehearsal = json.loads(rehearsal_output.read_text(encoding="utf-8"))
        _write(paths["rehearsal"], rehearsal)
        documents = {
            "plan": plan, "candidate": candidate,
            "patch_template": template, "preview": preview,
            "goal": definitions["goal"],
            "instrumentation": definitions["instrumentation"]["bundle"],
            "ledger": ledger, "rehearsal": rehearsal,
            "definitions": definition_bundle,
        }
        privacy = _privacy_scan(documents, fixture=fixture)
        after = live_parity_manifest(
            database_path=live_database_path, project_root=live_project_root,
        )
        validation = _validate_only(
            plan=plan, candidate=candidate, template=template,
            preview=preview, definitions=definitions,
            rehearsal=rehearsal, ledger=ledger, privacy=privacy,
            parity_before=before, parity_after=after,
            fixture_path=fixture_path,
            network_count=sentinel.network_call_count,
        )
        _write(paths["validation"], validation)
    _require(sentinel.network_call_count == 0, "materialization_network_observed")
    _require(validation["overall_status"] == "exact", "validate_only_blocked")
    index_body = {
        "schema": "R1PTR2MaterializationIndexV1", "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "contract_status": "R1_PTR2_OBSERVATION_APPROVAL_PACKET_READY",
        "status": "R1_PTR2_REAL_OBSERVATION_WAITING_FOR_FINAL_USER_AUTHORIZATION",
        "files": {
            path.name: file_sha256(path)
            for key, path in sorted(paths.items())
            if key not in {"index", "closure_rehearsal"}
        },
        "plan_sha256": plan["plan_sha256"],
        "approval_candidate_sha256": candidate["approval_candidate_sha256"],
        "authorization_patch_template_sha256": template[
            "authorization_patch_template_sha256"
        ],
        "validation_receipt_sha256": validation[
            "validation_receipt_sha256"
        ],
        "prelaunch_semantic_rehearsal_sha256": rehearsal["receipt_sha256"],
        "observation_goal_definition_sha256": definitions["goal"][
            "definition_sha256"
        ],
        "instrumentation_definition_bundle_sha256": definitions[
            "instrumentation"
        ]["bundle"]["definition_sha256"],
        "single_use_cohort_id": cohort_id,
        "execution_window": candidate["execution_window"],
        "approval_ledger_identity": candidate["approval_ledger_identity"],
        "approval_ledger_initial_entry_count": ledger["initial_entry_count"],
        "external_action_counters": validation["external_action_counters"],
        "privacy_status": privacy["status"],
        "live_parity_status": validation["parity"]["status"],
        "live_parity_sha256": validation["parity"]["after_sha256"],
        "privacy_scan_sha256": privacy["privacy_scan_sha256"],
        "real_provider_observation": "NOT_EXECUTED",
        "signed_approval": "ABSENT",
        "confirmed_patch": "ABSENT",
        "new_single_use_approval_required": True,
        "execution_performed": False,
    }
    index = _sealed(
        "novel-flywheel-r1-ptr2-materialization-index-v1", index_body,
        "definition_sha256",
    )
    _write(paths["index"], index)

    # Exercise the newly registered signed validate-only handler with a
    # synthetic authorization that remains local to this materialization.
    # Neither authorization object is persisted in the approval packet.
    from .approval_dispatch import materialize_signed_canary_approval
    from .planning_repair_approval import (
        materialize_planning_repair_observation_patch_v1,
    )
    from .planning_repair_closure import (
        validate_planning_repair_observation_closure,
    )

    rehearsal_now = window_start + timedelta(seconds=1)
    approval_timestamp = _utc(rehearsal_now)
    synthetic_patch = materialize_planning_repair_observation_patch_v1(
        template,
        named_approver="synthetic_validate_only_rehearsal",
        approval_timestamp=approval_timestamp,
    )
    synthetic_signed = materialize_signed_canary_approval(
        PROFILE_ID,
        candidate,
        synthetic_patch,
        now=rehearsal_now,
    )
    with tempfile.TemporaryDirectory(
        prefix="novel-r1-ptr2-signed-closure-rehearsal-"
    ) as closure_temporary:
        closure_root = Path(closure_temporary)
        patch_path = closure_root / "confirmed-patch.json"
        signed_path = closure_root / "signed-approval.json"
        _write(patch_path, synthetic_patch)
        _write(signed_path, synthetic_signed)
        signed_closure_rehearsal = (
            validate_planning_repair_observation_closure(
                plan_path=paths["plan"],
                approval_path=signed_path,
                source_candidate_path=paths["candidate"],
                source_authorization_patch_path=patch_path,
                packet_path=paths["index"],
                workload_fixture_path=fixture_path,
                live_database_path=live_database_path,
                live_project_root=live_project_root,
                canary_root=closure_root / "future-canary-root",
                approval_ledger_root=approval_ledger_root,
                cli_approved_plan_sha256=plan["plan_sha256"],
                now=rehearsal_now,
            )
        )
    _require(
        signed_closure_rehearsal["overall_status"] == "exact",
        "signed_validate_only_rehearsal_failed",
    )
    _require(
        signed_closure_rehearsal["external_action_counters"]
        == EXTERNAL_COUNTERS,
        "signed_validate_only_rehearsal_external_action_observed",
    )
    _write(paths["closure_rehearsal"], signed_closure_rehearsal)
    index_body.update({
        "files": {
            path.name: file_sha256(path)
            for key, path in sorted(paths.items()) if key != "index"
        },
        "signed_validate_only_rehearsal_sha256": (
            signed_closure_rehearsal["validation_receipt_sha256"]
        ),
    })
    index = _sealed(
        "novel-flywheel-r1-ptr2-materialization-index-v1", index_body,
        "definition_sha256",
    )
    _write(paths["index"], index)
    return {
        "plan": plan,
        "approval_candidate": candidate,
        "authorization_patch_template": template,
        "execution_preview": preview,
        "validation_receipt": validation,
        "semantic_rehearsal": rehearsal,
        "signed_closure_rehearsal": signed_closure_rehearsal,
        "ledger_readiness": ledger,
        "definition_bundle": definition_bundle,
        "index": index,
        "paths": paths,
        "approval_ledger_root": approval_ledger_root,
        "signed_approval": None,
        "confirmed_authorization_patch": None,
        "execution_performed": False,
    }


def _parse_utc_argument(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError("utc_timestamp_invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the disabled R1-PTR2 observation packet",
    )
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-project-root", type=Path, required=True)
    parser.add_argument("--workload-fixture", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--approval-ledger-root", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--run-namespace", required=True)
    parser.add_argument("--artifact-root-label", required=True)
    parser.add_argument("--materialized-at", type=_parse_utc_argument)
    args = parser.parse_args(argv)
    result = materialize_planning_repair_observation_1(
        live_database_path=args.live_database,
        live_project_root=args.live_project_root,
        fixture_path=args.workload_fixture,
        output_root=args.output_root,
        approval_ledger_root=args.approval_ledger_root,
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
