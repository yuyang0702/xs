"""Regression contract for compact signed incremental sidecars."""
from copy import deepcopy
import json

import httpx
import pytest

from tests.test_full_short_execution import _store,_authorize_offline,_observer,_payload
from tests.providers.test_anthropic_durable_stream_v4 import EVENTS,ERROR,PING,wire,outcome
from novel_flywheel.anthropic_durable_stream import DurableAnthropicStreamV1,digest
from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError
from novel_flywheel.full_short_stream_checkpoint import load_stream_owner_v1,persist_stream_checkpoint_v1
from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes


def setup_owner(tmp_path,name='delta-v2'):
    store=_store(tmp_path);_authorize_offline(store,name)
    observer=_observer(store,name)
    observer.before_http_dispatch(method='POST',url='https://unit.test/v1/messages',payload=_payload())
    owner=observer.create_anthropic_stream_owner_v1(encoding='utf-8')
    assert owner.persistence_failure_count==0
    return store,observer,owner,name


def reload_owner(store,observer,name):
    return load_stream_owner_v1(store=store,policy=observer.policy,execution_id=name,ordinal=1)


def submit(store,observer,name,checkpoint):
    return persist_stream_checkpoint_v1(store=store,policy=observer.policy,
        execution_id=name,ordinal=1,checkpoint=checkpoint)


@pytest.mark.parametrize('size',[37,257,4096])
def test_storage_keeps_each_journal_record_once_and_omits_growing_partial_line(tmp_path,size):
    store,observer,owner,name=setup_owner(tmp_path)
    # A growing unclosed JSON line exposes accidental repeated line_hex.
    raw=b'data: {"type":"ping","payload":"'+('中文🙂'*500).encode()
    for start in range(0,len(raw),size):owner.ingest(raw[start:start+size])
    owner.finish(httpx.ReadTimeout('synthetic'))
    assert owner.persistence_failure_count==0
    envelopes=[json.loads(path.read_bytes()) for path in store.root.glob('*.stream-1-*.json')]
    assert len(envelopes)==owner.generation
    assert sum(len(item['journal_suffix']) for item in envelopes)==len(owner.journal)
    assert sum(sum(len(json.dumps(record)) for record in item['journal_suffix']) for item in envelopes)==sum(len(json.dumps(record)) for record in owner.journal)
    assert all('journal' not in item['checkpoint_metadata'] for item in envelopes)
    assert all('line_hex' not in item['checkpoint_metadata']['framer'] for item in envelopes)
    metadata_bytes=sum(len(json.dumps({key:value for key,value in item.items() if key!='journal_suffix'}).encode()) for item in envelopes)
    assert metadata_bytes<4000*len(envelopes)
    restored=reload_owner(store,observer,name)
    assert restored.raw==raw
    assert restored.framer.snapshot()==owner.framer.snapshot()
    assert restored.snapshot()==owner.snapshot()


def test_live_submission_never_full_replays_but_restart_and_public_submission_do(tmp_path,monkeypatch):
    calls=[];original=DurableAnthropicStreamV1.restore
    def watch(cls,*args,**kwargs):
        calls.append(kwargs.get('expected_sha256'))
        return original(*args,**kwargs)
    monkeypatch.setattr(DurableAnthropicStreamV1,'restore',classmethod(watch))
    store,observer,owner,name=setup_owner(tmp_path)
    for event in EVENTS+[PING]:owner.ingest(wire([event]))
    owner.finish()
    assert calls==[]
    restored=reload_owner(store,observer,name)
    assert outcome(restored)==outcome(owner)
    assert len(calls)==1
    submit(store,observer,name,owner.checkpoint())
    assert len(calls)==2


def test_private_submit_capability_rejects_other_checkpoint_and_public_replays(tmp_path):
    store,observer,owner,name=setup_owner(tmp_path)
    checkpoint=owner.checkpoint();checkpoint['state']['primary_cause']='forged'
    with pytest.raises(FullShortExecutionBoundaryError,match='NOT_OWNER_SUBMITTED'):
        owner.sink(checkpoint)
    with pytest.raises(Exception,match='STATE_MISMATCH'):
        submit(store,observer,name,checkpoint)
    assert store.load_ledger(name)['attempts'][0]['stream_checkpoint_generation']==1


@pytest.mark.parametrize('before_replace',[True,False])
def test_orphan_or_lost_ack_reuses_identical_delta(tmp_path,monkeypatch,before_replace):
    store,observer,owner,name=setup_owner(tmp_path)
    original=store._replace;injected=[]
    def replace(path,value):
        relevant=path==store._path(name,'ledger') and not injected
        if relevant and before_replace:
            injected.append(True);raise OSError('synthetic before head selection')
        original(path,value)
        if relevant:
            injected.append(True);raise OSError('synthetic after head selection')
    monkeypatch.setattr(store,'_replace',replace)
    owner.ingest(wire(EVENTS));owner.finish()
    assert injected and owner.persistence_failure_count==0
    assert len(list(store.root.glob('*.stream-1-*.json')))==owner.generation
    assert reload_owner(store,observer,name).snapshot()==owner.snapshot()


def test_signed_legacy_full_checkpoint_can_anchor_new_delta_chain(tmp_path):
    store,observer,owner,name=setup_owner(tmp_path)
    submitted=[];sink=owner.sink
    def recording(checkpoint):
        submitted.append(deepcopy(checkpoint));return sink(checkpoint)
    owner.sink=recording
    owner.ingest(wire(EVENTS[:2]));checkpoint=submitted[-1]
    path=next(store.root.glob('*'+owner.checkpoint_sha256+'.json'))
    current=json.loads(path.read_bytes())
    legacy={'identity':current['identity'],'checkpoint':checkpoint}
    legacy['signature']=store._capture_attestation_private_key.sign(canonical_json_bytes(legacy)).hex()
    # Test-only fixture conversion; production does not rewrite evidence.
    path.write_bytes(canonical_json_bytes(legacy))
    assert reload_owner(store,observer,name).raw==owner.raw
    owner.ingest(wire(EVENTS[2:]+[PING]));owner.finish()
    assert owner.persistence_failure_count==0
    assert reload_owner(store,observer,name).snapshot()==owner.snapshot()


def test_restart_authenticates_ancestor_suffix_not_only_selected_head(tmp_path):
    store,observer,owner,name=setup_owner(tmp_path)
    owner.ingest(wire(EVENTS[:2]))
    path=next(store.root.glob('*'+owner.checkpoint_sha256+'.json'))
    owner.ingest(wire(EVENTS[2:]));owner.finish()
    ancestor=json.loads(path.read_bytes())
    ancestor['journal_suffix'][0]['bytes']='Zm9yZ2Vk'
    path.write_bytes(canonical_json_bytes(ancestor))
    with pytest.raises(FullShortExecutionBoundaryError,match='SIGNATURE_INVALID'):
        reload_owner(store,observer,name)


@pytest.mark.parametrize('newline',['\n','\r','\r\n'])
def test_selected_partial_frame_reconstructs_exact_cr_lf_utf8_line_state(tmp_path,newline):
    store,observer,owner,name=setup_owner(tmp_path)
    raw=wire(EVENTS+[PING],newline)+b'data: "'+('汉🙂').encode()[:5]
    # End on a split UTF-8 codepoint, with every CR/LF convention exercised.
    for offset in range(0,len(raw),31):owner.ingest(raw[offset:offset+31])
    restored=reload_owner(store,observer,name)
    assert restored.framer.snapshot()==owner.framer.snapshot()
    assert restored.raw==owner.raw
    assert restored.snapshot()==owner.snapshot()


def test_public_valid_replacement_of_old_journal_prefix_is_rejected(tmp_path):
    store,observer,owner,name=setup_owner(tmp_path)
    owner.ingest(wire(EVENTS))
    other=DurableAnthropicStreamV1(owner_id=owner.owner_id,require_durability=True)
    alternate=deepcopy(EVENTS);alternate[0]['message']['id']='different-valid-id'
    other.ingest(wire(alternate),persist=False)
    checkpoint=other.checkpoint();checkpoint['generation']=owner.generation+1
    checkpoint['parent_sha256']=owner.checkpoint_sha256
    with pytest.raises(FullShortExecutionBoundaryError,match='JOURNAL_REGRESSION'):
        submit(store,observer,name,checkpoint)
