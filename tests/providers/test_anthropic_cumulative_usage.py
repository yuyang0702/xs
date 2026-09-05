"""Protocol-owned usage; synthetic isomorphic probe fixture, never private prose."""
from __future__ import annotations

import json

import pytest

from novel_flywheel.provider_response_capture import (
    ProviderResponseCaptureError, extract_provider_reported_actual_usage_v1,
)
from novel_flywheel.providers.anthropic import (
    AnthropicAdapter, AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError, AnthropicStreamProtocolError,
)


def events(start=None, updates=None, *, stop="end_turn", block=None):
    start = start if start is not None else {
        "input_tokens": 48916, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    }
    updates = updates if updates is not None else [{
        "input_tokens": 89255, "output_tokens": 9,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "billing_usage": {"source": "oai_chat", "semantic": "openai",
                          "openai_usage": {"prompt_tokens": 89255,
                                           "completion_tokens": 9},
                          "input_tokens": 0, "output_tokens": 0},
    }]
    result = [
        {"type": "message_start", "message": {"id": "synthetic",
                                               "usage": start}},
        {"type": "content_block_start", "index": 0,
         "content_block": block or {"type": "text", "text": ""}},
    ]
    if block is None:
        for size in (5, 11, 16):
            result.append({"type": "content_block_delta", "index": 0,
                           "delta": {"type": "text_delta", "text": "x" * size}})
    result.append({"type": "content_block_stop", "index": 0})
    for index, usage in enumerate(updates):
        result.append({"type": "message_delta", "usage": usage,
                       "delta": {"stop_reason": stop if index == len(updates)-1 else None}})
    result.append({"type": "message_stop"})
    return result


def wire(items):
    return "".join("event: " + item["type"] + "\ndata: " +
                   json.dumps(item, separators=(",", ":")) + "\n\n"
                   for item in items).encode()


def project(items):
    raw = wire(items)
    response = AnthropicAdapter.replay_protocol_input_bytes_v1(
        raw, content_type="text/event-stream")
    receipt = extract_provider_reported_actual_usage_v1(
        raw, protocol="anthropic", content_type="text/event-stream")
    assert (response.input_tokens, response.output_tokens) == (
        receipt["input_tokens"], receipt["output_tokens"])
    return response, receipt


def test_sanitized_isomorphic_probe01_final_snapshot_crosses_adapter_receipt_boundary():
    response, receipt = project(events())
    assert (response.input_tokens, response.output_tokens) == (89255, 9)
    assert response.text == "x" * 32
    assert response.finish_reason == "end_turn"
    assert response.provider_state["protocol_terminal_event"] == "message_stop"
    assert receipt["source_topologies"] == [
        "event[0].message.usage", "event[6].usage"]


@pytest.mark.parametrize("start,updates,expected", [
    ({"input_tokens": 40, "output_tokens": 1}, [{"output_tokens": 9}], (40, 9)),
    ({"input_tokens": 40, "output_tokens": 1}, [{"input_tokens": 50, "output_tokens": 9}], (50, 9)),
    ({"input_tokens": 40, "output_tokens": 1}, [{"output_tokens": 3}, {"output_tokens": 9}], (40, 9)),
    ({"input_tokens": 40, "output_tokens": 9}, [{}], (40, 9)),
    ({"input_tokens": 40, "cache_read_input_tokens": 10, "output_tokens": 1},
     [{"input_tokens": 50, "output_tokens": 9}], (60, 9)),
    ({"input_tokens": 40, "cache_creation_input_tokens": 10, "output_tokens": 1},
     [{"input_tokens": None, "cache_creation_input_tokens": 0, "output_tokens": 9}], (40, 9)),
    ({"input_tokens": 40, "output_tokens": 1},
     [{"input_tokens": 50, "output_tokens": 8}, {"input_tokens": 35, "output_tokens": 7}], (35, 7)),
])
def test_cumulative_optional_sparse_and_zero_fields(start, updates, expected):
    response, _ = project(events(start, updates))
    assert (response.input_tokens, response.output_tokens) == expected


@pytest.mark.parametrize("stop,block", [
    ("end_turn", None), ("max_tokens", None),
    ("end_turn", {"type": "thinking", "thinking": "synthetic", "signature": "safe"}),
    ("tool_use", {"type": "tool_use", "id": "safe", "name": "receipt", "input": {"ok": True}}),
])
def test_terminal_and_artifact_semantics_unchanged(stop, block):
    response, _ = project(events(stop=stop, block=block))
    assert response.finish_reason == stop
    assert bool(response.tool_calls) is (stop == "tool_use")
    if block and block["type"] == "thinking":
        assert response.text == ""


def test_provider_error_after_usage_remains_provider_error():
    items = events()[:-1] + [{"type": "error", "error": {"type": "overloaded_error"}}]
    with pytest.raises(AnthropicProviderTerminalError):
        AnthropicAdapter.replay_protocol_input_bytes_v1(wire(items), content_type="text/event-stream")


@pytest.mark.parametrize("mutation,error", [
    (lambda e: e[:-1], AnthropicStreamIncompleteError),
    (lambda e: e[:-2] + [e[2]] + e[-2:], AnthropicStreamProtocolError),
    (lambda e: e[:-1] + [e[1]] + e[-1:], AnthropicStreamProtocolError),
])
def test_genuine_protocol_faults_still_fail_closed(mutation, error):
    with pytest.raises(error):
        AnthropicAdapter.replay_protocol_input_bytes_v1(wire(mutation(events())), content_type="text/event-stream")


@pytest.mark.parametrize("bad", [-1, True, "9", 1.5])
def test_invalid_usage_is_precise_and_fail_closed(bad):
    with pytest.raises(ProviderResponseCaptureError, match="PROVIDER_REPORTED_USAGE_FIELD_INVALID"):
        project(events(updates=[{"input_tokens": bad, "output_tokens": 9}]))


def test_json_and_stream_cached_input_use_the_same_canonical_total():
    usage = {"input_tokens": 11, "cache_read_input_tokens": 7,
             "cache_creation_input_tokens": 3, "output_tokens": 9}
    raw = json.dumps({"id": "safe", "content": [{"type": "text", "text": "ok"}],
                      "stop_reason": "end_turn", "usage": usage}).encode()
    response = AnthropicAdapter.replay_protocol_input_bytes_v1(raw, content_type="application/json")
    receipt = extract_provider_reported_actual_usage_v1(raw, protocol="anthropic", content_type="application/json")
    stream, _ = project(events(usage, [{}]))
    assert response.input_tokens == stream.input_tokens == receipt["input_tokens"] == 21
