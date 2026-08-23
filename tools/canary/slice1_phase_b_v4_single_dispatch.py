"""Versioned, packet-exact Slice1 Phase B CURRENT-Skill launcher.

This module is offline-only unless ``execute_authorized_once`` is called with a
separately sealed approval.  The profile is a closed allowlist for one packet;
scope, cohort, roots, and artifact names are never accepted from caller input.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    SLICE1_CONTRACT_IDENTITY,
    normalize_event_realization_input_authority_v1,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_single_dispatch as legacy


EXPECTED_BRANCH = base.EXPECTED_BRANCH
PROFILE_ID = "SLICE1_PHASE_B_CURRENT_SKILL_PACKET_V4"
APPROVAL_SCOPE = (
    "SLICE1_PHASE_B_CURRENT_SKILL_TUPLE_NORMALIZED_SINGLE_DISPATCH_V3_ONLY"
)
COHORT_ID = "slice1-phase-b-current-skill-launcher-v4-20260823t123857z-001"
MATERIALIZATION_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-materialization-v4"
)
EXECUTION_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-execution-v4"
)
APPROVAL_RELATIVE_PATH = (
    MATERIALIZATION_RELATIVE_ROOT
    + "/approval/phase-b-current-skill-v4-signed-authorization-v1.json"
)
NONCE_LEDGER_RELATIVE_PATH = (
    EXECUTION_RELATIVE_ROOT + "/ledger/single-use-ledger-v1.json"
)
NONCE_LEDGER_SCHEMA = "Slice1PhaseBSingleDispatchLedgerV1"
V3_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-materialization-v3"
)
V2_APPROVAL_HEAD = "85f5dc94b8aa218fbea3d12c617956eef4b2b505"
V2_NONCE_STATE = "SPENT_CONSUMED"
ZERO_COUNTERS = {
    **base.ZERO_COUNTERS,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_request_attempts": 0,
}

FILES = {
    "plan": "phase-b-current-skill-v4-plan-v1.json",
    "workload": "phase-b-current-skill-v4-workload-v1.json",
    "authority": "phase-b-current-skill-v4-authority-binding-v1.json",
    "normalization": "phase-b-current-skill-v4-authority-tuple-normalization-v1.json",
    "profile": "phase-b-current-skill-v4-skill-profile-v1.json",
    "model_input": "phase-b-current-skill-v4-model-input-binding-v1.json",
    "route": "phase-b-current-skill-v4-route-binding-v1.json",
    "launcher": "phase-b-current-skill-v4-launcher-binding-v1.json",
    "guard": "phase-b-current-skill-v4-transport-guard-binding-v1.json",
    "accounting": "phase-b-current-skill-v4-attempt-accounting-v1.json",
    "budget": "phase-b-current-skill-v4-budget-v1.json",
    "approval": "phase-b-current-skill-v4-approval-template-v1.json",
    "output": "phase-b-current-skill-v4-output-isolation-v1.json",
    "quality": "phase-b-current-skill-v4-quality-capture-v1.json",
    "ab_lock": "phase-b-current-skill-v4-ab-lock-v1.json",
    "old_approval": "phase-b-current-skill-v4-old-approval-nonreuse-v1.json",
    "offline": "phase-b-current-skill-v4-offline-test-receipt-v1.json",
    "privacy": "phase-b-current-skill-v4-privacy-scan-v1.json",
    "report": "phase-b-current-skill-v4-final-report-v1.md",
    "manifest": "sha256-manifest-v1.json",
}


class Slice1PhaseBV4LauncherError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise Slice1PhaseBV4LauncherError(reason_code)


_canonical_bytes = legacy._canonical_bytes
_json_bytes = legacy._json_bytes
_sha_bytes = legacy._sha_bytes
_sha_file = legacy._sha_file
_domain_sha = legacy._domain_sha
_sealed = legacy._sealed
_read_json = legacy._read_json
_write_json = legacy._write_json
_source_binding = legacy._source_binding


def packet_profile() -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-v4-packet-profile-v1",
        {
            "schema": "Slice1PhaseBPacketProfileV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "approval_relative_path": APPROVAL_RELATIVE_PATH,
            "nonce_ledger_relative_path": NONCE_LEDGER_RELATIVE_PATH,
            "nonce_ledger_schema": NONCE_LEDGER_SCHEMA,
            "arbitrary_scope_acceptance": False,
            "arbitrary_cohort_acceptance": False,
            "arbitrary_report_root_acceptance": False,
            "unknown_packet_fails_closed": True,
        },
        "launcher_profile_sha256",
    )


def transport_guard_contract(repo_root: Path) -> dict[str, Any]:
    policy = SingleDispatchTransportPolicyV1.phase_b()
    http_path = repo_root / "src/novel_flywheel/providers/http.py"
    registry_path = repo_root / "src/novel_flywheel/providers/registry.py"
    launcher_path = repo_root / "tools/canary/slice1_phase_b_v4_single_dispatch.py"
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
        "versioned_launcher_constructs_explicit_policy": (
            "transport_policy=SingleDispatchTransportPolicyV1.phase_b()"
            in launcher_source
        ),
    }
    _require(all(checks.values()), "single_dispatch_guard_build_unknown")
    return _sealed(
        "slice1-phase-b-v4-single-dispatch-transport-guard-v1",
        {
            "schema": "Slice1PhaseBV4SingleDispatchTransportGuardV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "policy": policy.definition(),
            "policy_definition_sha256": policy.definition_sha256(),
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
                    repo_root, "tools/canary/slice1_phase_b_v4_single_dispatch.py",
                ),
            ],
        },
        "transport_guard_sha256",
    )


def attempt_accounting_contract(guard: Mapping[str, Any]) -> dict[str, Any]:
    return legacy.attempt_accounting_contract(guard)


def launcher_binding(
    repo_root: Path,
    *,
    implementation_head: str,
    authority_normalization_sha256: str,
    guard: Mapping[str, Any],
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    profile = packet_profile()
    return _sealed(
        "slice1-phase-b-v4-launcher-binding-v1",
        {
            "schema": "Slice1PhaseBV4LauncherBindingV1",
            "version": 1,
            "implementation_head": implementation_head,
            "entrypoint": "tools.canary.slice1_phase_b_v4_single_dispatch",
            "entrypoint_source": _source_binding(
                repo_root, "tools/canary/slice1_phase_b_v4_single_dispatch.py",
            ),
            "launcher_profile": profile,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "approval_relative_path": APPROVAL_RELATIVE_PATH,
            "nonce_ledger_relative_path": NONCE_LEDGER_RELATIVE_PATH,
            "nonce_ledger_schema": NONCE_LEDGER_SCHEMA,
            "transport_guard_sha256": guard["transport_guard_sha256"],
            "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
            "authority_tuple_normalization_sha256": authority_normalization_sha256,
            "preflight_order": [
                "packet_head_build_validation",
                "launcher_binding_validation",
                "scope_cohort_root_validation",
                "approval_validation",
                "single_dispatch_guard_validation",
                "authority_tuple_validation",
                "budget_validation",
                "nonce_reservation",
                "credential_lookup",
                "provider_client_creation",
                "single_dispatch",
            ],
            "arbitrary_scope_acceptance": False,
            "arbitrary_cohort_acceptance": False,
            "arbitrary_report_root_acceptance": False,
            "unknown_packet_fails_closed": True,
        },
        "launcher_binding_sha256",
    )


def validate_launcher_binding(
    value: Mapping[str, Any],
    *,
    repo_root: Path,
    implementation_head: str,
    authority_normalization_sha256: str,
    guard: Mapping[str, Any],
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    expected = launcher_binding(
        repo_root,
        implementation_head=implementation_head,
        authority_normalization_sha256=authority_normalization_sha256,
        guard=guard,
        accounting=accounting,
    )
    _require(value == expected, "launcher_binding_mismatch")
    return expected


def _fresh_output_isolation() -> dict[str, Any]:
    value = dict(base.output_isolation_contract())
    value["namespace"] = f"slice1-phase-b-experiments/{COHORT_ID}"
    value.pop("output_isolation_sha256", None)
    return _sealed(
        "slice1-phase-b-v4-output-isolation-v1",
        value,
        "output_isolation_sha256",
    )


def _old_approval_receipt() -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-v4-old-approval-nonreuse-v1",
        {
            "schema": "Slice1PhaseBV4OldApprovalNonReuseV1",
            "version": 1,
            "previous_v2_approval_head": V2_APPROVAL_HEAD,
            "previous_v2_nonce_state": V2_NONCE_STATE,
            "previous_v2_approval_reuse_allowed": False,
            "previous_v2_nonce_reuse_allowed": False,
            "v3_failed_approval_created": False,
            "v3_failed_approval_nonce_issued": False,
        },
        "old_approval_nonreuse_sha256",
    )


def _approval_template(bound: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "slice1-phase-b-v4-approval-template-v1",
        {
            "schema": "Slice1PhaseBV4ApprovalTemplateV1",
            "version": 1,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "execution_authorized": False,
            "named_approver": None,
            "signed_approval": "ABSENT",
            "single_use_nonce": None,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "approval_reuse_allowed": False,
            "approval_cohort_reuse_allowed": False,
            "full_short_authorized": False,
            "draft_authorized": False,
            "final_review_authorized": False,
            "maintenance_authorized": False,
            "skill_v2_authorized": False,
            "planning_v2_cutover_authorized": False,
            "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False,
            "ready_mutation_allowed": False,
            "bound_hashes": dict(bound),
            "external_actions": dict(ZERO_COUNTERS),
        },
        "approval_template_sha256",
    )


def build_packet_documents(
    repo_root: Path,
    route_database: Path,
    *,
    validation_summary: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    git = base.verify_git_gate(repo_root, require_clean=True)
    ptr12 = base.verify_ptr12_final(repo_root)
    profile, compacted = base.verify_skill_resolution_twice(repo_root)
    workload_old, authority_value = base.load_fixture_binding(repo_root)
    contract = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(route_database)
    model_input, _, _ = base.build_model_input(
        repo_root, authority_value, compacted, profile, contract, route,
    )
    model_input_repeat, _, _ = base.build_model_input(
        repo_root, authority_value, compacted, profile, contract, route,
    )
    _require(model_input == model_input_repeat, "model_input_nondeterministic")
    EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value),
    )
    normalization = _read_json(
        repo_root / V3_RELATIVE_ROOT
        / "phase-b-current-skill-v3-authority-tuple-normalization-v1.json",
    )
    _require(
        normalization.get("authority_tuple_normalization_sha256")
        == "6775a251e3fece7225e4ddb2a780e18ceccb5a3ccfff785004837a44dbc5805a",
        "authority_tuple_normalization_changed",
    )
    guard = transport_guard_contract(repo_root)
    accounting = attempt_accounting_contract(guard)
    budget = legacy.guarded_budget_contract(route, model_input)
    output = _fresh_output_isolation()
    quality = base.quality_capture_contract()
    workload = dict(workload_old)
    workload["cohort_id"] = COHORT_ID
    workload.pop("workload_sha256", None)
    workload = _sealed("slice1-phase-b-v4-workload-v1", workload, "workload_sha256")
    ab_lock = base.ab_lock_contract(workload, contract, route, budget, output, quality)
    old_approval = _old_approval_receipt()
    launcher = launcher_binding(
        repo_root,
        implementation_head=git["head"],
        authority_normalization_sha256=normalization[
            "authority_tuple_normalization_sha256"
        ],
        guard=guard,
        accounting=accounting,
    )
    plan = _sealed(
        "slice1-phase-b-v4-plan-v1",
        {
            "schema": "Slice1PhaseBV4PlanV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "cohort_id": COHORT_ID,
            "approval_scope": APPROVAL_SCOPE,
            "materialization_head": git["head"],
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "shadow_only": True,
            "skill_arm": "CURRENT_RUNTIME_SKILL",
            "execution_authorized": False,
            "external_actions": dict(ZERO_COUNTERS),
        },
        "plan_sha256",
    )
    bound = {
        "materialization_head": git["head"],
        "plan_sha256": plan["plan_sha256"],
        "workload_sha256": workload["workload_sha256"],
        "authority_input_sha256": workload["authority_input_sha256"],
        "authority_tuple_normalization_sha256": normalization[
            "authority_tuple_normalization_sha256"
        ],
        "current_skill_profile_sha256": profile["profile_sha256"],
        "model_input_assembly_sha256": model_input["model_input_assembly_sha256"],
        "route_binding_sha256": route["route_binding_sha256"],
        "launcher_profile_sha256": packet_profile()["launcher_profile_sha256"],
        "launcher_binding_sha256": launcher["launcher_binding_sha256"],
        "transport_guard_sha256": guard["transport_guard_sha256"],
        "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "output_isolation_sha256": output["output_isolation_sha256"],
        "ptr12_manifest_sha256": ptr12["manifest_sha256"],
        "quality_capture_sha256": quality["quality_capture_contract_sha256"],
        "ab_lock_sha256": ab_lock["ab_comparison_lock_sha256"],
        "old_approval_nonreuse_sha256": old_approval[
            "old_approval_nonreuse_sha256"
        ],
    }
    approval = _approval_template(bound)
    authority_doc = {
        **contract,
        "authority_input_sha256": workload["authority_input_sha256"],
        "authority_tuple_normalization_sha256": normalization[
            "authority_tuple_normalization_sha256"
        ],
        "rehydrated_container_type": "tuple",
        "strict_model_validate": "PASS",
    }
    validation = dict(validation_summary or {})
    offline = {
        "schema": "Slice1PhaseBV4OfflineTestReceiptV1",
        "version": 1,
        "overall_status": "exact" if validation else "pending",
        "launcher_negative_matrix": validation.get("focused", "PENDING"),
        "related_tests": validation.get("related", "PENDING"),
        "full_suite": validation.get("full_suite", "PENDING"),
        "strict_l3": validation.get("strict_l3", "PENDING"),
        "r0f": validation.get("r0f", "PENDING"),
        "v2_historical_compatibility": validation.get("v2", "PENDING"),
        "model_input_deterministic_x2": "PASS",
        "skill_resolution_deterministic_x2": "PASS",
        "authority_tuple_validation": "PASS",
        "external_actions": dict(ZERO_COUNTERS),
    }
    docs: dict[str, bytes] = {
        "README.md": (
            "# Slice1 Phase B launcher-bound CURRENT-Skill baseline v4\n\n"
            "Fresh disabled packet. No approval, nonce, credential, Provider, "
            "network, model, paid, Draft, or Full Short action.\n"
        ).encode("utf-8"),
        FILES["plan"]: _json_bytes(plan),
        FILES["workload"]: _json_bytes(workload),
        FILES["authority"]: _json_bytes(authority_doc),
        FILES["normalization"]: _json_bytes(normalization),
        FILES["profile"]: _json_bytes(profile),
        FILES["model_input"]: _json_bytes(model_input),
        FILES["route"]: _json_bytes(route),
        FILES["launcher"]: _json_bytes(launcher),
        FILES["guard"]: _json_bytes(guard),
        FILES["accounting"]: _json_bytes(accounting),
        FILES["budget"]: _json_bytes(budget),
        FILES["approval"]: _json_bytes(approval),
        FILES["output"]: _json_bytes(output),
        FILES["quality"]: _json_bytes(quality),
        FILES["ab_lock"]: _json_bytes(ab_lock),
        FILES["old_approval"]: _json_bytes(old_approval),
        FILES["offline"]: _json_bytes(offline),
    }
    report = f"""# Slice1 Phase B launcher-bound CURRENT-Skill v4

`SLICE1_PHASE_B_CURRENT_SKILL_V3_LAUNCHER_BINDING_FIXED`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_REMATERIALIZED_WITH_LAUNCHER_BINDING`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_READY_FOR_FRESH_USER_APPROVAL=YES`

- Materialization HEAD: `{git['head']}`
- Cohort: `{COHORT_ID}`
- Approval scope: `{APPROVAL_SCOPE}`
- Launcher binding SHA-256: `{launcher['launcher_binding_sha256']}`
- Transport guard SHA-256: `{guard['transport_guard_sha256']}`
- Attempt accounting SHA-256: `{accounting['attempt_accounting_sha256']}`
- Exact next gate: `SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_FRESH_USER_APPROVAL_AFTER_LAUNCHER_FIX`

`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`SIGNED_APPROVAL=ABSENT`  
`NEW_SINGLE_USE_NONCE=NOT_ISSUED`  
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`HTTP_POST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    docs[FILES["report"]] = report.encode("utf-8")
    privacy = legacy._privacy_scan(docs)
    _require(privacy["overall_status"] == "exact", "privacy_scan_failed")
    docs[FILES["privacy"]] = _json_bytes(privacy)
    return docs, {
        "git": git,
        "profile": packet_profile(),
        "ptr12": ptr12,
        "workload": workload,
        "normalization": normalization,
        "skill_profile": profile,
        "model_input": model_input,
        "route": route,
        "launcher": launcher,
        "guard": guard,
        "accounting": accounting,
        "budget": budget,
        "approval": approval,
        "output": output,
        "quality": quality,
        "ab_lock": ab_lock,
        "old_approval": old_approval,
        "privacy": privacy,
    }


def materialize_packet(
    *,
    repo_root: Path,
    route_database: Path,
    output_root: Path,
    validation_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_root = (repo_root / MATERIALIZATION_RELATIVE_ROOT).resolve()
    _require(output_root.resolve() == canonical_root, "materialization_root_mismatch")
    _require(not output_root.exists(), "materialization_target_already_exists")
    docs, meta = build_packet_documents(
        repo_root, route_database, validation_summary=validation_summary,
    )
    output_root.mkdir(parents=True)
    for name, data in docs.items():
        (output_root / name).write_bytes(data)
    entries = [
        {
            "path": f"{MATERIALIZATION_RELATIVE_ROOT}/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": _sha_file(path),
        }
        for path in sorted(output_root.iterdir(), key=lambda item: item.name)
        if path.is_file()
    ]
    definition = {
        "schema": "Slice1PhaseBV4SHA256ManifestDefinitionV1",
        "version": 1,
        "profile_id": PROFILE_ID,
        "cohort_id": COHORT_ID,
        "materialization_head": meta["git"]["head"],
        "coverage_root": MATERIALIZATION_RELATIVE_ROOT,
        "self_excluded": True,
        "files": entries,
    }
    manifest = {
        **{key: value for key, value in definition.items() if key != "files"},
        "file_count": len(entries),
        "launcher_artifact_count": sum(
            1 for entry in entries if "launcher-binding" in entry["path"]
        ),
        "files": entries,
        "manifest_definition_sha256": _domain_sha(
            "slice1-phase-b-v4-manifest-v1", definition,
        ),
        "overall_status": "exact",
    }
    _write_json(output_root / FILES["manifest"], manifest)
    return {
        **meta,
        "manifest": manifest,
        "manifest_file_sha256": _sha_file(output_root / FILES["manifest"]),
    }


def _verify_manifest(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    canonical_root = (repo_root / MATERIALIZATION_RELATIVE_ROOT).resolve()
    _require(packet_root.resolve() == canonical_root, "packet_root_mismatch")
    manifest = _read_json(packet_root / FILES["manifest"])
    _require(manifest.get("overall_status") == "exact", "manifest_not_exact")
    _require(manifest.get("coverage_root") == MATERIALIZATION_RELATIVE_ROOT,
             "manifest_root_mismatch")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("file_count"), "manifest_coverage_mismatch")
    _require(manifest.get("launcher_artifact_count", 0) >= 1,
             "launcher_artifact_missing")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "packet_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "packet_file_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"), "packet_file_hash_mismatch")
    return manifest


def verify_execution_head_successor(repo_root: Path, bound_head: str) -> dict[str, Any]:
    git = base.verify_git_gate(repo_root, require_clean=True)
    try:
        base._git(repo_root, "merge-base", "--is-ancestor", bound_head, git["head"])
    except Exception as exc:
        raise Slice1PhaseBV4LauncherError("materialization_head_not_ancestor") from exc
    changed = tuple(filter(None, base._git(
        repo_root, "diff", "--name-only", f"{bound_head}..{git['head']}",
    ).splitlines()))
    prefix = MATERIALIZATION_RELATIVE_ROOT + "/"
    _require(all(path.startswith(prefix) for path in changed),
             "materialization_successor_contains_non_evidence_change")
    return {"head": git["head"], "changed_paths": list(changed)}


def validate_materialized_packet(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    manifest = _verify_manifest(repo_root, packet_root)
    plan = _read_json(packet_root / FILES["plan"])
    approval = _read_json(packet_root / FILES["approval"])
    launcher = _read_json(packet_root / FILES["launcher"])
    guard = _read_json(packet_root / FILES["guard"])
    accounting = _read_json(packet_root / FILES["accounting"])
    normalization = _read_json(packet_root / FILES["normalization"])
    _require(plan.get("approval_scope") == APPROVAL_SCOPE, "packet_scope_mismatch")
    _require(plan.get("cohort_id") == COHORT_ID, "packet_cohort_mismatch")
    _require(plan.get("materialization_relative_root") == MATERIALIZATION_RELATIVE_ROOT,
             "packet_materialization_root_mismatch")
    _require(plan.get("execution_relative_root") == EXECUTION_RELATIVE_ROOT,
             "packet_execution_root_mismatch")
    _require(approval.get("approval_scope") == APPROVAL_SCOPE,
             "approval_template_scope_mismatch")
    _require(approval.get("cohort_id") == COHORT_ID,
             "approval_template_cohort_mismatch")
    _require(approval.get("execution_authorized") is False,
             "disabled_approval_authorized")
    _require(approval.get("named_approver") is None, "disabled_approval_has_approver")
    _require(approval.get("signed_approval") == "ABSENT", "signed_approval_present")
    _require(approval.get("single_use_nonce") is None, "disabled_nonce_present")
    _require(guard == transport_guard_contract(repo_root), "transport_guard_changed")
    _require(accounting == attempt_accounting_contract(guard),
             "attempt_accounting_changed")
    validate_launcher_binding(
        launcher,
        repo_root=repo_root,
        implementation_head=str(plan["materialization_head"]),
        authority_normalization_sha256=str(
            normalization["authority_tuple_normalization_sha256"]
        ),
        guard=guard,
        accounting=accounting,
    )
    _require(
        approval.get("bound_hashes", {}).get("launcher_binding_sha256")
        == launcher["launcher_binding_sha256"],
        "approval_launcher_binding_mismatch",
    )
    return {
        "status": "exact",
        "manifest": manifest,
        "plan": plan,
        "approval": approval,
        "launcher": launcher,
        "guard": guard,
        "accounting": accounting,
        "normalization": normalization,
    }


def validate_signed_launch(
    *,
    repo_root: Path,
    packet_root: Path,
    signed_approval: Mapping[str, Any],
    run_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    packet = validate_materialized_packet(repo_root, packet_root)
    expected_run_root = (repo_root / EXECUTION_RELATIVE_ROOT).resolve()
    _require(run_root.resolve() == expected_run_root, "execution_root_mismatch")
    template = packet["approval"]
    _require(signed_approval.get("schema") == "Slice1PhaseBV4SignedApprovalV1",
             "signed_approval_schema_mismatch")
    _require(signed_approval.get("execution_authorized") is True,
             "execution_not_authorized")
    _require(bool(signed_approval.get("named_approver")), "named_approver_missing")
    _require(signed_approval.get("approval_scope") == APPROVAL_SCOPE,
             "approval_scope_mismatch")
    _require(signed_approval.get("cohort_id") == COHORT_ID,
             "approval_cohort_mismatch")
    _require(signed_approval.get("bound_hashes") == template.get("bound_hashes"),
             "approval_bound_hashes_mismatch")
    for forbidden in (
        "full_short_authorized", "draft_authorized", "final_review_authorized",
        "maintenance_authorized", "skill_v2_authorized",
        "planning_v2_cutover_authorized", "story_state_mutation_allowed",
        "canon_mutation_allowed", "ready_mutation_allowed",
    ):
        _require(signed_approval.get(forbidden) is False,
                 f"{forbidden}_forbidden")
    _require(signed_approval.get("nonce_reserved") is False, "nonce_already_reserved")
    _require(signed_approval.get("nonce_consumed") is False, "nonce_already_consumed")
    nonce = str(signed_approval.get("single_use_nonce") or "")
    _require(bool(nonce), "single_use_nonce_missing")
    window = signed_approval.get("execution_window") or {}
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise Slice1PhaseBV4LauncherError("execution_window_invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(start <= current <= end, "execution_window_inactive")
    verify_execution_head_successor(
        repo_root, str(template["bound_hashes"]["materialization_head"]),
    )
    _require(os.getenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1") == "1",
             "ptr12_observer_not_enabled")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return {
        "status": "exact",
        "nonce": nonce,
        "single_dispatch_transport_guard_active": True,
        "credential_lookup_allowed_after_this_return": True,
        "provider_client_creation_allowed_after_this_return": True,
    }


async def execute_authorized_once(
    *,
    repo_root: Path,
    packet_root: Path,
    signed_approval_path: Path,
    route_database: Path,
    run_root: Path,
) -> dict[str, Any]:
    """Execute one guarded call only after exact v4 signed preflight."""

    signed = _read_json(signed_approval_path)
    gate = validate_signed_launch(
        repo_root=repo_root,
        packet_root=packet_root,
        signed_approval=signed,
        run_root=run_root,
    )
    run_root.mkdir(parents=True)
    ledger_root = run_root / "ledger"
    ledger_root.mkdir()
    reservation = ledger_root / "single-use-ledger-v1.json"
    with reservation.open("x", encoding="utf-8") as handle:
        json.dump({
            "schema": NONCE_LEDGER_SCHEMA,
            "version": 1,
            "cohort_id": COHORT_ID,
            "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
            "usage_status": "reserved",
            "model_logical_calls": 0,
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
    budget = _read_json(packet_root / FILES["budget"])
    _require(
        model_input["model_input_assembly_sha256"]
        == signed["bound_hashes"]["model_input_assembly_sha256"],
        "model_input_changed_before_dispatch",
    )

    # Credential-capable imports remain below exact preflight and reservation.
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
        db,
        KeyringSecretStore(),
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value),
    )
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": workload["authority_input_sha256"]},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root,
        run_id=COHORT_ID,
        stage="planning",
        boundary="slice1_phase_b_current_skill_v4_single_dispatch",
        role="planning",
        route_kind="primary",
        contract_id=SLICE1_CONTRACT_IDENTITY,
        contract_version=1,
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
                "primary",
                "planning",
                system,
                user,
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
        adapter.transport_attempt_snapshot()
        if adapter is not None
        else {
            "model_logical_calls": 0,
            "http_post_attempts": 0,
            "real_provider_request_attempts": 0,
            "network_request_attempts": 0,
        }
    )
    _require(attempts["http_post_attempts"] <= 1, "http_attempt_cap_exceeded")
    _write_json(reservation, {
        "schema": NONCE_LEDGER_SCHEMA,
        "version": 1,
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
        "schema": "Slice1PhaseBGeneratedExperimentArtifactV2",
        "version": 2,
        "cohort_id": COHORT_ID,
        "skill_arm": base.SKILL_ARM,
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
        "status": "executed_once",
        "model_call_count": 1,
        "http_post_attempts": attempts["http_post_attempts"],
        "full_short_canary": "NOT_EXECUTED",
        "draft_entered": False,
        "production_database_mutation_count": 0,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--route-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--focused-result")
    parser.add_argument("--related-result")
    parser.add_argument("--full-suite-result")
    parser.add_argument("--strict-l3-result")
    parser.add_argument("--r0f-result")
    parser.add_argument("--v2-result")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_root = (
        args.output_root or repo_root / MATERIALIZATION_RELATIVE_ROOT
    ).resolve()
    if args.validate_only:
        result = validate_materialized_packet(repo_root, output_root)
    else:
        summary = {
            key: value
            for key, value in {
                "focused": args.focused_result,
                "related": args.related_result,
                "full_suite": args.full_suite_result,
                "strict_l3": args.strict_l3_result,
                "r0f": args.r0f_result,
                "v2": args.v2_result,
            }.items()
            if value is not None
        }
        result = materialize_packet(
            repo_root=repo_root,
            route_database=args.route_database.resolve(),
            output_root=output_root,
            validation_summary=summary or None,
        )
    print(json.dumps({
        "status": result.get("status", "materialized"),
        "profile_id": PROFILE_ID,
        "cohort_id": COHORT_ID,
        "approval_scope": APPROVAL_SCOPE,
        "execution_authorized": False,
        "external_actions": ZERO_COUNTERS,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
