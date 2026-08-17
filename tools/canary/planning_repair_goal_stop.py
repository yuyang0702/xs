"""Canary-only safe-stop state for Planning repair observation.

The latch observes R1-PTR1 hash-only reliability events.  It never changes
production workflow state.  A/B evidence may finish its current Planning
recovery path; the latch stops before the next major Provider boundary.  A
naturally observed fallback/output-limit amplifier closes the goal earlier,
but only a later Provider dispatch is blocked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping

from .goal_stop import (
    CanaryObservationGoalReachedStop,
    STOP_OUTCOME,
    _canonical_hash,
    _field,
)


STOP_REASON = "planning_repair_observation_goal_safe_stop"
PRIMARY_OUTCOME = "PRIMARY_EVIDENCE_CAPTURED"
NOT_EXERCISED_OUTCOME = "PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED"
PARTIAL_OUTCOME = "PLANNING_REPAIR_OBSERVATION_PARTIAL_EVIDENCE"


def _hash(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) == 64 else None


class PlanningRepairObservationGoalLatch:
    """First typed observation wins; stop is deferred to a safe boundary."""

    _EVENTS = {
        "diagnostic_planning_repair_domain",
        "diagnostic_planning_repair_finding_propagation",
        "diagnostic_provider_content_block_shape",
        "diagnostic_planning_repair_output_limit",
    }

    def __init__(self, *, receipt_path: Path | None = None) -> None:
        self.receipt_path = receipt_path
        self._lock = threading.RLock()
        self._domain: dict[str, Any] | None = None
        self._propagation: dict[str, Any] | None = None
        self._provider_shape: dict[str, Any] | None = None
        self._output_limit: dict[str, Any] | None = None
        self._reached = False
        self._outcome: str | None = None
        self._seen_dispatch = False
        self._duplicate_count = 0
        self._sink_failure_count = 0
        self._receipt_write_failure_count = 0
        self._blocked_dispatch_count = 0
        self._first_blocked_boundary_ordinal: int | None = None

    @staticmethod
    def _exact_target(envelope: Any) -> dict[str, Any] | None:
        event_type = _field(envelope, "event_type")
        if event_type not in PlanningRepairObservationGoalLatch._EVENTS:
            return None
        if _field(envelope, "observation_status") != "confirmed":
            return None
        payload = _field(envelope, "payload") or {}
        if not isinstance(payload, Mapping):
            return None
        schema = payload.get("schema")
        expected = {
            "diagnostic_planning_repair_domain": (
                "PlanningRepairDomainValidationSnapshotV1"
            ),
            "diagnostic_planning_repair_finding_propagation": (
                "PlanningRepairFindingPropagationSnapshotV1"
            ),
            "diagnostic_provider_content_block_shape": (
                "ProviderContentBlockShapeSnapshotV1"
            ),
            "diagnostic_planning_repair_output_limit": (
                "PlanningRepairOutputLimitObservationV1"
            ),
        }[str(event_type)]
        if schema != expected:
            return None
        return {"event_type": event_type, "payload": payload}

    @staticmethod
    def _domain_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if payload.get("domain_result") != "failed":
            return None
        if payload.get("substage") != "planning_repair_patch":
            return None
        receipt = _hash(payload.get("receipt_sha256"))
        if receipt is None:
            return None
        return {
            "receipt_sha256": receipt,
            "domain_result": "failed",
            "domain_rule_codes": list(payload.get("domain_rule_codes") or ()),
            "exact_field_paths": list(payload.get("exact_field_paths") or ()),
            "invariant_ids": list(payload.get("invariant_ids") or ()),
            "normalized_payload_sha256": _hash(
                payload.get("normalized_payload_sha256")
            ),
            "normalized_payload_shape_sha256": _hash(
                payload.get("normalized_payload_shape_sha256")
            ),
            "repair_target_identity_sha256": _hash(
                payload.get("repair_target_identity_sha256")
            ),
        }

    @staticmethod
    def _propagation_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        receipt = _hash(payload.get("receipt_sha256"))
        source = _hash(payload.get("source_finding_receipt_sha256"))
        request = _hash(payload.get("repair_request_semantic_sha256"))
        if None in {receipt, source, request}:
            return None
        return {
            "receipt_sha256": receipt,
            "source_finding_receipt_sha256": source,
            "source_attempt_ordinal": payload.get("source_attempt_ordinal"),
            "target_attempt_ordinal": payload.get("target_attempt_ordinal"),
            "finding_count": payload.get("finding_count"),
            "exact_rule_codes": list(payload.get("exact_rule_codes") or ()),
            "exact_field_paths": list(payload.get("exact_field_paths") or ()),
            "finding_propagation_status": payload.get(
                "finding_propagation_status"
            ),
            "repair_request_semantic_sha256": request,
        }

    @staticmethod
    def _provider_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if payload.get("route_kind") != "configured_fallback":
            return None
        snapshot = _hash(payload.get("snapshot_sha256"))
        if snapshot is None:
            return None
        return {
            "snapshot_sha256": snapshot,
            "route_kind": "configured_fallback",
            "content_block_count": payload.get("content_block_count"),
            "content_block_type_sequence": list(
                payload.get("content_block_type_sequence") or ()
            ),
            "text_block_count": payload.get("text_block_count"),
            "tool_call_block_count": payload.get("tool_call_block_count"),
            "reasoning_block_count": payload.get("reasoning_block_count"),
            "total_visible_text_chars": payload.get(
                "total_visible_text_chars"
            ),
            "tool_argument_presence": payload.get("tool_argument_presence"),
            "tool_argument_byte_length": payload.get(
                "tool_argument_byte_length"
            ),
            "stop_reason": payload.get("stop_reason"),
            "usage_output_tokens": payload.get("usage_output_tokens"),
            "zero_visible": payload.get("zero_visible"),
            "max_tokens": payload.get("max_tokens"),
            "requested_max_output_tokens": payload.get(
                "requested_max_output_tokens"
            ),
        }

    @staticmethod
    def _output_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        receipt = _hash(payload.get("receipt_sha256"))
        if receipt is None:
            return None
        return {
            "receipt_sha256": receipt,
            "provider_content_block_snapshot_sha256": _hash(
                payload.get("provider_content_block_snapshot_sha256")
            ),
            "requested_budget": payload.get("requested_budget"),
            "effective_budget": payload.get("effective_budget"),
            "output_tokens": payload.get("output_tokens"),
            "zero_visible": payload.get("zero_visible"),
            "parser_reached": payload.get("parser_reached"),
            "strict_tool_reached": payload.get("strict_tool_reached"),
            "domain_validator_reached": payload.get(
                "domain_validator_reached"
            ),
            "truncation_classifier_reason": payload.get(
                "truncation_classifier_reason"
            ),
            "contract_output_limit_action": payload.get(
                "contract_output_limit_action"
            ),
            "expansion_before": payload.get("expansion_before"),
            "expansion_after": payload.get("expansion_after"),
            "next_route_action": payload.get("next_route_action"),
        }

    def observe(self, envelope: Any) -> bool:
        target = self._exact_target(envelope)
        if target is None:
            return False
        event_type = str(target["event_type"])
        payload = target["payload"]
        accepted = False
        with self._lock:
            self._seen_dispatch = True
            if event_type == "diagnostic_planning_repair_domain":
                value = self._domain_snapshot(payload)
                if value is not None and self._domain is None:
                    self._domain = value
                    accepted = True
                elif value is not None:
                    self._duplicate_count += 1
            elif event_type == "diagnostic_planning_repair_finding_propagation":
                value = self._propagation_snapshot(payload)
                if value is not None and self._propagation is None:
                    self._propagation = value
                    accepted = True
                elif value is not None:
                    self._duplicate_count += 1
            elif event_type == "diagnostic_provider_content_block_shape":
                value = self._provider_snapshot(payload)
                if value is not None and self._provider_shape is None:
                    self._provider_shape = value
                    accepted = True
                elif value is not None:
                    self._duplicate_count += 1
            else:
                value = self._output_snapshot(payload)
                if value is not None and self._output_limit is None:
                    self._output_limit = value
                    accepted = True
                elif value is not None:
                    self._duplicate_count += 1
            if self._primary_exact_unlocked() and (
                self._provider_shape is not None or self._output_limit is not None
            ):
                self._reached = True
                self._outcome = PRIMARY_OUTCOME
            receipt = self._snapshot_unlocked()
        self._persist_receipt(receipt)
        return accepted

    def _primary_exact_unlocked(self) -> bool:
        return bool(
            self._domain
            and self._propagation
            and self._propagation["source_finding_receipt_sha256"]
            == self._domain["receipt_sha256"]
        )

    def before_dispatch(
        self, *, stage: str | None, boundary_ordinal: int | None = None,
    ) -> None:
        with self._lock:
            if stage in {"starting", "planning"}:
                self._seen_dispatch = True
            elif self._seen_dispatch and not self._reached:
                self._reached = True
                if self._primary_exact_unlocked():
                    self._outcome = PRIMARY_OUTCOME
                elif self._domain is None and self._propagation is None:
                    self._outcome = NOT_EXERCISED_OUTCOME
                else:
                    self._outcome = PARTIAL_OUTCOME
            if not self._reached:
                return
            self._blocked_dispatch_count += 1
            if self._first_blocked_boundary_ordinal is None:
                self._first_blocked_boundary_ordinal = boundary_ordinal
            receipt = self._snapshot_unlocked()
        self._persist_receipt(receipt)
        raise CanaryObservationGoalReachedStop(
            blocked_boundary_ordinal=boundary_ordinal,
            reason_code=STOP_REASON,
        )

    def raise_if_reached(self, *, boundary_ordinal: int | None = None) -> None:
        self.before_dispatch(stage=None, boundary_ordinal=boundary_ordinal)

    def record_sink_failure(self) -> None:
        with self._lock:
            self._sink_failure_count += 1
            receipt = self._snapshot_unlocked()
        self._persist_receipt(receipt)

    @property
    def reached(self) -> bool:
        with self._lock:
            return self._reached

    def _snapshot_unlocked(self) -> dict[str, Any]:
        primary = (
            "captured" if self._primary_exact_unlocked()
            else "partial" if self._domain or self._propagation
            else "not_exercised"
        )
        amplifier = (
            "captured" if self._provider_shape or self._output_limit
            else "not_reexercised"
        )
        return {
            "schema": "PlanningRepairObservationGoalReceiptV1",
            "version": 1,
            "observation_goal_reached": self._reached,
            "observation_goal_outcome": self._outcome,
            "stop_outcome": STOP_OUTCOME if self._reached else None,
            "stop_reason": STOP_REASON if self._reached else None,
            "primary_evidence_status": primary,
            "terminal_amplifier_status": amplifier,
            "domain_failure_snapshot": self._domain,
            "finding_propagation_snapshot": self._propagation,
            "fallback_provider_shape_snapshot": self._provider_shape,
            "output_limit_observation": self._output_limit,
            "duplicate_observation_count": self._duplicate_count,
            "sink_failure_count": self._sink_failure_count,
            "receipt_write_failure_count": self._receipt_write_failure_count,
            "blocked_dispatch_count": self._blocked_dispatch_count,
            "first_blocked_boundary_ordinal": (
                self._first_blocked_boundary_ordinal
            ),
            "raw_content_included": False,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def _persist_receipt(self, receipt: Mapping[str, Any]) -> None:
        if self.receipt_path is None:
            return
        body = dict(receipt)
        body["receipt_sha256"] = _canonical_hash(body)
        encoded = (
            json.dumps(body, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n"
        ).encode("utf-8")
        temporary = self.receipt_path.with_suffix(
            self.receipt_path.suffix + ".tmp"
        )
        try:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600,
            )
            try:
                if os.write(descriptor, encoded) != len(encoded):
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
