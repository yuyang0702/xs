import json
import re
from pydantic import BaseModel

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.providers.base import ProviderAdapter
from novel_flywheel.providers.http import ToolCapabilityError


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

    @staticmethod
    def _parse_json(text: str) -> dict:
        candidate = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        return json.loads(candidate)

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
            structured_ok = parsed.get("ok") is True
        except (json.JSONDecodeError, AttributeError):
            structured_ok = False
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
            if not tool_response or not any(
                call.name == "probe_tool" for call in tool_response.tool_calls
            ):
                tool_response = await self.adapter.complete(
                    tool_request.model_copy(update={"required_tool": None})
                )
            tool_ok = any(call.name == "probe_tool" for call in tool_response.tool_calls)
            if not tool_ok:
                errors.append("工具检测：供应商没有返回测试工具调用")
        except Exception as exc:
            tool_ok = False
            errors.append(f"tools: {self._error(exc)}")
        return ProbeResult(
            chat=True, structured_output=structured_ok,
            tool_calling=tool_ok, error="; ".join(errors) or None,
        )
