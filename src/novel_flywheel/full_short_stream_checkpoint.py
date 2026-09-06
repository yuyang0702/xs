"""Persistence port for the shared owner using existing Full Short authority."""
from __future__ import annotations
import base64
from copy import deepcopy
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from novel_flywheel.anthropic_durable_stream import (
    DurableAnthropicStreamV1, StreamDurableAckV1, digest,
)


def _identity(store, execution_id, ordinal, attempt, policy):
    return {'schema': 'FullShortStreamCheckpointEnvelopeV1',
            'execution_id': execution_id, 'ordinal': ordinal,
            'physical_attempt_id': attempt['physical_attempt_id'],
            'outbound_request_bytes_sha256': attempt.get('outbound_request_bytes_sha256'),
            'route_fingerprint': attempt.get('route_fingerprint'),
            'capacity_plan_sha256': attempt.get('capacity_plan_sha256'),
            'capacity_admission_receipt_sha256': attempt.get('capacity_admission_receipt_sha256'),
            'policy_sha256': policy['policy_sha256'],
            'store_root_sha256': store.store_root_sha256}


def _path(store, execution_id, ordinal, checkpoint_sha256):
    from novel_flywheel.full_short_execution import _require, _HEX64
    _require(type(ordinal) is int and ordinal > 0 and
             isinstance(checkpoint_sha256,str) and _HEX64.fullmatch(checkpoint_sha256),
             'STREAM_CHECKPOINT_IDENTITY_INVALID')
    return store.root / f'{store._key(execution_id)}.stream-{ordinal}-{checkpoint_sha256}.json'


_DELTA_SCHEMA = 'FullShortStreamCheckpointDeltaEnvelopeV2'


def _signed_body(store, envelope, identity):
    from novel_flywheel.full_short_execution import _require, FullShortExecutionBoundaryError
    from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes
    _require(isinstance(envelope,dict) and envelope.get('identity') == identity,
             'STREAM_CHECKPOINT_IDENTITY_INVALID')
    body=deepcopy(envelope)
    try:
        signature=bytes.fromhex(body.pop('signature'))
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(store.capture_attestation_public_key)).verify(
            signature,canonical_json_bytes(body))
    except (InvalidSignature,ValueError,TypeError,KeyError) as exc:
        raise FullShortExecutionBoundaryError('STREAM_CHECKPOINT_SIGNATURE_INVALID') from exc
    return body


def _metadata(checkpoint):
    metadata=deepcopy({key:value for key,value in checkpoint.items() if key!='journal'})
    metadata['framer'].pop('line_hex',None)
    return metadata


def _summary(checkpoint, checkpoint_hash):
    return {'hash':checkpoint_hash,'metadata':_metadata(checkpoint),
            'journal_count':len(checkpoint['journal']),
            'journal_sha256':digest(checkpoint['journal'])}


def _require_successor(checkpoint, previous):
    from novel_flywheel.full_short_execution import _require
    _require(all(checkpoint[key]==previous[key] for key in
                 ('encoding','usage_projection','require_durability','schema','owner_id')),
             'STREAM_CHECKPOINT_CONTRACT_CHANGED')
    for key in ('raw_prefix','framed_prefix','semantic_prefix'):
        _require(checkpoint[key]>=previous[key],'STREAM_CHECKPOINT_PREFIX_REGRESSION')
    for key in ('terminal_identity','success_terminal_identity','provider_error_terminal_identity'):
        _require(previous[key] is None or previous[key]==checkpoint[key],
                 'STREAM_CHECKPOINT_TERMINAL_CHANGED')


def _verify(store, envelope, identity, expected_sha256):
    """Authenticate the selected immutable chain and inflate one V1 checkpoint.

    Ancestors contain only their own journal suffix. Their signed declared
    hashes link the chain; the final reconstructed full checkpoint is hashed
    once, then the caller performs semantic restoration once. Legacy full
    signed checkpoints remain valid bases for a V2 suffix chain.
    """
    from novel_flywheel.full_short_execution import _require
    selected_hash=expected_sha256
    chain=[];seen=set();journal=[];previous=None;previous_hash=None
    while True:
        _require(expected_sha256 not in seen,'STREAM_CHECKPOINT_CHAIN_INVALID')
        seen.add(expected_sha256)
        body=_signed_body(store,envelope,identity)
        if body.get('schema')!=_DELTA_SCHEMA:
            checkpoint=body['checkpoint']
            _require(digest(checkpoint)==expected_sha256,'STREAM_CHECKPOINT_HASH_INVALID')
            journal=deepcopy(checkpoint['journal'])
            previous=checkpoint;previous_hash=expected_sha256
            break
        _require(body.get('checkpoint_sha256')==expected_sha256,
                 'STREAM_CHECKPOINT_HASH_INVALID')
        metadata=body['checkpoint_metadata']
        _require(type(body.get('journal_count')) is int and body['journal_count']>=0
                 and isinstance(body.get('journal_suffix'),list),
                 'STREAM_CHECKPOINT_SCHEMA_INVALID')
        chain.append(body)
        expected_sha256=metadata['parent_sha256']
        if expected_sha256 is None:
            break
        envelope=json.loads(_path(store,identity['execution_id'],identity['ordinal'],expected_sha256).read_bytes())
    for body in reversed(chain):
        metadata=body['checkpoint_metadata']
        _require(metadata['parent_sha256']==previous_hash and
                 metadata['generation']==(previous['generation']+1 if previous else 1),
                 'STREAM_CHECKPOINT_CHAIN_INVALID')
        if previous:
            _require_successor(metadata,previous)
        journal.extend(deepcopy(body['journal_suffix']))
        _require(len(journal)==body['journal_count'],'STREAM_CHECKPOINT_JOURNAL_REGRESSION')
        previous=metadata;previous_hash=body['checkpoint_sha256']
    if not chain:
        return previous
    checkpoint=deepcopy(previous)
    checkpoint['journal']=journal
    # The current physical line is exactly the raw suffix after the last CR
    # or LF. It is independent of semantic decoding and control records.
    raw=b''.join(base64.b64decode(item['bytes'],validate=True)
                 for item in journal if 'bytes' in item)
    checkpoint['framer']['line_hex']=raw[max(raw.rfind(b'\r'),raw.rfind(b'\n'))+1:].hex()
    _require(digest(journal)==chain[0]['journal_sha256'],'STREAM_CHECKPOINT_JOURNAL_INVALID')
    _require(digest(checkpoint)==selected_hash,'STREAM_CHECKPOINT_HASH_INVALID')
    return checkpoint


def _matches_submitted(store, envelope, identity, checkpoint, checkpoint_hash):
    """An owner-issued full checkpoint can verify a selected/orphan V2 write
    without replaying or loading its ancestors. No semantic state is cached.
    """
    from novel_flywheel.full_short_execution import _require
    body=_signed_body(store,envelope,identity)
    if body.get('schema')!=_DELTA_SCHEMA:
        _require(body.get('checkpoint')==checkpoint,'STREAM_CHECKPOINT_IDEMPOTENCE_INVALID')
        return
    suffix=body['journal_suffix']
    count=body['journal_count']
    _require(body['checkpoint_sha256']==checkpoint_hash and
             body['checkpoint_metadata']==_metadata(checkpoint) and
             count==len(checkpoint['journal']) and
             body['journal_sha256']==digest(checkpoint['journal']) and
             len(suffix)<=count and suffix==checkpoint['journal'][count-len(suffix):],
             'STREAM_CHECKPOINT_IDEMPOTENCE_INVALID')


def _load_bound_ledger(store, execution_id, policy):
    from novel_flywheel.full_short_execution import _require
    ledger=store._verify_seal(store.load_ledger(execution_id),
        domain='novel-flywheel-full-short-dispatch-ledger-v1',
        field='ledger_sha256',reason='LEDGER_SHA256_MISMATCH')
    _require(ledger.get('execution_id')==execution_id and
             ledger.get('policy_sha256')==policy['policy_sha256'] and
             ledger.get('store_root_sha256')==store.store_root_sha256,
             'STREAM_CHECKPOINT_LEDGER_BINDING_INVALID')
    return ledger


def persist_stream_checkpoint_v1(*, store, policy, execution_id, ordinal, checkpoint):
    """Untrusted submission retains complete semantic replay validation."""
    return _persist_stream_checkpoint_v1(store=store,policy=policy,
        execution_id=execution_id,ordinal=ordinal,checkpoint=checkpoint)


def _persist_stream_checkpoint_v1(*, store, policy, execution_id, ordinal, checkpoint,
                                  submitted_owner=None, metadata_cache=None):
    from novel_flywheel.full_short_execution import (
        _require, _seal, _now, _validate_ledger_mutation_v1,
    )
    from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes
    validated=store._verify_store_binding(policy)
    checkpoint=deepcopy(checkpoint)
    checkpoint_hash=digest(checkpoint)
    with store._locked():
        _require(not store._path(execution_id,'completion').exists(),'EXECUTION_ALREADY_COMPLETED')
        ledger=store._verify_seal(store._read(execution_id,'ledger'),
            domain='novel-flywheel-full-short-dispatch-ledger-v1',
            field='ledger_sha256',reason='LEDGER_SHA256_MISMATCH')
        _require(ledger['policy_sha256']==validated['policy_sha256'],'EXECUTION_CHAIN_POLICY_MISMATCH')
        _require(type(ordinal) is int and 0 < ordinal <= len(ledger['attempts']),
                 'STREAM_CHECKPOINT_ATTEMPT_INVALID')
        attempt=ledger['attempts'][ordinal-1]
        identity=_identity(store,execution_id,ordinal,attempt,validated)
        _require(checkpoint['owner_id']==digest(identity),'STREAM_CHECKPOINT_OWNER_MISMATCH')
        # Identity rejection precedes semantic rehydration; storage never
        # interprets another physical attempt's journal as this attempt.
        if submitted_owner is None:
            DurableAnthropicStreamV1.restore(checkpoint,expected_sha256=checkpoint_hash)
        else:
            # This private capability is created only by the factory below.
            # Its closure binds the one authoritative owner, not a verifier
            # reducer. Accept exactly its currently pending transaction.
            submitted=submitted_owner._pending_checkpoint or submitted_owner.checkpoint()
            _require(submitted_owner.owner_id==checkpoint['owner_id'] and checkpoint==submitted,
                     'STREAM_CHECKPOINT_NOT_OWNER_SUBMITTED')
        path=_path(store,execution_id,ordinal,checkpoint_hash)
        previous_hash=attempt.get('stream_checkpoint_sha256')
        previous_generation=attempt.get('stream_checkpoint_generation',0)
        if previous_hash==checkpoint_hash:
            _matches_submitted(store,json.loads(path.read_bytes()),identity,checkpoint,checkpoint_hash)
            if metadata_cache is not None:
                metadata_cache.clear();metadata_cache.update(_summary(checkpoint,checkpoint_hash))
            return StreamDurableAckV1.for_checkpoint(checkpoint)
        _require(checkpoint['parent_sha256']==previous_hash and
                 checkpoint['generation']==previous_generation+1,'STREAM_CHECKPOINT_STALE')
        previous_count=0
        if previous_hash:
            if metadata_cache is not None and metadata_cache.get('hash')==previous_hash:
                summary=metadata_cache
            else:
                previous=_verify(store,json.loads(_path(store,execution_id,ordinal,previous_hash).read_bytes()),identity,previous_hash)
                summary=_summary(previous,previous_hash)
            previous_count=summary['journal_count']
            _require(len(checkpoint['journal'])>=previous_count and
                     digest(checkpoint['journal'][:previous_count])==summary['journal_sha256'],
                     'STREAM_CHECKPOINT_JOURNAL_REGRESSION')
            _require_successor(checkpoint,summary['metadata'])
        _require(store._capture_attestation_private_key is not None,
                 'CAPTURE_ATTESTATION_SIGNER_UNAVAILABLE_AFTER_RESTART')
        envelope={'schema':_DELTA_SCHEMA,'identity':identity,
                  'checkpoint_sha256':checkpoint_hash,
                  'checkpoint_metadata':_metadata(checkpoint),
                  'journal_count':len(checkpoint['journal']),
                  'journal_sha256':digest(checkpoint['journal']),
                  'journal_suffix':deepcopy(checkpoint['journal'][previous_count:])}
        envelope['signature']=store._capture_attestation_private_key.sign(canonical_json_bytes(envelope)).hex()
        if path.exists():
            _matches_submitted(store,json.loads(path.read_bytes()),identity,checkpoint,checkpoint_hash)
        else:
            store._exclusive_write(path,envelope)
        before=deepcopy(ledger);before.pop('ledger_sha256',None)
        after=deepcopy(before)
        after['attempts'][ordinal-1].update(stream_checkpoint_sha256=checkpoint_hash,
                                         stream_checkpoint_generation=checkpoint['generation'])
        _validate_ledger_mutation_v1(before,after,mutation_kind='STREAM_CHECKPOINT')
        after['updated_at']=_now()
        store._replace(store._path(execution_id,'ledger'),_seal(
            'novel-flywheel-full-short-dispatch-ledger-v1',after,'ledger_sha256'))
        if metadata_cache is not None:
            metadata_cache.clear();metadata_cache.update(_summary(checkpoint,checkpoint_hash))
        return StreamDurableAckV1.for_checkpoint(checkpoint)


def create_stream_owner_v1(*, store, policy, execution_id, ordinal, encoding='utf-8'):
    from novel_flywheel.full_short_execution import _require
    validated=store._verify_store_binding(policy)
    ledger=_load_bound_ledger(store,execution_id,validated)
    _require(type(ordinal) is int and 0 < ordinal <= len(ledger['attempts']),
             'STREAM_CHECKPOINT_ATTEMPT_INVALID')
    attempt=ledger['attempts'][ordinal-1]
    _require(not attempt.get('stream_checkpoint_sha256'),'STREAM_OWNER_ALREADY_EXISTS')
    identity=_identity(store,execution_id,ordinal,attempt,validated)
    metadata_cache={}
    owner=DurableAnthropicStreamV1(owner_id=digest(identity),encoding=encoding)
    def submit(checkpoint):
        return _persist_stream_checkpoint_v1(store=store,policy=policy,
            execution_id=execution_id,ordinal=ordinal,checkpoint=checkpoint,
            submitted_owner=owner,metadata_cache=metadata_cache)
    owner.sink=submit
    owner.require_durability=True
    owner.commit()
    return owner


def load_stream_owner_v1(*, store, policy, execution_id, ordinal):
    """Read-only restore. No signer, observer claim, nonce or redispatch."""
    from novel_flywheel.full_short_execution import _require
    validated=store._verify_store_binding(policy)
    ledger=_load_bound_ledger(store,execution_id,validated)
    _require(type(ordinal) is int and 0 < ordinal <= len(ledger['attempts']),
             'STREAM_CHECKPOINT_ATTEMPT_INVALID')
    attempt=ledger['attempts'][ordinal-1]
    identity=_identity(store,execution_id,ordinal,attempt,validated)
    checkpoint_hash=attempt.get('stream_checkpoint_sha256')
    checkpoint=_verify(store,json.loads(_path(store,execution_id,ordinal,checkpoint_hash).read_bytes()),
                       identity,checkpoint_hash)
    _require(checkpoint['generation']==attempt['stream_checkpoint_generation'],
             'STREAM_CHECKPOINT_GENERATION_MISMATCH')
    return DurableAnthropicStreamV1.restore(checkpoint,expected_sha256=checkpoint_hash)
