"""Conservative, atomic pre-dispatch budget reservations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import threading
import time
from typing import Callable


class CanaryBudgetExceeded(RuntimeError):
    """Typed refusal raised before a Canary paid-boundary reservation."""

    def __init__(
        self, reason_code: str, *, dimension: str = "unknown",
        approved_ceiling: int | None = None,
        already_reserved: int | None = None,
        requested_reservation: int | None = None,
        remaining_before_request: int | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.dimension = dimension
        self.approved_ceiling = approved_ceiling
        self.already_reserved = already_reserved
        self.requested_reservation = requested_reservation
        self.remaining_before_request = remaining_before_request


@dataclass(frozen=True)
class BudgetLimits:
    maximum_model_calls_per_run: int
    maximum_total_model_calls: int
    maximum_input_tokens: int
    maximum_output_tokens: int
    maximum_estimated_cost_microunits: int
    maximum_elapsed_seconds: int


@dataclass(frozen=True)
class BudgetReservation:
    ordinal: int
    run_id_hash: str
    attempt_kind: str
    input_tokens: int
    output_tokens: int
    estimated_cost_microunits: int


class AtomicBudgetLedger:
    """Never releases reservations; missing usage therefore cannot become zero."""

    def __init__(
        self, limits: BudgetLimits, *, monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits
        self._monotonic = monotonic
        self._started = monotonic()
        self._lock = threading.Lock()
        self._calls_by_run: dict[str, int] = {}
        self._reservations: list[BudgetReservation] = []
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost = 0
        self._reported_usage: dict[int, dict[str, int | str]] = {}

    @staticmethod
    def _exceeded(
        reason_code: str, dimension: str, ceiling: int, reserved: int,
        requested: int,
    ) -> CanaryBudgetExceeded:
        return CanaryBudgetExceeded(
            reason_code, dimension=dimension, approved_ceiling=ceiling,
            already_reserved=reserved, requested_reservation=requested,
            remaining_before_request=max(0, ceiling - reserved),
        )

    def _check_locked(
        self, *, run_id_hash: str, input_tokens: int, output_tokens: int,
        estimated_cost_microunits: int,
    ) -> None:
        elapsed = int(self._monotonic() - self._started)
        if elapsed > self.limits.maximum_elapsed_seconds:
            raise self._exceeded(
                "elapsed_budget_exceeded", "elapsed_seconds",
                self.limits.maximum_elapsed_seconds, elapsed, 0,
            )
        run_reserved = self._calls_by_run.get(run_id_hash, 0)
        if run_reserved + 1 > self.limits.maximum_model_calls_per_run:
            raise self._exceeded(
                "single_run_call_budget_exceeded", "per_run_calls",
                self.limits.maximum_model_calls_per_run, run_reserved, 1,
            )
        total_reserved = len(self._reservations)
        if total_reserved + 1 > self.limits.maximum_total_model_calls:
            raise self._exceeded(
                "cohort_call_budget_exceeded", "cohort_calls",
                self.limits.maximum_total_model_calls, total_reserved, 1,
            )
        for reason, dimension, ceiling, reserved, requested in (
            ("input_token_budget_exceeded", "input_tokens", self.limits.maximum_input_tokens, self._input_tokens, input_tokens),
            ("output_token_budget_exceeded", "output_tokens", self.limits.maximum_output_tokens, self._output_tokens, output_tokens),
            ("cost_budget_exceeded", "legacy_cost_microunits", self.limits.maximum_estimated_cost_microunits, self._cost, estimated_cost_microunits),
        ):
            if reserved + requested > ceiling:
                raise self._exceeded(reason, dimension, ceiling, reserved, requested)

    def preview(
        self, *, run_id_hash: str, input_tokens: int, output_tokens: int,
        estimated_cost_microunits: int,
    ) -> None:
        values = (input_tokens, output_tokens, estimated_cost_microunits)
        if any(type(item) is not int or item < 0 for item in values):
            raise CanaryBudgetExceeded("budget_reservation_invalid")
        with self._lock:
            self._check_locked(
                run_id_hash=run_id_hash, input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_microunits=estimated_cost_microunits,
            )

    def reserve(
        self, *, run_id_hash: str, attempt_kind: str, input_tokens: int,
        output_tokens: int, estimated_cost_microunits: int,
    ) -> BudgetReservation:
        values = (input_tokens, output_tokens, estimated_cost_microunits)
        if any(type(item) is not int or item < 0 for item in values):
            raise CanaryBudgetExceeded("budget_reservation_invalid")
        with self._lock:
            self._check_locked(
                run_id_hash=run_id_hash, input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_microunits=estimated_cost_microunits,
            )
            run_calls = self._calls_by_run.get(run_id_hash, 0) + 1
            total_calls = len(self._reservations) + 1
            next_input = self._input_tokens + input_tokens
            next_output = self._output_tokens + output_tokens
            next_cost = self._cost + estimated_cost_microunits
            reservation = BudgetReservation(
                ordinal=total_calls, run_id_hash=run_id_hash,
                attempt_kind=attempt_kind, input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_microunits=estimated_cost_microunits,
            )
            self._calls_by_run[run_id_hash] = run_calls
            self._input_tokens = next_input
            self._output_tokens = next_output
            self._cost = next_cost
            self._reservations.append(reservation)
            return reservation

    def record_provider_usage(
        self, ordinal: int, *, input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        with self._lock:
            if ordinal < 1 or ordinal > len(self._reservations):
                raise CanaryBudgetExceeded("reservation_not_found")
            if input_tokens is None or output_tokens is None:
                self._reported_usage[ordinal] = {"status": "missing_reserved_value_retained"}
                return
            if min(input_tokens, output_tokens) < 0:
                raise CanaryBudgetExceeded("provider_usage_invalid")
            self._reported_usage[ordinal] = {
                "status": "reported", "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "reservation_count": len(self._reservations),
                "calls_by_run": dict(sorted(self._calls_by_run.items())),
                "reserved_input_tokens": self._input_tokens,
                "reserved_output_tokens": self._output_tokens,
                "reserved_cost_microunits": self._cost,
                "reservations": [asdict(item) for item in self._reservations],
                "reported_usage": {
                    str(key): value for key, value in sorted(self._reported_usage.items())
                },
            }
