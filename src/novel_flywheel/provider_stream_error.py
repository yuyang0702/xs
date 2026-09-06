"""Privacy-safe evidence for an authoritative, ordered SSE Provider error.

This module owns normalization only. The adapter owns semantic prefix validation;
HTTP completeness never grants or removes Provider error authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PayloadShape = Literal["object", "string", "number", "boolean", "array", "null", "raw", "empty", "missing"]
ProviderErrorType = Literal["invalid_request_error", "authentication_error", "permission_error", "not_found_error", "request_too_large", "rate_limit_error", "api_error", "overloaded_error", "provider_error"]
_KNOWN_TYPES = {"invalid_request_error", "authentication_error", "permission_error", "not_found_error", "request_too_large", "rate_limit_error", "api_error", "overloaded_error"}


class StreamProviderErrorEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    version: Literal[1] = 1
    primary_terminal_cause: Literal["PROVIDER_ERROR"] = "PROVIDER_ERROR"
    primary_cause_code: Literal["anthropic_provider_terminal_error"] = "anthropic_provider_terminal_error"
    primary_cause_family: Literal["provider.terminal_error_event"] = "provider.terminal_error_event"
    sse_event_type: Literal["error"] = "error"
    event_ordinal: int = Field(default=0, ge=0)
    payload_shape: PayloadShape
    nested_error_shape: PayloadShape = "missing"
    provider_error_type: ProviderErrorType = "provider_error"
    safe_message: Literal["Provider emitted a terminal stream error."] = "Provider emitted a terminal stream error."
    raw_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_payload_length: int = Field(ge=0)
    payload_hash_domain: Literal["sse_data_bytes", "canonical_event_json"] = "sse_data_bytes"
    event_data_type_conflict: bool = False
    transport_complete: bool | None = None
    secondary_post_error_ping_count: int = Field(default=0, ge=0, alias="SECONDARY_POST_ERROR_PING_COUNT")
    secondary_post_error_timeout_present: bool = Field(default=False, alias="SECONDARY_POST_ERROR_TIMEOUT_PRESENT")
    secondary_post_error_event_count: int = Field(default=0, ge=0)
    secondary_post_error_error_count: int = Field(default=0, ge=0)
    secondary_post_error_invalid_tail_present: bool = False
    secondary_post_error_transport_present: bool = False
    secondary_post_error_observer_failure_count: int = Field(default=0, ge=0)
    secondary_usage_projection_rejected: bool = False
    secondary_transport_exception_class: Literal["ReadTimeout", "WriteTimeout", "ConnectTimeout", "PoolTimeout", "TimeoutException", "CancelledError", "TransportError", "other"] | None = None
    provider_id_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    route_fingerprint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def payload_shape(value: object) -> PayloadShape:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "number"


def normalize_stream_error_v1(value: object, *, raw: bytes | None = None,
                              shape: PayloadShape | None = None,
                              ordinal: int = 0, conflict: bool = False) -> StreamProviderErrorEvidenceV1:
    hash_domain = "canonical_event_json" if raw is None else "sse_data_bytes"
    if raw is None:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=lambda _: None).encode("utf-8", errors="replace")
    nested = value.get("error") if isinstance(value, dict) else None
    nested_shape = payload_shape(nested) if isinstance(value, dict) and "error" in value else "missing"
    candidate = nested.get("type") if isinstance(nested, dict) else None
    return StreamProviderErrorEvidenceV1(
        payload_shape=shape or payload_shape(value), nested_error_shape=nested_shape,
        provider_error_type=candidate if isinstance(candidate, str) and candidate in _KNOWN_TYPES else "provider_error",
        raw_payload_sha256=hashlib.sha256(raw).hexdigest(), raw_payload_length=len(raw),
        payload_hash_domain=hash_domain,
        event_ordinal=ordinal, event_data_type_conflict=conflict,
    )


class ProviderErrorEventV1(dict):
    """In-memory provenance; remote JSON cannot supply this Python type."""
    def __init__(self, evidence: StreamProviderErrorEvidenceV1):
        super().__init__(type="error", error={"type": evidence.provider_error_type})
        self.evidence = evidence


def stream_error_evidence_v1(exc: BaseException) -> StreamProviderErrorEvidenceV1 | None:
    evidence = getattr(exc, "provider_stream_error", None)
    return evidence if isinstance(evidence, StreamProviderErrorEvidenceV1) else None
