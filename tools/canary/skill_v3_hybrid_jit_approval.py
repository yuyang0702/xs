"""Strict, durable JIT approvals for the sealed Skill V3 Hybrid pilot.

This module has no Provider or transport imports.  It only validates hash-only
campaign authority, seals one approval for the next eligible sample, and keeps
the immutable approval and mutable single-use lifecycle outside the worktree.
Historical Selective V1-V4 approval namespaces are intentionally untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid


APPROVAL_SCHEMA = "SkillV3HybridSampleJitSignedApprovalV1"
APPROVAL_VERSION = 1
APPROVAL_DOMAIN = "novel-flywheel-skill-v3-hybrid-sample-jit-signed-approval-v1"
LIFECYCLE_SCHEMA = "SkillV3HybridSampleApprovalLifecycleV1"
LIFECYCLE_DOMAIN = "novel-flywheel-skill-v3-hybrid-sample-approval-lifecycle-v1"
PERMISSION_SCHEMA = "SkillV3HybridCampaignPermissionV1"
PERMISSION_DOMAIN = "novel-flywheel-skill-v3-hybrid-campaign-permission-v1"
FAILURE_SCHEMA = "SkillV3HybridApprovalBoundaryFailureV1"
FAILURE_DOMAIN = "novel-flywheel-skill-v3-hybrid-approval-boundary-failure-v1"
APPROVAL_SCOPE = "SKILL_V3_HYBRID_CHARACTER_HEAVY_SINGLE_SAMPLE_JIT_ONLY"
WORKTREE_POLICY = "CLEAN"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
DEFAULT_STORE_RELATIVE = Path(
    "canary-approval-ledgers/skill-v3-hybrid-character-heavy-v1/jit-approvals-v1"
)
USAGE_STATES = {"UNUSED", "CONSUMED", "INVALID", "EXPIRED"}
TERMINAL_STATES = {"CONSUMED", "INVALID", "EXPIRED"}
ZERO_ATTEMPT_COUNTERS = {
    "logical_model_call_count": 0,
    "provider_request_attempt_count": 0,
    "http_post_attempt_count": 0,
    "network_attempt_count": 0,
}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")

_PERMISSION_FIELDS = {
    "schema", "version", "canonicalization_version", "permission_id",
    "pilot_id", "experiment_lock_sha256", "repository_head",
    "repository_branch", "worktree_policy", "authorized_sequence",
    "authorized_sample_ids", "authorized_sample_lock_sha256s",
    "provider", "provider_descriptor_sha256", "model",
    "model_binding_sha256", "protocol", "route_fingerprint",
    "destination_origin", "destination_hostname", "destination_port",
    "destination_path", "operator_classification", "egress_policy_sha256s",
    "per_sample_output_token_hard_cap", "total_output_token_hard_cap",
    "per_sample_provider_request_hard_cap", "total_provider_request_hard_cap",
    "max_campaign_elapsed_hours", "monetary_cost_cap",
    "actual_fee_risk_accepted", "stop_on_first_failure", "no_retry",
    "no_transport_retry", "no_fallback", "no_route_switch",
    "no_resume_dispatch", "no_second_dispatch", "no_alternate_destination",
    "no_cross_origin_redirect", "no_replacement_sample",
    "skill_v3_cutover_authorized", "planning_v2_cutover_authorized",
    "full_short_authorized", "authorization_text_sha256",
    "authorization_context_identity_sha256", "permission_scope_sha256",
    "issued_at", "expires_at", "active", "execution_authorized",
    "offline_test_only", "campaign_permission_sha256",
}

_APPROVAL_FIELDS = {
    "schema", "version", "canonicalization_version", "approval_id",
    "created_at", "expires_at", "single_use", "usage_state", "pilot_id",
    "experiment_lock_sha256", "current_execution_head", "expected_branch",
    "worktree_policy", "sample_id", "sample_slot", "pair_id", "arm",
    "sequence_position", "sample_lock_sha256",
    "model_input_component_sha256", "wire_input_sha256",
    "non_skill_identity_sha256", "reference_guidance_sha256",
    "skill_context_sha256", "output_contract_sha256", "provider",
    "provider_descriptor_sha256", "model", "model_binding_sha256",
    "protocol", "route_fingerprint", "destination_origin",
    "destination_hostname", "destination_port", "destination_path",
    "operator_classification", "egress_policy_sha256",
    "sampling_fingerprint", "validator_fingerprint", "output_token_hard_cap",
    "per_sample_logical_model_call_hard_cap",
    "per_sample_provider_request_hard_cap", "per_sample_http_post_hard_cap",
    "per_sample_network_attempt_hard_cap", "retry", "transport_retry",
    "fallback", "route_switch", "resume_dispatch", "second_dispatch",
    "alternate_destination", "cross_origin_redirect",
    "campaign_permission_sha256", "campaign_permission_scope_sha256",
    "campaign_permission_expiry", "nonce_state", "execution_authorized",
    "offline_test_only", "approval_scope", "signed_approval_sha256",
}


class HybridJitApprovalError(RuntimeError):
    """Typed fail-closed error with a bounded hash-only receipt."""

    def __init__(
        self, reason_code: str, *, operation: str = "approval_boundary",
        bindings: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason_code = reason_code
        safe = {
            str(key): str(value)
            for key, value in (bindings or {}).items()
            if key in {"pilot_id", "sample_id", "approval_id", "operation"}
        }
        body = {
            "schema": FAILURE_SCHEMA,
            "version": 1,
            "reason_code": reason_code,
            "operation": operation,
            "binding_sha256": domain_sha256(
                "novel-flywheel-skill-v3-hybrid-failure-binding-v1", safe,
            ),
            "external_action_count": 0,
            "raw_content_included": False,
        }
        self.failure_receipt = {
            **body,
            "failure_receipt_sha256": domain_sha256(FAILURE_DOMAIN, body),
        }
        super().__init__(reason_code)


def _fail(
    reason: str, *, operation: str = "approval_boundary",
    bindings: Mapping[str, Any] | None = None,
) -> None:
    raise HybridJitApprovalError(reason, operation=operation, bindings=bindings)


def _require(
    condition: bool, reason: str, *, operation: str = "approval_boundary",
    bindings: Mapping[str, Any] | None = None,
) -> None:
    if not condition:
        _fail(reason, operation=operation, bindings=bindings)


def _utc(value: Any, reason: str = "APPROVAL_TIME_INVALID") -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), reason)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        _fail(reason)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True,
            text=True, encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        _fail("GIT_STATE_UNAVAILABLE", operation="git_preflight")


def current_git_identity(repo_root: Path, *, require_clean: bool) -> tuple[str, str]:
    repo = repo_root.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    _require(_HEX40.fullmatch(head) is not None, "GIT_STATE_UNAVAILABLE")
    if require_clean:
        _require(
            not _git(repo, "status", "--porcelain=v1", "-uall"),
            "WORKTREE_POLICY_VIOLATION", operation="git_preflight",
        )
    return head, branch


def default_hybrid_approval_store_root() -> Path:
    return default_settings().data_dir / DEFAULT_STORE_RELATIVE


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _outside_store(repo_root: Path, store_root: Path) -> Path:
    repo = repo_root.resolve(strict=True)
    requested = Path(os.path.abspath(store_root))
    _require(
        not _path_is_within(requested, repo), "APPROVAL_STORE_INSIDE_GIT_WORKTREE",
        operation="approval_store",
    )
    requested.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=True)
    _require(
        os.path.normcase(str(resolved)) == os.path.normcase(str(requested)),
        "APPROVAL_STORE_PATH_NOT_EXACT", operation="approval_store",
    )
    for component in (resolved, *resolved.parents):
        attributes = getattr(component.stat(), "st_file_attributes", 0)
        _require(
            not attributes & 0x400, "APPROVAL_STORE_REPARSE_POINT_FORBIDDEN",
            operation="approval_store",
        )
        if component.parent == component:
            break
    return resolved


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_FileLock":
        self.path.touch(exist_ok=True)
        self.handle = self.path.open("r+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.handle.close()
            self.handle = None
            _fail("CONCURRENT_APPROVAL_MUTATION", operation="approval_store")
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        assert self.handle is not None
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def _write_exclusive(path: Path, value: Mapping[str, Any], reason: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _fail(reason, operation="approval_store")
    try:
        os.write(descriptor, canonical_json_bytes(value) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    _write_exclusive(temporary, value, "APPROVAL_STORE_TEMP_COLLISION")
    os.replace(temporary, path)


def _read_json(path: Path, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail(reason, operation="approval_store")
    _require(isinstance(value, dict), reason, operation="approval_store")
    return value


def _store_key(approval_id: str) -> str:
    _require(_ID.fullmatch(approval_id) is not None, "APPROVAL_ID_INVALID")
    return domain_sha256("novel-flywheel-skill-v3-hybrid-approval-key-v1", approval_id)


def _permission_scope_body(permission: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(permission[key]) for key in sorted(_PERMISSION_FIELDS)
        if key not in {"permission_scope_sha256", "campaign_permission_sha256"}
    }


def seal_campaign_permission_v1(body: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a fully explicit permission body; used by a future auth gate or tests."""

    value = deepcopy(dict(body))
    value["permission_scope_sha256"] = domain_sha256(
        "novel-flywheel-skill-v3-hybrid-campaign-permission-scope-v1", value,
    )
    value["campaign_permission_sha256"] = domain_sha256(PERMISSION_DOMAIN, value)
    return value


def campaign_permission_body_from_sealed(
    *, repo_root: Path, permission_id: str, repository_head: str,
    authorization_text_sha256: str,
    authorization_context_identity_sha256: str, issued_at: datetime,
    expires_at: datetime, offline_test_only: bool,
) -> dict[str, Any]:
    """Build the complete permission body using sealed local metadata only."""

    _require(_ID.fullmatch(permission_id) is not None, "CAMPAIGN_PERMISSION_ID_INVALID")
    _require(_HEX40.fullmatch(repository_head) is not None, "STALE_APPROVAL_HEAD")
    _require(_HEX64.fullmatch(authorization_text_sha256) is not None, "AUTHORIZATION_TEXT_SHA256_INVALID")
    _require(_HEX64.fullmatch(authorization_context_identity_sha256) is not None, "AUTHORIZATION_CONTEXT_IDENTITY_SHA256_INVALID")
    sealed = hybrid.load_sealed_pilot(repo_root)
    samples = sealed["samples"]
    route = json.loads(
        (repo_root / hybrid.REPORT_ROOT / "provider-model-route-binding-v1.json")
        .read_text(encoding="utf-8")
    )
    destination = json.loads(
        (repo_root / hybrid.REPORT_ROOT / "destination-binding-v1.json")
        .read_text(encoding="utf-8")
    )
    return {
        "schema": PERMISSION_SCHEMA, "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "permission_id": permission_id,
        "pilot_id": sealed["identity"]["PILOT_ID"],
        "experiment_lock_sha256": sealed["experiment"]["EXPERIMENT_LOCK_SHA256"],
        "repository_head": repository_head, "repository_branch": EXPECTED_BRANCH,
        "worktree_policy": WORKTREE_POLICY,
        "authorized_sequence": list(hybrid.SEQUENCE),
        "authorized_sample_ids": [row["SAMPLE_ID"] for row in samples],
        "authorized_sample_lock_sha256s": [row["SAMPLE_LOCK_SHA256"] for row in samples],
        "provider": route["PROVIDER"],
        "provider_descriptor_sha256": route["PROVIDER_DESCRIPTOR_SHA256"],
        "model": route["MODEL"], "model_binding_sha256": route["MODEL_BINDING_SHA256"],
        "protocol": route["PROTOCOL"], "route_fingerprint": route["ROUTE_FINGERPRINT"],
        "destination_origin": destination["DESTINATION_ORIGIN"],
        "destination_hostname": destination["DESTINATION_HOSTNAME"],
        "destination_port": destination["DESTINATION_PORT"],
        "destination_path": destination["DESTINATION_PATH"],
        "operator_classification": destination["OPERATOR_CLASSIFICATION"],
        "egress_policy_sha256s": [row["EGRESS_POLICY_SHA256"] for row in samples],
        "per_sample_output_token_hard_cap": 4624,
        "total_output_token_hard_cap": 27744,
        "per_sample_provider_request_hard_cap": 1,
        "total_provider_request_hard_cap": 6,
        "max_campaign_elapsed_hours": 10,
        "monetary_cost_cap": "UNKNOWN_NOT_SEALED",
        "actual_fee_risk_accepted": True, "stop_on_first_failure": True,
        "no_retry": True, "no_transport_retry": True, "no_fallback": True,
        "no_route_switch": True, "no_resume_dispatch": True,
        "no_second_dispatch": True, "no_alternate_destination": True,
        "no_cross_origin_redirect": True, "no_replacement_sample": True,
        "skill_v3_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "full_short_authorized": False,
        "authorization_text_sha256": authorization_text_sha256,
        "authorization_context_identity_sha256": authorization_context_identity_sha256,
        "issued_at": utc_text(issued_at), "expires_at": utc_text(expires_at),
        "active": True, "execution_authorized": not offline_test_only,
        "offline_test_only": offline_test_only,
    }


def _validate_destination(value: Mapping[str, Any]) -> None:
    origin = value.get("destination_origin")
    parsed = urlsplit(str(origin))
    _require(
        parsed.scheme == "https" and parsed.hostname == value.get("destination_hostname")
        and parsed.port in {None, int(value.get("destination_port", 0))}
        and not parsed.path and not parsed.query and not parsed.fragment,
        "DESTINATION_DRIFT",
    )
    _require(
        isinstance(value.get("destination_path"), str)
        and str(value["destination_path"]).startswith("/"),
        "DESTINATION_DRIFT",
    )


def validate_campaign_permission_v1(
    permission: Mapping[str, Any], *, repo_root: Path,
    now: datetime | None = None, require_executable: bool,
) -> dict[str, Any]:
    _require(isinstance(permission, Mapping), "CAMPAIGN_PERMISSION_SCHEMA_MISMATCH")
    _require(set(permission) == _PERMISSION_FIELDS, "CAMPAIGN_PERMISSION_FIELDS_UNEXPECTED")
    _require(
        permission.get("schema") == PERMISSION_SCHEMA
        and permission.get("version") == 1,
        "CAMPAIGN_PERMISSION_SCHEMA_MISMATCH",
    )
    _require(
        permission.get("canonicalization_version") == CANONICALIZATION_VERSION,
        "CAMPAIGN_PERMISSION_CANONICALIZATION_UNSUPPORTED",
    )
    scope = dict(permission)
    digest = scope.pop("campaign_permission_sha256")
    _require(digest == domain_sha256(PERMISSION_DOMAIN, scope), "CAMPAIGN_PERMISSION_SHA_MISMATCH")
    declared_scope = scope.pop("permission_scope_sha256")
    _require(
        declared_scope == domain_sha256(
            "novel-flywheel-skill-v3-hybrid-campaign-permission-scope-v1", scope,
        ),
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    sealed = hybrid.load_sealed_pilot(repo_root)
    samples = sealed["samples"]
    head, branch = current_git_identity(
        repo_root, require_clean=require_executable,
    )
    _require(permission.get("pilot_id") == sealed["identity"]["PILOT_ID"], "WRONG_PILOT")
    _require(
        permission.get("experiment_lock_sha256")
        == sealed["experiment"]["EXPERIMENT_LOCK_SHA256"],
        "WRONG_EXPERIMENT_LOCK",
    )
    _require(permission.get("repository_head") == head, "STALE_APPROVAL_HEAD")
    _require(permission.get("repository_branch") == branch == EXPECTED_BRANCH, "STALE_APPROVAL_BRANCH")
    _require(permission.get("worktree_policy") == WORKTREE_POLICY, "WORKTREE_POLICY_VIOLATION")
    _require(tuple(permission.get("authorized_sequence") or ()) == hybrid.SEQUENCE, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(
        tuple(permission.get("authorized_sample_ids") or ())
        == tuple(row["SAMPLE_ID"] for row in samples),
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    _require(
        tuple(permission.get("authorized_sample_lock_sha256s") or ())
        == tuple(row["SAMPLE_LOCK_SHA256"] for row in samples),
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    route = json.loads(
        (repo_root / hybrid.REPORT_ROOT / "provider-model-route-binding-v1.json")
        .read_text(encoding="utf-8")
    )
    destination = json.loads(
        (repo_root / hybrid.REPORT_ROOT / "destination-binding-v1.json")
        .read_text(encoding="utf-8")
    )
    expected = {
        "provider": route["PROVIDER"],
        "provider_descriptor_sha256": route["PROVIDER_DESCRIPTOR_SHA256"],
        "model": route["MODEL"], "model_binding_sha256": route["MODEL_BINDING_SHA256"],
        "protocol": route["PROTOCOL"], "route_fingerprint": route["ROUTE_FINGERPRINT"],
        "destination_origin": destination["DESTINATION_ORIGIN"],
        "destination_hostname": destination["DESTINATION_HOSTNAME"],
        "destination_port": destination["DESTINATION_PORT"],
        "destination_path": destination["DESTINATION_PATH"],
        "operator_classification": destination["OPERATOR_CLASSIFICATION"],
        "egress_policy_sha256s": [row["EGRESS_POLICY_SHA256"] for row in samples],
        "per_sample_output_token_hard_cap": 4624,
        "total_output_token_hard_cap": 27744,
        "per_sample_provider_request_hard_cap": 1,
        "total_provider_request_hard_cap": 6,
        "max_campaign_elapsed_hours": 10,
        "monetary_cost_cap": "UNKNOWN_NOT_SEALED",
    }
    for field, exact in expected.items():
        _require(permission.get(field) == exact, f"{field.upper()}_DRIFT")
    _validate_destination(permission)
    for field in (
        "actual_fee_risk_accepted", "stop_on_first_failure", "no_retry",
        "no_transport_retry", "no_fallback", "no_route_switch",
        "no_resume_dispatch", "no_second_dispatch", "no_alternate_destination",
        "no_cross_origin_redirect", "no_replacement_sample",
    ):
        _require(permission.get(field) is True, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    for field in (
        "skill_v3_cutover_authorized", "planning_v2_cutover_authorized",
        "full_short_authorized",
    ):
        _require(permission.get(field) is False, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    for field in (
        "experiment_lock_sha256", "provider_descriptor_sha256",
        "model_binding_sha256", "route_fingerprint", "authorization_text_sha256",
        "authorization_context_identity_sha256", "permission_scope_sha256",
        "campaign_permission_sha256",
    ):
        _require(_HEX64.fullmatch(str(permission.get(field))) is not None, f"{field.upper()}_INVALID")
    current = now or datetime.now(timezone.utc)
    issued = _utc(permission.get("issued_at"), "CAMPAIGN_PERMISSION_TIME_INVALID")
    expires = _utc(permission.get("expires_at"), "CAMPAIGN_PERMISSION_TIME_INVALID")
    _require(issued <= current <= expires, "CAMPAIGN_PERMISSION_INACTIVE_OR_EXPIRED")
    _require(permission.get("active") is True, "CAMPAIGN_PERMISSION_INACTIVE_OR_EXPIRED")
    if require_executable:
        _require(permission.get("execution_authorized") is True, "CAMPAIGN_PERMISSION_NOT_EXECUTABLE")
        _require(permission.get("offline_test_only") is False, "OFFLINE_APPROVAL_NOT_EXECUTABLE")
    else:
        _require(permission.get("offline_test_only") is True, "TEST_PERMISSION_MUST_BE_OFFLINE_ONLY")
        _require(permission.get("execution_authorized") is False, "TEST_PERMISSION_MUST_BE_NON_EXECUTABLE")
    return deepcopy(dict(permission))


def _next_eligible(
    samples: Sequence[Mapping[str, Any]], completed_sample_ids: Sequence[str],
) -> Mapping[str, Any]:
    expected_ids = [str(row["SAMPLE_ID"]) for row in samples]
    completed = list(completed_sample_ids)
    _require(completed == expected_ids[:len(completed)], "CAMPAIGN_LEDGER_SEQUENCE_INVALID")
    _require(len(completed) < len(expected_ids), "CAMPAIGN_ALREADY_COMPLETE")
    return samples[len(completed)]


def _approval_body(
    *, permission: Mapping[str, Any], lock: Mapping[str, Any], approval_id: str,
    created_at: datetime, expires_at: datetime, offline_test: bool,
) -> dict[str, Any]:
    return {
        "schema": APPROVAL_SCHEMA, "version": APPROVAL_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "approval_id": approval_id, "created_at": utc_text(created_at),
        "expires_at": utc_text(expires_at), "single_use": True,
        "usage_state": "UNUSED", "pilot_id": permission["pilot_id"],
        "experiment_lock_sha256": permission["experiment_lock_sha256"],
        "current_execution_head": permission["repository_head"],
        "expected_branch": permission["repository_branch"],
        "worktree_policy": WORKTREE_POLICY, "sample_id": lock["SAMPLE_ID"],
        "sample_slot": lock["SAMPLE_SLOT"], "pair_id": lock["PAIR_ID"],
        "arm": lock["ARM"], "sequence_position": lock["SEQUENCE_POSITION"],
        "sample_lock_sha256": lock["SAMPLE_LOCK_SHA256"],
        "model_input_component_sha256": lock["MODEL_INPUT_COMPONENT_SHA256"],
        "wire_input_sha256": lock["WIRE_INPUT_SHA256"],
        "non_skill_identity_sha256": lock["NON_SKILL_IDENTITY_SHA256"],
        "reference_guidance_sha256": lock["REFERENCE_GUIDANCE_SHA256"],
        "skill_context_sha256": lock["SKILL_CONTEXT_SHA256"],
        "output_contract_sha256": lock["OUTPUT_CONTRACT_SHA256"],
        "provider": permission["provider"],
        "provider_descriptor_sha256": lock["PROVIDER_DESCRIPTOR_SHA256"],
        "model": permission["model"], "model_binding_sha256": lock["MODEL_BINDING_SHA256"],
        "protocol": permission["protocol"],
        "route_fingerprint": lock["PROVIDER_MODEL_ROUTE_FINGERPRINT"],
        "destination_origin": permission["destination_origin"],
        "destination_hostname": permission["destination_hostname"],
        "destination_port": permission["destination_port"],
        "destination_path": permission["destination_path"],
        "operator_classification": permission["operator_classification"],
        "egress_policy_sha256": lock["EGRESS_POLICY_SHA256"],
        "sampling_fingerprint": lock["SAMPLING_FINGERPRINT"],
        "validator_fingerprint": lock["VALIDATOR_FINGERPRINT"],
        "output_token_hard_cap": lock["OUTPUT_CAP"],
        "per_sample_logical_model_call_hard_cap": 1,
        "per_sample_provider_request_hard_cap": 1,
        "per_sample_http_post_hard_cap": 1,
        "per_sample_network_attempt_hard_cap": 1,
        "retry": False, "transport_retry": False, "fallback": False,
        "route_switch": False, "resume_dispatch": False,
        "second_dispatch": False, "alternate_destination": False,
        "cross_origin_redirect": False,
        "campaign_permission_sha256": permission["campaign_permission_sha256"],
        "campaign_permission_scope_sha256": permission["permission_scope_sha256"],
        "campaign_permission_expiry": permission["expires_at"],
        "nonce_state": "NOT_CREATED", "execution_authorized": not offline_test,
        "offline_test_only": offline_test, "approval_scope": APPROVAL_SCOPE,
    }


def seal_approval_v1(body: Mapping[str, Any]) -> dict[str, Any]:
    _require(set(body) == _APPROVAL_FIELDS - {"signed_approval_sha256"}, "SIGNED_APPROVAL_FIELDS_UNEXPECTED")
    return {
        **deepcopy(dict(body)),
        "signed_approval_sha256": domain_sha256(APPROVAL_DOMAIN, body),
    }


def validate_approval_schema_v1(
    value: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "SIGNED_APPROVAL_SCHEMA_MISMATCH")
    _require(set(value) == _APPROVAL_FIELDS, "SIGNED_APPROVAL_FIELDS_UNEXPECTED")
    _require(
        value.get("schema") == APPROVAL_SCHEMA and value.get("version") == 1,
        "SIGNED_APPROVAL_SCHEMA_MISMATCH",
    )
    _require(value.get("canonicalization_version") == CANONICALIZATION_VERSION, "SIGNED_APPROVAL_CANONICALIZATION_UNSUPPORTED")
    for field in (
        "experiment_lock_sha256", "sample_lock_sha256",
        "model_input_component_sha256", "wire_input_sha256",
        "non_skill_identity_sha256", "reference_guidance_sha256",
        "skill_context_sha256", "output_contract_sha256",
        "provider_descriptor_sha256", "model_binding_sha256",
        "route_fingerprint", "egress_policy_sha256", "sampling_fingerprint",
        "validator_fingerprint", "campaign_permission_sha256",
        "campaign_permission_scope_sha256", "signed_approval_sha256",
    ):
        _require(_HEX64.fullmatch(str(value.get(field))) is not None, f"{field.upper()}_INVALID")
    _require(_HEX40.fullmatch(str(value.get("current_execution_head"))) is not None, "STALE_APPROVAL_HEAD")
    _require(_ID.fullmatch(str(value.get("approval_id"))) is not None, "APPROVAL_ID_INVALID")
    _require(value.get("single_use") is True, "APPROVAL_NOT_SINGLE_USE")
    _require(value.get("usage_state") == "UNUSED", "APPROVAL_REUSE")
    _require(value.get("nonce_state") == "NOT_CREATED", "NONCE_CREATED_DURING_APPROVAL")
    _require(value.get("approval_scope") == APPROVAL_SCOPE, "APPROVAL_SCOPE_MISMATCH")
    _require(value.get("sample_slot") in hybrid.SEQUENCE, "APPROVAL_FOR_WRONG_SAMPLE")
    _require(value.get("arm") in {"CONTROL", "HYBRID"}, "APPROVAL_FOR_WRONG_SAMPLE")
    _require(isinstance(value.get("sequence_position"), int), "APPROVAL_FOR_WRONG_SAMPLE")
    _validate_destination(value)
    for field in (
        "output_token_hard_cap", "per_sample_logical_model_call_hard_cap",
        "per_sample_provider_request_hard_cap", "per_sample_http_post_hard_cap",
        "per_sample_network_attempt_hard_cap",
    ):
        _require(type(value.get(field)) is int and int(value[field]) > 0, "APPROVAL_BUDGET_MISMATCH")
    _require(value.get("output_token_hard_cap") == 4624, "WRONG_OUTPUT_CAP")
    for field in (
        "per_sample_logical_model_call_hard_cap", "per_sample_provider_request_hard_cap",
        "per_sample_http_post_hard_cap", "per_sample_network_attempt_hard_cap",
    ):
        _require(value.get(field) == 1, "APPROVAL_BUDGET_MISMATCH")
    for field in (
        "retry", "transport_retry", "fallback", "route_switch",
        "resume_dispatch", "second_dispatch", "alternate_destination",
        "cross_origin_redirect",
    ):
        _require(value.get(field) is False, "APPROVAL_DISPATCH_POLICY_MISMATCH")
    _require(type(value.get("execution_authorized")) is bool, "SIGNED_APPROVAL_SCHEMA_MISMATCH")
    _require(type(value.get("offline_test_only")) is bool, "SIGNED_APPROVAL_SCHEMA_MISMATCH")
    _require(value.get("execution_authorized") is not value.get("offline_test_only"), "SIGNED_APPROVAL_EXECUTION_MODE_INVALID")
    created = _utc(value.get("created_at"))
    expires = _utc(value.get("expires_at"))
    campaign_expires = _utc(value.get("campaign_permission_expiry"))
    current = now or datetime.now(timezone.utc)
    _require(created <= current <= expires <= campaign_expires, "APPROVAL_EXPIRED")
    body = dict(value)
    digest = body.pop("signed_approval_sha256")
    _require(digest == domain_sha256(APPROVAL_DOMAIN, body), "SIGNED_APPROVAL_SHA256_MISMATCH")
    return deepcopy(dict(value))


def validate_approval_domain_v1(
    value: Mapping[str, Any], *, repo_root: Path,
    permission: Mapping[str, Any], completed_sample_ids: Sequence[str],
    attempt_counters: Mapping[str, Any], nonce_preexists: bool,
    now: datetime | None = None, require_executable: bool,
) -> dict[str, Any]:
    approval = validate_approval_schema_v1(value, now=now)
    exact_permission = validate_campaign_permission_v1(
        permission, repo_root=repo_root, now=now,
        require_executable=require_executable,
    )
    sealed = hybrid.load_sealed_pilot(repo_root)
    lock = _next_eligible(sealed["samples"], completed_sample_ids)
    _require(
        dict(attempt_counters) == ZERO_ATTEMPT_COUNTERS,
        "ATTEMPT_COUNTER_ALREADY_NONZERO",
    )
    _require(nonce_preexists is False, "NONCE_EXISTS_BEFORE_APPROVAL")
    expected = _approval_body(
        permission=exact_permission, lock=lock,
        approval_id=str(approval["approval_id"]),
        created_at=_utc(approval["created_at"]),
        expires_at=_utc(approval["expires_at"]),
        offline_test=not require_executable,
    )
    expected = seal_approval_v1(expected)
    _require(approval == expected, "APPROVAL_DOMAIN_BINDING_MISMATCH")
    return approval


def lifecycle_receipt(
    *, approval: Mapping[str, Any], usage_state: str,
    execution_receipt_sha256: str | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    _require(usage_state in USAGE_STATES, "APPROVAL_USAGE_STATE_INVALID")
    body = {
        "schema": LIFECYCLE_SCHEMA, "version": 1,
        "approval_id": approval["approval_id"],
        "signed_approval_sha256": approval["signed_approval_sha256"],
        "usage_state": usage_state,
        "execution_receipt_sha256": execution_receipt_sha256,
        "reason_code": reason_code,
    }
    return {**body, "lifecycle_sha256": domain_sha256(LIFECYCLE_DOMAIN, body)}


def validate_lifecycle(value: Mapping[str, Any], approval: Mapping[str, Any]) -> dict[str, Any]:
    _require(value.get("schema") == LIFECYCLE_SCHEMA and value.get("version") == 1, "APPROVAL_LIFECYCLE_INVALID")
    _require(value.get("approval_id") == approval.get("approval_id"), "APPROVAL_LIFECYCLE_INVALID")
    _require(value.get("signed_approval_sha256") == approval.get("signed_approval_sha256"), "APPROVAL_LIFECYCLE_INVALID")
    _require(value.get("usage_state") in USAGE_STATES, "APPROVAL_LIFECYCLE_INVALID")
    body = dict(value)
    digest = body.pop("lifecycle_sha256", None)
    _require(digest == domain_sha256(LIFECYCLE_DOMAIN, body), "APPROVAL_LIFECYCLE_SHA_MISMATCH")
    return deepcopy(dict(value))


class DurableHybridApprovalStoreV1:
    """Immutable approval plus atomic mutable lifecycle, outside Git."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.store_root = _outside_store(self.repo_root, store_root)
        self._lock_path = self.store_root / ".hybrid-approval-store.lock"

    def _paths(self, approval_id: str) -> tuple[Path, Path]:
        key = _store_key(approval_id)
        return (
            self.store_root / f"{key}.approval.json",
            self.store_root / f"{key}.state.json",
        )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with _FileLock(self._lock_path):
            yield

    def create(self, approval: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        value = validate_approval_schema_v1(approval, now=now)
        approval_path, state_path = self._paths(str(value["approval_id"]))
        with self._locked():
            _require(not approval_path.exists() and not state_path.exists(), "APPROVAL_ID_ALREADY_EXISTS")
            for existing_path in self.store_root.glob("*.approval.json"):
                existing = _read_json(existing_path, "SIGNED_APPROVAL_STORAGE_INVALID")
                existing_state_path = existing_path.with_name(
                    existing_path.name.replace(".approval.json", ".state.json")
                )
                existing_state = validate_lifecycle(
                    _read_json(existing_state_path, "APPROVAL_LIFECYCLE_INVALID"),
                    existing,
                )
                if (
                    existing.get("pilot_id") == value.get("pilot_id")
                    and existing.get("sample_id") == value.get("sample_id")
                    and existing.get("current_execution_head")
                    == value.get("current_execution_head")
                    and existing_state.get("usage_state") == "UNUSED"
                ):
                    _fail("ACTIVE_APPROVAL_ALREADY_EXISTS", operation="approval_store")
            _write_exclusive(approval_path, value, "APPROVAL_ID_ALREADY_EXISTS")
            try:
                _write_exclusive(
                    state_path,
                    lifecycle_receipt(approval=value, usage_state="UNUSED"),
                    "APPROVAL_ID_ALREADY_EXISTS",
                )
            except BaseException:
                approval_path.unlink(missing_ok=True)
                raise
        return value

    def load(self, approval_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        approval_path, state_path = self._paths(approval_id)
        with self._locked():
            approval = _read_json(approval_path, "SIGNED_APPROVAL_NOT_FOUND")
            validate_approval_schema_v1(
                approval, now=_utc(approval.get("created_at")),
            )
            state = validate_lifecycle(
                _read_json(state_path, "APPROVAL_LIFECYCLE_INVALID"), approval,
            )
            _require(state["usage_state"] == "UNUSED", "APPROVAL_REUSE")
            try:
                validate_approval_schema_v1(approval, now=now)
            except HybridJitApprovalError as exc:
                if exc.reason_code == "APPROVAL_EXPIRED":
                    expired = lifecycle_receipt(
                        approval=approval, usage_state="EXPIRED",
                        reason_code="APPROVAL_EXPIRED",
                    )
                    _atomic_replace(state_path, expired)
                raise
        return {"approval": approval, "lifecycle": state}

    def _terminal(
        self, approval_id: str, *, usage_state: str,
        execution_receipt_sha256: str | None, reason_code: str | None,
    ) -> dict[str, Any]:
        approval_path, state_path = self._paths(approval_id)
        with self._locked():
            approval = _read_json(approval_path, "SIGNED_APPROVAL_NOT_FOUND")
            validate_approval_schema_v1(
                approval, now=_utc(approval.get("created_at")),
            )
            state = validate_lifecycle(
                _read_json(state_path, "APPROVAL_LIFECYCLE_INVALID"), approval,
            )
            _require(state["usage_state"] == "UNUSED", "APPROVAL_REUSE")
            if execution_receipt_sha256 is not None:
                _require(_HEX64.fullmatch(execution_receipt_sha256) is not None, "EXECUTION_RECEIPT_SHA256_INVALID")
            updated = lifecycle_receipt(
                approval=approval, usage_state=usage_state,
                execution_receipt_sha256=execution_receipt_sha256,
                reason_code=reason_code,
            )
            _atomic_replace(state_path, updated)
        return updated

    def consume(self, approval_id: str, *, execution_receipt_sha256: str) -> dict[str, Any]:
        return self._terminal(
            approval_id, usage_state="CONSUMED",
            execution_receipt_sha256=execution_receipt_sha256,
            reason_code=None,
        )

    def invalidate(self, approval_id: str, *, reason_code: str) -> dict[str, Any]:
        return self._terminal(
            approval_id, usage_state="INVALID",
            execution_receipt_sha256=None, reason_code=reason_code,
        )


def create_one_hybrid_sample_jit_approval(
    *, repo_root: Path, store: DurableHybridApprovalStoreV1,
    permission: Mapping[str, Any], sample_id: str,
    completed_sample_ids: Sequence[str], approval_id: str,
    attempt_counters: Mapping[str, Any], nonce_preexists: bool,
    now: datetime, expires_at: datetime, offline_test: bool,
) -> dict[str, Any]:
    """Create exactly one approval for the current next-eligible sample."""

    exact_permission = validate_campaign_permission_v1(
        permission, repo_root=repo_root, now=now,
        require_executable=not offline_test,
    )
    sealed = hybrid.load_sealed_pilot(repo_root)
    lock = _next_eligible(sealed["samples"], completed_sample_ids)
    _require(lock["SAMPLE_ID"] == sample_id, "LATER_SAMPLE_APPROVAL_PRECREATION_FORBIDDEN")
    _require(now <= expires_at <= _utc(permission["expires_at"]), "APPROVAL_TIME_INVALID")
    approval = seal_approval_v1(_approval_body(
        permission=exact_permission, lock=lock, approval_id=approval_id,
        created_at=now, expires_at=expires_at, offline_test=offline_test,
    ))
    validate_approval_domain_v1(
        approval, repo_root=repo_root, permission=permission,
        completed_sample_ids=completed_sample_ids,
        attempt_counters=attempt_counters, nonce_preexists=nonce_preexists,
        now=now,
        require_executable=not offline_test,
    )
    store.create(approval, now=now)
    return approval


def project_verified_approval_for_legacy_launch(
    approval: Mapping[str, Any], *, offline_test: bool,
) -> dict[str, Any]:
    """Project an already verified approval into the sealed legacy launcher shape."""

    validate_approval_schema_v1(approval)
    return {
        "schema": "HybridVerifiedExecutableApprovalProjectionV1",
        "non_executable": offline_test,
        "approval_id": approval["approval_id"], "pilot_id": approval["pilot_id"],
        "sample_id": approval["sample_id"],
        "sample_lock_sha256": approval["sample_lock_sha256"],
        "experiment_lock_sha256": approval["experiment_lock_sha256"],
        "model_input_component_binding_sha256": approval["model_input_component_sha256"],
        "route_fingerprint": approval["route_fingerprint"],
        "destination_origin": approval["destination_origin"],
        "egress_policy_sha256": approval["egress_policy_sha256"],
        "wire_input_sha256": approval["wire_input_sha256"],
        "nonce_policy_version": hybrid.NONCE_POLICY_VERSION,
        "real_dispatcher_version": hybrid.REAL_DISPATCHER_VERSION,
        "nonce_state": "NOT_CREATED",
        "signed_approval_sha256": approval["signed_approval_sha256"],
        "repository_head": approval["current_execution_head"],
        "usage_status": "unused", "expired": False,
    }
