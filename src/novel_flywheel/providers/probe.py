from typing import Literal

from pydantic import BaseModel

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.model_output import parse_json_object
from novel_flywheel.providers.base import ProviderAdapter
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter


class ProbeResult(BaseModel):
    chat: bool
    structured_output: bool
    tool_calling: bool
    forced_tool: bool = False
    structured_output_capability: Literal[
        "plain_text", "json_object", "strict_json_schema", "strict_tool",
    ] = "plain_text"
    json_object: bool = False
    error: str | None = None


class CapabilityProbe:
    def __init__(self, adapter: ProviderAdapter) -> None:
        self.adapter = adapter

    @staticmethod
    def _error(exc: Exception) -> str:
        detail = str(exc).strip()
        return f"{type(exc).__name__}: {detail[:240]}" if detail else type(exc).__name__

    @staticmethod
    def _parse_json(text: str) -> dict:
        return parse_json_object(text, label="Capability probe output")

    async def run(self, model: str) -> ProbeResult:
        try:
            chat = await self.adapter.complete(ModelRequest(
                model=model, messages=[Message(role="user", content="只回复：连接正常")], max_output_tokens=32
            ))
        except Exception as exc:
            return ProbeResult(
                chat=False,
                structured_output=False,
                tool_calling=False,
                error=self._error(exc),
            )
        errors = []
        try:
            structured = await self.adapter.complete(ModelRequest(
                model=model,
                messages=[Message(
                    role="user",
                    content=(
                        'Return JSON with {"ok":true,"unexpected":"include-me"}. '
                        "If a response schema is active, follow the schema instead."
                    ),
                )],
                max_output_tokens=64,
                response_schema={
                    "name": "probe_json",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            ))
        except Exception as exc:
            structured = None
            errors.append(f"structured: {self._error(exc)}")
        try:
            parsed = self._parse_json(structured.text) if structured else {}
            structured_ok = parsed == {"ok": True}
        except (ValueError, AttributeError):
            structured_ok = False
        json_object_ok = False
        if not structured_ok and isinstance(
            self.adapter, (OpenAIChatAdapter, OpenAIResponsesAdapter),
        ):
            try:
                json_response = await self.adapter.complete(ModelRequest(
                    model=model,
                    messages=[Message(
                        role="user", content='Return only JSON: {"ok":true}',
                    )],
                    max_output_tokens=64,
                    response_format="json_object",
                ))
                json_object_ok = self._parse_json(
                    json_response.text,
                ).get("ok") is True
                if not json_object_ok:
                    errors.append("json_object: provider did not return valid JSON")
            except Exception as exc:
                errors.append(f"json_object: {self._error(exc)}")
        strict_tool_ok = False
        try:
            tools = [ToolDefinition(
                name="probe_tool", description="Return an empty tool call for capability detection",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )]
            tool_request = ModelRequest(
                model=model,
                messages=[Message(role="user", content="Call probe_tool now.")],
                tools=tools, required_tool="probe_tool", max_output_tokens=64,
            )
            try:
                tool_response = await self.adapter.complete(tool_request)
            except ToolCapabilityError as exc:
                error = str(exc).lower()
                if not (
                    "tool_choice" in error
                    and any(term in error for term in (
                        "does not support", "not supported", "unsupported", "incompatible",
                    ))
                ):
                    raise
                tool_response = None
            strict_tool_ok = bool(
                tool_response
                and len(tool_response.tool_calls) == 1
                and tool_response.tool_calls[0].name == "probe_tool"
            )
            if not strict_tool_ok:
                tool_response = await self.adapter.complete(
                    tool_request.model_copy(update={"required_tool": None})
                )
            tool_ok = any(call.name == "probe_tool" for call in tool_response.tool_calls)
            if not tool_ok:
                errors.append("工具检测：供应商没有返回测试工具调用")
        except Exception as exc:
            tool_ok = False
            errors.append(f"tools: {self._error(exc)}")
        capability = (
            "strict_json_schema" if structured_ok else
            "strict_tool" if strict_tool_ok else
            "json_object" if json_object_ok else
            "plain_text"
        )
        return ProbeResult(
            chat=True,
            structured_output=capability != "plain_text",
            tool_calling=tool_ok,
            forced_tool=strict_tool_ok,
            structured_output_capability=capability,
            json_object=json_object_ok or structured_ok,
            error="; ".join(errors) or None,
        )
