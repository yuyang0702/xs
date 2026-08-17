"""Fail-closed signed validate-only closure for planning_repair_observation_1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_dispatch import (
    profile_for_plan,
    validate_registered_approval_document,
    validate_registered_signed_plan,
    validate_registered_signed_sources,
)
from .approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
    approval_profile,
    validate_profile_definition,
)
from .approval_store import ApprovalConsumptionStore
from .artifact_hash import file_sha256, live_parity_manifest
from .contracts import validate_canary_experiment_plan_v1
from .hash_manifest import validate_import_closure
from .pa_strict_tool_obs import _privacy_scan, _production_source_clean
from .planning_repair_approval import (
    materialize_planning_repair_observation_patch_v1,
    validate_planning_repair_observation_patch_template_v1,
)
from .planning_repair_observation import (
    FEATURE_FLAGS,
    STOP_CONDITIONS,
    TARGET,
    _definitions,
    _prepare_base,
)


CLOSURE_PROFILE_ID = "planning_repair_observation_closure_v1"
SCHEMA = "PlanningRepairObservationApprovalClosureValidationV1"
DOMAIN = "novel-flywheel-planning-repair-observation-closure-v1"

CHECK_NAMES = (
    "registered_profile",
    "approval_scope",
    "closure_profile_version",
    "plan_canonical_hash",
    "approval_document",
    "candidate_binding",
    "authorization_patch_binding",
    "permitted_diff",
    "signed_plan_binding",
    "launcher_bytes_hash",
    "materialization_index",
    "materialized_file_bytes",
    "workload_fixture_hash",
    "workload_manifest_hash",
    "production_source_byte_revalidation",
    "build_fingerprint",
    "execution_config_fingerprint",
    "runtime_execution_fingerprint",
    "runtime_fingerprint_v2",
    "prompt_request_semantics",
    "provider_descriptor_manifest",
    "role_route_model_manifest",
    "target_filter",
    "observation_goal",
    "domain_validator_policy",
    "instrumentation_definitions",
    "instrumentation_bundle",
    "diagnostic_feature_flags",
    "phase1b_disabled",
    "production_repair_budget_policy",
    "retry_fallback_parity",
    "synthetic_target_injection_forbidden",
    "outer_budget",
    "stop_conditions",
    "approval_execution_window",
    "approval_cohort_single_use",
    "approval_ledger_identity",
    "approval_ledger_business_entry_count",
    "canary_root_binding",
    "external_action_authorization",
    "privacy",
    "live_parity",
    "external_action_zero",
)


class PlanningRepairClosureBlocked(RuntimeError):
    def __init__(self, check_name: str, reason_code: str) -> None:
        super().__init__(reason_code)
        self.check_name = check_name
        self.reason_code = reason_code


def planning_repair_observation_closure_definition_v1() -> dict[str, Any]:
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    body = {
        "schema": "PlanningRepairObservationClosureDefinitionV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "closure_profile_id": CLOSURE_PROFILE_ID,
        "profile_id": profile.profile_id,
        "approval_scope": profile.approval_scope,
        "receipt_schema": SCHEMA,
        "ordered_checks": list(CHECK_NAMES),
        "side_effect_policy": "read_only_zero_external_action",
        "unknown_profile_policy": "fail_closed_no_default",
    }
    return {
        **body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-planning-repair-observation-closure-definition-v1",
            body,
        ),
    }


def _read(path: Path, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanningRepairClosureBlocked("materialization_index", reason_code) from exc
    if not isinstance(value, dict):
        raise PlanningRepairClosureBlocked("materialization_index", reason_code)
    return value


def _result(
    name: str, status: str, reason_code: str,
    definition_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason_code": reason_code,
        "definition_sha256": definition_sha256,
    }


def _receipt(
    checks: list[dict[str, Any]], *, approval_kind: str,
    approval_identity: str | None, approval_state: str,
    ledger_state: str, canary_root_status: str,
    live_parity_sha256: str | None,
) -> dict[str, Any]:
    body = {
        "schema": SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "closure_profile_id": CLOSURE_PROFILE_ID,
        "closure_definition_sha256": (
            planning_repair_observation_closure_definition_v1()[
                "definition_sha256"
            ]
        ),
        "profile_id": PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
        "overall_status": (
            "exact" if all(item["status"] == "exact" for item in checks)
            else "blocked"
        ),
        "ordered_checks": checks,
        "approval_document_kind": approval_kind,
        "approval_identity_sha256": approval_identity,
        "approval_state": approval_state,
        "approval_ledger_state": ledger_state,
        "canary_root_candidate_status": canary_root_status,
        "live_parity_observation_sha256": live_parity_sha256,
        "privacy": {
            "status": "exact" if any(
                item["name"] == "privacy" and item["status"] == "exact"
                for item in checks
            ) else "unknown",
            "raw_content_included": False,
        },
        "external_action_counters": {
            "credential_lookup_count": 0,
            "provider_client_creation_count": 0,
            "network_call_count": 0,
            "model_call_count": 0,
            "paid_model_call_count": 0,
        },
        "execution_performed": False,
    }
    return {
        **body,
        "validation_receipt_sha256": domain_sha256(DOMAIN, body),
    }


def _canonical_index(index: Mapping[str, Any]) -> bool:
    digest = index.get("definition_sha256")
    body = {key: deepcopy(value) for key, value in index.items()
            if key != "definition_sha256"}
    return digest == domain_sha256(
        "novel-flywheel-r1-ptr2-materialization-index-v1", body,
    )


def _materialized_files_exact(
    index: Mapping[str, Any], packet_path: Path,
) -> bool:
    files = index.get("files")
    if not isinstance(files, Mapping) or not files:
        return False
    root = packet_path.parent
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            return False
        target = root / name
        if not target.is_file() or file_sha256(target) != expected:
            return False
    return True


def _canary_root_candidate_status(
    root: Path, *, live_database_path: Path, live_project_root: Path,
) -> str:
    candidate = root.resolve(strict=False)
    for live in (live_database_path.parent.resolve(), live_project_root.resolve()):
        try:
            candidate.relative_to(live)
            raise PlanningRepairClosureBlocked(
                "canary_root_binding", "canary_live_root_overlap",
            )
        except ValueError:
            pass
        try:
            live.relative_to(candidate)
            raise PlanningRepairClosureBlocked(
                "canary_root_binding", "canary_live_root_overlap",
            )
        except ValueError:
            pass
    if not root.exists():
        return "valid_absent_candidate"
    if root.is_dir() and not any(root.iterdir()):
        return "valid_empty_candidate"
    raise PlanningRepairClosureBlocked(
        "canary_root_binding", "canary_root_not_empty",
    )


def _validate(
    *, plan_path: Path, approval_path: Path,
    source_candidate_path: Path | None,
    source_authorization_patch_path: Path | None,
    packet_path: Path | None, workload_fixture_path: Path,
    live_database_path: Path, live_project_root: Path,
    canary_root: Path, approval_ledger_root: Path,
    cli_approved_plan_sha256: str, now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    checks: list[dict[str, Any]] = []

    def exact(
        name: str, condition: bool, reason: str,
        digest: str | None = None,
    ) -> None:
        if not condition:
            raise PlanningRepairClosureBlocked(name, reason)
        checks.append(_result(name, "exact", "exact", digest))

    plan = validate_canary_experiment_plan_v1(
        _read(plan_path, "plan_unavailable_or_invalid")
    )
    profile = validate_profile_definition(profile_for_plan(plan))
    exact("registered_profile",
          profile.profile_id == PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
          "approval_profile_scope_mismatch", profile.profile_definition_sha256)
    exact("approval_scope",
          profile.approval_scope
          == "PLANNING_REPAIR_SINGLE_REAL_PROVIDER_OBSERVATION_CANARY",
          "approval_scope_mismatch", profile.profile_definition_sha256)
    closure_definition = planning_repair_observation_closure_definition_v1()
    policy = plan.get("planning_repair_observation_policy") or {}
    exact("closure_profile_version",
          profile.validate_only_profile == CLOSURE_PROFILE_ID
          and policy.get("validate_only_closure_definition_sha256")
          == closure_definition["definition_sha256"],
          "validate_only_closure_definition_mismatch",
          closure_definition["definition_sha256"])
    exact("plan_canonical_hash", plan["plan_sha256"] == cli_approved_plan_sha256,
          "cli_approved_plan_hash_mismatch", plan["plan_sha256"])

    approval_input = _read(approval_path, "approval_unavailable_or_invalid")
    try:
        approval, approval_identity, approval_kind, document_profile = (
            validate_registered_approval_document(
                approval_input,
                expected_profile_id=profile.profile_id,
                expected_scope=profile.approval_scope,
                expected_plan_sha256=plan["plan_sha256"],
                expected_launcher_sha256=plan["launcher_sha256"],
                now=current,
                enforce_time=True,
            )
        )
    except Exception as exc:
        raise PlanningRepairClosureBlocked(
            "approval_document",
            getattr(exc, "reason_code", str(exc) or "approval_document_invalid"),
        ) from exc
    exact("approval_document", document_profile.profile_id == profile.profile_id,
          "approval_profile_scope_mismatch", approval_identity)

    if approval_kind != "signed_approval":
        raise PlanningRepairClosureBlocked(
            "external_action_authorization", "signed_approval_required",
        )
    if source_candidate_path is None or source_authorization_patch_path is None:
        raise PlanningRepairClosureBlocked(
            "candidate_binding", "signed_approval_source_document_missing",
        )
    candidate = _read(source_candidate_path, "candidate_unavailable_or_invalid")
    patch = _read(
        source_authorization_patch_path,
        "authorization_patch_unavailable_or_invalid",
    )
    try:
        validate_registered_signed_sources(
            profile.profile_id, approval, candidate, patch, now=current,
        )
    except Exception as exc:
        raise PlanningRepairClosureBlocked(
            "candidate_binding",
            getattr(exc, "reason_code", str(exc) or "signed_sources_invalid"),
        ) from exc
    exact("candidate_binding",
          approval["source_candidate_sha256"]
          == candidate["approval_candidate_sha256"],
          "signed_approval_candidate_source_mismatch",
          candidate["approval_candidate_sha256"])
    exact("authorization_patch_binding",
          approval["source_authorization_patch_sha256"]
          == patch["authorization_patch_sha256"],
          "signed_approval_patch_source_mismatch",
          patch["authorization_patch_sha256"])

    if packet_path is None:
        raise PlanningRepairClosureBlocked(
            "materialization_index", "materialization_index_missing",
        )
    index = _read(packet_path, "materialization_index_unavailable_or_invalid")
    template_path = packet_path.parent / "r1-ptr2-authorization-patch-template-v1.json"
    try:
        template = validate_planning_repair_observation_patch_template_v1(
            _read(template_path, "authorization_patch_template_missing")
        )
        expected_patch = materialize_planning_repair_observation_patch_v1(
            template,
            named_approver=patch["named_approver"],
            approval_timestamp=patch["approval_timestamp"],
        )
    except Exception as exc:
        raise PlanningRepairClosureBlocked(
            "permitted_diff",
            getattr(exc, "reason_code", str(exc) or "permitted_diff_invalid"),
        ) from exc
    exact("permitted_diff", expected_patch == patch,
          "authorization_patch_protected_fields_mismatch",
          patch["authorization_patch_sha256"])
    try:
        validate_registered_signed_plan(
            profile.profile_id, approval, plan, now=current,
        )
    except Exception as exc:
        raise PlanningRepairClosureBlocked(
            "signed_plan_binding",
            getattr(exc, "reason_code", str(exc) or "signed_plan_invalid"),
        ) from exc
    exact("signed_plan_binding", True, "signed_plan_binding_mismatch",
          plan["plan_sha256"])

    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=plan["approved_dependency_manifest"]["third_party"],
    )
    exact("launcher_bytes_hash",
          launcher["launcher_sha256"] == plan["launcher_sha256"],
          "launcher_changed_during_canary", launcher["launcher_sha256"])
    exact("materialization_index",
          index.get("schema") == "R1PTR2MaterializationIndexV1"
          and _canonical_index(index)
          and index.get("plan_sha256") == plan["plan_sha256"]
          and index.get("approval_candidate_sha256")
          == candidate["approval_candidate_sha256"],
          "materialization_index_mismatch", index.get("definition_sha256"))
    exact("materialized_file_bytes",
          _materialized_files_exact(index, packet_path),
          "materialized_file_byte_manifest_mismatch")

    fixture_hash = file_sha256(workload_fixture_path)
    workload = plan["workloads"][0]
    exact("workload_fixture_hash",
          fixture_hash == workload["fixture_sha256"],
          "workload_fixture_changed_during_canary", fixture_hash)
    exact("workload_manifest_hash",
          plan["workload_manifest_hash"]
          == approval["approved_workload_manifest_hash"],
          "workload_manifest_mismatch", plan["workload_manifest_hash"])

    with tempfile.TemporaryDirectory(
        prefix="novel-r1-ptr2-closure-"
    ) as temporary:
        fresh = _prepare_base(
            live_database_path=live_database_path,
            fixture_path=workload_fixture_path,
            cohort_id=approval["single_use_cohort_id"],
            run_namespace=plan["isolation"]["run_namespace"],
            now=current,
            temporary_root=Path(temporary),
        )
    source_clean, current_build = _production_source_clean()
    exact("production_source_byte_revalidation", source_clean is True,
          "production_source_dirty_or_unknown", current_build)
    exact("build_fingerprint",
          current_build == fresh["approved_build_fingerprint"]
          == plan["approved_build_fingerprint"],
          "build_fingerprint_mismatch", current_build)
    exact("execution_config_fingerprint",
          fresh["approved_execution_config_fingerprint"]
          == plan["approved_execution_config_fingerprint"],
          "execution_config_fingerprint_mismatch",
          fresh["approved_execution_config_fingerprint"])
    exact("runtime_execution_fingerprint",
          fresh["expected_runtime_execution_fingerprint"]
          == plan["expected_runtime_execution_fingerprint"],
          "runtime_execution_fingerprint_mismatch",
          fresh["expected_runtime_execution_fingerprint"])
    exact("runtime_fingerprint_v2",
          plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2",
          "runtime_fingerprint_policy_mismatch")

    definitions = _definitions()
    exact("prompt_request_semantics",
          policy.get("prompt_request_parity_definition_sha256")
          == definitions["prompt"]["definition_sha256"]
          and definitions["prompt"]["payload"][
              "diagnostic_flag_request_semantic_delta"
          ] is False
          and workload["prompt_policy_manifest_sha256"]
          == fresh["workloads"][0]["prompt_policy_manifest_sha256"],
          "prompt_request_semantic_mismatch",
          definitions["prompt"]["definition_sha256"])
    exact("provider_descriptor_manifest",
          plan["provider_descriptor_definition_sha256"]
          == fresh["provider_descriptor_definition_sha256"],
          "provider_descriptor_manifest_mismatch",
          fresh["provider_descriptor_definition_sha256"])
    exact("role_route_model_manifest",
          plan["role_binding_manifest_definition_sha256"]
          == fresh["role_binding_manifest_definition_sha256"],
          "role_route_model_manifest_mismatch",
          fresh["role_binding_manifest_definition_sha256"])
    exact("target_filter",
          policy.get("target") == TARGET
          and policy.get("target_filter_sha256")
          == definitions["target"]["definition_sha256"],
          "target_filter_mismatch", definitions["target"]["definition_sha256"])
    exact("observation_goal",
          policy.get("observation_goal_definition_sha256")
          == definitions["goal"]["definition_sha256"],
          "observation_goal_mismatch", definitions["goal"]["definition_sha256"])
    exact("domain_validator_policy",
          policy.get("domain_validator_policy_sha256")
          == definitions["validator"]["definition_sha256"],
          "domain_validator_policy_mismatch",
          definitions["validator"]["definition_sha256"])
    observer_hashes = {
        name: value["definition_sha256"]
        for name, value in definitions["instrumentation"]["definitions"].items()
    }
    exact("instrumentation_definitions",
          policy.get("instrumentation_definition_sha256s") == observer_hashes,
          "instrumentation_definition_mismatch",
          domain_sha256(
              "novel-flywheel-r1-ptr2-observer-hash-set-v1", observer_hashes,
          ))
    exact("instrumentation_bundle",
          policy.get("instrumentation_definition_bundle_sha256")
          == definitions["instrumentation"]["bundle"]["definition_sha256"],
          "instrumentation_bundle_mismatch",
          definitions["instrumentation"]["bundle"]["definition_sha256"])
    exact("diagnostic_feature_flags",
          plan["feature_flag_snapshot"] == FEATURE_FLAGS
          and FEATURE_FLAGS["NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1"] is True
          and FEATURE_FLAGS["NOVEL_RELIABILITY_TRACE"] is True
          and FEATURE_FLAGS["NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"] is False
          and FEATURE_FLAGS["NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"] is False,
          "diagnostic_feature_flag_mismatch",
          definitions["feature"]["definition_sha256"])
    exact("phase1b_disabled",
          FEATURE_FLAGS["NOVEL_SHORT_CANONICAL_V2"] is False
          and FEATURE_FLAGS["project_short_canonical_v2"] is False,
          "phase1b_enabled")
    exact("production_repair_budget_policy",
          policy.get("production_repair_budget_policy_sha256")
          == definitions["production_budget"]["definition_sha256"]
          and definitions["production_budget"]["payload"][
              "characterization_sequence"
          ] == [1977, 1977, 1977, 3954]
          and definitions["production_budget"]["payload"][
              "counterfactual_enabled"
          ] is False,
          "production_repair_budget_policy_mismatch",
          definitions["production_budget"]["definition_sha256"])
    exact("retry_fallback_parity",
          policy.get("production_retry_fallback_mutation_allowed") is False,
          "retry_fallback_policy_mismatch")
    exact("synthetic_target_injection_forbidden",
          policy.get("synthetic_target_injection_allowed") is False
          and TARGET["synthetic_target_injection_allowed"] is False,
          "synthetic_target_injection_enabled")

    budget = profile.budget()
    exact("outer_budget",
          all(plan["budgets"].get(name) == value
              for name, value in budget.items()
              if name not in {
                  "maximum_usd_cost_microunits",
                  "maximum_cny_cost_microunits",
              })
          and plan["budgets"]["monetary_budget"][
              "maximum_usd_cost_microunits"
          ] == budget["maximum_usd_cost_microunits"]
          and plan["budgets"]["monetary_budget"][
              "maximum_cny_cost_microunits"
          ] == budget["maximum_cny_cost_microunits"],
          "outer_budget_mismatch",
          approval["budget_definition_sha256"])
    exact("stop_conditions",
          plan["stop_conditions"] == list(STOP_CONDITIONS),
          "stop_condition_manifest_mismatch",
          definitions["stop"]["definition_sha256"])
    exact("approval_execution_window", True,
          "approval_outside_execution_window")

    store = ApprovalConsumptionStore(approval_ledger_root)
    state = store.status(approval)
    exact("approval_cohort_single_use", state["status"] == "unused",
          "approval_already_used")
    readiness = store.operational_readiness(
        ledger_identity=plan["isolation"]["approval_ledger_identity"],
    )
    exact("approval_ledger_identity", readiness["status"] == "exact",
          "approval_ledger_identity_mismatch",
          readiness["identity_definition_sha256"])
    exact("approval_ledger_business_entry_count",
          readiness["initial_entry_count"] == 0,
          "approval_ledger_not_empty")
    root_status = _canary_root_candidate_status(
        canary_root,
        live_database_path=live_database_path,
        live_project_root=live_project_root,
    )
    exact("canary_root_binding",
          approval["canary_root_identity_candidate"]
          == plan["isolation"]["stable_root_identity"],
          "canary_root_identity_mismatch",
          plan["isolation"]["stable_root_identity"])

    actions = approval["authorized_actions"]
    exact("external_action_authorization",
          approval["execution_authorized"] is True
          and all(approval[name] is True for name in (
              "authorize_credential_lookup",
              "authorize_provider_client_creation",
              "authorize_network",
              "authorize_paid_model_calls",
          ))
          and actions == {
              "credential_lookup": True,
              "provider_client_creation": True,
              "network": True,
              "paid_model_calls": True,
              "fake_boundary": False,
          },
          "signed_approval_authorization_missing")
    fixture = _read(workload_fixture_path, "workload_fixture_invalid")
    privacy = _privacy_scan({
        "plan": plan,
        "approval": approval,
        "candidate": candidate,
        "authorization_patch": patch,
        "materialization_index": index,
        "closure_definition": closure_definition,
    }, fixture=fixture)
    exact("privacy", privacy["status"] == "exact",
          "observation_privacy_violation", privacy["privacy_scan_sha256"])
    parity = live_parity_manifest(
        database_path=live_database_path,
        project_root=live_project_root,
    )
    exact("live_parity",
          index.get("live_parity_sha256") == parity["parity_sha256"]
          and index.get("live_parity_status") == "exact",
          "live_parity_mismatch", parity["parity_sha256"])
    exact("external_action_zero", True, "external_action_observed")

    return _receipt(
        checks,
        approval_kind=approval_kind,
        approval_identity=approval_identity,
        approval_state="signed_approval_exact_and_executable",
        ledger_state=state["status"],
        canary_root_status=root_status,
        live_parity_sha256=parity["parity_sha256"],
    )


def validate_planning_repair_observation_closure(
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a typed receipt for every result and never perform execution."""

    checks: list[dict[str, Any]] = []
    try:
        return _validate(**kwargs)
    except Exception as exc:
        check_name = getattr(exc, "check_name", "registered_profile")
        reason = getattr(
            exc, "reason_code", str(exc) or "closure_validation_failed",
        )
        seen_target = False
        for name in CHECK_NAMES:
            if name == check_name and not seen_target:
                checks.append(_result(name, "blocked", str(reason)))
                seen_target = True
            else:
                checks.append(_result(
                    name,
                    "not_evaluated",
                    "upstream_check_blocked",
                ))
        if not seen_target:
            checks[0] = _result(
                CHECK_NAMES[0], "blocked", "closure_validation_failed",
            )
        return _receipt(
            checks,
            approval_kind="unknown",
            approval_identity=None,
            approval_state="unknown",
            ledger_state="unknown",
            canary_root_status="unknown",
            live_parity_sha256=None,
        )
