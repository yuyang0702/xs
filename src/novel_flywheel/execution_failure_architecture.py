from __future__ import annotations

"""Canonical failure, recovery, and observer contracts for real execution.

This module deliberately contains no provider client or network code.  It is
the one safe projection used when an exception graph crosses a durable or
public boundary.  Raw exception messages are neither serialized nor hashed:
they can contain credentials, request bodies, or workstation paths.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.failure_boundary import contains_potential_secret
from novel_flywheel.full_short_reason_catalog import (
    FULL_SHORT_LITERAL_REASON_CATEGORY_V1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.full_short_runtime_kernel import full_short_boundary_entry


FAILURE_ARCHITECTURE_IDENTITY = "full-short-failure-architecture-v2"
RECOVERY_REGISTRY_IDENTITY = "full-short-exact-recovery-registry-v1"
PREDISPATCH_STATE_MACHINE_IDENTITY = "full-short-predispatch-state-machine-v1"
NONCE_RESERVATION_POLICY_IDENTITY = "dispatch-ready-lazy-nonce-v1"
OBSERVER_ISOLATION_POLICY_IDENTITY = "control-vs-best-effort-observer-v1"
DURABLE_FAILURE_EVIDENCE_POLICY_IDENTITY = "safe-ordered-failure-graph-v1"


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


@dataclass(frozen=True)
class _FailureTaxonomyRuleV1:
    code: str
    family: str
    layer: FailureLayer
    boundary: str
    failure_class: FailureClass
    retryable: bool
    dispatch_state: DispatchState
    authority_effect: AuthorityEffect
    restart_behavior: RestartBehavior
    recovery_action: str


def _predispatch_rule(
    code: str, *, family: str, layer: FailureLayer,
    failure_class: FailureClass,
) -> _FailureTaxonomyRuleV1:
    return _FailureTaxonomyRuleV1(
        code=code.casefold(), family=family, layer=layer,
        boundary=f"full_short.{layer.value}", failure_class=failure_class,
        retryable=False, dispatch_state=DispatchState.NOT_REACHED,
        authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
        restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
        recovery_action="repair_local_readiness_then_fresh_authorization",
    )


# FullShort reason codes are a machine-control field.  Only exact entries may
# override the source exception's safe projection; substring/token guessing is
# deliberately not authoritative.
_FULL_SHORT_BOUNDARY_TAXONOMY_V1 = {
    code: _predispatch_rule(
        code, family=f"provider.{code.casefold().removeprefix('provider_')}",
        layer=FailureLayer.PROVIDER_CREDENTIAL,
        failure_class=FailureClass.CREDENTIAL,
    )
    for code in (
        "CREDENTIAL_ABSENT", "CREDENTIAL_EMPTY", "CREDENTIAL_SOURCE_MISSING",
        "CREDENTIAL_ACCESS_FAILED", "CREDENTIAL_ACCESS_TYPED_ERROR",
    )
} | {
    code: _predispatch_rule(
        code, family=f"provider.{code.casefold().removeprefix('provider_')}",
        layer=FailureLayer.PROVIDER_ROUTE,
        failure_class=FailureClass.CAPABILITY,
    )
    for code in (
        "PROVIDER_ROUTE_CONFIG_MISSING", "PROVIDER_CONFIG_MISSING",
        "MODEL_CONFIG_MISSING", "ROUTE_FINGERPRINT_MISMATCH",
        "CAPABILITY_UNAVAILABLE",
    )
} | {
    code: _predispatch_rule(
        code, family=f"provider.{code.casefold()}",
        layer=FailureLayer.PROVIDER_CLIENT,
        failure_class=FailureClass.CAPABILITY,
    )
    for code in (
        "CLIENT_CONFIG_CONSTRUCTION_FAILED",
        "PROVIDER_CLIENT_CONFIG_FAILED",
        "PROVIDER_CLIENT_CONSTRUCTION_FAILED",
    )
} | {
    code: _predispatch_rule(
        code, family=f"provider.{code.casefold()}",
        layer=FailureLayer.PROVIDER_REQUEST_BUILD,
        failure_class=(
            FailureClass.CAPABILITY
            if code == "REASONING_POLICY_PROJECTION_FAILED"
            else FailureClass.SYNTAX_PROTOCOL
        ),
    )
    for code in (
        "REQUEST_BUILD_FAILED", "REQUEST_SERIALIZATION_FAILED",
        "REASONING_POLICY_PROJECTION_FAILED",
    )
} | {
    code: _predispatch_rule(
        code, family="execution.authorization_binding",
        layer=FailureLayer.EXECUTION_RUNTIME_BINDING,
        failure_class=FailureClass.STALE_AUTHORITY,
    )
    for code in (
        "HEAD_DRIFT",
    )
} | {
    code: _predispatch_rule(
        code, family="execution.authorization",
        layer=FailureLayer.EXECUTION_AUTHORIZATION,
        failure_class=FailureClass.STALE_AUTHORITY,
    )
    for code in (
        "ACTIVATED_AUTHORIZATION_SHA256_MISMATCH",
        "FULL_SHORT_AUTHORIZATION_OBJECT_DRIFT",
    )
}


def _closed_literal_reason_rule(
    code: str, category: str,
) -> _FailureTaxonomyRuleV1:
    if category == "authorization":
        return _predispatch_rule(
            code, family="execution.authorization",
            layer=FailureLayer.EXECUTION_AUTHORIZATION,
            failure_class=FailureClass.STALE_AUTHORITY,
        )
    if category == "route":
        return _predispatch_rule(
            code, family="provider.route_binding",
            layer=FailureLayer.PROVIDER_ROUTE,
            failure_class=FailureClass.CAPABILITY,
        )
    if category == "readiness":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="execution.dispatch_readiness",
            layer=FailureLayer.EXECUTION_RUNTIME_BINDING,
            boundary="full_short.execution.dispatch_readiness",
            failure_class=FailureClass.STALE_AUTHORITY, retryable=False,
            dispatch_state=DispatchState.READY_NOT_COMMITTED,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="repair_readiness_then_fresh_authorization",
        )
    if category == "predispatch":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="execution.predispatch_guard",
            layer=FailureLayer.EXECUTION_RUNTIME_BINDING,
            boundary="full_short.execution.predispatch_guard",
            failure_class=FailureClass.STALE_AUTHORITY, retryable=False,
            dispatch_state=DispatchState.READY_NOT_COMMITTED,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="repair_guard_then_fresh_authorization",
        )
    if category == "no_response":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="provider.response_absent",
            layer=FailureLayer.PROVIDER_TRANSPORT,
            boundary="full_short.provider.response_absent",
            failure_class=FailureClass.TRANSPORT, retryable=False,
            dispatch_state=DispatchState.NETWORK_AMBIGUOUS,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="reconcile_absent_response_without_redispatch",
        )
    if category == "postrun":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="authority.postrun_invariant",
            layer=FailureLayer.AUTHORITY,
            boundary="full_short.authority.postrun_invariant",
            failure_class=FailureClass.SEMANTIC_INVARIANT, retryable=False,
            dispatch_state=DispatchState.NOT_REACHED,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="inspect_durable_postrun_state",
        )
    if category == "transport":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="provider.transport_boundary",
            layer=FailureLayer.PROVIDER_TRANSPORT,
            boundary="full_short.provider.transport",
            failure_class=FailureClass.TRANSPORT, retryable=False,
            dispatch_state=DispatchState.NETWORK_AMBIGUOUS,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="reconcile_without_redispatch",
        )
    if category == "response":
        return _FailureTaxonomyRuleV1(
            code=code.casefold(), family="provider.response_boundary",
            layer=FailureLayer.PROVIDER_PROTOCOL,
            boundary="full_short.provider.response",
            failure_class=FailureClass.SYNTAX_PROTOCOL, retryable=False,
            dispatch_state=DispatchState.RESPONSE_CAPTURED,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="use_exact_capture_or_stop",
        )
    return _FailureTaxonomyRuleV1(
        code=code.casefold(), family="authority.invariant",
        layer=FailureLayer.AUTHORITY,
        boundary="full_short.authority.invariant",
        failure_class=FailureClass.SEMANTIC_INVARIANT, retryable=False,
        dispatch_state=DispatchState.NOT_REACHED,
        authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior=RestartBehavior.NO_REDISPATCH,
        recovery_action="inspect_durable_state_without_redispatch",
    )


for _reason_code, _reason_category in (
    FULL_SHORT_LITERAL_REASON_CATEGORY_V1.items()
):
    _FULL_SHORT_BOUNDARY_TAXONOMY_V1.setdefault(
        _reason_code,
        _closed_literal_reason_rule(_reason_code, _reason_category),
    )


_SOURCE_EXCEPTION_TAXONOMY_V1 = {
    ("novel_flywheel.models", "ModelRoutesExhaustedError"): _FailureTaxonomyRuleV1(
        code="model_routes_exhausted",
        family="provider.routes_exhausted",
        layer=FailureLayer.PROVIDER_ROUTE,
        boundary="model_gateway.routes_exhausted",
        failure_class=FailureClass.UNKNOWN, retryable=False,
        dispatch_state=DispatchState.NOT_REACHED,
        authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior=RestartBehavior.NO_REDISPATCH,
        recovery_action="stop_after_ordered_route_exhaustion",
    ),
    ("novel_flywheel.models", "TransportInterruptedError"): _FailureTaxonomyRuleV1(
        code="transport_interrupted", family="provider.transport_interrupted",
        layer=FailureLayer.PROVIDER_TRANSPORT,
        boundary="provider.transport.interrupted",
        failure_class=FailureClass.TRANSPORT, retryable=False,
        dispatch_state=DispatchState.NETWORK_AMBIGUOUS,
        authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior=RestartBehavior.NO_REDISPATCH,
        recovery_action="reconcile_transport_without_redispatch",
    ),
    (
        "novel_flywheel.models", "CapabilityRoutesExhaustedError",
    ): _FailureTaxonomyRuleV1(
        code="capability_routes_exhausted",
        family="provider.capability_routes_exhausted",
        layer=FailureLayer.PROVIDER_ROUTE,
        boundary="model_gateway.capability_routes_exhausted",
        failure_class=FailureClass.CAPABILITY, retryable=False,
        dispatch_state=DispatchState.NOT_REACHED,
        authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
        restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
        recovery_action="repair_capability_route_then_fresh_authorization",
    ),
    (
        "novel_flywheel.models", "ReasoningOnlyFinalArtifactUnavailableError",
    ): _FailureTaxonomyRuleV1(
        code="reasoning_only_final_artifact_unavailable",
        family="provider.reasoning_only_final_artifact_unavailable",
        layer=FailureLayer.PROVIDER_FINAL_ARTIFACT,
        boundary="model_gateway.final_artifact",
        failure_class=FailureClass.OUTPUT_TRUNCATION, retryable=False,
        dispatch_state=DispatchState.RESPONSE_CAPTURED,
        authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
        restart_behavior=RestartBehavior.NO_REDISPATCH,
        recovery_action="use_typed_shared_finalization_slot_or_stop",
    ),
}


_CONNECTION_ERROR_RULE = _FailureTaxonomyRuleV1(
    code="connection_error", family="provider.transport_interrupted",
    layer=FailureLayer.PROVIDER_TRANSPORT,
    boundary="provider.transport.connection",
    failure_class=FailureClass.TRANSPORT, retryable=False,
    dispatch_state=DispatchState.NETWORK_AMBIGUOUS,
    authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
    restart_behavior=RestartBehavior.NO_REDISPATCH,
    recovery_action="reconcile_transport_without_redispatch",
)


def full_short_boundary_taxonomy_v1(
    reason_code: str,
) -> dict[str, object] | None:
    """Return the closed taxonomy projection for one exact control reason."""

    normalized = re.sub(
        r"[^A-Z0-9]+", "_", str(reason_code).upper(),
    ).strip("_")
    rule = _FULL_SHORT_BOUNDARY_TAXONOMY_V1.get(normalized)
    if rule is None:
        return None
    return {
        "code": rule.code, "family": rule.family, "layer": rule.layer,
        "boundary": rule.boundary, "failure_class": rule.failure_class,
        "retryable": rule.retryable, "dispatch_state": rule.dispatch_state,
        "authority_effect": rule.authority_effect,
        "restart_behavior": rule.restart_behavior,
        "recovery_action": rule.recovery_action,
    }


def _explicit_taxonomy_rule(
    exc: BaseException,
) -> _FailureTaxonomyRuleV1 | None:
    reason_code = getattr(exc, "reason_code", None)
    if isinstance(reason_code, str):
        normalized = re.sub(
            r"[^A-Z0-9]+", "_", reason_code.upper(),
        ).strip("_")
        rule = _FULL_SHORT_BOUNDARY_TAXONOMY_V1.get(normalized)
        if rule is not None:
            return rule
    rule = _SOURCE_EXCEPTION_TAXONOMY_V1.get((
        type(exc).__module__, type(exc).__name__,
    ))
    if rule is not None:
        return rule
    if isinstance(exc, ConnectionError):
        return _CONNECTION_ERROR_RULE
    return None


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
    route_ordinal: int | None = Field(default=None, ge=1)
    provider_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    model_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
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


class ProviderRequestBuildFailure(ExecutionBoundaryFailure):
    """Local provider request materialization failed before dispatch authority."""

    def __init__(self, code: str = "request_build_failed") -> None:
        super().__init__(
            code, layer=FailureLayer.PROVIDER_REQUEST_BUILD,
            boundary="provider_http.request_materialization",
            failure_class=FailureClass.SYNTAX_PROTOCOL,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=RestartBehavior.FRESH_AUTHORIZATION_REQUIRED,
            recovery_action="repair_request_materialization_then_fresh_authorization",
        )


def _safe_name(value: object, *, fallback: str) -> str:
    raw_text = str(value or "").strip()
    if contains_potential_secret(raw_text):
        return fallback
    text = raw_text.casefold()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_.-"
    normalized = "".join(character if character in allowed else "_" for character in text)
    normalized = normalized.strip("_.-")
    normalized = normalized[:160]
    sensitive = (
        normalized.startswith(("sk-", "sk_", "bearer_", "bearer-"))
        or "private_credential" in normalized
        or "secret_value" in normalized
        or "api_key_value" in normalized
        or "password_value" in normalized
    )
    return fallback if not normalized or sensitive else normalized


def _safe_failure_code(value: object) -> str:
    """Reject opaque long tokens; failure codes must be visibly structured."""

    normalized = _safe_name(value, fallback="unclassified_failure")
    if not re.fullmatch(
        r"[a-z][a-z0-9]{1,31}(?:[._][a-z0-9][a-z0-9]{0,31}){0,9}",
        normalized,
    ):
        return "unclassified_failure"
    return normalized


def _safe_exception_class(exc: BaseException) -> str:
    name = type(exc).__name__
    folded = name.casefold()
    module = str(getattr(type(exc), "__module__", ""))
    source_owned = module == "novel_flywheel" or module.startswith("novel_flywheel.")
    if (
        len(name) <= 80
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        # Long CamelCase project exception names are source-controlled class
        # identifiers, not external high-entropy values.  Preserve them while
        # retaining the entropy screen for unknown/external exception types.
        and (source_owned or not contains_potential_secret(name))
        and not folded.startswith(("sk_", "bearer_"))
        and "privatecredential" not in folded
        and "secretvalue" not in folded
    ):
        return name
    return "RedactedExceptionClass"


def _enum_value(enum_type: type[StrEnum], value: object, default: StrEnum) -> StrEnum:
    try:
        return enum_type(str(getattr(value, "value", value)))
    except ValueError:
        return default


def _identity_sha256(value: object) -> str | None:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _ordered_children(
    exc: BaseException,
) -> tuple[tuple[BaseException, int, str | None, str | None], ...]:
    children: list[tuple[BaseException, int, str | None, str | None]] = []
    source_exception = getattr(exc, "source_exception", None)
    if isinstance(source_exception, BaseException):
        children.append((source_exception, 1, None, None))
    route_errors = getattr(exc, "route_errors", None)
    if isinstance(route_errors, (list, tuple)):
        for ordinal, item in enumerate(route_errors, len(children) + 1):
            candidate: object = item
            provider_id: object = None
            model_id: object = None
            if isinstance(item, RouteFailureAttemptV1):
                candidate = item.error
                provider_sha = item.provider_id_sha256
                model_sha = item.model_id_sha256
            elif isinstance(item, Mapping):
                candidate = item.get("error")
                provider_sha = _identity_sha256(item.get("provider_id"))
                model_sha = _identity_sha256(item.get("model_id"))
            elif isinstance(item, (list, tuple)) and item:
                candidate = item[-1]
                provider_id = item[0] if len(item) >= 2 else None
                model_id = item[1] if len(item) >= 3 else None
                provider_sha = _identity_sha256(provider_id)
                model_sha = _identity_sha256(model_id)
            else:
                provider_sha = None
                model_sha = None
            if isinstance(candidate, BaseException):
                children.append((candidate, ordinal, provider_sha, model_sha))
    if not children:
        for ordinal, attribute in enumerate(
            ("primary_error", "fallback_error"), 1,
        ):
            candidate = getattr(exc, attribute, None)
            if isinstance(candidate, BaseException):
                children.append((candidate, ordinal, None, None))
    for candidate in (
        exc.__cause__, None if exc.__suppress_context__ else exc.__context__,
    ):
        if (
            isinstance(candidate, BaseException)
            and all(candidate is not item[0] for item in children)
        ):
            children.append((candidate, len(children) + 1, None, None))
    return tuple(children)


def _layer_for_boundary(boundary: str) -> FailureLayer:
    value = boundary.casefold()
    for prefix, layer in (
        ("provider_registry.resolve", FailureLayer.PROVIDER_ROUTE),
        ("provider.route", FailureLayer.PROVIDER_ROUTE),
        ("credential", FailureLayer.PROVIDER_CREDENTIAL),
        ("provider_response", FailureLayer.PROVIDER_RESPONSE_ADAPTER),
        ("provider_transport", FailureLayer.PROVIDER_TRANSPORT),
        ("contract", FailureLayer.CONTRACT),
        ("business", FailureLayer.BUSINESS_COMPLETENESS),
        ("authority", FailureLayer.AUTHORITY),
        ("artifact", FailureLayer.ARTIFACT),
        ("observer", FailureLayer.OBSERVER),
        ("completion_supervisor", FailureLayer.WORKFLOW_RECOVERY),
        ("workflow", FailureLayer.WORKFLOW_RECOVERY),
        ("model_gateway", FailureLayer.WORKFLOW_RECOVERY),
    ):
        if value.startswith(prefix):
            return layer
    return FailureLayer.EXTERNAL


def _node(
    exc: BaseException, *, boundary: str, ancestors: frozenset[int],
    is_child: bool, route_ordinal: int | None = None,
    provider_id_sha256: str | None = None,
    model_id_sha256: str | None = None,
) -> SafeFailureNodeV1:
    if id(exc) in ancestors:
        return SafeFailureNodeV1(
            code="failure_graph_cycle", family="failure_graph",
            layer=FailureLayer.UNKNOWN, boundary=boundary,
            source_exception_class=_safe_exception_class(exc),
            failure_class=FailureClass.UNKNOWN, retryable=False,
            dispatch_state=DispatchState.NOT_REACHED,
            authority_effect=AuthorityEffect.PRESERVES_LAST_ACCEPTED,
            restart_behavior=RestartBehavior.NO_REDISPATCH,
            recovery_action="inspect_typed_failure",
            route_ordinal=route_ordinal,
            provider_id_sha256=provider_id_sha256,
            model_id_sha256=model_id_sha256,
        )
    child_ancestors = ancestors | {id(exc)}
    explicit_rule = _explicit_taxonomy_rule(exc)
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
    if code == "unclassified_failure":
        code = "unknown_child" if is_child else "external_unknown_after_boundary"
    family = _safe_name(
        getattr(exc, "failure_family", "") or f"{failure_class.value}.failure",
        fallback="unknown.failure",
    )
    layer = _enum_value(
        FailureLayer,
        getattr(exc, "failure_layer", _layer_for_boundary(node_boundary)),
        _layer_for_boundary(node_boundary),
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
    retryable = bool(getattr(reliability, "retryable", False))
    if explicit_rule is not None:
        code = explicit_rule.code
        family = explicit_rule.family
        layer = explicit_rule.layer
        node_boundary = explicit_rule.boundary
        failure_class = explicit_rule.failure_class
        retryable = explicit_rule.retryable
        dispatch_state = explicit_rule.dispatch_state
        authority_effect = explicit_rule.authority_effect
        restart_behavior = explicit_rule.restart_behavior
        recovery_action = explicit_rule.recovery_action
    children = tuple(
        _node(
            child, boundary=node_boundary, ancestors=child_ancestors,
            is_child=True, route_ordinal=ordinal,
            provider_id_sha256=provider_sha,
            model_id_sha256=model_sha,
        )
        for child, ordinal, provider_sha, model_sha in _ordered_children(exc)
    )
    if children and type(exc).__name__ in {
        "ModelRoutesExhaustedError", "CapabilityRoutesExhaustedError",
    }:
        if any(
            child.dispatch_state == DispatchState.RESPONSE_CAPTURED
            for child in children
        ):
            dispatch_state = DispatchState.RESPONSE_CAPTURED
        elif any(
            child.dispatch_state in {
                DispatchState.NETWORK_AMBIGUOUS,
                DispatchState.COMMITTED_PRE_NETWORK,
            }
            for child in children
        ):
            dispatch_state = DispatchState.NETWORK_AMBIGUOUS
        else:
            dispatch_state = DispatchState.NETWORK_AMBIGUOUS
        authority_effect = AuthorityEffect.PRESERVES_LAST_ACCEPTED
        restart_behavior = RestartBehavior.NO_REDISPATCH
    return SafeFailureNodeV1(
        code=code, family=family, layer=layer, boundary=node_boundary or "unknown",
        source_exception_class=_safe_exception_class(exc), failure_class=failure_class,
        retryable=retryable,
        dispatch_state=dispatch_state, authority_effect=authority_effect,
        restart_behavior=restart_behavior, recovery_action=recovery_action,
        route_ordinal=route_ordinal,
        provider_id_sha256=provider_id_sha256,
        model_id_sha256=model_id_sha256,
        children=children,
    )


def build_durable_failure_evidence(
    exc: BaseException, *, boundary: str,
) -> DurableFailureEvidenceV1:
    root = _node(
        exc, boundary=boundary, ancestors=frozenset(), is_child=False,
    )
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
    "shared_second_slot": ["reasoning_finalization", "business_recovery"],
    "maximum_accepted_final_artifacts": 1,
    "route_switch_allowed": False,
    "provider_retry_allowed": False,
    "transport_recovery": "complete_capture_local_exact_replay_only",
    "unknown_failure_disposition": "terminal",
    "layer_default_policies": {
        "execution.authorization": "terminal_fresh_authorization",
        "execution.runtime_binding": "terminal_fresh_authorization",
        "provider.route": "terminal_before_credential",
        "provider.credential": "terminal_before_nonce",
        "provider.client": "terminal_before_nonce",
        "provider.request_build": "terminal_before_nonce",
        "provider.transport": "terminal_no_redispatch",
        "provider.protocol": "terminal_no_redispatch",
        "provider.response_adapter": "terminal_or_exact_local_replay",
        "provider.final_artifact": "typed_shared_second_slot_or_terminal",
        "contract": "typed_shared_second_slot_or_terminal",
        "business.completeness": "typed_shared_second_slot_or_terminal",
        "workflow.recovery": "terminal_at_shared_ceiling",
        "authority": "terminal_preserve_last_accepted",
        "artifact": "terminal_preserve_last_accepted",
        "observer": "continue_original_business_outcome",
        "external": "terminal_no_redispatch",
        "unknown": "terminal_no_redispatch",
    },
    "failure_policies": {
        "business_incomplete": {
            "recovery": "shared_second_slot_same_route",
            "max_network_redispatches": 1,
            "restart": "no_redispatch",
        },
        "reasoning_only_final_artifact_unavailable": {
            "recovery": "shared_second_slot_reasoning_effort_none",
            "max_network_redispatches": 1,
            "restart": "no_redispatch",
        },
        "complete_valid_capture": {
            "recovery": "local_exact_replay",
            "max_network_redispatches": 0,
            "restart": "exact_replay_only",
        },
        "explicit_provider_error": {
            "recovery": "terminal",
            "max_network_redispatches": 0,
            "restart": "fresh_authorization_required",
        },
        "transport_ambiguous": {
            "recovery": "terminal",
            "max_network_redispatches": 0,
            "restart": "no_redispatch",
        },
        "structured_parse_or_schema": {
            "recovery": "shared_second_slot_same_route",
            "max_network_redispatches": 1,
            "restart": "no_redispatch",
        },
        "semantic_failure": {
            "recovery": "shared_second_slot_same_route",
            "max_network_redispatches": 1,
            "restart": "no_redispatch",
        },
        "draft_local_repair": {
            "recovery": "local_owned_scope_only",
            "max_network_redispatches": 0,
            "restart": "checkpoint_resume_allowed",
        },
        "review_repair": {
            "recovery": "shared_second_slot_same_route",
            "max_network_redispatches": 1,
            "restart": "no_redispatch",
        },
        "credential_unavailable": {
            "recovery": "terminal_before_nonce",
            "max_network_redispatches": 0,
            "restart": "fresh_authorization_required",
        },
        "route_unavailable": {
            "recovery": "terminal_before_credential",
            "max_network_redispatches": 0,
            "restart": "fresh_authorization_required",
        },
        "client_or_request_build_failure": {
            "recovery": "terminal_before_nonce",
            "max_network_redispatches": 0,
            "restart": "fresh_authorization_required",
        },
        "unknown_child": {
            "recovery": "terminal",
            "max_network_redispatches": 0,
            "restart": "no_redispatch",
        },
    },
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

    @full_short_boundary_entry("FS.RECOVERY.DECIDE")
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
        policy_key = (
            "reasoning_only_final_artifact_unavailable"
            if recovery_kind == "reasoning_finalization"
            else "business_incomplete"
        )
        policy = FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1[
            "failure_policies"
        ][policy_key]
        if (
            policy["max_network_redispatches"] != 1
            or not str(policy["recovery"]).startswith("shared_second_slot")
        ):
            raise ExactRecoveryViolation("registry_disallows_second_slot")
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


PREDISPATCH_STATE_MACHINE_V1 = {
    "identity": PREDISPATCH_STATE_MACHINE_IDENTITY,
    "ordering": [
        "authorization_exact", "public_route_readiness", "capability_readiness",
        "jit_approval", "credential_readiness", "client_config_readiness",
        "request_and_reasoning_projection", "wire_and_egress_exact",
        "dispatch_ready_receipt", "durable_nonce", "dispatch_commit", "network",
    ],
    "knowable_local_failure_nonce_disposition": "ABSENT_LOCAL_READINESS",
    "post_nonce_pre_network_crash_disposition": (
        "CONSUMED_DISPATCH_COMMIT_PENDING_NO_REDISPATCH"
    ),
}

NONCE_RESERVATION_POLICY_V1 = {
    "identity": NONCE_RESERVATION_POLICY_IDENTITY,
    "reservation_point": "AFTER_DISPATCH_READY_RECEIPT",
    "single_use": True,
    "restart_after_reservation": "FAIL_CLOSED_NO_REDISPATCH",
}

OBSERVER_ISOLATION_POLICY_V1 = {
    "identity": OBSERVER_ISOLATION_POLICY_IDENTITY,
    "control_evidence": [
        "nonce", "dispatch_ledger", "exact_capture", "local_stage_receipt",
    ],
    "best_effort": [
        "console", "run_event", "telemetry", "crewai_cleanup", "resource_close",
    ],
    "business_outcome_mutation_allowed": False,
}

DURABLE_FAILURE_EVIDENCE_POLICY_V1 = {
    "identity": DURABLE_FAILURE_EVIDENCE_POLICY_IDENTITY,
    "architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
    "ordered_children_required": True,
    "raw_exception_message_persisted": False,
    "raw_prompt_story_or_credential_persisted": False,
    "unknown_child_disposition": "UNKNOWN_CHILD_TERMINAL",
}


def _definition_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


PREDISPATCH_STATE_MACHINE_SHA256 = _definition_sha256(
    PREDISPATCH_STATE_MACHINE_V1
)
NONCE_RESERVATION_POLICY_SHA256 = _definition_sha256(
    NONCE_RESERVATION_POLICY_V1
)
OBSERVER_ISOLATION_POLICY_SHA256 = _definition_sha256(
    OBSERVER_ISOLATION_POLICY_V1
)
DURABLE_FAILURE_EVIDENCE_POLICY_SHA256 = _definition_sha256(
    DURABLE_FAILURE_EVIDENCE_POLICY_V1
)
