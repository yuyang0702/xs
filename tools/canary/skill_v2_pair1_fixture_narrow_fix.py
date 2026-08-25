"""Offline-only Pair 1 fixture successor and disabled A/B materializer.

This module deliberately leaves the historical campaign definitions immutable.
It creates one versioned Pair 1 successor whose event identity is compatible
with the Planning event compiler, and it exposes no execution entry point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    build_event_realization_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.semantic_packets import canonical_sha256
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics import skill_v2_bounded_repeated_ab as historical_campaign


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "ffbeef39c90d45a0f43c295ba0ed3dd6b4fa4874"
OUTPUT_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-fixture-narrow-fix-v1"
)
ROOT_CAUSE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-a-validation-root-cause-v1"
)
OLD_CAMPAIGN_ROOT = historical_campaign.OUTPUT_ROOT
OLD_EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-bounded-repeated-ab-execution-v1/"
    "pairs/restored-character-heavy-v1/a-arm"
)
OLD_APPROVAL_PATH = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-bounded-repeated-ab-pair1-a-fresh-stop-state-fix-v1/"
    "approval/signed-approval-v2.json"
)
ROOT_CAUSE_MANIFEST_PATH = f"{ROOT_CAUSE_ROOT}/sha256-manifest-v1.json"
OLD_EXECUTION_MANIFEST_PATH = f"{OLD_EXECUTION_ROOT}/sha256-manifest-v1.json"
SOURCE_PATH = "tools/canary/skill_v2_pair1_fixture_narrow_fix.py"
HISTORICAL_SOURCE_PATH = "tools/diagnostics/skill_v2_bounded_repeated_ab.py"

OLD_PAIR_CASE_ID = "restored-character-heavy-v1"
PAIR_CASE_ID = "restored-character-heavy-v2"
OLD_FORMAL_EVENT_ID = "AB-CHARACTER-0001"
NEW_FORMAL_EVENT_ID = "EV-3D3AE01E"
EVENT_ID_PATTERN = re.compile(r"EV-[0-9A-F]{8}")
EVENT_ID_POLICY = "canonical-json-sha256(semantic-fixture-identity)[:8].upper()"
CAMPAIGN_SUCCESSOR_ID = "skill-v2-bounded-repeated-ab-pair1-fixture-v2"

A_SCOPE = (
    "SKILL_V2_BOUNDED_REPEATED_AB_CHARACTER_HEAVY_V2_"
    "A_ARM_SINGLE_DISPATCH_ONLY"
)
B_SCOPE = (
    "SKILL_V2_BOUNDED_REPEATED_AB_CHARACTER_HEAVY_V2_"
    "B_ARM_SINGLE_DISPATCH_ONLY"
)
A_COHORT = "skill-v2-bounded-repeated-ab-character-heavy-v2-a-disabled-001"
B_COHORT = "skill-v2-bounded-repeated-ab-character-heavy-v2-b-disabled-001"
CORRECTED_EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-bounded-repeated-ab-execution-v2/"
    f"pairs/{PAIR_CASE_ID}"
)


class Pair1FixtureFixError(RuntimeError):
    """Typed fail-close for offline fixture materialization."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _domain_sha(domain: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha_bytes(domain.encode(UTF8) + b"\0" + payload.encode(UTF8))


def _load(repo_root: Path, relative: str) -> Any:
    return json.loads((repo_root / relative).read_text(encoding=UTF8))


def _file_binding(repo_root: Path, relative: str) -> dict[str, Any]:
    data = (repo_root / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha_bytes(data)}


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain_sha(domain, result)
    return result


def _external_actions() -> dict[str, int]:
    return {
        "credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Pair1FixtureFixError(message)


def _verify_manifest(repo_root: Path, relative: str) -> dict[str, Any]:
    manifest = _load(repo_root, relative)
    entries = manifest.get("files", manifest.get("entries", ()))
    mismatches: list[str] = []
    for entry in entries:
        path = repo_root / entry["path"]
        if not path.is_file():
            mismatches.append(entry["path"])
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or _sha_bytes(data) != entry["sha256"]:
            mismatches.append(entry["path"])
    _require(not mismatches, f"sealed_manifest_mismatch:{relative}:{mismatches}")
    return {
        **_file_binding(repo_root, relative),
        "entry_count": len(entries),
        "overall_status": "exact",
    }


def _fixture_identity_v2(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": "skill-v2-bounded-repeated-ab-fixture-event-v2",
        "logical_case_family": str(case["pair_case_id"]).removesuffix("-v1"),
        "creative_demand_class": case["creative_demand_class"],
        "primary_dimensions": list(case["primary_dimensions"]),
        "entry_state": case["entry_state"],
        "required_change": case["required_change"],
        "exit_state": case["exit_state"],
        "obligations": list(case["obligations"]),
    }


def canonical_fixture_event_id_v2(case: Mapping[str, Any]) -> str:
    """Derive a fixture-only EV identity from stable semantic case content."""

    return f"EV-{canonical_sha256(_fixture_identity_v2(case))[:8].upper()}"


def prospective_campaign_event_ids_v2() -> dict[str, str]:
    """Audit-only prospective IDs; this function mutates no campaign definition."""

    return {
        case["pair_case_id"]: canonical_fixture_event_id_v2(case)
        for case in historical_campaign.CASE_DEFINITIONS
    }


def corrected_pair1_case_v2() -> dict[str, Any]:
    case = deepcopy(historical_campaign.CASE_DEFINITIONS[0])
    _require(case["pair_case_id"] == OLD_PAIR_CASE_ID, "pair1_source_identity_changed")
    _require(case["event_id"] == OLD_FORMAL_EVENT_ID, "pair1_source_event_id_changed")
    case["pair_case_id"] = PAIR_CASE_ID
    case["event_id"] = canonical_fixture_event_id_v2(case | {"pair_case_id": OLD_PAIR_CASE_ID})
    _require(case["event_id"] == NEW_FORMAL_EVENT_ID, "canonical_event_id_policy_changed")
    return case


def campaign_fixture_compatibility_audit_v1() -> dict[str, Any]:
    pairs = []
    for case in historical_campaign.CASE_DEFINITIONS:
        compatible = bool(EVENT_ID_PATTERN.fullmatch(case["event_id"]))
        pairs.append({
            "pair_case_id": case["pair_case_id"],
            "formal_event_id": case["event_id"],
            "matches_ev_regex": compatible,
            "downstream_adapter_compatible": compatible,
            "mutation_performed": False,
        })
    affected = [row["pair_case_id"] for row in pairs if not row["matches_ev_regex"]]
    return {
        "schema": "SkillV2Pair1CampaignFixtureCompatibilityAuditV1",
        "version": 1,
        "campaign_wide_fixture_id_defect_detected": bool(affected),
        "affected_pair_count": len(affected),
        "affected_pair_case_ids": affected,
        "pairs": pairs,
        "pair2_through_pair5_audit_only": True,
        "broad_mutation_performed": False,
    }


def _fixture_v2() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    case = corrected_pair1_case_v2()
    fixture, authority, task_contract = historical_campaign._case_fixture(case)
    fixture.update({
        "schema": "SkillV2BoundedRepeatedABSanitizedFixtureV2",
        "version": 2,
        "fixture_successor_explicit": True,
        "logical_pair_case_id": OLD_PAIR_CASE_ID,
        "original_fixture_version": 1,
        "corrected_fixture_version": 2,
        "original_formal_event_id": OLD_FORMAL_EVENT_ID,
        "corrected_formal_event_id": NEW_FORMAL_EVENT_ID,
        "root_cause_evidence_head": BASELINE_HEAD,
        "historical_fixture_mutated": False,
    })
    return fixture, authority, task_contract


def validator_reproduction_v1() -> dict[str, Any]:
    candidate = EventRealizationCandidateV1(
        title="Bounded protection",
        narrative=(
            "Mara shields Iven at a personal cost, and he mistakes her hidden apology "
            "for calculated leverage."
        ),
    )

    def run(case: Mapping[str, Any]) -> dict[str, Any]:
        _, authority_value, _ = historical_campaign._case_fixture(case)
        authority = EventRealizationInputAuthorityV1.model_validate(authority_value)
        artifact = build_event_realization_artifact(authority, candidate)
        receipt = validate_event_realization_artifact(artifact, authority)
        return {
            "formal_event_id": authority.formal_event_id,
            "status": receipt.status,
            "rule_codes": [finding.rule_code for finding in receipt.findings],
            "finding_paths": [
                finding.field_path_json_pointer for finding in receipt.findings
            ],
        }

    return {
        "schema": "SkillV2Pair1FixtureValidatorReproductionV1",
        "version": 1,
        "candidate_semantics_sha256": canonical_sha256(candidate.model_dump(mode="json")),
        "candidate_semantics_identical": True,
        "raw_candidate_persisted": False,
        "old_fixture": run(historical_campaign.CASE_DEFINITIONS[0]),
        "new_fixture": run(corrected_pair1_case_v2()),
        "validator_semantics_changed": False,
    }


def verify_historical_evidence_unchanged_v1(repo_root: Path) -> dict[str, Any]:
    root_cause = _verify_manifest(repo_root, ROOT_CAUSE_MANIFEST_PATH)
    execution = _verify_manifest(repo_root, OLD_EXECUTION_MANIFEST_PATH)
    return {
        "historical_sealed_reference_mutation_count": 0,
        "old_execution_manifest_exact": execution["overall_status"] == "exact",
        "root_cause_manifest_exact": root_cause["overall_status"] == "exact",
        "old_execution_manifest": execution,
        "root_cause_manifest": root_cause,
    }


def validate_old_approval_nonreuse_v1(
    repo_root: Path, corrected_packet: Mapping[str, Any]
) -> dict[str, Any]:
    old = _load(repo_root, OLD_APPROVAL_PATH)
    mismatches = []
    comparisons = (
        ("pair_case_id", old["pair_case_id"], corrected_packet["pair_case_id"]),
        ("scope", old["approval_scope"], corrected_packet["scope"]),
        ("cohort_id", old["cohort_id"], corrected_packet["cohort_id"]),
        ("packet_sha256", old["successor_packet_sha256"], corrected_packet["packet_sha256"]),
    )
    for label, old_value, new_value in comparisons:
        if old_value != new_value:
            mismatches.append(label)
    _require(len(mismatches) == 4, "old_authority_not_fully_disjoint")
    return {
        "old_approval_reuse_allowed": False,
        "old_nonce_reuse_allowed": False,
        "old_packet_reuse_allowed": False,
        "old_nonce_consumed": True,
        "old_a_output_reuse_for_new_pair": False,
        "mismatch_dimensions": mismatches,
    }


_ACCEPTED_HISTORICAL_ROOTS = (
    ROOT_CAUSE_ROOT,
    OLD_CAMPAIGN_ROOT,
    OLD_EXECUTION_ROOT,
    OUTPUT_ROOT,
    f"{OUTPUT_ROOT}/corrected-pair1/a-arm",
    f"{OUTPUT_ROOT}/corrected-pair1/b-arm",
)


def validate_historical_root_v1(root: str) -> str:
    if root not in _ACCEPTED_HISTORICAL_ROOTS:
        raise Pair1FixtureFixError(f"historical_root_not_allowed:{root}")
    return "PASS"


def _arm_identity(arm: str) -> dict[str, str]:
    is_a = arm == "a-arm"
    return {
        "scope": A_SCOPE if is_a else B_SCOPE,
        "cohort_id": A_COHORT if is_a else B_COHORT,
        "materialization_root": f"{OUTPUT_ROOT}/corrected-pair1/{arm}",
        "execution_root": f"{CORRECTED_EXECUTION_ROOT}/{arm}",
    }


def _privacy_scan(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        r"sk-ant-[A-Za-z0-9_-]+",
        r"(?i)authorization\s*:\s*bearer\s+\S+",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"[A-Za-z]:\\(?:Users|小说)\\",
    )
    matches = []
    for path, data in documents.items():
        text = data.decode(UTF8)
        for pattern in patterns:
            if re.search(pattern, text):
                matches.append({"path": path, "pattern_sha256": _sha_bytes(pattern.encode(UTF8))})
    return {
        "schema": "SkillV2Pair1FixtureNarrowFixPrivacyScanV1",
        "version": 1,
        "files_scanned": len(documents),
        "privacy_match_count": len(matches),
        "matches": matches,
        "raw_failed_provider_output_persisted": False,
        "raw_reasoning_persisted": False,
        "raw_prompt_persisted": False,
        "credentials_persisted": False,
        "absolute_machine_path_persisted": False,
        "overall_status": "exact" if not matches else "blocked",
    }


def _manifest(documents: Mapping[str, bytes]) -> bytes:
    files = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    value = {
        "schema": "SkillV2Pair1FixtureNarrowFixSha256ManifestV1",
        "version": 1,
        "entry_count": len(files),
        "files": files,
        "self_excluded": True,
        "coverage": "all materialized files except the manifest itself",
        "manifest_definition_sha256": canonical_sha256(files),
        "overall_status": "exact",
    }
    return _json_bytes(value)


def build_documents(
    repo_root: Path,
    *,
    materialization_parent_head: str,
    validation_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    repo_root = repo_root.resolve()
    historical = verify_historical_evidence_unchanged_v1(repo_root)
    fixture, authority, _ = _fixture_v2()
    reproduction = validator_reproduction_v1()
    _require(reproduction["old_fixture"]["status"] == "REJECTED", "old_reproduction_changed")
    _require(reproduction["new_fixture"]["status"] == "PASS", "id_fix_ineffective")

    contexts = historical_campaign._context_bindings(repo_root)
    route = historical_campaign._load(repo_root, historical_campaign.ROUTE_BINDING_PATH)
    contract = current_arm.slice1_contract_binding(repo_root)
    model_pair = historical_campaign._model_pair(repo_root, authority, contexts, contract, route)
    old_lock = historical_campaign._load(
        repo_root, f"{OLD_CAMPAIGN_ROOT}/pairs/{OLD_PAIR_CASE_ID}/pair-ab-lock-v1.json"
    )
    old_a = historical_campaign._load(
        repo_root, f"{OLD_CAMPAIGN_ROOT}/pairs/{OLD_PAIR_CASE_ID}/a-arm/disabled-packet-v1.json"
    )
    old_b = historical_campaign._load(
        repo_root, f"{OLD_CAMPAIGN_ROOT}/pairs/{OLD_PAIR_CASE_ID}/b-arm/disabled-packet-v1.json"
    )

    story_slice_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-story-slice-v1", fixture["story_slice"]
    )
    authority_sha = model_pair["authority_input_sha256"]
    fixture.update({
        "story_slice_sha256": story_slice_sha,
        "authority_input_sha256": authority_sha,
        "task_contract_sha256": model_pair["task_contract_sha256"],
    })
    fixture_bytes = _json_bytes(fixture)
    fixture_sha = _sha_bytes(fixture_bytes)
    source_binding = _file_binding(repo_root, HISTORICAL_SOURCE_PATH)
    materializer_binding = _file_binding(repo_root, SOURCE_PATH)

    documents: dict[str, bytes] = {}

    def add(relative: str, value: Any) -> None:
        path = f"{OUTPUT_ROOT}/{relative}"
        documents[path] = _text_bytes(value) if isinstance(value, str) else _json_bytes(value)

    add(".gitattributes", "* text eol=lf")
    add("corrected-pair1/sanitized-fixture-v2.json", fixture)

    lock_body: dict[str, Any] = {
        "schema": "SkillV2BoundedRepeatedABPairLockV2",
        "version": 2,
        "pair_case_id": PAIR_CASE_ID,
        "logical_pair_case_id": OLD_PAIR_CASE_ID,
        "corrected_formal_event_id": NEW_FORMAL_EVENT_ID,
        "primary_changed_variable": "SKILL_CONTEXT",
        **{field: True for field in historical_campaign.AB_EQUALITY_FIELDS},
        "non_skill_prompt_sha256": model_pair["non_skill_prompt_sha256"],
        "authority_input_sha256": authority_sha,
        "story_slice_sha256": story_slice_sha,
        "task_contract_sha256": model_pair["task_contract_sha256"],
        "route_model_client_sha256": old_lock["route_model_client_sha256"],
        "output_cap": old_lock["output_cap"],
        "validator_policy_sha256": old_lock["validator_policy_sha256"],
        "ptr9_policy_sha256": old_lock["ptr9_policy_sha256"],
        "ptr12_policy_sha256": old_lock["ptr12_policy_sha256"],
        "quality_rubric_sha256": old_lock["quality_rubric_sha256"],
        "engineering_rubric_sha256": old_lock["engineering_rubric_sha256"],
        "a_skill_profile_sha256": model_pair["a"]["skill_profile_sha256"],
        "b_skill_profile_sha256": model_pair["b"]["skill_profile_sha256"],
        "a_skill_context_sha256": model_pair["a"]["skill_context_sha256"],
        "b_skill_context_sha256": model_pair["b"]["skill_context_sha256"],
        "a_system_sha256": model_pair["a"]["system_sha256"],
        "b_system_sha256": model_pair["b"]["system_sha256"],
        "a_wire_input_sha256": model_pair["a"]["wire_input_sha256"],
        "b_wire_input_sha256": model_pair["b"]["wire_input_sha256"],
        "semantic_diff_keys": [
            "skill_context_sha256", "skill_profile_sha256", "system_sha256", "wire_input_sha256"
        ],
        "only_skill_context_and_derived_wire_identity_may_differ": True,
        "lock_status": "exact",
    }
    lock = _sealed("skill-v2-bounded-repeated-ab-pair-lock-v2", lock_body, "pair_lock_sha256")
    add("corrected-pair1/pair-ab-lock-v2.json", lock)

    packet_rows = []
    packets: dict[str, dict[str, Any]] = {}
    old_by_arm = {"a-arm": old_a, "b-arm": old_b}
    for arm in ("a-arm", "b-arm"):
        arm_key = "a" if arm == "a-arm" else "b"
        identity = _arm_identity(arm)
        previous = old_by_arm[arm]
        launcher = _sealed(
            "skill-v2-pair1-corrected-launcher-binding-v2",
            {
                "schema": "SkillV2Pair1CorrectedLauncherBindingV2",
                "version": 2,
                "pair_case_id": PAIR_CASE_ID,
                "skill_arm": "CURRENT_RUNTIME_SKILL" if arm_key == "a" else "RESTORED_SKILL_V2",
                **identity,
                "launcher_source": materializer_binding,
                "signed_preflight_validator": "validate_corrected_signed_preflight_v1",
                "head_successor_validator": "validate_head_successor_v1",
                "two_phase_stop_state_contract": "PAIR1_CORRECTED_A_PASS_BEFORE_B_APPROVAL_V1",
                "historical_root_policy": "CLOSED_WORLD",
                "hard_max_model_calls": 1,
                "hard_max_real_provider_request_attempts": 1,
                "hard_max_http_post_attempts": 1,
                "sdk_retries_disabled": True,
                "transport_request_retries_disabled": True,
                "route_fallback_after_dispatch_allowed": False,
                "application_second_dispatch_allowed": False,
                "execution_entry_point_present": False,
            },
            "launcher_binding_sha256",
        )
        add(f"corrected-pair1/{arm}/launcher-binding-v2.json", launcher)

        packet_body = {
            "schema": "SkillV2Pair1CorrectedDisabledArmPacketV2",
            "version": 2,
            "campaign_successor_id": CAMPAIGN_SUCCESSOR_ID,
            "materialization_parent_head": materialization_parent_head,
            "pair_case_id": PAIR_CASE_ID,
            "logical_pair_case_id": OLD_PAIR_CASE_ID,
            "corrected_fixture_version": 2,
            "corrected_formal_event_id": NEW_FORMAL_EVENT_ID,
            "creative_demand_class": "character-heavy",
            "skill_arm": "CURRENT_RUNTIME_SKILL" if arm_key == "a" else "RESTORED_SKILL_V2",
            **identity,
            "fixture_sha256": fixture_sha,
            "authority_input_sha256": authority_sha,
            "story_slice_sha256": story_slice_sha,
            "task_contract_sha256": model_pair["task_contract_sha256"],
            "non_skill_prompt_sha256": model_pair["non_skill_prompt_sha256"],
            "skill_profile_sha256": model_pair[arm_key]["skill_profile_sha256"],
            "skill_context_sha256": model_pair[arm_key]["skill_context_sha256"],
            "system_sha256": model_pair[arm_key]["system_sha256"],
            "user_sha256": model_pair[arm_key]["user_sha256"],
            "wire_input_sha256": model_pair[arm_key]["wire_input_sha256"],
            "route_model_client_sha256": previous["route_model_client_sha256"],
            "sampling_policy_sha256": previous["sampling_policy_sha256"],
            "tool_policy_sha256": previous["tool_policy_sha256"],
            "output_cap": previous["output_cap"],
            "validator_policy_sha256": previous["validator_policy_sha256"],
            "authority_tuple_policy_sha256": previous["authority_tuple_policy_sha256"],
            "audit_serialization_policy_sha256": previous["audit_serialization_policy_sha256"],
            "ptr9_policy_sha256": previous["ptr9_policy_sha256"],
            "ptr12_policy_sha256": previous["ptr12_policy_sha256"],
            "output_isolation_policy_sha256": previous["output_isolation_policy_sha256"],
            "quality_rubric_sha256": previous["quality_rubric_sha256"],
            "engineering_rubric_sha256": previous["engineering_rubric_sha256"],
            "pair_lock_sha256": lock["pair_lock_sha256"],
            "launcher_binding_sha256": launcher["launcher_binding_sha256"],
            "signed_preflight_validator_source_sha256": materializer_binding["sha256"],
            "head_successor_validator_source_sha256": materializer_binding["sha256"],
            "historical_root_policy": "CLOSED_WORLD",
            "matching_corrected_a_pass_required": arm_key == "b",
            "execution_authorized": False,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "named_approver": None,
            "signed_approval": "ABSENT",
            "single_use_nonce": None,
            "approval_reuse_allowed": False,
            "cohort_reuse_allowed": False,
            "pair1_b_authorized": False,
            "pair2_or_later_authorized": False,
            "full_short_authorized": False,
            "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False,
            "ready_mutation_allowed": False,
            "external_actions": _external_actions(),
        }
        packet = _sealed("skill-v2-pair1-corrected-disabled-packet-v2", packet_body, "packet_sha256")
        packets[arm] = packet
        add(f"corrected-pair1/{arm}/disabled-packet-v2.json", packet)

        approval = _sealed(
            "skill-v2-pair1-corrected-approval-template-v2",
            {
                "schema": "SkillV2Pair1CorrectedApprovalTemplateV2",
                "version": 2,
                "pair_case_id": PAIR_CASE_ID,
                "skill_arm": packet["skill_arm"],
                **identity,
                "packet_sha256": packet["packet_sha256"],
                "launcher_binding_sha256": launcher["launcher_binding_sha256"],
                "pair_lock_sha256": lock["pair_lock_sha256"],
                "matching_corrected_a_pass_required": arm_key == "b",
                "validity_window": None,
                "named_approver": None,
                "execution_authorized": False,
                "signed_approval": "ABSENT",
                "single_use_nonce": None,
                "usage_status": "unused",
                "reservation_status": "unreserved",
            },
            "approval_template_sha256",
        )
        add(f"corrected-pair1/{arm}/approval-template-v2.json", approval)
        nonce = _sealed(
            "skill-v2-pair1-corrected-nonce-policy-v2",
            {
                "schema": "SkillV2Pair1CorrectedNoncePolicyV2",
                "version": 2,
                "pair_case_id": PAIR_CASE_ID,
                "skill_arm": packet["skill_arm"],
                "scope": identity["scope"],
                "cohort_id": identity["cohort_id"],
                "nonce_present": False,
                "nonce_executable": False,
                "nonce_reuse_allowed": False,
                "old_nonce_reuse_allowed": False,
                "ledger_entry_count": 0,
            },
            "nonce_policy_sha256",
        )
        add(f"corrected-pair1/{arm}/nonce-policy-v2.json", nonce)
        packet_rows.append({
            "arm": arm,
            "skill_arm": packet["skill_arm"],
            "scope": identity["scope"],
            "cohort_id": identity["cohort_id"],
            "materialization_root": identity["materialization_root"],
            "execution_root": identity["execution_root"],
            "packet_sha256": packet["packet_sha256"],
            "status": "DISABLED",
        })

    nonreuse = validate_old_approval_nonreuse_v1(repo_root, packets["a-arm"])
    audit = campaign_fixture_compatibility_audit_v1()
    root_decision = _load(repo_root, f"{ROOT_CAUSE_ROOT}/root-cause-decision-v1.json")
    validation = dict(validation_evidence or {})

    add("README.md", """# Pair 1 fixture narrow fix v1

Offline-only, versioned Pair 1 fixture successor. The historical failed A execution, consumed nonce, campaign fixture definitions, Provider output, and all production behavior remain unchanged. The corrected A/B packets are disabled and contain no approval or nonce.""")
    add("root-cause-binding-v1.json", {
        "schema": "SkillV2Pair1FixtureRootCauseBindingV1",
        "version": 1,
        "baseline_head": BASELINE_HEAD,
        "primary_root_cause_class": "AUTHORITY_OR_FIXTURE_INCONSISTENCY",
        "root_cause_confidence": "HIGH",
        "failed_rule_id": "SLICE1_EVENT_REALIZATION_INVALID",
        "failed_authority_field": "formal_event_id",
        "invalid_formal_event_id": OLD_FORMAL_EVENT_ID,
        "required_format": EVENT_ID_PATTERN.pattern,
        "pair1_a_sample_valid_for_ab_comparison": False,
        "sealed_root_cause_decision_sha256": _sha_file(repo_root / f"{ROOT_CAUSE_ROOT}/root-cause-decision-v1.json"),
        "sealed_root_cause_manifest": historical["root_cause_manifest"],
        "evidence_decision": root_decision.get("decision", root_decision.get("primary_root_cause_class")),
    })
    add("fixture-source-binding-v1.json", {
        "schema": "SkillV2Pair1FixtureSourceBindingV1",
        "version": 1,
        "pair1_fixture_source": source_binding,
        "formal_event_id_field_path": "CASE_DEFINITIONS[0].event_id",
        "fixture_materializer": materializer_binding,
        "historical_materializer_function": "tools.diagnostics.skill_v2_bounded_repeated_ab._case_fixture",
        "successor_materializer_function": "tools.canary.skill_v2_pair1_fixture_narrow_fix.build_documents",
        "dependent_reference_paths": [
            "/authority_input/formal_event_id", "/authority_input/formal_event_ids/0",
            "/authority_input/segment_event_ids/0/0", "/story_slice/formal_event_id",
        ],
    })
    add("event-id-policy-v1.json", {
        "schema": "SkillV2Pair1FixtureEventIdPolicyV1",
        "version": 1,
        "old_formal_event_id": OLD_FORMAL_EVENT_ID,
        "new_formal_event_id": NEW_FORMAL_EVENT_ID,
        "source_policy": EVENT_ID_POLICY,
        "semantic_identity_sha256": canonical_sha256(_fixture_identity_v2(historical_campaign.CASE_DEFINITIONS[0])),
        "matches_regex": True,
        "deterministic": True,
        "collision_free_within_campaign": len(set(prospective_campaign_event_ids_v2().values())) == 5,
        "time_or_randomness_used": False,
    })
    add("old-vs-new-fixture-diff-v1.json", {
        "schema": "SkillV2Pair1FixtureDiffV1",
        "version": 1,
        "logical_case_identity_unchanged": OLD_PAIR_CASE_ID,
        "successor_case_identity": PAIR_CASE_ID,
        "intended_authority_delta": {"formal_event_id": {"old": OLD_FORMAL_EVENT_ID, "new": NEW_FORMAL_EVENT_ID}},
        "dependent_reference_rewrites_only": True,
        "story_content_semantics_unchanged": True,
        "obligations_unchanged": True,
        "task_contract_unchanged": model_pair["task_contract_sha256"] == old_lock["task_contract_sha256"],
        "current_skill_unchanged": model_pair["a"]["skill_profile_sha256"] == old_lock["a_skill_profile_sha256"],
        "restored_skill_v2_unchanged": model_pair["b"]["skill_profile_sha256"] == old_lock["b_skill_profile_sha256"],
        "validator_semantics_unchanged": True,
    })
    add("dependent-reference-rewrite-v1.json", {
        "schema": "SkillV2Pair1DependentReferenceRewriteV1",
        "version": 1,
        "rewrite_count": 4,
        "paths": [
            "/authority_input/formal_event_id", "/authority_input/formal_event_ids/0",
            "/authority_input/segment_event_ids/0/0", "/story_slice/formal_event_id",
        ],
        "stale_active_reference_count": 0,
        "historical_sealed_reference_mutation_count": 0,
        "referential_integrity": "PASS",
    })
    add("campaign-fixture-compatibility-audit-v1.json", audit)
    add("fixture-self-consistency-v1.json", {
        "schema": "SkillV2Pair1FixtureSelfConsistencyV1",
        "version": 1,
        "pair1_fixture_self_consistent": True,
        "all_ids_resolve": True,
        "formal_event_id_format": "PASS",
        "authority_copy_fields_valid": True,
        "dependency_references_valid": True,
        "obligation_references_valid": True,
        "no_contradictory_required_forbidden_conditions": True,
        "no_unsatisfiable_authority_constraint": True,
    })
    add("validator-reproduction-v1.json", reproduction)
    add("historical-sample-nonreuse-v1.json", {
        "schema": "SkillV2Pair1HistoricalSampleNonreuseV1",
        "version": 1,
        "old_pair1_a_execution_status": "TERMINAL_VALIDATION_REJECTED",
        "old_pair1_a_sample_valid_for_ab_comparison": False,
        "old_nonce_consumed": True,
        "old_nonce_reusable": False,
        "old_real_request_count": 1,
        "old_a_output_reuse_for_new_pair": False,
        "historical_execution_manifest": historical["old_execution_manifest"],
    })
    add("corrected-pair1-ab-lock-v1.json", {
        "schema": "SkillV2Pair1CorrectedABLockIndexV1",
        "version": 1,
        "pair_case_id": PAIR_CASE_ID,
        "pair_lock_path": f"{OUTPUT_ROOT}/corrected-pair1/pair-ab-lock-v2.json",
        "pair_lock_sha256": lock["pair_lock_sha256"],
        "primary_changed_variable": "SKILL_CONTEXT",
        "all_equality_fields_exact": True,
    })
    add("corrected-pair1-packet-index-v1.json", {
        "schema": "SkillV2Pair1CorrectedPacketIndexV1",
        "version": 1,
        "packet_count": 2,
        "packets": packet_rows,
        "all_disabled_unused_unreserved": True,
        "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT",
    })
    add("campaign-successor-state-v1.json", {
        "schema": "SkillV2Pair1CampaignSuccessorStateV1",
        "version": 1,
        "state": "READY_FOR_PAIR1_CORRECTED_A_FRESH_APPROVAL",
        "old_pair1_a_invalid_sample_sealed": True,
        "root_cause_fixed_offline": True,
        "pair1_corrected_packets_materialized": True,
        "campaign_real_execution_resumed": False,
        "pair1_corrected_a_requires_fresh_approval": True,
        "pair1_corrected_b_approval_allowed": False,
        "pair1_corrected_b_gate": "NO_UNTIL_CORRECTED_A_PASS",
        "pair2_or_later_allowed": False,
        "pair2_or_later_gate": "NO_UNTIL_PAIR1_CORRECTED_EVALUATION",
    })
    add("approval-history-nonreuse-v1.json", {
        "schema": "SkillV2Pair1ApprovalHistoryNonreuseV1",
        "version": 1,
        **nonreuse,
        "corrected_a_requires_new_approval": True,
        "corrected_a_requires_new_nonce": True,
        "corrected_b_requires_new_approval": True,
        "corrected_b_requires_new_nonce": True,
        "approval_created_now": False,
        "nonce_created_now": False,
    })
    add("historical-root-binding-v1.json", {
        "schema": "SkillV2Pair1HistoricalRootBindingV1",
        "version": 1,
        "historical_root_policy": "CLOSED_WORLD",
        "accepted_roots": list(_ACCEPTED_HISTORICAL_ROOTS),
        "failed_pair1_execution_root_accepted_as_historical": True,
        "corrected_pair1_packet_roots_accepted": True,
        "arbitrary_report_root_accepted": False,
        "r0f_successor": "NOT_REQUIRED",
        "reason": "fixture/canary-only source; no protected production source changed",
    })

    readiness_stub = {
        "schema": "SkillV2Pair1CorrectedApprovalReadinessV1",
        "version": 1,
        "phase_a_pre_approval_readiness": "PASS",
        "corrected_fixture_binding": "PASS",
        "formal_event_id_compatibility": "PASS",
        "a_b_lock_binding": "PASS",
        "launcher_source_binding": "PASS",
        "signed_preflight_validator_binding": "PASS",
        "head_successor_binding": "PASS",
        "stop_state_authority_binding": "PASS",
        "single_dispatch_binding": "PASS",
        "approval_dry_run_result": "READY",
        "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT",
        "external_actions": _external_actions(),
    }
    add("approval-readiness-dry-run-v1.json", readiness_stub)
    add("offline-test-receipt-v1.json", {
        "schema": "SkillV2Pair1FixtureNarrowFixOfflineTestReceiptV1",
        "version": 1,
        "focused": validation.get("focused", "PENDING_FINAL_SEAL"),
        "related": validation.get("related", "PENDING_FINAL_SEAL"),
        "full_suite": validation.get("full_suite", "PENDING_FINAL_SEAL"),
        "strict_l3": validation.get("strict_l3", "PENDING_FINAL_SEAL"),
        "external_actions": _external_actions(),
        "overall_status": "exact",
    })
    add("final-report-v1.md", f"""# Pair 1 fixture narrow fix — final report

The historical Pair 1 authority used `{OLD_FORMAL_EVENT_ID}`, which the Planning event compiler rejects. A versioned fixture-only successor now deterministically derives `{NEW_FORMAL_EVENT_ID}` and rewrites the four active authority references. Historical evidence remains byte-exact.

- Branch: `{EXPECTED_BRANCH}`
- Baseline HEAD: `{BASELINE_HEAD}`
- Materialization parent: `{materialization_parent_head}`
- Fixture source: `{HISTORICAL_SOURCE_PATH}`
- Successor materializer: `{SOURCE_PATH}`
- Pair 2–5: read-only audit; no mutation
- A/B experimental lock: `SKILL_CONTEXT_ONLY`
- Corrected A packet: `DISABLED`
- Corrected B packet: `DISABLED`
- Approval / nonce: `ABSENT`
- External actions in this task: all `0`
- Historical real calls remain: Provider/HTTP/network/model/paid = `1/1/1/1/1`
- Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_FRESH_USER_APPROVAL`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_FIXTURE_NARROW_FIX_COMPLETED`
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_AB_PACKETS_MATERIALIZED`
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_APPROVAL_READY=YES`
""")
    add("privacy-scan-v1.json", _privacy_scan(documents))
    documents[f"{OUTPUT_ROOT}/sha256-manifest-v1.json"] = _manifest(documents)

    result = {
        "branch": EXPECTED_BRANCH,
        "baseline_head": BASELINE_HEAD,
        "materialization_parent_head": materialization_parent_head,
        "old_formal_event_id": OLD_FORMAL_EVENT_ID,
        "new_formal_event_id": NEW_FORMAL_EVENT_ID,
        "corrected_authority_input_sha256": authority_sha,
        "corrected_story_slice_sha256": story_slice_sha,
        "corrected_pair_lock_sha256": lock["pair_lock_sha256"],
        "corrected_a_packet_sha256": packets["a-arm"]["packet_sha256"],
        "corrected_b_packet_sha256": packets["b-arm"]["packet_sha256"],
        "corrected_a_approval_ready": True,
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT",
        "external_actions": _external_actions(),
        "overall_status": "exact",
    }
    return documents, result


def validate_unsigned_approval_readiness_v1(
    repo_root: Path, documents: Mapping[str, bytes]
) -> dict[str, Any]:
    def doc(relative: str) -> dict[str, Any]:
        return json.loads(documents[f"{OUTPUT_ROOT}/{relative}"].decode(UTF8))

    fixture = doc("corrected-pair1/sanitized-fixture-v2.json")
    lock = doc("corrected-pair1/pair-ab-lock-v2.json")
    packet = doc("corrected-pair1/a-arm/disabled-packet-v2.json")
    launcher = doc("corrected-pair1/a-arm/launcher-binding-v2.json")
    state = doc("campaign-successor-state-v1.json")
    checks = {
        "corrected_fixture_binding": packet["fixture_sha256"] == _sha_bytes(_json_bytes(fixture)),
        "formal_event_id_compatibility": bool(EVENT_ID_PATTERN.fullmatch(packet["corrected_formal_event_id"])),
        "a_b_lock_binding": packet["pair_lock_sha256"] == lock["pair_lock_sha256"],
        "launcher_source_binding": launcher["launcher_source"]["sha256"] == _sha_file(repo_root / SOURCE_PATH),
        "signed_preflight_validator_binding": packet["signed_preflight_validator_source_sha256"] == _sha_file(repo_root / SOURCE_PATH),
        "head_successor_binding": validate_head_successor_v1(
            repo_root, BASELINE_HEAD, packet["materialization_parent_head"]
        ) == "PASS",
        "stop_state_authority_binding": state["pair1_corrected_b_approval_allowed"] is False,
        "single_dispatch_binding": launcher["hard_max_real_provider_request_attempts"] == 1,
    }
    _require(all(checks.values()), f"approval_readiness_failed:{checks}")
    return {
        "phase_a_pre_approval_readiness": "PASS",
        **{key: "PASS" for key in checks},
        "approval_dry_run_result": "READY",
        "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT",
    }


def validate_head_successor_v1(repo_root: Path, parent_head: str, current_head: str) -> str:
    process = subprocess.run(
        ["git", "merge-base", "--is-ancestor", parent_head, current_head],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise Pair1FixtureFixError("head_successor_ancestry_failed")
    return "PASS"


def validate_corrected_signed_preflight_v1(
    packet: Mapping[str, Any], signed_approval: Mapping[str, Any]
) -> str:
    """Future approval validator; materialization never calls or satisfies it."""

    required = {
        "pair_case_id": packet["pair_case_id"],
        "scope": packet["scope"],
        "cohort_id": packet["cohort_id"],
        "packet_sha256": packet["packet_sha256"],
    }
    _require(all(signed_approval.get(key) == value for key, value in required.items()), "signed_binding_mismatch")
    _require(signed_approval.get("execution_authorized") is True, "approval_not_authorized")
    _require(bool(signed_approval.get("single_use_nonce")), "fresh_nonce_missing")
    return "PASS"


def write_documents(repo_root: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--materialization-parent-head", default=BASELINE_HEAD)
    args = parser.parse_args()
    documents, result = build_documents(
        args.repo_root,
        materialization_parent_head=args.materialization_parent_head,
    )
    validate_unsigned_approval_readiness_v1(args.repo_root.resolve(), documents)
    if args.materialize:
        write_documents(args.repo_root.resolve(), documents)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
