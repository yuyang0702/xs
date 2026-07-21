from novel_flywheel.domain.models import ModelRequest, ModelResponse
from novel_flywheel.providers.http import HttpProvider


def _output_text(body: dict) -> str:
    if body.get("output_text"):
        return body["output_text"]
    parts: list[str] = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(content.get("text", ""))
    return "".join(parts)


class OpenAIResponsesAdapter(HttpProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": request.model,
            "input": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["text"] = {"format": {"type": "json_schema", **request.response_schema}}
        body = await self.post("responses", payload=payload,
                               headers={"Authorization": f"Bearer {self.api_key}"})
        usage = body.get("usage", {})
        return ModelResponse(
            text=_output_text(body),
            finish_reason=body.get("status"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            raw_request_id=body.get("id"),
        )

