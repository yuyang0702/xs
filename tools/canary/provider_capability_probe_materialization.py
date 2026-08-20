"""Materialize an inert R1-PTR4 Provider capability probe approval packet.

The materializer is deliberately unable to create a Signed Approval or a
confirmed authorization patch.  It performs no credential lookup, Provider
client construction, network access, model call, or paid action.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .artifact_hash import file_sha256, live_parity_manifest
from .network_sentinel import FailClosedNetworkSentinel
from .provider_capability_probe_contract import (
    EXTERNAL_ACTION_COUNTERS,
    build_provider_capability_probe_definition_v1,
    build_provider_capability_probe_fixture_v1,
    build_provider_capability_probe_observation_v1,
    contract_artifacts_v1,
)


PROFILE_ID = "r1_ptr4_provider_capability_probe_1"
APPROVAL_SCOPE = "provider_capability_probe"
PARENT_PTR4_MANIFEST = Path(
    "docs/superpowers/reports/r1-ptr4/r1-ptr4-sha256-manifest-v1.json"
)
PARENT_PTR4_PRIVACY = Path(
    "docs/superpowers/reports/r1-ptr4/r1-ptr4-privacy-scan-v1.json"
)
PARENT_PTR4_V1_MANIFEST = Path(
    "docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-sha256-manifest-v1.json"
)
PARENT_PTR4_V1_PRIVACY = Path(
    "docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-privacy-scan-v1.json"
)
EXPECTED_PTR4_CANONICAL_SHA256 = (
    "e7806b206edbdddf21a1ea74c7d0ebbb327ccedf7216f528c281c4ac2edfdf4c"
)
EXPECTED_PTR4_V1_CANONICAL_SHA256 = (
    "844516d3d45a472134d8c724b817ab2c3a1f9c0f73f95d2b9b4b30322eed2181"
)


class ProviderCapabilityProbeMaterializationError(ValueError):
    """Stable fail-closed materialization error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise ProviderCapabilityProbeMaterializationError(reason_code)


def _utc(value: datetime) -> str:
    current = value.astimezone(timezone.utc).replace(microsecond=0)
    return current.isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderCapabilityProbeMaterializationError(
            "document_unreadable"
        ) from exc
    _require(isinstance(value, dict), "document_not_object")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    payload = dict(body)
    payload[field] = domain_sha256(domain, payload)
    return payload


def verify_sha_manifest_exact(
    repo_root: Path, manifest_path: Path, expected_canonical_sha256: str,
) -> dict[str, Any]:
    manifest = _read(repo_root / manifest_path)
    rows: list[str] = []
    for entry in sorted(
        manifest.get("files") or (), key=lambda item: item["path"],
    ):
        path = repo_root / entry["path"]
        _require(
            path.is_file()
            and path.stat().st_size == entry["bytes"]
            and file_sha256(path) == entry["sha256"],
            "R1_PTR4_PROBE_MAT_NO_GO_PARENT_EVIDENCE_CHANGED",
        )
        rows.append(
            f"{entry['path']}|{entry['bytes']}|{entry['sha256']}"
        )
    canonical = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    _require(
        canonical == expected_canonical_sha256
        and manifest.get("evidence_canonical_sha256") == canonical,
        "R1_PTR4_PROBE_MAT_NO_GO_PARENT_EVIDENCE_CHANGED",
    )
    return {
        "status": "exact",
        "manifest": manifest_path.as_posix(),
        "canonical_sha256": canonical,
        "file_count": len(rows),
    }


def verify_probe_materialization_parent_gate(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    ptr4 = verify_sha_manifest_exact(
        repo_root, PARENT_PTR4_MANIFEST, EXPECTED_PTR4_CANONICAL_SHA256,
    )
    ptr4_v1 = verify_sha_manifest_exact(
        repo_root, PARENT_PTR4_V1_MANIFEST,
        EXPECTED_PTR4_V1_CANONICAL_SHA256,
    )
    for privacy_path in (PARENT_PTR4_PRIVACY, PARENT_PTR4_V1_PRIVACY):
        privacy = _read(repo_root / privacy_path)
        _require(
            privacy.get("status") == "exact"
            and privacy.get("violation_count") == 0,
            "R1_PTR4_PROBE_MAT_NO_GO_PARENT_EVIDENCE_CHANGED",
        )
    artifacts = contract_artifacts_v1(repo_root)
    stored_definition = _read(
        repo_root / "docs/superpowers/reports/r1-ptr4-v1/"
        "provider-capability-probe-definition-v1.json"
    )
    stored_fixture = _read(
        repo_root / "docs/superpowers/reports/r1-ptr4-v1/"
        "provider-capability-probe-fixture-v1.json"
    )
    stored_observer = _read(
        repo_root / "docs/superpowers/reports/r1-ptr4-v1/"
        "provider-capability-probe-observer-schema-identity-v1.json"
    )
    _require(
        stored_definition == artifacts["definition"]
        and stored_fixture == artifacts["fixture"]
        and stored_observer.get("observation_schema_sha256")
        == artifacts["definition"]["observer_schema_sha256"]
        and stored_observer.get("schema_bundle_sha256")
        == artifacts["observer_schema_bundle"]["bundle_sha256"],
        "R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE",
    )
    target = artifacts["definition"]["target"]
    required_target = {
        "identity_sha256", "provider_descriptor_hash", "model_binding_hash",
        "route_kind", "protocol", "contract_sha256",
        "request_wire_schema_sha256", "tool_schema_sha256",
        "adapter_identity_sha256", "parser_identity_sha256",
        "strict_tool_identity_sha256",
        "output_limit_observer_identity_sha256",
    }
    _require(
        required_target <= set(target),
        "R1_PTR4_PROBE_MAT_NO_GO_TARGET_IDENTITY_UNRESOLVED",
    )
    required_fixture = {
        "fixture_id", "fixture_sha256", "request_shape_sha256",
        "contract_sha256", "tool_schema_sha256",
        "target_boundary_identity_sha256",
    }
    _require(
        required_fixture <= set(artifacts["fixture"]),
        "R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE",
    )
    return {
        "status": "exact",
        "ptr4": ptr4,
        "ptr4_v1": ptr4_v1,
        "privacy_status": "exact",
        "privacy_violation_count": 0,
        "definition_sha256": artifacts["definition"]["definition_sha256"],
        "fixture_sha256": artifacts["fixture"]["fixture_sha256"],
        "observer_schema_sha256": artifacts["definition"][
            "observer_schema_sha256"
        ],
    }


def _budget_definition() -> dict[str, Any]:
    body = {
        "schema": "ProviderCapabilityProbeBudgetDefinitionV1",
        "version": 1,
        "formal_contract_stricter_than_default": True,
        "maximum_runs": 1,
        "expected_model_calls": 1,
        "maximum_total_model_calls": 1,
        "maximum_output_tokens_per_call": 8798,
        "maximum_input_tokens": 128000,
        "maximum_output_tokens": 8798,
        "maximum_usd_cost": 5,
        "maximum_cny_cost": 10,
        "maximum_elapsed_seconds": 1800,
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
    }
    return _sealed(
        "r1-ptr4-probe-mat-budget-v1", body, "definition_sha256",
    )


def _stop_conditions() -> dict[str, Any]:
    body = {
        "schema": "ProviderCapabilityProbeStopConditionsV1",
        "version": 1,
        "conditions": [
            "stop_after_first_provider_response",
            "stop_after_first_transport_failure",
            "stop_on_target_identity_mismatch_before_external_action",
            "stop_on_request_reassembly_hash_mismatch_before_external_action",
            "stop_on_budget_or_elapsed_limit",
            "stop_on_privacy_or_lineage_receipt_failure",
            "stop_after_terminal_observer_receipt",
        ],
        "implicit_primary_allowed": False,
        "retry_allowed": False,
        "implicit_fallback_allowed": False,
        "output_expansion_allowed": False,
        "resume_allowed": False,
        "second_run_allowed": False,
        "full_short_allowed": False,
        "draft_allowed": False,
        "final_review_allowed": False,
        "maintenance_allowed": False,
    }
    return _sealed(
        "r1-ptr4-probe-mat-stop-conditions-v1", body,
        "definition_sha256",
    )


def _privacy_scan(
    documents: Mapping[str, Mapping[str, Any]], fixture_source: Mapping[str, Any],
) -> dict[str, Any]:
    serialized = json.dumps(
        documents, ensure_ascii=False, sort_keys=True, allow_nan=False,
    )
    violations: list[str] = []
    for field in ("title", "premise", "outline"):
        value = fixture_source.get(field)
        if isinstance(value, str) and value and value in serialized:
            violations.append(f"fixture_business_content:{field}")
    patterns = {
        "secret_token": r"sk-[A-Za-z0-9_-]{16,}",
        "aws_access_key": r"AKIA[0-9A-Z]{16}",
        "bearer_value": r"Bearer\s+[A-Za-z0-9._~+/-]{12,}",
        "private_key": r"BEGIN [A-Z ]+PRIVATE KEY",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, serialized, flags=re.IGNORECASE):
            violations.append(name)
    forbidden_exact_keys = {
        "raw_prompt", "raw_story", "raw_tool_arguments",
        "raw_provider_response", "provider_response_body", "authorization_header",
    }

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized = str(key).casefold()
                if normalized in forbidden_exact_keys:
                    violations.append(f"forbidden_key:{path}.{normalized}")
                walk(child, f"{path}.{normalized}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(documents, "documents")
    body = {
        "schema": "ProviderCapabilityProbePrivacyScanV1",
        "version": 1,
        "status": "exact" if not violations else "blocked",
        "scanned_documents": sorted(documents),
        "violation_count": len(violations),
        "violations": sorted(set(violations)),
        "raw_prompt_included": False,
        "raw_story_included": False,
        "raw_tool_arguments_included": False,
        "raw_provider_content_included": False,
        "credentials_or_headers_included": False,
    }
    return _sealed(
        "r1-ptr4-probe-mat-privacy-scan-v1", body,
        "privacy_scan_sha256",
    )


def _check(
    name: str, exact: bool, reason_code: str, evidence_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "exact" if exact else "blocked",
        "reason_code": "exact" if exact else reason_code,
        "evidence_sha256": evidence_sha256,
    }


def materialize_provider_capability_probe_packet(
    *, repo_root: Path, live_database_path: Path, live_project_root: Path,
    output_root: Path, ledger_root: Path, canary_root: Path,
    artifact_root_label: str, cohort_id: str, run_namespace: str,
    branch: str, source_head: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize and validate a disabled packet with zero external actions."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current = current.replace(microsecond=0)
    window_start = current + timedelta(minutes=15)
    window_end = window_start + timedelta(hours=48)
    _require(
        re.fullmatch(r"r1-ptr4-probe-[0-9]{8}t[0-9]{6}z-[0-9]{3}", cohort_id)
        is not None,
        "single_use_cohort_id_invalid",
    )
    _require(run_namespace == cohort_id, "run_namespace_mismatch")
    _require(len(source_head) == 40, "source_head_invalid")
    for root in (output_root, ledger_root, canary_root):
        _require(
            not root.exists() or not any(root.iterdir()),
            "materialization_target_not_empty",
        )

    repo_root = repo_root.resolve()
    parent = verify_probe_materialization_parent_gate(repo_root)
    artifacts = contract_artifacts_v1(repo_root)
    definition = build_provider_capability_probe_definition_v1(repo_root)
    fixture = build_provider_capability_probe_fixture_v1(repo_root, definition)
    target = artifacts["definition"]["target"]
    fixture_value = artifacts["fixture"]
    budget = _budget_definition()
    stop = _stop_conditions()
    parity_before = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )

    target_definition = _sealed(
        "r1-ptr4-probe-mat-target-definition-v1", {
            "schema": "ProviderCapabilityProbeTargetDefinitionV1",
            "version": 1,
            "source_definition_sha256": artifacts["definition"][
                "definition_sha256"
            ],
            "target": target,
            "replacement_allowed": False,
        }, "target_definition_sha256",
    )
    fixture_definition = _sealed(
        "r1-ptr4-probe-mat-fixture-definition-v1", {
            "schema": "ProviderCapabilityProbePacketFixtureDefinitionV1",
            "version": 1,
            "source_fixture": fixture_value,
            "request_reassembly_gate": (
                "must_match_sealed_system_user_contract_schema_tool_hashes"
            ),
            "input_content_embedded": False,
        }, "fixture_definition_sha256",
    )
    observer_bundle = _sealed(
        "r1-ptr4-probe-mat-observer-bundle-v1", {
            "schema": "ProviderCapabilityProbeObserverDefinitionBundleV1",
            "version": 1,
            "source_definition_sha256": artifacts["definition"][
                "definition_sha256"
            ],
            "observation_schema_sha256": artifacts["definition"][
                "observer_schema_sha256"
            ],
            "source_schema_bundle_sha256": artifacts[
                "observer_schema_bundle"
            ]["bundle_sha256"],
            "classifications": artifacts["definition"]["classifications"],
            "pre_normalization_fields": artifacts["definition"][
                "pre_normalization_fields"
            ],
            "post_adapter_fields": artifacts["definition"][
                "post_adapter_fields"
            ],
            "raw_content_allowed": False,
        }, "observer_definition_bundle_sha256",
    )
    lineage_definition = _sealed(
        "r1-ptr4-probe-mat-lineage-definition-v1", {
            "schema": "ProviderCapabilityProbeAdapterLineageDefinitionV1",
            "version": 1,
            "target_boundary_identity_sha256": target["identity_sha256"],
            "adapter_identity_sha256": target["adapter_identity_sha256"],
            "parser_identity_sha256": target["parser_identity_sha256"],
            "strict_tool_identity_sha256": target[
                "strict_tool_identity_sha256"
            ],
            "output_limit_observer_identity_sha256": target[
                "output_limit_observer_identity_sha256"
            ],
            "post_adapter_fields": artifacts["definition"][
                "post_adapter_fields"
            ],
            "lineage_receipt_required": True,
            "raw_content_allowed": False,
        }, "lineage_definition_sha256",
    )
    root_identity = _sealed(
        "r1-ptr4-probe-mat-canary-root-v1", {
            "schema": "ProviderCapabilityProbeCanaryRootIdentityV1",
            "version": 1,
            "cohort_id": cohort_id,
            "run_namespace": run_namespace,
            "root_label": f"{artifact_root_label.rstrip('/')}/canary-root",
            "target_boundary_identity_sha256": target["identity_sha256"],
            "status": "unused",
            "entry_count": 0,
        }, "canary_root_identity_sha256",
    )
    ledger = _sealed(
        "r1-ptr4-probe-mat-ledger-v1", {
            "schema": "ProviderCapabilityProbeApprovalLedgerV1",
            "version": 1,
            "cohort_id": cohort_id,
            "ledger_label": f"{artifact_root_label.rstrip('/')}/ledger",
            "status": "exact",
            "reservation_status": "unreserved",
            "usage_status": "unused",
            "entry_count": 0,
            "entries": [],
        }, "ledger_identity_sha256",
    )
    cohort = _sealed(
        "r1-ptr4-probe-mat-cohort-v1", {
            "schema": "ProviderCapabilityProbeCohortV1",
            "version": 1,
            "cohort_id": cohort_id,
            "run_namespace": run_namespace,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "materialized_at": _utc(current),
            "execution_window": {
                "not_before": _utc(window_start),
                "not_after": _utc(window_end),
            },
        }, "cohort_sha256",
    )

    plan = _sealed(
        "r1-ptr4-probe-mat-plan-v1", {
            "schema": "ProviderCapabilityProbePlanV1",
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "purpose": (
                "observe_boundary_12_provider_shape_and_adapter_visible_loss"
            ),
            "branch": branch,
            "source_head": source_head,
            "materialized_at": _utc(current),
            "single_use_cohort_id": cohort_id,
            "run_namespace": run_namespace,
            "execution_window": cohort["execution_window"],
            "parent_evidence": parent,
            "probe_definition_sha256": artifacts["definition"][
                "definition_sha256"
            ],
            "probe_fixture_sha256": fixture_value["fixture_sha256"],
            "observer_schema_sha256": artifacts["definition"][
                "observer_schema_sha256"
            ],
            "target_definition_sha256": target_definition[
                "target_definition_sha256"
            ],
            "fixture_definition_sha256": fixture_definition[
                "fixture_definition_sha256"
            ],
            "observer_definition_bundle_sha256": observer_bundle[
                "observer_definition_bundle_sha256"
            ],
            "lineage_definition_sha256": lineage_definition[
                "lineage_definition_sha256"
            ],
            "budget_definition_sha256": budget["definition_sha256"],
            "stop_conditions_sha256": stop["definition_sha256"],
            "canary_root_identity_sha256": root_identity[
                "canary_root_identity_sha256"
            ],
            "approval_ledger_identity_sha256": ledger[
                "ledger_identity_sha256"
            ],
            "target_boundary_identity_sha256": target["identity_sha256"],
            "approved_provider_descriptor_hash": target[
                "provider_descriptor_hash"
            ],
            "approved_model_binding_hash": target["model_binding_hash"],
            "approved_route_kind": "configured_fallback",
            "approved_protocol": "anthropic",
            "approved_execution_mode": "plain",
            "approved_requested_max_output_tokens": 8798,
            "external_actions_authorized": False,
            "execution_authorized": False,
            "excluded_scopes": [
                "full_short", "draft", "final_review", "maintenance",
                "planning_root_cause_fix", "production_fix",
            ],
        }, "plan_sha256",
    )
    candidate = _sealed(
        "r1-ptr4-probe-mat-candidate-v1", {
            "schema": "ProviderCapabilityProbeFinalApprovalCandidateV1",
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_probe_definition_sha256": artifacts["definition"][
                "definition_sha256"
            ],
            "bound_fixture_sha256": fixture_value["fixture_sha256"],
            "bound_observer_schema_sha256": artifacts["definition"][
                "observer_schema_sha256"
            ],
            "bound_target_boundary_identity_sha256": target[
                "identity_sha256"
            ],
            "single_use_cohort_id": cohort_id,
            "execution_window": cohort["execution_window"],
            "materialized_at": _utc(current),
            "named_approver": "FINAL_USER_AUTHORIZATION_REQUIRED",
            "candidate_status": "disabled",
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "execution_authorized": False,
            "authorize_credential_lookup": False,
            "authorize_provider_client_creation": False,
            "authorize_network": False,
            "authorize_model_call": False,
            "authorize_paid_model_call": False,
            "approved_budget": budget,
            "approved_stop_conditions_sha256": stop["definition_sha256"],
            "approval_ledger_identity_sha256": ledger[
                "ledger_identity_sha256"
            ],
            "canary_root_identity_sha256": root_identity[
                "canary_root_identity_sha256"
            ],
            "signed_approval_materialized": False,
            "confirmed_patch_materialized": False,
            "execution_performed": False,
        }, "approval_candidate_sha256",
    )
    patch = _sealed(
        "r1-ptr4-probe-mat-patch-template-v1", {
            "schema": "ProviderCapabilityProbeAuthorizationPatchTemplateV1",
            "version": 1,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "template_status": "unconfirmed",
            "confirmation_required": True,
            "execution_authorized": False,
            "authorize_credential_lookup": False,
            "authorize_provider_client_creation": False,
            "authorize_network": False,
            "authorize_model_call": False,
            "authorize_paid_model_call": False,
            "required_user_action": (
                "materialize_a_separate_confirmed_patch_and_signed_approval"
            ),
            "confirmed_patch_materialized": False,
        }, "authorization_patch_template_sha256",
    )
    preview = _sealed(
        "r1-ptr4-probe-mat-execution-preview-v1", {
            "schema": "ProviderCapabilityProbeExecutionPreviewV1",
            "version": 1,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "bound_authorization_patch_template_sha256": patch[
                "authorization_patch_template_sha256"
            ],
            "single_use_cohort_id": cohort_id,
            "execution_window": cohort["execution_window"],
            "future_sequence": [
                "validate_signed_approval_and_confirmed_patch",
                "revalidate_parent_evidence_and_live_parity",
                "reserve_isolated_ledger_once",
                "reassemble_request_and_require_all_sealed_hashes",
                "resolve_exact_bound_configured_fallback_identity",
                "perform_at_most_one_provider_model_network_paid_call",
                "capture_pre_normalization_hash_shape_count_metadata",
                "capture_post_adapter_and_parser_lineage",
                "persist_only_typed_statuses_counts_shapes_and_hashes",
                "consume_cohort_and_stop_after_first_terminal",
            ],
            "future_command": "ABSENT_UNTIL_SIGNED_APPROVAL",
            "candidate_is_executable": False,
            "execution_authorized": False,
            "do_not_execute": True,
            "signed_approval_materialized": False,
            "confirmed_patch_materialized": False,
        }, "execution_preview_sha256",
    )

    sentinel = FailClosedNetworkSentinel()
    with sentinel:
        fake_observation = build_provider_capability_probe_observation_v1(
            definition=definition,
            fixture=fixture,
            blocks=[],
            finish_reason="max_tokens",
            output_tokens=8798,
            effective_provider_max_output_tokens=None,
            adapter_visible_characters=0,
            adapter_tool_arguments_present=False,
            parser_reached=True,
            strict_tool_reached=False,
            json_conversion_reached=False,
            wire_schema_reached=False,
            semantic_validation_reached=False,
            provider_capability_evidence_status="fake_rehearsal_only",
        )
    _require(sentinel.network_call_count == 0, "materialization_network_observed")
    rehearsal = _sealed(
        "r1-ptr4-probe-mat-prelaunch-rehearsal-v1", {
            "schema": "ProviderCapabilityProbePreLaunchRehearsalV1",
            "version": 1,
            "status": "exact",
            "mode": "independent_fake_only",
            "bound_plan_sha256": plan["plan_sha256"],
            "observer_receipt_generated": True,
            "observer_receipt_sha256": fake_observation.receipt_sha256,
            "observer_classification": fake_observation.post_adapter.output_limit_classifier,
            "provider_capability_evidence_status": "fake_rehearsal_only",
            "goal_stop_verified": True,
            "control_plane_binding_verified": True,
            "privacy_contract_verified": True,
            "real_provider_probe": "NOT_EXECUTED",
            "external_action_counters": EXTERNAL_ACTION_COUNTERS,
        }, "prelaunch_rehearsal_sha256",
    )
    readiness = _sealed(
        "r1-ptr4-probe-mat-operational-readiness-v1", {
            "schema": "ProviderCapabilityProbeOperationalReadinessV1",
            "version": 1,
            "status": "exact",
            "control_plane_status": "exact",
            "parent_evidence_status": "exact",
            "target_binding_status": "exact",
            "fixture_binding_status": "exact_hash_bound",
            "observer_binding_status": "exact",
            "budget_status": "exact",
            "stop_conditions_status": "exact",
            "cohort_status": "unused",
            "approval_status": "unreserved_disabled_candidate",
            "ledger_status": "exact_empty",
            "canary_root_status": "exact_unused",
            "signed_approval_status": "ABSENT",
            "confirmed_patch_status": "ABSENT",
            "execution_status": "NOT_EXECUTED",
            "new_single_use_approval_required": True,
        }, "operational_readiness_sha256",
    )

    fixture_source = _read(repo_root / fixture.source_workload_file)
    pre_receipt_documents = {
        "plan": plan,
        "candidate": candidate,
        "patch_template": patch,
        "execution_preview": preview,
        "target_definition": target_definition,
        "fixture_definition": fixture_definition,
        "observer_bundle": observer_bundle,
        "lineage_definition": lineage_definition,
        "budget_definition": budget,
        "stop_conditions": stop,
        "cohort": cohort,
        "ledger": ledger,
        "canary_root": root_identity,
        "prelaunch_rehearsal": rehearsal,
        "operational_readiness": readiness,
    }
    privacy = _privacy_scan(pre_receipt_documents, fixture_source)
    parity_after = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
    )
    checks = [
        _check("profile_scope", plan["profile_id"] == PROFILE_ID and plan["approval_scope"] == APPROVAL_SCOPE, "profile_scope_mismatch", plan["plan_sha256"]),
        _check("ptr4_parent_evidence", parent["status"] == "exact", "R1_PTR4_PROBE_MAT_NO_GO_PARENT_EVIDENCE_CHANGED", parent["ptr4"]["canonical_sha256"]),
        _check("probe_definition", plan["probe_definition_sha256"] == artifacts["definition"]["definition_sha256"], "probe_definition_mismatch", artifacts["definition"]["definition_sha256"]),
        _check("fixture_definition", plan["probe_fixture_sha256"] == fixture_value["fixture_sha256"], "R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE", fixture_value["fixture_sha256"]),
        _check("boundary_12_identity", target["boundary"] == 12 and target["identity_sha256"] == fixture_value["target_boundary_identity_sha256"], "R1_PTR4_PROBE_MAT_NO_GO_TARGET_IDENTITY_UNRESOLVED", target["identity_sha256"]),
        _check("provider_model_route", target["route_kind"] == "configured_fallback" and target["protocol"] == "anthropic" and bool(target["provider_descriptor_hash"]) and bool(target["model_binding_hash"]), "target_route_identity_mismatch", target["identity_sha256"]),
        _check("adapter_parser_strict_tool", bool(target["adapter_identity_sha256"]) and bool(target["parser_identity_sha256"]) and bool(target["strict_tool_identity_sha256"]), "adapter_lineage_identity_mismatch", lineage_definition["lineage_definition_sha256"]),
        _check("observer_schema", observer_bundle["observation_schema_sha256"] == artifacts["definition"]["observer_schema_sha256"], "observer_schema_mismatch", observer_bundle["observer_definition_bundle_sha256"]),
        _check("privacy", privacy["status"] == "exact" and privacy["violation_count"] == 0, "privacy_violation", privacy["privacy_scan_sha256"]),
        _check("budget", budget["maximum_total_model_calls"] == 1 and budget["maximum_output_tokens_per_call"] == 8798, "budget_mismatch", budget["definition_sha256"]),
        _check("stop_conditions", stop["retry_allowed"] is False and stop["resume_allowed"] is False and stop["second_run_allowed"] is False, "stop_conditions_mismatch", stop["definition_sha256"]),
        _check("cohort", cohort["usage_status"] == "unused" and cohort["reservation_status"] == "unreserved", "cohort_not_unused", cohort["cohort_sha256"]),
        _check("ledger", ledger["entry_count"] == 0 and ledger["reservation_status"] == "unreserved", "ledger_not_empty", ledger["ledger_identity_sha256"]),
        _check("canary_root", root_identity["status"] == "unused" and root_identity["entry_count"] == 0, "canary_root_not_unused", root_identity["canary_root_identity_sha256"]),
        _check("disabled_candidate", candidate["execution_authorized"] is False and candidate["usage_status"] == "unused", "candidate_not_disabled", candidate["approval_candidate_sha256"]),
        _check("authorization_patch_template", patch["execution_authorized"] is False and patch["confirmed_patch_materialized"] is False, "patch_template_not_inert", patch["authorization_patch_template_sha256"]),
        _check("execution_preview", preview["do_not_execute"] is True and preview["future_command"] == "ABSENT_UNTIL_SIGNED_APPROVAL", "execution_preview_not_inert", preview["execution_preview_sha256"]),
        _check("prelaunch_rehearsal", rehearsal["provider_capability_evidence_status"] == "fake_rehearsal_only" and rehearsal["real_provider_probe"] == "NOT_EXECUTED", "fake_rehearsal_invalid", rehearsal["prelaunch_rehearsal_sha256"]),
        _check("operational_readiness", readiness["status"] == "exact" and readiness["signed_approval_status"] == "ABSENT", "operational_readiness_blocked", readiness["operational_readiness_sha256"]),
        _check("live_parity", parity_before["parity_sha256"] == parity_after["parity_sha256"], "live_parity_changed", parity_after["parity_sha256"]),
        _check("external_actions_zero", sentinel.network_call_count == 0 and all(value == 0 for value in EXTERNAL_ACTION_COUNTERS.values()), "external_action_observed"),
    ]
    receipt = _sealed(
        "r1-ptr4-probe-mat-validate-only-receipt-v1", {
            "schema": "ProviderCapabilityProbeValidateOnlyReceiptV1",
            "version": 1,
            "overall_status": (
                "exact" if all(item["status"] == "exact" for item in checks)
                else "blocked"
            ),
            "ordered_checks": checks,
            "bound_plan_sha256": plan["plan_sha256"],
            "bound_approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "approval_state": "disabled_candidate",
            "approval_reservation_status": "unreserved",
            "cohort_usage_status": "unused",
            "ledger_entry_count": 0,
            "parity": {
                "status": "exact",
                "before_sha256": parity_before["parity_sha256"],
                "after_sha256": parity_after["parity_sha256"],
            },
            "privacy": {
                "status": privacy["status"],
                "violation_count": privacy["violation_count"],
                "privacy_scan_sha256": privacy["privacy_scan_sha256"],
            },
            "external_action_counters": EXTERNAL_ACTION_COUNTERS,
            "signed_approval_materialized": False,
            "confirmed_patch_materialized": False,
            "execution_performed": False,
        }, "validate_only_receipt_sha256",
    )
    _require(receipt["overall_status"] == "exact", "validate_only_blocked")

    paths = {
        "plan": output_root / "provider-capability-probe-plan-v1.json",
        "candidate": output_root / "provider-capability-probe-final-approval-candidate-v1.json",
        "patch_template": output_root / "provider-capability-probe-authorization-patch-template-v1.json",
        "execution_preview": output_root / "provider-capability-probe-execution-preview-v1.json",
        "target_definition": output_root / "provider-capability-probe-target-definition-v1.json",
        "fixture_definition": output_root / "provider-capability-probe-fixture-definition-v1.json",
        "observer_bundle": output_root / "provider-capability-probe-observer-definition-bundle-v1.json",
        "lineage_definition": output_root / "provider-capability-probe-adapter-lineage-observation-definition-v1.json",
        "budget_definition": output_root / "provider-capability-probe-budget-definition-v1.json",
        "stop_conditions": output_root / "provider-capability-probe-stop-conditions-v1.json",
        "cohort": output_root / "provider-capability-probe-cohort-v1.json",
        "prelaunch_rehearsal": output_root / "provider-capability-probe-pre-launch-rehearsal-v1.json",
        "operational_readiness": output_root / "provider-capability-probe-operational-readiness-v1.json",
        "privacy": output_root / "provider-capability-probe-privacy-scan-v1.json",
        "validate_only_receipt": output_root / "provider-capability-probe-validate-only-receipt-v1.json",
        "ledger": ledger_root / "provider-capability-probe-approval-ledger-v1.json",
        "canary_root": canary_root / "provider-capability-probe-canary-root-identity-v1.json",
        "index": output_root / "provider-capability-probe-materialization-index-v1.json",
    }
    documents = {
        "plan": plan,
        "candidate": candidate,
        "patch_template": patch,
        "execution_preview": preview,
        "target_definition": target_definition,
        "fixture_definition": fixture_definition,
        "observer_bundle": observer_bundle,
        "lineage_definition": lineage_definition,
        "budget_definition": budget,
        "stop_conditions": stop,
        "cohort": cohort,
        "prelaunch_rehearsal": rehearsal,
        "operational_readiness": readiness,
        "privacy": privacy,
        "validate_only_receipt": receipt,
        "ledger": ledger,
        "canary_root": root_identity,
    }
    for name, document in documents.items():
        _write(paths[name], document)
    file_manifest = {
        path.relative_to(output_root.parent).as_posix(): file_sha256(path)
        for name, path in sorted(paths.items()) if name != "index"
    }
    index = _sealed(
        "r1-ptr4-probe-mat-index-v1", {
            "schema": "ProviderCapabilityProbeMaterializationIndexV1",
            "version": 1,
            "contract_status": (
                "R1_PTR4_PROVIDER_CAPABILITY_PROBE_APPROVAL_PACKET_READY"
            ),
            "status": (
                "R1_PTR4_PROVIDER_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION"
            ),
            "single_use_cohort_id": cohort_id,
            "execution_window": cohort["execution_window"],
            "files": file_manifest,
            "plan_sha256": plan["plan_sha256"],
            "approval_candidate_sha256": candidate[
                "approval_candidate_sha256"
            ],
            "authorization_patch_template_sha256": patch[
                "authorization_patch_template_sha256"
            ],
            "validate_only_receipt_sha256": receipt[
                "validate_only_receipt_sha256"
            ],
            "execution_preview_sha256": preview[
                "execution_preview_sha256"
            ],
            "probe_definition_sha256": artifacts["definition"][
                "definition_sha256"
            ],
            "fixture_sha256": fixture_value["fixture_sha256"],
            "observer_schema_sha256": artifacts["definition"][
                "observer_schema_sha256"
            ],
            "approval_reservation_status": "unreserved",
            "cohort_usage_status": "unused",
            "ledger_entry_count": 0,
            "external_action_counters": EXTERNAL_ACTION_COUNTERS,
            "signed_approval_materialized": False,
            "confirmed_patch_materialized": False,
            "real_provider_probe": "NOT_EXECUTED",
            "production_fix": "NOT_IMPLEMENTED",
        }, "materialization_index_sha256",
    )
    _write(paths["index"], index)
    return {
        **documents,
        "index": index,
        "paths": {name: path for name, path in paths.items()},
        "execution_performed": False,
        "external_action_counters": EXTERNAL_ACTION_COUNTERS,
    }


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize an inert R1-PTR4 Provider probe packet",
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--canary-root", type=Path, required=True)
    parser.add_argument("--artifact-root-label", required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--run-namespace", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--materialized-at", type=_parse_utc)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = materialize_provider_capability_probe_packet(
        repo_root=args.repo_root,
        live_database_path=args.live_database,
        live_project_root=args.live_project_root,
        output_root=args.output_root,
        ledger_root=args.ledger_root,
        canary_root=args.canary_root,
        artifact_root_label=args.artifact_root_label,
        cohort_id=args.cohort_id,
        run_namespace=args.run_namespace,
        branch=args.branch,
        source_head=args.source_head,
        now=args.materialized_at,
    )
    print(json.dumps({
        "gate": result["index"]["contract_status"],
        "status": result["index"]["status"],
        "cohort": result["index"]["single_use_cohort_id"],
        "plan_sha256": result["plan"]["plan_sha256"],
        "candidate_sha256": result["candidate"]["approval_candidate_sha256"],
        "external_action_counters": result["external_action_counters"],
        "execution_performed": result["execution_performed"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
