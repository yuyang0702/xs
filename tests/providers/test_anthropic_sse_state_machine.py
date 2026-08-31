from __future__ import annotations

import json

import pytest

from novel_flywheel.providers.anthropic import (
    AnthropicAdapter,
    AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError,
    AnthropicStreamProtocolError,
)


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
