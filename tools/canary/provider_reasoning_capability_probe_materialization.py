"""Materialize an inert R1-PTR7 reasoning capability probe packet.

This module cannot create a Signed Approval or Confirmed Patch and has no
credential, Provider-client, network, model, or paid-call implementation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .artifact_hash import file_sha256, live_parity_manifest


PROFILE_ID = "r1_ptr7_provider_reasoning_capability_probe_1"
APPROVAL_SCOPE = "provider_reasoning_capability_probe"
PARENT_ERROR = "R1_PTR7_NO_GO_PARENT_EVIDENCE_CHANGED"
TARGET_PROVIDER_IDENTITY = (
    "98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6"
)
TARGET_MODEL_IDENTITY = (
    "fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998"
)
PARENT_BOUNDARY_IDENTITY = (
    "851b447afba31d2296ebafc223ea4189464920e332693a5a03d5cf0b821675f0"
)
PARENT_CONTRACT_IDENTITY = (
    "f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7"
)
ZERO_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}
PARENT_MANIFESTS = (
    ("docs/superpowers/reports/r1-ptr4/r1-ptr4-sha256-manifest-v1.json", "files"),
    ("docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-sha256-manifest-v1.json", "files"),
    (
        "docs/superpowers/reports/r1-ptr4-probe-mat/"
        "r1-ptr4-probe-20260820t110721z-001/real-observation-v1/"
        "r1-ptr4-probe-real-obs-1-final-sha256-manifest-v1.json",
        "entries",
    ),
    ("docs/superpowers/reports/r1-ptr5/r1-ptr5-final-sha256-manifest-v1.json", "files"),
    ("docs/superpowers/reports/r1-ptr6/r1-ptr6-final-sha256-manifest-v1.json", "files"),
)


class ProviderReasoningProbeMaterializationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise ProviderReasoningProbeMaterializationError(reason_code)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderReasoningProbeMaterializationError(PARENT_ERROR) from exc
    _require(isinstance(value, dict), PARENT_ERROR)
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = dict(body)
    value[field] = domain_sha256(domain, value)
    return value


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def verify_parent_evidence_exact(repo_root: Path) -> dict[str, Any]:
    results = []
    for relative, collection in PARENT_MANIFESTS:
        manifest = _read(repo_root / relative)
        entries = list(manifest.get(collection) or ())
        _require(bool(entries), PARENT_ERROR)
        for entry in entries:
            path = repo_root / str(entry.get("path") or "")
            _require(path.is_file(), PARENT_ERROR)
            _require(file_sha256(path) == entry.get("sha256"), PARENT_ERROR)
            if entry.get("bytes") is not None:
                _require(path.stat().st_size == entry["bytes"], PARENT_ERROR)
        results.append({
            "manifest": relative,
            "entry_count": len(entries),
            "status": "exact",
            "manifest_sha256": file_sha256(repo_root / relative),
        })
    return {"status": "exact", "manifests": results}


def _classification_rules() -> dict[str, Any]:
    return {
        "SUPPORTED": [
            "parameter accepted",
            "reasoning is observably bounded at or below the requested cap",
            "a final text or tool artifact is emitted inside the unchanged total cap",
            "token separation is reported when the capability claim includes token separation",
        ],
        "UNSUPPORTED": [
            "typed parameter rejection",
            "protocol response states capability unavailable",
        ],
        "IGNORED": [
            "parameter accepted but observed reasoning exceeds the requested cap",
            "reasoning-only max_tokens repeats despite the requested reservation",
        ],
        "UNKNOWN": [
            "parameter accepted but enforcement cannot be observed",
            "reasoning/final token accounting is not separately exposed",
            "response shape is insufficient to distinguish support from coincidence",
        ],
    }


def materialize_provider_reasoning_probe_packet(
    *,
    repo_root: Path,
    live_database_path: Path,
    live_project_root: Path,
    cohort_root: Path,
    artifact_root_label: str,
    cohort_id: str,
    branch: str,
    source_head: str,
    now: datetime,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    cohort_root = cohort_root.resolve()
    _require(not cohort_root.exists(), "materialization_target_not_empty")
    parent = verify_parent_evidence_exact(repo_root)
    parity_before = live_parity_manifest(
        database_path=live_database_path,
        project_root=live_project_root,
    )
    created = _utc(now)
    expires = _utc(now + timedelta(hours=48))
    materialization = cohort_root / "materialization-v1"
    ledger_root = cohort_root / "ledger"
    canary_root = cohort_root / "canary-root"

    request_schema = {
        "protocol": "anthropic",
        "execution_mode": "canary_only_synthetic",
        "total_output_tokens": 16000,
        "requested_reasoning_cap_tokens": 8000,
        "requested_final_reserve_tokens": 8000,
        "reasoning_control_shape": {
            "type": "enabled",
            "budget_tokens": "integer",
        },
        "messages": ["system", "user"],
        "stream": True,
        "tools": False,
        "business_contract": False,
    }
    request_schema_sha = domain_sha256(
        "r1-ptr7-reasoning-request-schema-v1", request_schema,
    )
    route_identity = domain_sha256("r1-ptr7-route-identity-v1", {
        "provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
        "model_identity_sha256": TARGET_MODEL_IDENTITY,
        "route_kind": "configured_fallback",
        "protocol": "anthropic",
        "execution_mode": "canary_only_synthetic",
    })
    observer_fields = {
        "provider": [
            "provider_identity_sha256", "model_identity_sha256",
            "route_identity_sha256", "route_kind", "protocol",
            "requested_reasoning_cap_tokens",
            "requested_final_reserve_tokens", "parameter_disposition",
            "finish_reason", "output_tokens", "reasoning_tokens_if_reported",
            "final_output_tokens_if_reported", "token_separation_reported",
            "thinking_block_count", "final_text_block_count",
            "tool_block_count", "visible_characters",
            "reasoning_characters_if_observable",
        ],
        "privacy": [
            "raw_prompt_omitted", "raw_provider_content_omitted",
            "raw_tool_arguments_omitted", "credentials_omitted",
        ],
        "classifications": ["SUPPORTED", "UNSUPPORTED", "IGNORED", "UNKNOWN"],
        "rules": _classification_rules(),
    }
    observer_sha = domain_sha256(
        "provider-reasoning-capability-observer-v1", observer_fields,
    )
    definition = _sealed(
        "provider-reasoning-capability-probe-definition-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeDefinitionV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "target": {
                "provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
                "model_identity_sha256": TARGET_MODEL_IDENTITY,
                "route_identity_sha256": route_identity,
                "route_kind": "configured_fallback",
                "protocol": "anthropic",
                "parent_boundary_identity_sha256": PARENT_BOUNDARY_IDENTITY,
                "parent_contract_identity_sha256": PARENT_CONTRACT_IDENTITY,
                "request_schema_identity_sha256": request_schema_sha,
            },
            "capabilities_under_test": [
                "reasoning_budget_cap",
                "final_output_reservation",
                "reasoning_output_token_separation",
                "capability_bound_output_allocation",
            ],
            "one_call_only": True,
            "provider_switch_allowed": False,
            "model_substitution_allowed": False,
            "business_workflow_allowed": False,
            "production_runtime_used": False,
            "observer_identity_sha256": observer_sha,
            "classification_rules": _classification_rules(),
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "definition_sha256",
    )
    fixture = _sealed(
        "provider-reasoning-capability-probe-fixture-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeFixtureV1",
            "version": 1,
            "fixture_id": "r1-ptr7-synthetic-allocation-check-v1",
            "fixture_kind": "non_business_deterministic_checksum",
            "request_schema_identity_sha256": request_schema_sha,
            "provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
            "model_identity_sha256": TARGET_MODEL_IDENTITY,
            "route_identity_sha256": route_identity,
            "parent_contract_identity_sha256": PARENT_CONTRACT_IDENTITY,
            "synthetic_recipe": {
                "algorithm": "sha256_seeded_integer_checksum_v1",
                "seed_sha256": hashlib.sha256(
                    b"r1-ptr7-provider-reasoning-capability-probe-v1"
                ).hexdigest(),
                "item_count": 512,
                "final_artifact_schema": {
                    "type": "object",
                    "required": ["probe_result", "checksum"],
                    "additionalProperties": False,
                },
                "expected_final_artifact_hash_only": True,
            },
            "raw_prompt_embedded": False,
            "raw_story_embedded": False,
            "raw_tool_arguments_embedded": False,
        },
        "fixture_sha256",
    )
    observer = _sealed(
        "provider-reasoning-capability-probe-observer-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeObserverDefinitionV1",
            "version": 1,
            "fields": observer_fields,
            "raw_content_allowed": False,
            "observer_identity_sha256": observer_sha,
        },
        "observer_definition_sha256",
    )
    budget = _sealed(
        "provider-reasoning-capability-probe-budget-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeBudgetDefinitionV1",
            "version": 1,
            "formal_contract_stricter_than_default": False,
            "maximum_runs": 1,
            "maximum_total_model_calls": 1,
            "maximum_input_tokens": 128000,
            "maximum_output_tokens": 16000,
            "maximum_output_tokens_per_call": 16000,
            "requested_reasoning_cap_tokens": 8000,
            "requested_final_reserve_tokens": 8000,
            "maximum_usd_cost": 5,
            "maximum_cny_cost": 10,
            "maximum_elapsed_seconds": 1800,
            "first_terminal_stop": True,
            "second_run_allowed": False,
            "resume_after_terminal": False,
        },
        "budget_definition_sha256",
    )
    stop = _sealed(
        "provider-reasoning-capability-probe-stop-conditions-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeStopConditionsV1",
            "version": 1,
            "stop_on_first_terminal": True,
            "stop_after_first_model_call": True,
            "stop_on_parameter_rejection": True,
            "stop_on_budget_limit": True,
            "stop_on_identity_or_parity_mismatch_before_dispatch": True,
            "no_retry": True,
            "no_resume": True,
            "no_second_run": True,
            "no_provider_switch": True,
            "no_model_substitution": True,
            "no_business_workflow": True,
        },
        "stop_conditions_sha256",
    )
    cohort = _sealed(
        "provider-reasoning-capability-probe-cohort-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeCohortV1",
            "version": 1,
            "cohort_id": cohort_id,
            "run_namespace": cohort_id,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "execution_window_start_utc": created,
            "execution_window_end_utc": expires,
            "single_use": True,
        },
        "cohort_sha256",
    )
    canary = _sealed(
        "provider-reasoning-capability-probe-canary-root-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeCanaryRootV1",
            "version": 1,
            "cohort_id": cohort_id,
            "status": "unused",
            "entry_count": 0,
            "production_project_linked": False,
        },
        "canary_root_identity_sha256",
    )
    ledger = _sealed(
        "provider-reasoning-capability-probe-ledger-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeLedgerV1",
            "version": 1,
            "cohort_id": cohort_id,
            "reservation_status": "unreserved",
            "usage_status": "unused",
            "entry_count": 0,
            "entries": [],
        },
        "ledger_identity_sha256",
    )
    rehearsal = _sealed(
        "provider-reasoning-capability-probe-prelaunch-v1",
        {
            "schema": "ProviderReasoningCapabilityProbePrelaunchRehearsalV1",
            "version": 1,
            "status": "exact",
            "mode": "fake_offline_only",
            "cases": [
                {"case": "cap_enforced_final_emitted", "classification": "SUPPORTED"},
                {"case": "parameter_rejected", "classification": "UNSUPPORTED"},
                {"case": "reasoning_only_max_tokens", "classification": "IGNORED"},
                {"case": "accepted_no_token_split", "classification": "UNKNOWN"},
            ],
            "no_guessing_verified": True,
            "provider_capability_evidence_status": "fake_rehearsal_only",
            "real_provider_probe": "NOT_EXECUTED",
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "prelaunch_rehearsal_sha256",
    )
    plan = _sealed(
        "provider-reasoning-capability-probe-plan-v1",
        {
            "schema": "ProviderReasoningCapabilityProbePlanV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "branch": branch,
            "source_head": source_head,
            "cohort_id": cohort_id,
            "execution_window_start_utc": created,
            "execution_window_end_utc": expires,
            "definition_sha256": definition["definition_sha256"],
            "fixture_sha256": fixture["fixture_sha256"],
            "observer_sha256": observer["observer_definition_sha256"],
            "budget_sha256": budget["budget_definition_sha256"],
            "stop_conditions_sha256": stop["stop_conditions_sha256"],
            "only_provider_capability_probe": True,
            "production_fix_allowed": False,
            "full_short_allowed": False,
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "plan_sha256",
    )
    candidate = _sealed(
        "provider-reasoning-capability-probe-candidate-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeFinalApprovalCandidateV1",
            "version": 1,
            "candidate_status": "disabled",
            "execution_authorized": False,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": cohort_id,
            "plan_sha256": plan["plan_sha256"],
            "definition_sha256": definition["definition_sha256"],
            "fixture_sha256": fixture["fixture_sha256"],
            "observer_sha256": observer["observer_definition_sha256"],
            "budget_sha256": budget["budget_definition_sha256"],
            "stop_conditions_sha256": stop["stop_conditions_sha256"],
            "cohort_sha256": cohort["cohort_sha256"],
            "ledger_identity_sha256": ledger["ledger_identity_sha256"],
            "canary_root_identity_sha256": canary["canary_root_identity_sha256"],
            "signed_approval_status": "ABSENT",
            "confirmed_patch_status": "ABSENT",
            "authorize_credential_lookup": False,
            "authorize_provider_client_creation": False,
            "authorize_network": False,
            "authorize_model_call": False,
            "authorize_paid_model_call": False,
            "execution_performed": False,
        },
        "candidate_sha256",
    )
    patch = _sealed(
        "provider-reasoning-capability-probe-patch-template-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeAuthorizationPatchTemplateV1",
            "version": 1,
            "template_status": "unconfirmed",
            "execution_authorized": False,
            "candidate_sha256": candidate["candidate_sha256"],
            "confirmed_patch_materialized": False,
            "signed_approval_materialized": False,
            "required_future_action": "materialize separate confirmed patch and signed approval after final user authorization",
        },
        "authorization_patch_template_sha256",
    )
    preview = _sealed(
        "provider-reasoning-capability-probe-execution-preview-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeExecutionPreviewV1",
            "version": 1,
            "candidate_is_executable": False,
            "execution_authorized": False,
            "do_not_execute": True,
            "future_command": "ABSENT_UNTIL_SIGNED_APPROVAL",
            "expected_max_runs": 1,
            "expected_max_model_calls": 1,
            "provider_switch": False,
            "model_substitution": False,
            "production_workflow": False,
            "real_provider_probe": "NOT_EXECUTED",
        },
        "execution_preview_sha256",
    )
    privacy = _sealed(
        "provider-reasoning-capability-probe-privacy-v1",
        {
            "schema": "ProviderReasoningCapabilityProbePrivacyScanV1",
            "version": 1,
            "status": "exact",
            "violation_count": 0,
            "raw_prompt_present": False,
            "raw_story_present": False,
            "raw_tool_arguments_present": False,
            "raw_provider_content_present": False,
            "credentials_present": False,
            "provider_endpoint_present": False,
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "privacy_scan_sha256",
    )

    files = {
        "provider-reasoning-capability-probe-plan-v1.json": plan,
        "provider-reasoning-capability-probe-final-approval-candidate-v1.json": candidate,
        "provider-reasoning-capability-probe-authorization-patch-template-v1.json": patch,
        "provider-reasoning-capability-probe-execution-preview-v1.json": preview,
        "provider-reasoning-capability-probe-definition-v1.json": definition,
        "provider-reasoning-capability-probe-fixture-definition-v1.json": fixture,
        "provider-reasoning-capability-probe-observer-definition-v1.json": observer,
        "provider-reasoning-capability-probe-budget-definition-v1.json": budget,
        "provider-reasoning-capability-probe-stop-conditions-v1.json": stop,
        "provider-reasoning-capability-probe-cohort-v1.json": cohort,
        "provider-reasoning-capability-probe-pre-launch-rehearsal-v1.json": rehearsal,
        "provider-reasoning-capability-probe-privacy-scan-v1.json": privacy,
    }
    for name, value in files.items():
        _write(materialization / name, value)
    _write(ledger_root / "provider-reasoning-capability-probe-ledger-v1.json", ledger)
    _write(
        canary_root / "provider-reasoning-capability-probe-canary-root-v1.json",
        canary,
    )
    parity_after = live_parity_manifest(
        database_path=live_database_path,
        project_root=live_project_root,
    )
    _require(
        parity_before["parity_sha256"] == parity_after["parity_sha256"],
        "live_parity_mismatch",
    )
    checks = [
        ("parent_evidence", parent["status"] == "exact"),
        ("provider_identity", definition["target"]["provider_identity_sha256"] == TARGET_PROVIDER_IDENTITY),
        ("route_identity", definition["target"]["route_identity_sha256"] == route_identity),
        ("model_identity", definition["target"]["model_identity_sha256"] == TARGET_MODEL_IDENTITY),
        ("capability_definition", len(definition["capabilities_under_test"]) == 4),
        ("probe_fixture", fixture["raw_story_embedded"] is False),
        ("observer", observer["raw_content_allowed"] is False),
        ("budget", budget["maximum_total_model_calls"] == 1 and budget["maximum_output_tokens"] == 16000),
        ("stop_conditions", stop["no_retry"] and stop["no_second_run"]),
        ("cohort", cohort["usage_status"] == "unused" and cohort["reservation_status"] == "unreserved"),
        ("ledger", ledger["entry_count"] == 0 and ledger["reservation_status"] == "unreserved"),
        ("privacy", privacy["status"] == "exact" and privacy["violation_count"] == 0),
        ("live_parity", parity_before["parity_sha256"] == parity_after["parity_sha256"]),
        ("candidate_inert", candidate["execution_authorized"] is False and candidate["usage_status"] == "unused"),
        ("signed_approval_absent", candidate["signed_approval_status"] == "ABSENT"),
        ("confirmed_patch_absent", candidate["confirmed_patch_status"] == "ABSENT"),
        ("external_actions_zero", all(value == 0 for value in ZERO_COUNTERS.values())),
    ]
    receipt = _sealed(
        "provider-reasoning-capability-probe-validate-only-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeValidateOnlyReceiptV1",
            "version": 1,
            "overall_status": "exact" if all(ok for _, ok in checks) else "blocked",
            "ordered_checks": [
                {"name": name, "status": "exact" if ok else "blocked"}
                for name, ok in checks
            ],
            "approval_state": "disabled_candidate",
            "approval_reservation_status": "unreserved",
            "cohort_usage_status": "unused",
            "ledger_entry_count": 0,
            "live_parity_before_sha256": parity_before["parity_sha256"],
            "live_parity_after_sha256": parity_after["parity_sha256"],
            "signed_approval_status": "ABSENT",
            "confirmed_patch_status": "ABSENT",
            "execution_performed": False,
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "validate_only_receipt_sha256",
    )
    _require(receipt["overall_status"] == "exact", "validate_only_blocked")
    receipt_name = "provider-reasoning-capability-probe-validate-only-receipt-v1.json"
    _write(materialization / receipt_name, receipt)
    written = {
        f"materialization-v1/{name}": file_sha256(materialization / name)
        for name in sorted([*files, receipt_name])
    }
    written.update({
        "ledger/provider-reasoning-capability-probe-ledger-v1.json": file_sha256(
            ledger_root / "provider-reasoning-capability-probe-ledger-v1.json"
        ),
        "canary-root/provider-reasoning-capability-probe-canary-root-v1.json": file_sha256(
            canary_root / "provider-reasoning-capability-probe-canary-root-v1.json"
        ),
    })
    index = _sealed(
        "provider-reasoning-capability-probe-materialization-index-v1",
        {
            "schema": "ProviderReasoningCapabilityProbeMaterializationIndexV1",
            "version": 1,
            "contract_status": "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_APPROVAL_PACKET_READY",
            "status": "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION",
            "artifact_root": artifact_root_label,
            "cohort_id": cohort_id,
            "files": written,
            "plan_sha256": plan["plan_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "patch_template_sha256": patch["authorization_patch_template_sha256"],
            "validate_only_sha256": receipt["validate_only_receipt_sha256"],
            "definition_sha256": definition["definition_sha256"],
            "fixture_sha256": fixture["fixture_sha256"],
            "observer_sha256": observer["observer_definition_sha256"],
            "budget_sha256": budget["budget_definition_sha256"],
            "cohort_sha256": cohort["cohort_sha256"],
            "ledger_identity_sha256": ledger["ledger_identity_sha256"],
            "canary_root_identity_sha256": canary["canary_root_identity_sha256"],
            "signed_approval_status": "ABSENT",
            "confirmed_patch_status": "ABSENT",
            "ledger_entry_count": 0,
            "real_provider_probe": "NOT_EXECUTED",
            "production_fix": "NOT_IMPLEMENTED",
            "full_short_canary": "NOT_EXECUTED",
            "external_action_counters": dict(ZERO_COUNTERS),
        },
        "materialization_index_sha256",
    )
    index_path = materialization / "provider-reasoning-capability-probe-materialization-index-v1.json"
    _write(index_path, index)
    return {
        "parent": parent,
        "plan": plan,
        "candidate": candidate,
        "patch_template": patch,
        "validate_only": receipt,
        "execution_preview": preview,
        "index": index,
        "definition": definition,
        "fixture": fixture,
        "observer": observer,
        "budget": budget,
        "stop_conditions": stop,
        "cohort": cohort,
        "ledger": ledger,
        "canary_root": canary,
        "prelaunch": rehearsal,
        "privacy": privacy,
        "live_parity": parity_after,
        "index_path": index_path,
    }


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--projects", type=Path, required=True)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--artifact-root-label", required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--materialized-at", type=_parse_utc, required=True)
    args = parser.parse_args(argv)
    result = materialize_provider_reasoning_probe_packet(
        repo_root=args.repo_root,
        live_database_path=args.database,
        live_project_root=args.projects,
        cohort_root=args.cohort_root,
        artifact_root_label=args.artifact_root_label,
        cohort_id=args.cohort_id,
        branch=args.branch,
        source_head=args.source_head,
        now=args.materialized_at,
    )
    print(json.dumps({
        "status": result["index"]["status"],
        "index": str(result["index_path"]),
        "external_action_counters": ZERO_COUNTERS,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
