from novel_flywheel.domain.models import ModelRequest, ModelResponse
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
        body = await self.post("messages", payload=payload, headers={
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        usage = body.get("usage", {})
        return ModelResponse(
            text="".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text"),
            finish_reason=body.get("stop_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            raw_request_id=body.get("id"),
        )
