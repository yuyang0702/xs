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
        body = await self.post(path, payload=payload, headers={
            **auth_headers, "anthropic-version": "2023-06-01",
        })
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
            provider_state={"content": content},
        )
