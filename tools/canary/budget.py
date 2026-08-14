"""Conservative, atomic pre-dispatch budget reservations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import threading
import time
from typing import Callable


class CanaryBudgetExceeded(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


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

    def reserve(
        self, *, run_id_hash: str, attempt_kind: str, input_tokens: int,
        output_tokens: int, estimated_cost_microunits: int,
    ) -> BudgetReservation:
        values = (input_tokens, output_tokens, estimated_cost_microunits)
        if any(type(item) is not int or item < 0 for item in values):
            raise CanaryBudgetExceeded("budget_reservation_invalid")
        with self._lock:
            if self._monotonic() - self._started > self.limits.maximum_elapsed_seconds:
                raise CanaryBudgetExceeded("elapsed_budget_exceeded")
            run_calls = self._calls_by_run.get(run_id_hash, 0) + 1
            if run_calls > self.limits.maximum_model_calls_per_run:
                raise CanaryBudgetExceeded("single_run_call_budget_exceeded")
            total_calls = len(self._reservations) + 1
            if total_calls > self.limits.maximum_total_model_calls:
                raise CanaryBudgetExceeded("cohort_call_budget_exceeded")
            next_input = self._input_tokens + input_tokens
            if next_input > self.limits.maximum_input_tokens:
                raise CanaryBudgetExceeded("input_token_budget_exceeded")
            next_output = self._output_tokens + output_tokens
            if next_output > self.limits.maximum_output_tokens:
                raise CanaryBudgetExceeded("output_token_budget_exceeded")
            next_cost = self._cost + estimated_cost_microunits
            if next_cost > self.limits.maximum_estimated_cost_microunits:
                raise CanaryBudgetExceeded("cost_budget_exceeded")
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
