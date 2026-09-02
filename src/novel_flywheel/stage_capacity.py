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
MAX_CONTEXT_LIMIT_TOKENS_V1 = 2_000_000


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


class CapacityRecoveryDisposition(StrEnum):
    COMPACT = "COMPACT"
    SEGMENT = "SEGMENT"
    STOP = "STOP"


class RouteContextCapabilitySourceV1(StrEnum):
    ROUTE_CAPABILITY_REGISTRY = "route_capability_registry"
    MODEL_CONFIGURATION = "model_configuration"
    OFFLINE_DETERMINISTIC_GATEWAY_MANIFEST = (
        "offline_deterministic_gateway_manifest"
    )


class CapacityFailureCode(StrEnum):
    ROUTE_CAPABILITY_UNKNOWN = "capacity.route_capability_unknown"
    CONTEXT_WINDOW_EXCEEDED = "capacity.context_window_exceeded"
    MODEL_CONTEXT_EXCEEDED = "capacity.model_context_exceeded"
    OUTPUT_RESERVE_UNSATISFIED = "capacity.output_reserve_unsatisfied"
    PROTECTED_LAYERS_EXCEED_BUDGET = "capacity.protected_layers_exceed_budget"
    COMPACTION_INSUFFICIENT = "capacity.compaction_insufficient"
    WINDOWING_REQUIRED = "capacity.windowing_required"
    WINDOWING_EXHAUSTED = "capacity.windowing_exhausted"
    RENDERED_PROMPT_DRIFT = "capacity.rendered_prompt_drift"
    PHYSICAL_ATTEMPT_DRIFT = "capacity.physical_attempt_drift"
    INVALID_ATTEMPT_DELTA = "capacity.invalid_attempt_delta"
    PHYSICAL_ATTEMPT_CAP_EXHAUSTED = (
        "capacity.physical_attempt_cap_exhausted"
    )
    ESTIMATOR_UNCERTAINTY_EXCEEDED = (
        "capacity.estimator_uncertainty_exceeded"
    )
    CONTEXT_LIMIT_UNAVAILABLE = "capacity.context_limit_unavailable"
    CONTEXT_LIMIT_INCONSISTENT = "capacity.context_limit_inconsistent"
    POLICY_VIOLATION = "capacity.policy_violation"


CAPACITY_FAILURE_IDS_V1 = {
    CapacityFailureCode.MODEL_CONTEXT_EXCEEDED.value,
    CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED.value,
    CapacityFailureCode.PROTECTED_LAYERS_EXCEED_BUDGET.value,
    CapacityFailureCode.COMPACTION_INSUFFICIENT.value,
    CapacityFailureCode.WINDOWING_REQUIRED.value,
    CapacityFailureCode.WINDOWING_EXHAUSTED.value,
    CapacityFailureCode.RENDERED_PROMPT_DRIFT.value,
    CapacityFailureCode.CONTEXT_LIMIT_UNAVAILABLE.value,
    CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT.value,
    CapacityFailureCode.POLICY_VIOLATION.value,
}
CAPACITY_FAILURE_IDS_V3 = {item.value for item in CapacityFailureCode}


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
                CapacityFailureCode.CONTEXT_WINDOW_EXCEEDED,
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
                "stage_operational_context_ceiling_tokens": (
                    plan.stage_operational_context_ceiling_tokens
                ),
                "route_context_capability_limit_tokens": (
                    plan.route_context_capability_limit_tokens
                ),
                "route_context_capability_source": (
                    plan.route_context_capability_source.value
                ),
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
    stage_operational_context_ceiling_tokens: int = 32768
    allowed_transform_policy_ids: tuple[str, ...] = (
        "identity.v1",
        "advisory.paragraph.v1",
    )
    allowed_semantic_scopes: tuple[str, ...] = (
        "complete",
        "bounded_component",
    )
    compaction_policy_id: str = "capacity.compact.advisory.paragraph.v1"
    segmentation_policy_id: str = "capacity.segment.none.v1"
    recovery_policy_id: str = "capacity.recovery.fail-closed.v1"
    segmentation_failure_ids: tuple[CapacityFailureCode, ...] = ()

    def __post_init__(self) -> None:
        ceiling = self.stage_operational_context_ceiling_tokens
        if (
            isinstance(ceiling, bool)
            or not isinstance(ceiling, int)
            or ceiling <= 0
            or ceiling > MAX_CONTEXT_LIMIT_TOKENS_V1
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.POLICY_VIOLATION,
            )

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
            "stage_operational_context_ceiling_tokens": (
                self.stage_operational_context_ceiling_tokens
            ),
            "allowed_transform_policy_ids": list(
                self.allowed_transform_policy_ids
            ),
            "allowed_semantic_scopes": list(self.allowed_semantic_scopes),
            "compaction_policy_id": self.compaction_policy_id,
            "segmentation_policy_id": self.segmentation_policy_id,
            "recovery_policy_id": self.recovery_policy_id,
            "segmentation_failure_ids": [
                item.value for item in self.segmentation_failure_ids
            ],
        }

    def recovery_disposition(
        self,
        failure_id: CapacityFailureCode | str,
    ) -> CapacityRecoveryDisposition:
        failure = CapacityFailureCode(failure_id)
        if failure in self.segmentation_failure_ids:
            return CapacityRecoveryDisposition.SEGMENT
        if failure is CapacityFailureCode.MODEL_CONTEXT_EXCEEDED:
            return CapacityRecoveryDisposition.COMPACT
        return CapacityRecoveryDisposition.STOP


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

    def require_policy(self, stage: str) -> StageCapacityPolicyV1:
        try:
            return self.policies[stage]
        except KeyError as exc:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.POLICY_VIOLATION,
            ) from exc


_ALL_LAYER_CLASSES = tuple(CapacityLayerClass)
_SEGMENTABLE_CAPACITY_FAILURES = (
    CapacityFailureCode.MODEL_CONTEXT_EXCEEDED,
    CapacityFailureCode.PROTECTED_LAYERS_EXCEED_BUDGET,
    CapacityFailureCode.COMPACTION_INSUFFICIENT,
    CapacityFailureCode.WINDOWING_REQUIRED,
)
_SEGMENTATION_POLICY_IDS = {
    "planning": "capacity.segment.planning.semantic.v1",
    "draft": "capacity.segment.draft.event-owner.v1",
    "review": "capacity.segment.review.hierarchical.v1",
    "reader_review": "capacity.segment.reader-review.hierarchical.v1",
    "polish": "capacity.segment.polish.targeted.v1",
    "final_review": "capacity.segment.final-review.hierarchical.v1",
    "maintenance": "capacity.segment.maintenance.window.v1",
    "revision_plan": "capacity.segment.revision-plan.target.v1",
}
DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1 = StageCapacityPolicyRegistryV1(
    policies={
        stage: StageCapacityPolicyV1(
            stage=stage,
            policy_id=f"stage-capacity.{stage}.v1",
            allowed_layer_classes=_ALL_LAYER_CLASSES,
            compaction_allowed=True,
            semantic_windowing_allowed=True,
            minimum_wrapper_and_estimator_margin_tokens=1024,
            segmentation_policy_id=_SEGMENTATION_POLICY_IDS[stage],
            recovery_policy_id=f"capacity.recovery.{stage}.v1",
            segmentation_failure_ids=_SEGMENTABLE_CAPACITY_FAILURES,
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

    def canonical_payload(self) -> dict[str, object]:
        return {
            "layer_id": self.layer_id,
            "classification": self.classification.value,
            "owner": self.owner,
            "source_sha256": self.source_sha256,
            "semantic_scope": self.semantic_scope,
            "coverage": list(self.coverage),
            "pre_transform_characters": self.pre_transform_characters,
            "pre_transform_tokens": self.pre_transform_tokens,
            "post_transform_characters": self.post_transform_characters,
            "post_transform_tokens": self.post_transform_tokens,
            "transform_policy_id": self.transform_policy_id,
            "action": self.action,
            "rendered_sha256": self.rendered_sha256,
        }

    def __post_init__(self) -> None:
        _require_sha256(self.source_sha256, field_name="source_sha256")
        _require_sha256(self.rendered_sha256, field_name="rendered_sha256")
        _require_sha256(self.projection_sha256, field_name="projection_sha256")
        if _canonical_sha256(self.canonical_payload()) != self.projection_sha256:
            raise ValueError("capacity_layer_projection_sha256_mismatch")

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
    physical_attempt_id: str | None
    global_physical_attempt_ordinal: int | None
    logical_capacity_envelope_sha256: str | None
    route_capability_snapshot_sha256: str | None
    stage: str
    contract_name: str
    contract_version: int
    contract_schema_sha256: str
    provider_route_identity_sha256: str
    stage_operational_context_ceiling_tokens: int
    route_context_capability_limit_tokens: int
    route_context_capability_source: RouteContextCapabilitySourceV1
    model_context_limit: int
    requested_output_token_cap: int
    route_max_output_tokens: int
    final_output_reserve: int
    reasoning_token_reserve: int
    reasoning_token_accounting: str
    recovery_stage_role: str
    reasoning_policy: str
    prior_rendered_request_sha256: str | None
    recovery_prompt_delta_sha256: str
    recovery_source_capture_receipt_sha256: str | None
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
    compaction_policy_id: str
    segmentation_policy_id: str
    recovery_policy_id: str
    policy_registry_sha256: str
    plan_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("plan_sha256")
        payload["admission_status"] = self.admission_status.value
        payload["denial_failure_id"] = (
            self.denial_failure_id.value if self.denial_failure_id else None
        )
        payload["route_context_capability_source"] = (
            self.route_context_capability_source.value
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
            "recovery_prompt_delta_sha256",
            "policy_registry_sha256",
            "plan_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.parent_plan_sha256 is not None:
            _require_sha256(
                self.parent_plan_sha256,
                field_name="parent_plan_sha256",
            )
        for field_name in (
            "prior_rendered_request_sha256",
            "recovery_source_capture_receipt_sha256",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_sha256(value, field_name=field_name)
        for field_name in (
            "logical_capacity_envelope_sha256",
            "route_capability_snapshot_sha256",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_sha256(value, field_name=field_name)
        if self.physical_attempt_id is not None and (
            not self.physical_attempt_id.startswith("physical-")
            or len(self.physical_attempt_id) > 160
        ):
            raise ValueError("physical_attempt_id_invalid")
        if self.global_physical_attempt_ordinal is not None and (
            type(self.global_physical_attempt_ordinal) is not int
            or self.global_physical_attempt_ordinal < 1
        ):
            raise ValueError("global_physical_attempt_ordinal_invalid")
        if not isinstance(
            self.route_context_capability_source,
            RouteContextCapabilitySourceV1,
        ):
            raise ValueError("route_context_capability_source_invalid")
        for field_name in (
            "stage_operational_context_ceiling_tokens",
            "route_context_capability_limit_tokens",
            "model_context_limit",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > MAX_CONTEXT_LIMIT_TOKENS_V1
            ):
                raise ValueError(f"{field_name}_invalid")
        if self.model_context_limit != min(
            self.stage_operational_context_ceiling_tokens,
            self.route_context_capability_limit_tokens,
        ):
            raise ValueError("capacity_effective_context_limit_inconsistent")
        if (
            type(self.route_max_output_tokens) is not int
            or self.route_max_output_tokens <= 0
            or self.requested_output_token_cap > self.route_max_output_tokens
            or type(self.reasoning_token_reserve) is not int
            or self.reasoning_token_reserve < 0
            or not self.reasoning_token_accounting
        ):
            raise ValueError("capacity_output_or_reasoning_limit_invalid")
        if not self.recovery_stage_role or not self.reasoning_policy:
            raise ValueError("capacity_recovery_delta_identity_invalid")
        expected_delta = capacity_recovery_prompt_delta_sha256_v1(
            prior_rendered_request_sha256=(
                self.prior_rendered_request_sha256
            ),
            rendered_request_sha256=self.rendered_request_sha256,
            recovery_stage_role=self.recovery_stage_role,
            reasoning_policy=self.reasoning_policy,
            recovery_source_capture_receipt_sha256=(
                self.recovery_source_capture_receipt_sha256
            ),
        )
        if self.recovery_prompt_delta_sha256 != expected_delta:
            raise ValueError("capacity_recovery_prompt_delta_sha256_mismatch")
        if _canonical_sha256(self.canonical_payload()) != self.plan_sha256:
            raise ValueError("capacity_plan_sha256_mismatch")

    def require_pass(self) -> None:
        if self.admission_status is AdmissionStatus.PASS:
            return
        failure_id = self.denial_failure_id
        if failure_id is None:
            failure_id = CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
        raise CapacityAdmissionFailureV1(failure_id, plan=self)


def capacity_recovery_prompt_delta_sha256_v1(
    *, prior_rendered_request_sha256: str | None,
    rendered_request_sha256: str,
    recovery_stage_role: str,
    reasoning_policy: str,
    recovery_source_capture_receipt_sha256: str | None,
) -> str:
    _require_sha256(
        rendered_request_sha256, field_name="rendered_request_sha256",
    )
    for field_name, value in (
        ("prior_rendered_request_sha256", prior_rendered_request_sha256),
        (
            "recovery_source_capture_receipt_sha256",
            recovery_source_capture_receipt_sha256,
        ),
    ):
        if value is not None:
            _require_sha256(value, field_name=field_name)
    if not recovery_stage_role or not reasoning_policy:
        raise ValueError("capacity_recovery_delta_identity_invalid")
    return _canonical_sha256({
        "domain": "novel-flywheel-capacity-recovery-prompt-delta-v1",
        "prior_rendered_request_sha256": prior_rendered_request_sha256,
        "rendered_request_sha256": rendered_request_sha256,
        "recovery_stage_role": recovery_stage_role,
        "reasoning_policy": reasoning_policy,
        "recovery_source_capture_receipt_sha256": (
            recovery_source_capture_receipt_sha256
        ),
    })


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
    model_context_limit: int | None,
    requested_output_token_cap: int,
    final_output_reserve: int,
    rendered_message_tokens: int,
    structured_envelope_tokens: int,
    provider_envelope_tokens: int,
    wrapper_and_estimator_margin_tokens: int,
    rendered_request_sha256: str,
    layer_projections: Iterable[CapacityLayerProjectionV1],
    parent_plan_sha256: str | None,
    route_context_capability_source: (
        RouteContextCapabilitySourceV1 | str
    ) = RouteContextCapabilitySourceV1.MODEL_CONFIGURATION,
    physical_attempt_id: str | None = None,
    global_physical_attempt_ordinal: int | None = None,
    logical_capacity_envelope_sha256: str | None = None,
    route_capability_snapshot_sha256: str | None = None,
    route_max_output_tokens: int | None = None,
    reasoning_token_reserve: int = 0,
    reasoning_token_accounting: str = "INCLUDED_IN_COMPLETION_CAP",
    recovery_stage_role: str = "NORMAL",
    reasoning_policy: str = "DEFAULT",
    prior_rendered_request_sha256: str | None = None,
    recovery_source_capture_receipt_sha256: str | None = None,
    policy_registry: StageCapacityPolicyRegistryV1 = (
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1
    ),
) -> StageCapacityPlanV1:
    if stage not in policy_registry.policies:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.POLICY_VIOLATION,
        )
    if physical_attempt < 1:
        raise ValueError("capacity_physical_attempt_invalid")
    if model_context_limit is None:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.CONTEXT_LIMIT_UNAVAILABLE,
        )
    if (
        isinstance(model_context_limit, bool)
        or not isinstance(model_context_limit, int)
        or model_context_limit <= 0
        or model_context_limit > MAX_CONTEXT_LIMIT_TOKENS_V1
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT,
        )
    try:
        capability_source = RouteContextCapabilitySourceV1(
            route_context_capability_source
        )
    except (TypeError, ValueError) as exc:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT,
        ) from exc
    values = (
        requested_output_token_cap,
        final_output_reserve,
        rendered_message_tokens,
        structured_envelope_tokens,
        provider_envelope_tokens,
        wrapper_and_estimator_margin_tokens,
        reasoning_token_reserve,
    )
    if any(value < 0 for value in values):
        raise ValueError("capacity_value_negative")
    projections = tuple(layer_projections)
    policy = policy_registry.require_policy(stage)
    stage_context_ceiling = policy.stage_operational_context_ceiling_tokens
    effective_context_limit = min(model_context_limit, stage_context_ceiling)
    effective_route_max_output = int(
        route_max_output_tokens or requested_output_token_cap
    )
    if (
        effective_route_max_output <= 0
        or requested_output_token_cap > effective_route_max_output
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED,
        )
    if capability_source is RouteContextCapabilitySourceV1.ROUTE_CAPABILITY_REGISTRY:
        if any(item is None for item in (
            physical_attempt_id,
            global_physical_attempt_ordinal,
            logical_capacity_envelope_sha256,
            route_capability_snapshot_sha256,
        )):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT,
            )
        if physical_attempt == 1:
            if (
                recovery_stage_role != "NORMAL"
                or reasoning_policy != "DEFAULT"
                or prior_rendered_request_sha256 is not None
                or recovery_source_capture_receipt_sha256 is not None
            ):
                raise CapacityAdmissionFailureV1(
                    CapacityFailureCode.INVALID_ATTEMPT_DELTA,
                )
        elif (
            prior_rendered_request_sha256 is None
            or recovery_source_capture_receipt_sha256 is None
            or (recovery_stage_role, reasoning_policy) not in {
                ("PLANNING_FINAL_ARTIFACT_RECOVERY", "DISABLE_REASONING"),
                ("NORMAL", "PRESERVE_REASONING_POLICY"),
            }
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.INVALID_ATTEMPT_DELTA,
            )
    recovery_prompt_delta_sha256 = (
        capacity_recovery_prompt_delta_sha256_v1(
            prior_rendered_request_sha256=prior_rendered_request_sha256,
            rendered_request_sha256=rendered_request_sha256,
            recovery_stage_role=recovery_stage_role,
            reasoning_policy=reasoning_policy,
            recovery_source_capture_receipt_sha256=(
                recovery_source_capture_receipt_sha256
            ),
        )
    )
    expected_rendered_input = rendered_message_tokens + structured_envelope_tokens
    prompt_budget = (
        effective_context_limit
        - final_output_reserve
        - reasoning_token_reserve
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
    unsupported_layers = any(
        layer.classification not in policy.allowed_layer_classes
        for layer in projections
    )
    compaction_requested = any(
        layer.action in {"COMPACT", "SHED"}
        for layer in projections
    )
    windowing_requested = any(
        layer.semantic_scope != "complete"
        or layer.action in {"WINDOW", "SEGMENT"}
        for layer in projections
    )
    invalid_action = any(
        layer.action not in {
            "IDENTITY", "PRESERVE", "COMPACT", "SHED", "WINDOW",
            "SEGMENT",
        }
        for layer in projections
    )
    invalid_transform_policy = any(
        layer.transform_policy_id not in policy.allowed_transform_policy_ids
        for layer in projections
    )
    invalid_semantic_scope = any(
        layer.semantic_scope not in policy.allowed_semantic_scopes
        for layer in projections
    )
    protected_content_transformed = any(
        layer.classification in protected_classes
        and (
            layer.action in {"COMPACT", "SHED"}
            or layer.pre_transform_characters
            != layer.post_transform_characters
            or layer.pre_transform_tokens != layer.post_transform_tokens
            or layer.transform_policy_id != "identity.v1"
        )
        for layer in projections
    )
    if (
        unsupported_layers
        or invalid_action
        or invalid_transform_policy
        or invalid_semantic_scope
        or protected_content_transformed
        or compaction_requested and not policy.compaction_allowed
        or windowing_requested and not policy.semantic_windowing_allowed
        or wrapper_and_estimator_margin_tokens
        < policy.minimum_wrapper_and_estimator_margin_tokens
    ):
        status = AdmissionStatus.DENIED
        failure = CapacityFailureCode.POLICY_VIOLATION
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
        failure = (
            CapacityFailureCode.COMPACTION_INSUFFICIENT
            if compaction_requested
            else CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
        )
    else:
        status = AdmissionStatus.DENIED
        failure = CapacityFailureCode.MODEL_CONTEXT_EXCEEDED
    payload = {
        "stage_id": stage_id,
        "logical_stage_id": logical_stage_id,
        "physical_attempt": physical_attempt,
        "physical_attempt_id": physical_attempt_id,
        "global_physical_attempt_ordinal": global_physical_attempt_ordinal,
        "logical_capacity_envelope_sha256": (
            logical_capacity_envelope_sha256
        ),
        "route_capability_snapshot_sha256": (
            route_capability_snapshot_sha256
        ),
        "stage": stage,
        "contract_name": contract_name,
        "contract_version": contract_version,
        "contract_schema_sha256": contract_schema_sha256,
        "provider_route_identity_sha256": provider_route_identity_sha256,
        "stage_operational_context_ceiling_tokens": stage_context_ceiling,
        "route_context_capability_limit_tokens": model_context_limit,
        "route_context_capability_source": capability_source,
        "model_context_limit": effective_context_limit,
        "requested_output_token_cap": requested_output_token_cap,
        "route_max_output_tokens": effective_route_max_output,
        "final_output_reserve": final_output_reserve,
        "reasoning_token_reserve": reasoning_token_reserve,
        "reasoning_token_accounting": reasoning_token_accounting,
        "recovery_stage_role": recovery_stage_role,
        "reasoning_policy": reasoning_policy,
        "prior_rendered_request_sha256": prior_rendered_request_sha256,
        "recovery_prompt_delta_sha256": recovery_prompt_delta_sha256,
        "recovery_source_capture_receipt_sha256": (
            recovery_source_capture_receipt_sha256
        ),
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
        "compaction_policy_id": policy.compaction_policy_id,
        "segmentation_policy_id": policy.segmentation_policy_id,
        "recovery_policy_id": policy.recovery_policy_id,
        "policy_registry_sha256": policy_registry.identity_sha256,
    }
    canonical_payload = {
        **payload,
        "admission_status": status.value,
        "denial_failure_id": failure.value if failure else None,
        "route_context_capability_source": capability_source.value,
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
    *,
    policy_registry: StageCapacityPolicyRegistryV1 = (
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1
    ),
) -> StageCapacityPlanV1:
    if plan.policy_registry_sha256 != policy_registry.identity_sha256:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.POLICY_VIOLATION,
            plan=plan,
        )
    policy = policy_registry.require_policy(plan.stage)
    if (
        any(
            layer.classification not in policy.allowed_layer_classes
            for layer in plan.layer_projections
        )
        or any(
            layer.transform_policy_id
            not in policy.allowed_transform_policy_ids
            for layer in plan.layer_projections
        )
        or any(
            layer.semantic_scope not in policy.allowed_semantic_scopes
            for layer in plan.layer_projections
        )
        or any(
            layer.classification in {
                CapacityLayerClass.HARD_PROTECTED,
                CapacityLayerClass.SOFT_PROTECTED,
            }
            and (
                layer.action in {"COMPACT", "SHED"}
                or layer.pre_transform_characters
                != layer.post_transform_characters
                or layer.pre_transform_tokens != layer.post_transform_tokens
                or layer.transform_policy_id != "identity.v1"
            )
            for layer in plan.layer_projections
        )
        or any(
            layer.action not in {
                "IDENTITY", "PRESERVE", "COMPACT", "SHED", "WINDOW",
                "SEGMENT",
            }
            for layer in plan.layer_projections
        )
        or any(
            layer.action in {"COMPACT", "SHED"}
            for layer in plan.layer_projections
        ) and not policy.compaction_allowed
        or any(
            layer.semantic_scope != "complete"
            or layer.action in {"WINDOW", "SEGMENT"}
            for layer in plan.layer_projections
        ) and not policy.semantic_windowing_allowed
        or plan.wrapper_and_estimator_margin_tokens
        < policy.minimum_wrapper_and_estimator_margin_tokens
        or plan.compaction_policy_id != policy.compaction_policy_id
        or plan.segmentation_policy_id != policy.segmentation_policy_id
        or plan.recovery_policy_id != policy.recovery_policy_id
        or plan.stage_operational_context_ceiling_tokens
        != policy.stage_operational_context_ceiling_tokens
        or not isinstance(
            plan.route_context_capability_source,
            RouteContextCapabilitySourceV1,
        )
        or plan.model_context_limit != min(
            plan.stage_operational_context_ceiling_tokens,
            plan.route_context_capability_limit_tokens,
        )
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.POLICY_VIOLATION,
            plan=plan,
        )
    plan.require_pass()
    return plan


def capacity_failure_recovery_disposition_v1(
    *,
    stage: str,
    failure_id: CapacityFailureCode | str,
    policy_registry: StageCapacityPolicyRegistryV1 = (
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1
    ),
) -> CapacityRecoveryDisposition:
    return policy_registry.require_policy(stage).recovery_disposition(failure_id)


class StageCapacityAdmissionEngineV1:
    @staticmethod
    def admit(**kwargs: object) -> StageCapacityPlanV1:
        policy_registry = kwargs.get(
            "policy_registry", DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
        )
        if not isinstance(policy_registry, StageCapacityPolicyRegistryV1):
            raise TypeError("capacity_policy_registry_invalid")
        plan = build_stage_capacity_plan_v1(**kwargs)  # type: ignore[arg-type]
        return enforce_stage_capacity_plan_v1(
            plan,
            policy_registry=policy_registry,
        )

    @staticmethod
    def enforce(
        plan: StageCapacityPlanV1,
        *,
        policy_registry: StageCapacityPolicyRegistryV1 = (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1
        ),
    ) -> StageCapacityPlanV1:
        return enforce_stage_capacity_plan_v1(
            plan,
            policy_registry=policy_registry,
        )


@full_short_boundary_entry("FS.CAPACITY.ADMIT")
def require_route_capability_v1(record: object) -> object:
    """Reject an absent/UNKNOWN formal capability before dispatch planning."""

    from novel_flywheel.route_capabilities import (
        RouteCapabilityError,
        RouteCapabilityRecordV1,
    )

    if not isinstance(record, RouteCapabilityRecordV1):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    try:
        return record.require_dispatchable()
    except RouteCapabilityError as exc:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        ) from exc

__all__ = [
    "AdmissionStatus",
    "CAPACITY_BOUNDARY_ID_V1",
    "CAPACITY_FAILURE_IDS_V1",
    "CAPACITY_FAILURE_IDS_V3",
    "CapacityAdmissionFailureV1",
    "CapacityFailureCode",
    "CapacityLayerClass",
    "CapacityLayerProjectionV1",
    "DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1",
    "CapacityRecoveryDisposition",
    "MAX_CONTEXT_LIMIT_TOKENS_V1",
    "RouteContextCapabilitySourceV1",
    "StageCapacityAdmissionEngineV1",
    "StageCapacityPlanV1",
    "StageCapacityPolicyRegistryV1",
    "StageCapacityPolicyV1",
    "build_stage_capacity_plan_v1",
    "capacity_failure_recovery_disposition_v1",
    "enforce_stage_capacity_plan_v1",
    "verify_rendered_request_v1",
    "require_route_capability_v1",
]
