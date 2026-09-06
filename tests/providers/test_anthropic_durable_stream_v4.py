"""Invariant tests of the real incremental owner; all payloads synthetic."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from novel_flywheel.anthropic_stream import AnthropicProviderTerminalError, AnthropicStreamProtocolError, Event
from novel_flywheel.anthropic_durable_stream import (
    DurableAnthropicStreamV1, IncrementalSSEFramerV1, StreamDurableAckV1, digest,
)


def wire(events, newline='\n'):
    return ''.join('event: '+e['type']+newline+'data: '+json.dumps(e,ensure_ascii=False)+newline*2
                   for e in events).encode()


EVENTS = [
    {'type':'message_start','message':{'id':'synthetic','usage':{'input_tokens':17}}},
    {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
    {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'测试🙂 independent'}},
    {'type':'content_block_stop','index':0},
    {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':9}},
    {'type':'message_stop'},
]
ERROR = {'type':'error','error':{'type':'overloaded_error','message':'synthetic'}}
PING = {'type':'ping'}


class Sink:
    def __init__(self): self.checkpoints=[]
    def __call__(self,checkpoint):
        self.checkpoints.append(deepcopy(checkpoint))
        return StreamDurableAckV1.for_checkpoint(checkpoint)


def outcome(owner):
    try:
        body=owner.body()
        return ('success',body['content'],body['usage'])
    except BaseException as exc:
        return (type(exc).__name__,getattr(exc,'reason_code',None),
                getattr(exc,'error_type',None))


@pytest.mark.parametrize('newline',['\n','\r','\r\n'])
@pytest.mark.parametrize('chunk',[1,2,7,71,4096])
def test_incremental_chunk_invariance(newline,chunk):
    raw=wire(EVENTS+[PING]*3,newline)
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='test',sink=sink)
    for offset in range(0,len(raw),chunk):owner.ingest(raw[offset:offset+chunk])
    owner.finish()
    assert outcome(owner)==('success',[{'type':'text','text':'测试🙂 independent'}],{'input_tokens':17,'output_tokens':9})
    assert owner.post_terminal_ping_count==3
    assert owner.raw_durable_prefix==len(raw)
    assert owner.terminal_evidence_durable
    for old,new in zip(sink.checkpoints,sink.checkpoints[1:]):
        for field in ('raw_prefix','framed_prefix','semantic_prefix'):assert new[field]>=old[field]
    restored=DurableAnthropicStreamV1.restore(sink.checkpoints[-1],expected_sha256=digest(sink.checkpoints[-1]))
    assert outcome(restored)==outcome(owner)
    assert restored.snapshot()==owner.snapshot()


@pytest.mark.parametrize('fault',[httpx.ReadTimeout,asyncio.CancelledError,httpx.ReadError])
@pytest.mark.parametrize('terminal',['none','success','error'])
def test_partial_frame_causal_precedence(terminal,fault):
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='test',sink=sink)
    prefix=wire(EVENTS) if terminal=='success' else wire([ERROR]) if terminal=='error' else b''
    owner.ingest(prefix)
    owner.ingest(b'event: ping\ndata: {')
    injected=fault('synthetic')
    owner.finish(injected)
    if terminal=='success':assert outcome(owner)[0]=='success'
    elif terminal=='error':assert isinstance(owner.primary,AnthropicProviderTerminalError)
    else:assert owner.primary is injected
    assert not owner.semantic_terminal_complete if terminal!='success' else owner.semantic_terminal_complete
    checkpoint=sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(checkpoint,expected_sha256=digest(checkpoint))
    assert restored.snapshot()==owner.snapshot()
    assert outcome(restored)==outcome(owner)


@pytest.mark.parametrize('newline',['\n','\r','\r\n'])
def test_reload_then_continue_at_every_byte(newline):
    raw=wire(EVENTS+[PING],newline)+b'event: ping\ndata: {'
    # Every byte, including split UTF-8 and CR/LF, is a registered boundary.
    for cut in range(len(raw)+1):
        sink=Sink();live=DurableAnthropicStreamV1(owner_id='test',sink=sink)
        live.ingest(raw[:cut])
        cp=sink.checkpoints[-1]
        restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp),sink=Sink())
        for owner in (live,restored):
            owner.ingest(raw[cut:]);owner.finish(httpx.ReadTimeout('synthetic'))
        assert outcome(live)==outcome(restored),cut
        assert live.snapshot()==restored.snapshot(),cut


@pytest.mark.parametrize('fault',[None,httpx.ReadTimeout,asyncio.CancelledError,httpx.ReadError])
@pytest.mark.parametrize('newline',['\n','\r','\r\n'])
def test_fault_at_every_generated_byte_boundary(fault,newline):
    success=wire(EVENTS,newline);error=wire([ERROR],newline)
    # A CR alone completes the blank line; the optional following LF adds no
    # semantic information, including when a fault lands between CR and LF.
    optional_lf = 1 if newline == '\r\n' else 0
    for raw,terminal_end,expected in [(success+wire([PING],newline)+b'data: {',len(success)-optional_lf,'success'),
                                      (error+b'data: {',len(error)-optional_lf,'AnthropicProviderTerminalError')]:
        for cut in range(len(raw)+1):
            owner=DurableAnthropicStreamV1(owner_id='fault',sink=Sink())
            owner.ingest(raw[:cut]);owner.finish(fault('synthetic') if fault else None)
            if cut>=terminal_end:assert outcome(owner)[0]==expected,(cut,fault)
            else:assert outcome(owner)[0]!='success',(cut,fault)


def test_ack_requires_exact_owner_generation_and_prefix():
    owner=DurableAnthropicStreamV1(owner_id='test')
    cp=owner.checkpoint();ack=StreamDurableAckV1.for_checkpoint(cp)
    for invalid in (True,None,replace(ack,owner_id='other'),replace(ack,generation=2),
                    replace(ack,raw_durable_prefix=1)):
        with pytest.raises(AnthropicStreamProtocolError):owner.apply_ack(cp,invalid)
    owner.apply_ack(cp,ack)
    with pytest.raises(AnthropicStreamProtocolError):owner.apply_ack(cp,ack)


@pytest.mark.parametrize('event',[EVENTS[0],EVENTS[2],{'type':'future_event'},ERROR])
def test_ping_exception_does_not_generalize(event):
    owner=DurableAnthropicStreamV1(owner_id='strict',sink=Sink())
    owner.ingest(wire(EVENTS));identity=owner.terminal_identity
    owner.ingest(wire([event]));owner.finish()
    assert outcome(owner)[0]!='success'
    assert owner.terminal_identity==identity
    assert owner.success_terminal_identity==identity
    if event['type']=='error':assert owner.provider_error_terminal_identity not in {None,identity}


def test_checkpoint_tamper_rejected():
    owner=DurableAnthropicStreamV1(owner_id='test');owner.ingest(wire(EVENTS))
    cp=owner.checkpoint();expected=digest(cp);cp['raw_prefix']+=1
    with pytest.raises(AnthropicStreamProtocolError):DurableAnthropicStreamV1.restore(cp,expected_sha256=expected)
    with pytest.raises(AnthropicStreamProtocolError):DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))


@pytest.mark.parametrize('terminal',[EVENTS,[ERROR]])
def test_final_capture_failure_is_rehydrated(terminal):
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='capture',sink=sink)
    owner.ingest(wire(terminal));owner.finish()
    owner.step(Event.CAPTURE_FAILED,failure=RuntimeError('synthetic private failure'))
    cp=sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert outcome(owner)==outcome(restored)
    assert owner.snapshot()==restored.snapshot()
    tampered=deepcopy(cp);tampered['state']['primary_cause']='SUCCESS'
    with pytest.raises(AnthropicStreamProtocolError):
        DurableAnthropicStreamV1.restore(tampered,expected_sha256=digest(tampered))


def test_provider_error_survives_persistence_failure():
    def unavailable(checkpoint):raise OSError('synthetic storage unavailable')
    owner=DurableAnthropicStreamV1(owner_id='test',sink=unavailable)
    owner.ingest(wire([ERROR]));owner.finish(httpx.ReadTimeout('synthetic'))
    assert isinstance(owner.primary,AnthropicProviderTerminalError)
    assert not owner.terminal_evidence_durable
    owner.sink=Sink();owner.commit()
    cp=owner.sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert outcome(owner)==outcome(restored)
    assert owner.snapshot()==restored.snapshot()


def test_durable_success_survives_tail_checkpoint_failure():
    owner=DurableAnthropicStreamV1(owner_id='test',sink=Sink())
    owner.ingest(wire(EVENTS))
    def unavailable(checkpoint):raise OSError('synthetic')
    owner.sink=unavailable;owner.ingest(b'data: {');owner.finish(httpx.ReadTimeout('synthetic'))
    assert outcome(owner)[0]=='success'
    assert owner.persistence_failure_count==2
    owner.sink=Sink();owner.commit()
    cp=owner.sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert restored.snapshot()==owner.snapshot()


def test_ambiguous_committed_ack_is_confirmed_without_rewriting_generation():
    stored={};calls=[]
    def sink(cp):
        calls.append(digest(cp))
        previous=stored.setdefault(cp['generation'],deepcopy(cp))
        assert previous==cp
        if len(calls)<=2:raise OSError('synthetic ack lost')
        return StreamDurableAckV1.for_checkpoint(cp)
    owner=DurableAnthropicStreamV1(owner_id='ack-loss',sink=sink)
    owner.ingest(wire(EVENTS))
    owner.finish()
    assert calls[0]==calls[1]==calls[2]
    assert owner.generation==2
    cp=stored[2]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert outcome(restored)==outcome(owner)
    assert restored.snapshot()==owner.snapshot()


def test_read_only_rehydration_cannot_grant_new_nondurable_terminal():
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='read-only',sink=sink)
    owner.ingest(wire(EVENTS[:-1]));cp=sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    restored.ingest(wire(EVENTS[-1:]));restored.finish()
    with pytest.raises(AnthropicStreamProtocolError,match='NOT_DURABLE'):restored.body()


def test_rejected_bytes_after_close_do_not_corrupt_checkpoint():
    owner=DurableAnthropicStreamV1(owner_id='closed',sink=Sink())
    owner.ingest(wire(EVENTS));owner.finish();before=owner.checkpoint()
    with pytest.raises(AnthropicStreamProtocolError):owner.ingest(b'x')
    assert owner.checkpoint()==before


def test_tail_diagnostics_do_not_advance_semantic_accepted_prefix():
    owner=DurableAnthropicStreamV1(owner_id='prefix',sink=Sink())
    owner.ingest(wire(EVENTS));accepted=owner.semantic_accepted_prefix
    owner.ingest(wire([PING]));owner.ingest(b'data: {');owner.finish(httpx.ReadTimeout('synthetic'))
    assert owner.semantic_accepted_prefix==accepted
    assert owner.raw_durable_prefix>owner.framed_event_durable_prefix>accepted


@pytest.mark.parametrize('case', ['empty_event_reset', 'empty_data_tail',
    'invalid_event_only', 'invalid_overwritten_event', 'invalid_comment'])
def test_sse_field_normalization_and_encoding_at_every_split_and_reload(case):
    start = json.dumps(EVENTS[0]).encode()
    raw, expected = {
        'empty_event_reset': (b'event: error\nevent\ndata: '+start+b'\n\n'+wire(EVENTS[1:]), 'success'),
        'empty_data_tail': (wire(EVENTS)+b'data\n\n', 'ProviderResponseCaptureError'),
        'invalid_event_only': (b'event: \xff\n\n'+wire(EVENTS), 'ProviderResponseCaptureError'),
        'invalid_overwritten_event': (b'event: \xff\nevent: message_start\ndata: '+start+b'\n\n'+wire(EVENTS[1:]), 'ProviderResponseCaptureError'),
        'invalid_comment': (b': \xff\n\n'+wire(EVENTS), 'ProviderResponseCaptureError'),
    }[case]
    for cut in range(len(raw)+1):
        sink=Sink();live=DurableAnthropicStreamV1(owner_id='fields',sink=sink)
        live.ingest(raw[:cut]);cp=sink.checkpoints[-1]
        reloaded=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp),sink=Sink())
        for owner in (live,reloaded):
            owner.ingest(raw[cut:]);owner.finish()
            assert outcome(owner)[0]==expected,(case,cut,outcome(owner))
        assert live.snapshot()==reloaded.snapshot(),(case,cut)


@pytest.mark.parametrize('base',[httpx.ReadTimeout,asyncio.CancelledError,httpx.ReadError])
@pytest.mark.parametrize('terminal',['none','success','error'])
def test_transport_subclasses_use_identical_live_and_reload_categories(base,terminal):
    class DerivedTransportFailure(base):
        pass
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='subclass',sink=sink)
    owner.ingest(wire(EVENTS if terminal=='success' else [ERROR] if terminal=='error' else []))
    owner.ingest(b'data: {');owner.finish(DerivedTransportFailure('private synthetic'))
    cp=sink.checkpoints[-1]
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert outcome(owner)==outcome(restored)
    assert owner.snapshot()==restored.snapshot()
    if terminal=='none':assert type(owner.primary) is base
    if terminal=='error':
        assert owner.primary.provider_stream_error==restored.primary.provider_stream_error


def test_success_ack_does_not_attest_later_unpersisted_provider_error():
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='fatal-error',sink=sink)
    owner.ingest(wire(EVENTS));success_cp=sink.checkpoints[-1]
    assert owner.success_terminal_evidence_durable
    def unavailable(cp):raise OSError('synthetic')
    owner.sink=unavailable;owner.ingest(wire([ERROR]))
    assert isinstance(owner.primary,AnthropicProviderTerminalError)
    assert owner.success_terminal_evidence_durable
    assert not owner.provider_error_terminal_evidence_durable
    assert not owner.terminal_evidence_durable
    assert not owner.terminal_capture_complete
    assert owner.raw_durable_prefix==success_cp['raw_prefix']
    owner.sink=Sink();owner.commit()
    assert owner.provider_error_terminal_evidence_durable
    assert owner.terminal_evidence_durable
    cp=owner.sink.checkpoints[-1]
    reloaded=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert owner.snapshot()==reloaded.snapshot()


DURABILITY_ACK_CASES = ('valid','boolean','none','owner','generation','checkpoint_hash',
    'raw_prefix','framed_prefix','semantic_prefix','terminal_identity','stale','parent','not_submitted')


@pytest.mark.parametrize('case',DURABILITY_ACK_CASES)
def test_generated_durable_ack_binding(case):
    owner=DurableAnthropicStreamV1(owner_id='generated-ack')
    cp=owner.checkpoint();ack=StreamDurableAckV1.for_checkpoint(cp)
    if case=='valid':
        owner.apply_ack(cp,ack)
        assert owner.generation==1 and owner.checkpoint_sha256==digest(cp)
        assert not owner.terminal_evidence_durable
        return
    changes={
        'owner':{'owner_id':'other'},'generation':{'generation':2},
        'checkpoint_hash':{'checkpoint_sha256':'0'*64},
        'raw_prefix':{'raw_durable_prefix':1},'framed_prefix':{'framed_event_durable_prefix':1},
        'semantic_prefix':{'semantic_accepted_prefix':1},'terminal_identity':{'terminal_event_identity':'0'*64},
    }
    reason='ACK_MISMATCH'
    if case=='boolean':ack=True
    elif case=='none':ack=None
    elif case in changes:ack=replace(ack,**changes[case])
    elif case=='stale':owner.apply_ack(cp,ack);reason='ACK_STALE'
    elif case=='parent':
        cp['parent_sha256']='0'*64;ack=StreamDurableAckV1.for_checkpoint(cp);reason='ACK_STALE'
    elif case=='not_submitted':
        cp['journal']=[{'bytes':''}];ack=StreamDurableAckV1.for_checkpoint(cp);reason='ACK_NOT_SUBMITTED'
    before=owner.snapshot()
    with pytest.raises(AnthropicStreamProtocolError,match=reason):owner.apply_ack(cp,ack)
    assert owner.snapshot()==before


@pytest.mark.parametrize('event', [Event.EOF, Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION])
def test_explicit_transport_control_preserves_requested_event(event):
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='explicit-control',sink=sink)
    owner.step(event)
    assert owner.journal[-1]['transport']==event.value
    restored=DurableAnthropicStreamV1.restore(sink.checkpoints[-1],expected_sha256=digest(sink.checkpoints[-1]))
    assert owner.snapshot()==restored.snapshot() and outcome(owner)==outcome(restored)
    assert owner.primary is not None


@pytest.mark.parametrize('event,failure', [(Event.EOF,httpx.ReadTimeout('x')),
    (Event.TIMEOUT,asyncio.CancelledError()), (Event.CANCELLATION,httpx.ReadError('x'))])
def test_mismatched_transport_control_rejected_before_mutation(event,failure):
    owner=DurableAnthropicStreamV1(owner_id='explicit-mismatch',sink=Sink())
    before=owner.checkpoint()
    with pytest.raises(AnthropicStreamProtocolError,match='CONTROL_CAUSE_MISMATCH'):
        owner.step(event,failure=failure)
    assert owner.checkpoint()==before


@pytest.mark.parametrize('domain', ['capture','boundary','protocol'])
@pytest.mark.parametrize('subclass', [False,True])
@pytest.mark.parametrize('message', ['PRIVATE_CANARY_ONLY','PRIVATE_CANARY_ONLY: private suffix'])
def test_unregistered_uppercase_control_text_is_never_persisted(domain,subclass,message):
    from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
    from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError
    cls={'capture':ProviderResponseCaptureError,'boundary':FullShortExecutionBoundaryError,
         'protocol':AnthropicStreamProtocolError}[domain]
    if subclass:cls=type('PrivateSubclass',(cls,),{})
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='reason-privacy',sink=sink)
    owner.ingest(wire(EVENTS));owner.step(Event.CAPTURE_FAILED,failure=cls(message))
    cp=sink.checkpoints[-1]
    assert 'PRIVATE_CANARY_ONLY' not in json.dumps(cp)
    assert 'private suffix' not in json.dumps(cp)
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert type(owner.primary) is type(restored.primary)
    assert owner.primary.reliability_failure==restored.primary.reliability_failure


@pytest.mark.parametrize('terminal',['none','success','error'])
@pytest.mark.parametrize('case',['httpcore_read','httpcore_connect','foreign_timeout',
    'foreign_cancel','same_named_subclass'])
def test_exception_names_cannot_impersonate_registered_transport_types(terminal,case):
    import httpcore
    cls={'httpcore_read':httpcore.ReadTimeout,'httpcore_connect':httpcore.ConnectTimeout,
         'foreign_timeout':type('ReadTimeout',(RuntimeError,),{}),
         'foreign_cancel':type('CancelledError',(RuntimeError,),{}),
         'same_named_subclass':type('ReadTimeout',(httpx.ReadTimeout,),{})}[case]
    sink=Sink();owner=DurableAnthropicStreamV1(owner_id='actual-type',sink=sink)
    owner.ingest(wire(EVENTS if terminal=='success' else [ERROR] if terminal=='error' else []))
    owner.finish(cls('private transport text'))
    cp=sink.checkpoints[-1]
    expected=Event.TIMEOUT if case=='same_named_subclass' else Event.TRANSPORT_EXCEPTION
    assert owner.journal[-1]['transport']==expected.value
    restored=DurableAnthropicStreamV1.restore(cp,expected_sha256=digest(cp))
    assert owner.snapshot()==restored.snapshot() and outcome(owner)==outcome(restored)
    assert getattr(owner.primary,'provider_stream_error',None)==getattr(restored.primary,'provider_stream_error',None)
    if terminal=='none':assert type(owner.primary) is (httpx.ReadTimeout if case=='same_named_subclass' else RuntimeError)
