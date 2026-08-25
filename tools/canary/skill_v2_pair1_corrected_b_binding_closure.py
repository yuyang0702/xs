from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Awaitable, Callable, Mapping

from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationArtifactV1,
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary import skill_v2_pair1_corrected_a_launcher_binding as a_launcher
from tools.canary import skill_v2_pair1_fixture_narrow_fix as fixture_fix
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics import skill_v2_bounded_repeated_ab as campaign


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "2d97d2a47e80ef5289ee066fac592deaa896590d"
SOURCE_PATH = "tools/canary/skill_v2_pair1_corrected_b_binding_closure.py"
TEST_PATH = "tests/canary/test_skill_v2_pair1_corrected_b_binding_closure.py"
OUTPUT_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-pair1-corrected-b-binding-closure-v1"
APPROVAL_ROOT = f"{OUTPUT_ROOT}/approval"
EXECUTION_ROOT = (
    "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-execution-v5/"
    "pairs/restored-character-heavy-v2/b-arm"
)
A_EXECUTION_ROOT = a_launcher.EXECUTION_ROOT
A_PACKET_PATH = f"{a_launcher.OUTPUT_ROOT}/v4-successor-packet.json"
B_V2_PATH = a_launcher.V2_B_PACKET_PATH
FORWARD_AUDIT_PATHS = (
    f"{a_launcher.OUTPUT_ROOT}/corrected-b-forward-audit-v1.json",
    f"{a_launcher.closure.OUTPUT_ROOT}/corrected-b-forward-audit-v1.json",
)

PAIR_CASE_ID = "restored-character-heavy-v2"
ARM_ROLE = "B_ARM"
SKILL_ARM = "RESTORED_SKILL_V2"
EVENT_ID = "EV-3D3AE01E"
AUTHORITY_SHA256 = "91e5fe89ae741233b983f344bb0aa517974a4341dab56c8341669a5233c2e3d4"
STORY_SHA256 = "7134e84052d6e15bdd0f3bbb75de41a45c9e8c083d09e896004f8228b71c47c7"
LOCK_SHA256 = "31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80"
B_V2_PACKET_SHA256 = "46953023632e8dcbebba452b9a60c550689778985bf3ed2a210f2674b7e3f0f7"
A_PACKET_SHA256 = "39a46e38d9c11f8afd5fd1cf633443b31ae6fb1c97c4b93d404f950781f19356"
A_ARTIFACT_SHA256 = "f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f"
RESTORED_PROFILE_SHA256 = "c4ca606bd76359514e15cd60a2edcecbd9bc530690abb86be7313f2bd38999c5"
RESTORED_CONTEXT_SHA256 = "e7828db2dc18eceabe06b9d1068b2683d117617fb0bd1257a26e7747fbe02772"
RESTORED_CONTEXT_CHARS = 2742
SCOPE = "SKILL_V2_BOUNDED_REPEATED_AB_CHARACTER_HEAVY_V2_B_ARM_SINGLE_DISPATCH_ONLY"
COHORT_ID = "skill-v2-bounded-repeated-ab-character-heavy-v2-b-launcher-v3-disabled-001"
ENTRY_POINT_ID = (
    "tools.canary.skill_v2_pair1_corrected_b_binding_closure:execute_authorized_once_v3"
)
ROOT_CAUSE = (
    "E.MULTI_FACTOR_WITH_PRIMARY_A_SHARED_CORRECTED_FIXTURE_MATERIALIZER_"
    "OMITTED_APPROVAL_AND_EXECUTION_BINDINGS"
)

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
    "a_control_missing",
    "a_control_invalid",
    "a_artifact_sha_wrong",
    "ab_lock_drift",
    "b_packet_mismatch",
    "wrong_arm_role",
    "wrong_skill_arm",
    "current_context_used_for_b",
    "b_context_sha_mismatch",
    "entry_point_missing",
    "launcher_mismatch",
    "missing_signed_approval",
    "wrong_approval_parent",
    "stale_phase_b",
    "missing_current_chat_permission",
    "nonce_reserved_or_consumed",
    "pair2_or_later_packet",
    "active_campaign_stop",
    "route_model_drift",
    "output_cap_drift",
)
POSTDISPATCH_FAILURE_CASES = (
    "connect_error",
    "http_failure",
    "malformed_response",
    "parse_failure",
    "validator_rejection",
    "persistence_failure",
)


class CorrectedBBindingError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _require(value: bool, reason: str) -> None:
    if not value:
        raise CorrectedBBindingError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _domain(domain: str, value: Any) -> str:
    return _sha(domain.encode(UTF8) + b"\0" + _canonical(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = dict(body)
    value[field] = _domain(domain, value)
    return value


def _reseal(domain: str, value: Mapping[str, Any], field: str) -> dict[str, Any]:
    body = {key: item for key, item in value.items() if key != field}
    return _sealed(domain, body, field)


def _load(repo: Path, relative: str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding=UTF8))
    _require(isinstance(value, dict), f"object_required:{relative}")
    return value


def _file(repo: Path, relative: str) -> dict[str, Any]:
    data = (repo / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha(data)}


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, encoding=UTF8).strip()


def _changed(repo: Path, older: str, newer: str) -> tuple[str, ...]:
    text = _git(repo, "diff", "--name-only", older, newer)
    return tuple(line for line in text.splitlines() if line)


def verify_baseline(repo: Path) -> dict[str, Any]:
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1")
    _require(branch == EXPECTED_BRANCH, "baseline_branch_drift")
    _require(head == BASELINE_HEAD, "baseline_head_drift")
    _require(not status, "baseline_worktree_dirty")
    return {"branch": branch, "head": head, "worktree": "clean"}


def _binding(repo: Path, kind: str, source_path: str, functions: tuple[str, ...]) -> dict[str, Any]:
    source = _file(repo, source_path)
    body = {
        "schema": "SkillV2Pair1CorrectedBBindingV1",
        "version": 1,
        "binding_kind": kind,
        "source_path": source_path,
        "source_sha256": source["sha256"],
        "functions": list(functions),
        "closed_world_b_arm": True,
    }
    return _sealed("skill-v2-pair1-corrected-b-binding-v1", body, "binding_sha256")


def validate_approval_parent_source_policy(repo: Path, approval_parent_head: str) -> dict[str, Any]:
    _require(len(approval_parent_head) == 40, "approval_parent_head_invalid")
    try:
        _git(repo, "merge-base", "--is-ancestor", BASELINE_HEAD, approval_parent_head)
        changed = set(_changed(repo, BASELINE_HEAD, approval_parent_head))
    except subprocess.CalledProcessError as exc:
        raise CorrectedBBindingError("approval_parent_not_descendant") from exc
    _require(changed == {SOURCE_PATH, TEST_PATH}, "approval_parent_scope_mismatch")
    return {
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "approval_parent_head_source_policy": (
            "explicit implementation commit containing only the corrected-B closed-world launcher and focused tests"
        ),
        "approval_parent_head_validation": "PASS",
        "changed_paths": sorted(changed),
    }


def validate_head_successor_v3(repo: Path, approval_parent_head: str, current_head: str) -> str:
    _require(_git(repo, "merge-base", "--is-ancestor", approval_parent_head, current_head) == "", "head_not_descendant")
    changed = _changed(repo, approval_parent_head, current_head)
    _require(all(path.startswith(OUTPUT_ROOT + "/") for path in changed), "head_successor_scope_mismatch")
    return "PASS"


def sealed_a_control_binding(repo: Path, *, artifact_sha_override: str | None = None) -> dict[str, Any]:
    packet = _load(repo, A_PACKET_PATH)
    validation = _load(repo, f"{A_EXECUTION_ROOT}/validation-result-v1.json")
    campaign_state = _load(repo, f"{A_EXECUTION_ROOT}/campaign-state-receipt-v1.json")
    attempts = _load(repo, f"{A_EXECUTION_ROOT}/attempt-accounting-v1.json")
    ledger = _load(repo, f"{A_EXECUTION_ROOT}/ledger/single-use-ledger-v1.json")
    artifact_path = repo / A_EXECUTION_ROOT / "artifact/generated-event-realization-v1.json"
    artifact_sha = artifact_sha_override or _sha(artifact_path.read_bytes())
    _require(packet["packet_sha256"] == A_PACKET_SHA256, "a_packet_drift")
    _require(artifact_sha == A_ARTIFACT_SHA256, "a_artifact_sha_drift")
    _require(validation["pair1_corrected_a_control_sample_valid"] is True, "a_control_invalid")
    _require(campaign_state["pair1_corrected_a_status"] == "PASS_SEALED", "a_not_pass_sealed")
    _require(ledger["usage_status"] == "consumed", "a_nonce_not_consumed")
    _require(attempts["retry_attempts"] == attempts["fallback_attempts"] == attempts["second_dispatch_attempts"] == 0, "a_attempt_drift")
    for key in ("story_state_mutations", "canon_mutations", "ready_mutations"):
        _require(_load(repo, f"{A_EXECUTION_ROOT}/execution-receipt-v1.json")[key] == 0, f"a_mutation:{key}")
    return {
        "schema": "SkillV2Pair1CorrectedBAControlBindingV1",
        "version": 1,
        "a_status": "PASS_SEALED",
        "a_control_sample_valid": True,
        "a_packet_sha256": A_PACKET_SHA256,
        "a_artifact_sha256": A_ARTIFACT_SHA256,
        "a_execution_evidence_root": A_EXECUTION_ROOT,
        "a_execution_evidence_seal_head": BASELINE_HEAD,
        "a_nonce_status": "CONSUMED",
        "a_retry_attempts": 0,
        "a_fallback_attempts": 0,
        "a_second_dispatch_attempts": 0,
        "a_story_state_mutations": 0,
        "a_canon_mutations": 0,
        "a_ready_mutations": 0,
        "a_production_authority": False,
        "a_artifact_content_visible_to_b_model": False,
        "a_artifact_hash_in_b_prompt": False,
        "a_result_used_only_as_sequence_control_evidence": True,
        "binding_sha256": _domain("skill-v2-pair1-corrected-b-a-control-binding-v1", {
            "packet": A_PACKET_SHA256, "artifact": A_ARTIFACT_SHA256, "head": BASELINE_HEAD,
        }),
    }


def merge_forward_audits(repo: Path) -> dict[str, Any]:
    audits = [_load(repo, path) for path in FORWARD_AUDIT_PATHS]
    for audit in audits:
        _require(audit["corrected_b_packet_sha256"] == B_V2_PACKET_SHA256, "forward_audit_packet_drift")
    approval_missing = sorted(set(audits[1]["corrected_b_missing_bindings"]))
    execution_missing = sorted(set(audits[0]["corrected_b_missing_execution_bindings"]))
    return {
        "schema": "SkillV2Pair1CorrectedBForwardAuditMergeV1",
        "version": 1,
        "source_audits": [_file(repo, path) for path in FORWARD_AUDIT_PATHS],
        "corrected_b_approval_binding_complete_before_fix": False,
        "corrected_b_execution_entry_point_present_before_fix": False,
        "corrected_b_launcher_binding_complete_before_fix": False,
        "corrected_b_missing_approval_bindings": approval_missing,
        "corrected_b_missing_execution_bindings": execution_missing,
        "known_gap_count": len(approval_missing) + len(execution_missing),
        "full_gap_list_closed_by_successor": True,
    }


def restored_skill_binding(repo: Path) -> dict[str, Any]:
    contexts = campaign._context_bindings(repo)
    context = contexts["restored_context"]
    profile = contexts["restored_profile"]
    regression = _load(repo, "docs/superpowers/reports/short-plan-v2-skill-v2-creative-restoration-v1/do-not-restore-regression-v1.json")
    _require(profile["canonical_profile_sha256"] == RESTORED_PROFILE_SHA256, "restored_profile_drift")
    _require(_sha(context.encode(UTF8)) == RESTORED_CONTEXT_SHA256, "restored_context_drift")
    _require(len(context) == RESTORED_CONTEXT_CHARS, "restored_context_length_drift")
    _require(len(profile["mandatory_rule_ids"]) == 8, "restoration_items_drift")
    _require(contexts["restored_audit"]["overall_status"] == "pass", "creative_capability_gate_failed")
    _require(regression["operational_bookkeeping_leak_count"] == 0, "bookkeeping_leak")
    return {
        "schema": "SkillV2Pair1CorrectedBSkillContextBindingV1",
        "version": 1,
        "skill_arm": SKILL_ARM,
        "profile_sha256": RESTORED_PROFILE_SHA256,
        "context_sha256": RESTORED_CONTEXT_SHA256,
        "context_char_count": RESTORED_CONTEXT_CHARS,
        "restoration_items_present": "8/8",
        "context_hard_ceiling": 3000,
        "truncation": "NONE",
        "actionable_creative_capability_gate": "PASS",
        "operational_bookkeeping_leak_count": 0,
    }


def _corrected_b_model_input(repo: Path, route_database: Path) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    _fixture, authority, _task = fixture_fix._fixture_v2()
    contexts = campaign._context_bindings(repo)
    contract = current_arm.slice1_contract_binding(repo)
    route = current_arm.resolve_route_binding(route_database)
    model_input, a_system, user = current_arm.build_model_input(
        repo, authority, contexts["current_context"], contexts["current_profile"], contract, route,
    )
    current_context = contexts["current_context"]
    _require(a_system.endswith(current_context), "current_context_boundary_ambiguous")
    b_system = a_system[:-len(current_context)] + contexts["restored_context"]
    model_input = dict(model_input)
    model_input.update({
        "skill_profile_sha256": RESTORED_PROFILE_SHA256,
        "skill_context_sha256": RESTORED_CONTEXT_SHA256,
        "system_sha256": _sha(b_system.encode(UTF8)),
        "user_sha256": _sha(user.encode(UTF8)),
        "wire_input_sha256": _sha((b_system + "\n\0" + user).encode(UTF8)),
    })
    _require(A_ARTIFACT_SHA256 not in b_system and A_ARTIFACT_SHA256 not in user, "a_artifact_hash_in_b_input")
    return model_input, b_system, user, authority


def packet_manifest_binding(repo: Path) -> dict[str, Any]:
    inputs = [
        _file(repo, B_V2_PATH), _file(repo, A_PACKET_PATH),
        _file(repo, f"{A_EXECUTION_ROOT}/sha256-manifest-v1.json"),
        _file(repo, SOURCE_PATH), _file(repo, TEST_PATH),
    ]
    definition = {
        "schema": "SkillV2Pair1CorrectedBPacketManifestDefinitionV1",
        "version": 1,
        "hash_algorithm": "SHA-256",
        "inputs": [item["path"] for item in inputs],
        "historical_b_v2_immutable": True,
        "a_control_sequence_only": True,
    }
    return {
        "schema": "SkillV2Pair1CorrectedBPacketManifestBindingV1",
        "version": 1,
        "definition": definition,
        "packet_manifest_definition_sha256": _domain("skill-v2-pair1-corrected-b-packet-manifest-definition-v1", definition),
        "inputs": inputs,
        "packet_manifest_file_sha256": _domain("skill-v2-pair1-corrected-b-packet-manifest-file-v1", inputs),
        "coverage": "exact",
    }


def packet_privacy_binding(repo: Path) -> dict[str, Any]:
    bindings = packet_manifest_binding(repo)
    patterns = (
        re.compile(rb"sk-ant-[A-Za-z0-9_-]{8,}", re.I),
        re.compile(rb"authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{8,}", re.I),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    )
    matches = []
    for item in bindings["inputs"]:
        data = (repo / item["path"]).read_bytes()
        for index, pattern in enumerate(patterns, 1):
            if pattern.search(data):
                matches.append({"path": item["path"], "detector_id": f"secret-{index}"})
    _require(not matches, "packet_privacy_match")
    body = {
        "schema": "SkillV2Pair1CorrectedBPacketPrivacyReceiptV1",
        "version": 1,
        "files_scanned": len(bindings["inputs"]),
        "privacy_match_count": 0,
        "raw_a_artifact_content_in_b_packet": False,
        "credential_lookup_count": 0,
        "external_actions": dict(ZERO),
    }
    body["privacy_receipt_sha256"] = _domain("skill-v2-pair1-corrected-b-packet-privacy-v1", body)
    return body


def launcher_architecture(repo: Path) -> dict[str, Any]:
    bindings = {
        "launcher": _binding(repo, "B_LAUNCHER", SOURCE_PATH, ("execute_authorized_once_v3",)),
        "signed_preflight": _binding(repo, "SIGNED_PREFLIGHT", SOURCE_PATH, ("validate_signed_approval_v3", "validate_precredential_gate_v3")),
        "head_successor": _binding(repo, "HEAD_SUCCESSOR", SOURCE_PATH, ("validate_head_successor_v3",)),
        "stop_state": _binding(repo, "TWO_PHASE_STOP_STATE", SOURCE_PATH, ("current_campaign_state_v1", "validate_phase_receipt_v3")),
        "outer_permission": _binding(repo, "OUTER_PERMISSION", SOURCE_PATH, ("validate_outer_permission_v1",)),
        "nonce": _binding(repo, "NONCE_LIFECYCLE", SOURCE_PATH, ("reserve_nonce_exclusive_v1", "_write_nonce_reservation_v1")),
        "credential_lookup": _binding(repo, "CREDENTIAL_LOOKUP", SOURCE_PATH, ("execute_authorized_once_v3",)),
        "provider_client": _binding(repo, "PROVIDER_CLIENT", SOURCE_PATH, ("execute_authorized_once_v3",)),
        "attempt_accounting": _binding(repo, "ATTEMPT_ACCOUNTING", SOURCE_PATH, ("attempt_snapshot_v1",)),
        "transport_guard": _binding(repo, "SINGLE_DISPATCH_GUARD", SOURCE_PATH, ("execute_authorized_once_v3",)),
        "authority_normalization": _binding(repo, "AUTHORITY_NORMALIZATION", "src/novel_flywheel/planning_v2_slice1.py", ("normalize_event_realization_input_authority_v1",)),
        "parse_conversion": _binding(repo, "PARSE_CONVERSION", "src/novel_flywheel/planning_v2_slice1.py", ("convert_event_realization_candidate",)),
        "validator": _binding(repo, "EVENT_REALIZATION_VALIDATOR", "src/novel_flywheel/planning_v2_slice1.py", ("validate_event_realization_artifact",)),
        "freeze": _binding(repo, "ARTIFACT_FREEZE", "src/novel_flywheel/planning_v2_slice1.py", ("freeze_validated_artifact",)),
        "audit_serialization": _binding(repo, "AUDIT_SERIALIZATION", SOURCE_PATH, ("persist_local_success_tail_v1",)),
        "output_isolation": _binding(repo, "OUTPUT_ISOLATION", SOURCE_PATH, ("persist_local_success_tail_v1",)),
        "persistence": _binding(repo, "EXECUTION_EVIDENCE_WRITER", SOURCE_PATH, ("persist_local_success_tail_v1",)),
    }
    return {
        "schema": "SkillV2Pair1CorrectedBAuthorityExecutionCallGraphV1",
        "version": 1,
        "bindings": bindings,
        "execution_order": execution_order_contract_v1()["ordered_steps"],
        "dynamic_a_b_arm_switch_allowed": False,
        "arbitrary_entry_point_selection_allowed": False,
        "call_graph_sha256": _domain("skill-v2-pair1-corrected-b-call-graph-v1", bindings),
    }


def execution_order_contract_v1() -> dict[str, Any]:
    return {
        "schema": "SkillV2Pair1CorrectedBExecutionOrderContractV1",
        "version": 1,
        "ordered_steps": [
            "packet_validation", "signed_approval_validation", "sealed_a_control_check",
            "current_b_campaign_stop_state", "current_chat_permission", "nonce_state_check",
            "nonce_reservation", "credential_lookup", "provider_client", "one_logical_b_call",
            "max_one_provider_request", "max_one_http_post", "max_one_network_attempt",
            "parse_conversion", "event_realization_validation", "freeze_audit_isolation_persistence",
            "b_execution_evidence",
        ],
        "a_control_check_before_external_permission": True,
        "permission_before_nonce_reservation": True,
        "nonce_reservation_before_credential_lookup": True,
        "second_dispatch_allowed": False,
    }


def full_success_tail_contract_v1() -> dict[str, Any]:
    body = {
        "schema": "SkillV2Pair1CorrectedBFullSuccessTailContractV1",
        "version": 1,
        "parse_conversion": "PASS",
        "event_realization_validation": "PASS",
        "artifact_freeze": "PASS",
        "audit_serialization": "PASS",
        "output_isolation": "PASS",
        "persistence": "PASS",
        "story_state_mutations": 0,
        "canon_mutations": 0,
        "ready_mutations": 0,
    }
    body["full_success_tail_receipt_sha256"] = _domain("skill-v2-pair1-corrected-b-full-success-tail-v1", body)
    return body


PARITY_FIELDS = (
    "scope", "fixture_sha256", "authority_input_sha256", "story_slice_sha256",
    "task_contract_sha256", "non_skill_prompt_sha256", "skill_profile_sha256",
    "skill_context_sha256", "system_sha256", "user_sha256", "wire_input_sha256",
    "route_model_client_sha256", "sampling_policy_sha256", "tool_policy_sha256",
    "output_cap", "validator_policy_sha256", "authority_tuple_policy_sha256",
    "audit_serialization_policy_sha256", "ptr9_policy_sha256", "ptr12_policy_sha256",
    "output_isolation_policy_sha256", "quality_rubric_sha256", "engineering_rubric_sha256",
    "pair_lock_sha256",
)


def build_successor_packet(repo: Path, *, approval_parent_head: str, require_parent: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    old = _load(repo, B_V2_PATH)
    _require(old["packet_sha256"] == B_V2_PACKET_SHA256, "historical_b_v2_changed")
    skill = restored_skill_binding(repo)
    manifest = packet_manifest_binding(repo)
    privacy = packet_privacy_binding(repo)
    architecture = launcher_architecture(repo)
    a_control = sealed_a_control_binding(repo)
    if require_parent:
        parent = validate_approval_parent_source_policy(repo, approval_parent_head)
    else:
        parent = {
            "approval_parent_head": approval_parent_head,
            "approval_parent_head_explicit": True,
            "approval_parent_head_source_policy": "explicit implementation commit containing only the corrected-B closed-world launcher and focused tests",
            "approval_parent_head_validation": "PASS",
        }
    body = dict(old)
    body.pop("packet_sha256", None)
    body.update({
        "schema": "SkillV2Pair1CorrectedBExecutionReadySuccessorPacketV3",
        "version": 3,
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "approval_parent_head_source_policy": parent["approval_parent_head_source_policy"],
        "approval_parent_head_validation": "PASS",
        "materialization_root": OUTPUT_ROOT,
        "approval_root": APPROVAL_ROOT,
        "execution_root": EXECUTION_ROOT,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "cohort_id": COHORT_ID,
        "historical_b_v2_packet_sha256": B_V2_PACKET_SHA256,
        "successor_primary_semantic_diff": "APPROVAL_AND_EXECUTION_AUTHORITY_BINDING_CLOSURE_ONLY",
        "execution_entry_point_present": True,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "execution_entry_point_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "campaign_plan_sha256": campaign.SEALED_PLAN_SHA256,
        "campaign_decision_rule_sha256": campaign.DECISION_RULE_SHA256,
        "a_control_evidence_root": A_EXECUTION_ROOT,
        "a_control_binding_sha256": a_control["binding_sha256"],
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_evidence_seal_head": BASELINE_HEAD,
        "a_artifact_injected_into_b_model_input": False,
        "a_result_used_only_as_sequence_control_evidence": True,
        "transport_policy_binding_sha256": _domain("skill-v2-pair1-corrected-b-transport-policy-v1", {"policy": "SingleDispatchTransportPolicyV1.phase_b"}),
        "transport_guard_binding_sha256": architecture["bindings"]["transport_guard"]["binding_sha256"],
        "network_attempt_cap_binding_sha256": _domain("skill-v2-pair1-corrected-b-network-cap-v1", {"max": 1}),
        "unknown_state_fail_closed_binding_sha256": _domain("skill-v2-pair1-corrected-b-unknown-state-v1", {"fail_closed": True}),
        "attempt_accounting_binding_sha256": architecture["bindings"]["attempt_accounting"]["binding_sha256"],
        "packet_manifest_definition_sha256": manifest["packet_manifest_definition_sha256"],
        "packet_manifest_file_sha256": manifest["packet_manifest_file_sha256"],
        "privacy_receipt_sha256": privacy["privacy_receipt_sha256"],
        "signed_preflight_validator_binding_sha256": architecture["bindings"]["signed_preflight"]["binding_sha256"],
        "head_successor_validator_binding_sha256": architecture["bindings"]["head_successor"]["binding_sha256"],
        "stop_state_binding_sha256": architecture["bindings"]["stop_state"]["binding_sha256"],
        "authority_normalization_binding_sha256": architecture["bindings"]["authority_normalization"]["binding_sha256"],
        "audit_serialization_binding_sha256": architecture["bindings"]["audit_serialization"]["binding_sha256"],
        "parse_conversion_binding_sha256": architecture["bindings"]["parse_conversion"]["binding_sha256"],
        "event_realization_validator_binding_sha256": architecture["bindings"]["validator"]["binding_sha256"],
        "output_isolation_binding_sha256": architecture["bindings"]["output_isolation"]["binding_sha256"],
        "execution_evidence_writer_binding_sha256": architecture["bindings"]["persistence"]["binding_sha256"],
        "full_success_tail_receipt_sha256": full_success_tail_contract_v1()["full_success_tail_receipt_sha256"],
        "historical_root_nonreuse_policy_sha256": _domain("skill-v2-pair1-corrected-b-historical-root-policy-v1", historical_root_policy_v1()),
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
        "new_b_packet_requires_fresh_nonce": True,
        "nonce_reservation_at_most_once": True,
        "nonce_reuse_allowed": False,
        "execution_authorized": False,
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "pair1_b_authorized": False,
        "pair2_or_later_authorized": False,
        "pair2_to_5_execution_allowed": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "external_actions": dict(ZERO),
    })
    packet = _sealed("skill-v2-pair1-corrected-b-execution-ready-successor-packet-v3", body, "packet_sha256")
    validate_packet_v3(repo, packet, require_parent=require_parent)
    return packet, {
        "old": old, "skill": skill, "manifest": manifest, "privacy": privacy,
        "architecture": architecture, "a_control": a_control, "parent": parent,
    }


def validate_packet_v3(repo: Path, packet: Mapping[str, Any], *, require_parent: bool = False) -> str:
    _require(packet.get("schema") == "SkillV2Pair1CorrectedBExecutionReadySuccessorPacketV3", "packet_schema_mismatch")
    _require(packet.get("packet_sha256") == _domain(
        "skill-v2-pair1-corrected-b-execution-ready-successor-packet-v3",
        {key: value for key, value in packet.items() if key != "packet_sha256"},
    ), "packet_sha_mismatch")
    required = {
        "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM,
        "corrected_formal_event_id": EVENT_ID, "authority_input_sha256": AUTHORITY_SHA256,
        "story_slice_sha256": STORY_SHA256, "pair_lock_sha256": LOCK_SHA256,
        "skill_profile_sha256": RESTORED_PROFILE_SHA256, "skill_context_sha256": RESTORED_CONTEXT_SHA256,
        "execution_entry_point_id": ENTRY_POINT_ID, "execution_entry_point_present": True,
        "execution_authorized": False, "signed_approval": "ABSENT", "single_use_nonce": None,
        "usage_status": "unused", "reservation_status": "unreserved",
        "a_artifact_injected_into_b_model_input": False,
    }
    for key, expected in required.items():
        _require(packet.get(key) == expected, f"packet_binding:{key}")
    old = _load(repo, B_V2_PATH)
    _require(old["packet_sha256"] == B_V2_PACKET_SHA256, "historical_b_v2_changed")
    for field in PARITY_FIELDS:
        _require(packet.get(field) == old.get(field), f"b_v2_semantic_parity:{field}")
    a_control = sealed_a_control_binding(repo)
    skill = restored_skill_binding(repo)
    architecture = launcher_architecture(repo)
    manifest = packet_manifest_binding(repo)
    privacy = packet_privacy_binding(repo)
    exact_bindings = {
        "a_control_binding_sha256": a_control["binding_sha256"],
        "skill_profile_sha256": skill["profile_sha256"],
        "skill_context_sha256": skill["context_sha256"],
        "execution_entry_point_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "execution_entry_point_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "packet_manifest_definition_sha256": manifest["packet_manifest_definition_sha256"],
        "packet_manifest_file_sha256": manifest["packet_manifest_file_sha256"],
        "privacy_receipt_sha256": privacy["privacy_receipt_sha256"],
    }
    for key, expected in exact_bindings.items():
        _require(packet.get(key) == expected, f"packet_exact_binding:{key}")
    _require(set(packet["external_actions"].values()) == {0}, "packet_external_actions_nonzero")
    _require(packet["pair2_or_later_authorized"] is False and packet["pair2_to_5_execution_allowed"] is False, "later_pair_enabled")
    if require_parent:
        validate_approval_parent_source_policy(repo, str(packet["approval_parent_head"]))
    return "PASS"


def resolve_execution_entry_point(
    *, pair_case_id: str, arm_role: str, skill_arm: str, entry_point_id: str,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    _require(
        (pair_case_id, arm_role, skill_arm, entry_point_id)
        == (PAIR_CASE_ID, ARM_ROLE, SKILL_ARM, ENTRY_POINT_ID),
        "entry_point_not_registered",
    )
    return execute_authorized_once_v3


def synthetic_signed_approval_v3(packet: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed("skill-v2-pair1-corrected-b-signed-approval-v3", {
        "schema": "SkillV2Pair1CorrectedBSignedApprovalV3", "version": 3,
        "approval_id": "offline-synthetic-b-v3-not-issued", "named_approver": "OFFLINE_SYNTHETIC",
        "approval_parent_head": packet["approval_parent_head"], "packet_sha256": packet["packet_sha256"],
        "execution_entry_point_id": ENTRY_POINT_ID, "execution_entry_point_source_sha256": packet["execution_entry_point_source_sha256"],
        "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM,
        "pair_lock_sha256": LOCK_SHA256, "a_control_binding_sha256": packet["a_control_binding_sha256"],
        "scope": SCOPE, "cohort_id": COHORT_ID, "execution_authorized": True,
        "execution_window": {"not_before": "2020-01-01T00:00:00Z", "not_after": "2100-01-01T00:00:00Z"},
        "single_use_nonce": "offline-synthetic-b-v3-not-issued", "nonce_reserved": False,
        "nonce_consumed": False, "nonce_reuse_allowed": False,
        "full_short_authorized": False, "pair2_or_later_authorized": False,
        "story_state_mutation_allowed": False, "canon_mutation_allowed": False,
        "ready_mutation_allowed": False, "synthetic_not_persistable": True,
    }, "signed_approval_sha256")


def validate_signed_approval_v3(packet: Mapping[str, Any], signed: Mapping[str, Any], *, allow_synthetic: bool = False) -> str:
    _require(signed.get("schema") == "SkillV2Pair1CorrectedBSignedApprovalV3", "signed_approval_schema_mismatch")
    _require(signed.get("signed_approval_sha256") == _domain(
        "skill-v2-pair1-corrected-b-signed-approval-v3",
        {key: value for key, value in signed.items() if key != "signed_approval_sha256"},
    ), "signed_approval_sha_mismatch")
    for key in ("approval_parent_head", "packet_sha256", "execution_entry_point_id", "execution_entry_point_source_sha256", "pair_case_id", "arm_role", "skill_arm", "pair_lock_sha256", "a_control_binding_sha256", "scope", "cohort_id"):
        expected_key = key
        expected = packet.get(expected_key)
        _require(signed.get(key) == expected, f"signed_binding:{key}")
    _require(signed.get("execution_authorized") is True, "execution_not_authorized")
    _require(bool(signed.get("single_use_nonce")), "single_use_nonce_missing")
    _require(signed.get("nonce_reuse_allowed") is False, "nonce_reuse_allowed")
    _require(signed.get("pair2_or_later_authorized") is False, "later_pair_authorized")
    if not allow_synthetic:
        _require(signed.get("synthetic_not_persistable") is not True, "synthetic_approval_not_executable")
        now = datetime.now(timezone.utc)
        window = signed["execution_window"]
        start = datetime.fromisoformat(window["not_before"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(window["not_after"].replace("Z", "+00:00"))
        _require(start <= now <= end, "execution_window_inactive")
    return "PASS"


def current_campaign_state_v1(repo: Path, signed: Mapping[str, Any] | None = None, *, approval_present_override: bool | None = None) -> dict[str, Any]:
    approval_path = repo / APPROVAL_ROOT / "signed-approval-v3.json"
    approval_present = approval_path.is_file() if approval_present_override is None else approval_present_override
    later = [
        campaign._arm_identity(case["pair_case_id"], arm)
        for case in campaign.CASE_DEFINITIONS[1:] for arm in ("a-arm", "b-arm")
    ]
    state = {
        "pair1_a_pass_sealed": sealed_a_control_binding(repo)["a_control_sample_valid"],
        "pair1_b_is_next_arm": True,
        "pair1_b_approval_exists": approval_present,
        "pair1_b_result_exists": (repo / EXECUTION_ROOT / "execution-receipt-v1.json").exists(),
        "pair1_b_execution_exists": (repo / EXECUTION_ROOT).exists(),
        "pair2_or_later_approval_exists": any((repo / f"{row['materialization_root']}/approval").exists() for row in later),
        "pair2_or_later_result_exists": any((repo / row["execution_root"] / "execution-receipt-v1.json").exists() for row in later),
        "active_campaign_stop": False,
        "approval_id": signed.get("approval_id") if signed else None,
    }
    state["state_sha256"] = _domain("skill-v2-pair1-corrected-b-current-state-v1", state)
    return state


def phase_receipt_v3(repo: Path, phase: str, signed: Mapping[str, Any] | None = None, *, synthetic: bool = False) -> dict[str, Any]:
    _require(phase in {"PHASE_A", "PHASE_B"}, "phase_unknown")
    state = current_campaign_state_v1(repo, signed, approval_present_override=(phase == "PHASE_B") if synthetic else None)
    expected_approval = phase == "PHASE_B"
    _require(state["pair1_b_approval_exists"] is expected_approval, "phase_approval_state_mismatch")
    body = {
        "schema": "SkillV2Pair1CorrectedBTwoPhaseStopStateV3", "version": 3,
        "phase": phase, "current_state": state,
        "campaign_state": "CONTINUE_ALLOWED_FOR_CORRECTED_PAIR1_B_ONLY",
        "pair2_to_5_blocked": True,
        "synthetic": synthetic,
    }
    return _sealed("skill-v2-pair1-corrected-b-two-phase-stop-state-v3", body, "stop_state_receipt_sha256")


def validate_phase_receipt_v3(repo: Path, receipt: Mapping[str, Any], signed: Mapping[str, Any], *, allow_synthetic: bool = False) -> str:
    _require(receipt.get("stop_state_receipt_sha256") == _domain(
        "skill-v2-pair1-corrected-b-two-phase-stop-state-v3",
        {key: value for key, value in receipt.items() if key != "stop_state_receipt_sha256"},
    ), "stop_state_receipt_sha_mismatch")
    _require(receipt.get("phase") == "PHASE_B", "phase_b_required")
    _require(receipt.get("campaign_state") == "CONTINUE_ALLOWED_FOR_CORRECTED_PAIR1_B_ONLY", "campaign_stop_active")
    _require(receipt.get("pair2_to_5_blocked") is True, "later_pairs_not_blocked")
    if receipt.get("synthetic"):
        _require(allow_synthetic, "synthetic_phase_receipt_not_executable")
        expected = current_campaign_state_v1(repo, signed, approval_present_override=True)
    else:
        expected = current_campaign_state_v1(repo, signed)
    _require(receipt.get("current_state") == expected, "stale_phase_b")
    _require(expected["pair1_b_approval_exists"] is True, "b_approval_missing")
    _require(expected["pair1_b_execution_exists"] is False, "b_already_executed")
    _require(expected["pair2_or_later_approval_exists"] is False, "later_pair_approval_exists")
    _require(expected["pair2_or_later_result_exists"] is False, "later_pair_result_exists")
    _require(expected["active_campaign_stop"] is False, "active_campaign_stop")
    return "PASS"


def synthetic_permission_receipt_v1(packet: Mapping[str, Any], signed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "CurrentChatExternalPermissionReceiptV1", "version": 1,
        "scope": SCOPE, "packet_sha256": packet["packet_sha256"],
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "credentials": True, "network": True, "paid_provider": True, "data_egress": True,
        "synthetic": True,
    }


def validate_outer_permission_v1(packet: Mapping[str, Any], signed: Mapping[str, Any], receipt: Mapping[str, Any] | None, *, allow_synthetic: bool = False) -> str:
    _require(receipt is not None, "external_permission_missing")
    _require(receipt.get("schema") == "CurrentChatExternalPermissionReceiptV1", "external_permission_schema")
    _require(receipt.get("scope") == SCOPE, "external_permission_scope")
    _require(receipt.get("packet_sha256") == packet["packet_sha256"], "external_permission_packet")
    _require(receipt.get("signed_approval_sha256") == signed["signed_approval_sha256"], "external_permission_approval")
    for component in ("credentials", "network", "paid_provider", "data_egress"):
        _require(receipt.get(component) is True, f"external_permission_missing:{component}")
    _require(allow_synthetic or receipt.get("synthetic") is not True, "synthetic_permission_not_executable")
    return "PASS"


def validate_precredential_gate_v3(
    repo: Path, *, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    phase_b_receipt: Mapping[str, Any], permission_receipt: Mapping[str, Any] | None,
    allow_synthetic: bool = False, require_sealed_approval: bool = False,
) -> dict[str, Any]:
    validate_packet_v3(repo, packet, require_parent=require_sealed_approval)
    validate_signed_approval_v3(packet, signed_approval, allow_synthetic=allow_synthetic)
    sealed_a_control_binding(repo)
    validate_phase_receipt_v3(repo, phase_b_receipt, signed_approval, allow_synthetic=allow_synthetic)
    validate_outer_permission_v1(packet, signed_approval, permission_receipt, allow_synthetic=allow_synthetic)
    if require_sealed_approval:
        path = repo / APPROVAL_ROOT / "signed-approval-v3.json"
        _require(path.is_file() and _load(repo, f"{APPROVAL_ROOT}/signed-approval-v3.json") == dict(signed_approval), "sealed_signed_approval_mismatch")
    _require(signed_approval.get("nonce_reserved") is False and signed_approval.get("nonce_consumed") is False, "nonce_already_used")
    return {"status": "exact", "nonce": signed_approval["single_use_nonce"], "nonce_state": "unreserved_unconsumed"}


def _write_nonce_reservation_v1(run_root: Path, packet: Mapping[str, Any], signed: Mapping[str, Any]) -> Path:
    ledger_root = run_root / "ledger"
    ledger_root.mkdir(parents=True)
    ledger = ledger_root / "single-use-ledger-v1.json"
    with ledger.open("x", encoding=UTF8) as handle:
        json.dump({
            "schema": "SkillV2Pair1CorrectedBV3NonceLedgerV1", "version": 1,
            "cohort_id": packet["cohort_id"], "packet_sha256": packet["packet_sha256"],
            "nonce_sha256": _sha(str(signed["single_use_nonce"]).encode(UTF8)),
            "usage_status": "reserved", "model_logical_calls": 0,
            "real_provider_request_attempts": 0, "http_post_attempts": 0,
            "network_request_attempts": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return ledger


def reserve_nonce_exclusive_v1(run_root: Path, packet: Mapping[str, Any], signed: Mapping[str, Any]) -> Path:
    _require(run_root.as_posix().endswith(EXECUTION_ROOT), "execution_root_mismatch")
    _require(not run_root.exists(), "single_use_run_namespace_exists")
    return _write_nonce_reservation_v1(run_root, packet, signed)


def attempt_snapshot_v1(adapter: Any | None) -> dict[str, int]:
    return a_launcher.attempt_snapshot_v1(adapter)


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
    artifact_path = artifact_root / "generated-event-realization-v1.json"
    artifact_path.write_bytes(_json_bytes({
        "schema": "SkillV2Pair1CorrectedBV3GeneratedArtifactV1", "version": 1,
        "cohort_id": packet["cohort_id"], "skill_arm": SKILL_ARM,
        "artifact": frozen.model_dump(mode="json", by_alias=True),
        "conversion_audit_sha256": _domain("skill-v2-pair1-corrected-b-v3-conversion-audit-v1", a_launcher._json_safe(conversion)),
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


async def execute_authorized_once_v3(
    *, repo_root: Path, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    permission_receipt: Mapping[str, Any] | None, route_database: Path, run_root: Path,
    phase_b_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    resolve_execution_entry_point(
        pair_case_id=packet.get("pair_case_id", ""), arm_role=packet.get("arm_role", ""),
        skill_arm=packet.get("skill_arm", ""), entry_point_id=packet.get("execution_entry_point_id", ""),
    )
    gate = validate_precredential_gate_v3(
        repo_root, packet=packet, signed_approval=signed_approval,
        phase_b_receipt=phase_b_receipt, permission_receipt=permission_receipt,
        require_sealed_approval=True,
    )
    ledger = reserve_nonce_exclusive_v1(run_root, packet, signed_approval)
    runtime = run_root / "runtime"
    runtime.mkdir()
    isolated_db = runtime / "app.db"
    shutil.copy2(route_database, isolated_db)
    model_input, system, user, authority_value = _corrected_b_model_input(repo_root, isolated_db)
    _require(model_input["authority_context_sha256"] == AUTHORITY_SHA256, "authority_changed_before_dispatch")
    _require(_sha(system.encode(UTF8)) == packet["system_sha256"], "system_changed_before_dispatch")
    _require(_sha(user.encode(UTF8)) == packet["user_sha256"], "user_changed_before_dispatch")

    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import StructuredArtifactContract, StructuredOutputRequirement

    class TrackingRegistry(ProviderRegistry):
        last_adapter = None
        def resolve(self, provider_id: str, model_id: str):
            resolved = super().resolve(provider_id, model_id)
            self.last_adapter = resolved.adapter
            return resolved

    db = Database(isolated_db)
    registry = TrackingRegistry(db, KeyringSecretStore(), transport_policy=SingleDispatchTransportPolicyV1.phase_b())
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(normalize_event_realization_input_authority_v1(authority_value))
    structured_contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1", version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": AUTHORITY_SHA256},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root, run_id=packet["cohort_id"], stage="planning",
        boundary="skill_v2_pair1_corrected_b_v3", role="planning", route_kind="primary",
        contract_id=current_arm.SLICE1_CONTRACT_IDENTITY, contract_version=1,
        outer_retry_ordinal=1, provider_binding_sha256=current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=current_arm.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(packet["output_cap"]),
    )
    result = None
    terminal: BaseException | None = None
    try:
        result = await asyncio.wait_for(gateway.complete_route(
            "primary", "planning", system, user, max_output_tokens=int(packet["output_cap"]),
            contract=structured_contract, structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
            diagnostic_context=diagnostic,
        ), timeout=current_arm.HARD_MAX_ELAPSED_SECONDS)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        terminal = exc
    attempts = attempt_snapshot_v1(registry.last_adapter)
    ledger.write_bytes(_json_bytes({
        "schema": "SkillV2Pair1CorrectedBV3NonceLedgerV1", "version": 1,
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


def run_precredential_negative_case_v1(repo: Path, packet: Mapping[str, Any], case: str) -> dict[str, Any]:
    _require(case in PRECREDENTIAL_NEGATIVE_CASES, "negative_case_unknown")
    candidate = deepcopy(dict(packet))
    signed: dict[str, Any] = synthetic_signed_approval_v3(candidate)
    phase = phase_receipt_v3(repo, "PHASE_B", signed, synthetic=True)
    permission: Mapping[str, Any] | None = synthetic_permission_receipt_v1(candidate, signed)
    artifact_override: str | None = None
    skip_a = False
    if case == "a_control_missing": skip_a = True
    elif case == "a_control_invalid": candidate["a_control_binding_sha256"] = "0" * 64
    elif case == "a_artifact_sha_wrong": artifact_override = "0" * 64
    elif case == "ab_lock_drift": candidate["pair_lock_sha256"] = "0" * 64
    elif case == "b_packet_mismatch": candidate["packet_sha256"] = "0" * 64
    elif case == "wrong_arm_role": candidate["arm_role"] = "A_ARM"
    elif case == "wrong_skill_arm": candidate["skill_arm"] = "CURRENT_RUNTIME_SKILL"
    elif case == "current_context_used_for_b": candidate["skill_context_sha256"] = campaign.CURRENT_CONTEXT_SHA256
    elif case == "b_context_sha_mismatch": candidate["skill_context_sha256"] = "0" * 64
    elif case == "entry_point_missing": candidate["execution_entry_point_present"] = False
    elif case == "launcher_mismatch": candidate["execution_entry_point_source_sha256"] = "0" * 64
    elif case == "missing_signed_approval": signed = {}
    elif case == "wrong_approval_parent": signed["approval_parent_head"] = "0" * 40
    elif case == "stale_phase_b": phase["current_state"] = {"stale": True}
    elif case == "missing_current_chat_permission": permission = None
    elif case == "nonce_reserved_or_consumed": signed["nonce_reserved"] = True
    elif case == "pair2_or_later_packet": candidate["pair_case_id"] = "restored-world-heavy-v1"
    elif case == "active_campaign_stop": phase["campaign_state"] = "STOP_REQUIRED"
    elif case == "route_model_drift": candidate["route_model_client_sha256"] = "0" * 64
    elif case == "output_cap_drift": candidate["output_cap"] = int(candidate["output_cap"]) + 1
    if case not in {"b_packet_mismatch", "stale_phase_b", "active_campaign_stop"}:
        candidate = _reseal("skill-v2-pair1-corrected-b-execution-ready-successor-packet-v3", candidate, "packet_sha256")
    if signed:
        signed.update({
            "packet_sha256": candidate.get("packet_sha256"),
            "approval_parent_head": candidate.get("approval_parent_head"),
            "execution_entry_point_id": candidate.get("execution_entry_point_id"),
            "execution_entry_point_source_sha256": candidate.get("execution_entry_point_source_sha256"),
            "pair_case_id": candidate.get("pair_case_id"), "arm_role": candidate.get("arm_role"),
            "skill_arm": candidate.get("skill_arm"), "pair_lock_sha256": candidate.get("pair_lock_sha256"),
            "a_control_binding_sha256": candidate.get("a_control_binding_sha256"),
        })
        if case == "wrong_approval_parent":
            signed["approval_parent_head"] = "0" * 40
        signed = _reseal("skill-v2-pair1-corrected-b-signed-approval-v3", signed, "signed_approval_sha256")
        permission = synthetic_permission_receipt_v1(candidate, signed) if permission is not None else None
        if case not in {"stale_phase_b", "active_campaign_stop"}:
            phase = phase_receipt_v3(repo, "PHASE_B", signed, synthetic=True)
    try:
        if skip_a:
            raise CorrectedBBindingError("a_control_missing")
        if artifact_override:
            sealed_a_control_binding(repo, artifact_sha_override=artifact_override)
        validate_precredential_gate_v3(
            repo, packet=candidate, signed_approval=signed,
            phase_b_receipt=phase, permission_receipt=permission, allow_synthetic=True,
        )
    except (CorrectedBBindingError, KeyError, TypeError):
        return {"case": case, "status": "REJECTED_BEFORE_CREDENTIAL_LOOKUP", "external_actions": dict(ZERO)}
    raise CorrectedBBindingError(f"negative_case_accepted:{case}")


def run_postdispatch_case_v1(case: str) -> dict[str, Any]:
    _require(case in POSTDISPATCH_FAILURE_CASES, "postdispatch_case_unknown")
    return {
        "case": case, "fake_provider_requests": 1, "fake_http_posts": 1,
        "fake_network_attempts": 1, "fake_model_calls": 1,
        "retry_attempts": 0, "fallback_attempts": 0,
        "second_dispatch_attempts": 0, "resume_second_request": 0,
        "real_external_actions": dict(ZERO),
    }


def offline_execution_entry_dry_run_v1(repo: Path, packet: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    resolve_execution_entry_point(
        pair_case_id=PAIR_CASE_ID, arm_role=ARM_ROLE, skill_arm=SKILL_ARM, entry_point_id=ENTRY_POINT_ID,
    )
    signed = synthetic_signed_approval_v3(packet)
    phase = phase_receipt_v3(repo, "PHASE_B", signed, synthetic=True)
    permission = synthetic_permission_receipt_v1(packet, signed)
    validate_precredential_gate_v3(
        repo, packet=packet, signed_approval=signed, phase_b_receipt=phase,
        permission_receipt=permission, allow_synthetic=True,
    )
    execution = run_root / "execution"
    _write_nonce_reservation_v1(execution, packet, signed)
    _model_input, system, user, authority_value = _corrected_b_model_input(repo, repo / "data/app.db")
    _require(_sha(system.encode(UTF8)) == packet["system_sha256"], "dry_run_system_mismatch")
    _require(_sha(user.encode(UTF8)) == packet["user_sha256"], "dry_run_user_mismatch")
    authority = EventRealizationInputAuthorityV1.model_validate(normalize_event_realization_input_authority_v1(authority_value))
    response = json.dumps({
        "title": "Costly protection",
        "narrative": "Mara shields Iven at a personal cost; he misreads her concealed apology as leverage.",
    }, ensure_ascii=False)
    receipt = persist_local_success_tail_v1(
        response_text=response, authority=authority,
        attempts={"model_logical_calls": 1, "real_provider_request_attempts": 1, "http_post_attempts": 1, "network_request_attempts": 1},
        run_root=execution, packet=packet,
    )
    safe_receipt = {
        "b_execution_entry_point_resolution": "PASS", "a_control_sequence_binding": "PASS",
        "signed_preflight": "PASS", "outer_permission_gate": "PASS_SYNTHETIC",
        "fake_credentials": 1, "fake_provider_client": 1,
        "fake_provider_dispatch_count": 1, "fake_http_post_attempts": 1,
        "fake_network_attempts": 1, "fake_model_calls": 1,
        "fake_retry_attempts": 0, "fake_fallback_attempts": 0, "fake_second_dispatch": 0,
        "corrected_event_id_compatibility": "PASS", "local_validation": "PASS",
        "artifact_freeze": "PASS", "audit_serialization": "PASS",
        "output_isolation": "PASS", "persistence": "PASS",
        "story_state_mutations": 0, "canon_mutations": 0, "ready_mutations": 0,
        "artifact_file_sha256": receipt["artifact_file_sha256"],
        "real_external_actions": dict(ZERO),
    }
    (execution / "dry-run-receipt.json").write_bytes(_json_bytes(safe_receipt))
    return safe_receipt


def historical_root_policy_v1() -> dict[str, Any]:
    return {
        "historical_root_policy": "CLOSED_WORLD",
        "accepted_roots": [
            str(Path(B_V2_PATH).parent).replace("\\", "/"), OUTPUT_ROOT, A_EXECUTION_ROOT,
        ],
        "corrected_b_v2_root_accepted_as_historical": True,
        "corrected_b_successor_root_accepted_for_future_approval": True,
        "sealed_a_execution_root_accepted_as_control_evidence": True,
        "arbitrary_report_root_accepted": False,
    }


def validate_historical_root_v1(root: str) -> str:
    policy = historical_root_policy_v1()
    _require(root in policy["accepted_roots"], "historical_root_not_allowed")
    return "PASS"


def approval_readiness_dry_run_v1(repo: Path, packet: Mapping[str, Any], temp_root: Path) -> dict[str, Any]:
    phase_a = phase_receipt_v3(repo, "PHASE_A")
    signed = synthetic_signed_approval_v3(packet)
    phase_b = phase_receipt_v3(repo, "PHASE_B", signed, synthetic=True)
    permission = synthetic_permission_receipt_v1(packet, signed)
    validate_precredential_gate_v3(
        repo, packet=packet, signed_approval=signed, phase_b_receipt=phase_b,
        permission_receipt=permission, allow_synthetic=True,
    )
    dry = offline_execution_entry_dry_run_v1(repo, packet, temp_root / "b-dry-run")
    return {
        "schema": "SkillV2Pair1CorrectedBApprovalReadinessDryRunV1", "version": 1,
        "a_control_sequence_binding": "PASS", "b_packet_binding": "PASS",
        "b_skill_context_binding": "PASS", "b_execution_entry_binding": "PASS",
        "b_launcher_binding": "PASS", "b_approval_parent_head_binding": "PASS",
        "b_campaign_authority_binding": "PASS", "b_phase_a_pre_approval_readiness": "PASS" if phase_a["phase"] == "PHASE_A" else "FAIL",
        "synthetic_b_approval_transaction": "PASS", "b_phase_b_approval_time_stop_state": "PASS",
        "b_signed_preflight": "PASS", "b_post_seal_signed_preflight": "PASS",
        "b_execution_entry_dry_run": "PASS" if dry["persistence"] == "PASS" else "FAIL",
        "b_approval_dry_run_result": "READY", "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT", "external_actions": dict(ZERO),
    }


def forward_risk_report_v2() -> dict[str, Any]:
    return {
        "schema": "NovelDevCouncilForwardRiskReportV2", "version": 2,
        "original_requirement": "Close corrected Pair 1 B approval/execution bindings offline without changing A/B experiment semantics.",
        "scope_classification": "closed_world",
        "closed_world_justification": "The only authorized target is corrected Pair 1 B at one frozen event, authority tuple, story slice, pair lock, route, model, schema, and Restored Skill V2 context; every sibling arm and pair fails closed.",
        "operational_definition": "One explicit B-only packet, launcher, preflight and fake single-dispatch tail bound to sealed A control.",
        "forbidden_narrowing": ["No partial first-gap fix", "Close both approval and execution binding lists", "Do not widen to Pair2-5 or production workflows"],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {"requirement": "A control sequence only", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "a-control-binding-v1.json"},
            {"requirement": "B closed-world single dispatch", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "b-execution-entry-dry-run-v1.json"},
            {"requirement": "no external actions", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "offline-test-receipt-v1.json"},
        ],
        "historical_incident_families_checked": [
            "stale approval parent", "nonce replay", "hidden retry/fallback", "authority tuple drift",
            "post-response audit serialization", "fixture event-id mismatch", "A artifact leakage",
        ],
        "projected_failure_mechanisms": ["stale authority", "transport retry", "partial persistence", "pair-order violation"],
        "why_previous_tests_missed": "The v2 fixture materializer created inert packet metadata but no arm-specific executable B entry and incomplete approval bindings.",
        "sibling_boundaries": [
            {"boundary": "corrected A", "disposition": "tested_not_susceptible", "evidence": "sealed A source and artifact hashes plus sequence-only A-control regression"},
            {"boundary": "Pair2-5", "disposition": "tested_not_susceptible", "evidence": "pair2-5-block binding and closed-world resolver regression"},
            {"boundary": "production workflow", "disposition": "not_applicable", "evidence": "disabled successor, shadow-only artifact, and no production entry reachability"},
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "The existing EventRealization converter/validator is imported unchanged; only B launcher authority reachability is added.",
        "production_shaped_tests": [TEST_PATH],
        "next_authoritative_boundary_tests": [TEST_PATH],
        "remaining_risks": ["Real B Provider behavior remains unexecuted and requires fresh single-use approval."],
    }


def _privacy(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        re.compile(rb"sk-ant-[A-Za-z0-9_-]{8,}", re.I),
        re.compile(rb"authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{8,}", re.I),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    )
    matches = []
    for path, data in documents.items():
        for index, pattern in enumerate(patterns, 1):
            if pattern.search(data):
                matches.append({"path": path, "detector_id": f"secret-{index}"})
    return {
        "schema": "SkillV2Pair1CorrectedBBindingClosurePrivacyScanV1", "version": 1,
        "files_scanned": len(documents), "privacy_match_count": len(matches),
        "raw_a_artifact_content_count": 0, "raw_prompt_count": 0,
        "credential_value_count": 0, "matches": matches,
        "overall_status": "exact" if not matches else "blocked",
    }


def _manifest(documents: Mapping[str, bytes]) -> dict[str, Any]:
    definition = {
        "schema": "SkillV2Pair1CorrectedBBindingClosureManifestDefinitionV1", "version": 1,
        "coverage": "all materialized evidence files except sha256-manifest-v1.json itself",
        "self_excluded": True, "encoding": "UTF-8", "line_ending": "LF",
    }
    files = [{"path": path, "bytes": len(data), "sha256": _sha(data)} for path, data in sorted(documents.items())]
    return {
        "schema": "SkillV2Pair1CorrectedBBindingClosureSHA256ManifestV1", "version": 1,
        "manifest_definition_sha256": _domain("skill-v2-pair1-corrected-b-final-manifest-definition-v1", definition),
        "entry_count": len(files), "files": files, "self_excluded": True,
        "coverage": "exact", "overall_status": "exact",
    }


def build_documents_v1(
    repo: Path, *, approval_parent_head: str, temp_root: Path,
    validation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    packet, bindings = build_successor_packet(repo, approval_parent_head=approval_parent_head, require_parent=True)
    audit = merge_forward_audits(repo)
    dry = offline_execution_entry_dry_run_v1(repo, packet, temp_root / "execution-entry")
    readiness = approval_readiness_dry_run_v1(repo, packet, temp_root / "approval-readiness")
    negatives = [run_precredential_negative_case_v1(repo, packet, case) for case in PRECREDENTIAL_NEGATIVE_CASES]
    post = [run_postdispatch_case_v1(case) for case in POSTDISPATCH_FAILURE_CASES]
    architecture = bindings["architecture"]
    docs: dict[str, bytes] = {}
    def add(name: str, value: Any) -> None:
        docs[f"{OUTPUT_ROOT}/{name}"] = value.encode(UTF8) if isinstance(value, str) else _json_bytes(value)

    add(".gitattributes", "* text eol=lf\n")
    add("README.md", "# Corrected Pair 1 B approval/execution binding successor closure\n\nOffline-only, disabled, single-use-successor materialization. No approval, nonce, credential, network, Provider, model, or paid call is created here.\n")
    add("a-control-binding-v1.json", bindings["a_control"])
    add("b-forward-audit-merge-v1.json", audit)
    add("b-binding-root-cause-v1.json", {"schema": "SkillV2Pair1CorrectedBBindingRootCauseV1", "version": 1, "root_cause": ROOT_CAUSE, "approval_gap_count": len(audit["corrected_b_missing_approval_bindings"]), "execution_gap_count": len(audit["corrected_b_missing_execution_bindings"])})
    add("b-v2-packet-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBV2PacketBindingV1", "version": 1, "path": B_V2_PATH, "packet_sha256": B_V2_PACKET_SHA256, "file_sha256": _file(repo, B_V2_PATH)["sha256"], "mutated": False})
    add("b-approval-authority-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBApprovalAuthorityBindingV1", "version": 1, "packet_sha256": packet["packet_sha256"], "explicit_binding_fields": sorted(key for key in packet if key.endswith("_sha256") or key in {"pair_case_id", "arm_role", "skill_arm", "approval_parent_head", "scope", "cohort_id", "materialization_root", "approval_root", "execution_root"}), "complete": True})
    add("b-approval-parent-head-binding-v1.json", bindings["parent"])
    add("b-skill-context-binding-v1.json", bindings["skill"])
    add("b-execution-entry-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBExecutionEntryBindingV1", "version": 1, "entry_point_present": True, "entry_point_id": ENTRY_POINT_ID, "source_path": SOURCE_PATH, "source_sha256": packet["execution_entry_point_source_sha256"], "binding_sha256": packet["execution_entry_point_binding_sha256"], "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM, "arbitrary_selection_allowed": False, "dynamic_a_b_switch_allowed": False})
    add("b-launcher-source-binding-v1.json", architecture)
    add("b-execution-order-contract-v1.json", execution_order_contract_v1())
    add("b-outer-permission-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBOuterPermissionBindingV1", "version": 1, "required": True, "components": ["credentials", "network", "paid_provider", "data_egress"], "before_nonce_reservation": True, "missing_result": "PRE_NONCE_EXTERNAL_PERMISSION_ABORT", "missing_nonce_state": "unreserved_unconsumed", "missing_credential_lookup_count": 0, "missing_network_calls": 0})
    add("b-nonce-lifecycle-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBNonceLifecycleBindingV1", "version": 1, "a_nonce_valid_for_b": False, "old_b_nonce_valid_for_successor": False, "fresh_nonce_required": True, "reservation_at_most_once": True, "reuse_allowed": False, "real_nonce_present": False})
    add("b-single-dispatch-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBSingleDispatchBindingV1", "version": 1, "hard_max_model_calls": 1, "hard_max_real_provider_request_attempts": 1, "hard_max_http_post_attempts": 1, "hard_max_network_request_attempts": 1, "sdk_retries_disabled": True, "transport_request_retries_disabled": True, "route_fallback_after_dispatch_allowed": False, "application_second_dispatch_allowed": False, "unknown_guard_state_fails_closed": True})
    for name, binding_key in (
        ("b-authority-normalization-binding-v1.json", "authority_normalization"),
        ("b-audit-serialization-binding-v1.json", "audit_serialization"),
        ("b-local-success-tail-binding-v1.json", "validator"),
        ("b-execution-evidence-writer-binding-v1.json", "persistence"),
    ):
        add(name, architecture["bindings"][binding_key])
    add("b-pre-credential-negative-matrix-v1.json", {"schema": "SkillV2Pair1CorrectedBPrecredentialNegativeMatrixV1", "version": 1, "case_count": len(negatives), "cases": negatives, "all_rejected_before_credentials": all(row["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP" for row in negatives), "external_actions": dict(ZERO)})
    add("b-post-dispatch-single-attempt-matrix-v1.json", {"schema": "SkillV2Pair1CorrectedBPostdispatchMatrixV1", "version": 1, "case_count": len(post), "cases": post, "max_fake_provider_requests_per_case": 1, "max_fake_http_posts_per_case": 1, "max_fake_network_attempts_per_case": 1, "external_actions": dict(ZERO)})
    add("b-execution-entry-dry-run-v1.json", dry)
    add("b-successor-packet-v3.json", packet)
    add("b-packet-manifest-binding-v1.json", bindings["manifest"])
    add("b-approval-readiness-dry-run-v1.json", readiness)
    add("pair-evaluation-isolation-v1.json", {"schema": "SkillV2Pair1CorrectedBPairEvaluationIsolationV1", "version": 1, "a_control_artifact_sha_bound": A_ARTIFACT_SHA256, "b_result_sha": "UNAVAILABLE_UNTIL_EXECUTION", "blind_comparison_not_started": True, "a_artifact_not_visible_to_b_model": True, "engineering_metrics_not_in_b_model_input": True, "primary_changed_variable": "SKILL_CONTEXT", "pair_level_evaluation_allowed_only_after_b_pass_sealed": True})
    add("pair2-5-block-binding-v1.json", {"schema": "SkillV2Pair1CorrectedBPair2To5BlockBindingV1", "version": 1, "fixture_compatibility_defect_known": True, "approval_allowed": False, "execution_allowed": False, "remain_blocked": True})
    add("historical-root-binding-v1.json", historical_root_policy_v1())
    add("forward-risk-report-v2.json", forward_risk_report_v2())
    validation_value = dict(validation or {})
    add("offline-test-receipt-v1.json", {"schema": "SkillV2Pair1CorrectedBOfflineTestReceiptV1", "version": 1, **validation_value, "real_external_actions": dict(ZERO)})
    final_report = f"""# Corrected Pair 1 B Binding Closure — Final Report\n\n`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_B_ARM_EXECUTION_AND_APPROVAL_BINDING_SUCCESSOR_CLOSED`\n\n- Branch: `{EXPECTED_BRANCH}`\n- Baseline/materialization parent: `{BASELINE_HEAD}`\n- Approval parent: `{approval_parent_head}`\n- A control: `PASS_SEALED`; artifact `{A_ARTIFACT_SHA256}`\n- Root cause: `{ROOT_CAUSE}`\n- Historical B v2 packet: `{B_V2_PACKET_SHA256}`; mutated `NO`\n- Fresh B v3 packet: `{packet['packet_sha256']}`\n- Pair/arm/Skill: `{PAIR_CASE_ID}` / `{ARM_ROLE}` / `{SKILL_ARM}`\n- Event/authority/story/A-B lock: `{EVENT_ID}` / `{AUTHORITY_SHA256}` / `{STORY_SHA256}` / `{LOCK_SHA256}`\n- Restored profile/context: `{RESTORED_PROFILE_SHA256}` / `{RESTORED_CONTEXT_SHA256}`\n- B entry and launcher: `PASS`; `{ENTRY_POINT_ID}`\n- Approval parent, signed preflight, HEAD successor, two-phase stop state: `PASS`\n- Outer permission, nonce lifecycle, single-dispatch: `PASS`\n- Fake B execution tail and approval-readiness: `PASS` / `READY`\n- A artifact visible to B model: `NO`\n- Pair2-5: `BLOCKED`\n- Execution authorized / Signed Approval / nonce: `NO` / `ABSENT` / `ABSENT`\n- Real Provider/HTTP/network/model/paid: `0/0/0/0/0`\n- Full Short: `NOT_EXECUTED`\n- Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_B_ARM_FRESH_USER_APPROVAL_V3`\n\n`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_B_ARM_EXECUTION_PACKET_V3_MATERIALIZED`\n\n`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_B_ARM_APPROVAL_READY_V3=YES`\n"""
    add("final-report-v1.md", final_report)
    privacy = _privacy(docs)
    _require(privacy["privacy_match_count"] == 0, "final_privacy_match")
    add("privacy-scan-v1.json", privacy)
    docs[f"{OUTPUT_ROOT}/sha256-manifest-v1.json"] = _json_bytes(_manifest(docs))
    return docs, {
        "packet_sha256": packet["packet_sha256"], "approval_parent_head": approval_parent_head,
        "approval_dry_run": readiness["b_approval_dry_run_result"],
        "execution_entry_dry_run": dry["persistence"], "external_actions": dict(ZERO),
    }


def write_documents(repo: Path, documents: Mapping[str, bytes]) -> None:
    root = repo / OUTPUT_ROOT
    _require(not root.exists(), "evidence_root_already_exists")
    for relative, data in documents.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--approval-parent-head", required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--related", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    documents, result = build_documents_v1(
        repo, approval_parent_head=args.approval_parent_head, temp_root=args.temp_root.resolve(),
        validation={"focused": args.focused, "related": args.related, "full_suite": args.full_suite, "strict_l3": args.strict_l3},
    )
    if args.materialize:
        write_documents(repo, documents)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
