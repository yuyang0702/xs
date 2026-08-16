import json

from novel_flywheel.domain.models import ModelRequest, ModelResponse, ToolCall
from novel_flywheel.model_diagnostics import (
    attach_exception_snapshot,
    provider_snapshot_with_status,
    provider_tool_shape_snapshot,
    strict_snapshot_capture_requested,
)
from novel_flywheel.planning_repair_diagnostics import (
    attach_provider_content_snapshot,
    finalize_provider_content_block_snapshot,
    safe_capture_provider_content_block_snapshot,
)
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
    DIAGNOSTIC_ADAPTER_ID = "openai_responses"
    DIAGNOSTIC_ADAPTER_VERSION = 1

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
        elif request.response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
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
        nested_content = [
            part
            for item in output if isinstance(item, dict)
            for part in (item.get("content") or []) if isinstance(part, dict)
        ]
        content_snapshot = safe_capture_provider_content_block_snapshot(
            adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
            adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
            protocol="openai-responses",
            provider_response=body,
            request_max_output_tokens=request.max_output_tokens,
            finish_reason=finish_reason,
            output_tokens=usage.get("output_tokens", 0),
            block_types=(
                [
                    item.get("type") for item in output if isinstance(item, dict)
                ]
                + [part.get("type") for part in nested_content]
                + (["output_text"] if streamed_text else [])
            ),
            text_values=([streamed_text] if streamed_text else []) + [
                part.get("text")
                for part in nested_content
                if part.get("type") in {"output_text", "text"}
            ],
            tool_arguments=[
                item.get("arguments") for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"
            ],
            tool_argument_presence=any(
                "arguments" in item for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"
            ),
            reasoning_block_count=sum(
                item.get("type") in {"reasoning", "thinking"}
                for item in output if isinstance(item, dict)
            ),
        )
        snapshot = None
        if strict_snapshot_capture_requested():
            raw_calls = [
                item for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"
            ]
            call_inputs = [{
                "call_id": item.get("call_id") or item.get("id"),
                "name": item.get("name"),
                "arguments_present": "arguments" in item,
                "arguments": item.get("arguments"),
                "partial": not bool(item.get("name")) or "arguments" not in item,
            } for item in raw_calls]
            status = (
                "snapshot_partial"
                if raw_finish_reason == "incomplete"
                or any(item["partial"] for item in call_inputs)
                else "snapshot_exact"
            )
            snapshot = provider_tool_shape_snapshot(
                adapter_id=self.DIAGNOSTIC_ADAPTER_ID,
                adapter_version=self.DIAGNOSTIC_ADAPTER_VERSION,
                provider_body=body,
                provider_request_id=body.get("id"),
                content_block_count=len(output),
                text_present=bool(_output_text(body) or streamed_text),
                tool_use_present=bool(call_inputs),
                finish_reason=finish_reason,
                calls=call_inputs,
                snapshot_status=status,
            )
        try:
            response = ModelResponse(
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
                    **({
                        "_r1_pa1_tool_shape_snapshot": snapshot.model_dump(
                            mode="json", by_alias=True,
                        ),
                    } if snapshot is not None else {}),
                },
            )
            if content_snapshot is not None:
                try:
                    content_snapshot = finalize_provider_content_block_snapshot(
                        content_snapshot,
                        normalized_text=response.text,
                        normalized_tool_call_count=len(response.tool_calls),
                    )
                    response = response.model_copy(update={
                        "provider_state": {
                            **response.provider_state,
                            "_r1_ptr1_provider_content_snapshot": (
                                content_snapshot.model_dump(
                                    mode="json", by_alias=True,
                                )
                            ),
                        },
                    })
                except Exception:
                    pass
            return response
        except Exception as exc:
            if snapshot is not None:
                attach_exception_snapshot(
                    exc, provider_snapshot_with_status(
                        snapshot, "adapter_exception_with_snapshot",
                    ),
                )
            if content_snapshot is not None:
                attach_provider_content_snapshot(exc, content_snapshot)
            raise

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
