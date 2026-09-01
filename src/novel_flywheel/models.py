from dataclasses import dataclass
import asyncio
import hashlib
import inspect
import json
import time
from typing import Literal

import httpx

from novel_flywheel.db import Database
from novel_flywheel.domain.models import (
    Message,
    ModelRequest,
    ModelResponse,
    ProviderOutputShapeV1,
    ToolDefinition,
)
from novel_flywheel.failure_boundary import (
    project_safe_failure,
    safe_local_validation_message,
)
from novel_flywheel.context_policy import classify_model_failure, normalize_finish_reason
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1,
    bind_ptr12_raw_shape_observation,
    bind_diagnostic_context,
    build_ptr12_guard_decision,
    current_ptr12_raw_shape,
    observe_strict_tool_shape,
    observe_ptr12_shape_delta,
    open_ptr12_raw_shape_capture,
    reset_ptr12_raw_shape_capture,
    reset_bound_diagnostic_context,
)
from novel_flywheel.planning_repair_diagnostics import (
    observe_provider_content_block_shape,
)
from novel_flywheel.provider_output import provider_output_shape_from_response
from novel_flywheel.provider_reasoning_policy import (
    PLANNING_FINAL_ARTIFACT_RECOVERY,
    ReasoningPolicy,
    resolve_provider_reasoning_directive_v1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers.http import ToolCapabilityError
from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputCapability,
    StructuredOutputCapabilityError,
    StructuredOutputRequirement,
    capability_satisfies,
    configured_structured_output_capability,
)


def _safe_model_error(exc: BaseException, *, boundary: str) -> str:
    return project_safe_failure(
        exc, boundary=boundary, code="model.route_failed",
        family="provider.request_failed",
        message="模型路由未完成。", retryable=True,
        recovery_action="retry_or_select_fallback",
    ).persistence_summary()


@dataclass(frozen=True)
class ModelResult:
    text: str
    receipt: dict


class ModelRoutesExhaustedError(RuntimeError):
    def __init__(self, primary_error: Exception, fallback_error: Exception) -> None:
        super().__init__("primary and fallback model routes were exhausted")
        self.primary_error = primary_error
        self.fallback_error = fallback_error


class CapabilityRoutesExhaustedError(RuntimeError):
    """Every route that explicitly advertised the required protocol failed."""

    def __init__(self, route_errors: list[tuple[str, str, Exception]]) -> None:
        self.route_errors = list(route_errors)
        super().__init__(
            "all structured-output routes were exhausted"
            if self.route_errors else "no structured-output route is configured"
        )


class TransportInterruptedError(RuntimeError):
    """A route returned a partial/non-terminal response body."""

    def __init__(self, receipt: dict, partial_text: str = "") -> None:
        super().__init__("provider transport ended before a terminal response")
        self.receipt = receipt
        self.partial_text = partial_text


class StructuredRouteQuarantinedError(RuntimeError):
    """A route/mode/schema tuple has failed business-shaped validation."""

    def __init__(self, execution_mode: str) -> None:
        super().__init__("structured route mode is quarantined")
        self.execution_mode = execution_mode


class FinalArtifactCapabilityError(RuntimeError):
    """Safe typed base for route-local final-artifact capability failures."""

    failure_kind = "final_artifact_unavailable"

    def __init__(self, message: str, *, receipt: dict) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)
        self.reliability_failure = ReliabilityFailure(
            code=str(getattr(self, "failure_code", self.failure_kind)),
            failure_class=FailureClass.CAPABILITY,
            boundary="model_gateway_final_artifact",
            message=message,
            retryable=False,
        )


class ReasoningOnlyFinalArtifactUnavailableError(FinalArtifactCapabilityError):
    """Provider exhausted output on reasoning without an artifact projection."""

    failure_code = "reasoning_only_final_artifact_unavailable"

    def __init__(self, *, receipt: dict) -> None:
        super().__init__(
            "reasoning-only provider output exhausted without a final artifact",
            receipt=receipt,
        )
        self.reliability_failure = ReliabilityFailure(
            code=self.failure_code,
            failure_class=FailureClass.OUTPUT_TRUNCATION,
            boundary="model_gateway_final_artifact",
            message=str(self),
            retryable=False,
        )


class FinalArtifactRouteQuarantinedError(FinalArtifactCapabilityError):
    """The exact route/contract fingerprint has negative artifact evidence."""

    failure_code = "final_artifact_route_quarantined"

    def __init__(self, *, receipt: dict) -> None:
        super().__init__(
            "final-artifact route capability is quarantined",
            receipt=receipt,
        )


def _reasoning_only_final_artifact_unavailable(
    response: ModelResponse,
) -> ProviderOutputShapeV1 | None:
    shape = response.output_shape
    if shape is None:
        return None
    if normalize_finish_reason(response.finish_reason) not in {
        "length", "max_output_tokens", "max_tokens", "model_length",
    }:
        return None
    exact_reasoning_only = all((
        shape.reasoning_block_count > 0,
        shape.text_block_count == 0,
        shape.provider_visible_text_chars == 0,
        shape.tool_call_count == 0,
        shape.normalized_visible_text_chars == 0,
        shape.normalized_tool_call_count == 0,
        shape.unknown_block_count == 0,
        shape.content_block_count == shape.reasoning_block_count,
        shape.adapter_projection_status == "exact",
        shape.transport_complete,
    ))
    return shape if exact_reasoning_only else None


class ModelGateway:
    CONNECT_RETRY_DELAY = 2

    def __init__(self, db: Database, registry: ProviderRegistry) -> None:
        self.db = db
        self.registry = registry
        # Negative final-artifact evidence blocks an exact fingerprint only
        # inside one explicitly identified run.  A gateway is application
        # scoped, so gateway lifetime is not a safe proxy for authorization
        # or recovery-schedule lifetime.
        self._final_artifact_route_blocks: set[
            tuple[str, str, str, str, str, str, str, str]
        ] = set()

    def _resolve_bound_route(
        self, provider_id: str, model_id: str, *, role: str, lane: str,
    ):
        """Pass role authority to production registries without breaking old doubles."""

        parameters = inspect.signature(self.registry.resolve).parameters
        if "role" in parameters and "lane" in parameters:
            return self.registry.resolve(
                provider_id, model_id, role=role, lane=lane,
            )
        return self.registry.resolve(provider_id, model_id)

    def has_configured_fallback(self, role: str) -> bool:
        binding = self.db.get_role_binding(role) or {}
        return bool(
            binding.get("fallback_provider_id")
            and binding.get("fallback_model_id")
        )

    async def complete(self, role: str, system: str, user: str,
                       max_output_tokens: int | None = None,
                       fallback_max_output_tokens: int | None = None,
                       response_schema: dict | None = None,
                       structured_requirement: StructuredOutputRequirement = (
                           StructuredOutputRequirement.PLAIN_TEXT
                       )) -> ModelResult:
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
            resolved = self._resolve_bound_route(
                binding["primary_provider_id"], binding["primary_model_id"],
                role=role, lane="primary",
            )
            return await self._complete_resolved(
                role, system, user, resolved, primary_limit,
                response_schema=response_schema,
                structured_requirement=structured_requirement,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if resolved is not None and self._is_transient_connect_error(exc):
                await asyncio.sleep(self.CONNECT_RETRY_DELAY)
                try:
                    return await self._complete_resolved(
                        role, system, user, resolved, primary_limit,
                        response_schema=response_schema,
                        structured_requirement=structured_requirement,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    exc = retry_exc
            try:
                fallback = self._resolve_configured_fallback(binding, role=role)
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                # A missing or invalid fallback credential is part of the
                # route failure.  Do not let fallback resolution replace the
                # primary error with a bare ValueError; recovery layers need
                # both route failures to classify the incident correctly.
                raise ModelRoutesExhaustedError(exc, fallback_exc) from fallback_exc
            if fallback is None:
                raise
            try:
                result = await self._complete_resolved(
                    role, system, user, fallback, fallback_limit,
                    response_schema=response_schema,
                    structured_requirement=structured_requirement,
                )
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                raise ModelRoutesExhaustedError(exc, fallback_exc) from fallback_exc
            return self._mark_fallback(
                result, binding["primary_provider_id"], binding["primary_model_id"], exc,
            )

    async def complete_structured(
        self,
        role: str,
        system: str,
        user: str,
        contract: StructuredArtifactContract,
        *,
        max_output_tokens: int | None = None,
        fallback_max_output_tokens: int | None = None,
        requirement: StructuredOutputRequirement = StructuredOutputRequirement.STRICT,
        allow_capability_roster: bool = False,
    ) -> ModelResult:
        """Complete one schema-bound task using route-local capabilities.

        No vendor or model-name inference is performed.  A third-party route
        must explicitly declare a compatible capability before native schema
        or forced-tool parameters are sent to it.
        """

        if allow_capability_roster:
            return await self._complete_structured_from_capability_roster(
                role,
                system,
                user,
                contract,
                max_output_tokens=max_output_tokens,
                fallback_max_output_tokens=fallback_max_output_tokens,
                requirement=requirement,
            )
        return await self.complete(
            role,
            system,
            user,
            max_output_tokens=max_output_tokens,
            fallback_max_output_tokens=fallback_max_output_tokens,
            response_schema=contract.provider_schema(),
            structured_requirement=requirement,
        )

    def configured_structured_capabilities(
        self, role: str, *, include_capability_roster: bool = False,
    ) -> list[StructuredOutputCapability]:
        binding = self.db.get_role_binding(role)
        if binding is None:
            return []
        capabilities: list[StructuredOutputCapability] = []
        for model_id in (
            binding.get("primary_model_id"), binding.get("fallback_model_id"),
        ):
            if not model_id:
                continue
            model = self.db.get_model(model_id) or {}
            capabilities.append(configured_structured_output_capability(
                model.get("capabilities") or {},
            ))
        if include_capability_roster:
            configured_ids = {
                str(value) for value in (
                    binding.get("primary_model_id"),
                    binding.get("fallback_model_id"),
                ) if value
            }
            for provider in self.db.list_providers():
                if not provider.get("enabled"):
                    continue
                for model in self.db.list_models(provider["id"]):
                    if str(model.get("id") or "") in configured_ids:
                        continue
                    capabilities.append(configured_structured_output_capability(
                        model.get("capabilities") or {},
                    ))
        return capabilities

    def _structured_capability_roster(
        self, role: str, requirement: StructuredOutputRequirement,
    ) -> list[tuple[str, str]]:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        routes: list[tuple[str, str]] = []

        def add(provider_id: object, model_id: object, *, discovered: bool) -> None:
            provider_value = str(provider_id or "").strip()
            model_value = str(model_id or "").strip()
            route = (provider_value, model_value)
            if not all(route) or route in routes:
                return
            if discovered:
                model = self.db.get_model(model_value) or {}
                capability = configured_structured_output_capability(
                    model.get("capabilities") or {},
                )
                if not capability_satisfies(capability, requirement):
                    return
            routes.append(route)

        add(
            binding.get("primary_provider_id"),
            binding.get("primary_model_id"),
            discovered=False,
        )
        add(
            binding.get("fallback_provider_id"),
            binding.get("fallback_model_id"),
            discovered=False,
        )
        for provider in self.db.list_providers():
            if not provider.get("enabled"):
                continue
            for model in self.db.list_models(provider["id"]):
                add(provider["id"], model.get("id"), discovered=True)
        return routes

    async def _complete_structured_from_capability_roster(
        self,
        role: str,
        system: str,
        user: str,
        contract: StructuredArtifactContract,
        *,
        max_output_tokens: int | None,
        fallback_max_output_tokens: int | None,
        requirement: StructuredOutputRequirement,
    ) -> ModelResult:
        routes = self._structured_capability_roster(role, requirement)
        errors: list[tuple[str, str, Exception]] = []
        schema = contract.provider_schema()
        primary = routes[0] if routes else ("", "")
        for index, (provider_id, model_id) in enumerate(routes):
            try:
                resolved = self._resolve_bound_route(
                    provider_id, model_id, role=role,
                    lane=(
                        "primary" if index == 0 else
                        "fallback" if index == 1 else "capability_roster"
                    ),
                )
                requested_limit = (
                    max_output_tokens if index == 0
                    else fallback_max_output_tokens
                    if fallback_max_output_tokens is not None
                    else max_output_tokens
                )
                result = await self._complete_resolved(
                    role,
                    system,
                    user,
                    resolved,
                    self._route_output_limit(model_id, requested_limit),
                    response_schema=schema,
                    structured_requirement=requirement,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append((provider_id, model_id, exc))
                continue
            receipt = {
                **result.receipt,
                "capability_roster_fallback": index > 0,
                "attempted_route_count": index + 1,
                "attempted_routes": [
                    {"provider_id": value[0], "model_id": value[1]}
                    for value in routes[:index + 1]
                ],
            }
            if index > 0:
                receipt.update({
                    "fallback_used": True,
                    "fallback_from_provider_id": primary[0],
                    "fallback_from_model_id": primary[1],
                    "primary_error": (
                        _safe_model_error(
                            errors[0][2], boundary="model.capability_roster.primary",
                        ) if errors else ""
                    ),
                })
            return ModelResult(result.text, receipt)
        raise CapabilityRoutesExhaustedError(errors)

    async def complete_primary(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None,
        response_schema: dict | None = None,
        structured_requirement: StructuredOutputRequirement = (
            StructuredOutputRequirement.PLAIN_TEXT
        ),
        diagnostic_context: ModelDiagnosticContextV1 | None = None,
        reasoning_policy: ReasoningPolicy = ReasoningPolicy.CURRENT_PROVIDER_DEFAULT,
        stage_role: str = "NORMAL",
        stage: str | None = None,
        contract_name: str = "",
        contract_version: int = 0,
    ) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = self._resolve_bound_route(
            binding["primary_provider_id"], binding["primary_model_id"],
            role=role, lane="primary",
        )
        return await self._complete_resolved(
            role, system, user, resolved,
            self._route_output_limit(binding.get("primary_model_id"), max_output_tokens),
            response_schema=response_schema,
            structured_requirement=structured_requirement,
            diagnostic_context=diagnostic_context,
            reasoning_policy=reasoning_policy,
            stage_role=stage_role,
            stage=stage,
            contract_name=contract_name,
            contract_version=contract_version,
        )

    async def complete_configured_fallback(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None,
        response_schema: dict | None = None,
        structured_requirement: StructuredOutputRequirement = (
            StructuredOutputRequirement.PLAIN_TEXT
        ),
        diagnostic_context: ModelDiagnosticContextV1 | None = None,
        reasoning_policy: ReasoningPolicy = ReasoningPolicy.CURRENT_PROVIDER_DEFAULT,
        stage_role: str = "NORMAL",
        stage: str | None = None,
        contract_name: str = "",
        contract_version: int = 0,
    ) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        fallback = self._resolve_configured_fallback(binding, role=role)
        if fallback is None:
            raise LookupError(f"Model role has no configured fallback: {role}")
        result = await self._complete_resolved(
            role, system, user, fallback,
            self._route_output_limit(binding.get("fallback_model_id"), max_output_tokens),
            response_schema=response_schema,
            structured_requirement=structured_requirement,
            diagnostic_context=diagnostic_context,
            reasoning_policy=reasoning_policy,
            stage_role=stage_role,
            stage=stage,
            contract_name=contract_name,
            contract_version=contract_version,
        )
        return ModelResult(result.text, {
            **result.receipt, "configured_fallback_direct": True,
        })

    async def complete_route(
        self,
        route: Literal["primary", "configured_fallback"],
        role: str,
        system: str,
        user: str,
        *,
        max_output_tokens: int | None = None,
        contract: StructuredArtifactContract | None = None,
        structured_requirement: StructuredOutputRequirement = (
            StructuredOutputRequirement.PLAIN_TEXT
        ),
        diagnostic_context: ModelDiagnosticContextV1 | None = None,
        reasoning_policy: ReasoningPolicy = ReasoningPolicy.CURRENT_PROVIDER_DEFAULT,
        stage_role: str = "NORMAL",
        stage: str | None = None,
    ) -> ModelResult:
        """Execute exactly one Runtime-selected route, with no hidden fallback."""

        response_schema = contract.provider_schema() if contract is not None else None
        if route == "primary":
            return await self.complete_primary(
                role,
                system,
                user,
                max_output_tokens=max_output_tokens,
                response_schema=response_schema,
                structured_requirement=structured_requirement,
                diagnostic_context=diagnostic_context,
                reasoning_policy=reasoning_policy,
                stage_role=stage_role,
                stage=stage,
                contract_name=(contract.name if contract is not None else ""),
                contract_version=(contract.version if contract is not None else 0),
            )
        if route == "configured_fallback":
            return await self.complete_configured_fallback(
                role,
                system,
                user,
                max_output_tokens=max_output_tokens,
                response_schema=response_schema,
                structured_requirement=structured_requirement,
                diagnostic_context=diagnostic_context,
                reasoning_policy=reasoning_policy,
                stage_role=stage_role,
                stage=stage,
                contract_name=(contract.name if contract is not None else ""),
                contract_version=(contract.version if contract is not None else 0),
            )
        raise ValueError(f"unknown explicit model route: {route}")

    @staticmethod
    def _is_transient_connect_error(exc: Exception) -> bool:
        return isinstance(exc, (
            httpx.TransportError,
            asyncio.TimeoutError,
            ConnectionError,
            TimeoutError,
            TransportInterruptedError,
        )) or classify_model_failure(exc) in {
            "transport_interrupted", "timeout", "connection_failed",
        }

    async def _complete_resolved(
        self, role, system, user, resolved, max_output_tokens, *,
        response_schema: dict | None = None,
        structured_requirement: StructuredOutputRequirement = (
            StructuredOutputRequirement.PLAIN_TEXT
        ),
        diagnostic_context: ModelDiagnosticContextV1 | None = None,
        reasoning_policy: ReasoningPolicy = ReasoningPolicy.CURRENT_PROVIDER_DEFAULT,
        stage_role: str = "NORMAL",
        stage: str | None = None,
        contract_name: str = "",
        contract_version: int = 0,
    ) -> ModelResult:
        capability = configured_structured_output_capability(
            resolved.capabilities,
        )
        if not capability_satisfies(capability, structured_requirement):
            raise StructuredOutputCapabilityError(
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                capability=capability,
                requirement=structured_requirement,
            )

        route_fingerprint = self._route_fingerprint(resolved, "plain")
        reasoning_directive = resolve_provider_reasoning_directive_v1(
            reasoning_policy,
            provider_id=resolved.provider_id,
            operator=str(getattr(resolved, "provider_operator", "")),
            destination=str(getattr(resolved, "destination", "")),
            protocol=str(getattr(resolved, "protocol", "")),
            model_id=resolved.model_id,
            model=resolved.model_name,
            route_fingerprint=route_fingerprint,
            lane=str(getattr(resolved, "route_lane", "")),
            stage=str(stage or role),
            contract_name=contract_name,
            contract_version=contract_version,
            model_role=role,
            stage_role=stage_role,
        )
        request = ModelRequest(
            model=resolved.model_name,
            messages=[
                Message(role="system", content=system),
                Message(role="user", content=user),
            ],
            max_output_tokens=max_output_tokens,
            reasoning_directive=reasoning_directive.value,
            stage_role=stage_role,
        )
        execution_mode = "plain"
        structured_mode_degraded = False
        route_fingerprint = self._route_fingerprint(resolved, execution_mode)
        contract_name = ""
        schema_sha256 = ""
        if response_schema is not None:
            contract_name = str(
                response_schema.get("name") or "structured_output"
            )
            schema_value = dict(response_schema.get("schema") or {})
            schema_sha256 = hashlib.sha256(json.dumps(
                schema_value, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            configured_mode = (
                "strict_tool"
                if capability == StructuredOutputCapability.STRICT_TOOL
                else "strict_json_schema"
                if capability == StructuredOutputCapability.STRICT_JSON_SCHEMA
                else "json_object"
                if capability == StructuredOutputCapability.JSON_OBJECT
                else "plain"
            )
            final_artifact_recovery_scope = (
                diagnostic_context.run_id
                if diagnostic_context is not None else "unbound"
            )
            final_artifact_key = (
                final_artifact_recovery_scope,
                resolved.provider_id,
                resolved.model_id,
                route_fingerprint,
                contract_name,
                schema_sha256,
                reasoning_policy.value,
                stage_role,
            )
            if final_artifact_key in self._final_artifact_route_blocks:
                raise FinalArtifactRouteQuarantinedError(receipt={
                    "role": role,
                    "provider_id": resolved.provider_id,
                    "model_id": resolved.model_id,
                    "model_name": resolved.model_name,
                    "route_fingerprint": route_fingerprint,
                    "execution_mode": "final_artifact",
                    "contract_name": contract_name,
                    "schema_sha256": schema_sha256,
                    "failure_code": "final_artifact_route_quarantined",
                    "failure_reason": "negative_final_artifact_capability",
                    "provider_call_executed": False,
                })
            qualification = self.db.get_structured_route_qualification(
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                route_fingerprint=route_fingerprint,
                execution_mode=configured_mode,
                contract_name=contract_name,
                schema_sha256=schema_sha256,
            )
            if qualification and qualification.get("status") == "quarantined":
                if configured_mode == "plain":
                    raise StructuredRouteQuarantinedError(configured_mode)
                plain_qualification = self.db.get_structured_route_qualification(
                    provider_id=resolved.provider_id,
                    model_id=resolved.model_id,
                    route_fingerprint=route_fingerprint,
                    execution_mode="plain",
                    contract_name=contract_name,
                    schema_sha256=schema_sha256,
                )
                if (
                    plain_qualification
                    and plain_qualification.get("status") == "quarantined"
                ):
                    raise StructuredRouteQuarantinedError("plain")
                structured_mode_degraded = True
                execution_mode = "plain"
            elif capability == StructuredOutputCapability.STRICT_TOOL:
                tool_name = str(response_schema.get("name") or "structured_output")
                request = request.model_copy(update={
                    "tools": [ToolDefinition(
                        name=tool_name,
                        description="Return the complete validated structured artifact.",
                        input_schema=dict(response_schema.get("schema") or {}),
                    )],
                    "required_tool": tool_name,
                })
                execution_mode = "strict_tool"
            elif capability == StructuredOutputCapability.STRICT_JSON_SCHEMA:
                request = request.model_copy(update={
                    "response_schema": response_schema,
                })
                execution_mode = "strict_json_schema"
            elif capability == StructuredOutputCapability.JSON_OBJECT:
                request = request.model_copy(update={
                    "response_format": "json_object",
                })
                execution_mode = "json_object"

        diagnostic_token = (
            bind_diagnostic_context(diagnostic_context)
            if diagnostic_context is not None else None
        )
        ptr12_capture_token = open_ptr12_raw_shape_capture()
        ptr12_snapshot = None
        try:
            response = await resolved.adapter.complete(request)
            ptr12_snapshot = current_ptr12_raw_shape()
        except Exception as exc:
            ptr12_snapshot = current_ptr12_raw_shape()
            raw_observation = bind_ptr12_raw_shape_observation(
                diagnostic_context,
                snapshot=ptr12_snapshot,
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                route_fingerprint=route_fingerprint,
                schema_sha256=schema_sha256 or None,
                request_mode=execution_mode,
            )
            delta = observe_ptr12_shape_delta(
                diagnostic_context,
                raw_shape=raw_observation,
                normalized_shape=None,
                normalized_finish_reason=None,
            )
            build_ptr12_guard_decision(
                diagnostic_context,
                shape=None,
                raw_shape=raw_observation,
                delta=delta,
                finish_reason=None,
                scope_eligible=response_schema is not None,
                guard_reached=False,
                guard_triggered=False,
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                route_fingerprint=route_fingerprint,
                contract_identity=contract_name or "unbound",
                schema_sha256=schema_sha256 or None,
                recovery_status="UNKNOWN",
            )
            observe_provider_content_block_shape(
                context=diagnostic_context,
                exc=exc,
            )
            if execution_mode == "strict_tool" and response_schema is not None:
                observe_strict_tool_shape(
                    context=diagnostic_context,
                    adapter=resolved.adapter,
                    provider_id=resolved.provider_id,
                    model_id=resolved.model_id,
                    request=request,
                    expected_tool=str(
                        response_schema.get("name") or "structured_output"
                    ),
                    exc=exc,
                )
            native_protocol_rejected = (
                execution_mode != "plain"
                and response_schema is not None
                and (
                    isinstance(exc, ToolCapabilityError)
                    or (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code in {400, 422}
                    )
                )
            )
            if native_protocol_rejected:
                self.db.save_structured_route_outcome(
                    provider_id=resolved.provider_id,
                    model_id=resolved.model_id,
                    route_fingerprint=route_fingerprint,
                    execution_mode=execution_mode,
                    contract_name=contract_name,
                    schema_sha256=schema_sha256,
                    outcome="protocol_invalid",
                    failure_reason="native_protocol_rejected",
                )
            raise
        finally:
            reset_ptr12_raw_shape_capture(ptr12_capture_token)
            if diagnostic_token is not None:
                reset_bound_diagnostic_context(diagnostic_token)
        raw_observation = bind_ptr12_raw_shape_observation(
            diagnostic_context,
            snapshot=ptr12_snapshot,
            provider_id=resolved.provider_id,
            model_id=resolved.model_id,
            route_fingerprint=route_fingerprint,
            schema_sha256=schema_sha256 or None,
            request_mode=execution_mode,
        )
        output_shape = provider_output_shape_from_response(
            resolved.adapter, response,
        )
        if output_shape is not None and response.output_shape is None:
            response = response.model_copy(update={"output_shape": output_shape})
        ptr12_delta = observe_ptr12_shape_delta(
            diagnostic_context,
            raw_shape=raw_observation,
            normalized_shape=output_shape,
            normalized_finish_reason=normalize_finish_reason(response.finish_reason) or None,
        )
        observe_provider_content_block_shape(
            context=diagnostic_context,
            response=response,
        )
        receipt = {
            "role": role,
            "provider_id": resolved.provider_id,
            "model_id": resolved.model_id,
            "model_name": resolved.model_name,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "request_id": response.raw_request_id,
            "finish_reason": normalize_finish_reason(response.finish_reason) or None,
            "raw_finish_reason": response.provider_state.get(
                "raw_finish_reason", response.finish_reason,
            ),
            "transport_complete": response.provider_state.get(
                "transport_complete", True,
            ) is not False,
            "requested_max_output_tokens": max_output_tokens,
            "route_fingerprint": route_fingerprint,
            "execution_mode": execution_mode,
            "structured_output_capability": capability.value,
            "structured_mode_degraded": structured_mode_degraded,
            "contract_name": contract_name or None,
            "schema_sha256": schema_sha256 or None,
            "reasoning_policy": reasoning_policy.value,
            "reasoning_directive": reasoning_directive.value,
            "stage_role": stage_role,
        }
        guarded_shape = (
            _reasoning_only_final_artifact_unavailable(response)
            if response_schema is not None else None
        )
        if (
            response_schema is not None
            and
            guarded_shape is None
            and reasoning_policy is ReasoningPolicy.FINALIZATION_FIRST
            and stage_role == PLANNING_FINAL_ARTIFACT_RECOVERY
        ):
            self._final_artifact_route_blocks.discard((
                final_artifact_recovery_scope,
                resolved.provider_id,
                resolved.model_id,
                route_fingerprint,
                contract_name,
                schema_sha256,
                ReasoningPolicy.CURRENT_PROVIDER_DEFAULT.value,
                "NORMAL",
            ))
        if guarded_shape is not None:
            self._final_artifact_route_blocks.add((
                final_artifact_recovery_scope,
                resolved.provider_id,
                resolved.model_id,
                route_fingerprint,
                contract_name,
                schema_sha256,
                reasoning_policy.value,
                stage_role,
            ))
            safe_receipt = {
                key: value for key, value in receipt.items()
                if key not in {"request_id", "raw_finish_reason"}
            }
            if response.raw_request_id:
                safe_receipt["request_id_sha256"] = hashlib.sha256(
                    response.raw_request_id.encode("utf-8")
                ).hexdigest()
            guard_receipt = {
                **safe_receipt,
                "failure_code": "reasoning_only_final_artifact_unavailable",
                "capability": f"{contract_name}_final_artifact",
                "capability_state": "unsupported_or_unreliable",
                "provider_call_executed": True,
                "parser_reached": False,
                "schema_validation_reached": False,
                "provider_output_shape": guarded_shape.model_dump(
                    mode="json", by_alias=True,
                ),
            }
            self._record_output_observation(receipt, response.text)
            qualification_memory_status = "RECORDED"
            try:
                self.db.save_structured_route_outcome(
                    provider_id=resolved.provider_id,
                    model_id=resolved.model_id,
                    route_fingerprint=route_fingerprint,
                    execution_mode="final_artifact",
                    contract_name=contract_name,
                    schema_sha256=schema_sha256,
                    outcome="reasoning_only_output_limit",
                    failure_reason="reasoning_only_max_tokens",
                    observed_visible_characters=0,
                    expected_visible_characters=0,
                )
                guard_receipt["qualification_memory_status"] = "recorded"
            except Exception:
                guard_receipt["qualification_memory_status"] = "write_failed"
                qualification_memory_status = "WRITE_FAILED"
            decision = build_ptr12_guard_decision(
                diagnostic_context,
                shape=response.output_shape,
                raw_shape=raw_observation,
                delta=ptr12_delta,
                finish_reason=normalize_finish_reason(response.finish_reason) or None,
                scope_eligible=True,
                guard_triggered=True,
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                route_fingerprint=route_fingerprint,
                contract_identity=contract_name or "unbound",
                schema_sha256=schema_sha256 or None,
                negative_write_status=qualification_memory_status,
            )
            failure = ReasoningOnlyFinalArtifactUnavailableError(receipt=guard_receipt)
            if decision is not None:
                try:
                    setattr(
                        failure, "_r1_ptr12_decision_receipt_sha256",
                        decision.decision_receipt_sha256,
                    )
                except Exception:
                    pass
            raise failure
        decision = build_ptr12_guard_decision(
            diagnostic_context,
            shape=response.output_shape,
            raw_shape=raw_observation,
            delta=ptr12_delta,
            finish_reason=normalize_finish_reason(response.finish_reason) or None,
            scope_eligible=response_schema is not None,
            guard_reached=response_schema is not None,
            guard_triggered=False,
            provider_id=resolved.provider_id,
            model_id=resolved.model_id,
            route_fingerprint=route_fingerprint,
            contract_identity=contract_name or "unbound",
            schema_sha256=schema_sha256 or None,
            recovery_status="NORMAL_RETURN",
        )
        if execution_mode == "strict_tool" and response_schema is not None:
            expected_name = str(response_schema.get("name") or "structured_output")
            observe_strict_tool_shape(
                context=diagnostic_context,
                adapter=resolved.adapter,
                provider_id=resolved.provider_id,
                model_id=resolved.model_id,
                request=request,
                expected_tool=expected_name,
                response=response,
            )
            matching = [
                call for call in response.tool_calls if call.name == expected_name
            ]
            if len(matching) != 1 or len(response.tool_calls) != 1:
                raise RuntimeError(
                    "strict structured tool route returned no unique artifact"
                )
            response = response.model_copy(update={
                "text": json.dumps(matching[0].arguments, ensure_ascii=False),
            })
        capture_contract_input = getattr(
            resolved.adapter, "capture_contract_runtime_input", None,
        )
        if response_schema is not None and callable(capture_contract_input):
            capture_contract_input(
                response.text,
                adapter_id=str(getattr(
                    resolved.adapter, "DIAGNOSTIC_ADAPTER_ID", "unknown",
                )),
                adapter_version=int(getattr(
                    resolved.adapter, "DIAGNOSTIC_ADAPTER_VERSION", 1,
                )),
                finish_reason=normalize_finish_reason(response.finish_reason) or None,
                transport_complete=bool(receipt["transport_complete"]),
            )
        self._record_output_observation(receipt, response.text)
        if not receipt["transport_complete"]:
            raise TransportInterruptedError(receipt, response.text)
        return ModelResult(response.text, receipt)

    async def complete_with_tools(self, role: str, system: str, user: str, toolbox,
                                  fallback_context, run_id: str | None = None,
                                  max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = None
        try:
            resolved = self._resolve_bound_route(
                binding["primary_provider_id"], binding["primary_model_id"],
                role=role, lane="primary",
            )
            return await self._complete_with_tools_resolved(
                role, system, user, toolbox, fallback_context, run_id,
                max_output_tokens, resolved,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            recovered = self._recover_toolbox_proposals(role, resolved, toolbox, exc)
            if recovered is not None:
                return recovered
            if resolved is not None and self._is_transient_connect_error(exc):
                await asyncio.sleep(self.CONNECT_RETRY_DELAY)
                try:
                    return await self._complete_with_tools_resolved(
                        role, system, user, toolbox, fallback_context, run_id,
                        max_output_tokens, resolved,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    exc = retry_exc
                    recovered = self._recover_toolbox_proposals(
                        role, resolved, toolbox, exc,
                    )
                    if recovered is not None:
                        return recovered
            try:
                fallback = self._resolve_configured_fallback(binding, role=role)
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                raise ModelRoutesExhaustedError(exc, fallback_exc) from fallback_exc
            if fallback is None:
                raise
            repair_context = self._prepare_toolbox_fallback(toolbox, exc)
            fallback_user = user + (
                "\n\nRUNTIME REPAIR CONTEXT:\n" + repair_context
                if repair_context else ""
            )
            try:
                result = await self._complete_with_tools_resolved(
                    role, system, fallback_user, toolbox, fallback_context, run_id,
                    max_output_tokens, fallback,
                )
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                recovered = self._recover_toolbox_proposals(
                    role, fallback, toolbox, fallback_exc,
                )
                if recovered is None:
                    raise ModelRoutesExhaustedError(exc, fallback_exc) from fallback_exc
                recovered = ModelResult(recovered.text, {
                    **recovered.receipt,
                    "fallback_route_error": _safe_model_error(
                        fallback_exc, boundary="model.tools.fallback_recovery",
                    ),
                })
                return self._mark_fallback(
                    recovered, binding["primary_provider_id"],
                    binding["primary_model_id"], exc,
                )
            return self._mark_fallback(
                result, binding["primary_provider_id"], binding["primary_model_id"], exc,
            )

    async def complete_with_tools_route(
        self,
        route: Literal["primary", "configured_fallback"],
        role: str,
        system: str,
        user: str,
        toolbox,
        fallback_context,
        run_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResult:
        """Execute one exact native-tool route without hidden route switching.

        Retry and fallback ownership belongs to ``contract_runtime``. Local
        toolbox proposal recovery remains safe here because it does not select
        another provider/model and cannot fabricate a tool result.
        """

        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        if route == "primary":
            resolved = self._resolve_bound_route(
                binding["primary_provider_id"], binding["primary_model_id"],
                role=role, lane="primary",
            )
        elif route == "configured_fallback":
            resolved = self._resolve_configured_fallback(binding, role=role)
            if resolved is None:
                raise LookupError(f"Model role has no configured fallback: {role}")
        else:  # pragma: no cover - Literal plus shared dispatcher validates it
            raise ValueError(f"unknown explicit model route: {route}")
        try:
            return await self._complete_with_tools_resolved(
                role, system, user, toolbox, fallback_context, run_id,
                max_output_tokens, resolved,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            recovered = self._recover_toolbox_proposals(
                role, resolved, toolbox, exc,
            )
            if recovered is not None:
                return recovered
            raise

    @staticmethod
    def _prepare_toolbox_fallback(toolbox, error: Exception) -> str:
        prepare = getattr(toolbox, "prepare_fallback", None)
        if not callable(prepare):
            return ""
        try:
            return str(prepare(error) or "")
        except Exception:
            return ""

    @staticmethod
    def _recover_toolbox_proposals(
        role: str, resolved, toolbox, error: Exception,
    ) -> ModelResult | None:
        finalize = getattr(toolbox, "finalize_after_route_error", None)
        if not callable(finalize):
            return None
        try:
            summary = finalize()
        except Exception:
            return None
        if summary is None:
            return None
        return ModelResult(str(summary), {
            "role": role,
            "provider_id": getattr(resolved, "provider_id", None),
            "model_id": getattr(resolved, "model_id", None),
            "model_name": getattr(resolved, "model_name", None),
            "input_tokens": 0,
            "output_tokens": 0,
            "request_id": None,
            "finish_reason": "runtime_recovered",
            "execution_mode": "native_tools",
            "tool_call_count": 0,
            "proposal_recovered": True,
            "route_error": _safe_model_error(
                error, boundary="model.tools.proposal_recovery",
            ),
        })

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
        forced_tool = next(
            (definition.name for definition in tool_definitions
             if definition.name not in {"complete_skill", "request_user_input"}),
            None,
        ) if controlled_runtime else None
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
                request = ModelRequest(
                    model=resolved.model_name, messages=messages, tools=request_tools,
                    required_tool=forced_tool if round_index == 0 else None,
                    max_output_tokens=max_output_tokens,
                )
                try:
                    response = await resolved.adapter.complete(request)
                except ToolCapabilityError:
                    if not request.required_tool:
                        raise
                    # Some providers support tools but reject tool_choice. Retry
                    # the same round with ordinary optional tool calling.
                    forced_tool = None
                    response = await resolved.adapter.complete(
                        request.model_copy(update={"required_tool": None}),
                    )
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
                round_receipt = self._receipt(
                    role, resolved, response, response.input_tokens,
                    response.output_tokens, "native_tool_round", 0,
                    max_output_tokens,
                )
                self._record_output_observation(round_receipt, response.text)
                if not round_receipt["transport_complete"]:
                    raise TransportInterruptedError(round_receipt, response.text)
                if not response.tool_calls:
                    if controlled_runtime:
                        if getattr(toolbox, "awaiting_question", None):
                            return ModelResult(response.text, self._receipt(
                                role, resolved, response, input_tokens, output_tokens,
                                "native_tools", calls, max_output_tokens,
                            ))
                        summary = finalize() if finalize else None
                        if summary is not None:
                            return ModelResult(summary, self._receipt(
                                role, resolved, response, input_tokens, output_tokens,
                                "native_tools", calls, max_output_tokens,
                            ))
                        if round_index < round_limit - 1:
                            messages.append(Message(
                                role="assistant", content=response.text or "No tool call returned.",
                            ))
                            messages.append(Message(
                                role="user",
                                content=(
                                    "The controlled task is not complete: no accepted file proposal "
                                    "or completion tool call exists. Continue now with the supplied "
                                    "runtime tools. Do not stop after reading or listing files."
                                ),
                            ))
                            continue
                        raise RuntimeError(
                            "Controlled runtime ended without required tool output"
                        )
                    return ModelResult(response.text, self._receipt(
                        role, resolved, response, input_tokens, output_tokens,
                        "native_tools", calls, max_output_tokens,
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
                        failure = project_safe_failure(
                            exc, boundary=f"model.tool.{call.name}",
                            code="model.tool_failed", family="runtime.tool_failure",
                            message="工具执行失败，已保留当前任务状态。",
                            retryable=True, recovery_action="repair_tool_input_or_retry",
                        )
                        result = {
                            "error": safe_local_validation_message(
                                exc, fallback=failure.message,
                            ),
                            "error_code": failure.code,
                            "incident_id": failure.failure_sha256[:16],
                            "retryable": True,
                        }
                        status = "failed"
                        error = failure.persistence_summary()
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
                        "native_tools", calls, max_output_tokens,
                    ))
                messages.append(Message(role="assistant", content="Requested read-only story evidence."))
                messages.append(Message(role="user", content="TOOL RESULTS:\n" + json.dumps(summaries, ensure_ascii=False)))
            summary = finalize() if finalize else None
            if summary is not None:
                return ModelResult(summary, self._receipt(
                    role, resolved, response, input_tokens, output_tokens,
                    "native_tools", calls, max_output_tokens,
                ))
            raise RuntimeError("Controlled runtime ended without required tool output")
        except ToolCapabilityError as exc:
            if mode == "enabled":
                raise
            return await self._fallback(
                role, system, user, fallback_context(), resolved, run_id,
                _safe_model_error(exc, boundary="model.tools.capability"),
                max_output_tokens,
            )

    def _resolve_configured_fallback(self, binding, *, role: str):
        provider_id = binding.get("fallback_provider_id")
        model_id = binding.get("fallback_model_id")
        if not provider_id or not model_id:
            return None
        return self._resolve_bound_route(
            provider_id, model_id, role=role, lane="fallback",
        )

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
            "primary_error": _safe_model_error(
                error, boundary="model.configured_fallback.primary",
            ),
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
                                response.output_tokens, "degraded_prompt_mode", 0,
                                max_output_tokens)
        self._record_output_observation(receipt, response.text)
        if not receipt["transport_complete"]:
            raise TransportInterruptedError(receipt, response.text)
        receipt["fallback_reason"] = reason
        return ModelResult(response.text, receipt)

    def _receipt(self, role, resolved, response, input_tokens, output_tokens, mode, calls,
                 requested_max_output_tokens=None):
        return {
            "role": role, "provider_id": resolved.provider_id, "model_id": resolved.model_id,
            "model_name": resolved.model_name, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "request_id": response.raw_request_id,
            "finish_reason": normalize_finish_reason(response.finish_reason) or None,
            "raw_finish_reason": response.provider_state.get(
                "raw_finish_reason", response.finish_reason,
            ),
            "transport_complete": response.provider_state.get(
                "transport_complete", True,
            ) is not False,
            "requested_max_output_tokens": requested_max_output_tokens,
            "route_fingerprint": self._route_fingerprint(resolved, mode),
            "execution_mode": mode, "tool_call_count": calls,
        }

    def _route_fingerprint(self, resolved, execution_mode: str = "") -> str:
        declared = str(getattr(resolved, "route_fingerprint", "") or "")
        if len(declared) == 64:
            return declared
        provider = self.db.get_provider(resolved.provider_id) or {}
        payload = {
            "provider_id": resolved.provider_id,
            "model_id": resolved.model_id,
            "model_name": resolved.model_name,
            "protocol": provider.get("protocol"),
            "base_url": provider.get("base_url"),
            "auth_type": provider.get("auth_type"),
            "header_names": sorted((provider.get("extra_headers") or {}).keys()),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def record_structured_contract_outcome(
        self, receipt: dict, contract: StructuredArtifactContract, *,
        outcome: str, failure_reason: str | None = None,
        observed_visible_characters: int = 0,
        expected_visible_characters: int = 0,
    ) -> dict:
        """Bind empirical business validation to an immutable route identity."""

        return self.db.save_structured_route_outcome(
            provider_id=str(receipt.get("provider_id") or ""),
            model_id=str(receipt.get("model_id") or ""),
            route_fingerprint=str(receipt.get("route_fingerprint") or ""),
            execution_mode=str(receipt.get("execution_mode") or "plain"),
            contract_name=contract.name,
            schema_sha256=contract.schema_sha256(),
            outcome=outcome,
            failure_reason=failure_reason,
            observed_visible_characters=observed_visible_characters,
            expected_visible_characters=expected_visible_characters,
        )

    def _record_output_observation(self, receipt: dict, text: str) -> None:
        self.db.save_model_output_observation(
            provider_id=str(receipt.get("provider_id") or ""),
            model_id=str(receipt.get("model_id") or ""),
            route_fingerprint=str(receipt.get("route_fingerprint") or ""),
            execution_mode=str(receipt.get("execution_mode") or "plain"),
            requested_max_output_tokens=receipt.get("requested_max_output_tokens"),
            actual_output_tokens=int(receipt.get("output_tokens") or 0),
            visible_characters=len(text or ""),
            finish_reason=normalize_finish_reason(receipt.get("finish_reason")) or None,
            transport_complete=bool(receipt.get("transport_complete", True)),
        )
