from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import types
from typing import Any, Mapping

from novel_flywheel.canonical_shadow import canonical_sha256
from novel_flywheel.runtime_skill_profiles import (
    build_planning_v2_event_realization_profile_residual_v3,
)
from tools.canary import skill_v2_pair1_demand_aware_b_revalidation as predecessor


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "c68969a836a7ac754910002435d67c405dee33a6"
SOURCE_PATH = "tools/canary/skill_v2_pair1_residual_v3_b_revalidation.py"
TEST_PATH = "tests/canary/test_skill_v2_pair1_residual_v3_b_revalidation.py"
PARENT_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-residual-creative-semantic-narrow-fix-v3"
)
EVIDENCE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-residual-v3-b-only-approval-readiness-v1"
)
APPROVAL_ROOT = f"{EVIDENCE_ROOT}/approval"
EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-residual-v3-b-only-execution-v1/"
    "pairs/restored-character-heavy-v2-residual-v3/b-arm"
)

CANDIDATE_PATH = f"{PARENT_ROOT}/revalidation-candidate-v1.json"
LOCK_PATH = f"{PARENT_ROOT}/successor-v3-ab-lock-v1.json"
REUSE_DECISION_PATH = f"{PARENT_ROOT}/a-control-reuse-v3-binding-v1.json"
PARENT_MANIFEST_PATH = f"{PARENT_ROOT}/sha256-manifest-v1.json"

CANDIDATE_SHA256 = "c3b8562c359328148e34215db3c5b36e432e6bfe3bdd061740f0ab9299d30bdd"
PROFILE_SHA256 = "82a4542326e9b20771efc5f05e080ff0ac56438bef8288d61f30e6d905af708a"
CONTEXT_SHA256 = "98c5adc38074f442a986764fb140baf4d3bf3fa1ab58e34ba7f82b7ddc8888ba"
CONTEXT_CHARACTERS = 2998
AB_LOCK_SHA256 = "817d88552c273fc2a9521423725af7460fd09b83b9d3eb558d2bd3cacaee75cf"
PARENT_MANIFEST_FILE_SHA256 = "d1e6bb83175f11a000a44c4c0867f9d1e9f1b8d3dbf98f28e5c2fc2b883803c8"

A_PACKET_SHA256 = predecessor.A_PACKET_SHA256
A_ARTIFACT_SHA256 = predecessor.A_ARTIFACT_SHA256
A_CONTROL_EVIDENCE_HEAD = predecessor.A_CONTROL_EVIDENCE_HEAD
HISTORICAL_B_PACKET_SHA256 = predecessor.HISTORICAL_B_PACKET_SHA256
HISTORICAL_B_ARTIFACT_SHA256 = predecessor.HISTORICAL_B_ARTIFACT_SHA256
A_EXECUTION_ROOT = predecessor.A_EXECUTION_ROOT
HISTORICAL_B_EXECUTION_ROOT = predecessor.HISTORICAL_B_EXECUTION_ROOT
OLD_B_PACKET_PATH = predecessor.OLD_B_PACKET_PATH
HISTORICAL_B_ARTIFACT_PATH = predecessor.HISTORICAL_B_ARTIFACT_PATH

PAIR_CASE_ID = "restored-character-heavy-v2-residual-v3"
ARM_ROLE = "B_ARM"
SKILL_ARM = "RESTORED_SKILL_V2_CHARACTER_CORE_V3"
SCOPE = "SKILL_V2_PAIR1_RESIDUAL_V3_B_ONLY_REVALIDATION_SINGLE_DISPATCH_ONLY"
COHORT_ID = "skill-v2-pair1-residual-v3-b-revalidation-disabled-20260826-001"
ENTRY_POINT_ID = (
    "tools.canary.skill_v2_pair1_residual_v3_b_revalidation:"
    "execute_authorized_once_v1"
)

ZERO_EXTERNAL_ACTIONS = dict(predecessor.ZERO_EXTERNAL_ACTIONS)
SHARED_BINDING_FIELDS = predecessor.SHARED_BINDING_FIELDS
POSTDISPATCH_FAILURE_CASES = predecessor.POSTDISPATCH_FAILURE_CASES
PRECREDENTIAL_NEGATIVE_CASES = predecessor.PRECREDENTIAL_NEGATIVE_CASES + (
    "v2_profile_context_substitution",
    "wrong_route",
    "wrong_model",
    "wrong_client",
    "historical_b_prose_injection",
    "private_blind_evidence_injection",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(repo: Path, relative: str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding=UTF8))
    if not isinstance(value, dict):
        raise predecessor.DemandAwareBReadinessError(f"json_object_required:{relative}")
    return value


def _require(value: bool, reason: str) -> None:
    if not value:
        raise predecessor.DemandAwareBReadinessError(reason)


def _verify_parent_manifest_v3(repo: Path) -> dict[str, Any]:
    data = (repo / PARENT_MANIFEST_PATH).read_bytes()
    _require(_sha(data) == PARENT_MANIFEST_FILE_SHA256, "parent_manifest_file_sha_mismatch")
    manifest = json.loads(data.decode(UTF8))
    entries = manifest.get("files")
    _require(
        isinstance(entries, list) and manifest.get("entry_count") == len(entries),
        "parent_manifest_shape_mismatch",
    )
    mismatches: list[str] = []
    for entry in entries:
        target = repo / PARENT_ROOT / str(entry["path"])
        if not target.is_file():
            mismatches.append(str(entry["path"]))
            continue
        payload = target.read_bytes()
        if len(payload) != entry["bytes"] or _sha(payload) != entry["sha256"]:
            mismatches.append(str(entry["path"]))
    _require(not mismatches, "parent_manifest_entry_mismatch")
    return {
        "path": PARENT_MANIFEST_PATH,
        "file_sha256": _sha(data),
        "entry_count": len(entries),
        "mismatch_count": 0,
        "status": "EXACT",
    }


def _candidate_binding_v3(repo: Path) -> dict[str, Any]:
    manifest = _verify_parent_manifest_v3(repo)
    candidate = _load(repo, CANDIDATE_PATH)
    lock = _load(repo, LOCK_PATH)
    candidate_body = {key: value for key, value in candidate.items() if key != "candidate_sha256"}
    lock_body = {key: value for key, value in lock.items() if key != "successor_v3_ab_lock_sha256"}
    _require(
        canonical_sha256("SkillV2Pair1ResidualV3BOnlyRevalidationCandidateV1", candidate_body)
        == CANDIDATE_SHA256 == candidate.get("candidate_sha256"),
        "candidate_logical_sha_mismatch",
    )
    _require(
        canonical_sha256("SkillV2Pair1ResidualV3SuccessorABLockV1", lock_body)
        == AB_LOCK_SHA256 == lock.get("successor_v3_ab_lock_sha256"),
        "successor_ab_lock_sha_mismatch",
    )
    required = {
        "new_profile_sha256": PROFILE_SHA256,
        "new_context_sha256": CONTEXT_SHA256,
        "new_context_characters": CONTEXT_CHARACTERS,
        "successor_v3_ab_lock_sha256": AB_LOCK_SHA256,
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
        "schema": "SkillV2Pair1ResidualV3BOnlyCandidateBindingV1",
        "version": 1,
        "candidate_sha256": CANDIDATE_SHA256,
        "candidate_file_sha256": _sha((repo / CANDIDATE_PATH).read_bytes()),
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


class _ResidualProfileAdapter:
    @staticmethod
    def _profile_evidence(repo: Path) -> dict[str, Any]:
        evidence = dict(predecessor.demand_fix._profile_evidence(repo))
        v2 = evidence["new"]
        v3 = build_planning_v2_event_realization_profile_residual_v3(
            repo / "vendor/novel-skills/source",
            predecessor.demand_fix._inputs(repo),
            pair_creative_demand_class="character-heavy",
        )
        v3_context, v3_receipt = predecessor.demand_fix._render(v3)
        v2_rules = predecessor.demand_fix._rules(v2)
        v3_rules = predecessor.demand_fix._rules(v3)
        changed = tuple(
            rule_id for rule_id in v3.included_rule_ids
            if v2_rules[rule_id] != v3_rules[rule_id]
        )
        _require(changed == ("DRAFT_SCENE", "ANTI_TAXONOMY"), "v3_rule_scope_mismatch")
        evidence.update({
            "old": v2,
            "new": v3,
            "old_context": evidence["new_context"],
            "new_context": v3_context,
            "old_receipt": evidence["new_receipt"],
            "new_receipt": v3_receipt,
            "old_rules": v2_rules,
            "new_rules": v3_rules,
            "changed": changed,
            "unchanged": tuple(rule_id for rule_id in v3.included_rule_ids if rule_id not in changed),
        })
        return evidence


def _a_control_reuse_binding_v3(repo: Path) -> dict[str, Any]:
    decision = _load(repo, REUSE_DECISION_PATH)
    candidate = _load(repo, CANDIDATE_PATH)
    old_packet = _load(repo, OLD_B_PACKET_PATH)
    control = predecessor.corrected_b.sealed_a_control_binding(repo)
    _require(decision.get("sealed_decision") == "CONDITIONAL", "a_control_decision_drift")
    _require(decision.get("a_control_reuse_conditions_satisfied") == "YES", "a_control_conditions")
    _require(decision.get("overall_status") == "exact", "a_control_not_exact")
    _require(control["a_status"] == "PASS_SEALED", "a_control_not_pass_sealed")
    _require(control["a_packet_sha256"] == A_PACKET_SHA256, "a_control_packet_drift")
    _require(control["a_artifact_sha256"] == A_ARTIFACT_SHA256, "a_control_artifact_drift")
    mismatches = [
        field for field in SHARED_BINDING_FIELDS
        if candidate["shared_experiment_bindings"].get(field) != old_packet.get(field)
    ]
    _require(not mismatches, "a_control_non_skill_lock_mismatch")
    conditions = decision.get("conditions", {})
    _require(all(conditions.values()), "a_control_condition_false")
    return {
        "schema": "SkillV2Pair1ResidualV3BOnlyAControlReuseBindingV1",
        "version": 1,
        "a_control_reuse_binding": "PASS",
        "a_control_reuse_decision": "CONDITIONAL",
        "a_control_reuse_conditions_satisfied": "YES",
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


def _clone_function(function: types.FunctionType, namespace: dict[str, Any]) -> types.FunctionType:
    cloned = types.FunctionType(
        function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__,
    )
    cloned.__kwdefaults__ = function.__kwdefaults__
    cloned.__annotations__ = dict(function.__annotations__)
    cloned.__doc__ = function.__doc__
    return cloned


def _build_runtime() -> dict[str, Any]:
    namespace = dict(vars(predecessor))
    namespace.update({
        "EXPECTED_BRANCH": EXPECTED_BRANCH,
        "BASELINE_HEAD": BASELINE_HEAD,
        "SOURCE_PATH": SOURCE_PATH,
        "TEST_PATH": TEST_PATH,
        "PARENT_ROOT": PARENT_ROOT,
        "EVIDENCE_ROOT": EVIDENCE_ROOT,
        "APPROVAL_ROOT": APPROVAL_ROOT,
        "EXECUTION_ROOT": EXECUTION_ROOT,
        "CANDIDATE_PATH": CANDIDATE_PATH,
        "LOCK_PATH": LOCK_PATH,
        "REUSE_DECISION_PATH": REUSE_DECISION_PATH,
        "PARENT_MANIFEST_PATH": PARENT_MANIFEST_PATH,
        "PARENT_MANIFEST_FILE_SHA256": PARENT_MANIFEST_FILE_SHA256,
        "CANDIDATE_SHA256": CANDIDATE_SHA256,
        "PROFILE_SHA256": PROFILE_SHA256,
        "CONTEXT_SHA256": CONTEXT_SHA256,
        "CONTEXT_CHARACTERS": CONTEXT_CHARACTERS,
        "AB_LOCK_SHA256": AB_LOCK_SHA256,
        "PAIR_CASE_ID": PAIR_CASE_ID,
        "ARM_ROLE": ARM_ROLE,
        "SKILL_ARM": SKILL_ARM,
        "SCOPE": SCOPE,
        "COHORT_ID": COHORT_ID,
        "ENTRY_POINT_ID": ENTRY_POINT_ID,
        "PRECREDENTIAL_NEGATIVE_CASES": predecessor.PRECREDENTIAL_NEGATIVE_CASES,
        "demand_fix": _ResidualProfileAdapter,
    })
    for name, value in vars(predecessor).items():
        if isinstance(value, types.FunctionType) and value.__module__ == predecessor.__name__:
            namespace[name] = _clone_function(value, namespace)
    namespace["_verify_parent_manifest"] = _verify_parent_manifest_v3
    namespace["candidate_binding_v1"] = _candidate_binding_v3
    namespace["a_control_reuse_binding_v1"] = _a_control_reuse_binding_v3
    return namespace


_runtime = _build_runtime()
_raw_build_packet = _runtime["build_approval_readiness_packet"]
_raw_validate_packet = _runtime["validate_approval_readiness_packet"]
_raw_execute = _runtime["execute_authorized_once_v1"]


def candidate_binding_v1(repo: Path) -> dict[str, Any]:
    return _candidate_binding_v3(repo)


def residual_v3_skill_binding_v1(repo: Path) -> dict[str, Any]:
    return _runtime["demand_aware_skill_binding_v1"](repo)


def a_control_reuse_binding_v1(repo: Path) -> dict[str, Any]:
    return _a_control_reuse_binding_v3(repo)


def build_approval_readiness_packet(
    repo: Path, *, approval_parent_head: str, require_parent: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    packet, bindings = _raw_build_packet(
        repo, approval_parent_head=approval_parent_head, require_parent=require_parent,
    )
    packet = dict(packet)
    packet["private_blind_evidence_injected_into_b_model_input"] = False
    packet = _runtime["_reseal_packet"](packet)
    validate_approval_readiness_packet(repo, packet, require_parent=require_parent)
    return packet, bindings


def validate_approval_readiness_packet(
    repo: Path, packet: Mapping[str, Any], *, require_parent: bool = False,
) -> str:
    _raw_validate_packet(repo, packet, require_parent=require_parent)
    _require(
        packet.get("private_blind_evidence_injected_into_b_model_input") is False,
        "private_blind_evidence_injection",
    )
    return "PASS"


async def execute_authorized_once_v1(**kwargs: Any) -> dict[str, Any]:
    validate_approval_readiness_packet(
        kwargs["repo_root"], kwargs["packet"], require_parent=True,
    )
    return await _raw_execute(**kwargs)


_runtime["execute_authorized_once_v1"] = execute_authorized_once_v1


def run_precredential_negative_case_v1(
    repo: Path, packet: Mapping[str, Any], case: str,
) -> dict[str, Any]:
    _require(case in PRECREDENTIAL_NEGATIVE_CASES, "negative_case_unknown")
    if case in predecessor.PRECREDENTIAL_NEGATIVE_CASES:
        return _runtime["run_precredential_negative_case_v1"](repo, packet, case)
    candidate = deepcopy(dict(packet))
    if case == "v2_profile_context_substitution":
        candidate["skill_profile_sha256"] = predecessor.PROFILE_SHA256
        candidate["skill_context_sha256"] = predecessor.CONTEXT_SHA256
    elif case == "wrong_route":
        candidate["route_fingerprint"] = "0" * 64
    elif case == "wrong_model":
        candidate["model_binding_sha256"] = "0" * 64
    elif case == "wrong_client":
        candidate["client"] = "WrongAdapter"
    elif case == "historical_b_prose_injection":
        candidate["historical_b_result_injected_into_new_b_model_input"] = True
    elif case == "private_blind_evidence_injection":
        candidate["private_blind_evidence_injected_into_b_model_input"] = True
    candidate = _runtime["_reseal_packet"](candidate)
    signed = _runtime["synthetic_signed_approval_v1"](candidate)
    phase = _runtime["phase_b_receipt_v1"](repo, signed, synthetic=True)
    permission = _runtime["synthetic_permission_receipt_v1"](candidate, signed)
    try:
        validate_approval_readiness_packet(repo, candidate)
        _runtime["validate_precredential_gate_v1"](
            repo,
            packet=candidate,
            signed_approval=signed,
            phase_b_receipt=phase,
            permission_receipt=permission,
            allow_synthetic=True,
        )
    except (predecessor.DemandAwareBReadinessError, KeyError, TypeError, ValueError):
        return {
            "case": case,
            "status": "REJECTED_BEFORE_CREDENTIAL_LOOKUP",
            "real_boundary_reached": False,
            "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        }
    raise predecessor.DemandAwareBReadinessError(f"negative_case_accepted:{case}")


def negative_test_matrix_v1(
    repo: Path, packet: Mapping[str, Any],
) -> dict[str, Any]:
    precredential = [
        run_precredential_negative_case_v1(repo, packet, case)
        for case in PRECREDENTIAL_NEGATIVE_CASES
    ]
    postdispatch = [
        _runtime["run_postdispatch_case_v1"](case)
        for case in POSTDISPATCH_FAILURE_CASES
    ]
    return {
        "schema": "SkillV2Pair1ResidualV3BOnlyNegativeTestMatrixV1",
        "version": 1,
        "precredential_case_count": len(precredential),
        "precredential_pass_count": len(precredential),
        "postdispatch_case_count": len(postdispatch),
        "postdispatch_single_attempt_pass_count": len(postdispatch),
        "total_case_count": len(precredential) + len(postdispatch),
        "cases": precredential + postdispatch,
        "real_external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        "overall_status": "PASS",
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def build_documents_v1(
    repo: Path,
    *,
    approval_parent_head: str,
    validation: Mapping[str, Any],
    temp_root: Path,
    require_parent: bool = True,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    documents, _ = _runtime["build_documents_v1"](
        repo,
        approval_parent_head=approval_parent_head,
        validation=validation,
        temp_root=temp_root,
        require_parent=require_parent,
    )
    for name in (
        "privacy-scan-v1.json", "manifest-coverage-receipt-v1.json",
        "sha256-manifest-v1.json", "final-report-v1.md",
    ):
        documents.pop(f"{EVIDENCE_ROOT}/{name}", None)
    packet, bindings = build_approval_readiness_packet(
        repo, approval_parent_head=approval_parent_head, require_parent=require_parent,
    )
    phase_a = _runtime["phase_a_preapproval_readiness_v1"](repo, packet)
    negative = negative_test_matrix_v1(repo, packet)
    dry_run = _runtime["offline_execution_dry_run_v1"](repo, packet, temp_root)

    def add(name: str, value: Any) -> None:
        documents[f"{EVIDENCE_ROOT}/{name}"] = (
            _text_bytes(value) if isinstance(value, str) else _json_bytes(value)
        )

    add("README.md", """# Pair 1 residual V3 B-only approval readiness

Offline-only readiness evidence for the exact disabled residual V3 B treatment. No signed approval, nonce, credential, Provider response, model call, or execution authority is present.
""")
    add("candidate-binding-v1.json", bindings["candidate"])
    add("v3-profile-context-binding-v1.json", residual_v3_skill_binding_v1(repo))
    add("a-control-reuse-binding-v1.json", bindings["a_control"])
    add("successor-v3-ab-lock-binding-v1.json", {
        "schema": "SkillV2Pair1ResidualV3ABLockBindingV1",
        "version": 1,
        "pair_case_id": PAIR_CASE_ID,
        "skill_arm": SKILL_ARM,
        "successor_v3_ab_lock_sha256": AB_LOCK_SHA256,
        "unintended_ab_lock_diff_count": 0,
        "v2_profile_context_substitution_allowed": False,
        "status": "exact",
    })
    add("approval-readiness-packet-v1.json", packet)
    add("phase-a-preapproval-readiness-v1.json", phase_a)
    add("negative-test-matrix-v1.json", negative)
    add("offline-dry-run-v1.json", dry_run)
    add("future-data-egress-scope-v1.json", {
        **_runtime["future_data_egress_scope_v1"](repo),
        "only_new_v3_b_packet_required_data_egress": True,
        "private_blind_evidence_egress": False,
    })
    add("change-contract-v1.json", {
        "schema": "SkillV2Pair1ResidualV3BOnlyApprovalReadinessChangeContractV1",
        "version": 1,
        "scope_classification": "closed_world",
        "authorization": "implementation_offline_only",
        "allowed_changes": [SOURCE_PATH, TEST_PATH, f"{EVIDENCE_ROOT}/**"],
        "protected_source_diff_count": 0,
        "resolution_status": "case_fixed",
    })
    add("forward-risk-report-v2.json", {
        "version": 2,
        "original_requirement": "Bind the exact sealed residual V3 Pair 1 B-only candidate for later fresh approval and one request.",
        "scope_classification": "closed_world",
        "operational_definition": "Canary-only exact V3 adapter over the sealed one-shot execution engine.",
        "forbidden_narrowing": ["no V2 substitution", "no historical prose", "no retry/fallback/resume", "no authority mutation"],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {"requirement": "V3 identity", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "candidate/profile/lock bindings"},
            {"requirement": "one-shot and terminal tail", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "contracts and dry run"},
            {"requirement": "preapproval only", "implementation": SOURCE_PATH, "test_paths": [TEST_PATH], "evidence": "Phase A and nonce receipts"},
        ],
        "historical_incident_families_checked": ["stale binding", "profile substitution", "hidden retry", "nonce replay", "historical prose leakage", "authority mutation"],
        "projected_failure_mechanisms": ["binding drift", "approval staleness", "replay", "egress contamination"],
        "why_previous_tests_missed": "The predecessor launcher froze V2 before the sealed residual V3 successor existed.",
        "sibling_boundaries": [
            {"boundary": "production runtime", "disposition": "not_applicable", "evidence": "tools/canary only; src and baml unchanged"},
            {"boundary": "Pair2-5", "disposition": "tested_not_susceptible", "evidence": "closed identity and negative matrix"},
            {"boundary": "StoryState Canon READY", "disposition": "tested_not_susceptible", "evidence": "zero-mutation signed contract"},
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "Existing conversion, validator, artifact freeze, audit serialization and persistence functions are reused unchanged.",
        "production_shaped_tests": [TEST_PATH],
        "next_authoritative_boundary_tests": [TEST_PATH],
        "remaining_risks": ["Literary comparison requires a separately approved B execution and fresh blind evaluation."],
    })
    add("manifest-definition-v1.json", {
        "schema": "SkillV2Pair1ResidualV3BOnlyManifestDefinitionV1",
        "version": 1,
        "algorithm": "SHA-256",
        "path_format": "repository-relative POSIX",
        "entry_order": "path ascending",
        "coverage": "all evidence payload files except manifest and final report",
        "historical_evidence_rewritten": False,
    })
    privacy = _runtime["_privacy_scan"](documents)
    _require(privacy["privacy_match_count"] == 0, "privacy_scan_failed")
    add("privacy-scan-v1.json", privacy)
    covered_before_receipt = len(documents)
    add("manifest-coverage-receipt-v1.json", {
        "schema": "SkillV2Pair1ResidualV3BOnlyManifestCoverageReceiptV1",
        "version": 1,
        "covered_payload_count_before_receipt": covered_before_receipt,
        "manifest_excludes": ["sha256-manifest-v1.json", "final-report-v1.md"],
        "coverage_status": "exact",
    })
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha(data)}
        for path, data in sorted(documents.items())
    ]
    manifest_definition_sha = _sha(documents[f"{EVIDENCE_ROOT}/manifest-definition-v1.json"])
    manifest = _json_bytes({
        "schema": "SkillV2Pair1ResidualV3BOnlySha256ManifestV1",
        "version": 1,
        "algorithm": "SHA-256",
        "entry_count": len(entries),
        "files": entries,
        "definition_sha256": _runtime["_domain"]("skill-v2-pair1-residual-v3-b-only-sha256-manifest-v1", entries),
        "coverage": "all evidence payload files except manifest and final report",
        "overall_status": "exact",
    })
    manifest_sha = _sha(manifest)
    documents[f"{EVIDENCE_ROOT}/sha256-manifest-v1.json"] = manifest
    focused = validation.get("focused", "PENDING")
    adjacent = validation.get("adjacent", "PENDING")
    full_suite = validation.get("full_suite", "PENDING")
    strict_l3 = validation.get("strict_l3", "PENDING")
    report = f"""# Pair 1 residual V3 B-only approval readiness — Final Report

- Branch: `{EXPECTED_BRANCH}`
- Baseline/materialization parent HEAD: `{BASELINE_HEAD}`
- Launcher/approval parent HEAD: `{approval_parent_head}`
- Final evidence seal: `THIS_COMMIT`
- Candidate SHA: `{CANDIDATE_SHA256}`
- Revalidation case / arm / Skill: `{PAIR_CASE_ID}` / `{ARM_ROLE}` / `{SKILL_ARM}`
- V3 profile/context: `{PROFILE_SHA256}` / `{CONTEXT_SHA256}` / `{CONTEXT_CHARACTERS}` chars
- Successor V3 A/B lock: `{AB_LOCK_SHA256}`
- A-control reuse/injection: `PASS/NO`; historical-B isolation: `PASS`
- Execution entry / launcher / single dispatch / terminal local pipeline: `PASS/PASS/PASS/PASS`
- Approval-readiness packet: `{packet['approval_readiness_packet_sha256']}`
- Phase A: `PASS`; Phase B: `NOT_EXECUTED`
- Signed Approval: `ABSENT`; execution authorized: `false`
- Nonce: `NOT_YET_CREATED_BY_DESIGN`; reserved `NO`; consumed `NO`
- Permission before nonce / future reconfirmation: `YES/YES`
- Negative matrix: `{negative['total_case_count']}/{negative['total_case_count']} PASS`
- Offline dry-run: `PASS`; real boundary reached `NO`
- Tests: focused `{focused}`; adjacent `{adjacent}`; full `{full_suite}`
- Strict L3: `{strict_l3}`; warnings `{validation.get('strict_l3_warnings', 'PENDING')}`; blockers `{validation.get('strict_l3_blockers', 'PENDING')}`
- New owning-source regressions: `{validation.get('new_owning_source_regression_count', 0)}`
- Source/tool diff: `{SOURCE_PATH}`, `{TEST_PATH}` only; production/baml diff `0`
- Pair2-5: `BLOCKED`; Skill V2/Planning V2 cutover: `NOT_AUTHORIZED/NOT_AUTHORIZED`
- Privacy: `PASS`; match count `0`
- Manifest definition file SHA: `{manifest_definition_sha}`
- Manifest file SHA: `{manifest_sha}`
- Manifest coverage: `{len(entries)}/{len(entries)}` payload files
- External counters: all `0`; Full Short: `NOT_EXECUTED`

`SKILL_V2_PAIR_1_RESIDUAL_V3_B_ONLY_REVALIDATION_APPROVAL_READY=YES`

Exact next gate: `SKILL_V2_PAIR_1_RESIDUAL_V3_B_ONLY_REVALIDATION_FRESH_USER_APPROVAL`.

`SIGNED_APPROVAL_PRESENT=NO`
`EXECUTION_AUTHORIZED=false`
`PHASE_B_APPROVAL_TIME_SIGNED_PREFLIGHT=NOT_EXECUTED`
`NONCE_RESERVED=NO`
`NONCE_CONSUMED=NO`
`PAIR2_TO_5_EXECUTION_ALLOWED=NO`
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`
`HTTP_POST_ATTEMPTS=0`
`NETWORK_CALLS=0`
`MODEL_CALLS=0`
`PAID_CALLS=0`
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    add("final-report-v1.md", report)
    return documents, {
        "approval_readiness_packet_sha256": packet["approval_readiness_packet_sha256"],
        "negative_test_count": negative["total_case_count"],
        "privacy_match_count": 0,
        "manifest_definition_file_sha256": manifest_definition_sha,
        "manifest_file_sha256": manifest_sha,
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


DemandAwareBReadinessError = predecessor.DemandAwareBReadinessError
historical_b_isolation_v1 = _runtime["historical_b_isolation_v1"]
resolve_execution_entry_point = _runtime["resolve_execution_entry_point"]
phase_a_preapproval_readiness_v1 = _runtime["phase_a_preapproval_readiness_v1"]
offline_execution_dry_run_v1 = _runtime["offline_execution_dry_run_v1"]
run_postdispatch_case_v1 = _runtime["run_postdispatch_case_v1"]
single_dispatch_contract_v1 = _runtime["single_dispatch_contract_v1"]
terminal_local_pipeline_contract_v1 = _runtime["terminal_local_pipeline_contract_v1"]
launcher_architecture_v1 = _runtime["launcher_architecture_v1"]
validate_approval_parent_source_policy = _runtime["validate_approval_parent_source_policy"]
validate_head_successor_v1 = _runtime["validate_head_successor_v1"]
future_permission_before_nonce_v1 = _runtime["future_permission_before_nonce_v1"]
future_data_egress_scope_v1 = _runtime["future_data_egress_scope_v1"]
nonce_readiness_v1 = _runtime["nonce_readiness_v1"]
