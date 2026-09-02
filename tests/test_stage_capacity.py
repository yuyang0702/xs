from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from novel_flywheel.stage_capacity import (
    CAPACITY_FAILURE_IDS_V1,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
    AdmissionStatus,
    CapacityAdmissionFailureV1,
    CapacityFailureCode,
    CapacityLayerClass,
    CapacityLayerProjectionV1,
    build_stage_capacity_plan_v1,
    verify_rendered_request_v1,
)


def _layer(
    layer_id: str,
    classification: CapacityLayerClass,
    tokens: int,
) -> CapacityLayerProjectionV1:
    source_sha256 = hashlib.sha256(
        f"source:{layer_id}".encode("utf-8")
    ).hexdigest()
    rendered_sha256 = hashlib.sha256(
        f"rendered:{layer_id}".encode("utf-8")
    ).hexdigest()
    return CapacityLayerProjectionV1.create(
        layer_id=layer_id,
        classification=classification,
        owner="test",
        source_sha256=source_sha256,
        semantic_scope="complete",
        coverage=(layer_id,),
        pre_transform_characters=tokens * 2,
        pre_transform_tokens=tokens,
        post_transform_characters=tokens * 2,
        post_transform_tokens=tokens,
        transform_policy_id="identity.v1",
        action="PRESERVE",
        rendered_sha256=rendered_sha256,
    )


def _plan(**overrides):
    values = {
        "stage_id": "review-unit-001",
        "logical_stage_id": "review-unit-001",
        "physical_attempt": 1,
        "stage": "review",
        "contract_name": "planning_adaptation_segment",
        "contract_version": 2,
        "contract_schema_sha256": "a" * 64,
        "provider_route_identity_sha256": "b" * 64,
        "model_context_limit": 32768,
        "requested_output_token_cap": 2316,
        "final_output_reserve": 2316,
        "rendered_message_tokens": 22379,
        "structured_envelope_tokens": 177,
        "provider_envelope_tokens": 256,
        "wrapper_and_estimator_margin_tokens": 1024,
        "rendered_request_sha256": "c" * 64,
        "layer_projections": (
            _layer("current_contract", CapacityLayerClass.HARD_PROTECTED, 25),
            _layer("mandatory_rules", CapacityLayerClass.HARD_PROTECTED, 9685),
            _layer("relevant_context", CapacityLayerClass.SOFT_PROTECTED, 4601),
            _layer("global_skeleton", CapacityLayerClass.HARD_PROTECTED, 7802),
            _layer("advisory", CapacityLayerClass.ADVISORY_SHEDDABLE, 0),
        ),
        "parent_plan_sha256": None,
    }
    values.update(overrides)
    return build_stage_capacity_plan_v1(**values)


def test_policy_registry_covers_every_real_full_short_stage() -> None:
    assert set(DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.policies) == {
        "planning",
        "draft",
        "review",
        "reader_review",
        "polish",
        "final_review",
        "maintenance",
        "revision_plan",
    }
    assert DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256


def test_exact_ready_pref_fix_shape_has_deterministic_headroom() -> None:
    plan = _plan()
    assert plan.admission_status is AdmissionStatus.PASS
    assert plan.expected_rendered_input == 22556
    assert plan.prompt_budget == 29172
    assert plan.headroom == 6616
    assert plan.protected_layer_tokens == 22113
    assert plan.advisory_layer_tokens == 0
    assert plan.plan_sha256 == _plan().plan_sha256


def test_protected_layers_over_budget_require_registered_windowing() -> None:
    plan = _plan(
        rendered_message_tokens=31000,
        layer_projections=(
            _layer("current_contract", CapacityLayerClass.HARD_PROTECTED, 15000),
            _layer("global_skeleton", CapacityLayerClass.HARD_PROTECTED, 16000),
        ),
    )
    assert plan.admission_status is AdmissionStatus.WINDOWING_REQUIRED
    assert plan.denial_failure_id == CapacityFailureCode.WINDOWING_REQUIRED


def test_output_reserve_conflict_is_typed_and_denied() -> None:
    plan = _plan(
        requested_output_token_cap=33000,
        final_output_reserve=33000,
    )
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id == CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        plan.require_pass()
    assert caught.value.failure_id == "capacity.output_reserve_unsatisfied"


def test_missing_context_limit_is_typed_and_denied() -> None:
    plan = _plan(model_context_limit=0)
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id == CapacityFailureCode.CONTEXT_LIMIT_UNAVAILABLE


def test_every_capacity_failure_code_is_registered() -> None:
    assert CAPACITY_FAILURE_IDS_V1 == {
        item.value for item in CapacityFailureCode
    }


def test_rendered_request_drift_fails_closed() -> None:
    plan = _plan()
    verify_rendered_request_v1(plan, rendered_request_sha256="c" * 64)
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        verify_rendered_request_v1(plan, rendered_request_sha256="d" * 64)
    assert caught.value.failure_id == "capacity.rendered_prompt_drift"


def test_plan_hash_rejects_mutated_status() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="capacity_plan_sha256_mismatch"):
        replace(plan, admission_status=AdmissionStatus.DENIED)
