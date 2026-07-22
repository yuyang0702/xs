from dataclasses import dataclass
import json
import time

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers.http import ToolCapabilityError


@dataclass(frozen=True)
class ModelResult:
    text: str
    receipt: dict


class ModelGateway:
    def __init__(self, db: Database, registry: ProviderRegistry) -> None:
        self.db = db
        self.registry = registry

    async def complete(self, role: str, system: str, user: str,
                       max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = self.registry.resolve(binding["primary_provider_id"], binding["primary_model_id"])
        response = await resolved.adapter.complete(ModelRequest(
            model=resolved.model_name,
            messages=[Message(role="system", content=system), Message(role="user", content=user)],
            max_output_tokens=max_output_tokens,
        ))
        return ModelResult(response.text, {
            "role": role,
            "provider_id": resolved.provider_id,
            "model_id": resolved.model_id,
            "model_name": resolved.model_name,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "request_id": response.raw_request_id,
        })

    async def complete_with_tools(self, role: str, system: str, user: str, toolbox,
                                  fallback_context, run_id: str | None = None,
                                  max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = self.registry.resolve(binding["primary_provider_id"], binding["primary_model_id"])
        mode = resolved.capabilities.get("tool_support", "auto")
        if mode == "disabled":
            return await self._fallback(role, system, user, fallback_context(), resolved, run_id,
                                        "configured disabled", max_output_tokens)
        messages = [Message(role="system", content=system), Message(role="user", content=user)]
        calls = 0
        input_tokens = output_tokens = 0
        try:
            for _ in range(8):
                response = await resolved.adapter.complete(ModelRequest(
                    model=resolved.model_name, messages=messages, tools=toolbox.definitions(),
                    max_output_tokens=max_output_tokens,
                ))
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
                if not response.tool_calls:
                    return ModelResult(response.text, self._receipt(
                        role, resolved, response, input_tokens, output_tokens,
                        "native_tools", calls,
                    ))
                calls += len(response.tool_calls)
                summaries = []
                for call in response.tool_calls:
                    started = time.perf_counter()
                    try:
                        result = toolbox.execute(call.name, call.arguments)
                        status = "succeeded"
                        error = None
                    except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
                        result = {"error": str(exc), "retryable": True}
                        status = "failed"
                        error = str(exc)
                    encoded = json.dumps(result, ensure_ascii=False)
                    self.db.save_tool_receipt(
                        run_id=run_id, stage=role, model_id=resolved.model_id,
                        execution_mode="native_tools", tool_name=call.name,
                        arguments=call.arguments, result_size=len(encoded),
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        status=status, fallback_reason=error,
                    )
                    summaries.append({"call_id": call.id, "tool": call.name, "result": result})
                messages.append(Message(role="assistant", content="Requested read-only story evidence."))
                messages.append(Message(role="user", content="TOOL RESULTS:\n" + json.dumps(summaries, ensure_ascii=False)))
            raise RuntimeError("Model exceeded the eight-round tool limit")
        except ToolCapabilityError as exc:
            if mode == "enabled":
                raise
            return await self._fallback(role, system, user, fallback_context(), resolved, run_id,
                                        str(exc), max_output_tokens)

    async def _fallback(self, role, system, user, evidence, resolved, run_id, reason,
                        max_output_tokens) -> ModelResult:
        response = await resolved.adapter.complete(ModelRequest(
            model=resolved.model_name,
            messages=[Message(role="system", content=system),
                      Message(role="user", content=f"{user}\n\nRETRIEVED EVIDENCE:\n{evidence}")],
            max_output_tokens=max_output_tokens,
        ))
        self.db.save_tool_receipt(
            run_id=run_id, stage=role, model_id=resolved.model_id,
            execution_mode="degraded_prompt_mode", status="succeeded", fallback_reason=reason,
        )
        receipt = self._receipt(role, resolved, response, response.input_tokens,
                                response.output_tokens, "degraded_prompt_mode", 0)
        receipt["fallback_reason"] = reason
        return ModelResult(response.text, receipt)

    @staticmethod
    def _receipt(role, resolved, response, input_tokens, output_tokens, mode, calls):
        return {
            "role": role, "provider_id": resolved.provider_id, "model_id": resolved.model_id,
            "model_name": resolved.model_name, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "request_id": response.raw_request_id,
            "execution_mode": mode, "tool_call_count": calls,
        }
