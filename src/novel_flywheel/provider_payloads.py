"""Pure provider wire-payload projections shared by adapters and egress guards."""

from __future__ import annotations

from typing import Any

from novel_flywheel.domain.models import ModelRequest


def anthropic_payload_v1(request: ModelRequest) -> dict[str, Any]:
    system = "\n\n".join(
        message.content for message in request.messages
        if message.role == "system"
    )
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [
            message.model_dump() for message in request.messages
            if message.role != "system"
        ],
        "max_tokens": request.max_output_tokens or 8192,
    }
    if system:
        payload["system"] = system
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.response_schema is not None:
        schema = request.response_schema.get("schema", request.response_schema)
        payload["output_config"] = {
            "format": {"type": "json_schema", "schema": schema},
        }
    if request.tools:
        payload["tools"] = [{
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        } for tool in request.tools]
    if request.required_tool:
        payload["tool_choice"] = {
            "type": "tool", "name": request.required_tool,
        }
    if request.reasoning_directive == "disable_reasoning":
        payload["reasoning"] = {"effort": "none"}
    payload["stream"] = True
    return payload

