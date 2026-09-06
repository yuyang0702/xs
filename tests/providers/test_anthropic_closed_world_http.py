"""Closed-world fault injection at the production HTTP/network seam only.

The fixtures are synthetic protocol bytes. No parser, owner, adapter, request
builder, or capture method is mocked; MockTransport is the sole replacement.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import uuid

import httpx
import pytest

from novel_flywheel.anthropic_stream import (
    AnthropicStream, AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError, AnthropicStreamProtocolError, CaptureState, Event, State,
)
from novel_flywheel.domain.models import Message, ModelRequest, ModelResponse
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1


def wire(events):
    return b"".join(
        ("event: " + item["type"] + "\ndata: " +
         json.dumps(item, ensure_ascii=False) + "\n\n").encode()
        for item in events
    )


START = {"type": "message_start", "message": {
    "id": "synthetic-closed-world", "usage": {"input_tokens": 7, "output_tokens": 1}}}
BLOCK = {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}}
DELTA = {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "synthetic accepted response"}}
BLOCK_STOP = {"type": "content_block_stop", "index": 0}
MESSAGE_DELTA = {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {"input_tokens": 11, "output_tokens": 9}}
STOP = {"type": "message_stop"}
PING = {"type": "ping", "usage": {"input_tokens": 99999},
        "delta": {"stop_reason": "max_tokens"}}
ERROR = {"type": "error", "error": {"type": "overloaded_error", "message": "synthetic"}}
COMPLETE = [START, BLOCK, DELTA, BLOCK_STOP, MESSAGE_DELTA, STOP]

# Independent fixture-to-state oracle; the registry under test does not create
# its own expected results. Both entry to and progress within content are used.
PREFIXES = [
    pytest.param([], State.BEFORE_MESSAGE, id="before-message"),
    pytest.param([START], State.MESSAGE_ACTIVE, id="message-active"),
    pytest.param([START, BLOCK], State.CONTENT_ACTIVE, id="content-open"),
    pytest.param([START, BLOCK, DELTA], State.CONTENT_ACTIVE, id="content-progress"),
    pytest.param(COMPLETE[:4], State.CONTENT_COMPLETE, id="content-complete"),
    pytest.param(COMPLETE[:5], State.MESSAGE_DELTA, id="message-delta"),
]
FAULTS = ["eof", "timeout", "cancel", "transport", "iterator"]
TAIL_EVENT = {"eof": Event.EOF, "timeout": Event.TIMEOUT,
              "cancel": Event.CANCELLATION, "transport": Event.TRANSPORT_EXCEPTION,
              "iterator": Event.TRANSPORT_EXCEPTION}


def fault(kind):
    return {"eof": lambda: None,
            "timeout": lambda: httpx.ReadTimeout("synthetic timeout"),
            "cancel": lambda: asyncio.CancelledError("synthetic cancellation"),
            "transport": lambda: httpx.RemoteProtocolError("synthetic transport"),
            "iterator": lambda: RuntimeError("synthetic iterator failure")}[kind]()


class FaultWire(httpx.AsyncByteStream):
    def __init__(self, raw, iterator_failure=None, close_failure=None):
        self.raw = raw
        self.iterator_failure = iterator_failure
        self.close_failure = close_failure
        self.close_count = 0

    async def __aiter__(self):
        # Deliberately split JSON tokens, multibyte text and frame delimiters.
        for offset in range(0, len(self.raw), 11):
            yield self.raw[offset:offset + 11]
        if self.iterator_failure is not None:
            raise self.iterator_failure

    async def aclose(self):
        self.close_count += 1
        if self.close_failure is not None:
            raise self.close_failure


class CaptureObserver:
    capture_root = None

    def __init__(self, capture_failure=None, capture_ack=True):
        self.capture_failure = capture_failure
        self.capture_ack = capture_ack
        self.capture_path = None
        self.captures = []
        self.posts = self.network = 0

    def before_http_post(self):
        self.posts += 1

    def before_network_request(self):
        self.network += 1

    def capture_provider_protocol_input(self, **kwargs):
        self.captures.append(kwargs)
        if self.capture_failure is not None:
            raise self.capture_failure
        if self.capture_ack is not True:
            # Metadata-only observers do not acknowledge durable raw bytes.
            return self.capture_ack
        self.capture_path = self.capture_root / ("capture-" + uuid.uuid4().hex + ".raw")
        with self.capture_path.open("xb") as output:
            output.write(kwargs["data"])
            output.flush()
            os.fsync(output.fileno())
        assert hashlib.sha256(self.capture_path.read_bytes()).digest() == (
            hashlib.sha256(kwargs["data"]).digest())
        return True


@pytest.fixture(autouse=True)
def isolated_durable_capture_directory(tmp_path, monkeypatch):
    # The offline runner binds pytest basetemp outside the repository. Each
    # test retains its raw capture through completion and gets a unique path.
    monkeypatch.setattr(CaptureObserver, "capture_root", tmp_path)


@dataclass
class Invocation:
    response: ModelResponse | None
    failure: BaseException | None
    adapter: AnthropicAdapter
    observer: CaptureObserver
    stream: FaultWire

    @property
    def owner(self):
        owner = self.adapter._last_stream_outcome_v1
        from novel_flywheel.anthropic_durable_stream import DurableAnthropicStreamV1
        assert isinstance(owner, DurableAnthropicStreamV1)
        return owner


async def invoke(raw, *, iterator_failure=None, close_failure=None, capture_failure=None,
                 capture_ack=True):
    observer = CaptureObserver(capture_failure, capture_ack)
    stream = FaultWire(raw, iterator_failure, close_failure)
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, request=request, stream=stream,
                              headers={"content-type": "text/event-stream"})

    adapter = AnthropicAdapter("https://offline.invalid/v1", "synthetic-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer, injected_http_transport=httpx.MockTransport(respond))
    response = failure = None
    try:
        response = await adapter.complete(ModelRequest(model="synthetic",
            messages=[Message(role="user", content="synthetic authority")],
            max_output_tokens=64))
    except (Exception, asyncio.CancelledError) as exc:
        failure = exc
    finally:
        await adapter.client.aclose()
    assert len(requests) == observer.posts == observer.network == 1
    attempts = adapter.transport_attempt_snapshot()
    assert attempts["model_logical_calls"] == attempts["http_post_attempts"] == 1
    assert attempts["network_request_attempts"] == 1
    assert attempts["sdk_retries_disabled"] is True
    assert attempts["transport_request_retries_disabled"] is True
    assert attempts["application_second_dispatch_allowed"] is False
    assert len(observer.captures) == 1
    assert observer.captures[0]["data"] == raw
    if capture_ack is True and capture_failure is None:
        assert observer.capture_path.read_bytes() == raw
    else:
        assert observer.capture_path is None
    assert stream.close_count == 1
    return Invocation(response, failure, adapter, observer, stream)


def assert_replay_semantics(result, raw):
    assert result.failure is None
    assert isinstance(result.response, ModelResponse)
    replay = AnthropicAdapter.replay_protocol_input_bytes_v1(raw, content_type="text/event-stream")
    # Output-shape annotation is added by replay/gateway, outside HTTP. Live
    # capture/tail diagnostics are intentionally distinct from byte-only replay.
    assert result.response.model_dump(exclude={"provider_state", "output_shape"}) == (
        replay.model_dump(exclude={"provider_state", "output_shape"}))
    for field in ("content", "transport_complete", "protocol_terminal_event",
                  "raw_finish_reason", "POST_TERMINAL_PING_COUNT",
                  "POST_TERMINAL_PING_IGNORED_COUNT"):
        assert result.response.provider_state[field] == replay.provider_state[field]


@pytest.mark.parametrize("events,state", PREFIXES)
@pytest.mark.parametrize("ending", FAULTS)
@pytest.mark.parametrize("seam", ["iterator", "aclose"])
async def test_every_preterminal_prefix_fails_without_retry(events, state, ending, seam):
    injected = fault(ending)
    kwargs = {"iterator_failure" if seam == "iterator" else "close_failure": injected}
    result = await invoke(wire(events), **kwargs)
    assert result.response is None
    if injected is None:
        assert isinstance(result.failure, AnthropicStreamIncompleteError)
    else:
        assert result.failure is injected
    owner = result.owner
    assert owner.state == State.TRANSPORT_FAILURE
    assert owner.primary is result.failure
    assert owner.semantic_terminal_complete is False
    assert owner.terminal_capture_complete is False
    assert owner.tail_closed_cleanly is (ending == "eof")
    transition = next(row for row in owner.trace if row["event"] == TAIL_EVENT[ending].value)
    assert transition["from_state"] == state.value
    assert transition["next_state"] == State.TRANSPORT_FAILURE.value
    if ending != "eof":
        assert result.observer.captures[0]["transport_complete"] is False


@pytest.mark.parametrize("ending", FAULTS)
@pytest.mark.parametrize("seam", ["iterator", "aclose"])
@pytest.mark.parametrize("pings", [0, 3])
async def test_success_tail_fault_retains_complete_capture_and_exact_replay(ending, seam, pings):
    raw = wire(COMPLETE + [PING] * pings)
    kwargs = {"iterator_failure" if seam == "iterator" else "close_failure": fault(ending)}
    result = await invoke(raw, **kwargs)
    assert_replay_semantics(result, raw)
    assert (result.response.input_tokens, result.response.output_tokens) == (11, 9)
    assert result.observer.captures[0]["transport_complete"] is True
    assert result.owner.semantic_terminal_complete is True
    assert result.owner.terminal_capture_complete is True
    assert result.owner.tail_closed_cleanly is (ending == "eof")
    assert result.owner.primary is None
    assert result.owner.post_terminal_ping_count == pings
    assert result.owner.tail_counts[TAIL_EVENT[ending].value] == 1


@pytest.mark.parametrize("events,state", PREFIXES + [pytest.param(COMPLETE, State.SUCCESS, id="success")])
@pytest.mark.parametrize("ending", FAULTS)
async def test_error_at_each_meaningful_state_remains_primary(events, state, ending):
    raw = wire(events + [ERROR, PING])
    result = await invoke(raw, iterator_failure=fault(ending))
    assert result.response is None
    assert isinstance(result.failure, AnthropicProviderTerminalError)
    assert result.failure.error_type == "overloaded_error"
    assert result.owner.primary is result.failure
    assert result.owner.semantic_terminal_complete is False
    assert result.owner.terminal_capture_complete is True
    assert result.owner.tail_closed_cleanly is (ending == "eof")
    assert result.owner.snapshot()["primary_cause"] == "PROVIDER_ERROR"
    transition = next(row for row in result.owner.trace if row["event"] == "error")
    assert transition["from_state"] == state.value
    evidence = result.failure.provider_stream_error
    assert evidence.secondary_post_error_ping_count == 1
    assert evidence.secondary_post_error_transport_present is (ending != "eof")
    assert evidence.secondary_post_error_timeout_present is (ending == "timeout")


@pytest.mark.parametrize("ending", FAULTS[1:])
async def test_provider_error_survives_iterator_and_aclose_faults(ending):
    result = await invoke(wire([ERROR, PING]), iterator_failure=fault(ending),
                          close_failure=httpx.ReadTimeout("synthetic close timeout"))
    assert isinstance(result.failure, AnthropicProviderTerminalError)
    assert result.failure is result.owner.primary
    assert result.failure.error_type == "overloaded_error"
    assert result.owner.terminal_capture_complete is True
    assert result.owner.tail_closed_cleanly is False
    evidence = result.failure.provider_stream_error
    assert evidence.secondary_post_error_timeout_present is True
    assert evidence.secondary_post_error_transport_present is True


@pytest.mark.parametrize("continuation", [START, BLOCK, DELTA, BLOCK_STOP, MESSAGE_DELTA, STOP,
                                         {"type": "future_semantic_extension"}])
@pytest.mark.parametrize("ending", ["eof", "timeout"])
async def test_semantic_continuation_cannot_become_complete_success(continuation, ending):
    raw = wire(COMPLETE + [PING, continuation])
    result = await invoke(raw, iterator_failure=fault(ending))
    assert result.response is None
    assert isinstance(result.failure, AnthropicStreamProtocolError)
    assert result.failure.reason_code == "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP"
    assert result.owner.state == State.PROTOCOL_INVALID
    assert result.owner.primary is result.failure
    assert result.owner.semantic_terminal_complete is False
    assert result.owner.terminal_capture_complete is False
    with pytest.raises(AnthropicStreamProtocolError):
        AnthropicAdapter.replay_protocol_input_bytes_v1(raw, content_type="text/event-stream")


@pytest.mark.parametrize("ending", FAULTS)
async def test_success_capture_callback_failure_cannot_claim_durable_capture(ending):
    capture_failure = RuntimeError("synthetic capture persistence failure")
    result = await invoke(wire(COMPLETE + [PING] * 3), iterator_failure=fault(ending),
                          capture_failure=capture_failure)
    assert result.response is None
    # Persistable controls normalize private exception instances into a safe
    # public category shared by live execution and checkpoint restoration.
    assert type(result.failure) is RuntimeError
    assert result.owner.primary is result.failure
    assert 'synthetic capture persistence failure' not in str(result.failure)
    assert result.owner.semantic_terminal_complete is True
    assert result.owner.terminal_capture_complete is False
    assert result.owner.snapshot()["primary_cause"] == "CAPTURE_FAILURE"
    assert result.owner.tail_closed_cleanly is (ending == "eof")
    assert result.observer.captures[0]["transport_complete"] is True


@pytest.mark.parametrize("ending", FAULTS)
async def test_capture_callback_failure_is_secondary_to_provider_error(ending):
    result = await invoke(wire([ERROR, PING]), iterator_failure=fault(ending),
                          capture_failure=RuntimeError("synthetic capture failure"))
    assert isinstance(result.failure, AnthropicProviderTerminalError)
    assert result.failure is result.owner.primary
    assert result.failure.error_type == "overloaded_error"
    assert result.owner.semantic_terminal_complete is False
    assert result.owner.terminal_capture_complete is False
    assert result.owner.snapshot()["primary_cause"] == "PROVIDER_ERROR"
    assert result.failure.provider_stream_error.secondary_post_error_observer_failure_count == 1


def topology_events(topology, stop):
    blocks = {
        "text": [{"type": "text", "text": "synthetic multilingual 甲"}],
        "multitext": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
        "thinking": [{"type": "thinking", "thinking": "synthetic", "signature": "opaque"}],
        "redacted": [{"type": "redacted_thinking", "data": "synthetic opaque"}],
        "tool": [{"type": "tool_use", "id": "synthetic-call", "name": "receipt", "input": {}}],
        "schema": [{"type": "tool_use", "id": "synthetic-schema", "name": "receipt",
                    "input": {"unseen_archive": {"nodes": [True, 7]}}}],
        "mixed": [{"type": "thinking", "thinking": "synthetic", "signature": "opaque"},
                  {"type": "text", "text": "synthetic final"}],
    }[topology]
    events = [START, PING]
    for index, block in enumerate(blocks):
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        if topology == "tool":
            for part in ['{"unseen_bundle":', '{"owners":[1,2],"accepted":true}}']:
                events.append({"type": "content_block_delta", "index": index,
                               "delta": {"type": "input_json_delta", "partial_json": part}})
        events.extend([PING, {"type": "content_block_stop", "index": index}])
    events.extend([
        {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 5}},
        {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"input_tokens": 11}},
        STOP, PING, PING, PING,
    ])
    return events


@pytest.mark.parametrize("topology", ["text", "multitext", "thinking", "redacted", "tool", "schema", "mixed"])
@pytest.mark.parametrize("stop", ["end_turn", "max_tokens"])
@pytest.mark.parametrize("ending", ["eof", "timeout", "cancel", "transport"])
async def test_valid_topologies_preserve_http_replay_and_cumulative_usage(topology, stop, ending):
    raw = wire(topology_events(topology, stop))
    result = await invoke(raw, iterator_failure=fault(ending))
    assert_replay_semantics(result, raw)
    assert (result.response.input_tokens, result.response.output_tokens) == (11, 5)
    assert result.response.finish_reason == stop
    assert result.response.provider_state["POST_TERMINAL_PING_IGNORED_COUNT"] == 3
    assert result.owner.semantic_terminal_complete is True
    assert result.owner.terminal_capture_complete is True
    assert result.owner.tail_closed_cleanly is (ending == "eof")
    assert result.observer.captures[0]["transport_complete"] is True


@pytest.mark.parametrize("ending", FAULTS[1:])
async def test_success_survives_both_iterator_and_aclose_faults(ending):
    raw = wire(COMPLETE + [PING] * 3)
    result = await invoke(raw, iterator_failure=fault(ending),
                          close_failure=httpx.ReadTimeout("synthetic close timeout"))
    assert_replay_semantics(result, raw)
    assert result.owner.semantic_terminal_complete is True
    assert result.owner.terminal_capture_complete is True
    assert result.owner.tail_closed_cleanly is False
    assert result.observer.captures[0]["transport_complete"] is True
    assert sum(result.owner.tail_counts.get(event.value, 0) for event in
               [Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION]) == 2


@pytest.mark.parametrize("capture_ack", [None, False], ids=["none", "false"])
@pytest.mark.parametrize("ending", FAULTS)
@pytest.mark.parametrize("terminal", ["success", "provider-error"])
async def test_metadata_only_capture_cannot_claim_durable_completion(capture_ack, ending, terminal):
    raw = wire((COMPLETE if terminal == "success" else [ERROR]) + [PING] * 3)
    result = await invoke(raw, iterator_failure=fault(ending), capture_ack=capture_ack)
    if terminal == "success":
        assert_replay_semantics(result, raw)
        assert result.owner.semantic_terminal_complete is True
        assert result.observer.captures[0]["transport_complete"] is True
    else:
        assert result.response is None
        assert isinstance(result.failure, AnthropicProviderTerminalError)
        assert result.owner.primary is result.failure
        assert result.owner.semantic_terminal_complete is False
    assert result.owner.capture_state == CaptureState.NOT_ATTEMPTED
    assert result.owner.terminal_capture_complete is False
    assert result.owner.tail_closed_cleanly is (ending == "eof")
    assert all(row["event"] != Event.CAPTURE_COMMITTED.value for row in result.owner.trace)
    assert result.observer.capture_path is None
