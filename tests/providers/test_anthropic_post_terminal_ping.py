"""Protocol invariants across complete semantic messages and transport pings."""
from copy import deepcopy
import json

import httpx
import pytest

from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.provider_response_capture import (
    ProviderResponseCaptureError, extract_provider_reported_actual_usage_v1,
    provider_protocol_input_has_terminal_bytes_v1,
)
from novel_flywheel.providers.anthropic import (
    AnthropicAdapter, AnthropicProviderTerminalError,
    AnthropicStreamIncompleteError, AnthropicStreamProtocolError,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.production_incidents import classify_production_failure


def wire(events):
    return ''.join('event: '+e['type']+'\ndata: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events).encode()


def semantic_events(topology='text', stop='end_turn'):
    result=[{'type':'message_start','message':{'id':'synthetic-ping-fixture','usage':{'input_tokens':2,'cache_creation_input_tokens':137302,'cache_read_input_tokens':0,'output_tokens':1}}}]
    blocks={
        'text':[{'type':'text','text':''}],
        'multitext':[{'type':'text','text':'甲'},{'type':'text','text':'乙'}],
        'thinking':[{'type':'thinking','thinking':'private','signature':'synthetic'}],
        'redacted':[{'type':'redacted_thinking','data':'opaque'}],
        'tool':[{'type':'tool_use','id':'call-safe','name':'receipt','input':{}}],
        'schema':[{'type':'tool_use','id':'schema-safe','name':'receipt','input':{'unseen_receipt_tree':{'closure_nodes':[{'accepted':True}]}}}],
        'mixed':[{'type':'thinking','thinking':'analysis','signature':'opaque'},{'type':'text','text':'ending'}],
    }[topology]
    for index,block in enumerate(blocks):
        result.append({'type':'content_block_start','index':index,'content_block':block})
        if topology=='text':
            result.append({'type':'ping'})
            for n in range(15):
                result.append({'type':'content_block_delta','index':index,'delta':{'type':'text_delta','text':f'事件{n}完成。'}})
        if topology=='tool':
            result.append({'type':'content_block_delta','index':index,'delta':{'type':'input_json_delta','partial_json':json.dumps({'new_archive_frame':{'owners':[1,2],'complete':True}})}})
        result.append({'type':'content_block_stop','index':index})
    result += [{'type':'message_delta','delta':{'stop_reason':stop},'usage':{'input_tokens':2,'cache_creation_input_tokens':137302,'cache_read_input_tokens':0,'output_tokens':64}}, {'type':'message_stop'}]
    return result


def replay(events):
    return AnthropicAdapter.replay_protocol_input_bytes_v1(wire(events),content_type='text/event-stream')


def test_terminal_boundary_incident_has_implementable_capture_recovery():
    incident=classify_production_failure(
        'anthropic_sse_protocol_invalid.anthropic_sse_event_after_message_stop',
        workflow='short',stage='polish')
    assert incident is not None
    assert incident['incident_family']=='provider.semantic_transport_terminal_boundary'
    assert 'immutable capture' in incident['known_resolution']
    typed=AnthropicStreamProtocolError('ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP')
    with_typed=classify_production_failure('safe typed failure',workflow='short',stage='polish',failure=typed.reliability_failure)
    assert with_typed['incident_family']==incident['incident_family']
    assert with_typed['incident_key']==incident['incident_key']


@pytest.mark.parametrize('topology',['text','multitext','thinking','redacted','tool','schema','mixed'])
@pytest.mark.parametrize('ping_count',[0,1,3,19])
def test_ping_preserves_complete_message_and_usage(topology,ping_count):
    items=semantic_events(topology)
    original=deepcopy(items)
    before=replay(items)
    # Even arbitrary extension fields on a ping have no semantic authority.
    ping={'type':'ping','usage':{'input_tokens':9999999,'output_tokens':9999999},'delta':{'stop_reason':'max_tokens'},'message':{'id':'poison'},'content':[{'type':'text','text':'poison'}]}
    after=replay(items+[ping]*ping_count)
    assert items==original
    left,right=before.model_dump(),after.model_dump()
    for value in (left,right):
        value['provider_state'].pop('POST_TERMINAL_PING_COUNT',None)
        value['provider_state'].pop('POST_TERMINAL_PING_IGNORED_COUNT',None)
    assert left==right
    assert after.provider_state['POST_TERMINAL_PING_COUNT']==ping_count
    assert after.provider_state['POST_TERMINAL_PING_IGNORED_COUNT']==ping_count
    receipt=extract_provider_reported_actual_usage_v1(wire(items+[ping]*ping_count),protocol='anthropic',content_type='text/event-stream')
    assert (after.input_tokens,after.output_tokens)==(receipt['input_tokens'],receipt['output_tokens'])==(137304,64)
    assert receipt['usage_record_count']==2


@pytest.mark.parametrize('kind',['message_start','message_delta','content_block_start','content_block_delta','content_block_stop','message_stop','future_event'])
def test_post_terminal_semantics_rejected(kind):
    items=semantic_events()+[{'type':'ping'},{'type':kind,'usage':{'input_tokens':999999,'output_tokens':8888}},{'type':'ping'}]
    with pytest.raises(AnthropicStreamProtocolError,match='EVENT_AFTER_MESSAGE_STOP'):
        replay(items)
    with pytest.raises(ProviderResponseCaptureError):
        extract_provider_reported_actual_usage_v1(wire(items),protocol='anthropic',content_type='text/event-stream')


@pytest.mark.parametrize('suffix',[[],[{'type':'ping'}]])
def test_post_terminal_error_is_typed_and_never_usage(suffix):
    items=semantic_events()+[{'type':'error','error':{'type':'overloaded_error'}}]+suffix
    with pytest.raises(AnthropicProviderTerminalError) as caught:
        replay(items)
    assert caught.value.error_type=='overloaded_error'
    assert caught.value.reliability_failure.code=='anthropic_provider_terminal_error'
    with pytest.raises(ProviderResponseCaptureError):
        extract_provider_reported_actual_usage_v1(wire(items),protocol='anthropic',content_type='text/event-stream')


def test_preterminal_ping_positions_and_cumulative_updates():
    items=semantic_events('multitext')
    interspersed=[{'type':'ping'}]
    for item in items:
        interspersed.append(item)
        if item['type']!='message_stop':
            interspersed.append({'type':'ping'})
    assert replay(interspersed).model_dump()==replay(items).model_dump()
    items[-2:-2]=[{'type':'message_delta','usage':{'output_tokens':3},'delta':{}}]
    assert replay(items+[{'type':'ping'}]).output_tokens==64


@pytest.mark.parametrize('topology',['text','thinking','tool','schema'])
def test_max_tokens_complete_message_unchanged(topology):
    result=replay(semantic_events(topology,'max_tokens')+[{'type':'ping'}])
    assert result.finish_reason=='max_tokens'
    assert result.provider_state['transport_complete'] is True


def test_incomplete_and_non_anthropic_terminal_rules_unchanged():
    items=semantic_events()[:-1]+[{'type':'ping'}]
    with pytest.raises(AnthropicStreamIncompleteError):
        replay(items)
    assert not provider_protocol_input_has_terminal_bytes_v1(wire(items),content_type='text/event-stream')
    for terminal in ['response.completed','response.failed','response.incomplete']:
        assert not provider_protocol_input_has_terminal_bytes_v1(wire([{'type':terminal},{'type':'ping'}]),content_type='text/event-stream')
    raw=wire(semantic_events()+[{'type':'ping'}])[:-1]
    assert not provider_protocol_input_has_terminal_bytes_v1(raw,content_type='text/event-stream')
    # V4: the complete message prefix owns usage; an unfinished tail ping is
    # diagnostic data and cannot erase its cumulative counters.
    tail_usage=extract_provider_reported_actual_usage_v1(raw,protocol='anthropic',content_type='text/event-stream')
    complete_usage=extract_provider_reported_actual_usage_v1(wire(semantic_events()),protocol='anthropic',content_type='text/event-stream')
    for field in ('input_tokens','output_tokens','source_topologies','usage_record_count'):
        assert tail_usage[field]==complete_usage[field]
    assert tail_usage['provider_entity_sha256']!=complete_usage['provider_entity_sha256']


class InterruptedStream(httpx.AsyncByteStream):
    def __init__(self,raw):
        self.raw=raw
    async def __aiter__(self):
        for offset in range(0,len(self.raw),23):
            yield self.raw[offset:offset+23]
        raise httpx.ReadTimeout('synthetic iterator timeout')
    async def aclose(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize('ping_count',[0,1,3])
async def test_interrupted_transport_after_complete_pings_uses_one_local_replay(ping_count):
    raw=wire(semantic_events()+[{'type':'ping'}]*ping_count)
    adapter=AnthropicAdapter('https://offline.invalid/v1','offline-secret-never-in-payload',transport_policy=SingleDispatchTransportPolicyV1.phase_b())
    await adapter.client.aclose()
    calls=[]
    async def respond(request):
        calls.append(request)
        return httpx.Response(200,stream=InterruptedStream(raw),headers={'content-type':'text/event-stream'},request=request)
    adapter.client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        response=await adapter.complete(ModelRequest(model='synthetic',messages=[Message(role='user',content='synthetic authority')],max_output_tokens=128))
    finally:
        await adapter.client.aclose()
    assert len(calls)==adapter.transport_attempt_snapshot()['http_post_attempts']==1
    assert response.provider_state['POST_TERMINAL_PING_COUNT']==ping_count
    assert response.output_tokens==64
