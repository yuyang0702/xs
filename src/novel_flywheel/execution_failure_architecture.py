from __future__ import annotations

"""Canonical failure, recovery, and observer contracts for real execution.

This module deliberately contains no provider client or network code.  It is
the one safe projection used when an exception graph crosses a durable or
public boundary.  Raw exception messages are neither serialized nor hashed:
they can contain credentials, request bodies, or workstation paths.
"""

from collections.abc import Callable, Mapping
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


FAILURE_ARCHITECTURE_IDENTITY = "full-short-failure-architecture-v2"
RECOVERY_REGISTRY_IDENTITY = "full-short-exact-recovery-registry-v1"


class FailureLayer(StrEnum):
    EXECUTION_AUTHORIZATION = "execution.authorization"
    EXECUTION_RUNTIME_BINDING = "execution.runtime_binding"
    PROVIDER_ROUTE = "provider.route"
    PROVIDER_CREDENTIAL = "provider.credential"
    PROVIDER_CLIENT = "provider.client"
    PROVIDER_REQUEST_BUILD = "provider.request_build"
    PROVIDER_TRANSPORT = "provider.transport"
    PROVIDER_PROTOCOL = "provider.protocol"
    PROVIDER_RESPONSE_ADAPTER = "provider.response_adapter"
    PROVIDER_FINAL_ARTIFACT = "provider.final_artifact"
    CONTRACT = "contract"
    BUSINESS_COMPLETENESS = "business.completeness"
    WORKFLOW_RECOVERY = "workflow.recovery"
    AUTHORITY = "authority"
    ARTIFACT = "artifact"
    OBSERVER = "observer"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class DispatchState(StrEnum):
    NOT_REACHED = "not_reached"
    READY_NOT_COMMITTED = "ready_not_committed"
    COMMITTED_PRE_NETWORK = "committed_pre_network"
    NETWORK_AMBIGUOUS = "network_ambiguous"
    RESPONSE_CAPTURED = "response_captured"


class AuthorityEffect(StrEnum):
    NONE = "none"
    BLOCKS_ACCEPTANCE = "blocks_acceptance"
    PRESERVES_LAST_ACCEPTED = "preserves_last_accepted"
    INVALIDATES_CANDIDATE = "invalidates_candidate"
    REQUIRES_FRESH_AUTHORIZATION = "requires_fresh_authorization"


class RestartBehavior(StrEnum):
    LOCAL_RETRY_ALLOWED = "local_retry_allowed"
    CHECKPOINT_RESUME_ALLOWED = "checkpoint_resume_allowed"
    EXACT_REPLAY_ONLY = "exact_replay_only"
    NO_REDISPATCH = "no_redispatch"
    FRESH_AUTHORIZATION_REQUIRED = "fresh_authorization_required"


class SafeFailureNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    code: str = Field(min_length=3, max_length=160)
    family: str = Field(min_length=3, max_length=160)
    layer: FailureLayer
    boundary: str = Field(min_length=1, max_length=200)
    source_exception_class: str = Field(min_length=1, max_length=160)
    failure_class: FailureClass
    retryable: bool
    dispatch_state: DispatchState
    authority_effect: AuthorityEffect
    restart_behavior: RestartBehavior
    recovery_action: str = Field(min_length=1, max_length=200)
    children: tuple["SafeFailureNodeV1", ...] = ()


class DurableFailureEvidenceV1(BaseModel):
    """Secret-free, ordered, recursively complete durable failure evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    architecture_identity: Literal["full-short-failure-architecture-v2"] = (
        FAILURE_ARCHITECTURE_IDENTITY
    )
    root: SafeFailureNodeV1
    failure_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def event_metadata(self) -> dict[str, Any]:
        return {
            "failure_contract": FAILURE_ARCHITECTURE_IDENTITY,
            "failure_graph_sha256": self.failure_graph_sha256,
            "failure_graph": self.root.model_dump(mode="json"),
        }


class RouteFailureAttemptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: str = Field(min_length=1, max_length=80)
    provider_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    model_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    error: BaseException

    model_config = ConfigDict(
        extra="forbid", frozen=True, arbitrary_types_allowed=True,
    )


class ExecutionBoundaryFailure(ValueError):
    """Typed exception that retains a safe owning layer and restart policy."""

    def __init__(
        self, code: str, *, layer: FailureLayer, boundary: str,
        failure_class: FailureClass = FailureClass.UNKNOWN,
        retryable: bool = False,
        dispatch_state: DispatchState = DispatchState.NOT_REACHED,
        authority_effect: AuthorityEffect = AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior: RestartBehavior = RestartBehavior.NO_REDISPATCH,
        recovery_action: str = "inspect_typed_failure",
    ) -> None:
        super().__init__(code)
        self.failure_layer = layer
        self.dispatch_state = dispatch_state
        self.authority_effect = authority_effect
        self.restart_behavior = restart_behavior
        self.recovery_action = recovery_action
        self.reliability_failure = ReliabilityFailure(
            code=code,
            failure_class=failure_class,
            boundary=boundary,
            message="",
            retryable=retryable,
        )


class ProviderRouteFailure(ExecutionBoundaryFailure):
    def __init__(self, code: str) -> None:
        super().__init__(
            code, layer=FailureLayer.PROVIDER_ROUTE,
            boundary="provider_registry.resolve_public_route",
            failure_class=FailureClass.CAPABILITY,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="correct_authorized_route_binding",
        )


class ProviderCredentialFailure(ExecutionBoundaryFailure):
    def __init__(self, code: str) -> None:
        super().__init__(
            code, layer=FailureLayer.PROVIDER_CREDENTIAL,
            boundary="provider_registry.credential_lookup",
            failure_class=FailureClass.CREDENTIAL,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="provision_credential_then_fresh_authorization",
        )


class ProviderClientConstructionFailure(ExecutionBoundaryFailure):
    def __init__(self, code: str = "provider_client_construction_failed") -> None:
        super().__init__(
            code, layer=FailureLayer.PROVIDER_CLIENT,
            boundary="provider_registry.client_construction",
            failure_class=FailureClass.CAPABILITY,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="repair_client_configuration_then_fresh_authorization",
        )


def _safe_name(value: object, *, fallback: str) -> str:
    text = str(value or "").strip().casefold()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_.-"
    normalized = "".join(character if character in allowed else "_" for character in text)
    normalized = normalized.strip("_.-")
    return (normalized or fallback)[:160]


def _safe_failure_code(value: object) -> str:
    """Reject opaque long tokens; failure codes must be visibly structured."""

    normalized = _safe_name(value, fallback="unclassified_failure")
    if len(normalized) > 32 and not any(mark in normalized for mark in "._-"):
        return "unclassified_failure"
    return normalized


def _enum_value(enum_type: type[StrEnum], value: object, default: StrEnum) -> StrEnum:
    try:
        return enum_type(str(getattr(value, "value", value)))
    except ValueError:
        return default


def _ordered_children(exc: BaseException) -> tuple[BaseException, ...]:
    children: list[BaseException] = []
    route_errors = getattr(exc, "route_errors", None)
    if isinstance(route_errors, (list, tuple)):
        for item in route_errors:
            candidate: object = item
            if isinstance(item, RouteFailureAttemptV1):
                candidate = item.error
            elif isinstance(item, Mapping):
                candidate = item.get("error")
            elif isinstance(item, (list, tuple)) and item:
                candidate = item[-1]
            if isinstance(candidate, BaseException):
                children.append(candidate)
    if not children:
        for attribute in ("primary_error", "fallback_error"):
            candidate = getattr(exc, attribute, None)
            if isinstance(candidate, BaseException):
                children.append(candidate)
    for candidate in (
        exc.__cause__, None if exc.__suppress_context__ else exc.__context__,
    ):
        if isinstance(candidate, BaseException) and candidate not in children:
            children.append(candidate)
    return tuple(children)


def _node(
    exc: BaseException, *, boundary: str, seen: set[int],
) -> SafeFailureNodeV1:
    if id(exc) in seen:
        return SafeFailureNodeV1(
            code="failure_graph_cycle", family="failure_graph",
            layer=FailureLayer.UNKNOWN, boundary=boundary,
            source_exception_class=type(exc).__name__,
            failure_class=FailureClass.UNKNOWN, retryable=False,
            dispatch_state=DispatchState.NOT_REACHED,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="inspect_typed_failure",
        )
    seen.add(id(exc))
    reliability = getattr(exc, "reliability_failure", None)
    raw_failure_class = getattr(reliability, "failure_class", FailureClass.UNKNOWN)
    failure_class = _enum_value(
        FailureClass, raw_failure_class, FailureClass.UNKNOWN,
    )
    node_boundary = _safe_name(
        getattr(reliability, "boundary", "") or boundary,
        fallback="unknown_boundary",
    )
    code = _safe_failure_code(getattr(reliability, "code", ""))
    family = _safe_name(
        getattr(exc, "failure_family", "") or f"{failure_class.value}.failure",
        fallback="unknown.failure",
    )
    layer = _enum_value(
        FailureLayer, getattr(exc, "failure_layer", FailureLayer.UNKNOWN),
        FailureLayer.UNKNOWN,
    )
    dispatch_state = _enum_value(
        DispatchState, getattr(exc, "dispatch_state", DispatchState.NOT_REACHED),
        DispatchState.NOT_REACHED,
    )
    authority_effect = _enum_value(
        AuthorityEffect,
        getattr(exc, "authority_effect", AuthorityEffect.PRESERVES_LAST_ACCEPTED),
        AuthorityEffect.PRESERVES_LAST_ACCEPTED,
    )
    restart_behavior = _enum_value(
        RestartBehavior,
        getattr(exc, "restart_behavior", RestartBehavior.NO_REDISPATCH),
        RestartBehavior.NO_REDISPATCH,
    )
    recovery_action = _safe_name(
        getattr(exc, "recovery_action", ""), fallback="inspect_typed_failure",
    )
    children = tuple(
        _node(child, boundary=node_boundary, seen=seen)
        for child in _ordered_children(exc)
    )
    return SafeFailureNodeV1(
        code=code, family=family, layer=layer, boundary=node_boundary or "unknown",
        source_exception_class=type(exc).__name__, failure_class=failure_class,
        retryable=bool(getattr(reliability, "retryable", False)),
        dispatch_state=dispatch_state, authority_effect=authority_effect,
        restart_behavior=restart_behavior, recovery_action=recovery_action,
        children=children,
    )


def build_durable_failure_evidence(
    exc: BaseException, *, boundary: str,
) -> DurableFailureEvidenceV1:
    root = _node(exc, boundary=boundary, seen=set())
    canonical = json.dumps(
        root.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return DurableFailureEvidenceV1(
        root=root, failure_graph_sha256=hashlib.sha256(canonical).hexdigest(),
    )


class ObserverGuard:
    """Fail-open wrapper exclusively for diagnostic/best-effort observers."""

    def __init__(self, on_failure: Callable[[BaseException], None] | None = None) -> None:
        self.on_failure = on_failure

    def emit(self, operation: Callable[[], Any]) -> bool:
        try:
            operation()
            return True
        except Exception as exc:  # diagnostics may never alter business outcome
            if self.on_failure is not None:
                try:
                    self.on_failure(exc)
                except Exception:
                    pass
            return False


FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1: dict[str, Any] = {
    "identity": RECOVERY_REGISTRY_IDENTITY,
    "max_physical_attempts_per_logical_stage": 2,
    "shared_second_slot": ("reasoning_finalization", "business_recovery"),
    "maximum_accepted_final_artifacts": 1,
    "route_switch_allowed": False,
    "provider_retry_allowed": False,
    "transport_recovery": "complete_capture_local_exact_replay_only",
    "unknown_failure_disposition": "terminal",
}


FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256 = hashlib.sha256(json.dumps(
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
).encode("utf-8")).hexdigest()


class ExactRecoveryViolation(RuntimeError):
    pass


class FullShortExactRecoveryControllerV1:
    """One authoritative in-memory mirror of the durable N/N+1 policy."""

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._accepted: set[str] = set()

    def record_initial_attempt(self, logical_stage_id: str) -> None:
        if self._attempts.get(logical_stage_id, 0) != 0:
            raise ExactRecoveryViolation("initial_attempt_already_recorded")
        self._attempts[logical_stage_id] = 1

    def authorize_shared_second_slot(
        self, logical_stage_id: str, *, typed_rejection_code: str,
        recovery_kind: Literal["reasoning_finalization", "business_recovery"],
        route_switch: bool = False,
    ) -> int:
        if route_switch:
            raise ExactRecoveryViolation("route_switch_forbidden")
        if not typed_rejection_code:
            raise ExactRecoveryViolation("typed_rejection_required")
        if self._attempts.get(logical_stage_id) != 1:
            raise ExactRecoveryViolation("shared_second_slot_unavailable")
        if logical_stage_id in self._accepted:
            raise ExactRecoveryViolation("artifact_already_accepted")
        if recovery_kind == "reasoning_finalization" and typed_rejection_code != (
            "reasoning_only_final_artifact_unavailable"
        ):
            raise ExactRecoveryViolation("reasoning_recovery_without_exact_rejection")
        self._attempts[logical_stage_id] = 2
        return 2

    def accept_final_artifact(self, logical_stage_id: str) -> None:
        if logical_stage_id in self._accepted:
            raise ExactRecoveryViolation("multiple_final_artifacts_forbidden")
        if self._attempts.get(logical_stage_id, 0) not in {1, 2}:
            raise ExactRecoveryViolation("artifact_without_physical_attempt")
        self._accepted.add(logical_stage_id)

    def attempt_count(self, logical_stage_id: str) -> int:
        return self._attempts.get(logical_stage_id, 0)
