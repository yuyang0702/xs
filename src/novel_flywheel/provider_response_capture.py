"""Private, worktree-external exact Provider response capture and replay.

The capture format deliberately stores only response bytes plus hash-bound
execution metadata.  Request bodies, headers, credentials, and prompts are
not accepted by this boundary.  Captures are immutable and are never written
inside the Git worktree.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any, Collection, Iterator, Mapping

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


CAPTURE_SCHEMA = "ProviderResponseExactCaptureV1"
CAPTURE_MAGIC = b"NOVEL_FLYWHEEL_PROVIDER_RESPONSE_CAPTURE_V1\n"
PROVIDER_PROTOCOL_INPUT_BYTES = "PROVIDER_PROTOCOL_INPUT_BYTES_V1"
CONTRACT_RUNTIME_INPUT_BYTES = "CONTRACT_RUNTIME_INPUT_BYTES_V1"
CAPTURE_DOMAINS = frozenset({
    PROVIDER_PROTOCOL_INPUT_BYTES,
    CONTRACT_RUNTIME_INPUT_BYTES,
})
PRIVACY_CLASSIFICATION = "PRIVATE_PROVIDER_OUTPUT_EXTERNAL_ONLY"
PROVIDER_REPORTED_USAGE_SCHEMA = "ProviderReportedActualUsageV1"
PROHIBITED_METADATA_KEYS = frozenset({
    "authorization", "api_key", "credential", "headers", "prompt",
    "request_body", "story", "system", "tool_arguments", "user",
})
PUBLIC_METADATA_FIELDS = frozenset({
    "execution_id", "call_id", "stage_id", "provider_id_sha256",
    "model_id_sha256", "route_fingerprint", "protocol", "contract_name",
    "contract_version", "contract_schema_sha256", "adapter_id",
    "adapter_version", "content_type", "encoding", "transport_complete",
    "status_code", "http_success", "response_status_sha256",
})


class ProviderResponseCaptureError(RuntimeError):
    """Typed fail-closed response-capture or replay failure."""

    def __init__(self, message: str) -> None:
        self.reliability_failure = ReliabilityFailure(
            code="provider_response_capture_integrity_failure",
            failure_class=FailureClass.SYNTAX_PROTOCOL,
            boundary="provider_response_capture",
            message=message,
            retryable=False,
        )
        super().__init__(message)


class FullShortTransportEvidenceStateV1(StrEnum):
    COMPLETE_VALID_CAPTURE = "complete_valid_capture"
    EXPLICIT_PROVIDER_ERROR = "explicit_provider_error"
    PROVEN_PRE_RESPONSE_NON_COMPLETION = "proven_pre_response_non_completion"
    AMBIGUOUS_EXTERNAL_COMPLETION = "ambiguous_external_completion"


@dataclass(frozen=True)
class FullShortTransportRecoveryDecisionV1:
    state: FullShortTransportEvidenceStateV1
    action: str
    exact_local_replay_allowed: bool
    network_retry_allowed: bool = False
    physical_dispatch_delta: int = 0


def decide_full_short_transport_recovery_v1(
    state: FullShortTransportEvidenceStateV1 | str,
) -> FullShortTransportRecoveryDecisionV1:
    """Closed offline recovery policy for the single-use Full Short run.

    This policy never authorizes a network action.  A complete valid capture
    may be projected locally; every other state is classified or reconciled
    without consuming a nonce or creating another physical dispatch.
    """

    try:
        typed = FullShortTransportEvidenceStateV1(state)
    except ValueError as exc:
        raise ProviderResponseCaptureError(
            "FULL_SHORT_TRANSPORT_EVIDENCE_STATE_UNKNOWN"
        ) from exc
    actions = {
        FullShortTransportEvidenceStateV1.COMPLETE_VALID_CAPTURE:
            ("EXACT_LOCAL_REPLAY", True),
        FullShortTransportEvidenceStateV1.EXPLICIT_PROVIDER_ERROR:
            ("TERMINAL_TYPED_PROVIDER_FAILURE", False),
        FullShortTransportEvidenceStateV1.PROVEN_PRE_RESPONSE_NON_COMPLETION:
            ("TERMINAL_NO_CURRENT_AUTHORITY_FOR_REDISPATCH", False),
        FullShortTransportEvidenceStateV1.AMBIGUOUS_EXTERNAL_COMPLETION:
            ("FAIL_CLOSED_RECONCILIATION_ONLY", False),
    }
    action, replay = actions[typed]
    return FullShortTransportRecoveryDecisionV1(
        state=typed, action=action, exact_local_replay_allowed=replay,
    )


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_public_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(metadata)
    lowered = {str(key).lower() for key in value}
    forbidden = sorted(lowered & PROHIBITED_METADATA_KEYS)
    if forbidden:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_CAPTURE_PROHIBITED_METADATA:" + ",".join(forbidden)
        )
    unknown = sorted(set(value) - PUBLIC_METADATA_FIELDS)
    missing = sorted(PUBLIC_METADATA_FIELDS - set(value))
    if unknown:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_CAPTURE_METADATA_FIELD_UNKNOWN:"
            + ",".join(unknown)
        )
    if missing:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_CAPTURE_METADATA_FIELD_MISSING:"
            + ",".join(missing)
        )
    required_strings = (
        "execution_id", "call_id", "stage_id", "provider_id_sha256",
        "model_id_sha256", "route_fingerprint", "protocol",
        "contract_name", "contract_schema_sha256", "adapter_id",
        "content_type", "encoding",
    )
    for field in required_strings:
        if not isinstance(value.get(field), str) or not value[field]:
            raise ProviderResponseCaptureError(
                f"PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID:{field}"
            )
    for field in (
        "provider_id_sha256", "model_id_sha256", "route_fingerprint",
        "contract_schema_sha256",
    ):
        if len(value[field]) != 64 or any(c not in "0123456789abcdef" for c in value[field]):
            raise ProviderResponseCaptureError(
                f"PROVIDER_RESPONSE_CAPTURE_HASH_INVALID:{field}"
            )
    for field in ("contract_version", "adapter_version"):
        if type(value.get(field)) is not int or value[field] < 1:
            raise ProviderResponseCaptureError(
                f"PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID:{field}"
            )
    if type(value.get("transport_complete")) is not bool:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID:transport_complete"
        )
    status_code = value.get("status_code")
    http_success = value.get("http_success")
    status_sha256 = value.get("response_status_sha256")
    if status_code is None or http_success is None or status_sha256 is None:
        if not (
            status_code is None
            and http_success is None
            and status_sha256 is None
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_INCOMPLETE"
            )
    else:
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID:status_code"
            )
        if type(http_success) is not bool:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID:http_success"
            )
        if http_success is not (200 <= status_code < 300):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_MISMATCH"
            )
        expected_status_sha256 = _sha256(str(status_code).encode("ascii"))
        if status_sha256 != expected_status_sha256:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_STATUS_SHA256_MISMATCH"
            )
    return value


@dataclass(frozen=True)
class ProviderResponseCaptureReceiptV1:
    byte_domain: str
    byte_sha256: str
    byte_length: int
    metadata_sha256: str
    capture_path_sha256: str
    privacy_classification: str = PRIVACY_CLASSIFICATION

    def document(self) -> dict[str, Any]:
        return {
            "schema": "ProviderResponseCaptureReceiptV1",
            "version": 1,
            "byte_domain": self.byte_domain,
            "byte_sha256": self.byte_sha256,
            "byte_length": self.byte_length,
            "metadata_sha256": self.metadata_sha256,
            "capture_path_sha256": self.capture_path_sha256,
            "privacy_classification": self.privacy_classification,
            "raw_bytes_persisted_outside_worktree": True,
            "request_headers_persisted": False,
            "credentials_persisted": False,
            "request_prompt_persisted": False,
        }


class ProviderResponseCaptureStoreV1:
    """Crash-safe, exclusive-create exact response storage."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        requested = Path(os.path.abspath(store_root))
        if _inside(requested, self.repo_root):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_STORE_INSIDE_WORKTREE"
            )
        requested.mkdir(parents=True, exist_ok=True)
        self.root = requested.resolve(strict=True)
        if os.path.normcase(str(self.root)) != os.path.normcase(str(requested)):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_STORE_PATH_NOT_EXACT"
            )
        self.execution_store_root = (
            self.root.parent
            if self.root.name == "provider-response-captures-v1"
            else None
        )

    @contextmanager
    def _execution_store_locked(self) -> Iterator[None]:
        if self.execution_store_root is None:
            yield
            return
        lock_path = self.execution_store_root / ".full-short-execution.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_EXECUTION_STORE_BUSY"
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _completion_exists(self, execution_id: str) -> bool:
        if self.execution_store_root is None:
            return False
        key = domain_sha256(
            "full-short-execution-storage-key-v1", execution_id,
        )
        return (self.execution_store_root / f"{key}.completion.json").exists()

    @staticmethod
    def _capture_key(metadata: Mapping[str, Any], byte_domain: str) -> str:
        identity = {
            key: metadata[key] for key in (
                "execution_id", "call_id", "stage_id", "provider_id_sha256",
                "model_id_sha256", "route_fingerprint", "protocol",
                "contract_name", "contract_version", "contract_schema_sha256",
                "adapter_id", "adapter_version",
            )
        }
        identity["byte_domain"] = byte_domain
        return _sha256(_canonical_json_bytes(identity))

    def _path(self, metadata: Mapping[str, Any], byte_domain: str) -> Path:
        return self.root / f"{self._capture_key(metadata, byte_domain)}.capture"

    @staticmethod
    def _write_exclusive_crash_safe(path: Path, payload: bytes) -> None:
        from novel_flywheel.storage import _windows_extended_path

        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        system_temporary = _windows_extended_path(temporary)
        system_path = _windows_extended_path(path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(system_temporary, flags, 0o600)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise ProviderResponseCaptureError(
                        "PROVIDER_RESPONSE_CAPTURE_DURABLE_WRITE_NO_PROGRESS"
                    )
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            # Hard-link publication is atomic and refuses to replace a prior
            # capture.  The temporary is fully flushed before it becomes live.
            os.link(system_temporary, system_path)
        except FileExistsError as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_DUPLICATE"
            ) from exc
        finally:
            try:
                system_temporary.unlink()
            except FileNotFoundError:
                pass

    def capture(
        self, *, byte_domain: str, data: bytes,
        metadata: Mapping[str, Any],
    ) -> ProviderResponseCaptureReceiptV1:
        if byte_domain not in CAPTURE_DOMAINS:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_DOMAIN_INVALID"
            )
        if not isinstance(data, bytes):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_BYTES_REQUIRED"
            )
        public = _validate_public_metadata(metadata)
        if byte_domain == PROVIDER_PROTOCOL_INPUT_BYTES and (
            public["status_code"] is None
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_REQUIRED"
            )
        with self._execution_store_locked():
            if self._completion_exists(str(public["execution_id"])):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_EXECUTION_ALREADY_COMPLETED"
                )
            header = {
                "schema": CAPTURE_SCHEMA,
                "version": 1,
                "byte_domain": byte_domain,
                **public,
                "byte_sha256": _sha256(data),
                "byte_length": len(data),
                "privacy_classification": PRIVACY_CLASSIFICATION,
                "request_headers_persisted": False,
                "credentials_persisted": False,
                "request_prompt_persisted": False,
                "created_at": datetime.now(timezone.utc).replace(
                    microsecond=0,
                ).isoformat().replace("+00:00", "Z"),
            }
            header_bytes = _canonical_json_bytes(header)
            path = self._path(public, byte_domain)
            self._write_exclusive_crash_safe(
                path, CAPTURE_MAGIC + header_bytes + b"\n" + data,
            )
        return ProviderResponseCaptureReceiptV1(
            byte_domain=byte_domain,
            byte_sha256=header["byte_sha256"],
            byte_length=header["byte_length"],
            metadata_sha256=_sha256(header_bytes),
            capture_path_sha256=_sha256(str(path).encode("utf-8")),
        )

    def replay(
        self, *, byte_domain: str, expected_metadata: Mapping[str, Any],
        expected_receipt_sha256: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Authoritatively replay bytes bound by an external receipt hash.

        The capture envelope is deliberately not its own integrity authority:
        an attacker able to replace the file can rewrite both its header and
        bytes consistently.  Therefore every replay requires a receipt hash
        obtained from an independent ledger/attestation boundary.
        """

        if (
            not isinstance(expected_receipt_sha256, str)
            or len(expected_receipt_sha256) != 64
            or any(
                char not in "0123456789abcdef"
                for char in expected_receipt_sha256
            )
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_EXTERNAL_ANCHOR_REQUIRED"
            )
        if byte_domain not in CAPTURE_DOMAINS:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_DOMAIN_INVALID"
            )
        expected = _validate_public_metadata(expected_metadata)
        if byte_domain == PROVIDER_PROTOCOL_INPUT_BYTES and (
            expected["status_code"] is None
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_HTTP_CLASSIFICATION_REQUIRED"
            )
        path = self._path(expected, byte_domain)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_CAPTURE_MISSING"
            ) from exc
        if not payload.startswith(CAPTURE_MAGIC):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_MAGIC_MISMATCH"
            )
        try:
            header_bytes, data = payload[len(CAPTURE_MAGIC):].split(b"\n", 1)
            header = json.loads(header_bytes.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_ENVELOPE_CORRUPT"
            ) from exc
        if not isinstance(header, dict):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_ENVELOPE_CORRUPT"
            )
        for key, value in expected.items():
            if header.get(key) != value:
                raise ProviderResponseCaptureError(
                    f"PROVIDER_RESPONSE_REPLAY_METADATA_MISMATCH:{key}"
                )
        if header.get("schema") != CAPTURE_SCHEMA or header.get("version") != 1:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_SCHEMA_MISMATCH"
            )
        if header.get("byte_domain") != byte_domain:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_DOMAIN_MISMATCH"
            )
        if header.get("byte_length") != len(data):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_LENGTH_MISMATCH"
            )
        if header.get("byte_sha256") != _sha256(data):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_SHA256_MISMATCH"
            )
        receipt = ProviderResponseCaptureReceiptV1(
            byte_domain=byte_domain,
            byte_sha256=str(header["byte_sha256"]),
            byte_length=int(header["byte_length"]),
            metadata_sha256=_sha256(header_bytes),
            capture_path_sha256=_sha256(str(path).encode("utf-8")),
        )
        ledger_receipt_sha256 = domain_sha256(
            "novel-flywheel-provider-response-capture-receipt-v1",
            receipt.document(),
        )
        if expected_receipt_sha256 != ledger_receipt_sha256:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_LEDGER_RECEIPT_MISMATCH"
            )
        header["ledger_receipt_sha256"] = ledger_receipt_sha256
        header["integrity_authority"] = "EXTERNAL_RECEIPT_ANCHORED"
        header["authoritative"] = True
        return data, header

    def inspect_all_unanchored(self) -> list[dict[str, Any]]:
        """Inspect internal consistency only; results are non-authoritative.

        This is useful for orphan discovery and diagnostics, but it cannot
        establish that the capture was not replaced with a self-consistent
        rewritten envelope.  Production replay, accounting, and completion
        callers must use :meth:`audit_all` with external receipt anchors.
        """

        receipts: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.capture")):
            try:
                payload = path.read_bytes()
                header_bytes, data = payload[len(CAPTURE_MAGIC):].split(b"\n", 1)
                header = json.loads(header_bytes.decode("utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_ENVELOPE_CORRUPT"
                ) from exc
            if not payload.startswith(CAPTURE_MAGIC) or not isinstance(header, dict):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_ENVELOPE_CORRUPT"
                )
            domain = str(header.get("byte_domain") or "")
            metadata = {
                key: header.get(key) for key in (
                    "execution_id", "call_id", "stage_id",
                    "provider_id_sha256", "model_id_sha256",
                    "route_fingerprint", "protocol", "contract_name",
                    "contract_version", "contract_schema_sha256",
                    "adapter_id", "adapter_version", "content_type",
                    "encoding", "transport_complete", "status_code",
                    "http_success", "response_status_sha256",
                )
            }
            _validate_public_metadata(metadata)
            if domain == PROVIDER_PROTOCOL_INPUT_BYTES and (
                metadata["status_code"] is None
            ):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_HTTP_CLASSIFICATION_REQUIRED"
                )
            if domain not in CAPTURE_DOMAINS:
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_DOMAIN_INVALID"
                )
            if path != self._path(metadata, domain):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_IDENTITY_MISMATCH"
                )
            if header.get("schema") != CAPTURE_SCHEMA or header.get("version") != 1:
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_SCHEMA_MISMATCH"
                )
            if header.get("byte_length") != len(data):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_LENGTH_MISMATCH"
                )
            if header.get("byte_sha256") != _sha256(data):
                raise ProviderResponseCaptureError(
                    "PROVIDER_RESPONSE_CAPTURE_AUDIT_SHA256_MISMATCH"
                )
            receipts.append({
                "integrity_authority": "UNANCHORED_NON_AUTHORITATIVE_INSPECTION",
                "authoritative": False,
                "byte_domain": domain,
                "byte_sha256": header["byte_sha256"],
                "byte_length": header["byte_length"],
                "metadata_sha256": _sha256(header_bytes),
                "capture_path_sha256": _sha256(str(path).encode("utf-8")),
                "execution_id": metadata["execution_id"],
                "call_id": metadata["call_id"],
                "stage_id": metadata["stage_id"],
                "transport_complete": metadata["transport_complete"],
                "metadata": metadata,
                "ledger_receipt_sha256": domain_sha256(
                    "novel-flywheel-provider-response-capture-receipt-v1",
                    ProviderResponseCaptureReceiptV1(
                        byte_domain=domain,
                        byte_sha256=str(header["byte_sha256"]),
                        byte_length=int(header["byte_length"]),
                        metadata_sha256=_sha256(header_bytes),
                        capture_path_sha256=_sha256(
                            str(path).encode("utf-8")
                        ),
                    ).document(),
                ),
            })
        return receipts

    def audit_all(
        self, *, expected_receipt_sha256s: Collection[str],
    ) -> list[dict[str, Any]]:
        """Authoritatively audit all captures against external anchors.

        Exact set equality is intentional: an unanchored extra capture is an
        integrity failure, not something an authoritative caller may ignore.
        """

        if isinstance(expected_receipt_sha256s, (str, bytes)):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_AUDIT_EXTERNAL_ANCHORS_REQUIRED"
            )
        expected = list(expected_receipt_sha256s)
        if (
            len(set(expected)) != len(expected)
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in expected
            )
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_AUDIT_EXTERNAL_ANCHORS_REQUIRED"
            )
        inspected = self.inspect_all_unanchored()
        actual = [item["ledger_receipt_sha256"] for item in inspected]
        if set(actual) != set(expected) or len(actual) != len(expected):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_AUDIT_EXTERNAL_ANCHOR_MISMATCH"
            )
        return [
            {
                **item,
                "integrity_authority": "EXTERNAL_RECEIPT_ANCHORED",
                "authoritative": True,
            }
            for item in inspected
        ]


def parse_provider_protocol_input_bytes_v1(
    data: bytes, *, content_type: str, encoding: str = "utf-8",
    anthropic_errors: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse exact captured HTTP entity bytes at the production protocol seam."""

    if "text/event-stream" in content_type.lower():
        if anthropic_errors:
            from novel_flywheel.anthropic_stream import (
                aggregate_events, decode_sse, InvalidFrame,
            )
            events = decode_sse(data, encoding=encoding)
            # Surface framing faults through the original public typed API.
            # Ordered terminal precedence is decided exclusively by the owner.
            if any(isinstance(event, InvalidFrame) for event in events):
                outcome = aggregate_events(events)
                if isinstance(outcome.primary, ProviderResponseCaptureError):
                    raise outcome.primary
            return events, None
        try:
            text = data.decode(encoding)
        except (LookupError, UnicodeError) as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID"
            ) from exc
        events, _done_seen = _parse_sse_events_v1(text)
        return events, None
    try:
        text = data.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID"
        ) from exc
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_REPLAY_JSON_INVALID"
        ) from exc
    if not isinstance(value, dict):
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_REPLAY_JSON_OBJECT_REQUIRED"
        )
    return [], value


def _parse_sse_events_v1(
    text: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse only delimiter-closed SSE events and retain the DONE terminal."""

    events: list[dict[str, Any]] = []
    data_lines: list[str] = []
    done_seen = False

    def dispatch() -> None:
        nonlocal done_seen
        raw = "\n".join(data_lines)
        data_lines.clear()
        if done_seen:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_SSE_EVENT_AFTER_DONE"
            )
        if raw == "[DONE]":
            done_seen = True
            return
        try:
            event = json.loads(raw)
        except ValueError as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_SSE_JSON_INVALID"
            ) from exc
        if not isinstance(event, dict):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_SSE_OBJECT_REQUIRED"
            )
        events.append(event)

    for line in text.splitlines():
        if not line:
            if data_lines:
                dispatch()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DELIMITER_MISSING"
        )
    return events, done_seen


def provider_protocol_input_has_terminal_bytes_v1(
    data: bytes, *, content_type: str, encoding: str = "utf-8",
) -> bool:
    """Return whether interrupted SSE bytes contain a closed terminal frame.

    This is deliberately SSE-only: a parseable JSON prefix is not proof that
    an interrupted HTTP entity had no remaining bytes.
    """

    if "text/event-stream" not in content_type.lower():
        return False
    try:
        text = data.decode(encoding)
        events, done_seen = _parse_sse_events_v1(text)
    except (LookupError, UnicodeError, ProviderResponseCaptureError):
        return False
    if done_seen:
        return True
    if not events:
        return False
    terminal_type = events[-1].get("type")
    if terminal_type == "ping":
        # Only Anthropic's message_stop admits a trailing keepalive suffix.
        # This is a byte-completeness hint; the adapter still validates the
        # entire semantic sequence before any local recovery can succeed.
        index = len(events) - 1
        while index >= 0 and events[index].get("type") == "ping":
            index -= 1
        return index >= 0 and events[index].get("type") == "message_stop"
    return terminal_type in {
        "error",
        "message_stop",
        "response.completed",
        "response.failed",
        "response.incomplete",
    }


def _usage_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ProviderResponseCaptureError(
            f"PROVIDER_REPORTED_USAGE_FIELD_INVALID:{field}"
        )
    return value


def _aliased_usage_int(
    usage: Mapping[str, Any], *, primary: str, alias: str,
) -> int | None:
    values = []
    for field in (primary, alias):
        if field in usage:
            values.append(_usage_int(usage[field], field=field))
    if not values:
        return None
    if len(set(values)) != 1:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_ALIAS_CONFLICT"
        )
    return values[0]


ANTHROPIC_USAGE_COUNTER_FIELDS_V1 = (
    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    "output_tokens",
)


def merge_anthropic_usage_snapshot_v1(
    snapshot: Mapping[str, int], usage: Mapping[str, Any],
) -> dict[str, int]:
    """Replace protocol-owned cumulative counters, retaining omitted optionals.

    Anthropic SDK 62de60b27d04f0927a0ccf0f2610597fafcfab6a,
    lib/streaming/_messages.py:520-534. Cache counters must merge before input
    summation. Relay extensions and nested billing aliases have no authority.
    Missing output retains the existing compatible-adapter behavior; explicit
    null output remains invalid (the official delta schema requires an int).
    """
    if not isinstance(usage, Mapping):
        raise ProviderResponseCaptureError("PROVIDER_REPORTED_USAGE_OBJECT_INVALID")
    result = dict(snapshot)
    for field in ANTHROPIC_USAGE_COUNTER_FIELDS_V1:
        if field not in usage:
            continue
        if usage[field] is None and field != "output_tokens":
            continue
        result[field] = _usage_int(usage[field], field=field)
    return result


def canonical_anthropic_usage_v1(
    usage: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    snapshot = merge_anthropic_usage_snapshot_v1({}, usage)
    inputs = [snapshot[field] for field in ANTHROPIC_USAGE_COUNTER_FIELDS_V1[:-1]
              if field in snapshot]
    return (sum(inputs) if inputs else None, snapshot.get("output_tokens"))


def _canonical_usage_sample_v1(
    protocol: str, usage: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    """Project a protocol-owned usage object without scanning arbitrary JSON."""

    if protocol == "anthropic":
        return canonical_anthropic_usage_v1(usage)
    if protocol == "openai-chat":
        return (
            _aliased_usage_int(
                usage, primary="prompt_tokens", alias="input_tokens",
            ),
            _aliased_usage_int(
                usage, primary="completion_tokens", alias="output_tokens",
            ),
        )
    if protocol == "openai-responses":
        return (
            _aliased_usage_int(
                usage, primary="input_tokens", alias="prompt_tokens",
            ),
            _aliased_usage_int(
                usage, primary="output_tokens", alias="completion_tokens",
            ),
        )
    raise ProviderResponseCaptureError(
        "PROVIDER_REPORTED_USAGE_PROTOCOL_UNSUPPORTED"
    )


def extract_provider_reported_actual_usage_v1(
    data: bytes, *, protocol: str, content_type: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Derive actual token usage from one exact captured Provider entity.

    Only closed protocol-owned usage locations are considered. Anthropic SSE
    counters are cumulative snapshot replacements; OpenAI validation remains
    independent. The entity must include a closed terminal frame. The receipt's
    existing byte hash and source topologies retain exact lineage authority.
    """

    canonical_protocol = str(protocol).strip().casefold().replace("_", "-")
    if canonical_protocol not in {
        "anthropic", "openai-chat", "openai-responses",
    }:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_PROTOCOL_UNSUPPORTED"
        )
    events, document = parse_provider_protocol_input_bytes_v1(
        data, content_type=content_type, encoding=encoding,
        anthropic_errors=canonical_protocol == "anthropic",
    )
    is_sse = "text/event-stream" in content_type.lower()
    if is_sse and canonical_protocol != "anthropic" and not provider_protocol_input_has_terminal_bytes_v1(
        data, content_type=content_type, encoding=encoding,
    ):
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_SSE_TERMINAL_MISSING"
        )
    containers: list[tuple[str, Mapping[str, Any]]] = []
    values = events if is_sse else [document]
    if canonical_protocol == "anthropic" and is_sse:
        from novel_flywheel.anthropic_stream import usage_containers
        containers = usage_containers(events)
        values = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            continue
        direct = value.get("usage")
        if isinstance(direct, Mapping):
            containers.append((f"event[{index}].usage", direct))
        if canonical_protocol == "anthropic":
            message = value.get("message")
            nested = message.get("usage") if isinstance(message, Mapping) else None
            if isinstance(nested, Mapping):
                containers.append((f"event[{index}].message.usage", nested))
        if canonical_protocol == "openai-responses":
            response = value.get("response")
            nested = response.get("usage") if isinstance(response, Mapping) else None
            if isinstance(nested, Mapping):
                containers.append((f"event[{index}].response.usage", nested))
    if not containers:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_MISSING"
        )
    samples: list[tuple[str, int | None, int | None]] = []
    anthropic_snapshot: dict[str, int] = {}
    for topology, usage in containers:
        if canonical_protocol == "anthropic":
            update = merge_anthropic_usage_snapshot_v1({}, usage)
            anthropic_snapshot = merge_anthropic_usage_snapshot_v1(
                anthropic_snapshot, usage,
            )
            if not update:
                continue
            usage = anthropic_snapshot
        input_tokens, output_tokens = _canonical_usage_sample_v1(
            canonical_protocol, usage,
        )
        if input_tokens is not None or output_tokens is not None:
            samples.append((topology, input_tokens, output_tokens))
    if not samples:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_MISSING"
        )
    input_samples = [item[1] for item in samples if item[1] is not None]
    output_samples = [item[2] for item in samples if item[2] is not None]
    if not input_samples or not output_samples:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_INCOMPLETE"
        )
    if canonical_protocol != "anthropic" and len(set(input_samples)) != 1:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_INPUT_CONFLICT"
        )
    if canonical_protocol != "anthropic" and output_samples != sorted(output_samples):
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_OUTPUT_NON_MONOTONIC"
        )
    input_tokens = input_samples[-1]
    output_tokens = output_samples[-1]
    if input_tokens <= 0 or output_tokens <= 0:
        raise ProviderResponseCaptureError(
            "PROVIDER_REPORTED_USAGE_NOT_POSITIVE"
        )
    body = {
        "schema": PROVIDER_REPORTED_USAGE_SCHEMA,
        "version": 1,
        "protocol": canonical_protocol,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "provider_entity_sha256": _sha256(data),
        "source_topologies": [item[0] for item in samples],
        "usage_record_count": len(samples),
    }
    return {
        **body,
        "usage_receipt_sha256": domain_sha256(
            "novel-flywheel-provider-reported-actual-usage-v1", body,
        ),
    }
import base64
import inspect
import re
from urllib.parse import urlsplit
class ReviewDiagnosticCaptureScopeError(RuntimeError):
    """Fail-closed local scope/preflight error for the review observer.

    This is deliberately distinct from ``ProviderResponseCaptureError``:
    scope and dispatch-guard checks happen before a Provider response exists,
    so they must not be classified as malformed Provider or generated-artifact
    output.  The reliability boundary identifies the local observer as the
    owner and forbids a redispatch.
    """

    def __init__(self, message: str) -> None:
        self.code = "review_diagnostic_capture_scope_failure"
        self.provider_call_executed = False
        self.reliability_failure = ReliabilityFailure(
            code=self.code,
            failure_class=FailureClass.UNKNOWN,
            boundary="review_diagnostic_capture.observer_scope",
            message=message,
            retryable=False,
        )
        super().__init__(message)


class ReviewDiagnosticCaptureObserverV1:
    """One-call, task-scoped diagnostic capture for a formal Review attempt.

    This observer is deliberately separate from the production receipt ledger:
    it stores the exact serialized request and a redacted response projection
    in the user-authorized evidence directory, while the normal workflow and
    qualification decisions remain authoritative.  It never stores headers,
    credentials, cookies, or hidden reasoning content.
    """

    _FORBIDDEN_KEYS = frozenset({
        "authorization", "api_key", "apikey", "cookie", "headers",
        "credential", "credentials",
    })
    _REASONING_KEYS = frozenset({
        "analysis", "reasoning", "thinking", "encrypted_content",
    })

    def __init__(
        self, *, store_root: Path, provider_id: str, model_id: str,
        hostname: str, context: Mapping[str, Any] | None = None,
    ) -> None:
        root = Path(os.path.abspath(store_root))
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        self.provider_id = str(provider_id)
        self.model_id = str(model_id)
        if isinstance(hostname, str):
            hostnames = [item.strip().lower() for item in hostname.split(",")]
        else:
            hostnames = [str(item).strip().lower() for item in hostname]
        self._hostnames = frozenset(item for item in hostnames if item)
        if not self._hostnames:
            raise ValueError("at least one capture hostname is required")
        self.hostname = sorted(self._hostnames)[0]
        self.context = dict(context or {})
        self.stage_context: dict[str, Any] | None = None
        self._scope_active = False
        # Route resolution is also used by capacity/qualification preflight.
        # That lookup happens before the native Review contract is bound, so
        # keep the identity hash-only until the formal stage context exists.
        # It is never persisted or treated as a dispatch.
        self._pending_route: dict[str, Any] | None = None
        self.bound_route: dict[str, Any] | None = None
        self.bound_request: dict[str, Any] | None = None
        self.dispatch_count = 0
        self.response_count = 0
        self.runtime_input_count = 0
        self._event_index = 0
        self._write_json("00-context.json", {
            "schema": "ReviewDiagnosticCaptureContextV1",
            "version": 1,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "hostname": self.hostname,
            "context": self._safe_value(self.context),
        })

    @staticmethod
    def _safe_value(value: Any) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, child in value.items():
                key_text = str(key)
                if key_text.casefold() in ReviewDiagnosticCaptureObserverV1._FORBIDDEN_KEYS:
                    continue
                result[key_text] = ReviewDiagnosticCaptureObserverV1._safe_value(child)
            return result
        if isinstance(value, (list, tuple)):
            return [ReviewDiagnosticCaptureObserverV1._safe_value(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _redact_reasoning(value: Any) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            item_type = str(value.get("type") or "").casefold()
            hidden_item = item_type in {"reasoning", "thinking", "analysis"}
            for key, child in value.items():
                key_text = str(key)
                if key_text.casefold() in ReviewDiagnosticCaptureObserverV1._FORBIDDEN_KEYS:
                    continue
                if hidden_item or key_text.casefold() in ReviewDiagnosticCaptureObserverV1._REASONING_KEYS:
                    raw = json.dumps(child, ensure_ascii=False, sort_keys=True)
                    result[key_text] = {
                        "redacted": True,
                        "sha256": _sha256(raw.encode("utf-8")),
                        "length": len(raw),
                    }
                else:
                    result[key_text] = ReviewDiagnosticCaptureObserverV1._redact_reasoning(child)
            if hidden_item:
                result["hidden_content_redacted"] = True
            return result
        if isinstance(value, (list, tuple)):
            return [ReviewDiagnosticCaptureObserverV1._redact_reasoning(item) for item in value]
        return value

    def _write_exclusive(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_CAPTURE_DUPLICATE"
            )
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_bytes(payload)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)
        return path

    def _write_json(self, name: str, value: Mapping[str, Any]) -> Path:
        body = json.dumps(
            self._safe_value(value), ensure_ascii=False, sort_keys=True,
            indent=2, allow_nan=False,
        ).encode("utf-8")
        return self._write_exclusive(name, body + b"\n")

    def _event(self, kind: str, value: Mapping[str, Any]) -> None:
        self._event_index += 1
        self._write_json(
            f"events/{self._event_index:03d}-{kind}.json",
            {"schema": "ReviewDiagnosticEventV1", "kind": kind, **dict(value)},
        )

    def bind_stage_context(
        self, *, stage_id: str, contract_name: str, contract_version: int,
        contract_schema_sha256: str,
        contract_runtime_input_required: bool = False,
        contract_attempt_index: int | None = None,
        contract_route: str | None = None,
        contract_route_attempt: int | None = None,
        stage_role: str = "NORMAL",
    ) -> None:
        """Bind the formal Review contract before route resolution.

        The canary installs this observer on the shared registry, so route
        identity alone is insufficient to scope a capture.  Only the native
        semantic receipt contracts are eligible; every other contract fails
        closed before credential lookup or network dispatch.
        """

        target_contracts = frozenset({
            "draft_atomic_semantic_receipt",
            "draft_segment_semantic_receipt",
        })
        if str(contract_name) not in target_contracts:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_NON_TARGET_CONTRACT"
            )
        if type(contract_version) is not int or contract_version < 1:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_CONTRACT_VERSION_INVALID"
            )
        if (
            not isinstance(contract_schema_sha256, str)
            or len(contract_schema_sha256) != 64
            or any(c not in "0123456789abcdef" for c in contract_schema_sha256)
        ):
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_CONTRACT_SCHEMA_INVALID"
            )
        self.stage_context = {
            "stage_id": str(stage_id),
            "contract_name": str(contract_name),
            "contract_version": contract_version,
            "contract_schema_sha256": contract_schema_sha256,
            "contract_runtime_input_required": bool(
                contract_runtime_input_required
            ),
            "contract_attempt_index": contract_attempt_index,
            "contract_route": contract_route,
            "contract_route_attempt": contract_route_attempt,
            "stage_role": str(stage_role),
        }
        self._scope_active = True
        self._event("stage-context", self.stage_context)
        if self._pending_route is not None:
            pending = self._pending_route
            self._pending_route = None
            self.bind_route(**pending)

    def bind_route(
        self, *, role: str, lane: str, provider_id: str, model_id: str,
        route_fingerprint: str,
    ) -> None:
        if not self._scope_active:
            # ProviderRegistry.resolve is legitimately called during local
            # preflight.  Defer the binding until bind_stage_context proves
            # this is one of the explicitly scoped Review contracts.
            pending = {
                "role": str(role), "lane": str(lane),
                "provider_id": str(provider_id), "model_id": str(model_id),
                "route_fingerprint": str(route_fingerprint),
            }
            if self._pending_route is None:
                self._pending_route = pending
                return
            identity_keys = ("role", "lane", "provider_id", "model_id")
            if any(
                self._pending_route.get(key) != pending.get(key)
                for key in identity_keys
            ):
                # Capacity preflight may inspect the configured fallback after
                # the primary route.  Neither lookup is a dispatch.  Retain
                # the first route; the actual request resolves again after
                # stage binding and is checked fail-closed there.
                return
            if self._pending_route.get("route_fingerprint") != pending[
                "route_fingerprint"
            ]:
                self._pending_route = pending
            return
        route = {
            "role": str(role), "lane": str(lane),
            "provider_id": str(provider_id), "model_id": str(model_id),
            "route_fingerprint": str(route_fingerprint),
        }
        if (
            self.bound_route is None
            and (
                route["provider_id"] != self.provider_id
                or route["model_id"] != self.model_id
            )
        ):
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_ROUTE_MISMATCH"
            )
        if (
            self.bound_route is not None
            and (
                self.bound_route.get("provider_id") != route["provider_id"]
                or self.bound_route.get("model_id") != route["model_id"]
            )
        ):
            same_review_role = (
                self.bound_route.get("role") == route["role"] == "review"
            )
            allowed_lane_transition = (
                self.bound_route.get("lane") == "primary"
                and route["lane"] in {"fallback", "configured_fallback"}
                and self.stage_context is not None
                and self.stage_context.get("contract_route") in {
                    "fallback", "configured_fallback",
                }
            )
            if self.dispatch_count == 0 and same_review_role and allowed_lane_transition:
                self._event(
                    "route-rebind",
                    {
                        "previous": dict(self.bound_route),
                        "current": dict(route),
                        "reason": "pre_dispatch_fallback",
                    },
                )
                self.bound_route = route
                self.provider_id = route["provider_id"]
                self.model_id = route["model_id"]
            else:
                raise ReviewDiagnosticCaptureScopeError(
                    "REVIEW_DIAGNOSTIC_ROUTE_MISMATCH"
                    if self.dispatch_count
                    else "REVIEW_DIAGNOSTIC_ROUTE_DRIFT"
                )
        if self.bound_route is not None:
            identity_keys = ("role", "lane", "provider_id", "model_id")
            if any(self.bound_route.get(key) != route.get(key) for key in identity_keys):
                raise ReviewDiagnosticCaptureScopeError(
                    "REVIEW_DIAGNOSTIC_ROUTE_DRIFT"
                )
            if self.bound_route.get("route_fingerprint") != route["route_fingerprint"]:
                self._event(
                    "route-rebind",
                    {"previous": dict(self.bound_route), "current": dict(route)},
                )
                self.bound_route = route
            return
        self.bound_route = route
        self._write_json("01-route.json", self.bound_route)

    def bind_model_request(self, *, protocol: str, request: Any) -> None:
        if not self._scope_active:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_STAGE_CONTEXT_MISSING"
            )
        model_dump = getattr(request, "model_dump", None)
        value = model_dump(mode="json") if callable(model_dump) else dict(request)
        self.bound_request = {
            "protocol": str(protocol), "request": self._safe_value(value),
        }
        self._write_json("02-model-request.json", self.bound_request)

    def before_http_dispatch(
        self, *, method: str, url: str, payload: Mapping[str, Any],
        request_bytes: bytes | None = None,
    ) -> None:
        if not self._scope_active:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_STAGE_CONTEXT_MISSING"
            )
        if self.dispatch_count:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_SECOND_DISPATCH"
            )
        if method != "POST" or urlsplit(url).hostname not in self._hostnames:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_DESTINATION_MISMATCH"
            )
        if not isinstance(request_bytes, bytes):
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_REQUEST_BYTES_MISSING"
            )
        parsed = json.loads(request_bytes.decode("utf-8"))
        if not isinstance(parsed, Mapping) or dict(parsed) != dict(payload):
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_REQUEST_BYTES_DRIFT"
            )
        if str(payload.get("model") or "") == "":
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_WIRE_MODEL_MISSING"
            )
        self.dispatch_count = 1
        self._write_exclusive("10-request.json", json.dumps({
            "schema": "ReviewDiagnosticWireRequestV1", "method": method,
            "url": url, "payload_sha256": _sha256(request_bytes),
            "payload_bytes_base64": base64.b64encode(request_bytes).decode("ascii"),
            "payload": self._safe_value(parsed),
        }, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")

    def before_http_post(self) -> None:
        if self.dispatch_count != 1:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_DISPATCH_NOT_CAPTURED"
            )

    def before_network_request(self) -> None:
        if self.dispatch_count != 1:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_DISPATCH_NOT_CAPTURED"
            )

    def capture_provider_protocol_input(
        self, *, data: bytes, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        if self.response_count:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_RESPONSE_DUPLICATE"
            )
        if self.dispatch_count != 1:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_RESPONSE_WITHOUT_REQUEST"
            )
        record = provider_response_evidence_projection_v1(
            data, content_type=content_type, encoding=encoding,
            transport_complete=transport_complete,
        )
        record.update({
            "schema": "ReviewDiagnosticProviderResponseV1",
            "status_code": status_code,
        })
        self._write_json("20-provider-response.json", record)
        self.response_count = 1

    def capture_contract_runtime_input(
        self, text: str, *, adapter_id: str, adapter_version: int,
        finish_reason: str | None, transport_complete: bool,
    ) -> None:
        if self.runtime_input_count:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_RUNTIME_INPUT_DUPLICATE"
            )
        if self.response_count != 1:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_RUNTIME_INPUT_WITHOUT_RESPONSE"
            )
        data = text.encode("utf-8")
        self._write_json("30-adapter-output.json", {
            "schema": "ReviewDiagnosticAdapterOutputV1",
            "adapter_id": adapter_id, "adapter_version": adapter_version,
            "finish_reason": finish_reason, "transport_complete": transport_complete,
            "text_sha256": _sha256(data), "text_length": len(text),
            "text": text,
        })
        self.runtime_input_count = 1

    def capture_review_diagnostic(self, *, event: str, **value: Any) -> None:
        self._event(event, value)

    def __call__(self, observation: Mapping[str, Any]) -> None:
        self._event("runtime-observation", {"observation": dict(observation)})

    def after_http_response(self, *, status_code: int) -> None:
        self._event("http-status", {"status_code": status_code})

    def after_http_failure(self, *, failure_kind: str) -> None:
        self._event("http-failure", {"failure_kind": failure_kind})


def provider_response_evidence_projection_v1(
    data: bytes, *, content_type: str, encoding: str,
    transport_complete: bool,
) -> dict[str, Any]:
    """Build the shared privacy-safe Provider response evidence projection.

    The byte hash and length retain transport identity. Parsed final content
    remains available for replay and validation while hidden reasoning is
    removed. Malformed protocol input remains diagnosable without persisting
    opaque bytes that may contain hidden reasoning.
    """

    if not isinstance(data, bytes):
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_EVIDENCE_BYTES_REQUIRED"
        )
    structured: Any = None
    parse_error: str | None = None
    try:
        events, body = parse_provider_protocol_input_bytes_v1(
            data, content_type=content_type, encoding=encoding,
        )
        structured = ReviewDiagnosticCaptureObserverV1._redact_reasoning(
            {"events": events, "body": body} if events else body
        )
    except Exception as exc:
        parse_error = type(exc).__name__ + ":" + str(exc)
    record: dict[str, Any] = {
        "schema": "ProviderResponseEvidenceProjectionV1",
        "content_type": content_type or "application/octet-stream",
        "encoding": encoding or "utf-8",
        "transport_complete": bool(transport_complete),
        "raw_sha256": _sha256(data),
        "raw_length": len(data),
        "redaction": "hidden_reasoning_content_removed",
        "structured": structured,
        "parse_error": parse_error,
    }
    if structured is None and not any(
        token in data.lower() for token in (b"reasoning", b"thinking", b"analysis")
    ):
        record["safe_raw_bytes_base64"] = base64.b64encode(data).decode("ascii")
    return record


class ShortAutoRecoveryCaptureObserverV1:
    """Attach per-dispatch Review capture to an existing execution observer.

    The diagnostic observer was originally used by the one-call capture
    harness.  Automatic Short correction can contain two real dispatches, so
    each dispatch gets its own immutable child directory while the existing
    Full Short ledger remains the authoritative observer.  This is a narrow
    composition layer: it does not alter routing, retry policy, or acceptance.
    """

    def __init__(
        self, *, base_observer: Any, store_root: Path, registry: Any,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.base_observer = base_observer
        self.store_root = Path(store_root).resolve()
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.registry = registry
        self.context = dict(context or {})
        self._capture: ReviewDiagnosticCaptureObserverV1 | None = None
        self._stage_key: tuple[Any, ...] | None = None
        self._stage_context: dict[str, Any] | None = None
        self._route: dict[str, Any] | None = None
        self._manifest_path = self.store_root / "capture-manifest.json"
        self._manifest_entries: list[dict[str, Any]] = []
        self.store_root.joinpath("00-auto-recovery-context.json").write_text(
            json.dumps({
                "schema": "ShortAutoRecoveryCaptureContextV1",
                "context": ReviewDiagnosticCaptureObserverV1._safe_value(self.context),
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_manifest(self) -> None:
        payload = {
            "schema": "ShortAutoRecoveryCaptureManifestV1",
            "version": 1,
            "project_id": str(self.context.get("project_id") or ""),
            "run_id": str(self.context.get("run_id") or ""),
            "canonical_episode_id": str(self.context.get("canonical_episode_id") or ""),
            "physical_request_id": str(self.context.get("physical_request_id") or ""),
            "execution_envelope_hash": str(self.context.get("execution_envelope_hash") or ""),
            "runtime_path_id": str(self.context.get("runtime_path_id") or ""),
            "release_build_id": str(self.context.get("release_build_id") or ""),
            "worker_fencing_id": str(self.context.get("worker_fencing_id") or ""),
            "entries": list(self._manifest_entries),
        }
        temporary = self._manifest_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(temporary, self._manifest_path)

    def _new_capture(self, route: Mapping[str, Any]) -> None:
        public = self.registry.inspect_public_route(
            str(route["provider_id"]), str(route["model_id"]),
        )
        host = urlsplit(str(public.destination)).hostname
        if not host:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_DESTINATION_HOST_MISSING"
            )
        # `_stage` installs a fresh composition wrapper for each explicit
        # route attempt.  Recover the durable ordinal from prior immutable
        # attempt directories so fallback/correction never reuses
        # `attempt-01` after a process or wrapper boundary.
        existing_indices = [
            int(match.group(1))
            for path in self.store_root.iterdir()
            if path.is_dir()
            and (match := re.fullmatch(
                r"attempt-(\d+)", path.name,
            )) is not None
        ]
        index = max(
            [int(self.context.get("dispatch_index") or 0), *existing_indices],
        ) + 1
        self.context["dispatch_index"] = index
        self._capture = ReviewDiagnosticCaptureObserverV1(
            store_root=self.store_root / f"attempt-{index:02d}",
            provider_id=str(route["provider_id"]),
            model_id=str(route["model_id"]),
            hostname=host,
            context={**self.context, "route": dict(route)},
        )
        self._route = dict(route)
        self._manifest_entries.append({
            "capture_id": f"{self.context.get('run_id') or 'run'}-{index:02d}",
            "capture_attempt": f"attempt-{index:02d}",
            "capture_path": f"attempt-{index:02d}",
            "project_id": str(self.context.get("project_id") or ""),
            "run_id": str(self.context.get("run_id") or ""),
            "candidate_sha256": str(self.context.get("candidate_sha256") or ""),
            "authorization_revision": str(self.context.get("authorization_revision") or ""),
            "provider_id": str(route.get("provider_id") or ""),
            "model_id": str(route.get("model_id") or ""),
            "status": "prepared",
        })
        self._write_manifest()
        if self._stage_context is not None:
            self._capture.bind_stage_context(**self._stage_context)
        self._capture.bind_route(**dict(route))

    def bind_route(self, **kwargs: Any) -> None:
        callback = getattr(self.base_observer, "bind_route", None)
        if callable(callback):
            callback(**kwargs)
        route = dict(kwargs)
        route_identity = tuple(route.get(k) for k in ("role", "lane", "provider_id", "model_id"))
        if self._capture is None:
            self._new_capture(route)
        elif self._route is not None:
            current_identity = tuple(self._route.get(k) for k in ("role", "lane", "provider_id", "model_id"))
            if route_identity != current_identity:
                same_review_role = (
                    self._route.get("role") == route.get("role") == "review"
                )
                allowed_lane_transition = (
                    self._route.get("lane") == "primary"
                    and route.get("lane") in {"fallback", "configured_fallback"}
                    and self._stage_context is not None
                    and self._stage_context.get("contract_route") in {
                        "fallback", "configured_fallback",
                    }
                )
                if (
                    self._capture.dispatch_count == 0
                    and same_review_role
                    and allowed_lane_transition
                ):
                    self._new_capture(route)
                else:
                    raise ReviewDiagnosticCaptureScopeError(
                        "REVIEW_DIAGNOSTIC_ROUTE_DRIFT"
                    )
            elif self._capture.dispatch_count:
                self._new_capture(route)
            else:
                self._capture.bind_route(**route)

    def bind_stage_context(self, **kwargs: Any) -> None:
        callback = getattr(self.base_observer, "bind_stage_context", None)
        if callable(callback):
            callback(**kwargs)
        self._stage_context = dict(kwargs)
        if self._manifest_entries:
            self._manifest_entries[-1].update({
                "logical_stage_id": str(kwargs.get("stage_id") or ""),
                "contract_name": str(kwargs.get("contract_name") or ""),
                "contract_version": kwargs.get("contract_version"),
                "contract_schema_sha256": str(
                    kwargs.get("contract_schema_sha256") or ""
                ),
            })
            self._write_manifest()
        if self._capture is not None:
            self._capture.bind_stage_context(**kwargs)

    def bind_canonical_dispatch(self, **kwargs: Any) -> None:
        """Attach the execution-envelope identity to this capture manifest."""
        safe = {
            "canonical_episode_id": str(
                ((kwargs.get("episode") or {}).get("episode_sha256")) or ""
            ),
            "physical_request_id": str(kwargs.get("physical_request_id") or ""),
            "execution_envelope_hash": str(kwargs.get("envelope_sha256") or ""),
            "runtime_path_id": str(
                ((kwargs.get("release") or {}).get("runtime_path_id")) or ""
            ),
            "release_build_id": str(
                ((kwargs.get("release") or {}).get("release_build_id")) or ""
            ),
            "worker_fencing_id": str(
                ((kwargs.get("release") or {}).get("worker_fencing_id")) or ""
            ),
        }
        self.context.update({k: v for k, v in safe.items() if v})
        if self._manifest_entries:
            self._manifest_entries[-1].update({k: v for k, v in safe.items() if v})
            self._write_manifest()

    def bind_model_request(self, **kwargs: Any) -> None:
        callback = getattr(self.base_observer, "bind_model_request", None)
        if callable(callback):
            callback(**kwargs)
        if self._capture is None:
            raise ReviewDiagnosticCaptureScopeError(
                "REVIEW_DIAGNOSTIC_ROUTE_NOT_BOUND"
            )
        self._capture.bind_model_request(**kwargs)

    def capture_review_diagnostic(self, *, event: str, **value: Any) -> None:
        if self._capture is not None:
            self._capture.capture_review_diagnostic(event=event, **value)

    def __getattr__(self, name: str) -> Any:
        if self.base_observer is not None:
            return getattr(self.base_observer, name)
        # A normal resumed Short process has no Full Short execution
        # observer.  These attributes must remain absent/false; returning a
        # generic callable here would make the workflow mistake this narrow
        # diagnostic wrapper for a sealed Full Short observer and reject the
        # request before the HTTP seam.
        if name == "exact_full_short_execution":
            return False
        if name in {
            "policy",
            "sealed_route_for_next_logical_stage",
            "capacity_admission_context",
            "authorize_capacity_dispatch_token",
        }:
            return None
        if name == "bound_route":
            return self._route
        if name == "contract_runtime_capture_present":
            return lambda: bool(
                self._capture is not None and self._capture.runtime_input_count
            )
        # Only the explicitly optional native-ledger callbacks are no-ops.
        # Unknown names must retain normal Python AttributeError semantics;
        # manufacturing a callable for them can silently turn a wiring error
        # into a route or capability decision before the HTTP seam.
        if name in {
            "bind_capacity_plan",
            "mark_local_attempt_rejected",
            "mark_local_stage_complete",
        }:
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def _fanout(self, name: str, **kwargs: Any) -> Any:
        callback = getattr(self.base_observer, name, None)
        result = callback(**kwargs) if callable(callback) else None
        if self._capture is not None:
            capture_callback = getattr(self._capture, name, None)
            if callable(capture_callback):
                capture_callback(**kwargs)
        return result

    def before_http_dispatch(self, **kwargs: Any) -> Any:
        return self._fanout("before_http_dispatch", **kwargs)

    def before_http_post(self) -> Any:
        return self._fanout("before_http_post")

    def before_network_request(self) -> Any:
        return self._fanout("before_network_request")

    def capture_provider_protocol_input(self, **kwargs: Any) -> Any:
        return self._fanout("capture_provider_protocol_input", **kwargs)

    def capture_contract_runtime_input(self, text: str, **kwargs: Any) -> Any:
        callback = getattr(self.base_observer, "capture_contract_runtime_input", None)
        if callable(callback):
            try:
                parameter_names = inspect.signature(callback).parameters
            except (TypeError, ValueError):
                parameter_names = {}
            if "data" in parameter_names and "text" not in parameter_names:
                result = callback(data=text.encode("utf-8"), **kwargs)
            else:
                result = callback(text=text, **kwargs)
        else:
            result = None
        if self._capture is not None:
            capture_callback = getattr(self._capture, "capture_contract_runtime_input", None)
            if callable(capture_callback):
                capture_callback(text, **kwargs)
        if self._manifest_entries:
            self._manifest_entries[-1]["status"] = "complete"
            self._manifest_entries[-1]["adapter_output_sha256"] = _sha256(
                text.encode("utf-8")
            )
            self._write_manifest()
        return result

    def after_http_response(self, **kwargs: Any) -> Any:
        return self._fanout("after_http_response", **kwargs)

    def after_http_failure(self, **kwargs: Any) -> Any:
        return self._fanout("after_http_failure", **kwargs)

    def __call__(self, observation: Mapping[str, Any]) -> None:
        callback = getattr(self.base_observer, "__call__", None)
        if callable(callback):
            callback(observation)
        if self._capture is not None:
            self._capture(observation)
