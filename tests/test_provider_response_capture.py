import hashlib
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    replay_captured_contract_runtime_input_v1,
)
from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    registered_business_wire_schema,
)
from novel_flywheel.model_diagnostics import domain_sha256
from novel_flywheel.provider_response_capture import (
    CAPTURE_MAGIC,
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureError,
    ProviderResponseCaptureStoreV1,
    FullShortTransportEvidenceStateV1,
    decide_full_short_transport_recovery_v1,
    extract_provider_reported_actual_usage_v1,
    parse_provider_protocol_input_bytes_v1,
)
from novel_flywheel.providers.http import (
    HttpProvider,
    SingleDispatchTransportPolicyV1,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


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
        "status_code": 200,
        "http_success": True,
        "response_status_sha256": hashlib.sha256(b"200").hexdigest(),
    }
    value.update(updates)
    return value


def _store(tmp_path: Path) -> ProviderResponseCaptureStoreV1:
    repo = tmp_path / "repo"
    repo.mkdir()
    return ProviderResponseCaptureStoreV1(
        repo_root=repo, store_root=tmp_path / "private-captures",
    )


def _anchor(receipt) -> str:
    return domain_sha256(
        "novel-flywheel-provider-response-capture-receipt-v1",
        receipt.document(),
    )


@pytest.mark.parametrize(
    "state,action,replay",
    [
        ("complete_valid_capture", "EXACT_LOCAL_REPLAY", True),
        ("explicit_provider_error", "TERMINAL_TYPED_PROVIDER_FAILURE", False),
        (
            "proven_pre_response_non_completion",
            "TERMINAL_NO_CURRENT_AUTHORITY_FOR_REDISPATCH", False,
        ),
        (
            "ambiguous_external_completion",
            "FAIL_CLOSED_RECONCILIATION_ONLY", False,
        ),
    ],
)
def test_full_short_transport_recovery_policy_is_closed_and_offline(
    state: str, action: str, replay: bool,
) -> None:
    decision = decide_full_short_transport_recovery_v1(
        FullShortTransportEvidenceStateV1(state),
    )
    assert decision.action == action
    assert decision.exact_local_replay_allowed is replay
    assert decision.network_retry_allowed is False
    assert decision.physical_dispatch_delta == 0


def test_full_short_transport_recovery_policy_rejects_unknown_state() -> None:
    with pytest.raises(ProviderResponseCaptureError, match="STATE_UNKNOWN"):
        decide_full_short_transport_recovery_v1("future_state")


class _CaptureObserver:
    def __init__(self) -> None:
        self.captures: list[dict] = []

    def before_http_dispatch(self, **_kwargs) -> None:
        return None

    def before_http_post(self) -> None:
        return None

    def before_network_request(self) -> None:
        return None

    def capture_provider_protocol_input(self, **kwargs) -> None:
        self.captures.append(kwargs)

    def after_http_failure(self, **_kwargs) -> None:
        return None

    def after_http_response(self, **_kwargs) -> None:
        return None


class _InterruptedEmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise httpx.ReadError("offline interrupted empty stream")
        yield b""  # pragma: no cover

    async def aclose(self) -> None:
        return None


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
        expected_receipt_sha256=_anchor(receipt),
    )

    assert replayed == data
    assert header["byte_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt.byte_length == len(data)


@pytest.mark.parametrize("status_code", [200, 503])
def test_capture_envelope_binds_normalized_http_classification(
    tmp_path: Path, status_code: int,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata(
        status_code=status_code,
        http_success=200 <= status_code < 300,
        response_status_sha256=hashlib.sha256(
            str(status_code).encode("ascii")
        ).hexdigest(),
    )
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b'{"error":"offline"}', metadata=metadata,
    )

    _, header = store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata,
        expected_receipt_sha256=_anchor(receipt),
    )

    assert header["status_code"] == status_code
    assert header["http_success"] is (200 <= status_code < 300)
    assert header["response_status_sha256"] == hashlib.sha256(
        str(status_code).encode("ascii")
    ).hexdigest()


def test_capture_rejects_inconsistent_http_classification(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(
        ProviderResponseCaptureError, match="HTTP_CLASSIFICATION_MISMATCH",
    ):
        store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=b"{}", metadata=_metadata(status_code=503),
        )


def test_capture_durable_write_zero_progress_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(
        "novel_flywheel.provider_response_capture.os.write",
        lambda _descriptor, _payload: 0,
    )

    with pytest.raises(
        ProviderResponseCaptureError, match="DURABLE_WRITE_NO_PROGRESS",
    ):
        store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=b"{}", metadata=_metadata(),
        )
    assert list(store.root.glob("*.capture")) == []


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


@pytest.mark.parametrize(
    "raw",
    [
        b'data: {"type":"message_stop"}',
        b'data: {"type":"message_stop"}\n',
        b'data: [DONE]\r\n',
    ],
    ids=["no-newline", "single-newline", "done-single-newline"],
)
def test_sse_parser_rejects_eof_without_empty_line_delimiter(raw: bytes) -> None:
    with pytest.raises(
        ProviderResponseCaptureError, match="SSE_EVENT_DELIMITER_MISSING",
    ):
        parse_provider_protocol_input_bytes_v1(
            raw, content_type="text/event-stream", encoding="utf-8",
        )


def test_duplicate_capture_is_rejected_without_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    receipt = store.capture(
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
        expected_receipt_sha256=_anchor(receipt),
    )
    assert replayed == b"first"


def test_tampered_bytes_fail_before_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    receipt = store.capture(
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
            expected_receipt_sha256=_anchor(receipt),
        )


def test_self_consistent_envelope_rewrite_fails_ledger_anchor(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"original", metadata=metadata,
    )
    ledger_anchor = domain_sha256(
        "novel-flywheel-provider-response-capture-receipt-v1",
        receipt.document(),
    )
    capture = next(store.root.glob("*.capture"))
    payload = capture.read_bytes()
    header_bytes, _data = payload[len(CAPTURE_MAGIC):].split(b"\n", 1)
    header = json.loads(header_bytes.decode("utf-8"))
    replacement = b"rewritten"
    header["byte_sha256"] = hashlib.sha256(replacement).hexdigest()
    header["byte_length"] = len(replacement)
    rewritten_header = json.dumps(
        header, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    capture.write_bytes(CAPTURE_MAGIC + rewritten_header + b"\n" + replacement)

    with pytest.raises(
        ProviderResponseCaptureError, match="LEDGER_RECEIPT_MISMATCH",
    ):
        store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=metadata,
            expected_receipt_sha256=ledger_anchor,
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
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"identity", metadata=metadata,
    )
    changed = dict(metadata)
    changed[field] = "9" * 64 if field.endswith("sha256") or field == "route_fingerprint" else "wrong"

    with pytest.raises(ProviderResponseCaptureError, match="MISSING"):
        store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=changed,
            expected_receipt_sha256=_anchor(receipt),
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


def test_capture_metadata_rejects_unknown_header_like_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(
        ProviderResponseCaptureError, match="METADATA_FIELD_UNKNOWN",
    ):
        store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=b"safe",
            metadata=_metadata(authorization_header="forbidden"),
        )


def test_malformed_provider_bytes_remain_replayable_after_parse_failure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    raw = b'{"broken":'
    receipt = store.capture(
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
        expected_receipt_sha256=_anchor(receipt),
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
    receipt = store.capture(
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
        expected_receipt_sha256=_anchor(receipt),
    )
    assert failure_code(replayed) == live_code


def test_crash_after_capture_before_conversion_restarts_from_ledger_anchor(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    raw = b'{"content":[{"type":"text","text":"ok"}]}'
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=raw, metadata=metadata,
    )
    anchor = domain_sha256(
        "novel-flywheel-provider-response-capture-receipt-v1",
        receipt.document(),
    )

    restarted = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root, store_root=store.root,
    )
    replayed, header = restarted.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata, expected_receipt_sha256=anchor,
    )
    events, body = parse_provider_protocol_input_bytes_v1(
        replayed, content_type=header["content_type"],
        encoding=header["encoding"],
    )

    assert events == []
    assert body == {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.asyncio
async def test_crash_after_conversion_before_stage_receipt_reenters_runtime(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata(
        content_type="text/plain; purpose=contract-runtime-input",
    )
    payload = {
        "facts": [], "state": {},
        "coverage": {"manuscript_sha256": "a" * 64, "complete": True},
        "disposition": "no_change",
        "no_change_reason": "Full manuscript inspected; no durable delta.",
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    receipt = store.capture(
        byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
        data=raw, metadata=metadata,
    )
    anchor = domain_sha256(
        "novel-flywheel-provider-response-capture-receipt-v1",
        receipt.document(),
    )
    registration = ARTIFACT_CONTRACT_REGISTRY[
        "short_maintenance_business_complete_v2"
    ]
    spec = ExecutableContractSpec(
        contract_name=registration.name,
        structured_contract=StructuredArtifactContract(
            name=registration.name, version=registration.version,
            schema=registered_business_wire_schema(registration.name, {}),
        ),
        semantic_normalizer=lambda value: dict(value),
        domain_validator=lambda value: value["coverage"]["manuscript_sha256"],
    )

    restarted = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root, store_root=store.root,
    )
    result = await replay_captured_contract_runtime_input_v1(
        capture_store=restarted, expected_metadata=metadata,
        expected_receipt_sha256=anchor, execution_spec=spec,
    )

    assert result.payload == payload
    assert result.domain_value == "a" * 64


def test_empty_captured_provider_entity_replay_fails_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    metadata = _metadata()
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b"", metadata=metadata,
    )
    anchor = domain_sha256(
        "novel-flywheel-provider-response-capture-receipt-v1",
        receipt.document(),
    )
    replayed, header = store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=metadata, expected_receipt_sha256=anchor,
    )

    with pytest.raises(ProviderResponseCaptureError, match="JSON_INVALID"):
        parse_provider_protocol_input_bytes_v1(
            replayed, content_type=header["content_type"],
            encoding=header["encoding"],
        )


@pytest.mark.asyncio
async def test_http_error_body_is_captured_before_status_failure() -> None:
    observer = _CaptureObserver()
    provider = HttpProvider(
        "https://offline.invalid", "not-a-real-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            503, content=b'{"error":"offline"}', request=request,
            headers={"content-type": "application/json"},
        ),
    ))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.post("messages", payload={}, headers={})
    finally:
        await provider.client.aclose()

    assert len(observer.captures) == 1
    assert observer.captures[0]["data"] == b'{"error":"offline"}'
    assert observer.captures[0]["status_code"] == 503
    assert observer.captures[0]["transport_complete"] is True


@pytest.mark.asyncio
async def test_zero_byte_interrupted_stream_records_incomplete_capture() -> None:
    observer = _CaptureObserver()
    provider = HttpProvider(
        "https://offline.invalid", "not-a-real-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=_InterruptedEmptyStream(), request=request,
            headers={"content-type": "text/event-stream"},
        )

    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(httpx.ReadError):
            await provider.post_stream("messages", payload={}, headers={})
    finally:
        await provider.client.aclose()

    assert len(observer.captures) == 1
    assert observer.captures[0]["data"] == b""
    assert observer.captures[0]["transport_complete"] is False


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
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b'{"private":"response"}', metadata=metadata,
    )

    receipts = store.audit_all(
        expected_receipt_sha256s=[_anchor(receipt)],
    )

    assert len(receipts) == 1
    assert receipts[0]["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
    assert receipts[0]["authoritative"] is True
    assert "private" not in json.dumps(receipts)


def test_audit_all_fails_closed_on_tampered_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = store.capture(
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
        store.audit_all(expected_receipt_sha256s=[_anchor(receipt)])


def test_unanchored_inspection_is_explicitly_non_authoritative_and_rewrite_fails_audit(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    receipt = store.capture(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        data=b'{"original":true}', metadata=_metadata(),
    )
    anchor = _anchor(receipt)
    path = next(store.root.glob("*.capture"))
    payload = path.read_bytes()
    header_bytes, _ = payload[len(CAPTURE_MAGIC):].split(b"\n", 1)
    header = json.loads(header_bytes.decode("utf-8"))
    replacement = b'{"rewritten":true}'
    header["byte_sha256"] = hashlib.sha256(replacement).hexdigest()
    header["byte_length"] = len(replacement)
    rewritten_header = json.dumps(
        header, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(CAPTURE_MAGIC + rewritten_header + b"\n" + replacement)

    inspected = store.inspect_all_unanchored()
    assert inspected[0]["authoritative"] is False
    assert inspected[0]["integrity_authority"] == (
        "UNANCHORED_NON_AUTHORITATIVE_INSPECTION"
    )
    with pytest.raises(
        ProviderResponseCaptureError, match="EXTERNAL_ANCHOR_MISMATCH",
    ):
        store.audit_all(expected_receipt_sha256s=[anchor])


@pytest.mark.parametrize(
    ("protocol", "content_type", "data", "expected"),
    [
        (
            "anthropic", "application/json",
            b'{"usage":{"input_tokens":10,"cache_read_input_tokens":3,"output_tokens":7}}',
            (13, 7),
        ),
        (
            "anthropic", "text/event-stream",
            b'data: {"type":"message_start","message":{"usage":{"input_tokens":11,"output_tokens":0}}}\n\n'
            b'data: {"type":"message_delta","usage":{"output_tokens":9}}\n\n'
            b'data: {"type":"message_stop"}\n\n',
            (11, 9),
        ),
        (
            "openai-chat", "application/json",
            b'{"usage":{"prompt_tokens":12,"completion_tokens":8}}',
            (12, 8),
        ),
        (
            "openai-chat", "text/event-stream",
            b'data: {"choices":[],"usage":{"prompt_tokens":13,"completion_tokens":6}}\n\n'
            b'data: [DONE]\n\n',
            (13, 6),
        ),
        (
            "openai-responses", "application/json",
            b'{"usage":{"input_tokens":14,"output_tokens":5}}',
            (14, 5),
        ),
        (
            "openai-responses", "text/event-stream",
            b'data: {"type":"response.completed","response":{"usage":{"input_tokens":15,"output_tokens":4}}}\n\n',
            (15, 4),
        ),
    ],
)
def test_exact_provider_usage_formats_are_hash_bound(
    protocol: str, content_type: str, data: bytes,
    expected: tuple[int, int],
) -> None:
    receipt = extract_provider_reported_actual_usage_v1(
        data, protocol=protocol, content_type=content_type,
    )

    assert (receipt["input_tokens"], receipt["output_tokens"]) == expected
    assert receipt["provider_entity_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["usage_record_count"] >= 1
    assert len(receipt["usage_receipt_sha256"]) == 64


@pytest.mark.parametrize(
    ("protocol", "content_type", "data", "reason"),
    [
        (
            "anthropic", "application/json", b'{"content":[]}',
            "PROVIDER_REPORTED_USAGE_MISSING",
        ),
        (
            "openai-chat", "text/event-stream",
            b'data: {"usage":{"prompt_tokens":2,"completion_tokens":9}}\n\n'
            b'data: {"usage":{"prompt_tokens":2,"completion_tokens":8}}\n\n'
            b'data: [DONE]\n\n',
            "PROVIDER_REPORTED_USAGE_OUTPUT_NON_MONOTONIC",
        ),
        (
            "openai-chat", "text/event-stream",
            b'data: {"usage":{"prompt_tokens":2,"completion_tokens":1}}\n\n',
            "PROVIDER_REPORTED_USAGE_SSE_TERMINAL_MISSING",
        ),
        (
            "openai-responses", "application/json", b'{not-json}',
            "PROVIDER_RESPONSE_REPLAY_JSON_INVALID",
        ),
    ],
)
def test_provider_usage_missing_conflicting_or_incomplete_fails_closed(
    protocol: str, content_type: str, data: bytes, reason: str,
) -> None:
    with pytest.raises(ProviderResponseCaptureError, match=reason):
        extract_provider_reported_actual_usage_v1(
            data, protocol=protocol, content_type=content_type,
        )
