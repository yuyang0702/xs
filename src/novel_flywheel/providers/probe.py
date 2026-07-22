import json
from pydantic import BaseModel

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.providers.base import ProviderAdapter


class ProbeResult(BaseModel):
    chat: bool
    structured_output: bool
    tool_calling: bool
    error: str | None = None


class CapabilityProbe:
    def __init__(self, adapter: ProviderAdapter) -> None:
        self.adapter = adapter

    @staticmethod
    def _error(exc: Exception) -> str:
        detail = str(exc).strip()
        return f"{type(exc).__name__}: {detail[:240]}" if detail else type(exc).__name__

    async def run(self, model: str) -> ProbeResult:
        try:
            chat = await self.adapter.complete(ModelRequest(
                model=model, messages=[Message(role="user", content="只回复：连接正常")], max_output_tokens=32
            ))
        except Exception as exc:
            return ProbeResult(chat=False, structured_output=False, tool_calling=False,
                               error=self._error(exc))
        errors = []
        try:
            structured = await self.adapter.complete(ModelRequest(
                model=model,
                messages=[Message(role="user", content='只输出 JSON：{"ok":true}')],
                max_output_tokens=64,
            ))
        except Exception as exc:
            structured = None
            errors.append(f"structured: {self._error(exc)}")
        try:
            parsed = json.loads(structured.text) if structured else {}
            structured_ok = parsed.get("ok") is True
        except (json.JSONDecodeError, AttributeError):
            structured_ok = False
        try:
            tools = [ToolDefinition(
                name="probe_tool", description="Return an empty tool call for capability detection",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )]
            tool_response = await self.adapter.complete(ModelRequest(
                model=model,
                messages=[Message(role="user", content="Call probe_tool now.")],
                tools=tools, max_output_tokens=64,
            ))
            tool_ok = any(call.name == "probe_tool" for call in tool_response.tool_calls)
        except Exception as exc:
            tool_ok = False
            errors.append(f"tools: {self._error(exc)}")
        return ProbeResult(
            chat=bool(chat.text.strip()), structured_output=structured_ok,
            tool_calling=tool_ok, error="; ".join(errors) or None,
        )
