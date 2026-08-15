"""Canary-only outcome taxonomy, separate from production incident rates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CanaryOutcome(str, Enum):
    CANARY_BLOCKED_PRE_PROVIDER = "CANARY_BLOCKED_PRE_PROVIDER"
    CANARY_BUDGET_EXHAUSTED = "CANARY_BUDGET_EXHAUSTED"
    CANARY_STARTED = "CANARY_STARTED"
    CANARY_OBSERVATION_GOAL_REACHED_STOPPED = "CANARY_OBSERVATION_GOAL_REACHED_STOPPED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    CONTROLLED_NONTERMINAL = "CONTROLLED_NONTERMINAL"
    WORKFLOW_TERMINAL = "WORKFLOW_TERMINAL"
    CANARY_INFRASTRUCTURE_FAILURE = "CANARY_INFRASTRUCTURE_FAILURE"


@dataclass(frozen=True)
class CanaryOutcomeRecord:
    outcome: CanaryOutcome
    reason_code: str
    workflow_terminal_counted: bool
    production_incident_counted: bool = False


def blocked_outcome(reason_code: str) -> CanaryOutcomeRecord:
    return CanaryOutcomeRecord(
        CanaryOutcome.CANARY_BLOCKED_PRE_PROVIDER,
        reason_code,
        workflow_terminal_counted=False,
    )


def infrastructure_outcome(reason_code: str) -> CanaryOutcomeRecord:
    return CanaryOutcomeRecord(
        CanaryOutcome.CANARY_INFRASTRUCTURE_FAILURE,
        reason_code,
        workflow_terminal_counted=False,
    )


def budget_exhausted_outcome(reason_code: str) -> CanaryOutcomeRecord:
    return CanaryOutcomeRecord(
        CanaryOutcome.CANARY_BUDGET_EXHAUSTED,
        reason_code,
        workflow_terminal_counted=False,
        production_incident_counted=False,
    )


def observation_goal_stopped_outcome(reason_code: str) -> CanaryOutcomeRecord:
    return CanaryOutcomeRecord(
        CanaryOutcome.CANARY_OBSERVATION_GOAL_REACHED_STOPPED,
        reason_code,
        workflow_terminal_counted=False,
        production_incident_counted=False,
    )


def outcome_for_boundary_abort(kind: str, reason_code: str) -> CanaryOutcomeRecord:
    """Typed mapping; callers must pass the abort kind, never exception text."""
    if kind == "budget_exhausted":
        return budget_exhausted_outcome(reason_code)
    return blocked_outcome(reason_code)
