"""Durable single-use nonce ledger for the isolated Skill V3 pilot.

The ledger is deliberately pilot-scoped and lives outside the Git worktree.
It stores only content-addressed execution bindings and lifecycle metadata; it
never stores prompts, story prose, provider responses, or credentials.
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
from typing import Any, Iterator, Mapping

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)


NONCE_SCHEMA = "SkillV3PilotDurableNonceV1"
NONCE_SCHEMA_V2 = "SkillV3PilotDestinationBoundDurableNonceV2"
NONCE_POLICY_VERSION = "skill-v3-pilot-durable-nonce-policy-v1"
NONCE_DOMAIN = "novel-flywheel-skill-v3-pilot-durable-nonce-v1"
NONCE_DOMAIN_V2 = "novel-flywheel-skill-v3-pilot-destination-bound-durable-nonce-v2"
DEFAULT_STORE_RELATIVE = Path(
    "canary-nonce-ledgers/skill-v3-character-heavy-multi-sample-v1/nonces-v1"
)
TERMINAL_STATES = {
    "CONSUMED",
    "INVALIDATED_PRE_DISPATCH",
    "INVALIDATED_FAILED_DISPATCH",
    "CLOSED",
}
ALL_STATES = {"RESERVED", "DISPATCH_ATTEMPTED", *TERMINAL_STATES}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class SkillV3NonceStoreError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise SkillV3NonceStoreError(reason_code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def default_nonce_store_root() -> Path:
    return default_settings().data_dir / DEFAULT_STORE_RELATIVE


class _FileLock:
    """Small cross-platform advisory lock that is released by process exit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

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
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise SkillV3NonceStoreError("CONCURRENT_NONCE_RESERVATION") from exc
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


class DurablePilotNonceStoreV1:
    """Atomic, restart-safe nonce lifecycle for one isolated pilot."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        requested = Path(os.path.abspath(store_root))
        _require(
            not _path_is_within(requested, self.repo_root),
            "NONCE_STORE_INSIDE_GIT_WORKTREE",
        )
        requested.mkdir(parents=True, exist_ok=True)
        self.store_root = requested.resolve(strict=True)
        _require(
            os.path.normcase(str(self.store_root)) == os.path.normcase(str(requested)),
            "NONCE_STORE_PATH_NOT_EXACT",
        )
        self._lock_path = self.store_root / ".nonce-store.lock"

    def _binding_key(self, pilot_id: str, sample_id: str, approval_id: str) -> str:
        for value in (pilot_id, sample_id, approval_id):
            _require(_ID.fullmatch(value) is not None, "NONCE_BINDING_ID_INVALID")
        return domain_sha256(
            "skill-v3-pilot-nonce-storage-key-v1",
            {"pilot_id": pilot_id, "sample_id": sample_id, "approval_id": approval_id},
        )

    def _path(self, pilot_id: str, sample_id: str, approval_id: str) -> Path:
        return self.store_root / f"{self._binding_key(pilot_id, sample_id, approval_id)}.nonce.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with _FileLock(self._lock_path):
            yield

    @staticmethod
    def _seal(body: Mapping[str, Any]) -> dict[str, Any]:
        domain = NONCE_DOMAIN_V2 if body.get("schema") == NONCE_SCHEMA_V2 else NONCE_DOMAIN
        return {
            **deepcopy(dict(body)),
            "nonce_receipt_sha256": domain_sha256(domain, body),
        }

    @staticmethod
    def _validate(value: Mapping[str, Any]) -> dict[str, Any]:
        schema = value.get("schema")
        version = value.get("version")
        _require(
            (schema == NONCE_SCHEMA and version == 1)
            or (schema == NONCE_SCHEMA_V2 and version == 2),
            "NONCE_SCHEMA_MISMATCH",
        )
        _require(
            value.get("canonicalization_version") == CANONICALIZATION_VERSION,
            "NONCE_CANONICALIZATION_UNSUPPORTED",
        )
        _require(value.get("nonce_policy_version") == NONCE_POLICY_VERSION, "NONCE_POLICY_MISMATCH")
        _require(value.get("state") in ALL_STATES, "NONCE_STATE_INVALID")
        _require(value.get("single_use") is True, "NONCE_NOT_SINGLE_USE")
        _require(value.get("max_provider_request_attempts") == 1, "NONCE_BUDGET_MISMATCH")
        _require(value.get("max_network_request_attempts") == 1, "NONCE_BUDGET_MISMATCH")
        _require(int(value.get("provider_dispatch_attempts", -1)) in {0, 1}, "NONCE_BUDGET_MISMATCH")
        _require(int(value.get("network_request_attempts", -1)) in {0, 1}, "NONCE_BUDGET_MISMATCH")
        for field in (
            "sample_lock_sha256",
            "parent_experiment_lock_sha256",
            "signed_approval_sha256",
            "model_input_component_binding_sha256",
            "route_fingerprint",
        ):
            _require(_HEX64.fullmatch(str(value.get(field))) is not None, f"{field.upper()}_INVALID")
        if schema == NONCE_SCHEMA_V2:
            for field in (
                "approved_destination_origin_sha256",
                "egress_policy_sha256",
            ):
                _require(
                    _HEX64.fullmatch(str(value.get(field))) is not None,
                    f"{field.upper()}_INVALID",
                )
            _require(
                isinstance(value.get("approved_destination_origin"), str)
                and str(value["approved_destination_origin"]).startswith("https://"),
                "NONCE_DESTINATION_ORIGIN_INVALID",
            )
            _require(
                isinstance(value.get("approved_destination_path_or_prefix"), str)
                and str(value["approved_destination_path_or_prefix"]).startswith("/"),
                "NONCE_DESTINATION_PATH_INVALID",
            )
            _require(value.get("cross_origin_redirect_allowed") is False, "CROSS_ORIGIN_REDIRECT")
            _require(value.get("unbound_proxy_route_allowed") is False, "UNBOUND_PROXY_ROUTE")
        _require(_HEX40.fullmatch(str(value.get("execution_head"))) is not None, "STALE_NONCE_HEAD")
        body = dict(value)
        digest = body.pop("nonce_receipt_sha256", None)
        domain = NONCE_DOMAIN_V2 if schema == NONCE_SCHEMA_V2 else NONCE_DOMAIN
        _require(digest == domain_sha256(domain, body), "NONCE_RECEIPT_SHA256_MISMATCH")
        return deepcopy(dict(value))

    @staticmethod
    def _exclusive_write(path: Path, value: Mapping[str, Any]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise SkillV3NonceStoreError("NONCE_REUSE") from exc
        try:
            os.write(descriptor, canonical_json_bytes(value) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _atomic_replace(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        DurablePilotNonceStoreV1._exclusive_write(temporary, value)
        os.replace(temporary, path)

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SkillV3NonceStoreError("NONCE_NOT_FOUND_OR_CORRUPT") from exc
        _require(isinstance(value, dict), "NONCE_NOT_FOUND_OR_CORRUPT")
        return self._validate(value)

    def reserve(
        self,
        *,
        pilot_id: str,
        sample_id: str,
        sample_lock_sha256: str,
        parent_experiment_lock_sha256: str,
        execution_head: str,
        approval_id: str,
        signed_approval_sha256: str,
        model_input_component_binding_sha256: str,
        route_fingerprint: str,
    ) -> dict[str, Any]:
        path = self._path(pilot_id, sample_id, approval_id)
        now = _utc_now()
        body = {
            "schema": NONCE_SCHEMA,
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "nonce_policy_version": NONCE_POLICY_VERSION,
            "nonce_id": f"sv3n-{secrets.token_hex(16)}",
            "pilot_id": pilot_id,
            "sample_id": sample_id,
            "sample_lock_sha256": sample_lock_sha256,
            "parent_experiment_lock_sha256": parent_experiment_lock_sha256,
            "execution_head": execution_head,
            "signed_approval_id": approval_id,
            "signed_approval_sha256": signed_approval_sha256,
            "model_input_component_binding_sha256": model_input_component_binding_sha256,
            "route_fingerprint": route_fingerprint,
            "max_provider_request_attempts": 1,
            "max_network_request_attempts": 1,
            "provider_dispatch_attempts": 0,
            "network_request_attempts": 0,
            "created_at": now,
            "reserved_at": now,
            "dispatch_attempted_at": None,
            "finalized_at": None,
            "state": "RESERVED",
            "single_use": True,
            "final_reason": None,
        }
        value = self._validate(self._seal(body))
        with self._locked():
            _require(not path.exists(), "NONCE_REUSE")
            self._exclusive_write(path, value)
        return value

    def reserve_destination_bound_v2(
        self,
        *,
        pilot_id: str,
        sample_id: str,
        sample_lock_sha256: str,
        parent_experiment_lock_sha256: str,
        execution_head: str,
        approval_id: str,
        signed_approval_sha256: str,
        model_input_component_binding_sha256: str,
        route_fingerprint: str,
        approved_destination_origin: str,
        approved_destination_origin_sha256: str,
        approved_destination_path_or_prefix: str,
        egress_policy_sha256: str,
        cross_origin_redirect_allowed: bool,
        unbound_proxy_route_allowed: bool,
    ) -> dict[str, Any]:
        path = self._path(pilot_id, sample_id, approval_id)
        now = _utc_now()
        body = {
            "schema": NONCE_SCHEMA_V2,
            "version": 2,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "nonce_policy_version": NONCE_POLICY_VERSION,
            "nonce_id": f"sv3n-{secrets.token_hex(16)}",
            "pilot_id": pilot_id,
            "sample_id": sample_id,
            "sample_lock_sha256": sample_lock_sha256,
            "parent_experiment_lock_sha256": parent_experiment_lock_sha256,
            "execution_head": execution_head,
            "signed_approval_id": approval_id,
            "signed_approval_sha256": signed_approval_sha256,
            "model_input_component_binding_sha256": model_input_component_binding_sha256,
            "route_fingerprint": route_fingerprint,
            "approved_destination_origin": approved_destination_origin,
            "approved_destination_origin_sha256": approved_destination_origin_sha256,
            "approved_destination_path_or_prefix": approved_destination_path_or_prefix,
            "egress_policy_sha256": egress_policy_sha256,
            "cross_origin_redirect_allowed": cross_origin_redirect_allowed,
            "unbound_proxy_route_allowed": unbound_proxy_route_allowed,
            "max_provider_request_attempts": 1,
            "max_network_request_attempts": 1,
            "provider_dispatch_attempts": 0,
            "network_request_attempts": 0,
            "created_at": now,
            "reserved_at": now,
            "dispatch_attempted_at": None,
            "finalized_at": None,
            "state": "RESERVED",
            "single_use": True,
            "final_reason": None,
        }
        value = self._validate(self._seal(body))
        with self._locked():
            _require(not path.exists(), "NONCE_REUSE")
            self._exclusive_write(path, value)
        return value

    def load(self, *, pilot_id: str, sample_id: str, approval_id: str) -> dict[str, Any]:
        value = self._read(self._path(pilot_id, sample_id, approval_id))
        _require(value.get("pilot_id") == pilot_id, "NONCE_FOR_WRONG_BINDING")
        _require(value.get("sample_id") == sample_id, "NONCE_FOR_WRONG_BINDING")
        _require(value.get("signed_approval_id") == approval_id, "NONCE_FOR_WRONG_BINDING")
        return value

    def is_reusable(self, *, pilot_id: str, sample_id: str, approval_id: str) -> bool:
        path = self._path(pilot_id, sample_id, approval_id)
        if not path.exists():
            return True
        self._read(path)
        return False

    def _transition(
        self,
        *,
        pilot_id: str,
        sample_id: str,
        approval_id: str,
        expected_nonce_id: str,
        allowed_states: set[str],
        new_state: str,
        provider_dispatch_attempts: int | None = None,
        network_request_attempts: int | None = None,
        final_reason: str | None = None,
    ) -> dict[str, Any]:
        path = self._path(pilot_id, sample_id, approval_id)
        with self._locked():
            value = self._read(path)
            _require(value.get("nonce_id") == expected_nonce_id, "NONCE_FOR_WRONG_BINDING")
            _require(value.get("state") in allowed_states, "NONCE_REUSE")
            body = dict(value)
            body.pop("nonce_receipt_sha256", None)
            body["state"] = new_state
            if provider_dispatch_attempts is not None:
                body["provider_dispatch_attempts"] = provider_dispatch_attempts
            if network_request_attempts is not None:
                body["network_request_attempts"] = network_request_attempts
            if new_state == "DISPATCH_ATTEMPTED":
                body["dispatch_attempted_at"] = _utc_now()
            if new_state in TERMINAL_STATES:
                body["finalized_at"] = _utc_now()
            body["final_reason"] = final_reason
            updated = self._validate(self._seal(body))
            self._atomic_replace(path, updated)
            return updated

    def mark_dispatch_attempt(
        self, *, pilot_id: str, sample_id: str, approval_id: str, nonce_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            pilot_id=pilot_id,
            sample_id=sample_id,
            approval_id=approval_id,
            expected_nonce_id=nonce_id,
            allowed_states={"RESERVED"},
            new_state="DISPATCH_ATTEMPTED",
            provider_dispatch_attempts=1,
        )

    def note_network_attempt(
        self, *, pilot_id: str, sample_id: str, approval_id: str, nonce_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            pilot_id=pilot_id,
            sample_id=sample_id,
            approval_id=approval_id,
            expected_nonce_id=nonce_id,
            allowed_states={"DISPATCH_ATTEMPTED"},
            new_state="DISPATCH_ATTEMPTED",
            provider_dispatch_attempts=1,
            network_request_attempts=1,
        )

    def consume(
        self, *, pilot_id: str, sample_id: str, approval_id: str, nonce_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            pilot_id=pilot_id,
            sample_id=sample_id,
            approval_id=approval_id,
            expected_nonce_id=nonce_id,
            allowed_states={"DISPATCH_ATTEMPTED"},
            new_state="CONSUMED",
            final_reason="SEALED_VALID",
        )

    def invalidate(
        self,
        *,
        pilot_id: str,
        sample_id: str,
        approval_id: str,
        nonce_id: str,
        reason: str,
        after_dispatch_attempt: bool,
    ) -> dict[str, Any]:
        return self._transition(
            pilot_id=pilot_id,
            sample_id=sample_id,
            approval_id=approval_id,
            expected_nonce_id=nonce_id,
            allowed_states={"DISPATCH_ATTEMPTED"} if after_dispatch_attempt else {"RESERVED"},
            new_state=(
                "INVALIDATED_FAILED_DISPATCH"
                if after_dispatch_attempt
                else "INVALIDATED_PRE_DISPATCH"
            ),
            final_reason=reason,
        )
