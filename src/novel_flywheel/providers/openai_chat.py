import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
from novel_flywheel.model_diagnostics import (
    attach_exception_snapshot,
    provider_snapshot_with_status,
    provider_tool_shape_snapshot,
    strict_snapshot_capture_requested,
)
from novel_flywheel.providers.http import HttpProvider


class OpenAIChatAdapter(HttpProvider):
    DIAGNOSTIC_ADAPTER_ID = "openai_chat"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    async def complete(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": request.response_schema}
        elif request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": tool.input_schema,
            }} for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function", "function": {"name": request.required_tool},
            }
        if "api.moonshot.cn" in self.base_url and (
            request.required_tool or request.response_schema or request.response_format
        ):
            payload["thinking"] = {"type": "disabled"}
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        events, body = await self.post_stream(
            "chat/completions", payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if body is None:
            body = self._aggregate_stream(events)
        choice = body["choices"][0]
        usage = body.get("usage", {})
        message = choice["message"]
        snapshot = None
        if strict_snapshot_capture_requested():
            raw_calls = message.get("tool_calls", [])
            raw_calls = raw_calls if isinstance(raw_calls, list) else []
            call_inputs = []
            for call in raw_calls:
                function = call.get("function") if isinstance(call, dict) else None
                function = function if isinstance(function, dict) else {}
                call_inputs.append({
                    "call_id": call.get("id") if isinstance(call, dict) else None,
                    "name": function.get("name"),
                    "arguments_present": "arguments" in function,
                    "arguments": function.get("arguments"),
                    "partial": not bool(function.get("name")) or "arguments" not in function,
                })
            status = (
                "snapshot_partial"
                if choice.get("finish_reason") in {"length", "max_tokens"}
                or any(item["partial"] for item in call_inputs)
                else "snapshot_exact"
            )
            snapshot = provider_tool_shape_snapshot(
                adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
                adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
                provider_body=body,
                provider_request_id=body.get("id"),
                content_block_count=(
                    len(call_inputs) + (1 if message.get("content") else 0)
                ),
                text_present=bool(message.get("content")),
                tool_use_present=bool(call_inputs),
                finish_reason=choice.get("finish_reason"),
                calls=call_inputs,
                snapshot_status=status,
            )
        try:
            return ModelResponse(
                text=message.get("content") or "",
                tool_calls=[ToolCall(
                    id=call["id"], name=call["function"]["name"],
                    arguments=json.loads(call["function"].get("arguments") or "{}"),
                ) for call in message.get("tool_calls", [])],
                finish_reason=choice.get("finish_reason"),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                raw_request_id=body.get("id"),
                provider_state={
                    "assistant": message,
                    "transport_complete": choice.get("finish_reason") is not None,
                    "raw_finish_reason": choice.get("finish_reason"),
                    **({
                        "_r1_pa1_tool_shape_snapshot": snapshot.model_dump(
                            mode="json", by_alias=True,
                        ),
                    } if snapshot is not None else {}),
                },
            )
        except Exception as exc:
            if snapshot is not None:
                attach_exception_snapshot(
                    exc, provider_snapshot_with_status(
                        snapshot, "adapter_exception_with_snapshot",
                    ),
                )
            raise

    @staticmethod
    def _aggregate_stream(events: list[dict]) -> dict:
        text: list[str] = []
        tools: dict[int, dict] = {}
        request_id = None
        finish_reason = None
        usage: dict = {}
        for event in events:
            request_id = event.get("id") or request_id
            usage = event.get("usage") or usage
            for choice in event.get("choices", []):
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str):
                    text.append(delta["content"])
                for call in delta.get("tool_calls") or []:
                    item = tools.setdefault(call.get("index", len(tools)), {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    item["id"] = call.get("id") or item["id"]
                    function = call.get("function") or {}
                    item["function"]["name"] += function.get("name") or ""
                    item["function"]["arguments"] += function.get("arguments") or ""
        return {
            "id": request_id,
            "choices": [{"message": {"content": "".join(text), "tool_calls": list(tools.values())},
                         "finish_reason": finish_reason}],
            "usage": usage,
        }
