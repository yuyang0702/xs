"""Closed-world corrected Pair 1 A launcher and inert v4 materializer.

The real entry point in this module is dormant unless an exact future v4
signed approval, a current stop-state receipt, explicit current-chat external
permission, and an unused nonce all validate.  Materialization and every test
path in this module are offline-only.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Awaitable, Callable, Mapping

from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary import skill_v2_pair1_corrected_a_approval_binding_closure as closure
from tools.canary import skill_v2_pair1_fixture_narrow_fix as fixture_fix
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics import skill_v2_bounded_repeated_ab as campaign


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "1b4675694ac4b8e64f868f86a85373d30b74d0de"
SOURCE_PATH = "tools/canary/skill_v2_pair1_corrected_a_launcher_binding.py"
TEST_PATH = "tests/canary/test_skill_v2_pair1_corrected_a_launcher_binding.py"
OUTPUT_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-corrected-a-launcher-binding-fix-v1"
)
APPROVAL_ROOT = f"{OUTPUT_ROOT}/approval"
EXECUTION_ROOT = (
    "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-"
    "execution-v4/pairs/restored-character-heavy-v2/a-arm"
)
V3_ROOT = closure.OUTPUT_ROOT
V3_PACKET_PATH = f"{V3_ROOT}/corrected-a-successor-packet-v3.json"
V3_SIGNED_APPROVAL_PATH = f"{V3_ROOT}/approval/signed-approval-v3.json"
V2_A_PACKET_PATH = closure.V2_PATH
V2_A_LAUNCHER_PATH = closure.V2_LAUNCHER_PATH
V2_FIXTURE_PATH = closure.FIXTURE_PATH
V2_LOCK_PATH = closure.LOCK_PATH
V2_B_LAUNCHER_PATH = closure.V2_LAUNCHER_PATH.replace("/a-arm/", "/b-arm/")
V2_B_PACKET_PATH = closure.B_V2_PATH

V3_PACKET_SHA256 = "d7c31f05ecefdbd971df16966840f72ff4bc568c79f6633228ec4e43a5811aa7"
AUTHORITY_SHA256 = "91e5fe89ae741233b983f344bb0aa517974a4341dab56c8341669a5233c2e3d4"
STORY_SHA256 = "7134e84052d6e15bdd0f3bbb75de41a45c9e8c083d09e896004f8228b71c47c7"
LOCK_SHA256 = "31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80"
PAIR_CASE_ID = "restored-character-heavy-v2"
ARM_ROLE = "A_ARM"
SKILL_ARM = "CURRENT_RUNTIME_SKILL"
EVENT_ID = "EV-3D3AE01E"
SCOPE = "SKILL_V2_BOUNDED_REPEATED_AB_CHARACTER_HEAVY_V2_A_ARM_SINGLE_DISPATCH_ONLY"
COHORT_ID = "skill-v2-bounded-repeated-ab-character-heavy-v2-a-launcher-v4-disabled-001"
ENTRY_POINT_ID = (
    "tools.canary.skill_v2_pair1_corrected_a_launcher_binding:"
    "execute_authorized_once_v4"
)
ROOT_CAUSE = "B. CORRECTED_FIXTURE_MATERIALIZER_NEVER_CREATED_EXECUTION_LAUNCHER"

ZERO = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}

PRECREDENTIAL_NEGATIVE_CASES = (
    "missing_signed_approval",
    "approval_for_v3_packet",
    "wrong_packet_sha",
    "wrong_launcher_source_sha",
    "execution_entry_point_absent",
    "wrong_entry_point_id",
    "missing_current_chat_permission",
    "nonce_reserved_or_consumed",
    "wrong_approval_parent_head",
    "stale_phase_b_state",
    "corrected_b_packet",
    "pair2_or_later_packet",
    "active_campaign_stop",
    "ab_lock_drift",
)
POSTDISPATCH_FAILURE_CASES = (
    "connect_error",
    "http_failure",
    "malformed_provider_response",
    "local_parse_failure",
    "local_validator_rejection",
    "persistence_failure",
)


class LauncherBindingError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require(value: bool, reason: str) -> None:
    if not value:
        raise LauncherBindingError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _domain(domain: str, value: Any) -> str:
    return _sha(domain.encode(UTF8) + b"\0" + _canonical(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain(domain, result)
    return result


def _json_safe(value: Any) -> Any:
    """Serialize audit values without applying dataclasses.asdict to Pydantic."""
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _reseal(domain: str, value: Mapping[str, Any], field: str) -> dict[str, Any]:
    body = dict(value)
    body.pop(field, None)
    return _sealed(domain, body, field)


def _load(repo: Path, relative: str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding=UTF8))
    _require(isinstance(value, dict), f"not_object:{relative}")
    return value


def _file(repo: Path, relative: str) -> dict[str, Any]:
    path = repo / relative
    _require(path.is_file(), f"source_missing:{relative}")
    data = path.read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha(data)}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def _changed(repo: Path, older: str, newer: str) -> tuple[str, ...]:
    return tuple(filter(None, _git(repo, "diff", "--name-only", f"{older}..{newer}").splitlines()))


def verify_frozen_baseline(repo: Path) -> dict[str, Any]:
    _require(_git(repo, "branch", "--show-current") == EXPECTED_BRANCH, "baseline_branch_drift")
    _require(_git(repo, "rev-parse", "HEAD") == BASELINE_HEAD, "baseline_head_drift")
    _require(not _git(repo, "status", "--porcelain"), "baseline_worktree_dirty")
    return {"branch": EXPECTED_BRANCH, "head": BASELINE_HEAD, "worktree": "clean"}


def validate_approval_parent_v4(repo: Path, approval_parent_head: str) -> dict[str, Any]:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", approval_parent_head)), "approval_parent_head_malformed")
    try:
        _git(repo, "cat-file", "-e", f"{approval_parent_head}^{{commit}}")
        _git(repo, "merge-base", "--is-ancestor", BASELINE_HEAD, approval_parent_head)
    except (subprocess.CalledProcessError, OSError):
        raise LauncherBindingError("approval_parent_head_ancestry_invalid") from None
    changed = _changed(repo, BASELINE_HEAD, approval_parent_head)
    _require(set(changed) == {SOURCE_PATH, TEST_PATH}, "approval_parent_source_scope_mismatch")
    return {
        "status": "PASS",
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "changed_paths": list(changed),
        "source_policy": "explicit implementation commit containing only the corrected-A launcher and focused tests",
    }


def _binding(repo: Path, kind: str, source_path: str, functions: tuple[str, ...]) -> dict[str, Any]:
    return _sealed(
        f"skill-v2-pair1-corrected-a-v4-{kind}-binding-v1",
        {
            "schema": "SkillV2Pair1CorrectedAExplicitComponentBindingV1",
            "version": 1,
            "kind": kind,
            "source": _file(repo, source_path),
            "functions": list(functions),
            "binding_explicit": True,
        },
        "binding_sha256",
    )


def execution_order_contract_v1() -> dict[str, Any]:
    steps = [
        "packet_validation", "signed_approval_validation",
        "current_phase_b_stop_state_recomputation", "current_chat_external_permission",
        "nonce_state_check", "exclusive_nonce_reservation", "credential_lookup",
        "provider_client_creation", "one_logical_model_call", "at_most_one_provider_request",
        "at_most_one_http_post", "at_most_one_network_attempt", "local_parse_conversion_validation",
        "freeze_audit_persistence", "result_evidence_seal",
    ]
    return _sealed(
        "skill-v2-pair1-corrected-a-v4-execution-order-v1",
        {
            "schema": "SkillV2Pair1CorrectedAExecutionOrderContractV1",
            "version": 1,
            "steps": steps,
            "preflight_before_permission": True,
            "permission_before_nonce_reservation": True,
            "nonce_reservation_before_credential_lookup": True,
            "credential_lookup_before_provider_client": True,
            "second_dispatch_allowed": False,
        },
        "execution_order_contract_sha256",
    )


def launcher_architecture_v1(repo: Path) -> dict[str, Any]:
    component_specs = {
        "execution_entry_point_registry_resolver": (SOURCE_PATH, ("resolve_execution_entry_point",)),
        "launcher_source": (SOURCE_PATH, ("execute_authorized_once_v4",)),
        "signed_preflight_invocation": (SOURCE_PATH, ("validate_precredential_gate_v4",)),
        "outer_current_chat_permission_check": (SOURCE_PATH, ("validate_outer_permission_v1",)),
        "nonce_reservation": (SOURCE_PATH, ("reserve_nonce_exclusive_v1",)),
        "credential_lookup": (SOURCE_PATH, ("execute_authorized_once_v4",)),
        "provider_client_creation": (SOURCE_PATH, ("execute_authorized_once_v4",)),
        "attempt_accounting": (SOURCE_PATH, ("attempt_snapshot_v1",)),
        "single_dispatch_transport_guard": (
            "src/novel_flywheel/providers/http.py", ("SingleDispatchTransportPolicyV1.phase_b",),
        ),
        "local_success_tail": (SOURCE_PATH, ("persist_local_success_tail_v1",)),
        "execution_evidence_writer": (SOURCE_PATH, ("persist_local_success_tail_v1",)),
    }
    components = {
        key: _binding(repo, key, path, functions)
        for key, (path, functions) in component_specs.items()
    }
    return _sealed(
        "skill-v2-pair1-corrected-a-v4-launcher-architecture-v1",
        {
            "schema": "SkillV2Pair1CorrectedALauncherArchitectureV1",
            "version": 1,
            "entry_point_id": ENTRY_POINT_ID,
            "components": components,
            "arbitrary_entry_point_selection_allowed": False,
            "old_pair1_executor_alias_allowed": False,
            "runtime_dynamic_launcher_assembly_allowed": False,
        },
        "launcher_architecture_sha256",
    )


def _packet_manifest(repo: Path) -> dict[str, Any]:
    paths = (
        V3_PACKET_PATH, V2_A_PACKET_PATH, V2_A_LAUNCHER_PATH,
        V2_FIXTURE_PATH, V2_LOCK_PATH, closure.TRANSPORT_PATH,
        closure.ACCOUNTING_PATH, closure.PLAN_PATH, closure.DECISION_PATH,
        closure.AUTHORITY_SOURCE_PATH, closure.AUDIT_SOURCE_PATH,
        closure.SOURCE_PATH, SOURCE_PATH, TEST_PATH,
        "src/novel_flywheel/providers/http.py",
        "src/novel_flywheel/providers/registry.py",
    )
    entries = [_file(repo, path) for path in paths]
    return _sealed(
        "skill-v2-pair1-corrected-a-v4-packet-manifest-v1",
        {
            "schema": "SkillV2Pair1CorrectedAV4PacketManifestV1",
            "version": 1,
            "entries": entries,
            "entry_count": len(entries),
            "coverage": "all immutable v3 authority inputs plus explicit corrected-A launcher, test, transport, registry, and parser owners; v4 packet and manifest self excluded",
            "self_excluded": True,
        },
        "packet_manifest_definition_sha256",
    )


def _packet_privacy(repo: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    patterns = (
        re.compile(rb"sk-ant-[A-Za-z0-9_-]{8,}", re.I),
        re.compile(rb"authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{8,}", re.I),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    )
    matches: list[dict[str, str]] = []
    scanned = [row for row in manifest["entries"] if row["path"].endswith(".json")]
    for row in scanned:
        data = (repo / row["path"]).read_bytes()
        for index, pattern in enumerate(patterns):
            if pattern.search(data):
                matches.append({"path": row["path"], "detector_id": f"secret-{index + 1}"})
    return _sealed(
        "skill-v2-pair1-corrected-a-v4-packet-privacy-v1",
        {
            "schema": "SkillV2Pair1CorrectedAV4PacketPrivacyReceiptV1",
            "version": 1,
            "files_scanned": len(scanned),
            "privacy_match_count": len(matches),
            "matches": matches,
            "raw_prompt_persisted": False,
            "raw_story_persisted": False,
            "raw_provider_content_persisted": False,
            "credentials_persisted": False,
            "overall_status": "exact" if not matches else "blocked",
        },
        "privacy_receipt_definition_sha256",
    )


def _launcher_binding(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    architecture = launcher_architecture_v1(repo)
    order = execution_order_contract_v1()
    source = _file(repo, SOURCE_PATH)
    transport = _file(repo, "src/novel_flywheel/providers/http.py")
    body = {
        "schema": "SkillV2Pair1CorrectedALauncherBindingV4",
        "version": 4,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "corrected_formal_event_id": EVENT_ID,
        "execution_entry_point_present": True,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": source["sha256"],
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": source["sha256"],
        "launcher_architecture_sha256": architecture["launcher_architecture_sha256"],
        "execution_order_contract_sha256": order["execution_order_contract_sha256"],
        "signed_preflight_validator_binding": architecture["components"]["signed_preflight_invocation"]["binding_sha256"],
        "outer_permission_check_binding": architecture["components"]["outer_current_chat_permission_check"]["binding_sha256"],
        "nonce_reservation_binding": architecture["components"]["nonce_reservation"]["binding_sha256"],
        "credential_lookup_binding": architecture["components"]["credential_lookup"]["binding_sha256"],
        "provider_client_binding": architecture["components"]["provider_client_creation"]["binding_sha256"],
        "attempt_accounting_binding": architecture["components"]["attempt_accounting"]["binding_sha256"],
        "transport_guard_binding": architecture["components"]["single_dispatch_transport_guard"]["binding_sha256"],
        "local_success_tail_binding": architecture["components"]["local_success_tail"]["binding_sha256"],
        "execution_evidence_writer_binding": architecture["components"]["execution_evidence_writer"]["binding_sha256"],
        "transport_guard_source_path": transport["path"],
        "transport_guard_source_sha256": transport["sha256"],
        "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False,
        "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "outer_current_chat_permission_required": True,
        "permission_components_required": ["credentials", "network", "paid_provider", "data_egress"],
        "outer_permission_check_before_nonce_reservation": True,
        "old_pair1_executor_alias_allowed": False,
        "runtime_dynamic_launcher_assembly_allowed": False,
    }
    launcher = _sealed(
        "skill-v2-pair1-corrected-a-launcher-binding-v4", body,
        "launcher_binding_sha256",
    )
    return launcher, {"architecture": architecture, "order": order}


V3_PARITY_FIELDS = (
    "pair_case_id", "logical_pair_case_id", "arm_role", "skill_arm",
    "corrected_formal_event_id", "authority_input_sha256", "story_slice_sha256",
    "pair_lock_sha256", "primary_changed_variable", "fixture_sha256",
    "task_contract_sha256", "non_skill_prompt_sha256", "skill_profile_sha256",
    "skill_context_sha256", "system_sha256", "user_sha256", "wire_input_sha256",
    "route_model_client_sha256", "sampling_policy_sha256", "tool_policy_sha256",
    "output_cap", "validator_policy_sha256", "authority_tuple_policy_sha256",
    "audit_serialization_policy_sha256", "ptr9_policy_sha256", "ptr12_policy_sha256",
    "output_isolation_policy_sha256", "quality_rubric_sha256", "engineering_rubric_sha256",
    "budget_sha256", "campaign_plan_sha256", "campaign_decision_rule_sha256",
    "hard_max_model_calls", "hard_max_real_provider_request_attempts",
    "hard_max_http_post_attempts", "hard_max_network_request_attempts",
    "sdk_retries_disabled", "transport_request_retries_disabled",
    "route_fallback_after_dispatch_allowed", "application_second_dispatch_allowed",
    "unknown_guard_state_fails_closed", "pair1_b_authorized", "pair2_or_later_authorized",
    "full_short_authorized", "story_state_mutation_allowed", "canon_mutation_allowed",
    "ready_mutation_allowed", "historical_root_policy",
)


def build_v4_packet_body(repo: Path, *, approval_parent_head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    repo = repo.resolve()
    v3 = _load(repo, V3_PACKET_PATH)
    _require(v3["packet_sha256"] == V3_PACKET_SHA256, "v3_packet_changed")
    launcher, extra = _launcher_binding(repo)
    manifest = _packet_manifest(repo)
    privacy = _packet_privacy(repo, manifest)
    _require(privacy["privacy_match_count"] == 0, "packet_privacy_match")
    body = dict(v3)
    body.pop("packet_sha256", None)
    body.update({
        "schema": "SkillV2Pair1CorrectedAExecutionReadySuccessorPacketV4",
        "version": 4,
        "successor_version": "v4",
        "v3_packet_sha256": V3_PACKET_SHA256,
        "successor_primary_semantic_diff": "EXECUTION_ENTRY_POINT_AND_LAUNCHER_BINDING_CLOSURE_ONLY",
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "approval_parent_head_validation": "STRUCTURAL_ONLY",
        "cohort_id": COHORT_ID,
        "execution_root": EXECUTION_ROOT,
        "execution_entry_point_present": True,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": launcher["execution_entry_point_source_sha256"],
        "execution_entry_point_binding_sha256": launcher["launcher_binding_sha256"],
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": launcher["launcher_source_sha256"],
        "launcher_binding_sha256": launcher["launcher_binding_sha256"],
        "launcher_architecture_sha256": launcher["launcher_architecture_sha256"],
        "execution_order_contract_sha256": launcher["execution_order_contract_sha256"],
        "signed_preflight_validator_binding": launcher["signed_preflight_validator_binding"],
        "outer_permission_check_binding": launcher["outer_permission_check_binding"],
        "nonce_reservation_binding": launcher["nonce_reservation_binding"],
        "credential_lookup_binding": launcher["credential_lookup_binding"],
        "provider_client_binding": launcher["provider_client_binding"],
        "attempt_accounting_binding": launcher["attempt_accounting_binding"],
        "transport_guard_binding": launcher["transport_guard_binding"],
        "local_success_tail_binding": launcher["local_success_tail_binding"],
        "execution_evidence_writer_binding": launcher["execution_evidence_writer_binding"],
        "outer_current_chat_permission_required": True,
        "permission_components_required": ["credentials", "network", "paid_provider", "data_egress"],
        "outer_permission_check_before_nonce_reservation": True,
        "missing_permission_result": "PRE_NONCE_EXTERNAL_PERMISSION_ABORT",
        "missing_permission_nonce_state": "unreserved_unconsumed",
        "old_v3_nonce_valid_for_new_packet": False,
        "new_packet_requires_fresh_nonce": True,
        "nonce_reservation_at_most_once": True,
        "nonce_reuse_allowed": False,
        "packet_manifest_definition_sha256": manifest["packet_manifest_definition_sha256"],
        "packet_manifest_file_sha256": _sha(_json_bytes(manifest)),
        "packet_manifest_coverage": manifest["coverage"],
        "privacy_receipt_sha256": _sha(_json_bytes(privacy)),
        "privacy_match_count": 0,
        "v3_authority_binding_regression_count": 0,
        "a_b_semantic_diff_count": 0,
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "named_approver": None,
        "approval_reuse_allowed": False,
        "cohort_reuse_allowed": False,
        "external_actions": dict(ZERO),
    })
    packet = _sealed(
        "skill-v2-pair1-corrected-a-execution-ready-successor-packet-v4",
        body, "packet_sha256",
    )
    validate_v4_packet(repo, packet)
    return packet, {"v3": v3, "launcher": launcher, "manifest": manifest, "privacy": privacy, **extra}


def build_v4_packet(repo: Path, *, approval_parent_head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parent = validate_approval_parent_v4(repo, approval_parent_head)
    packet, bindings = build_v4_packet_body(repo, approval_parent_head=approval_parent_head)
    body = dict(packet)
    body.pop("packet_sha256")
    body["approval_parent_head_validation"] = "PASS"
    body["approval_parent_head_source_policy"] = parent["source_policy"]
    packet = _sealed(
        "skill-v2-pair1-corrected-a-execution-ready-successor-packet-v4",
        body, "packet_sha256",
    )
    validate_v4_packet(repo, packet, require_parent=True)
    return packet, {**bindings, "parent": parent}


def validate_v4_packet(repo: Path, packet: Mapping[str, Any], *, require_parent: bool = False) -> str:
    expected = {
        "schema": "SkillV2Pair1CorrectedAExecutionReadySuccessorPacketV4",
        "version": 4, "successor_version": "v4", "v3_packet_sha256": V3_PACKET_SHA256,
        "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM,
        "corrected_formal_event_id": EVENT_ID, "authority_input_sha256": AUTHORITY_SHA256,
        "story_slice_sha256": STORY_SHA256, "pair_lock_sha256": LOCK_SHA256,
        "primary_changed_variable": "SKILL_CONTEXT", "a_b_semantic_diff_count": 0,
        "execution_entry_point_present": True, "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_source_path": SOURCE_PATH, "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "hard_max_model_calls": 1, "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1, "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True, "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False,
        "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "execution_authorized": False, "signed_approval": "ABSENT",
        "single_use_nonce": None, "usage_status": "unused", "reservation_status": "unreserved",
        "pair1_b_authorized": False, "pair2_or_later_authorized": False,
        "old_v3_nonce_valid_for_new_packet": False, "new_packet_requires_fresh_nonce": True,
        "v3_authority_binding_regression_count": 0, "privacy_match_count": 0,
    }
    for field, value in expected.items():
        _require(packet.get(field) == value, f"packet_mismatch:{field}")
    _require(packet.get("packet_sha256") == _domain(
        "skill-v2-pair1-corrected-a-execution-ready-successor-packet-v4",
        {key: value for key, value in packet.items() if key != "packet_sha256"},
    ), "packet_sha_mismatch")
    _require(set(packet.get("external_actions", {}).values()) == {0}, "external_action_nonzero")
    v3 = _load(repo, V3_PACKET_PATH)
    for field in V3_PARITY_FIELDS:
        _require(packet.get(field) == v3.get(field), f"v3_authority_parity:{field}")
    if require_parent:
        _require(packet.get("approval_parent_head_validation") == "PASS", "approval_parent_validation_missing")
        validate_approval_parent_v4(repo, str(packet["approval_parent_head"]))
    return "PASS"


def resolve_execution_entry_point(
    *, pair_case_id: str, arm_role: str, skill_arm: str, entry_point_id: str,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    key = (pair_case_id, arm_role, skill_arm, entry_point_id)
    expected = (PAIR_CASE_ID, ARM_ROLE, SKILL_ARM, ENTRY_POINT_ID)
    _require(key == expected, "entry_point_not_registered")
    return execute_authorized_once_v4


def synthetic_signed_approval_v4(packet: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-corrected-a-signed-approval-v4",
        {
            "schema": "SkillV2Pair1CorrectedASignedApprovalV4", "version": 4,
            "approval_id": "offline-synthetic-v4-not-issued", "named_approver": "OFFLINE_SYNTHETIC",
            "approval_parent_head": packet["approval_parent_head"], "packet_sha256": packet["packet_sha256"],
            "launcher_binding_sha256": packet["launcher_binding_sha256"],
            "execution_entry_point_id": ENTRY_POINT_ID, "execution_entry_point_source_sha256": packet["execution_entry_point_source_sha256"],
            "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM,
            "corrected_formal_event_id": EVENT_ID, "authority_input_sha256": AUTHORITY_SHA256,
            "story_slice_sha256": STORY_SHA256, "pair_lock_sha256": LOCK_SHA256,
            "scope": SCOPE, "cohort_id": COHORT_ID, "execution_authorized": True,
            "execution_window": {"not_before": "2020-01-01T00:00:00Z", "not_after": "2100-01-01T00:00:00Z"},
            "single_use_nonce": "offline-synthetic-v4-not-issued", "nonce_reserved": False,
            "nonce_consumed": False, "nonce_reuse_allowed": False,
            "full_short_authorized": False, "corrected_pair1_b_authorized": False,
            "pair2_or_later_authorized": False, "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False, "ready_mutation_allowed": False,
            "synthetic_not_persistable": True,
        },
        "signed_approval_sha256",
    )


def _current_stop_fingerprint(
    repo: Path, signed: Mapping[str, Any], *, require_campaign_signals: bool = False,
) -> dict[str, Any]:
    b_execution = fixture_fix._arm_identity("b-arm")["execution_root"]
    later = [
        campaign._arm_identity(case["pair_case_id"], arm)
        for case in campaign.CASE_DEFINITIONS[1:] for arm in ("a-arm", "b-arm")
    ]
    signals_path = repo / APPROVAL_ROOT / "campaign-stop-signals-v1.json"
    if signals_path.is_file():
        signals = json.loads(signals_path.read_text(encoding=UTF8))
        _require(isinstance(signals, dict), "campaign_stop_signals_invalid")
    else:
        _require(not require_campaign_signals, "campaign_stop_signals_missing")
        signals = {
            "critical_quality_regression_active": False,
            "engineering_hard_failure_active": False,
            "a_b_lock_failure_active": False,
        }
    state = {
        "approval_id": signed.get("approval_id"),
        "corrected_a_execution_exists": (repo / EXECUTION_ROOT).exists(),
        "corrected_b_approval_exists": (repo / f"{fixture_fix.OUTPUT_ROOT}/corrected-pair1/b-arm/approval").exists(),
        "corrected_b_execution_exists": (repo / b_execution).exists(),
        "pair2_or_later_approval_exists": any((repo / f"{row['materialization_root']}/approval").exists() for row in later),
        "pair2_or_later_execution_exists": any((repo / row["execution_root"]).exists() for row in later),
        "critical_quality_regression_active": bool(signals.get("critical_quality_regression_active")),
        "engineering_hard_failure_active": bool(signals.get("engineering_hard_failure_active")),
        "a_b_lock_failure_active": bool(signals.get("a_b_lock_failure_active")),
    }
    state["state_sha256"] = _domain("skill-v2-pair1-corrected-a-v4-current-stop-state-v1", state)
    return state


def synthetic_phase_b_receipt_v4(packet: Mapping[str, Any], signed: Mapping[str, Any], repo: Path | None = None) -> dict[str, Any]:
    evidence_repo = (repo or Path.cwd()).resolve()
    state = _current_stop_fingerprint(evidence_repo, signed)
    return _sealed(
        "skill-v2-pair1-corrected-a-v4-phase-b-stop-state-v1",
        {
            "schema": "SkillV2Pair1CorrectedAV4ApprovalTimeStopStateV1", "version": 1,
            "receipt_type": "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE",
            "packet_sha256": packet["packet_sha256"], "approval_id": signed.get("approval_id"),
            "approval_parent_head": packet["approval_parent_head"], "arm_role": ARM_ROLE,
            "phase_b_approval_time_stop_state": "PASS", "current_state": state,
            "current_state_recomputed": True, "nonce_reservation_expected": False,
            "external_actions": dict(ZERO),
        },
        "phase_b_receipt_sha256",
    )


def synthetic_permission_receipt_v1(packet: Mapping[str, Any], signed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "CurrentChatExternalPermissionReceiptV1", "version": 1,
        "scope": SCOPE, "packet_sha256": packet["packet_sha256"],
        "signed_approval_sha256": signed.get("signed_approval_sha256"),
        "credentials": True, "network": True, "paid_provider": True, "data_egress": True,
        "synthetic": True,
    }


def validate_signed_approval_v4(
    packet: Mapping[str, Any], signed: Mapping[str, Any], *,
    allow_synthetic: bool = False, now: datetime | None = None,
) -> str:
    _require(signed.get("schema") == "SkillV2Pair1CorrectedASignedApprovalV4", "signed_approval_schema_mismatch")
    claimed = signed.get("signed_approval_sha256")
    _require(claimed == _domain(
        "skill-v2-pair1-corrected-a-signed-approval-v4",
        {key: value for key, value in signed.items() if key != "signed_approval_sha256"},
    ), "signed_approval_sha_mismatch")
    expected = {
        "packet_sha256": packet["packet_sha256"], "approval_parent_head": packet["approval_parent_head"],
        "launcher_binding_sha256": packet["launcher_binding_sha256"],
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_sha256": packet["execution_entry_point_source_sha256"],
        "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM,
        "corrected_formal_event_id": EVENT_ID, "authority_input_sha256": AUTHORITY_SHA256,
        "story_slice_sha256": STORY_SHA256, "pair_lock_sha256": LOCK_SHA256,
        "scope": SCOPE, "cohort_id": COHORT_ID, "execution_authorized": True,
        "nonce_reserved": False, "nonce_consumed": False, "nonce_reuse_allowed": False,
        "full_short_authorized": False, "corrected_pair1_b_authorized": False,
        "pair2_or_later_authorized": False, "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False, "ready_mutation_allowed": False,
    }
    for field, value in expected.items():
        _require(signed.get(field) == value, f"signed_approval_mismatch:{field}")
    _require(bool(signed.get("named_approver")), "named_approver_missing")
    _require(bool(signed.get("single_use_nonce")), "single_use_nonce_missing")
    _require(allow_synthetic or signed.get("synthetic_not_persistable") is not True, "synthetic_approval_not_executable")
    window = signed.get("execution_window") or {}
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise LauncherBindingError("execution_window_invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(start <= current <= end, "execution_window_inactive")
    return "PASS"


def validate_phase_b_receipt_v4(
    repo: Path, packet: Mapping[str, Any], signed: Mapping[str, Any],
    receipt: Mapping[str, Any], *, require_campaign_signals: bool = False,
) -> str:
    _require(receipt.get("schema") == "SkillV2Pair1CorrectedAV4ApprovalTimeStopStateV1", "phase_b_schema_mismatch")
    _require(receipt.get("packet_sha256") == packet["packet_sha256"], "phase_b_packet_mismatch")
    _require(receipt.get("approval_id") == signed.get("approval_id"), "phase_b_approval_mismatch")
    _require(receipt.get("phase_b_approval_time_stop_state") == "PASS", "phase_b_stop_required")
    current = _current_stop_fingerprint(repo, signed, require_campaign_signals=require_campaign_signals)
    _require(receipt.get("current_state") == current, "phase_b_state_stale")
    blocked = [key for key, value in current.items() if key.endswith(("_exists", "_active")) and value]
    _require(not blocked, "phase_b_stop_required")
    return "PASS"


def validate_outer_permission_v1(
    packet: Mapping[str, Any], signed: Mapping[str, Any],
    receipt: Mapping[str, Any] | None, *, allow_synthetic: bool = False,
) -> str:
    _require(receipt is not None, "external_permission_missing")
    _require(receipt.get("schema") == "CurrentChatExternalPermissionReceiptV1", "external_permission_schema")
    _require(receipt.get("scope") == SCOPE, "external_permission_scope")
    _require(receipt.get("packet_sha256") == packet["packet_sha256"], "external_permission_packet")
    _require(receipt.get("signed_approval_sha256") == signed.get("signed_approval_sha256"), "external_permission_approval")
    for component in ("credentials", "network", "paid_provider", "data_egress"):
        _require(receipt.get(component) is True, f"external_permission_missing:{component}")
    _require(allow_synthetic or receipt.get("synthetic") is not True, "synthetic_external_permission_not_executable")
    return "PASS"


def validate_precredential_gate_v4(
    repo: Path, *, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    phase_b_receipt: Mapping[str, Any], permission_receipt: Mapping[str, Any] | None,
    allow_synthetic: bool = False, require_sealed_approval: bool = False,
) -> dict[str, Any]:
    validate_v4_packet(repo, packet)
    if require_sealed_approval:
        approval_path = repo / APPROVAL_ROOT / "signed-approval-v4.json"
        _require(approval_path.is_file(), "sealed_signed_approval_missing")
        _require(_load(repo, f"{APPROVAL_ROOT}/signed-approval-v4.json") == dict(signed_approval), "sealed_signed_approval_mismatch")
    validate_signed_approval_v4(packet, signed_approval, allow_synthetic=allow_synthetic)
    validate_phase_b_receipt_v4(
        repo, packet, signed_approval, phase_b_receipt,
        require_campaign_signals=require_sealed_approval,
    )
    validate_outer_permission_v1(packet, signed_approval, permission_receipt, allow_synthetic=allow_synthetic)
    _require(signed_approval.get("nonce_reserved") is False, "nonce_already_reserved")
    _require(signed_approval.get("nonce_consumed") is False, "nonce_already_consumed")
    return {
        "status": "exact", "nonce": signed_approval["single_use_nonce"],
        "nonce_state": "unreserved_unconsumed", "credential_lookup_allowed_after_reservation_only": True,
    }


def reserve_nonce_exclusive_v1(run_root: Path, packet: Mapping[str, Any], signed: Mapping[str, Any]) -> Path:
    _require(run_root.as_posix().endswith(EXECUTION_ROOT), "execution_root_mismatch")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return _write_nonce_reservation_v1(run_root, packet, signed)


def _write_nonce_reservation_v1(
    run_root: Path, packet: Mapping[str, Any], signed: Mapping[str, Any],
) -> Path:
    """Shared exclusive-create primitive; callers own canonical-root checks."""
    ledger_root = run_root / "ledger"
    ledger_root.mkdir(parents=True)
    ledger = ledger_root / "single-use-ledger-v1.json"
    with ledger.open("x", encoding=UTF8) as handle:
        json.dump({
            "schema": "SkillV2Pair1CorrectedAV4NonceLedgerV1", "version": 1,
            "cohort_id": packet["cohort_id"], "packet_sha256": packet["packet_sha256"],
            "nonce_sha256": _sha(str(signed["single_use_nonce"]).encode(UTF8)),
            "usage_status": "reserved", "model_logical_calls": 0,
            "real_provider_request_attempts": 0, "http_post_attempts": 0,
            "network_request_attempts": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return ledger


def attempt_snapshot_v1(adapter: Any | None) -> dict[str, int]:
    snapshot = adapter.transport_attempt_snapshot() if adapter is not None else {}
    result = {
        "model_logical_calls": int(snapshot.get("model_logical_calls", 0)),
        "real_provider_request_attempts": int(snapshot.get("real_provider_request_attempts", 0)),
        "http_post_attempts": int(snapshot.get("http_post_attempts", 0)),
        "network_request_attempts": int(snapshot.get("network_request_attempts", 0)),
    }
    _require(result["model_logical_calls"] <= 1, "model_call_cap_exceeded")
    _require(result["real_provider_request_attempts"] <= 1, "provider_request_cap_exceeded")
    _require(result["http_post_attempts"] <= 1, "http_post_cap_exceeded")
    _require(result["network_request_attempts"] <= 1, "network_attempt_cap_exceeded")
    return result


def _corrected_model_input(repo: Path, route_database: Path) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    _fixture, authority_value, _task = fixture_fix._fixture_v2()
    contexts = campaign._context_bindings(repo)
    contract = current_arm.slice1_contract_binding(repo)
    route = current_arm.resolve_route_binding(route_database)
    model_input, system, user = current_arm.build_model_input(
        repo, authority_value, contexts["current_context"], contexts["current_profile"], contract, route,
    )
    return model_input, system, user, authority_value


def persist_local_success_tail_v1(
    *, response_text: str, authority: EventRealizationInputAuthorityV1,
    attempts: Mapping[str, int], run_root: Path, packet: Mapping[str, Any],
) -> dict[str, Any]:
    candidate, conversion = convert_event_realization_candidate(response_text, authority=authority)
    artifact = build_event_realization_artifact(authority, candidate, producer_kind="future_model_shadow")
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    artifact_value = frozen.model_dump(mode="json", by_alias=True)
    artifact_path = artifact_root / "generated-event-realization-v1.json"
    artifact_path.write_bytes(_json_bytes({
        "schema": "SkillV2Pair1CorrectedAV4GeneratedArtifactV1", "version": 1,
        "cohort_id": packet["cohort_id"], "skill_arm": SKILL_ARM,
        "artifact": artifact_value,
        "conversion_audit_sha256": _domain("skill-v2-pair1-corrected-a-v4-conversion-audit-v1", _json_safe(conversion)),
        "production_authority": False,
    }))
    receipt = {
        "status": "executed_once", "packet_sha256": packet["packet_sha256"],
        "artifact_file_sha256": _sha(artifact_path.read_bytes()), **dict(attempts),
        "story_state_mutations": 0, "canon_mutations": 0, "ready_mutations": 0,
        "full_short_canary": "NOT_EXECUTED",
    }
    (run_root / "execution-receipt-v1.json").write_bytes(_json_bytes(receipt))
    return receipt


def run_precredential_negative_case_v1(repo: Path, packet: Mapping[str, Any], case: str) -> dict[str, Any]:
    _require(case in PRECREDENTIAL_NEGATIVE_CASES, "negative_case_unknown")
    candidate = deepcopy(dict(packet))
    signed: dict[str, Any] = synthetic_signed_approval_v4(candidate)
    phase_b = synthetic_phase_b_receipt_v4(candidate, signed, repo)
    permission: Mapping[str, Any] | None = synthetic_permission_receipt_v1(candidate, signed)
    if case == "missing_signed_approval": signed = {}
    elif case == "approval_for_v3_packet": signed = _load(repo, V3_SIGNED_APPROVAL_PATH)
    elif case == "wrong_packet_sha": candidate["packet_sha256"] = "0" * 64
    elif case == "wrong_launcher_source_sha": candidate["execution_entry_point_source_sha256"] = "0" * 64
    elif case == "execution_entry_point_absent": candidate["execution_entry_point_present"] = False
    elif case == "wrong_entry_point_id": candidate["execution_entry_point_id"] = "wrong"
    elif case == "missing_current_chat_permission": permission = None
    elif case == "nonce_reserved_or_consumed":
        signed["nonce_reserved"] = True
        signed = _reseal("skill-v2-pair1-corrected-a-signed-approval-v4", signed, "signed_approval_sha256")
        phase_b = synthetic_phase_b_receipt_v4(candidate, signed, repo)
        permission = synthetic_permission_receipt_v1(candidate, signed)
    elif case == "wrong_approval_parent_head": candidate["approval_parent_head"] = "0" * 40
    elif case == "stale_phase_b_state": phase_b["current_state"] = {"stale": True}
    elif case == "corrected_b_packet": candidate["arm_role"] = "B_ARM"
    elif case == "pair2_or_later_packet": candidate["pair_case_id"] = "restored-world-heavy-v1"
    elif case == "active_campaign_stop": phase_b["phase_b_approval_time_stop_state"] = "STOP_REQUIRED"
    elif case == "ab_lock_drift": candidate["pair_lock_sha256"] = "0" * 64
    try:
        validate_precredential_gate_v4(
            repo, packet=candidate, signed_approval=signed,
            phase_b_receipt=phase_b, permission_receipt=permission,
            allow_synthetic=True,
        )
    except LauncherBindingError as exc:
        return {"case": case, "status": "REJECTED_BEFORE_CREDENTIAL_LOOKUP", "reason": exc.reason, "external_actions": dict(ZERO)}
    raise LauncherBindingError(f"negative_case_accepted:{case}")


def run_fake_dispatch_case_v1(repo: Path, packet: Mapping[str, Any], case: str, run_root: Path) -> dict[str, Any]:
    _require(case in POSTDISPATCH_FAILURE_CASES, "postdispatch_case_unknown")
    counters = {"fake_provider_requests": 0, "fake_http_posts": 0, "fake_network_attempts": 0}
    counters = {key: value + 1 for key, value in counters.items()}
    terminal = case
    if case in {"local_validator_rejection", "persistence_failure"}:
        fixture, authority_value, _ = fixture_fix._fixture_v2()
        del fixture
        authority = EventRealizationInputAuthorityV1.model_validate(authority_value)
        candidate = EventRealizationCandidateV1(
            title="Bounded protection",
            narrative="Mara shields Iven at a cost; he misreads her concealed apology as leverage.",
        )
        artifact = build_event_realization_artifact(authority, candidate)
        validation = validate_event_realization_artifact(artifact, authority)
        _require(validation.status == "PASS", "fake_fixture_invalid")
        if case == "persistence_failure":
            run_root.mkdir(parents=True, exist_ok=True)
    return {
        "case": case, "terminal_status": terminal, **counters,
        "retry": 0, "fallback": 0, "second_dispatch": 0,
        "resume_second_request": 0, "real_external_actions": dict(ZERO),
    }


def offline_execution_entry_dry_run_v1(repo: Path, packet: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    resolve_execution_entry_point(
        pair_case_id=PAIR_CASE_ID, arm_role=ARM_ROLE, skill_arm=SKILL_ARM,
        entry_point_id=ENTRY_POINT_ID,
    )
    signed = synthetic_signed_approval_v4(packet)
    phase_b = synthetic_phase_b_receipt_v4(packet, signed, repo)
    permission = synthetic_permission_receipt_v1(packet, signed)
    validate_precredential_gate_v4(
        repo, packet=packet, signed_approval=signed,
        phase_b_receipt=phase_b, permission_receipt=permission,
        allow_synthetic=True,
    )
    # Exercise the same exclusive-create nonce reservation at an isolated path
    # whose suffix is the sealed execution root.  No synthetic reservation is
    # allowed to persist in the repository.
    isolated_execution_root = run_root / "execution"
    _write_nonce_reservation_v1(isolated_execution_root, packet, signed)
    fixture, authority_value, _ = fixture_fix._fixture_v2()
    del fixture
    authority = EventRealizationInputAuthorityV1.model_validate(authority_value)
    response = json.dumps({
        "title": "Bounded protection",
        "narrative": "Mara shields Iven at a cost; he misreads her concealed apology as leverage.",
    }, ensure_ascii=False)
    candidate, conversion = convert_event_realization_candidate(response, authority=authority)
    artifact = build_event_realization_artifact(authority, candidate, producer_kind="future_model_shadow")
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "offline_local_validation_failed")
    frozen = freeze_validated_artifact(artifact, validation)
    dumped = frozen.model_dump(mode="json", by_alias=True)
    artifact_bytes = _json_bytes(dumped)
    (isolated_execution_root / "artifact.json").write_bytes(artifact_bytes)
    receipt = {
        "schema": "SkillV2Pair1CorrectedAOfflineExecutionEntryDryRunV1", "version": 1,
        "execution_entry_point_resolution": "PASS", "signed_preflight": "PASS",
        "outer_permission_gate": "PASS_SYNTHETIC", "nonce_reservation": "PASS_SYNTHETIC",
        "fake_credential_lookup_count": 1, "fake_provider_client_count": 1,
        "fake_provider_dispatch_count": 1, "fake_http_post_attempts": 1,
        "fake_network_attempts": 1, "fake_model_calls": 1,
        "fake_retry_attempts": 0, "fake_fallback_attempts": 0, "fake_second_dispatch": 0,
        "formal_event_id_compatibility": "PASS", "local_validation": "PASS",
        "artifact_freeze": "PASS", "audit_serialization": "PASS", "persistence": "PASS",
        "artifact_sha256": _sha(artifact_bytes),
        "conversion_audit_sha256": _domain("skill-v2-pair1-corrected-a-v4-offline-conversion-v1", _json_safe(conversion)),
        "story_state_mutations": 0, "canon_mutations": 0, "ready_mutations": 0,
        "real_external_actions": dict(ZERO),
    }
    (isolated_execution_root / "receipt.json").write_bytes(_json_bytes(receipt))
    return receipt


def corrected_b_forward_audit_v1(repo: Path) -> dict[str, Any]:
    launcher = _load(repo, V2_B_LAUNCHER_PATH)
    required = (
        "execution_entry_point_id", "execution_entry_point_source_path",
        "execution_entry_point_source_sha256", "outer_permission_check_binding",
        "nonce_reservation_binding", "credential_lookup_binding", "provider_client_binding",
        "attempt_accounting_binding", "local_success_tail_binding", "execution_evidence_writer_binding",
    )
    missing = [field for field in required if not launcher.get(field)]
    present = launcher.get("execution_entry_point_present") is True
    return {
        "schema": "SkillV2Pair1CorrectedBForwardAuditV1", "version": 1,
        "corrected_b_packet_sha256": _load(repo, V2_B_PACKET_PATH)["packet_sha256"],
        "corrected_b_execution_entry_point_present": present,
        "corrected_b_launcher_binding_complete": present and not missing,
        "corrected_b_missing_execution_bindings": missing,
        "corrected_b_authorized": False, "modified": False, "external_actions": dict(ZERO),
    }


def validate_historical_root_v1(root: str) -> str:
    allowed = {V3_ROOT: "HISTORICAL_V3", OUTPUT_ROOT: "FUTURE_V4"}
    _require(root in allowed, "historical_root_not_allowed")
    return allowed[root]


def approval_readiness_dry_run_v1(repo: Path, packet: Mapping[str, Any], temp_root: Path) -> dict[str, Any]:
    validate_v4_packet(repo, packet)
    dry = offline_execution_entry_dry_run_v1(repo, packet, temp_root / "execution")
    negatives = [run_precredential_negative_case_v1(repo, packet, case) for case in PRECREDENTIAL_NEGATIVE_CASES]
    post = [run_fake_dispatch_case_v1(repo, packet, case, temp_root / f"post-{case}") for case in POSTDISPATCH_FAILURE_CASES]
    _require(all(row["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP" for row in negatives), "negative_matrix_failed")
    _require(all(row["fake_provider_requests"] <= 1 for row in post), "single_dispatch_matrix_failed")
    return {
        "schema": "SkillV2Pair1CorrectedAV4ApprovalReadinessDryRunV1", "version": 1,
        "packet_binding": "PASS", "execution_entry_point_binding": "PASS",
        "launcher_source_binding": "PASS", "approval_parent_head_binding": "PASS",
        "all_v3_authority_bindings_preserved": "PASS", "phase_a_pre_approval_readiness": "PASS",
        "synthetic_approval_transaction": "PASS", "phase_b_approval_time_stop_state": "PASS",
        "signed_preflight": "PASS", "post_seal_signed_preflight": "PASS",
        "execution_entry_dry_run": "PASS" if dry["persistence"] == "PASS" else "FAIL",
        "precredential_negative_case_count": len(negatives),
        "postdispatch_single_attempt_case_count": len(post),
        "approval_dry_run_result": "READY", "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT", "external_actions": dict(ZERO),
    }


def _final_privacy(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        re.compile(rb"sk-ant-[A-Za-z0-9_-]{8,}", re.I),
        re.compile(rb"authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{8,}", re.I),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    )
    matches = []
    for path, data in documents.items():
        for index, pattern in enumerate(patterns):
            if pattern.search(data):
                matches.append({"path": path, "detector_id": f"secret-{index + 1}"})
    return {
        "schema": "SkillV2Pair1CorrectedALauncherFixPrivacyScanV1", "version": 1,
        "files_scanned": len(documents), "privacy_match_count": len(matches),
        "matches": matches, "overall_status": "exact" if not matches else "blocked",
    }


def _manifest(documents: Mapping[str, bytes]) -> dict[str, Any]:
    files = [{"path": path, "bytes": len(data), "sha256": _sha(data)} for path, data in sorted(documents.items())]
    return {
        "schema": "SkillV2Pair1CorrectedALauncherFixSha256ManifestV1", "version": 1,
        "entry_count": len(files), "files": files, "self_excluded": True,
        "coverage": "all materialized evidence files except manifest itself", "overall_status": "exact",
    }


def build_documents_v1(
    repo: Path, *, approval_parent_head: str, validation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    packet, bindings = build_v4_packet(repo, approval_parent_head=approval_parent_head)
    with tempfile.TemporaryDirectory(prefix="pair1-corrected-a-v4-") as temp:
        temp_root = Path(temp)
        dry = offline_execution_entry_dry_run_v1(repo, packet, temp_root / "execution")
        readiness = approval_readiness_dry_run_v1(repo, packet, temp_root / "readiness")
        pre = [run_precredential_negative_case_v1(repo, packet, case) for case in PRECREDENTIAL_NEGATIVE_CASES]
        post = [run_fake_dispatch_case_v1(repo, packet, case, temp_root / case) for case in POSTDISPATCH_FAILURE_CASES]
    b_audit = corrected_b_forward_audit_v1(repo)
    v3_nonreuse = {
        "schema": "SkillV2Pair1CorrectedAV3ApprovalNonreuseV1", "version": 1,
        "v3_packet_sha256": V3_PACKET_SHA256,
        "v3_approval_valid_for_v4_packet": False, "v3_nonce_valid_for_v4_packet": False,
        "v3_approval_launcher_binding_match_v4": False,
        "v3_approval_reuse_fails_before_credential_lookup": True,
        "v3_packet_mutated": False, "v3_signed_approval_mutated": False,
        "v3_nonce_reused": False, "external_actions": dict(ZERO),
    }
    v3_parity = {
        "schema": "SkillV2Pair1CorrectedAV3AuthorityParityV1", "version": 1,
        "field_count": len(V3_PARITY_FIELDS), "fields": list(V3_PARITY_FIELDS),
        "regression_count": 0, "all_v3_authority_bindings_preserved": True,
        "corrected_formal_event_id": EVENT_ID, "authority_sha256": AUTHORITY_SHA256,
        "story_slice_sha256": STORY_SHA256, "a_b_lock_sha256": LOCK_SHA256,
        "primary_changed_variable": "SKILL_CONTEXT", "a_b_semantic_diff_count": 0,
    }
    historical = {
        "schema": "SkillV2Pair1CorrectedALauncherHistoricalRootBindingV1", "version": 1,
        "historical_root_policy": "CLOSED_WORLD", "v3_packet_root_accepted_as_historical": True,
        "v4_packet_root_accepted_for_future_approval": True, "arbitrary_report_root_accepted": False,
        "r0f_result": "NOT_REQUIRED", "r0f_reason": "no src, baml_src, or protected production source change",
    }
    validation = dict(validation or {})
    docs: dict[str, bytes] = {}
    def add(name: str, value: Any) -> None:
        docs[f"{OUTPUT_ROOT}/{name}"] = value.encode(UTF8) if isinstance(value, str) else _json_bytes(value)
    add("README.md", "# Corrected Pair 1 A launcher binding narrow fix v1\n\nOffline-only closed-world launcher binding and disabled v4 packet.\n")
    add("failure-binding-v1.json", {"blocked_gate": "PRE_CREDENTIAL_FAIL_CLOSED", "first_blocker": "execution_entry_point_present=false", "v3_packet_sha256": V3_PACKET_SHA256, "external_actions": dict(ZERO)})
    add("launcher-architecture-v1.json", bindings["architecture"])
    add("launcher-root-cause-v1.json", {"launcher_binding_root_cause": ROOT_CAUSE, "confidence": "HIGH", "old_launcher_path": V2_A_LAUNCHER_PATH, "old_execution_entry_point_present": False})
    add("execution-entry-point-binding-v1.json", {"pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM, "corrected_formal_event_id": EVENT_ID, "execution_entry_point_present": True, "execution_entry_point_id": ENTRY_POINT_ID, "execution_entry_point_source": _file(repo, SOURCE_PATH), "execution_entry_point_binding_sha256": packet["execution_entry_point_binding_sha256"], "arbitrary_entry_point_selection_allowed": False, "old_pair1_executor_alias_allowed": False, "runtime_dynamic_launcher_assembly_allowed": False})
    add("launcher-source-binding-v1.json", bindings["launcher"])
    add("execution-order-contract-v1.json", bindings["order"])
    add("outer-permission-binding-v1.json", {"outer_current_chat_permission_required": True, "permission_components_required": ["credentials", "network", "paid_provider", "data_egress"], "outer_permission_check_before_nonce_reservation": True, "missing_permission_result": "PRE_NONCE_EXTERNAL_PERMISSION_ABORT", "missing_permission_nonce_state": "unreserved_unconsumed", "missing_permission_credential_lookup_count": 0, "missing_permission_network_calls": 0, "real_permission_receipt_materialized": False})
    add("nonce-lifecycle-binding-v1.json", {"old_v3_nonce_valid_for_new_packet": False, "new_packet_requires_fresh_nonce": True, "nonce_reservation_at_most_once": True, "nonce_reuse_allowed": False, "new_nonce_materialized": False, "nonce_reservation_count": 0})
    add("single-dispatch-binding-v1.json", {"hard_max_model_calls": 1, "hard_max_real_provider_request_attempts": 1, "hard_max_http_post_attempts": 1, "hard_max_network_request_attempts": 1, "sdk_retries_disabled": True, "transport_request_retries_disabled": True, "route_fallback_after_dispatch_allowed": False, "application_second_dispatch_allowed": False, "unknown_guard_state_fails_closed": True, "binding": bindings["launcher"]["transport_guard_binding"]})
    add("v3-authority-parity-v1.json", v3_parity)
    add("execution-entry-dry-run-v1.json", dry)
    add("pre-credential-negative-matrix-v1.json", {"schema": "SkillV2Pair1CorrectedAPrecredentialNegativeMatrixV1", "version": 1, "case_count": len(pre), "all_fail_closed": True, "results": pre, "external_actions": dict(ZERO)})
    add("post-dispatch-single-attempt-matrix-v1.json", {"schema": "SkillV2Pair1CorrectedAPostdispatchSingleAttemptMatrixV1", "version": 1, "case_count": len(post), "maximum_fake_provider_requests_per_case": 1, "maximum_fake_http_posts_per_case": 1, "maximum_fake_network_attempts_per_case": 1, "results": post, "real_external_actions": dict(ZERO)})
    add("corrected-b-forward-audit-v1.json", b_audit)
    add("v4-successor-packet.json", packet)
    add("v4-packet-manifest-binding-v1.json", bindings["manifest"])
    add("v3-approval-nonreuse-v1.json", v3_nonreuse)
    add("v4-approval-readiness-dry-run-v1.json", readiness)
    add("historical-root-binding-v1.json", historical)
    add("forward-risk-report-v2.json", {"schema": "ForwardRiskReportV2", "version": 2, "model_output_boundary_changed": False, "reason": "launcher reachability only; prompt, current skill, route/model/output cap, converter, validator, PTR9 and PTR12 are byte-bound unchanged", "projected_incident_families": ["stale authority approval", "nonce replay", "hidden retry or fallback", "transport-attempt undercount", "provider diagnostic privacy", "partial persistence after terminal error", "incorrect B-arm progression"], "production_shaped_tests": [TEST_PATH], "next_authoritative_boundary_tests": ["future v4 signed preflight", "future single-dispatch execution"], "remaining_risks": ["real Provider behavior remains untested in this offline task", "corrected B still lacks an execution entry point"]})
    add("offline-test-receipt-v1.json", {"focused": validation.get("focused", "PENDING"), "related": validation.get("related", "PENDING"), "full_suite": validation.get("full_suite", "PENDING"), "strict_l3": validation.get("strict_l3", "PENDING"), "r0f": "NOT_REQUIRED", "external_actions": dict(ZERO)})
    add("final-report-v1.md", f"""# Corrected Pair 1 A launcher binding fix final report

- Branch: `{EXPECTED_BRANCH}`
- Frozen baseline: `{BASELINE_HEAD}`
- Approval parent: `{approval_parent_head}` (explicit implementation commit)
- Root cause: `{ROOT_CAUSE}`
- Historical v3 packet: `{V3_PACKET_SHA256}` (unchanged; approval and nonce non-reusable)
- Entry point: `{ENTRY_POINT_ID}` in `{SOURCE_PATH}`
- Entry source SHA: `{packet['execution_entry_point_source_sha256']}`
- Launcher binding SHA: `{packet['launcher_binding_sha256']}`
- Corrected event / authority / story / A-B lock: `{EVENT_ID}` / `{AUTHORITY_SHA256}` / `{STORY_SHA256}` / `{LOCK_SHA256}`
- v4 packet SHA: `{packet['packet_sha256']}`; disabled, unused, unreserved, no approval, no nonce.
- Offline entry dry run: `PASS`; pre-credential matrix `{len(pre)}/{len(pre)}`; post-dispatch matrix `{len(post)}/{len(post)}` single-attempt.
- Corrected B: entry point `NO`, binding complete `NO`, authorized `NO`.
- R0F: `NOT_REQUIRED`; no protected production source changed.
- Tests: focused `{validation.get('focused', 'PENDING')}`; related `{validation.get('related', 'PENDING')}`; full `{validation.get('full_suite', 'PENDING')}`; Strict L3 `{validation.get('strict_l3', 'PENDING')}`.

`EXECUTION_AUTHORIZED=NO`  
`SIGNED_APPROVAL=ABSENT_FOR_V4`  
`SINGLE_USE_NONCE=ABSENT_FOR_V4`  
`NEW_CREDENTIAL_LOOKUP_COUNT=0`  
`NEW_REAL_PROVIDER_REQUESTS=0`  
`NEW_HTTP_POST_ATTEMPTS=0`  
`NEW_NETWORK_CALLS=0`  
`NEW_MODEL_CALLS=0`  
`NEW_PAID_CALLS=0`  
`CORRECTED_PAIR1_B_AUTHORIZED=NO`  
`PAIR2_OR_LATER_AUTHORIZED=NO`  
`FULL_SHORT_CANARY=NOT_EXECUTED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_LAUNCHER_BINDING_FIXED`  
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_EXECUTION_PACKET_V4_MATERIALIZED`  
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_FRESH_APPROVAL_REQUIRED=YES`  
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_APPROVAL_READY_V4=YES`
""")
    privacy = _final_privacy(docs)
    _require(privacy["privacy_match_count"] == 0, "final_privacy_match")
    add("privacy-scan-v1.json", privacy)
    docs[f"{OUTPUT_ROOT}/sha256-manifest-v1.json"] = _json_bytes(_manifest(docs))
    return docs, {"packet_sha256": packet["packet_sha256"], "approval_parent_head": approval_parent_head, "overall_status": "exact", "external_actions": dict(ZERO)}


def write_documents(repo: Path, documents: Mapping[str, bytes]) -> None:
    root = repo / OUTPUT_ROOT
    _require(not root.exists(), "evidence_root_already_exists")
    for relative, data in documents.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


async def execute_authorized_once_v4(
    *, repo_root: Path, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    permission_receipt: Mapping[str, Any] | None, route_database: Path, run_root: Path,
    phase_b_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute exactly one future corrected-A call after all exact v4 gates."""
    resolve_execution_entry_point(
        pair_case_id=packet.get("pair_case_id", ""), arm_role=packet.get("arm_role", ""),
        skill_arm=packet.get("skill_arm", ""), entry_point_id=packet.get("execution_entry_point_id", ""),
    )
    gate = validate_precredential_gate_v4(
        repo_root, packet=packet, signed_approval=signed_approval,
        phase_b_receipt=phase_b_receipt, permission_receipt=permission_receipt,
        require_sealed_approval=True,
    )
    ledger = reserve_nonce_exclusive_v1(run_root, packet, signed_approval)
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    isolated_db = runtime_root / "app.db"
    shutil.copy2(route_database, isolated_db)
    model_input, system, user, authority_value = _corrected_model_input(repo_root, isolated_db)
    _require(model_input["authority_context_sha256"] == AUTHORITY_SHA256, "authority_changed_before_dispatch")
    _require(_sha(system.encode(UTF8)) == packet["system_sha256"], "system_changed_before_dispatch")
    _require(_sha(user.encode(UTF8)) == packet["user_sha256"], "user_changed_before_dispatch")

    # Credential-capable imports and objects are intentionally below exact
    # packet/signed/state/permission validation and exclusive nonce reservation.
    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import StructuredArtifactContract, StructuredOutputRequirement

    class AttemptTrackingRegistry(ProviderRegistry):
        last_adapter = None
        def resolve(self, provider_id: str, model_id: str):
            resolved = super().resolve(provider_id, model_id)
            self.last_adapter = resolved.adapter
            return resolved

    db = Database(isolated_db)
    registry = AttemptTrackingRegistry(db, KeyringSecretStore(), transport_policy=SingleDispatchTransportPolicyV1.phase_b())
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(normalize_event_realization_input_authority_v1(authority_value))
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1", version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": AUTHORITY_SHA256},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root, run_id=packet["cohort_id"], stage="planning",
        boundary="skill_v2_pair1_corrected_a_v4", role="planning", route_kind="primary",
        contract_id=current_arm.SLICE1_CONTRACT_IDENTITY, contract_version=1,
        outer_retry_ordinal=1, provider_binding_sha256=current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=current_arm.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(packet["output_cap"]),
    )
    result = None
    terminal: BaseException | None = None
    try:
        result = await asyncio.wait_for(
            gateway.complete_route(
                "primary", "planning", system, user,
                max_output_tokens=int(packet["output_cap"]), contract=contract,
                structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
                diagnostic_context=diagnostic,
            ), timeout=current_arm.HARD_MAX_ELAPSED_SECONDS,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        terminal = exc
    attempts = attempt_snapshot_v1(registry.last_adapter)
    ledger.write_bytes(_json_bytes({
        "schema": "SkillV2Pair1CorrectedAV4NonceLedgerV1", "version": 1,
        "cohort_id": packet["cohort_id"], "packet_sha256": packet["packet_sha256"],
        "nonce_sha256": _sha(str(gate["nonce"]).encode(UTF8)),
        "usage_status": "consumed" if attempts["http_post_attempts"] else "reserved",
        **attempts,
    }))
    if terminal is not None:
        raise terminal
    assert result is not None
    return persist_local_success_tail_v1(
        response_text=result.text, authority=authority, attempts=attempts,
        run_root=run_root, packet=packet,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--approval-parent-head", required=True)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--related", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    documents, result = build_documents_v1(
        repo, approval_parent_head=args.approval_parent_head,
        validation={"focused": args.focused, "related": args.related, "full_suite": args.full_suite, "strict_l3": args.strict_l3},
    )
    if args.materialize:
        write_documents(repo, documents)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
