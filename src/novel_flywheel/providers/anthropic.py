import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
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
from novel_flywheel.provider_output import capture_provider_raw_shape_v1


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
        try:
            response = ModelResponse(
                text="".join(part.get("text", "") for part in content if part.get("type") == "text"),
                tool_calls=[ToolCall(
                    id=part["id"], name=part["name"], arguments=part.get("input") or {},
                ) for part in content if part.get("type") == "tool_use"],
                finish_reason=body.get("stop_reason"),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                raw_request_id=body.get("id"),
                provider_state={
                    "content": content,
                    "transport_complete": body.get("stop_reason") is not None,
                    "raw_finish_reason": body.get("stop_reason"),
                    **({
                        "_r1_pa1_tool_shape_snapshot": snapshot.model_dump(
                            mode="json", by_alias=True,
                        ),
                    } if snapshot is not None else {}),
                },
            )
            if content_snapshot is not None:
                try:
                    content_snapshot = finalize_provider_content_block_snapshot(
                        content_snapshot,
                        normalized_text=response.text,
                        normalized_tool_call_count=len(response.tool_calls),
                    )
                    response = response.model_copy(update={
                        "provider_state": {
                            **response.provider_state,
                            "_r1_ptr1_provider_content_snapshot": (
                                content_snapshot.model_dump(
                                    mode="json", by_alias=True,
                                )
                            ),
                        },
                    })
                except Exception:
                    pass
            return response
        except Exception as exc:
            if snapshot is not None:
                attach_exception_snapshot(
                    exc, provider_snapshot_with_status(
                        snapshot, "adapter_exception_with_snapshot",
                    ),
                )
            if content_snapshot is not None:
                attach_provider_content_snapshot(exc, content_snapshot)
            raise

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
        for event in events:
            kind = event.get("type")
            if kind == "message_start":
                message = event.get("message") or {}
                message_id = message.get("id")
                input_tokens = (message.get("usage") or {}).get("input_tokens", 0)
            elif kind == "content_block_start":
                index = event.get("index", len(blocks))
                block = dict(event.get("content_block") or {})
                blocks[index] = block
                if block.get("type") == "tool_use":
                    tool_json[index] = []
            elif kind == "content_block_delta":
                index = event.get("index", 0)
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    blocks.setdefault(index, {"type": "text", "text": ""})["text"] += delta.get("text", "")
                elif delta.get("type") == "input_json_delta":
                    tool_json.setdefault(index, []).append(delta.get("partial_json", ""))
            elif kind == "message_delta":
                stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                output_tokens = (event.get("usage") or {}).get("output_tokens", output_tokens)
        for index, parts in tool_json.items():
            raw = "".join(parts)
            if raw:
                blocks[index]["input"] = json.loads(raw)
        return {
            "id": message_id, "content": [blocks[index] for index in sorted(blocks)],
            "stop_reason": stop_reason,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
