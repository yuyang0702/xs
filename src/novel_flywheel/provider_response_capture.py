"""Private, worktree-external exact Provider response capture and replay.

The capture format deliberately stores only response bytes plus hash-bound
execution metadata.  Request bodies, headers, credentials, and prompts are
not accepted by this boundary.  Captures are immutable and are never written
inside the Git worktree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any, Mapping

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
PROHIBITED_METADATA_KEYS = frozenset({
    "authorization", "api_key", "credential", "headers", "prompt",
    "request_body", "story", "system", "tool_arguments", "user",
})
PUBLIC_METADATA_FIELDS = frozenset({
    "execution_id", "call_id", "stage_id", "provider_id_sha256",
    "model_id_sha256", "route_fingerprint", "protocol", "contract_name",
    "contract_version", "contract_schema_sha256", "adapter_id",
    "adapter_version", "content_type", "encoding", "transport_complete",
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
                offset += os.write(descriptor, payload[offset:])
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
        expected_receipt_sha256: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        if byte_domain not in CAPTURE_DOMAINS:
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_DOMAIN_INVALID"
            )
        expected = _validate_public_metadata(expected_metadata)
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
        if expected_receipt_sha256 is not None and (
            expected_receipt_sha256 != ledger_receipt_sha256
        ):
            raise ProviderResponseCaptureError(
                "PROVIDER_RESPONSE_REPLAY_LEDGER_RECEIPT_MISMATCH"
            )
        header["ledger_receipt_sha256"] = ledger_receipt_sha256
        return data, header

    def audit_all(self) -> list[dict[str, Any]]:
        """Verify every immutable capture and return metadata-only receipts."""

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
                key: header[key] for key in (
                    "execution_id", "call_id", "stage_id",
                    "provider_id_sha256", "model_id_sha256",
                    "route_fingerprint", "protocol", "contract_name",
                    "contract_version", "contract_schema_sha256",
                    "adapter_id", "adapter_version", "content_type",
                    "encoding", "transport_complete",
                )
            }
            _validate_public_metadata(metadata)
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


def parse_provider_protocol_input_bytes_v1(
    data: bytes, *, content_type: str, encoding: str = "utf-8",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse exact captured HTTP entity bytes at the production protocol seam."""

    try:
        text = data.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise ProviderResponseCaptureError(
            "PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID"
        ) from exc
    if "text/event-stream" not in content_type.lower():
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
    events: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                raw = "\n".join(data_lines)
                data_lines.clear()
                if raw != "[DONE]":
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
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        raw = "\n".join(data_lines)
        if raw != "[DONE]":
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
    return events, None
