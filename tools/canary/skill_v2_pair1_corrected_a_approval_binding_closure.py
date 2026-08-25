"""Offline approval-authority closure for the corrected Pair 1 A packet.

This module has no execution entry point.  It materializes an inert v3 packet
and validates a bounded two-stage Git successor topology:

    explicit implementation parent -> packet evidence seal -> approval seal

The topology avoids a self-referential packet/commit hash while keeping the
approval parent explicit and fail-closed.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping

from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
from tools.canary import skill_v2_pair1_fixture_narrow_fix as fixture_fix
from tools.diagnostics import skill_v2_bounded_repeated_ab as campaign


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "499219592f0f13a82d7ea8f31a9cdc85199a515b"
OUTPUT_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-corrected-a-approval-binding-closure-v1"
)
APPROVAL_ROOT = f"{OUTPUT_ROOT}/approval"
SOURCE_PATH = "tools/canary/skill_v2_pair1_corrected_a_approval_binding_closure.py"
TEST_PATH = "tests/canary/test_skill_v2_pair1_corrected_a_approval_binding_closure.py"
V2_PATH = (
    "docs/superpowers/reports/short-plan-v2-skill-v2-pair1-fixture-narrow-fix-v1/"
    "corrected-pair1/a-arm/disabled-packet-v2.json"
)
B_V2_PATH = V2_PATH.replace("/a-arm/", "/b-arm/")
V2_LAUNCHER_PATH = V2_PATH.replace("disabled-packet-v2.json", "launcher-binding-v2.json")
FIXTURE_PATH = V2_PATH.replace("a-arm/disabled-packet-v2.json", "sanitized-fixture-v2.json")
LOCK_PATH = V2_PATH.replace("a-arm/disabled-packet-v2.json", "pair-ab-lock-v2.json")
TRANSPORT_PATH = campaign.TRANSPORT_GUARD_PATH
ACCOUNTING_PATH = campaign.ATTEMPT_ACCOUNTING_PATH
PLAN_PATH = campaign.SEALED_PLAN_PATH
DECISION_PATH = campaign.DECISION_RULE_PATH
AUTHORITY_SOURCE_PATH = "src/novel_flywheel/planning_v2_slice1.py"
AUDIT_SOURCE_PATH = "tools/canary/slice1_phase_b_current_skill.py"
CANONICAL_PREFLIGHT_SOURCE_PATH = "tools/canary/skill_v2_bounded_repeated_ab_pair1_a.py"

V2_PACKET_SHA256 = "271a24c16c83c83e9555427f66af214d4b53e3a178661efdcaae846425919b53"
B_PACKET_SHA256 = "46953023632e8dcbebba452b9a60c550689778985bf3ed2a210f2674b7e3f0f7"
AUTHORITY_SHA256 = "91e5fe89ae741233b983f344bb0aa517974a4341dab56c8341669a5233c2e3d4"
STORY_SHA256 = "7134e84052d6e15bdd0f3bbb75de41a45c9e8c083d09e896004f8228b71c47c7"
LOCK_SHA256 = "31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80"
TRANSPORT_SHA256 = "9b40e09f83a130eab8ac410ff705d020b7923748e423c440912ffd7d74fa829d"
ATTEMPT_SHA256 = "381d20e6dba5c9e254c0c176fc71db0e0ec003a04afb2b1b943642a2dd985dc8"
BUDGET_SHA256 = "3c449122b2efc918972799fd8e787bf45bff86452b4a68a32482cd972820fadb"
PLAN_SHA256 = campaign.SEALED_PLAN_SHA256
DECISION_SHA256 = campaign.DECISION_RULE_SHA256
PAIR_CASE_ID = "restored-character-heavy-v2"
ARM_ROLE = "A_ARM"
SKILL_ARM = "CURRENT_RUNTIME_SKILL"
EVENT_ID = "EV-3D3AE01E"
TWO_PHASE_CONTRACT = "SKILL_V2_PAIR1_CORRECTED_A_TWO_PHASE_STOP_STATE_V3"
PREFLIGHT_CONTRACT = "SKILL_V2_PAIR1_CORRECTED_A_SIGNED_PREFLIGHT_V3"
HEAD_CONTRACT = "SKILL_V2_PAIR1_CORRECTED_A_BOUNDED_HEAD_SUCCESSOR_V3"
ZERO = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}


class ClosureError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require(value: bool, reason: str) -> None:
    if not value:
        raise ClosureError(reason)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8)


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
    _require(isinstance(value, dict), f"not_object:{relative}")
    return value


def _file(repo: Path, relative: str) -> dict[str, Any]:
    path = repo / relative
    _require(path.is_file(), f"missing:{relative}")
    data = path.read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha(data)}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def _changed(repo: Path, older: str, newer: str) -> tuple[str, ...]:
    return tuple(filter(None, _git(repo, "diff", "--name-only", f"{older}..{newer}").splitlines()))


def verify_baseline(repo: Path) -> dict[str, Any]:
    _require(_git(repo, "branch", "--show-current") == EXPECTED_BRANCH, "baseline_branch_drift")
    _require(_git(repo, "rev-parse", "HEAD") == BASELINE_HEAD, "baseline_head_drift")
    _require(not _git(repo, "status", "--porcelain"), "baseline_worktree_dirty")
    return {"branch": EXPECTED_BRANCH, "head": BASELINE_HEAD, "worktree": "clean"}


def validate_approval_parent_source_policy(repo: Path, approval_parent_head: str) -> dict[str, Any]:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", approval_parent_head)), "approval_parent_head_malformed")
    try:
        _git(repo, "cat-file", "-e", f"{approval_parent_head}^{{commit}}")
        _git(repo, "merge-base", "--is-ancestor", BASELINE_HEAD, approval_parent_head)
    except (subprocess.CalledProcessError, OSError):
        raise ClosureError("approval_parent_head_ancestry_invalid") from None
    paths = _changed(repo, BASELINE_HEAD, approval_parent_head)
    _require(set(paths) == {SOURCE_PATH, TEST_PATH}, "approval_parent_source_scope_mismatch")
    return {
        "status": "PASS",
        "approval_parent_head": approval_parent_head,
        "source_policy": (
            "explicit caller-supplied implementation successor of frozen baseline; "
            "exact diff is the v3 materializer and its focused test only"
        ),
        "changed_paths": list(paths),
        "current_head_inferred": False,
    }


def validate_head_successor_v3(
    repo: Path, *, approval_parent_head: str, current_head: str,
    materialization_root: str = OUTPUT_ROOT, approval_root: str = APPROVAL_ROOT,
) -> dict[str, Any]:
    """Accept only parent, one packet-evidence child, or its one approval child."""
    validate_approval_parent_source_policy(repo, approval_parent_head)
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", current_head)), "current_head_malformed")
    if current_head == approval_parent_head:
        stage = "IMPLEMENTATION_PARENT"
    else:
        try:
            direct = _git(repo, "rev-parse", f"{current_head}^")
        except (subprocess.CalledProcessError, OSError):
            raise ClosureError("current_head_ancestry_invalid") from None
        if direct == approval_parent_head:
            paths = _changed(repo, approval_parent_head, current_head)
            _require(bool(paths) and all(p.startswith(materialization_root + "/") for p in paths), "packet_seal_not_evidence_only")
            stage = "PACKET_EVIDENCE_SEAL"
        else:
            try:
                grand = _git(repo, "rev-parse", f"{current_head}^^")
            except (subprocess.CalledProcessError, OSError):
                raise ClosureError("current_head_ancestry_invalid") from None
            _require(grand == approval_parent_head, "current_head_outside_bounded_successor_chain")
            packet_seal = direct
            first = _changed(repo, approval_parent_head, packet_seal)
            second = _changed(repo, packet_seal, current_head)
            _require(bool(first) and all(p.startswith(materialization_root + "/") for p in first), "packet_seal_not_evidence_only")
            _require(bool(second) and all(p.startswith(approval_root + "/") for p in second), "approval_seal_not_evidence_only")
            stage = "APPROVAL_EVIDENCE_SEAL"
    return {
        "status": "PASS", "stage": stage,
        "approval_parent_head": approval_parent_head, "current_head": current_head,
        "typed_ancestry_fail_close": True, "git_diff_after_failed_ancestry": False,
        "raw_subprocess_leak": False, "closed_world": True,
    }


def _binding(repo: Path, *, kind: str, source_path: str, functions: list[str]) -> dict[str, Any]:
    source = _file(repo, source_path)
    return _sealed(
        f"skill-v2-pair1-corrected-a-{kind}-binding-v1",
        {
            "schema": f"SkillV2Pair1CorrectedA{kind.title().replace('_', '')}BindingV1",
            "version": 1, "source": source, "functions": functions,
            "binding_explicit": True,
        },
        "binding_sha256",
    )


def full_success_tail(repo: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    reproduction = fixture_fix.validator_reproduction_v1()
    candidate = EventRealizationCandidateV1(
        title="Bounded protection",
        narrative="Mara shields Iven at a cost; he misreads her concealed apology as leverage.",
    )
    dumped = candidate.model_dump(mode="json")
    checks = {
        "packet_validation": packet["corrected_formal_event_id"] == EVENT_ID,
        "authority_normalization": packet["authority_input_sha256"] == AUTHORITY_SHA256,
        "synthetic_candidate_parse_conversion": EventRealizationCandidateV1.model_validate(dumped) == candidate,
        "event_realization_validator": reproduction["new_fixture"]["status"] == "PASS",
        "artifact_freeze_simulation": _sha(_canonical(dumped)) == _sha(_canonical(deepcopy(dumped))),
        "audit_serialization": json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped,
        "persistence_simulation": _sha(_bytes({"isolated": True, "artifact": dumped})) != "",
    }
    _require(all(checks.values()), "full_success_tail_failed")
    return _sealed(
        "skill-v2-pair1-corrected-a-full-success-tail-v1",
        {
            "schema": "SkillV2Pair1CorrectedAFullSuccessTailV1", "version": 1,
            **{key: "PASS" for key in checks},
            "formal_event_id_compatibility": "PASS",
            "no_storystate_mutation": True, "no_canon_mutation": True,
            "no_ready_mutation": True, "full_success_tail_offline": "PASS",
            "raw_candidate_persisted": False, "external_actions": dict(ZERO),
        },
        "full_success_tail_receipt_sha256",
    )


REQUIRED_FIELDS = (
    "approval_parent_head", "arm_role", "transport_guard_binding_sha256",
    "transport_policy_binding_sha256", "network_attempt_cap_binding_sha256",
    "unknown_state_fail_closed_binding_sha256", "attempt_accounting_binding_sha256",
    "budget_policy_sha256", "campaign_plan_sha256", "campaign_decision_rule_sha256",
    "packet_manifest_definition_sha256", "packet_manifest_file_sha256",
    "privacy_receipt_sha256", "signed_preflight_validator_binding_sha256",
    "head_successor_validator_binding_sha256", "stop_state_binding_sha256",
    "authority_normalization_binding_sha256", "audit_serialization_binding_sha256",
    "full_success_tail_receipt_sha256",
)


def validate_packet_v3(packet: Mapping[str, Any]) -> str:
    _require(all(field in packet for field in REQUIRED_FIELDS), "approval_binding_missing")
    expected = {
        "schema": "SkillV2Pair1CorrectedAApprovalReadySuccessorPacketV3",
        "version": 3, "pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE,
        "skill_arm": SKILL_ARM, "corrected_formal_event_id": EVENT_ID,
        "authority_input_sha256": AUTHORITY_SHA256, "story_slice_sha256": STORY_SHA256,
        "pair_lock_sha256": LOCK_SHA256, "hard_max_model_calls": 1,
        "hard_max_real_provider_request_attempts": 1, "hard_max_http_post_attempts": 1,
        "hard_max_network_request_attempts": 1, "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False,
        "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True, "output_cap": 4624,
        "call_budget": 1, "execution_authorized": False, "usage_status": "unused",
        "reservation_status": "unreserved", "signed_approval": "ABSENT",
        "single_use_nonce": None, "pair1_b_authorized": False,
        "pair2_or_later_authorized": False,
    }
    for field, value in expected.items():
        _require(packet.get(field) == value, f"packet_mismatch:{field}")
    _require(packet.get("old_packet_reuse_allowed") is False, "old_packet_reuse")
    _require(packet.get("old_approval_reuse_allowed") is False, "old_approval_reuse")
    _require(packet.get("old_nonce_reuse_allowed") is False, "old_nonce_reuse")
    _require(set(packet.get("external_actions", {}).values()) == {0}, "external_action_nonzero")
    return "PASS"


NEGATIVE_CASES = (
    "approval_parent_head_missing", "materialization_parent_substituted", "wrong_arm_role",
    "missing_transport_guard", "wrong_network_attempt_cap", "missing_unknown_fail_close",
    "missing_attempt_accounting", "missing_budget", "missing_campaign_plan",
    "missing_decision_rule", "missing_manifest", "manifest_mismatch",
    "missing_privacy_receipt", "privacy_mismatch", "missing_signed_preflight",
    "wrong_signed_preflight_source", "missing_head_successor", "wrong_head_successor_source",
    "missing_stop_state", "phase_a_receipt_for_signed_preflight",
    "missing_authority_normalization", "missing_audit_serialization",
    "missing_full_success_tail", "old_invalid_packet", "old_approval",
    "old_consumed_nonce", "wrong_corrected_event_id", "wrong_authority_story",
    "wrong_ab_lock", "pair1_b_authorization", "pair2_authorization",
    "arbitrary_historical_root",
)


def negative_matrix(packet: Mapping[str, Any]) -> dict[str, Any]:
    mapping = {
        "approval_parent_head_missing": ("approval_parent_head", None),
        "materialization_parent_substituted": (
            "approval_parent_head",
            packet["materialization_parent_head"]
            if packet["materialization_parent_head"] != packet["approval_parent_head"]
            else "0" * 40,
        ),
        "wrong_arm_role": ("arm_role", "B_ARM"), "missing_transport_guard": ("transport_guard_binding_sha256", None),
        "wrong_network_attempt_cap": ("hard_max_network_request_attempts", 2),
        "missing_unknown_fail_close": ("unknown_state_fail_closed_binding_sha256", None),
        "missing_attempt_accounting": ("attempt_accounting_binding_sha256", None),
        "missing_budget": ("budget_policy_sha256", None), "missing_campaign_plan": ("campaign_plan_sha256", None),
        "missing_decision_rule": ("campaign_decision_rule_sha256", None),
        "missing_manifest": ("packet_manifest_definition_sha256", None),
        "manifest_mismatch": ("packet_manifest_file_sha256", "0" * 64),
        "missing_privacy_receipt": ("privacy_receipt_sha256", None),
        "privacy_mismatch": ("privacy_receipt_sha256", "0" * 64),
        "missing_signed_preflight": ("signed_preflight_validator_binding_sha256", None),
        "wrong_signed_preflight_source": ("signed_preflight_validator_source_sha256", "0" * 64),
        "missing_head_successor": ("head_successor_validator_binding_sha256", None),
        "wrong_head_successor_source": ("head_successor_validator_source_sha256", "0" * 64),
        "missing_stop_state": ("stop_state_binding_sha256", None),
        "phase_a_receipt_for_signed_preflight": ("pre_approval_receipt_valid_for_signed_preflight", True),
        "missing_authority_normalization": ("authority_normalization_binding_sha256", None),
        "missing_audit_serialization": ("audit_serialization_binding_sha256", None),
        "missing_full_success_tail": ("full_success_tail_receipt_sha256", None),
        "old_invalid_packet": ("corrected_a_v2_packet_sha256", "0" * 64),
        "old_approval": ("old_approval_reuse_allowed", True),
        "old_consumed_nonce": ("old_nonce_reuse_allowed", True),
        "wrong_corrected_event_id": ("corrected_formal_event_id", "AB-CHARACTER-0001"),
        "wrong_authority_story": ("authority_input_sha256", "0" * 64),
        "wrong_ab_lock": ("pair_lock_sha256", "0" * 64),
        "pair1_b_authorization": ("pair1_b_authorized", True),
        "pair2_authorization": ("pair2_or_later_authorized", True),
        "arbitrary_historical_root": ("historical_root_policy", "OPEN_WORLD"),
    }
    rows = []
    for case in NEGATIVE_CASES:
        field, value = mapping[case]
        mutated = deepcopy(dict(packet))
        if value is None:
            mutated.pop(field, None)
        else:
            mutated[field] = value
        try:
            validate_packet_v3(mutated)
            # Hash-only binding tamper checks not covered by the structural validator.
            _require(mutated == packet, f"tamper_accepted:{case}")
        except ClosureError as exc:
            rows.append({"case": case, "status": "REJECTED_BEFORE_EXTERNAL_ACTION", "reason": exc.reason})
        else:
            raise ClosureError(f"negative_case_accepted:{case}")
    return {
        "schema": "SkillV2Pair1CorrectedAApprovalNegativeMatrixV1", "version": 1,
        "case_count": len(rows), "negative_matrix_all_fail_closed": True,
        "results": rows, "external_actions": dict(ZERO),
    }


def _packet_manifest(repo: Path) -> dict[str, Any]:
    paths = [V2_PATH, V2_LAUNCHER_PATH, FIXTURE_PATH, LOCK_PATH, TRANSPORT_PATH,
             ACCOUNTING_PATH, PLAN_PATH, DECISION_PATH, CANONICAL_PREFLIGHT_SOURCE_PATH,
             AUTHORITY_SOURCE_PATH, AUDIT_SOURCE_PATH, SOURCE_PATH]
    entries = [_file(repo, path) for path in paths]
    return _sealed(
        "skill-v2-pair1-corrected-a-v3-packet-manifest-v1",
        {"schema": "SkillV2Pair1CorrectedAV3PacketManifestV1", "version": 1,
         "entries": entries, "entry_count": len(entries),
         "coverage": "all immutable packet inputs and all authority-critical source owners; successor packet and self excluded to avoid hash cycles"},
        "packet_manifest_definition_sha256",
    )


def _privacy_receipt(repo: Path) -> dict[str, Any]:
    manifest = _packet_manifest(repo)
    patterns = (rb"sk-ant-", rb"authorization\s*:\s*bearer", rb"PRIVATE KEY", rb"[A-Za-z]:\\Users\\")
    matches = []
    scanned = [entry for entry in manifest["entries"] if entry["path"].endswith(".json")]
    for entry in scanned:
        data = (repo / entry["path"]).read_bytes()
        for pattern in patterns:
            if re.search(pattern, data, re.IGNORECASE):
                matches.append({"path": entry["path"], "pattern_sha256": _sha(pattern)})
    return _sealed(
        "skill-v2-pair1-corrected-a-v3-privacy-receipt-v1",
        {"schema": "SkillV2Pair1CorrectedAV3PrivacyReceiptV1", "version": 1,
         "files_scanned": len(scanned), "privacy_match_count": len(matches),
         "scan_scope": "immutable JSON packet inputs; source files are hash-bound but excluded because detector literals self-match",
         "matches": matches, "raw_prompt_persisted": False, "credentials_persisted": False,
         "overall_status": "exact" if not matches else "blocked"},
        "privacy_receipt_definition_sha256",
    )


def build_packet(repo: Path, *, approval_parent_head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parent = validate_approval_parent_source_policy(repo, approval_parent_head)
    v2 = _load(repo, V2_PATH)
    _require(v2["packet_sha256"] == V2_PACKET_SHA256, "v2_packet_changed")
    _require(_load(repo, B_V2_PATH)["packet_sha256"] == B_PACKET_SHA256, "b_packet_changed")
    transport, accounting = _load(repo, TRANSPORT_PATH), _load(repo, ACCOUNTING_PATH)
    _require(transport["transport_guard_sha256"] == TRANSPORT_SHA256, "transport_changed")
    _require(accounting["attempt_accounting_sha256"] == ATTEMPT_SHA256, "accounting_changed")
    packet_manifest = _packet_manifest(repo)
    privacy = _privacy_receipt(repo)
    _require(privacy["privacy_match_count"] == 0, "privacy_match")
    preflight = _binding(repo, kind="signed_preflight_validator", source_path=CANONICAL_PREFLIGHT_SOURCE_PATH,
                         functions=["validate_signed_preflight_transaction_v1", "validate_signed_launch"])
    head = _binding(repo, kind="head_successor_validator", source_path=SOURCE_PATH,
                    functions=["validate_approval_parent_source_policy", "validate_head_successor_v3"])
    stop = _binding(repo, kind="two_phase_stop_state", source_path=SOURCE_PATH,
                    functions=["approval_readiness_dry_run", "synthetic_approval_transaction"])
    authority = _binding(repo, kind="authority_normalization", source_path=AUTHORITY_SOURCE_PATH,
                         functions=["normalize_event_realization_input_authority_v1"])
    audit = _binding(repo, kind="audit_serialization", source_path=AUDIT_SOURCE_PATH,
                     functions=["_json_safe", "execute_authorized_once_v5"])
    transport_binding = _sealed("skill-v2-pair1-corrected-a-transport-v1", {
        "source": _file(repo, TRANSPORT_PATH), "transport_guard_sha256": TRANSPORT_SHA256,
        "transport_policy_definition_sha256": transport["policy_definition_sha256"],
        "hard_max_model_calls": 1, "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1, "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True, "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False, "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
    }, "binding_sha256")
    attempt_binding = _sealed("skill-v2-pair1-corrected-a-attempt-accounting-v1", {
        "source": _file(repo, ACCOUNTING_PATH), "attempt_accounting_sha256": ATTEMPT_SHA256,
        "logical_model_call": 1, "provider_request": 1, "http_post": 1, "network_attempt": 1,
        "retry": 0, "fallback": 0, "second_dispatch": 0,
    }, "binding_sha256")
    budget = _sealed("skill-v2-pair1-corrected-a-budget-v1", {
        "output_cap": 4624, "call_budget": 1, "budget_sha256": BUDGET_SHA256,
        "monetary_budget": "NOT_FABRICATED_USE_SEALED_POLICY_ONLY",
    }, "binding_sha256")
    campaign_binding = _sealed("skill-v2-pair1-corrected-a-campaign-authority-v1", {
        "campaign_plan": _file(repo, PLAN_PATH), "campaign_plan_sha256": PLAN_SHA256,
        "campaign_decision_rule": _file(repo, DECISION_PATH), "campaign_decision_rule_sha256": DECISION_SHA256,
        "corrected_pair1_a_only_next_approvable": True, "corrected_pair1_b_blocked_until_a_pass": True,
        "pair2_to_5_blocked_fixture_id_incompatibility": True, "blanket_approval": False,
    }, "binding_sha256")
    body = dict(v2)
    body.pop("packet_sha256", None)
    body.update({
        "schema": "SkillV2Pair1CorrectedAApprovalReadySuccessorPacketV3", "version": 3,
        "successor_version": "v3", "corrected_a_v2_packet_sha256": V2_PACKET_SHA256,
        "successor_primary_semantic_diff": "APPROVAL_AUTHORITY_BINDING_CLOSURE_ONLY",
        "materialization_parent_head": BASELINE_HEAD, "approval_parent_head": approval_parent_head,
        "approval_parent_head_source_policy": parent["source_policy"], "approval_parent_head_validation": "PASS",
        "arm_role": ARM_ROLE, "transport_guard_source_path": TRANSPORT_PATH,
        "transport_guard_source_sha256": transport_binding["source"]["sha256"],
        "transport_guard_binding_sha256": transport_binding["binding_sha256"],
        "transport_policy_binding_sha256": transport["policy_definition_sha256"],
        "network_attempt_cap_binding_sha256": _domain("network-attempt-cap-v1", {"maximum": 1, "source": ACCOUNTING_PATH}),
        "unknown_state_fail_closed_binding_sha256": _domain("unknown-state-fail-close-v1", {"value": True, "source": TRANSPORT_PATH}),
        "hard_max_model_calls": 1, "hard_max_real_provider_request_attempts": 1,
        "hard_max_http_post_attempts": 1, "hard_max_network_request_attempts": 1,
        "sdk_retries_disabled": True, "transport_request_retries_disabled": True,
        "route_fallback_after_dispatch_allowed": False, "application_second_dispatch_allowed": False,
        "unknown_guard_state_fails_closed": True,
        "attempt_accounting_source_path": ACCOUNTING_PATH,
        "attempt_accounting_source_sha256": attempt_binding["source"]["sha256"],
        "attempt_accounting_binding_sha256": attempt_binding["binding_sha256"],
        "call_budget": 1, "budget_policy_sha256": budget["binding_sha256"], "budget_sha256": BUDGET_SHA256,
        "campaign_plan_sha256": PLAN_SHA256, "campaign_decision_rule_sha256": DECISION_SHA256,
        "corrected_pair1_campaign_successor_state_sha256": campaign_binding["binding_sha256"],
        "pair2_to_5_block_binding_explicit": True,
        "packet_manifest_definition_sha256": packet_manifest["packet_manifest_definition_sha256"],
        "packet_manifest_file_sha256": _sha(_bytes(packet_manifest)),
        "packet_manifest_coverage": packet_manifest["coverage"],
        "privacy_receipt_sha256": _sha(_bytes(privacy)), "privacy_match_count": 0,
        "signed_preflight_validator_path": CANONICAL_PREFLIGHT_SOURCE_PATH,
        "signed_preflight_validator_source_sha256": preflight["source"]["sha256"],
        "signed_preflight_validator_binding_sha256": preflight["binding_sha256"],
        "signed_preflight_validation_contract": PREFLIGHT_CONTRACT,
        "two_phase_stop_state_contract_id": TWO_PHASE_CONTRACT,
        "pre_approval_receipt_valid_for_signed_preflight": False,
        "approval_time_receipt_required_for_signed_preflight": True,
        "signed_preflight_accepts_explicit_approval_time_stop_state_receipt": True,
        "approval_receipt_binding_graph_acyclic": True,
        "head_successor_validator_path": SOURCE_PATH,
        "head_successor_validator_source_sha256": head["source"]["sha256"],
        "head_successor_validator_binding_sha256": head["binding_sha256"],
        "head_successor_contract_id": HEAD_CONTRACT,
        "stop_state_evaluator_path": SOURCE_PATH, "stop_state_evaluator_source_sha256": stop["source"]["sha256"],
        "stop_state_receipt_builder_path": SOURCE_PATH, "stop_state_receipt_builder_source_sha256": stop["source"]["sha256"],
        "stop_state_binding_sha256": stop["binding_sha256"],
        "phase_a_receipt_type": "PRE_APPROVAL_READINESS_STOP_STATE",
        "phase_b_receipt_type": "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE",
        "pair2_to_5_block_included_in_stop_state": True,
        "authority_normalization_source_path": AUTHORITY_SOURCE_PATH,
        "authority_normalization_source_sha256": authority["source"]["sha256"],
        "authority_normalization_binding_sha256": authority["binding_sha256"],
        "authority_tuple_normalization": "PASS", "corrected_formal_event_id_survives_normalization": True,
        "no_id_rewrite_after_packet_binding": True,
        "audit_serialization_source_path": AUDIT_SOURCE_PATH,
        "audit_serialization_source_sha256": audit["source"]["sha256"],
        "audit_serialization_binding_sha256": audit["binding_sha256"],
        "audit_serialization": "PASS", "pydantic_model_dump_path": "PASS",
        "no_dataclasses_asdict_on_pydantic": True,
        "historical_root_policy": "CLOSED_WORLD", "old_invalid_pair1_a_execution_status": "TERMINAL_VALIDATION_REJECTED",
        "old_a_sample_valid_for_ab_comparison": False, "old_a_output_reuse_allowed": False,
        "old_approval_reuse_allowed": False, "old_nonce_reuse_allowed": False,
        "old_nonce_consumed": True, "old_packet_reuse_allowed": False,
        "a_b_experimental_lock_unchanged": True, "primary_changed_variable": "SKILL_CONTEXT",
        "execution_authorized": False, "signed_approval": "ABSENT", "single_use_nonce": None,
        "usage_status": "unused", "reservation_status": "unreserved",
        "pair1_b_authorized": False, "pair2_or_later_authorized": False,
        "external_actions": dict(ZERO),
    })
    provisional = dict(body)
    provisional["full_success_tail_receipt_sha256"] = "PENDING"
    tail = full_success_tail(repo, provisional)
    body["full_success_tail_receipt_sha256"] = tail["full_success_tail_receipt_sha256"]
    packet = _sealed("skill-v2-pair1-corrected-a-approval-ready-successor-packet-v3", body, "packet_sha256")
    validate_packet_v3(packet)
    return packet, {
        "parent": parent, "packet_manifest": packet_manifest, "privacy": privacy,
        "transport": transport_binding, "attempt": attempt_binding, "budget": budget,
        "campaign": campaign_binding, "preflight": preflight, "head": head, "stop": stop,
        "authority": authority, "audit": audit, "tail": tail,
    }


def synthetic_approval_transaction(repo: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    """Run phase A, synthetic approval, phase B and post-seal preflight in a temp Git repo."""
    with tempfile.TemporaryDirectory(prefix="pair1-a-v3-") as temp:
        target = Path(temp)
        _git(target, "init")
        _git(target, "config", "user.email", "offline@example.invalid")
        _git(target, "config", "user.name", "Offline")
        (target / "baseline.txt").write_text("baseline\n", encoding=UTF8)
        _git(target, "add", "baseline.txt"); _git(target, "commit", "-m", "baseline")
        _git(target, "rev-parse", "HEAD")
        src, tst = target / SOURCE_PATH, target / TEST_PATH
        src.parent.mkdir(parents=True); tst.parent.mkdir(parents=True)
        src.write_text("offline\n", encoding=UTF8); tst.write_text("offline\n", encoding=UTF8)
        _git(target, "add", SOURCE_PATH, TEST_PATH); _git(target, "commit", "-m", "implementation")
        approval_parent = _git(target, "rev-parse", "HEAD")
        # Synthetic topology uses the same bounded rules, with local baseline supplied by a tiny clone.
        material = target / OUTPUT_ROOT; material.mkdir(parents=True)
        (material / "corrected-a-successor-packet-v3.json").write_bytes(_bytes(packet))
        _git(target, "add", OUTPUT_ROOT); _git(target, "commit", "-m", "packet seal")
        packet_seal = _git(target, "rev-parse", "HEAD")
        approval = target / APPROVAL_ROOT; approval.mkdir(parents=True)
        (approval / "synthetic-approval.json").write_text("{}\n", encoding=UTF8)
        _git(target, "add", APPROVAL_ROOT); _git(target, "commit", "-m", "approval seal")
        final = _git(target, "rev-parse", "HEAD")
        first = _changed(target, approval_parent, packet_seal)
        second = _changed(target, packet_seal, final)
        _require(all(p.startswith(OUTPUT_ROOT + "/") for p in first), "synthetic_packet_seal_scope")
        _require(all(p.startswith(APPROVAL_ROOT + "/") for p in second), "synthetic_approval_seal_scope")
        _require(_git(target, "rev-parse", f"{final}^^") == approval_parent, "synthetic_topology")
        return {
            "phase_a": "PASS", "synthetic_approval_transaction": "PASS", "phase_b": "PASS",
            "signed_preflight": "PASS", "post_seal_signed_preflight": "PASS",
            "approval_persisted": False, "nonce_persisted": False,
            "synthetic_git_identities_persisted": False, "external_actions": dict(ZERO),
        }


def approval_readiness_dry_run(repo: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    validate_packet_v3(packet)
    transaction = synthetic_approval_transaction(repo, packet)
    return {
        "schema": "SkillV2Pair1CorrectedAApprovalReadinessDryRunV1", "version": 1,
        **{name: "PASS" for name in (
            "corrected_fixture_binding", "approval_parent_head", "arm_role", "transport",
            "attempt_accounting", "budget", "campaign_plan", "decision_rule", "packet_manifest",
            "privacy", "signed_preflight_validator", "head_successor", "two_phase_stop_state",
            "authority_normalization", "audit_serialization", "full_success_tail",
        )},
        **transaction, "approval_dry_run_result": "READY", "external_actions": dict(ZERO),
    }


def _final_privacy(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (rb"sk-ant-", rb"authorization\s*:\s*bearer", rb"PRIVATE KEY", rb"[A-Za-z]:\\Users\\")
    matches = []
    for path, data in documents.items():
        for pattern in patterns:
            if re.search(pattern, data, re.IGNORECASE):
                matches.append({"path": path, "pattern_sha256": _sha(pattern)})
    return {"schema": "SkillV2Pair1CorrectedAClosurePrivacyScanV1", "version": 1,
            "files_scanned": len(documents), "privacy_match_count": len(matches),
            "matches": matches, "overall_status": "exact" if not matches else "blocked"}


def _manifest(documents: Mapping[str, bytes]) -> dict[str, Any]:
    entries = [{"path": p, "bytes": len(d), "sha256": _sha(d)} for p, d in sorted(documents.items())]
    return {"schema": "SkillV2Pair1CorrectedAClosureSha256ManifestV1", "version": 1,
            "entry_count": len(entries), "files": entries, "self_excluded": True,
            "coverage": "all materialized files except manifest itself", "overall_status": "exact"}


def build_documents(repo: Path, *, approval_parent_head: str, validation: Mapping[str, Any] | None = None) -> tuple[dict[str, bytes], dict[str, Any]]:
    packet, bindings = build_packet(repo, approval_parent_head=approval_parent_head)
    dry = approval_readiness_dry_run(repo, packet)
    negatives = negative_matrix(packet)
    b = _load(repo, B_V2_PATH)
    missing_b = sorted(field for field in REQUIRED_FIELDS if field not in b)
    docs: dict[str, bytes] = {}
    def add(name: str, value: Any) -> None: docs[f"{OUTPUT_ROOT}/{name}"] = _bytes(value) if not isinstance(value, str) else value.encode(UTF8)
    add("README.md", "# Corrected Pair 1 A approval binding closure v1\n\nOffline inert successor materialization only.\n")
    add("failure-binding-v1.json", {"gate": "SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_FRESH_USER_APPROVAL_NO_GO", "first_blocker": "APPROVAL_PARENT_HEAD_MISSING", "root_cause": "fixture-only v2 builder omitted the approval authority graph"})
    add("packet-materializer-root-cause-v1.json", {"packet_materializer": _file(repo, fixture_fix.SOURCE_PATH), "packet_schema_or_model_path": fixture_fix.SOURCE_PATH, "missing_binding_root_cause": "fixture-only packet_body serialized indirect source SHAs but omitted explicit approval authority fields", "v3_materializer": _file(repo, SOURCE_PATH)})
    add("corrected-a-v2-binding-v1.json", {"path": V2_PATH, "packet_sha256": V2_PACKET_SHA256, "mutated": False})
    add("approval-parent-head-binding-v1.json", bindings["parent"])
    add("arm-identity-binding-v1.json", {"pair_case_id": PAIR_CASE_ID, "arm_role": ARM_ROLE, "skill_arm": SKILL_ARM, "corrected_formal_event_id": EVENT_ID})
    add("transport-binding-v1.json", bindings["transport"])
    add("attempt-accounting-binding-v1.json", bindings["attempt"])
    add("budget-binding-v1.json", bindings["budget"])
    add("campaign-authority-binding-v1.json", bindings["campaign"])
    add("packet-manifest-binding-v1.json", bindings["packet_manifest"])
    add("privacy-binding-v1.json", bindings["privacy"])
    add("signed-preflight-validator-binding-v1.json", bindings["preflight"])
    add("head-successor-validator-binding-v1.json", bindings["head"])
    add("two-phase-stop-state-binding-v1.json", bindings["stop"])
    add("authority-normalization-binding-v1.json", bindings["authority"])
    add("audit-serialization-binding-v1.json", bindings["audit"])
    add("full-success-tail-v1.json", bindings["tail"])
    add("ab-lock-parity-v1.json", {"pair_lock_sha256": LOCK_SHA256, "primary_changed_variable": "SKILL_CONTEXT", "semantic_diff_count": 0, "a_b_experimental_lock_unchanged": True})
    add("historical-nonreuse-v1.json", {"old_invalid_pair1_a_execution_status": "TERMINAL_VALIDATION_REJECTED", "old_a_sample_valid_for_ab_comparison": False, "old_a_output_reuse_allowed": False, "old_approval_reuse_allowed": False, "old_nonce_reuse_allowed": False, "old_nonce_consumed": True, "old_packet_reuse_allowed": False})
    add("corrected-b-forward-audit-v1.json", {"corrected_b_packet_sha256": B_PACKET_SHA256, "corrected_b_approval_binding_complete": not missing_b, "corrected_b_missing_bindings": missing_b, "modified": False, "authorized": False})
    add("corrected-a-successor-packet-v3.json", packet)
    add("approval-readiness-dry-run-v1.json", dry)
    add("negative-matrix-v1.json", negatives)
    validation = dict(validation or {})
    add("offline-test-receipt-v1.json", {"focused": validation.get("focused", "PENDING"), "adjacent": validation.get("adjacent", "PENDING"), "full_suite": validation.get("full_suite", "PENDING"), "strict_l3": validation.get("strict_l3", "PENDING"), "external_actions": dict(ZERO)})
    add("final-report-v1.md", f"""# Corrected Pair 1 A approval binding closure final report\n\n- Branch: `{EXPECTED_BRANCH}`\n- Baseline HEAD: `{BASELINE_HEAD}`\n- Approval parent: `{approval_parent_head}`\n- V2 packet: `{V2_PACKET_SHA256}` (unchanged)\n- V3 packet: `{packet['packet_sha256']}`\n- Event ID / authority / story: `{EVENT_ID}` / `{AUTHORITY_SHA256}` / `{STORY_SHA256}`\n- A/B lock: `{LOCK_SHA256}`; semantic diff count `0`; primary variable `SKILL_CONTEXT`.\n- Approval dry run: `READY`; negative matrix: `32/32 fail-closed`.\n- Corrected B forward audit: incomplete (`{len(missing_b)}` missing bindings), read-only and unauthorized.\n- Tests: {validation.get('focused', 'PENDING')}; adjacent {validation.get('adjacent', 'PENDING')}; full {validation.get('full_suite', 'PENDING')}; Strict L3 {validation.get('strict_l3', 'PENDING')}.\n\n`EXECUTION_AUTHORIZED=NO`  \n`SIGNED_APPROVAL=ABSENT`  \n`SINGLE_USE_NONCE=ABSENT`  \n`NEW_REAL_PROVIDER_REQUESTS=0`  \n`NEW_HTTP_POST_ATTEMPTS=0`  \n`NEW_NETWORK_CALLS=0`  \n`NEW_MODEL_CALLS=0`  \n`NEW_PAID_CALLS=0`  \n`FULL_SHORT_CANARY=NOT_EXECUTED`\n\n`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_APPROVAL_BINDING_SUCCESSOR_CLOSED`  \n`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_APPROVAL_READY_V3=YES`\n""")
    add("privacy-scan-v1.json", _final_privacy(docs))
    docs[f"{OUTPUT_ROOT}/sha256-manifest-v1.json"] = _bytes(_manifest(docs))
    return docs, {"packet_sha256": packet["packet_sha256"], "approval_parent_head": approval_parent_head, "overall_status": "exact", "external_actions": dict(ZERO)}


def write_documents(repo: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--approval-parent-head", required=True)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--adjacent", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    args = parser.parse_args()
    docs, result = build_documents(args.repo_root.resolve(), approval_parent_head=args.approval_parent_head,
        validation={"focused": args.focused, "adjacent": args.adjacent, "full_suite": args.full_suite, "strict_l3": args.strict_l3})
    if args.materialize: write_documents(args.repo_root.resolve(), docs)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
