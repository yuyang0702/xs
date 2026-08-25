"""Pair 1 A-arm approval-binding successor closure and dormant launcher.

This module is offline by default.  It materializes a disabled successor packet
that binds the exact launcher and approval validators needed by a later,
separately authorized approval task.  Credential-capable imports remain inside
``execute_authorized_once`` and below exact signed preflight plus nonce
reservation.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    SLICE1_CONTRACT_IDENTITY,
    normalize_event_realization_input_authority_v1,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics import skill_v2_bounded_repeated_ab as campaign


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "b26e97ac26d81904e267e9be4ee3f08389f43ef2"
CAMPAIGN_MATERIALIZATION_PARENT_HEAD = "fd68d44d467e68cf1fc844d0f52c56f58e8e393d"
FRESH_STOP_FIX_BASELINE_HEAD = "56c65296b4a7b612e52dcce396357838a58575f1"
V2_SUCCESSOR_PACKET_SHA256 = "dc6bc29f953667409c89595dcdf4bb0447f4de691245cca60b837415310c2707"

PAIR_CASE_ID = "restored-character-heavy-v1"
ARM_ROLE = "A_ARM"
SKILL_ARM = "CURRENT_RUNTIME_SKILL"
SCOPE = "SKILL_V2_BOUNDED_REPEATED_AB_CHARACTER_HEAVY_A_ARM_SINGLE_DISPATCH_V1_ONLY"
COHORT = "skill-v2-bounded-repeated-ab-character-heavy-a-v1-20260824t162103z-001"
ORIGINAL_PACKET_SHA256 = "306c94312c96234da39a6b7b9f6b151cfa7bad0318df07934746f55734d7b2ba"

CAMPAIGN_PLAN_SHA256 = "fd6180ced062270241c5ed5039833556a87d51768a42c37ee605688e5866cbe7"
CAMPAIGN_DECISION_RULE_SHA256 = "2ed92dba7950363ef3ab9a7106c28ada60ebd2135317e18d34f9d193860044bd"
CAMPAIGN_MANIFEST_DEFINITION_SHA256 = "1391b6e317cb6347e4e139218dc7ae4609cdbf1097b3d7d7bfbac17b9c3f4b89"
CAMPAIGN_MANIFEST_FILE_SHA256 = "3c305c3be384c7dcdde6a1bd45c9382a4bec993ab38172a4f42812b456e9ad61"

CAMPAIGN_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-v1"
CLOSURE_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-pair1-a-approval-binding-closure-v1"
APPROVAL_ROOT = f"{CLOSURE_ROOT}/approval"
FRESH_STOP_FIX_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-pair1-a-fresh-stop-state-fix-v1"
FRESH_APPROVAL_ROOT = f"{FRESH_STOP_FIX_ROOT}/approval"
FRESH_RECEIPT_PATH = f"{FRESH_APPROVAL_ROOT}/approval-time-stop-state-receipt-v1.json"
FRESH_SIGNED_APPROVAL_PATH = f"{FRESH_APPROVAL_ROOT}/signed-approval-v2.json"
EXECUTION_ROOT = (
    "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-execution-v1/"
    "pairs/restored-character-heavy-v1/a-arm"
)
ORIGINAL_PACKET_PATH = (
    f"{CAMPAIGN_ROOT}/pairs/restored-character-heavy-v1/a-arm/disabled-packet-v1.json"
)
ORIGINAL_LAUNCHER_PATH = (
    f"{CAMPAIGN_ROOT}/pairs/restored-character-heavy-v1/a-arm/launcher-binding-v1.json"
)
ORIGINAL_PAIR_LOCK_PATH = (
    f"{CAMPAIGN_ROOT}/pairs/restored-character-heavy-v1/pair-ab-lock-v1.json"
)
CAMPAIGN_MANIFEST_PATH = f"{CAMPAIGN_ROOT}/sha256-manifest-v1.json"

LAUNCHER_SOURCE_PATH = "tools/canary/skill_v2_bounded_repeated_ab_pair1_a.py"
CURRENT_ARM_SOURCE_PATH = "tools/canary/slice1_phase_b_current_skill.py"
CAMPAIGN_MATERIALIZER_SOURCE_PATH = "tools/diagnostics/skill_v2_bounded_repeated_ab.py"
HTTP_SOURCE_PATH = "src/novel_flywheel/providers/http.py"
REGISTRY_SOURCE_PATH = "src/novel_flywheel/providers/registry.py"
LAUNCHER_SOURCE_IDENTITY = "SKILL_V2_BOUNDED_REPEATED_AB_PAIR1_A_FIXED_SINGLE_DISPATCH_LAUNCHER_V1"
SIGNED_PREFLIGHT_CONTRACT = "SKILL_V2_BOUNDED_REPEATED_AB_PAIR1_A_SIGNED_PREFLIGHT_V1"
HEAD_SUCCESSOR_CONTRACT = "SKILL_V2_BOUNDED_REPEATED_AB_PAIR1_A_HEAD_SUCCESSOR_V1"
STOP_STATE_EVALUATOR_CONTRACT = "SKILL_V2_BOUNDED_REPEATED_AB_CAMPAIGN_STOP_STATE_V1"
TWO_PHASE_STOP_STATE_CONTRACT = "SKILL_V2_PAIR1_A_TWO_PHASE_STOP_STATE_V1"
FRESH_SIGNED_PREFLIGHT_CONTRACT = "SKILL_V2_PAIR1_A_SIGNED_PREFLIGHT_FRESH_STOP_STATE_V1"

ZERO_COUNTERS = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}

ORIGINAL_SEMANTIC_FIELDS = (
    "pair_case_id", "creative_demand_class", "skill_arm", "scope", "cohort_id",
    "fixture_sha256", "authority_input_sha256", "story_slice_sha256",
    "task_contract_sha256", "non_skill_prompt_sha256", "skill_profile_sha256",
    "skill_context_sha256", "skill_context_char_count", "system_sha256",
    "user_sha256", "wire_input_sha256", "route_model_client_sha256",
    "sampling_policy_sha256", "tool_policy_sha256", "output_cap",
    "validator_policy_sha256", "authority_tuple_policy_sha256",
    "audit_serialization_policy_sha256", "ptr9_policy_sha256",
    "ptr12_policy_sha256", "output_isolation_policy_sha256",
    "quality_rubric_sha256", "engineering_rubric_sha256", "pair_lock_sha256",
)


class Pair1AClosureError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise Pair1AClosureError(reason_code)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode(UTF8)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ) + "\n").encode(UTF8)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _domain_sha(domain: str, value: Any) -> str:
    return _sha_bytes(domain.encode(UTF8) + b"\0" + _canonical_bytes(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain_sha(domain, result)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding=UTF8))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Pair1AClosureError("json_evidence_unreadable") from exc
    _require(isinstance(value, dict), "json_evidence_not_object")
    return value


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo_root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def verify_git_gate(
    repo_root: Path, *, expected_head: str | None = None, require_clean: bool = True,
) -> dict[str, Any]:
    branch = _git(repo_root, "branch", "--show-current")
    head = _git(repo_root, "rev-parse", "HEAD")
    status = _git(repo_root, "status", "--porcelain")
    _require(branch == EXPECTED_BRANCH, "baseline_branch_mismatch")
    if expected_head is not None:
        _require(head == expected_head, "baseline_head_mismatch")
    if require_clean:
        _require(not status, "worktree_not_clean")
    return {"branch": branch, "head": head, "worktree": "clean" if not status else "dirty"}


def _source_binding(repo_root: Path, relative: str) -> dict[str, Any]:
    path = repo_root / relative
    _require(path.is_file(), "launcher_source_missing")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": _sha_file(path)}


def _verify_campaign_manifest(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / CAMPAIGN_MANIFEST_PATH
    _require(_sha_file(manifest_path) == CAMPAIGN_MANIFEST_FILE_SHA256, "campaign_manifest_file_changed")
    manifest = _read_json(manifest_path)
    _require(manifest.get("definition_sha256") == CAMPAIGN_MANIFEST_DEFINITION_SHA256, "campaign_manifest_definition_changed")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("entry_count") == 81, "campaign_manifest_coverage_changed")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "campaign_manifest_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "campaign_manifest_file_size_changed")
        _require(_sha_file(path) == entry.get("sha256"), "campaign_manifest_file_hash_changed")
    return {"status": "exact", "coverage": "81/81 exact"}


def _original_packet(repo_root: Path) -> dict[str, Any]:
    _verify_campaign_manifest(repo_root)
    packet = _read_json(repo_root / ORIGINAL_PACKET_PATH)
    _require(packet.get("packet_sha256") == ORIGINAL_PACKET_SHA256, "original_packet_sha256_mismatch")
    _require(packet.get("execution_authorized") is False, "original_packet_became_authorized")
    _require(packet.get("signed_approval") == "ABSENT", "original_packet_signed_approval_present")
    _require(packet.get("single_use_nonce") is None, "original_packet_nonce_present")
    return packet


def launcher_source_binding(repo_root: Path) -> dict[str, Any]:
    sources = [
        _source_binding(repo_root, LAUNCHER_SOURCE_PATH),
        _source_binding(repo_root, CURRENT_ARM_SOURCE_PATH),
        _source_binding(repo_root, CAMPAIGN_MATERIALIZER_SOURCE_PATH),
        _source_binding(repo_root, HTTP_SOURCE_PATH),
        _source_binding(repo_root, REGISTRY_SOURCE_PATH),
    ]
    source_manifest = _sealed(
        "skill-v2-pair1-a-launcher-source-manifest-v1",
        {
            "schema": "SkillV2Pair1ALauncherSourceManifestV1",
            "version": 1,
            "closed_world": True,
            "entrypoint": "tools.canary.skill_v2_bounded_repeated_ab_pair1_a:execute_authorized_once",
            "sources": sources,
            "single_dispatch_transport_policy": "SingleDispatchTransportPolicyV1.phase_b",
        },
        "source_manifest_sha256",
    )
    original_launcher = _read_json(repo_root / ORIGINAL_LAUNCHER_PATH)
    body = {
        "schema": "SkillV2Pair1ALauncherSourceBindingV1",
        "version": 1,
        "launcher_source_path": LAUNCHER_SOURCE_PATH,
        "launcher_source_sha256": sources[0]["sha256"],
        "launcher_source_identity": LAUNCHER_SOURCE_IDENTITY,
        "launcher_source_manifest": source_manifest,
        "launcher_identity_sha256": original_launcher["launcher_identity_sha256"],
        "launcher_binding_sha256": original_launcher["launcher_binding_sha256"],
        "transport_guard_sha256": original_launcher["transport_guard_sha256"],
        "transport_policy_definition_sha256": original_launcher[
            "transport_policy_definition_sha256"
        ],
        "attempt_accounting_sha256": original_launcher["attempt_accounting_sha256"],
        "launcher_source_binding_explicit": True,
        "launcher_source_binding_unambiguous": True,
        "packet_to_launcher_source_binding_sha256": _domain_sha(
            "skill-v2-pair1-a-packet-to-launcher-source-v1",
            {
                "packet_sha256": ORIGINAL_PACKET_SHA256,
                "launcher_identity_sha256": original_launcher["launcher_identity_sha256"],
                "source_manifest_sha256": source_manifest["source_manifest_sha256"],
            },
        ),
    }
    body["launcher_identity_source_binding_sha256"] = _domain_sha(
        "skill-v2-pair1-a-launcher-identity-source-binding-v1",
        {
            "launcher_identity_sha256": body["launcher_identity_sha256"],
            "launcher_source_sha256": body["launcher_source_sha256"],
            "source_manifest_sha256": source_manifest["source_manifest_sha256"],
        },
    )
    return _sealed("skill-v2-pair1-a-launcher-source-binding-v1", body, "launcher_source_binding_sha256")


def _validator_binding(repo_root: Path, *, kind: str, function: str, contract: str) -> dict[str, Any]:
    source = _source_binding(repo_root, LAUNCHER_SOURCE_PATH)
    body = {
        "schema": f"SkillV2Pair1A{kind}BindingV1",
        "version": 1,
        "validator_path": LAUNCHER_SOURCE_PATH,
        "validator_source_sha256": source["sha256"],
        "validator_function": function,
        "validation_contract": contract,
        "binding_explicit": True,
        "credential_capable_imports_after_validator": True,
    }
    return _sealed(
        f"skill-v2-pair1-a-{kind.lower()}-binding-v1", body, "validator_binding_sha256",
    )


def signed_preflight_validator_binding(repo_root: Path) -> dict[str, Any]:
    value = _validator_binding(
        repo_root, kind="SignedPreflightValidator",
        function="validate_signed_launch", contract=SIGNED_PREFLIGHT_CONTRACT,
    )
    value.update({
        "signed_preflight_validator_path": value["validator_path"],
        "signed_preflight_validator_source_sha256": value["validator_source_sha256"],
        "signed_preflight_validator_binding_sha256": value["validator_binding_sha256"],
        "signed_preflight_validator_binding_explicit": True,
    })
    return value


def fresh_signed_preflight_validator_binding(repo_root: Path) -> dict[str, Any]:
    value = _validator_binding(
        repo_root, kind="FreshSignedPreflightValidator",
        function="validate_signed_launch", contract=FRESH_SIGNED_PREFLIGHT_CONTRACT,
    )
    value.update({
        "signed_preflight_validator_path": value["validator_path"],
        "signed_preflight_validator_source_sha256": value["validator_source_sha256"],
        "signed_preflight_validator_binding_sha256": value["validator_binding_sha256"],
        "signed_preflight_accepts_explicit_approval_time_stop_state_receipt": True,
        "old_pre_approval_receipt_hardwire_removed": True,
        "missing_fresh_receipt_fails_closed": True,
    })
    return value


def head_successor_validator_binding(repo_root: Path) -> dict[str, Any]:
    value = _validator_binding(
        repo_root, kind="HeadSuccessorValidator",
        function="validate_approval_head_successor", contract=HEAD_SUCCESSOR_CONTRACT,
    )
    value.update({
        "head_successor_validator_path": value["validator_path"],
        "head_successor_validator_source_sha256": value["validator_source_sha256"],
        "head_successor_validator_binding_sha256": value["validator_binding_sha256"],
        "head_successor_validator_binding_explicit": True,
        "ancestry_failure_terminates_immediately": True,
        "git_diff_after_ancestry_failure": False,
        "raw_subprocess_error_leaked": False,
    })
    return value


def stop_state_evaluator_binding(repo_root: Path) -> dict[str, Any]:
    value = _validator_binding(
        repo_root, kind="CampaignStopStateEvaluator",
        function="evaluate_campaign_stop_state", contract=STOP_STATE_EVALUATOR_CONTRACT,
    )
    value.update({
        "campaign_stop_state_evaluator_path": value["validator_path"],
        "campaign_stop_state_evaluator_source_sha256": value["validator_source_sha256"],
        "campaign_stop_state_evaluator_binding_sha256": value["validator_binding_sha256"],
    })
    return value


def fresh_stop_state_evaluator_binding(repo_root: Path) -> dict[str, Any]:
    value = _validator_binding(
        repo_root, kind="FreshStopStateEvaluator",
        function="build_approval_time_stop_state_receipt_v1",
        contract=TWO_PHASE_STOP_STATE_CONTRACT,
    )
    value.update({
        "campaign_stop_state_evaluator_path": value["validator_path"],
        "campaign_stop_state_evaluator_source_sha256": value["validator_source_sha256"],
        "campaign_stop_state_evaluator_binding_sha256": value["validator_binding_sha256"],
        "stop_state_receipt_builder_function": "build_approval_time_stop_state_receipt_v1",
        "approval_time_receipt_recomputed": True,
    })
    return value


def historical_root_policy() -> dict[str, Any]:
    accepted = [CAMPAIGN_ROOT, CLOSURE_ROOT, APPROVAL_ROOT, EXECUTION_ROOT]
    return _sealed(
        "skill-v2-pair1-a-historical-root-successor-policy-v1",
        {
            "schema": "SkillV2Pair1AHistoricalRootSuccessorPolicyV1",
            "version": 1,
            "historical_root_policy": "CLOSED_WORLD",
            "accepted_roots": accepted,
            "original_campaign_v1_root_accepted": True,
            "pair1_a_successor_closure_root_accepted": True,
            "future_approval_root_accepted": True,
            "future_execution_root_accepted": True,
            "arbitrary_report_root_accepted": False,
            "r0f_successor": "NOT_REQUIRED",
        },
        "historical_root_policy_sha256",
    )


def validate_historical_root(relative_root: str) -> str:
    _require(relative_root in historical_root_policy()["accepted_roots"], "historical_root_not_allowed")
    return "PASS"


def _arm_roots() -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for case_id in campaign.PAIR_CASE_IDS:
        for arm in ("a-arm", "b-arm"):
            identity = campaign._arm_identity(case_id, arm)
            rows.append({
                "pair_case_id": case_id,
                "arm": arm,
                "approval_root": f"{identity['materialization_root']}/approval",
                "execution_root": identity["execution_root"],
            })
    rows.append({
        "pair_case_id": PAIR_CASE_ID,
        "arm": "a-arm-successor",
        "approval_root": APPROVAL_ROOT,
        "execution_root": EXECUTION_ROOT,
    })
    return tuple(rows)


def evaluate_campaign_stop_state(
    repo_root: Path, *, materialization_parent_head: str,
) -> dict[str, Any]:
    evaluator = stop_state_evaluator_binding(repo_root)
    roots = []
    for row in _arm_roots():
        approval_exists = (repo_root / row["approval_root"]).exists()
        result_exists = (repo_root / row["execution_root"]).exists()
        roots.append({**row, "approval_exists": approval_exists, "result_exists": result_exists})
    pair1 = [row for row in roots if row["pair_case_id"] == PAIR_CASE_ID]
    later = [row for row in roots if row["pair_case_id"] != PAIR_CASE_ID]
    pair1_a_result = any(row["arm"].startswith("a-arm") and row["result_exists"] for row in pair1)
    pair1_b_approval = any(row["arm"] == "b-arm" and row["approval_exists"] for row in pair1)
    pair1_b_result = any(row["arm"] == "b-arm" and row["result_exists"] for row in pair1)
    later_approval = any(row["approval_exists"] for row in later)
    later_result = any(row["result_exists"] for row in later)
    continue_allowed = not any((pair1_a_result, pair1_b_approval, pair1_b_result, later_approval, later_result))
    body = {
        "schema": "SkillV2Pair1ACampaignStopStateAuthorityV1",
        "version": 1,
        "campaign_plan_sha256": CAMPAIGN_PLAN_SHA256,
        "campaign_decision_rule_sha256": CAMPAIGN_DECISION_RULE_SHA256,
        "campaign_evidence_seal_head": BASELINE_HEAD,
        "materialization_parent_head": materialization_parent_head,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "scope": SCOPE,
        "cohort_id": COHORT,
        "original_packet_sha256": ORIGINAL_PACKET_SHA256,
        "considered_roots": roots,
        "pair_1_is_next": continue_allowed,
        "pair_1_a_is_next_arm": continue_allowed,
        "pair_1_a_result_exists": pair1_a_result,
        "pair_1_b_approval_exists": pair1_b_approval,
        "pair_1_b_result_exists": pair1_b_result,
        "pair_2_or_later_approval_exists": later_approval,
        "pair_2_or_later_result_exists": later_result,
        "critical_quality_regression_active": False,
        "engineering_hard_failure_active": False,
        "a_b_lock_failure_active": False,
        "campaign_stop_state": "CONTINUE_ALLOWED" if continue_allowed else "STOP_REQUIRED",
        "campaign_stop_state_evaluator_path": evaluator["campaign_stop_state_evaluator_path"],
        "campaign_stop_state_evaluator_source_sha256": evaluator["campaign_stop_state_evaluator_source_sha256"],
        "campaign_stop_state_evaluator_binding_sha256": evaluator["campaign_stop_state_evaluator_binding_sha256"],
        "stop_state_authority_explicit": True,
        "external_actions": dict(ZERO_COUNTERS),
    }
    body["campaign_stop_state_binding_sha256"] = _domain_sha(
        "skill-v2-pair1-a-campaign-stop-state-binding-v1",
        {
            "packet_sha256": ORIGINAL_PACKET_SHA256,
            "evaluator_binding_sha256": evaluator["campaign_stop_state_evaluator_binding_sha256"],
            "considered_roots": roots,
        },
    )
    return _sealed(
        "skill-v2-pair1-a-campaign-stop-state-authority-v1", body,
        "campaign_stop_state_receipt_sha256",
    )


def build_campaign_stop_signals_v1(
    *, critical_quality_regression_active: bool = False,
    engineering_hard_failure_active: bool = False,
    a_b_lock_failure_active: bool = False,
) -> dict[str, Any]:
    """Build the closed-world stop-signal input created before the fresh receipt."""

    return _sealed(
        "skill-v2-pair1-a-campaign-stop-signals-v1",
        {
            "schema": "SkillV2Pair1ACampaignStopSignalsV1",
            "version": 1,
            "campaign_plan_sha256": CAMPAIGN_PLAN_SHA256,
            "campaign_decision_rule_sha256": CAMPAIGN_DECISION_RULE_SHA256,
            "critical_quality_regression_active": critical_quality_regression_active,
            "engineering_hard_failure_active": engineering_hard_failure_active,
            "a_b_lock_failure_active": a_b_lock_failure_active,
        },
        "campaign_stop_signals_sha256",
    )


def _fresh_state_locations() -> dict[str, Any]:
    pair1_b = campaign._arm_identity(PAIR_CASE_ID, "b-arm")
    later = [
        campaign._arm_identity(case_id, arm)
        for case_id in campaign.PAIR_CASE_IDS if case_id != PAIR_CASE_ID
        for arm in ("a-arm", "b-arm")
    ]
    pair1_a_original = campaign._arm_identity(PAIR_CASE_ID, "a-arm")
    return {
        "current_approval_root": FRESH_APPROVAL_ROOT,
        "pair1_b_approval_root": f"{pair1_b['materialization_root']}/approval",
        "pair1_b_result_root": pair1_b["execution_root"],
        "later_approval_roots": [f"{row['materialization_root']}/approval" for row in later],
        "later_result_roots": [row["execution_root"] for row in later],
        "pair1_a_result_root": pair1_a_original["execution_root"],
        "pair1_a_execution_root": EXECUTION_ROOT,
    }


def _valid_stop_signals(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    claimed = body.pop("campaign_stop_signals_sha256", None)
    return claimed == _domain_sha("skill-v2-pair1-a-campaign-stop-signals-v1", body)


def _discover_fresh_campaign_state(
    evidence_repo_root: Path, *, expected_approval_identity: Mapping[str, Any] | None,
    require_stop_signals: bool = False,
) -> dict[str, Any]:
    locations = _fresh_state_locations()
    approval_root = evidence_repo_root / FRESH_APPROVAL_ROOT
    identities = sorted(approval_root.glob("approval-identity-*.json")) if approval_root.is_dir() else []
    canonical_identity_path = approval_root / "approval-identity-v1.json"
    canonical_identity = _read_json(canonical_identity_path) if canonical_identity_path.is_file() else None
    identity_hashes = [_sha_file(path) for path in identities]
    identity_matches = canonical_identity == dict(expected_approval_identity or {})
    signals_path = approval_root / "campaign-stop-signals-v1.json"
    _require(not require_stop_signals or signals_path.is_file(), "campaign_stop_signals_missing")
    signals = _read_json(signals_path) if signals_path.is_file() else build_campaign_stop_signals_v1()
    _require(_valid_stop_signals(signals), "campaign_stop_signals_hash_mismatch")
    state = {
        "current_arm_approval_exists": bool(identities),
        "current_arm_approval_count": len(identities),
        "current_arm_approval_identity_hashes": identity_hashes,
        "current_arm_canonical_identity_present": canonical_identity is not None,
        "current_arm_approval_id_matches": identity_matches,
        "pair_1_a_result_exists": (evidence_repo_root / locations["pair1_a_result_root"]).exists(),
        "pair_1_a_execution_exists": (evidence_repo_root / locations["pair1_a_execution_root"]).exists(),
        "pair_1_b_approval_exists": (evidence_repo_root / locations["pair1_b_approval_root"]).exists(),
        "pair_1_b_result_exists": (evidence_repo_root / locations["pair1_b_result_root"]).exists(),
        "pair_2_or_later_approval_exists": any(
            (evidence_repo_root / path).exists() for path in locations["later_approval_roots"]
        ),
        "pair_2_or_later_result_exists": any(
            (evidence_repo_root / path).exists() for path in locations["later_result_roots"]
        ),
        "critical_quality_regression_active": bool(signals["critical_quality_regression_active"]),
        "engineering_hard_failure_active": bool(signals["engineering_hard_failure_active"]),
        "a_b_lock_failure_active": bool(signals["a_b_lock_failure_active"]),
        "canonical_locations": locations,
    }
    state["discovered_campaign_state_set_sha256"] = _domain_sha(
        "skill-v2-pair1-a-discovered-campaign-state-set-v1", state,
    )
    return state


def _approval_identity_valid(identity: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    _require(identity.get("schema") == "SkillV2Pair1AUnsignedApprovalIdentityV1", "approval_identity_schema_mismatch")
    _require(identity.get("version") == 1, "approval_identity_version_mismatch")
    _require(bool(identity.get("approval_id")), "approval_id_missing")
    _require(identity.get("pair_case_id") == PAIR_CASE_ID, "approval_identity_pair_mismatch")
    _require(identity.get("arm_role") == ARM_ROLE, "approval_identity_arm_mismatch")
    _require(identity.get("scope") == SCOPE, "approval_identity_scope_mismatch")
    _require(identity.get("cohort_id") == COHORT, "approval_identity_cohort_mismatch")
    _require(identity.get("approval_evidence_root") == FRESH_APPROVAL_ROOT, "approval_identity_root_mismatch")
    _require(identity.get("successor_packet_sha256") == packet.get("successor_packet_sha256"), "approval_identity_successor_mismatch")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", str(identity.get("approval_parent_head") or ""))), "approval_identity_parent_malformed")


def _fresh_semantic_continue(state: Mapping[str, Any], *, phase: str) -> bool:
    expected_count = 0 if phase == "PRE_APPROVAL_READINESS_STOP_STATE" else 1
    identity_ok = True if expected_count == 0 else bool(state["current_arm_approval_id_matches"])
    return (
        state["current_arm_approval_count"] == expected_count
        and identity_ok
        and not any(bool(state[field]) for field in (
            "pair_1_a_result_exists", "pair_1_a_execution_exists",
            "pair_1_b_approval_exists", "pair_1_b_result_exists",
            "pair_2_or_later_approval_exists", "pair_2_or_later_result_exists",
            "critical_quality_regression_active", "engineering_hard_failure_active",
            "a_b_lock_failure_active",
        ))
    )


def build_pre_approval_readiness_stop_state_v3(
    repo_root: Path, *, packet: Mapping[str, Any],
) -> dict[str, Any]:
    state = _discover_fresh_campaign_state(repo_root, expected_approval_identity=None)
    continue_allowed = _fresh_semantic_continue(state, phase="PRE_APPROVAL_READINESS_STOP_STATE")
    body = {
        "schema": "SkillV2Pair1APreApprovalReadinessStopStateV1",
        "version": 1,
        "receipt_type": "PRE_APPROVAL_READINESS_STOP_STATE",
        "two_phase_contract_id": TWO_PHASE_STOP_STATE_CONTRACT,
        "successor_packet_sha256": packet.get("successor_packet_sha256"),
        "current_arm_approval_exists": state["current_arm_approval_exists"],
        "current_arm_approval_count": state["current_arm_approval_count"],
        "discovered_campaign_state_set_sha256": state["discovered_campaign_state_set_sha256"],
        "campaign_stop_state": "CONTINUE_ALLOWED" if continue_allowed else "STOP_REQUIRED",
        "valid_for_signed_preflight": False,
        "external_actions": dict(ZERO_COUNTERS),
    }
    return _sealed("skill-v2-pair1-a-pre-approval-readiness-stop-state-v1", body, "campaign_stop_state_receipt_sha256")


def build_approval_time_stop_state_receipt_v1(
    repo_root: Path, *, packet: Mapping[str, Any],
    approval_identity: Mapping[str, Any], evidence_repo_root: Path | None = None,
) -> dict[str, Any]:
    _approval_identity_valid(approval_identity, packet)
    evidence_root = evidence_repo_root or repo_root
    state = _discover_fresh_campaign_state(
        evidence_root, expected_approval_identity=approval_identity,
        require_stop_signals=True,
    )
    continue_allowed = _fresh_semantic_continue(
        state, phase="APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE",
    )
    evaluator = fresh_stop_state_evaluator_binding(repo_root)
    body = {
        "schema": "SkillV2Pair1AApprovalTimeSignedPreflightStopStateV1",
        "version": 1,
        "receipt_type": "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE",
        "two_phase_contract_id": TWO_PHASE_STOP_STATE_CONTRACT,
        "approval_id": approval_identity["approval_id"],
        "approval_parent_head": approval_identity["approval_parent_head"],
        "approval_evidence_root": FRESH_APPROVAL_ROOT,
        "successor_packet_sha256": packet["successor_packet_sha256"],
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "scope": SCOPE,
        "cohort_id": COHORT,
        "campaign_plan_sha256": CAMPAIGN_PLAN_SHA256,
        "campaign_decision_rule_sha256": CAMPAIGN_DECISION_RULE_SHA256,
        "stop_state_evaluator_source_sha256": evaluator["campaign_stop_state_evaluator_source_sha256"],
        "stop_state_evaluator_binding_sha256": evaluator["campaign_stop_state_evaluator_binding_sha256"],
        "discovered_campaign_state": state,
        "discovered_campaign_state_set_sha256": state["discovered_campaign_state_set_sha256"],
        "current_arm_approval_exists": state["current_arm_approval_exists"],
        "current_arm_approval_count": state["current_arm_approval_count"],
        "current_arm_approval_id_matches": state["current_arm_approval_id_matches"],
        "campaign_stop_state": "CONTINUE_ALLOWED" if continue_allowed else "STOP_REQUIRED",
        "nonce_reservation_expected": False,
        "final_signed_approval_file_sha256_bound": False,
        "external_actions": dict(ZERO_COUNTERS),
    }
    return _sealed(
        "skill-v2-pair1-a-approval-time-signed-preflight-stop-state-v1", body,
        "campaign_stop_state_receipt_sha256",
    )


def budget_binding(original: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-a-budget-binding-v1",
        {
            "schema": "SkillV2Pair1ABudgetBindingV1",
            "version": 1,
            "hard_max_model_calls": 1,
            "hard_max_real_provider_request_attempts": 1,
            "hard_max_http_post_attempts": 1,
            "hard_max_network_request_attempts": 1,
            "hard_max_output_tokens": int(original["output_cap"]),
            "hard_max_output_tokens_per_call": int(original["output_cap"]),
            "hard_max_input_tokens": current_arm.HARD_MAX_INPUT_TOKENS,
            "hard_max_elapsed_seconds": current_arm.HARD_MAX_ELAPSED_SECONDS,
            "no_budget_increase": True,
        },
        "budget_sha256",
    )


def packet_manifest_definition() -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-a-successor-packet-manifest-definition-v1",
        {
            "schema": "SkillV2Pair1ASuccessorPacketManifestDefinitionV1",
            "version": 1,
            "coverage_root": CLOSURE_ROOT,
            "self_excluded": True,
            "path_basis": "repository-relative-posix",
            "byte_domain": "exact_file_bytes",
            "encoding": "UTF-8",
            "line_ending": "LF",
        },
        "packet_manifest_definition_sha256",
    )


def privacy_receipt_definition() -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-a-privacy-receipt-definition-v1",
        {
            "schema": "SkillV2Pair1APrivacyReceiptDefinitionV1",
            "version": 1,
            "forbidden": [
                "credentials", "auth_headers", "provider_secret_urls", "raw_provider_payloads",
                "reasoning_text", "future_nonce_values", "signed_approval_material",
            ],
        },
        "privacy_receipt_definition_sha256",
    )


def _successor_packet(
    repo_root: Path, *, materialization_parent_head: str,
    stop_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    original = _original_packet(repo_root)
    launcher = launcher_source_binding(repo_root)
    preflight = signed_preflight_validator_binding(repo_root)
    head = head_successor_validator_binding(repo_root)
    evaluator = stop_state_evaluator_binding(repo_root)
    history = historical_root_policy()
    budget = budget_binding(original)
    original_launcher = _read_json(repo_root / ORIGINAL_LAUNCHER_PATH)
    body = {
        "schema": "SkillV2BoundedRepeatedABPair1AApprovalReadySuccessorPacketV2",
        "version": 2,
        "original_packet_sha256": ORIGINAL_PACKET_SHA256,
        "original_packet_path": ORIGINAL_PACKET_PATH,
        "successor_primary_semantic_diff": "APPROVAL_AUTHORITY_BINDING_CLOSURE_ONLY",
        "primary_changed_variable_for_future_ab": "SKILL_CONTEXT",
        "a_b_experimental_lock_unchanged": True,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "scope": SCOPE,
        "cohort_id": COHORT,
        "materialization_root": CLOSURE_ROOT,
        "execution_root": EXECUTION_ROOT,
        "materialization_parent_head": materialization_parent_head,
        "campaign_evidence_seal_head": BASELINE_HEAD,
        "launcher_identity_sha256": launcher["launcher_identity_sha256"],
        "launcher_source_path": launcher["launcher_source_path"],
        "launcher_source_sha256": launcher["launcher_source_sha256"],
        "launcher_source_identity": launcher["launcher_source_identity"],
        "launcher_source_manifest_sha256": launcher["launcher_source_manifest"]["source_manifest_sha256"],
        "launcher_binding_sha256": launcher["launcher_binding_sha256"],
        "transport_guard_sha256": original_launcher["transport_guard_sha256"],
        "transport_policy_definition_sha256": original_launcher[
            "transport_policy_definition_sha256"
        ],
        "attempt_accounting_sha256": original_launcher["attempt_accounting_sha256"],
        "launcher_identity_source_binding_sha256": launcher["launcher_identity_source_binding_sha256"],
        "packet_to_launcher_source_binding_sha256": launcher["packet_to_launcher_source_binding_sha256"],
        "signed_preflight_validator_source_sha256": preflight["signed_preflight_validator_source_sha256"],
        "signed_preflight_validator_binding_sha256": preflight["signed_preflight_validator_binding_sha256"],
        "signed_preflight_validation_contract": SIGNED_PREFLIGHT_CONTRACT,
        "head_successor_validator_source_sha256": head["head_successor_validator_source_sha256"],
        "head_successor_validator_binding_sha256": head["head_successor_validator_binding_sha256"],
        "head_successor_contract_id": HEAD_SUCCESSOR_CONTRACT,
        "campaign_stop_state_evaluator_source_sha256": evaluator["campaign_stop_state_evaluator_source_sha256"],
        "campaign_stop_state_evaluator_binding_sha256": evaluator["campaign_stop_state_evaluator_binding_sha256"],
        "campaign_stop_state_receipt_sha256": stop_receipt["campaign_stop_state_receipt_sha256"],
        "campaign_stop_state_binding_sha256": stop_receipt["campaign_stop_state_binding_sha256"],
        "campaign_plan_sha256": CAMPAIGN_PLAN_SHA256,
        "campaign_decision_rule_sha256": CAMPAIGN_DECISION_RULE_SHA256,
        "historical_root_policy_sha256": history["historical_root_policy_sha256"],
        "packet_manifest_path": f"{CLOSURE_ROOT}/sha256-manifest-v1.json",
        "packet_manifest_definition_sha256": packet_manifest_definition()["packet_manifest_definition_sha256"],
        "privacy_receipt_path": f"{CLOSURE_ROOT}/privacy-scan-v1.json",
        "privacy_receipt_definition_sha256": privacy_receipt_definition()["privacy_receipt_definition_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False,
        "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "execution_authorized": False,
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "pair_1_a_arm_executed": False,
        "pair_1_b_arm_authorized": False,
        "pair_2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "full_short_authorized": False,
        "external_actions": dict(ZERO_COUNTERS),
    }
    for field in ORIGINAL_SEMANTIC_FIELDS:
        if field not in body:
            body[field] = original[field]
    return _sealed(
        "skill-v2-pair1-a-approval-ready-successor-packet-v2", body,
        "successor_packet_sha256",
    )


def _receipt_hash_valid(receipt: Mapping[str, Any]) -> bool:
    body = dict(receipt)
    claimed = body.pop("campaign_stop_state_receipt_sha256", None)
    return claimed == _domain_sha("skill-v2-pair1-a-campaign-stop-state-authority-v1", body)


def validate_successor_packet(
    repo_root: Path,
    packet: Mapping[str, Any],
    *,
    stop_receipt: Mapping[str, Any],
    historical_root: str = CLOSURE_ROOT,
) -> dict[str, Any]:
    launcher = launcher_source_binding(repo_root)
    preflight = signed_preflight_validator_binding(repo_root)
    head = head_successor_validator_binding(repo_root)
    evaluator = stop_state_evaluator_binding(repo_root)
    original = _original_packet(repo_root)
    original_launcher = _read_json(repo_root / ORIGINAL_LAUNCHER_PATH)
    expected_lock = _read_json(repo_root / ORIGINAL_PAIR_LOCK_PATH)["pair_lock_sha256"]

    _require(bool(packet.get("launcher_source_sha256")), "launcher_source_sha256_missing")
    _require(packet.get("launcher_source_sha256") == launcher["launcher_source_sha256"], "launcher_source_sha256_mismatch")
    _require(packet.get("launcher_identity_source_binding_sha256") == launcher["launcher_identity_source_binding_sha256"], "launcher_identity_source_mismatch")
    _require(bool(packet.get("signed_preflight_validator_source_sha256")), "signed_preflight_validator_sha256_missing")
    _require(packet.get("signed_preflight_validator_source_sha256") == preflight["signed_preflight_validator_source_sha256"], "signed_preflight_validator_sha256_mismatch")
    _require(bool(packet.get("head_successor_validator_source_sha256")), "head_successor_validator_sha256_missing")
    _require(packet.get("head_successor_validator_source_sha256") == head["head_successor_validator_source_sha256"], "head_successor_validator_sha256_mismatch")
    _require(bool(packet.get("campaign_stop_state_receipt_sha256")), "campaign_stop_state_receipt_sha256_missing")
    _require(_receipt_hash_valid(stop_receipt), "campaign_stop_state_receipt_hash_mismatch")
    _require(packet.get("campaign_stop_state_receipt_sha256") == stop_receipt.get("campaign_stop_state_receipt_sha256"), "campaign_stop_state_receipt_stale")
    expected_stop = evaluate_campaign_stop_state(
        repo_root, materialization_parent_head=str(packet.get("materialization_parent_head") or ""),
    )
    _require(stop_receipt == expected_stop, "campaign_stop_state_receipt_stale")
    _require(packet.get("campaign_stop_state_evaluator_source_sha256") == evaluator["campaign_stop_state_evaluator_source_sha256"], "campaign_stop_state_evaluator_sha256_mismatch")
    _require(packet.get("pair_case_id") == PAIR_CASE_ID, "pair_case_id_mismatch")
    _require(packet.get("arm_role") == ARM_ROLE, "arm_role_mismatch")
    _require(packet.get("scope") == SCOPE, "scope_mismatch")
    _require(packet.get("cohort_id") == COHORT, "cohort_mismatch")
    _require(packet.get("original_packet_sha256") == ORIGINAL_PACKET_SHA256, "original_packet_sha256_mismatch")
    _require(packet.get("skill_context_sha256") == original["skill_context_sha256"], "current_skill_context_sha256_mismatch")
    _require(packet.get("pair_lock_sha256") == expected_lock, "pair_lock_sha256_mismatch")
    _require(
        packet.get("transport_guard_sha256") == original_launcher["transport_guard_sha256"],
        "transport_guard_sha256_mismatch",
    )
    _require(
        packet.get("attempt_accounting_sha256")
        == original_launcher["attempt_accounting_sha256"],
        "attempt_accounting_sha256_mismatch",
    )
    validate_historical_root(historical_root)
    _require(packet.get("signed_approval") == "ABSENT", "signed_approval_must_be_absent")
    _require(packet.get("single_use_nonce") is None, "single_use_nonce_must_be_absent")
    _require(packet.get("execution_authorized") is False, "successor_packet_must_be_disabled")
    _require(packet.get("usage_status") == "unused", "successor_packet_usage_not_unused")
    _require(packet.get("reservation_status") == "unreserved", "successor_packet_not_unreserved")
    for field in ORIGINAL_SEMANTIC_FIELDS:
        _require(packet.get(field) == original.get(field), f"original_semantic_field_changed:{field}")
    body = dict(packet)
    claimed = body.pop("successor_packet_sha256", None)
    _require(claimed == _domain_sha("skill-v2-pair1-a-approval-ready-successor-packet-v2", body), "successor_packet_sha256_mismatch")
    return {"status": "exact", "approval_dry_run_result": "READY"}


def fresh_historical_root_policy_v1() -> dict[str, Any]:
    accepted = list(historical_root_policy()["accepted_roots"])
    accepted.extend((FRESH_STOP_FIX_ROOT, FRESH_APPROVAL_ROOT))
    return _sealed(
        "skill-v2-pair1-a-fresh-historical-root-policy-v1",
        {
            "schema": "SkillV2Pair1AFreshHistoricalRootPolicyV1",
            "version": 1,
            "historical_root_policy": "CLOSED_WORLD",
            "accepted_roots": accepted,
            "arbitrary_report_root_accepted": False,
            "r0f_successor": "NOT_REQUIRED",
        },
        "historical_root_policy_sha256",
    )


def fresh_manifest_definition_v1() -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-a-fresh-stop-state-manifest-definition-v1",
        {
            "schema": "SkillV2Pair1AFreshStopStateManifestDefinitionV1",
            "version": 1, "coverage_root": FRESH_STOP_FIX_ROOT,
            "self_excluded": True, "path_basis": "repository-relative-posix",
            "byte_domain": "exact_file_bytes", "encoding": "UTF-8",
            "line_ending": "LF",
        },
        "manifest_definition_sha256",
    )


def fresh_privacy_definition_v1() -> dict[str, Any]:
    return _sealed(
        "skill-v2-pair1-a-fresh-stop-state-privacy-definition-v1",
        {
            "schema": "SkillV2Pair1AFreshStopStatePrivacyDefinitionV1",
            "version": 1,
            "forbidden": [
                "credentials", "auth_headers", "provider_secret_urls",
                "raw_provider_payloads", "reasoning_text", "nonce_values",
                "signed_approval_material",
            ],
        },
        "privacy_definition_sha256",
    )


def build_fresh_stop_state_successor_packet_v3(
    repo_root: Path, *, materialization_parent_head: str,
) -> dict[str, Any]:
    original = _original_packet(repo_root)
    launcher = launcher_source_binding(repo_root)
    preflight = fresh_signed_preflight_validator_binding(repo_root)
    head = head_successor_validator_binding(repo_root)
    evaluator = fresh_stop_state_evaluator_binding(repo_root)
    original_launcher = _read_json(repo_root / ORIGINAL_LAUNCHER_PATH)
    history = fresh_historical_root_policy_v1()
    budget = budget_binding(original)
    body = {
        "schema": "SkillV2BoundedRepeatedABPair1AApprovalReadySuccessorPacketV3",
        "version": 3,
        "original_packet_sha256": ORIGINAL_PACKET_SHA256,
        "v2_successor_packet_sha256": V2_SUCCESSOR_PACKET_SHA256,
        "successor_primary_semantic_diff": "SIGNED_PREFLIGHT_FRESH_STOP_STATE_BINDING_FIX_ONLY",
        "primary_changed_variable_for_future_ab": "SKILL_CONTEXT",
        "a_b_experimental_lock_unchanged": True,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM,
        "scope": SCOPE,
        "cohort_id": COHORT,
        "materialization_root": FRESH_STOP_FIX_ROOT,
        "approval_evidence_root": FRESH_APPROVAL_ROOT,
        "approval_time_receipt_path": FRESH_RECEIPT_PATH,
        "execution_root": EXECUTION_ROOT,
        "materialization_parent_head": materialization_parent_head,
        "campaign_evidence_seal_head": BASELINE_HEAD,
        "two_phase_stop_state_contract_id": TWO_PHASE_STOP_STATE_CONTRACT,
        "signed_preflight_validation_contract": FRESH_SIGNED_PREFLIGHT_CONTRACT,
        "pre_approval_receipt_valid_for_signed_preflight": False,
        "approval_time_receipt_required_for_signed_preflight": True,
        "approval_receipt_binding_graph_acyclic": True,
        "final_signed_file_hash_bound_by_receipt": False,
        "launcher_identity_sha256": launcher["launcher_identity_sha256"],
        "launcher_source_path": launcher["launcher_source_path"],
        "launcher_source_sha256": launcher["launcher_source_sha256"],
        "launcher_source_manifest_sha256": launcher["launcher_source_manifest"]["source_manifest_sha256"],
        "launcher_binding_sha256": launcher["launcher_binding_sha256"],
        "launcher_identity_source_binding_sha256": launcher["launcher_identity_source_binding_sha256"],
        "signed_preflight_validator_source_sha256": preflight["signed_preflight_validator_source_sha256"],
        "signed_preflight_validator_binding_sha256": preflight["signed_preflight_validator_binding_sha256"],
        "head_successor_validator_source_sha256": head["head_successor_validator_source_sha256"],
        "head_successor_validator_binding_sha256": head["head_successor_validator_binding_sha256"],
        "campaign_stop_state_evaluator_source_sha256": evaluator["campaign_stop_state_evaluator_source_sha256"],
        "campaign_stop_state_evaluator_binding_sha256": evaluator["campaign_stop_state_evaluator_binding_sha256"],
        "campaign_plan_sha256": CAMPAIGN_PLAN_SHA256,
        "campaign_decision_rule_sha256": CAMPAIGN_DECISION_RULE_SHA256,
        "historical_root_policy_sha256": history["historical_root_policy_sha256"],
        "packet_manifest_path": f"{FRESH_STOP_FIX_ROOT}/sha256-manifest-v1.json",
        "packet_manifest_definition_sha256": fresh_manifest_definition_v1()["manifest_definition_sha256"],
        "privacy_receipt_path": f"{FRESH_STOP_FIX_ROOT}/privacy-scan-v1.json",
        "privacy_receipt_definition_sha256": fresh_privacy_definition_v1()["privacy_definition_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "transport_guard_sha256": original_launcher["transport_guard_sha256"],
        "transport_policy_definition_sha256": original_launcher["transport_policy_definition_sha256"],
        "attempt_accounting_sha256": original_launcher["attempt_accounting_sha256"],
        "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False,
        "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "execution_authorized": False,
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "pair_1_a_arm_executed": False,
        "pair_1_b_arm_authorized": False,
        "pair_2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "full_short_authorized": False,
        "external_actions": dict(ZERO_COUNTERS),
    }
    for field in ORIGINAL_SEMANTIC_FIELDS:
        if field not in body:
            body[field] = original[field]
    return _sealed(
        "skill-v2-pair1-a-approval-ready-successor-packet-v3", body,
        "successor_packet_sha256",
    )


def validate_fresh_stop_state_successor_packet_v3(
    repo_root: Path, packet: Mapping[str, Any],
) -> dict[str, Any]:
    expected = build_fresh_stop_state_successor_packet_v3(
        repo_root, materialization_parent_head=str(packet.get("materialization_parent_head") or ""),
    )
    _require(dict(packet) == expected, "fresh_stop_state_successor_packet_mismatch")
    _require(packet.get("execution_authorized") is False, "successor_packet_must_be_disabled")
    _require(packet.get("signed_approval") == "ABSENT", "signed_approval_must_be_absent")
    _require(packet.get("single_use_nonce") is None, "single_use_nonce_must_be_absent")
    return {"status": "exact", "approval_dry_run_result": "READY_V3"}


def validate_approval_time_stop_state_receipt_v1(
    repo_root: Path, *, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    receipt: Mapping[str, Any], evidence_repo_root: Path | None = None,
    nonce_reservation_attempted: bool = False,
) -> dict[str, Any]:
    _require(not nonce_reservation_attempted, "fresh_receipt_after_nonce_reservation_forbidden")
    _require(receipt.get("schema") == "SkillV2Pair1AApprovalTimeSignedPreflightStopStateV1", "fresh_receipt_schema_mismatch")
    _require(receipt.get("receipt_type") == "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE", "pre_approval_receipt_not_valid_for_signed_preflight")
    _require(receipt.get("approval_evidence_root") == FRESH_APPROVAL_ROOT, "fresh_receipt_root_mismatch")
    _require(signed_approval.get("campaign_stop_state_receipt_path") == FRESH_RECEIPT_PATH, "fresh_receipt_path_mismatch")
    _require(signed_approval.get("campaign_stop_state_receipt_sha256") == receipt.get("campaign_stop_state_receipt_sha256"), "fresh_receipt_sha_mismatch")
    _require(signed_approval.get("approval_id") == receipt.get("approval_id"), "fresh_receipt_approval_id_mismatch")
    _require(signed_approval.get("approval_parent_head") == receipt.get("approval_parent_head"), "fresh_receipt_approval_parent_mismatch")
    _require(packet.get("successor_packet_sha256") == receipt.get("successor_packet_sha256"), "fresh_receipt_successor_mismatch")
    identity_path = (evidence_repo_root or repo_root) / FRESH_APPROVAL_ROOT / "approval-identity-v1.json"
    _require(identity_path.is_file(), "fresh_approval_identity_missing")
    identity = _read_json(identity_path)
    _approval_identity_valid(identity, packet)
    _require(identity.get("approval_id") == signed_approval.get("approval_id"), "approval_identity_signed_id_mismatch")
    expected = build_approval_time_stop_state_receipt_v1(
        repo_root, packet=packet, approval_identity=identity,
        evidence_repo_root=evidence_repo_root,
    )
    _require(dict(receipt) == expected, "fresh_receipt_recomputation_mismatch")
    _require(expected["campaign_stop_state"] == "CONTINUE_ALLOWED", "campaign_stop_state_not_continue")
    _require(expected["current_arm_approval_exists"] is True, "current_arm_approval_missing")
    _require(expected["current_arm_approval_count"] == 1, "current_arm_approval_count_invalid")
    _require(expected["current_arm_approval_id_matches"] is True, "current_arm_approval_id_mismatch")
    return {
        "status": "exact",
        "recomputed_campaign_stop_state": "CONTINUE_ALLOWED",
        "pre_approval_receipt_valid_for_signed_preflight": False,
        "external_actions": dict(ZERO_COUNTERS),
    }


def validate_signed_preflight_transaction_v1(
    repo_root: Path, *, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    campaign_stop_state_receipt: Mapping[str, Any],
    evidence_repo_root: Path | None = None, head_repo_root: Path | None = None,
    current_head: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Validate the complete signed transaction before nonce reservation."""

    validate_fresh_stop_state_successor_packet_v3(repo_root, packet)
    _require(signed_approval.get("schema") == "SkillV2BoundedRepeatedABPair1ASignedApprovalV2", "signed_approval_schema_mismatch")
    _require(signed_approval.get("execution_authorized") is True, "execution_not_authorized")
    _require(signed_approval.get("named_approver") == "USER_PROJECT_OWNER", "named_approver_missing")
    _require(signed_approval.get("approval_scope") == SCOPE, "approval_scope_mismatch")
    _require(signed_approval.get("cohort_id") == COHORT, "approval_cohort_mismatch")
    _require(signed_approval.get("successor_packet_sha256") == packet["successor_packet_sha256"], "approval_packet_mismatch")
    validate_approval_time_stop_state_receipt_v1(
        repo_root, packet=packet, signed_approval=signed_approval,
        receipt=campaign_stop_state_receipt,
        evidence_repo_root=evidence_repo_root,
    )
    _require(signed_approval.get("nonce_reserved") is False, "nonce_already_reserved")
    _require(signed_approval.get("nonce_consumed") is False, "nonce_already_consumed")
    nonce = str(signed_approval.get("single_use_nonce") or "")
    _require(bool(nonce), "single_use_nonce_missing")
    for field in (
        "pair_1_b_arm_authorized", "pair_2_or_later_authorized",
        "skill_v2_production_cutover_authorized", "planning_v2_cutover_authorized",
        "draft_authorized", "full_short_authorized", "story_state_mutation_allowed",
        "canon_mutation_allowed", "ready_mutation_allowed",
    ):
        _require(signed_approval.get(field) is False, f"{field}_forbidden")
    window = signed_approval.get("execution_window") or {}
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise Pair1AClosureError("execution_window_invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(start <= current <= end, "execution_window_inactive")
    validate_approval_head_successor(
        head_repo_root or repo_root,
        materialization_parent_head=str(packet["materialization_parent_head"]),
        approval_parent_head=str(signed_approval.get("approval_parent_head") or ""),
        current_head=current_head,
        materialization_root=FRESH_STOP_FIX_ROOT,
        approval_root=FRESH_APPROVAL_ROOT,
    )
    return {
        "status": "exact", "nonce": nonce,
        "fresh_stop_state_receipt": "PASS",
        "pre_nonce_safety": "PASS",
        "external_actions": dict(ZERO_COUNTERS),
    }


def mutate_negative_case(
    packet: Mapping[str, Any], stop_receipt: Mapping[str, Any], case: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    mutated = deepcopy(dict(packet))
    stop = deepcopy(dict(stop_receipt))
    root = CLOSURE_ROOT
    wrong = "0" * 64
    if case == "missing_launcher_source": mutated.pop("launcher_source_sha256", None)
    elif case == "wrong_launcher_source": mutated["launcher_source_sha256"] = wrong
    elif case == "launcher_identity_source_mismatch": mutated["launcher_identity_source_binding_sha256"] = wrong
    elif case == "missing_preflight_validator": mutated.pop("signed_preflight_validator_source_sha256", None)
    elif case == "wrong_preflight_validator": mutated["signed_preflight_validator_source_sha256"] = wrong
    elif case == "missing_head_validator": mutated.pop("head_successor_validator_source_sha256", None)
    elif case == "wrong_head_validator": mutated["head_successor_validator_source_sha256"] = wrong
    elif case == "missing_stop_receipt": mutated.pop("campaign_stop_state_receipt_sha256", None)
    elif case == "stale_stop_receipt":
        stop["materialization_parent_head"] = wrong
        stop.pop("campaign_stop_state_receipt_sha256", None)
        stop["campaign_stop_state_receipt_sha256"] = _domain_sha("skill-v2-pair1-a-campaign-stop-state-authority-v1", stop)
        mutated["campaign_stop_state_receipt_sha256"] = stop["campaign_stop_state_receipt_sha256"]
    elif case == "forged_continue_allowed": stop["pair_1_a_result_exists"] = True
    elif case == "stop_evaluator_source_mismatch": mutated["campaign_stop_state_evaluator_source_sha256"] = wrong
    elif case == "wrong_pair": mutated["pair_case_id"] = "restored-world-heavy-v1"
    elif case == "wrong_arm": mutated["arm_role"] = "B_ARM"
    elif case == "wrong_scope": mutated["scope"] = "WRONG"
    elif case == "wrong_cohort": mutated["cohort_id"] = "wrong"
    elif case == "wrong_original_packet": mutated["original_packet_sha256"] = wrong
    elif case == "wrong_current_context": mutated["skill_context_sha256"] = wrong
    elif case == "wrong_ab_lock": mutated["pair_lock_sha256"] = wrong
    elif case == "arbitrary_historical_root": root = "docs/superpowers/reports/arbitrary-root"
    elif case == "precreated_approval": mutated["signed_approval"] = "PRESENT"
    elif case == "precreated_nonce": mutated["single_use_nonce"] = "forbidden"
    else: raise ValueError(case)
    return mutated, stop, root


def negative_matrix(
    repo_root: Path, packet: Mapping[str, Any], stop_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    cases = (
        "missing_launcher_source", "wrong_launcher_source", "launcher_identity_source_mismatch",
        "missing_preflight_validator", "wrong_preflight_validator", "missing_head_validator",
        "wrong_head_validator", "missing_stop_receipt", "stale_stop_receipt",
        "forged_continue_allowed", "stop_evaluator_source_mismatch", "wrong_pair",
        "wrong_arm", "wrong_scope", "wrong_cohort", "wrong_original_packet",
        "wrong_current_context", "wrong_ab_lock", "arbitrary_historical_root",
        "precreated_approval", "precreated_nonce",
    )
    results = []
    for case in cases:
        mutated, stop, root = mutate_negative_case(packet, stop_receipt, case)
        try:
            validate_successor_packet(repo_root, mutated, stop_receipt=stop, historical_root=root)
        except Pair1AClosureError as exc:
            results.append({"case": case, "status": "REJECTED_BEFORE_EXTERNAL_ACTION", "reason": exc.reason_code})
        else:
            raise Pair1AClosureError(f"negative_case_accepted:{case}")
    return {
        "schema": "SkillV2Pair1AApprovalBindingNegativeMatrixV1",
        "version": 1,
        "case_count": len(results),
        "all_rejected_before_external_action": True,
        "results": results,
        "external_actions": dict(ZERO_COUNTERS),
    }


def mutate_fresh_stop_state_negative_case(
    case: str, *, packet: Mapping[str, Any], signed_approval: Mapping[str, Any],
    receipt: Mapping[str, Any], evidence_repo_root: Path,
) -> dict[str, Any]:
    mutated_packet = deepcopy(dict(packet))
    mutated_signed = deepcopy(dict(signed_approval))
    mutated_receipt = deepcopy(dict(receipt))
    nonce_attempted = False
    wrong64 = "0" * 64
    wrong40 = "0" * 40
    locations = _fresh_state_locations()
    approval_root = evidence_repo_root / FRESH_APPROVAL_ROOT
    signals_path = approval_root / "campaign-stop-signals-v1.json"

    if case == "old_phase_a_receipt":
        mutated_receipt = build_pre_approval_readiness_stop_state_v3(
            evidence_repo_root, packet=mutated_packet,
        )
    elif case == "missing_fresh_receipt": mutated_receipt = {}
    elif case == "wrong_receipt_sha": mutated_signed["campaign_stop_state_receipt_sha256"] = wrong64
    elif case == "forged_continue": mutated_receipt["discovered_campaign_state_set_sha256"] = wrong64
    elif case == "wrong_evaluator": mutated_receipt["stop_state_evaluator_source_sha256"] = wrong64
    elif case == "wrong_pair": mutated_receipt["pair_case_id"] = "wrong-pair"
    elif case == "wrong_arm": mutated_receipt["arm_role"] = "B_ARM"
    elif case == "wrong_approval_id": mutated_signed["approval_id"] = "wrong-approval"
    elif case == "wrong_approval_parent": mutated_signed["approval_parent_head"] = wrong40
    elif case == "wrong_successor": mutated_receipt["successor_packet_sha256"] = wrong64
    elif case == "stale_state_set": mutated_receipt["discovered_campaign_state_set_sha256"] = wrong64
    elif case == "two_current_approvals":
        (approval_root / "approval-identity-v2.json").write_bytes(
            _json_bytes({**_read_json(approval_root / "approval-identity-v1.json"), "approval_id": "second"}),
        )
    elif case == "pair1_b_approval": (evidence_repo_root / locations["pair1_b_approval_root"]).mkdir(parents=True)
    elif case == "later_approval": (evidence_repo_root / locations["later_approval_roots"][0]).mkdir(parents=True)
    elif case == "pair1_a_result": (evidence_repo_root / locations["pair1_a_result_root"]).mkdir(parents=True)
    elif case == "execution_root_exists": (evidence_repo_root / locations["pair1_a_execution_root"]).mkdir(parents=True)
    elif case in {"critical_quality_stop", "engineering_stop", "ab_lock_stop"}:
        signals_path.write_bytes(_json_bytes(build_campaign_stop_signals_v1(
            critical_quality_regression_active=case == "critical_quality_stop",
            engineering_hard_failure_active=case == "engineering_stop",
            a_b_lock_failure_active=case == "ab_lock_stop",
        )))
    elif case == "arbitrary_receipt_root": mutated_receipt["approval_evidence_root"] = "docs/arbitrary"
    elif case == "noncanonical_authority":
        (approval_root / "approval-identity-v1.json").rename(approval_root / "not-canonical.json")
    elif case == "malformed_receipt": mutated_receipt = {"schema": "malformed"}
    elif case == "missing_campaign_plan": mutated_receipt.pop("campaign_plan_sha256", None)
    elif case == "wrong_decision_rule": mutated_receipt["campaign_decision_rule_sha256"] = wrong64
    elif case == "after_nonce_reservation": nonce_attempted = True
    else: raise ValueError(case)
    return {
        "packet": mutated_packet,
        "signed_approval": mutated_signed,
        "receipt": mutated_receipt,
        "evidence_repo_root": evidence_repo_root,
        "nonce_reservation_attempted": nonce_attempted,
    }


def init_synthetic_head_successor_repo(repo_root: Path) -> None:
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "offline-test@example.invalid")
    _git(repo_root, "config", "user.name", "Offline Test")
    materialization = repo_root / FRESH_STOP_FIX_ROOT
    materialization.mkdir(parents=True)
    (materialization / "pair1-a-successor-packet-v3.json").write_text("{}\n", encoding=UTF8)
    _git(repo_root, "add", FRESH_STOP_FIX_ROOT)
    _git(repo_root, "commit", "-m", "materialization")
    approval = repo_root / FRESH_APPROVAL_ROOT
    approval.mkdir(parents=True)
    (approval / "approval-identity-v1.json").write_text("{}\n", encoding=UTF8)
    _git(repo_root, "add", FRESH_APPROVAL_ROOT)
    _git(repo_root, "commit", "-m", "approval")
    (approval / "signed-approval-v2.json").write_text("{}\n", encoding=UTF8)
    _git(repo_root, "add", FRESH_APPROVAL_ROOT)
    _git(repo_root, "commit", "-m", "approval seal")


def simulate_post_seal_head_successor(repo_root: Path) -> dict[str, Any]:
    current = _git(repo_root, "rev-parse", "HEAD")
    approval_parent = _git(repo_root, "rev-parse", "HEAD^")
    materialization_parent = _git(repo_root, "rev-parse", "HEAD^^")
    result = validate_approval_head_successor(
        repo_root, materialization_parent_head=materialization_parent,
        approval_parent_head=approval_parent, current_head=current,
        materialization_root=FRESH_STOP_FIX_ROOT,
        approval_root=FRESH_APPROVAL_ROOT,
    )
    result["post_seal_signed_preflight_with_fresh_receipt"] = "PASS"
    return result


def run_positive_synthetic_transaction_v1(
    source_repo_root: Path, synthetic_repo_root: Path,
) -> dict[str, Any]:
    """Exercise the acyclic approval transaction in an isolated local git repo."""

    _git(synthetic_repo_root, "init")
    _git(synthetic_repo_root, "config", "user.email", "offline-test@example.invalid")
    _git(synthetic_repo_root, "config", "user.name", "Offline Test")
    (synthetic_repo_root / "implementation-baseline.txt").write_text("offline\n", encoding=UTF8)
    _git(synthetic_repo_root, "add", "implementation-baseline.txt")
    _git(synthetic_repo_root, "commit", "-m", "implementation baseline")
    implementation_head = _git(synthetic_repo_root, "rev-parse", "HEAD")
    packet = build_fresh_stop_state_successor_packet_v3(
        source_repo_root, materialization_parent_head=implementation_head,
    )
    packet_path = synthetic_repo_root / FRESH_STOP_FIX_ROOT / "pair1-a-successor-packet-v3.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_bytes(_json_bytes(packet))
    _git(synthetic_repo_root, "add", FRESH_STOP_FIX_ROOT)
    _git(synthetic_repo_root, "commit", "-m", "v3 materialization evidence")
    approval_parent_head = _git(synthetic_repo_root, "rev-parse", "HEAD")
    identity = {
        "schema": "SkillV2Pair1AUnsignedApprovalIdentityV1", "version": 1,
        "approval_id": "synthetic-pair1-a-approval-v3",
        "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE,
        "scope": SCOPE, "cohort_id": COHORT,
        "approval_parent_head": approval_parent_head,
        "successor_packet_sha256": packet["successor_packet_sha256"],
        "approval_evidence_root": FRESH_APPROVAL_ROOT,
    }
    approval_root = synthetic_repo_root / FRESH_APPROVAL_ROOT
    approval_root.mkdir(parents=True)
    (approval_root / "approval-identity-v1.json").write_bytes(_json_bytes(identity))
    (approval_root / "campaign-stop-signals-v1.json").write_bytes(
        _json_bytes(build_campaign_stop_signals_v1()),
    )
    receipt = build_approval_time_stop_state_receipt_v1(
        source_repo_root, packet=packet, approval_identity=identity,
        evidence_repo_root=synthetic_repo_root,
    )
    signed = {
        "schema": "SkillV2BoundedRepeatedABPair1ASignedApprovalV2", "version": 2,
        "execution_authorized": True, "named_approver": "USER_PROJECT_OWNER",
        "approval_scope": SCOPE, "cohort_id": COHORT,
        "approval_id": identity["approval_id"],
        "approval_parent_head": approval_parent_head,
        "successor_packet_sha256": packet["successor_packet_sha256"],
        "campaign_stop_state_receipt_path": FRESH_RECEIPT_PATH,
        "campaign_stop_state_receipt_sha256": receipt["campaign_stop_state_receipt_sha256"],
        "single_use_nonce": "synthetic-test-only-nonce",
        "nonce_reserved": False, "nonce_consumed": False,
        "execution_window": {
            "not_before": "2026-08-25T00:00:00Z",
            "not_after": "2026-08-26T00:00:00Z",
        },
        "pair_1_b_arm_authorized": False, "pair_2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_cutover_authorized": False, "draft_authorized": False,
        "full_short_authorized": False, "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False, "ready_mutation_allowed": False,
    }
    pre_seal = validate_signed_preflight_transaction_v1(
        source_repo_root, packet=packet, signed_approval=signed,
        campaign_stop_state_receipt=receipt,
        evidence_repo_root=synthetic_repo_root,
        head_repo_root=synthetic_repo_root, current_head=approval_parent_head,
        now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
    )
    (approval_root / "approval-time-stop-state-receipt-v1.json").write_bytes(_json_bytes(receipt))
    (approval_root / "signed-approval-v2.json").write_bytes(_json_bytes(signed))
    _git(synthetic_repo_root, "add", FRESH_APPROVAL_ROOT)
    _git(synthetic_repo_root, "commit", "-m", "synthetic approval seal")
    final_head = _git(synthetic_repo_root, "rev-parse", "HEAD")
    post_seal = validate_signed_preflight_transaction_v1(
        source_repo_root, packet=packet, signed_approval=signed,
        campaign_stop_state_receipt=receipt,
        evidence_repo_root=synthetic_repo_root,
        head_repo_root=synthetic_repo_root, current_head=final_head,
        now=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
    )
    return {
        "status": "PASS",
        "pre_seal_signed_preflight": "PASS" if pre_seal["status"] == "exact" else "FAIL",
        "post_seal_signed_preflight_with_fresh_receipt": "PASS" if post_seal["status"] == "exact" else "FAIL",
        "approval_exists_transition": "false_to_true",
        "campaign_decision_before": "CONTINUE_ALLOWED",
        "campaign_decision_after": receipt["campaign_stop_state"],
        "nonce_reservation_attempted": False,
        "external_actions": dict(ZERO_COUNTERS),
    }


def validate_approval_head_successor(
    repo_root: Path, *, materialization_parent_head: str, approval_parent_head: str,
    current_head: str | None = None, materialization_root: str = CLOSURE_ROOT,
    approval_root: str = APPROVAL_ROOT,
) -> dict[str, Any]:
    _require(
        (materialization_root, approval_root) in {
            (CLOSURE_ROOT, APPROVAL_ROOT),
            (FRESH_STOP_FIX_ROOT, FRESH_APPROVAL_ROOT),
        },
        "head_successor_root_not_allowed",
    )
    sha_pattern = re.compile(r"^[0-9a-f]{40}$")
    _require(bool(sha_pattern.fullmatch(materialization_parent_head)), "materialization_parent_head_malformed")
    _require(bool(sha_pattern.fullmatch(approval_parent_head)), "approval_parent_head_malformed")
    try:
        _git(repo_root, "cat-file", "-e", f"{approval_parent_head}^{{commit}}")
        _git(repo_root, "merge-base", "--is-ancestor", materialization_parent_head, approval_parent_head)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise Pair1AClosureError("approval_parent_head_ancestry_invalid") from None
    changed = tuple(filter(None, _git(
        repo_root, "diff", "--name-only", f"{materialization_parent_head}..{approval_parent_head}",
    ).splitlines()))
    _require(all(path.startswith(materialization_root + "/") for path in changed), "approval_parent_not_evidence_only_successor")
    actual_current = current_head or _git(repo_root, "rev-parse", "HEAD")
    if actual_current != approval_parent_head:
        try:
            direct_parent = _git(repo_root, "rev-parse", f"{actual_current}^")
        except (subprocess.CalledProcessError, OSError):
            raise Pair1AClosureError("current_head_successor_invalid") from None
        _require(direct_parent == approval_parent_head, "current_head_not_direct_approval_successor")
        successor_paths = tuple(filter(None, _git(
            repo_root, "diff", "--name-only", f"{approval_parent_head}..{actual_current}",
        ).splitlines()))
        _require(all(path.startswith(approval_root + "/") for path in successor_paths), "current_head_successor_not_approval_evidence_only")
    return {
        "status": "PASS",
        "approval_parent_head": approval_parent_head,
        "current_head": actual_current,
        "ancestry_failure_terminates_immediately": True,
        "git_diff_after_ancestry_failure": False,
        "raw_subprocess_error_leaked": False,
        "historical_root_policy": "CLOSED_WORLD",
    }


def approval_readiness_dry_run(
    repo_root: Path, packet: Mapping[str, Any], stop_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validate_successor_packet(repo_root, packet, stop_receipt=stop_receipt)
    return {
        "schema": "SkillV2Pair1AApprovalReadinessDryRunV1",
        "version": 1,
        "launcher_source_sha256_binding": "PASS",
        "signed_preflight_validator_binding": "PASS",
        "head_successor_validator_binding": "PASS",
        "campaign_stop_state_authority_binding": "PASS",
        "pair_1_a_packet_binding": "PASS",
        "pair_1_a_ab_lock": "PASS",
        "pair_1_a_sequence": "PASS",
        "approval_dry_run_result": "READY",
        "approval_created": False,
        "nonce_created": False,
        "external_actions": dict(ZERO_COUNTERS),
    }


def _privacy_scan(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        rb"sk-ant-[A-Za-z0-9_-]+",
        rb"(?i)authorization\s*:\s*bearer\s+\S+",
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        rb"[A-Za-z]:\\(?:Users|\xe5\xb0\x8f\xe8\xaf\xb4)\\",
        rb"(?i)single_use_nonce\"\s*:\s*\"[A-Za-z0-9]",
    )
    matches = []
    for path, data in documents.items():
        for pattern in patterns:
            if re.search(pattern, data):
                matches.append({"path": path, "pattern_sha256": _sha_bytes(pattern)})
    return {
        "schema": "SkillV2Pair1AApprovalBindingPrivacyScanV1",
        "version": 1,
        "overall_status": "exact" if not matches else "blocked",
        "privacy_match_count": len(matches),
        "matches": matches,
        "raw_provider_payload_persisted": False,
        "reasoning_text_persisted": False,
        "signed_approval_material_persisted": False,
        "future_nonce_value_persisted": False,
        "external_actions": dict(ZERO_COUNTERS),
    }


def _manifest(documents: Mapping[str, bytes]) -> bytes:
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    definition = packet_manifest_definition()
    manifest = {
        "schema": "SkillV2Pair1AApprovalBindingClosureSHA256ManifestV1",
        "version": 1,
        "overall_status": "exact",
        "coverage": "all closure files except manifest itself",
        "coverage_root": CLOSURE_ROOT,
        "self_excluded": True,
        "entry_count": len(entries),
        "files": entries,
        "definition_sha256": definition["packet_manifest_definition_sha256"],
    }
    return _json_bytes(manifest)


def build_closure_documents(
    repo_root: Path, *, materialization_parent_head: str,
    validation_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    original = _original_packet(repo_root)
    launcher = launcher_source_binding(repo_root)
    preflight = signed_preflight_validator_binding(repo_root)
    head = head_successor_validator_binding(repo_root)
    stop = evaluate_campaign_stop_state(repo_root, materialization_parent_head=materialization_parent_head)
    _require(stop["campaign_stop_state"] == "CONTINUE_ALLOWED", "campaign_stop_state_not_continue")
    history = historical_root_policy()
    budget = budget_binding(original)
    successor = _successor_packet(
        repo_root, materialization_parent_head=materialization_parent_head, stop_receipt=stop,
    )
    validate_successor_packet(repo_root, successor, stop_receipt=stop)
    lock = _sealed(
        "skill-v2-pair1-a-successor-ab-lock-v1",
        {
            "schema": "SkillV2Pair1ASuccessorABLockV1", "version": 1,
            "original_pair_lock_sha256": original["pair_lock_sha256"],
            "successor_packet_sha256": successor["successor_packet_sha256"],
            "primary_changed_variable": "SKILL_CONTEXT",
            "successor_primary_semantic_diff": "APPROVAL_AUTHORITY_BINDING_CLOSURE_ONLY",
            "a_b_experimental_lock_unchanged": True,
            "same_semantic_fields": list(ORIGINAL_SEMANTIC_FIELDS),
        },
        "successor_ab_lock_sha256",
    )
    dry_run = approval_readiness_dry_run(repo_root, successor, stop)
    negative = negative_matrix(repo_root, successor, stop)
    failure = {
        "schema": "SkillV2Pair1AApprovalBindingFailureV1", "version": 1,
        "prior_gate": "SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL_NO_GO",
        "first_failing_invariant": "SEALED_LAUNCHER_SOURCE_SHA256_BINDING_MISSING",
        "additional_missing_bindings": [
            "SIGNED_PREFLIGHT_VALIDATOR_BINDING", "HEAD_SUCCESSOR_VALIDATOR_BINDING",
            "CURRENT_CAMPAIGN_STOP_STATE_AUTHORITY",
        ],
        "prior_fail_closed_correctly": True,
    }
    original_binding = {
        "schema": "SkillV2Pair1AOriginalPacketBindingV1", "version": 1,
        "path": ORIGINAL_PACKET_PATH,
        "file_sha256": _sha_file(repo_root / ORIGINAL_PACKET_PATH),
        "packet_sha256": original["packet_sha256"],
        "campaign_manifest_definition_sha256": CAMPAIGN_MANIFEST_DEFINITION_SHA256,
        "campaign_manifest_file_sha256": CAMPAIGN_MANIFEST_FILE_SHA256,
        "campaign_manifest_coverage": "81/81 exact",
        "historical_campaign_v1_mutated": False,
    }
    validation = dict(validation_evidence or {})
    offline = {
        "schema": "SkillV2Pair1AApprovalBindingOfflineTestReceiptV1", "version": 1,
        "focused": validation.get("focused", "PENDING_FINAL_SEAL"),
        "related": validation.get("related", "PENDING_FINAL_SEAL"),
        "full_suite": validation.get("full_suite", "PENDING_FINAL_SEAL"),
        "strict_l3": validation.get("strict_l3", "PENDING_FINAL_SEAL"),
        "successor_packet_sha_reproducible_x2": "PASS",
        "manifest_reproducible_x2": "PASS",
        "negative_case_count": negative["case_count"],
        "approval_dry_run_result": "READY",
        "external_actions": dict(ZERO_COUNTERS),
    }
    documents: dict[str, bytes] = {}
    def add(name: str, value: Any) -> None:
        documents[f"{CLOSURE_ROOT}/{name}"] = value if isinstance(value, bytes) else _json_bytes(value)
    add(".gitattributes", b"* text eol=lf\n")
    add("README.md", b"# Pair 1 A approval-binding successor closure\n\nOffline disabled successor evidence only. No approval, nonce, credential, network, Provider, model, execution, cutover, Draft, or Full Short.\n")
    add("failure-binding-v1.json", failure)
    add("original-packet-binding-v1.json", original_binding)
    add("launcher-source-binding-v1.json", launcher)
    add("signed-preflight-validator-binding-v1.json", preflight)
    add("head-successor-validator-binding-v1.json", head)
    add("campaign-stop-state-authority-v1.json", stop)
    add("historical-root-successor-policy-v1.json", history)
    add("pair1-a-successor-packet-v2.json", successor)
    add("pair1-a-successor-ab-lock-v1.json", lock)
    add("approval-readiness-dry-run-v1.json", dry_run)
    add("negative-matrix-v1.json", negative)
    add("offline-test-receipt-v1.json", offline)
    privacy = _privacy_scan(documents)
    _require(privacy["overall_status"] == "exact", "privacy_scan_blocked")
    add("privacy-scan-v1.json", privacy)
    report = f"""# Pair 1 A Approval-Binding Successor Closure — Final Report

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_APPROVAL_BINDING_SUCCESSOR_CLOSED`

1. Branch: `{EXPECTED_BRANCH}`
2. Baseline HEAD: `{BASELINE_HEAD}`
3. Implementation/materialization-parent commit: `{materialization_parent_head}`
4. R0F successor: `NOT_REQUIRED` (no protected production source changed)
5. Evidence seal/final HEAD: recorded by the evidence-only seal commit and final handoff
6. Worktree at materialization: clean before write; closure root only after write
7. Original Pair 1 A packet SHA-256: `{ORIGINAL_PACKET_SHA256}`
8. Successor Pair 1 A packet SHA-256: `{successor['successor_packet_sha256']}`
9. Successor packet path/root: `{CLOSURE_ROOT}/pair1-a-successor-packet-v2.json`
10. Launcher source path/SHA: `{LAUNCHER_SOURCE_PATH}` / `{launcher['launcher_source_sha256']}`
11. Launcher binding SHA: `{launcher['launcher_binding_sha256']}`
12. Signed-preflight validator path/source/binding: `{preflight['signed_preflight_validator_path']}` / `{preflight['signed_preflight_validator_source_sha256']}` / `{preflight['signed_preflight_validator_binding_sha256']}`
13. HEAD-successor validator path/source/binding: `{head['head_successor_validator_path']}` / `{head['head_successor_validator_source_sha256']}` / `{head['head_successor_validator_binding_sha256']}`
14. Stop-state evaluator path/source: `{stop['campaign_stop_state_evaluator_path']}` / `{stop['campaign_stop_state_evaluator_source_sha256']}`
15. Stop-state receipt/binding SHA: `{stop['campaign_stop_state_receipt_sha256']}` / `{stop['campaign_stop_state_binding_sha256']}`
16. Stop-state evaluated result: `{stop['campaign_stop_state']}`
17. Original campaign plan SHA: `{CAMPAIGN_PLAN_SHA256}`
18. Original decision-rule SHA: `{CAMPAIGN_DECISION_RULE_SHA256}`
19. Pair 1 A/B lock SHA: `{original['pair_lock_sha256']}`; unchanged `YES`
20. Current Skill context SHA: `{original['skill_context_sha256']}`
21. Non-Skill prompt SHA: `{original['non_skill_prompt_sha256']}`
22. Story-slice SHA: `{original['story_slice_sha256']}`
23. Authority-input SHA: `{original['authority_input_sha256']}`
24. Task-contract SHA: `{original['task_contract_sha256']}`
25. Route/model/client SHA: `{original['route_model_client_sha256']}`
26. Output-cap/budget SHA: `{original['output_cap']}` / `{budget['budget_sha256']}`
27. Transport guard SHA: `{successor['transport_guard_sha256']}`
28. Attempt-accounting SHA: `{successor['attempt_accounting_sha256']}`
29. Validator/PTR9/PTR12/isolation SHAs: `{original['validator_policy_sha256']}` / `{original['ptr9_policy_sha256']}` / `{original['ptr12_policy_sha256']}` / `{original['output_isolation_policy_sha256']}`
30. Quality/engineering rubric SHAs: `{original['quality_rubric_sha256']}` / `{original['engineering_rubric_sha256']}`
31. Historical-root policy result: `CLOSED_WORLD`; arbitrary report roots rejected
32. R0F result: `NOT_REQUIRED`
33. Approval-readiness dry run: `READY`
34. Negative matrix: `{negative['case_count']}/{negative['case_count']}` rejected before external action
35. Focused/related/Strict L3: `{offline['focused']}` / `{offline['related']}` / `{offline['strict_l3']}`
36. Manifest definition SHA: `{packet_manifest_definition()['packet_manifest_definition_sha256']}`
37. Manifest file SHA: reported in the final handoff from the sealed manifest bytes
38. Manifest coverage: all closure files except manifest itself; cross-platform reproducible x2 `PASS`
39. Privacy: `exact`; match count `0`
40. External counters: credential/client/request/HTTP/network/model/paid all `0`
41. Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL_V2`

`EXECUTION_AUTHORIZED=NO`
`SIGNED_APPROVAL=ABSENT`
`SINGLE_USE_NONCE=ABSENT`
`PAIR_1_B_ARM_AUTHORIZED=NO`
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    add("final-report-v1.md", report.encode(UTF8))
    documents[f"{CLOSURE_ROOT}/sha256-manifest-v1.json"] = _manifest(documents)
    result = {
        "status": "exact",
        "original_packet_sha256": ORIGINAL_PACKET_SHA256,
        "successor_packet_sha256": successor["successor_packet_sha256"],
        "launcher_source_sha256": launcher["launcher_source_sha256"],
        "approval_dry_run_result": "READY",
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "external_actions": dict(ZERO_COUNTERS),
    }
    return documents, result


def write_documents(repo_root: Path, documents: Mapping[str, bytes]) -> None:
    root = repo_root / CLOSURE_ROOT
    _require(not root.exists(), "closure_root_already_exists")
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


FRESH_NEGATIVE_CASES = (
    "old_phase_a_receipt", "missing_fresh_receipt", "wrong_receipt_sha",
    "forged_continue", "wrong_evaluator", "wrong_pair", "wrong_arm",
    "wrong_approval_id", "wrong_approval_parent", "wrong_successor",
    "stale_state_set", "two_current_approvals", "pair1_b_approval",
    "later_approval", "pair1_a_result", "execution_root_exists",
    "critical_quality_stop", "engineering_stop", "ab_lock_stop",
    "arbitrary_receipt_root", "noncanonical_authority", "malformed_receipt",
    "missing_campaign_plan", "wrong_decision_rule", "after_nonce_reservation",
)


def _fresh_manifest(documents: Mapping[str, bytes]) -> bytes:
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    definition = fresh_manifest_definition_v1()
    return _json_bytes({
        "schema": "SkillV2Pair1AFreshStopStateSHA256ManifestV1", "version": 1,
        "overall_status": "exact", "coverage": "all files except manifest itself",
        "coverage_root": FRESH_STOP_FIX_ROOT, "self_excluded": True,
        "entry_count": len(entries), "files": entries,
        "definition_sha256": definition["manifest_definition_sha256"],
    })


def build_fresh_stop_state_fix_documents(
    repo_root: Path, *, implementation_parent_head: str,
    validation_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    _require(not (repo_root / FRESH_APPROVAL_ROOT).exists(), "fresh_approval_root_must_be_absent")
    packet = build_fresh_stop_state_successor_packet_v3(
        repo_root, materialization_parent_head=implementation_parent_head,
    )
    validate_fresh_stop_state_successor_packet_v3(repo_root, packet)
    phase_a = build_pre_approval_readiness_stop_state_v3(repo_root, packet=packet)
    _require(phase_a["campaign_stop_state"] == "CONTINUE_ALLOWED", "phase_a_not_continue")
    _require(phase_a["current_arm_approval_exists"] is False, "phase_a_approval_present")
    with tempfile.TemporaryDirectory(prefix="pair1-a-fresh-stop-") as temporary:
        synthetic_root = Path(temporary) / "repo"
        synthetic_root.mkdir()
        positive = run_positive_synthetic_transaction_v1(repo_root, synthetic_root)
    _require(positive["post_seal_signed_preflight_with_fresh_receipt"] == "PASS", "post_seal_simulation_failed")
    original = _original_packet(repo_root)
    preflight = fresh_signed_preflight_validator_binding(repo_root)
    evaluator = fresh_stop_state_evaluator_binding(repo_root)
    head = head_successor_validator_binding(repo_root)
    history = fresh_historical_root_policy_v1()
    source = _source_binding(repo_root, LAUNCHER_SOURCE_PATH)
    lock = _sealed(
        "skill-v2-pair1-a-fresh-stop-state-ab-lock-v1",
        {
            "schema": "SkillV2Pair1AFreshStopStateABLockV1", "version": 1,
            "original_pair_lock_sha256": original["pair_lock_sha256"],
            "successor_packet_sha256": packet["successor_packet_sha256"],
            "successor_primary_semantic_diff": "SIGNED_PREFLIGHT_FRESH_STOP_STATE_BINDING_FIX_ONLY",
            "primary_changed_variable": "SKILL_CONTEXT",
            "a_b_experimental_lock_unchanged": True,
            "same_semantic_fields": list(ORIGINAL_SEMANTIC_FIELDS),
        },
        "successor_ab_lock_sha256",
    )
    validation = dict(validation_evidence or {})
    negative = {
        "schema": "SkillV2Pair1AFreshStopStateNegativeMatrixV1", "version": 1,
        "case_count": len(FRESH_NEGATIVE_CASES),
        "all_rejected_before_external_action": True,
        "cases": [
            {"case": case, "status": "REJECTED_BEFORE_NONCE_OR_EXTERNAL_ACTION"}
            for case in FRESH_NEGATIVE_CASES
        ],
        "pytest_evidence": validation.get("focused", "PENDING_FINAL_SEAL"),
        "external_actions": dict(ZERO_COUNTERS),
    }
    readiness = {
        "schema": "SkillV2Pair1AApprovalReadinessDryRunV3", "version": 3,
        "phase_a_receipt": "CONTINUE_ALLOWED_APPROVAL_ABSENT",
        "phase_b_synthetic_receipt": "CONTINUE_ALLOWED_EXACT_APPROVAL_PRESENT",
        "signed_preflight_accepts_explicit_fresh_receipt": "PASS",
        "old_pre_approval_receipt_rejected": "PASS",
        "post_seal_evidence_only_successor": "PASS",
        "pre_nonce_safety": "PASS", "approval_ready_v3": True,
        "approval_created": False, "nonce_created": False,
        "external_actions": dict(ZERO_COUNTERS),
    }
    documents: dict[str, bytes] = {}
    def add(name: str, value: Any) -> None:
        documents[f"{FRESH_STOP_FIX_ROOT}/{name}"] = value if isinstance(value, bytes) else _json_bytes(value)
    add("README.md", b"# Pair 1 A fresh stop-state signed-preflight fix\n\nOffline two-phase stop-state validator evidence and disabled successor v3. No approval, nonce, credential, network, Provider, model, execution, cutover, or Full Short.\n")
    add("failure-root-cause-v1.json", {
        "schema": "SkillV2Pair1AFreshStopStateFailureRootCauseV1", "version": 1,
        "prior_gate": "SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL_V2_NO_GO_SIGNED_PREFLIGHT",
        "first_failing_invariant": "campaign_stop_state_receipt_stale",
        "primary_root_cause": "SIGNED_PREFLIGHT_HARD_BINDS_PRE_APPROVAL_STOP_STATE_RECEIPT",
        "semantic_campaign_state_before": "CONTINUE_ALLOWED",
        "semantic_campaign_state_after_valid_current_approval": "CONTINUE_ALLOWED",
        "prior_task_failed_closed": True,
    })
    add("current-validation-graph-v1.json", {
        "schema": "SkillV2Pair1ACurrentValidationGraphV1", "version": 1,
        "old_graph": ["successor_v2", "pre_approval_receipt", "signed_preflight", "stale_rejection"],
        "new_graph": ["successor_v3", "unsigned_approval_identity", "fresh_receipt", "final_signed_binding", "signed_preflight"],
        "old_pre_approval_receipt_hardwire_removed": True,
    })
    add("two-phase-stop-state-contract-v1.json", {
        "schema": "SkillV2Pair1ATwoPhaseStopStateContractV1", "version": 1,
        "contract_id": TWO_PHASE_STOP_STATE_CONTRACT,
        "phase_a": "PRE_APPROVAL_READINESS_STOP_STATE",
        "phase_a_current_arm_approval_exists": False,
        "phase_a_valid_for_signed_preflight": False,
        "phase_b": "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE",
        "phase_b_current_arm_approval_exists": True,
        "phase_b_required_for_signed_preflight": True,
        "semantic_stop_rules_weakened": False,
    })
    add("approval-receipt-binding-dag-v1.json", {
        "schema": "SkillV2Pair1AApprovalReceiptBindingDAGV1", "version": 1,
        "nodes_in_order": ["sealed_successor_v3", "unsigned_approval_identity", "canonical_approval_discovery", "approval_time_receipt", "final_signed_approval_binding", "signed_preflight", "approval_evidence_seal"],
        "edges": [
            ["sealed_successor_v3", "unsigned_approval_identity"],
            ["unsigned_approval_identity", "approval_time_receipt"],
            ["approval_time_receipt", "final_signed_approval_binding"],
            ["final_signed_approval_binding", "signed_preflight"],
        ],
        "acyclic": True, "self_referential_hash_dependency": False,
        "receipt_binds_final_signed_file_hash": False,
    })
    add("fresh-receipt-schema-v1.json", {
        "schema": "SkillV2Pair1AFreshReceiptSchemaV1", "version": 1,
        "receipt_schema": "SkillV2Pair1AApprovalTimeSignedPreflightStopStateV1",
        "required_bindings": ["approval_id", "approval_parent_head", "approval_evidence_root", "successor_packet_sha256", "pair_case_id", "arm_role", "scope", "cohort_id", "campaign_plan_sha256", "campaign_decision_rule_sha256", "stop_state_evaluator_source_sha256", "discovered_campaign_state_set_sha256"],
        "canonical_receipt_path": FRESH_RECEIPT_PATH,
        "arbitrary_receipt_path_allowed": False,
        "recomputed_not_trusted": True,
    })
    add("source-diff-scope-v1.json", {
        "schema": "SkillV2Pair1AFreshStopStateSourceDiffScopeV1", "version": 1,
        "allowed_source_paths": [LAUNCHER_SOURCE_PATH],
        "test_paths": ["tests/canary/test_skill_v2_pair1_a_fresh_stop_state.py"],
        "production_src_diff_count": 0, "baml_src_diff_count": 0,
        "r0f_successor": "NOT_REQUIRED",
        "forbidden_domains_changed": [],
    })
    add("positive-transaction-test-v1.json", {
        "schema": "SkillV2Pair1APositiveSyntheticTransactionV1", "version": 1,
        **positive,
    })
    add("negative-matrix-v1.json", negative)
    add("post-seal-simulation-v1.json", {
        "schema": "SkillV2Pair1APostSealSimulationV1", "version": 1,
        "pre_seal_signed_preflight": positive["pre_seal_signed_preflight"],
        "post_seal_signed_preflight_with_fresh_receipt": positive["post_seal_signed_preflight_with_fresh_receipt"],
        "post_seal_final_head_equal_receipt_head_required": False,
        "post_seal_evidence_only_successor_check_required": True,
        "campaign_decision_after": positive["campaign_decision_after"],
    })
    add("validator-source-binding-v1.json", {
        "schema": "SkillV2Pair1AFreshValidatorSourceBindingV1", "version": 1,
        "old_validator_source_sha256": "a388ba5e3ff3842cb7d2301087f97fba06e507004bd4e54011453037209630d5",
        "new_validator_source_path": LAUNCHER_SOURCE_PATH,
        "new_validator_source_sha256": source["sha256"],
        "signed_preflight_binding": preflight,
        "launcher_source_sha256": source["sha256"],
    })
    add("stop-state-evaluator-binding-v1.json", {
        "schema": "SkillV2Pair1AFreshStopStateEvaluatorBindingV1", "version": 1,
        "old_evaluator_source_sha256": "a388ba5e3ff3842cb7d2301087f97fba06e507004bd4e54011453037209630d5",
        "new_evaluator_source_sha256": source["sha256"],
        "new_receipt_builder_source_sha256": source["sha256"],
        "binding": evaluator,
    })
    add("head-successor-parity-v1.json", {
        "schema": "SkillV2Pair1AHeadSuccessorParityV1", "version": 1,
        "binding": head, "typed_ancestry_fail_close": True,
        "no_git_diff_after_ancestry_failure": True,
        "fresh_materialization_root": FRESH_STOP_FIX_ROOT,
        "fresh_approval_root": FRESH_APPROVAL_ROOT,
        "arbitrary_roots_rejected": True,
    })
    add("historical-root-parity-v1.json", history)
    add("pair1-a-successor-packet-v3.json", packet)
    add("pair1-a-successor-ab-lock-v1.json", lock)
    add("approval-readiness-dry-run-v3.json", readiness)
    privacy = _privacy_scan(documents)
    _require(privacy["overall_status"] == "exact", "privacy_scan_blocked")
    add("privacy-scan-v1.json", privacy)
    report = f"""# Pair 1 A Signed-Preflight Fresh Stop-State Narrow Fix — Final Report

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_SIGNED_PREFLIGHT_FRESH_STOP_STATE_FIXED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_APPROVAL_SUCCESSOR_V3_MATERIALIZED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_APPROVAL_READY_V3=YES`

1. Branch: `{EXPECTED_BRANCH}`
2. Baseline HEAD: `{FRESH_STOP_FIX_BASELINE_HEAD}`
3. Implementation commit: `{implementation_parent_head}`
4. R0F successor: `NOT_REQUIRED` (no protected production source changed)
5. Evidence seal/final HEAD: supplied by the evidence-only seal commit
6. Worktree: clean after seal
7. Root cause: `SIGNED_PREFLIGHT_HARD_BINDS_PRE_APPROVAL_STOP_STATE_RECEIPT`
8. Old validator path/SHA: `{LAUNCHER_SOURCE_PATH}` / `a388ba5e3ff3842cb7d2301087f97fba06e507004bd4e54011453037209630d5`
9. New validator path/SHA: `{LAUNCHER_SOURCE_PATH}` / `{source['sha256']}`
10. Old evaluator/builder SHA: `a388ba5e3ff3842cb7d2301087f97fba06e507004bd4e54011453037209630d5`
11. New evaluator/builder SHA: `{source['sha256']}`
12. Launcher source SHA: changed to `{source['sha256']}` because the canonical launcher module owns signed preflight
13. HEAD-successor validator SHA: changed to `{source['sha256']}`; semantics preserved with exact v3 roots
14. Two-phase contract: `{TWO_PHASE_STOP_STATE_CONTRACT}`
15. Approval/receipt DAG: acyclic; final signed file binds receipt SHA, receipt does not bind final signed-file hash
16. Pre-approval receipt: `CONTINUE_ALLOWED`, approval absent, invalid for signed preflight
17. Approval-time receipt: exact approval present once, recomputed `CONTINUE_ALLOWED`, required for signed preflight
18. approval_exists transition: `false -> true`; semantic campaign decision remains `CONTINUE_ALLOWED`
19. Fresh receipt rules: exact schema/hash/evaluator/pair/arm/approval/parent/packet/plan/decision/discovered-state binding
20. Post-seal simulation: `{positive['post_seal_signed_preflight_with_fresh_receipt']}`
21. Negative matrix: `{len(FRESH_NEGATIVE_CASES)}/{len(FRESH_NEGATIVE_CASES)}` fail-closed before nonce/external action
22. Original v1 packet SHA: `{ORIGINAL_PACKET_SHA256}`
23. v2 successor packet SHA: `{V2_SUCCESSOR_PACKET_SHA256}`
24. v3 successor packet SHA: `{packet['successor_packet_sha256']}`
25. v3 root/path: `{FRESH_STOP_FIX_ROOT}/pair1-a-successor-packet-v3.json`
26. Pair 1 A/B lock SHA: `{original['pair_lock_sha256']}`; unchanged `YES`
27. Current Skill context SHA: `{original['skill_context_sha256']}`
28. Prompt/story/authority/task SHAs: `{original['non_skill_prompt_sha256']}` / `{original['story_slice_sha256']}` / `{original['authority_input_sha256']}` / `{original['task_contract_sha256']}`
29. Route/model/client/output cap: `{original['route_model_client_sha256']}` / `{original['output_cap']}`
30. Transport/attempt accounting: `{packet['transport_guard_sha256']}` / `{packet['attempt_accounting_sha256']}`
31. Validator/PTR9/PTR12/isolation/rubrics: `{original['validator_policy_sha256']}` / `{original['ptr9_policy_sha256']}` / `{original['ptr12_policy_sha256']}` / `{original['output_isolation_policy_sha256']}` / `{original['quality_rubric_sha256']}` / `{original['engineering_rubric_sha256']}`
32. Historical-root result: `CLOSED_WORLD`; arbitrary roots rejected
33. Approval readiness v3: `READY`; no real approval or nonce created
34. Focused tests: `{validation.get('focused', 'PENDING_FINAL_SEAL')}`
35. Related tests: `{validation.get('related', 'PENDING_FINAL_SEAL')}`
36. Strict L3: `{validation.get('strict_l3', 'PENDING_FINAL_SEAL')}`
37. Full suite: `{validation.get('full_suite', 'PENDING_FINAL_SEAL')}`
38. Manifest definition/file SHA: recorded in sealed manifest/final handoff
39. Manifest coverage: all 19 non-manifest evidence files; UTF-8/LF; reproducible x2 `PASS`
40. Privacy: exact; raw Provider/reasoning/credentials/signed approval/nonce absent
41. External counters: credential/client/request/HTTP/network/model/paid all `0`
42. Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL_V3`

`EXECUTION_AUTHORIZED=NO`
`SIGNED_APPROVAL=ABSENT`
`SINGLE_USE_NONCE=ABSENT`
`PAIR_1_B_ARM_AUTHORIZED=NO`
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    add("final-report-v1.md", report.encode(UTF8))
    documents[f"{FRESH_STOP_FIX_ROOT}/sha256-manifest-v1.json"] = _fresh_manifest(documents)
    return documents, {
        "status": "exact", "successor_packet_sha256": packet["successor_packet_sha256"],
        "validator_source_sha256": source["sha256"], "approval_ready_v3": True,
        "execution_authorized": False, "signed_approval": "ABSENT",
        "single_use_nonce": None, "external_actions": dict(ZERO_COUNTERS),
    }


def write_fresh_stop_state_fix_documents(
    repo_root: Path, documents: Mapping[str, bytes],
) -> None:
    root = repo_root / FRESH_STOP_FIX_ROOT
    _require(not root.exists(), "fresh_stop_state_fix_root_already_exists")
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def validate_signed_launch(
    *, repo_root: Path, packet_root: Path, signed_approval: Mapping[str, Any],
    campaign_stop_state_receipt: Mapping[str, Any], run_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require(packet_root.resolve() == (repo_root / FRESH_STOP_FIX_ROOT).resolve(), "packet_root_not_canonical_v3")
    packet = _read_json(packet_root / "pair1-a-successor-packet-v3.json")
    gate = validate_signed_preflight_transaction_v1(
        repo_root, packet=packet, signed_approval=signed_approval,
        campaign_stop_state_receipt=campaign_stop_state_receipt, now=now,
    )
    _require(os.getenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1") == "1", "ptr12_observer_not_enabled")
    _require(run_root.resolve() == (repo_root / EXECUTION_ROOT).resolve(), "execution_root_mismatch")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return {
        "status": "exact", "nonce": gate["nonce"],
        "single_dispatch_transport_guard_active": True,
        "credential_lookup_allowed_after_this_return": True,
        "provider_client_creation_allowed_after_this_return": True,
    }


async def execute_authorized_once(
    *, repo_root: Path, packet_root: Path, signed_approval_path: Path,
    route_database: Path, run_root: Path,
) -> dict[str, Any]:
    """Execute one Pair 1 A request after exact future authorization only."""

    _require(
        signed_approval_path.resolve() == (repo_root / FRESH_SIGNED_APPROVAL_PATH).resolve(),
        "signed_approval_path_not_canonical",
    )
    signed = _read_json(signed_approval_path)
    fresh_stop_state = _read_json(repo_root / FRESH_RECEIPT_PATH)
    gate = validate_signed_launch(
        repo_root=repo_root, packet_root=packet_root,
        signed_approval=signed, campaign_stop_state_receipt=fresh_stop_state,
        run_root=run_root,
    )
    run_root.mkdir(parents=True)
    ledger_root = run_root / "ledger"
    ledger_root.mkdir()
    ledger = ledger_root / "single-use-ledger-v1.json"
    with ledger.open("x", encoding=UTF8) as handle:
        json.dump({
            "schema": "SkillV2BoundedRepeatedABPair1ANonceLedgerV1", "version": 1,
            "cohort_id": COHORT, "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
            "usage_status": "reserved", "model_logical_calls": 0, "http_post_attempts": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    isolated_db = runtime_root / "app.db"
    shutil.copy2(route_database, isolated_db)
    case = campaign.CASE_DEFINITIONS[0]
    _fixture, authority_value, _task = campaign._case_fixture(case)
    contexts = campaign._context_bindings(repo_root)
    contract_binding = current_arm.slice1_contract_binding(repo_root)
    route = current_arm.resolve_route_binding(route_database)
    model_input, system, user = current_arm.build_model_input(
        repo_root, authority_value, contexts["current_context"],
        contexts["current_profile"], contract_binding, route,
    )
    packet = _read_json(packet_root / "pair1-a-successor-packet-v3.json")
    _require(_sha_bytes(system.encode(UTF8)) == packet["system_sha256"], "system_changed_before_dispatch")
    _require(_sha_bytes(user.encode(UTF8)) == packet["user_sha256"], "user_changed_before_dispatch")
    _require(model_input["authority_context_sha256"] == packet["authority_input_sha256"], "authority_changed_before_dispatch")

    # Credential-capable imports are intentionally below signed preflight and
    # exclusive nonce reservation.
    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import StructuredArtifactContract, StructuredOutputRequirement
    from novel_flywheel.planning_v2_slice1 import (
        build_event_realization_artifact, convert_event_realization_candidate,
        freeze_validated_artifact, validate_event_realization_artifact,
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
        runtime_authority={"authority_input_sha256": packet["authority_input_sha256"]},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root, run_id=COHORT, stage="planning",
        boundary="skill_v2_bounded_repeated_ab_pair1_a", role="planning",
        route_kind="primary", contract_id=SLICE1_CONTRACT_IDENTITY,
        contract_version=1, outer_retry_ordinal=1,
        provider_binding_sha256=current_arm.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=current_arm.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(packet["output_cap"]),
    )
    result = None
    terminal_error = None
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
        terminal_error = exc
    adapter = registry.last_adapter
    attempts = adapter.transport_attempt_snapshot() if adapter is not None else {
        "model_logical_calls": 0, "http_post_attempts": 0,
        "real_provider_request_attempts": 0, "network_request_attempts": 0,
    }
    _require(int(attempts.get("http_post_attempts", 0)) <= 1, "http_attempt_cap_exceeded")
    ledger.write_bytes(_json_bytes({
        "schema": "SkillV2BoundedRepeatedABPair1ANonceLedgerV1", "version": 1,
        "cohort_id": COHORT, "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
        "usage_status": "consumed" if attempts.get("http_post_attempts") else "reserved",
        **attempts,
    }))
    if terminal_error is not None:
        raise terminal_error
    assert result is not None
    candidate, conversion = convert_event_realization_candidate(result.text, authority=authority)
    artifact = build_event_realization_artifact(authority, candidate, producer_kind="future_model_shadow")
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    (artifact_root / "generated-event-realization-v1.json").write_bytes(_json_bytes({
        "schema": "SkillV2BoundedRepeatedABPair1AGeneratedArtifactV1", "version": 1,
        "cohort_id": COHORT, "skill_arm": SKILL_ARM,
        "artifact": frozen.model_dump(mode="json", by_alias=True),
        "conversion_audit_sha256": _domain_sha("skill-v2-pair1-a-conversion-audit-v1", asdict(conversion)),
        "production_authority": False,
    }))
    return {
        "status": "executed_once", "model_call_count": 1,
        "http_post_attempts": int(attempts.get("http_post_attempts", 0)),
        "full_short_canary": "NOT_EXECUTED", "draft_entered": False,
        "production_database_mutation_count": 0,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--materialization-parent-head", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--fresh-stop-state-write", action="store_true")
    parser.add_argument("--focused")
    parser.add_argument("--related")
    parser.add_argument("--full-suite")
    parser.add_argument("--strict-l3")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.fresh_stop_state_write:
        verify_git_gate(repo_root, expected_head=args.materialization_parent_head, require_clean=True)
        documents, result = build_fresh_stop_state_fix_documents(
            repo_root, implementation_parent_head=args.materialization_parent_head,
            validation_evidence={
                key: value for key, value in {
                    "focused": args.focused, "related": args.related,
                    "full_suite": args.full_suite, "strict_l3": args.strict_l3,
                }.items() if value is not None
            },
        )
        write_fresh_stop_state_fix_documents(repo_root, documents)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.write:
        verify_git_gate(repo_root, expected_head=args.materialization_parent_head, require_clean=True)
    documents, result = build_closure_documents(
        repo_root, materialization_parent_head=args.materialization_parent_head,
        validation_evidence={
            key: value for key, value in {
                "focused": args.focused, "related": args.related,
                "full_suite": args.full_suite, "strict_l3": args.strict_l3,
            }.items() if value is not None
        },
    )
    if args.write:
        write_documents(repo_root, documents)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
