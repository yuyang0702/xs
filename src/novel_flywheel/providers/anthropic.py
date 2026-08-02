import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
from novel_flywheel.providers.http import HttpProvider


class AnthropicAdapter(HttpProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
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
        if body is None:
            body = self._aggregate_stream(events)
        usage = body.get("usage", {})
        content = body.get("content", [])
        return ModelResponse(
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
            },
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
