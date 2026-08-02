import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
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
        if request.tools:
            payload["tools"] = [{
                "type": "function", "name": tool.name, "description": tool.description,
                "parameters": tool.input_schema,
            } for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {"type": "function", "name": request.required_tool}
        payload["stream"] = True
        events, body = await self.post_stream(
            "responses", payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        streamed_text = ""
        if body is None:
            body, streamed_text = self._aggregate_stream(events)
        usage = body.get("usage", {})
        output = body.get("output", [])
        raw_finish_reason = body.get("status")
        incomplete_reason = (body.get("incomplete_details") or {}).get("reason")
        finish_reason = raw_finish_reason
        if raw_finish_reason == "incomplete":
            finish_reason = (
                "max_tokens"
                if incomplete_reason in {"max_output_tokens", "max_tokens"}
                else incomplete_reason or "incomplete"
            )
        return ModelResponse(
            text=_output_text(body) or streamed_text,
            tool_calls=[ToolCall(
                id=item.get("call_id") or item.get("id"), name=item["name"],
                arguments=json.loads(item.get("arguments") or "{}"),
            ) for item in output if item.get("type") == "function_call"],
            finish_reason=finish_reason,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            raw_request_id=body.get("id"),
            provider_state={
                "output": output,
                "transport_complete": raw_finish_reason in {
                    "completed", "incomplete", "failed", "cancelled",
                },
                "raw_finish_reason": raw_finish_reason,
                "incomplete_reason": incomplete_reason,
            },
        )

    @staticmethod
    def _aggregate_stream(events: list[dict]) -> tuple[dict, str]:
        text: list[str] = []
        response: dict = {}
        for event in events:
            if event.get("type") == "response.output_text.delta":
                text.append(event.get("delta", ""))
            elif event.get("type") in {"response.completed", "response.incomplete", "response.failed"}:
                response = event.get("response") or response
            elif event.get("type") == "response.created":
                response = {**(event.get("response") or {}), **response}
        return response, "".join(text)
