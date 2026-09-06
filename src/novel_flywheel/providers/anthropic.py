import asyncio
import json
import httpx

from novel_flywheel.provider_stream_error import (
    ProviderErrorEventV1, StreamProviderErrorEvidenceV1, normalize_stream_error_v1,
)

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
from novel_flywheel.provider_response_capture import (
    FullShortTransportEvidenceStateV1,
    ProviderResponseCaptureError,
    canonical_anthropic_usage_v1,
    merge_anthropic_usage_snapshot_v1,
    decide_full_short_transport_recovery_v1,
    parse_provider_protocol_input_bytes_v1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.model_diagnostics import (
    attach_exception_snapshot,
    provider_snapshot_with_status,
    provider_tool_shape_snapshot,
    strict_snapshot_capture_requested,
)
from novel_flywheel.planning_repair_diagnostics import (
    attach_provider_content_snapshot,
    finalize_provider_content_block_snapshot,
    safe_capture_provider_content_block_snapshot,
)
from novel_flywheel.providers.http import HttpProvider
from novel_flywheel.provider_output import (
    capture_provider_raw_shape_v1,
    provider_output_shape_from_response,
)
from novel_flywheel.provider_payloads import anthropic_payload_v1


from novel_flywheel.anthropic_stream import (
    AnthropicStreamProtocolError, AnthropicStreamIncompleteError, AnthropicProviderTerminalError,
    aggregate_events, evaluate_bytes, Event, OwnedStreamEvents,
)


class AnthropicAdapter(HttpProvider):
    DIAGNOSTIC_ADAPTER_ID = "anthropic"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    async def _consume_protocol_stream(self, response):
        """Advance the shared owner before requesting the next network chunk."""
        from novel_flywheel.anthropic_durable_stream import DurableAnthropicStreamV1
        encoding = response.encoding or 'utf-8'
        factory = getattr(self.attempt_observer, 'create_anthropic_stream_owner_v1', None)
        stream = (factory(encoding=encoding) if callable(factory) else
                  DurableAnthropicStreamV1(owner_id='adapter-local', encoding=encoding))
        self._last_stream_outcome_v1 = stream
        tail_error = None
        try:
            async for chunk in response.aiter_bytes():
                stream.ingest(chunk)
        except (asyncio.CancelledError, Exception) as exc:
            tail_error = exc
        stream.finish(tail_error)
        # httpx closes on clean iterator exhaustion. Explicitly close interrupted
        # iterators here so the final checkpoint/capture includes close failures.
        try:
            await response.aclose()
        except (asyncio.CancelledError, Exception) as exc:
            stream.finish(exc)
        raw = stream.raw
        content_type = response.headers.get('content-type', '')
        legacy_complete = stream.semantic_terminal_complete or tail_error is None
        try:
            capture_ack = self._capture_provider_protocol_input(raw,
                status_code=response.status_code, content_type=content_type,
                encoding=encoding, transport_complete=legacy_complete)
        except Exception as exc:
            stream.step(Event.CAPTURE_FAILED, failure=exc)
        else:
            # Compatibility observers acknowledge their one raw capture only.
            # Production Full Short durability comes exclusively from typed
            # checkpoint acknowledgements, never this legacy return value.
            if stream.sink is None and capture_ack is True:
                stream.step(Event.CAPTURE_COMMITTED)
        if stream.semantic_terminal_complete:
            self._last_protocol_input_v1 = (raw, content_type, encoding)
        return OwnedStreamEvents(stream.events, stream), stream

    @staticmethod
    def _stream_tail_event(exc):
        if exc is None:
            return Event.EOF
        if isinstance(exc, httpx.TimeoutException):
            return Event.TIMEOUT
        if isinstance(exc, asyncio.CancelledError):
            return Event.CANCELLATION
        return Event.TRANSPORT_EXCEPTION

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._bind_model_request("anthropic", request)
        payload = anthropic_payload_v1(request)
        auth_headers = ({"Authorization": f"Bearer {self.api_key}"}
                        if self.auth_type == "bearer" else {"x-api-key": self.api_key})
        path = "messages" if self.base_url.endswith("/v1") else "v1/messages"
        events, body = await self.post_stream(path, payload=payload, headers={
            **auth_headers, "anthropic-version": "2023-06-01",
        })
        capture_provider_raw_shape_v1(
            protocol="anthropic", body=body, events=events,
            requested_output_cap=request.max_output_tokens,
            effective_output_cap=payload["max_tokens"],
        )
        if body is None:
            try:
                body = self._aggregate_stream(events)
            except Exception as exc:
                replayed = self._replay_complete_valid_capture(exc)
                if replayed is not None:
                    replay_events, replay_body = replayed
                    try:
                        body = (
                            replay_body
                            if replay_body is not None
                            else self._aggregate_stream(replay_events)
                        )
                    except Exception as replay_exc:
                        if strict_snapshot_capture_requested():
                            snapshot = self._stream_exception_snapshot(
                                replay_events
                            )
                            attach_exception_snapshot(replay_exc, snapshot)
                        raise
                    events = replay_events
                else:
                    if strict_snapshot_capture_requested():
                        snapshot = self._stream_exception_snapshot(events)
                        attach_exception_snapshot(exc, snapshot)
                    raise
        usage = body.get("usage", {})
        content = body.get("content", [])
        content_snapshot = safe_capture_provider_content_block_snapshot(
            adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
            adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
            protocol="anthropic",
            provider_response=body,
            request_max_output_tokens=request.max_output_tokens,
            finish_reason=body.get("stop_reason"),
            output_tokens=usage.get("output_tokens", 0),
            block_types=[
                part.get("type") for part in content if isinstance(part, dict)
            ],
            text_values=[
                part.get("text") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ],
            tool_arguments=[
                part.get("input") for part in content
                if isinstance(part, dict) and part.get("type") == "tool_use"
            ],
            tool_argument_presence=any(
                "input" in part for part in content
                if isinstance(part, dict) and part.get("type") == "tool_use"
            ),
            reasoning_block_count=sum(
                part.get("type") in {"thinking", "reasoning", "redacted_thinking"}
                for part in content if isinstance(part, dict)
            ),
        )
        snapshot = None
        if strict_snapshot_capture_requested():
            raw_calls = [
                part for part in content
                if isinstance(part, dict) and part.get("type") == "tool_use"
            ]
            call_inputs = [{
                "call_id": part.get("id"),
                "name": part.get("name"),
                "arguments_present": "input" in part,
                "arguments": part.get("input"),
                "partial": not bool(part.get("name")) or "input" not in part,
            } for part in raw_calls]
            status = (
                "snapshot_partial"
                if body.get("stop_reason") == "max_tokens"
                or any(item["partial"] for item in call_inputs)
                else "snapshot_exact"
            )
            snapshot = provider_tool_shape_snapshot(
                adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
                adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
                provider_body=body,
                provider_request_id=body.get("id"),
                content_block_count=len(content),
                text_present=any(
                    part.get("type") == "text" and bool(part.get("text"))
                    for part in content if isinstance(part, dict)
                ),
                tool_use_present=bool(call_inputs),
                finish_reason=body.get("stop_reason"),
                calls=call_inputs,
                snapshot_status=status,
            )
        def project_response(projected_body: dict) -> ModelResponse:
            response = self._model_response_from_body(
                projected_body,
                provider_state_extra=({
                    "_r1_pa1_tool_shape_snapshot": snapshot.model_dump(
                        mode="json", by_alias=True,
                    ),
                } if snapshot is not None else None),
            )
            if content_snapshot is not None:
                try:
                    finalized_snapshot = finalize_provider_content_block_snapshot(
                        content_snapshot,
                        normalized_text=response.text,
                        normalized_tool_call_count=len(response.tool_calls),
                    )
                    response = response.model_copy(update={
                        "provider_state": {
                            **response.provider_state,
                            "_r1_ptr1_provider_content_snapshot": (
                                finalized_snapshot.model_dump(
                                    mode="json", by_alias=True,
                                )
                            ),
                        },
                    })
                except Exception:
                    pass
            return response

        try:
            return project_response(body)
        except Exception as exc:
            replayed = self._replay_complete_valid_capture(exc)
            if replayed is not None:
                _replay_events, replay_body = replayed
                try:
                    return project_response(replay_body)
                except Exception as replay_exc:
                    if snapshot is not None:
                        attach_exception_snapshot(
                            replay_exc, provider_snapshot_with_status(
                                snapshot, "adapter_exception_with_snapshot",
                            ),
                        )
                    if content_snapshot is not None:
                        attach_provider_content_snapshot(
                            replay_exc, content_snapshot,
                        )
                    raise
            if snapshot is not None:
                attach_exception_snapshot(
                    exc, provider_snapshot_with_status(
                        snapshot, "adapter_exception_with_snapshot",
                    ),
                )
            if content_snapshot is not None:
                attach_provider_content_snapshot(exc, content_snapshot)
            raise

    @staticmethod
    def _model_response_from_body(
        body: dict, *, provider_state_extra: dict | None = None,
    ) -> ModelResponse:
        """Shared live/replay projection after protocol validation."""

        AnthropicAdapter._validate_json_body(body)
        usage = body.get("usage", {})
        input_tokens, output_tokens = canonical_anthropic_usage_v1(usage)
        content = body.get("content", [])
        return ModelResponse(
            text="".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ),
            tool_calls=[ToolCall(
                id=part["id"], name=part["name"],
                arguments=part.get("input") or {},
            ) for part in content
              if isinstance(part, dict) and part.get("type") == "tool_use"],
            finish_reason=body.get("stop_reason"),
            input_tokens=input_tokens if input_tokens is not None else 0,
            output_tokens=output_tokens if output_tokens is not None else 0,
            raw_request_id=body.get("id"),
            provider_state={
                "content": content,
                "transport_complete": bool(
                    body.get("_protocol_complete", body.get("stop_reason") is not None)
                ),
                "protocol_terminal_event": body.get("_terminal_event"),
                "raw_finish_reason": body.get("stop_reason"),
                "POST_TERMINAL_PING_COUNT": body.get("_post_terminal_ping_count", 0),
                "POST_TERMINAL_PING_IGNORED_COUNT": body.get("_post_terminal_ping_count", 0),
                **(provider_state_extra or {}),
            },
        )

    @classmethod
    def replay_protocol_input_bytes_v1(
        cls, data: bytes, *, content_type: str, encoding: str = "utf-8",
    ) -> ModelResponse:
        """Replay immutable response bytes without a client or network seam."""

        events, body = parse_provider_protocol_input_bytes_v1(
            data, content_type=content_type, encoding=encoding, anthropic_errors=True,
        )
        if body is None:
            body = cls._aggregate_stream(events)
        response = cls._model_response_from_body(body)
        shape = provider_output_shape_from_response(cls, response)
        return response.model_copy(update={"output_shape": shape})

    @staticmethod
    def _validate_json_body(body: dict) -> None:
        """Validate the non-streaming Anthropic completion envelope."""

        if not isinstance(body, dict):
            raise AnthropicStreamProtocolError(
                "ANTHROPIC_JSON_RESPONSE_OBJECT_REQUIRED"
            )
        if "error" in body:
            raise AnthropicProviderTerminalError(evidence=normalize_stream_error_v1(body))
        if not isinstance(body.get("content"), list):
            raise AnthropicStreamProtocolError(
                "ANTHROPIC_JSON_CONTENT_INVALID"
            )
        stop_reason = body.get("stop_reason")
        if not isinstance(stop_reason, str) or not stop_reason:
            raise AnthropicStreamProtocolError(
                "ANTHROPIC_JSON_STOP_REASON_MISSING"
            )
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            raise AnthropicStreamProtocolError(
                "ANTHROPIC_JSON_USAGE_INVALID"
            )
        for block in body["content"]:
            if not isinstance(block, dict):
                raise AnthropicStreamProtocolError(
                    "ANTHROPIC_JSON_CONTENT_BLOCK_INVALID"
                )
            block_type = block.get("type")
            if block_type == "tool_use":
                if (
                    not isinstance(block.get("id"), str)
                    or not block["id"]
                    or not isinstance(block.get("name"), str)
                    or not block["name"]
                ):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_TOOL_USE_FIELDS_INVALID"
                    )
                if "input" in block and not isinstance(block["input"], dict):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_TOOL_ARGUMENTS_INVALID"
                    )
            elif block_type == "text" and not isinstance(
                block.get("text", ""), str
            ):
                raise AnthropicStreamProtocolError(
                    "ANTHROPIC_JSON_TEXT_BLOCK_INVALID"
                )

    def _replay_complete_valid_capture(
        self, original_error: BaseException,
    ) -> tuple[list[dict], dict] | None:
        """Reparse only a capture independently proven complete and valid."""

        if isinstance(
            original_error,
            (
                AnthropicStreamProtocolError,
                AnthropicStreamIncompleteError,
                AnthropicProviderTerminalError,
            ),
        ):
            return None
        try:
            replayed = self._replay_last_protocol_input_v1()
        except ProviderResponseCaptureError:
            return None
        if replayed is None:
            return None
        replay_events, replay_body = replayed
        try:
            if replay_body is None:
                replay_body = self._aggregate_stream(replay_events)
            else:
                self._validate_json_body(replay_body)
        except (
            AnthropicStreamProtocolError,
            AnthropicStreamIncompleteError,
            AnthropicProviderTerminalError,
        ):
            return None
        decision = decide_full_short_transport_recovery_v1(
            FullShortTransportEvidenceStateV1.COMPLETE_VALID_CAPTURE,
        )
        if not decision.exact_local_replay_allowed:
            return None
        return replay_events, replay_body

    def _stream_exception_snapshot(self, events: list[dict]):
        blocks: dict[int, dict] = {}
        arguments: dict[int, list[str]] = {}
        request_id = None
        finish_reason = None
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "message_start":
                message = event.get("message")
                if isinstance(message, dict) and isinstance(message.get("id"), str):
                    request_id = message["id"] or request_id
            elif kind == "content_block_start":
                index = event.get("index", len(blocks))
                block = event.get("content_block")
                if type(index) is not int or not isinstance(block, dict):
                    continue
                blocks[index] = block
                if block.get("type") == "tool_use":
                    arguments[index] = []
            elif kind == "content_block_delta":
                index = event.get("index", 0)
                delta = event.get("delta") or {}
                if type(index) is int and isinstance(delta, dict) and delta.get("type") == "input_json_delta":
                    part = delta.get("partial_json", "")
                    if isinstance(part, str):
                        arguments.setdefault(index, []).append(part)
            elif kind == "message_delta":
                delta = event.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                    finish_reason = delta["stop_reason"] or finish_reason
        calls = []
        for index, block in sorted(blocks.items()):
            if block.get("type") != "tool_use":
                continue
            raw_arguments = "".join(arguments.get(index, []))
            calls.append({
                "call_id": block.get("id"),
                "name": block.get("name"),
                "arguments_present": bool(raw_arguments) or "input" in block,
                "arguments": raw_arguments if raw_arguments else block.get("input"),
                "partial": True,
            })
        return provider_tool_shape_snapshot(
            adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
            adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
            provider_body=events,
            provider_request_id=request_id,
            content_block_count=len(blocks),
            text_present=any(
                block.get("type") == "text" for block in blocks.values()
            ),
            tool_use_present=bool(calls),
            finish_reason=finish_reason,
            calls=calls,
            snapshot_status="adapter_exception_with_snapshot",
        )

    @staticmethod
    def _aggregate_stream(events: list[dict]) -> dict:
        if isinstance(events, OwnedStreamEvents):
            return events.owner.body()
        stream = aggregate_events(events)
        stream.step(Event.EOF)
        return stream.body()
