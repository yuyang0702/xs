from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable, Mapping


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
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CREDENTIAL: (
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CAPABILITY: (
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.CONTEXT_CAPACITY: (
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.OUTPUT_TRUNCATION: (
        RecoveryAction.INCREASE_VERIFIED_HEADROOM,
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.SYNTAX_PROTOCOL: (
        RecoveryAction.LOCAL_NORMALIZE,
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.OWNERSHIP_EVIDENCE: (
        RecoveryAction.AST_OWNERSHIP_REPAIR,
        RecoveryAction.RECEIPT_ONLY_RETRY,
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.REBUILD_COMPLETE_UNIT,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.SEMANTIC_INVARIANT: (
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.REBUILD_COMPLETE_UNIT,
        RecoveryAction.SEMANTIC_SPLIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.QUALITY_REGRESSION: (
        RecoveryAction.PATCH_SMALLEST_UNIT,
        RecoveryAction.FALLBACK_CAPABLE_ROUTE,
        RecoveryAction.RESTORE_BEST,
    ),
    FailureClass.STALE_AUTHORITY: (
        RecoveryAction.RELOAD_AUTHORITY,
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
