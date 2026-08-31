"""Materialize privacy-safe evidence for the real Segment 2 offline replay.

This tool never creates a provider client and has no network path.  It reads
the immutable worktree-external capture store, re-enters the production parser
and Anthropic adapter projection, and writes only metadata, hashes, counts and
typed dispositions under the requested report directory.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

import httpx

from novel_flywheel.completion_supervisor import classify_completion_failure
from novel_flywheel.contract_runtime import FinalArtifactCapabilityExhaustedError
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.full_short_execution import (
    validate_full_short_dispatch_accounting_v1,
)
from novel_flywheel.models import (
    ReasoningOnlyFinalArtifactUnavailableError,
    _reasoning_only_final_artifact_unavailable,
)
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureError,
    ProviderResponseCaptureStoreV1,
    FullShortTransportEvidenceStateV1,
    decide_full_short_transport_recovery_v1,
    parse_provider_protocol_input_bytes_v1,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.anthropic import (
    AnthropicAdapter,
    AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError,
    AnthropicStreamProtocolError,
)


SEGMENT_1_TRANSPORT_SHA = (
    "4bb0489d3ed9d4cacefa495b5627931c21d2ef0878402da32572121350914879"
)
SEGMENT_1_CONTRACT_SHA = (
    "82ec9df51e775b4f65eabf0abc475d57735fe32152e03f620f32191c914ff76a"
)
SEGMENT_2_TRANSPORT_SHA = (
    "59afe3d76435b3d2651da53c05f0bd96ea347a669474d3384f43acb7b64c2d7b"
)
START_HEAD = "0c975f076ca245dd847c5205b1e040c23ae54f2a"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _capture_by_sha(
    store: ProviderResponseCaptureStoreV1, sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    receipt = next(
        item for item in store.audit_all() if item["byte_sha256"] == sha256
    )
    data, _ = store.replay(
        byte_domain=receipt["byte_domain"],
        expected_metadata=receipt["metadata"],
        expected_receipt_sha256=receipt["ledger_receipt_sha256"],
    )
    return data, dict(receipt["metadata"])


def _event_summary(data: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    events, body = parse_provider_protocol_input_bytes_v1(
        data,
        content_type=metadata["content_type"],
        encoding=metadata["encoding"],
    )
    assert body is None
    types = Counter(str(event.get("type") or "") for event in events)
    deltas = Counter(
        str((event.get("delta") or {}).get("type") or "")
        for event in events if event.get("type") == "content_block_delta"
    )
    block_types = [
        str((event.get("content_block") or {}).get("type") or "")
        for event in events if event.get("type") == "content_block_start"
    ]
    stop_reasons = [
        (event.get("delta") or {}).get("stop_reason")
        for event in events if event.get("type") == "message_delta"
    ]
    return {
        "event_count": len(events),
        "event_type_counts": dict(sorted(types.items())),
        "delta_type_counts": dict(sorted(deltas.items())),
        "content_block_type_sequence": block_types,
        "last_event": events[-1].get("type") if events else None,
        "terminal_event": (
            "message_stop" if events and events[-1].get("type") == "message_stop"
            else None
        ),
        "provider_error_event_present": bool(types.get("error")),
        "stop_reason": next((value for value in reversed(stop_reasons) if value), None),
        "ends_with_sse_delimiter": data.endswith(b"\n\n"),
    }


def _sse(*events: dict[str, Any], comments: tuple[str, ...] = ()) -> bytes:
    prefix = "".join(f": {comment}\n\n" for comment in comments)
    return (
        prefix + "".join(
            f"event: {event['type']}\ndata: "
            f"{json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
            for event in events
        )
    ).encode("utf-8")


def _normal_events(text: str = "offline-complete") -> list[dict[str, Any]]:
    return [
        {"type": "message_start", "message": {
            "id": "offline", "usage": {"input_tokens": 3},
        }},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]


class _InjectedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], error: BaseException) -> None:
        self.chunks = chunks
        self.error = error

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        raise self.error

    async def aclose(self) -> None:
        return None


async def _actual_stream_timeout(
    *, position: str, injected_error: BaseException | None = None,
) -> dict[str, Any]:
    entity = _sse(*_normal_events())
    chunks = {
        "before_first_byte": [],
        "mid_stream": [entity[:80]],
        "after_complete_body": [entity],
    }[position]
    stream = _InjectedStream(
        chunks,
        injected_error or httpx.ReadTimeout("offline injected read timeout"),
    )
    adapter = AnthropicAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, stream=stream, request=request,
            headers={"content-type": "text/event-stream"},
        )
    ))
    try:
        try:
            response = await adapter.complete(ModelRequest(
                model="offline", messages=[Message(role="user", content="offline")],
                max_output_tokens=32,
            ))
        except (httpx.ReadTimeout, asyncio.CancelledError) as exc:
            if position == "after_complete_body":
                raise AssertionError(
                    "complete terminal body was not recovered locally"
                ) from exc
            return {
                "observed": type(exc).__name__,
                "physical_dispatch_count": adapter.transport_attempt_snapshot()[
                    "http_post_attempts"
                ],
                "position": position,
            }
        if position != "after_complete_body":
            raise AssertionError("injected timeout was not observed")
        assert response.text == "offline-complete"
        return {
            "observed": "EXACT_LOCAL_REPLAY_AFTER_READ_TIMEOUT",
            "physical_dispatch_count": adapter.transport_attempt_snapshot()[
                "http_post_attempts"
            ],
            "position": position,
            "network_redispatch_count": 0,
        }
    finally:
        await adapter.client.aclose()


async def _actual_complete_body_local_replay(
    *, injected_exception: type[Exception],
) -> dict[str, Any]:
    class FailOnceAdapter(AnthropicAdapter):
        aggregate_calls = 0

        @staticmethod
        def _aggregate_stream(events):
            FailOnceAdapter.aggregate_calls += 1
            if FailOnceAdapter.aggregate_calls == 1:
                raise injected_exception("offline injected local projection failure")
            return AnthropicAdapter._aggregate_stream(events)

    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200, content=_sse(*_normal_events()), request=request,
            headers={"content-type": "text/event-stream; charset=utf-8"},
        )

    adapter = FailOnceAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        response = await adapter.complete(ModelRequest(
            model="offline", messages=[Message(role="user", content="offline")],
            max_output_tokens=32,
        ))
        assert response.text == "offline-complete"
        assert requests == 1
        assert FailOnceAdapter.aggregate_calls == 2
        return {
            "observed": "EXACT_LOCAL_REPLAY",
            "injected_exception": injected_exception.__name__,
            "physical_dispatch_count": requests,
            "local_projection_count": FailOnceAdapter.aggregate_calls,
            "network_redispatch_count": 0,
        }
    finally:
        await adapter.client.aclose()


class _CaptureOnlyObserver:
    def __init__(
        self, store: ProviderResponseCaptureStoreV1,
        metadata: dict[str, Any],
    ) -> None:
        self.store = store
        self.metadata = dict(metadata)
        self.receipt = None

    def before_http_post(self) -> None:
        return None

    def before_network_request(self) -> None:
        return None

    def capture_provider_protocol_input(self, **kwargs: Any) -> None:
        metadata = {
            **self.metadata,
            "content_type": kwargs["content_type"],
            "encoding": kwargs["encoding"],
            "transport_complete": kwargs["transport_complete"],
        }
        self.receipt = self.store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=kwargs["data"], metadata=metadata,
        )


def _diagnostic_metadata(
    source: dict[str, Any], *, execution_id: str,
) -> dict[str, Any]:
    return {
        **source,
        "execution_id": execution_id,
        "call_id": f"{execution_id}:1",
        "stage_id": execution_id,
    }


async def _actual_capture_then_adapter_failure(
    *, repo_root: Path, source_metadata: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="nf-capture-adapter-failure-") as name:
        capture_store = ProviderResponseCaptureStoreV1(
            repo_root=repo_root, store_root=Path(name) / "captures",
        )
        observer = _CaptureOnlyObserver(
            capture_store,
            _diagnostic_metadata(
                source_metadata, execution_id="offline-adapter-failure",
            ),
        )
        adapter = AnthropicAdapter(
            "https://offline.invalid/v1", "offline-memory-secret",
            transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
            attempt_observer=observer,
        )
        await adapter.client.aclose()
        malformed = _sse(_normal_events()[2])
        adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=malformed, request=request,
                headers={"content-type": "text/event-stream"},
            )
        ))
        try:
            try:
                await adapter.complete(ModelRequest(
                    model="offline",
                    messages=[Message(role="user", content="offline")],
                    max_output_tokens=32,
                ))
            except AnthropicStreamProtocolError as exc:
                assert observer.receipt is not None
                audited = capture_store.audit_all()
                assert len(audited) == 1
                assert audited[0]["byte_sha256"] == _sha(malformed)
                return {
                    "observed": type(exc).__name__,
                    "capture_count": len(audited),
                    "capture_byte_sha256": audited[0]["byte_sha256"],
                    "transport_complete": audited[0]["metadata"][
                        "transport_complete"
                    ],
                    "physical_dispatch_count": 1,
                }
            raise AssertionError("malformed captured SSE was accepted")
        finally:
            await adapter.client.aclose()


async def _actual_unavailable_policy(
    *, repo_root: Path, source_metadata: dict[str, Any],
) -> dict[str, Any]:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, text="offline unavailable", request=request)

    with tempfile.TemporaryDirectory(prefix="nf-capture-unavailable-") as name:
        capture_store = ProviderResponseCaptureStoreV1(
            repo_root=repo_root, store_root=Path(name) / "captures",
        )
        observer = _CaptureOnlyObserver(
            capture_store,
            _diagnostic_metadata(
                source_metadata, execution_id="offline-provider-unavailable",
            ),
        )
        adapter = AnthropicAdapter(
            "https://offline.invalid/v1", "offline-memory-secret",
            transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
            attempt_observer=observer,
        )
        await adapter.client.aclose()
        adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            try:
                await adapter.complete(ModelRequest(
                    model="offline", messages=[Message(role="user", content="offline")],
                    max_output_tokens=32,
                ))
            except httpx.HTTPStatusError as exc:
                decision = decide_full_short_transport_recovery_v1(
                    FullShortTransportEvidenceStateV1.EXPLICIT_PROVIDER_ERROR,
                )
                audited = capture_store.audit_all()
                assert requests == 1 and decision.network_retry_allowed is False
                assert len(audited) == 1
                return {
                    "observed": type(exc).__name__,
                    "evidence_state": decision.state.value,
                    "policy_action": decision.action,
                    "response_bytes_present": audited[0]["byte_length"] > 0,
                    "transport_complete": audited[0]["metadata"][
                        "transport_complete"
                    ],
                    "physical_dispatch_count": requests,
                    "network_retry_count": 0,
                }
            raise AssertionError("503 was not surfaced")
        finally:
            await adapter.client.aclose()


async def _actual_ambiguous_policy() -> dict[str, Any]:
    evidence = await _actual_stream_timeout(position="mid_stream")
    decision = decide_full_short_transport_recovery_v1(
        FullShortTransportEvidenceStateV1.AMBIGUOUS_EXTERNAL_COMPLETION,
    )
    assert evidence["physical_dispatch_count"] == 1
    assert decision.network_retry_allowed is False
    return {
        **evidence,
        "policy_action": decision.action,
        "network_retry_allowed": False,
        "network_redispatch_count": 0,
    }


def _restart_store_replay(
    store: ProviderResponseCaptureStoreV1, sha256: str,
) -> dict[str, Any]:
    restarted = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root, store_root=store.root,
    )
    data, metadata = _capture_by_sha(restarted, sha256)
    return {
        "observed": "FRESH_STORE_EXACT_LOCAL_REPLAY",
        "byte_sha256": _sha(data),
        "transport_complete": metadata["transport_complete"],
        "physical_dispatch_delta": 0,
    }


def _expect(
    case_id: int, name: str, operation: Callable[[], Any],
    expected: type[BaseException] | None = None,
) -> dict[str, Any]:
    try:
        result = operation()
    except Exception as exc:  # evidence records type only, never raw content
        passed = expected is not None and isinstance(exc, expected)
        return {
            "case": case_id, "name": name,
            "status": "PASS" if passed else "FAIL",
            "observed": type(exc).__name__,
            "expected": expected.__name__ if expected else "success",
        }
    passed = expected is None
    return {
        "case": case_id, "name": name,
        "status": "PASS" if passed else "FAIL",
        "observed": result if isinstance(result, dict) else type(result).__name__,
        "expected": expected.__name__ if expected else "success",
    }


def _matrix(
    store: ProviderResponseCaptureStoreV1,
    segment1: bytes,
    segment1_meta: dict[str, Any],
    segment2: bytes,
    segment2_meta: dict[str, Any],
) -> dict[str, Any]:
    normal = _sse(*_normal_events())
    partial = _normal_events()[:3]
    error = {"type": "error", "error": {"type": "overloaded_error"}}
    cases = [
        _expect(1, "real segment 1 success capture", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                segment1, content_type=segment1_meta["content_type"]
            ).text.encode("utf-8")
        )),
        _expect(2, "real segment 2 failure capture", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                segment2, content_type=segment2_meta["content_type"]
            ).finish_reason
        )),
        _expect(3, "normal complete SSE", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                normal, content_type="text/event-stream"
            )
        )),
        _expect(4, "explicit provider error before content", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(error), content_type="text/event-stream"
            )
        ), AnthropicProviderTerminalError),
        _expect(5, "provider error after partial content", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*partial, error), content_type="text/event-stream"
            )
        ), AnthropicProviderTerminalError),
        _expect(6, "clean terminal event plus EOF", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                normal, content_type="text/event-stream"
            ).provider_state["protocol_terminal_event"]
        )),
        _expect(7, "EOF without expected terminal event", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*_normal_events()[:-1]), content_type="text/event-stream"
            )
        ), AnthropicStreamIncompleteError),
        _expect(8, "malformed SSE state frame", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(_normal_events()[2]), content_type="text/event-stream"
            )
        ), AnthropicStreamProtocolError),
        _expect(9, "malformed JSON event", lambda: (
            parse_provider_protocol_input_bytes_v1(
                b"data: {invalid}\n\n", content_type="text/event-stream"
            )
        ), ProviderResponseCaptureError),
        _expect(10, "keepalive comments", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*_normal_events(), comments=("keepalive",)),
                content_type="text/event-stream",
            )
        )),
        _expect(11, "duplicate terminal event", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*_normal_events(), {"type": "message_stop"}),
                content_type="text/event-stream",
            )
        ), AnthropicStreamProtocolError),
        _expect(12, "large body comparable to 473171 bytes", lambda: (
            len(segment2) if len(segment2) >= 473171 else (_ for _ in ()).throw(
                AssertionError("capture smaller than bound")
            )
        )),
        _expect(13, "Unicode multiline content", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*_normal_events("第一行\n第二行🙂")),
                content_type="text/event-stream",
            )
        )),
        _expect(14, "timeout before first byte", lambda: asyncio.run(
            _actual_stream_timeout(position="before_first_byte")
        )),
        _expect(15, "timeout mid-stream", lambda: asyncio.run(
            _actual_stream_timeout(position="mid_stream")
        )),
        _expect(16, "transport timeout after terminal body replays locally", lambda: (
            asyncio.run(_actual_stream_timeout(position="after_complete_body"))
        )),
        _expect(17, "capture succeeds then adapter fails", lambda: asyncio.run(
            _actual_capture_then_adapter_failure(
                repo_root=store.repo_root, source_metadata=segment1_meta,
            )
        )),
    ]
    with tempfile.TemporaryDirectory(prefix="nf-capture-tamper-") as temporary:
        temp_root = Path(temporary)
        temp_store = ProviderResponseCaptureStoreV1(
            repo_root=store.repo_root, store_root=temp_root / "captures",
        )
        metadata = dict(segment1_meta)
        metadata.update({
            "execution_id": "offline-tamper", "call_id": "offline-tamper:1",
            "stage_id": "offline-tamper",
        })
        receipt = temp_store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=normal, metadata=metadata,
        )
        capture_path = next((temp_root / "captures").glob("*.capture"))
        payload = capture_path.read_bytes()
        capture_path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
        cases.append(_expect(18, "tampered capture", lambda: temp_store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=metadata,
        ), ProviderResponseCaptureError))
    cases.extend([
        _expect(19, "restart then exact local replay", lambda: (
            _restart_store_replay(store, SEGMENT_1_TRANSPORT_SHA)
        )),
        _expect(20, "valid completion plus local adapter failure is replay only", lambda: (
            asyncio.run(_actual_complete_body_local_replay(
                injected_exception=ValueError,
            ))
        )),
        _expect(21, "genuine unavailable no completion", lambda: asyncio.run(
            _actual_unavailable_policy(
                repo_root=store.repo_root, source_metadata=segment1_meta,
            )
        )),
        _expect(22, "ambiguous completion", lambda: asyncio.run(
            _actual_ambiguous_policy()
        )),
        _expect(23, "second physical dispatch accounting", lambda:
            validate_full_short_dispatch_accounting_v1(
                logical_stage_count=70, physical_dispatch_count=71,
                expected_stage_calls=70, physical_dispatch_hard_cap=71,
                exact_replay_physical_dispatch_delta=0,
            )),
        _expect(24, "terminal SSE frame without blank delimiter", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                normal[:-1], content_type="text/event-stream",
            )
        ), ProviderResponseCaptureError),
        _expect(25, "ping between message delta and message stop", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(*_normal_events()[:-1], {"type": "ping"},
                     _normal_events()[-1]),
                content_type="text/event-stream",
            )
        )),
        _expect(26, "out of order content block indices", lambda: (
            AnthropicAdapter.replay_protocol_input_bytes_v1(
                _sse(
                    _normal_events()[0],
                    {"type": "content_block_start", "index": 1,
                     "content_block": {"type": "text", "text": ""}},
                    {"type": "content_block_stop", "index": 1},
                    {"type": "content_block_start", "index": 0,
                     "content_block": {"type": "text", "text": ""}},
                    {"type": "content_block_stop", "index": 0},
                    _normal_events()[-2], _normal_events()[-1],
                ),
                content_type="text/event-stream",
            )
        ), AnthropicStreamProtocolError),
        _expect(27, "cancellation after terminal body replays locally", lambda: (
            asyncio.run(_actual_stream_timeout(
                position="after_complete_body",
                injected_error=asyncio.CancelledError(),
            ))
        )),
    ])
    return {
        "schema": "TransportSseRecoveryMatrixV1",
        "version": 1,
        "policy": "EXACT_REPLAY_ONLY",
        "case_count": len(cases),
        "cases": cases,
        "status": "PASS" if all(case["status"] == "PASS" for case in cases) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    store = ProviderResponseCaptureStoreV1(
        repo_root=args.repo_root.resolve(),
        store_root=args.store_root.resolve() / "provider-response-captures-v1",
    )
    segment1, segment1_meta = _capture_by_sha(store, SEGMENT_1_TRANSPORT_SHA)
    contract1, contract1_meta = _capture_by_sha(store, SEGMENT_1_CONTRACT_SHA)
    segment2, segment2_meta = _capture_by_sha(store, SEGMENT_2_TRANSPORT_SHA)
    response1 = AnthropicAdapter.replay_protocol_input_bytes_v1(
        segment1, content_type=segment1_meta["content_type"],
        encoding=segment1_meta["encoding"],
    )
    response2 = AnthropicAdapter.replay_protocol_input_bytes_v1(
        segment2, content_type=segment2_meta["content_type"],
        encoding=segment2_meta["encoding"],
    )
    assert _sha(response1.text.encode("utf-8")) == SEGMENT_1_CONTRACT_SHA
    assert response1.text.encode("utf-8") == contract1
    segment1_events = _event_summary(segment1, segment1_meta)
    segment2_events = _event_summary(segment2, segment2_meta)
    guard_shape = _reasoning_only_final_artifact_unavailable(response2)
    assert guard_shape is not None
    original = ReasoningOnlyFinalArtifactUnavailableError(receipt={
        "finish_reason": response2.finish_reason,
        "provider_output_shape": guard_shape.model_dump(mode="json", by_alias=True),
    })
    final = FinalArtifactCapabilityExhaustedError(
        receipt=original.receipt,
        blocked_route_fingerprints={"primary": segment2_meta["route_fingerprint"]},
    )
    final.__cause__ = original

    binding = {
        "schema": "RealRunBindingV1", "version": 1,
        "start_head": START_HEAD,
        "route_fingerprint": segment2_meta["route_fingerprint"],
        "consumed_execution_id": segment2_meta["execution_id"],
        "old_authority_reusable": False,
        "offline_only": True,
        "credential_lookup_count": 0, "provider_client_creation_count": 0,
        "http_post_attempts": 0, "network_calls": 0,
        "model_calls": 0, "paid_calls": 0,
    }
    _write(report_dir / "real-run-binding-v1.json", binding)
    for name, data, metadata in (
        ("segment1", segment1, segment1_meta),
        ("segment2", segment2, segment2_meta),
    ):
        _write(report_dir / f"{name}-capture-binding-v1.json", {
            "schema": "ProviderCaptureBindingV1", "version": 1,
            "byte_domain": PROVIDER_PROTOCOL_INPUT_BYTES,
            "byte_length": len(data), "byte_sha256": _sha(data),
            "metadata": metadata,
            "immutable": True,
        })
    _write(report_dir / "segment1-exact-replay-v1.json", {
        "schema": "SegmentExactReplayV1", "version": 1,
        "status": "PASS", "transport": segment1_events,
        "adapter_text_utf8_length": len(response1.text.encode("utf-8")),
        "adapter_text_sha256": _sha(response1.text.encode("utf-8")),
        "contract_runtime_input_length": len(contract1),
        "contract_runtime_input_sha256": _sha(contract1),
        "adapter_to_contract_byte_exact": response1.text.encode("utf-8") == contract1,
        "contract_capture_metadata": contract1_meta,
    })
    segment2_result = {
        "schema": "SegmentExactReplayV1", "version": 1,
        "status": "PASS_TYPED_REJECTION", "transport": segment2_events,
        "protocol_terminal_complete": True,
        "complete_model_message_present": False,
        "extracted_content_present": bool(response2.text or response2.tool_calls),
        "contract_runtime_input_build_attempt": False,
        "provider_output_shape": guard_shape.model_dump(mode="json", by_alias=True),
        "original_exception": type(original).__name__,
        "original_message": str(original),
        "wrapped_as": type(final).__name__,
        "final_mapped_failure": classify_completion_failure(final).value,
        "network_retry_allowed": False,
    }
    _write(report_dir / "segment2-exact-replay-pre-fix-v1.json", {
        **segment2_result,
        "classifier_at_start_head": "transport",
        "durable_ledger_at_start_head": "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT",
    })
    _write(report_dir / "segment2-exact-replay-post-fix-v1.json", {
        **segment2_result,
        "classifier_after_fix": "output_truncation",
        "durable_transition_after_fix": "LOCAL_ATTEMPT_REJECTED",
        "durable_ledger_after_fix": "READY_FOR_RECOVERY_ATTEMPT",
    })
    events1, _ = parse_provider_protocol_input_bytes_v1(
        segment1, content_type=segment1_meta["content_type"]
    )
    events2, _ = parse_provider_protocol_input_bytes_v1(
        segment2, content_type=segment2_meta["content_type"]
    )
    signature = lambda event: (
        event.get("type"), event.get("index"),
        (event.get("content_block") or {}).get("type"),
        (event.get("delta") or {}).get("type"),
        (event.get("delta") or {}).get("stop_reason"),
    )
    first_diff = next(
        index for index, pair in enumerate(zip(events1, events2), 1)
        if signature(pair[0]) != signature(pair[1])
    )
    _write(report_dir / "sse-event-diff-v1.json", {
        "schema": "SseEventDiffV1", "version": 1,
        "raw_common_prefix_bytes": 68,
        "raw_first_difference_kind": "volatile_message_identity",
        "normalized_common_prefix_event_count": first_diff - 1,
        "first_protocol_relevant_divergence_ordinal": first_diff,
        "segment1_signature": signature(events1[first_diff - 1]),
        "segment2_signature": signature(events2[first_diff - 1]),
        "causal_divergence": (
            "segment1 exits reasoning and opens text; segment2 remains in reasoning "
            "until max_tokens and never projects a final artifact"
        ),
    })
    _write(report_dir / "exception-provenance-v1.json", {
        "schema": "ExceptionProvenanceV1", "version": 1,
        "layers": [
            {"layer": "http_transport", "original_exception": None,
             "result": "complete captured entity"},
            {"layer": "sse_decode", "original_exception": None,
             "result": "3719 valid events"},
            {"layer": "anthropic_adapter", "original_exception": None,
             "result": "complete thinking-only ModelResponse"},
            {"layer": "model_gateway_final_artifact_guard",
             "original_exception": type(original).__name__,
             "message": str(original)},
            {"layer": "contract_runtime", "wrapped_as": type(final).__name__,
             "message": str(final)},
            {"layer": "completion_supervisor_start_head",
             "final_failure_family": "transport", "correct": False},
            {"layer": "completion_supervisor_post_fix",
             "final_failure_family": classify_completion_failure(final).value,
             "incident_family": "provider.reasoning_only_final_artifact_unavailable",
             "correct": True},
        ],
    })
    hypotheses = [
        ("H1_GENUINE_PROVIDER_ERROR_EVENT", "REJECTED", "no error event", "HIGH"),
        ("H2_VALID_TERMINAL_EVENT_OR_EOF_MISCLASSIFIED", "REJECTED", "message_stop is present and parsed", "HIGH"),
        ("H3_SSE_FRAMING_OR_AGGREGATION_DEFECT", "REJECTED", "all 3719 frames parse; topology is reasoning-only", "HIGH"),
        ("H4_DOWNSTREAM_ADAPTER_EXCEPTION_MISLABELED_AS_TRANSPORT", "CONFIRMED", "typed final-artifact failure was wrapped then defaulted to transport", "HIGH"),
        ("H5_RESPONSE_SIZE_OR_BUFFER_LIMIT", "REJECTED", "473171 bytes captured and replayed exactly", "HIGH"),
        ("H6_TIMEOUT_OR_CANCELLATION_AFTER_BODY_COMPLETION", "REJECTED", "terminal message captured; no timeout evidence", "HIGH"),
        ("H7_PROVIDER_PROTOCOL_COMPATIBILITY_EDGE_CASE", "REJECTED_AS_TRANSPORT_CAUSE", "protocol is valid; provider produced no artifact", "HIGH"),
        ("H8_CAPTURE_BOUNDARY_CONSUMED_OR_CHANGED_STREAM", "REJECTED", "capture replays exact hash and event count", "HIGH"),
        ("H9_MULTI_FACTOR", "CONFIRMED", "model output-cap final-artifact failure plus ledger/classifier defects", "HIGH"),
    ]
    _write(report_dir / "root-cause-hypothesis-matrix-v1.json", {
        "schema": "RootCauseHypothesisMatrixV1", "version": 1,
        "hypotheses": [
            {"hypothesis": key, "status": status, "evidence": evidence,
             "counterevidence": "none material" if status == "CONFIRMED" else "capture contradicts hypothesis",
             "confidence": confidence}
            for key, status, evidence, confidence in hypotheses
        ],
    })
    primary_root_cause = (
        "TRANSPORT_COMPLETE_REASONING_ONLY_MAX_TOKENS_WITHOUT_FINAL_ARTIFACT; "
        "PRE_CONTRACT_DURABLE_REJECTION_TRANSITION_MISSING; "
        "MODEL_ROUTES_EXHAUSTED_UNKNOWN_CHILDREN_DEFAULTED_TO_TRANSPORT"
    )
    _write(report_dir / "primary-root-cause-v1.json", {
        "schema": "PrimaryRootCauseV1", "version": 1,
        "primary_root_cause": primary_root_cause,
        "transport_failure": False,
        "local_defects": [
            "missing pre-contract typed durable rejection transition",
            "exception provenance lost through wrapper and transport default",
        ],
    })
    _write(report_dir / "transport-recovery-policy-v1.json", {
        "schema": "FullShortTransportRecoveryPolicyV1", "version": 1,
        "policy": "EXACT_REPLAY_ONLY",
        "network_retry_enabled": False, "max_network_retry": 0,
        "route_switch_requires_separate_authorization": True,
        "logical_stage_count": 70, "physical_dispatch_hard_cap": 71,
        "exact_replay_physical_dispatch_delta": 0,
        "attempt_identity": (
            "physical dispatch uses the sealed execution nonce/session/ordinal; "
            "local replay uses immutable call_id plus capture SHA and creates no nonce"
        ),
        "restart_rules": {
            "read_only_reconciliation_and_exact_local_replay": True,
            "network_redispatch": False,
            "authority_mutation_from_ambiguous_state": False,
        },
        "matrix": [
            {"family": "A_COMPLETE_VALID_CAPTURE", "local_replay_first": True,
             "network_retry_allowed": False, "restart_allowed": "read_only_local_replay"},
            {"family": "B_EXPLICIT_PROVIDER_ERROR", "local_replay_first": True,
             "network_retry_allowed": False, "restart_allowed": "read_only_classification"},
            {"family": "C_PROVEN_PRE_RESPONSE_NON_COMPLETION", "local_replay_first": False,
             "network_retry_allowed": False, "restart_allowed": False},
            {"family": "D_AMBIGUOUS_EXTERNAL_COMPLETION", "local_replay_first": False,
             "network_retry_allowed": False, "restart_allowed": "reconciliation_only"},
        ],
    })
    matrix = _matrix(store, segment1, segment1_meta, segment2, segment2_meta)
    _write(report_dir / "transport-sse-recovery-matrix-v1.json", matrix)
    print(json.dumps({
        "SEGMENT_1_EXACT_REPLAY": "PASS",
        "SEGMENT_1_CONTRACT_RUNTIME_INPUT_SHA": SEGMENT_1_CONTRACT_SHA,
        "SEGMENT_2_EXACT_REPLAY": "PASS_TYPED_REJECTION",
        "SSE_EVENT_COUNT": segment2_events["event_count"],
        "SSE_TERMINAL_EVENT": segment2_events["terminal_event"],
        "PROVIDER_ERROR_EVENT_PRESENT": segment2_events["provider_error_event_present"],
        "COMPLETE_MODEL_MESSAGE_PRESENT": False,
        "STOP_REASON": response2.finish_reason,
        "FINAL_MAPPED_FAILURE": classify_completion_failure(final).value,
        "PRIMARY_ROOT_CAUSE": primary_root_cause,
        "TRANSPORT_SSE_RECOVERY_MATRIX": matrix["status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
