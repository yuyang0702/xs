"""Fail-closed one-shot control plane for an authorized Full Short run.

The ordinary application does not enable this boundary.  A dedicated Full
Short launcher must supply an exact, externally materialized authorization,
then create one JIT approval and one durable nonce.  The ledger is written
before the lowest HTTP transport seam so a restart can never guess that an
ambiguous provider request is safe to repeat.

The public ledger persists only hashes, route/destination identities,
counters, and typed states.  When the prospective response-capture contract
is enabled, exact Provider response bytes are stored separately in the same
worktree-external private store; credentials, request headers, request prompts,
and tool arguments remain excluded from public receipts and Git.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit

from novel_flywheel.domain.models import ModelRequest
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureStoreV1,
)


POLICY_SCHEMA = "FullShortExecutionPolicyV1"
PERMISSION_SCHEMA = "FullShortExecutionPermissionV1"
APPROVAL_SCHEMA = "FullShortJitSignedApprovalV1"
NONCE_SCHEMA = "FullShortDurableNonceV1"
LEDGER_SCHEMA = "FullShortDispatchLedgerV1"
COMPLETION_SCHEMA = "FullShortCompletionReceiptV1"
AUTHORIZATION_SCHEMA = "FullShortCanonicalAuthorizationV1"
PREFLIGHT_SCHEMA = "FullShortAuthorizationPreflightReceiptV1"
POLICY_VERSION = "full-short-trustworthy-execution-v1"
SHORT_COMPLETION_GOAL = "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
REQUIRED_FINAL_BINDING_KEYS = frozenset({
    "manuscript_sha256",
    "chapter_sha256",
    "canon_sha256",
    "story_state_sha256",
    "quality_checkpoint_sha256",
    "terminal_verification_sha256",
})
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_FULL_SHORT_EGRESS_ALLOWED = (
    "system_context", "task_contract", "authority", "story_slice",
    "current_baseline_skill_context", "output_contract",
    "provider_request_metadata",
)
_FULL_SHORT_EGRESS_FORBIDDEN = (
    "credentials", "unrelated_project_data", "raw_provider_evidence",
    "retired_skill_v3_hybrid_context",
)
RESPONSE_CAPTURE_POLICY_V1 = {
    "schema": "FullShortProviderResponseCapturePolicyV1",
    "version": 1,
    "required_byte_domains": [
        PROVIDER_PROTOCOL_INPUT_BYTES,
        CONTRACT_RUNTIME_INPUT_BYTES,
    ],
    "storage": "WORKTREE_EXTERNAL_EXCLUSIVE_CREATE_CRASH_SAFE",
    "capture_before_lossy_conversion": True,
    "failed_conversion_capture_retained": True,
    "exact_replay_required": True,
    "credentials_or_request_secrets_persisted": False,
    "restart_network_redispatch_allowed": False,
}
RESPONSE_CAPTURE_POLICY_SHA256 = hashlib.sha256(
    canonical_json_bytes(RESPONSE_CAPTURE_POLICY_V1),
).hexdigest()
_CLOSED_LOCAL_ATTEMPT_STATES = frozenset({
    "LOCAL_STAGE_COMPLETE", "LOCAL_ATTEMPT_REJECTED",
})
_LOCAL_REJECTION_RECEIPT_FIELDS = frozenset({
    "schema", "version", "contract_name", "contract_version",
    "contract_schema_sha256", "attempt_index", "route", "route_attempt",
    "failure_kind", "failure_reason_sha256", "response_text_sha256",
    "conversion_audit_sha256", "raw_content_persisted",
})
_FINAL_ARTIFACT_REJECTION_RECEIPT_FIELDS = frozenset({
    "schema", "version", "contract_name", "contract_version",
    "contract_schema_sha256", "attempt_index", "route", "route_attempt",
    "failure_kind", "failure_code", "failure_reason_sha256",
    "provider_output_shape_sha256", "contract_runtime_input_present",
    "raw_content_persisted",
})


class FullShortExecutionBoundaryError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FullShortExecutionBoundaryError(reason)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _expected_provider_payload_v1(
    protocol: str, request: ModelRequest, *, destination: str,
) -> dict[str, Any]:
    """Project one typed model request into the exact adapter wire payload."""

    if protocol == "anthropic":
        system = "\n\n".join(
            message.content for message in request.messages
            if message.role == "system"
        )
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                message.model_dump() for message in request.messages
                if message.role != "system"
            ],
            "max_tokens": request.max_output_tokens or 8192,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_schema is not None:
            schema = request.response_schema.get(
                "schema", request.response_schema,
            )
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": schema},
            }
        if request.tools:
            payload["tools"] = [{
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            } for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "tool", "name": request.required_tool,
            }
        payload["stream"] = True
        return payload
    if protocol == "openai-chat":
        payload = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": request.response_schema,
            }
        elif request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }} for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": request.required_tool},
            }
        if urlsplit(destination).hostname == "api.moonshot.cn" and (
            request.required_tool
            or request.response_schema
            or request.response_format
        ):
            payload["thinking"] = {"type": "disabled"}
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload
    if protocol == "openai-responses":
        payload = {
            "model": request.model,
            "input": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["text"] = {
                "format": {"type": "json_schema", **request.response_schema},
            }
        elif request.response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        if request.tools:
            payload["tools"] = [{
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            } for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function", "name": request.required_tool,
            }
        payload["stream"] = True
        return payload
    raise FullShortExecutionBoundaryError("EGRESS_PROTOCOL_NOT_AUTHORIZED")


def _seal(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {**deepcopy(dict(body)), field: domain_sha256(domain, body)}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class _ExclusiveFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_ExclusiveFileLock":
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
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_STORE_CONCURRENT_ACCESS",
            ) from exc
        return self

    def __exit__(self, *_args: object) -> None:
        assert self.handle is not None
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


@dataclass(frozen=True)
class FullShortExecutionPolicyV1:
    execution_head: str
    branch: str
    run_id: str
    project_id_sha256: str
    workload_sha256: str
    runtime_authority_sha256: str
    style_reference_authority_sha256: str
    route_manifest_sha256: str
    destination_manifest_sha256: str
    egress_policy_sha256: str
    store_root_sha256: str
    required_stage_roles: tuple[str, ...]
    expected_stage_calls: int
    hard_max_provider_requests: int
    hard_max_http_posts: int
    hard_max_network_attempts: int
    per_call_output_token_hard_cap: int
    total_output_token_hard_cap: int
    maximum_elapsed_seconds: int
    response_capture_policy_sha256: str = RESPONSE_CAPTURE_POLICY_SHA256
    monetary_cost_cap_state: str = "UNKNOWN_NOT_SEALED"

    def document(self) -> dict[str, Any]:
        body = {
            "schema": POLICY_SCHEMA,
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "policy_version": POLICY_VERSION,
            "execution_head": self.execution_head,
            "branch": self.branch,
            "run_id": self.run_id,
            "project_id_sha256": self.project_id_sha256,
            "workload_sha256": self.workload_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "style_reference_authority_sha256": (
                self.style_reference_authority_sha256
            ),
            "route_manifest_sha256": self.route_manifest_sha256,
            "destination_manifest_sha256": self.destination_manifest_sha256,
            "egress_policy_sha256": self.egress_policy_sha256,
            "response_capture_policy_sha256": (
                self.response_capture_policy_sha256
            ),
            "store_root_sha256": self.store_root_sha256,
            "required_stage_roles": list(self.required_stage_roles),
            "expected_stage_calls": self.expected_stage_calls,
            "hard_max_provider_requests": self.hard_max_provider_requests,
            "hard_max_http_posts": self.hard_max_http_posts,
            "hard_max_network_attempts": self.hard_max_network_attempts,
            "per_call_output_token_hard_cap": (
                self.per_call_output_token_hard_cap
            ),
            "total_output_token_hard_cap": self.total_output_token_hard_cap,
            "maximum_elapsed_seconds": self.maximum_elapsed_seconds,
            "monetary_cost_cap_state": self.monetary_cost_cap_state,
            "single_use": True,
            "retry_policy": "existing_workflow_bounds_only",
            "transport_retry_allowed": False,
            "ambiguous_dispatch_restart_policy": "FAIL_CLOSED_NO_REDISPATCH",
            "restart_policy": "FAIL_CLOSED_NO_RESUME_OR_REDISPATCH",
            "skill_v3_production_cutover": False,
            "planning_v2_production_cutover": False,
            "full_short_count": 1,
            "long_execution_allowed": False,
        }
        validate_policy_v1(body)
        return _seal(
            "novel-flywheel-full-short-execution-policy-v1",
            body, "policy_sha256",
        )


def render_full_short_canonical_authorization_v1(
    *, policy: Mapping[str, Any], public_bindings: Mapping[str, Any],
) -> bytes:
    """Render the only byte representation accepted by the real preflight.

    This is intentionally an authorization *template*.  Creating these bytes
    never activates external actions; a fresh user message must explicitly
    activate the exact SHA-256 after the final execution HEAD is frozen.
    """

    validated = validate_policy_v1(policy)
    _require(
        isinstance(public_bindings, Mapping) and bool(public_bindings),
        "AUTHORIZATION_BINDINGS_INVALID",
    )
    _require(
        public_bindings.get("store_root_sha256")
        == validated["store_root_sha256"],
        "AUTHORIZATION_STORE_ROOT_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("routes"))
        == validated["route_manifest_sha256"],
        "AUTHORIZATION_ROUTE_MANIFEST_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("destinations"))
        == validated["destination_manifest_sha256"],
        "AUTHORIZATION_DESTINATION_MANIFEST_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("egress_policy"))
        == validated["egress_policy_sha256"],
        "AUTHORIZATION_EGRESS_POLICY_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("response_capture_policy"))
        == validated["response_capture_policy_sha256"],
        "AUTHORIZATION_RESPONSE_CAPTURE_POLICY_MISMATCH",
    )
    body = {
        "schema": AUTHORIZATION_SCHEMA,
        "version": 1,
        "activation_rule": (
            "TEMPLATE_ONLY_UNTIL_FRESH_USER_ACTIVATES_EXACT_UTF8_BYTES"
        ),
        "authorization_scope": "ONE_TRUSTWORTHY_FULL_SHORT_ONLY",
        "policy": validated,
        "public_bindings": deepcopy(dict(public_bindings)),
        "fresh_jit_approval_required": True,
        "durable_single_use_nonce_required": True,
        "later_approval_or_nonce_precreation_allowed": False,
        "long_execution_allowed": False,
        "skill_v3_production_cutover": False,
        "planning_v2_production_cutover": False,
        "actual_fee_risk_acceptance_required": (
            validated["monetary_cost_cap_state"] == "UNKNOWN_NOT_SEALED"
        ),
        "stop_on_first_blocked_invalid_drifted_failed_privacy_or_budget_state": True,
    }
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ).encode("utf-8") + b"\n"


def validate_full_short_canonical_authorization_v1(
    raw: bytes, *, policy: Mapping[str, Any],
    public_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    expected = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public_bindings,
    )
    _require(raw == expected, "AUTHORIZATION_CANONICAL_BYTES_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise FullShortExecutionBoundaryError(
            "AUTHORIZATION_UTF8_OR_JSON_INVALID",
        ) from exc
    _require(isinstance(value, dict), "AUTHORIZATION_UTF8_OR_JSON_INVALID")
    value["authorization_text_sha256"] = hashlib.sha256(raw).hexdigest()
    return value


def validate_full_short_preflight_v1(
    *, policy: Mapping[str, Any], actual: Mapping[str, Any],
    authorization_text_sha256: str, external_actions_enabled: bool,
) -> dict[str, Any]:
    """Validate every immutable binding before approval, nonce or credentials."""

    validated = validate_policy_v1(policy)
    _require(
        _HEX64.fullmatch(authorization_text_sha256) is not None,
        "AUTHORIZATION_SHA256_INVALID",
    )
    required_equal = {
        "head": validated["execution_head"],
        "branch": validated["branch"],
        "run_id": validated["run_id"],
        "project_id_sha256": validated["project_id_sha256"],
        "workload_sha256": validated["workload_sha256"],
        "runtime_authority_sha256": validated["runtime_authority_sha256"],
        "style_reference_authority_sha256": (
            validated["style_reference_authority_sha256"]
        ),
        "route_manifest_sha256": validated["route_manifest_sha256"],
        "destination_manifest_sha256": validated[
            "destination_manifest_sha256"
        ],
        "egress_policy_sha256": validated["egress_policy_sha256"],
        "response_capture_policy_sha256": validated[
            "response_capture_policy_sha256"
        ],
        "store_root_sha256": validated["store_root_sha256"],
    }
    for field, expected in required_equal.items():
        _require(actual.get(field) == expected, f"{field.upper()}_DRIFT")
    _require(actual.get("worktree_clean") is True, "WORKTREE_DRIFT")
    _require(
        actual.get("skill_v3_production_cutover") is False,
        "SKILL_V3_CUTOVER_DRIFT",
    )
    _require(
        actual.get("planning_v2_production_cutover") is False,
        "PLANNING_V2_CUTOVER_DRIFT",
    )
    counters = dict(actual.get("external_action_counters") or {})
    for field in (
        "credential_lookup", "provider_client_creation", "provider_request",
        "http_post", "network", "model", "paid",
    ):
        _require(counters.get(field) == 0, "PREFLIGHT_EXTERNAL_ACTION_OCCURRED")
    body = {
        "schema": PREFLIGHT_SCHEMA,
        "version": 1,
        "policy_sha256": validated["policy_sha256"],
        "authorization_text_sha256": authorization_text_sha256,
        "binding_status": "exact",
        "external_actions_enabled": bool(external_actions_enabled),
        "external_action_counters": counters,
        "approval_state": "NOT_CREATED",
        "nonce_state": "NOT_CREATED",
        "credential_state": "NOT_ACCESSED",
        "provider_client_state": "NOT_CREATED",
        "network_state": "NOT_ACCESSED",
        "created_at": _now(),
    }
    return _seal(
        "novel-flywheel-full-short-authorization-preflight-v1", body,
        "preflight_receipt_sha256",
    )


def validate_policy_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(value)
    digest = body.pop("policy_sha256", None)
    _require(body.get("schema") == POLICY_SCHEMA, "POLICY_SCHEMA_MISMATCH")
    _require(body.get("version") == 1, "POLICY_SCHEMA_MISMATCH")
    _require(body.get("policy_version") == POLICY_VERSION, "POLICY_VERSION_MISMATCH")
    _require(_HEX40.fullmatch(str(body.get("execution_head"))) is not None, "HEAD_INVALID")
    _require(_ID.fullmatch(str(body.get("run_id"))) is not None, "RUN_ID_INVALID")
    for field in (
        "project_id_sha256", "workload_sha256", "runtime_authority_sha256",
        "style_reference_authority_sha256", "route_manifest_sha256",
        "destination_manifest_sha256", "egress_policy_sha256",
        "response_capture_policy_sha256",
        "store_root_sha256",
    ):
        _require(_HEX64.fullmatch(str(body.get(field))) is not None, f"{field.upper()}_INVALID")
    _require(
        body["response_capture_policy_sha256"]
        == RESPONSE_CAPTURE_POLICY_SHA256,
        "RESPONSE_CAPTURE_POLICY_NOT_ENFORCED",
    )
    for field in (
        "expected_stage_calls", "hard_max_provider_requests",
        "hard_max_http_posts", "hard_max_network_attempts",
        "per_call_output_token_hard_cap",
        "total_output_token_hard_cap", "maximum_elapsed_seconds",
    ):
        _require(type(body.get(field)) is int and int(body[field]) > 0, "CAPS_INVALID")
    _require(
        body["expected_stage_calls"] <= body["hard_max_provider_requests"]
        == body["hard_max_http_posts"] == body["hard_max_network_attempts"],
        "CAPS_INVALID",
    )
    _require(body.get("single_use") is True, "POLICY_NOT_SINGLE_USE")
    _require(body.get("transport_retry_allowed") is False, "TRANSPORT_RETRY_ENABLED")
    _require(body.get("full_short_count") == 1, "FULL_SHORT_COUNT_INVALID")
    roles = body.get("required_stage_roles")
    _require(
        isinstance(roles, list) and bool(roles)
        and all(isinstance(role, str) and _ID.fullmatch(role) for role in roles)
        and len(roles) == len(set(roles)),
        "REQUIRED_STAGE_ROLES_INVALID",
    )
    _require(
        body.get("restart_policy") == "FAIL_CLOSED_NO_RESUME_OR_REDISPATCH",
        "RESTART_POLICY_NOT_FAIL_CLOSED",
    )
    if digest is not None:
        _require(
            digest == domain_sha256(
                "novel-flywheel-full-short-execution-policy-v1", body,
            ),
            "POLICY_SHA256_MISMATCH",
        )
        body["policy_sha256"] = digest
    return body


class FullShortDurableExecutionStoreV1:
    """External, exclusive, hash-only permission/approval/nonce/dispatch store."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        requested = Path(os.path.abspath(store_root))
        _require(not _inside(requested, self.repo_root), "STORE_INSIDE_GIT_WORKTREE")
        requested.mkdir(parents=True, exist_ok=True)
        self.root = requested.resolve(strict=True)
        _require(
            os.path.normcase(str(self.root)) == os.path.normcase(str(requested)),
            "STORE_PATH_NOT_EXACT",
        )
        self.lock_path = self.root / ".full-short-execution.lock"
        self.store_root_sha256 = hashlib.sha256(
            str(self.root).encode("utf-8"),
        ).hexdigest()

    def _verify_store_binding(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_policy_v1(policy)
        _require(
            validated["store_root_sha256"] == self.store_root_sha256,
            "STORE_ROOT_POLICY_MISMATCH",
        )
        return validated

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with _ExclusiveFileLock(self.lock_path):
            yield

    @staticmethod
    def _exclusive_write(path: Path, value: Mapping[str, Any]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise FullShortExecutionBoundaryError("SINGLE_USE_REPLAY") from exc
        try:
            os.write(descriptor, canonical_json_bytes(value) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _replace(cls, path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        cls._exclusive_write(temporary, value)
        os.replace(temporary, path)

    def _key(self, execution_id: str) -> str:
        _require(_ID.fullmatch(execution_id) is not None, "EXECUTION_ID_INVALID")
        return domain_sha256("full-short-execution-storage-key-v1", execution_id)

    def _path(self, execution_id: str, kind: str) -> Path:
        return self.root / f"{self._key(execution_id)}.{kind}.json"

    def _read(self, execution_id: str, kind: str) -> dict[str, Any]:
        try:
            value = json.loads(
                self._path(execution_id, kind).read_text(encoding="utf-8"),
            )
        except (OSError, ValueError) as exc:
            raise FullShortExecutionBoundaryError(
                f"{kind.upper()}_NOT_FOUND_OR_CORRUPT",
            ) from exc
        _require(isinstance(value, dict), f"{kind.upper()}_NOT_FOUND_OR_CORRUPT")
        return value

    def create_permission(
        self, *, execution_id: str, authorization_text_sha256: str,
        policy: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        validated = self._verify_store_binding(policy)
        _require(
            _HEX64.fullmatch(authorization_text_sha256) is not None,
            "AUTHORIZATION_SHA256_INVALID",
        )
        body = {
            "schema": PERMISSION_SCHEMA, "version": 1,
            "execution_id": execution_id,
            "authorization_text_sha256": authorization_text_sha256,
            "policy_sha256": validated["policy_sha256"],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "state": "ACTIVE", "created_at": _now(), "single_use": True,
        }
        value = _seal(
            "novel-flywheel-full-short-permission-v1", body,
            "permission_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "permission"), value)
        return value

    def create_jit_approval(
        self, *, execution_id: str, policy: Mapping[str, Any],
        permission: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        validated = self._verify_store_binding(policy)
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(
            permission.get("policy_sha256") == validated["policy_sha256"],
            "APPROVAL_POLICY_MISMATCH",
        )
        body = {
            "schema": APPROVAL_SCHEMA, "version": 1,
            "approval_id": f"fsa-{secrets.token_hex(16)}",
            "execution_id": execution_id,
            "permission_sha256": permission["permission_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "nonce_state": "NOT_CREATED", "state": "SIGNED",
            "created_at": _now(), "single_use": True,
        }
        value = _seal(
            "novel-flywheel-full-short-jit-approval-v1", body,
            "signed_approval_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "approval"), value)
        return value

    def reserve_nonce(
        self, *, execution_id: str, policy: Mapping[str, Any],
        approval: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        validated = self._verify_store_binding(policy)
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        _require(
            approval.get("policy_sha256") == validated["policy_sha256"],
            "NONCE_POLICY_MISMATCH",
        )
        reservation_body = {
            "schema": NONCE_SCHEMA, "version": 1,
            "nonce_id": f"fsn-{secrets.token_hex(16)}",
            "execution_id": execution_id,
            "signed_approval_sha256": approval["signed_approval_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "created_at": _now(), "single_use": True,
        }
        reservation = _seal(
            "novel-flywheel-full-short-nonce-v1", reservation_body,
            "nonce_sha256",
        )
        value = _seal(
            "novel-flywheel-full-short-nonce-record-v1",
            {
                **reservation,
                "state": "RESERVED",
                "dispatch_attempt_count": 0,
                "consumed_at": None,
                "consumed_session_sha256": None,
                "observer_session_sha256": None,
            },
            "nonce_record_sha256",
        )
        ledger_body = {
            "schema": LEDGER_SCHEMA, "version": 1,
            "execution_id": execution_id,
            "nonce_sha256": reservation["nonce_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "store_root_sha256": self.store_root_sha256,
            "state": "READY", "attempts": [], "completed_stage_receipts": [],
            "created_at": _now(), "updated_at": _now(),
        }
        ledger = _seal(
            "novel-flywheel-full-short-dispatch-ledger-v1", ledger_body,
            "ledger_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "nonce"), value)
            self._exclusive_write(self._path(execution_id, "ledger"), ledger)
        return value

    def load_ledger(self, execution_id: str) -> dict[str, Any]:
        return self._read(execution_id, "ledger")

    @staticmethod
    def _verify_seal(
        value: Mapping[str, Any], *, domain: str, field: str, reason: str,
    ) -> dict[str, Any]:
        body = dict(value)
        digest = body.pop(field, None)
        _require(
            isinstance(digest, str) and digest == domain_sha256(domain, body),
            reason,
        )
        body[field] = digest
        return body

    def verify_ready_chain(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool,
    ) -> dict[str, dict[str, Any]]:
        """Re-read the complete durable authority chain before dispatch."""

        validated = self._verify_store_binding(policy)
        permission = self._verify_seal(
            self._read(execution_id, "permission"),
            domain="novel-flywheel-full-short-permission-v1",
            field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
        )
        approval = self._verify_seal(
            self._read(execution_id, "approval"),
            domain="novel-flywheel-full-short-jit-approval-v1",
            field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
        )
        nonce = self._verify_seal(
            self._read(execution_id, "nonce"),
            domain="novel-flywheel-full-short-nonce-record-v1",
            field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
        )
        nonce_identity = self._verify_seal(
            {key: value for key, value in nonce.items() if key not in {
                "state", "dispatch_attempt_count", "consumed_at",
                "consumed_session_sha256", "observer_session_sha256",
                "nonce_record_sha256",
            }},
            domain="novel-flywheel-full-short-nonce-v1",
            field="nonce_sha256", reason="NONCE_SHA256_MISMATCH",
        )
        ledger = self._verify_seal(
            self._read(execution_id, "ledger"),
            domain="novel-flywheel-full-short-dispatch-ledger-v1",
            field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
        )
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        if nonce.get("state") == "CONSUMED":
            raise FullShortExecutionBoundaryError(
                "NONCE_ALREADY_CONSUMED_NO_RESTART",
            )
        _require(nonce.get("state") == "RESERVED", "NONCE_NOT_RESERVED")
        for value in (permission, approval, nonce, ledger):
            _require(
                value.get("execution_id") == execution_id,
                "EXECUTION_CHAIN_ID_MISMATCH",
            )
            _require(
                value.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            _require(
                value.get("store_root_sha256") == self.store_root_sha256,
                "EXECUTION_CHAIN_STORE_ROOT_MISMATCH",
            )
        _require(
            approval.get("permission_sha256") == permission["permission_sha256"],
            "APPROVAL_PERMISSION_MISMATCH",
        )
        _require(
            nonce.get("signed_approval_sha256")
            == approval["signed_approval_sha256"],
            "NONCE_APPROVAL_MISMATCH",
        )
        _require(
            ledger.get("nonce_sha256") == nonce_identity["nonce_sha256"],
            "LEDGER_NONCE_MISMATCH",
        )
        for value in (permission, approval, nonce):
            _require(
                value.get("external_actions_enabled")
                is external_actions_enabled,
                "EXTERNAL_ACTION_AUTHORITY_MISMATCH",
            )
        return {
            "permission": permission, "approval": approval,
            "nonce": nonce, "ledger": ledger,
        }

    def claim_observer_session(
        self, *, execution_id: str, policy: Mapping[str, Any], session_id: str,
    ) -> None:
        """Claim the reserved execution once; construction is not resumable."""

        validated = self._verify_store_binding(policy)
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            _require(nonce.get("state") == "RESERVED", "NONCE_NOT_RESERVED")
            _require(
                nonce.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            _require(
                nonce.get("observer_session_sha256") is None,
                "OBSERVER_ALREADY_CLAIMED_NO_RESTART",
            )
            body = dict(nonce)
            body.pop("nonce_record_sha256", None)
            body["observer_session_sha256"] = session_sha256
            self._replace(
                self._path(execution_id, "nonce"),
                _seal(
                    "novel-flywheel-full-short-nonce-record-v1", body,
                    "nonce_record_sha256",
                ),
            )

    def consume_nonce_and_record_dispatch(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool, session_id: str,
        attempt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Permanently consume once, then record before outbound HTTP.

        The nonce file is replaced first while holding the exclusive lock. If
        the process stops before the ledger replacement, the durable consumed
        nonce still makes every restart fail closed.
        """

        validated = self._verify_store_binding(policy)
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            _require(
                not self._path(execution_id, "completion").exists(),
                "EXECUTION_ALREADY_COMPLETED",
            )
            permission = self._verify_seal(
                self._read(execution_id, "permission"),
                domain="novel-flywheel-full-short-permission-v1",
                field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
            )
            approval = self._verify_seal(
                self._read(execution_id, "approval"),
                domain="novel-flywheel-full-short-jit-approval-v1",
                field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
            )
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            attempts = list(ledger.get("attempts") or [])
            for value in (permission, approval, nonce, ledger):
                _require(
                    value.get("execution_id") == execution_id
                    and value.get("policy_sha256") == validated["policy_sha256"]
                    and value.get("store_root_sha256") == self.store_root_sha256,
                    "EXECUTION_CHAIN_MISMATCH",
                )
            _require(
                permission.get("state") == "ACTIVE"
                and approval.get("state") == "SIGNED"
                and approval.get("permission_sha256")
                == permission.get("permission_sha256")
                and nonce.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and ledger.get("nonce_sha256") == nonce.get("nonce_sha256"),
                "EXECUTION_CHAIN_LINK_MISMATCH",
            )
            for value in (permission, approval, nonce):
                _require(
                    value.get("external_actions_enabled")
                    is external_actions_enabled,
                    "EXTERNAL_ACTION_AUTHORITY_MISMATCH",
                )
            _require(
                attempt.get("ordinal") == len(attempts) + 1,
                "DUPLICATE_OR_RACING_DISPATCH",
            )
            _require(
                len(attempts) < validated["hard_max_provider_requests"],
                "PROVIDER_REQUEST_CAP_EXHAUSTED",
            )
            if attempts:
                _require(
                    attempts[-1].get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                    and attempts[-1].get("session_id") == session_id,
                    "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART",
                )
            requested_tokens = int(attempt.get("requested_output_tokens") or 0)
            _require(
                0 < requested_tokens
                <= validated["per_call_output_token_hard_cap"],
                "PER_CALL_OUTPUT_TOKEN_CAP_EXHAUSTED",
            )
            _require(
                sum(int(item.get("requested_output_tokens") or 0)
                    for item in attempts) + requested_tokens
                <= validated["total_output_token_hard_cap"],
                "TOTAL_OUTPUT_TOKEN_CAP_EXHAUSTED",
            )
            if not attempts:
                _require(nonce.get("state") == "RESERVED", "NONCE_NOT_RESERVED")
                _require(
                    nonce.get("observer_session_sha256") == session_sha256,
                    "OBSERVER_SESSION_MISMATCH",
                )
                consumed_body = dict(nonce)
                consumed_body.pop("nonce_record_sha256", None)
                consumed_body.update({
                    "state": "CONSUMED",
                    "dispatch_attempt_count": 1,
                    "consumed_at": _now(),
                    "consumed_session_sha256": session_sha256,
                })
                self._replace(
                    self._path(execution_id, "nonce"),
                    _seal(
                        "novel-flywheel-full-short-nonce-record-v1",
                        consumed_body, "nonce_record_sha256",
                    ),
                )
            else:
                _require(nonce.get("state") == "CONSUMED", "NONCE_NOT_CONSUMED")
                _require(
                    nonce.get("consumed_session_sha256") == session_sha256,
                    "NONCE_ALREADY_CONSUMED_NO_RESTART",
                )
                nonce_body = dict(nonce)
                nonce_body.pop("nonce_record_sha256", None)
                nonce_body["dispatch_attempt_count"] = len(attempts) + 1
                self._replace(
                    self._path(execution_id, "nonce"),
                    _seal(
                        "novel-flywheel-full-short-nonce-record-v1",
                        nonce_body, "nonce_record_sha256",
                    ),
                )
            _require(
                ledger.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            attempts.append(deepcopy(dict(attempt)))
            ledger_body = dict(ledger)
            ledger_body.pop("ledger_sha256", None)
            ledger_body["attempts"] = attempts
            ledger_body["total_requested_output_tokens"] = sum(
                int(item["requested_output_tokens"]) for item in attempts
            )
            ledger_body["state"] = "DISPATCH_IN_FLIGHT"
            ledger_body["updated_at"] = _now()
            sealed = _seal(
                "novel-flywheel-full-short-dispatch-ledger-v1",
                ledger_body, "ledger_sha256",
            )
            self._replace(self._path(execution_id, "ledger"), sealed)
            return sealed

    def update_ledger(
        self, execution_id: str, mutator: Any,
    ) -> dict[str, Any]:
        with self._locked():
            _require(
                not self._path(execution_id, "completion").exists(),
                "EXECUTION_ALREADY_COMPLETED",
            )
            current = self._read(execution_id, "ledger")
            body = dict(current)
            digest = body.pop("ledger_sha256", None)
            _require(
                digest == domain_sha256(
                    "novel-flywheel-full-short-dispatch-ledger-v1", body,
                ),
                "LEDGER_SHA256_MISMATCH",
            )
            changed = mutator(deepcopy(body))
            _require(isinstance(changed, dict), "LEDGER_MUTATION_INVALID")
            changed["updated_at"] = _now()
            value = _seal(
                "novel-flywheel-full-short-dispatch-ledger-v1", changed,
                "ledger_sha256",
            )
            self._replace(self._path(execution_id, "ledger"), value)
            return value

    def commit_completion(
        self, *, execution_id: str, policy: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Durably close the single-use execution before returning success."""

        value = self._verify_seal(
            receipt, domain="novel-flywheel-full-short-completion-receipt-v1",
            field="completion_receipt_sha256",
            reason="COMPLETION_RECEIPT_SHA256_MISMATCH",
        )
        _require(value.get("schema") == COMPLETION_SCHEMA, "COMPLETION_SCHEMA_MISMATCH")
        _require(value.get("execution_id") == execution_id, "EXECUTION_CHAIN_ID_MISMATCH")
        validated = self._verify_store_binding(policy)
        _require(
            value.get("policy_sha256") == validated["policy_sha256"],
            "EXECUTION_CHAIN_POLICY_MISMATCH",
        )
        with self._locked():
            permission = self._verify_seal(
                self._read(execution_id, "permission"),
                domain="novel-flywheel-full-short-permission-v1",
                field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
            )
            approval = self._verify_seal(
                self._read(execution_id, "approval"),
                domain="novel-flywheel-full-short-jit-approval-v1",
                field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
            )
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            _require(nonce.get("state") == "CONSUMED", "NONCE_NOT_CONSUMED")
            for chain_value in (permission, approval, nonce, ledger):
                _require(
                    chain_value.get("execution_id") == execution_id
                    and chain_value.get("policy_sha256")
                    == validated["policy_sha256"]
                    and chain_value.get("store_root_sha256")
                    == self.store_root_sha256,
                    "EXECUTION_CHAIN_MISMATCH",
                )
            _require(
                approval.get("permission_sha256") == permission.get("permission_sha256")
                and nonce.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and ledger.get("nonce_sha256") == nonce.get("nonce_sha256"),
                "EXECUTION_CHAIN_LINK_MISMATCH",
            )
            _require(
                value.get("permission_sha256") == permission.get("permission_sha256")
                and value.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and value.get("nonce_sha256") == nonce.get("nonce_sha256")
                and value.get("dispatch_ledger_sha256") == ledger.get("ledger_sha256"),
                "COMPLETION_CHAIN_MISMATCH",
            )
            attempts = ledger.get("attempts")
            _require(
                ledger.get("state") == "READY_FOR_NEXT_STAGE"
                and isinstance(attempts, list)
                and bool(attempts)
                and all(item.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                        for item in attempts)
                and value.get("provider_request_count") == len(attempts),
                "COMPLETION_LEDGER_NOT_EXACT",
            )
            self._exclusive_write(self._path(execution_id, "completion"), value)
        return value

    def completion_exists(self, execution_id: str) -> bool:
        """Cheap preflight only; the locked dispatch mutation rechecks it."""

        return self._path(execution_id, "completion").exists()


class FullShortDispatchLedgerObserverV1:
    """Durable observer attached to the production ``HttpProvider`` seam."""

    def __init__(
        self, *, store: FullShortDurableExecutionStoreV1,
        execution_id: str, policy: Mapping[str, Any],
        authorized_routes: tuple[Mapping[str, Any], ...],
        egress_policy: Mapping[str, Any], session_id: str | None = None,
        external_actions_enabled: bool = False,
        live_authority_recheck: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self.execution_id = execution_id
        self.policy = validate_policy_v1(policy)
        _require(bool(authorized_routes), "OBSERVER_ROUTE_BINDINGS_REQUIRED")
        self.authorized_routes = tuple(deepcopy(dict(item)) for item in authorized_routes)
        _require(
            _canonical_sha256(list(self.authorized_routes))
            == self.policy["route_manifest_sha256"],
            "ROUTE_MANIFEST_DRIFT",
        )
        destinations = sorted({str(item.get("destination") or "").rstrip("/")
                               for item in self.authorized_routes})
        _require(
            all(destination.startswith("https://") for destination in destinations),
            "DESTINATION_BINDING_INVALID",
        )
        _require(
            _canonical_sha256(destinations)
            == self.policy["destination_manifest_sha256"],
            "DESTINATION_MANIFEST_DRIFT",
        )
        _require(
            _canonical_sha256(egress_policy) == self.policy["egress_policy_sha256"],
            "EGRESS_POLICY_DRIFT",
        )
        _require(
            set(egress_policy) == {"allowed", "forbidden"}
            and tuple(egress_policy.get("allowed") or ())
            == _FULL_SHORT_EGRESS_ALLOWED
            and tuple(egress_policy.get("forbidden") or ())
            == _FULL_SHORT_EGRESS_FORBIDDEN,
            "EGRESS_POLICY_NOT_CLOSED",
        )
        self.egress_policy_sha256 = self.policy["egress_policy_sha256"]
        self.session_id = session_id or secrets.token_hex(16)
        self.external_actions_enabled = external_actions_enabled
        self.live_authority_recheck = live_authority_recheck
        self.pending_ordinal: int | None = None
        self.bound_route: dict[str, Any] | None = None
        self.expected_provider_payload: dict[str, Any] | None = None
        self.egress_intent_sha256: str | None = None
        self.pending_stage_context: dict[str, Any] | None = None
        self.capture_store = ProviderResponseCaptureStoreV1(
            repo_root=self.store.repo_root,
            store_root=self.store.root / "provider-response-captures-v1",
        )
        self.store.verify_ready_chain(
            execution_id=execution_id, policy=self.policy,
            external_actions_enabled=external_actions_enabled,
        )
        self.store.claim_observer_session(
            execution_id=execution_id, policy=self.policy,
            session_id=self.session_id,
        )

    def bind_stage_context(
        self, *, stage_id: str, contract_name: str, contract_version: int,
        contract_schema_sha256: str,
        contract_runtime_input_required: bool = False,
    ) -> None:
        """Bind the exact local stage/contract before any route resolution."""

        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        _require(_ID.fullmatch(stage_id) is not None, "CAPTURE_STAGE_ID_INVALID")
        _require(bool(contract_name), "CAPTURE_CONTRACT_NAME_INVALID")
        _require(type(contract_version) is int and contract_version > 0,
                 "CAPTURE_CONTRACT_VERSION_INVALID")
        _require(_HEX64.fullmatch(contract_schema_sha256) is not None,
                 "CAPTURE_CONTRACT_SCHEMA_INVALID")
        _require(type(contract_runtime_input_required) is bool,
                 "CAPTURE_CONTRACT_INPUT_POLICY_INVALID")
        logical_stage_id = self._logical_stage_identity(stage_id)
        self.pending_stage_context = {
            "stage_id": stage_id,
            "logical_stage_base_id": stage_id,
            "logical_stage_id": logical_stage_id,
            "contract_name": contract_name,
            "contract_version": contract_version,
            "contract_schema_sha256": contract_schema_sha256,
            "contract_runtime_input_required": contract_runtime_input_required,
            "capture_enforcement_required": True,
        }

    def _logical_stage_identity(self, stage_id: str) -> str:
        """Allocate one durable logical occurrence, reusing only a rejection."""

        attempts = list(
            self.store.load_ledger(self.execution_id).get("attempts") or []
        )
        matching = [
            item for item in attempts
            if item.get("logical_stage_base_id", item.get("logical_stage_id"))
            == stage_id
        ]
        if matching and matching[-1].get("state") == "LOCAL_ATTEMPT_REJECTED":
            logical_stage_id = str(matching[-1].get("logical_stage_id") or "")
            _require(
                _ID.fullmatch(logical_stage_id) is not None,
                "LOGICAL_STAGE_ID_INVALID",
            )
            return logical_stage_id
        occurrence = len({
            str(item.get("logical_stage_id") or "") for item in matching
        }) + 1
        if occurrence == 1:
            return stage_id
        digest = hashlib.sha256(stage_id.encode("utf-8")).hexdigest()[:8]
        suffix = f".{occurrence}.{digest}"
        return f"{stage_id[:160 - len(suffix)]}{suffix}"

    def bind_route(
        self, *, role: str, lane: str, provider_id: str, model_id: str,
        route_fingerprint: str,
    ) -> None:
        """Bind the next route before ProviderRegistry reads a credential."""

        if self.live_authority_recheck is not None:
            self.live_authority_recheck()
        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        provider_hash = hashlib.sha256(provider_id.encode("utf-8")).hexdigest()
        model_hash = hashlib.sha256(model_id.encode("utf-8")).hexdigest()
        matches = [item for item in self.authorized_routes if (
            item.get("role") == role
            and item.get("lane") == lane
            and item.get("provider_id_sha256") == provider_hash
            and item.get("model_id_sha256") == model_hash
            and item.get("route_fingerprint") == route_fingerprint
        )]
        _require(len(matches) == 1, "ROUTE_BINDING_DRIFT")
        route = deepcopy(matches[0])
        route["role_binding_sha256"] = domain_sha256(
            "novel-flywheel-full-short-role-binding-v1",
            {key: route.get(key) for key in (
                "role", "lane", "provider_id_sha256", "model_id_sha256",
                "model_name", "protocol", "route_fingerprint", "destination",
            )},
        )
        if self.bound_route is not None:
            _require(
                self.expected_provider_payload is None
                and self.egress_intent_sha256 is None,
                "ROUTE_ALREADY_BOUND",
            )
            # Capacity preflight may resolve more than one already-authorized
            # lane before constructing any model request.  The latest exact
            # manifest member becomes the candidate; wire binding below still
            # makes the eventual dispatch lane/destination immutable.
        self.bound_route = route

    def bind_model_request(
        self, *, protocol: str, request: ModelRequest,
    ) -> None:
        """Bind typed model intent before an adapter constructs wire bytes."""

        route = self.bound_route
        _require(route is not None, "ROUTE_NOT_BOUND_BEFORE_MODEL_REQUEST")
        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        _require(
            self.expected_provider_payload is None,
            "MODEL_REQUEST_ALREADY_BOUND",
        )
        if self.pending_stage_context is None:
            response_schema = request.response_schema or {}
            schema_value = response_schema.get("schema", response_schema)
            stage_id = str(route.get("role") or "model")
            self.pending_stage_context = {
                "stage_id": stage_id,
                "logical_stage_base_id": stage_id,
                "logical_stage_id": self._logical_stage_identity(stage_id),
                "contract_name": str(
                    response_schema.get("name") or "unstructured_text"
                ),
                "contract_version": 1,
                "contract_schema_sha256": _canonical_sha256(schema_value),
                "contract_runtime_input_required": bool(request.response_schema),
                "capture_enforcement_required": False,
            }
        _require(protocol == route.get("protocol"), "EGRESS_PROTOCOL_DRIFT")
        expected = _expected_provider_payload_v1(
            protocol, request, destination=str(route["destination"]),
        )
        self.expected_provider_payload = expected
        self.egress_intent_sha256 = domain_sha256(
            "novel-flywheel-full-short-egress-intent-v1",
            {
                "protocol": protocol,
                "role_binding_sha256": route["role_binding_sha256"],
                "provider_payload_sha256": _canonical_sha256(expected),
            },
        )

    def before_http_dispatch(
        self, *, method: str, url: str, payload: Mapping[str, Any],
    ) -> None:
        if self.live_authority_recheck is not None:
            self.live_authority_recheck()
        target = urlsplit(url)
        normalized = f"{target.scheme}://{target.hostname}:{target.port or 443}{target.path}"
        _require(method == "POST", "HTTP_METHOD_NOT_AUTHORIZED")
        _require(
            target.scheme == "https" and target.hostname is not None
            and target.username is None and target.password is None
            and not target.query and not target.fragment,
            "DESTINATION_URL_NOT_EXACT",
        )
        route = self.bound_route
        _require(route is not None, "ROUTE_NOT_BOUND_BEFORE_CREDENTIAL_OR_HTTP")
        _require(
            isinstance(self.pending_stage_context, dict),
            "CAPTURE_STAGE_CONTEXT_NOT_BOUND",
        )
        _require(normalized == route.get("destination"), "DESTINATION_DRIFT")
        expected_payload = self.expected_provider_payload
        _require(
            expected_payload is not None
            and self.egress_intent_sha256 is not None,
            "MODEL_REQUEST_EGRESS_INTENT_NOT_BOUND",
        )
        _require(
            dict(payload) == expected_payload,
            "EGRESS_PAYLOAD_SCHEMA_OR_CONTENT_DRIFT",
        )
        _require(
            str(payload.get("model") or "") == route.get("model_name"),
            "MODEL_BINDING_DRIFT",
        )
        request_shape = {
            "method": method,
            "destination": normalized,
            "model_sha256": hashlib.sha256(
                str(payload.get("model") or "").encode("utf-8"),
            ).hexdigest(),
            "payload_key_sequence": sorted(str(key) for key in payload),
            "requested_output_tokens": int(
                payload.get("max_tokens") or payload.get("max_output_tokens") or 0,
            ),
            "provider_payload_sha256": _canonical_sha256(payload),
            "message_count": len(
                payload.get("messages") or payload.get("input") or [],
            ),
            "tool_count": len(payload.get("tools") or []),
        }
        request_shape_sha256 = domain_sha256(
            "novel-flywheel-full-short-request-shape-v1", request_shape,
        )
        ledger = self.store.load_ledger(self.execution_id)
        attempts = list(ledger.get("attempts") or [])
        try:
            created_at = datetime.fromisoformat(
                str(ledger["created_at"]).replace("Z", "+00:00"),
            )
        except (KeyError, ValueError) as exc:
            raise FullShortExecutionBoundaryError("LEDGER_CREATED_AT_INVALID") from exc
        _require(
            (datetime.now(timezone.utc) - created_at).total_seconds()
            <= self.policy["maximum_elapsed_seconds"],
            "MAXIMUM_ELAPSED_EXPIRED",
        )
        _require(
            len(attempts) < self.policy["hard_max_provider_requests"],
            "PROVIDER_REQUEST_CAP_EXHAUSTED",
        )
        _require(
            not self.store.completion_exists(self.execution_id),
            "EXECUTION_ALREADY_COMPLETED",
        )
        if attempts:
            previous = attempts[-1]
            _require(
                previous.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                and previous.get("session_id") == self.session_id,
                "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART",
            )
        ordinal = len(attempts) + 1
        requested_tokens = request_shape["requested_output_tokens"]
        _require(requested_tokens > 0, "OUTPUT_TOKEN_CAP_INVALID")
        _require(
            requested_tokens <= self.policy["per_call_output_token_hard_cap"],
            "PER_CALL_OUTPUT_TOKEN_CAP_EXHAUSTED",
        )
        total_requested = sum(
            int(item.get("requested_output_tokens") or 0) for item in attempts
        ) + requested_tokens
        _require(
            total_requested <= self.policy["total_output_token_hard_cap"],
            "TOTAL_OUTPUT_TOKEN_CAP_EXHAUSTED",
        )
        logical_stage_id = str(self.pending_stage_context["logical_stage_id"])
        prior_logical_attempts = [
            item for item in attempts
            if item.get("logical_stage_id", item.get("stage"))
            == logical_stage_id
        ]
        distinct_logical_stage_ids = {
            str(item.get("logical_stage_id", item.get("stage")) or "")
            for item in attempts
        }
        if not prior_logical_attempts:
            _require(
                len(distinct_logical_stage_ids)
                < self.policy["expected_stage_calls"],
                "LOGICAL_STAGE_CALL_CAP_EXHAUSTED",
            )
        else:
            _require(
                prior_logical_attempts[-1].get("state")
                == "LOCAL_ATTEMPT_REJECTED"
                and not any(
                    item.get("state") == "LOCAL_STAGE_COMPLETE"
                    for item in prior_logical_attempts
                ),
                "LOGICAL_STAGE_REDISPATCH_NOT_AUTHORIZED",
            )
        attempt = {
            "ordinal": ordinal,
            "session_id": self.session_id,
            "request_shape_sha256": request_shape_sha256,
            "requested_output_tokens": requested_tokens,
            "provider_id_sha256": route["provider_id_sha256"],
            "model_id_sha256": route["model_id_sha256"],
            "model_name_sha256": request_shape["model_sha256"],
            "route_fingerprint": route["route_fingerprint"],
            "destination": normalized,
            "destination_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "egress_policy_sha256": self.egress_policy_sha256,
            "egress_intent_sha256": self.egress_intent_sha256,
            "provider_payload_sha256": request_shape[
                "provider_payload_sha256"
            ],
            "protocol_schema_id": f"{route['protocol']}-wire-v1",
            "message_count": request_shape["message_count"],
            "tool_count": request_shape["tool_count"],
            "role_binding_sha256": route["role_binding_sha256"],
            "bound_role": route["role"],
            "bound_lane": route["lane"],
            "stage": self.pending_stage_context["stage_id"],
            "logical_stage_base_id": self.pending_stage_context[
                "logical_stage_base_id"
            ],
            "logical_stage_id": logical_stage_id,
            "contract_name": self.pending_stage_context["contract_name"],
            "contract_version": self.pending_stage_context["contract_version"],
            "contract_schema_sha256": self.pending_stage_context[
                "contract_schema_sha256"
            ],
            "contract_runtime_input_required": self.pending_stage_context[
                "contract_runtime_input_required"
            ],
            "capture_enforcement_required": self.pending_stage_context[
                "capture_enforcement_required"
            ],
            "state": "DISPATCH_ATTEMPTED",
            "attempted_at": _now(),
            "response_status_sha256": None,
            "local_stage_receipt_sha256": None,
            "provider_protocol_capture_receipt_sha256": None,
            "contract_runtime_capture_receipt_sha256": None,
        }
        self.store.consume_nonce_and_record_dispatch(
            execution_id=self.execution_id, policy=self.policy,
            external_actions_enabled=self.external_actions_enabled,
            session_id=self.session_id, attempt=attempt,
        )
        self.pending_ordinal = ordinal

    def before_http_post(self) -> None:
        # Backward-compatible observer hook; the exact dispatch is already
        # durably recorded by ``before_http_dispatch``.
        _require(self.pending_ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

    def before_network_request(self) -> None:
        _require(self.pending_ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

    def _capture_metadata(
        self, *, adapter_id: str, adapter_version: int,
        content_type: str, encoding: str, transport_complete: bool,
    ) -> dict[str, Any]:
        ordinal = self.pending_ordinal
        route = self.bound_route
        context = self.pending_stage_context
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")
        _require(isinstance(route, dict), "CAPTURE_ROUTE_NOT_BOUND")
        _require(isinstance(context, dict), "CAPTURE_STAGE_CONTEXT_NOT_BOUND")
        return {
            "execution_id": self.execution_id,
            "call_id": f"{self.execution_id}:{ordinal}",
            "stage_id": context["stage_id"],
            "provider_id_sha256": route["provider_id_sha256"],
            "model_id_sha256": route["model_id_sha256"],
            "route_fingerprint": route["route_fingerprint"],
            "protocol": route["protocol"],
            "contract_name": context["contract_name"],
            "contract_version": context["contract_version"],
            "contract_schema_sha256": context["contract_schema_sha256"],
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "content_type": content_type,
            "encoding": encoding,
            "transport_complete": transport_complete,
        }

    def _record_capture_receipt(
        self, *, field: str, receipt_sha256: str,
    ) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("state") in {
                    "DISPATCH_ATTEMPTED", "RESPONSE_RECEIVED",
                },
                "CAPTURE_LEDGER_STATE_INVALID",
            )
            _require(current.get(field) is None, "CAPTURE_RECEIPT_DUPLICATE")
            current[field] = receipt_sha256
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            return body

        self.store.update_ledger(self.execution_id, mutate)

    def capture_provider_protocol_input(
        self, *, data: bytes, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        _require(100 <= status_code <= 599, "CAPTURE_HTTP_STATUS_INVALID")
        route = self.bound_route
        _require(isinstance(route, dict), "CAPTURE_ROUTE_NOT_BOUND")
        receipt = self.capture_store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=data,
            metadata=self._capture_metadata(
                adapter_id=str(route["protocol"]), adapter_version=1,
                content_type=content_type, encoding=encoding,
                transport_complete=transport_complete,
            ),
        )
        self._record_capture_receipt(
            field="provider_protocol_capture_receipt_sha256",
            receipt_sha256=domain_sha256(
                "novel-flywheel-provider-response-capture-receipt-v1",
                receipt.document(),
            ),
        )

    def capture_contract_runtime_input(
        self, *, data: bytes, adapter_id: str, adapter_version: int,
        finish_reason: str | None, transport_complete: bool,
    ) -> None:
        receipt = self.capture_store.capture(
            byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
            data=data,
            metadata=self._capture_metadata(
                adapter_id=adapter_id, adapter_version=adapter_version,
                content_type="text/plain; purpose=contract-runtime-input",
                encoding="utf-8", transport_complete=transport_complete,
            ),
        )
        self._record_capture_receipt(
            field="contract_runtime_capture_receipt_sha256",
            receipt_sha256=domain_sha256(
                "novel-flywheel-provider-response-capture-receipt-v1",
                receipt.document(),
            ),
        )

    def contract_runtime_capture_present(self) -> bool:
        if self.pending_ordinal is None:
            return False
        ledger = self.store.load_ledger(self.execution_id)
        attempts = list(ledger.get("attempts") or [])
        return bool(
            len(attempts) >= self.pending_ordinal
            and attempts[self.pending_ordinal - 1].get(
                "contract_runtime_capture_receipt_sha256"
            )
        )

    def after_http_response(self, *, status_code: int) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")
        _require(type(status_code) is int, "HTTP_STATUS_INVALID")

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            _require(current.get("state") == "DISPATCH_ATTEMPTED", "DISPATCH_STATE_INVALID")
            if not 200 <= status_code < 300:
                current["state"] = "HTTP_RESPONSE_FAILED_CLOSED"
                current["response_status_sha256"] = hashlib.sha256(
                    str(status_code).encode("ascii"),
                ).hexdigest()
                attempts[ordinal - 1] = current
                body["attempts"] = attempts
                body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
                return body
            current["state"] = "RESPONSE_RECEIVED"
            current["response_status_sha256"] = hashlib.sha256(
                str(status_code).encode("ascii"),
            ).hexdigest()
            current["response_received_at"] = _now()
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT"
            return body

        self.store.update_ledger(self.execution_id, mutate)
        _require(200 <= status_code < 300, "HTTP_RESPONSE_NOT_SUCCESSFUL")

    def after_http_failure(self, *, failure_kind: str) -> None:
        ordinal = self.pending_ordinal
        if ordinal is None:
            # A local authorization/cap failure before the durable dispatch
            # seam cannot leave request identity attached to a later route.
            # No external completion is possible because no attempt ordinal
            # was recorded.
            self.bound_route = None
            self.expected_provider_payload = None
            self.egress_intent_sha256 = None
            self.pending_stage_context = None
            return

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("state") == "DISPATCH_ATTEMPTED",
                "SUCCESSFUL_RESPONSE_CANNOT_BE_REWRITTEN_AS_FAILURE",
            )
            current["state"] = "OUTCOME_UNKNOWN_FAIL_CLOSED"
            current["failure_kind_sha256"] = hashlib.sha256(
                failure_kind.encode("utf-8"),
            ).hexdigest()
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
            return body

        self.store.update_ledger(self.execution_id, mutate)

    def mark_local_stage_complete(
        self, *, stage: str, role: str, role_binding_sha256: str,
        output_sha256: str, receipt_sha256: str,
    ) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "NO_RESPONSE_TO_COMPLETE")
        _require(_HEX64.fullmatch(output_sha256) is not None, "OUTPUT_SHA256_INVALID")
        _require(_HEX64.fullmatch(receipt_sha256) is not None, "RECEIPT_SHA256_INVALID")
        _require(
            _HEX64.fullmatch(role_binding_sha256) is not None,
            "ROLE_BINDING_SHA256_INVALID",
        )

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            receipts = list(body.get("completed_stage_receipts") or [])
            _require(0 < ordinal <= len(attempts), "PENDING_ORDINAL_INVALID")
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("ordinal") == ordinal
                and current.get("session_id") == self.session_id
                and current.get("state") == "RESPONSE_RECEIVED",
                "RESPONSE_NOT_RECEIVED",
            )
            if current.get("capture_enforcement_required"):
                _require(
                    _HEX64.fullmatch(str(current.get(
                        "provider_protocol_capture_receipt_sha256"
                    ))) is not None,
                    "PROVIDER_RESPONSE_CAPTURE_REQUIRED",
                )
                if current.get("contract_runtime_input_required"):
                    _require(
                        _HEX64.fullmatch(str(current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ))) is not None,
                        "CONTRACT_RUNTIME_INPUT_CAPTURE_REQUIRED",
                    )
            _require(current.get("bound_role") == role, "STAGE_ROLE_DRIFT")
            _require(
                current.get("role_binding_sha256") == role_binding_sha256,
                "ROLE_BINDING_DRIFT",
            )
            current.update({
                "state": "LOCAL_STAGE_COMPLETE",
                "local_stage_receipt_sha256": receipt_sha256,
                "output_sha256": output_sha256,
                "stage": stage,
                "role": role,
            })
            attempts[ordinal - 1] = current
            receipts.append({
                "ordinal": ordinal,
                "stage": stage,
                "role": role,
                "role_binding_sha256": role_binding_sha256,
                "output_sha256": output_sha256,
                "receipt_sha256": receipt_sha256,
            })
            body["attempts"] = attempts
            body["completed_stage_receipts"] = receipts
            body["state"] = "READY_FOR_NEXT_STAGE"
            return body

        self.store.update_ledger(self.execution_id, mutate)
        self.pending_ordinal = None
        self.bound_route = None
        self.expected_provider_payload = None
        self.egress_intent_sha256 = None
        self.pending_stage_context = None

    def mark_local_attempt_rejected(
        self, *, stage: str, role: str, role_binding_sha256: str,
        rejection: Mapping[str, Any],
    ) -> None:
        """Durably close one 2xx response rejected by local contract logic.

        The state authorizes only the already-sealed next attempt in this same
        observer session.  It is not a stage receipt and cannot satisfy the
        logical Full Short completion matrix.
        """

        ordinal = self.pending_ordinal
        _require(ordinal is not None, "NO_RESPONSE_TO_REJECT")
        value = dict(rejection)
        pre_contract_final_artifact = (
            value.get("schema") == "ProviderFinalArtifactRejectionReceiptV1"
        )
        _require(
            set(value) == (
                _FINAL_ARTIFACT_REJECTION_RECEIPT_FIELDS
                if pre_contract_final_artifact
                else _LOCAL_REJECTION_RECEIPT_FIELDS
            ),
            "LOCAL_REJECTION_RECEIPT_SHAPE_INVALID",
        )
        _require(
            value.get("schema") in {
                "ContractLocalRejectionReceiptV1",
                "ProviderFinalArtifactRejectionReceiptV1",
            }
            and value.get("version") == 1
            and isinstance(value.get("contract_name"), str)
            and bool(value.get("contract_name"))
            and type(value.get("contract_version")) is int
            and int(value["contract_version"]) > 0
            and type(value.get("attempt_index")) is int
            and int(value["attempt_index"]) > 0
            and type(value.get("route_attempt")) is int
            and int(value["route_attempt"]) > 0
            and value.get("failure_kind") in (
                {"final_artifact_unavailable"}
                if pre_contract_final_artifact
                else {
                    "artifact_conversion", "business_incomplete",
                    "domain_validation",
                }
            )
            and type(value.get("raw_content_persisted")) is bool,
            "LOCAL_REJECTION_RECEIPT_INVALID",
        )
        if pre_contract_final_artifact:
            _require(
                isinstance(value.get("failure_code"), str)
                and bool(value.get("failure_code"))
                and value.get("contract_runtime_input_present") is False
                and value.get("raw_content_persisted") is False,
                "FINAL_ARTIFACT_REJECTION_RECEIPT_INVALID",
            )
        for field in ((
            "contract_schema_sha256", "failure_reason_sha256",
            "provider_output_shape_sha256",
        ) if pre_contract_final_artifact else (
            "contract_schema_sha256", "failure_reason_sha256",
            "response_text_sha256", "conversion_audit_sha256",
        )):
            _require(
                _HEX64.fullmatch(str(value.get(field))) is not None,
                "LOCAL_REJECTION_RECEIPT_HASH_INVALID",
            )
        _require(
            _HEX64.fullmatch(role_binding_sha256) is not None,
            "ROLE_BINDING_SHA256_INVALID",
        )
        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            _require(0 < ordinal <= len(attempts), "PENDING_ORDINAL_INVALID")
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("ordinal") == ordinal
                and current.get("session_id") == self.session_id
                and current.get("state") == "RESPONSE_RECEIVED",
                "RESPONSE_NOT_RECEIVED",
            )
            if current.get("capture_enforcement_required"):
                _require(
                    _HEX64.fullmatch(str(current.get(
                        "provider_protocol_capture_receipt_sha256"
                    ))) is not None,
                    "PROVIDER_RESPONSE_CAPTURE_REQUIRED",
                )
                if (
                    current.get("contract_runtime_input_required")
                    and not pre_contract_final_artifact
                ):
                    _require(
                        _HEX64.fullmatch(str(current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ))) is not None,
                        "CONTRACT_RUNTIME_INPUT_CAPTURE_REQUIRED",
                    )
                if pre_contract_final_artifact:
                    _require(
                        current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ) is None,
                        "FINAL_ARTIFACT_REJECTION_AFTER_CONTRACT_INPUT",
                    )
            _require(current.get("bound_role") == role, "STAGE_ROLE_DRIFT")
            _require(
                current.get("role_binding_sha256") == role_binding_sha256,
                "ROLE_BINDING_DRIFT",
            )
            contract_route = value.get("route")
            manifest_lane = (
                "fallback"
                if contract_route == "configured_fallback"
                else contract_route
            )
            _require(
                self.bound_route is not None
                and manifest_lane == self.bound_route.get("lane"),
                "LOCAL_REJECTION_ROUTE_DRIFT",
            )
            _require(
                int(value["route_attempt"]) <= int(value["attempt_index"]),
                "LOCAL_REJECTION_ATTEMPT_IDENTITY_INVALID",
            )
            prior_same_stage = [
                item for item in attempts[:ordinal - 1]
                if item.get("logical_stage_id", item.get("stage"))
                == current["logical_stage_id"]
            ]
            _require(
                int(value["attempt_index"]) == len(prior_same_stage) + 1,
                "LOCAL_REJECTION_ATTEMPT_IDENTITY_INVALID",
            )
            bound_rejection = {
                **value,
                "physical_ordinal": ordinal,
                "logical_stage_id": str(current["logical_stage_id"]),
                "nonce_sha256": str(body["nonce_sha256"]),
                "session_id_sha256": hashlib.sha256(
                    self.session_id.encode("utf-8"),
                ).hexdigest(),
                "request_shape_sha256": str(current["request_shape_sha256"]),
                "provider_protocol_capture_receipt_sha256": str(
                    current["provider_protocol_capture_receipt_sha256"]
                ),
            }
            rejection_receipt_sha256 = domain_sha256(
                (
                    "novel-flywheel-provider-final-artifact-rejection-receipt-v2"
                    if pre_contract_final_artifact
                    else "novel-flywheel-contract-local-rejection-receipt-v2"
                ),
                bound_rejection,
            )
            current.update({
                "state": "LOCAL_ATTEMPT_REJECTED",
                "local_rejection_receipt_sha256": rejection_receipt_sha256,
                "local_rejection_failure_kind": value["failure_kind"],
                "local_rejection_schema": value["schema"],
                "local_rejection_physical_ordinal": ordinal,
                "local_rejection_logical_stage_id": str(
                    current["logical_stage_id"]
                ),
                "local_rejection_failure_reason_sha256": value[
                    "failure_reason_sha256"
                ],
                "contract_name": value["contract_name"],
                "contract_version": value["contract_version"],
                "contract_schema_sha256": value["contract_schema_sha256"],
                "stage": stage,
                "role": role,
            })
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "READY_FOR_RECOVERY_ATTEMPT"
            return body

        self.store.update_ledger(self.execution_id, mutate)
        self.pending_ordinal = None
        self.bound_route = None
        self.expected_provider_payload = None
        self.egress_intent_sha256 = None
        self.pending_stage_context = None


def validate_full_short_dispatch_accounting_v1(
    *, logical_stage_count: int, physical_dispatch_count: int,
    expected_stage_calls: int, physical_dispatch_hard_cap: int,
    exact_replay_physical_dispatch_delta: int = 0,
) -> dict[str, int]:
    """Validate physical/logical/replay counts through one closed boundary."""

    values = (
        logical_stage_count, physical_dispatch_count, expected_stage_calls,
        physical_dispatch_hard_cap, exact_replay_physical_dispatch_delta,
    )
    _require(all(type(value) is int for value in values),
             "DISPATCH_ACCOUNTING_TYPE_INVALID")
    _require(
        logical_stage_count == expected_stage_calls,
        "EXPECTED_STAGE_CALL_COUNT_MISMATCH",
    )
    _require(
        logical_stage_count <= physical_dispatch_count
        <= physical_dispatch_hard_cap,
        "COMPLETION_CALL_CAP_EXCEEDED",
    )
    _require(
        exact_replay_physical_dispatch_delta == 0,
        "EXACT_REPLAY_CREATED_PHYSICAL_DISPATCH",
    )
    return {
        "logical_stage_count": logical_stage_count,
        "physical_dispatch_count": physical_dispatch_count,
        "physical_dispatch_hard_cap": physical_dispatch_hard_cap,
        "exact_replay_physical_dispatch_delta": 0,
    }


def build_full_short_completion_receipt_v1(
    *, execution_id: str, policy: Mapping[str, Any],
    permission_sha256: str, signed_approval_sha256: str, nonce_sha256: str,
    ledger: Mapping[str, Any], final_bindings: Mapping[str, str],
    terminal_verification: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_policy_v1(policy)
    sealed_ledger = FullShortDurableExecutionStoreV1._verify_seal(
        ledger, domain="novel-flywheel-full-short-dispatch-ledger-v1",
        field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
    )
    _require(
        sealed_ledger.get("execution_id") == execution_id
        and sealed_ledger.get("policy_sha256") == validated["policy_sha256"]
        and sealed_ledger.get("store_root_sha256")
        == validated["store_root_sha256"]
        and sealed_ledger.get("nonce_sha256") == nonce_sha256,
        "COMPLETION_LEDGER_CHAIN_MISMATCH",
    )
    _require(sealed_ledger.get("state") == "READY_FOR_NEXT_STAGE", "LEDGER_NOT_CLOSED")
    attempts = sealed_ledger.get("attempts")
    _require(isinstance(attempts, list) and attempts, "LEDGER_HAS_NO_DISPATCH")
    _require(
        all(item.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES for item in attempts),
        "LEDGER_HAS_UNCLOSED_DISPATCH",
    )
    _require(
        [item.get("ordinal") for item in attempts]
        == list(range(1, len(attempts) + 1)),
        "LEDGER_ORDINALS_INVALID",
    )
    completed_stage_receipts = list(
        sealed_ledger.get("completed_stage_receipts") or []
    )
    validate_full_short_dispatch_accounting_v1(
        logical_stage_count=len(completed_stage_receipts),
        physical_dispatch_count=len(attempts),
        expected_stage_calls=validated["expected_stage_calls"],
        physical_dispatch_hard_cap=validated["hard_max_provider_requests"],
    )
    _require(
        len(attempts) <= validated["hard_max_provider_requests"]
        and len(attempts) <= validated["hard_max_http_posts"]
        and len(attempts) <= validated["hard_max_network_attempts"],
        "COMPLETION_CALL_CAP_EXCEEDED",
    )
    requested_total = sum(int(item.get("requested_output_tokens") or 0)
                          for item in attempts)
    _require(
        all(0 < int(item.get("requested_output_tokens") or 0)
            <= validated["per_call_output_token_hard_cap"] for item in attempts),
        "COMPLETION_PER_CALL_CAP_INVALID",
    )
    _require(
        requested_total == sealed_ledger.get("total_requested_output_tokens")
        and requested_total <= validated["total_output_token_hard_cap"],
        "COMPLETION_TOTAL_OUTPUT_CAP_INVALID",
    )
    try:
        created_at = datetime.fromisoformat(
            str(sealed_ledger["created_at"]).replace("Z", "+00:00"),
        )
    except (KeyError, ValueError) as exc:
        raise FullShortExecutionBoundaryError("LEDGER_CREATED_AT_INVALID") from exc
    _require(
        (datetime.now(timezone.utc) - created_at).total_seconds()
        <= validated["maximum_elapsed_seconds"],
        "MAXIMUM_ELAPSED_EXPIRED",
    )
    receipts = completed_stage_receipts
    _require(
        isinstance(receipts, list)
        and len(receipts) == validated["expected_stage_calls"]
        and all(type(item.get("ordinal")) is int for item in receipts)
        and [item.get("ordinal") for item in receipts]
        == sorted({item.get("ordinal") for item in receipts})
        and all(0 < item["ordinal"] <= len(attempts) for item in receipts),
        "STAGE_MATRIX_INVALID",
    )
    _require(
        len({
            str(attempts[item["ordinal"] - 1].get(
                "logical_stage_id", attempts[item["ordinal"] - 1].get("stage")
            ))
            for item in receipts
        }) == validated["expected_stage_calls"],
        "LOGICAL_STAGE_MATRIX_DUPLICATE",
    )
    required_roles = set(validated["required_stage_roles"])
    _require(
        {item.get("role") for item in receipts} == required_roles,
        "REQUIRED_STAGE_ROLE_MATRIX_INCOMPLETE",
    )
    receipt_by_ordinal = {item["ordinal"]: item for item in receipts}
    _require(
        all(
            (attempt.get("ordinal") in receipt_by_ordinal)
            == (attempt.get("state") == "LOCAL_STAGE_COMPLETE")
            for attempt in attempts
        ),
        "STAGE_MATRIX_INVALID",
    )
    for stage_receipt in receipts:
        attempt = attempts[stage_receipt["ordinal"] - 1]
        _require(
            attempt.get("stage") == stage_receipt.get("stage")
            and attempt.get("role") == stage_receipt.get("role")
            and attempt.get("role_binding_sha256")
            == stage_receipt.get("role_binding_sha256")
            and attempt.get("output_sha256") == stage_receipt.get("output_sha256")
            and attempt.get("local_stage_receipt_sha256")
            == stage_receipt.get("receipt_sha256"),
            "STAGE_MATRIX_BINDING_MISMATCH",
        )
    _require(
        set(final_bindings) == REQUIRED_FINAL_BINDING_KEYS,
        "COMPLETION_BINDING_KEYS_MISMATCH",
    )
    terminal = FullShortDurableExecutionStoreV1._verify_seal(
        terminal_verification,
        domain="novel-flywheel-short-completion-verification-v1",
        field="verification_receipt_sha256",
        reason="TERMINAL_VERIFICATION_SHA256_MISMATCH",
    )
    _require(
        terminal.get("schema") == "ShortCompletionVerificationV1"
        and terminal.get("version") == 1
        and terminal.get("workflow_final_status") == "completed"
        and terminal.get("unresolved_terminal_status") == "none"
        and terminal.get("live_parity_status") == "exact"
        and terminal.get("completion_goal_outcome") == SHORT_COMPLETION_GOAL
        and terminal.get("final_manuscript_binding_status") == "exact"
        and (terminal.get("final_review") or {}).get("accepted_status") == "accepted"
        and (terminal.get("final_review") or {}).get("binding_status") == "exact"
        and (terminal.get("maintenance") or {}).get("closure_status") == "exact"
        and (terminal.get("final_artifact") or {}).get("binding_status") == "exact"
        and (terminal.get("final_checkpoint") or {}).get("closure_status") == "exact",
        "TERMINAL_VERIFICATION_NOT_SUCCESSFUL",
    )
    _require(
        final_bindings["terminal_verification_sha256"]
        == terminal_verification.get("verification_receipt_sha256"),
        "TERMINAL_VERIFICATION_BINDING_MISMATCH",
    )
    _require(
        final_bindings["manuscript_sha256"]
        == terminal.get("final_manuscript_sha256"),
        "TERMINAL_MANUSCRIPT_BINDING_MISMATCH",
    )
    for value in (
        permission_sha256, signed_approval_sha256, nonce_sha256,
        *final_bindings.values(),
    ):
        _require(_HEX64.fullmatch(str(value)) is not None, "COMPLETION_BINDING_INVALID")
    body = {
        "schema": COMPLETION_SCHEMA, "version": 1,
        "execution_id": execution_id,
        "policy_sha256": validated["policy_sha256"],
        "permission_sha256": permission_sha256,
        "signed_approval_sha256": signed_approval_sha256,
        "nonce_sha256": nonce_sha256,
        "dispatch_ledger_sha256": sealed_ledger["ledger_sha256"],
        "provider_request_count": len(attempts),
        "http_post_count": len(attempts),
        "network_attempt_count": len(attempts),
        "completed_stage_count": len(receipts),
        "requested_output_tokens": requested_total,
        "required_stage_roles": sorted(required_roles),
        "final_bindings": dict(sorted(final_bindings.items())),
        "outcome": "FULL_SHORT_COMPLETED_EXACT",
        "created_at": _now(),
    }
    return _seal(
        "novel-flywheel-full-short-completion-receipt-v1", body,
        "completion_receipt_sha256",
    )


def replay_full_short_provider_attempt_v1(
    *, store: FullShortDurableExecutionStoreV1, execution_id: str,
    ordinal: int,
):
    """Read-only replay of one receipt-anchored captured provider entity.

    This function deliberately has no provider registry, credential, client,
    nonce mutation, or network path.  An orphan capture without an exact
    ledger receipt fails closed and therefore cannot silently authorize a
    restart or redispatch.
    """

    _require(type(ordinal) is int and ordinal > 0, "REPLAY_ORDINAL_INVALID")
    ledger = store.load_ledger(execution_id)
    attempts = list(ledger.get("attempts") or [])
    _require(ordinal <= len(attempts), "REPLAY_ATTEMPT_MISSING")
    attempt = attempts[ordinal - 1]
    receipt_sha256 = attempt.get(
        "provider_protocol_capture_receipt_sha256"
    )
    _require(
        isinstance(receipt_sha256, str)
        and _HEX64.fullmatch(receipt_sha256) is not None,
        "REPLAY_LEDGER_CAPTURE_RECEIPT_MISSING",
    )
    capture_store = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root,
        store_root=store.root / "provider-response-captures-v1",
    )
    matches = [
        item for item in capture_store.audit_all()
        if item["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
        and item["execution_id"] == execution_id
        and item["call_id"] == f"{execution_id}:{ordinal}"
        and item["ledger_receipt_sha256"] == receipt_sha256
    ]
    _require(len(matches) == 1, "REPLAY_CAPTURE_IDENTITY_NOT_EXACT")
    capture = matches[0]
    data, metadata = capture_store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=capture["metadata"],
        expected_receipt_sha256=receipt_sha256,
    )
    _require(metadata["protocol"] == "anthropic", "REPLAY_PROTOCOL_UNSUPPORTED")
    from novel_flywheel.providers.anthropic import AnthropicAdapter

    return AnthropicAdapter.replay_protocol_input_bytes_v1(
        data, content_type=metadata["content_type"],
        encoding=metadata["encoding"],
    )
