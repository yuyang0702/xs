"""Offline validation for frozen-HEAD external workload evidence.

This module deliberately has no filesystem, Git, provider, or network capability.  It
accepts only a canonical, authenticated V1 envelope and returns an immutable value
which callers may project into a post-freeze capacity map.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping


SCHEMA = "ExternalWorkloadEvidenceV1"
SIGNATURE_ALGORITHM = "HMAC-SHA256"
_SIGNING_DOMAIN = b"novel-flywheel.external-workload-evidence.v1\x00"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40}\Z")


class ExternalWorkloadEvidenceError(ValueError):
    """A fixed, non-secret reason for rejecting external evidence."""


@dataclass(frozen=True)
class ExpectedWorkloadEvidenceV1:
    authorization_sha256: str
    final_execution_head: str
    provider: str
    operator: str
    destination: str
    protocol: str
    model: str
    route_fingerprint_sha256: str
    case_id: str
    fixture_sha256: str
    request_family_sha256: str
    request_sha256: str
    input_tokens: int
    requested_output_tokens: int
    key_id: str
    historical_admission_sha256: str | None = None


@dataclass(frozen=True)
class VerifiedWorkloadEvidenceV1:
    package_bytes: bytes
    key_id: str
    evidence_sha256: str
    payload_sha256: str
    authorization_sha256: str
    final_execution_head: str
    provider: str
    operator: str
    destination: str
    protocol: str
    model: str
    route_fingerprint_sha256: str
    case_id: str
    fixture_sha256: str
    request_family_sha256: str
    request_sha256: str
    nonce_sha256: str
    input_tokens: int
    actual_input_tokens: int
    requested_output_tokens: int
    actual_output_tokens: int
    response_sha256: str
    historical_admission_sha256: str | None = None
    admission_authorization_sha256: str | None = None
    admission_execution_head: str | None = None

    @property
    def capacity_authorization_sha256(self) -> str:
        return self.admission_authorization_sha256 or self.authorization_sha256

    @property
    def capacity_execution_head(self) -> str:
        return self.admission_execution_head or self.final_execution_head

    @property
    def route_key(self) -> str:
        material = canonical_json_bytes({
            "destination": self.destination,
            "model": self.model,
            "operator": self.operator,
            "protocol": self.protocol,
            "provider": self.provider,
            "route_fingerprint_sha256": self.route_fingerprint_sha256,
        })
        return hashlib.sha256(b"route-key-v1\x00" + material).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole accepted JSON representation."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def seal_external_workload_evidence_v1(
    payload: Mapping[str, Any], *, key_id: str, signing_key: bytes,
) -> bytes:
    """Create a canonical envelope; intended for the external evidence writer."""
    _nonempty("key_id", key_id)
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ExternalWorkloadEvidenceError("INVALID_SIGNING_KEY")
    body = dict(payload)
    payload_bytes = canonical_json_bytes(body)
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    signature = hmac.new(
        signing_key, _SIGNING_DOMAIN + payload_bytes, hashlib.sha256,
    ).hexdigest()
    return canonical_json_bytes({
        "payload": body,
        "payload_sha256": payload_sha256,
        "schema": SCHEMA,
        "signature": {
            "algorithm": SIGNATURE_ALGORITHM,
            "key_id": key_id,
            "value": signature,
        },
    })


def validate_external_workload_evidence_v1(
    package_bytes: bytes,
    *,
    expected: ExpectedWorkloadEvidenceV1,
    verification_keys: Mapping[str, bytes],
) -> VerifiedWorkloadEvidenceV1:
    """Verify a canonical sealed package against frozen authorization and route."""
    if not isinstance(package_bytes, bytes):
        raise ExternalWorkloadEvidenceError("PACKAGE_MUST_BE_BYTES")
    try:
        envelope = json.loads(package_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ExternalWorkloadEvidenceError("INVALID_CANONICAL_JSON") from None
    try:
        canonical_envelope = canonical_json_bytes(envelope)
    except (TypeError, ValueError):
        raise ExternalWorkloadEvidenceError("INVALID_CANONICAL_JSON") from None
    if canonical_envelope != package_bytes:
        raise ExternalWorkloadEvidenceError("NONCANONICAL_PACKAGE")
    _exact_keys(envelope, {"schema", "payload", "payload_sha256", "signature"}, "ENVELOPE")
    from novel_flywheel.ping_successor import HISTORICAL_ADMISSION_SCHEMA
    historical = envelope["schema"] == HISTORICAL_ADMISSION_SCHEMA
    if envelope["schema"] != SCHEMA and not historical:
        raise ExternalWorkloadEvidenceError("WRONG_SCHEMA")
    if historical != (expected.historical_admission_sha256 is not None):
        raise ExternalWorkloadEvidenceError("HISTORICAL_ADMISSION_NOT_AUTHORIZED")
    signature = envelope["signature"]
    _exact_keys(signature, {"algorithm", "key_id", "value"}, "SIGNATURE")
    if signature["algorithm"] != SIGNATURE_ALGORITHM:
        raise ExternalWorkloadEvidenceError("WRONG_SIGNATURE_ALGORITHM")
    if signature["key_id"] != expected.key_id:
        raise ExternalWorkloadEvidenceError("WRONG_SIGNING_KEY")
    key = verification_keys.get(expected.key_id)
    if not isinstance(key, bytes) or len(key) < 32:
        raise ExternalWorkloadEvidenceError("VERIFICATION_KEY_UNAVAILABLE")
    payload = envelope["payload"]
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    if not _is_hash(envelope["payload_sha256"]) or not hmac.compare_digest(
        envelope["payload_sha256"], payload_hash,
    ):
        raise ExternalWorkloadEvidenceError("PAYLOAD_SEAL_MISMATCH")
    if not _is_hash(signature["value"]):
        raise ExternalWorkloadEvidenceError("INVALID_SIGNATURE")
    domain = _HISTORICAL_SIGNING_DOMAIN if historical else _SIGNING_DOMAIN
    wanted = hmac.new(key, domain + payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature["value"], wanted):
        raise ExternalWorkloadEvidenceError("INVALID_SIGNATURE")
    _validate_expected(expected)
    if historical:
        return _validate_historical_admission(payload, expected, package_bytes, payload_hash)
    return _validate_payload(payload, expected, package_bytes, payload_hash)


_HISTORICAL_SIGNING_DOMAIN = b"novel-flywheel.historical-workload-admission.v1\x00"


def seal_historical_workload_admission_v1(*, proof: Mapping[str, Any],
    expected: ExpectedWorkloadEvidenceV1, signing_key: bytes) -> bytes:
    """Sign a capacity admission, never a dispatch receipt or a new nonce."""
    from dataclasses import asdict
    from novel_flywheel.ping_successor import HISTORICAL_ADMISSION_SCHEMA
    _validate_expected(expected)
    if len(signing_key) < 32 or not expected.historical_admission_sha256:
        raise ExternalWorkloadEvidenceError("HISTORICAL_ADMISSION_NOT_AUTHORIZED")
    payload = {"admission": asdict(expected), "historical_proof": dict(proof),
        "fresh_dispatch_count": 0}
    raw = canonical_json_bytes(payload)
    package = canonical_json_bytes({"schema": HISTORICAL_ADMISSION_SCHEMA,
        "payload": payload, "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "signature": {"algorithm": SIGNATURE_ALGORITHM, "key_id": expected.key_id,
            "value": hmac.new(signing_key, _HISTORICAL_SIGNING_DOMAIN + raw, hashlib.sha256).hexdigest()}})
    validate_external_workload_evidence_v1(package, expected=expected,
        verification_keys={expected.key_id: signing_key})
    return package


def _validate_historical_admission(payload: Any, expected: ExpectedWorkloadEvidenceV1,
    raw: bytes, payload_hash: str) -> VerifiedWorkloadEvidenceV1:
    from dataclasses import asdict
    from novel_flywheel.ping_successor import HistoricalAdmissionProof, compact_sha
    _exact_keys(payload, {"admission", "historical_proof", "fresh_dispatch_count"}, "HISTORICAL_ADMISSION")
    if (payload["admission"] != asdict(expected) or type(payload["fresh_dispatch_count"]) is not int
        or payload["fresh_dispatch_count"] != 0):
        raise ExternalWorkloadEvidenceError("HISTORICAL_ADMISSION_BINDING_DRIFT")
    try:
        proof = HistoricalAdmissionProof.model_validate(payload["historical_proof"])
    except ValueError:
        raise ExternalWorkloadEvidenceError("HISTORICAL_PROOF_INVALID") from None
    if (compact_sha(payload["historical_proof"]) != expected.historical_admission_sha256
        or proof.case_id != expected.case_id or proof.source_request_sha256 != expected.request_sha256
        or proof.source_authorization_sha256 == expected.authorization_sha256
        or proof.source_execution_head == expected.final_execution_head
        or proof.canonical_output_tokens > expected.requested_output_tokens):
        raise ExternalWorkloadEvidenceError("HISTORICAL_PROVENANCE_DRIFT")
    return VerifiedWorkloadEvidenceV1(package_bytes=raw, key_id=expected.key_id,
        evidence_sha256=hashlib.sha256(raw).hexdigest(), payload_sha256=payload_hash,
        authorization_sha256=proof.source_authorization_sha256,
        final_execution_head=proof.source_execution_head,
        provider=expected.provider, operator=expected.operator, destination=expected.destination,
        protocol=expected.protocol, model=expected.model,
        route_fingerprint_sha256=expected.route_fingerprint_sha256,
        case_id=expected.case_id, fixture_sha256=expected.fixture_sha256,
        request_family_sha256=expected.request_family_sha256, request_sha256=expected.request_sha256,
        nonce_sha256=proof.source_nonce_sha256, input_tokens=expected.input_tokens,
        actual_input_tokens=proof.canonical_input_tokens, requested_output_tokens=expected.requested_output_tokens,
        actual_output_tokens=proof.canonical_output_tokens, response_sha256=proof.source_capture_sha256,
        historical_admission_sha256=expected.historical_admission_sha256,
        admission_authorization_sha256=expected.authorization_sha256,
        admission_execution_head=expected.final_execution_head)


def deterministic_promotion_mapping_v1(
    evidence: Iterable[VerifiedWorkloadEvidenceV1],
) -> Mapping[str, Mapping[str, Any]]:
    """Build an immutable, order-independent capacity projection without Git I/O."""
    promoted: dict[str, Mapping[str, Any]] = {}
    observed_nonce_sha256s: set[str] = set()
    observed_evidence_sha256s: set[str] = set()
    for item in sorted(evidence, key=lambda value: (value.route_key, value.case_id)):
        key = f"{item.route_key}:{item.case_id}"
        if key in promoted:
            raise ExternalWorkloadEvidenceError("DUPLICATE_PROMOTION_IDENTITY")
        if item.nonce_sha256 in observed_nonce_sha256s:
            raise ExternalWorkloadEvidenceError("NONCE_REUSE_FORBIDDEN")
        if item.evidence_sha256 in observed_evidence_sha256s:
            raise ExternalWorkloadEvidenceError("EVIDENCE_REUSE_FORBIDDEN")
        observed_nonce_sha256s.add(item.nonce_sha256)
        observed_evidence_sha256s.add(item.evidence_sha256)
        promoted[key] = MappingProxyType({
            "authorization_sha256": item.authorization_sha256,
            "actual_input_tokens": item.actual_input_tokens,
            "evidence_sha256": item.evidence_sha256,
            "final_execution_head": item.final_execution_head,
            "input_tokens": item.input_tokens,
            "request_family_sha256": item.request_family_sha256,
            "request_sha256": item.request_sha256,
            "requested_output_tokens": item.requested_output_tokens,
            "route_fingerprint_sha256": item.route_fingerprint_sha256,
            "verified_workload_shape": True,
        })
    return MappingProxyType(promoted)


_PAYLOAD_KEYS = {
    "authorization_sha256", "case", "final_execution_head", "nonce", "request",
    "result", "route",
}
_ROUTE_KEYS = {
    "destination", "model", "operator", "protocol", "provider",
    "route_fingerprint_sha256",
}
_CASE_KEYS = {"case_id", "fixture_sha256"}
_REQUEST_KEYS = {
    "input_tokens", "request_family_sha256", "request_sha256",
    "requested_output_tokens",
}
_NONCE_KEYS = {"dispatch_attempt_count", "nonce_sha256", "state"}
_RESULT_KEYS = {
    "actual_input_tokens", "actual_output_tokens", "complete", "input_accepted",
    "output_accepted", "response_sha256", "terminal_status",
}


def _validate_payload(
    payload: Any, expected: ExpectedWorkloadEvidenceV1,
    package_bytes: bytes, payload_hash: str,
) -> VerifiedWorkloadEvidenceV1:
    _exact_keys(payload, _PAYLOAD_KEYS, "PAYLOAD")
    route, case, request = payload["route"], payload["case"], payload["request"]
    nonce, result = payload["nonce"], payload["result"]
    _exact_keys(route, _ROUTE_KEYS, "ROUTE")
    _exact_keys(case, _CASE_KEYS, "CASE")
    _exact_keys(request, _REQUEST_KEYS, "REQUEST")
    _exact_keys(nonce, _NONCE_KEYS, "NONCE")
    _exact_keys(result, _RESULT_KEYS, "RESULT")
    pairs = {
        "authorization_sha256": (payload["authorization_sha256"], expected.authorization_sha256),
        "final_execution_head": (payload["final_execution_head"], expected.final_execution_head),
        "provider": (route["provider"], expected.provider),
        "operator": (route["operator"], expected.operator),
        "destination": (route["destination"], expected.destination),
        "protocol": (route["protocol"], expected.protocol),
        "model": (route["model"], expected.model),
        "route_fingerprint_sha256": (route["route_fingerprint_sha256"], expected.route_fingerprint_sha256),
        "case_id": (case["case_id"], expected.case_id),
        "fixture_sha256": (case["fixture_sha256"], expected.fixture_sha256),
        "request_family_sha256": (
            request["request_family_sha256"],
            expected.request_family_sha256,
        ),
        "request_sha256": (request["request_sha256"], expected.request_sha256),
        "input_tokens": (request["input_tokens"], expected.input_tokens),
        "requested_output_tokens": (request["requested_output_tokens"], expected.requested_output_tokens),
    }
    for name, (actual, wanted) in pairs.items():
        if actual != wanted:
            raise ExternalWorkloadEvidenceError(f"{name.upper()}_MISMATCH")
    for name in (
        "authorization_sha256", "route_fingerprint_sha256", "fixture_sha256",
        "request_family_sha256", "request_sha256",
    ):
        if not _is_hash(pairs[name][0]):
            raise ExternalWorkloadEvidenceError(f"INVALID_{name.upper()}")
    if not isinstance(payload["final_execution_head"], str) or not _HEAD.fullmatch(payload["final_execution_head"]):
        raise ExternalWorkloadEvidenceError("INVALID_FINAL_EXECUTION_HEAD")
    if nonce["state"] != "CONSUMED" or nonce["dispatch_attempt_count"] != 1:
        raise ExternalWorkloadEvidenceError("NONCE_NOT_SUCCESSFULLY_CONSUMED")
    if not _is_hash(nonce["nonce_sha256"]):
        raise ExternalWorkloadEvidenceError("INVALID_NONCE_SHA256")
    if result["terminal_status"] != "SUCCESS" or result["complete"] is not True:
        raise ExternalWorkloadEvidenceError("UNSUCCESSFUL_OR_INCOMPLETE_RESULT")
    if result["input_accepted"] is not True or result["output_accepted"] is not True:
        raise ExternalWorkloadEvidenceError("WORKLOAD_NOT_ACCEPTED")
    if not _positive_int(request["input_tokens"]) or not _positive_int(request["requested_output_tokens"]):
        raise ExternalWorkloadEvidenceError("INVALID_REQUEST_BOUNDS")
    actual_input = result["actual_input_tokens"]
    if not _positive_int(actual_input):
        raise ExternalWorkloadEvidenceError("INVALID_ACTUAL_INPUT_TOKENS")
    # The bound is the exact accepted request under the deterministic local
    # estimator. Provider tokenizer units are separate realized accounting.
    actual_output = result["actual_output_tokens"]
    if not _positive_int(actual_output) or actual_output > request["requested_output_tokens"]:
        raise ExternalWorkloadEvidenceError("OUTPUT_OUTSIDE_REQUEST_BOUND")
    if not _is_hash(result["response_sha256"]):
        raise ExternalWorkloadEvidenceError("INVALID_RESPONSE_SHA256")
    return VerifiedWorkloadEvidenceV1(
        package_bytes=package_bytes,
        key_id=expected.key_id,
        evidence_sha256=hashlib.sha256(package_bytes).hexdigest(),
        payload_sha256=payload_hash,
        authorization_sha256=payload["authorization_sha256"],
        final_execution_head=payload["final_execution_head"],
        provider=route["provider"], operator=route["operator"],
        destination=route["destination"], protocol=route["protocol"],
        model=route["model"], route_fingerprint_sha256=route["route_fingerprint_sha256"],
        case_id=case["case_id"], fixture_sha256=case["fixture_sha256"],
        request_family_sha256=request["request_family_sha256"],
        request_sha256=request["request_sha256"], nonce_sha256=nonce["nonce_sha256"],
        input_tokens=request["input_tokens"],
        actual_input_tokens=actual_input,
        requested_output_tokens=request["requested_output_tokens"],
        actual_output_tokens=actual_output, response_sha256=result["response_sha256"],
    )


def _validate_expected(value: ExpectedWorkloadEvidenceV1) -> None:
    for name in (
        "authorization_sha256", "route_fingerprint_sha256", "fixture_sha256",
        "request_family_sha256", "request_sha256",
    ):
        if not _is_hash(getattr(value, name)):
            raise ExternalWorkloadEvidenceError(f"INVALID_EXPECTED_{name.upper()}")
    if not _HEAD.fullmatch(value.final_execution_head):
        raise ExternalWorkloadEvidenceError("INVALID_EXPECTED_FINAL_EXECUTION_HEAD")
    for name in ("provider", "operator", "destination", "protocol", "model", "case_id", "key_id"):
        _nonempty(name, getattr(value, name))
    if not _positive_int(value.input_tokens) or not _positive_int(value.requested_output_tokens):
        raise ExternalWorkloadEvidenceError("INVALID_EXPECTED_REQUEST_BOUNDS")


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ExternalWorkloadEvidenceError(f"INVALID_{label}_SHAPE")


def _nonempty(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ExternalWorkloadEvidenceError(f"INVALID_{name.upper()}")


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
