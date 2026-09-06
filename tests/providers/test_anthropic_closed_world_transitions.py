"""Independent closed-world contract oracles executing the production owner.

Every state is reached through real safe events. The literal oracle below is
intentionally independent of TRANSITIONS and never assigns stream.state.
All fixtures are synthetic; this module performs no I/O or network dispatch.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import httpx
import pytest

from novel_flywheel.anthropic_stream import (
    Action, AnthropicProviderTerminalError, AnthropicStream,
    AnthropicStreamIncompleteError, AnthropicStreamProtocolError,
    Event, InvalidFrame, State, evaluate_bytes,
)
from novel_flywheel.provider_response_capture import ProviderResponseCaptureError


STATES = {
    "B": State.BEFORE_MESSAGE, "M": State.MESSAGE_ACTIVE,
    "C": State.CONTENT_ACTIVE, "D": State.CONTENT_COMPLETE,
    "U": State.MESSAGE_DELTA, "S": State.SUCCESS,
    "ST": State.SUCCESS_TAIL, "P": State.PROVIDER_ERROR,
    "PT": State.ERROR_TAIL, "T": State.TRANSPORT_FAILURE,
    "I": State.PROTOCOL_INVALID,
}
EVENTS = (
    Event.MESSAGE_START, Event.CONTENT_START, Event.CONTENT_DELTA,
    Event.CONTENT_STOP, Event.MESSAGE_DELTA, Event.MESSAGE_STOP,
    Event.PING, Event.ERROR, Event.UNKNOWN, Event.INVALID,
    Event.EOF, Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION,
    Event.CAPTURE_COMMITTED, Event.CAPTURE_FAILED,
)
# Each token is action / destination. Rows form a reviewable normative contract:
# a=advance, i=invalid, k=keepalive, p=Provider terminal, u=unknown policy,
# t=transport terminal, s=success, c=capture proof, f=capture failure.
ORACLE_ROWS = {
    "B":  "a/M i/I i/I i/I i/I i/I k/B p/P u/I i/I t/T t/T t/T t/T c/B f/B",
    "M":  "i/I a/C i/I i/I a/U i/I k/M p/P u/I i/I t/T t/T t/T t/T c/M f/M",
    "C":  "i/I i/I a/C a/D i/I i/I k/C p/P u/I i/I t/T t/T t/T t/T c/C f/C",
    "D":  "i/I a/C i/I i/I a/U i/I k/D p/P u/I i/I t/T t/T t/T t/T c/D f/D",
    "U":  "i/I i/I i/I i/I a/U s/S k/U p/P u/I i/I t/T t/T t/T t/T c/U f/U",
    "S":  "i/I i/I i/I i/I i/I i/I k/ST p/P u/I i/I s/ST s/ST s/ST s/ST c/S f/S",
    "ST": "i/I i/I i/I i/I i/I i/I k/ST p/P u/I i/I s/ST s/ST s/ST s/ST c/ST f/ST",
    "P":  "p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT c/P p/PT",
    "PT": "p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT p/PT c/PT p/PT",
    "T":  "t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T t/T",
    "I":  "i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I i/I",
}
ACTION_VALUES = {
    "a": "ACCEPT_ADVANCE", "i": "FAIL_CLOSED_PROTOCOL_INVALID",
    "k": "IGNORE_TRANSPORT_KEEPALIVE", "p": "TERMINAL_PROVIDER_ERROR",
    "u": "VERSIONED_UNKNOWN_EVENT_POLICY", "t": "TERMINAL_TRANSPORT_FAILURE",
    "s": "TERMINAL_SUCCESS", "c": "ACKNOWLEDGE_CAPTURE_PROOF",
    "f": "TERMINAL_CAPTURE_FAILURE",
}
CELLS = [
    (source, event, token)
    for source, row in ORACLE_ROWS.items()
    for event, token in zip(EVENTS, row.split(), strict=True)
]
SEMANTIC_TERMINALS = {"S", "ST"}
PROVIDER_TERMINALS = {"P", "PT"}
TRANSPORT_EVENTS = {
    Event.EOF, Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION,
}


def start():
    return {"type": "message_start", "message": {
        "id": "safe-matrix", "usage": {"input_tokens": 20, "output_tokens": 1},
    }}


def content(index=0, block=None):
    return {"type": "content_block_start", "index": index,
            "content_block": deepcopy(block if block is not None else
                                      {"type": "text", "text": "seed"})}


def delta(index=0):
    return {"type": "content_block_delta", "index": index,
            "delta": {"type": "text_delta", "text": " plus"}}


def usage_delta(output=4, reason="end_turn"):
    return {"type": "message_delta", "delta": {"stop_reason": reason},
            "usage": {"output_tokens": output}}


def error():
    return {"type": "error", "error": {"type": "overloaded_error"}}


def prefix(source):
    complete = [start(), content(), {"type": "content_block_stop", "index": 0},
                usage_delta(), {"type": "message_stop"}]
    prefixes = {
        "B": [], "M": complete[:1], "C": complete[:2], "D": complete[:3],
        "U": complete[:4], "S": complete,
        "ST": complete + [{"type": "ping"}],
        "P": [error()], "PT": [error(), {"type": "ping"}],
        "T": [Event.TIMEOUT], "I": [{"type": "safe_unrecognized_event_v2"}],
    }
    stream = AnthropicStream()
    for item in deepcopy(prefixes[source]):
        stream.step(item)
    assert stream.state == STATES[source], "prefix must reach its state through production transitions"
    return stream


def input_for(source, event):
    index = 1 if source in {"D", "U", "S", "ST"} else 0
    semantic = {
        Event.MESSAGE_START: start(), Event.CONTENT_START: content(index),
        Event.CONTENT_DELTA: delta(),
        Event.CONTENT_STOP: {"type": "content_block_stop", "index": 0},
        Event.MESSAGE_DELTA: {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                              "usage": {"input_tokens": 30, "cache_read_input_tokens": 2,
                                        "output_tokens": 9}},
        Event.MESSAGE_STOP: {"type": "message_stop"},
        Event.PING: {"type": "ping", "usage": {"input_tokens": 999999},
                     "delta": {"stop_reason": "max_tokens"}},
        Event.ERROR: error(), Event.UNKNOWN: {"type": "safe_unrecognized_event_v2"},
    }
    failures = {
        Event.INVALID: AnthropicStreamProtocolError("SAFE_FRAMING_MARKER"),
        Event.TIMEOUT: httpx.ReadTimeout("safe timeout"),
        Event.CANCELLATION: asyncio.CancelledError("safe cancellation"),
        Event.TRANSPORT_EXCEPTION: httpx.ReadError("safe transport"),
        Event.CAPTURE_FAILED: ProviderResponseCaptureError("SAFE_CAPTURE_MARKER"),
    }
    failure = failures.get(event)
    payload = InvalidFrame(failure) if event == Event.INVALID else semantic.get(event, event)
    return payload, failure


def message_data(stream):
    return deepcopy({"id": stream.message_id, "usage": stream.usage,
                     "stop_reason": stream.stop_reason, "blocks": stream.blocks,
                     "tool_json": stream.tool_json, "active_index": stream.active_index})


def expected_data(before, event, action, payload):
    expected = deepcopy(before)
    if action != "a":
        return expected
    if event == Event.MESSAGE_START:
        expected["id"] = "safe-matrix"
        expected["usage"] = {"input_tokens": 20, "output_tokens": 1}
    elif event == Event.CONTENT_START:
        expected["blocks"][payload["index"]] = {"type": "text", "text": "seed"}
        expected["active_index"] = payload["index"]
    elif event == Event.CONTENT_DELTA:
        expected["blocks"][0]["text"] += " plus"
    elif event == Event.CONTENT_STOP:
        expected["active_index"] = None
    elif event == Event.MESSAGE_DELTA:
        expected["usage"].update(input_tokens=30, cache_read_input_tokens=2, output_tokens=9)
        expected["stop_reason"] = "end_turn"
    return expected


def test_registered_domain_is_exactly_the_independently_specified_domain():
    assert set(STATES.values()) == set(State)
    assert set(EVENTS) == set(Event)
    assert len(CELLS) == 176
    assert len({(source, event) for source, event, _ in CELLS}) == 176


@pytest.mark.parametrize("source,event,expected", CELLS,
                         ids=[f"{s}-{e.value}" for s, e, _ in CELLS])
def test_every_registered_state_event_transition(source, event, expected):
    stream = prefix(source)
    before = stream.snapshot()
    data_before = message_data(stream)
    primary_before = stream.primary
    payload, failure = input_for(source, event)
    action, destination = expected.split("/")
    rule = stream.step(payload, failure=failure)
    snapshot = stream.snapshot()

    assert rule.action.value == ACTION_VALUES[action]
    assert rule.next_state == stream.state == STATES[destination]
    expected_primary = (
        "CAPTURE_FAILURE" if action == "f" else
        "PROVIDER_ERROR" if destination in PROVIDER_TERMINALS else
        "PROTOCOL_INVALID" if destination == "I" else
        "TRANSPORT_FAILURE" if destination == "T" else
        "SUCCESS" if destination in SEMANTIC_TERMINALS else "NONE"
    )
    assert snapshot["primary_cause"] == expected_primary
    assert snapshot["semantic_terminal_complete"] is (destination in SEMANTIC_TERMINALS)
    assert snapshot["terminal_capture_complete"] is (
        action == "c" and source in SEMANTIC_TERMINALS | PROVIDER_TERMINALS)
    assert message_data(stream) == expected_data(data_before, event, action, payload)
    expected_counts = dict(before["tail_counts"])
    if source in SEMANTIC_TERMINALS | PROVIDER_TERMINALS:
        expected_counts[event.value] = expected_counts.get(event.value, 0) + 1
    assert snapshot["tail_counts"] == expected_counts
    assert snapshot["post_terminal_ping_count"] == before["post_terminal_ping_count"] + (
        source in SEMANTIC_TERMINALS and event == Event.PING)
    assert snapshot["transport_tail_closed_cleanly"] is (
        event == Event.EOF if event in TRANSPORT_EVENTS else before["transport_tail_closed_cleanly"])
    assert len(stream.trace) >= 1
    assert stream.trace[-1]["from_state"] == STATES[source].value
    assert stream.trace[-1]["event"] == event.value

    if source in {"T", "I"} | PROVIDER_TERMINALS:
        assert stream.primary is primary_before, "later input must not replace the existing terminal cause"
    elif destination in PROVIDER_TERMINALS:
        assert isinstance(stream.primary, AnthropicProviderTerminalError)
    elif event in {Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION} and destination == "T":
        assert stream.primary is failure
    elif event == Event.INVALID:
        assert stream.primary is failure
    elif action == "f":
        assert stream.primary is failure
    elif destination == "I":
        assert isinstance(stream.primary, AnthropicStreamProtocolError)
    elif event == Event.EOF and destination == "T":
        assert isinstance(stream.primary, AnthropicStreamIncompleteError)
    if destination in SEMANTIC_TERMINALS and action != "f":
        body = stream.body()
        assert body["_protocol_complete"] is True
        assert body["_terminal_event"] == "message_stop"
    elif stream.primary is not None:
        with pytest.raises(BaseException) as caught:
            stream.body()
        assert caught.value is stream.primary


@pytest.mark.parametrize("source", ["B", "M", "C", "D", "U", "S", "ST", "P", "PT"])
@pytest.mark.parametrize("fault", [Event.EOF, Event.TIMEOUT, Event.CANCELLATION,
                                   Event.TRANSPORT_EXCEPTION, Event.PING, Event.ERROR, Event.INVALID])
def test_fault_campaign_with_capture_acknowledged_first(source, fault):
    stream = prefix(source)
    stream.step(Event.CAPTURE_COMMITTED)
    before = message_data(stream)
    primary = stream.primary
    payload, failure = input_for(source, fault)
    stream.step(payload, failure=failure)
    snap = stream.snapshot()
    assert message_data(stream) == before
    if source in PROVIDER_TERMINALS:
        assert snap["primary_cause"] == "PROVIDER_ERROR"
        assert stream.primary is primary
        assert snap["terminal_capture_complete"] is True
        assert snap["semantic_terminal_complete"] is False
    elif source in SEMANTIC_TERMINALS and fault in TRANSPORT_EVENTS | {Event.PING}:
        assert snap["primary_cause"] == "SUCCESS"
        assert snap["semantic_terminal_complete"] is True
        assert snap["terminal_capture_complete"] is True
    elif source not in SEMANTIC_TERMINALS:
        assert snap["semantic_terminal_complete"] is False
        assert snap["terminal_capture_complete"] is False
        if fault in TRANSPORT_EVENTS:
            assert snap["primary_cause"] == "TRANSPORT_FAILURE"


@pytest.mark.parametrize("source", ["S", "ST", "P", "PT"])
@pytest.mark.parametrize("tail", [Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION])
def test_success_or_provider_primary_survives_ping_and_interruption(source, tail):
    stream = prefix(source)
    stream.step(Event.CAPTURE_COMMITTED)
    expected_cause = "SUCCESS" if source in SEMANTIC_TERMINALS else "PROVIDER_ERROR"
    primary = stream.primary
    data = message_data(stream)
    for _ in range(3):
        stream.step({"type": "ping", "usage": {"output_tokens": 999999}})
    _, failure = input_for(source, tail)
    stream.step(tail, failure=failure)
    snap = stream.snapshot()
    assert snap["primary_cause"] == expected_cause
    assert stream.primary is primary
    assert snap["terminal_capture_complete"] is True
    assert snap["transport_tail_closed_cleanly"] is False
    assert message_data(stream) == data
    if source in PROVIDER_TERMINALS:
        evidence = stream.primary.provider_stream_error
        assert evidence.secondary_post_error_ping_count >= 3
        assert evidence.secondary_post_error_transport_present is True


@pytest.mark.parametrize("source", ["B", "M", "C", "D", "U", "S", "ST", "P", "PT"])
def test_capture_failure_is_separate_from_semantic_completion(source):
    stream = prefix(source)
    before = stream.snapshot()
    failure = ProviderResponseCaptureError("SAFE_CAPTURE_WRITE_FAILED")
    stream.step(Event.CAPTURE_FAILED, failure=failure)
    snap = stream.snapshot()
    assert snap["semantic_terminal_complete"] == before["semantic_terminal_complete"]
    assert snap["terminal_capture_complete"] is False
    if source in PROVIDER_TERMINALS:
        assert snap["primary_cause"] == "PROVIDER_ERROR"
        assert stream.primary.provider_stream_error.secondary_post_error_observer_failure_count == 1
    else:
        assert stream.state == STATES[source]
        assert snap["primary_cause"] == "CAPTURE_FAILURE"
        with pytest.raises(ProviderResponseCaptureError) as caught:
            stream.body()
        assert caught.value is failure


@pytest.mark.parametrize("payload", [None, [], [1], "safe", 1, True])
def test_nonobject_events_are_typed_protocol_failures(payload):
    stream = prefix("B")
    rule = stream.step(payload)
    assert rule.action == Action.INVALID
    assert stream.state == State.PROTOCOL_INVALID
    assert isinstance(stream.primary, AnthropicStreamProtocolError)
    assert not isinstance(stream.primary, AttributeError)


@pytest.mark.parametrize("field,bad", [
    ("message", None), ("message", []), ("message", [1]), ("message", "safe"),
    ("message", 1), ("message", True),
])
def test_message_start_shape_failures_do_not_mutate(field, bad):
    stream = prefix("B")
    before = message_data(stream)
    stream.step({"type": "message_start", field: bad})
    assert stream.state == State.PROTOCOL_INVALID
    assert isinstance(stream.primary, AnthropicStreamProtocolError)
    assert message_data(stream) == before


@pytest.mark.parametrize("source,payload", [
    ("M", {"type": "content_block_start", "index": True, "content_block": {"type": "text"}}),
    ("M", {"type": "content_block_start", "index": -1, "content_block": {"type": "text"}}),
    ("M", {"type": "content_block_start", "index": 3, "content_block": {"type": "text"}}),
    ("M", {"type": "content_block_start", "index": 0, "content_block": [1]}),
    ("M", {"type": "content_block_start", "index": 0, "content_block": {"type": "safe_future_block"}}),
    ("C", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "x"}}),
    ("C", {"type": "content_block_delta", "index": 0, "delta": [1]}),
    ("C", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
    ("C", {"type": "content_block_stop", "index": 2}),
    ("D", {"type": "message_delta", "delta": [1]}),
    ("D", {"type": "message_delta", "delta": {"stop_reason": 12}}),
])
def test_payload_guards_are_atomic_typed_and_fail_closed(source, payload):
    stream = prefix(source)
    before = message_data(stream)
    stream.step(deepcopy(payload))
    assert stream.state == State.PROTOCOL_INVALID
    assert isinstance(stream.primary, AnthropicStreamProtocolError)
    assert message_data(stream) == before


@pytest.mark.parametrize("counter", ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"])
@pytest.mark.parametrize("bad", [-1, True, "9", 1.5, [9], {"safe": 9}])
def test_invalid_cumulative_counter_preserves_the_last_snapshot(counter, bad):
    stream = prefix("D")
    before = message_data(stream)
    stream.step({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {counter: bad}})
    assert stream.state == State.PROTOCOL_INVALID
    assert isinstance(stream.primary, ProviderResponseCaptureError)
    assert message_data(stream) == before


@pytest.mark.parametrize("updates,expected", [
    ([{"output_tokens": 9}], {"input_tokens": 20, "output_tokens": 9}),
    ([{"input_tokens": 30, "output_tokens": 9}, {"input_tokens": 10, "output_tokens": 4}],
     {"input_tokens": 10, "output_tokens": 4}),
    ([{"cache_read_input_tokens": 3, "output_tokens": 9}, {}],
     {"input_tokens": 20, "cache_read_input_tokens": 3, "output_tokens": 9}),
    ([{"input_tokens": None, "cache_read_input_tokens": None, "output_tokens": 0}],
     {"input_tokens": 20, "output_tokens": 0}),
])
def test_cumulative_replacement_and_omission_are_protocol_owned(updates, expected):
    stream = prefix("D")
    for update in updates:
        stream.step({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                     "usage": {**update, "billing_usage": {"input_tokens": 999999}}})
    stream.step({"type": "message_stop"})
    assert stream.body()["usage"] == expected


@pytest.mark.parametrize("reason", ["end_turn", "max_tokens", "tool_use"])
@pytest.mark.parametrize("blocks", [
    [{"type": "text", "text": "safe prose"}],
    [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}],
    [{"type": "thinking", "thinking": "safe", "signature": "safe-signature"}],
    [{"type": "redacted_thinking", "data": "safe"}],
    [{"type": "tool_use", "id": "safe-call", "name": "receipt", "input": {"unseen_nodes": [{"accepted": True}]}}],
    [{"type": "thinking", "thinking": "safe"}, {"type": "text", "text": "visible"}],
])
def test_terminal_content_topologies_do_not_require_visible_text(reason, blocks):
    stream = prefix("M")
    for index, block in enumerate(blocks):
        stream.step(content(index, block))
        stream.step({"type": "content_block_stop", "index": index})
    stream.step(usage_delta(reason=reason))
    stream.step({"type": "message_stop"})
    assert stream.snapshot()["semantic_terminal_complete"] is True
    assert stream.body()["content"] == blocks
    assert stream.body()["stop_reason"] == reason


@pytest.mark.parametrize("raw", ["{", "[]", "null", "false", '"safe"', "4"])
def test_tool_json_is_validated_before_success(raw):
    stream = prefix("M")
    stream.step(content(block={"type": "tool_use", "id": "safe-call", "name": "receipt", "input": {}}))
    stream.step({"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": raw}})
    stream.step({"type": "content_block_stop", "index": 0})
    stream.step(usage_delta(reason="tool_use"))
    before = message_data(stream)
    stream.step({"type": "message_stop"})
    assert stream.state == State.PROTOCOL_INVALID
    assert stream.snapshot()["semantic_terminal_complete"] is False
    assert message_data(stream) == before


@pytest.mark.parametrize("raw,shape", [
    (b'{"error":{"type":"overloaded_error"}}', "object"),
    (b'{"unexpected":[1]}', "object"), (b'"safe"', "string"),
    (b"4", "number"), (b"true", "boolean"), (b"[1]", "array"),
    (b"null", "null"), (b"safe malformed", "raw"), (b"", "empty"),
])
def test_all_error_payload_shapes_remain_provider_primary(raw, shape):
    frame = b"event: error\ndata: " + raw + b"\n\n"
    _, stream = evaluate_bytes(frame + b'event: ping\ndata: {"type":"ping"}\n\n')
    stream.step(Event.TIMEOUT, failure=httpx.ReadTimeout("safe timeout"))
    assert isinstance(stream.primary, AnthropicProviderTerminalError)
    evidence = stream.primary.provider_stream_error
    assert evidence.payload_shape == shape
    assert evidence.raw_payload_length == len(raw)
    assert evidence.secondary_post_error_ping_count == 1
    assert evidence.secondary_post_error_timeout_present is True
    assert len(evidence.raw_payload_sha256) == 64


@pytest.mark.parametrize("event", [Event.EOF, Event.TIMEOUT, Event.CANCELLATION,
                                   Event.TRANSPORT_EXCEPTION, Event.CAPTURE_COMMITTED, Event.CAPTURE_FAILED])
def test_remote_json_cannot_forge_internal_lifecycle_signals(event):
    stream = prefix("M")
    stream.step({"type": event.value})
    assert stream.state == State.PROTOCOL_INVALID
    assert stream.snapshot()["terminal_capture_complete"] is False


def test_capture_failure_cannot_be_rescued_by_later_provider_success():
    stream = prefix("M")
    failure = ProviderResponseCaptureError("SAFE_CAPTURE_FAILED")
    stream.step(Event.CAPTURE_FAILED, failure=failure)
    stream.step(usage_delta())
    stream.step({"type": "message_stop"})
    assert stream.snapshot()["terminal_capture_complete"] is False
    with pytest.raises(ProviderResponseCaptureError) as caught:
        stream.body()
    assert caught.value is failure


def test_usage_projection_retains_abbreviated_historical_envelope_without_message_authority():
    stream = AnthropicStream(usage_projection=True)
    for event in [start(), {"type": "message_delta", "usage": {"output_tokens": 9}},
                  {"type": "message_stop"}]:
        stream.step(event)
    assert stream.usage == {"input_tokens": 20, "output_tokens": 9}
    assert stream.snapshot()["semantic_terminal_complete"] is False
    stream.step({"type": "message_delta", "usage": {"output_tokens": 999999}})
    assert stream.state == State.PROTOCOL_INVALID
    assert stream.usage["output_tokens"] == 9
