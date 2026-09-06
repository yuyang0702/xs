"""Versioned, response-only Anthropic lifecycle and terminal authority.

The transition registry is executable production policy. Framing, content guards
and durable capture acknowledgements are distinct inputs to the same owner.
No transition performs I/O, dispatch, retry, or narrative acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from novel_flywheel.provider_stream_error import (
    ProviderErrorEventV1, StreamProviderErrorEvidenceV1, normalize_stream_error_v1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


class AnthropicStreamProtocolError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_sse_protocol_invalid", failure_class=FailureClass.SYNTAX_PROTOCOL,
            boundary="anthropic_sse_state_machine", message=reason_code, retryable=False)
        super().__init__(reason_code)


class AnthropicStreamIncompleteError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_sse_terminal_missing", failure_class=FailureClass.TRANSPORT,
            boundary="anthropic_sse_state_machine", message=reason_code, retryable=False)
        super().__init__(reason_code)


class AnthropicProviderTerminalError(RuntimeError):
    failure_family = "provider.terminal_error_event"
    failure_layer = "provider.protocol"
    dispatch_state = "response_captured"
    authority_effect = "preserves_last_accepted"
    restart_behavior = "no_redispatch"
    recovery_action = "stop_without_additional_dispatch"

    def __init__(self, error_type: str = "", *, evidence: StreamProviderErrorEvidenceV1 | None = None):
        self.provider_stream_error = evidence or normalize_stream_error_v1({"error": {"type": error_type}})
        self.error_type = self.provider_stream_error.provider_error_type
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_provider_terminal_error", failure_class=FailureClass.UNKNOWN,
            boundary="anthropic_sse_state_machine", message=self.error_type, retryable=False)
        super().__init__("provider emitted an explicit terminal error")


class State(StrEnum):
    BEFORE_MESSAGE = "BEFORE_MESSAGE"
    MESSAGE_ACTIVE = "MESSAGE_ACTIVE"
    CONTENT_ACTIVE = "CONTENT_ACTIVE"
    CONTENT_COMPLETE = "CONTENT_COMPLETE"
    MESSAGE_DELTA = "MESSAGE_DELTA"
    SUCCESS = "SEMANTIC_SUCCESS_TERMINAL"
    SUCCESS_TAIL = "SUCCESS_TRANSPORT_TAIL"
    PROVIDER_ERROR = "PROVIDER_ERROR_TERMINAL"
    ERROR_TAIL = "PROVIDER_ERROR_TRANSPORT_TAIL"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE_TERMINAL"
    PROTOCOL_INVALID = "PROTOCOL_INVALID_TERMINAL"


class Event(StrEnum):
    MESSAGE_START = "message_start"
    CONTENT_START = "content_block_start"
    CONTENT_DELTA = "content_block_delta"
    CONTENT_STOP = "content_block_stop"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_STOP = "message_stop"
    PING = "ping"
    ERROR = "error"
    UNKNOWN = "unknown_versioned_event"
    INVALID = "invalid_frame_or_payload"
    EOF = "EOF"
    TIMEOUT = "TIMEOUT"
    CANCELLATION = "CANCELLATION"
    TRANSPORT_EXCEPTION = "TRANSPORT_EXCEPTION"
    CAPTURE_COMMITTED = "CAPTURE_COMMITTED"
    CAPTURE_FAILED = "CAPTURE_FAILED"


class Action(StrEnum):
    ADVANCE = "ACCEPT_ADVANCE"
    KEEPALIVE = "IGNORE_TRANSPORT_KEEPALIVE"
    SUCCESS = "TERMINAL_SUCCESS"
    PROVIDER_ERROR = "TERMINAL_PROVIDER_ERROR"
    TRANSPORT_FAILURE = "TERMINAL_TRANSPORT_FAILURE"
    INVALID = "FAIL_CLOSED_PROTOCOL_INVALID"
    UNKNOWN = "VERSIONED_UNKNOWN_EVENT_POLICY"
    CAPTURE = "ACKNOWLEDGE_CAPTURE_PROOF"
    CAPTURE_FAILURE = "TERMINAL_CAPTURE_FAILURE"


class CaptureState(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


SUCCESS_STATES = frozenset({State.SUCCESS, State.SUCCESS_TAIL})
ERROR_STATES = frozenset({State.PROVIDER_ERROR, State.ERROR_TAIL})
FAILED_STATES = frozenset({State.TRANSPORT_FAILURE, State.PROTOCOL_INVALID})
TAIL_EVENTS = frozenset({Event.EOF, Event.TIMEOUT, Event.CANCELLATION, Event.TRANSPORT_EXCEPTION})
UNKNOWN_EVENT_POLICY = "anthropic_stream_v1_typed_fail_closed_without_semantic_mutation"


@dataclass(frozen=True)
class Rule:
    action: Action
    next_state: State
    reason: str = ""


def _registered_rule(state: State, event: Event) -> Rule:
    # Absorbing invalid/transport terminals cannot be rescued by later bytes.
    if state in FAILED_STATES:
        return Rule(Action.INVALID if state == State.PROTOCOL_INVALID else Action.TRANSPORT_FAILURE, state)
    if event == Event.CAPTURE_COMMITTED:
        return Rule(Action.CAPTURE, state)
    if state in ERROR_STATES:
        return Rule(Action.PROVIDER_ERROR, State.ERROR_TAIL)
    if event == Event.CAPTURE_FAILED:
        return Rule(Action.CAPTURE_FAILURE, state, "ANTHROPIC_CAPTURE_PERSISTENCE_FAILED")
    if event == Event.ERROR:
        return Rule(Action.PROVIDER_ERROR, State.PROVIDER_ERROR)
    if event == Event.PING:
        return Rule(Action.KEEPALIVE, State.SUCCESS_TAIL if state in SUCCESS_STATES else state)
    if event in TAIL_EVENTS:
        if state in SUCCESS_STATES:
            return Rule(Action.SUCCESS, State.SUCCESS_TAIL)
        return Rule(Action.TRANSPORT_FAILURE, State.TRANSPORT_FAILURE, "ANTHROPIC_SSE_MESSAGE_STOP_MISSING")
    if event == Event.UNKNOWN:
        return Rule(Action.UNKNOWN, State.PROTOCOL_INVALID,
                    "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP" if state in SUCCESS_STATES else
                    "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_DELTA" if state == State.MESSAGE_DELTA else
                    "ANTHROPIC_SSE_EVENT_TYPE_UNSUPPORTED")
    if event == Event.INVALID:
        return Rule(Action.INVALID, State.PROTOCOL_INVALID, "ANTHROPIC_SSE_FRAME_OR_PAYLOAD_INVALID")
    if state in SUCCESS_STATES:
        return Rule(Action.INVALID, State.PROTOCOL_INVALID, "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP")
    allowed = {
        State.BEFORE_MESSAGE: {Event.MESSAGE_START: State.MESSAGE_ACTIVE},
        State.MESSAGE_ACTIVE: {Event.CONTENT_START: State.CONTENT_ACTIVE, Event.MESSAGE_DELTA: State.MESSAGE_DELTA},
        State.CONTENT_ACTIVE: {Event.CONTENT_DELTA: State.CONTENT_ACTIVE, Event.CONTENT_STOP: State.CONTENT_COMPLETE},
        State.CONTENT_COMPLETE: {Event.CONTENT_START: State.CONTENT_ACTIVE, Event.MESSAGE_DELTA: State.MESSAGE_DELTA},
        State.MESSAGE_DELTA: {Event.MESSAGE_DELTA: State.MESSAGE_DELTA, Event.MESSAGE_STOP: State.SUCCESS},
    }
    if event in allowed[state]:
        return Rule(Action.SUCCESS if event == Event.MESSAGE_STOP else Action.ADVANCE, allowed[state][event])
    reason = (
        "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_DELTA" if state == State.MESSAGE_DELTA else
        "ANTHROPIC_SSE_DUPLICATE_MESSAGE_START" if event == Event.MESSAGE_START else
        "ANTHROPIC_SSE_BLOCK_BEFORE_MESSAGE_START" if event == Event.CONTENT_START and state == State.BEFORE_MESSAGE else
        "ANTHROPIC_SSE_CONTENT_BLOCK_START_BEFORE_STOP" if event == Event.CONTENT_START else
        "ANTHROPIC_SSE_DELTA_OUTSIDE_CONTENT_BLOCK" if event == Event.CONTENT_DELTA else
        "ANTHROPIC_SSE_CONTENT_BLOCK_STOP_UNBALANCED" if event == Event.CONTENT_STOP else
        "ANTHROPIC_SSE_MESSAGE_DELTA_STATE_INVALID" if event == Event.MESSAGE_DELTA else
        "ANTHROPIC_SSE_MESSAGE_STOP_STATE_INVALID"
    )
    return Rule(Action.INVALID, State.PROTOCOL_INVALID, reason)


TRANSITIONS = {(s, e): _registered_rule(s, e) for s in State for e in Event}
assert len(TRANSITIONS) == len(State) * len(Event)


class InvalidFrame(dict):
    """An ordered framing failure; remote JSON cannot forge the Python type."""
    def __init__(self, error: BaseException):
        super().__init__(type=Event.INVALID.value)
        self.error = error


class OwnedStreamEvents(list):
    """Compatibility adapter view of an already-evaluated production stream."""
    def __init__(self, events, owner):
        super().__init__(events)
        self.owner = owner


class AnthropicStream:
    def __init__(self, *, usage_projection: bool = False):
        self.state = State.BEFORE_MESSAGE
        self.message_id = None
        self.usage: dict[str, int] = {}
        self.stop_reason = None
        self.blocks: dict[int, dict] = {}
        self.tool_json: dict[int, list[str]] = {}
        self.active_index: int | None = None
        self.primary: BaseException | None = None
        self.tail_closed_cleanly: bool | None = None
        self.capture_state = CaptureState.NOT_ATTEMPTED
        self.post_terminal_ping_count = 0
        self.tail_counts: dict[str, int] = {}
        self.usage_projection = usage_projection
        self.trace: list[dict[str, str]] = []

    @property
    def semantic_terminal_complete(self) -> bool:
        return self.state in SUCCESS_STATES and not self.usage_projection

    @property
    def terminal_capture_complete(self) -> bool:
        return self.capture_state == CaptureState.COMPLETE

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state.value,
                "semantic_terminal_complete": self.semantic_terminal_complete,
                "terminal_capture_complete": self.terminal_capture_complete,
                "transport_tail_closed_cleanly": self.tail_closed_cleanly,
                "primary_cause": "PROVIDER_ERROR" if isinstance(self.primary, AnthropicProviderTerminalError) else
                    "PROTOCOL_INVALID" if self.state == State.PROTOCOL_INVALID else
                    "TRANSPORT_FAILURE" if self.state == State.TRANSPORT_FAILURE else
                    "CAPTURE_FAILURE" if self.capture_state == CaptureState.FAILED else
                    "SUCCESS" if self.state in SUCCESS_STATES else "NONE",
                "post_terminal_ping_count": self.post_terminal_ping_count,
                "tail_counts": dict(self.tail_counts), "unknown_event_policy": UNKNOWN_EVENT_POLICY}

    def step(self, payload: dict | Event, *, failure: BaseException | None = None) -> Rule:
        before = self.state
        if isinstance(payload, Event):
            event = payload
            value: dict = {}
        else:
            value = payload
            if not isinstance(value, dict):
                event = Event.INVALID
            elif isinstance(value, InvalidFrame):
                event = Event.INVALID
                failure = value.error
            else:
                try:
                    event = Event(value.get("type"))
                    # Internal signals cannot be injected as remote event names.
                    if event in TAIL_EVENTS or event in {Event.CAPTURE_COMMITTED, Event.CAPTURE_FAILED}:
                        event = Event.UNKNOWN
                except (ValueError, TypeError):
                    event = Event.UNKNOWN
        rule = TRANSITIONS[before, event]
        if event in TAIL_EVENTS:
            self.tail_closed_cleanly = event == Event.EOF
        if before in SUCCESS_STATES | ERROR_STATES:
            self.tail_counts[event.value] = self.tail_counts.get(event.value, 0) + 1
        if before in FAILED_STATES:
            pass  # Absorbing terminal preserves the exact primary and data.
        elif event == Event.CAPTURE_COMMITTED:
            if before in SUCCESS_STATES | ERROR_STATES:
                self.capture_state = CaptureState.COMPLETE
        elif before in ERROR_STATES:
            if event == Event.CAPTURE_FAILED:
                self.capture_state = CaptureState.FAILED
            self._error_tail(event, failure)
        elif rule.action == Action.CAPTURE_FAILURE:
            self.capture_state = CaptureState.FAILED
            self.primary = failure or AnthropicStreamProtocolError(rule.reason)
        elif rule.action == Action.PROVIDER_ERROR:
            evidence = value.evidence if isinstance(value, ProviderErrorEventV1) else normalize_stream_error_v1(value)
            self.primary = AnthropicProviderTerminalError(evidence=evidence)
        elif rule.action == Action.KEEPALIVE:
            if before in SUCCESS_STATES:
                self.post_terminal_ping_count += 1
        elif rule.action in {Action.INVALID, Action.UNKNOWN}:
            self.primary = failure or AnthropicStreamProtocolError(rule.reason)
        elif rule.action == Action.TRANSPORT_FAILURE:
            self.primary = failure or AnthropicStreamIncompleteError(rule.reason)
        elif event not in TAIL_EVENTS:
            try:
                self._apply(event, value)
            except Exception as exc:
                # Semantic guards own their typed error; an arbitrary bug is
                # never classified as transport or silently granted success.
                self.primary = exc
                rule = Rule(Action.INVALID, State.PROTOCOL_INVALID,
                            getattr(exc, "reason_code", "ANTHROPIC_SSE_PAYLOAD_REJECTED"))
        self.state = rule.next_state
        self.trace.append({"from_state": before.value, "event": event.value,
                           "action": rule.action.value, "next_state": self.state.value})
        return rule

    def _error_tail(self, event: Event, failure: BaseException | None) -> None:
        assert isinstance(self.primary, AnthropicProviderTerminalError)
        evidence = self.primary.provider_stream_error
        update: dict[str, Any] = {}
        if event == Event.PING:
            update['secondary_post_error_ping_count'] = evidence.secondary_post_error_ping_count + 1
        if event == Event.ERROR:
            update['secondary_post_error_error_count'] = evidence.secondary_post_error_error_count + 1
        if event in {Event.INVALID, Event.UNKNOWN}:
            update['secondary_post_error_invalid_tail_present'] = True
        if event not in TAIL_EVENTS:
            update['secondary_post_error_event_count'] = evidence.secondary_post_error_event_count + 1
        if event in TAIL_EVENTS - {Event.EOF}:
            update['secondary_post_error_transport_present'] = True
            update['secondary_post_error_timeout_present'] = evidence.secondary_post_error_timeout_present or event == Event.TIMEOUT
            name = type(failure).__name__ if failure else event.value
            update['secondary_transport_exception_class'] = name if name in {'ReadTimeout','WriteTimeout','ConnectTimeout','PoolTimeout','TimeoutException','CancelledError'} else 'TransportError'
        if event in TAIL_EVENTS:
            update['transport_complete'] = event == Event.EOF
        if event == Event.CAPTURE_FAILED:
            update['secondary_post_error_observer_failure_count'] = evidence.secondary_post_error_observer_failure_count + 1
        self.primary.provider_stream_error = evidence.model_copy(update=update)

    def body(self) -> dict:
        if self.primary is not None:
            raise self.primary
        if self.state not in SUCCESS_STATES:
            raise AnthropicStreamIncompleteError('ANTHROPIC_SSE_MESSAGE_STOP_MISSING')
        return {'id': self.message_id, 'content': [self.blocks[i] for i in sorted(self.blocks)],
                'stop_reason': self.stop_reason, 'usage': dict(self.usage), '_protocol_complete': True,
                '_terminal_event': 'message_stop', '_post_terminal_ping_count': self.post_terminal_ping_count,
                '_shared_stream_state': self.snapshot()}

    def _apply(self, event: Event, value: dict) -> None:
        from novel_flywheel.provider_response_capture import merge_anthropic_usage_snapshot_v1

        def reject(reason: str):
            raise AnthropicStreamProtocolError('ANTHROPIC_SSE_' + reason)

        if event == Event.MESSAGE_START:
            message = value.get('message')
            if not isinstance(message, dict):
                reject('MESSAGE_OBJECT_INVALID')
            raw_usage = message.get('usage')
            usage = merge_anthropic_usage_snapshot_v1({}, {} if raw_usage is None else raw_usage)
            if message.get('id') is not None and not isinstance(message['id'], str):
                reject('MESSAGE_ID_INVALID')
            self.message_id, self.usage = message.get('id'), usage
        elif event == Event.CONTENT_START:
            index = value.get('index')
            if type(index) is not int or index < 0:
                reject('CONTENT_BLOCK_INDEX_INVALID')
            if index in self.blocks:
                reject('DUPLICATE_CONTENT_BLOCK')
            if index != len(self.blocks):
                reject('CONTENT_BLOCK_INDEX_NONCONTIGUOUS')
            raw = value.get('content_block')
            if not isinstance(raw, dict):
                reject('CONTENT_BLOCK_INVALID')
            block = deepcopy(raw)
            kind = block.get('type')
            if not isinstance(kind, str) or kind not in {'text', 'tool_use', 'thinking', 'redacted_thinking'}:
                reject('CONTENT_BLOCK_TYPE_UNSUPPORTED')
            if kind == 'text' and not isinstance(block.get('text', ''), str):
                reject('TEXT_BLOCK_INVALID')
            if kind == 'tool_use' and (not isinstance(block.get('id'), str) or not block['id']
                    or not isinstance(block.get('name'), str) or not block['name']):
                reject('TOOL_USE_FIELDS_INVALID')
            self.blocks[index], self.active_index = block, index
            if kind == 'tool_use':
                self.tool_json[index] = []
        elif event == Event.CONTENT_DELTA:
            index = value.get('index')
            if type(index) is not int or index < 0:
                reject('CONTENT_BLOCK_INDEX_INVALID')
            if index != self.active_index:
                reject('DELTA_OUTSIDE_CONTENT_BLOCK')
            delta = value.get('delta')
            if not isinstance(delta, dict):
                reject('CONTENT_DELTA_INVALID')
            kind = self.blocks[index]['type']
            subtype = delta.get('type')
            accepted = {'text': {'text_delta'}, 'tool_use': {'input_json_delta'},
                        'thinking': {'thinking_delta', 'signature_delta'}, 'redacted_thinking': set()}
            if not isinstance(subtype, str) or subtype not in accepted[kind]:
                reject('CONTENT_DELTA_TYPE_MISMATCH')
            if subtype == 'text_delta':
                text = delta.get('text')
                if not isinstance(text, str):
                    reject('TEXT_DELTA_INVALID')
                self.blocks[index]['text'] = self.blocks[index].get('text', '') + text
            elif subtype == 'input_json_delta':
                partial = delta.get('partial_json')
                if not isinstance(partial, str):
                    reject('TOOL_ARGUMENT_DELTA_INVALID')
                self.tool_json[index].append(partial)
            # Thinking/signature bytes retain their historical response projection.
        elif event == Event.CONTENT_STOP:
            index = value.get('index')
            if type(index) is not int or index < 0:
                reject('CONTENT_BLOCK_INDEX_INVALID')
            if index != self.active_index:
                reject('CONTENT_BLOCK_STOP_UNBALANCED')
            self.active_index = None
        elif event == Event.MESSAGE_DELTA:
            raw_delta = value.get('delta')
            delta = {} if raw_delta is None else raw_delta
            if not isinstance(delta, dict):
                reject('MESSAGE_DELTA_OBJECT_INVALID')
            raw_usage = value.get('usage')
            usage = merge_anthropic_usage_snapshot_v1(self.usage, {} if raw_usage is None else raw_usage)
            reason = self.stop_reason if delta.get('stop_reason') is None else delta['stop_reason']
            if reason is not None and not isinstance(reason, str):
                reject('STOP_REASON_INVALID')
            self.usage, self.stop_reason = usage, reason
        elif event == Event.MESSAGE_STOP:
            if not self.stop_reason and not self.usage_projection:
                reject('MESSAGE_STOP_STATE_INVALID')
            complete = deepcopy(self.blocks)
            for index, parts in self.tool_json.items():
                raw = ''.join(parts)
                if raw:
                    try:
                        arguments = json.loads(raw)
                    except ValueError as exc:
                        raise AnthropicStreamProtocolError('ANTHROPIC_SSE_TOOL_ARGUMENT_JSON_INVALID') from exc
                    if not isinstance(arguments, dict):
                        reject('TOOL_ARGUMENTS_INVALID')
                    complete[index]['input'] = arguments
                elif 'input' in complete[index] and not isinstance(complete[index]['input'], dict):
                    reject('TOOL_ARGUMENTS_INVALID')
            self.blocks = complete


def aggregate_events(events: list[dict], *, usage_projection: bool = False) -> AnthropicStream:
    if isinstance(events, OwnedStreamEvents) and not usage_projection:
        return events.owner
    stream = AnthropicStream(usage_projection=usage_projection)
    for event in events:
        stream.step(event)
    return stream


def _decode_complete_sse(data: bytes, *, encoding: str = 'utf-8') -> list[dict]:
    """Frame exact bytes without owning semantic or terminal precedence.

    Every invalid closed frame remains an ordered input to the lifecycle owner.
    The generic decoder for other protocols is not changed by this path.
    """
    import re
    from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
    events: list[dict] = []
    # Validate every byte of a closed frame, including fields that are ignored
    # or overwritten. Partial UTF-8 remains buffered by the incremental framer.
    try:
        data.decode(encoding)
    except (UnicodeError, LookupError):
        return [InvalidFrame(ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID'))]
    data_lines: list[bytes] = []
    name = b''
    ordinal = 0

    def dispatch():
        nonlocal name, ordinal
        raw = b'\n'.join(data_lines)
        data_lines.clear()
        event_name, name = name, b''
        ordinal += 1
        try:
            text = raw.decode(encoding)
            explicit_error = event_name == b'error'
            try:
                payload = json.loads(text)
                shape = None
            except ValueError:
                if not explicit_error:
                    raise ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_SSE_JSON_INVALID')
                payload, shape = None, 'empty' if not raw else 'raw'
            if explicit_error or (isinstance(payload, dict) and payload.get('type') == 'error' and not event_name):
                events.append(ProviderErrorEventV1(normalize_stream_error_v1(payload, raw=raw, shape=shape,
                    ordinal=ordinal, conflict=isinstance(payload, dict) and 'type' in payload and payload['type'] != 'error')))
                return
            if not isinstance(payload, dict):
                raise ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_SSE_OBJECT_REQUIRED')
            if event_name and payload.get('type') != event_name.decode(encoding):
                raise ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DATA_CONFLICT')
            events.append(payload)
        except (UnicodeError, LookupError) as exc:
            events.append(InvalidFrame(ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_ENCODING_INVALID')))
        except ProviderResponseCaptureError as exc:
            events.append(InvalidFrame(exc))

    lines = re.split(br'\r\n|\r|\n', data)
    if lines and not lines[-1]:
        lines.pop()
    for line in lines:
        if not line:
            if data_lines or name == b'error':
                dispatch()
            else:
                name = b''
        else:
            # A field without a colon has an empty value under SSE. Only the
            # first colon separates a field; remove at most one leading space.
            field, separator, value = line.partition(b':')
            value = value.removeprefix(b' ') if separator else b''
            if field == b'event':
                name = value
            elif field == b'data':
                data_lines.append(value)
    if data_lines or name == b'error':
        events.append(InvalidFrame(ProviderResponseCaptureError('PROVIDER_RESPONSE_REPLAY_SSE_EVENT_DELIMITER_MISSING')))
    return events


def evaluate_bytes(data: bytes, *, encoding: str = 'utf-8', usage_projection: bool = False):
    from novel_flywheel.anthropic_durable_stream import DurableAnthropicStreamV1
    owner = DurableAnthropicStreamV1(owner_id='offline-replay', encoding=encoding,
                                     usage_projection=usage_projection)
    owner.ingest(data)
    owner.finish()
    return OwnedStreamEvents(owner.events, owner), owner


def decode_sse(data: bytes, *, encoding: str = 'utf-8') -> list[dict]:
    events, owner = evaluate_bytes(data, encoding=encoding)
    from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
    if isinstance(owner.primary, ProviderResponseCaptureError) and not any(
            isinstance(event, InvalidFrame) for event in events):
        events.append(InvalidFrame(owner.primary))
    return events



def usage_containers(events: list[dict]) -> list[tuple[str, dict]]:
    """Protocol-owned usage lineage, explicitly not Message acceptance.

    The historical abbreviated message_start/delta/stop receipt is evaluated in
    usage projection mode. It does not manufacture a stop reason or content and
    cannot obtain semantic_terminal_complete. Source indices remain lossless.
    """
    from novel_flywheel.provider_response_capture import ProviderResponseCaptureError
    stream = AnthropicStream(usage_projection=True)
    containers = []
    for index, value in enumerate(events):
        before = stream.state
        stream.step(value)
        kind = value.get('type') if isinstance(value, dict) else None
        if isinstance(stream.primary, AnthropicProviderTerminalError):
            raise ProviderResponseCaptureError('PROVIDER_REPORTED_USAGE_PROVIDER_ERROR')
        if before in SUCCESS_STATES and kind != 'ping':
            raise ProviderResponseCaptureError('PROVIDER_REPORTED_USAGE_EVENT_AFTER_MESSAGE_STOP')
        if stream.primary is not None:
            raise stream.primary
        if kind == 'message_start':
            message = value.get('message')
            nested = message.get('usage') if isinstance(message, dict) else None
            if isinstance(nested, dict):
                containers.append((f'event[{index}].message.usage', nested))
        elif kind == 'message_delta':
            direct = value.get('usage')
            if isinstance(direct, dict):
                containers.append((f'event[{index}].usage', direct))
    if stream.state not in SUCCESS_STATES:
        raise ProviderResponseCaptureError('PROVIDER_REPORTED_USAGE_SSE_TERMINAL_MISSING')
    return containers
