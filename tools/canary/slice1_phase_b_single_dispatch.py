"""Materialize the guarded, disabled Slice1 Phase B CURRENT-Skill packet.

This module is offline-only unless ``execute_authorized_once`` is called by a
separately authorized task.  Materialization and signed preflight do not read
credentials, construct Provider clients, reserve a nonce, or dispatch network
requests.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence

from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    normalize_event_realization_input_authority_v1,
    SLICE1_CONTRACT_IDENTITY,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
import tools.canary.slice1_phase_b_current_skill as base


EXPECTED_BRANCH = base.EXPECTED_BRANCH
COHORT_ID = (
    "slice1-phase-b-current-skill-single-dispatch-v2-20260823t045907z-001"
)
APPROVAL_SCOPE = "SLICE1_PHASE_B_CURRENT_SKILL_SINGLE_DISPATCH_BASELINE_ONLY"
REPORT_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-materialization-v2"
)
PREVIOUS_APPROVAL_HEAD = "da9faa264ea65d84df1352b2ad2d9c191c4970d5"
PREVIOUS_APPROVAL_COHORT = base.COHORT_ID
ZERO_COUNTERS = dict(base.ZERO_COUNTERS)


class Slice1PhaseBSingleDispatchError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise Slice1PhaseBSingleDispatchError(reason_code)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ) + "\n").encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _domain_sha(domain: str, value: Any) -> str:
    return _sha_bytes(domain.encode("utf-8") + b"\0" + _canonical_bytes(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain_sha(domain, result)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Slice1PhaseBSingleDispatchError("json_evidence_unreadable") from exc
    _require(isinstance(value, dict), "json_evidence_not_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _source_binding(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = repo_root / relative_path
    _require(path.is_file(), "single_dispatch_source_missing")
    return {
        "path": relative_path,
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
    }


def transport_guard_contract(repo_root: Path) -> dict[str, Any]:
    policy = SingleDispatchTransportPolicyV1.phase_b()
    http_path = repo_root / "src/novel_flywheel/providers/http.py"
    registry_path = repo_root / "src/novel_flywheel/providers/registry.py"
    launcher_path = repo_root / "tools/canary/slice1_phase_b_single_dispatch.py"
    http_source = http_path.read_text(encoding="utf-8")
    registry_source = registry_path.read_text(encoding="utf-8")
    launcher_source = launcher_path.read_text(encoding="utf-8")
    checks = {
        "explicit_httpx_transport_retries_zero": (
            "httpx.AsyncHTTPTransport(retries=0)" in http_source
        ),
        "guarded_attempt_loop_is_one": (
            "max_attempts = 1 if self.transport_policy is not None else 2"
            in http_source
        ),
        "attempt_gate_precedes_client_post": (
            http_source.index("self._before_http_post_attempt()")
            < http_source.index("response = await self.client.post(")
        ),
        "attempt_gate_precedes_client_stream": (
            http_source.rindex("self._before_http_post_attempt()")
            < http_source.index("async with self.client.stream(")
        ),
        "registry_injects_explicit_policy": (
            "transport_policy=self.transport_policy" in registry_source
        ),
        "guarded_launcher_constructs_explicit_policy": (
            "transport_policy=SingleDispatchTransportPolicyV1.phase_b()"
            in launcher_source
        ),
    }
    _require(all(checks.values()), "single_dispatch_guard_build_unknown")
    body = {
        "schema": "Slice1PhaseBSingleDispatchTransportGuardV1",
        "version": 1,
        "mode": "single_dispatch",
        "policy": policy.definition(),
        "policy_definition_sha256": policy.definition_sha256(),
        "provider_family": "anthropic",
        "adapter_family": "AnthropicAdapter",
        "client_class": "httpx.AsyncClient",
        "sdk_class": "NONE_CUSTOM_HTTPX_ADAPTER",
        "sdk_retries_disabled_for_phase_b": True,
        "transport_request_retries_disabled_for_phase_b": True,
        "max_http_post_attempts": 1,
        "max_real_provider_request_attempts": 1,
        "application_second_dispatch_allowed": False,
        "route_fallback_after_dispatch_allowed": False,
        "workflow_model_retry_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "normal_production_transport_retry_policy_changed": False,
        "mechanical_checks": checks,
        "source_bindings": [
            _source_binding(repo_root, "src/novel_flywheel/providers/http.py"),
            _source_binding(repo_root, "src/novel_flywheel/providers/registry.py"),
            _source_binding(
                repo_root, "tools/canary/slice1_phase_b_single_dispatch.py",
            ),
        ],
    }
    return _sealed(
        "slice1-phase-b-single-dispatch-transport-guard-v1", body,
        "transport_guard_sha256",
    )


def attempt_accounting_contract(guard: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-attempt-accounting-v1",
        {
            "schema": "Slice1PhaseBAttemptAccountingContractV1",
            "version": 1,
            "model_logical_call_definition": (
                "one explicit AnthropicAdapter complete invocation"
            ),
            "real_provider_request_attempt_definition": (
                "one pre-authorized call to httpx AsyncClient POST/stream POST"
            ),
            "http_post_attempt_definition": (
                "one entry past HttpProvider._before_http_post_attempt"
            ),
            "network_request_attempt_definition": (
                "the same guarded outbound HTTP POST attempt boundary"
            ),
            "enforcement_boundary": (
                "HttpProvider._before_http_post_attempt before client.post/client.stream"
            ),
            "hard_max_model_logical_calls": 1,
            "hard_max_real_provider_request_attempts": 1,
            "hard_max_http_post_attempts": 1,
            "hard_max_network_request_attempts": 1,
            "post_hoc_count_only": False,
            "transport_guard_sha256": guard["transport_guard_sha256"],
        },
        "attempt_accounting_sha256",
    )


def guarded_budget_contract(
    route: Mapping[str, Any], model_input: Mapping[str, Any],
) -> dict[str, Any]:
    old = base.budget_contract(route, model_input)
    body = {key: value for key, value in old.items() if key != "budget_sha256"}
    body.update({
        "schema": "Slice1PhaseBSingleDispatchBudgetV1",
        "version": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "sdk_retries_allowed": False,
        "transport_request_retries_allowed": False,
        "route_fallback_after_dispatch_allowed": False,
    })
    return _sealed("slice1-phase-b-single-dispatch-budget-v1", body, "budget_sha256")


def approval_template(bound: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-single-dispatch-approval-template-v1",
        {
            "schema": "Slice1PhaseBSingleDispatchApprovalTemplateV1",
            "version": 1,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "bound_hashes": dict(bound),
            "execution_authorized": False,
            "named_approver": None,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "single_use_nonce": None,
            "execution_window": None,
            "signed_approval": "ABSENT",
            "approval_reuse_allowed": False,
            "full_short_authorized": False,
            "skill_v2_authorized": False,
            "draft_authorized": False,
            "credential_lookup_authorized": False,
            "provider_client_creation_authorized": False,
            "network_authorized": False,
            "model_call_authorized": False,
            "paid_call_authorized": False,
            "external_actions": dict(ZERO_COUNTERS),
        },
        "approval_template_sha256",
    )


def old_approval_non_reuse_receipt() -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-old-approval-non-reuse-v1",
        {
            "schema": "Slice1PhaseBOldApprovalNonReuseReceiptV1",
            "version": 1,
            "previous_approval_head": PREVIOUS_APPROVAL_HEAD,
            "previous_approval_cohort": PREVIOUS_APPROVAL_COHORT,
            "previous_approval_nonce_state": "UNUSED_UNRESERVED_NOT_CONSUMED",
            "previous_approval_reuse_allowed": False,
            "previous_nonce_consumed": False,
            "reason": "runtime_build_semantics_changed_after_approved_packet",
            "historical_abort_evidence_preserved": True,
        },
        "old_approval_non_reuse_sha256",
    )


def _privacy_scan(files: Mapping[str, bytes]) -> dict[str, Any]:
    absolute = re.compile(rb"(?:[A-Za-z]:[\\/]|/(?:home|Users|workspace)/)")
    secret = re.compile(
        rb"(?i)(?:api[_-]?key|authorization|bearer)\s*[:=]\s*[^\s,}\]]+",
    )
    raw = re.compile(
        rb"(?i)(?:raw_provider_(?:response|content)|raw_prompt|raw_story)\s*[:=]",
    )
    violations = [
        name for name, data in files.items()
        if absolute.search(data) or secret.search(data) or raw.search(data)
    ]
    return {
        "schema": "Slice1PhaseBSingleDispatchPrivacyScanV1",
        "version": 1,
        "overall_status": "exact" if not violations else "blocked",
        "scanned_file_count": len(files),
        "materialization_privacy_match_count": len(violations),
        "raw_prompt_field_count": 0,
        "raw_story_field_count": 0,
        "raw_provider_content_count": 0,
        "credential_value_count": 0,
        "private_absolute_path_count": 0,
        "violating_files": violations,
        "external_actions": dict(ZERO_COUNTERS),
    }


def build_packet_documents(
    *, repo_root: Path, route_database: Path,
    validation_summary: Mapping[str, str] | None = None,
    expected_routes: Mapping[str, Mapping[str, str]] | None = None,
    skill_roots: Sequence[Path] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    git = base.verify_git_gate(repo_root, require_clean=True)
    ptr12 = base.verify_ptr12_final(repo_root)
    profile, compacted = base.verify_skill_resolution_twice(
        repo_root, roots=skill_roots,
    )
    workload, authority = base.load_fixture_binding(repo_root)
    contract = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(
        route_database, expected_routes=expected_routes,
    )
    model_input, _system, _user = base.build_model_input(
        repo_root, authority, compacted, profile, contract, route,
    )
    call_graph = base.call_graph_contract()
    budget = guarded_budget_contract(route, model_input)
    output = base.output_isolation_contract()
    quality = base.quality_capture_contract()
    ab_lock = base.ab_lock_contract(
        workload, contract, route, budget, output, quality,
    )
    guard = transport_guard_contract(repo_root)
    accounting = attempt_accounting_contract(guard)
    old_approval = old_approval_non_reuse_receipt()
    plan = _sealed(
        "slice1-phase-b-single-dispatch-plan-v1",
        {
            "schema": "Slice1PhaseBSingleDispatchPlanV1",
            "version": 1,
            "branch": git["branch"],
            "materialization_head": git["head"],
            "cohort_id": COHORT_ID,
            "scope": APPROVAL_SCOPE,
            "materialization_only": True,
            "single_dispatch_transport_guard_required": True,
            "phase_b_status": "NOT_STARTED",
            "planning_v1_production_authority": True,
            "slice1_phase_b_shadow_only": True,
            "skill_arm": base.SKILL_ARM,
            "skill_v2_profile_active": False,
            "prompt_changed": False,
            "route_model_changed": False,
            "fallback_policy_changed": False,
            "normal_production_retry_policy_changed": False,
            "output_budget_policy_changed": False,
            "planning_v1_changed": False,
            "planning_v2_changed": False,
            "skill_profile_changed": False,
            "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False,
            "draft_authorized": False,
            "full_short_authorized": False,
            "external_actions": dict(ZERO_COUNTERS),
        },
        "plan_sha256",
    )
    bound = {
        "materialization_head": git["head"],
        "plan_sha256": plan["plan_sha256"],
        "workload_sha256": workload["workload_sha256"],
        "authority_input_sha256": workload["authority_input_sha256"],
        "current_skill_profile_sha256": profile["profile_sha256"],
        "model_input_assembly_sha256": model_input["model_input_assembly_sha256"],
        "route_binding_sha256": route["route_binding_sha256"],
        "transport_guard_sha256": guard["transport_guard_sha256"],
        "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "ptr12_manifest_sha256": ptr12["manifest_sha256"],
        "output_isolation_sha256": output["output_isolation_sha256"],
        "call_graph_sha256": call_graph["call_graph_sha256"],
        "quality_capture_contract_sha256": quality["quality_capture_contract_sha256"],
        "ab_comparison_lock_sha256": ab_lock["ab_comparison_lock_sha256"],
        "old_approval_non_reuse_sha256": old_approval["old_approval_non_reuse_sha256"],
    }
    launcher = _sealed(
        "slice1-phase-b-single-dispatch-launcher-v1",
        {
            "schema": "Slice1PhaseBSingleDispatchLauncherBindingV1",
            "version": 1,
            "launcher_source": _source_binding(
                repo_root, "tools/canary/slice1_phase_b_single_dispatch.py",
            ),
            "preflight_order": [
                "head_and_packet", "signed_approval", "guard_build",
                "attempt_cap", "nonce_reservation", "credential_lookup",
                "provider_client_creation", "single_dispatch",
            ],
            "guard_verified_before_nonce_reservation": True,
            "credential_capable_imports_after_signed_preflight": True,
            "transport_guard_sha256": guard["transport_guard_sha256"],
            "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
        },
        "launcher_binding_sha256",
    )
    bound["launcher_binding_sha256"] = launcher["launcher_binding_sha256"]
    approval = approval_template(bound)
    validation = dict(validation_summary or {})
    offline = {
        "schema": "Slice1PhaseBSingleDispatchOfflineTestReceiptV1",
        "version": 1,
        "overall_status": "exact" if validation else "pending",
        "fake_transport_matrix": validation.get("focused", "PENDING"),
        "phase_b_preflight_tests": validation.get("preflight", "PENDING"),
        "related_tests": validation.get("related", "PENDING"),
        "full_suite": validation.get("full_suite", "PENDING"),
        "strict_l3": validation.get("strict_l3", "PENDING"),
        "ptr12_regression": validation.get("ptr12", "PENDING"),
        "r0f_regression": validation.get("r0f", "PENDING"),
        "normal_production_retry_parity": validation.get(
            "production_retry_parity", "PENDING",
        ),
        "external_actions": dict(ZERO_COUNTERS),
    }
    docs: dict[str, bytes] = {
        "README.md": (
            "# Slice1 Phase B guarded CURRENT-Skill baseline v2\n\n"
            "Fresh disabled packet. No signed approval, nonce reservation, credential "
            "lookup, Provider client, network, model, paid call, Draft, or Full Short.\n"
        ).encode("utf-8"),
        "phase-b-current-skill-single-dispatch-plan-v1.json": _json_bytes(plan),
        "phase-b-current-skill-workload-v1.json": _json_bytes(workload),
        "phase-b-current-skill-profile-v1.json": _json_bytes(profile),
        "phase-b-current-skill-authority-binding-v1.json": _json_bytes(contract),
        "phase-b-current-skill-route-binding-v1.json": _json_bytes(route),
        "phase-b-current-skill-model-input-assembly-v1.json": _json_bytes(model_input),
        "phase-b-current-skill-call-graph-v1.json": _json_bytes(call_graph),
        "phase-b-current-skill-single-dispatch-transport-guard-v1.json": _json_bytes(guard),
        "phase-b-current-skill-attempt-accounting-v1.json": _json_bytes(accounting),
        "phase-b-current-skill-budget-v1.json": _json_bytes(budget),
        "phase-b-current-skill-approval-template-v1.json": _json_bytes(approval),
        "phase-b-current-skill-launcher-binding-v1.json": _json_bytes(launcher),
        "phase-b-current-skill-output-isolation-v1.json": _json_bytes(output),
        "phase-b-current-skill-quality-capture-contract-v1.json": _json_bytes(quality),
        "phase-b-current-skill-ab-comparison-lock-v1.json": _json_bytes(ab_lock),
        "phase-b-current-skill-old-approval-non-reuse-v1.json": _json_bytes(old_approval),
        "phase-b-current-skill-offline-test-receipt-v1.json": _json_bytes(offline),
    }
    report = f"""# Slice1 Phase B Single-Dispatch CURRENT-Skill Materialization v2

`SLICE1_PHASE_B_SINGLE_DISPATCH_TRANSPORT_GUARD_FIXED`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_REMATERIALIZED`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_READY_FOR_FRESH_USER_APPROVAL=YES`

- Branch: `{git['branch']}`
- Materialization HEAD: `{git['head']}`
- Cohort: `{COHORT_ID}`
- Provider / adapter: `anthropic / AnthropicAdapter`
- Guard policy SHA-256: `{guard['policy_definition_sha256']}`
- Transport guard SHA-256: `{guard['transport_guard_sha256']}`
- Attempt accounting SHA-256: `{accounting['attempt_accounting_sha256']}`
- Current Skill profile SHA-256: `{profile['profile_sha256']}`
- Model input assembly SHA-256: `{model_input['model_input_assembly_sha256']}`
- Route binding SHA-256: `{route['route_binding_sha256']}`
- Budget SHA-256: `{budget['budget_sha256']}`
- Approval template SHA-256: `{approval['approval_template_sha256']}`
- Previous approval HEAD: `{PREVIOUS_APPROVAL_HEAD}`
- Previous nonce: `UNUSED_UNRESERVED_NOT_CONSUMED`
- Previous approval reuse allowed: `NO`
- Offline focused: `{offline['fake_transport_matrix']}`
- Offline related: `{offline['related_tests']}`
- Full suite: `{offline['full_suite']}`
- Strict L3: `{offline['strict_l3']}`
- Exact next gate: `SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_FRESH_USER_APPROVAL`

`SINGLE_DISPATCH_TRANSPORT_GUARD=PASS`  
`MAX_REAL_PROVIDER_REQUEST_ATTEMPTS=1`  
`MAX_HTTP_POST_ATTEMPTS=1`  
`SDK_RETRIES_DISABLED_FOR_PHASE_B=YES`  
`TRANSPORT_REQUEST_RETRIES_DISABLED_FOR_PHASE_B=YES`  
`NORMAL_PRODUCTION_TRANSPORT_RETRY_POLICY_CHANGED=NO`  
`OLD_APPROVAL_REUSE_ALLOWED=NO`  
`OLD_NONCE_CONSUMED=NO`  
`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`SIGNED_APPROVAL=ABSENT`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`SLICE1_PHASE_B=NOT_STARTED`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    docs["phase-b-current-skill-single-dispatch-final-report-v1.md"] = report.encode(
        "utf-8",
    )
    privacy = _privacy_scan(docs)
    _require(privacy["overall_status"] == "exact", "materialization_privacy_blocked")
    docs["phase-b-current-skill-privacy-scan-v1.json"] = _json_bytes(privacy)
    definition = {
        "schema": "Slice1PhaseBSingleDispatchPacketDefinitionV1",
        "version": 1,
        "cohort_id": COHORT_ID,
        "materialization_head": git["head"],
        "document_names": sorted(docs),
        "bound_hashes": bound,
    }
    packet_definition_sha = _domain_sha(
        "slice1-phase-b-single-dispatch-packet-definition-v1", definition,
    )
    return docs, {
        "git": git, "ptr12": ptr12, "profile": profile,
        "model_input": model_input, "route": route, "guard": guard,
        "accounting": accounting, "budget": budget, "approval": approval,
        "launcher": launcher, "privacy": privacy,
        "packet_definition_sha256": packet_definition_sha,
    }


def materialize_packet(
    *, repo_root: Path, route_database: Path, output_root: Path,
    validation_summary: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _require(not output_root.exists(), "materialization_target_already_exists")
    docs, meta = build_packet_documents(
        repo_root=repo_root, route_database=route_database,
        validation_summary=validation_summary,
    )
    output_root.mkdir(parents=True)
    for name, data in docs.items():
        (output_root / name).write_bytes(data)
    files = [{
        "path": f"{REPORT_RELATIVE_ROOT}/{path.name}",
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
    } for path in sorted(output_root.iterdir(), key=lambda item: item.name)
        if path.is_file()]
    manifest = {
        "schema": "Slice1PhaseBSingleDispatchSHA256ManifestV1",
        "version": 1,
        "overall_status": "exact",
        "coverage_root": REPORT_RELATIVE_ROOT,
        "inclusion_rule": "all direct regular files except sha256-manifest-v1.json",
        "self_excluded": True,
        "algorithm": "sha256",
        "path_basis": "repository-relative-posix",
        "byte_domain": "exact_file_bytes",
        "files": files,
        "file_count": len(files),
        "packet_definition_sha256": meta["packet_definition_sha256"],
        "external_actions": dict(ZERO_COUNTERS),
    }
    manifest["manifest_definition_sha256"] = _domain_sha(
        "slice1-phase-b-single-dispatch-manifest-definition-v1",
        {key: value for key, value in manifest.items() if key != "files"},
    )
    _write_json(output_root / "sha256-manifest-v1.json", manifest)
    return {
        **meta, "manifest": manifest,
        "manifest_sha256": _sha_file(output_root / "sha256-manifest-v1.json"),
    }


def validate_materialized_packet(
    repo_root: Path, packet_root: Path,
) -> dict[str, Any]:
    manifest = _read_json(packet_root / "sha256-manifest-v1.json")
    _require(manifest.get("overall_status") == "exact", "packet_manifest_not_exact")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("file_count"), "packet_manifest_coverage_mismatch")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "packet_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "packet_file_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"), "packet_file_hash_mismatch")
    approval = _read_json(packet_root / "phase-b-current-skill-approval-template-v1.json")
    _require(approval.get("execution_authorized") is False, "disabled_approval_authorized")
    _require(approval.get("named_approver") is None, "disabled_approval_has_approver")
    _require(approval.get("usage_status") == "unused", "disabled_approval_used")
    _require(approval.get("reservation_status") == "unreserved", "approval_reserved")
    guard = _read_json(
        packet_root / "phase-b-current-skill-single-dispatch-transport-guard-v1.json",
    )
    _require(guard == transport_guard_contract(repo_root), "transport_guard_changed")
    return {"status": "exact", "approval": approval, "guard": guard}


def verify_execution_head_successor(repo_root: Path, bound_head: str) -> dict[str, Any]:
    git = base.verify_git_gate(repo_root, require_clean=True)
    try:
        base._git(repo_root, "merge-base", "--is-ancestor", bound_head, git["head"])
    except Exception as exc:
        raise Slice1PhaseBSingleDispatchError(
            "materialization_head_not_ancestor",
        ) from exc
    changed = tuple(filter(None, base._git(
        repo_root, "diff", "--name-only", f"{bound_head}..{git['head']}",
    ).splitlines()))
    prefix = REPORT_RELATIVE_ROOT + "/"
    _require(all(path.startswith(prefix) for path in changed),
             "materialization_successor_contains_non_evidence_change")
    return {"head": git["head"], "changed_paths": list(changed)}


def validate_signed_launch(
    *, repo_root: Path, packet_root: Path, signed_approval: Mapping[str, Any],
    run_root: Path, now: datetime | None = None,
) -> dict[str, Any]:
    packet = validate_materialized_packet(repo_root, packet_root)
    template = packet["approval"]
    _require(
        signed_approval.get("schema") == "Slice1PhaseBSingleDispatchSignedApprovalV1",
        "signed_approval_schema_mismatch",
    )
    _require(signed_approval.get("execution_authorized") is True,
             "execution_not_authorized")
    _require(bool(signed_approval.get("named_approver")), "named_approver_missing")
    _require(signed_approval.get("approval_scope") == APPROVAL_SCOPE,
             "approval_scope_mismatch")
    _require(signed_approval.get("cohort_id") == COHORT_ID, "approval_cohort_mismatch")
    _require(signed_approval.get("bound_hashes") == template.get("bound_hashes"),
             "approval_bound_hashes_mismatch")
    _require(signed_approval.get("full_short_authorized") is False,
             "full_short_authorization_forbidden")
    _require(signed_approval.get("skill_v2_authorized") is False,
             "skill_v2_authorization_forbidden")
    _require(signed_approval.get("draft_authorized") is False,
             "draft_authorization_forbidden")
    nonce = str(signed_approval.get("single_use_nonce") or "")
    _require(bool(nonce), "single_use_nonce_missing")
    window = signed_approval.get("execution_window") or {}
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise Slice1PhaseBSingleDispatchError("execution_window_invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(start <= current <= end, "execution_window_inactive")
    bound_head = str(template["bound_hashes"]["materialization_head"])
    verify_execution_head_successor(repo_root, bound_head)
    guard = transport_guard_contract(repo_root)
    _require(guard["transport_guard_sha256"] ==
             template["bound_hashes"]["transport_guard_sha256"],
             "transport_guard_binding_mismatch")
    _require(guard["max_http_post_attempts"] == 1,
             "http_attempt_cap_not_one")
    _require(guard["sdk_retries_disabled_for_phase_b"] is True,
             "sdk_retries_not_disabled")
    _require(guard["transport_request_retries_disabled_for_phase_b"] is True,
             "transport_retries_not_disabled")
    _require(os.getenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1") == "1",
             "ptr12_observer_not_enabled")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return {
        "status": "exact", "nonce": nonce,
        "single_dispatch_transport_guard_active": True,
        "max_http_post_attempts": 1,
        "max_real_provider_request_attempts": 1,
        "credential_lookup_allowed_after_this_return": True,
        "provider_client_creation_allowed_after_this_return": True,
    }


async def execute_authorized_once(
    *, repo_root: Path, packet_root: Path, signed_approval_path: Path,
    route_database: Path, run_root: Path,
) -> dict[str, Any]:
    """Execute one future guarded call after a separate signed authorization."""

    signed = _read_json(signed_approval_path)
    gate = validate_signed_launch(
        repo_root=repo_root, packet_root=packet_root,
        signed_approval=signed, run_root=run_root,
    )
    run_root.mkdir(parents=True)
    ledger_root = run_root / "ledger"
    ledger_root.mkdir()
    reservation = ledger_root / "single-use-ledger-v1.json"
    with reservation.open("x", encoding="utf-8") as handle:
        json.dump({
            "schema": "Slice1PhaseBSingleDispatchLedgerV1", "version": 1,
            "cohort_id": COHORT_ID,
            "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
            "usage_status": "reserved", "model_logical_calls": 0,
            "http_post_attempts": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    isolated_db = runtime_root / "app.db"
    shutil.copy2(route_database, isolated_db)
    workload, authority_value = base.load_fixture_binding(repo_root)
    profile, compacted = base.verify_skill_resolution_twice(repo_root)
    contract_binding = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(route_database)
    model_input, system, user = base.build_model_input(
        repo_root, authority_value, compacted, profile, contract_binding, route,
    )
    budget = _read_json(packet_root / "phase-b-current-skill-budget-v1.json")
    _require(model_input["model_input_assembly_sha256"] ==
             signed["bound_hashes"]["model_input_assembly_sha256"],
             "model_input_changed_before_dispatch")

    # Credential-capable imports and Provider client construction remain below
    # signed preflight and exclusive nonce reservation.
    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import (
        StructuredArtifactContract,
        StructuredOutputRequirement,
    )
    from novel_flywheel.planning_v2_slice1 import (
        build_event_realization_artifact,
        convert_event_realization_candidate,
        freeze_validated_artifact,
        validate_event_realization_artifact,
    )

    class AttemptTrackingRegistry(ProviderRegistry):
        last_adapter = None

        def resolve(self, provider_id: str, model_id: str):
            resolved = super().resolve(provider_id, model_id)
            self.last_adapter = resolved.adapter
            return resolved

    db = Database(isolated_db)
    registry = AttemptTrackingRegistry(
        db, KeyringSecretStore(),
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value),
    )
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1", version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": workload["authority_input_sha256"]},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root, run_id=COHORT_ID, stage="planning",
        boundary="slice1_phase_b_current_skill_single_dispatch",
        role="planning", route_kind="primary",
        contract_id=SLICE1_CONTRACT_IDENTITY, contract_version=1,
        outer_retry_ordinal=1,
        provider_binding_sha256=base.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=base.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(budget["hard_max_output_tokens_per_call"]),
    )
    result = None
    terminal_error = None
    try:
        result = await asyncio.wait_for(
            gateway.complete_route(
                "primary", "planning", system, user,
                max_output_tokens=int(budget["hard_max_output_tokens_per_call"]),
                contract=contract,
                structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
                diagnostic_context=diagnostic,
            ),
            timeout=int(budget["hard_max_elapsed_seconds"]),
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        terminal_error = exc
    adapter = registry.last_adapter
    attempts = (
        adapter.transport_attempt_snapshot() if adapter is not None else {
            "model_logical_calls": 0, "http_post_attempts": 0,
            "real_provider_request_attempts": 0,
            "network_request_attempts": 0,
        }
    )
    _require(attempts["http_post_attempts"] <= 1, "http_attempt_cap_exceeded")
    _write_json(reservation, {
        "schema": "Slice1PhaseBSingleDispatchLedgerV1", "version": 1,
        "cohort_id": COHORT_ID,
        "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
        "usage_status": "consumed" if attempts["http_post_attempts"] else "reserved",
        **attempts,
    })
    if terminal_error is not None:
        raise terminal_error
    assert result is not None
    candidate, conversion = convert_event_realization_candidate(
        result.text, authority=authority,
    )
    artifact = build_event_realization_artifact(
        authority, candidate, producer_kind="future_model_shadow",
    )
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    _write_json(artifact_root / "generated-event-realization-v1.json", {
        "schema": "Slice1PhaseBGeneratedExperimentArtifactV2", "version": 2,
        "cohort_id": COHORT_ID, "skill_arm": base.SKILL_ARM,
        "artifact": frozen.model_dump(mode="json", by_alias=True),
        "conversion_audit_sha256": _domain_sha(
            "slice1-phase-b-conversion-audit-v2", asdict(conversion),
        ),
        "model_receipt": {
            key: value for key, value in result.receipt.items()
            if key not in {"raw_response", "raw_content", "request_id"}
        },
        "transport_attempts": attempts,
        "production_authority": False,
    })
    return {
        "status": "executed_once", "model_call_count": 1,
        "http_post_attempts": attempts["http_post_attempts"],
        "full_short_canary": "NOT_EXECUTED", "draft_entered": False,
        "production_database_mutation_count": 0,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--route-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--focused-result")
    parser.add_argument("--preflight-result")
    parser.add_argument("--related-result")
    parser.add_argument("--full-suite-result")
    parser.add_argument("--strict-l3-result")
    parser.add_argument("--ptr12-result")
    parser.add_argument("--r0f-result")
    parser.add_argument("--production-retry-parity-result")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_root = (args.output_root or repo_root / REPORT_RELATIVE_ROOT).resolve()
    if args.validate_only:
        result = validate_materialized_packet(repo_root, output_root)
    else:
        summary = {
            key: value for key, value in {
                "focused": args.focused_result,
                "preflight": args.preflight_result,
                "related": args.related_result,
                "full_suite": args.full_suite_result,
                "strict_l3": args.strict_l3_result,
                "ptr12": args.ptr12_result,
                "r0f": args.r0f_result,
                "production_retry_parity": args.production_retry_parity_result,
            }.items() if value is not None
        }
        result = materialize_packet(
            repo_root=repo_root, route_database=args.route_database.resolve(),
            output_root=output_root, validation_summary=summary or None,
        )
    print(json.dumps({
        "status": result.get("status", "materialized"),
        "cohort_id": COHORT_ID,
        "execution_authorized": False,
        "external_actions": ZERO_COUNTERS,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
