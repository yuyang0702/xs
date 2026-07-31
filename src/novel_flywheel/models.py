from dataclasses import dataclass
import asyncio
import json
import time

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.errors import describe_error
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers.http import ToolCapabilityError


@dataclass(frozen=True)
class ModelResult:
    text: str
    receipt: dict


class ModelRoutesExhaustedError(RuntimeError):
    def __init__(self, primary_error: Exception, fallback_error: Exception) -> None:
        super().__init__(str(fallback_error))
        self.primary_error = primary_error
        self.fallback_error = fallback_error


class ModelGateway:
    CONNECT_RETRY_DELAY = 2

    def __init__(self, db: Database, registry: ProviderRegistry) -> None:
        self.db = db
        self.registry = registry

    async def complete(self, role: str, system: str, user: str,
                       max_output_tokens: int | None = None,
                       fallback_max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        primary_limit = self._route_output_limit(
            binding.get("primary_model_id"), max_output_tokens,
        )
        fallback_limit = self._route_output_limit(
            binding.get("fallback_model_id"),
            fallback_max_output_tokens if fallback_max_output_tokens is not None
            else max_output_tokens,
        )
        resolved = None
        try:
            resolved = self.registry.resolve(
                binding["primary_provider_id"], binding["primary_model_id"],
            )
            return await self._complete_resolved(
                role, system, user, resolved, primary_limit,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if resolved is not None and self._is_transient_connect_error(exc):
                await asyncio.sleep(self.CONNECT_RETRY_DELAY)
                try:
                    return await self._complete_resolved(
                        role, system, user, resolved, primary_limit,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    exc = retry_exc
            fallback = self._resolve_configured_fallback(binding)
            if fallback is None:
                raise
            try:
                result = await self._complete_resolved(
                    role, system, user, fallback, fallback_limit,
                )
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                raise ModelRoutesExhaustedError(exc, fallback_exc) from fallback_exc
            return self._mark_fallback(
                result, binding["primary_provider_id"], binding["primary_model_id"], exc,
            )

    async def complete_primary(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None,
    ) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = self.registry.resolve(
            binding["primary_provider_id"], binding["primary_model_id"],
        )
        return await self._complete_resolved(
            role, system, user, resolved,
            self._route_output_limit(binding.get("primary_model_id"), max_output_tokens),
        )

    async def complete_configured_fallback(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None,
    ) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        fallback = self._resolve_configured_fallback(binding)
        if fallback is None:
            raise LookupError(f"Model role has no configured fallback: {role}")
        result = await self._complete_resolved(
            role, system, user, fallback,
            self._route_output_limit(binding.get("fallback_model_id"), max_output_tokens),
        )
        return ModelResult(result.text, {
            **result.receipt, "configured_fallback_direct": True,
        })

    @staticmethod
    def _is_transient_connect_error(exc: Exception) -> bool:
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return False
        return any(marker in message for marker in (
            "connection attempts failed", "connection reset", "connection refused",
            "connecterror", "server disconnected",
        ))

    async def _complete_resolved(self, role, system, user, resolved,
                                 max_output_tokens) -> ModelResult:
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
            "finish_reason": response.finish_reason,
        })

    async def complete_with_tools(self, role: str, system: str, user: str, toolbox,
                                  fallback_context, run_id: str | None = None,
                                  max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        try:
            resolved = self.registry.resolve(
                binding["primary_provider_id"], binding["primary_model_id"],
            )
            return await self._complete_with_tools_resolved(
                role, system, user, toolbox, fallback_context, run_id,
                max_output_tokens, resolved,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fallback = self._resolve_configured_fallback(binding)
            if fallback is None:
                raise
            result = await self._complete_with_tools_resolved(
                role, system, user, toolbox, fallback_context, run_id,
                max_output_tokens, fallback,
            )
            return self._mark_fallback(
                result, binding["primary_provider_id"], binding["primary_model_id"], exc,
            )

    async def _complete_with_tools_resolved(
        self, role, system, user, toolbox, fallback_context, run_id,
        max_output_tokens, resolved,
    ) -> ModelResult:
        mode = resolved.capabilities.get("tool_support", "auto")
        if mode == "disabled":
            return await self._fallback(role, system, user, fallback_context(), resolved, run_id,
                                        "configured disabled", max_output_tokens)
        messages = [Message(role="system", content=system), Message(role="user", content=user)]
        calls = 0
        input_tokens = output_tokens = 0
        tool_definitions = toolbox.definitions()
        finalize = getattr(toolbox, "finalize_on_tool_limit", None)
        controlled_runtime = callable(finalize) or any(
            definition.name == "complete_skill" for definition in tool_definitions
        )
        round_limit = 8 if controlled_runtime else 4
        try:
            for round_index in range(round_limit):
                request_tools = tool_definitions
                if round_index == round_limit - 1:
                    if controlled_runtime:
                        final_instruction = (
                            "FINAL TOOL ROUND: Stop reading. Complete required proposals now and "
                            "call complete_skill. Do not request more evidence."
                        )
                    else:
                        final_instruction = (
                            "FINAL RESPONSE: Stop calling tools. Use the evidence already retrieved and "
                            "produce the complete requested output now."
                        )
                        request_tools = []
                    messages.append(Message(role="user", content=final_instruction))
                response = await resolved.adapter.complete(ModelRequest(
                    model=resolved.model_name, messages=messages, tools=request_tools,
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
                completion_summary = None
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
                    if (call.name == "complete_skill" and status == "succeeded"
                            and result.get("status") == "validating"):
                        completion_summary = str(result.get("summary", ""))
                if completion_summary is not None:
                    return ModelResult(completion_summary, self._receipt(
                        role, resolved, response, input_tokens, output_tokens,
                        "native_tools", calls,
                    ))
                messages.append(Message(role="assistant", content="Requested read-only story evidence."))
                messages.append(Message(role="user", content="TOOL RESULTS:\n" + json.dumps(summaries, ensure_ascii=False)))
            summary = finalize() if finalize else None
            if summary is not None:
                return ModelResult(summary, self._receipt(
                    role, resolved, response, input_tokens, output_tokens,
                    "native_tools", calls,
                ))
            raise RuntimeError("Model exceeded the eight-round tool limit")
        except ToolCapabilityError as exc:
            if mode == "enabled":
                raise
            return await self._fallback(role, system, user, fallback_context(), resolved, run_id,
                                        str(exc), max_output_tokens)

    def _resolve_configured_fallback(self, binding):
        provider_id = binding.get("fallback_provider_id")
        model_id = binding.get("fallback_model_id")
        if not provider_id or not model_id:
            return None
        return self.registry.resolve(provider_id, model_id)

    def _route_output_limit(self, model_id: str | None,
                            requested: int | None) -> int | None:
        if requested is None:
            return None
        model = self.db.get_model(model_id or "") or {}
        ceiling = model.get("max_output_tokens")
        if isinstance(ceiling, int) and ceiling > 0:
            return min(requested, ceiling)
        return requested

    @staticmethod
    def _mark_fallback(
        result: ModelResult, primary_provider_id: str, primary_model_id: str,
        error: Exception,
    ) -> ModelResult:
        return ModelResult(result.text, {
            **result.receipt,
            "fallback_used": True,
            "fallback_from_provider_id": primary_provider_id,
            "fallback_from_model_id": primary_model_id,
            "primary_error": describe_error(error),
        })

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
            "finish_reason": response.finish_reason,
            "execution_mode": mode, "tool_call_count": calls,
        }
