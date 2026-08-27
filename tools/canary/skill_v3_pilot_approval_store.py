"""Pilot-scoped durable signed-approval storage for the Skill V3 experiment.

The store lives under the configured application data directory and is rejected
when it resolves inside the Git worktree.  Repository reports are audit copies;
they are not runtime approval authority.  This module performs local file and
Git checks only and has no Provider or transport capability.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)

from . import skill_v3_character_heavy_pilot as pilot


SIGNED_APPROVAL_SCHEMA = "SkillV3PilotSuccessorSignedApprovalV1"
CONSUMPTION_SCHEMA = "SkillV3PilotSuccessorApprovalConsumptionV1"
APPROVAL_SCOPE = "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_A1_ONLY"
SIGNED_APPROVAL_DOMAIN = "novel-flywheel-skill-v3-pilot-successor-signed-approval-v1"
CONSUMPTION_DOMAIN = "novel-flywheel-skill-v3-pilot-successor-approval-consumption-v1"
DEFAULT_STORE_RELATIVE = Path(
    "canary-approval-ledgers/skill-v3-character-heavy-multi-sample-v1/signed-approvals-v1"
)
REQUIRED_EGRESS_SCOPE = (
    "exact sealed A1 system/context packet",
    "A1 authority/task/story slice",
    "frozen non-Skill project guidance",
    "A-arm Skill context",
    "structured output contract",
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_PAYLOAD_FIELDS = {
    "approval_id",
    "repository_head",
    "pilot_id",
    "sample_id",
    "sample_slot",
    "arm",
    "sample_index",
    "sample_lock_sha256",
    "parent_experiment_lock_sha256",
    "model_input_component_binding_sha256",
    "provider_descriptor_sha256",
    "model_binding_sha256",
    "route_fingerprint",
    "max_output_tokens",
    "user_authorization_message_sha256",
    "user_authorization_context_identity_sha256",
    "issued_at",
    "expires_at",
}
_SIGNED_FIELDS = _PAYLOAD_FIELDS | {
    "schema",
    "version",
    "canonicalization_version",
    "repository_branch",
    "approval_scope",
    "max_provider_request_attempts",
    "max_network_request_attempts",
    "max_http_post_attempts",
    "max_logical_model_calls",
    "no_retry",
    "no_transport_retry",
    "no_fallback",
    "no_route_switch",
    "no_resume",
    "no_second_dispatch",
    "required_egress_scope",
    "raw_ref_corpus_egress",
    "named_approver",
    "approval_method",
    "authorized_actions",
    "single_use",
    "usage_status",
    "execution_authorized",
    "other_samples_authorized",
    "skill_v3_cutover_authorized",
    "planning_v2_cutover_authorized",
    "full_short_authorized",
    "nonce_state",
    "signed_approval_sha256",
}


class SkillV3ApprovalStoreError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise SkillV3ApprovalStoreError(reason_code)


def _parse_utc(value: Any) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), "APPROVAL_TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise SkillV3ApprovalStoreError("APPROVAL_TIME_INVALID") from exc


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SkillV3ApprovalStoreError("GIT_STATE_UNAVAILABLE") from exc
    return completed.stdout.strip()


def _clean_git_identity(repo_root: Path) -> tuple[str, str]:
    repo = repo_root.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    _require(_HEX40.fullmatch(head) is not None, "GIT_STATE_UNAVAILABLE")
    _require(not _git(repo, "status", "--porcelain=v1", "-uall"), "WORKTREE_NOT_CLEAN")
    return head, branch


def default_successor_approval_store_root() -> Path:
    return default_settings().data_dir / DEFAULT_STORE_RELATIVE


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _exact_store_root(repo_root: Path, store_root: Path) -> Path:
    repo = repo_root.resolve(strict=True)
    requested = Path(os.path.abspath(store_root))
    _require(not _path_is_within(requested, repo), "APPROVAL_STORE_INSIDE_GIT_WORKTREE")
    requested.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=True)
    _require(
        os.path.normcase(str(resolved)) == os.path.normcase(str(requested)),
        "APPROVAL_STORE_PATH_NOT_EXACT",
    )
    for component in (resolved, *resolved.parents):
        attributes = getattr(component.stat(), "st_file_attributes", 0)
        _require(not attributes & 0x400, "APPROVAL_STORE_REPARSE_POINT_FORBIDDEN")
        if component.parent == component:
            break
    return resolved


def _approval_key(approval_id: str) -> str:
    _require(_APPROVAL_ID.fullmatch(approval_id) is not None, "APPROVAL_ID_INVALID")
    return domain_sha256("skill-v3-pilot-approval-storage-key-v1", approval_id)


def _approval_path(root: Path, approval_id: str) -> Path:
    return root / f"{_approval_key(approval_id)}.approval.json"


def _consumption_path(root: Path, approval_id: str) -> Path:
    return root / f"{_approval_key(approval_id)}.consumed.json"


def _exclusive_write(path: Path, value: Mapping[str, Any], replay_code: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SkillV3ApprovalStoreError(replay_code) from exc
    try:
        os.write(descriptor, canonical_json_bytes(value) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillV3ApprovalStoreError(reason_code) from exc
    _require(isinstance(value, dict), reason_code)
    return value


def _sealed_approval(payload: Mapping[str, Any], branch: str) -> dict[str, Any]:
    _require(set(payload) == _PAYLOAD_FIELDS, "SIGNED_APPROVAL_FIELDS_UNEXPECTED")
    body = {
        "schema": SIGNED_APPROVAL_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
        "repository_branch": branch,
        "approval_scope": APPROVAL_SCOPE,
        "max_provider_request_attempts": 1,
        "max_network_request_attempts": 1,
        "max_http_post_attempts": 1,
        "max_logical_model_calls": 1,
        "no_retry": True,
        "no_transport_retry": True,
        "no_fallback": True,
        "no_route_switch": True,
        "no_resume": True,
        "no_second_dispatch": True,
        "required_egress_scope": list(REQUIRED_EGRESS_SCOPE),
        "raw_ref_corpus_egress": False,
        "named_approver": "USER_PROJECT_OWNER",
        "approval_method": "explicit_same_conversation_user_authorization",
        "authorized_actions": {
            "credential_lookup": True,
            "provider_client_creation": True,
            "network": True,
            "paid_provider_model_request": True,
            "necessary_request_data_egress": True,
        },
        "single_use": True,
        "usage_status": "unused",
        "execution_authorized": True,
        "other_samples_authorized": False,
        "skill_v3_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "full_short_authorized": False,
        "nonce_state": "NOT_CREATED",
    }
    return {
        **body,
        "signed_approval_sha256": domain_sha256(SIGNED_APPROVAL_DOMAIN, body),
    }


def validate_successor_signed_approval_v1(
    value: Mapping[str, Any],
    *,
    expected_head: str,
    expected_sample_id: str,
    expected_sample_lock_sha256: str,
    expected_parent_experiment_lock_sha256: str,
    expected_branch: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "SIGNED_APPROVAL_SCHEMA_MISMATCH")
    _require(
        value.get("schema") == SIGNED_APPROVAL_SCHEMA and value.get("version") == 1,
        "SIGNED_APPROVAL_SCHEMA_MISMATCH",
    )
    _require(set(value) == _SIGNED_FIELDS, "SIGNED_APPROVAL_FIELDS_UNEXPECTED")
    _require(
        value.get("canonicalization_version") == CANONICALIZATION_VERSION,
        "SIGNED_APPROVAL_CANONICALIZATION_UNSUPPORTED",
    )
    _require(value.get("approval_scope") == APPROVAL_SCOPE, "APPROVAL_SCOPE_MISMATCH")
    _require(value.get("pilot_id") == pilot.PILOT_ID, "STALE_APPROVAL")
    _require(value.get("sample_id") == expected_sample_id, "APPROVAL_FOR_WRONG_SAMPLE")
    _require(
        value.get("sample_lock_sha256") == expected_sample_lock_sha256,
        "APPROVAL_FOR_WRONG_SAMPLE_LOCK",
    )
    _require(
        value.get("parent_experiment_lock_sha256")
        == expected_parent_experiment_lock_sha256,
        "STALE_PARENT_EXPERIMENT_LOCK",
    )
    _require(value.get("repository_head") == expected_head, "STALE_APPROVAL_HEAD")
    _require(_HEX40.fullmatch(str(value.get("repository_head"))) is not None, "STALE_APPROVAL_HEAD")
    if expected_branch is not None:
        _require(value.get("repository_branch") == expected_branch, "STALE_APPROVAL_BRANCH")
    for field in (
        "sample_lock_sha256",
        "parent_experiment_lock_sha256",
        "model_input_component_binding_sha256",
        "provider_descriptor_sha256",
        "model_binding_sha256",
        "route_fingerprint",
        "user_authorization_message_sha256",
        "user_authorization_context_identity_sha256",
    ):
        _require(_HEX64.fullmatch(str(value.get(field))) is not None, f"{field.upper()}_INVALID")
    _require(value.get("sample_slot") == "A1", "APPROVAL_FOR_WRONG_SAMPLE")
    _require(value.get("arm") == "A" and value.get("sample_index") == 1, "APPROVAL_FOR_WRONG_SAMPLE")
    _require(value.get("max_output_tokens") == 4624, "WRONG_OUTPUT_CAP")
    for field in (
        "max_provider_request_attempts",
        "max_network_request_attempts",
        "max_http_post_attempts",
        "max_logical_model_calls",
    ):
        _require(value.get(field) == 1, "APPROVAL_BUDGET_MISMATCH")
    for field in (
        "no_retry",
        "no_transport_retry",
        "no_fallback",
        "no_route_switch",
        "no_resume",
        "no_second_dispatch",
    ):
        _require(value.get(field) is True, "APPROVAL_DISPATCH_POLICY_MISMATCH")
    _require(tuple(value.get("required_egress_scope") or ()) == REQUIRED_EGRESS_SCOPE, "APPROVAL_EGRESS_SCOPE_MISMATCH")
    _require(value.get("raw_ref_corpus_egress") is False, "APPROVAL_EGRESS_SCOPE_MISMATCH")
    _require(value.get("named_approver") == "USER_PROJECT_OWNER", "NAMED_APPROVER_INVALID")
    _require(
        value.get("authorized_actions") == {
            "credential_lookup": True,
            "provider_client_creation": True,
            "network": True,
            "paid_provider_model_request": True,
            "necessary_request_data_egress": True,
        },
        "APPROVAL_ACTION_SCOPE_MISMATCH",
    )
    _require(value.get("single_use") is True, "APPROVAL_NOT_SINGLE_USE")
    _require(value.get("usage_status") == "unused", "APPROVAL_REUSE")
    _require(value.get("execution_authorized") is True, "SIGNED_APPROVAL_NOT_EXECUTABLE")
    _require(value.get("nonce_state") == "NOT_CREATED", "NONCE_CREATED_DURING_APPROVAL")
    _require(
        all(value.get(field) is False for field in (
            "other_samples_authorized",
            "skill_v3_cutover_authorized",
            "planning_v2_cutover_authorized",
            "full_short_authorized",
        )),
        "APPROVAL_SCOPE_MISMATCH",
    )
    issued = _parse_utc(value.get("issued_at"))
    expires = _parse_utc(value.get("expires_at"))
    current = now or datetime.now(timezone.utc)
    _require(issued <= current <= expires, "STALE_APPROVAL")
    body = dict(value)
    digest = body.pop("signed_approval_sha256", None)
    _require(digest == domain_sha256(SIGNED_APPROVAL_DOMAIN, body), "SIGNED_APPROVAL_SHA256_MISMATCH")
    return deepcopy(dict(value))


def _active_approval_exists(root: Path, value: Mapping[str, Any], now: datetime) -> bool:
    for path in root.glob("*.approval.json"):
        existing = _read_json(path, "SIGNED_APPROVAL_STORAGE_INVALID")
        if (
            existing.get("pilot_id") == value.get("pilot_id")
            and existing.get("sample_id") == value.get("sample_id")
            and existing.get("repository_head") == value.get("repository_head")
            and not _consumption_path(root, str(existing.get("approval_id"))).exists()
            and _parse_utc(existing.get("expires_at")) >= now
        ):
            return True
    return False


def create_successor_signed_approval_v1(
    *,
    repo_root: Path,
    store_root: Path,
    payload: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    before_head, branch = _clean_git_identity(repo_root)
    _require(payload.get("repository_head") == before_head, "STALE_APPROVAL_HEAD")
    root = _exact_store_root(repo_root, store_root)
    current = now or datetime.now(timezone.utc)
    value = _sealed_approval(payload, branch)
    value = validate_successor_signed_approval_v1(
        value,
        expected_head=before_head,
        expected_sample_id=str(payload["sample_id"]),
        expected_sample_lock_sha256=str(payload["sample_lock_sha256"]),
        expected_parent_experiment_lock_sha256=str(payload["parent_experiment_lock_sha256"]),
        expected_branch=branch,
        now=current,
    )
    _require(not _active_approval_exists(root, value, current), "ACTIVE_APPROVAL_ALREADY_EXISTS")
    _exclusive_write(
        _approval_path(root, str(value["approval_id"])),
        value,
        "APPROVAL_ID_ALREADY_EXISTS",
    )
    after_head, after_branch = _clean_git_identity(repo_root)
    _require(after_head == before_head and after_branch == branch, "APPROVAL_CHANGED_GIT_STATE")
    return value


def load_successor_signed_approval_v1(
    *,
    repo_root: Path,
    store_root: Path,
    approval_id: str,
    expected_sample_id: str,
    expected_sample_lock_sha256: str,
    expected_parent_experiment_lock_sha256: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    head, branch = _clean_git_identity(repo_root)
    root = _exact_store_root(repo_root, store_root)
    _require(not _consumption_path(root, approval_id).exists(), "APPROVAL_REUSE")
    value = _read_json(_approval_path(root, approval_id), "SIGNED_APPROVAL_NOT_FOUND")
    return validate_successor_signed_approval_v1(
        value,
        expected_head=head,
        expected_sample_id=expected_sample_id,
        expected_sample_lock_sha256=expected_sample_lock_sha256,
        expected_parent_experiment_lock_sha256=expected_parent_experiment_lock_sha256,
        expected_branch=branch,
        now=now,
    )


def consume_successor_signed_approval_v1(
    *, store_root: Path, approval_id: str, execution_receipt_sha256: str,
) -> dict[str, Any]:
    root = Path(store_root).resolve(strict=True)
    approval = _read_json(_approval_path(root, approval_id), "SIGNED_APPROVAL_NOT_FOUND")
    _require(_HEX64.fullmatch(execution_receipt_sha256) is not None, "EXECUTION_RECEIPT_SHA256_INVALID")
    body = {
        "schema": CONSUMPTION_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "approval_id": approval_id,
        "signed_approval_sha256": approval.get("signed_approval_sha256"),
        "execution_receipt_sha256": execution_receipt_sha256,
    }
    receipt = {
        **body,
        "consumption_sha256": domain_sha256(CONSUMPTION_DOMAIN, body),
    }
    _exclusive_write(
        _consumption_path(root, approval_id), receipt, "APPROVAL_REUSE",
    )
    return receipt


def successor_payload_from_sealed_a1_v1(
    *,
    repo_root: Path,
    approval_id: str,
    user_authorization_message_sha256: str,
    user_authorization_context_identity_sha256: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    head, _branch = _clean_git_identity(repo_root)
    sealed = pilot.load_sealed_pilot(repo_root)
    lock = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    model_input = pilot.reconstruct_sample_input(repo_root, str(lock["sample_id"]))
    return {
        "approval_id": approval_id,
        "repository_head": head,
        "pilot_id": pilot.PILOT_ID,
        "sample_id": lock["sample_id"],
        "sample_slot": lock["sample_slot"],
        "arm": lock["arm"],
        "sample_index": int(lock["sample_index"]),
        "sample_lock_sha256": lock["sample_lock_sha256"],
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "model_input_component_binding_sha256": model_input.model_input_component_binding_sha256,
        "provider_descriptor_sha256": model_input.provider_descriptor_sha256,
        "model_binding_sha256": model_input.model_binding_sha256,
        "route_fingerprint": model_input.route_fingerprint,
        "max_output_tokens": model_input.output_cap,
        "user_authorization_message_sha256": user_authorization_message_sha256,
        "user_authorization_context_identity_sha256": user_authorization_context_identity_sha256,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
