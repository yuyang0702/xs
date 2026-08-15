"""Hash-only evidence for a Canary budget refusal before paid delegation."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .budget import CanaryBudgetExceeded


SCHEMA = "CanaryBudgetStopEvidenceV1"
DOMAIN = "novel-flywheel-canary-budget-stop-evidence-v1"
_BINDING_STATUSES = {"exact", "none_available", "unverifiable"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNKNOWN_WORKLOAD_HASH = domain_sha256(
    "novel-flywheel-canary-unknown-workload-v1", {"status": "unknown"},
)


def _hash_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX64.fullmatch(value) else None


def _binding(value: Mapping[str, Any] | None, *, kind: str) -> dict[str, Any]:
    source = dict(value or {})
    status = str(source.get("binding_status") or "none_available")
    if status not in _BINDING_STATUSES:
        status = "unverifiable"
    reference = _hash_or_none(source.get("reference"))
    identity = _hash_or_none(source.get("identity_sha256"))
    receipt = _hash_or_none(source.get("binding_receipt_sha256"))
    if status == "exact" and (reference is None or identity is None or receipt is None):
        status = "unverifiable"
    return {
        "kind": str(source.get("kind") or kind),
        "reference": reference,
        "identity_sha256": identity,
        "revision": source.get("revision"),
        "execution_epoch": source.get("execution_epoch"),
        "authority_boundary": _hash_or_none(source.get("authority_boundary")),
        "binding_receipt_sha256": receipt,
        "binding_status": status,
    }


def build_budget_stop_evidence_v1(
    *, request: Mapping[str, Any], failure: CanaryBudgetExceeded,
    workload_identifier_hash: str, ledger_snapshot: Mapping[str, Any],
    monetary_snapshot: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None = None,
    previous_boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic receipt without raw content or machine paths."""

    current = dict(context or {})
    previous = dict(previous_boundary or {})
    previous_observation = dict(previous.get("provider_observation") or {})
    previous_receipt = (
        domain_sha256("novel-flywheel-canary-boundary-receipt-v1", previous)
        if previous else None
    )
    ledger_receipt = domain_sha256(
        "novel-flywheel-canary-budget-ledger-receipt-v1", {
            "tokens": dict(ledger_snapshot),
            "monetary": dict(monetary_snapshot or {}),
        },
    )
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "run_identifier_hash": _hash_or_none(request["run_id_hash"]),
        "workload_identifier_hash": (
            _hash_or_none(workload_identifier_hash) or _UNKNOWN_WORKLOAD_HASH
        ),
        "stage": request["stage"],
        "role": request["role"],
        "attempt_ordinal": request["ordinal"],
        "route_kind": request["route_kind"],
        "provider_descriptor_hash": _hash_or_none(request["provider_descriptor_hash"]),
        "model_binding_hash": _hash_or_none(request["model_binding_hash"]),
        "current_executor_epoch": current.get("current_executor_epoch"),
        "budget_dimension_exhausted": failure.dimension,
        "approved_ceiling": failure.approved_ceiling,
        "already_reserved_amount": failure.already_reserved,
        "requested_reservation": failure.requested_reservation,
        "remaining_amount_before_request": failure.remaining_before_request,
        "ledger_receipt_hash": ledger_receipt,
        "current_checkpoint": _binding(current.get("checkpoint"), kind="checkpoint"),
        "last_legal_artifact": _binding(current.get("last_legal_artifact"), kind="artifact"),
        "last_legal_authority_boundary": _hash_or_none(
            current.get("last_legal_authority_boundary")
        ),
        "previous_attempt_receipt_hash": previous_receipt,
        "previous_successful_model_boundary_receipt_hash": (
            previous_receipt
            if previous_observation.get("status") == "completed" else None
        ),
        "underlying_previous_failure": (
            previous_observation.get("typed_failure")
            or previous_observation.get("failure_code")
        ),
        "previous_route_kind": previous.get("route_kind"),
        "current_requested_next_action": (
            request.get("retry_fallback_reason") or request.get("route_kind")
        ),
        "stop_reason_code": failure.reason_code,
        "raw_content_included": False,
    }
    body["stop_receipt_hash"] = domain_sha256(DOMAIN, body)
    return deepcopy(body)
