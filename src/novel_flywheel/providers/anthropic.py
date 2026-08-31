import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
from novel_flywheel.provider_response_capture import (
    FullShortTransportEvidenceStateV1,
    ProviderResponseCaptureError,
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


class AnthropicStreamProtocolError(RuntimeError):
    """A complete HTTP entity violates the Anthropic SSE state contract."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_sse_protocol_invalid",
            failure_class=FailureClass.SYNTAX_PROTOCOL,
            boundary="anthropic_sse_state_machine",
            message=reason_code,
            retryable=False,
        )
        super().__init__(reason_code)


class AnthropicStreamIncompleteError(RuntimeError):
    """The captured entity ended without the provider's terminal message."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_sse_terminal_missing",
            failure_class=FailureClass.TRANSPORT,
            boundary="anthropic_sse_state_machine",
            message=reason_code,
            retryable=False,
        )
        super().__init__(reason_code)


class AnthropicProviderTerminalError(RuntimeError):
    """The provider emitted an explicit terminal error event."""

    def __init__(self, error_type: str) -> None:
        self.error_type = error_type or "provider_error"
        self.reliability_failure = ReliabilityFailure(
            code="anthropic_provider_terminal_error",
            failure_class=FailureClass.UNKNOWN,
            boundary="anthropic_sse_state_machine",
            message=self.error_type,
            retryable=False,
        )
        super().__init__("provider emitted an explicit terminal error")


class AnthropicAdapter(HttpProvider):
    DIAGNOSTIC_ADAPTER_ID = "anthropic"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._bind_model_request("anthropic", request)
        system = "\n\n".join(message.content for message in request.messages if message.role == "system")
        payload = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages if message.role != "system"],
            "max_tokens": request.max_output_tokens or 8192,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_schema is not None:
            schema = request.response_schema.get(
                "schema", request.response_schema,
            )
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": schema},
            }
        if request.tools:
            payload["tools"] = [{
                "name": tool.name, "description": tool.description, "input_schema": tool.input_schema,
            } for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {"type": "tool", "name": request.required_tool}
        auth_headers = ({"Authorization": f"Bearer {self.api_key}"}
                        if self.auth_type == "bearer" else {"x-api-key": self.api_key})
        path = "messages" if self.base_url.endswith("/v1") else "v1/messages"
        payload["stream"] = True
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
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            raw_request_id=body.get("id"),
            provider_state={
                "content": content,
                "transport_complete": bool(
                    body.get("_protocol_complete", body.get("stop_reason") is not None)
                ),
                "protocol_terminal_event": body.get("_terminal_event"),
                "raw_finish_reason": body.get("stop_reason"),
                **(provider_state_extra or {}),
            },
        )

    @classmethod
    def replay_protocol_input_bytes_v1(
        cls, data: bytes, *, content_type: str, encoding: str = "utf-8",
    ) -> ModelResponse:
        """Replay immutable response bytes without a client or network seam."""

        events, body = parse_provider_protocol_input_bytes_v1(
            data, content_type=content_type, encoding=encoding,
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
            error = body.get("error")
            error_type = error.get("type") if isinstance(error, dict) else ""
            raise AnthropicProviderTerminalError(str(error_type or ""))
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
            kind = event.get("type")
            if kind == "message_start":
                request_id = (event.get("message") or {}).get("id") or request_id
            elif kind == "content_block_start":
                index = event.get("index", len(blocks))
                block = dict(event.get("content_block") or {})
                blocks[index] = block
                if block.get("type") == "tool_use":
                    arguments[index] = []
            elif kind == "content_block_delta":
                index = event.get("index", 0)
                delta = event.get("delta") or {}
                if delta.get("type") == "input_json_delta":
                    arguments.setdefault(index, []).append(delta.get("partial_json", ""))
            elif kind == "message_delta":
                finish_reason = (event.get("delta") or {}).get("stop_reason") or finish_reason
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
        message_id = None
        input_tokens = 0
        output_tokens = 0
        stop_reason = None
        blocks: dict[int, dict] = {}
        tool_json: dict[int, list[str]] = {}
        open_blocks: set[int] = set()
        message_started = False
        message_stopped = False
        message_delta_seen = False
        for event in events:
            kind = event.get("type")
            if message_stopped:
                raise AnthropicStreamProtocolError(
                    "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_STOP"
                )
            if message_delta_seen and kind not in {"ping", "message_stop"}:
                raise AnthropicStreamProtocolError(
                    "ANTHROPIC_SSE_EVENT_AFTER_MESSAGE_DELTA"
                )
            if kind == "error":
                error = event.get("error") or {}
                raise AnthropicProviderTerminalError(str(error.get("type") or ""))
            if kind == "message_start":
                if message_started:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_DUPLICATE_MESSAGE_START"
                    )
                message_started = True
                message = event.get("message") or {}
                message_id = message.get("id")
                input_tokens = (message.get("usage") or {}).get("input_tokens", 0)
            elif kind == "content_block_start":
                if not message_started:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_BLOCK_BEFORE_MESSAGE_START"
                    )
                index = event.get("index")
                if type(index) is not int or index < 0:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_INVALID"
                    )
                if index in blocks or index in open_blocks:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_DUPLICATE_CONTENT_BLOCK"
                    )
                if index != len(blocks):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_NONCONTIGUOUS"
                    )
                if open_blocks:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_START_BEFORE_STOP"
                    )
                raw_block = event.get("content_block")
                if not isinstance(raw_block, dict):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_INVALID"
                    )
                block = dict(raw_block)
                if block.get("type") not in {
                    "text", "tool_use", "thinking", "redacted_thinking",
                }:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_TYPE_UNSUPPORTED"
                    )
                if block.get("type") == "tool_use" and (
                    not isinstance(block.get("id"), str)
                    or not block["id"]
                    or not isinstance(block.get("name"), str)
                    or not block["name"]
                ):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_TOOL_USE_FIELDS_INVALID"
                    )
                blocks[index] = block
                open_blocks.add(index)
                if block.get("type") == "tool_use":
                    tool_json[index] = []
            elif kind == "content_block_delta":
                index = event.get("index")
                if type(index) is not int or index < 0:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_INVALID"
                    )
                if index not in open_blocks:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_DELTA_OUTSIDE_CONTENT_BLOCK"
                    )
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_DELTA_INVALID"
                    )
                block_type = blocks[index].get("type")
                delta_type = delta.get("type")
                allowed_deltas = {
                    "text": {"text_delta"},
                    "tool_use": {"input_json_delta"},
                    "thinking": {"thinking_delta", "signature_delta"},
                    "redacted_thinking": set(),
                }
                if delta_type not in allowed_deltas[block_type]:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_DELTA_TYPE_MISMATCH"
                    )
                if delta_type == "text_delta":
                    blocks[index]["text"] = (
                        str(blocks[index].get("text") or "")
                        + str(delta.get("text") or "")
                    )
                elif delta_type == "input_json_delta":
                    partial_json = delta.get("partial_json")
                    if not isinstance(partial_json, str):
                        raise AnthropicStreamProtocolError(
                            "ANTHROPIC_SSE_TOOL_ARGUMENT_DELTA_INVALID"
                        )
                    tool_json.setdefault(index, []).append(partial_json)
            elif kind == "content_block_stop":
                index = event.get("index")
                if type(index) is not int or index < 0:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_INDEX_INVALID"
                    )
                if index not in open_blocks:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_CONTENT_BLOCK_STOP_UNBALANCED"
                    )
                open_blocks.remove(index)
            elif kind == "message_delta":
                if not message_started or open_blocks or message_delta_seen:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_MESSAGE_DELTA_STATE_INVALID"
                    )
                message_delta_seen = True
                stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                output_tokens = (event.get("usage") or {}).get("output_tokens", output_tokens)
            elif kind == "message_stop":
                if (
                    not message_started or open_blocks or not message_delta_seen
                    or not stop_reason
                ):
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_MESSAGE_STOP_STATE_INVALID"
                    )
                message_stopped = True
            elif kind != "ping":
                raise AnthropicStreamProtocolError(
                    "ANTHROPIC_SSE_EVENT_TYPE_UNSUPPORTED"
                )
        if not message_stopped:
            raise AnthropicStreamIncompleteError(
                "ANTHROPIC_SSE_MESSAGE_STOP_MISSING"
            )
        for index, parts in tool_json.items():
            raw = "".join(parts)
            if raw:
                try:
                    blocks[index]["input"] = json.loads(raw)
                except ValueError as exc:
                    raise AnthropicStreamProtocolError(
                        "ANTHROPIC_SSE_TOOL_ARGUMENT_JSON_INVALID"
                    ) from exc
        return {
            "id": message_id, "content": [blocks[index] for index in sorted(blocks)],
            "stop_reason": stop_reason,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "_protocol_complete": True,
            "_terminal_event": "message_stop",
        }
