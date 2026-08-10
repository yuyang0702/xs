from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Callable, Iterable, Literal, Mapping


class FailureClass(StrEnum):
    TRANSPORT = "transport"
    CREDENTIAL = "credential"
    CAPABILITY = "capability"
    CONTEXT_CAPACITY = "context_capacity"
    OUTPUT_TRUNCATION = "output_truncation"
    SYNTAX_PROTOCOL = "syntax_protocol"
    OWNERSHIP_EVIDENCE = "ownership_evidence"
    SEMANTIC_INVARIANT = "semantic_invariant"
    QUALITY_REGRESSION = "quality_regression"
    STALE_AUTHORITY = "stale_authority"
    UNKNOWN = "unknown"


class ValidationStage(StrEnum):
    TRANSPORT = "transport"
    SYNTAX = "syntax"
    OWNERSHIP = "ownership"
    LOCAL_SEMANTICS = "local_semantics"
    ADJACENT_HANDOFF = "adjacent_handoff"
    WHOLE_STORY = "whole_story"
    QUALITY = "quality"


VALIDATION_STAGE_ORDER = {
    stage: index for index, stage in enumerate(ValidationStage)
}


class RecoveryAction(StrEnum):
    LOCAL_NORMALIZE = "local_normalize"
    AST_OWNERSHIP_REPAIR = "ast_ownership_repair"
    RECEIPT_ONLY_RETRY = "receipt_only_retry"
    RETRY_SAME_ROUTE = "retry_same_route"
    INCREASE_VERIFIED_HEADROOM = "increase_verified_headroom"
    PATCH_SMALLEST_UNIT = "patch_smallest_unit"
    REBUILD_COMPLETE_UNIT = "rebuild_complete_unit"
    SEMANTIC_SPLIT = "semantic_split"
    FALLBACK_CAPABLE_ROUTE = "fallback_capable_route"
    RELOAD_AUTHORITY = "reload_authority"
    RESTORE_BEST = "restore_best"
    MINIMAL_REGENERATE = "minimal_regenerate"
    RESUME_CHECKPOINT = "resume_checkpoint"


@dataclass(frozen=True)
class ProtocolReceiptAttempt:
    """One route-isolated attempt in a bounded receipt recovery schedule."""

    attempt_index: int
    route_attempt: int
    route: Literal["primary", "configured_fallback"]
    action: RecoveryAction | None
    is_last: bool

    @property
    def use_configured_fallback(self) -> bool:
        return self.route == "configured_fallback"


@dataclass
class _ProtocolRouteCircuitState:
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open_probe: bool = False
    last_failure_code: str = "protocol_route_transport_interrupted"
    last_failure_class: FailureClass = FailureClass.TRANSPORT


class ProtocolRouteCircuitBreaker:
    """Run-scoped circuit breaker for explicit immutable-receipt routes.

    Only failures proving that a selected route could not execute count toward
    the circuit.  Syntax, ownership, semantic, and capacity failures remain in
    their own recovery layers.  An open circuit periodically admits one
    half-open probe so a recovered third-party route can rejoin automatically.
    """

    def __init__(
        self, *, failure_threshold: int = 2, cooldown_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._states: dict[tuple[str, str, str], _ProtocolRouteCircuitState] = {}

    @staticmethod
    def _key(run_id: str, role: str, route: str) -> tuple[str, str, str]:
        return str(run_id), str(role), str(route)

    def acquire(self, run_id: str, role: str, route: str) -> str:
        """Return ``closed``, ``half_open``, or ``open`` for one route call."""

        state = self._states.get(self._key(run_id, role, route))
        if state is None or state.opened_at is None:
            return "closed"
        if (
            not state.half_open_probe
            and self._clock() - state.opened_at >= self.cooldown_seconds
        ):
            state.half_open_probe = True
            return "half_open"
        return "open"

    def record_execution_failure(
        self, run_id: str, role: str, route: str, *,
        failure_code: str = "protocol_route_transport_interrupted",
        failure_class: FailureClass = FailureClass.TRANSPORT,
    ) -> bool:
        """Record a route-execution failure and report a closed-to-open edge."""

        key = self._key(run_id, role, route)
        state = self._states.setdefault(key, _ProtocolRouteCircuitState())
        was_open = state.opened_at is not None
        state.consecutive_failures += 1
        state.last_failure_code = failure_code
        state.last_failure_class = failure_class
        if state.half_open_probe or state.consecutive_failures >= self.failure_threshold:
            state.opened_at = self._clock()
            state.half_open_probe = False
        return not was_open and state.opened_at is not None

    def last_failure(
        self, run_id: str, role: str, route: str,
    ) -> tuple[str, FailureClass]:
        state = self._states.get(self._key(run_id, role, route))
        if state is None:
            return "protocol_route_transport_interrupted", FailureClass.TRANSPORT
        return state.last_failure_code, state.last_failure_class

    def record_route_response(self, run_id: str, role: str, route: str) -> bool:
        """Close the circuit after any response that reached validation."""

        key = self._key(run_id, role, route)
        state = self._states.get(key)
        if state is None:
            return False
        was_open = state.opened_at is not None
        self._states.pop(key, None)
        return was_open


def protocol_receipt_attempts(
    *, same_route_attempts: int,
    configured_fallback_available: bool,
    fallback_attempts: int = 1,
) -> tuple[ProtocolReceiptAttempt, ...]:
    """Build one provider-agnostic protocol recovery route schedule.

    Syntax/receipt defects first retry the immutable contract on the selected
    route.  Exhaustion then moves to the configured independent route.  The
    schedule is typed and bounded; callers validate every returned artifact
    through the same canonical contract and domain authority.
    """

    if same_route_attempts < 1:
        raise ValueError("same_route_attempts must be positive")
    if fallback_attempts < 0:
        raise ValueError("fallback_attempts cannot be negative")
    routes: list[tuple[Literal["primary", "configured_fallback"], int,
                       RecoveryAction | None]] = []
    for route_attempt in range(1, same_route_attempts + 1):
        routes.append((
            "primary",
            route_attempt,
            None if route_attempt == 1 else RecoveryAction.RECEIPT_ONLY_RETRY,
        ))
    if configured_fallback_available:
        for route_attempt in range(1, fallback_attempts + 1):
            routes.append((
                "configured_fallback",
                route_attempt,
                RecoveryAction.FALLBACK_CAPABLE_ROUTE,
            ))
    return tuple(
        ProtocolReceiptAttempt(
            attempt_index=index,
            route_attempt=route_attempt,
            route=route,
            action=action,
            is_last=index == len(routes),
        )
        for index, (route, route_attempt, action) in enumerate(routes, 1)
    )


@dataclass(frozen=True)
class ReliabilityFailure:
    code: str
    failure_class: FailureClass
    boundary: str
    unit_id: str = "whole"
    message: str = ""
    protocol_only: bool = False
    retryable: bool = True


@dataclass(frozen=True)
class RecoveryCandidate:
    issue_keys: frozenset[str]
    scope_hashes: Mapping[str, str] = field(default_factory=dict)
    quality: Mapping[str, float] = field(default_factory=dict)
    issues: tuple["RecoveryIssue", ...] = ()


@dataclass(frozen=True)
class RecoveryIssue:
    key: str
    stage: ValidationStage
    unit_id: str = "whole"
    root_key: str = ""
    blocked_by: tuple[str, ...] = ()
    revealed_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateDecision:
    accepted: bool
    reason: str
    resolved_issue_keys: tuple[str, ...]
    introduced_issue_keys: tuple[str, ...]
    quality_regressions: tuple[str, ...] = ()
    changed_unowned_scopes: tuple[str, ...] = ()
    revealed_issue_keys: tuple[str, ...] = ()
    previous_stage: str = ""
    candidate_stage: str = ""


DEFAULT_LADDERS: dict[FailureClass, tuple[RecoveryAction, ...]] = {
    FailureClass.TRANSPORT: (
        RecoveryAction.RETRY_SAME_ROUTE,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CREDENTIAL: (
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CAPABILITY: (
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CONTEXT_CAPACITY: (
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.OUTPUT_TRUNCATION: (
        RecoveryAction.INCREASE_VERIFIED_HEADROOM,
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.MINIMAL_REGENERATE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.SYNTAX_PROTOCOL: (
        RecoveryAction.LOCAL_NORMALIZE,
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.MINIMAL_REGENERATE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.OWNERSHIP_EVIDENCE: (
        RecoveryAction.AST_OWNERSHIP_REPAIR,
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.REBUILD_COMPLETE_UNIT,
        RecoveryAction.MINIMAL_REGENERATE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.SEMANTIC_INVARIANT: (
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.REBUILD_COMPLETE_UNIT,
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.MINIMAL_REGENERATE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.QUALITY_REGRESSION: (
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.STALE_AUTHORITY: (
        RecoveryAction.RELOAD_AUTHORITY,
        RecoveryAction.RESUME_CHECKPOINT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.UNKNOWN: (RecoveryAction.RESTORE_BEST,),
}


def compare_recovery_candidates(
    previous: RecoveryCandidate,
    candidate: RecoveryCandidate,
    *, changed_scopes: Iterable[str] = (),
    quality_tolerance: float = 0.0,
) -> CandidateDecision:
    """Apply staged monotonic progress to every generated mutation.

    A syntax repair is allowed to reveal an ownership or semantic issue that
    the earlier broken representation masked.  It is not allowed to introduce
    an issue at the same or an earlier validation stage.  Legacy callers that
    provide only flat keys retain the historical strict-subset behavior.
    """
    changed = {str(item) for item in changed_scopes}
    introduced = tuple(sorted(candidate.issue_keys - previous.issue_keys))
    resolved = tuple(sorted(previous.issue_keys - candidate.issue_keys))
    changed_unowned = tuple(sorted(
        scope for scope, old_hash in previous.scope_hashes.items()
        if scope not in changed
        and candidate.scope_hashes.get(scope, old_hash) != old_hash
    ))
    quality_regressions = tuple(sorted(
        key for key, old_value in previous.quality.items()
        if candidate.quality.get(key, old_value) + quality_tolerance < old_value
    ))
    revealed: tuple[str, ...] = ()
    previous_stage = ""
    candidate_stage = ""
    blocking_introduced = introduced
    stage_progress = False
    if previous.issues or candidate.issues:
        previous_by_key = {item.key: item for item in previous.issues}
        candidate_by_key = {item.key: item for item in candidate.issues}
        previous_ranks = [
            VALIDATION_STAGE_ORDER[item.stage] for item in previous.issues
        ]
        candidate_ranks = [
            VALIDATION_STAGE_ORDER[item.stage] for item in candidate.issues
        ]
        if previous_ranks:
            active_rank = min(previous_ranks)
            previous_stage = list(ValidationStage)[active_rank].value
            if candidate_ranks:
                candidate_stage = list(ValidationStage)[min(candidate_ranks)].value
            previous_active = {
                item.key for item in previous.issues
                if VALIDATION_STAGE_ORDER[item.stage] == active_rank
            }
            candidate_active = {
                item.key for item in candidate.issues
                if VALIDATION_STAGE_ORDER[item.stage] == active_rank
            }
            blocking_introduced = tuple(sorted(
                key for key in introduced
                if key not in candidate_by_key
                or VALIDATION_STAGE_ORDER[candidate_by_key[key].stage] <= active_rank
            ))
            revealed = tuple(sorted(set(introduced) - set(blocking_introduced)))
            earlier_candidate = any(
                rank < active_rank for rank in candidate_ranks
            )
            stage_progress = (
                len(candidate_active) < len(previous_active)
                and not earlier_candidate
            )
        else:
            blocking_introduced = introduced
    else:
        stage_progress = bool(resolved) and not introduced

    accepted = (
        stage_progress
        and not blocking_introduced
        and not changed_unowned
        and not quality_regressions
    )
    reason = (
        "stage_progress_revealed_later_issue"
        if accepted and revealed else
        "strict_improvement" if accepted else
        "introduced_hard_issue" if blocking_introduced else
        "unowned_scope_changed" if changed_unowned else
        "quality_regression" if quality_regressions else
        "no_semantic_progress"
    )
    return CandidateDecision(
        accepted=accepted,
        reason=reason,
        resolved_issue_keys=resolved,
        introduced_issue_keys=blocking_introduced,
        quality_regressions=quality_regressions,
        changed_unowned_scopes=changed_unowned,
        revealed_issue_keys=revealed,
        previous_stage=previous_stage,
        candidate_stage=candidate_stage,
    )


class RecoveryController:
    """Choose one bounded recovery action per typed failure and unit."""

    def __init__(
        self, *, ladders: Mapping[FailureClass, tuple[RecoveryAction, ...]] | None = None,
    ) -> None:
        self.ladders = dict(ladders or DEFAULT_LADDERS)
        self.attempts: dict[tuple[str, FailureClass], int] = {}

    def next_action(
        self, failure: ReliabilityFailure, *, capable_fallback: bool = True,
    ) -> RecoveryAction:
        if not failure.retryable:
            return RecoveryAction.RESTORE_BEST
        key = (failure.unit_id, failure.failure_class)
        attempt = self.attempts.get(key, 0)
        ladder = self.ladders.get(failure.failure_class, DEFAULT_LADDERS[FailureClass.UNKNOWN])
        action = ladder[min(attempt, len(ladder) - 1)]
        self.attempts[key] = attempt + 1
        if action == RecoveryAction.FALLBACK_CAPABLE_ROUTE and not capable_fallback:
            return RecoveryAction.RESTORE_BEST
        return action

    def record_progress(self, unit_id: str) -> None:
        """Strict progress refreshes budgets only for the still-failing unit."""
        for key in list(self.attempts):
            if key[0] == unit_id:
                del self.attempts[key]
