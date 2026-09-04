from __future__ import annotations

import json

import pytest

from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    ExternalWorkloadEvidenceError,
    deterministic_promotion_mapping_v1,
    seal_external_workload_evidence_v1,
    validate_external_workload_evidence_v1,
)


KEY = b"offline-test-verification-key-32-bytes-minimum"
H = "a" * 64


def _expected(**changes):
    values = dict(
        authorization_sha256="1" * 64, final_execution_head="2" * 40,
        provider="provider-explicit", operator="relay-explicit",
        destination="https://synthetic.invalid/v1/responses", protocol="responses-v1",
        model="model-explicit", route_fingerprint_sha256="3" * 64,
        case_id="probe-01", fixture_sha256="4" * 64,
        request_family_sha256="5" * 64, request_sha256="8" * 64,
        input_tokens=12345,
        requested_output_tokens=2048, key_id="campaign-key-01",
    )
    values.update(changes)
    return ExpectedWorkloadEvidenceV1(**values)


def _payload(expected=None):
    e = expected or _expected()
    return {
        "authorization_sha256": e.authorization_sha256,
        "case": {"case_id": e.case_id, "fixture_sha256": e.fixture_sha256},
        "final_execution_head": e.final_execution_head,
        "nonce": {"dispatch_attempt_count": 1, "nonce_sha256": "6" * 64, "state": "CONSUMED"},
        "request": {"input_tokens": e.input_tokens, "request_family_sha256": e.request_family_sha256, "request_sha256": e.request_sha256, "requested_output_tokens": e.requested_output_tokens},
        "result": {"actual_input_tokens": e.input_tokens, "actual_output_tokens": 144, "complete": True, "input_accepted": True, "output_accepted": True, "response_sha256": "7" * 64, "terminal_status": "SUCCESS"},
        "route": {"destination": e.destination, "model": e.model, "operator": e.operator, "protocol": e.protocol, "provider": e.provider, "route_fingerprint_sha256": e.route_fingerprint_sha256},
    }


def _seal(payload=None):
    return seal_external_workload_evidence_v1(payload or _payload(), key_id="campaign-key-01", signing_key=KEY)


def _validate(package=None, expected=None):
    return validate_external_workload_evidence_v1(package or _seal(), expected=expected or _expected(), verification_keys={"campaign-key-01": KEY})


def test_valid_exact_frozen_head_evidence_promotes_deterministically() -> None:
    verified = _validate()
    left = deterministic_promotion_mapping_v1([verified])
    right = deterministic_promotion_mapping_v1(reversed([verified]))
    assert dict(left) == dict(right)
    promoted = next(iter(left.values()))
    assert promoted["verified_workload_shape"] is True
    assert promoted["final_execution_head"] == "2" * 40
    assert promoted["input_tokens"] == 12345
    assert promoted["actual_input_tokens"] == 12345
    assert promoted["request_family_sha256"] == "5" * 64
    assert promoted["request_sha256"] == "8" * 64
    with pytest.raises(TypeError):
        promoted["input_tokens"] = 1


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("authorization_sha256",), "8" * 64, "AUTHORIZATION_SHA256_MISMATCH"),
        (("final_execution_head",), "9" * 40, "FINAL_EXECUTION_HEAD_MISMATCH"),
        (("route", "provider"), "alias-provider", "PROVIDER_MISMATCH"),
        (("route", "operator"), "upstream", "OPERATOR_MISMATCH"),
        (("route", "destination"), "https://other.invalid", "DESTINATION_MISMATCH"),
        (("route", "protocol"), "chat-alias", "PROTOCOL_MISMATCH"),
        (("route", "model"), "upstream-inherited-model", "MODEL_MISMATCH"),
        (("route", "route_fingerprint_sha256"), "8" * 64, "ROUTE_FINGERPRINT_SHA256_MISMATCH"),
        (("case", "fixture_sha256"), "8" * 64, "FIXTURE_SHA256_MISMATCH"),
        (("request", "request_family_sha256"), "9" * 64, "REQUEST_FAMILY_SHA256_MISMATCH"),
        (("request", "request_sha256"), "9" * 64, "REQUEST_SHA256_MISMATCH"),
        (("nonce", "state"), "RESERVED", "NONCE_NOT_SUCCESSFULLY_CONSUMED"),
        (("nonce", "dispatch_attempt_count"), 2, "NONCE_NOT_SUCCESSFULLY_CONSUMED"),
        (("result", "terminal_status"), "FAILED", "UNSUCCESSFUL_OR_INCOMPLETE_RESULT"),
        (("result", "complete"), False, "UNSUCCESSFUL_OR_INCOMPLETE_RESULT"),
        (("result", "input_accepted"), False, "WORKLOAD_NOT_ACCEPTED"),
        (("result", "output_accepted"), False, "WORKLOAD_NOT_ACCEPTED"),
        (("result", "actual_input_tokens"), 0, "INVALID_ACTUAL_INPUT_TOKENS"),
        (("result", "actual_input_tokens"), 12344, "ACTUAL_INPUT_BELOW_PROMOTED_WORKLOAD_BOUND"),
        (("result", "actual_output_tokens"), 2049, "OUTPUT_OUTSIDE_REQUEST_BOUND"),
    ],
)
def test_exact_contract_rejects_mismatch_even_when_resigned(path, value, reason) -> None:
    payload = _payload()
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ExternalWorkloadEvidenceError, match=reason):
        _validate(_seal(payload))


def test_tamper_and_arbitrary_json_fail_closed() -> None:
    package = json.loads(_seal())
    package["payload"]["result"]["actual_output_tokens"] = 1
    tampered = json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ExternalWorkloadEvidenceError, match="PAYLOAD_SEAL_MISMATCH"):
        _validate(tampered)
    arbitrary = json.dumps({"provider": "provider-explicit"}, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ExternalWorkloadEvidenceError, match="INVALID_ENVELOPE_SHAPE"):
        _validate(arbitrary)


def test_alias_or_upstream_inheritance_field_is_not_part_of_schema() -> None:
    payload = _payload()
    payload["route"]["upstream_model"] = payload["route"]["model"]
    with pytest.raises(ExternalWorkloadEvidenceError, match="INVALID_ROUTE_SHAPE"):
        _validate(_seal(payload))


def test_noncanonical_json_and_wrong_key_fail_closed() -> None:
    package = _seal()
    with pytest.raises(ExternalWorkloadEvidenceError, match="NONCANONICAL_PACKAGE"):
        _validate(package + b"\n")
    with pytest.raises(ExternalWorkloadEvidenceError, match="INVALID_SIGNATURE"):
        validate_external_workload_evidence_v1(package, expected=_expected(), verification_keys={"campaign-key-01": b"x" * 32})


def test_duplicate_promotion_identity_is_rejected() -> None:
    item = _validate()
    with pytest.raises(ExternalWorkloadEvidenceError, match="DUPLICATE_PROMOTION_IDENTITY"):
        deterministic_promotion_mapping_v1([item, item])


def test_nonce_is_globally_unique_across_distinct_promoted_cases() -> None:
    first = _validate()
    second_expected = _expected(
        case_id="probe-02",
        fixture_sha256="9" * 64,
        request_family_sha256="b" * 64,
        request_sha256="c" * 64,
    )
    second = _validate(
        _seal(_payload(second_expected)), expected=second_expected,
    )
    assert first.case_id != second.case_id
    assert first.evidence_sha256 != second.evidence_sha256
    assert first.nonce_sha256 == second.nonce_sha256
    with pytest.raises(ExternalWorkloadEvidenceError, match="NONCE_REUSE_FORBIDDEN"):
        deterministic_promotion_mapping_v1([first, second])
