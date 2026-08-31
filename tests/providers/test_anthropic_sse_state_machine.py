from __future__ import annotations

import asyncio
import json

import pytest
import httpx

from novel_flywheel.providers.anthropic import (
    AnthropicAdapter,
    AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError,
    AnthropicStreamProtocolError,
)
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.production_incidents import classify_production_failure


def _sse(*events: dict) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: "
        f"{json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for event in events
    ).encode("utf-8")


def _complete_events(text: str = "可验证的完整结果") -> list[dict]:
    return [
        {
            "type": "message_start",
            "message": {"id": "offline", "usage": {"input_tokens": 7}},
        },
        {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta", "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 9},
        },
        {"type": "message_stop"},
    ]


class _CaptureObserver:
    def __init__(self) -> None:
        self.captures: list[dict] = []
        self.outcomes: list[str] = []

    def before_http_dispatch(self, **_kwargs) -> None:
        return None

    def before_http_post(self) -> None:
        return None

    def before_network_request(self) -> None:
        return None

    def capture_provider_protocol_input(self, **kwargs) -> None:
        self.captures.append(kwargs)

    def after_http_failure(self, *, failure_kind: str) -> None:
        self.outcomes.append(f"failure:{failure_kind}")

    def after_http_response(self, *, status_code: int) -> None:
        self.outcomes.append(f"response:{status_code}")


class _InjectedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], failure: BaseException) -> None:
        self.chunks = chunks
        self.failure = failure

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        raise self.failure

    async def aclose(self) -> None:
        return None


def test_exact_local_replay_uses_terminal_state_and_shared_projection() -> None:
    response = AnthropicAdapter.replay_protocol_input_bytes_v1(
        _sse(*_complete_events()), content_type="text/event-stream; charset=utf-8",
    )

    assert response.text == "可验证的完整结果"
    assert response.finish_reason == "end_turn"
    assert response.provider_state["transport_complete"] is True
    assert response.provider_state["protocol_terminal_event"] == "message_stop"
    assert response.output_shape is not None
    assert response.output_shape.adapter_projection_status == "exact"


def test_reasoning_only_terminal_response_is_complete_but_has_no_artifact() -> None:
    events = _complete_events("")
    events[1]["content_block"] = {"type": "thinking", "thinking": ""}
    events[2]["delta"] = {"type": "thinking_delta", "thinking": "reason"}
    events[4]["delta"]["stop_reason"] = "max_tokens"
    response = AnthropicAdapter.replay_protocol_input_bytes_v1(
        _sse(*events), content_type="text/event-stream",
    )

    assert response.text == ""
    assert response.finish_reason == "max_tokens"
    assert response.provider_state["transport_complete"] is True
    assert response.output_shape.reasoning_block_count == 1
    assert response.output_shape.text_block_count == 0


def test_ping_between_message_delta_and_message_stop_is_valid() -> None:
    events = _complete_events()
    events.insert(-1, {"type": "ping"})

    response = AnthropicAdapter.replay_protocol_input_bytes_v1(
        _sse(*events), content_type="text/event-stream",
    )

    assert response.text == "可验证的完整结果"
    assert response.provider_state["protocol_terminal_event"] == "message_stop"


def test_contiguous_multiple_content_blocks_preserve_index_order() -> None:
    events = _complete_events("第一段")
    events[4:4] = [
        {
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "text_delta", "text": "第二段"},
        },
        {"type": "content_block_stop", "index": 1},
    ]

    response = AnthropicAdapter.replay_protocol_input_bytes_v1(
        _sse(*events), content_type="text/event-stream",
    )

    assert response.text == "第一段第二段"


@pytest.mark.parametrize("bad_index", [1, 2, -1, True, None])
def test_first_content_block_index_must_be_integer_zero(bad_index) -> None:
    events = _complete_events()
    events[1]["index"] = bad_index

    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )

    assert caught.value.reason_code in {
        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_INVALID",
        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_NONCONTIGUOUS",
    }


def test_later_content_block_index_gap_fails_closed() -> None:
    events = _complete_events()
    events[4:4] = [
        {
            "type": "content_block_start", "index": 2,
            "content_block": {"type": "text", "text": ""},
        },
        {"type": "content_block_stop", "index": 2},
    ]

    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )

    assert caught.value.reason_code == (
        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_NONCONTIGUOUS"
    )


def test_explicit_provider_error_before_content_is_not_transport() -> None:
    with pytest.raises(AnthropicProviderTerminalError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse({
                "type": "error",
                "error": {"type": "overloaded_error", "message": "private"},
            }),
            content_type="text/event-stream",
        )
    assert caught.value.error_type == "overloaded_error"
    incident = classify_production_failure(
        str(caught.value), workflow="short-story", stage="planning",
        failure=caught.value.reliability_failure,
    )
    assert incident["incident_family"] == "provider.terminal_error_event"


def test_explicit_provider_error_after_partial_content_is_not_accepted() -> None:
    events = _complete_events()
    with pytest.raises(AnthropicProviderTerminalError):
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events[:3], {
                "type": "error",
                "error": {"type": "api_error", "message": "private"},
            }),
            content_type="text/event-stream",
        )


def test_eof_without_message_stop_is_typed_incomplete() -> None:
    with pytest.raises(AnthropicStreamIncompleteError):
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*_complete_events()[:-1]), content_type="text/event-stream",
        )


def test_duplicate_terminal_event_is_protocol_error() -> None:
    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*_complete_events(), {"type": "message_stop"}),
            content_type="text/event-stream",
        )
    assert caught.value.reason_code == "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP"


def test_delta_outside_open_block_is_protocol_error() -> None:
    events = _complete_events()
    del events[1]
    with pytest.raises(AnthropicStreamProtocolError):
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )


def test_block_after_message_delta_is_protocol_error() -> None:
    events = _complete_events()
    events.insert(-1, {
        "type": "content_block_start", "index": 1,
        "content_block": {"type": "text", "text": ""},
    })
    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )
    assert caught.value.reason_code == "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_DELTA"


@pytest.mark.parametrize(
    "block,delta",
    [
        ({"type": "thinking", "thinking": ""},
         {"type": "text_delta", "text": "leak"}),
        ({"type": "text", "text": ""},
         {"type": "input_json_delta", "partial_json": "{}"}),
        ({"type": "tool_use", "id": "call", "name": "done"},
         {"type": "unknown_delta"}),
    ],
)
def test_block_delta_type_mismatch_is_typed_protocol_error(block, delta) -> None:
    events = _complete_events()
    events[1]["content_block"] = block
    events[2]["delta"] = delta
    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )
    assert caught.value.reason_code == (
        "ANTHROPIC_SSE_CONTENT_DELTA_TYPE_MISMATCH"
    )


def test_unknown_block_type_is_typed_protocol_error() -> None:
    events = _complete_events()
    events[1]["content_block"] = {"type": "future_private_block"}
    with pytest.raises(AnthropicStreamProtocolError) as caught:
        AnthropicAdapter.replay_protocol_input_bytes_v1(
            _sse(*events), content_type="text/event-stream",
        )
    assert caught.value.reason_code == (
        "ANTHROPIC_SSE_CONTENT_BLOCK_TYPE_UNSUPPORTED"
    )


@pytest.mark.asyncio
async def test_transient_local_aggregation_failure_replays_without_dispatch() -> None:
    class FailOnceAdapter(AnthropicAdapter):
        aggregate_calls = 0

        @staticmethod
        def _aggregate_stream(events):
            FailOnceAdapter.aggregate_calls += 1
            if FailOnceAdapter.aggregate_calls == 1:
                raise RuntimeError("injected local adapter failure")
            return AnthropicAdapter._aggregate_stream(events)

    adapter = FailOnceAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=_sse(*_complete_events()), request=request,
            headers={"content-type": "text/event-stream; charset=utf-8"},
        )
    ))
    try:
        response = await adapter.complete(ModelRequest(
            model="offline", messages=[Message(role="user", content="offline")],
            max_output_tokens=32,
        ))
    finally:
        await adapter.client.aclose()

    assert response.text == "可验证的完整结果"
    assert FailOnceAdapter.aggregate_calls == 2
    assert adapter.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
async def test_transient_local_projection_failure_replays_without_dispatch() -> None:
    class FailOnceAdapter(AnthropicAdapter):
        projection_calls = 0

        @staticmethod
        def _model_response_from_body(body, *, provider_state_extra=None):
            FailOnceAdapter.projection_calls += 1
            if FailOnceAdapter.projection_calls == 1:
                raise RuntimeError("injected local projection failure")
            return AnthropicAdapter._model_response_from_body(
                body, provider_state_extra=provider_state_extra,
            )

    adapter = FailOnceAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": "offline",
                "content": [{"type": "text", "text": "exact replay"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 9},
            },
            request=request,
            headers={"content-type": "application/json"},
        )
    ))
    try:
        response = await adapter.complete(ModelRequest(
            model="offline", messages=[Message(role="user", content="offline")],
            max_output_tokens=32,
        ))
    finally:
        await adapter.client.aclose()

    assert response.text == "exact replay"
    assert FailOnceAdapter.projection_calls == 2
    assert adapter.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("iterator timed out after terminal bytes"),
        asyncio.CancelledError("iterator cancelled after terminal bytes"),
    ],
    ids=["timeout", "cancellation"],
)
async def test_terminal_bytes_recover_iterator_failure_by_exact_local_replay(
    failure: BaseException,
) -> None:
    raw = _sse(*_complete_events("终态后仍可本地重放"))
    observer = _CaptureObserver()
    adapter = AnthropicAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    await adapter.client.aclose()

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=_InjectedStream([raw], failure), request=request,
            headers={"content-type": "text/event-stream; charset=utf-8"},
        )

    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        response = await adapter.complete(ModelRequest(
            model="offline",
            messages=[Message(role="user", content="offline")],
            max_output_tokens=32,
        ))
    finally:
        await adapter.client.aclose()

    assert observer.captures == [{
        "data": raw,
        "status_code": 200,
        "content_type": "text/event-stream; charset=utf-8",
        "encoding": "utf-8",
        "transport_complete": True,
    }]
    assert observer.outcomes == ["response:200"]
    assert adapter._last_protocol_input_v1 == (
        raw, "text/event-stream; charset=utf-8", "utf-8",
    )
    replayed = AnthropicAdapter.replay_protocol_input_bytes_v1(
        adapter._last_protocol_input_v1[0],
        content_type=adapter._last_protocol_input_v1[1],
        encoding=adapter._last_protocol_input_v1[2],
    )
    assert response.model_dump(exclude={"output_shape"}) == replayed.model_dump(
        exclude={"output_shape"},
    )
    assert replayed.text == "终态后仍可本地重放"
    assert adapter.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
async def test_unterminated_bytes_before_timeout_remain_incomplete_and_unreplayable() -> None:
    raw = _sse(*_complete_events()[:-1])
    observer = _CaptureObserver()
    adapter = AnthropicAdapter(
        "https://offline.invalid/v1", "offline-memory-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    await adapter.client.aclose()

    async def respond(request: httpx.Request) -> httpx.Response:
        failure = httpx.ReadTimeout(
            "iterator timed out before terminal bytes", request=request,
        )
        return httpx.Response(
            200, stream=_InjectedStream([raw], failure), request=request,
            headers={"content-type": "text/event-stream"},
        )

    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(httpx.ReadTimeout):
            await adapter.complete(ModelRequest(
                model="offline",
                messages=[Message(role="user", content="offline")],
                max_output_tokens=32,
            ))
    finally:
        await adapter.client.aclose()

    assert observer.captures[0]["data"] == raw
    assert observer.captures[0]["transport_complete"] is False
    assert observer.outcomes == ["failure:ReadTimeout"]
    assert adapter._last_protocol_input_v1 is None
