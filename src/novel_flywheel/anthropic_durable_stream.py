"""Response-only incremental SSE and a single checkpoint/terminal owner.

Checkpoint data is private capture material. Public projections contain only
hashes, typed causes and counts. Restoring never dispatches or authorizes I/O.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Callable

import httpx

from novel_flywheel.anthropic_stream import (
    AnthropicStream, AnthropicProviderTerminalError, AnthropicStreamProtocolError,
    CaptureState, Event, InvalidFrame, SUCCESS_STATES, ERROR_STATES,
    _decode_complete_sse,
)
from novel_flywheel.provider_stream_error import ProviderErrorEventV1


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


class FrameState(StrEnum):
    EMPTY = 'FRAME_EMPTY'
    PARTIAL = 'FRAME_PARTIAL'
    COMPLETE = 'FRAME_COMPLETE_NOT_DECODED'
    DECODED = 'FRAME_DECODED'
    CLOSED = 'STREAM_CLOSED'


class IncrementalSSEFramerV1:
    """CR is immediately a line boundary; its following LF is swallowed.

    UTF-8 codepoints cannot contain CR/LF bytes. Decode only complete frames;
    retain exact pending bytes including a split codepoint and CRLF state.
    """
    def __init__(self):
        self.raw = bytearray()
        self.frame_start = 0
        self.line = bytearray()
        self.skip_lf = False
        self.ready: list[tuple[int, int]] = []
        self.state = FrameState.EMPTY
        self.framed_prefix = 0

    def receive(self, data: bytes) -> None:
        if self.state == FrameState.CLOSED:
            raise AnthropicStreamProtocolError('STREAM_BYTES_AFTER_CLOSE')
        if not isinstance(data, bytes):
            raise TypeError('stream bytes required')
        for byte in data:
            self.raw.append(byte)
            if self.skip_lf:
                self.skip_lf = False
                if byte == 10:
                    # This LF belongs to the preceding CR delimiter.
                    if self.frame_start == len(self.raw) - 1:
                        self.frame_start += 1
                    continue
            if byte in (10, 13):
                self.skip_lf = byte == 13
                if not self.line:
                    end = len(self.raw)
                    self.ready.append((self.frame_start, end))
                    self.frame_start = end
                    self.framed_prefix = end
                self.line.clear()
            else:
                self.line.append(byte)
        self.state = (FrameState.COMPLETE if self.ready else
                      FrameState.PARTIAL if self.pending else FrameState.EMPTY)

    @property
    def pending(self) -> bytes:
        return bytes(self.raw[self.frame_start:])

    def pop(self) -> tuple[bytes, int, int] | None:
        if not self.ready:
            return None
        start, end = self.ready.pop(0)
        if self.state != FrameState.CLOSED:
            self.state = (FrameState.COMPLETE if self.ready else
                          FrameState.PARTIAL if self.pending else FrameState.DECODED)
        return bytes(self.raw[start:end]), start, end

    def close(self) -> None:
        self.state = FrameState.CLOSED

    def snapshot(self) -> dict:
        return {'state': self.state.value, 'raw_length': len(self.raw),
                'frame_start': self.frame_start, 'line_hex': bytes(self.line).hex(),
                'skip_lf': self.skip_lf, 'ready': [list(x) for x in self.ready],
                'framed_prefix': self.framed_prefix}


@dataclass(frozen=True)
class StreamDurableAckV1:
    owner_id: str
    generation: int
    checkpoint_sha256: str
    raw_durable_prefix: int
    framed_event_durable_prefix: int
    semantic_accepted_prefix: int
    terminal_event_identity: str | None

    @classmethod
    def for_checkpoint(cls, checkpoint: dict) -> 'StreamDurableAckV1':
        return cls(checkpoint['owner_id'], checkpoint['generation'], digest(checkpoint),
                   checkpoint['raw_prefix'], checkpoint['framed_prefix'],
                   checkpoint['semantic_prefix'], checkpoint['terminal_identity'])


def transport_event(exc: BaseException | None) -> Event:
    if exc is None:
        return Event.EOF
    if isinstance(exc, asyncio.CancelledError):
        return Event.CANCELLATION
    if isinstance(exc, httpx.TimeoutException):
        return Event.TIMEOUT
    return Event.TRANSPORT_EXCEPTION


# Explicit source-defined public capture reasons; formatting alone is not authority.
_CAPTURE_REASONS = frozenset({
    'FULL_SHORT_TRANSPORT_EVIDENCE_STATE_UNKNOWN',
    'PROVIDER_REPORTED_USAGE_ALIAS_CONFLICT',
    'PROVIDER_REPORTED_USAGE_EVENT_AFTER_MESSAGE_STOP',
    'PROVIDER_REPORTED_USAGE_FIELD_INVALID',
    'PROVIDER_REPORTED_USAGE_INCOMPLETE',
    'PROVIDER_REPORTED_USAGE_INPUT_CONFLICT',
    'PROVIDER_REPORTED_USAGE_MISSING',
    'PROVIDER_REPORTED_USAGE_NOT_POSITIVE',
    'PROVIDER_REPORTED_USAGE_OBJECT_INVALID',
    'PROVIDER_REPORTED_USAGE_OUTPUT_NON_MONOTONIC',
    'PROVIDER_REPORTED_USAGE_PROTOCOL_UNSUPPORTED',
    'PROVIDER_REPORTED_USAGE_PROVIDER_ERROR',
    'PROVIDER_REPORTED_USAGE_SSE_TERMINAL_MISSING',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_DOMAIN_INVALID',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_ENVELOPE_CORRUPT',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_EXTERNAL_ANCHORS_REQUIRED',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_EXTERNAL_ANCHOR_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_HTTP_CLASSIFICATION_REQUIRED',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_IDENTITY_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_LENGTH_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_SCHEMA_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_AUDIT_SHA256_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_BYTES_REQUIRED',
    'PROVIDER_RESPONSE_CAPTURE_DOMAIN_INVALID',
    'PROVIDER_RESPONSE_CAPTURE_DUPLICATE',
    'PROVIDER_RESPONSE_CAPTURE_DURABLE_WRITE_NO_PROGRESS',
    'PROVIDER_RESPONSE_CAPTURE_EXECUTION_ALREADY_COMPLETED',
    'PROVIDER_RESPONSE_CAPTURE_EXECUTION_STORE_BUSY',
    'PROVIDER_RESPONSE_CAPTURE_FAILED',
    'PROVIDER_RESPONSE_CAPTURE_HASH_INVALID',
    'PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_INCOMPLETE',
    'PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_HTTP_CLASSIFICATION_REQUIRED',
    'PROVIDER_RESPONSE_CAPTURE_METADATA_INVALID',
    'PROVIDER_RESPONSE_CAPTURE_STATUS_SHA256_MISMATCH',
    'PROVIDER_RESPONSE_CAPTURE_STORE_INSIDE_WORKTREE',
    'PROVIDER_RESPONSE_CAPTURE_STORE_PATH_NOT_EXACT',
    'PROVIDER_RESPONSE_REPLAY_CAPTURE_MISSING',
    'PROVIDER_RESPONSE_REPLAY_DOMAIN_INVALID',
    'PROVIDER_RESPONSE_REPLAY_DOMAIN_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID',
    'PROVIDER_RESPONSE_REPLAY_ENVELOPE_CORRUPT',
    'PROVIDER_RESPONSE_REPLAY_EXTERNAL_ANCHOR_REQUIRED',
    'PROVIDER_RESPONSE_REPLAY_HTTP_CLASSIFICATION_REQUIRED',
    'PROVIDER_RESPONSE_REPLAY_JSON_INVALID',
    'PROVIDER_RESPONSE_REPLAY_JSON_OBJECT_REQUIRED',
    'PROVIDER_RESPONSE_REPLAY_LEDGER_RECEIPT_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_LENGTH_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_MAGIC_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_METADATA_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_SCHEMA_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_SHA256_MISMATCH',
    'PROVIDER_RESPONSE_REPLAY_SSE_EVENT_AFTER_DONE',
    'PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DATA_CONFLICT',
    'PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DELIMITER_MISSING',
    'PROVIDER_RESPONSE_REPLAY_SSE_JSON_INVALID',
    'PROVIDER_RESPONSE_REPLAY_SSE_OBJECT_REQUIRED',
})


_PROTOCOL_REASONS = frozenset({
    'ANTHROPIC_CAPTURE_PERSISTENCE_FAILED',
    'ANTHROPIC_SSE_',
    'ANTHROPIC_SSE_BLOCK_BEFORE_MESSAGE_START',
    'ANTHROPIC_SSE_CONTENT_BLOCK_START_BEFORE_STOP',
    'ANTHROPIC_SSE_CONTENT_BLOCK_STOP_UNBALANCED',
    'ANTHROPIC_SSE_DELTA_OUTSIDE_CONTENT_BLOCK',
    'ANTHROPIC_SSE_DUPLICATE_MESSAGE_START',
    'ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_DELTA',
    'ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP',
    'ANTHROPIC_SSE_EVENT_TYPE_UNSUPPORTED',
    'ANTHROPIC_SSE_FRAME_OR_PAYLOAD_INVALID',
    'ANTHROPIC_SSE_MESSAGE_DELTA_STATE_INVALID',
    'ANTHROPIC_SSE_MESSAGE_STOP_MISSING',
    'ANTHROPIC_SSE_MESSAGE_STOP_STATE_INVALID',
    'ANTHROPIC_SSE_PAYLOAD_REJECTED',
    'ANTHROPIC_SSE_TOOL_ARGUMENT_JSON_INVALID',
    'STREAM_BYTES_AFTER_CLOSE',
    'STREAM_CAPTURE_BOUNDARY_FAILED',
    'STREAM_CHECKPOINT_CAUSE_INVALID',
    'STREAM_CHECKPOINT_CONTROL_INVALID',
    'STREAM_CHECKPOINT_DURABILITY_INVALID',
    'STREAM_CHECKPOINT_HASH_INVALID',
    'STREAM_CHECKPOINT_JOURNAL_INVALID',
    'STREAM_CHECKPOINT_PERSISTENCE_FAILED',
    'STREAM_CHECKPOINT_SCHEMA_INVALID',
    'STREAM_CHECKPOINT_STATE_MISMATCH',
    'STREAM_CLOSED',
    'STREAM_CONTROL_CAUSE_MISMATCH',
    'STREAM_CONTROL_EVENT_INVALID',
    'STREAM_CONTROL_FAILURE',
    'STREAM_DURABLE_ACK_MISMATCH',
    'STREAM_DURABLE_ACK_NOT_SUBMITTED',
    'STREAM_DURABLE_ACK_STALE',
    'STREAM_DURABLE_PREFIX_REGRESSION',
    'STREAM_TERMINAL_NOT_DURABLE',
})


def safe_failure(exc: BaseException | None) -> dict | None:
    if exc is None:
        return None
    # These local capture boundaries carry public reliability taxonomy. Keep
    # their registered type/reason, never arbitrary exception payload text.
    from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
    from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError
    for cls, fallback in ((ProviderResponseCaptureError, 'PROVIDER_RESPONSE_CAPTURE_FAILED'),
                          (FullShortExecutionBoundaryError, 'STREAM_CAPTURE_BOUNDARY_FAILED')):
        if isinstance(exc, cls):
            reason = str(exc).split(':', 1)[0]
            from novel_flywheel.execution_failure_architecture import full_short_boundary_taxonomy_v1
            registered = (reason in _CAPTURE_REASONS if cls is ProviderResponseCaptureError
                          else re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}', reason) is not None
                          and full_short_boundary_taxonomy_v1(reason) is not None)
            if not registered:
                reason = fallback
            return {'class': cls.__name__, 'reason': reason}
    if isinstance(exc, AnthropicStreamProtocolError):
        reason = exc.reason_code if exc.reason_code in _PROTOCOL_REASONS else 'STREAM_CONTROL_FAILURE'
        return {'class': 'AnthropicStreamProtocolError', 'reason': reason}
    if isinstance(exc, asyncio.CancelledError):
        return {'class': 'CancelledError'}
    # Persist the supported base category, never an arbitrary subclass name.
    # Rehydration must normalize to the same transport event as live ingestion.
    for base in (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout,
                 httpx.PoolTimeout, httpx.TimeoutException, httpx.RemoteProtocolError,
                 httpx.ReadError, httpx.WriteError, httpx.ConnectError, httpx.TransportError):
        if isinstance(exc, base):
            return {'class': base.__name__}
    return {'class': 'RuntimeError'}


def restore_failure(record: dict | None) -> BaseException | None:
    if record is None:
        return None
    name = record['class']
    if name in {'ProviderResponseCaptureError', 'FullShortExecutionBoundaryError'}:
        reason = record.get('reason')
        from novel_flywheel.execution_failure_architecture import full_short_boundary_taxonomy_v1
        valid = isinstance(reason, str) and (reason in _CAPTURE_REASONS
            if name == 'ProviderResponseCaptureError' else
            reason == 'STREAM_CAPTURE_BOUNDARY_FAILED' or (re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}', reason) is not None
                and full_short_boundary_taxonomy_v1(reason) is not None))
        if not valid:
            raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CAUSE_INVALID')
        if name == 'ProviderResponseCaptureError':
            from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
            return ProviderResponseCaptureError(reason)
        from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError
        return FullShortExecutionBoundaryError(reason)
    if name == 'AnthropicStreamProtocolError':
        if record.get('reason') not in _PROTOCOL_REASONS:
            raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CAUSE_INVALID')
        return AnthropicStreamProtocolError(record['reason'])
    if name == 'CancelledError':
        return asyncio.CancelledError()
    if name not in {'ReadTimeout','WriteTimeout','ConnectTimeout','PoolTimeout','TimeoutException',
                    'RemoteProtocolError','ReadError','WriteError','ConnectError','TransportError','RuntimeError'}:
        raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CAUSE_INVALID')
    cls = getattr(httpx, name, RuntimeError)
    if not isinstance(cls, type) or not issubclass(cls, BaseException):
        raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CAUSE_INVALID')
    return cls('stream failure' if name == 'RuntimeError' else 'stream transport failure')


class DurableAnthropicStreamV1:
    """Only this owner accepts persistence ACKs or defines stream eligibility.

    The deterministic journal is the lossless serialized state representation;
    replay runs the same framer and reducer, and verifies derived state. A sink
    is storage only, and cannot reinterpret framing or semantic outcomes.
    """
    def __init__(self, *, owner_id: str, encoding: str = 'utf-8',
                 sink: Callable[[dict], StreamDurableAckV1] | None = None,
                 usage_projection: bool = False, require_durability: bool | None = None):
        self.owner_id = owner_id
        self.encoding = encoding
        self.sink = sink
        self.require_durability = sink is not None if require_durability is None else require_durability
        self._pending_checkpoint: dict | None = None
        self.semantic = AnthropicStream(usage_projection=usage_projection)
        self.framer = IncrementalSSEFramerV1()
        self.events: list[dict] = []
        self.journal: list[dict] = []
        self.semantic_prefix = 0
        self.frame_ordinal = 0
        self.terminal_identity: str | None = None
        self.success_terminal_identity: str | None = None
        self.provider_error_terminal_identity: str | None = None
        self.terminal_raw_prefix = 0
        self.generation = 0
        self.checkpoint_sha256: str | None = None
        self.raw_durable_prefix = 0
        self.framed_event_durable_prefix = 0
        self.semantic_accepted_prefix = 0
        self.success_terminal_evidence_durable = False
        self.provider_error_terminal_evidence_durable = False
        self.persistence_failure_count = 0
        self.partial_tail_count = 0

    def __getattr__(self, name):
        # Compatibility read projection, never another state store.
        return getattr(self.semantic, name)

    @property
    def raw(self) -> bytes:
        return bytes(self.framer.raw)

    @property
    def terminal_evidence_durable(self) -> bool:
        # A later explicit Provider error supersedes success under the strict
        # fatal-event rule. The old success ACK cannot attest the new error.
        if self.provider_error_terminal_identity is not None:
            return self.provider_error_terminal_evidence_durable
        return self.success_terminal_evidence_durable

    def ingest(self, data: bytes, *, persist: bool = True) -> None:
        self.framer.receive(data)
        self.journal.append({'bytes': base64.b64encode(data).decode('ascii')})
        while (frame := self.framer.pop()) is not None:
            raw, start, end = frame
            if start == 0:
                raw = raw.removeprefix(b'\xef\xbb\xbf')
            decoded = _decode_complete_sse(raw, encoding=self.encoding)
            for event in decoded:
                self.frame_ordinal += 1
                if isinstance(event, ProviderErrorEventV1):
                    event.evidence = event.evidence.model_copy(update={'event_ordinal': self.frame_ordinal})
                self.events.append(event)
                before = self.semantic.state
                self.semantic.step(event)
                entered_success = before not in SUCCESS_STATES and self.semantic.state in SUCCESS_STATES
                entered_error = before not in ERROR_STATES and self.semantic.state in ERROR_STATES
                if entered_success or entered_error:
                    identity = digest({'owner_id': self.owner_id,
                        'ordinal': self.frame_ordinal, 'raw_prefix': end,
                        'raw_sha256': hashlib.sha256(self.raw[:end]).hexdigest(),
                        'kind': 'error' if self.semantic.state in ERROR_STATES else 'message_stop'})
                    if entered_success:
                        self.success_terminal_identity = identity
                    else:
                        self.provider_error_terminal_identity = identity
                        self.semantic.capture_state = CaptureState.NOT_ATTEMPTED
                    if self.terminal_identity is None:
                        self.terminal_identity = identity
                        self.terminal_raw_prefix = end
                if (before not in SUCCESS_STATES | ERROR_STATES and
                        (self.semantic.primary is None or entered_error)) or entered_error:
                    self.semantic_prefix = end
        if persist:
            self.commit()

    def finish(self, exc: BaseException | None = None, *, persist: bool = True) -> None:
        record = safe_failure(exc)
        if exc is not None:
            canonical = restore_failure(record)
            if type(exc) is not type(canonical) or ('reason' in record and str(exc) != record['reason']):
                exc = canonical
        event = transport_event(exc)
        self.journal.append({'transport': event.value, 'failure': safe_failure(exc)})
        pending = self.framer.pending
        if pending and self.framer.state != FrameState.CLOSED:
            if self.terminal_identity is not None:
                self.partial_tail_count += 1
                self.semantic.tail_counts['PARTIAL_FRAME'] = self.partial_tail_count
                if isinstance(self.semantic.primary, AnthropicProviderTerminalError):
                    evidence = self.semantic.primary.provider_stream_error
                    self.semantic.primary.provider_stream_error = evidence.model_copy(update={
                        'secondary_post_error_invalid_tail_present': True})
            elif exc is None and self.semantic.primary is None:
                from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
                self.semantic.step(InvalidFrame(ProviderResponseCaptureError(
                    'PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DELIMITER_MISSING')))
            else:
                self.semantic.tail_counts['PARTIAL_FRAME'] = 1
        self.semantic.step(event, failure=exc)
        self.framer.close()
        if persist:
            self.commit()

    def step(self, event: Event, *, failure: BaseException | None = None):
        if event in {Event.EOF, Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION}:
            if failure is None:
                failure = {Event.EOF: None, Event.TIMEOUT: httpx.TimeoutException('stream timeout'),
                           Event.CANCELLATION: asyncio.CancelledError(),
                           Event.TRANSPORT_EXCEPTION: httpx.TransportError('stream transport failure')}[event]
            if transport_event(failure) != event:
                raise AnthropicStreamProtocolError('STREAM_CONTROL_CAUSE_MISMATCH')
            self.finish(failure)
        else:
            if event not in {Event.CAPTURE_COMMITTED, Event.CAPTURE_FAILED}:
                raise AnthropicStreamProtocolError('STREAM_CONTROL_EVENT_INVALID')
            record = safe_failure(failure)
            failure = restore_failure(record)
            self.journal.append({'capture': event.value, 'failure': record})
            result = self.semantic.step(event, failure=failure)
            self.commit()
            return result

    def checkpoint(self) -> dict:
        return {'schema': 'DurableAnthropicStreamCheckpointV1', 'owner_id': self.owner_id,
                'encoding': self.encoding, 'usage_projection': self.semantic.usage_projection,
                'require_durability': self.require_durability,
                'generation': self.generation + 1, 'parent_sha256': self.checkpoint_sha256,
                'journal': list(self.journal), 'raw_prefix': len(self.raw),
                'framed_prefix': self.framer.framed_prefix, 'semantic_prefix': self.semantic_prefix,
                'terminal_identity': self.terminal_identity, 'terminal_raw_prefix': self.terminal_raw_prefix,
                'success_terminal_identity': self.success_terminal_identity,
                'provider_error_terminal_identity': self.provider_error_terminal_identity,
                'framer': self.framer.snapshot(), 'state': self.semantic.snapshot(),
                'partial_tail_count': self.partial_tail_count,
                'persistence_failure_count': self.persistence_failure_count}

    def apply_ack(self, checkpoint: dict, ack: StreamDurableAckV1) -> None:
        if not isinstance(ack, StreamDurableAckV1) or ack != StreamDurableAckV1.for_checkpoint(checkpoint):
            raise AnthropicStreamProtocolError('STREAM_DURABLE_ACK_MISMATCH')
        if ack.owner_id != self.owner_id or checkpoint['parent_sha256'] != self.checkpoint_sha256 or ack.generation != self.generation + 1:
            raise AnthropicStreamProtocolError('STREAM_DURABLE_ACK_STALE')
        submitted = self._pending_checkpoint or self.checkpoint()
        if digest(checkpoint) != digest(submitted):
            raise AnthropicStreamProtocolError('STREAM_DURABLE_ACK_NOT_SUBMITTED')
        if (ack.raw_durable_prefix < self.raw_durable_prefix or
                ack.framed_event_durable_prefix < self.framed_event_durable_prefix or
                ack.semantic_accepted_prefix < self.semantic_accepted_prefix):
            raise AnthropicStreamProtocolError('STREAM_DURABLE_PREFIX_REGRESSION')
        self.generation = ack.generation
        self.checkpoint_sha256 = ack.checkpoint_sha256
        self.raw_durable_prefix = ack.raw_durable_prefix
        self.framed_event_durable_prefix = ack.framed_event_durable_prefix
        self.semantic_accepted_prefix = ack.semantic_accepted_prefix
        self.success_terminal_evidence_durable = (
            self.success_terminal_identity is not None and
            checkpoint['success_terminal_identity'] == self.success_terminal_identity)
        self.provider_error_terminal_evidence_durable = (
            self.provider_error_terminal_identity is not None and
            checkpoint['provider_error_terminal_identity'] == self.provider_error_terminal_identity)
        if self.terminal_evidence_durable and (
                self.semantic.primary is None or isinstance(self.semantic.primary, AnthropicProviderTerminalError)):
            self.semantic.capture_state = CaptureState.COMPLETE

    def commit(self) -> None:
        if self.sink is None:
            return
        # Preserve the exact pending transaction until its outcome is known.
        # Diagnostic journal entries/new bytes cannot rewrite an ambiguous
        # committed generation after an ACK was lost.
        checkpoint = self._pending_checkpoint or self.checkpoint()
        self._pending_checkpoint = deepcopy(checkpoint)
        try:
            try:
                ack = self.sink(deepcopy(checkpoint))
            except Exception:
                # One bounded local confirmation, with identical identity.
                # This is not a Provider retry or new physical attempt.
                ack = self.sink(deepcopy(checkpoint))
            self.apply_ack(checkpoint, ack)
        except Exception:
            self.persistence_failure_count += 1
            preserved = self.terminal_evidence_durable
            failure = AnthropicStreamProtocolError('STREAM_CHECKPOINT_PERSISTENCE_FAILED')
            self.journal.append({'capture': Event.CAPTURE_FAILED.value,
                'failure': safe_failure(failure), 'persistence_failure': True,
                'preserve_durable_terminal': preserved})
            if preserved:
                self.semantic.tail_counts['PERSISTENCE_FAILURE'] = self.persistence_failure_count
            else:
                self.semantic.step(Event.CAPTURE_FAILED, failure=failure)
            # A storage exception cannot replace an already observed Provider
            # error. Eligibility and persistence diagnostics remain owned here.
            return
        self._pending_checkpoint = None
        if checkpoint['journal'] != self.journal:
            # A previously ambiguous transaction was confirmed. Persist the
            # already-received suffix under the next generation, once.
            self.commit()

    @classmethod
    def restore(cls, checkpoint: dict, *, expected_sha256: str,
                sink: Callable[[dict], StreamDurableAckV1] | None = None):
        if digest(checkpoint) != expected_sha256 or checkpoint.get('schema') != 'DurableAnthropicStreamCheckpointV1':
            raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_HASH_INVALID')
        if (type(checkpoint.get('generation')) is not int or checkpoint['generation'] < 1
                or type(checkpoint.get('require_durability')) is not bool
                or type(checkpoint.get('usage_projection')) is not bool
                or any(type(checkpoint.get(key)) is not int or checkpoint[key] < 0 for key in
                       ('raw_prefix','framed_prefix','semantic_prefix','terminal_raw_prefix',
                        'partial_tail_count','persistence_failure_count'))):
            raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_SCHEMA_INVALID')
        owner = cls(owner_id=checkpoint['owner_id'], encoding=checkpoint['encoding'],
                    usage_projection=checkpoint['usage_projection'],
                    require_durability=checkpoint['require_durability'])
        for item in checkpoint['journal']:
            if 'bytes' in item:
                owner.ingest(base64.b64decode(item['bytes'], validate=True), persist=False)
            elif 'transport' in item:
                failure = restore_failure(item['failure'])
                if transport_event(failure).value != item['transport']:
                    raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CAUSE_INVALID')
                owner.finish(failure, persist=False)
            elif 'capture' in item:
                event = Event(item['capture'])
                if event not in {Event.CAPTURE_COMMITTED, Event.CAPTURE_FAILED}:
                    raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_CONTROL_INVALID')
                owner.journal.append(deepcopy(item))
                if item.get('persistence_failure') is True:
                    owner.persistence_failure_count += 1
                if item.get('preserve_durable_terminal') is True:
                    if owner.terminal_identity is None:
                        raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_DURABILITY_INVALID')
                    owner.semantic.tail_counts['PERSISTENCE_FAILURE'] = owner.persistence_failure_count
                else:
                    owner.semantic.step(event, failure=restore_failure(item['failure']))
            else:
                raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_JOURNAL_INVALID')
        derived = owner.checkpoint()
        for key in ('raw_prefix','framed_prefix','semantic_prefix','terminal_identity',
                    'terminal_raw_prefix','framer','partial_tail_count','persistence_failure_count',
                    'success_terminal_identity','provider_error_terminal_identity'):
            if derived[key] != checkpoint[key]:
                raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_STATE_MISMATCH')
        # Persistence ACK changes only capture durability; it is not a semantic
        # journal event. All other derived terminal/diagnostic state must match.
        for key in set(derived['state']) - {'terminal_capture_complete'}:
            if derived['state'][key] != checkpoint['state'][key]:
                raise AnthropicStreamProtocolError('STREAM_CHECKPOINT_STATE_MISMATCH')
        owner.generation = checkpoint['generation'] - 1
        owner.checkpoint_sha256 = checkpoint['parent_sha256']
        owner._pending_checkpoint = deepcopy(checkpoint)
        owner.apply_ack(checkpoint, StreamDurableAckV1.for_checkpoint(checkpoint))
        owner._pending_checkpoint = None
        owner.sink = sink
        return owner

    def snapshot(self) -> dict:
        return {**self.semantic.snapshot(), 'durable_owner_version': 1,
                'raw_durable_prefix': self.raw_durable_prefix,
                'framed_event_durable_prefix': self.framed_event_durable_prefix,
                'semantic_accepted_prefix': self.semantic_accepted_prefix,
                'terminal_identity': self.terminal_identity,
                'success_terminal_identity': self.success_terminal_identity,
                'provider_error_terminal_identity': self.provider_error_terminal_identity,
                'terminal_evidence_durable': self.terminal_evidence_durable,
                'success_terminal_evidence_durable': self.success_terminal_evidence_durable,
                'provider_error_terminal_evidence_durable': self.provider_error_terminal_evidence_durable,
                'tail_persistence_failure_count': self.persistence_failure_count,
                'partial_tail_count': self.partial_tail_count}

    def body(self) -> dict:
        body = self.semantic.body()
        if self.require_durability and not self.terminal_evidence_durable:
            raise AnthropicStreamProtocolError('STREAM_TERMINAL_NOT_DURABLE')
        body['_shared_stream_state'] = self.snapshot()
        return body
