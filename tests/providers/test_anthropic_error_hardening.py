"""Offline first Provider error precedence across the actual HTTP seam."""
import json

import httpx
import pytest

from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.anthropic import AnthropicAdapter, AnthropicProviderTerminalError
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.execution_failure_architecture import build_durable_failure_evidence
from novel_flywheel.provider_response_capture import parse_provider_protocol_input_bytes_v1, ProviderResponseCaptureError
from novel_flywheel.providers.anthropic import AnthropicStreamProtocolError


def frame(value, event="error"):
    return f"event: {event}\ndata: {json.dumps(value)}\n\n".encode()


class Wire(httpx.AsyncByteStream):
    def __init__(self, raw, timeout):
        self.raw, self.timeout = raw, timeout

    async def __aiter__(self):
        for index in range(0, len(self.raw), 7):
            yield self.raw[index:index + 7]
        if self.timeout:
            raise self.timeout if isinstance(self.timeout, BaseException) else httpx.ReadTimeout("synthetic timeout")

    async def aclose(self):
        pass


async def invoke(raw, timeout=False, observer=None):
    posts = []

    async def respond(request):
        posts.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=Wire(raw, timeout), request=request)

    adapter = AnthropicAdapter("https://offline.invalid/v1", "synthetic-key",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer, injected_http_transport=httpx.MockTransport(respond))
    try:
        await adapter.complete(ModelRequest(model="synthetic", messages=[Message(role="user", content="fixture")], max_output_tokens=64))
    except Exception as exc:
        return exc, posts
    finally:
        await adapter.client.aclose()
    pytest.fail("error stream became success")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"type":"error","error":{"type":"overloaded_error"}}, "private string", 7, True, [], None, {"error":False}, {"error":[]}])
@pytest.mark.parametrize("timeout", [False, True])
async def test_provider_error_wins_over_ping_tail(payload, timeout):
    exc, posts = await invoke(frame(payload) + frame({"type":"ping"}, "ping"), timeout)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert len(posts) == 1
    assert exc.provider_stream_error.secondary_post_error_ping_count == 1
    assert exc.provider_stream_error.secondary_post_error_timeout_present is timeout
    assert exc.provider_stream_error.transport_complete is (not timeout)
    root = build_durable_failure_evidence(exc, boundary="provider_transport").root
    assert root.family == "provider.terminal_error_event"
    assert root.dispatch_state == "response_captured"
    assert root.provider_stream_error is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", [b"data: incomplete", b"data: {bad}\n\n", b"data: \xff\n\n"])
async def test_bad_tail_does_not_destroy_observed_provider_error(tail):
    exc, posts = await invoke(frame({"error":{"type":"overloaded_error"}}) + tail, True)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert len(posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,shape", [(b"event: error\ndata: not-json\n\n", "raw"),
    (b"event: error\ndata:\n\n", "empty"), (b"event: error\n\n", "empty"),
    (frame(""), "string"), (frame(False), "boolean"), (frame(0), "number"),
    (frame({"error":{}}), "object"), (frame({}), "object")])
async def test_raw_empty_and_unrecognized_error_shapes(raw, shape):
    exc, posts = await invoke(raw)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.provider_stream_error.payload_shape == shape
    assert exc.provider_stream_error.raw_payload_sha256
    assert len(posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [None, False, 0, [], "", ["private"], {"type":True}, {"type":["overloaded_error"]}])
async def test_nested_nonobject_and_falsy_errors_never_escape(nested):
    exc, _ = await invoke(frame({"type":"error", "error":nested}), True)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.error_type == "provider_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", [frame({"type":"message_stop"}, "message_stop"),
    frame({"type":"message_delta","delta":{"stop_reason":"end_turn"}}, "message_delta"),
    frame({"type":"content_block_delta"}, "content_block_delta"),
    frame({"type":"error","error":{"type":"authentication_error"}}),
    b"event: ping\ndata: poisoned-non-json\n\n"])
async def test_primary_type_is_frozen_across_semantic_and_error_tails(tail):
    exc, _ = await invoke(frame({"error":{"type":"overloaded_error"}}) + tail, True)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.error_type == "overloaded_error"
    assert exc.provider_stream_error.secondary_post_error_event_count == 1


@pytest.mark.asyncio
async def test_named_error_is_authoritative_even_when_data_claims_success():
    exc, _ = await invoke(frame({"type":"ping", "error":{"type":"overloaded_error"}}))
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.provider_stream_error.event_data_type_conflict


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [b"data: broken\n\n", b"data: \xff\n\n",
    b": invalid-utf8-\xff\n\n", b"event: \xff\n\ndata: {}\n\n",
    frame({"type":"content_block_delta","index":0}, "content_block_delta"),
    frame({"type":"unknown"}, "unknown"),
    frame({"type":"error"}, "ping"), b"data: [DONE]\n\n"])
@pytest.mark.parametrize("timeout", [False, True])
async def test_later_error_cannot_skip_a_fatal_prefix(prefix, timeout):
    exc, _ = await invoke(prefix + frame({"error":{"type":"overloaded_error"}}), timeout)
    assert not isinstance(exc, AnthropicProviderTerminalError)


@pytest.mark.parametrize("name,kind", [("message_stop", "ping"), ("ping", "error"), ("message_delta", "ping")])
def test_conflicting_nonerror_event_metadata_is_fail_closed(name, kind):
    with pytest.raises(ProviderResponseCaptureError):
        parse_provider_protocol_input_bytes_v1(frame({"type":kind}, name), content_type="text/event-stream", anthropic_errors=True)


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\r\n"])
def test_unclosed_error_is_not_authoritative(suffix):
    with pytest.raises(ProviderResponseCaptureError):
        parse_provider_protocol_input_bytes_v1(b"event: error\ndata: {}" + suffix, content_type="text/event-stream", anthropic_errors=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
async def test_error_frames_support_sse_line_endings(ending):
    raw = b"event: error\ndata: {\ndata:   \"error\":{\"type\":\"overloaded_error\"}\ndata: }\n\n".replace(b"\n", ending)
    exc, _ = await invoke(raw, True)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.error_type == "overloaded_error"


class BrokenObserver:
    def before_http_post(self): pass
    def before_network_request(self): pass
    def capture_provider_protocol_input(self, **kwargs):
        self.capture = kwargs
        raise ValueError("private observer detail")
    def after_http_failure(self, **kwargs):
        raise RuntimeError("private usage detail")


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_capture_and_failure_observers_cannot_replace_primary(timeout):
    observer = BrokenObserver()
    exc, _ = await invoke(frame({"error":{"type":"overloaded_error"}}), timeout, observer)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.provider_stream_error.secondary_post_error_observer_failure_count == 2
    assert observer.capture["transport_complete"] is (not timeout)
    assert exc.__cause__ is None and exc.__suppress_context__


@pytest.mark.asyncio
async def test_safe_public_evidence_never_retains_provider_text_or_forged_metadata():
    private = "sk-private-novel-prose-secret-value"
    payload = {"type":"error", "error":{"type":private,"message":private},
               "provider_stream_error":{"provider_error_type":private}, "PRIMARY_TERMINAL_CAUSE":"SUCCESS"}
    exc, _ = await invoke(frame(payload))
    document = build_durable_failure_evidence(exc,boundary="provider_transport").model_dump_json()
    assert private not in document
    assert private not in str(exc)
    assert exc.error_type == "provider_error"


@pytest.mark.asyncio
async def test_no_error_timeout_keeps_existing_transport_outcome():
    exc, _ = await invoke(frame({"type":"ping"}, "ping"), True)
    assert isinstance(exc, httpx.ReadTimeout)


def test_shared_decoder_does_not_change_other_protocol_error_payloads():
    value = {"type":"error", "error":{"type":"legacy", "message":"opaque"}}
    events, _ = parse_provider_protocol_input_bytes_v1(
        frame(value) + frame({"type":"ping"}, "ping"), content_type="text/event-stream",
    )
    assert events == [value, {"type":"ping"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [b"", frame({"type":"ping"}, "ping")])
async def test_error_after_message_stop_is_not_ignored(suffix):
    start = [
        {"type":"message_start", "message":{"id":"fixture", "usage":{"input_tokens":3}}},
        {"type":"message_delta", "delta":{"stop_reason":"end_turn"}, "usage":{"output_tokens":1}},
        {"type":"message_stop"},
    ]
    prefix = b"".join(frame(item, item["type"]) for item in start)
    exc, _ = await invoke(prefix + frame({"error":{"type":"overloaded_error"}}) + suffix, True)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.error_type == "overloaded_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.DecodingError("private decoder tail"), RuntimeError("private iterator tail"), httpx.RemoteProtocolError("private protocol tail")])
async def test_reader_failure_after_error_is_secondary(failure):
    exc, _ = await invoke(frame({"error":{"type":"overloaded_error"}}), failure)
    assert isinstance(exc, AnthropicProviderTerminalError)
    assert exc.provider_stream_error.secondary_post_error_transport_present
