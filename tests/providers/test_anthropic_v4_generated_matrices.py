"""Generated cells execute the production framer and independent semantic oracle."""
from pathlib import Path
import json

import httpx
import pytest

from novel_flywheel.anthropic_durable_stream import (
    DurableAnthropicStreamV1, IncrementalSSEFramerV1, FrameState, digest,
)
from novel_flywheel.anthropic_stream import AnthropicStreamProtocolError, State
from tests.providers.test_anthropic_durable_stream_v4 import EVENTS, ERROR, PING, Sink, outcome, wire
from tests.providers.test_anthropic_closed_world_transitions import (
    CELLS, test_every_registered_state_event_transition as assert_semantic_cell,
)

REPORTS=Path(__file__).resolve().parents[2]/'docs/superpowers/reports/new-main-shared-anthropic-stream-autonomous-closure-v4'
FRAMING=json.loads((REPORTS/'sse-framing-transition-matrix-v1.json').read_bytes())['cells']
SEMANTIC=json.loads((REPORTS/'semantic-stream-transition-matrix-v2.json').read_bytes())['cells']


def framer_at(state):
    framer=IncrementalSSEFramerV1()
    if state=='FRAME_PARTIAL':framer.receive(b'data: {')
    elif state in {'FRAME_COMPLETE_NOT_DECODED','FRAME_DECODED'}:
        framer.receive(b'data: {}\n\n')
        if state=='FRAME_DECODED':framer.pop()
    elif state=='STREAM_CLOSED':framer.close()
    assert framer.state.value==state
    return framer


@pytest.mark.parametrize('cell',FRAMING,ids=lambda c:c['from_state']+'-'+c['input_class'])
def test_generated_framing_cell(cell):
    framer=framer_at(cell['from_state']);before=framer.snapshot();raw=bytes(framer.raw)
    if cell['input_class'] in {'BYTES','EVENT_DELIMITER'}:
        if cell['from_state']=='STREAM_CLOSED':
            with pytest.raises(AnthropicStreamProtocolError):framer.receive(bytes.fromhex(cell['test_input_hex']))
            assert framer.snapshot()==before
        else:
            framer.receive(bytes.fromhex(cell['test_input_hex']))
            assert bytes(framer.raw)==raw+bytes.fromhex(cell['test_input_hex'])
    else:
        framer.close()
        assert bytes(framer.raw)==raw
        assert framer.framed_prefix==before['framed_prefix']
    assert framer.state.value==cell['test_expected_next_state']


@pytest.mark.parametrize('source,event,expected',[c for c in CELLS if c[1].value in {r['input_class'] for r in SEMANTIC}])
def test_generated_semantic_cell(source,event,expected):
    # Normative expected outcomes come from independently specified literal
    # rows; the runtime registry does not generate its own expected answers.
    assert_semantic_cell(source,event,expected)


PERSISTABLE=[
    (State.BEFORE_MESSAGE,[]),(State.MESSAGE_ACTIVE,EVENTS[:1]),
    (State.CONTENT_ACTIVE,EVENTS[:3]),(State.CONTENT_COMPLETE,EVENTS[:4]),
    (State.MESSAGE_DELTA,EVENTS[:5]),(State.SUCCESS,EVENTS),
    (State.SUCCESS_TAIL,EVENTS+[PING]),(State.PROVIDER_ERROR,[ERROR]),
    (State.ERROR_TAIL,[ERROR,PING]),(State.TRANSPORT_FAILURE,[]),
    (State.PROTOCOL_INVALID,[{'type':'unseen_version_event'}]),
]


@pytest.mark.parametrize('state,events',PERSISTABLE,ids=[s.value for s,_ in PERSISTABLE])
@pytest.mark.parametrize('partial',[False,True])
def test_registered_persistable_state_rehydration(state,events,partial):
    owner=DurableAnthropicStreamV1(owner_id='all-states',sink=Sink())
    owner.ingest(wire(events))
    if partial:owner.ingest(b'event: ping\ndata: {')
    if state==State.TRANSPORT_FAILURE:owner.finish(httpx.ReadTimeout('synthetic'))
    assert owner.state==state
    cp=owner.sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp),sink=Sink())
    assert restored.snapshot()==owner.snapshot()
    for current in (owner,restored):current.finish(httpx.ReadTimeout('synthetic'))
    assert outcome(owner)==outcome(restored)
    assert owner.snapshot()==restored.snapshot()
