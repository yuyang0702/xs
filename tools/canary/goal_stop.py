"""Canary-only observation-goal latch and trace interception.

The latch never participates in production workflow state.  It observes only
the hash-only reliability envelope inside an isolated Canary process and
prevents a later Canary Provider boundary from being dispatched.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterator, Mapping
from unittest.mock import patch


GOAL_OUTCOME = "TARGET_STRICT_TOOL_SHAPE_OBSERVED"
STOP_OUTCOME = "CANARY_OBSERVATION_GOAL_REACHED_STOPPED"
STOP_REASON = "target_strict_tool_shape_exact_captured"


class CanaryObservationGoalReachedStop(asyncio.CancelledError):
    """Typed Canary stop; production failure and incident classifiers do not own it."""

    reason_code = STOP_REASON

    def __init__(
        self, *, blocked_boundary_ordinal: int | None = None,
        reason_code: str = STOP_REASON,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.blocked_boundary_ordinal = blocked_boundary_ordinal


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ObservationGoalLatch:
    """Thread-safe, idempotent first-exact-target-wins observation latch."""

    def __init__(self, *, receipt_path: Path | None = None) -> None:
        self.receipt_path = receipt_path
        self._lock = threading.RLock()
        self._reached = False
        self._first: dict[str, Any] | None = None
        self._duplicate_count = 0
        self._sink_failure_count = 0
        self._receipt_write_failure_count = 0
        self._blocked_dispatch_count = 0
        self._first_blocked_boundary_ordinal: int | None = None

    @staticmethod
    def _exact_target(envelope: Any) -> dict[str, Any] | None:
        if _field(envelope, "event_type") != "diagnostic_strict_tool_shape":
            return None
        payload = _field(envelope, "payload") or {}
        if not isinstance(payload, Mapping):
            return None
        if payload.get("target_status") != "target":
            return None
        if payload.get("observation_status") != "exact":
            return None
        if _field(envelope, "observation_status") != "confirmed":
            return None
        observation_hash = payload.get("observation_sha256")
        correlation_hash = payload.get("shape_correlation_sha256")
        if not all(
            isinstance(item, str) and len(item) == 64
            for item in (observation_hash, correlation_hash)
        ):
            return None
        return {
            "observation_sha256": observation_hash,
            "shape_correlation_sha256": correlation_hash,
            "observation_status": "exact",
            "strict_tool_decision": payload.get("strict_tool_decision"),
            "strict_tool_failure_code": payload.get("strict_tool_failure_code"),
            "stage_id": _field(envelope, "stage_id"),
        }

    def observe(self, envelope: Any) -> bool:
        """Record an exact target before the best-effort trace append runs."""
        target = self._exact_target(envelope)
        if target is None:
            return False
        first = False
        with self._lock:
            if self._reached:
                self._duplicate_count += 1
            else:
                self._reached = True
                self._first = target
                first = True
            receipt = self._snapshot_unlocked()
        self._persist_receipt(receipt)
        return first

    def record_sink_failure(self) -> None:
        with self._lock:
            self._sink_failure_count += 1
            receipt = self._snapshot_unlocked()
        self._persist_receipt(receipt)

    def _persist_receipt(self, receipt: Mapping[str, Any]) -> None:
        if self.receipt_path is None:
            return
        body = dict(receipt)
        body["receipt_sha256"] = _canonical_hash(body)
        encoded = (
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        temporary = self.receipt_path.with_suffix(self.receipt_path.suffix + ".tmp")
        try:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600,
            )
            try:
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError("partial goal receipt write")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, self.receipt_path)
        except Exception:
            with self._lock:
                self._receipt_write_failure_count += 1
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass

    def raise_if_reached(self, *, boundary_ordinal: int | None = None) -> None:
        with self._lock:
            if not self._reached:
                return
            self._blocked_dispatch_count += 1
            if self._first_blocked_boundary_ordinal is None:
                self._first_blocked_boundary_ordinal = boundary_ordinal
        raise CanaryObservationGoalReachedStop(
            blocked_boundary_ordinal=boundary_ordinal,
        )

    @property
    def reached(self) -> bool:
        with self._lock:
            return self._reached

    def _snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "schema": "CanaryObservationGoalReceiptV1",
            "version": 1,
            "observation_goal_reached": self._reached,
            "observation_goal_outcome": GOAL_OUTCOME if self._reached else None,
            "stop_outcome": STOP_OUTCOME if self._reached else None,
            "stop_reason": STOP_REASON if self._reached else None,
            "first_exact_target": dict(self._first) if self._first else None,
            "duplicate_observation_count": self._duplicate_count,
            "sink_failure_count": self._sink_failure_count,
            "receipt_write_failure_count": self._receipt_write_failure_count,
            "blocked_dispatch_count": self._blocked_dispatch_count,
            "first_blocked_boundary_ordinal": self._first_blocked_boundary_ordinal,
            "raw_content_included": False,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def observation_summary(self, trace_summary: Mapping[str, Any] | None) -> dict[str, Any]:
        """Prefer the trace report; retain hash-only exact evidence if its sink failed."""
        with self._lock:
            first = dict(self._first) if self._first else None
            failures = self._sink_failure_count
        if trace_summary and trace_summary.get("target_observation_count", 0):
            return dict(trace_summary)
        if first is None:
            return dict(trace_summary or {
                "observation_goal_outcome": "TARGET_NOT_REACHED",
                "target_observation_count": 0,
                "damaged_trace_line_count": 0,
                "observations": [],
                "raw_content_included": False,
            })
        return {
            "observation_goal_outcome": GOAL_OUTCOME,
            "target_observation_count": 1,
            "damaged_trace_line_count": 0,
            "observations": [first],
            "trace_sink_failure_count": failures,
            "observation_source": "canary_goal_latch",
            "raw_content_included": False,
        }


@contextmanager
def capture_reliability_trace_goal(
    latch: ObservationGoalLatch | None,
) -> Iterator[None]:
    """Install a process-local Canary observer; never alter production source."""
    if latch is None:
        with nullcontext():
            yield
        return

    from novel_flywheel.reliability_trace import BestEffortTraceSink

    original_emit = BestEffortTraceSink.emit

    def intercept(sink: Any, envelope: Any) -> bool:
        latch.observe(envelope)
        try:
            written = bool(original_emit(sink, envelope))
        except BaseException:
            latch.record_sink_failure()
            return False
        if not written and latch._exact_target(envelope) is not None:
            latch.record_sink_failure()
        return written

    with patch.object(BestEffortTraceSink, "emit", intercept):
        yield
