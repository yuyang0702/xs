from __future__ import annotations

from dataclasses import replace

import pytest

from novel_flywheel.route_capabilities import (
    CapabilityEvidenceV1,
    CapabilityStatus,
    RouteCapabilityError,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
)
from novel_flywheel.stage_capacity import (
    CapacityAdmissionFailureV1,
    require_route_capability_v1,
)


def _evidence(route_fingerprint: str = "c" * 64) -> CapabilityEvidenceV1:
    return CapabilityEvidenceV1(
        source_kind="historical_official_documentation",
        source_locator="docs/evidence.json#route",
        source_evidence_sha256="d" * 64,
        evidence_version=1,
        evidence_date="2026-08-14",
        route_fingerprint=route_fingerprint,
        proved_fields=(
            "context_window_tokens", "max_output_tokens",
            "reasoning_token_accounting", "reasoning_output_reservation",
        ),
        provenance_available=True,
    )


def _record(
    *,
    role: str = "planning",
    lane: str = "primary",
    status: CapabilityStatus = CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE,
) -> RouteCapabilityRecordV1:
    verified = status is not CapabilityStatus.UNKNOWN_BLOCKED
    return RouteCapabilityRecordV1.create(
        role=role,
        lane=lane,
        provider="provider",
        provider_id_sha256="a" * 64,
        operator="EXACT_OPERATOR",
        destination="https://unit.test:443/v1/messages",
        protocol="anthropic",
        model="model",
        model_id_sha256="b" * 64,
        route_fingerprint="c" * 64,
        context_window_tokens=100_000 if verified else None,
        max_output_tokens=8_192 if verified else None,
        reasoning_token_accounting="INCLUDED_IN_COMPLETION_CAP",
        reasoning_output_reservation="WITHIN_COMPLETION_CAP",
        capability_status=status,
        source_evidence=(_evidence(),) if verified else (),
        blocking_reason_codes=() if verified else ("NO_TRUSTWORTHY_EVIDENCE",),
    )


def test_verified_record_is_content_addressed_and_dispatchable() -> None:
    first = _record()
    second = _record()

    assert first == second
    assert first.require_dispatchable() is first
    assert first.require_exact_route_identity(
        role=first.role,
        lane=first.lane,
        provider=first.provider,
        provider_id_sha256=first.provider_id_sha256,
        operator=first.operator,
        destination=first.destination,
        protocol=first.protocol,
        model=first.model,
        model_id_sha256=first.model_id_sha256,
        route_fingerprint=first.route_fingerprint,
    ) is first


@pytest.mark.parametrize(
    ("field", "drifted"),
    (
        ("role", "draft"),
        ("lane", "fallback"),
        ("provider", "other-provider"),
        ("provider_id_sha256", "e" * 64),
        ("operator", "OTHER_OPERATOR"),
        ("destination", "https://other.test:443/v1/messages"),
        ("protocol", "openai-responses"),
        ("model", "other-model"),
        ("model_id_sha256", "f" * 64),
        ("route_fingerprint", "0" * 64),
    ),
)
def test_exact_route_identity_rejects_every_field_drift(
    field: str, drifted: str,
) -> None:
    record = _record()
    identity = {
        "role": record.role,
        "lane": record.lane,
        "provider": record.provider,
        "provider_id_sha256": record.provider_id_sha256,
        "operator": record.operator,
        "destination": record.destination,
        "protocol": record.protocol,
        "model": record.model,
        "model_id_sha256": record.model_id_sha256,
        "route_fingerprint": record.route_fingerprint,
    }
    identity[field] = drifted
    with pytest.raises(
        RouteCapabilityError, match="capacity.route_capability_identity_drift"
    ):
        record.require_exact_route_identity(**identity)


def test_unknown_record_is_present_but_not_dispatchable() -> None:
    record = _record(status=CapabilityStatus.UNKNOWN_BLOCKED)
    registry = RouteCapabilityRegistryV1.create((record,))

    assert registry.require_record(role="planning", lane="primary") == record
    with pytest.raises(
        RouteCapabilityError, match="capacity.route_capability_unknown"
    ):
        registry.require_dispatchable(role="planning", lane="primary")

    with pytest.raises(CapacityAdmissionFailureV1) as typed:
        require_route_capability_v1(record)
    assert typed.value.failure_id == "capacity.route_capability_unknown"


def test_unknown_record_cannot_smuggle_guessed_limits() -> None:
    with pytest.raises(
        ValueError, match="unknown_route_capability_must_not_guess_limits"
    ):
        replace(
            _record(status=CapabilityStatus.UNKNOWN_BLOCKED),
            context_window_tokens=32_768,
        )


def test_verified_record_requires_provenance_for_both_limits() -> None:
    incomplete = replace(
        _evidence(), proved_fields=("context_window_tokens",)
    )
    with pytest.raises(
        ValueError, match="verified_route_capability_evidence_incomplete"
    ):
        RouteCapabilityRecordV1.create(
            role="planning",
            lane="primary",
            provider="provider",
            provider_id_sha256="a" * 64,
            operator="EXACT_OPERATOR",
            destination="https://unit.test:443/v1/messages",
            protocol="anthropic",
            model="model",
            model_id_sha256="b" * 64,
            route_fingerprint="c" * 64,
            context_window_tokens=100_000,
            max_output_tokens=8_192,
            capability_status=(
                CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE
            ),
            source_evidence=(incomplete,),
        )


def test_verified_record_requires_explicit_reasoning_accounting() -> None:
    with pytest.raises(
        ValueError, match="verified_route_capability_evidence_incomplete"
    ):
        replace(
            _record(),
            reasoning_token_accounting="UNKNOWN",
        )


@pytest.mark.parametrize(
    "drift",
    ("operator", "destination", "protocol", "model", "route_fingerprint"),
)
def test_every_route_identity_field_changes_capability_sha(drift: str) -> None:
    first = _record()
    values = {
        "operator": "OTHER_OPERATOR",
        "destination": "https://other.test:443/v1/messages",
        "protocol": "openai-responses",
        "model": "other-model",
        "route_fingerprint": "e" * 64,
    }
    kwargs = {drift: values[drift]}
    evidence = (_evidence("e" * 64),) if drift == "route_fingerprint" else (
        first.source_evidence
    )
    second = RouteCapabilityRecordV1.create(
        role=first.role,
        lane=first.lane,
        provider=first.provider,
        provider_id_sha256=first.provider_id_sha256,
        operator=kwargs.get("operator", first.operator),
        destination=kwargs.get("destination", first.destination),
        protocol=kwargs.get("protocol", first.protocol),
        model=kwargs.get("model", first.model),
        model_id_sha256=first.model_id_sha256,
        route_fingerprint=kwargs.get(
            "route_fingerprint", first.route_fingerprint
        ),
        context_window_tokens=first.context_window_tokens,
        max_output_tokens=first.max_output_tokens,
        reasoning_token_accounting=first.reasoning_token_accounting,
        reasoning_output_reservation=first.reasoning_output_reservation,
        capability_status=first.capability_status,
        source_evidence=evidence,
    )
    assert second.capability_sha256 != first.capability_sha256


def test_registry_requires_one_exact_role_lane_record() -> None:
    registry = RouteCapabilityRegistryV1.create((
        _record(role="planning", lane="primary"),
        _record(
            role="planning",
            lane="fallback",
            status=CapabilityStatus.UNKNOWN_BLOCKED,
        ),
    ))

    assert registry.unknown_required_count((
        ("planning", "primary"),
    )) == 0
    assert registry.unknown_required_count((
        ("planning", "primary"),
        ("planning", "fallback"),
        ("draft", "primary"),
    )) == 2

    assert RouteCapabilityRegistryV1.from_document(
        registry.to_document()
    ) == registry


def test_registry_rejects_duplicate_role_lane_even_for_distinct_models() -> None:
    with pytest.raises(
        ValueError, match="route_capability_registry_identity_invalid"
    ):
        RouteCapabilityRegistryV1.create((_record(), _record()))
