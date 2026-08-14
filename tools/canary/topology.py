"""C0B Short dispatch and elapsed hard-budget definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from novel_flywheel.runtime_fingerprint_build import domain_sha256


def c0b_short_call_topology_v1() -> dict:
    # One-segment 6K workload. The component values are Canary-authorized
    # paid-dispatch slots, not a claim that every semantic recovery transition
    # must be consumed. Each logical boundary owns at most two primary and two
    # configured-fallback route attempts in Contract Runtime.
    components = {
        "normal_primary": 16,
        "normal_protocol_retry": 16,
        "normal_configured_fallback": 16,
        "normal_fallback_retry": 16,
        "bounded_scoped_repair_dispatches": 32,
        "quality_correction_dispatches": 32,
        "maintenance_repair_dispatches": 8,
        "role_fallback_dispatches": 8,
    }
    body = {
        "schema": "C0BShortCallTopologyV1", "version": 1,
        "workload_id": "short-normal-v1", "target_words": 6000,
        "segment_count": 1,
        "expected_logical_boundaries": 16,
        "expected_primary_calls": 16,
        "maximum_primary_calls": 36,
        "maximum_protocol_retries": 36,
        "maximum_configured_fallback_calls": 36,
        "maximum_repair_calls": 32,
        "maximum_maintenance_extra_calls": 8,
        "provider_hidden_retry_calls": 0,
        "resume_paid_continuation": "within_same_single_use_budget_and_window_only",
        "per_boundary_route_schedule": {
            "primary": 1, "protocol_retry": 1,
            "configured_fallback": 1, "fallback_retry": 1,
        },
        "maximum_components": components,
        "maximum_total_paid_dispatches": sum(components.values()),
        "maximum_kind": "exact_canary_authorization_cap",
        "runtime_theoretical_global_maximum": "NOT_GLOBALLY_BOUNDED",
        "runtime_theoretical_maximum_reason": (
            "planning adaptation resets per-unit attempt counters after each "
            "strictly improved candidate; Runtime has no single workflow-wide "
            "paid-dispatch counter"
        ),
        "first_terminal_stop": True,
        "terminal_semantics": (
            "the first terminal or controlled provider capability outcome stops "
            "the cohort; dispatch 145 is rejected before credential lookup"
        ),
        "evidence": {
            "observed_normal_boundary_count": 16,
            "runtime_same_route_attempts": 2,
            "runtime_configured_fallback_attempts": 2,
            "source_locations": [
                "src/novel_flywheel/contract_runtime.py:model_route_attempts",
                "src/novel_flywheel/workflows.py:_short_pipeline",
                "src/novel_flywheel/workflows.py:_quality_polish",
                "src/novel_flywheel/workflows.py:_close_short_maintenance_authority",
                "src/novel_flywheel/workflows.py:_ensure_short_plan_adaptations:12101-12111",
            ],
        },
    }
    return {
        **body, "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-short-call-topology-v1", body,
        ),
    }


def expand_dispatch_schedule(logical_boundaries: int = 36) -> list[dict]:
    if logical_boundaries < 0:
        raise ValueError("logical_boundary_count_invalid")
    schedule = []
    kinds = (
        ("primary", 1), ("protocol_retry", 2),
        ("configured_fallback", 1), ("fallback_retry", 2),
    )
    for boundary in range(1, logical_boundaries + 1):
        for kind, route_attempt in kinds:
            schedule.append({
                "ordinal": len(schedule) + 1, "logical_boundary": boundary,
                "attempt_kind": kind, "route_attempt": route_attempt,
            })
    return schedule


def verify_topology_source_contract(source_text: str) -> dict:
    checks = {
        "runtime_primary_attempts_two": "same_route_attempts: int = 2" in source_text,
        "runtime_fallback_attempts_two": "fallback_attempts: int = 2" in source_text,
        "one_segment_for_6000": "if target_words <= 8000:" in source_text,
        "causal_repair_two": "for repair_attempt in range(1, 3):" in source_text,
        "manifest_repair_two": "for semantic_repair in range(2):" in source_text,
        "maintenance_repair_two": "for attempt in range(2):" in source_text,
        "short_quality_two_corrections": '"max_corrections": 2 if enhanced else 1' in source_text,
        "planning_improvement_resets_attempts": "targeted_attempts = {}" in source_text
        and "rebuild_attempts = {}" in source_text,
    }
    return {
        "schema": "C0BShortTopologySourceAuditV1",
        "status": "exact" if all(checks.values()) else "drift",
        "checks": checks,
    }


@dataclass(frozen=True)
class C0BElapsedBudgetV1:
    expected_duration_seconds: int
    provider_timeout_seconds: int
    worst_legal_stage_seconds: int
    worst_legal_run_seconds: int
    fingerprint_overhead_seconds: int
    hard_launcher_timeout_seconds: int

    @classmethod
    def from_topology(cls, topology: dict) -> "C0BElapsedBudgetV1":
        maximum = int(topology["maximum_total_paid_dispatches"])
        provider_timeout = 180
        # Four sequential explicit route attempts plus bounded preflight work.
        worst_stage = provider_timeout * 4 + 8
        # The 144 slots include repair/role-fallback schedules. Fingerprint
        # revalidation is budgeted from C0A p95 (~1.1s) at 2s/slot, with a
        # fixed 10-minute local artifact/DB allowance.
        fingerprint = maximum * 2
        worst_run = maximum * provider_timeout + fingerprint + 600
        return cls(
            expected_duration_seconds=1800,
            provider_timeout_seconds=provider_timeout,
            worst_legal_stage_seconds=worst_stage,
            worst_legal_run_seconds=worst_run,
            fingerprint_overhead_seconds=fingerprint,
            hard_launcher_timeout_seconds=worst_run + 300,
        )

    def require_remaining(self, elapsed_seconds: float) -> None:
        if elapsed_seconds > self.hard_launcher_timeout_seconds:
            raise TimeoutError("elapsed_budget_exceeded")

    def definition(self) -> dict:
        body = {"schema": "C0BElapsedBudgetV1", "version": 1, **asdict(self)}
        return {
            **body, "definition_sha256": domain_sha256(
                "novel-flywheel-c0b-elapsed-budget-v1", body,
            ),
        }
