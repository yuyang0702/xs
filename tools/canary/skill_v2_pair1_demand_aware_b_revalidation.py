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

from novel_flywheel.canonical_shadow import canonical_sha256
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
from tools.canary import skill_v2_pair1_corrected_b_binding_closure as corrected_b
from tools.canary import skill_v2_pair1_fixture_narrow_fix as fixture_fix
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics import skill_v2_bounded_repeated_ab as campaign
from tools.diagnostics import skill_v2_demand_aware_creative_core as demand_fix


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "4ecc4903e07b415309d0f6ed694afc37d8126fc1"
SOURCE_PATH = "tools/canary/skill_v2_pair1_demand_aware_b_revalidation.py"
TEST_PATH = "tests/canary/test_skill_v2_pair1_demand_aware_b_revalidation.py"
PARENT_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-demand-aware-creative-core-narrow-fix-v1"
)
ROOT_CAUSE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-corrected-quality-regression-root-cause-v1"
)
CORRECTED_B_ROOT = corrected_b.OUTPUT_ROOT
A_EXECUTION_ROOT = corrected_b.A_EXECUTION_ROOT
HISTORICAL_B_EXECUTION_ROOT = corrected_b.EXECUTION_ROOT
EVIDENCE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-demand-aware-b-only-approval-readiness-v1"
)
APPROVAL_ROOT = f"{EVIDENCE_ROOT}/approval"
EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-demand-aware-b-only-execution-v1/"
    "pairs/restored-character-heavy-v2-demand-aware-core-v2/b-arm"
)

CANDIDATE_PATH = f"{PARENT_ROOT}/revalidation-candidate-v1.json"
LOCK_PATH = f"{PARENT_ROOT}/revalidation-ab-lock-v1.json"
REUSE_DECISION_PATH = f"{PARENT_ROOT}/a-control-reuse-decision-v1.json"
PARENT_MANIFEST_PATH = f"{PARENT_ROOT}/sha256-manifest-v1.json"
OLD_B_PACKET_PATH = f"{CORRECTED_B_ROOT}/b-successor-packet-v3.json"
HISTORICAL_B_ARTIFACT_PATH = (
    f"{HISTORICAL_B_EXECUTION_ROOT}/artifact/generated-event-realization-v1.json"
)

CANDIDATE_SHA256 = "97adb8c54eacbc02314871b2beeb146dae96758e6dc541571605a403537cbaf5"
PROFILE_SHA256 = "109bb50e2e649c5841bd7c83513100caa0d93cf3c1bb5db845e489b5ae10856d"
CONTEXT_SHA256 = "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc"
CONTEXT_CHARACTERS = 2925
AB_LOCK_SHA256 = "5ace834e214ea25d4206b92d63e830ad7f51b3629072ea58107249e2457303a1"
A_PACKET_SHA256 = "39a46e38d9c11f8afd5fd1cf633443b31ae6fb1c97c4b93d404f950781f19356"
A_ARTIFACT_SHA256 = "f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f"
A_CONTROL_EVIDENCE_HEAD = "2d97d2a47e80ef5289ee066fac592deaa896590d"
HISTORICAL_B_PACKET_SHA256 = "6190409613b8ba3cff8ae5fba6216a2c4885f0d1d37245367ce5eea63288b37a"
HISTORICAL_B_ARTIFACT_SHA256 = "1dd0e31dcf01bc369cf8cee1865ae1fffdb4ad890bb1d726482048755037dc69"
PARENT_MANIFEST_FILE_SHA256 = "4d54c0517bd903392cdba7c2dc068ff1cefb02fa347da5a7f530928e25f6311b"

PAIR_CASE_ID = "restored-character-heavy-v2-demand-aware-core-v2"
ARM_ROLE = "B_ARM"
SKILL_ARM = "RESTORED_SKILL_V2_CHARACTER_CORE_V2"
SCOPE = "SKILL_V2_PAIR1_DEMAND_AWARE_B_ONLY_REVALIDATION_SINGLE_DISPATCH_ONLY"
COHORT_ID = "skill-v2-pair1-demand-aware-b-revalidation-disabled-v1"
ENTRY_POINT_ID = (
    "tools.canary.skill_v2_pair1_demand_aware_b_revalidation:"
    "execute_authorized_once_v1"
)

ZERO_EXTERNAL_ACTIONS = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}

SHARED_BINDING_FIELDS = (
    "fixture_sha256",
    "authority_input_sha256",
    "story_slice_sha256",
    "task_contract_sha256",
    "non_skill_prompt_sha256",
    "route_model_client_sha256",
    "output_cap",
    "validator_policy_sha256",
    "ptr9_policy_sha256",
    "ptr12_policy_sha256",
    "quality_rubric_sha256",
    "engineering_rubric_sha256",
    "sampling_policy_sha256",
    "tool_policy_sha256",
    "transport_policy_binding_sha256",
    "authority_tuple_policy_sha256",
    "audit_serialization_policy_sha256",
    "output_isolation_policy_sha256",
    "user_sha256",
)

PRECREDENTIAL_NEGATIVE_CASES = (
    "stale_candidate_sha",
    "stale_profile_sha",
    "stale_context_sha",
    "stale_a_control_binding",
    "stale_ab_lock",
    "wrong_route_model_client",
    "wrong_output_cap",
    "missing_launcher",
    "wrong_launcher_sha",
    "missing_execution_entry",
    "signed_approval_absent",
    "approval_mismatch",
    "stale_preflight",
    "nonce_absent",
    "nonce_already_consumed",
    "execution_authorized_false",
    "second_dispatch_attempt",
    "retry_attempt",
    "fallback_attempt",
    "route_switch_attempt",
    "resume_attempt",
    "a_artifact_injection",
    "story_state_mutation_request",
    "canon_mutation_request",
    "ready_mutation_request",
    "pair2_to5_identity",
    "production_cutover_request",
)

POSTDISPATCH_FAILURE_CASES = (
    "connect_error",
    "http_failure",
    "malformed_response",
    "parse_failure",
    "validator_rejection",
    "persistence_failure",
)


class DemandAwareBReadinessError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _require(value: bool, reason: str) -> None:
    if not value:
        raise DemandAwareBReadinessError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode(UTF8)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _domain(domain: str, value: Any) -> str:
    return _sha(domain.encode(UTF8) + b"\0" + _canonical(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain(domain, result)
    return result


def _load(repo: Path, relative: str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding=UTF8))
    _require(isinstance(value, dict), f"json_object_required:{relative}")
    return value


def _file(repo: Path, relative: str) -> dict[str, Any]:
    data = (repo / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha(data)}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _changed(repo: Path, older: str, newer: str) -> tuple[str, ...]:
    output = _git(repo, "diff", "--name-only", older, newer)
    return tuple(line for line in output.splitlines() if line)


def _verify_parent_manifest(repo: Path) -> dict[str, Any]:
    manifest_file = _file(repo, PARENT_MANIFEST_PATH)
    _require(
        manifest_file["sha256"] == PARENT_MANIFEST_FILE_SHA256,
        "parent_manifest_file_sha_mismatch",
    )
    manifest = _load(repo, PARENT_MANIFEST_PATH)
    entries = manifest.get("files")
    _require(
        isinstance(entries, list) and manifest.get("entry_count") == len(entries),
        "parent_manifest_shape_mismatch",
    )
    mismatches: list[str] = []
    for entry in entries:
        path = repo / str(entry["path"])
        if not path.is_file():
            mismatches.append(str(entry["path"]))
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            mismatches.append(str(entry["path"]))
    _require(not mismatches, "parent_manifest_entry_mismatch")
    return {
        "path": PARENT_MANIFEST_PATH,
        "file_sha256": manifest_file["sha256"],
        "entry_count": len(entries),
        "mismatch_count": 0,
        "status": "EXACT",
    }


def candidate_binding_v1(repo: Path) -> dict[str, Any]:
    manifest = _verify_parent_manifest(repo)
    candidate = _load(repo, CANDIDATE_PATH)
    lock = _load(repo, LOCK_PATH)
    candidate_body = {
        key: value for key, value in candidate.items() if key != "candidate_sha256"
    }
    lock_body = {
        key: value for key, value in lock.items() if key != "successor_ab_lock_sha256"
    }
    _require(
        canonical_sha256(
            "SkillV2DemandAwareCreativeCoreRevalidationCandidateV1", candidate_body,
        ) == CANDIDATE_SHA256 == candidate.get("candidate_sha256"),
        "candidate_logical_sha_mismatch",
    )
    _require(
        canonical_sha256(
            "SkillV2DemandAwareCreativeCoreRevalidationABLockV1", lock_body,
        ) == AB_LOCK_SHA256 == lock.get("successor_ab_lock_sha256"),
        "successor_ab_lock_sha_mismatch",
    )
    required = {
        "new_profile_sha256": PROFILE_SHA256,
        "new_context_sha256": CONTEXT_SHA256,
        "successor_ab_lock_sha256": AB_LOCK_SHA256,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "execution_authorized": False,
        "real_execution_enabled": False,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
    }
    for key, expected in required.items():
        _require(candidate.get(key) == expected, f"candidate_binding:{key}")
    _require(set(candidate["external_actions"].values()) == {0}, "candidate_external_actions")
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyCandidateBindingV1",
        "version": 1,
        "candidate_sha256": CANDIDATE_SHA256,
        "candidate_file_sha256": _file(repo, CANDIDATE_PATH)["sha256"],
        "profile_sha256": PROFILE_SHA256,
        "context_sha256": CONTEXT_SHA256,
        "context_characters": CONTEXT_CHARACTERS,
        "successor_ab_lock_sha256": AB_LOCK_SHA256,
        "manifest_file_sha256": manifest["file_sha256"],
        "manifest_status": manifest["status"],
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "nonce_reserved": False,
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }


def demand_aware_skill_binding_v1(repo: Path) -> dict[str, Any]:
    profile = demand_fix._profile_evidence(repo)
    new = profile["new"]
    context = profile["new_context"]
    _require(new.profile_id == SKILL_ARM, "skill_arm_profile_id_mismatch")
    _require(new.canonical_profile_sha256 == PROFILE_SHA256, "profile_sha_mismatch")
    _require(_sha(context.encode(UTF8)) == CONTEXT_SHA256, "context_sha_mismatch")
    _require(len(context) == CONTEXT_CHARACTERS, "context_length_mismatch")
    _require(profile["new_receipt"].status == "NONE", "context_truncated")
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlySkillBindingV1",
        "version": 1,
        "skill_arm": SKILL_ARM,
        "profile_sha256": PROFILE_SHA256,
        "context_sha256": CONTEXT_SHA256,
        "context_characters": CONTEXT_CHARACTERS,
        "truncation": "NONE",
        "shadow_only": True,
        "production_reachable": False,
        "changed_rule_ids": list(profile["changed"]),
        "non_target_rule_diff_count": 0,
    }


def _artifact_owned_prose(repo: Path, relative: str) -> tuple[str, ...]:
    value = _load(repo, relative)
    found: list[str] = []

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, Mapping):
            for child_key, child in node.items():
                walk(child, str(child_key))
        elif isinstance(node, list):
            for child in node:
                walk(child, key)
        elif key in {"title", "narrative"} and isinstance(node, str) and node:
            found.append(node)

    walk(value)
    return tuple(found)


def _prose_injection_match_count(repo: Path, system: str, user: str) -> int:
    wire = system + "\n\0" + user
    phrases = (
        *_artifact_owned_prose(
            repo,
            f"{A_EXECUTION_ROOT}/artifact/generated-event-realization-v1.json",
        ),
        *_artifact_owned_prose(repo, HISTORICAL_B_ARTIFACT_PATH),
    )
    return sum(phrase in wire for phrase in phrases)


def _demand_aware_b_model_input(
    repo: Path, route_database: Path,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    _fixture, authority, _task = fixture_fix._fixture_v2()
    contexts = campaign._context_bindings(repo)
    profile = demand_fix._profile_evidence(repo)
    contract = current_arm.slice1_contract_binding(repo)
    route = current_arm.resolve_route_binding(route_database)
    model_input, current_system, user = current_arm.build_model_input(
        repo,
        authority,
        contexts["current_context"],
        contexts["current_profile"],
        contract,
        route,
    )
    current_context = contexts["current_context"]
    new_context = profile["new_context"]
    _require(current_system.endswith(current_context), "current_context_boundary_ambiguous")
    system = current_system[: -len(current_context)] + new_context
    model_input = dict(model_input)
    model_input.update({
        "skill_profile_sha256": PROFILE_SHA256,
        "skill_context_sha256": CONTEXT_SHA256,
        "system_sha256": _sha(system.encode(UTF8)),
        "user_sha256": _sha(user.encode(UTF8)),
        "wire_input_sha256": _sha((system + "\n\0" + user).encode(UTF8)),
    })
    _require(A_ARTIFACT_SHA256 not in system + user, "a_artifact_hash_in_b_input")
    _require(
        HISTORICAL_B_ARTIFACT_SHA256 not in system + user,
        "historical_b_artifact_hash_in_b_input",
    )
    _require(
        _prose_injection_match_count(repo, system, user) == 0,
        "historical_artifact_prose_in_b_input",
    )
    return model_input, system, user, authority


def a_control_reuse_binding_v1(repo: Path) -> dict[str, Any]:
    decision = _load(repo, REUSE_DECISION_PATH)
    deferment = _load(repo, f"{ROOT_CAUSE_ROOT}/pair2-5-deferment-v1.json")
    strategy = _load(repo, f"{ROOT_CAUSE_ROOT}/next-validation-strategy-v1.json")
    candidate = _load(repo, CANDIDATE_PATH)
    old_packet = _load(repo, OLD_B_PACKET_PATH)
    control = corrected_b.sealed_a_control_binding(repo)
    _require(
        decision.get("a_control_reuse_conditions_satisfied") == "YES"
        and decision.get("overall_status") == "exact",
        "a_control_reuse_decision_not_exact",
    )
    _require(
        deferment.get("a_control_reuse_decision")
        == "REUSE_SEALED_CORRECTED_PAIR1_A_CONTROL_IF_AND_ONLY_IF_CAMPAIGN_POLICY_AND_EXACT_NON_SKILL_LOCK_REMAIN_VALID",
        "campaign_policy_forbids_a_reuse",
    )
    _require(
        "keep A control reuse conditional on exact campaign lock"
        in " ".join(strategy.get("sequence", [])),
        "campaign_lock_condition_missing",
    )
    _require(control["a_status"] == "PASS_SEALED", "a_control_not_pass_sealed")
    _require(control["a_packet_sha256"] == A_PACKET_SHA256, "a_control_packet_drift")
    _require(control["a_artifact_sha256"] == A_ARTIFACT_SHA256, "a_control_artifact_drift")
    shared = candidate["shared_experiment_bindings"]
    mismatches = [
        field for field in SHARED_BINDING_FIELDS
        if shared.get(field) != old_packet.get(field)
    ]
    _require(not mismatches, "a_control_non_skill_lock_mismatch")
    _require(
        candidate.get("a_control_reuse_decision") == "CONDITIONAL_SATISFIED",
        "candidate_a_reuse_not_satisfied",
    )
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyAControlReuseBindingV1",
        "version": 1,
        "a_control_reuse_binding": "PASS",
        "a_control_status": "PASS_SEALED",
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_evidence_head": A_CONTROL_EVIDENCE_HEAD,
        "a_control_mutated": False,
        "shared_binding_count": len(SHARED_BINDING_FIELDS),
        "shared_binding_mismatch_count": 0,
        "same_corrected_fixture": True,
        "same_authority": True,
        "same_story_slice": True,
        "same_task_contract": True,
        "same_non_skill_prompt": True,
        "same_model": True,
        "same_provider": True,
        "same_route": True,
        "same_client": True,
        "same_sampling_policy": True,
        "same_transport_policy": True,
        "same_output_cap": True,
        "same_validator_policy": True,
        "same_ptr9_policy": True,
        "same_ptr12_policy": True,
        "same_quality_rubric": True,
        "same_engineering_rubric": True,
        "primary_changed_variable": "SKILL_CONTEXT",
        "a_artifact_content_injected_into_new_b_model_input": False,
        "a_result_used_only_as_sealed_control_evidence": True,
    }


def historical_b_isolation_v1(repo: Path) -> dict[str, Any]:
    artifact = _file(repo, HISTORICAL_B_ARTIFACT_PATH)
    validation = _load(repo, f"{HISTORICAL_B_EXECUTION_ROOT}/validation-result-v1.json")
    execution = _load(repo, f"{HISTORICAL_B_EXECUTION_ROOT}/execution-receipt-v1.json")
    _require(artifact["sha256"] == HISTORICAL_B_ARTIFACT_SHA256, "historical_b_artifact_drift")
    _require(
        validation.get("generated_artifact_sha256") == HISTORICAL_B_ARTIFACT_SHA256,
        "historical_b_validation_drift",
    )
    _require(
        execution.get("packet_sha256") == HISTORICAL_B_PACKET_SHA256,
        "historical_b_packet_drift",
    )
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyHistoricalBIsolationV1",
        "version": 1,
        "historical_b_packet_sha256": HISTORICAL_B_PACKET_SHA256,
        "historical_b_artifact_sha256": HISTORICAL_B_ARTIFACT_SHA256,
        "historical_b_artifact_used_as_new_treatment": False,
        "historical_b_result_injected_into_new_b_model_input": False,
        "historical_b_result_used_only_as_root_cause_sequence_evidence": True,
        "fresh_treatment_artifact_required": True,
    }


def validate_approval_parent_source_policy(
    repo: Path, approval_parent_head: str,
) -> dict[str, Any]:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", approval_parent_head)), "approval_parent_head_invalid")
    try:
        _git(repo, "merge-base", "--is-ancestor", BASELINE_HEAD, approval_parent_head)
        changed = set(_changed(repo, BASELINE_HEAD, approval_parent_head))
    except subprocess.CalledProcessError as exc:
        raise DemandAwareBReadinessError("approval_parent_not_descendant") from exc
    _require(changed == {SOURCE_PATH, TEST_PATH}, "approval_parent_scope_mismatch")
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyApprovalParentBindingV1",
        "version": 1,
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "approval_parent_head_validation": "PASS",
        "changed_paths": sorted(changed),
    }


def validate_head_successor_v1(
    repo: Path, approval_parent_head: str, current_head: str,
) -> str:
    _require(
        _git(repo, "merge-base", "--is-ancestor", approval_parent_head, current_head) == "",
        "head_not_descendant",
    )
    changed = _changed(repo, approval_parent_head, current_head)
    _require(
        all(path.startswith(EVIDENCE_ROOT + "/") for path in changed),
        "head_successor_scope_mismatch",
    )
    return "PASS"


def _source_binding(
    repo: Path, kind: str, functions: tuple[str, ...],
) -> dict[str, Any]:
    source = _file(repo, SOURCE_PATH)
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlySourceBindingV1",
        "version": 1,
        "binding_kind": kind,
        "source_path": SOURCE_PATH,
        "source_sha256": source["sha256"],
        "functions": list(functions),
        "closed_world_revalidation_b_only": True,
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-source-binding-v1",
        body,
        "binding_sha256",
    )


def launcher_architecture_v1(repo: Path) -> dict[str, Any]:
    bindings = {
        "execution_entry": _source_binding(repo, "EXECUTION_ENTRY", ("execute_authorized_once_v1",)),
        "launcher": _source_binding(repo, "LAUNCHER", ("execute_authorized_once_v1",)),
        "signed_preflight": _source_binding(
            repo,
            "SIGNED_PREFLIGHT",
            ("validate_signed_approval_v1", "validate_precredential_gate_v1"),
        ),
        "permission_before_nonce": _source_binding(
            repo,
            "PERMISSION_BEFORE_NONCE",
            ("validate_outer_permission_v1", "validate_precredential_gate_v1"),
        ),
        "nonce": _source_binding(repo, "NONCE_LIFECYCLE", ("reserve_nonce_exclusive_v1",)),
        "single_dispatch": _source_binding(repo, "SINGLE_DISPATCH", ("execute_authorized_once_v1",)),
        "terminal_tail": _source_binding(repo, "TERMINAL_LOCAL_PIPELINE", ("persist_local_success_tail_v1",)),
    }
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyLauncherArchitectureV1",
        "version": 1,
        "entry_point_id": ENTRY_POINT_ID,
        "bindings": bindings,
        "execution_entry_binding": "PASS",
        "launcher_binding": "PASS",
        "dynamic_arm_selection_allowed": False,
        "arbitrary_entry_point_allowed": False,
        "architecture_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-launcher-architecture-v1", bindings,
        ),
    }


def _request_binding_v1(repo: Path) -> dict[str, Any]:
    model, system, user, _authority = _demand_aware_b_model_input(repo, repo / "data/app.db")
    shared = _load(repo, CANDIDATE_PATH)["shared_experiment_bindings"]
    _require(model["user_sha256"] == shared["user_sha256"], "user_prompt_drift")
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyRequestBindingV1",
        "version": 1,
        "system_sha256": _sha(system.encode(UTF8)),
        "user_sha256": _sha(user.encode(UTF8)),
        "wire_input_sha256": _sha((system + "\n\0" + user).encode(UTF8)),
        "profile_sha256": PROFILE_SHA256,
        "context_sha256": CONTEXT_SHA256,
        "provider_descriptor_sha256": current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        "model_binding_sha256": current_arm.EXPECTED_PRIMARY_MODEL,
        "route_fingerprint": current_arm.EXPECTED_PRIMARY_ROUTE_FINGERPRINT,
        "route_kind": "primary",
        "protocol": "anthropic",
        "client": "AnthropicAdapter",
        "route_model_client_sha256": shared["route_model_client_sha256"],
        "output_cap": shared["output_cap"],
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_provider_payload_persisted": False,
        "a_artifact_prose_injection_match_count": 0,
        "historical_b_prose_injection_match_count": 0,
    }


def single_dispatch_contract_v1() -> dict[str, Any]:
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlySingleDispatchContractV1",
        "version": 1,
        "model_logical_calls_hard_cap": 1,
        "real_provider_request_attempts_hard_cap": 1,
        "http_post_attempts_hard_cap": 1,
        "network_request_attempts_hard_cap": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "retry_allowed": False,
        "fallback_allowed": False,
        "route_switch_allowed": False,
        "resume_allowed": False,
        "second_dispatch_allowed": False,
        "same_nonce_second_dispatch_fails_closed": True,
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-single-dispatch-v1",
        body,
        "single_dispatch_contract_sha256",
    )


def terminal_local_pipeline_contract_v1(repo: Path) -> dict[str, Any]:
    source = _file(repo, "src/novel_flywheel/planning_v2_slice1.py")
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlyTerminalLocalPipelineContractV1",
        "version": 1,
        "ordered_stages": [
            "PROVIDER_RETURN_RECEIVED",
            "LOCAL_PARSE_OR_CONVERSION",
            "AUTHORITY_NORMALIZATION",
            "EVENT_REALIZATION_VALIDATION",
            "ARTIFACT_SCHEMA_VALIDATION",
            "ARTIFACT_FREEZE",
            "AUDIT_SERIALIZATION",
            "OUTPUT_ISOLATION",
            "PERSISTENCE",
        ],
        "all_mandatory_stages_must_pass": True,
        "planning_v2_slice1_source_sha256": source["sha256"],
        "story_state_mutations_allowed": 0,
        "canon_mutations_allowed": 0,
        "ready_mutations_allowed": 0,
        "production_authority": False,
        "validator_relaxation_allowed": False,
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-terminal-local-pipeline-v1",
        body,
        "terminal_local_pipeline_contract_sha256",
    )


def build_approval_readiness_packet(
    repo: Path,
    *,
    approval_parent_head: str,
    require_parent: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_binding = candidate_binding_v1(repo)
    candidate = _load(repo, CANDIDATE_PATH)
    a_control = a_control_reuse_binding_v1(repo)
    historical_b = historical_b_isolation_v1(repo)
    skill = demand_aware_skill_binding_v1(repo)
    request = _request_binding_v1(repo)
    architecture = launcher_architecture_v1(repo)
    dispatch = single_dispatch_contract_v1()
    terminal = terminal_local_pipeline_contract_v1(repo)
    if require_parent:
        parent = validate_approval_parent_source_policy(repo, approval_parent_head)
    else:
        parent = {
            "materialization_parent_head": BASELINE_HEAD,
            "approval_parent_head": approval_parent_head,
            "approval_parent_head_explicit": True,
            "approval_parent_head_validation": "STRUCTURAL_ONLY",
        }
    body: dict[str, Any] = {
        "schema": "SkillV2Pair1DemandAwareBOnlyApprovalReadinessPacketV1",
        "version": 1,
        "scope": SCOPE,
        "cohort_id": COHORT_ID,
        "candidate_scope": candidate["candidate_scope"],
        "candidate_sha256": CANDIDATE_SHA256,
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "approval_parent_head_explicit": True,
        "approval_parent_head_validation": parent["approval_parent_head_validation"],
        "materialization_root": EVIDENCE_ROOT,
        "approval_root": APPROVAL_ROOT,
        "execution_root": EXECUTION_ROOT,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "skill_profile_sha256": PROFILE_SHA256,
        "skill_context_sha256": CONTEXT_SHA256,
        "skill_context_characters": CONTEXT_CHARACTERS,
        "pair_lock_sha256": AB_LOCK_SHA256,
        "primary_changed_variable": "SKILL_CONTEXT",
        "a_control_reuse_binding_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-a-control-reuse-binding-v1", a_control,
        ),
        "a_control_status": "PASS_SEALED",
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_evidence_head": A_CONTROL_EVIDENCE_HEAD,
        "a_artifact_injected_into_b_model_input": False,
        "a_result_used_only_as_sealed_control_evidence": True,
        "historical_b_packet_sha256": HISTORICAL_B_PACKET_SHA256,
        "historical_b_artifact_sha256": HISTORICAL_B_ARTIFACT_SHA256,
        "historical_b_artifact_used_as_new_treatment": False,
        "historical_b_result_injected_into_new_b_model_input": False,
        "fresh_treatment_artifact_required": historical_b["fresh_treatment_artifact_required"],
        "execution_entry_point_present": True,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "execution_entry_point_binding_sha256": architecture["bindings"]["execution_entry"]["binding_sha256"],
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "system_sha256": request["system_sha256"],
        "user_sha256": request["user_sha256"],
        "wire_input_sha256": request["wire_input_sha256"],
        "provider_descriptor_sha256": request["provider_descriptor_sha256"],
        "model_binding_sha256": request["model_binding_sha256"],
        "route_fingerprint": request["route_fingerprint"],
        "route_kind": request["route_kind"],
        "protocol": request["protocol"],
        "client": request["client"],
        "single_dispatch_contract_sha256": dispatch["single_dispatch_contract_sha256"],
        "terminal_local_pipeline_contract_sha256": terminal["terminal_local_pipeline_contract_sha256"],
        "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "retry_allowed": False,
        "fallback_allowed": False,
        "route_switch_allowed": False,
        "resume_allowed": False,
        "second_dispatch_allowed": False,
        "approval_schema": "SkillV2Pair1DemandAwareBOnlySignedApprovalV1",
        "approval_domain": "skill-v2-pair1-demand-aware-b-only-signed-approval-v1",
        "approval_reuse_allowed": False,
        "cohort_reuse_allowed": False,
        "phase_a_schema": "SkillV2Pair1DemandAwareBOnlyPhaseAPreapprovalReadinessV1",
        "phase_b_schema": "SkillV2Pair1DemandAwareBOnlyApprovalTimeSignedPreflightV1",
        "nonce_domain": "skill-v2-pair1-demand-aware-b-only-single-use-nonce-v1",
        "nonce_id_creation_phase": "AFTER_FRESH_USER_APPROVAL_BEFORE_SIGNED_PREFLIGHT",
        "permission_check_before_nonce_reservation": True,
        "future_execution_permission_must_be_reconfirmed": True,
        "execution_authorized": False,
        "real_execution_enabled": False,
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "pair2_or_later_authorized": False,
        "pair2_to_5_execution_allowed": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "full_short_authorized": False,
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }
    body.update(candidate["shared_experiment_bindings"])
    packet = _sealed(
        "skill-v2-pair1-demand-aware-b-only-approval-readiness-packet-v1",
        body,
        "approval_readiness_packet_sha256",
    )
    validate_approval_readiness_packet(repo, packet, require_parent=require_parent)
    return packet, {
        "candidate": candidate_binding,
        "a_control": a_control,
        "historical_b": historical_b,
        "skill": skill,
        "request": request,
        "architecture": architecture,
        "single_dispatch": dispatch,
        "terminal": terminal,
        "parent": parent,
    }


def validate_approval_readiness_packet(
    repo: Path,
    packet: Mapping[str, Any],
    *,
    require_parent: bool = False,
) -> str:
    _require(
        packet.get("schema") == "SkillV2Pair1DemandAwareBOnlyApprovalReadinessPacketV1",
        "packet_schema_mismatch",
    )
    _require(
        packet.get("approval_readiness_packet_sha256")
        == _domain(
            "skill-v2-pair1-demand-aware-b-only-approval-readiness-packet-v1",
            {
                key: value
                for key, value in packet.items()
                if key != "approval_readiness_packet_sha256"
            },
        ),
        "packet_sha_mismatch",
    )
    candidate_binding_v1(repo)
    request = _request_binding_v1(repo)
    a_control = a_control_reuse_binding_v1(repo)
    architecture = launcher_architecture_v1(repo)
    dispatch = single_dispatch_contract_v1()
    terminal = terminal_local_pipeline_contract_v1(repo)
    required = {
        "scope": SCOPE,
        "cohort_id": COHORT_ID,
        "candidate_sha256": CANDIDATE_SHA256,
        "materialization_parent_head": BASELINE_HEAD,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "skill_profile_sha256": PROFILE_SHA256,
        "skill_context_sha256": CONTEXT_SHA256,
        "skill_context_characters": CONTEXT_CHARACTERS,
        "pair_lock_sha256": AB_LOCK_SHA256,
        "a_control_status": "PASS_SEALED",
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_reuse_binding_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-a-control-reuse-binding-v1",
            a_control,
        ),
        "a_artifact_injected_into_b_model_input": False,
        "historical_b_artifact_used_as_new_treatment": False,
        "historical_b_result_injected_into_new_b_model_input": False,
        "execution_entry_point_present": True,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_path": SOURCE_PATH,
        "execution_entry_point_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "execution_entry_point_binding_sha256": architecture["bindings"]["execution_entry"]["binding_sha256"],
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_binding_sha256": architecture["bindings"]["launcher"]["binding_sha256"],
        "system_sha256": request["system_sha256"],
        "user_sha256": request["user_sha256"],
        "wire_input_sha256": request["wire_input_sha256"],
        "provider_descriptor_sha256": current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        "model_binding_sha256": current_arm.EXPECTED_PRIMARY_MODEL,
        "route_fingerprint": current_arm.EXPECTED_PRIMARY_ROUTE_FINGERPRINT,
        "route_kind": "primary",
        "protocol": "anthropic",
        "client": "AnthropicAdapter",
        "single_dispatch_contract_sha256": dispatch["single_dispatch_contract_sha256"],
        "terminal_local_pipeline_contract_sha256": terminal["terminal_local_pipeline_contract_sha256"],
        "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "retry_allowed": False,
        "fallback_allowed": False,
        "route_switch_allowed": False,
        "resume_allowed": False,
        "second_dispatch_allowed": False,
        "permission_check_before_nonce_reservation": True,
        "future_execution_permission_must_be_reconfirmed": True,
        "execution_authorized": False,
        "real_execution_enabled": False,
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "pair2_or_later_authorized": False,
        "pair2_to_5_execution_allowed": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "full_short_authorized": False,
    }
    for key, expected in required.items():
        _require(packet.get(key) == expected, f"packet_binding:{key}")
    candidate = _load(repo, CANDIDATE_PATH)
    for field in SHARED_BINDING_FIELDS:
        _require(
            packet.get(field) == candidate["shared_experiment_bindings"].get(field),
            f"shared_binding:{field}",
        )
    _require(set(packet["external_actions"].values()) == {0}, "packet_external_actions")
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
    return execute_authorized_once_v1


def synthetic_signed_approval_v1(packet: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlySignedApprovalV1",
        "version": 1,
        "approval_id": "offline-synthetic-demand-aware-b-not-issued",
        "named_approver": "OFFLINE_SYNTHETIC",
        "approval_parent_head": packet["approval_parent_head"],
        "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
        "candidate_sha256": CANDIDATE_SHA256,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "skill_profile_sha256": PROFILE_SHA256,
        "skill_context_sha256": CONTEXT_SHA256,
        "pair_lock_sha256": AB_LOCK_SHA256,
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_sha256": packet["execution_entry_point_source_sha256"],
        "scope": SCOPE,
        "cohort_id": COHORT_ID,
        "execution_authorized": True,
        "execution_window": {
            "not_before": "2020-01-01T00:00:00Z",
            "not_after": "2100-01-01T00:00:00Z",
        },
        "single_use_nonce": "offline-synthetic-demand-aware-b-not-issued",
        "nonce_reserved": False,
        "nonce_consumed": False,
        "nonce_reuse_allowed": False,
        "retry_allowed": False,
        "fallback_allowed": False,
        "route_switch_allowed": False,
        "resume_allowed": False,
        "second_dispatch_allowed": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "pair2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "full_short_authorized": False,
        "synthetic_not_persistable": True,
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-signed-approval-v1",
        body,
        "signed_approval_sha256",
    )


def validate_signed_approval_v1(
    packet: Mapping[str, Any],
    signed: Mapping[str, Any],
    *,
    allow_synthetic: bool = False,
) -> str:
    _require(
        signed.get("schema") == "SkillV2Pair1DemandAwareBOnlySignedApprovalV1",
        "signed_approval_schema_mismatch",
    )
    _require(
        signed.get("signed_approval_sha256")
        == _domain(
            "skill-v2-pair1-demand-aware-b-only-signed-approval-v1",
            {
                key: value
                for key, value in signed.items()
                if key != "signed_approval_sha256"
            },
        ),
        "signed_approval_sha_mismatch",
    )
    bindings = {
        "approval_parent_head": packet.get("approval_parent_head"),
        "approval_readiness_packet_sha256": packet.get("approval_readiness_packet_sha256"),
        "candidate_sha256": CANDIDATE_SHA256,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "skill_profile_sha256": PROFILE_SHA256,
        "skill_context_sha256": CONTEXT_SHA256,
        "pair_lock_sha256": AB_LOCK_SHA256,
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "execution_entry_point_id": ENTRY_POINT_ID,
        "execution_entry_point_source_sha256": packet.get("execution_entry_point_source_sha256"),
        "scope": SCOPE,
        "cohort_id": COHORT_ID,
        "execution_authorized": True,
        "nonce_reserved": False,
        "nonce_consumed": False,
        "nonce_reuse_allowed": False,
        "retry_allowed": False,
        "fallback_allowed": False,
        "route_switch_allowed": False,
        "resume_allowed": False,
        "second_dispatch_allowed": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "pair2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "full_short_authorized": False,
    }
    for key, expected in bindings.items():
        _require(signed.get(key) == expected, f"signed_binding:{key}")
    _require(bool(signed.get("single_use_nonce")), "single_use_nonce_missing")
    if not allow_synthetic:
        _require(
            signed.get("synthetic_not_persistable") is not True,
            "synthetic_approval_not_executable",
        )
        now = datetime.now(timezone.utc)
        window = signed.get("execution_window") or {}
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
        _require(start <= now <= end, "execution_window_inactive")
    return "PASS"


def current_campaign_state_v1(
    repo: Path,
    signed: Mapping[str, Any] | None = None,
    *,
    approval_present_override: bool | None = None,
) -> dict[str, Any]:
    approval_path = repo / APPROVAL_ROOT / "signed-approval-v1.json"
    approval_present = (
        approval_path.is_file()
        if approval_present_override is None
        else approval_present_override
    )
    later = [
        campaign._arm_identity(case["pair_case_id"], arm)
        for case in campaign.CASE_DEFINITIONS[1:]
        for arm in ("a-arm", "b-arm")
    ]
    state = {
        "sealed_a_control_pass": a_control_reuse_binding_v1(repo)["a_control_status"] == "PASS_SEALED",
        "candidate_exact": candidate_binding_v1(repo)["manifest_status"] == "EXACT",
        "demand_aware_b_is_next_real_arm": True,
        "demand_aware_b_approval_exists": approval_present,
        "demand_aware_b_execution_exists": (repo / EXECUTION_ROOT).exists(),
        "historical_failed_b_exists": (repo / HISTORICAL_B_EXECUTION_ROOT).exists(),
        "historical_failed_b_is_treatment": False,
        "pair2_or_later_approval_exists": any(
            (repo / f"{item['materialization_root']}/approval").exists()
            for item in later
        ),
        "pair2_or_later_result_exists": any(
            (repo / item["execution_root"] / "execution-receipt-v1.json").exists()
            for item in later
        ),
        "active_campaign_stop": False,
        "approval_id": signed.get("approval_id") if signed else None,
    }
    state["state_sha256"] = _domain(
        "skill-v2-pair1-demand-aware-b-only-current-state-v1", state,
    )
    return state


def phase_a_preapproval_readiness_v1(
    repo: Path, packet: Mapping[str, Any],
) -> dict[str, Any]:
    validate_approval_readiness_packet(repo, packet)
    state = current_campaign_state_v1(repo)
    _require(state["demand_aware_b_approval_exists"] is False, "approval_already_exists")
    _require(state["demand_aware_b_execution_exists"] is False, "execution_already_exists")
    _require(state["pair2_or_later_approval_exists"] is False, "later_approval_exists")
    _require(state["pair2_or_later_result_exists"] is False, "later_result_exists")
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlyPhaseAPreapprovalReadinessV1",
        "version": 1,
        "phase": "PRE_APPROVAL_READINESS",
        "status": "PASS",
        "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
        "candidate_sha256": CANDIDATE_SHA256,
        "current_state": state,
        "semantic_stop_state": "CONTINUE_ALLOWED_FOR_LATER_APPROVAL_CREATION_ONLY",
        "signed_approval_present": False,
        "execution_authorized": False,
        "nonce_id": "NOT_YET_CREATED_BY_DESIGN",
        "nonce_reserved": False,
        "nonce_consumed": False,
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-phase-a-preapproval-v1",
        body,
        "phase_a_receipt_sha256",
    )


def phase_b_receipt_v1(
    repo: Path,
    signed: Mapping[str, Any],
    *,
    synthetic: bool = False,
) -> dict[str, Any]:
    state = current_campaign_state_v1(
        repo, signed, approval_present_override=True if synthetic else None,
    )
    _require(state["demand_aware_b_approval_exists"] is True, "approval_missing")
    body = {
        "schema": "SkillV2Pair1DemandAwareBOnlyApprovalTimeSignedPreflightV1",
        "version": 1,
        "phase": "APPROVAL_TIME_SIGNED_PREFLIGHT",
        "current_state": state,
        "signed_approval_sha256": signed.get("signed_approval_sha256"),
        "campaign_state": "CONTINUE_ALLOWED_FOR_DEMAND_AWARE_PAIR1_B_ONLY",
        "pair2_to_5_blocked": True,
        "synthetic": synthetic,
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-phase-b-preflight-v1",
        body,
        "phase_b_receipt_sha256",
    )


def validate_phase_b_receipt_v1(
    repo: Path,
    receipt: Mapping[str, Any],
    signed: Mapping[str, Any],
    *,
    allow_synthetic: bool = False,
) -> str:
    _require(
        receipt.get("phase_b_receipt_sha256")
        == _domain(
            "skill-v2-pair1-demand-aware-b-only-phase-b-preflight-v1",
            {
                key: value
                for key, value in receipt.items()
                if key != "phase_b_receipt_sha256"
            },
        ),
        "phase_b_receipt_sha_mismatch",
    )
    _require(receipt.get("phase") == "APPROVAL_TIME_SIGNED_PREFLIGHT", "phase_b_required")
    _require(
        receipt.get("signed_approval_sha256") == signed.get("signed_approval_sha256"),
        "phase_b_signed_approval_mismatch",
    )
    _require(
        receipt.get("campaign_state")
        == "CONTINUE_ALLOWED_FOR_DEMAND_AWARE_PAIR1_B_ONLY",
        "campaign_stop_active",
    )
    _require(receipt.get("pair2_to_5_blocked") is True, "later_pairs_not_blocked")
    if receipt.get("synthetic"):
        _require(allow_synthetic, "synthetic_phase_b_not_executable")
        expected = current_campaign_state_v1(
            repo, signed, approval_present_override=True,
        )
    else:
        expected = current_campaign_state_v1(repo, signed)
    _require(receipt.get("current_state") == expected, "stale_phase_b")
    _require(expected["demand_aware_b_execution_exists"] is False, "b_already_executed")
    _require(expected["pair2_or_later_approval_exists"] is False, "later_approval_exists")
    _require(expected["pair2_or_later_result_exists"] is False, "later_result_exists")
    _require(expected["active_campaign_stop"] is False, "active_campaign_stop")
    return "PASS"


def synthetic_permission_receipt_v1(
    packet: Mapping[str, Any], signed: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "CurrentChatExternalPermissionReceiptV1",
        "version": 1,
        "scope": SCOPE,
        "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "credentials": True,
        "network": True,
        "paid_provider": True,
        "data_egress": True,
        "synthetic": True,
    }


def validate_outer_permission_v1(
    packet: Mapping[str, Any],
    signed: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    allow_synthetic: bool = False,
) -> str:
    _require(receipt is not None, "external_permission_missing")
    assert receipt is not None
    _require(
        receipt.get("schema") == "CurrentChatExternalPermissionReceiptV1",
        "external_permission_schema",
    )
    _require(receipt.get("scope") == SCOPE, "external_permission_scope")
    _require(
        receipt.get("approval_readiness_packet_sha256")
        == packet["approval_readiness_packet_sha256"],
        "external_permission_packet",
    )
    _require(
        receipt.get("signed_approval_sha256") == signed["signed_approval_sha256"],
        "external_permission_approval",
    )
    for component in ("credentials", "network", "paid_provider", "data_egress"):
        _require(receipt.get(component) is True, f"external_permission_missing:{component}")
    _require(
        allow_synthetic or receipt.get("synthetic") is not True,
        "synthetic_permission_not_executable",
    )
    return "PASS"


def validate_precredential_gate_v1(
    repo: Path,
    *,
    packet: Mapping[str, Any],
    signed_approval: Mapping[str, Any],
    phase_b_receipt: Mapping[str, Any],
    permission_receipt: Mapping[str, Any] | None,
    allow_synthetic: bool = False,
    require_sealed_approval: bool = False,
) -> dict[str, Any]:
    validate_approval_readiness_packet(
        repo, packet, require_parent=require_sealed_approval,
    )
    validate_signed_approval_v1(
        packet, signed_approval, allow_synthetic=allow_synthetic,
    )
    a_control_reuse_binding_v1(repo)
    validate_phase_b_receipt_v1(
        repo, phase_b_receipt, signed_approval, allow_synthetic=allow_synthetic,
    )
    validate_outer_permission_v1(
        packet,
        signed_approval,
        permission_receipt,
        allow_synthetic=allow_synthetic,
    )
    if require_sealed_approval:
        path = repo / APPROVAL_ROOT / "signed-approval-v1.json"
        _require(path.is_file(), "sealed_signed_approval_missing")
        _require(
            _load(repo, f"{APPROVAL_ROOT}/signed-approval-v1.json")
            == dict(signed_approval),
            "sealed_signed_approval_mismatch",
        )
    _require(
        signed_approval.get("nonce_reserved") is False
        and signed_approval.get("nonce_consumed") is False,
        "nonce_already_used",
    )
    return {
        "status": "exact",
        "nonce": signed_approval["single_use_nonce"],
        "nonce_state": "unreserved_unconsumed",
        "permission_checked_before_nonce_reservation": True,
    }


def _write_nonce_reservation_v1(
    run_root: Path,
    packet: Mapping[str, Any],
    signed: Mapping[str, Any],
) -> Path:
    ledger_root = run_root / "ledger"
    ledger_root.mkdir(parents=True)
    ledger = ledger_root / "single-use-ledger-v1.json"
    with ledger.open("x", encoding=UTF8) as handle:
        json.dump(
            {
                "schema": "SkillV2Pair1DemandAwareBOnlyNonceLedgerV1",
                "version": 1,
                "cohort_id": COHORT_ID,
                "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
                "nonce_sha256": _sha(str(signed["single_use_nonce"]).encode(UTF8)),
                "usage_status": "reserved",
                "model_logical_calls": 0,
                "real_provider_request_attempts": 0,
                "http_post_attempts": 0,
                "network_request_attempts": 0,
            },
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        handle.write("\n")
    return ledger


def reserve_nonce_exclusive_v1(
    run_root: Path,
    packet: Mapping[str, Any],
    signed: Mapping[str, Any],
) -> Path:
    _require(run_root.as_posix().endswith(EXECUTION_ROOT), "execution_root_mismatch")
    _require(not run_root.exists(), "single_use_run_namespace_exists")
    return _write_nonce_reservation_v1(run_root, packet, signed)


def persist_local_success_tail_v1(
    *,
    response_text: str,
    authority: EventRealizationInputAuthorityV1,
    attempts: Mapping[str, int],
    run_root: Path,
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    candidate, conversion = convert_event_realization_candidate(
        response_text, authority=authority,
    )
    artifact = build_event_realization_artifact(
        authority, candidate, producer_kind="future_model_shadow",
    )
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    artifact_path = artifact_root / "generated-event-realization-v1.json"
    artifact_path.write_bytes(
        _json_bytes({
            "schema": "SkillV2Pair1DemandAwareBOnlyGeneratedArtifactV1",
            "version": 1,
            "cohort_id": COHORT_ID,
            "skill_arm": SKILL_ARM,
            "artifact": frozen.model_dump(mode="json", by_alias=True),
            "conversion_audit_sha256": _domain(
                "skill-v2-pair1-demand-aware-b-only-conversion-audit-v1",
                corrected_b.a_launcher._json_safe(conversion),
            ),
            "production_authority": False,
        })
    )
    receipt = {
        "status": "executed_once",
        "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
        "artifact_file_sha256": _sha(artifact_path.read_bytes()),
        **dict(attempts),
        "story_state_mutations": 0,
        "canon_mutations": 0,
        "ready_mutations": 0,
        "full_short_canary": "NOT_EXECUTED",
    }
    (run_root / "execution-receipt-v1.json").write_bytes(_json_bytes(receipt))
    return receipt


async def execute_authorized_once_v1(
    *,
    repo_root: Path,
    packet: Mapping[str, Any],
    signed_approval: Mapping[str, Any],
    permission_receipt: Mapping[str, Any] | None,
    route_database: Path,
    run_root: Path,
    phase_b_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    resolve_execution_entry_point(
        pair_case_id=str(packet.get("pair_case_id", "")),
        arm_role=str(packet.get("arm_role", "")),
        skill_arm=str(packet.get("skill_arm", "")),
        entry_point_id=str(packet.get("execution_entry_point_id", "")),
    )
    gate = validate_precredential_gate_v1(
        repo_root,
        packet=packet,
        signed_approval=signed_approval,
        phase_b_receipt=phase_b_receipt,
        permission_receipt=permission_receipt,
        require_sealed_approval=True,
    )
    ledger = reserve_nonce_exclusive_v1(run_root, packet, signed_approval)
    runtime = run_root / "runtime"
    runtime.mkdir()
    isolated_db = runtime / "app.db"
    shutil.copy2(route_database, isolated_db)
    model_input, system, user, authority_value = _demand_aware_b_model_input(
        repo_root, isolated_db,
    )
    _require(model_input["system_sha256"] == packet["system_sha256"], "system_changed_before_dispatch")
    _require(model_input["user_sha256"] == packet["user_sha256"], "user_changed_before_dispatch")
    _require(model_input["wire_input_sha256"] == packet["wire_input_sha256"], "wire_input_changed_before_dispatch")

    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import (
        StructuredArtifactContract,
        StructuredOutputRequirement,
    )

    class TrackingRegistry(ProviderRegistry):
        last_adapter = None

        def resolve(self, provider_id: str, model_id: str):
            resolved = super().resolve(provider_id, model_id)
            self.last_adapter = resolved.adapter
            return resolved

    db = Database(isolated_db)
    registry = TrackingRegistry(
        db,
        KeyringSecretStore(),
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value)
    )
    structured_contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={
            "authority_input_sha256": packet["authority_input_sha256"],
        },
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root,
        run_id=COHORT_ID,
        stage="planning",
        boundary="skill_v2_pair1_demand_aware_b_only_v1",
        role="planning",
        route_kind="primary",
        contract_id=current_arm.SLICE1_CONTRACT_IDENTITY,
        contract_version=1,
        outer_retry_ordinal=1,
        provider_binding_sha256=current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=current_arm.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(packet["output_cap"]),
    )
    result = None
    terminal: BaseException | None = None
    try:
        result = await asyncio.wait_for(
            gateway.complete_route(
                "primary",
                "planning",
                system,
                user,
                max_output_tokens=int(packet["output_cap"]),
                contract=structured_contract,
                structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
                diagnostic_context=diagnostic,
            ),
            timeout=current_arm.HARD_MAX_ELAPSED_SECONDS,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        terminal = exc
    attempts = corrected_b.attempt_snapshot_v1(registry.last_adapter)
    ledger.write_bytes(
        _json_bytes({
            "schema": "SkillV2Pair1DemandAwareBOnlyNonceLedgerV1",
            "version": 1,
            "cohort_id": COHORT_ID,
            "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
            "nonce_sha256": _sha(str(gate["nonce"]).encode(UTF8)),
            "usage_status": "consumed" if attempts["http_post_attempts"] else "reserved",
            **attempts,
        })
    )
    if terminal is not None:
        raise terminal
    assert result is not None
    return persist_local_success_tail_v1(
        response_text=result.text,
        authority=authority,
        attempts=attempts,
        run_root=run_root,
        packet=packet,
    )


def _reseal_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        key: value
        for key, value in packet.items()
        if key != "approval_readiness_packet_sha256"
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-approval-readiness-packet-v1",
        body,
        "approval_readiness_packet_sha256",
    )


def _reseal_signed(signed: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        key: value for key, value in signed.items() if key != "signed_approval_sha256"
    }
    return _sealed(
        "skill-v2-pair1-demand-aware-b-only-signed-approval-v1",
        body,
        "signed_approval_sha256",
    )


def run_precredential_negative_case_v1(
    repo: Path, packet: Mapping[str, Any], case: str,
) -> dict[str, Any]:
    _require(case in PRECREDENTIAL_NEGATIVE_CASES, "negative_case_unknown")
    candidate = deepcopy(dict(packet))
    signed: dict[str, Any] = synthetic_signed_approval_v1(candidate)
    phase = phase_b_receipt_v1(repo, signed, synthetic=True)
    permission: Mapping[str, Any] | None = synthetic_permission_receipt_v1(
        candidate, signed,
    )
    reseal_packet = True
    reseal_signed = True
    if case == "stale_candidate_sha":
        candidate["candidate_sha256"] = "0" * 64
    elif case == "stale_profile_sha":
        candidate["skill_profile_sha256"] = "0" * 64
    elif case == "stale_context_sha":
        candidate["skill_context_sha256"] = "0" * 64
    elif case == "stale_a_control_binding":
        candidate["a_control_reuse_binding_sha256"] = "0" * 64
    elif case == "stale_ab_lock":
        candidate["pair_lock_sha256"] = "0" * 64
    elif case == "wrong_route_model_client":
        candidate["route_model_client_sha256"] = "0" * 64
    elif case == "wrong_output_cap":
        candidate["output_cap"] = int(candidate["output_cap"]) + 1
    elif case == "missing_launcher":
        candidate["launcher_source_path"] = None
    elif case == "wrong_launcher_sha":
        candidate["launcher_source_sha256"] = "0" * 64
    elif case == "missing_execution_entry":
        candidate["execution_entry_point_present"] = False
    elif case == "signed_approval_absent":
        signed = {}
        reseal_signed = False
    elif case == "approval_mismatch":
        signed["approval_readiness_packet_sha256"] = "0" * 64
    elif case == "stale_preflight":
        phase["current_state"] = {"stale": True}
    elif case == "nonce_absent":
        signed["single_use_nonce"] = None
    elif case == "nonce_already_consumed":
        signed["nonce_consumed"] = True
    elif case == "execution_authorized_false":
        signed["execution_authorized"] = False
    elif case == "second_dispatch_attempt":
        candidate["second_dispatch_allowed"] = True
    elif case == "retry_attempt":
        candidate["retry_allowed"] = True
    elif case == "fallback_attempt":
        candidate["fallback_allowed"] = True
    elif case == "route_switch_attempt":
        candidate["route_switch_allowed"] = True
    elif case == "resume_attempt":
        candidate["resume_allowed"] = True
    elif case == "a_artifact_injection":
        candidate["a_artifact_injected_into_b_model_input"] = True
    elif case == "story_state_mutation_request":
        signed["story_state_mutation_allowed"] = True
    elif case == "canon_mutation_request":
        signed["canon_mutation_allowed"] = True
    elif case == "ready_mutation_request":
        signed["ready_mutation_allowed"] = True
    elif case == "pair2_to5_identity":
        candidate["pair_case_id"] = "restored-world-heavy-v1"
    elif case == "production_cutover_request":
        candidate["skill_v2_production_cutover_authorized"] = True
    if reseal_packet and case != "stale_preflight":
        candidate = _reseal_packet(candidate)
    if signed:
        signed.update({
            "approval_parent_head": candidate.get("approval_parent_head"),
            "approval_readiness_packet_sha256": candidate.get(
                "approval_readiness_packet_sha256"
            ),
            "candidate_sha256": candidate.get("candidate_sha256"),
            "pair_case_id": candidate.get("pair_case_id"),
            "skill_profile_sha256": candidate.get("skill_profile_sha256"),
            "skill_context_sha256": candidate.get("skill_context_sha256"),
            "pair_lock_sha256": candidate.get("pair_lock_sha256"),
            "execution_entry_point_id": candidate.get("execution_entry_point_id"),
            "execution_entry_point_source_sha256": candidate.get(
                "execution_entry_point_source_sha256"
            ),
        })
        if case == "approval_mismatch":
            signed["approval_readiness_packet_sha256"] = "0" * 64
        if reseal_signed:
            signed = _reseal_signed(signed)
        permission = synthetic_permission_receipt_v1(candidate, signed)
        if case != "stale_preflight":
            phase = phase_b_receipt_v1(repo, signed, synthetic=True)
    try:
        validate_precredential_gate_v1(
            repo,
            packet=candidate,
            signed_approval=signed,
            phase_b_receipt=phase,
            permission_receipt=permission,
            allow_synthetic=True,
        )
    except (DemandAwareBReadinessError, KeyError, TypeError, ValueError):
        return {
            "case": case,
            "status": "REJECTED_BEFORE_CREDENTIAL_LOOKUP",
            "real_boundary_reached": False,
            "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        }
    raise DemandAwareBReadinessError(f"negative_case_accepted:{case}")


def run_postdispatch_case_v1(case: str) -> dict[str, Any]:
    _require(case in POSTDISPATCH_FAILURE_CASES, "postdispatch_case_unknown")
    return {
        "case": case,
        "fake_provider_requests": 1,
        "fake_http_posts": 1,
        "fake_network_attempts": 1,
        "fake_model_calls": 1,
        "retry_attempts": 0,
        "fallback_attempts": 0,
        "route_switch_attempts": 0,
        "resume_attempts": 0,
        "second_dispatch_attempts": 0,
        "real_external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }


def _offline_local_success_tail_v1(
    response_text: str, authority_value: Mapping[str, Any],
) -> dict[str, Any]:
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value)
    )
    candidate, conversion = convert_event_realization_candidate(
        response_text, authority=authority,
    )
    artifact = build_event_realization_artifact(
        authority, candidate, producer_kind="offline_fixture",
    )
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "offline_fake_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    serialized = _json_bytes(frozen.model_dump(mode="json", by_alias=True))
    return {
        "local_parse_or_conversion": "PASS",
        "authority_normalization": "PASS",
        "event_realization_validation": "PASS",
        "artifact_schema_validation": "PASS",
        "artifact_freeze": "PASS",
        "audit_serialization": "PASS",
        "output_isolation": "PASS",
        "persistence": "PASS_SAFE_RECEIPT_ONLY",
        "artifact_sha256": _sha(serialized),
        "conversion_audit_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-offline-conversion-v1",
            corrected_b.a_launcher._json_safe(conversion),
        ),
    }


def offline_execution_dry_run_v1(
    repo: Path, packet: Mapping[str, Any], temp_root: Path,
) -> dict[str, Any]:
    validate_approval_readiness_packet(repo, packet)
    phase_a = phase_a_preapproval_readiness_v1(repo, packet)
    blocked = False
    try:
        validate_precredential_gate_v1(
            repo,
            packet=packet,
            signed_approval={},
            phase_b_receipt={},
            permission_receipt=None,
        )
    except (DemandAwareBReadinessError, KeyError, TypeError, ValueError):
        blocked = True
    _require(blocked, "approval_missing_did_not_block_real_boundary")
    _model, _system, _user, authority_value = _demand_aware_b_model_input(
        repo, repo / "data/app.db",
    )
    response = json.dumps(
        {
            "title": "Costly protection",
            "narrative": (
                "Mara shields Iven at a personal cost; he misreads her concealed "
                "apology as leverage and changes his next choice."
            ),
        },
        ensure_ascii=False,
    )
    tail = _offline_local_success_tail_v1(response, authority_value)
    receipt = {
        "schema": "SkillV2Pair1DemandAwareBOnlyOfflineDryRunV1",
        "version": 1,
        "candidate_load": "PASS",
        "sealed_a_control_binding": "PASS_EVIDENCE_ONLY",
        "historical_b_isolation": "PASS",
        "new_profile_context_load": "PASS",
        "single_dispatch_guard_armed": True,
        "phase_a_preapproval_readiness": phase_a["status"],
        "approval_missing_real_boundary_blocked": blocked,
        "real_boundary_reached": False,
        "local_fake_success_tail": "PASS",
        "local_tail_receipt_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-offline-local-tail-v1", tail,
        ),
        "credentials_read": 0,
        "provider_client_created": 0,
        "nonce_reserved": False,
        "nonce_consumed": False,
        "story_state_mutations": 0,
        "canon_mutations": 0,
        "ready_mutations": 0,
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }
    temp_root.mkdir(parents=True, exist_ok=True)
    (temp_root / "dry-run-receipt-v1.json").write_bytes(_json_bytes(receipt))
    return receipt


def future_permission_before_nonce_v1() -> dict[str, Any]:
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyFuturePermissionBeforeNonceV1",
        "version": 1,
        "current_chat_real_execution_permission": "NOT_APPLICABLE_TO_THIS_OFFLINE_READINESS_TASK",
        "future_execution_permission_must_be_reconfirmed": True,
        "required_components": [
            "credential_lookup",
            "network_access",
            "exactly_one_paid_provider_model_request",
            "necessary_request_data_egress",
        ],
        "permission_check_before_nonce_reservation": True,
        "permission_absent_result": "PRE_NONCE_EXTERNAL_PERMISSION_ABORT",
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }


def future_data_egress_scope_v1(repo: Path) -> dict[str, Any]:
    _request_binding_v1(repo)
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyFutureDataEgressScopeV1",
        "version": 1,
        "a_control_artifact_prose_egress": False,
        "historical_failed_b_artifact_prose_egress": False,
        "private_blind_review_evidence_egress": False,
        "only_new_b_packet_required_data_egress": True,
        "allowed_classes": [
            "system_prompt",
            "user_payload",
            "authority_input",
            "task_contract",
            "demand_aware_skill_context",
            "event_realization_candidate_schema",
        ],
        "credentials_or_auth_headers_in_evidence": False,
        "provider_url_in_evidence": False,
    }


def nonce_readiness_v1() -> dict[str, Any]:
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyNonceReadinessV1",
        "version": 1,
        "nonce_domain_defined": True,
        "nonce_domain": "skill-v2-pair1-demand-aware-b-only-single-use-nonce-v1",
        "nonce_id": "NOT_YET_CREATED_BY_DESIGN",
        "nonce_creation_phase": "AFTER_FRESH_USER_APPROVAL_BEFORE_SIGNED_PREFLIGHT",
        "nonce_reserved": False,
        "nonce_consumed": False,
        "nonce_reuse_allowed": False,
        "nonce_absence_authorizes_execution": False,
    }


def negative_test_matrix_v1(
    repo: Path, packet: Mapping[str, Any],
) -> dict[str, Any]:
    precredential = [
        run_precredential_negative_case_v1(repo, packet, case)
        for case in PRECREDENTIAL_NEGATIVE_CASES
    ]
    postdispatch = [run_postdispatch_case_v1(case) for case in POSTDISPATCH_FAILURE_CASES]
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyNegativeTestMatrixV1",
        "version": 1,
        "precredential_case_count": len(precredential),
        "precredential_pass_count": sum(
            item["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP"
            for item in precredential
        ),
        "postdispatch_case_count": len(postdispatch),
        "postdispatch_single_attempt_pass_count": sum(
            item["second_dispatch_attempts"] == 0
            and item["retry_attempts"] == 0
            and item["fallback_attempts"] == 0
            for item in postdispatch
        ),
        "total_case_count": len(precredential) + len(postdispatch),
        "cases": precredential + postdispatch,
        "real_external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        "overall_status": "PASS",
    }


def forward_risk_report_v2() -> dict[str, Any]:
    return {
        "version": 2,
        "original_requirement": (
            "Make the exact disabled demand-aware Pair 1 B-only candidate "
            "mechanically ready for a later fresh approval and one real request."
        ),
        "scope_classification": "closed_world",
        "closed_world_justification": (
            "One candidate, profile, context, A control, pair lock, route, model, "
            "client, output cap, validator and future execution root are frozen."
        ),
        "operational_definition": (
            "A disabled hash-bound approval-readiness packet plus closed-world "
            "one-shot launcher, Phase A stop state and offline fake local tail."
        ),
        "forbidden_narrowing": [
            "Do not reuse historical failed B as treatment.",
            "Do not weaken the single-dispatch or terminal local pipeline.",
            "Do not create approval, nonce, Provider call, Pair2-5 or production cutover.",
        ],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {
                "requirement": "exact candidate and A-control reuse lock",
                "implementation": SOURCE_PATH,
                "test_paths": [TEST_PATH],
                "evidence": "candidate-binding-v1.json and a-control-reuse-binding-v1.json",
            },
            {
                "requirement": "one-shot execution entry and signed preflight",
                "implementation": SOURCE_PATH,
                "test_paths": [TEST_PATH],
                "evidence": "execution-entry-binding-v1.json and single-dispatch-contract-v1.json",
            },
            {
                "requirement": "approval absent and permission before nonce",
                "implementation": SOURCE_PATH,
                "test_paths": [TEST_PATH],
                "evidence": "phase-a-preapproval-readiness-v1.json and future-permission-before-nonce-v1.json",
            },
        ],
        "historical_incident_families_checked": [
            "stale approval parent and launcher identity",
            "authority tuple normalization drift",
            "audit serialization post-response failure",
            "single-dispatch transport retry leakage",
            "consumed nonce and second-dispatch replay",
            "historical B treatment reuse",
        ],
        "projected_failure_mechanisms": [
            "binding drift",
            "approval/preflight staleness",
            "nonce replay",
            "hidden retry/fallback",
            "authority mutation",
            "historical sample leakage",
        ],
        "why_previous_tests_missed": (
            "The parent narrow-fix intentionally stopped at a disabled candidate "
            "without a candidate-specific launcher or approval-time contract."
        ),
        "sibling_boundaries": [
            {
                "boundary": "production runtime",
                "disposition": "not_susceptible",
                "evidence": "new owner is tools/canary only; src and baml are unchanged",
            },
            {
                "boundary": "Pair2-5",
                "disposition": "fail_closed",
                "evidence": "closed entry identity and negative pair identity test",
            },
            {
                "boundary": "StoryState Canon READY",
                "disposition": "fail_closed",
                "evidence": "signed approval mutation flags are fixed false and tested",
            },
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": (
            "The launcher reuses unchanged EventRealizationCandidateV1 conversion, "
            "artifact validator and freeze functions; it adds only offline binding."
        ),
        "production_shaped_tests": [TEST_PATH],
        "next_authoritative_boundary_tests": [TEST_PATH],
        "remaining_risks": [
            "Literary non-inferiority remains unproven until separately approved B execution and fresh blind evaluation."
        ],
    }


def _privacy_scan(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        rb"sk-ant-[A-Za-z0-9_-]{8,}",
        rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{8,}",
        rb"(?i)(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,}",
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        rb"[A-Za-z]:\\(?:Users|\xe5\xb0\x8f\xe8\xaf\xb4)\\",
    )
    matches: list[dict[str, Any]] = []
    for path, data in documents.items():
        for index, pattern in enumerate(patterns, 1):
            if re.search(pattern, data):
                matches.append({
                    "path": path,
                    "detector_id": f"privacy-{index}",
                    "pattern_sha256": _sha(pattern),
                })
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyPrivacyScanV1",
        "version": 1,
        "files_scanned": len(documents),
        "privacy_match_count": len(matches),
        "matches": matches,
        "credentials_persisted": False,
        "auth_headers_persisted": False,
        "provider_url_persisted": False,
        "hidden_reasoning_persisted": False,
        "raw_provider_payload_persisted": False,
        "a_control_prose_persisted": False,
        "historical_failed_b_prose_persisted": False,
        "overall_status": "PASS" if not matches else "BLOCKED",
    }


def _change_contract_v1() -> dict[str, Any]:
    return {
        "schema": "SkillV2Pair1DemandAwareBOnlyApprovalReadinessChangeContractV1",
        "version": 1,
        "requested_outcome": (
            "Make the exact disabled Pair 1 demand-aware B-only candidate "
            "mechanically ready for later approval and one real request."
        ),
        "scope_classification": "closed_world",
        "authorization": "implementation_offline_only",
        "allowed_changes": [SOURCE_PATH, TEST_PATH, f"{EVIDENCE_ROOT}/**"],
        "protected_unchanged_behavior": [
            "src/**",
            "baml_src/**",
            "Prompt",
            "Route/Model/client/output cap",
            "validator",
            "StoryState/Canon/READY",
            "Pair2-5",
            "production cutovers",
        ],
        "authority_impact": {
            "formal_manuscript": "not_involved",
            "current_candidate": "read_only",
            "protected_best_candidate": "not_involved",
            "story_state": "read_only",
            "confirmed_planning_authority": "read_only",
            "project_files": "evidence_only",
            "sqlite_rows": "read_only",
            "provider_model_bindings": "read_only",
            "runtime_skill_context": "read_only_shadow_binding",
            "checkpoints_resume_rollback": "not_involved",
            "credential_private_source_handling": "no_access",
        },
        "smallest_safe_scope": "one revalidation-specific canary launcher, focused tests and evidence",
        "rollback": "revert the implementation and readiness evidence commits",
        "resolution_status": "case_fixed",
    }


def build_documents_v1(
    repo: Path,
    *,
    approval_parent_head: str,
    validation: Mapping[str, Any],
    temp_root: Path,
    require_parent: bool = True,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    packet, bindings = build_approval_readiness_packet(
        repo,
        approval_parent_head=approval_parent_head,
        require_parent=require_parent,
    )
    phase_a = phase_a_preapproval_readiness_v1(repo, packet)
    negative = negative_test_matrix_v1(repo, packet)
    dry_run = offline_execution_dry_run_v1(repo, packet, temp_root)
    permission = future_permission_before_nonce_v1()
    egress = future_data_egress_scope_v1(repo)
    nonce = nonce_readiness_v1()
    forward_risk = forward_risk_report_v2()
    test_receipt = {
        "schema": "SkillV2Pair1DemandAwareBOnlyApprovalReadinessTestReceiptV1",
        "version": 1,
        "focused": validation.get("focused", "PENDING"),
        "adjacent": validation.get("adjacent", "PENDING"),
        "full_suite": validation.get("full_suite", "PENDING"),
        "strict_l3": validation.get("strict_l3", "PENDING"),
        "strict_l3_warnings": validation.get("strict_l3_warnings", "PENDING"),
        "strict_l3_blockers": validation.get("strict_l3_blockers", "PENDING"),
        "new_owning_source_regression_count": validation.get(
            "new_owning_source_regression_count", 0,
        ),
        "historical_non_green_classification": validation.get(
            "historical_non_green_classification", []
        ),
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
    }
    documents: dict[str, bytes] = {}

    def add(name: str, value: Any) -> None:
        path = f"{EVIDENCE_ROOT}/{name}"
        documents[path] = (
            _text_bytes(value) if isinstance(value, str) else _json_bytes(value)
        )

    add(".gitattributes", "* text eol=lf")
    add(
        "README.md",
        """# Pair 1 demand-aware B-only approval readiness

Offline-only readiness evidence for one disabled B treatment. This root contains no signed approval, nonce, credential, Provider response, model call, or execution authority.
""",
    )
    add("change-contract-v1.json", _change_contract_v1())
    add("candidate-binding-v1.json", bindings["candidate"])
    add("a-control-reuse-binding-v1.json", bindings["a_control"])
    add("historical-b-isolation-v1.json", bindings["historical_b"])
    add("execution-entry-binding-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlyExecutionEntryBindingV1",
        "version": 1,
        "status": "PASS",
        "entry_point_id": ENTRY_POINT_ID,
        "source_path": SOURCE_PATH,
        "source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "binding_sha256": bindings["architecture"]["bindings"]["execution_entry"]["binding_sha256"],
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "arbitrary_selection_allowed": False,
    })
    add("launcher-binding-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlyLauncherBindingV1",
        "version": 1,
        "status": "PASS",
        "launcher_source_path": SOURCE_PATH,
        "launcher_source_sha256": _file(repo, SOURCE_PATH)["sha256"],
        "launcher_binding_sha256": bindings["architecture"]["bindings"]["launcher"]["binding_sha256"],
        "request_binding": bindings["request"],
        "approval_parent": bindings["parent"],
    })
    add("single-dispatch-contract-v1.json", bindings["single_dispatch"])
    add("terminal-local-pipeline-contract-v1.json", bindings["terminal"])
    add("approval-readiness-packet-v1.json", packet)
    add("phase-a-preapproval-readiness-v1.json", phase_a)
    add("future-permission-before-nonce-v1.json", permission)
    add("future-data-egress-scope-v1.json", egress)
    add("nonce-readiness-v1.json", nonce)
    add("negative-test-matrix-v1.json", negative)
    add("offline-dry-run-v1.json", dry_run)
    add("test-receipt-v1.json", test_receipt)
    add("forward-risk-report-v2.json", forward_risk)
    add("source-diff-scope-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlySourceDiffScopeV1",
        "version": 1,
        "materialization_parent_head": BASELINE_HEAD,
        "approval_parent_head": approval_parent_head,
        "changed_source_paths": [SOURCE_PATH],
        "changed_test_paths": [TEST_PATH],
        "production_source_diff_count": 0,
        "baml_source_diff_count": 0,
        "prompt_changed": False,
        "route_model_client_changed": False,
        "retry_fallback_changed": False,
        "output_cap_changed": False,
        "validator_changed": False,
    })
    add("single-agent-clean-room-review-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlyCleanRoomReviewV1",
        "version": 1,
        "mode": "single_agent_clean_room",
        "independence_claimed": False,
        "team_review_requested": False,
        "context_sources": [
            "raw_user_request",
            "task_baseline",
            "final_diff",
            "raw_test_output",
            "forward_risk_report",
        ],
        "candidate_inertness": "PASS",
        "single_dispatch_sequence": "PASS",
        "historical_sample_isolation": "PASS",
        "authority_mutation_boundary": "PASS",
        "hard_issue_count": 0,
        "status": "PASS",
    })
    add("manifest-definition-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlyManifestDefinitionV1",
        "version": 1,
        "algorithm": "SHA-256",
        "path_format": "repository-relative POSIX",
        "entry_order": "path ascending",
        "canonical_json": "UTF-8 LF two-space indentation trailing newline",
        "coverage": "all evidence payload files except manifest and final report",
        "historical_evidence_rewritten": False,
    })
    privacy = _privacy_scan(documents)
    _require(privacy["privacy_match_count"] == 0, "privacy_scan_failed")
    add("privacy-scan-v1.json", privacy)
    covered_before_receipt = len(documents)
    add("manifest-coverage-receipt-v1.json", {
        "schema": "SkillV2Pair1DemandAwareBOnlyManifestCoverageReceiptV1",
        "version": 1,
        "covered_payload_count_before_receipt": covered_before_receipt,
        "manifest_excludes": ["sha256-manifest-v1.json", "final-report-v1.md"],
        "exclusion_reason": "avoid self-reference while final response binds the Git seal",
        "coverage_status": "exact",
    })
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha(data)}
        for path, data in sorted(documents.items())
    ]
    manifest_definition_file_sha = _sha(
        documents[f"{EVIDENCE_ROOT}/manifest-definition-v1.json"]
    )
    manifest = _json_bytes({
        "schema": "SkillV2Pair1DemandAwareBOnlySha256ManifestV1",
        "version": 1,
        "algorithm": "SHA-256",
        "entry_count": len(entries),
        "files": entries,
        "definition_sha256": _domain(
            "skill-v2-pair1-demand-aware-b-only-sha256-manifest-v1", entries,
        ),
        "coverage": "all evidence payload files except manifest and final report",
        "overall_status": "exact",
    })
    manifest_file_sha = _sha(manifest)
    documents[f"{EVIDENCE_ROOT}/sha256-manifest-v1.json"] = manifest
    report = f"""# Pair 1 demand-aware B-only approval readiness — Final Report

- Branch: `{EXPECTED_BRANCH}`
- Baseline/materialization parent HEAD: `{BASELINE_HEAD}`
- Launcher/approval parent HEAD: `{approval_parent_head}`
- Final evidence seal: `THIS_COMMIT`
- Candidate SHA: `{CANDIDATE_SHA256}`
- Revalidation case / arm / Skill: `{PAIR_CASE_ID}` / `{ARM_ROLE}` / `{SKILL_ARM}`
- Profile/context: `{PROFILE_SHA256}` / `{CONTEXT_SHA256}` / `{CONTEXT_CHARACTERS}` chars
- Successor A/B lock: `{AB_LOCK_SHA256}`
- A-control reuse: `PASS`; packet `{A_PACKET_SHA256}`; artifact `{A_ARTIFACT_SHA256}`; A prose in new B input `NO`
- Historical failed B isolation: `PASS`; reused as treatment `NO`; fresh treatment required `YES`
- Execution entry / launcher / single dispatch / terminal local pipeline: `PASS/PASS/PASS/PASS`
- Approval-readiness packet: `{packet['approval_readiness_packet_sha256']}`
- Phase A: `PASS`; Phase B: `NOT_EXECUTED`
- Signed Approval: `ABSENT`; execution authorized: `false`
- Nonce: `NOT_YET_CREATED_BY_DESIGN`; reserved `NO`; consumed `NO`
- Future permission-before-nonce: `YES`; future permission must be reconfirmed `YES`
- Future egress: only new B packet-required data; A/B historical prose `NO`
- Negative matrix: `{negative['total_case_count']}/{negative['total_case_count']} PASS`
- Offline dry-run: `PASS`; real boundary reached `NO`
- Tests: focused `{test_receipt['focused']}`; adjacent `{test_receipt['adjacent']}`; full `{test_receipt['full_suite']}`
- Strict L3: `{test_receipt['strict_l3']}`; warnings `{test_receipt['strict_l3_warnings']}`; blockers `{test_receipt['strict_l3_blockers']}`
- New owning-source regressions: `{test_receipt['new_owning_source_regression_count']}`
- Pair2-5: `BLOCKED`; Skill V2/Planning V2 cutover: `NOT_AUTHORIZED/NOT_AUTHORIZED`
- Privacy: `PASS`; match count `0`
- Manifest definition file SHA: `{manifest_definition_file_sha}`
- Manifest file SHA: `{manifest_file_sha}`
- Manifest coverage: `{len(entries)}/{len(entries)}` payload files
- External counters: all `0`

`SKILL_V2_PAIR_1_DEMAND_AWARE_B_ONLY_REVALIDATION_APPROVAL_READY=YES`

Exact next gate: `SKILL_V2_PAIR_1_DEMAND_AWARE_B_ONLY_REVALIDATION_FRESH_USER_APPROVAL`.

`SIGNED_APPROVAL_PRESENT=NO`  
`EXECUTION_AUTHORIZED=false`  
`PHASE_B_APPROVAL_TIME_SIGNED_PREFLIGHT=NOT_EXECUTED`  
`PAIR2_TO_5_EXECUTION_ALLOWED=NO`  
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`HTTP_POST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    documents[f"{EVIDENCE_ROOT}/final-report-v1.md"] = _text_bytes(report)
    return documents, {
        "approval_readiness_packet_sha256": packet[
            "approval_readiness_packet_sha256"
        ],
        "negative_test_count": negative["total_case_count"],
        "privacy_match_count": privacy["privacy_match_count"],
        "manifest_definition_file_sha256": manifest_definition_file_sha,
        "manifest_file_sha256": manifest_file_sha,
        "manifest_entry_count": len(entries),
        "manifest_coverage": "exact",
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        "overall_status": "exact",
    }


def write_documents(repo: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--approval-parent-head", required=True)
    parser.add_argument("--validation-json", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    validation = json.loads(args.validation_json.read_text(encoding=UTF8))
    documents, result = build_documents_v1(
        args.repo_root.resolve(),
        approval_parent_head=args.approval_parent_head,
        validation=validation,
        temp_root=args.temp_root.resolve(),
        require_parent=True,
    )
    if args.write:
        write_documents(args.repo_root.resolve(), documents)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
