from __future__ import annotations

"""Content-addressed, route-exact capacity evidence contracts.

This module is deliberately independent from provider clients and credentials.
It accepts only already-collected public route identity and hash-bound evidence.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Iterable


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name}_invalid")


class CapabilityStatus(StrEnum):
    VERIFIED_HISTORICAL_EVIDENCE = "VERIFIED_HISTORICAL_EVIDENCE"
    VERIFIED_LOCAL_CONFIG_WITH_PROVENANCE = (
        "VERIFIED_LOCAL_CONFIG_WITH_PROVENANCE"
    )
    VERIFIED_PUBLIC_DOCUMENTATION = "VERIFIED_PUBLIC_DOCUMENTATION"
    UNKNOWN_BLOCKED = "UNKNOWN_BLOCKED"


VERIFIED_CAPABILITY_STATUSES = frozenset({
    CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE,
    CapabilityStatus.VERIFIED_LOCAL_CONFIG_WITH_PROVENANCE,
    CapabilityStatus.VERIFIED_PUBLIC_DOCUMENTATION,
})


class RouteCapabilityError(ValueError):
    def __init__(self, failure_id: str) -> None:
        self.failure_id = failure_id
        super().__init__(failure_id)


@dataclass(frozen=True)
class CapabilityEvidenceV1:
    source_kind: str
    source_locator: str
    source_evidence_sha256: str
    evidence_version: int
    evidence_date: str
    route_fingerprint: str
    proved_fields: tuple[str, ...]
    provenance_available: bool

    def __post_init__(self) -> None:
        _require_sha256(
            self.source_evidence_sha256, "source_evidence_sha256"
        )
        _require_sha256(self.route_fingerprint, "route_fingerprint")
        if self.evidence_version < 1:
            raise ValueError("evidence_version_invalid")
        if not self.source_kind or not self.source_locator or not self.evidence_date:
            raise ValueError("capability_evidence_identity_incomplete")
        if not self.proved_fields or len(set(self.proved_fields)) != len(
            self.proved_fields
        ):
            raise ValueError("capability_evidence_proved_fields_invalid")


@dataclass(frozen=True)
class RouteCapabilityRecordV1:
    role: str
    lane: str
    provider: str
    provider_id_sha256: str
    operator: str
    destination: str
    protocol: str
    model: str
    model_id_sha256: str
    route_fingerprint: str
    context_window_tokens: int | None
    max_output_tokens: int | None
    reasoning_token_accounting: str
    reasoning_output_reservation: str
    reasoning_token_reserve: int | None
    capability_status: CapabilityStatus
    source_evidence: tuple[CapabilityEvidenceV1, ...]
    blocking_reason_codes: tuple[str, ...]
    capability_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("capability_sha256")
        payload["capability_status"] = self.capability_status.value
        return payload

    def __post_init__(self) -> None:
        if self.lane not in {"primary", "fallback"}:
            raise ValueError("route_capability_lane_invalid")
        if not all((
            self.role,
            self.provider,
            self.operator,
            self.destination,
            self.protocol,
            self.model,
        )):
            raise ValueError("route_capability_identity_incomplete")
        if not self.destination.startswith("https://"):
            raise ValueError("route_capability_destination_invalid")
        for field_name in (
            "provider_id_sha256",
            "model_id_sha256",
            "route_fingerprint",
            "capability_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        for field_name in ("context_window_tokens", "max_output_tokens"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{field_name}_invalid")
        if any(
            evidence.route_fingerprint != self.route_fingerprint
            for evidence in self.source_evidence
        ):
            raise ValueError("capability_evidence_route_fingerprint_drift")
        reasoning_pair = (
            self.reasoning_token_accounting,
            self.reasoning_output_reservation,
        )
        included_reasoning = reasoning_pair == (
            "INCLUDED_IN_COMPLETION_CAP", "WITHIN_COMPLETION_CAP",
        )
        separate_reasoning = reasoning_pair == (
            "SEPARATE_IF_REPORTED",
            "SEPARATE_REPORTED_RESERVATION_REQUIRED",
        )
        unknown_reasoning = reasoning_pair == ("UNKNOWN", "UNKNOWN")
        if not (included_reasoning or separate_reasoning) and not (
            self.capability_status is CapabilityStatus.UNKNOWN_BLOCKED
            and unknown_reasoning
            and self.reasoning_token_reserve is None
        ):
            raise ValueError(
                "verified_route_capability_evidence_incomplete"
                if self.capability_status in VERIFIED_CAPABILITY_STATUSES
                else "reasoning_capacity_semantics_invalid"
            )
        if included_reasoning and self.reasoning_token_reserve != 0:
            raise ValueError("reasoning_capacity_reserve_invalid")
        if separate_reasoning and self.capability_status in (
            VERIFIED_CAPABILITY_STATUSES
        ) and (
            type(self.reasoning_token_reserve) is not int
            or self.reasoning_token_reserve <= 0
        ):
            raise ValueError("reasoning_capacity_reserve_invalid")
        if self.capability_status in VERIFIED_CAPABILITY_STATUSES:
            proved = {
                field
                for evidence in self.source_evidence
                if evidence.provenance_available
                for field in evidence.proved_fields
            }
            if (
                self.context_window_tokens is None
                or self.max_output_tokens is None
                or not self.source_evidence
                or not {
                    "context_window_tokens",
                    "max_output_tokens",
                    "reasoning_token_accounting",
                    "reasoning_output_reservation",
                    "route_fingerprint",
                    "provider",
                    "provider_id_sha256",
                    "operator",
                    "destination",
                    "protocol",
                    "model",
                    "model_id_sha256",
                } <= proved
                or self.blocking_reason_codes
                or (
                    separate_reasoning
                    and "reasoning_token_reserve" not in proved
                )
            ):
                raise ValueError("verified_route_capability_evidence_incomplete")
        else:
            if self.capability_status is not CapabilityStatus.UNKNOWN_BLOCKED:
                raise ValueError("route_capability_status_invalid")
            if not self.blocking_reason_codes:
                raise ValueError("unknown_route_capability_reason_required")
            if (
                self.context_window_tokens is not None
                or self.max_output_tokens is not None
                or separate_reasoning
                and self.reasoning_token_reserve is not None
            ):
                raise ValueError("unknown_route_capability_must_not_guess_limits")
        if _canonical_sha256(self.canonical_payload()) != self.capability_sha256:
            raise ValueError("route_capability_sha256_mismatch")

    @classmethod
    def create(
        cls,
        *,
        role: str,
        lane: str,
        provider: str,
        provider_id_sha256: str,
        operator: str,
        destination: str,
        protocol: str,
        model: str,
        model_id_sha256: str,
        route_fingerprint: str,
        context_window_tokens: int | None,
        max_output_tokens: int | None,
        reasoning_token_accounting: str = "UNKNOWN",
        reasoning_output_reservation: str = "UNKNOWN",
        reasoning_token_reserve: int | None = None,
        capability_status: CapabilityStatus,
        source_evidence: Iterable[CapabilityEvidenceV1] = (),
        blocking_reason_codes: Iterable[str] = (),
    ) -> RouteCapabilityRecordV1:
        if (
            reasoning_token_reserve is None
            and reasoning_token_accounting == "INCLUDED_IN_COMPLETION_CAP"
            and reasoning_output_reservation == "WITHIN_COMPLETION_CAP"
        ):
            reasoning_token_reserve = 0
        evidence = tuple(source_evidence)
        reasons = tuple(blocking_reason_codes)
        payload = {
            "role": role,
            "lane": lane,
            "provider": provider,
            "provider_id_sha256": provider_id_sha256,
            "operator": operator,
            "destination": destination,
            "protocol": protocol,
            "model": model,
            "model_id_sha256": model_id_sha256,
            "route_fingerprint": route_fingerprint,
            "context_window_tokens": context_window_tokens,
            "max_output_tokens": max_output_tokens,
            "reasoning_token_accounting": reasoning_token_accounting,
            "reasoning_output_reservation": reasoning_output_reservation,
            "reasoning_token_reserve": reasoning_token_reserve,
            "capability_status": capability_status.value,
            "source_evidence": [asdict(item) for item in evidence],
            "blocking_reason_codes": list(reasons),
        }
        return cls(
            role=role,
            lane=lane,
            provider=provider,
            provider_id_sha256=provider_id_sha256,
            operator=operator,
            destination=destination,
            protocol=protocol,
            model=model,
            model_id_sha256=model_id_sha256,
            route_fingerprint=route_fingerprint,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
            reasoning_token_accounting=reasoning_token_accounting,
            reasoning_output_reservation=reasoning_output_reservation,
            reasoning_token_reserve=reasoning_token_reserve,
            capability_status=capability_status,
            source_evidence=evidence,
            blocking_reason_codes=reasons,
            capability_sha256=_canonical_sha256(payload),
        )

    def require_dispatchable(self) -> RouteCapabilityRecordV1:
        if self.capability_status not in VERIFIED_CAPABILITY_STATUSES:
            raise RouteCapabilityError("capacity.route_capability_unknown")
        return self

    def require_exact_route_identity(
        self,
        *,
        role: str,
        lane: str,
        provider: str,
        provider_id_sha256: str,
        operator: str,
        destination: str,
        protocol: str,
        model: str,
        model_id_sha256: str,
        route_fingerprint: str,
    ) -> RouteCapabilityRecordV1:
        expected = (
            role, lane, provider, provider_id_sha256, operator, destination,
            protocol, model, model_id_sha256, route_fingerprint,
        )
        actual = (
            self.role, self.lane, self.provider, self.provider_id_sha256,
            self.operator, self.destination, self.protocol, self.model,
            self.model_id_sha256, self.route_fingerprint,
        )
        if actual != expected:
            raise RouteCapabilityError(
                "capacity.route_capability_identity_drift"
            )
        return self


@dataclass(frozen=True)
class RouteCapabilityRegistryV1:
    records: tuple[RouteCapabilityRecordV1, ...]
    registry_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": "RouteCapabilityRegistryV1",
            "version": 1,
            "records": [
                {
                    **record.canonical_payload(),
                    "capability_sha256": record.capability_sha256,
                }
                for record in self.records
            ],
        }

    def to_document(self) -> dict[str, object]:
        return {
            **self.canonical_payload(),
            "registry_sha256": self.registry_sha256,
        }

    def __post_init__(self) -> None:
        identities = [(record.role, record.lane) for record in self.records]
        if identities != sorted(identities) or len(set(identities)) != len(
            identities
        ):
            raise ValueError("route_capability_registry_identity_invalid")
        _require_sha256(self.registry_sha256, "registry_sha256")
        if _canonical_sha256(self.canonical_payload()) != self.registry_sha256:
            raise ValueError("route_capability_registry_sha256_mismatch")

    @classmethod
    def create(
        cls, records: Iterable[RouteCapabilityRecordV1]
    ) -> RouteCapabilityRegistryV1:
        ordered = tuple(sorted(records, key=lambda item: (item.role, item.lane)))
        payload = {
            "schema": "RouteCapabilityRegistryV1",
            "version": 1,
            "records": [
                {
                    **record.canonical_payload(),
                    "capability_sha256": record.capability_sha256,
                }
                for record in ordered
            ],
        }
        return cls(records=ordered, registry_sha256=_canonical_sha256(payload))

    @classmethod
    def from_document(
        cls, document: dict[str, object]
    ) -> RouteCapabilityRegistryV1:
        if set(document) != {
            "schema", "version", "records", "registry_sha256"
        }:
            raise ValueError("route_capability_registry_document_invalid")
        if (
            document.get("schema") != "RouteCapabilityRegistryV1"
            or document.get("version") != 1
            or not isinstance(document.get("records"), list)
        ):
            raise ValueError("route_capability_registry_document_invalid")
        records: list[RouteCapabilityRecordV1] = []
        for raw in document["records"]:
            if not isinstance(raw, dict):
                raise ValueError("route_capability_record_document_invalid")
            item = dict(raw)
            evidence_raw = item.pop("source_evidence", None)
            status_raw = item.pop("capability_status", None)
            if not isinstance(evidence_raw, (list, tuple)):
                raise ValueError("route_capability_evidence_document_invalid")
            evidence = tuple(
                CapabilityEvidenceV1(
                    source_kind=str(entry["source_kind"]),
                    source_locator=str(entry["source_locator"]),
                    source_evidence_sha256=str(
                        entry["source_evidence_sha256"]
                    ),
                    evidence_version=int(entry["evidence_version"]),
                    evidence_date=str(entry["evidence_date"]),
                    route_fingerprint=str(entry["route_fingerprint"]),
                    proved_fields=tuple(entry["proved_fields"]),
                    provenance_available=bool(
                        entry["provenance_available"]
                    ),
                )
                for entry in evidence_raw
                if isinstance(entry, dict)
            )
            if len(evidence) != len(evidence_raw):
                raise ValueError("route_capability_evidence_document_invalid")
            item["source_evidence"] = evidence
            if "reasoning_token_reserve" not in item:
                item["reasoning_token_reserve"] = (
                    0
                    if item.get("reasoning_token_accounting")
                    == "INCLUDED_IN_COMPLETION_CAP"
                    and item.get("reasoning_output_reservation")
                    == "WITHIN_COMPLETION_CAP"
                    else None
                )
            item["blocking_reason_codes"] = tuple(
                item.get("blocking_reason_codes", ())
            )
            item["capability_status"] = CapabilityStatus(str(status_raw))
            records.append(RouteCapabilityRecordV1(**item))
        return cls(
            records=tuple(records),
            registry_sha256=str(document["registry_sha256"]),
        )

    def require_record(self, *, role: str, lane: str) -> RouteCapabilityRecordV1:
        matches = [
            record
            for record in self.records
            if record.role == role and record.lane == lane
        ]
        if len(matches) != 1:
            raise RouteCapabilityError("capacity.route_capability_unknown")
        return matches[0]

    def require_dispatchable(
        self, *, role: str, lane: str
    ) -> RouteCapabilityRecordV1:
        return self.require_record(role=role, lane=lane).require_dispatchable()

    def unknown_required_count(
        self, required_routes: Iterable[tuple[str, str]]
    ) -> int:
        count = 0
        for role, lane in required_routes:
            try:
                self.require_dispatchable(role=role, lane=lane)
            except RouteCapabilityError:
                count += 1
        return count


__all__ = [
    "CapabilityEvidenceV1",
    "CapabilityStatus",
    "RouteCapabilityError",
    "RouteCapabilityRecordV1",
    "RouteCapabilityRegistryV1",
    "VERIFIED_CAPABILITY_STATUSES",
]
