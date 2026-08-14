"""Canary-only outcome taxonomy, separate from production incident rates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CanaryOutcome(str, Enum):
    CANARY_BLOCKED_PRE_PROVIDER = "CANARY_BLOCKED_PRE_PROVIDER"
    CANARY_STARTED = "CANARY_STARTED"
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
