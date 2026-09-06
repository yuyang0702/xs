"""Malformed semantic fields must fail before gaining terminal authority."""
import pytest

from novel_flywheel.anthropic_stream import (
    AnthropicStream, AnthropicStreamProtocolError, State,
)


START = {"type": "message_start", "message": {"id": "synthetic", "usage": {}}}
BLOCK = {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}}


@pytest.mark.parametrize("value", [[], {}, 0, False, None])
@pytest.mark.parametrize("location", ["initial_text", "delta_text"])
def test_invalid_text_never_becomes_stringified_semantic_content(location, value):
    owner = AnthropicStream()
    owner.step(START)
    if location == "initial_text":
        owner.step({**BLOCK, "content_block": {"type": "text", "text": value}})
    else:
        owner.step(BLOCK)
        owner.step({"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": value}})
    assert owner.state == State.PROTOCOL_INVALID
    assert isinstance(owner.primary, AnthropicStreamProtocolError)
    assert not owner.semantic_terminal_complete
    owner.step({"type": "message_stop"})
    assert not owner.semantic_terminal_complete


@pytest.mark.parametrize("value", [[], "", 0, False])
@pytest.mark.parametrize("location", ["start_usage", "delta_usage", "delta_object"])
def test_falsey_nonobjects_do_not_gain_missing_field_semantics(location, value):
    owner = AnthropicStream()
    if location == "start_usage":
        owner.step({"type": "message_start", "message": {"usage": value}})
    else:
        owner.step(START)
        owner.step({"type": "message_delta", "delta": value} if location == "delta_object"
                   else {"type": "message_delta", "usage": value})
    assert owner.state == State.PROTOCOL_INVALID
    assert owner.primary is not None
    assert not isinstance(owner.primary, (AttributeError, TypeError))
    assert not owner.semantic_terminal_complete
