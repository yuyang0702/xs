from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable

from novel_flywheel.full_short_runtime_kernel import (
    RegisteredBoundaryFailureV1,
    full_short_boundary_entry,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


CAPACITY_BOUNDARY_ID_V1 = "FS.CAPACITY.ADMIT"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: str, *, field_name: str) -> None:
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name}_invalid")


class CapacityLayerClass(StrEnum):
    HARD_PROTECTED = "HARD_PROTECTED"
    SOFT_PROTECTED = "SOFT_PROTECTED"
    ADVISORY_COMPACTABLE = "ADVISORY_COMPACTABLE"
    ADVISORY_SHEDDABLE = "ADVISORY_SHEDDABLE"
    DERIVED_REGENERABLE = "DERIVED_REGENERABLE"


class AdmissionStatus(StrEnum):
    PASS = "PASS"
    COMPACTION_REQUIRED = "COMPACTION_REQUIRED"
    WINDOWING_REQUIRED = "WINDOWING_REQUIRED"
    DENIED = "DENIED"


class CapacityFailureCode(StrEnum):
    MODEL_CONTEXT_EXCEEDED = "capacity.model_context_exceeded"
    OUTPUT_RESERVE_UNSATISFIED = "capacity.output_reserve_unsatisfied"
    PROTECTED_LAYERS_EXCEED_BUDGET = "capacity.protected_layers_exceed_budget"
    COMPACTION_INSUFFICIENT = "capacity.compaction_insufficient"
    WINDOWING_REQUIRED = "capacity.windowing_required"
    WINDOWING_EXHAUSTED = "capacity.windowing_exhausted"
    RENDERED_PROMPT_DRIFT = "capacity.rendered_prompt_drift"
    CONTEXT_LIMIT_UNAVAILABLE = "capacity.context_limit_unavailable"
    CONTEXT_LIMIT_INCONSISTENT = "capacity.context_limit_inconsistent"


CAPACITY_FAILURE_IDS_V1 = {item.value for item in CapacityFailureCode}


class CapacityAdmissionFailureV1(RegisteredBoundaryFailureV1):
    def __init__(
        self,
        failure_id: CapacityFailureCode | str,
        *,
        plan: StageCapacityPlanV1 | None = None,
    ) -> None:
        code = CapacityFailureCode(failure_id)
        super().__init__(
            boundary_id=CAPACITY_BOUNDARY_ID_V1,
            failure_id=code.value,
        )
        self.failure_code = code.value
        self.reason_code = code.value
        self.reliability_failure = ReliabilityFailure(
            code=code.value,
            failure_class=FailureClass.CONTEXT_CAPACITY,
            boundary=CAPACITY_BOUNDARY_ID_V1,
            retryable=code in {
                CapacityFailureCode.MODEL_CONTEXT_EXCEEDED,
                CapacityFailureCode.PROTECTED_LAYERS_EXCEED_BUDGET,
                CapacityFailureCode.COMPACTION_INSUFFICIENT,
                CapacityFailureCode.WINDOWING_REQUIRED,
            },
        )
        if plan is not None:
            self.receipt = {
                "schema": "CapacityAdmissionFailureReceiptV1",
                "failure_id": code.value,
                "stage_id_sha256": hashlib.sha256(
                    plan.stage_id.encode("utf-8")
                ).hexdigest(),
                "logical_stage_id_sha256": hashlib.sha256(
                    plan.logical_stage_id.encode("utf-8")
                ).hexdigest(),
                "physical_attempt": plan.physical_attempt,
                "plan_sha256": plan.plan_sha256,
                "admission_status": plan.admission_status.value,
                "model_context_limit": plan.model_context_limit,
                "prompt_budget": plan.prompt_budget,
                "expected_rendered_input": plan.expected_rendered_input,
                "protected_layer_tokens": plan.protected_layer_tokens,
                "advisory_layer_tokens": plan.advisory_layer_tokens,
                "headroom": plan.headroom,
                "raw_prompt_persisted": False,
            }


@dataclass(frozen=True)
class StageCapacityPolicyV1:
    stage: str
    policy_id: str
    allowed_layer_classes: tuple[CapacityLayerClass, ...]
    compaction_allowed: bool
    semantic_windowing_allowed: bool
    minimum_wrapper_and_estimator_margin_tokens: int

    def canonical_payload(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "policy_id": self.policy_id,
            "allowed_layer_classes": [
                item.value for item in self.allowed_layer_classes
            ],
            "compaction_allowed": self.compaction_allowed,
            "semantic_windowing_allowed": self.semantic_windowing_allowed,
            "minimum_wrapper_and_estimator_margin_tokens": (
                self.minimum_wrapper_and_estimator_margin_tokens
            ),
        }


@dataclass(frozen=True)
class StageCapacityPolicyRegistryV1:
    policies: dict[str, StageCapacityPolicyV1]

    def __post_init__(self) -> None:
        if set(self.policies) != {policy.stage for policy in self.policies.values()}:
            raise ValueError("capacity_policy_registry_stage_mismatch")

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256({
            stage: policy.canonical_payload()
            for stage, policy in sorted(self.policies.items())
        })


_ALL_LAYER_CLASSES = tuple(CapacityLayerClass)
DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1 = StageCapacityPolicyRegistryV1(
    policies={
        stage: StageCapacityPolicyV1(
            stage=stage,
            policy_id=f"stage-capacity.{stage}.v1",
            allowed_layer_classes=_ALL_LAYER_CLASSES,
            compaction_allowed=True,
            semantic_windowing_allowed=True,
            minimum_wrapper_and_estimator_margin_tokens=1024,
        )
        for stage in (
            "planning",
            "draft",
            "review",
            "reader_review",
            "polish",
            "final_review",
            "maintenance",
            "revision_plan",
        )
    }
)


@dataclass(frozen=True)
class CapacityLayerProjectionV1:
    layer_id: str
    classification: CapacityLayerClass
    owner: str
    source_sha256: str
    semantic_scope: str
    coverage: tuple[str, ...]
    pre_transform_characters: int
    pre_transform_tokens: int
    post_transform_characters: int
    post_transform_tokens: int
    transform_policy_id: str
    action: str
    rendered_sha256: str
    projection_sha256: str

    @classmethod
    def create(
        cls,
        *,
        layer_id: str,
        classification: CapacityLayerClass,
        owner: str,
        source_sha256: str,
        semantic_scope: str,
        coverage: Iterable[str],
        pre_transform_characters: int,
        pre_transform_tokens: int,
        post_transform_characters: int,
        post_transform_tokens: int,
        transform_policy_id: str,
        action: str,
        rendered_sha256: str,
    ) -> CapacityLayerProjectionV1:
        _require_sha256(source_sha256, field_name="source_sha256")
        _require_sha256(rendered_sha256, field_name="rendered_sha256")
        if min(
            pre_transform_characters,
            pre_transform_tokens,
            post_transform_characters,
            post_transform_tokens,
        ) < 0:
            raise ValueError("capacity_layer_size_negative")
        payload = {
            "layer_id": layer_id,
            "classification": classification.value,
            "owner": owner,
            "source_sha256": source_sha256,
            "semantic_scope": semantic_scope,
            "coverage": list(coverage),
            "pre_transform_characters": pre_transform_characters,
            "pre_transform_tokens": pre_transform_tokens,
            "post_transform_characters": post_transform_characters,
            "post_transform_tokens": post_transform_tokens,
            "transform_policy_id": transform_policy_id,
            "action": action,
            "rendered_sha256": rendered_sha256,
        }
        return cls(
            layer_id=layer_id,
            classification=classification,
            owner=owner,
            source_sha256=source_sha256,
            semantic_scope=semantic_scope,
            coverage=tuple(payload["coverage"]),
            pre_transform_characters=pre_transform_characters,
            pre_transform_tokens=pre_transform_tokens,
            post_transform_characters=post_transform_characters,
            post_transform_tokens=post_transform_tokens,
            transform_policy_id=transform_policy_id,
            action=action,
            rendered_sha256=rendered_sha256,
            projection_sha256=_canonical_sha256(payload),
        )


@dataclass(frozen=True)
class StageCapacityPlanV1:
    stage_id: str
    logical_stage_id: str
    physical_attempt: int
    stage: str
    contract_name: str
    contract_version: int
    contract_schema_sha256: str
    provider_route_identity_sha256: str
    model_context_limit: int
    requested_output_token_cap: int
    final_output_reserve: int
    rendered_message_tokens: int
    structured_envelope_tokens: int
    provider_envelope_tokens: int
    wrapper_and_estimator_margin_tokens: int
    rendered_request_sha256: str
    layer_projections: tuple[CapacityLayerProjectionV1, ...]
    parent_plan_sha256: str | None
    expected_rendered_input: int
    prompt_budget: int
    protected_layer_tokens: int
    advisory_layer_tokens: int
    headroom: int
    admission_status: AdmissionStatus
    denial_failure_id: CapacityFailureCode | None
    policy_registry_sha256: str
    plan_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("plan_sha256")
        payload["admission_status"] = self.admission_status.value
        payload["denial_failure_id"] = (
            self.denial_failure_id.value if self.denial_failure_id else None
        )
        payload["layer_projections"] = [
            {
                **asdict(layer),
                "classification": layer.classification.value,
            }
            for layer in self.layer_projections
        ]
        return payload

    def __post_init__(self) -> None:
        for field_name in (
            "contract_schema_sha256",
            "provider_route_identity_sha256",
            "rendered_request_sha256",
            "policy_registry_sha256",
            "plan_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.parent_plan_sha256 is not None:
            _require_sha256(
                self.parent_plan_sha256,
                field_name="parent_plan_sha256",
            )
        if _canonical_sha256(self.canonical_payload()) != self.plan_sha256:
            raise ValueError("capacity_plan_sha256_mismatch")

    def require_pass(self) -> None:
        if self.admission_status is AdmissionStatus.PASS:
            return
        failure_id = self.denial_failure_id
        if failure_id is None:
            failure_id = CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
        raise CapacityAdmissionFailureV1(failure_id, plan=self)


def build_stage_capacity_plan_v1(
    *,
    stage_id: str,
    logical_stage_id: str,
    physical_attempt: int,
    stage: str,
    contract_name: str,
    contract_version: int,
    contract_schema_sha256: str,
    provider_route_identity_sha256: str,
    model_context_limit: int,
    requested_output_token_cap: int,
    final_output_reserve: int,
    rendered_message_tokens: int,
    structured_envelope_tokens: int,
    provider_envelope_tokens: int,
    wrapper_and_estimator_margin_tokens: int,
    rendered_request_sha256: str,
    layer_projections: Iterable[CapacityLayerProjectionV1],
    parent_plan_sha256: str | None,
    policy_registry: StageCapacityPolicyRegistryV1 = (
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1
    ),
) -> StageCapacityPlanV1:
    if stage not in policy_registry.policies:
        raise ValueError(f"capacity_policy_missing:{stage}")
    if physical_attempt < 1:
        raise ValueError("capacity_physical_attempt_invalid")
    values = (
        requested_output_token_cap,
        final_output_reserve,
        rendered_message_tokens,
        structured_envelope_tokens,
        provider_envelope_tokens,
        wrapper_and_estimator_margin_tokens,
    )
    if any(value < 0 for value in values):
        raise ValueError("capacity_value_negative")
    projections = tuple(layer_projections)
    expected_rendered_input = rendered_message_tokens + structured_envelope_tokens
    prompt_budget = (
        model_context_limit
        - final_output_reserve
        - provider_envelope_tokens
        - wrapper_and_estimator_margin_tokens
    )
    protected_classes = {
        CapacityLayerClass.HARD_PROTECTED,
        CapacityLayerClass.SOFT_PROTECTED,
    }
    protected_tokens = sum(
        layer.post_transform_tokens
        for layer in projections
        if layer.classification in protected_classes
    )
    advisory_tokens = sum(
        layer.post_transform_tokens
        for layer in projections
        if layer.classification not in protected_classes
    )
    if model_context_limit <= 0:
        status = AdmissionStatus.DENIED
        failure = CapacityFailureCode.CONTEXT_LIMIT_UNAVAILABLE
    elif (
        requested_output_token_cap <= 0
        or final_output_reserve < requested_output_token_cap
        or prompt_budget <= 0
    ):
        status = AdmissionStatus.DENIED
        failure = CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED
    elif expected_rendered_input <= prompt_budget:
        status = AdmissionStatus.PASS
        failure = None
    elif protected_tokens + structured_envelope_tokens > prompt_budget:
        status = AdmissionStatus.WINDOWING_REQUIRED
        failure = CapacityFailureCode.WINDOWING_REQUIRED
    elif advisory_tokens > 0:
        status = AdmissionStatus.COMPACTION_REQUIRED
        failure = CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
    else:
        status = AdmissionStatus.DENIED
        failure = CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
    payload = {
        "stage_id": stage_id,
        "logical_stage_id": logical_stage_id,
        "physical_attempt": physical_attempt,
        "stage": stage,
        "contract_name": contract_name,
        "contract_version": contract_version,
        "contract_schema_sha256": contract_schema_sha256,
        "provider_route_identity_sha256": provider_route_identity_sha256,
        "model_context_limit": model_context_limit,
        "requested_output_token_cap": requested_output_token_cap,
        "final_output_reserve": final_output_reserve,
        "rendered_message_tokens": rendered_message_tokens,
        "structured_envelope_tokens": structured_envelope_tokens,
        "provider_envelope_tokens": provider_envelope_tokens,
        "wrapper_and_estimator_margin_tokens": wrapper_and_estimator_margin_tokens,
        "rendered_request_sha256": rendered_request_sha256,
        "layer_projections": projections,
        "parent_plan_sha256": parent_plan_sha256,
        "expected_rendered_input": expected_rendered_input,
        "prompt_budget": prompt_budget,
        "protected_layer_tokens": protected_tokens,
        "advisory_layer_tokens": advisory_tokens,
        "headroom": prompt_budget - expected_rendered_input,
        "admission_status": status,
        "denial_failure_id": failure,
        "policy_registry_sha256": policy_registry.identity_sha256,
    }
    canonical_payload = {
        **payload,
        "admission_status": status.value,
        "denial_failure_id": failure.value if failure else None,
        "layer_projections": [
            {
                **asdict(layer),
                "classification": layer.classification.value,
            }
            for layer in projections
        ],
    }
    return StageCapacityPlanV1(
        **payload,
        plan_sha256=_canonical_sha256(canonical_payload),
    )


def verify_rendered_request_v1(
    plan: StageCapacityPlanV1,
    *,
    rendered_request_sha256: str,
) -> None:
    _require_sha256(
        rendered_request_sha256,
        field_name="rendered_request_sha256",
    )
    if rendered_request_sha256 != plan.rendered_request_sha256:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.RENDERED_PROMPT_DRIFT
        )


@full_short_boundary_entry("FS.CAPACITY.ADMIT")
def enforce_stage_capacity_plan_v1(
    plan: StageCapacityPlanV1,
) -> StageCapacityPlanV1:
    plan.require_pass()
    return plan


class StageCapacityAdmissionEngineV1:
    @staticmethod
    def admit(**kwargs: object) -> StageCapacityPlanV1:
        plan = build_stage_capacity_plan_v1(**kwargs)  # type: ignore[arg-type]
        return enforce_stage_capacity_plan_v1(plan)

    @staticmethod
    def enforce(plan: StageCapacityPlanV1) -> StageCapacityPlanV1:
        return enforce_stage_capacity_plan_v1(plan)


__all__ = [
    "AdmissionStatus",
    "CAPACITY_BOUNDARY_ID_V1",
    "CAPACITY_FAILURE_IDS_V1",
    "CapacityAdmissionFailureV1",
    "CapacityFailureCode",
    "CapacityLayerClass",
    "CapacityLayerProjectionV1",
    "DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1",
    "StageCapacityAdmissionEngineV1",
    "StageCapacityPlanV1",
    "StageCapacityPolicyRegistryV1",
    "StageCapacityPolicyV1",
    "build_stage_capacity_plan_v1",
    "enforce_stage_capacity_plan_v1",
    "verify_rendered_request_v1",
]
