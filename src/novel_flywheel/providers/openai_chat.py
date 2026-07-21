from novel_flywheel.domain.models import ModelRequest, ModelResponse
from novel_flywheel.providers.http import HttpProvider


class OpenAIChatAdapter(HttpProvider):
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
        body = await self.post("chat/completions", payload=payload,
                               headers={"Authorization": f"Bearer {self.api_key}"})
        choice = body["choices"][0]
        usage = body.get("usage", {})
        return ModelResponse(
            text=choice["message"].get("content") or "",
            finish_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw_request_id=body.get("id"),
        )

