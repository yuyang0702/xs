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
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(temporary, flags, 0o600)
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
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_CAPTURE_DUPLICATE"
            ) from exc
        finally:
            try:
                temporary.unlink()
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
            raise ProviderResponseCaptureError("PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID") from exc
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
        raise ProviderResponseCaptureError("PROVIDER_RESPONSE_REPLAY_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ProviderResponseCaptureError("PROVIDER_RESPONSE_REPLAY_JSON_OBJECT_REQUIRED")
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
