"""Actual Full Short observer, signed storage, adapter and HTTP-only fault seam."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from tests.test_full_short_execution import (
    _store, _authorize_offline, _observer, _request, _policy, _routes, _egress, _bind_route_with_capacity,
)
from tests.providers.test_anthropic_durable_stream_v4 import EVENTS, ERROR, PING, wire, outcome
from novel_flywheel.anthropic_durable_stream import digest
from novel_flywheel.anthropic_stream import AnthropicProviderTerminalError
from novel_flywheel.full_short_stream_checkpoint import load_stream_owner_v1, persist_stream_checkpoint_v1
from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError, FullShortDispatchLedgerObserverV1
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.provider_response_capture import ProviderResponseCaptureError


class Chunks(httpx.AsyncByteStream):
    def __init__(self,raw,fault=None,close_fault=None):
        self.raw,self.fault,self.close_fault=raw,fault,close_fault
    async def __aiter__(self):
        for start in range(0,len(self.raw),37):yield self.raw[start:start+37]
        if self.fault:raise self.fault
    async def aclose(self):
        if self.close_fault:raise self.close_fault


@pytest.mark.parametrize('terminal', ['success','error','partial'])
@pytest.mark.parametrize('failure_type,reason', [
    (ProviderResponseCaptureError,'PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID'),
    (FullShortExecutionBoundaryError,'CAPTURE_ATTESTATION_SIGNER_UNAVAILABLE_AFTER_RESTART'),
    (RuntimeError,'private synthetic payload'),
])
async def test_capture_control_preserves_typed_failure_after_signed_reload(tmp_path,terminal,failure_type,reason):
    store=_store(tmp_path);execution_id='capture-control'
    _authorize_offline(store,execution_id)
    observer=FullShortDispatchLedgerObserverV1(store=store,execution_id=execution_id,
        policy=_policy(store),authorized_routes=_routes(),egress_policy=_egress())
    _bind_route_with_capacity(observer,role='planning',lane='primary',provider_id='provider',
        model_id='model-id',route_fingerprint='9'*64)
    raw=wire(EVENTS+[PING] if terminal=='success' else [ERROR] if terminal=='error' else [])
    posts=[]
    async def respond(request):
        posts.append(request)
        return httpx.Response(200,request=request,stream=Chunks(raw),headers={'content-type':'text/event-stream'})
    adapter=AnthropicAdapter('https://unit.test/v1','synthetic',
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),attempt_observer=observer,
        injected_http_transport=httpx.MockTransport(respond))
    def failed_capture(*args,**kwargs):
        raise failure_type(reason+': private synthetic payload')
    adapter._capture_provider_protocol_input=failed_capture
    try:
        with pytest.raises(Exception):await adapter.complete(_request())
    finally:await adapter.client.aclose()
    live=adapter._last_stream_outcome_v1
    restored=load_stream_owner_v1(store=store,policy=observer.policy,execution_id=execution_id,ordinal=1)
    assert len(posts)==1
    assert live.snapshot()==restored.snapshot()
    assert type(live.primary) is type(restored.primary)
    assert str(live.primary)==str(restored.primary)
    assert getattr(live.primary,'reliability_failure',None)==getattr(restored.primary,'reliability_failure',None)
    assert getattr(live.primary,'provider_stream_error',None)==getattr(restored.primary,'provider_stream_error',None)
    assert 'private synthetic payload' not in json.dumps(live.journal)
    if terminal=='success':
        assert type(live.primary) is failure_type
        if failure_type is not RuntimeError:
            assert str(live.primary)==reason
            assert live.primary.reliability_failure is not None


@pytest.mark.parametrize('terminal',['success','error','partial'])
@pytest.mark.parametrize('fault',[None,httpx.ReadTimeout,asyncio.CancelledError])
@pytest.mark.parametrize('close_fault',[False,True])
async def test_full_short_actual_observer_owner_equivalence(tmp_path,terminal,fault,close_fault):
    store=_store(tmp_path);execution_id='stream-v4'
    _authorize_offline(store,execution_id)
    observer=FullShortDispatchLedgerObserverV1(store=store,execution_id=execution_id,
        policy=_policy(store),authorized_routes=_routes(),egress_policy=_egress())
    _bind_route_with_capacity(observer,role='planning',lane='primary',provider_id='provider',
        model_id='model-id',route_fingerprint='9'*64)
    raw=(wire(EVENTS+[PING]*3) if terminal=='success' else wire([ERROR]) if terminal=='error' else b'')
    if fault:raw+=b'event: ping\ndata: {'
    stream=Chunks(raw,fault('synthetic') if fault else None,
                  httpx.ReadTimeout('synthetic close') if close_fault else None)
    posts=[]
    async def respond(request):
        posts.append(request)
        return httpx.Response(200,request=request,stream=stream,headers={'content-type':'text/event-stream'})
    adapter=AnthropicAdapter('https://unit.test/v1','synthetic',
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,injected_http_transport=httpx.MockTransport(respond))
    response=failure=None
    try:response=await adapter.complete(_request())
    except BaseException as exc:failure=exc
    finally:await adapter.client.aclose()
    assert len(posts)==1,type(failure).__name__
    owner=adapter._last_stream_outcome_v1
    restored=load_stream_owner_v1(store=store,policy=observer.policy,execution_id=execution_id,ordinal=1)
    assert outcome(owner)==outcome(restored)
    assert owner.snapshot()==restored.snapshot()
    assert owner.raw_durable_prefix==len(raw)
    assert restored.raw==raw
    if terminal=='success':
        assert failure is None
        assert response.input_tokens==17 and response.output_tokens==9
        assert owner.terminal_evidence_durable
    elif terminal=='error':assert isinstance(failure,AnthropicProviderTerminalError)
    else:assert failure is not None
    assert len(list(observer.capture_store.root.glob('*.capture')))==1
    ledger=store.load_ledger(execution_id)
    assert ledger['attempts'][0]['stream_checkpoint_sha256']==owner.checkpoint_sha256
    assert ledger['attempts'][0]['stream_checkpoint_generation']==owner.generation
    # Replay/reload does not authorize another dispatch or alter the nonce.
    with pytest.raises(FullShortExecutionBoundaryError):
        observer.create_anthropic_stream_owner_v1(encoding='utf-8')


def test_checkpoint_pointer_requires_owned_transaction(tmp_path):
    store=_store(tmp_path);execution_id='stream-pointer'
    _authorize_offline(store,execution_id);observer=_observer(store,execution_id)
    from tests.test_full_short_execution import _payload
    observer.before_http_dispatch(method='POST',url='https://unit.test/v1/messages',payload=_payload())
    owner=observer.create_anthropic_stream_owner_v1(encoding='utf-8')
    owner.ingest(wire(EVENTS))
    def tamper(body):
        body['attempts'][0]['stream_checkpoint_sha256']='0'*64
        return body
    with pytest.raises(FullShortExecutionBoundaryError,match='OWNED_TRANSACTION'):
        store.update_ledger(execution_id,tamper)
    checkpoint=owner.checkpoint()
    ack=persist_stream_checkpoint_v1(store=store,policy=observer.policy,
        execution_id=execution_id,ordinal=1,checkpoint=checkpoint)
    assert ack==persist_stream_checkpoint_v1(store=store,policy=observer.policy,
        execution_id=execution_id,ordinal=1,checkpoint=checkpoint)
    bad=deepcopy(checkpoint);bad['owner_id']='other'
    with pytest.raises(FullShortExecutionBoundaryError):
        persist_stream_checkpoint_v1(store=store,policy=observer.policy,
            execution_id=execution_id,ordinal=1,checkpoint=bad)


def test_restore_checks_ledger_seal_before_trusting_old_signed_head(tmp_path):
    store=_store(tmp_path);execution_id='stream-seal'
    _authorize_offline(store,execution_id);observer=_observer(store,execution_id)
    from tests.test_full_short_execution import _payload
    observer.before_http_dispatch(method='POST',url='https://unit.test/v1/messages',payload=_payload())
    owner=observer.create_anthropic_stream_owner_v1(encoding='utf-8')
    old=store.load_ledger(execution_id)['attempts'][0]
    owner.ingest(wire(EVENTS))
    ledger=store.load_ledger(execution_id)
    for key in ('stream_checkpoint_sha256','stream_checkpoint_generation'):
        ledger['attempts'][0][key]=old[key]
    store._replace(store._path(execution_id,'ledger'),ledger)
    with pytest.raises(FullShortExecutionBoundaryError,match='LEDGER_SHA256_MISMATCH'):
        load_stream_owner_v1(store=store,policy=observer.policy,execution_id=execution_id,ordinal=1)


@pytest.mark.parametrize('field,value',[('encoding','ascii'),('usage_projection',True),('require_durability',False)])
def test_checkpoint_contract_cannot_change_between_generations(tmp_path,field,value):
    store=_store(tmp_path);execution_id='stream-contract'
    _authorize_offline(store,execution_id);observer=_observer(store,execution_id)
    from tests.test_full_short_execution import _payload
    observer.before_http_dispatch(method='POST',url='https://unit.test/v1/messages',payload=_payload())
    owner=observer.create_anthropic_stream_owner_v1(encoding='utf-8')
    checkpoint=owner.checkpoint();checkpoint[field]=value
    with pytest.raises(FullShortExecutionBoundaryError,match='CONTRACT_CHANGED'):
        persist_stream_checkpoint_v1(store=store,policy=observer.policy,
            execution_id=execution_id,ordinal=1,checkpoint=checkpoint)
