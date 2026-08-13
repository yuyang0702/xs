from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Mapping

from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    ArtifactConversionAudit,
    ArtifactConversionError,
    ArtifactConversionResult,
    GeneratedArtifactGateway,
    SemanticNormalizer,
)
from novel_flywheel.context_policy import (
    classify_model_failure,
    expanded_output_budget,
    output_limited,
)
from novel_flywheel.recovery_engine import (
    ProtocolReceiptAttempt,
    RecoveryAction,
    protocol_receipt_attempts,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


DomainValidator = Callable[[Mapping[str, Any]], Any]
TextValidator = Callable[[str], Any]
AuditSink = Callable[[ArtifactConversionAudit], None]
ModelRoute = Literal["primary", "configured_fallback"]
ContractAttemptExecutor = Callable[
    [
        ProtocolReceiptAttempt, str, str, str, int | None,
        StructuredArtifactContract,
    ],
    Awaitable[Any],
]


class ContractOutputLimitExhaustedError(RuntimeError):
    """Every permitted route returned a structurally incomplete artifact."""

    def __init__(self, message: str, *, receipt: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


class ContractBusinessOutputIncompleteError(RuntimeError):
    """Every permitted route/mode failed structural business completeness."""

    def __init__(self, reason: str, *, receipt: Mapping[str, Any]) -> None:
        super().__init__(
            "structured business output remained incomplete after route recovery"
        )
        self.reason = reason
        self.receipt = dict(receipt)


@dataclass(frozen=True)
class ExecutableContractSpec:
    """An indivisible model-output contract execution boundary.

    Business callers may construct the Runtime-owned wire authority dynamically,
    but they cannot select a schema without also selecting the canonical
    normalizer and the domain validator that proves the artifact is usable.
    This prevents a provider response from falling back to a raw-text workflow
    parser merely because one optional callback was omitted.
    """

    contract_name: str
    structured_contract: StructuredArtifactContract
    semantic_normalizer: SemanticNormalizer
    domain_validator: DomainValidator
    retry_domain_failures: bool = False
    expected_event_ids: tuple[str, ...] = ()
    owns_opening: bool = True
    owns_ending: bool = True

    def __post_init__(self) -> None:
        registration = ARTIFACT_CONTRACT_REGISTRY.get(self.contract_name)
        if registration is None:
            raise KeyError(
                "unregistered generated artifact contract: "
                f"{self.contract_name}"
            )
        if self.structured_contract.name != self.contract_name:
            raise ValueError(
                "structured wire contract name does not match the registered "
                f"artifact contract: {self.contract_name}"
            )
        if self.structured_contract.version != registration.version:
            raise ValueError(
                "structured wire contract version does not match the registered "
                f"artifact contract: {self.structured_contract.name}"
            )
        if not callable(self.semantic_normalizer):
            raise TypeError("executable contract semantic normalizer must be callable")
        if not callable(self.domain_validator):
            raise TypeError("executable contract domain validator must be callable")
        if (
            self.retry_domain_failures
            and "minimal_regeneration" not in registration.recovery_ladder
        ):
            raise ValueError(
                "contract recovery ladder does not authorize domain regeneration"
            )



@dataclass(frozen=True)
class ContractRecoveryPolicy:
    """Executable subset of one registered structured-artifact recovery ladder."""

    contract_version: int
    protocol_retry: bool
    model_fallback: bool
    minimal_regeneration: bool


@dataclass(frozen=True)
class ContractRouteCapacityPlan:
    """Route-owned input ceilings shared by every structured business caller."""

    primary_input_token_limit: int
    fallback_input_token_limit: int | None

    @property
    def maximum_input_token_limit(self) -> int:
        return max(
            self.primary_input_token_limit,
            self.fallback_input_token_limit or 0,
        )

    def attempt_routes(
        self, input_tokens: int, *, attempts_per_route: int = 2,
    ) -> tuple[Literal["primary", "configured_fallback"], ...]:
        if input_tokens <= 0:
            raise ValueError("contract route input size must be positive")
        if attempts_per_route < 1:
            raise ValueError("contract route attempts must be positive")
        routes: list[Literal["primary", "configured_fallback"]] = []
        if input_tokens <= self.primary_input_token_limit:
            routes.extend(["primary"] * attempts_per_route)
        if (
            self.fallback_input_token_limit is not None
            and input_tokens <= self.fallback_input_token_limit
        ):
            routes.extend(["configured_fallback"] * attempts_per_route)
        if not routes:
            raise ValueError(
                "contract input exceeds every configured model route"
            )
        return tuple(routes)


def contract_route_capacity_plan(
    db: Any,
    gateway: Any,
    *,
    role: str,
    output_reserve_tokens: int,
    context_utilization: float,
    unknown_context_tokens: int,
) -> ContractRouteCapacityPlan:
    """Compile configured model metadata into one explicit route-capacity plan."""

    if output_reserve_tokens < 1:
        raise ValueError("contract output reserve must be positive")
    if not 0 < context_utilization < 1:
        raise ValueError("contract context utilization must be between zero and one")
    if unknown_context_tokens < 1:
        raise ValueError("unknown route context must be positive")
    binding = db.get_role_binding(role) or {}

    def route_limit(model_id: object) -> int:
        model = db.get_model(str(model_id)) if model_id else None
        context_window = (
            int(model.get("context_window"))
            if model and isinstance(model.get("context_window"), int)
            and int(model["context_window"]) > 0
            else unknown_context_tokens
        )
        declared_output = (
            int(model.get("max_output_tokens"))
            if model and isinstance(model.get("max_output_tokens"), int)
            and int(model["max_output_tokens"]) > 0
            else output_reserve_tokens
        )
        reserve = min(output_reserve_tokens, declared_output)
        return max(1, int(context_window * context_utilization) - reserve)

    primary_limit = route_limit(binding.get("primary_model_id"))
    fallback_model_id = (
        binding.get("fallback_model_id")
        if binding.get("fallback_provider_id") and binding.get("fallback_model_id")
        else None
    )
    if (
        fallback_model_id is None
        and not binding
        and callable(getattr(gateway, "complete_configured_fallback", None))
    ):
        fallback_model_id = "__gateway_managed_fallback__"
    return ContractRouteCapacityPlan(
        primary_input_token_limit=primary_limit,
        fallback_input_token_limit=(
            route_limit(fallback_model_id) if fallback_model_id else None
        ),
    )


def _contract_recovery_policy(contract_name: str) -> ContractRecoveryPolicy:
    registration = ARTIFACT_CONTRACT_REGISTRY.get(contract_name)
    if registration is None:
        raise KeyError(f"unregistered generated artifact contract: {contract_name}")
    ladder = set(registration.recovery_ladder)
    return ContractRecoveryPolicy(
        contract_version=registration.version,
        protocol_retry="semantic_protocol_retry" in ladder,
        model_fallback="model_fallback" in ladder,
        minimal_regeneration="minimal_regeneration" in ladder,
    )


def _contract_attempts(
    gateway: Any,
    *,
    role: str,
    policy: ContractRecoveryPolicy,
    same_route_attempts: int,
    fallback_attempts: int,
    attempt_routes: tuple[
        Literal["primary", "configured_fallback"], ...
    ] | None,
) -> tuple[ProtocolReceiptAttempt, ...]:
    """Compile caller preferences through the registered recovery authority."""

    if attempt_routes is not None:
        if (
            not policy.protocol_retry
            and len(attempt_routes) != len(set(attempt_routes))
        ):
            raise ValueError(
                "contract recovery ladder does not authorize repeated route attempts"
            )
        if (
            not policy.model_fallback
            and "configured_fallback" in attempt_routes
        ):
            raise ValueError(
                "contract recovery ladder does not authorize model fallback"
            )
    return _runtime_attempts(
        gateway,
        role=role,
        same_route_attempts=(same_route_attempts if policy.protocol_retry else 1),
        fallback_attempts=(fallback_attempts if policy.model_fallback else 0),
        attempt_routes=attempt_routes,
    )


@dataclass(frozen=True)
class ContractRuntimeResult:
    """One validated canonical artifact plus its explicit route evidence."""

    payload: dict[str, Any]
    domain_value: Any
    conversion: ArtifactConversionResult
    model_response: Any
    attempt: ProtocolReceiptAttempt


@dataclass(frozen=True)
class TextRuntimeResult:
    """One validated prose artifact plus its explicit route evidence."""

    text: str
    domain_value: Any
    model_response: Any
    attempt: ProtocolReceiptAttempt


@dataclass(frozen=True)
class ModelRouteRuntimeResult:
    """One raw model response plus the exact route selected by Runtime."""

    model_response: Any
    attempt: ProtocolReceiptAttempt


def _configured_fallback_available(gateway: Any, role: str) -> bool:
    declared = getattr(gateway, "has_configured_fallback", None)
    if callable(declared):
        return bool(declared(role))
    return callable(getattr(gateway, "complete_configured_fallback", None))


def _runtime_attempts(
    gateway: Any,
    *,
    role: str,
    same_route_attempts: int,
    fallback_attempts: int,
    attempt_routes: tuple[
        Literal["primary", "configured_fallback"], ...
    ] | None,
) -> tuple[ProtocolReceiptAttempt, ...]:
    if attempt_routes is None:
        return protocol_receipt_attempts(
            same_route_attempts=same_route_attempts,
            configured_fallback_available=_configured_fallback_available(
                gateway, role,
            ),
            fallback_attempts=fallback_attempts,
        )
    if not attempt_routes:
        raise ValueError("explicit runtime attempt route plan cannot be empty")
    route_counts = {"primary": 0, "configured_fallback": 0}
    explicit_attempts: list[ProtocolReceiptAttempt] = []
    for index, route in enumerate(attempt_routes, 1):
        route_counts[route] += 1
        explicit_attempts.append(ProtocolReceiptAttempt(
            attempt_index=index,
            route_attempt=route_counts[route],
            route=route,
            action=(
                RecoveryAction.FALLBACK_CAPABLE_ROUTE
                if route == "configured_fallback"
                else None if route_counts[route] == 1
                else RecoveryAction.RECEIPT_ONLY_RETRY
            ),
            is_last=index == len(attempt_routes),
        ))
    return tuple(explicit_attempts)


def model_route_attempts(
    gateway: Any,
    *,
    role: str,
    same_route_attempts: int = 2,
    fallback_attempts: int = 2,
    attempt_routes: tuple[ModelRoute, ...] | None = None,
) -> tuple[ProtocolReceiptAttempt, ...]:
    """Public immutable route schedule shared by protocol/domain runtimes."""

    return _runtime_attempts(
        gateway,
        role=role,
        same_route_attempts=same_route_attempts,
        fallback_attempts=fallback_attempts,
        attempt_routes=attempt_routes,
    )


async def dispatch_explicit_model_route(
    gateway: Any,
    route: ModelRoute,
    *,
    role: str,
    system: str,
    user: str,
    max_output_tokens: int | None,
    structured_contract: StructuredArtifactContract | None = None,
    allow_implicit_primary: bool = True,
    toolbox: Any | None = None,
    fallback_context: Callable[[], str] | None = None,
    run_id: str | None = None,
) -> Any:
    """Execute exactly one selected route without a hidden route fallback."""

    if toolbox is not None:
        complete_tools = getattr(gateway, "complete_with_tools_route", None)
        if not callable(complete_tools):
            legacy_tools = getattr(gateway, "complete_with_tools", None)
            if (
                route != "primary"
                or _configured_fallback_available(gateway, role)
                or not callable(legacy_tools)
            ):
                raise RuntimeError(
                    "exact native-tool route interface is unavailable"
                )
            return await legacy_tools(
                role,
                system,
                user,
                toolbox,
                fallback_context=fallback_context or (lambda: ""),
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            )
        return await complete_tools(
            route,
            role,
            system,
            user,
            toolbox,
            fallback_context or (lambda: ""),
            run_id=run_id,
            max_output_tokens=max_output_tokens,
        )
    route_executor = getattr(gateway, "complete_route", None)
    if callable(route_executor):
        return await route_executor(
            route,
            role,
            system,
            user,
            max_output_tokens=max_output_tokens,
            contract=structured_contract,
        )
    if route == "configured_fallback":
        complete = getattr(gateway, "complete_configured_fallback", None)
        if not callable(complete):
            raise LookupError(f"configured fallback is unavailable for role: {role}")
        return await complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )
    complete = getattr(gateway, "complete_primary", None)
    if callable(complete):
        return await complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )
    if not allow_implicit_primary:
        raise RuntimeError("primary route interface unavailable")
    if _configured_fallback_available(gateway, role):
        raise RuntimeError(
            "implicit primary interface is unsafe when a configured fallback exists"
        )
    complete = getattr(gateway, "complete", None)
    if not callable(complete):
        raise LookupError(f"primary route is unavailable for role: {role}")
    return await complete(
        role, system, user, max_output_tokens=max_output_tokens,
    )


async def execute_model_route_runtime(
    gateway: Any,
    *,
    role: str,
    system: str,
    user: str,
    max_output_tokens: int | None = None,
    route_max_output_tokens: Mapping[ModelRoute, int | None] | None = None,
    same_route_attempts: int = 2,
    fallback_attempts: int = 2,
    attempt_routes: tuple[ModelRoute, ...] | None = None,
    structured_contract: StructuredArtifactContract | None = None,
    allow_implicit_primary: bool = True,
    toolbox: Any | None = None,
    fallback_context: Callable[[], str] | None = None,
    run_id: str | None = None,
) -> ModelRouteRuntimeResult:
    """Execute one immutable task through an explicit, auditable route plan.

    This is the common transport boundary for prose, structured artifacts,
    workflow stages, and native-tool Skill execution. It owns only route
    selection and bounded transport retry; business validation remains with
    the caller.
    """

    attempts = _runtime_attempts(
        gateway,
        role=role,
        same_route_attempts=same_route_attempts,
        fallback_attempts=fallback_attempts,
        attempt_routes=attempt_routes,
    )
    last_error: Exception | None = None
    primary_error: Exception | None = None
    fallback_error: Exception | None = None
    for attempt in attempts:
        route_user = user
        if (
            toolbox is not None
            and attempt.route == "configured_fallback"
            and last_error is not None
        ):
            prepare = getattr(toolbox, "prepare_fallback", None)
            repair_context = ""
            if callable(prepare):
                try:
                    repair_context = str(prepare(last_error) or "")
                except Exception:
                    repair_context = ""
            if repair_context:
                route_user += "\n\nRUNTIME REPAIR CONTEXT:\n" + repair_context
        try:
            route_budget = (
                route_max_output_tokens.get(attempt.route, max_output_tokens)
                if route_max_output_tokens is not None else max_output_tokens
            )
            response = await dispatch_explicit_model_route(
                gateway,
                attempt.route,
                role=role,
                system=system,
                user=route_user,
                max_output_tokens=route_budget,
                structured_contract=structured_contract,
                allow_implicit_primary=allow_implicit_primary,
                toolbox=toolbox,
                fallback_context=fallback_context,
                run_id=run_id,
            )
        except Exception as exc:
            last_error = exc
            if attempt.route == "configured_fallback":
                fallback_error = exc
            else:
                primary_error = exc
            # An unchanged request cannot recover from route capacity by being
            # replayed on that same route.  Return pressure immediately to the
            # caller-owned semantic splitter instead of issuing duplicate
            # doomed requests or hiding the topology change in a fallback.
            if classify_model_failure(exc) == "input_context_overflow":
                raise
            continue
        receipt = getattr(response, "receipt", None)
        if isinstance(receipt, dict):
            receipt.setdefault("runtime_selected_route", attempt.route)
            receipt.setdefault("runtime_route_attempt", attempt.route_attempt)
            if attempt.route == "configured_fallback":
                receipt.setdefault("configured_fallback_direct", True)
                receipt.setdefault("fallback_used", True)
        return ModelRouteRuntimeResult(response, attempt)
    if last_error is None:  # pragma: no cover - attempt constructor is non-empty
        raise RuntimeError("model route runtime had no executable attempt")
    if primary_error is not None and fallback_error is not None:
        # Lazy import avoids coupling model initialization to the contract
        # registry while preserving both route failures for recovery/audit.
        from novel_flywheel.models import ModelRoutesExhaustedError
        raise ModelRoutesExhaustedError(
            primary_error, fallback_error,
        ) from fallback_error
    raise last_error


async def _dispatch_explicit_route(
    gateway: Any,
    attempt: ProtocolReceiptAttempt,
    *,
    role: str,
    system: str,
    user: str,
    max_output_tokens: int | None,
    structured_contract: StructuredArtifactContract,
) -> Any:
    return await dispatch_explicit_model_route(
        gateway,
        attempt.route,
        role=role,
        system=system,
        user=user,
        max_output_tokens=max_output_tokens,
        structured_contract=structured_contract,
    )


async def _dispatch_explicit_text_route(
    gateway: Any,
    attempt: ProtocolReceiptAttempt,
    *,
    role: str,
    system: str,
    user: str,
    max_output_tokens: int | None,
) -> Any:
    return await dispatch_explicit_model_route(
        gateway,
        attempt.route,
        role=role,
        system=system,
        user=user,
        max_output_tokens=max_output_tokens,
    )


async def execute_text_runtime(
    gateway: Any,
    *,
    role: str,
    system: str,
    user: str,
    domain_validator: TextValidator | None = None,
    max_output_tokens: int | None = None,
    same_route_attempts: int = 2,
    fallback_attempts: int = 2,
    attempt_routes: tuple[
        Literal["primary", "configured_fallback"], ...
    ] | None = None,
    retry_domain_failures: bool = False,
) -> TextRuntimeResult:
    """Run prose generation on explicit routes without imposing a JSON shape.

    Transport retry and route selection are shared with structured contracts.
    Narrative validity remains caller-owned and is never reduced to a generic
    success boolean.  When enabled, a failed candidate triggers the same
    immutable task again; the failed prose is not promoted or persisted.
    """

    attempts = _runtime_attempts(
        gateway,
        role=role,
        same_route_attempts=same_route_attempts,
        fallback_attempts=fallback_attempts,
        attempt_routes=attempt_routes,
    )
    last_error: Exception | None = None
    last_domain_error = False
    for attempt in attempts:
        route_system = system
        if last_domain_error:
            route_system = (
                system
                + "\n\nThe previous candidate failed Runtime-owned business "
                "validation. Retry the same task without weakening, deleting, "
                "or reinterpreting any locked constraint."
            )
        try:
            response = await _dispatch_explicit_text_route(
                gateway,
                attempt,
                role=role,
                system=route_system,
                user=user,
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:
            last_error = exc
            last_domain_error = False
            continue
        text = str(response.text)
        try:
            if not text.strip():
                raise ValueError("text runtime returned an empty candidate")
            domain_value = (
                domain_validator(text)
                if domain_validator is not None else text
            )
        except (TypeError, ValueError) as exc:
            if not retry_domain_failures:
                raise
            last_error = exc
            last_domain_error = True
            continue
        return TextRuntimeResult(
            text=text,
            domain_value=domain_value,
            model_response=response,
            attempt=attempt,
        )
    if last_error is None:  # pragma: no cover - attempt constructor is non-empty
        raise RuntimeError("text runtime had no executable attempt")
    raise last_error


def _protocol_regeneration_system(system: str) -> str:
    """Retry the immutable task when local conversion cannot prove semantics."""

    return (
        system
        + "\n\nThe previous response could not be deterministically converted into "
        "the registered JSON contract. Re-run the same task against the exact same "
        "authority and return the specified JSON. Do not weaken, omit, or invent "
        "business facts."
    )


def _best_effort_object(text: str) -> dict[str, Any] | None:
    try:
        return GeneratedArtifactGateway().convert_object(
            text, contract_name="capability_probe",
        ).payload
    except (TypeError, ValueError, ArtifactConversionError):
        return None


def _business_incomplete_reason(
    text: str,
    contract: StructuredArtifactContract,
    *,
    payload: Mapping[str, Any] | None = None,
    expected_output_characters: int = 0,
) -> str | None:
    """Classify invariant structural deficits, never creative shortness alone."""

    visible = str(text or "").strip()
    if not visible:
        return "empty_output"
    candidate = dict(payload) if payload is not None else _best_effort_object(visible)
    if candidate == {}:
        return "empty_object"
    required = contract.required_top_level_fields()
    if candidate is not None and required:
        missing = [field for field in required if field not in candidate]
        if missing:
            return "required_fields_missing"
    floor = max(24, int(max(0, expected_output_characters) * 0.25))
    if expected_output_characters > 0 and len(visible) < floor:
        return "underfilled"
    return None


def _record_business_outcome(
    gateway: Any,
    response: Any,
    contract: StructuredArtifactContract,
    *,
    outcome: str,
    failure_reason: str | None,
    expected_output_characters: int,
) -> None:
    recorder = getattr(gateway, "record_structured_contract_outcome", None)
    receipt = getattr(response, "receipt", None)
    if not callable(recorder) or not isinstance(receipt, dict):
        return
    try:
        recorder(
            receipt,
            contract,
            outcome=outcome,
            failure_reason=failure_reason,
            observed_visible_characters=len(str(getattr(response, "text", "") or "")),
            expected_visible_characters=max(0, expected_output_characters),
        )
    except Exception:
        # Qualification memory is protective telemetry.  A storage fault must
        # not replace the business result or suppress configured fallback.
        return


async def execute_contract_runtime(
    gateway: Any,
    *,
    role: str,
    system: str,
    user: str,
    execution_spec: ExecutableContractSpec,
    max_output_tokens: int | None = None,
    expected_output_characters: int = 0,
    same_route_attempts: int = 2,
    fallback_attempts: int = 2,
    attempt_routes: tuple[
        Literal["primary", "configured_fallback"], ...
    ] | None = None,
    audit_sink: AuditSink | None = None,
    attempt_executor: ContractAttemptExecutor | None = None,
) -> ContractRuntimeResult:
    """Run one shared syntax/adapter/schema recovery ladder on explicit routes.

    Only representation failures enter protocol repair. A canonical artifact that
    fails the caller's domain validator is returned to that domain as a semantic
    failure and is never silently rewritten by this layer.
    """

    contract_name = execution_spec.contract_name
    structured_contract = execution_spec.structured_contract
    registration = ARTIFACT_CONTRACT_REGISTRY[contract_name]
    # A calibrated contract baseline outranks source-scaled caller estimates.
    # Uncalibrated dynamic contracts (for example wizard/interview schemas)
    # retain their task-local estimate instead of silently disabling the size
    # guard.  Every fixed workflow contract is calibrated in the registry.
    expected_output_characters = max(0, (
        expected_output_characters
        if registration.minimum_business_characters is None
        else registration.minimum_business_characters
    ))
    policy = _contract_recovery_policy(contract_name)
    converter = GeneratedArtifactGateway()
    last_error: Exception | None = None
    primary_error: Exception | None = None
    fallback_error: Exception | None = None
    last_receipt: Mapping[str, Any] = {}
    output_limit_seen = False
    last_business_incomplete_reason: str | None = None
    attempt_output_tokens = max_output_tokens

    attempts = _contract_attempts(
        gateway,
        role=role,
        policy=policy,
        same_route_attempts=same_route_attempts,
        fallback_attempts=fallback_attempts,
        attempt_routes=attempt_routes,
    )
    for attempt in attempts:
        route_system = system
        route_user = user
        if isinstance(
            last_error,
            (ArtifactConversionError, ContractBusinessOutputIncompleteError),
        ):
            route_system = _protocol_regeneration_system(system)
        try:
            response = (
                await attempt_executor(
                    attempt, role, route_system, route_user,
                    attempt_output_tokens, structured_contract,
                )
                if attempt_executor is not None
                else await _dispatch_explicit_route(
                    gateway,
                    attempt,
                    role=role,
                    system=route_system,
                    user=route_user,
                    max_output_tokens=attempt_output_tokens,
                    structured_contract=structured_contract,
                )
            )
            receipt = getattr(response, "receipt", None)
            if isinstance(receipt, Mapping):
                last_receipt = dict(receipt)
                output_limit_seen = output_limit_seen or output_limited(
                    last_receipt,
                )
        except Exception as exc:
            last_error = exc
            if attempt.route == "configured_fallback":
                fallback_error = exc
            else:
                primary_error = exc
            if classify_model_failure(exc) == "input_context_overflow":
                raise
            continue
        try:
            conversion = converter.convert_object(
                str(getattr(response, "text", response)),
                contract_name=contract_name,
                semantic_normalizer=execution_spec.semantic_normalizer,
                expected_event_ids=execution_spec.expected_event_ids,
                owns_opening=execution_spec.owns_opening,
                owns_ending=execution_spec.owns_ending,
            )
        except ArtifactConversionError as exc:
            if audit_sink is not None:
                audit_sink(exc.audit)
            last_error = exc
            receipt = getattr(response, "receipt", None)
            incomplete_reason = _business_incomplete_reason(
                str(getattr(response, "text", response)),
                structured_contract,
                expected_output_characters=expected_output_characters,
            )
            if incomplete_reason is not None:
                last_business_incomplete_reason = incomplete_reason
            _record_business_outcome(
                gateway, response, structured_contract,
                outcome=(
                    incomplete_reason
                    or (
                        "output_limited"
                        if output_limited(
                            receipt if isinstance(receipt, dict) else None
                        )
                        else "protocol_invalid"
                    )
                ),
                failure_reason=incomplete_reason,
                expected_output_characters=expected_output_characters,
            )
            if output_limited(receipt if isinstance(receipt, dict) else None):
                attempt_output_tokens = expanded_output_budget(
                    attempt_output_tokens,
                )
            continue
        if audit_sink is not None:
            audit_sink(conversion.audit)
        incomplete_reason = _business_incomplete_reason(
            str(getattr(response, "text", response)),
            structured_contract,
            payload=conversion.payload,
            expected_output_characters=expected_output_characters,
        )
        if incomplete_reason is not None:
            last_business_incomplete_reason = incomplete_reason
            receipt = getattr(response, "receipt", None)
            _record_business_outcome(
                gateway, response, structured_contract,
                outcome=incomplete_reason,
                failure_reason=incomplete_reason,
                expected_output_characters=expected_output_characters,
            )
            if output_limited(receipt if isinstance(receipt, dict) else None):
                attempt_output_tokens = expanded_output_budget(
                    attempt_output_tokens,
                )
            last_error = ContractBusinessOutputIncompleteError(
                incomplete_reason,
                receipt=(dict(receipt) if isinstance(receipt, Mapping) else {}),
            )
            continue
        try:
            domain_value = execution_spec.domain_validator(conversion.payload)
        except (TypeError, ValueError) as exc:
            if not execution_spec.retry_domain_failures:
                raise
            last_error = exc
            receipt = getattr(response, "receipt", None)
            incomplete_reason = _business_incomplete_reason(
                str(getattr(response, "text", response)),
                structured_contract,
                payload=conversion.payload,
                expected_output_characters=expected_output_characters,
            )
            if incomplete_reason is not None:
                last_business_incomplete_reason = incomplete_reason
            _record_business_outcome(
                gateway, response, structured_contract,
                outcome=(
                    incomplete_reason
                    or (
                        "output_limited"
                        if output_limited(
                            receipt if isinstance(receipt, dict) else None
                        )
                        else "semantic_invalid"
                    )
                ),
                failure_reason=incomplete_reason,
                expected_output_characters=expected_output_characters,
            )
            if output_limited(receipt if isinstance(receipt, dict) else None):
                attempt_output_tokens = expanded_output_budget(
                    attempt_output_tokens,
                )
            continue
        _record_business_outcome(
            gateway, response, structured_contract,
            outcome="valid",
            failure_reason=None,
            expected_output_characters=expected_output_characters,
        )
        return ContractRuntimeResult(
            payload=conversion.payload,
            domain_value=domain_value,
            conversion=conversion,
            model_response=response,
            attempt=attempt,
        )
    if last_error is None:  # pragma: no cover - attempt constructor is non-empty
        raise RuntimeError("structured contract runtime had no executable attempt")
    if output_limit_seen and (
        isinstance(last_error, ArtifactConversionError)
        or last_business_incomplete_reason is not None
    ):
        raise ContractOutputLimitExhaustedError(
            "structured output remained incomplete after every permitted route",
            receipt=last_receipt,
        ) from last_error
    if last_business_incomplete_reason is not None:
        raise ContractBusinessOutputIncompleteError(
            last_business_incomplete_reason,
            receipt=last_receipt,
        ) from last_error
    if primary_error is not None and fallback_error is not None:
        from novel_flywheel.models import ModelRoutesExhaustedError
        raise ModelRoutesExhaustedError(
            primary_error, fallback_error,
        ) from fallback_error
    raise last_error
