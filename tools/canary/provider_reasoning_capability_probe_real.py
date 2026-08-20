"""Single-use execution closure for the R1-PTR7 reasoning capability probe.

Materialization and validate-only are offline and must retain zero external
action counters.  Only ``execute`` may read one credential, construct one
Provider client, and issue one network/model/paid request.  Raw request and
Provider content remain memory-only.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

import httpx

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.db import Database
from novel_flywheel.model_output import parse_json_object
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.secrets import KeyringSecretStore

from .artifact_hash import file_sha256, live_parity_manifest, parity_equal
from .descriptors import production_route_identity
from .provider_matrix import production_price_catalog
from .provider_reasoning_capability_probe_materialization import (
    TARGET_MODEL_IDENTITY,
    TARGET_PROVIDER_IDENTITY,
    verify_parent_evidence_exact,
)


PROFILE_ID = "r1_ptr7_provider_reasoning_capability_probe_1"
APPROVAL_SCOPE = "provider_reasoning_capability_probe"
COHORT_ID = "r1-ptr7-reasoning-probe-20260820t144046z-001"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
PLAN_SHA256 = "322c58857c4e323db00965e97ed6fefe7432dbd9a6f24ebee07ebd9725b2d51b"
CANDIDATE_SHA256 = "fdf28472be5db33aca26933175d02b2439abaf66aeb105216c253d54d542b979"
PATCH_TEMPLATE_SHA256 = "feaf8e71f38081e5976c1274a789836dad3e450efb17aacbe43033c6edad34db"
DISABLED_VALIDATE_SHA256 = "ebb5721f5502cba87a20da9230611915f51fd59b45d6fe5b862ab4f1d69be968"
DEFINITION_SHA256 = "b871900490c55b18de33376e24e09483b2f852e7988e80656efc97e7986bda44"
FIXTURE_SHA256 = "15d87e12050cda4c9718b62e1234c9e50aa158f439b4c592827d5847498f404e"
OBSERVER_SHA256 = "b48e877ac61d3fe7be6bb743a09d98787e4ce89f14e1830ff50539afd234cf07"
ROUTE_SHA256 = "31adb8879560c60a09db4c0955237480ab836f153ff97515fc5911e9fe1d8d34"
NOT_BEFORE = "2026-08-20T14:40:46Z"
NOT_AFTER = "2026-08-22T14:40:46Z"
MAX_INPUT_TOKENS = 128_000
MAX_OUTPUT_TOKENS = 16_000
REASONING_CAP_TOKENS = 8_000
FINAL_RESERVE_TOKENS = 8_000
MAX_USD_MICROUNITS = 5_000_000
MAX_CNY_MICROUNITS = 10_000_000
MAX_ELAPSED_SECONDS = 1_800
ZERO_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}


class ProviderReasoningProbeRealError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise ProviderReasoningProbeRealError(reason_code)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "document_not_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2,
                   allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _exclusive_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        ) + "\n")


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = dict(body)
    value[field] = domain_sha256(domain, value)
    return value


def _document_digest(domain: str, value: Mapping[str, Any], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return domain_sha256(domain, body)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc,
    )


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def _git_preflight(repo_root: Path, *, require_clean: bool) -> dict[str, str]:
    branch = _git(repo_root, "branch", "--show-current")
    head = _git(repo_root, "rev-parse", "HEAD")
    status = _git(repo_root, "status", "--porcelain")
    _require(branch == EXPECTED_BRANCH, "branch_mismatch")
    if require_clean:
        _require(not status, "worktree_not_clean")
    return {"branch": branch, "head": head, "worktree": "clean" if not status else "dirty"}


def _packet_paths(packet_root: Path) -> dict[str, Path]:
    material = packet_root / "materialization-v1"
    return {
        "manifest": packet_root / "r1-ptr7-probe-mat-final-sha256-manifest-v1.json",
        "plan": material / "provider-reasoning-capability-probe-plan-v1.json",
        "candidate": material / "provider-reasoning-capability-probe-final-approval-candidate-v1.json",
        "template": material / "provider-reasoning-capability-probe-authorization-patch-template-v1.json",
        "disabled": material / "provider-reasoning-capability-probe-validate-only-receipt-v1.json",
        "definition": material / "provider-reasoning-capability-probe-definition-v1.json",
        "fixture": material / "provider-reasoning-capability-probe-fixture-definition-v1.json",
        "observer": material / "provider-reasoning-capability-probe-observer-definition-v1.json",
        "budget": material / "provider-reasoning-capability-probe-budget-definition-v1.json",
        "stop": material / "provider-reasoning-capability-probe-stop-conditions-v1.json",
        "cohort": material / "provider-reasoning-capability-probe-cohort-v1.json",
        "ledger": packet_root / "ledger/provider-reasoning-capability-probe-ledger-v1.json",
        "canary": packet_root / "canary-root/provider-reasoning-capability-probe-canary-root-v1.json",
    }


def verify_fresh_packet_exact(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    paths = _packet_paths(packet_root)
    manifest = _read_json(paths["manifest"])
    entries = list(manifest.get("entries") or ())
    _require(manifest.get("entry_count") == 23 and len(entries) == 23,
             "packet_manifest_entry_count_mismatch")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "packet_manifest_file_missing")
        _require(file_sha256(path) == entry.get("sha256"),
                 "packet_manifest_sha256_mismatch")
        _require(path.stat().st_size == entry.get("bytes"),
                 "packet_manifest_size_mismatch")
    verify_parent_evidence_exact(repo_root)
    plan = _read_json(paths["plan"])
    candidate = _read_json(paths["candidate"])
    template = _read_json(paths["template"])
    disabled = _read_json(paths["disabled"])
    definition = _read_json(paths["definition"])
    fixture = _read_json(paths["fixture"])
    observer = _read_json(paths["observer"])
    budget = _read_json(paths["budget"])
    stop = _read_json(paths["stop"])
    cohort = _read_json(paths["cohort"])
    ledger = _read_json(paths["ledger"])
    canary = _read_json(paths["canary"])
    _require(plan.get("plan_sha256") == PLAN_SHA256, "plan_sha256_mismatch")
    _require(candidate.get("candidate_sha256") == CANDIDATE_SHA256,
             "candidate_sha256_mismatch")
    _require(template.get("authorization_patch_template_sha256") == PATCH_TEMPLATE_SHA256,
             "patch_template_sha256_mismatch")
    _require(disabled.get("validate_only_receipt_sha256") == DISABLED_VALIDATE_SHA256
             and disabled.get("overall_status") == "exact",
             "disabled_validate_sha256_mismatch")
    _require(definition.get("definition_sha256") == DEFINITION_SHA256,
             "definition_sha256_mismatch")
    _require(fixture.get("fixture_sha256") == FIXTURE_SHA256,
             "fixture_sha256_mismatch")
    _require(observer.get("observer_definition_sha256") == OBSERVER_SHA256,
             "observer_sha256_mismatch")
    target = definition.get("target") or {}
    _require(target.get("provider_identity_sha256") == TARGET_PROVIDER_IDENTITY
             and target.get("model_identity_sha256") == TARGET_MODEL_IDENTITY
             and target.get("route_identity_sha256") == ROUTE_SHA256,
             "packet_target_identity_mismatch")
    _require(candidate.get("execution_authorized") is False
             and candidate.get("usage_status") == "unused"
             and candidate.get("reservation_status") == "unreserved",
             "candidate_not_inert")
    _require(ledger.get("entry_count") == 0
             and ledger.get("usage_status") == "unused"
             and ledger.get("reservation_status") == "unreserved"
             and canary.get("entry_count") == 0
             and canary.get("status") == "unused",
             "packet_cohort_not_unused")
    _require(cohort.get("cohort_id") == COHORT_ID
             and cohort.get("execution_window_start_utc") == NOT_BEFORE
             and cohort.get("execution_window_end_utc") == NOT_AFTER,
             "cohort_binding_mismatch")
    _require(budget.get("maximum_runs") == 1
             and budget.get("maximum_total_model_calls") == 1
             and budget.get("maximum_input_tokens") == MAX_INPUT_TOKENS
             and budget.get("maximum_output_tokens") == MAX_OUTPUT_TOKENS
             and budget.get("requested_reasoning_cap_tokens") == REASONING_CAP_TOKENS
             and budget.get("requested_final_reserve_tokens") == FINAL_RESERVE_TOKENS,
             "packet_budget_mismatch")
    _require(stop.get("no_retry") is True and stop.get("no_resume") is True
             and stop.get("no_second_run") is True,
             "packet_stop_conditions_mismatch")
    return {"plan": plan, "candidate": candidate, "disabled": disabled,
            "ledger": ledger,
            "definition": definition, "fixture": fixture, "budget": budget}


def _validate_live_route(live_database: Path) -> dict[str, Any]:
    identity = production_route_identity(Database(live_database), "planning", "fallback")
    _require(identity.get("provider_descriptor_hash") == TARGET_PROVIDER_IDENTITY
             and identity.get("model_binding_hash") == TARGET_MODEL_IDENTITY
             and identity.get("protocol") == "anthropic",
             "live_provider_model_route_mismatch")
    route = domain_sha256("r1-ptr7-route-identity-v1", {
        "provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
        "model_identity_sha256": TARGET_MODEL_IDENTITY,
        "route_kind": "configured_fallback",
        "protocol": "anthropic",
        "execution_mode": "canary_only_synthetic",
    })
    _require(route == ROUTE_SHA256, "route_identity_mismatch")
    return identity


def _synthetic_request() -> dict[str, Any]:
    seed = hashlib.sha256(b"r1-ptr7-provider-reasoning-capability-probe-v1").digest()
    values: list[int] = []
    state = seed
    for index in range(512):
        state = hashlib.sha256(state + index.to_bytes(4, "big")).digest()
        values.append(int.from_bytes(state[:4], "big") % 1_000_003)
    checksum = sum((index + 1) * value for index, value in enumerate(values)) % 1_000_000_007
    expected = {"probe_result": "complete", "checksum": checksum}
    system = (
        "This is a synthetic provider capability probe with no business or story data. "
        "Perform any private reasoning needed, then emit the required final JSON artifact."
    )
    user = (
        "Compute the index-weighted checksum modulo 1000000007 for this ordered integer list. "
        "Return exactly one JSON object with probe_result='complete' and integer checksum; "
        "do not omit the final artifact. Values: " + ",".join(map(str, values))
    )
    receipt = _sealed("r1-ptr7-reasoning-probe-request-reassembly-v1", {
        "schema": "ProviderReasoningCapabilityProbeRequestReassemblyReceiptV1",
        "version": 1,
        "fixture_sha256": FIXTURE_SHA256,
        "algorithm": "sha256_seeded_integer_checksum_v1",
        "item_count": 512,
        "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
        "expected_final_artifact_sha256": domain_sha256(
            "r1-ptr7-reasoning-probe-final-artifact-v1", expected,
        ),
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
    }, "request_reassembly_receipt_sha256")
    return {"system": system, "user": user, "expected": expected, "receipt": receipt}


def materialize_signed_authorization(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    live_database: Path, live_projects: Path,
) -> dict[str, Any]:
    _require(not output_root.exists(), "signed_output_root_already_exists")
    git = _git_preflight(repo_root, require_clean=True)
    packet = verify_fresh_packet_exact(repo_root, packet_root)
    now = _utc_now()
    _require(_parse_utc(NOT_BEFORE) <= _parse_utc(now) <= _parse_utc(NOT_AFTER),
             "approval_outside_execution_window")
    route = _validate_live_route(live_database)
    before = live_parity_manifest(database_path=live_database, project_root=live_projects)
    request = _synthetic_request()
    after = live_parity_manifest(database_path=live_database, project_root=live_projects)
    _require(parity_equal(before, after), "live_parity_changed_during_preflight")
    _require(before["parity_sha256"] ==
             packet["disabled"].get("live_parity_after_sha256"),
             "live_parity_packet_mismatch")
    output_root.mkdir(parents=True)
    authorization = output_root / "authorization"
    ledger = output_root / "approval-ledger"
    authorization.mkdir()
    ledger.mkdir()
    _write_json(authorization / "provider-reasoning-capability-probe-request-reassembly-receipt-v1.json",
                request["receipt"])
    executor_sha = file_sha256(Path(__file__))
    auth_record = domain_sha256("r1-ptr7-reasoning-probe-user-authorization-v1", {
        "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
        "plan_sha256": PLAN_SHA256, "candidate_sha256": CANDIDATE_SHA256,
        "patch_template_sha256": PATCH_TEMPLATE_SHA256,
        "definition_sha256": DEFINITION_SHA256, "fixture_sha256": FIXTURE_SHA256,
        "observer_sha256": OBSERVER_SHA256, "route_sha256": ROUTE_SHA256,
        "not_before": NOT_BEFORE, "not_after": NOT_AFTER,
        "maximum_runs": 1, "maximum_total_model_calls": 1,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "requested_reasoning_cap_tokens": REASONING_CAP_TOKENS,
        "requested_final_reserve_tokens": FINAL_RESERVE_TOKENS,
        "first_terminal_stop": True, "second_run_allowed": False,
        "resume_after_terminal": False,
        "approval_method": "explicit_final_user_authorization_in_current_task",
    })
    patch = _sealed("r1-ptr7-reasoning-probe-confirmed-authorization-patch-v1", {
        "schema": "ProviderReasoningCapabilityProbeConfirmedAuthorizationPatchV1",
        "version": 1, "profile_id": PROFILE_ID, "single_use_cohort_id": COHORT_ID,
        "bound_plan_sha256": PLAN_SHA256,
        "bound_approval_candidate_sha256": CANDIDATE_SHA256,
        "bound_authorization_patch_template_sha256": PATCH_TEMPLATE_SHA256,
        "authorization_record_sha256": auth_record, "confirmed_at": now,
        "execution_window": {"not_before": NOT_BEFORE, "not_after": NOT_AFTER},
        "execution_authorized": True, "authorize_credential_lookup": True,
        "authorize_provider_client_creation": True, "authorize_network": True,
        "authorize_model_call": True, "authorize_paid_model_call": True,
        "maximum_executions": 1, "maximum_total_model_calls": 1,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "retry_allowed": False, "resume_allowed": False,
        "second_run_allowed": False, "full_short_allowed": False,
        "draft_review_maintenance_allowed": False, "production_fix_allowed": False,
        "status": "confirmed_unused",
    }, "confirmed_authorization_patch_sha256")
    _write_json(authorization / "provider-reasoning-capability-probe-confirmed-authorization-patch-v1.json", patch)
    ledger_identity = domain_sha256("r1-ptr7-reasoning-probe-operational-ledger-v1", {
        "packet_ledger_identity_sha256": packet["ledger"]["ledger_identity_sha256"],
        "cohort_id": COHORT_ID, "profile_id": PROFILE_ID,
    })
    _write_json(ledger / ".provider-reasoning-capability-probe-ledger-identity-v1.json", {
        "schema": "ProviderReasoningCapabilityProbeOperationalLedgerIdentityV1",
        "version": 1, "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
        "ledger_identity_sha256": ledger_identity,
    })
    signed = _sealed("r1-ptr7-reasoning-probe-signed-approval-v1", {
        "schema": "ProviderReasoningCapabilityProbeSignedApprovalV1", "version": 1,
        "profile_id": PROFILE_ID, "approval_scope": APPROVAL_SCOPE,
        "single_use_cohort_id": COHORT_ID, "bound_plan_sha256": PLAN_SHA256,
        "source_approval_candidate_sha256": CANDIDATE_SHA256,
        "source_confirmed_authorization_patch_sha256": patch["confirmed_authorization_patch_sha256"],
        "bound_request_reassembly_receipt_sha256": request["receipt"]["request_reassembly_receipt_sha256"],
        "bound_probe_definition_sha256": DEFINITION_SHA256,
        "bound_fixture_sha256": FIXTURE_SHA256,
        "bound_observer_sha256": OBSERVER_SHA256,
        "bound_provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
        "bound_route_identity_sha256": ROUTE_SHA256,
        "bound_model_identity_sha256": TARGET_MODEL_IDENTITY,
        "bound_executor_source_sha256": executor_sha,
        "approval_ledger_identity_sha256": ledger_identity,
        "authorization_record_sha256": auth_record,
        "authorization_source_head": git["head"],
        "named_approver": "final_user",
        "approval_method": "explicit_final_user_authorization_in_current_task",
        "signed_at": now,
        "execution_window": {"not_before": NOT_BEFORE, "not_after": NOT_AFTER},
        "usage_status": "unused", "reservation_status": "unreserved",
        "execution_authorized": True, "authorize_credential_lookup": True,
        "authorize_provider_client_creation": True, "authorize_network": True,
        "authorize_model_call": True, "authorize_paid_model_call": True,
        "approved_budget": {
            "maximum_runs": 1, "maximum_total_model_calls": 1,
            "maximum_input_tokens": MAX_INPUT_TOKENS,
            "maximum_output_tokens": MAX_OUTPUT_TOKENS,
            "maximum_output_tokens_per_call": MAX_OUTPUT_TOKENS,
            "requested_reasoning_cap_tokens": REASONING_CAP_TOKENS,
            "requested_final_reserve_tokens": FINAL_RESERVE_TOKENS,
            "maximum_usd_cost_microunits": MAX_USD_MICROUNITS,
            "maximum_cny_cost_microunits": MAX_CNY_MICROUNITS,
            "maximum_elapsed_seconds": MAX_ELAPSED_SECONDS,
        },
        "first_terminal_stop": True, "retry_allowed": False,
        "resume_after_terminal": False, "second_run_allowed": False,
        "full_short_allowed": False, "draft_review_maintenance_allowed": False,
        "production_fix_allowed": False, "maximum_executions": 1,
    }, "signed_approval_sha256")
    _write_json(authorization / "provider-reasoning-capability-probe-signed-approval-v1.json", signed)
    receipt = validate_signed_authorization(
        repo_root=repo_root, packet_root=packet_root, output_root=output_root,
        live_database=live_database, live_projects=live_projects,
        require_clean=False,
    )
    _write_json(authorization / "provider-reasoning-capability-probe-signed-validate-only-receipt-v1.json", receipt)
    return {"patch": patch, "signed_approval": signed, "receipt": receipt,
            "route": route}


def validate_signed_authorization(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    live_database: Path, live_projects: Path, require_clean: bool = True,
) -> dict[str, Any]:
    git = _git_preflight(repo_root, require_clean=require_clean)
    verify_fresh_packet_exact(repo_root, packet_root)
    authorization = output_root / "authorization"
    patch = _read_json(authorization / "provider-reasoning-capability-probe-confirmed-authorization-patch-v1.json")
    signed = _read_json(authorization / "provider-reasoning-capability-probe-signed-approval-v1.json")
    stored_request = _read_json(authorization / "provider-reasoning-capability-probe-request-reassembly-receipt-v1.json")
    _require(patch.get("confirmed_authorization_patch_sha256") == _document_digest(
        "r1-ptr7-reasoning-probe-confirmed-authorization-patch-v1", patch,
        "confirmed_authorization_patch_sha256"), "confirmed_patch_hash_mismatch")
    _require(signed.get("signed_approval_sha256") == _document_digest(
        "r1-ptr7-reasoning-probe-signed-approval-v1", signed,
        "signed_approval_sha256"), "signed_approval_hash_mismatch")
    _require(signed.get("source_confirmed_authorization_patch_sha256") ==
             patch.get("confirmed_authorization_patch_sha256")
             and signed.get("source_approval_candidate_sha256") == CANDIDATE_SHA256
             and signed.get("bound_plan_sha256") == PLAN_SHA256
             and signed.get("bound_executor_source_sha256") == file_sha256(Path(__file__)),
             "signed_source_binding_mismatch")
    now = _utc_now()
    _require(_parse_utc(NOT_BEFORE) <= _parse_utc(now) <= _parse_utc(NOT_AFTER),
             "approval_outside_execution_window")
    _require(signed.get("usage_status") == "unused"
             and signed.get("reservation_status") == "unreserved"
             and signed.get("maximum_executions") == 1,
             "signed_approval_state_invalid")
    budget = signed.get("approved_budget") or {}
    _require(budget == {
        "maximum_runs": 1, "maximum_total_model_calls": 1,
        "maximum_input_tokens": MAX_INPUT_TOKENS,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "maximum_output_tokens_per_call": MAX_OUTPUT_TOKENS,
        "requested_reasoning_cap_tokens": REASONING_CAP_TOKENS,
        "requested_final_reserve_tokens": FINAL_RESERVE_TOKENS,
        "maximum_usd_cost_microunits": MAX_USD_MICROUNITS,
        "maximum_cny_cost_microunits": MAX_CNY_MICROUNITS,
        "maximum_elapsed_seconds": MAX_ELAPSED_SECONDS,
    }, "signed_budget_mismatch")
    _require(all(signed.get(field) is True for field in (
        "execution_authorized", "authorize_credential_lookup",
        "authorize_provider_client_creation", "authorize_network",
        "authorize_model_call", "authorize_paid_model_call", "first_terminal_stop",
    )), "signed_authorization_missing")
    _require(all(signed.get(field) is False for field in (
        "retry_allowed", "resume_after_terminal", "second_run_allowed",
        "full_short_allowed", "draft_review_maintenance_allowed",
        "production_fix_allowed",
    )), "signed_forbidden_scope_enabled")
    route = _validate_live_route(live_database)
    before = live_parity_manifest(database_path=live_database, project_root=live_projects)
    request = _synthetic_request()
    after = live_parity_manifest(database_path=live_database, project_root=live_projects)
    _require(parity_equal(before, after), "live_parity_changed_during_preflight")
    _require(request["receipt"] == stored_request, "request_reassembly_changed")
    ledger = output_root / "approval-ledger"
    _require((ledger / ".provider-reasoning-capability-probe-ledger-identity-v1.json").is_file()
             and not (ledger / "reserved-v1.json").exists()
             and not (ledger / "consumed-v1.json").exists(),
             "operational_ledger_not_unused")
    checks = [
        ("fresh_packet", PLAN_SHA256),
        ("confirmed_patch", patch["confirmed_authorization_patch_sha256"]),
        ("signed_approval", signed["signed_approval_sha256"]),
        ("execution_window", signed["authorization_record_sha256"]),
        ("definition", DEFINITION_SHA256), ("fixture", FIXTURE_SHA256),
        ("observer", OBSERVER_SHA256), ("provider", TARGET_PROVIDER_IDENTITY),
        ("route", ROUTE_SHA256), ("model", TARGET_MODEL_IDENTITY),
        ("request_reassembly", request["receipt"]["request_reassembly_receipt_sha256"]),
        ("ledger_unused", signed["approval_ledger_identity_sha256"]),
        ("live_parity", after["parity_sha256"]), ("external_actions_zero", None),
    ]
    body = {
        "schema": "ProviderReasoningCapabilityProbeSignedValidateOnlyReceiptV1",
        "version": 1, "overall_status": "exact", "validated_at": signed["signed_at"],
        "profile_id": PROFILE_ID, "single_use_cohort_id": COHORT_ID,
        "branch": git["branch"], "bound_plan_sha256": PLAN_SHA256,
        "bound_signed_approval_sha256": signed["signed_approval_sha256"],
        "bound_confirmed_authorization_patch_sha256": patch["confirmed_authorization_patch_sha256"],
        "approval_state": "signed_approval_exact_and_executable",
        "cohort_usage_status": "unused", "approval_reservation_status": "unreserved",
        "ledger_entry_count": 0, "live_parity_sha256": after["parity_sha256"],
        "provider_model_route_binding_sha256": route["model_binding_hash"],
        "ordered_checks": [{"name": name, "status": "exact", "evidence_sha256": evidence}
                           for name, evidence in checks],
        "external_action_counters": dict(ZERO_COUNTERS),
        "raw_prompt_omitted": True, "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True, "raw_provider_content_omitted": True,
    }
    return _sealed("r1-ptr7-reasoning-probe-signed-validate-only-v1", body,
                   "signed_validate_only_receipt_sha256")


def _parse_json_artifact(text: str, expected: Mapping[str, Any]) -> tuple[bool, str | None]:
    try:
        value = parse_json_object(text)
    except Exception:
        return False, None
    exact = value == dict(expected)
    return exact, domain_sha256("r1-ptr7-reasoning-probe-final-artifact-v1", value)


def _new_observation() -> dict[str, Any]:
    return {
        "parameter_disposition": "unknown", "http_status_class": "unknown",
        "finish_reason": "unknown", "input_tokens": 0, "output_tokens": 0,
        "reasoning_tokens_if_reported": None,
        "final_output_tokens_if_reported": None,
        "token_separation_reported": False,
        "thinking_block_count": 0, "final_text_block_count": 0,
        "tool_block_count": 0, "visible_characters": 0,
        "reasoning_characters_if_observable": 0, "unknown_block_count": 0,
        "block_type_sequence_sha256": None, "final_artifact_exact": False,
        "final_artifact_sha256": None,
    }


def _consume_event(event: Mapping[str, Any], state: dict[str, Any]) -> None:
    kind = str(event.get("type") or "")
    if kind == "message_start":
        usage = (event.get("message") or {}).get("usage") or {}
        state["input_tokens"] = int(usage.get("input_tokens") or 0)
    elif kind == "content_block_start":
        index = int(event.get("index") or 0)
        block = event.get("content_block") or {}
        block_type = str(block.get("type") or "unknown")
        state["block_types"][index] = block_type
        if block_type in {"thinking", "reasoning", "redacted_thinking"}:
            state["thinking_block_count"] += 1
            state["reasoning_characters_if_observable"] += len(str(
                block.get("thinking") or block.get("text") or ""
            ))
        elif block_type in {"text", "output_text"}:
            state["final_text_block_count"] += 1
            text = str(block.get("text") or "")
            state["visible_characters"] += len(text)
            state["text_parts"].append(text)
        elif block_type in {"tool_use", "tool_call", "function_call"}:
            state["tool_block_count"] += 1
        else:
            state["unknown_block_count"] += 1
    elif kind == "content_block_delta":
        delta = event.get("delta") or {}
        delta_type = str(delta.get("type") or "")
        if delta_type in {"thinking_delta", "reasoning_delta"}:
            state["reasoning_characters_if_observable"] += len(str(
                delta.get("thinking") or delta.get("reasoning") or ""
            ))
        elif delta_type in {"text_delta", "output_text_delta"}:
            text = str(delta.get("text") or "")
            state["visible_characters"] += len(text)
            state["text_parts"].append(text)
    elif kind == "message_delta":
        state["finish_reason"] = str((event.get("delta") or {}).get("stop_reason")
                                     or state["finish_reason"])
        usage = event.get("usage") or {}
        state["output_tokens"] = int(usage.get("output_tokens") or state["output_tokens"])
        for key in ("reasoning_tokens", "thinking_tokens"):
            if usage.get(key) is not None:
                state["reasoning_tokens_if_reported"] = int(usage[key])
        for key in ("final_output_tokens", "text_tokens"):
            if usage.get(key) is not None:
                state["final_output_tokens_if_reported"] = int(usage[key])


def _consume_body(body: Mapping[str, Any], state: dict[str, Any]) -> None:
    state["finish_reason"] = str(body.get("stop_reason") or body.get("finish_reason") or "unknown")
    usage = body.get("usage") or {}
    state["input_tokens"] = int(usage.get("input_tokens") or 0)
    state["output_tokens"] = int(usage.get("output_tokens") or 0)
    for key in ("reasoning_tokens", "thinking_tokens"):
        if usage.get(key) is not None:
            state["reasoning_tokens_if_reported"] = int(usage[key])
    for key in ("final_output_tokens", "text_tokens"):
        if usage.get(key) is not None:
            state["final_output_tokens_if_reported"] = int(usage[key])
    for index, block in enumerate(body.get("content") or []):
        if isinstance(block, Mapping):
            _consume_event({"type": "content_block_start", "index": index,
                            "content_block": block}, state)


def _classification(observation: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    disposition = observation.get("parameter_disposition")
    finish = observation.get("finish_reason")
    reasoning = observation.get("reasoning_tokens_if_reported")
    final_exact = observation.get("final_artifact_exact") is True
    final_present = observation.get("visible_characters", 0) > 0 or observation.get("tool_block_count", 0) > 0
    if disposition == "rejected":
        overall = "UNSUPPORTED"
    elif disposition != "accepted":
        overall = "UNKNOWN"
    elif reasoning is not None and reasoning > REASONING_CAP_TOKENS:
        overall = "IGNORED"
    elif finish == "max_tokens" and observation.get("thinking_block_count", 0) > 0 and not final_present:
        overall = "IGNORED"
    elif reasoning is not None and final_exact and observation.get("token_separation_reported"):
        overall = "SUPPORTED"
    else:
        overall = "UNKNOWN"
    capabilities = {
        "reasoning_budget_cap": overall,
        "final_output_reservation": "SUPPORTED" if overall == "SUPPORTED" else overall,
        "reasoning_output_token_separation": (
            "SUPPORTED" if observation.get("token_separation_reported") and overall == "SUPPORTED"
            else "UNSUPPORTED" if overall == "UNSUPPORTED" else "UNKNOWN"
        ),
        "capability_bound_output_allocation": overall,
    }
    return overall, capabilities


async def _one_provider_request(
    *, live_database: Path, request: Mapping[str, Any], counters: dict[str, int],
) -> dict[str, Any]:
    estimated_input = estimate_input_tokens(str(request["system"]) + "\n" + str(request["user"]))
    _require(estimated_input <= MAX_INPUT_TOKENS, "maximum_input_tokens_preflight_exceeded")
    db = Database(live_database)
    binding = db.get_role_binding("planning") or {}
    provider_id = str(binding.get("fallback_provider_id") or "")
    model_id = str(binding.get("fallback_model_id") or "")
    _require(bool(provider_id and model_id), "configured_fallback_not_available")

    class CountingSecrets:
        def __init__(self) -> None:
            self.delegate = KeyringSecretStore()

        def get(self, selected_provider_id: str) -> str | None:
            counters["credential_lookup_count"] += 1
            return self.delegate.get(selected_provider_id)

        def set(self, _provider_id: str, _value: str) -> None:
            raise ProviderReasoningProbeRealError("credential_mutation_forbidden")

        def delete(self, _provider_id: str) -> None:
            raise ProviderReasoningProbeRealError("credential_mutation_forbidden")

    resolved = ProviderRegistry(db, CountingSecrets()).resolve(provider_id, model_id)
    counters["provider_client_creation_count"] += 1
    route = _validate_live_route(live_database)
    price = production_price_catalog().require(route["provider_alias"], route["model_alias"], "default")
    worst = price.cost_microunits(
        input_tokens=MAX_INPUT_TOKENS, cached_input_tokens=0,
        output_tokens=MAX_OUTPUT_TOKENS, reasoning_tokens=REASONING_CAP_TOKENS,
    )
    cost_limit = MAX_USD_MICROUNITS if price.currency == "USD" else MAX_CNY_MICROUNITS if price.currency == "CNY" else 0
    _require(cost_limit > 0 and worst <= cost_limit, "maximum_cost_preflight_exceeded")
    adapter = resolved.adapter
    _require(hasattr(adapter, "client") and hasattr(adapter, "base_url"), "provider_adapter_not_http")
    auth = ({"Authorization": f"Bearer {adapter.api_key}"}
            if adapter.auth_type == "bearer" else {"x-api-key": adapter.api_key})
    headers = {**auth, "anthropic-version": "2023-06-01", **adapter.headers}
    path = "messages" if adapter.base_url.endswith("/v1") else "v1/messages"
    payload = {
        "model": resolved.model_name,
        "messages": [{"role": "user", "content": request["user"]}],
        "system": request["system"], "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "enabled", "budget_tokens": REASONING_CAP_TOKENS},
        "stream": True,
    }
    state = _new_observation()
    state.update({"block_types": {}, "text_parts": []})
    counters["network_call_count"] += 1
    counters["model_call_count"] += 1
    counters["paid_model_call_count"] += 1
    try:
        async with adapter.client.stream(
            "POST", f"{adapter.base_url}/{path}", json=payload, headers=headers,
        ) as response:
            state["http_status_class"] = f"{response.status_code // 100}xx"
            if response.status_code >= 400:
                await response.aread()
                detail = response.text.casefold()
                capability_terms = ("thinking", "reasoning", "budget_tokens", "budget tokens")
                rejection_terms = ("unsupported", "not support", "invalid", "unrecognized", "unknown")
                state["parameter_disposition"] = (
                    "rejected" if response.status_code in {400, 404, 422}
                    and any(term in detail for term in capability_terms)
                    and any(term in detail for term in rejection_terms) else "unknown"
                )
                state["finish_reason"] = "http_error"
            else:
                state["parameter_disposition"] = "accepted"
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type:
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if not line:
                            if data_lines:
                                raw = "\n".join(data_lines)
                                data_lines.clear()
                                if raw != "[DONE]":
                                    _consume_event(json.loads(raw), state)
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                    if data_lines:
                        raw = "\n".join(data_lines)
                        if raw != "[DONE]":
                            _consume_event(json.loads(raw), state)
                else:
                    await response.aread()
                    _consume_body(response.json(), state)
    finally:
        await adapter.client.aclose()
    text = "".join(state.pop("text_parts"))
    block_map = state.pop("block_types")
    block_types = [block_map[key] for key in sorted(block_map)]
    state["block_type_sequence_sha256"] = domain_sha256(
        "r1-ptr7-reasoning-probe-block-type-sequence-v1", block_types,
    )
    exact, artifact_hash = _parse_json_artifact(text, request["expected"])
    state["final_artifact_exact"] = exact
    state["final_artifact_sha256"] = artifact_hash
    state["token_separation_reported"] = (
        state["reasoning_tokens_if_reported"] is not None
        and state["final_output_tokens_if_reported"] is not None
    )
    actual_cost = price.cost_microunits(
        input_tokens=state["input_tokens"], cached_input_tokens=0,
        output_tokens=state["output_tokens"],
        reasoning_tokens=int(state["reasoning_tokens_if_reported"] or 0),
    )
    return {"observation": state, "cost_currency": price.currency,
            "actual_cost_microunits": actual_cost,
            "maximum_cost_microunits": cost_limit}


def execute_real_probe_once(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    live_database: Path, live_projects: Path,
) -> dict[str, Any]:
    signed_receipt = validate_signed_authorization(
        repo_root=repo_root, packet_root=packet_root, output_root=output_root,
        live_database=live_database, live_projects=live_projects,
    )
    _require(signed_receipt.get("overall_status") == "exact", "signed_validate_not_exact")
    signed = _read_json(output_root / "authorization/provider-reasoning-capability-probe-signed-approval-v1.json")
    request = _synthetic_request()
    before = live_parity_manifest(database_path=live_database, project_root=live_projects)
    ledger = output_root / "approval-ledger"
    reservation = _sealed("r1-ptr7-reasoning-probe-reservation-v1", {
        "schema": "ProviderReasoningCapabilityProbeReservationV1", "version": 1,
        "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "reserved_at": _utc_now(), "status": "reserved",
    }, "reservation_receipt_sha256")
    _exclusive_write(ledger / "reserved-v1.json", reservation)
    counters = dict(ZERO_COUNTERS)
    started = time.monotonic()
    call_result: dict[str, Any] | None = None
    terminal_status = "typed_provider_call_failure"
    failure_type_sha256: str | None = None
    try:
        call_result = asyncio.run(_one_provider_request(
            live_database=live_database, request=request, counters=counters,
        ))
        terminal_status = "provider_response_observed"
    except BaseException as exc:
        failure_type_sha256 = domain_sha256(
            "r1-ptr7-reasoning-probe-failure-type-v1", type(exc).__name__,
        )
    elapsed = int((time.monotonic() - started) * 1_000_000)
    _require(all(counters[key] <= 1 for key in (
        "credential_lookup_count", "provider_client_creation_count",
        "network_call_count", "model_call_count", "paid_model_call_count",
    )), "single_action_budget_exceeded")
    _require(elapsed <= MAX_ELAPSED_SECONDS * 1_000_000, "elapsed_budget_exceeded")
    after = live_parity_manifest(database_path=live_database, project_root=live_projects)
    _require(parity_equal(before, after), "live_parity_changed_after_probe")
    observation: dict[str, Any] | None = None
    classification = "UNKNOWN"
    capabilities = {name: "UNKNOWN" for name in (
        "reasoning_budget_cap", "final_output_reservation",
        "reasoning_output_token_separation", "capability_bound_output_allocation",
    )}
    cost = {"currency": "unknown", "actual_cost_microunits": None,
            "maximum_cost_microunits": None, "status": "unknown_after_failure"}
    if call_result is not None:
        classification, capabilities = _classification(call_result["observation"])
        observation = _sealed("r1-ptr7-reasoning-probe-observation-v1", {
            "schema": "ProviderReasoningCapabilityProbeObservationV1", "version": 1,
            "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
            "provider_identity_sha256": TARGET_PROVIDER_IDENTITY,
            "route_identity_sha256": ROUTE_SHA256,
            "model_identity_sha256": TARGET_MODEL_IDENTITY,
            "protocol": "anthropic", "route_kind": "configured_fallback",
            "requested_reasoning_cap_tokens": REASONING_CAP_TOKENS,
            "requested_final_reserve_tokens": FINAL_RESERVE_TOKENS,
            **call_result["observation"], "classification": classification,
            "capability_classifications": capabilities,
            "raw_prompt_omitted": True, "raw_story_omitted": True,
            "raw_tool_arguments_omitted": True, "raw_provider_content_omitted": True,
            "credentials_omitted": True,
        }, "observation_receipt_sha256")
        cost = {
            "currency": call_result["cost_currency"],
            "actual_cost_microunits": call_result["actual_cost_microunits"],
            "maximum_cost_microunits": call_result["maximum_cost_microunits"],
            "status": "within_budget" if call_result["actual_cost_microunits"] <= call_result["maximum_cost_microunits"] else "exceeded_after_call",
        }
    execution = _sealed("r1-ptr7-reasoning-probe-execution-receipt-v1", {
        "schema": "ProviderReasoningCapabilityProbeRealExecutionReceiptV1", "version": 1,
        "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "signed_validate_only_receipt_sha256": signed_receipt["signed_validate_only_receipt_sha256"],
        "reservation_receipt_sha256": reservation["reservation_receipt_sha256"],
        "request_reassembly_receipt_sha256": request["receipt"]["request_reassembly_receipt_sha256"],
        "observation_receipt_sha256": observation["observation_receipt_sha256"] if observation else None,
        "terminal_status": terminal_status, "failure_type_sha256": failure_type_sha256,
        "classification": classification, "capability_classifications": capabilities,
        "executed_at": _utc_now(), "executed_run_count": 1 if counters["model_call_count"] else 0,
        "cost": cost, "elapsed_micros": elapsed, "external_action_counters": counters,
        "live_parity": {"status": "exact", "before_sha256": before["parity_sha256"],
                        "after_sha256": after["parity_sha256"]},
        "real_provider_probe": "EXECUTED_ONCE" if counters["model_call_count"] == 1 else "NOT_EXECUTED",
        "full_short_canary": "NOT_EXECUTED", "production_fix": "NOT_IMPLEMENTED",
        "retry_performed": False, "resume_performed": False,
        "second_run_performed": False, "raw_prompt_omitted": True,
        "raw_story_omitted": True, "raw_tool_arguments_omitted": True,
        "raw_provider_content_omitted": True,
    }, "execution_receipt_sha256")
    reports = output_root / "reports"
    if observation is not None:
        _write_json(reports / "provider-reasoning-capability-probe-observation-v1.json", observation)
    _write_json(reports / "provider-reasoning-capability-probe-real-execution-receipt-v1.json", execution)
    consumption = _sealed("r1-ptr7-reasoning-probe-consumption-v1", {
        "schema": "ProviderReasoningCapabilityProbeConsumptionV1", "version": 1,
        "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "reservation_receipt_sha256": reservation["reservation_receipt_sha256"],
        "execution_receipt_sha256": execution["execution_receipt_sha256"],
        "consumed_at": _utc_now(), "status": "consumed",
    }, "consumption_receipt_sha256")
    _exclusive_write(ledger / "consumed-v1.json", consumption)
    return {"observation": observation, "execution": execution,
            "consumption": consumption}


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("materialize", "validate", "execute"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-projects", type=Path, required=True)
    args = parser.parse_args()
    common = {name: getattr(args, name).resolve() for name in (
        "repo_root", "packet_root", "output_root", "live_database", "live_projects",
    )}
    if args.command == "materialize":
        result = materialize_signed_authorization(**common)
        public = {
            "gate": "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_SIGNED_VALIDATE_EXACT",
            "confirmed_patch_sha256": result["patch"]["confirmed_authorization_patch_sha256"],
            "signed_approval_sha256": result["signed_approval"]["signed_approval_sha256"],
            "signed_validate_only_receipt_sha256": result["receipt"]["signed_validate_only_receipt_sha256"],
            "external_action_counters": result["receipt"]["external_action_counters"],
        }
    elif args.command == "validate":
        result = validate_signed_authorization(**common)
        public = {
            "gate": "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_SIGNED_VALIDATE_EXACT",
            "signed_validate_only_receipt_sha256": result["signed_validate_only_receipt_sha256"],
            "external_action_counters": result["external_action_counters"],
        }
    else:
        result = execute_real_probe_once(**common)
        public = {
            "gate": "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_EXECUTION_TERMINAL",
            "execution_receipt_sha256": result["execution"]["execution_receipt_sha256"],
            "observation_receipt_sha256": (result["observation"] or {}).get("observation_receipt_sha256"),
            "terminal_status": result["execution"]["terminal_status"],
            "classification": result["execution"]["classification"],
            "external_action_counters": result["execution"]["external_action_counters"],
            "full_short_canary": "NOT_EXECUTED", "production_fix": "NOT_IMPLEMENTED",
        }
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
