import hashlib
import json
from typing import Literal

import httpx
from pydantic import BaseModel

from novel_flywheel.domain.models import Message, ModelRequest, ToolDefinition
from novel_flywheel.failure_boundary import project_safe_failure
from novel_flywheel.generated_artifacts import GeneratedArtifactGateway
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
    protocol_capability: Literal[
        "plain_text", "json_object", "strict_json_schema", "strict_tool",
    ] = "plain_text"
    qualification_status: Literal[
        "unqualified", "protocol_only", "business_qualified",
    ] = "unqualified"
    verified_output_characters: int = 0
    qualification_schema_sha256: str = ""
    json_object: bool = False
    error: str | None = None
    diagnostic_code: Literal[
        "route_endpoint_not_found", "credentials_rejected", "rate_limited",
        "timeout", "connection_failed",
    ] | None = None


class CapabilityProbe:
    BUSINESS_NONCE = "novel-flywheel-business-qualification-v2"
    BUSINESS_ITEM_COUNT = 12
    BUSINESS_PAYLOAD_CHARACTERS = 96

    def __init__(self, adapter: ProviderAdapter) -> None:
        self.adapter = adapter

    @staticmethod
    def _error(exc: Exception) -> str:
        return project_safe_failure(
            exc, boundary="provider.capability_probe",
            code="provider.probe_failed", family="provider.request_failed",
            message="模型能力探测未完成。", retryable=True,
            recovery_action="verify_endpoint_and_retry_probe",
        ).persistence_summary()

    @staticmethod
    def _diagnostic_code(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                return "route_endpoint_not_found"
            if status_code in {401, 403}:
                return "credentials_rejected"
            if status_code == 429:
                return "rate_limited"
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        # Some third-party routers surface HTTP/transport failures through a
        # generic SDK exception. Classification is deliberately performed in
        # memory before the exception crosses the safe-failure boundary; the
        # raw provider text is never returned or persisted.
        diagnostic = str(exc).strip().casefold()
        if "404" in diagnostic or "not found" in diagnostic:
            return "route_endpoint_not_found"
        if any(token in diagnostic for token in ("401", "403", "unauthorized", "forbidden")):
            return "credentials_rejected"
        if "429" in diagnostic or "rate limit" in diagnostic:
            return "rate_limited"
        if "timeout" in diagnostic or "timed out" in diagnostic:
            return "timeout"
        return "connection_failed"

    @staticmethod
    def _parse_json(text: str) -> dict:
        return GeneratedArtifactGateway().convert_object(
            text, contract_name="capability_probe",
        ).payload

    @classmethod
    def _business_payload(cls) -> dict:
        items = []
        for ordinal in range(1, cls.BUSINESS_ITEM_COUNT + 1):
            prefix = f"item-{ordinal:02d}:"
            items.append({
                "ordinal": ordinal,
                "payload": prefix + "x" * (
                    cls.BUSINESS_PAYLOAD_CHARACTERS - len(prefix)
                ),
            })
        return {
            "probe_version": 2,
            "nonce": cls.BUSINESS_NONCE,
            "items": items,
            "complete": True,
        }

    @classmethod
    def _business_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "probe_version": {"type": "integer", "enum": [2]},
                "nonce": {"type": "string", "enum": [cls.BUSINESS_NONCE]},
                "items": {
                    "type": "array",
                    "minItems": cls.BUSINESS_ITEM_COUNT,
                    "maxItems": cls.BUSINESS_ITEM_COUNT,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ordinal": {
                                "type": "integer", "minimum": 1,
                                "maximum": cls.BUSINESS_ITEM_COUNT,
                            },
                            "payload": {
                                "type": "string",
                                "minLength": cls.BUSINESS_PAYLOAD_CHARACTERS,
                                "maxLength": cls.BUSINESS_PAYLOAD_CHARACTERS,
                            },
                        },
                        "required": ["ordinal", "payload"],
                        "additionalProperties": False,
                    },
                },
                "complete": {"type": "boolean", "enum": [True]},
            },
            "required": ["probe_version", "nonce", "items", "complete"],
            "additionalProperties": False,
        }

    @classmethod
    def _business_probe_prompt(cls) -> str:
        return (
            "Return exactly this JSON object with no wrapper or commentary. "
            "Do not shorten any payload string:\n"
            + json.dumps(cls._business_payload(), ensure_ascii=False)
        )

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
                diagnostic_code=self._diagnostic_code(exc),
            )
        errors = []
        expected = self._business_payload()
        business_schema = self._business_schema()
        schema_sha256 = hashlib.sha256(json.dumps(
            business_schema, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        expected_characters = len(json.dumps(
            expected, ensure_ascii=False, separators=(",", ":"),
        ))
        strict_schema_protocol = False
        try:
            structured = await self.adapter.complete(ModelRequest(
                model=model,
                messages=[Message(
                    role="user",
                    content=self._business_probe_prompt(),
                )],
                max_output_tokens=2048,
                response_schema={
                    "name": "business_qualification_probe",
                    "strict": True,
                    "schema": business_schema,
                },
            ))
        except Exception as exc:
            structured = None
            errors.append(f"structured: {self._error(exc)}")
        try:
            parsed = self._parse_json(structured.text) if structured else {}
            strict_schema_protocol = structured is not None and isinstance(parsed, dict)
            structured_ok = parsed == expected
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
                        role="user", content=self._business_probe_prompt(),
                    )],
                    max_output_tokens=2048,
                    response_format="json_object",
                ))
                json_payload = self._parse_json(json_response.text)
                json_object_protocol = isinstance(json_payload, dict)
                json_object_ok = json_payload == expected
                if not json_object_ok:
                    errors.append(
                        "json_object: provider did not return the complete "
                        "business qualification payload"
                    )
            except Exception as exc:
                json_object_protocol = False
                errors.append(f"json_object: {self._error(exc)}")
        else:
            json_object_protocol = False
        strict_tool_ok = False
        try:
            tools = [ToolDefinition(
                name="probe_tool",
                description="Return the complete business qualification payload",
                input_schema=business_schema,
            )]
            tool_request = ModelRequest(
                model=model, messages=[Message(
                    role="user", content=self._business_probe_prompt(),
                )],
                tools=tools, required_tool="probe_tool", max_output_tokens=2048,
            )
            try:
                tool_response = await self.adapter.complete(tool_request)
            except ToolCapabilityError:
                tool_response = None
            forced_tool_protocol = bool(
                tool_response
                and len(tool_response.tool_calls) == 1
                and tool_response.tool_calls[0].name == "probe_tool"
            )
            strict_tool_ok = bool(
                forced_tool_protocol
                and tool_response.tool_calls[0].arguments == expected
            )
            if not forced_tool_protocol:
                tool_response = await self.adapter.complete(
                    tool_request.model_copy(update={"required_tool": None})
                )
            tool_ok = any(call.name == "probe_tool" for call in tool_response.tool_calls)
            if not tool_ok:
                errors.append("工具检测：供应商没有返回测试工具调用")
        except Exception as exc:
            tool_ok = False
            forced_tool_protocol = False
            errors.append(f"tools: {self._error(exc)}")
        capability = (
            "strict_json_schema" if structured_ok else
            "strict_tool" if strict_tool_ok else
            "json_object" if json_object_ok else
            "plain_text"
        )
        protocol_capability = (
            "strict_json_schema" if strict_schema_protocol else
            "strict_tool" if forced_tool_protocol else
            "json_object" if json_object_protocol else
            "plain_text"
        )
        return ProbeResult(
            chat=True,
            structured_output=capability != "plain_text",
            tool_calling=tool_ok,
            forced_tool=forced_tool_protocol,
            structured_output_capability=capability,
            protocol_capability=protocol_capability,
            qualification_status=(
                "business_qualified" if capability != "plain_text" else
                "protocol_only" if (
                    protocol_capability != "plain_text" or tool_ok
                ) else "unqualified"
            ),
            verified_output_characters=(
                expected_characters if capability != "plain_text" else 0
            ),
            qualification_schema_sha256=schema_sha256,
            json_object=json_object_ok or structured_ok,
            error="; ".join(errors) or None,
            diagnostic_code=None,
        )
