from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_flywheel.contract_runtime import (
    ContractOutputLimitExhaustedError,
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    ArtifactConversionError,
    GeneratedArtifactGateway,
    registered_business_wire_schema,
)
from novel_flywheel.failure_boundary import failure_evidence_sha256
from novel_flywheel.planning_adaptation import (
    WHOLE_STORY_FIELDS,
    normalize_planning_adaptation_whole_receipt,
    planning_adaptation_whole_receipt_issues,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


FIXTURE = Path(__file__).parent / "fixtures" / (
    "r1_pa0_planning_adaptation_receipt_evidence_v1.json"
)


def _evidence() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _whole_payload(*, summary: str = "offline controlled whole receipt") -> dict:
    evidence = _evidence()["planning_adaptation"]
    return {
        "authority_sha256": evidence["whole_authority_sha256"],
        "planning_sha256": evidence["planning_sha256"],
        "segment_numbers": [1],
        "event_ids": evidence["event_ids"],
        **{field: True for field in WHOLE_STORY_FIELDS},
        "affected_segments": [],
        "affected_event_ids": [],
        "reason": "none",
        "summary": summary,
    }


def _whole_spec() -> ExecutableContractSpec:
    evidence = _evidence()["planning_adaptation"]
    authority = {
        "authority_sha256": evidence["whole_authority_sha256"],
        "planning_sha256": evidence["planning_sha256"],
        "segment_numbers": [1],
        "event_ids": evidence["event_ids"],
    }
    contract = StructuredArtifactContract(
        name="planning_adaptation_whole",
        version=ARTIFACT_CONTRACT_REGISTRY["planning_adaptation_whole"].version,
        schema=registered_business_wire_schema(
            "planning_adaptation_whole", authority,
        ),
        runtime_authority=authority,
    )

    def validate(payload):
        normalized = normalize_planning_adaptation_whole_receipt(payload)
        issues = planning_adaptation_whole_receipt_issues(
            normalized,
            authority_sha256=evidence["whole_authority_sha256"],
            planning_sha256=evidence["planning_sha256"],
            segment_count=1,
            expected_event_ids=evidence["event_ids"],
        )
        if issues:
            raise ValueError(issues)
        return normalized

    return ExecutableContractSpec(
        contract_name="planning_adaptation_whole",
        structured_contract=contract,
        semantic_normalizer=lambda value: dict(value),
        domain_validator=validate,
        retry_domain_failures=True,
    )


def test_r1_pa0_evidence_ledger_preserves_exact_route_counts() -> None:
    evidence = _evidence()
    calls = evidence["calls"]

    assert len(calls) == evidence["real_model_call_count"] == 11
    assert sum(item["route"] == "primary" for item in calls) == 8
    assert sum(item["route"] == "configured_fallback" for item in calls) == 3
    assert [item["ordinal"] for item in calls] == list(range(1, 12))


def test_primary_empty_max_tokens_candidate_is_output_truncation() -> None:
    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            "", contract_name="planning_adaptation_whole",
        )

    assert caught.value.audit.failure_code == "output_truncated"
    assert caught.value.audit.raw_sha256 == hashlib.sha256(b"").hexdigest()
    assert caught.value.reliability_failure.failure_class.value == "output_truncation"


@pytest.mark.asyncio
async def test_outer_route_isolation_resets_existing_output_expansion() -> None:
    """Characterize the observed workflow-owned one-route Runtime topology."""

    valid = json.dumps(_whole_payload(summary="x" * 700), ensure_ascii=False)

    class CapacityGateway:
        def __init__(self):
            self.budgets = []

        async def complete_route(self, route, role, system, user, **kwargs):
            budget = kwargs["max_output_tokens"]
            self.budgets.append(budget)
            if budget <= 1276:
                return SimpleNamespace(
                    text="",
                    receipt={
                        "finish_reason": "max_tokens",
                        "requested_max_output_tokens": budget,
                        "output_tokens": budget,
                    },
                )
            return SimpleNamespace(
                text=valid,
                receipt={
                    "finish_reason": "stop",
                    "requested_max_output_tokens": budget,
                    "output_tokens": 300,
                },
            )

    isolated = CapacityGateway()
    for _ in range(3):
        with pytest.raises(ContractOutputLimitExhaustedError):
            await execute_contract_runtime(
                isolated,
                role="review",
                system="immutable system",
                user="immutable whole task",
                execution_spec=_whole_spec(),
                max_output_tokens=1276,
                attempt_routes=("primary",),
            )
    assert isolated.budgets == [1276, 1276, 1276]

    retained = CapacityGateway()
    result = await execute_contract_runtime(
        retained,
        role="review",
        system="immutable system",
        user="immutable whole task",
        execution_spec=_whole_spec(),
        max_output_tokens=1276,
        attempt_routes=("primary", "primary"),
    )
    assert retained.budgets == [1276, 2552]
    assert result.domain_value["summary"] == "x" * 700


def test_segment_shape_cannot_deterministically_satisfy_whole_contract() -> None:
    evidence = _evidence()["planning_adaptation"]
    segment_shape = {
        "authority_sha256": evidence["segment_authority_sha256"],
        "planning_sha256": evidence["planning_sha256"],
        "authority_version": 3,
        "segment": 1,
        "event_reviews": [],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "validated segment",
    }

    required = set(
        ARTIFACT_CONTRACT_REGISTRY[
            "planning_adaptation_whole"
        ].wire_required_fields
    )
    missing = required - set(segment_shape)

    assert set(WHOLE_STORY_FIELDS) - {"formal_direction_preserved"} <= missing
    assert {"segment_numbers", "event_ids", "affected_segments"} <= missing
    converted = GeneratedArtifactGateway().convert_object(
        json.dumps(segment_shape),
        contract_name="planning_adaptation_whole",
    )
    with pytest.raises(ValueError):
        _whole_spec().domain_validator(converted.payload)


def test_controlled_complete_whole_receipt_passes_current_contract() -> None:
    raw = json.dumps(_whole_payload(summary="x" * 700), ensure_ascii=False)
    conversion = GeneratedArtifactGateway().convert_object(
        raw, contract_name="planning_adaptation_whole",
    )
    validated = _whole_spec().domain_validator(conversion.payload)

    assert validated["segment_numbers"] == [1]
    assert validated["event_ids"] == ["EV-F2DD1CE1", "EV-A8353187"]


def test_segment_and_whole_contracts_share_version_and_recovery_not_schema() -> None:
    segment = ARTIFACT_CONTRACT_REGISTRY["planning_adaptation_segment"]
    whole = ARTIFACT_CONTRACT_REGISTRY["planning_adaptation_whole"]

    assert segment.version == whole.version == 1
    assert segment.recovery_ladder == whole.recovery_ladder
    assert segment.minimum_business_characters == whole.minimum_business_characters == 600
    assert segment.wire_required_fields != whole.wire_required_fields
    assert "event_reviews" in segment.wire_required_fields
    assert set(WHOLE_STORY_FIELDS) <= set(whole.wire_required_fields)


def test_whole_fallback_error_hash_binds_to_no_unique_tool_artifact() -> None:
    observed = _evidence()["planning_adaptation"]
    error = RuntimeError(observed["whole_fallback_exact_error"])

    assert failure_evidence_sha256(
        error, boundary="protocol_route.normal_invalid_output",
    ) == observed["whole_fallback_error_sha256"]
    assert observed["whole_fallback_raw_status"] == "not_persisted_unverifiable"
