from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Any, Awaitable, Callable, Literal, Mapping, Sequence

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
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1, PTR9GuardDecisionObserverV1,
    clear_ptr12_guard_decision_capture, current_ptr12_guard_decision,
    domain_sha256, emit_budget_lineage, emit_ptr12_guard_recovery,
    emit_ptr12_output_limit_classification,
)
from novel_flywheel.models import FinalArtifactCapabilityError, ModelResult
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    ProviderResponseCaptureStoreV1,
)
from novel_flywheel.planning_repair_diagnostics import (
    PlanningRepairDomainValidationSnapshotV1,
    PlanningRepairRetryFindingContractError,
    observe_domain_validation_snapshot,
    observe_finding_propagation,
    observe_output_limit,
)
from novel_flywheel.recovery_engine import (
    FailureClass,
    ProtocolReceiptAttempt,
    ReliabilityFailure,
    RecoveryAction,
    protocol_receipt_attempts,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


DomainValidator = Callable[[Mapping[str, Any]], Any]
DomainDiagnosticExtractor = Callable[
    [Mapping[str, Any]], Sequence[Mapping[str, Any]]
]
DomainRetryRenderer = Callable[
    [Sequence[Mapping[str, Any]], Mapping[str, Any], str], str
]
TextValidator = Callable[[str], Any]
AuditSink = Callable[[ArtifactConversionAudit], None]
AttemptObserver = Callable[[dict[str, Any]], None]
LocalRejectionSink = Callable[[Mapping[str, Any]], None]
ModelRoute = Literal["primary", "configured_fallback"]
ContractAttemptExecutor = Callable[
    [
        ProtocolReceiptAttempt, str, str, str, int | None,
        StructuredArtifactContract,
    ],
    Awaitable[Any],
]


def _observe_attempt(observer: AttemptObserver | None, **observation: Any) -> None:
    if observer is None:
        return
    try:
        observer(observation)
    except Exception:
        # Observation must never alter retry, fallback, timeout, or failure.
        return


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


class FinalArtifactCapabilityExhaustedError(RuntimeError):
    """No distinct eligible route can produce the required final artifact."""

    failure_kind = "final_artifact_unavailable"
    failure_code = "final_artifact_capability_exhausted"

    def __init__(
        self,
        *,
        receipt: Mapping[str, Any],
        blocked_route_fingerprints: Mapping[str, str],
    ) -> None:
        super().__init__(
            "final-artifact capability was exhausted across permitted routes"
        )
        self.receipt = dict(receipt)
        self.blocked_route_fingerprints = dict(blocked_route_fingerprints)
        self.reliability_failure = ReliabilityFailure(
            code=self.failure_code,
            failure_class=(
                FailureClass.OUTPUT_TRUNCATION
                if output_limited(self.receipt)
                else FailureClass.CAPABILITY
            ),
            boundary="contract_runtime_final_artifact",
            message=str(self),
            retryable=False,
        )


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
    domain_diagnostic_extractor: DomainDiagnosticExtractor | None = None
    domain_diagnostic_metadata: Mapping[str, Any] | None = None
    domain_retry_renderer: DomainRetryRenderer | None = None
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
        if self.domain_retry_renderer is not None and (
            self.domain_diagnostic_extractor is None
            or not self.retry_domain_failures
        ):
            raise ValueError(
                "domain retry rendering requires diagnostics and domain retries"
            )
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
    accepted_system_sha256: str
    accepted_user_sha256: str
    accepted_input_sha256: str


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
    diagnostic_context: ModelDiagnosticContextV1 | None = None,
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
        route_kwargs = {
            "max_output_tokens": max_output_tokens,
            "contract": structured_contract,
        }
        if diagnostic_context is not None:
            route_kwargs["diagnostic_context"] = diagnostic_context
        return await route_executor(
            route,
            role,
            system,
            user,
            **route_kwargs,
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
    attempt_observer: AttemptObserver | None = None,
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
            _observe_attempt(
                attempt_observer,
                attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(
                    str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None
                ),
                route=attempt.route,
                route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
                outcome="transport_failure",
                failure_class=classify_model_failure(exc),
                error_class=type(exc).__name__,
                model_call_delta=1,
            )
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
        _observe_attempt(
            attempt_observer,
            attempt_id=str(attempt.attempt_index),
            parent_attempt_id=(
                str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None
            ),
            route=attempt.route,
            route_attempt=attempt.route_attempt,
            action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
            outcome="returned",
            failure_class=None,
            model_call_delta=1,
            input_tokens=(receipt or {}).get("input_tokens") if isinstance(receipt, dict) else None,
            output_tokens=(receipt or {}).get("output_tokens") if isinstance(receipt, dict) else None,
        )
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
    diagnostic_context: ModelDiagnosticContextV1 | None = None,
) -> Any:
    return await dispatch_explicit_model_route(
        gateway,
        attempt.route,
        role=role,
        system=system,
        user=user,
        max_output_tokens=max_output_tokens,
        structured_contract=structured_contract,
        diagnostic_context=diagnostic_context,
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
    attempt_observer: AttemptObserver | None = None,
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
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
                outcome="transport_failure", failure_class=classify_model_failure(exc),
                error_class=type(exc).__name__, model_call_delta=1,
            )
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
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.MINIMAL_REGENERATE),
                outcome="domain_failure", failure_class="domain_validation",
                error_class=type(exc).__name__, model_call_delta=1,
            )
            if not retry_domain_failures:
                raise
            last_error = exc
            last_domain_error = True
            continue
        receipt = getattr(response, "receipt", None)
        _observe_attempt(
            attempt_observer, attempt_id=str(attempt.attempt_index),
            parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
            route=attempt.route, route_attempt=attempt.route_attempt,
            action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
            outcome="valid", failure_class=None, model_call_delta=1,
            input_tokens=(receipt or {}).get("input_tokens") if isinstance(receipt, dict) else None,
            output_tokens=(receipt or {}).get("output_tokens") if isinstance(receipt, dict) else None,
        )
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


def _emit_local_rejection(
    sink: LocalRejectionSink | None,
    *,
    response: Any,
    contract: StructuredArtifactContract,
    attempt: ProtocolReceiptAttempt,
    audit: ArtifactConversionAudit,
    failure_kind: Literal[
        "artifact_conversion", "business_incomplete", "domain_validation",
    ],
    failure_reason: str,
) -> None:
    """Close one successful dispatch with content-free local rejection proof.

    This is control-plane authority rather than best-effort telemetry.  A sink
    failure propagates so the Full Short boundary cannot dispatch again from
    an ambiguous durable state.  Only stable hashes and typed classifications
    cross the boundary; provider text and converted payload never do.
    """

    if sink is None:
        return
    sink({
        "schema": "ContractLocalRejectionReceiptV1",
        "version": 1,
        "contract_name": contract.name,
        "contract_version": contract.version,
        "contract_schema_sha256": contract.schema_sha256(),
        "attempt_index": attempt.attempt_index,
        "route": attempt.route,
        "route_attempt": attempt.route_attempt,
        "failure_kind": failure_kind,
        "failure_reason_sha256": hashlib.sha256(
            failure_reason.encode("utf-8"),
        ).hexdigest(),
        "response_text_sha256": hashlib.sha256(
            str(getattr(response, "text", response)).encode("utf-8"),
        ).hexdigest(),
        "conversion_audit_sha256": domain_sha256(
            "novel-flywheel-artifact-conversion-audit-v1",
            audit.model_dump(mode="json"),
        ),
        "raw_content_persisted": False,
    })


def _emit_final_artifact_rejection(
    sink: LocalRejectionSink | None,
    *,
    error: FinalArtifactCapabilityError,
    contract: StructuredArtifactContract,
    attempt: ProtocolReceiptAttempt,
) -> None:
    """Close a captured 2xx response rejected before Contract Runtime input.

    The receipt deliberately contains no provider content.  It proves that the
    provider-protocol capture exists at the execution boundary while recording
    that an adapter-visible final artifact was unavailable, so the missing
    Contract Runtime capture is an expected typed state rather than ambiguity.
    """

    if sink is None:
        return
    receipt = getattr(error, "receipt", None)
    receipt = dict(receipt) if isinstance(receipt, Mapping) else {}
    output_shape = receipt.get("provider_output_shape")
    output_shape = dict(output_shape) if isinstance(output_shape, Mapping) else {}
    sink({
        "schema": "ProviderFinalArtifactRejectionReceiptV1",
        "version": 1,
        "contract_name": contract.name,
        "contract_version": contract.version,
        "contract_schema_sha256": contract.schema_sha256(),
        "attempt_index": attempt.attempt_index,
        "route": attempt.route,
        "route_attempt": attempt.route_attempt,
        "failure_kind": "final_artifact_unavailable",
        "failure_code": str(
            getattr(error, "failure_code", "final_artifact_unavailable")
        ),
        "failure_reason_sha256": hashlib.sha256(
            str(error).encode("utf-8"),
        ).hexdigest(),
        "provider_output_shape_sha256": str(
            output_shape.get("shape_sha256") or ""
        ),
        "contract_runtime_input_present": False,
        "raw_content_persisted": False,
    })


def _close_durable_post_capture_exception(
    gateway: Any, *, error: BaseException,
    failure_class: str, attempt: ProtocolReceiptAttempt,
) -> bool:
    """Close a complete provider entity before Contract Runtime can retry it."""

    registry = getattr(gateway, "registry", None)
    observer = getattr(registry, "attempt_observer", None)
    capture_complete = getattr(
        observer, "provider_protocol_capture_complete", None,
    )
    contract_input_present = getattr(
        observer, "contract_runtime_capture_present", None,
    )
    close_terminal = getattr(
        observer, "mark_post_capture_terminal_failure", None,
    )
    if (
        not callable(capture_complete)
        or not callable(contract_input_present)
        or not callable(close_terminal)
    ):
        return False
    if not capture_complete() or contract_input_present():
        return False
    close_terminal(
        failure_kind=type(error).__name__,
        failure_class=failure_class,
        contract_attempt_index=attempt.attempt_index,
        contract_route=attempt.route,
        contract_route_attempt=attempt.route_attempt,
    )
    return True


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
    attempt_observer: AttemptObserver | None = None,
    local_rejection_sink: LocalRejectionSink | None = None,
    diagnostic_context: ModelDiagnosticContextV1 | None = None,
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
    last_domain_snapshot: PlanningRepairDomainValidationSnapshotV1 | None = None
    pending_domain_findings: tuple[Mapping[str, Any], ...] = ()
    pending_source_identity: str | None = None
    attempt_output_tokens = max_output_tokens
    contract_schema = structured_contract.json_schema
    blocked_route_fingerprints: dict[str, str] = {}
    final_artifact_failure_seen = False
    non_final_failure_seen = False
    ptr12_triggered_context: tuple[
        ModelDiagnosticContextV1, PTR9GuardDecisionObserverV1
    ] | None = None

    def emit_ptr12_recovery(
        *, selected: bool, fail_close: bool, status: str,
    ) -> None:
        if ptr12_triggered_context is None:
            return
        context, decision = ptr12_triggered_context
        emit_ptr12_guard_recovery(
            context, decision,
            alternate_route_considered=True,
            alternate_route_selected=selected,
            fail_close_selected=fail_close,
            recovery_status=status,
        )

    def lineage_cap_values(target: int | None) -> dict[str, Any]:
        after_provider = target
        sources: list[str] = []
        provider_limit = (
            diagnostic_context.provider_declared_output_limit
            if diagnostic_context is not None else None
        )
        if after_provider is not None and provider_limit is not None \
                and after_provider > provider_limit:
            after_provider = provider_limit
            sources.append("model")
        after_canary = after_provider
        canary_limit = (
            diagnostic_context.canary_output_limit
            if diagnostic_context is not None else None
        )
        if after_canary is not None and canary_limit is not None \
                and after_canary > canary_limit:
            after_canary = canary_limit
            sources.append("canary")
        return {
            "effective_budget_after_provider_cap": after_provider,
            "effective_budget_after_canary_cap": after_canary,
            "cap_applied": bool(sources),
            "cap_source": sources[-1] if sources else "none",
            "cap_sources": tuple(sources),
        }
    emit_budget_lineage(
        diagnostic_context,
        lineage_event="runtime_created",
        system=system,
        user=user,
        contract_schema=contract_schema,
        original_requested_output_budget=max_output_tokens,
        current_requested_output_budget=max_output_tokens,
        previous_attempt_budget=None,
        expansion_trigger=None,
        expansion_requested=False,
        expansion_target=None,
        expansion_target_before_cap=None,
        effective_budget_after_policy=max_output_tokens,
        effective_budget_after_provider_cap=max_output_tokens,
        effective_budget_after_canary_cap=max_output_tokens,
        expansion_applied=False,
        retained_expansion_state=False,
        runtime_reconstructed=bool(
            diagnostic_context and diagnostic_context.outer_retry_ordinal > 1
        ),
        reconstruction_reason=(
            "workflow_owned_protocol_retry"
            if diagnostic_context and diagnostic_context.outer_retry_ordinal > 1 else None
        ),
        retry_owner="workflow_outer_receipt_schedule",
        route_kind=(diagnostic_context.route_kind if diagnostic_context else None),
        finish_reason=None,
        typed_failure=None,
        cap_applied=False,
        cap_source="none",
        cap_sources=(),
    )
    if diagnostic_context is not None and diagnostic_context.outer_retry_ordinal > 1:
        previous_context = replace(
            diagnostic_context,
            outer_retry_ordinal=diagnostic_context.outer_retry_ordinal - 1,
        )
        emit_budget_lineage(
            diagnostic_context,
            lineage_event="outer_runtime_reconstructed",
            previous_contract_runtime_instance_id=previous_context.runtime_instance_id,
            system=system,
            user=user,
            contract_schema=contract_schema,
            original_requested_output_budget=max_output_tokens,
            current_requested_output_budget=max_output_tokens,
            previous_attempt_budget=max_output_tokens,
            expansion_trigger=None,
            expansion_requested=False,
            expansion_target=None,
            expansion_target_before_cap=None,
            effective_budget_after_policy=max_output_tokens,
            effective_budget_after_provider_cap=max_output_tokens,
            effective_budget_after_canary_cap=max_output_tokens,
            expansion_applied=False,
            retained_expansion_state=False,
            runtime_reconstructed=True,
            reconstruction_reason="workflow_owned_protocol_retry",
            retry_owner="workflow_outer_receipt_schedule",
            route_kind=diagnostic_context.route_kind,
            finish_reason=None,
            typed_failure=None,
            cap_applied=False,
            cap_source="none",
            cap_sources=(),
        )

    attempts = _contract_attempts(
        gateway,
        role=role,
        policy=policy,
        same_route_attempts=same_route_attempts,
        fallback_attempts=fallback_attempts,
        attempt_routes=attempt_routes,
    )

    def next_route_action(current: ProtocolReceiptAttempt) -> str:
        if current.attempt_index >= len(attempts):
            return "terminal"
        following = attempts[current.attempt_index]
        return (
            "retry_same_route"
            if following.route == current.route
            else "advance_to_configured_fallback"
        )

    for attempt in attempts:
        attempt_context = (
            replace(
                diagnostic_context,
                route_kind=attempt.route,
                inner_attempt_ordinal=attempt.attempt_index,
                parent_attempt_ordinal=(
                    attempt.attempt_index - 1 if attempt.attempt_index > 1 else None
                ),
            )
            if diagnostic_context is not None else None
        )
        if attempt.route in blocked_route_fingerprints:
            _observe_attempt(
                attempt_observer,
                attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(
                    str(attempt.attempt_index - 1)
                    if attempt.attempt_index > 1 else None
                ),
                route=attempt.route,
                route_attempt=attempt.route_attempt,
                action="skip_negative_final_artifact_capability",
                outcome="capability_skipped",
                failure_class="final_artifact_unavailable",
                error_class="FinalArtifactRouteQuarantinedError",
                route_fingerprint=blocked_route_fingerprints[attempt.route],
                model_call_delta=0,
            )
            continue
        emit_budget_lineage(
            attempt_context if attempt_executor is None else None,
            lineage_event="request_dispatched",
            system=system,
            user=user,
            contract_schema=contract_schema,
            original_requested_output_budget=max_output_tokens,
            current_requested_output_budget=attempt_output_tokens,
            previous_attempt_budget=None,
            expansion_trigger=None,
            expansion_requested=False,
            expansion_target=None,
            expansion_target_before_cap=None,
            effective_budget_after_policy=attempt_output_tokens,
            effective_budget_after_provider_cap=attempt_output_tokens,
            effective_budget_after_canary_cap=attempt_output_tokens,
            expansion_applied=False,
            retained_expansion_state=(
                attempt.attempt_index > 1 and attempt_output_tokens != max_output_tokens
            ),
            runtime_reconstructed=False,
            reconstruction_reason=None,
            retry_owner="contract_runtime_inner",
            route_kind=attempt.route,
            finish_reason=None,
            typed_failure=None,
            cap_applied=False,
            cap_source="none",
            cap_sources=(),
        )
        route_system = system
        route_user = user
        if isinstance(
            last_error,
            (ArtifactConversionError, ContractBusinessOutputIncompleteError),
        ):
            route_system = _protocol_regeneration_system(system)
        propagated_findings: tuple[Mapping[str, Any], ...] = ()
        propagated_receipt: str | None = None
        if pending_domain_findings and execution_spec.domain_retry_renderer:
            if pending_source_identity is None:
                raise PlanningRepairRetryFindingContractError(
                    "pending finding source identity is missing"
                )
            finding_block = execution_spec.domain_retry_renderer(
                pending_domain_findings,
                execution_spec.domain_diagnostic_metadata or {},
                pending_source_identity,
            )
            route_user = f"{route_user}\n\n{finding_block}"
            propagated_findings = pending_domain_findings
            propagated_receipt = (
                last_domain_snapshot.receipt_sha256
                if last_domain_snapshot is not None else None
            )
            pending_domain_findings = ()
            pending_source_identity = None
        observe_finding_propagation(
            source=last_domain_snapshot,
            target_context=attempt_context,
            system=route_system,
            user=route_user,
            propagated_findings=propagated_findings,
            propagated_finding_receipt_sha256=propagated_receipt,
        )
        try:
            clear_ptr12_guard_decision_capture()
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
                    diagnostic_context=attempt_context,
                )
            )
            receipt = getattr(response, "receipt", None)
            if isinstance(receipt, Mapping):
                last_receipt = dict(receipt)
                output_limit_seen = output_limit_seen or output_limited(
                    last_receipt,
                )
            attempt_ptr12_decision = current_ptr12_guard_decision()
        except Exception as exc:
            attempt_ptr12_decision = current_ptr12_guard_decision()
            final_artifact_failure = isinstance(
                exc, FinalArtifactCapabilityError,
            )
            failure_class = (
                "final_artifact_unavailable"
                if final_artifact_failure else classify_model_failure(exc)
            )
            post_capture_terminal = _close_durable_post_capture_exception(
                gateway, error=exc, failure_class=failure_class,
                attempt=attempt,
            )
            error_receipt = getattr(exc, "receipt", None)
            provider_call_executed = not (
                final_artifact_failure
                and isinstance(error_receipt, Mapping)
                and error_receipt.get("provider_call_executed") is False
            )
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
                outcome=(
                    "post_capture_terminal_failure"
                    if post_capture_terminal
                    else (
                        "final_artifact_capability_failure"
                        if final_artifact_failure else "transport_failure"
                    )
                ),
                failure_class=failure_class,
                error_class=type(exc).__name__,
                model_call_delta=1 if provider_call_executed else 0,
            )
            if post_capture_terminal:
                # The complete entity is authoritative.  Propagate its exact
                # adapter/protocol exception and forbid a second provider call.
                raise
            last_error = exc
            if isinstance(error_receipt, Mapping):
                last_receipt = dict(error_receipt)
            if final_artifact_failure and provider_call_executed:
                _emit_final_artifact_rejection(
                    local_rejection_sink,
                    error=exc,
                    contract=structured_contract,
                    attempt=attempt,
                )
            if final_artifact_failure:
                final_artifact_failure_seen = True
                fingerprint = str(
                    (error_receipt or {}).get("route_fingerprint")
                    if isinstance(error_receipt, Mapping) else ""
                )
                if fingerprint:
                    blocked_route_fingerprints[attempt.route] = fingerprint
                if (
                    attempt_context is not None
                    and attempt_ptr12_decision is not None
                ):
                    ptr12_triggered_context = (
                        attempt_context, attempt_ptr12_decision,
                    )
            else:
                non_final_failure_seen = True
            if attempt.route == "configured_fallback":
                fallback_error = exc
            else:
                primary_error = exc
            if failure_class == "input_context_overflow":
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
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RECEIPT_ONLY_RETRY),
                outcome="protocol_failure", failure_class="protocol",
                error_class=type(exc).__name__, model_call_delta=1,
            )
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
            _emit_local_rejection(
                local_rejection_sink,
                response=response,
                contract=structured_contract,
                attempt=attempt,
                audit=exc.audit,
                failure_kind="artifact_conversion",
                failure_reason=(
                    incomplete_reason
                    or str(exc.audit.failure_code or "artifact_conversion")
                ),
            )
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
                emit_ptr12_output_limit_classification(
                    attempt_context,
                    output_limit_seen=True,
                    receipt=receipt if isinstance(receipt, Mapping) else None,
                    terminal=False,
                )
                previous_budget = attempt_output_tokens
                target_budget = expanded_output_budget(previous_budget)
                cap_values = lineage_cap_values(target_budget)
                observe_output_limit(
                    attempt_context,
                    requested_budget=previous_budget,
                    effective_budget=previous_budget,
                    output_tokens=(
                        int(receipt.get("output_tokens") or 0)
                        if isinstance(receipt, Mapping) else 0
                    ),
                    stop_reason=(
                        receipt.get("finish_reason")
                        if isinstance(receipt, Mapping) else None
                    ),
                    zero_visible=not bool(
                        str(getattr(response, "text", response) or "").strip()
                    ),
                    parser_reached=True,
                    strict_tool_reached=bool(
                        isinstance(receipt, Mapping)
                        and receipt.get("execution_mode") == "strict_tool"
                    ),
                    domain_validator_reached=False,
                    truncation_classifier_reason=(
                        incomplete_reason
                        or str(exc.audit.failure_code or "artifact_conversion")
                    ),
                    contract_output_limit_action=(
                        "terminal_exhausted"
                        if attempt.is_last else "expand_and_continue"
                    ),
                    expansion_before=previous_budget,
                    expansion_after=target_budget,
                    next_route_action=next_route_action(attempt),
                )
                emit_budget_lineage(
                    attempt_context,
                    lineage_event="expansion_decided",
                    system=route_system,
                    user=route_user,
                    contract_schema=contract_schema,
                    original_requested_output_budget=max_output_tokens,
                    current_requested_output_budget=previous_budget,
                    previous_attempt_budget=previous_budget,
                    expansion_trigger="output_limit",
                    expansion_requested=True,
                    expansion_target=target_budget,
                    expansion_target_before_cap=target_budget,
                    effective_budget_after_policy=target_budget,
                    expansion_applied=attempt.attempt_index < len(attempts),
                    retained_expansion_state=False,
                    runtime_reconstructed=False,
                    reconstruction_reason=None,
                    retry_owner="contract_runtime_inner",
                    route_kind=attempt.route,
                    finish_reason=(receipt or {}).get("finish_reason") if isinstance(receipt, Mapping) else None,
                    typed_failure="output_limit",
                    **cap_values,
                )
                attempt_output_tokens = target_budget
            continue
        if audit_sink is not None:
            audit_sink(conversion.audit)
        incomplete_reason = _business_incomplete_reason(
            str(getattr(response, "text", response)),
            structured_contract,
            payload=conversion.payload,
            expected_output_characters=expected_output_characters,
        )
        authoritative_domain_diagnostics = bool(
            incomplete_reason == "required_fields_missing"
            and execution_spec.domain_diagnostic_extractor is not None
            and execution_spec.domain_retry_renderer is not None
        )
        if incomplete_reason is not None and not authoritative_domain_diagnostics:
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RECEIPT_ONLY_RETRY),
                outcome="business_incomplete", failure_class=incomplete_reason,
                model_call_delta=1,
            )
            last_business_incomplete_reason = incomplete_reason
            receipt = getattr(response, "receipt", None)
            _record_business_outcome(
                gateway, response, structured_contract,
                outcome=incomplete_reason,
                failure_reason=incomplete_reason,
                expected_output_characters=expected_output_characters,
            )
            _emit_local_rejection(
                local_rejection_sink,
                response=response,
                contract=structured_contract,
                attempt=attempt,
                audit=conversion.audit,
                failure_kind="business_incomplete",
                failure_reason=incomplete_reason,
            )
            if output_limited(receipt if isinstance(receipt, dict) else None):
                previous_budget = attempt_output_tokens
                target_budget = expanded_output_budget(previous_budget)
                cap_values = lineage_cap_values(target_budget)
                observe_output_limit(
                    attempt_context,
                    requested_budget=previous_budget,
                    effective_budget=previous_budget,
                    output_tokens=(
                        int(receipt.get("output_tokens") or 0)
                        if isinstance(receipt, Mapping) else 0
                    ),
                    stop_reason=(
                        receipt.get("finish_reason")
                        if isinstance(receipt, Mapping) else None
                    ),
                    zero_visible=not bool(
                        str(getattr(response, "text", response) or "").strip()
                    ),
                    parser_reached=True,
                    strict_tool_reached=bool(
                        isinstance(receipt, Mapping)
                        and receipt.get("execution_mode") == "strict_tool"
                    ),
                    domain_validator_reached=False,
                    truncation_classifier_reason=incomplete_reason,
                    contract_output_limit_action=(
                        "terminal_exhausted"
                        if attempt.is_last else "expand_and_continue"
                    ),
                    expansion_before=previous_budget,
                    expansion_after=target_budget,
                    next_route_action=next_route_action(attempt),
                )
                emit_budget_lineage(
                    attempt_context,
                    lineage_event="expansion_decided",
                    system=route_system,
                    user=route_user,
                    contract_schema=contract_schema,
                    original_requested_output_budget=max_output_tokens,
                    current_requested_output_budget=previous_budget,
                    previous_attempt_budget=previous_budget,
                    expansion_trigger="output_limit",
                    expansion_requested=True,
                    expansion_target=target_budget,
                    expansion_target_before_cap=target_budget,
                    effective_budget_after_policy=target_budget,
                    expansion_applied=attempt.attempt_index < len(attempts),
                    retained_expansion_state=False,
                    runtime_reconstructed=False,
                    reconstruction_reason=None,
                    retry_owner="contract_runtime_inner",
                    route_kind=attempt.route,
                    finish_reason=(receipt or {}).get("finish_reason") if isinstance(receipt, Mapping) else None,
                    typed_failure="output_limit",
                    **cap_values,
                )
                attempt_output_tokens = target_budget
            last_error = ContractBusinessOutputIncompleteError(
                incomplete_reason,
                receipt=(dict(receipt) if isinstance(receipt, Mapping) else {}),
            )
            continue
        try:
            domain_value = execution_spec.domain_validator(conversion.payload)
        except (TypeError, ValueError) as exc:
            _emit_local_rejection(
                local_rejection_sink,
                response=response,
                contract=structured_contract,
                attempt=attempt,
                audit=conversion.audit,
                failure_kind="domain_validation",
                failure_reason=type(exc).__name__,
            )
            diagnostic_findings: Sequence[Mapping[str, Any]] = ()
            if execution_spec.domain_diagnostic_extractor is not None:
                try:
                    diagnostic_findings = (
                        execution_spec.domain_diagnostic_extractor(
                            conversion.payload,
                        )
                    )
                    if not isinstance(diagnostic_findings, Sequence):
                        raise TypeError(
                            "domain diagnostic extractor must return a sequence"
                        )
                except Exception:
                    if execution_spec.domain_retry_renderer is not None:
                        raise
                    diagnostic_findings = ()
            if execution_spec.domain_retry_renderer is not None:
                pending_domain_findings = diagnostic_findings
                validator_source_identity = getattr(
                    diagnostic_findings, "source_payload_sha256", None,
                )
                pending_source_identity = (
                    validator_source_identity
                    if isinstance(validator_source_identity, str)
                    else domain_sha256(
                        "r1-ptr3-domain-attempt-source-v2",
                        {
                            "contract_name": contract_name,
                            "attempt_index": attempt.attempt_index,
                            "repair_target_identity_sha256": (
                                execution_spec.domain_diagnostic_metadata or {}
                            ).get("repair_target_identity_sha256"),
                            "rejected_candidate_sha256": domain_sha256(
                                "r1-ptr3-rejected-domain-candidate-v1",
                                conversion.payload,
                            ),
                        },
                    )
                )
            observed_domain = observe_domain_validation_snapshot(
                attempt_context,
                payload=conversion.payload,
                domain_result="failed",
                findings=diagnostic_findings,
                metadata=execution_spec.domain_diagnostic_metadata or {},
            )
            if observed_domain is not None:
                last_domain_snapshot = observed_domain
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.MINIMAL_REGENERATE),
                outcome="domain_failure", failure_class="domain_validation",
                error_class=type(exc).__name__, model_call_delta=1,
            )
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
            actionable_required_field_recovery = bool(
                incomplete_reason == "required_fields_missing"
                and execution_spec.domain_diagnostic_extractor is not None
                and execution_spec.domain_retry_renderer is not None
                and execution_spec.retry_domain_failures
                and not attempt.is_last
            )
            if not actionable_required_field_recovery:
                # Route qualification is a contract-level outcome.  Do not
                # quarantine the exact route between two attempts in the same
                # already-authorized typed recovery sequence; doing so would
                # make the propagated finding unreachable.  A terminal miss
                # is still persisted fail-closed, while a successful next
                # attempt records the route as valid below.
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
                previous_budget = attempt_output_tokens
                target_budget = expanded_output_budget(previous_budget)
                cap_values = lineage_cap_values(target_budget)
                emit_budget_lineage(
                    attempt_context,
                    lineage_event="expansion_decided",
                    system=route_system,
                    user=route_user,
                    contract_schema=contract_schema,
                    original_requested_output_budget=max_output_tokens,
                    current_requested_output_budget=previous_budget,
                    previous_attempt_budget=previous_budget,
                    expansion_trigger="output_limit",
                    expansion_requested=True,
                    expansion_target=target_budget,
                    expansion_target_before_cap=target_budget,
                    effective_budget_after_policy=target_budget,
                    expansion_applied=attempt.attempt_index < len(attempts),
                    retained_expansion_state=False,
                    runtime_reconstructed=False,
                    reconstruction_reason=None,
                    retry_owner="contract_runtime_inner",
                    route_kind=attempt.route,
                    finish_reason=(receipt or {}).get("finish_reason") if isinstance(receipt, Mapping) else None,
                    typed_failure="output_limit",
                    **cap_values,
                )
                attempt_output_tokens = target_budget
            continue
        if incomplete_reason is not None:
            # An authoritative domain validator is expected to reject a
            # required-field omission.  Keep the generic gate as a fail-closed
            # backstop if a future diagnostic validator is accidentally weak.
            _observe_attempt(
                attempt_observer, attempt_id=str(attempt.attempt_index),
                parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
                route=attempt.route, route_attempt=attempt.route_attempt,
                action=str(attempt.action or RecoveryAction.RECEIPT_ONLY_RETRY),
                outcome="business_incomplete", failure_class=incomplete_reason,
                model_call_delta=1,
            )
            last_business_incomplete_reason = incomplete_reason
            receipt = getattr(response, "receipt", None)
            _record_business_outcome(
                gateway, response, structured_contract,
                outcome=incomplete_reason,
                failure_reason=incomplete_reason,
                expected_output_characters=expected_output_characters,
            )
            _emit_local_rejection(
                local_rejection_sink,
                response=response,
                contract=structured_contract,
                attempt=attempt,
                audit=conversion.audit,
                failure_kind="business_incomplete",
                failure_reason=incomplete_reason,
            )
            last_error = ContractBusinessOutputIncompleteError(
                incomplete_reason,
                receipt=(dict(receipt) if isinstance(receipt, Mapping) else {}),
            )
            continue
        observe_domain_validation_snapshot(
            attempt_context,
            payload=conversion.payload,
            domain_result="passed",
            findings=(),
            metadata=execution_spec.domain_diagnostic_metadata or {},
        )
        _record_business_outcome(
            gateway, response, structured_contract,
            outcome="valid",
            failure_reason=None,
            expected_output_characters=expected_output_characters,
        )
        receipt = getattr(response, "receipt", None)
        _observe_attempt(
            attempt_observer, attempt_id=str(attempt.attempt_index),
            parent_attempt_id=(str(attempt.attempt_index - 1) if attempt.attempt_index > 1 else None),
            route=attempt.route, route_attempt=attempt.route_attempt,
            action=str(attempt.action or RecoveryAction.RETRY_SAME_ROUTE),
            outcome="valid", failure_class=None, model_call_delta=1,
            input_tokens=(receipt or {}).get("input_tokens") if isinstance(receipt, Mapping) else None,
            output_tokens=(receipt or {}).get("output_tokens") if isinstance(receipt, Mapping) else None,
        )
        emit_ptr12_recovery(
            selected=ptr12_triggered_context is not None,
            fail_close=False,
            status=(
                "ALTERNATE_ROUTE_SELECTED"
                if ptr12_triggered_context is not None else "NORMAL_RETURN"
            ),
        )
        emit_ptr12_guard_recovery(
            attempt_context, attempt_ptr12_decision,
            alternate_route_considered=False,
            alternate_route_selected=False,
            fail_close_selected=False,
            recovery_status="NORMAL_RETURN",
        )
        return ContractRuntimeResult(
            payload=conversion.payload,
            domain_value=domain_value,
            conversion=conversion,
            model_response=response,
            attempt=attempt,
            accepted_system_sha256=hashlib.sha256(
                route_system.encode("utf-8")
            ).hexdigest(),
            accepted_user_sha256=hashlib.sha256(
                route_user.encode("utf-8")
            ).hexdigest(),
            accepted_input_sha256=hashlib.sha256(
                (route_system + "\n" + route_user).encode("utf-8")
            ).hexdigest(),
        )
    if last_error is None:  # pragma: no cover - attempt constructor is non-empty
        raise RuntimeError("structured contract runtime had no executable attempt")
    if ptr12_triggered_context is not None and not (
        final_artifact_failure_seen and not non_final_failure_seen
    ):
        emit_ptr12_recovery(
            selected=False, fail_close=False,
            status="RUNTIME_CONTINUED_EXISTING_POLICY",
        )
    if final_artifact_failure_seen and not non_final_failure_seen:
        emit_ptr12_recovery(
            selected=False, fail_close=True, status="TYPED_FAIL_CLOSE",
        )
        raise FinalArtifactCapabilityExhaustedError(
            receipt=last_receipt,
            blocked_route_fingerprints=blocked_route_fingerprints,
        ) from last_error
    if output_limit_seen and (
        isinstance(last_error, ArtifactConversionError)
        or last_business_incomplete_reason is not None
    ):
        emit_ptr12_output_limit_classification(
            attempt_context,
            output_limit_seen=True,
            receipt=last_receipt,
            terminal=True,
        )
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


async def replay_captured_contract_runtime_input_v1(
    *, capture_store: ProviderResponseCaptureStoreV1,
    expected_metadata: Mapping[str, Any],
    expected_receipt_sha256: str,
    execution_spec: ExecutableContractSpec,
    role: str = "offline_exact_response_replay",
    expected_output_characters: int = 0,
) -> ContractRuntimeResult:
    """Re-enter the production Contract Runtime from an immutable capture.

    The ledger receipt is an independent anchor: rewriting both an envelope
    header and its body cannot make the captured attempt authoritative again.
    One offline executor supplies the exact post-adapter UTF-8 bytes, while
    ``execute_contract_runtime`` remains the sole conversion, schema/business
    completeness and domain-validation owner.  No provider route is resolved
    and no retry/fallback is available during replay.
    """

    captured, _header = capture_store.replay(
        byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
        expected_metadata=expected_metadata,
        expected_receipt_sha256=expected_receipt_sha256,
    )
    try:
        captured_text = captured.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("CAPTURED_CONTRACT_RUNTIME_INPUT_UTF8_INVALID") from exc
    dispatched = False

    async def execute_once(
        _attempt: ProtocolReceiptAttempt, _role: str, _system: str,
        _user: str, _maximum: int | None,
        _contract: StructuredArtifactContract,
    ) -> ModelResult:
        nonlocal dispatched
        if dispatched:
            raise RuntimeError("CAPTURED_CONTRACT_RUNTIME_REPLAY_REDISPATCH")
        dispatched = True
        return ModelResult(captured_text, {
            "provider_call_executed": False,
            "replay_mode": "exact_captured_contract_runtime_input_v1",
            "transport_complete": bool(
                expected_metadata.get("transport_complete")
            ),
            "contract_name": execution_spec.contract_name,
        })

    result = await execute_contract_runtime(
        None, role=role, system="", user="",
        execution_spec=execution_spec,
        expected_output_characters=expected_output_characters,
        same_route_attempts=1, fallback_attempts=0,
        attempt_routes=("primary",), attempt_executor=execute_once,
    )
    if not dispatched:  # pragma: no cover - the explicit schedule is non-empty
        raise RuntimeError("CAPTURED_CONTRACT_RUNTIME_REPLAY_NOT_DISPATCHED")
    return result
