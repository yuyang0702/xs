import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from novel_flywheel.generated_artifacts import (
    registered_business_wire_schema,
)
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureError,
    ProviderResponseCaptureStoreV1,
    parse_provider_protocol_input_bytes_v1,
)


def _metadata(**updates):
    value = {
        "execution_id": "offline-capture-run",
        "call_id": "offline-capture-run:1",
        "stage_id": "planning-semantic-v2",
        "provider_id_sha256": "1" * 64,
        "model_id_sha256": "2" * 64,
        "route_fingerprint": "3" * 64,
        "protocol": "anthropic",
        "contract_name": "short_maintenance_business_complete_v2",
        "contract_version": 1,
        "contract_schema_sha256": "4" * 64,
        "adapter_id": "anthropic",
        "adapter_version": 1,
        "content_type": "application/json",
        "encoding": "utf-8",
        "transport_complete": True,
    }
    value.update(updates)
    return value


def _store(tmp_path: Path) -> ProviderResponseCaptureStoreV1:
    repo = tmp_path / "repo"
    repo.mkdir()
    return ProviderResponseCaptureStoreV1(
        repo_root=repo, store_root=tmp_path / "private-captures",
    )


@pytest.mark.parametrize(
    "data",
    [
        b'{"value":"ok"}',
        '{"text":"换行\\n与雪☃"}\r\n'.encode("utf-8"),
        b"",
        b"x" * 65536,
    ],
    ids=["json", "unicode-newlines", "empty", "near-cap"],
)
def test_exact_capture_replay_preserves_every_byte(tmp_path: Path, data: bytes) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=data, metadata=metadata,
    )

    replayed, header = store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata,
    )

    assert replayed == data
    assert header["byte_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt.byte_length == len(data)


def test_sse_parser_replays_unicode_newline_and_escaping_exactly() -> None:
    raw = (
        b'data: {"type":"delta","text":"a\\nb"}\r\n\r\n'
        + 'data: {"type":"delta","text":"雪"}\n\n'.encode("utf-8")
        + b"data: [DONE]\r\n\r\n"
    )

    events, body = parse_provider_protocol_input_bytes_v1(
        raw, content_type="text/event-stream", encoding="utf-8",
    )

    assert body is None
    assert events == [
        {"type": "delta", "text": "a\nb"},
        {"type": "delta", "text": "雪"},
    ]


def test_duplicate_capture_is_rejected_without_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"first", metadata=metadata,
    )

    with pytest.raises(ProviderResponseCaptureError, match="DUPLICATE"):
        store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=b"second", metadata=metadata,
        )
    replayed, _ = store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata,
    )
    assert replayed == b"first"


def test_tampered_bytes_fail_before_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"original", metadata=metadata,
    )
    capture = next(store.root.glob("*.capture"))
    value = capture.read_bytes()
    capture.write_bytes(value[:-1] + b"X")

    with pytest.raises(ProviderResponseCaptureError, match="SHA256_MISMATCH"):
        store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=metadata,
        )


@pytest.mark.parametrize("field", [
    "execution_id", "call_id", "stage_id", "route_fingerprint",
    "contract_schema_sha256",
])
def test_wrong_identity_or_metadata_fails_closed(
    tmp_path: Path, field: str,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"identity", metadata=metadata,
    )
    changed = dict(metadata)
    changed[field] = "9" * 64 if field.endswith("sha256") or field == "route_fingerprint" else "wrong"

    with pytest.raises(ProviderResponseCaptureError, match="MISSING"):
        store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=changed,
        )


@pytest.mark.parametrize("field", [
    "authorization", "api_key", "credential", "headers", "prompt",
    "request_body", "story", "system", "tool_arguments", "user",
])
def test_capture_metadata_rejects_secret_or_request_fields(
    tmp_path: Path, field: str,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ProviderResponseCaptureError, match="PROHIBITED_METADATA"):
        store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=b"safe", metadata=_metadata(**{field: "forbidden"}),
        )


def test_malformed_provider_bytes_remain_replayable_after_parse_failure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    raw = b'{"broken":'
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=raw, metadata=metadata,
    )
    with pytest.raises(ProviderResponseCaptureError, match="JSON_INVALID"):
        parse_provider_protocol_input_bytes_v1(
            raw, content_type="application/json",
        )
    replayed, _ = store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata,
    )
    assert replayed == raw


def test_business_incomplete_conversion_replays_same_failure_family(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata(
        content_type="text/plain; purpose=contract-runtime-input",
    )
    raw = json.dumps({"facts": []}, separators=(",", ":")).encode("utf-8")
    store.capture(
        byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
        data=raw, metadata=metadata,
    )

    def failure_code(data: bytes) -> str:
        payload = json.loads(data.decode("utf-8"))
        schema = registered_business_wire_schema(
            "short_maintenance_business_complete_v2", {},
        )
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda item: list(item.absolute_path),
        )
        assert errors
        return "schema_validation_failed:" + errors[0].validator

    live_code = failure_code(raw)
    replayed, _ = store.replay(
        byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
        expected_metadata=metadata,
    )
    assert failure_code(replayed) == live_code


def test_capture_store_refuses_git_worktree_location(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ProviderResponseCaptureError, match="INSIDE_WORKTREE"):
        ProviderResponseCaptureStoreV1(
            repo_root=repo, store_root=repo / "captures",
        )


def test_audit_all_verifies_identity_and_returns_no_raw_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b'{"private":"response"}', metadata=metadata,
    )

    receipts = store.audit_all()

    assert len(receipts) == 1
    assert receipts[0]["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
    assert "private" not in json.dumps(receipts)


def test_audit_all_fails_closed_on_tampered_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b'{"ok":true}', metadata=_metadata(),
    )
    path = next(store.root.glob("*.capture"))
    payload = path.read_bytes()
    path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))

    with pytest.raises(
        ProviderResponseCaptureError,
        match="PROVIDER_RESPONSE_CAPTURE_AUDIT_SHA256_MISMATCH",
    ):
        store.audit_all()
