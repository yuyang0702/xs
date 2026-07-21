import json
from pydantic import BaseModel

from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.base import ProviderAdapter


class ProbeResult(BaseModel):
    chat: bool
    structured_output: bool
    error: str | None = None


class CapabilityProbe:
    def __init__(self, adapter: ProviderAdapter) -> None:
        self.adapter = adapter

    async def run(self, model: str) -> ProbeResult:
        try:
            chat = await self.adapter.complete(ModelRequest(
                model=model, messages=[Message(role="user", content="只回复：连接正常")], max_output_tokens=32
            ))
            structured = await self.adapter.complete(ModelRequest(
                model=model,
                messages=[Message(role="user", content='只输出 JSON：{"ok":true}')],
                max_output_tokens=64,
            ))
        except Exception as exc:
            return ProbeResult(chat=False, structured_output=False, error=type(exc).__name__)
        try:
            parsed = json.loads(structured.text)
            structured_ok = parsed.get("ok") is True
        except (json.JSONDecodeError, AttributeError):
            structured_ok = False
        return ProbeResult(chat=bool(chat.text.strip()), structured_output=structured_ok)

