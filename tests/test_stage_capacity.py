from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

import novel_flywheel.contract_runtime as contract_runtime_module
from novel_flywheel.contract_runtime import (
    dispatch_explicit_model_route,
    execute_model_route_runtime,
)
from novel_flywheel.full_short_runtime_kernel import FullShortBoundaryFailureV1
from novel_flywheel.stage_capacity import (
    CAPACITY_FAILURE_IDS_V1,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
    AdmissionStatus,
    CapacityAdmissionFailureV1,
    CapacityFailureCode,
    CapacityLayerClass,
    CapacityLayerProjectionV1,
    CapacityRecoveryDisposition,
    MAX_CONTEXT_LIMIT_TOKENS_V1,
    RouteContextCapabilitySourceV1,
    StageCapacityAdmissionEngineV1,
    StageCapacityPolicyRegistryV1,
    StageCapacityPolicyV1,
    build_stage_capacity_plan_v1,
    capacity_failure_recovery_disposition_v1,
    verify_rendered_request_v1,
)


def _layer(
    layer_id: str,
    classification: CapacityLayerClass,
    tokens: int,
    *,
    action: str = "PRESERVE",
    semantic_scope: str = "complete",
    transform_policy_id: str = "identity.v1",
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
        semantic_scope=semantic_scope,
        coverage=(layer_id,),
        pre_transform_characters=tokens * 2,
        pre_transform_tokens=tokens,
        post_transform_characters=tokens * 2,
        post_transform_tokens=tokens,
        transform_policy_id=transform_policy_id,
        action=action,
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
    assert plan.stage_operational_context_ceiling_tokens == 32768
    assert plan.route_context_capability_limit_tokens == 32768
    assert (
        plan.route_context_capability_source
        is RouteContextCapabilitySourceV1.MODEL_CONFIGURATION
    )
    assert plan.model_context_limit == 32768
    assert plan.plan_sha256 == _plan().plan_sha256


def test_route_capability_below_stage_ceiling_is_effective_limit() -> None:
    plan = _plan(
        model_context_limit=16384,
        rendered_message_tokens=10000,
    )
    assert plan.route_context_capability_limit_tokens == 16384
    assert plan.stage_operational_context_ceiling_tokens == 32768
    assert plan.model_context_limit == 16384
    assert plan.prompt_budget == 12788


def test_route_capability_above_stage_ceiling_cannot_raise_runtime_policy() -> None:
    plan = _plan(model_context_limit=128000)
    assert plan.route_context_capability_limit_tokens == 128000
    assert plan.stage_operational_context_ceiling_tokens == 32768
    assert plan.model_context_limit == 32768
    assert plan.prompt_budget == 29172


def test_offline_manifest_context_source_is_hash_bound() -> None:
    plan = _plan(
        route_context_capability_source=(
            "offline_deterministic_gateway_manifest"
        ),
    )
    assert (
        plan.route_context_capability_source
        is RouteContextCapabilitySourceV1.OFFLINE_DETERMINISTIC_GATEWAY_MANIFEST
    )
    assert plan.plan_sha256 != _plan().plan_sha256


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


def test_advisory_over_budget_requires_compaction_then_types_insufficiency() -> None:
    advisory = _layer(
        "advisory", CapacityLayerClass.ADVISORY_COMPACTABLE, 12000,
    )
    original = _plan(
        rendered_message_tokens=31000,
        layer_projections=(advisory,),
    )
    assert original.admission_status is AdmissionStatus.COMPACTION_REQUIRED
    assert original.denial_failure_id is CapacityFailureCode.MODEL_CONTEXT_EXCEEDED

    compacted_but_still_large = _layer(
        "advisory", CapacityLayerClass.ADVISORY_COMPACTABLE, 12000,
        action="COMPACT",
    )
    insufficient = _plan(
        rendered_message_tokens=31000,
        layer_projections=(compacted_but_still_large,),
    )
    assert insufficient.admission_status is AdmissionStatus.COMPACTION_REQUIRED
    assert (
        insufficient.denial_failure_id
        is CapacityFailureCode.COMPACTION_INSUFFICIENT
    )


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


def test_missing_context_limit_is_typed_and_fails_closed() -> None:
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        _plan(model_context_limit=None)
    assert caught.value.failure_id == "capacity.context_limit_unavailable"


@pytest.mark.parametrize(
    "invalid_limit",
    (True, False, -1, 0, MAX_CONTEXT_LIMIT_TOKENS_V1 + 1),
)
def test_invalid_route_context_capability_is_typed(
    invalid_limit: object,
) -> None:
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        _plan(model_context_limit=invalid_limit)
    assert caught.value.failure_id == "capacity.context_limit_inconsistent"


def test_unknown_route_context_capability_source_is_typed() -> None:
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        _plan(route_context_capability_source="provider_marketing_page")
    assert caught.value.failure_id == "capacity.context_limit_inconsistent"


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


def test_layer_projection_hash_rejects_tampered_transform() -> None:
    layer = _layer("advisory", CapacityLayerClass.ADVISORY_COMPACTABLE, 25)
    with pytest.raises(
        ValueError,
        match="capacity_layer_projection_sha256_mismatch",
    ):
        replace(layer, action="SHED")


@pytest.mark.asyncio
async def test_denied_attempt_never_retries_or_reaches_gateway() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls = 0

        @staticmethod
        def has_configured_fallback(_role: str) -> bool:
            return True

        async def complete_primary(self, *_args, **_kwargs):
            self.calls += 1

        async def complete_configured_fallback(self, *_args, **_kwargs):
            self.calls += 1

    gateway = Gateway()

    def deny(*_args, **_kwargs) -> None:
        _plan(model_context_limit=None)

    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        await execute_model_route_runtime(
            gateway,
            role="review",
            system="system",
            user="user",
            same_route_attempts=2,
            fallback_attempts=2,
            attempt_admitter=deny,
        )

    assert caught.value.failure_id == "capacity.context_limit_unavailable"
    assert gateway.calls == 0


def _review_registry(**overrides) -> StageCapacityPolicyRegistryV1:
    original = DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.policies["review"]
    values = {
        "stage": original.stage,
        "policy_id": original.policy_id,
        "allowed_layer_classes": original.allowed_layer_classes,
        "compaction_allowed": original.compaction_allowed,
        "semantic_windowing_allowed": original.semantic_windowing_allowed,
        "minimum_wrapper_and_estimator_margin_tokens": (
            original.minimum_wrapper_and_estimator_margin_tokens
        ),
        "stage_operational_context_ceiling_tokens": (
            original.stage_operational_context_ceiling_tokens
        ),
        "allowed_transform_policy_ids": original.allowed_transform_policy_ids,
        "allowed_semantic_scopes": original.allowed_semantic_scopes,
        "compaction_policy_id": original.compaction_policy_id,
        "segmentation_policy_id": original.segmentation_policy_id,
        "recovery_policy_id": original.recovery_policy_id,
        "segmentation_failure_ids": original.segmentation_failure_ids,
    }
    values.update(overrides)
    return StageCapacityPolicyRegistryV1(
        policies={"review": StageCapacityPolicyV1(**values)},
    )


def test_active_registry_identity_is_enforced_not_merely_recorded() -> None:
    plan = _plan()
    drifted = _review_registry(policy_id="stage-capacity.review.drifted")
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        StageCapacityAdmissionEngineV1.enforce(
            plan,
            policy_registry=drifted,
        )
    assert caught.value.failure_id == "capacity.policy_violation"


def test_registry_rejects_disallowed_layer_class() -> None:
    registry = _review_registry(
        allowed_layer_classes=(CapacityLayerClass.HARD_PROTECTED,),
    )
    plan = _plan(policy_registry=registry)
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id is CapacityFailureCode.POLICY_VIOLATION


@pytest.mark.parametrize(
    ("registry", "layer"),
    (
        (
            _review_registry(compaction_allowed=False),
            _layer(
                "advisory", CapacityLayerClass.ADVISORY_COMPACTABLE, 25,
                action="COMPACT",
            ),
        ),
        (
            _review_registry(semantic_windowing_allowed=False),
            _layer(
                "window", CapacityLayerClass.HARD_PROTECTED, 25,
                action="WINDOW", semantic_scope="bounded_component",
            ),
        ),
    ),
)
def test_registry_rejects_unauthorized_transform(
    registry: StageCapacityPolicyRegistryV1,
    layer: CapacityLayerProjectionV1,
) -> None:
    plan = _plan(policy_registry=registry, layer_projections=(layer,))
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id is CapacityFailureCode.POLICY_VIOLATION


def test_registry_minimum_estimator_margin_is_an_admission_rule() -> None:
    registry = _review_registry(
        minimum_wrapper_and_estimator_margin_tokens=2048,
    )
    plan = _plan(policy_registry=registry)
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id is CapacityFailureCode.POLICY_VIOLATION


def test_custom_registry_stage_ceiling_controls_effective_limit() -> None:
    registry = _review_registry(
        stage_operational_context_ceiling_tokens=20000,
    )
    plan = _plan(
        policy_registry=registry,
        model_context_limit=128000,
        rendered_message_tokens=10000,
    )
    assert plan.stage_operational_context_ceiling_tokens == 20000
    assert plan.route_context_capability_limit_tokens == 128000
    assert plan.model_context_limit == 20000
    assert plan.policy_registry_sha256 == registry.identity_sha256
    StageCapacityAdmissionEngineV1.enforce(plan, policy_registry=registry)


@pytest.mark.parametrize("invalid_ceiling", (True, 0, -1, 2_000_001))
def test_invalid_registry_stage_ceiling_is_policy_violation(
    invalid_ceiling: object,
) -> None:
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        _review_registry(
            stage_operational_context_ceiling_tokens=invalid_ceiling,
        )
    assert caught.value.failure_id == "capacity.policy_violation"


def test_dual_context_limits_and_source_reject_hash_or_semantic_tamper() -> None:
    plan = _plan(model_context_limit=128000)
    with pytest.raises(
        ValueError,
        match="capacity_effective_context_limit_inconsistent",
    ):
        replace(plan, model_context_limit=128000)
    with pytest.raises(ValueError, match="capacity_plan_sha256_mismatch"):
        replace(
            plan,
            route_context_capability_source=(
                RouteContextCapabilitySourceV1.OFFLINE_DETERMINISTIC_GATEWAY_MANIFEST
            ),
        )


@pytest.mark.parametrize(
    "layer",
    (
        _layer(
            "unknown-transform",
            CapacityLayerClass.ADVISORY_COMPACTABLE,
            25,
            action="COMPACT",
            transform_policy_id="unregistered.compactor.v999",
        ),
        _layer(
            "unknown-scope",
            CapacityLayerClass.HARD_PROTECTED,
            25,
            semantic_scope="arbitrary-silent-scope",
        ),
        _layer(
            "protected-compaction",
            CapacityLayerClass.HARD_PROTECTED,
            25,
            action="COMPACT",
            transform_policy_id="advisory.paragraph.v1",
        ),
    ),
)
def test_registry_rejects_unregistered_or_protected_transform(
    layer: CapacityLayerProjectionV1,
) -> None:
    plan = _plan(layer_projections=(layer,))
    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id is CapacityFailureCode.POLICY_VIOLATION


@pytest.mark.parametrize(
    ("pre_characters", "post_characters", "pre_tokens", "post_tokens"),
    ((5000, 1, 1250, 1), (5000, 5000, 1250, 1)),
)
def test_protected_layers_cannot_hide_transform_as_preserve(
    pre_characters: int,
    post_characters: int,
    pre_tokens: int,
    post_tokens: int,
) -> None:
    protected = CapacityLayerProjectionV1.create(
        layer_id="authority",
        classification=CapacityLayerClass.HARD_PROTECTED,
        owner="review",
        source_sha256="a" * 64,
        semantic_scope="complete",
        coverage=("authority",),
        pre_transform_characters=pre_characters,
        pre_transform_tokens=pre_tokens,
        post_transform_characters=post_characters,
        post_transform_tokens=post_tokens,
        transform_policy_id="identity.v1",
        action="PRESERVE",
        rendered_sha256="b" * 64,
    )
    plan = _plan(layer_projections=(protected,))

    assert plan.admission_status is AdmissionStatus.DENIED
    assert plan.denial_failure_id is CapacityFailureCode.POLICY_VIOLATION


def test_stage_specific_segmentation_and_recovery_are_registry_bound() -> None:
    policies = DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.policies
    assert len({
        policy.segmentation_policy_id for policy in policies.values()
    }) == len(policies)
    assert capacity_failure_recovery_disposition_v1(
        stage="review",
        failure_id=CapacityFailureCode.WINDOWING_REQUIRED,
    ) is CapacityRecoveryDisposition.SEGMENT
    assert capacity_failure_recovery_disposition_v1(
        stage="review",
        failure_id=CapacityFailureCode.RENDERED_PROMPT_DRIFT,
    ) is CapacityRecoveryDisposition.STOP


@pytest.mark.asyncio
async def test_exact_dispatch_api_requires_and_consumes_capacity_token() -> None:
    class Observer:
        exact_full_short_execution = True

        def __init__(self) -> None:
            self.tokens: list[str] = []

        def authorize_capacity_dispatch_token(self, token: str) -> None:
            self.tokens.append(token)

    class Gateway:
        def __init__(self) -> None:
            self.observer = Observer()
            self.registry = SimpleNamespace(attempt_observer=self.observer)
            self.calls = 0

        async def complete_route(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return "ok"

    gateway = Gateway()
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        await dispatch_explicit_model_route(
            gateway,
            "primary",
            role="review",
            system="system",
            user="user",
            max_output_tokens=128,
        )
    assert caught.value.failure_id == "capacity.policy_violation"
    assert gateway.calls == 0

    result = await dispatch_explicit_model_route(
        gateway,
        "primary",
        role="review",
        system="system",
        user="user",
        max_output_tokens=128,
        capacity_admission_token="a" * 64,
    )
    assert result == "ok"
    assert gateway.calls == 1
    assert gateway.observer.tokens == ["a" * 64]


@pytest.mark.asyncio
async def test_wrapped_capacity_token_drift_is_not_counted_or_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CapacityTokenDrift(RuntimeError):
        reason_code = "CAPACITY_DISPATCH_TOKEN_MISSING_OR_STALE"

    source = CapacityTokenDrift("stale")
    wrapped = FullShortBoundaryFailureV1.__new__(FullShortBoundaryFailureV1)
    Exception.__init__(wrapped, "wrapped capacity denial")
    wrapped.source_exception = source
    dispatch_calls = 0

    async def fail_before_dispatch(*_args, **_kwargs):
        nonlocal dispatch_calls
        dispatch_calls += 1
        raise wrapped

    monkeypatch.setattr(
        contract_runtime_module,
        "dispatch_explicit_model_route",
        fail_before_dispatch,
    )
    observations: list[dict] = []
    gateway = SimpleNamespace(
        has_configured_fallback=lambda _role: True,
    )

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await execute_model_route_runtime(
            gateway,
            role="review",
            system="system",
            user="user",
            same_route_attempts=2,
            fallback_attempts=2,
            attempt_observer=observations.append,
            attempt_admitter=lambda *_args: "a" * 64,
        )

    assert caught.value is wrapped
    assert dispatch_calls == 1
    assert observations == []
