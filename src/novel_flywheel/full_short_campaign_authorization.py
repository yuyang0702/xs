"""Canonical authorization for the budget-unblocked Full Short campaign.

The contract in this module is intentionally an offline value object.  It cannot
read Git, credentials, projects, or external evidence, and it cannot dispatch a
provider request.  Materializers must derive all identities before calling the
renderer; launchers must validate the exact bytes again immediately before use.

The campaign authorization wraps, rather than replaces, the existing
``FullShortCanonicalAuthorizationV1``.  Its exact bytes are embedded and are
validated by the original validator, preserving every production execution
boundary owned by :mod:`novel_flywheel.full_short_execution`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from hashlib import sha256
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from novel_flywheel.ping_successor import (
    PING_RECOVERY_SCHEMA, PING_RECOVERY_SOURCE_IDENTITY, PING_RECOVERY_SOURCE_SHA256,
    PingRecoveryProofs, compact_sha, historical_by_case, selected_ordinals,
    ERROR_HARDENING_SCHEMA, ErrorHardeningRecoveryProofs,
)

from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    ExternalWorkloadEvidenceError,
    VerifiedWorkloadEvidenceV1,
    validate_external_workload_evidence_v1,
)
from novel_flywheel.full_short_execution import (
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
)
from novel_flywheel.full_short_probe_campaign import (
    CampaignLimits,
    ProbeCase,
    ProbeRouteIdentity,
    build_probe_campaign_plan,
)


SCHEMA = "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1"
AUTHORIZATION_SCHEMA = SCHEMA
AUTHORIZATION_SOURCE_SHA256 = (
    "29ab6557dc7ebdf687b86ee47f55472aa01e406166d0cfde87641630bd22791e"
)
AUTHORIZATION_SOURCE_IDENTITY = "FULL_SHORT_END_TO_END_ONE_ROUND_INPUT_BUDGET_UNBLOCK_EXECUTE_MASTER"
SHARED_USAGE_RECOVERY_SCHEMA = (
    "FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1"
)
SHARED_USAGE_RECOVERY_SOURCE_IDENTITY = (
    "PROBE01_SHARED_PROTOCOL_SAFE_CUMULATIVE_USAGE_FIX_REPLAY_AND_END_TO_END_CONTINUE_MASTER"
)
SHARED_USAGE_RECOVERY_SOURCE_SHA256 = (
    "925e5482cea2ac56e5a0b9dbc3b233563a2be15e00c0e0714d83d2a846ed5d10"
)
EXACT_READY_PROJECT_ID = "2ad716f3c0d1"
EXACT_READY_PROJECT_ID_SHA256 = (
    "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720"
)
EXACT_PRE_DISPATCH_ESTIMATED_INPUT_TOKENS = 2_559_809
PLAN_DERIVED_MAX_INPUT_TOKENS = 3_071_771
NEW_ABSOLUTE_MAX_INPUT_TOKENS = 4_000_000
NAMED_APPROVER = "USER_PREAUTHORIZED_BY_THIS_MASTER"

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40}\Z")


class FullShortCampaignAuthorizationError(ValueError):
    """Stable, non-secret failure raised by the canonical boundary."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BoundIdentityV1(_ClosedModel):
    identity: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _no_surrounding_whitespace(self) -> "BoundIdentityV1":
        if self.identity.strip() != self.identity:
            raise ValueError("identity is not canonical")
        return self


class AuthorizationSourceV1(_ClosedModel):
    identity: Literal[
        "FULL_SHORT_END_TO_END_ONE_ROUND_INPUT_BUDGET_UNBLOCK_EXECUTE_MASTER"
    ]
    sha256: Literal[
        "29ab6557dc7ebdf687b86ee47f55472aa01e406166d0cfde87641630bd22791e"
    ]


class SharedUsageRecoveryAuthorizationSourceV1(_ClosedModel):
    identity: Literal[
        "PROBE01_SHARED_PROTOCOL_SAFE_CUMULATIVE_USAGE_FIX_REPLAY_AND_END_TO_END_CONTINUE_MASTER"
    ]
    sha256: Literal[
        "925e5482cea2ac56e5a0b9dbc3b233563a2be15e00c0e0714d83d2a846ed5d10"
    ]


class SharedProtocolUsageRecoveryV1(_ClosedModel):
    """Exact proof references; the controller verifies committed file contents."""

    authoritative_usage_semantics: BoundIdentityV1
    raw_capture_sha256: Literal[
        "de1cdf7b6eefcab2fa28f6bab664aad159be87d1d4e152250a77e61974bef713"
    ]
    exact_replay: BoundIdentityV1
    workload_disposition: BoundIdentityV1
    probe01_disposition: Literal["FRESH_REPLACEMENT_REQUIRED"]
    request_zero_diff: BoundIdentityV1
    response_regression_matrix: BoundIdentityV1

    @model_validator(mode="after")
    def _relative_proof_paths(self) -> "SharedProtocolUsageRecoveryV1":
        for proof in (
            self.authoritative_usage_semantics, self.exact_replay,
            self.workload_disposition,
            self.request_zero_diff, self.response_regression_matrix,
        ):
            if (
                "\\" in proof.identity or ":" in proof.identity
                or any(part in {"", ".", ".."} for part in proof.identity.split("/"))
                or any(ord(char) < 32 for char in proof.identity)
            ):
                raise ValueError("proof identity is not a canonical relative path")
        return self


class FrozenExecutionV1(_ClosedModel):
    final_execution_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    branch: str = Field(min_length=1)
    worktree: Literal["CLEAN"]
    no_git_write_after_final_head_freeze: Literal[True]

    @model_validator(mode="after")
    def _canonical_branch(self) -> "FrozenExecutionV1":
        if self.branch.strip() != self.branch:
            raise ValueError("branch is not canonical")
        return self


class ProbeRouteV1(_ClosedModel):
    provider: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    destination_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol: str = Field(min_length=1)
    model: str = Field(min_length=1)
    route_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _bind_destination(self) -> "ProbeRouteV1":
        strings = (self.provider, self.operator, self.destination, self.protocol, self.model)
        if any(value.strip() != value for value in strings):
            raise ValueError("route string is not canonical")
        if sha256(self.destination.encode("utf-8")).hexdigest() != self.destination_sha256:
            raise ValueError("destination hash mismatch")
        return self


class ProbeCaseAuthorizationV1(_ClosedModel):
    ordinal: int = Field(ge=1, le=8)
    case_id: str = Field(min_length=1)
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: ProbeRouteV1
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_family_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimated_input_tokens: int = Field(gt=0)
    wire_requested_output_cap: int = Field(gt=0, le=32_000)
    blocked_shape_ordinals: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _bind_probe_case(self) -> "ProbeCaseAuthorizationV1":
        if self.case_id.strip() != self.case_id:
            raise ValueError("case id is not canonical")
        if self.blocked_shape_ordinals != sorted(set(self.blocked_shape_ordinals)):
            raise ValueError("shape coverage is not canonical")
        case = ProbeCase(
            ordinal=self.ordinal,
            case_id=self.case_id,
            route=ProbeRouteIdentity(
                provider=self.route.provider,
                operator=self.route.operator,
                destination_sha256=self.route.destination_sha256,
                protocol=self.route.protocol,
                model=self.route.model,
                route_fingerprint=self.route.route_fingerprint,
            ),
            fixture_sha256=self.fixture_sha256,
            input_envelope_sha256=self.input_envelope_sha256,
            estimated_input_tokens=self.estimated_input_tokens,
            wire_requested_output_cap=self.wire_requested_output_cap,
            blocked_shape_ordinals=tuple(self.blocked_shape_ordinals),
        )
        if case.case_sha256 != self.case_sha256:
            raise ValueError("probe case hash mismatch")
        return self

    def runtime_case(self) -> ProbeCase:
        return ProbeCase(
            ordinal=self.ordinal,
            case_id=self.case_id,
            route=ProbeRouteIdentity(
                provider=self.route.provider,
                operator=self.route.operator,
                destination_sha256=self.route.destination_sha256,
                protocol=self.route.protocol,
                model=self.route.model,
                route_fingerprint=self.route.route_fingerprint,
            ),
            fixture_sha256=self.fixture_sha256,
            input_envelope_sha256=self.input_envelope_sha256,
            estimated_input_tokens=self.estimated_input_tokens,
            wire_requested_output_cap=self.wire_requested_output_cap,
            blocked_shape_ordinals=tuple(self.blocked_shape_ordinals),
        )


class ProbeCampaignAuthorizationV1(_ClosedModel):
    schema_name: Literal["FullShortEightProbeCampaignV1"] = Field(alias="schema")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[ProbeCaseAuthorizationV1] = Field(min_length=8, max_length=8)
    source_blocked_shape_ordinals: list[int] = Field(min_length=111, max_length=111)
    blocked_shape_coverage_count: Literal[111]
    uncovered_blocked_shape_count: Literal[0]
    limits: dict[str, int]
    sequential: Literal[True]
    maximum_physical_requests_per_case: Literal[1]
    retry_allowed: Literal[False]
    fallback_allowed: Literal[False]
    route_switch_allowed: Literal[False]
    stop_on_first_dispatched_failure: Literal[True]
    exact_response_capture_required: Literal[True]
    raw_novel_content_egress_count: Literal[0]
    real_project_content_egress_count: Literal[0]

    @model_validator(mode="after")
    def _bind_runtime_plan(self) -> "ProbeCampaignAuthorizationV1":
        required_limits = {
            "provider_requests": 144,
            "http_post_attempts": 144,
            "network_requests": 144,
            "input_tokens": 4_000_000,
            "generated_output_tokens": 2_000_000,
            "output_tokens_per_request": 32_000,
            "elapsed_seconds": 36_000,
        }
        if self.limits != required_limits:
            raise ValueError("probe limits drift")
        if [case.ordinal for case in self.cases] != list(range(1, 9)):
            raise ValueError("probe case order drift")
        if len({case.case_id for case in self.cases}) != 8:
            raise ValueError("probe case identity reused")
        if self.source_blocked_shape_ordinals != sorted(
            set(self.source_blocked_shape_ordinals)
        ):
            raise ValueError("source shape set is not canonical")
        plan = build_probe_campaign_plan(
            [case.runtime_case() for case in self.cases],
            CampaignLimits(**{
                **required_limits,
                "elapsed_seconds": float(required_limits["elapsed_seconds"]),
            }),
            source_blocked_shape_ordinals=self.source_blocked_shape_ordinals,
        )
        if plan.plan_sha256 != self.plan_sha256:
            raise ValueError("probe plan hash mismatch")
        return self


class EvidenceVerificationKeyV1(_ClosedModel):
    key_id: str = Field(min_length=1)
    algorithm: Literal["HMAC-SHA256"]
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidencePromotionPolicyV1(_ClosedModel):
    identity: Literal["EXACT_SIGNED_WORKLOAD_LOWER_BOUND_ONLY"]
    accept_verified_safe_lower_bound: Literal[True]
    accept_verified_workload_shape: Literal[True]
    accept_verified_request_output_shape: Literal[True]
    theoretical_maximum_inference_allowed: Literal[False]
    arbitrary_external_json_allowed: Literal[False]
    upstream_model_name_inheritance_allowed: Literal[False]
    exact_authorization_hash_required: Literal[True]
    exact_frozen_head_required: Literal[True]
    exact_current_route_required: Literal[True]
    post_freeze_git_write_allowed: Literal[False]


class ExternalEvidenceAuthorizationV1(_ClosedModel):
    schema_name: Literal["ExternalWorkloadEvidenceV1"] = Field(alias="schema")
    verification_key: EvidenceVerificationKeyV1
    promotion_policy: EvidencePromotionPolicyV1
    promotion_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _bind_policy(self) -> "ExternalEvidenceAuthorizationV1":
        actual = _sha256_json(self.promotion_policy.model_dump(mode="json"))
        if actual != self.promotion_policy_sha256:
            raise ValueError("promotion policy hash mismatch")
        return self


class ExactReadyTargetV1(_ClosedModel):
    project_id: Literal["2ad716f3c0d1"]
    project_id_sha256: Literal[
        "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720"
    ]
    ready_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_status: Literal["READY"]


class ProductionRouteV1(_ClosedModel):
    ordinal: int = Field(ge=1)
    role: str = Field(min_length=1)
    lane: Literal["primary", "fallback"]
    provider: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    model: str = Field(min_length=1)
    route_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductionBindingsV1(_ClosedModel):
    route_model_graph: list[ProductionRouteV1] = Field(min_length=1)
    route_model_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_manifest: BoundIdentityV1
    destination_manifest: BoundIdentityV1
    runtime_kernel: BoundIdentityV1
    baseline_skill: BoundIdentityV1
    segmentation_windowing_policy: BoundIdentityV1
    capacity_admission_policy: BoundIdentityV1
    transport_recovery_policy: BoundIdentityV1
    logical_stage_recovery_policy: BoundIdentityV1
    authority_gates: BoundIdentityV1
    response_capture_policy: BoundIdentityV1
    response_replay_policy: BoundIdentityV1
    full_short_canonical_authorization_schema: Literal[
        "FullShortCanonicalAuthorizationV1"
    ]
    post_probe_authorization_derivation: "PostProbeAuthorizationDerivationV1"

    @model_validator(mode="after")
    def _bind_graph_and_bytes(self) -> "ProductionBindingsV1":
        if [route.ordinal for route in self.route_model_graph] != list(
            range(1, len(self.route_model_graph) + 1)
        ):
            raise ValueError("production route graph order drift")
        if len({(route.role, route.lane) for route in self.route_model_graph}) != len(
            self.route_model_graph
        ):
            raise ValueError("production route identity reused")
        if _sha256_json([
            route.model_dump(mode="json") for route in self.route_model_graph
        ]) != self.route_model_graph_sha256:
            raise ValueError("production route graph hash mismatch")
        return self


class PostProbeAuthorizationDerivationV1(_ClosedModel):
    """Close the formerly circular nested-authorization dependency.

    Probe evidence binds the outer authorization hash, while the production
    Full Short public bindings bind that evidence.  Therefore the nested
    canonical authorization can only be derived after the probes.  This
    policy authorizes that one derivation without authorizing substitution.
    """

    identity: Literal[
        "FROZEN_HEAD_VERIFIED_EXTERNAL_EVIDENCE_DERIVATION_ONLY"
    ]
    exact_outer_authorization_sha256_required: Literal[True]
    exact_frozen_head_required: Literal[True]
    exact_verified_evidence_packages_required: Literal[True]
    exact_production_route_graph_required: Literal[True]
    exact_ready_target_required: Literal[True]
    canonical_runtime_validator_required: Literal[True]
    external_non_git_storage_required: Literal[True]
    arbitrary_nested_authorization_allowed: Literal[False]
    derivation_count_maximum: Literal[1]


class CampaignBudgetsV1(_ClosedModel):
    budget_recalculation_source: BoundIdentityV1
    authoritative_attempt_matrix_source: BoundIdentityV1
    probe_family_derivation_source: BoundIdentityV1
    maximum_typed_business_recovery_path_physical_calls: Literal[96]
    maximum_typed_business_recovery_path_provider_wire_input: Literal[2_373_076]
    exact_probe_fixture_input_tokens: Literal[186_733]
    plan_derived_margin_numerator: Literal[120]
    plan_derived_margin_denominator: Literal[100]
    old_absolute_max_input_tokens: Literal[2_000_000]
    old_campaign_input_lower_bound: Literal[2_388_221]
    restored_deduplicated_call_input: Literal[16_037]
    exact_pre_dispatch_estimated_input_tokens: Literal[2_559_809]
    plan_derived_max_input_tokens: Literal[3_071_771]
    new_absolute_max_input_tokens: Literal[4_000_000]
    absolute_max_provider_requests: Literal[144]
    absolute_max_http_post_attempts: Literal[144]
    absolute_max_network_requests: Literal[144]
    absolute_max_generated_output_tokens: Literal[2_000_000]
    absolute_max_output_tokens_per_provider_request: Literal[32_000]
    absolute_max_elapsed_seconds: Literal[36_000]
    usd_hard_cap_if_reliably_meterable: Literal[60]
    cny_hard_cap_if_reliably_meterable: Literal[120]
    budget_gate: Literal["PASS"]


class CampaignScopeV1(_ClosedModel):
    single_campaign: Literal[True]
    reusable: Literal[False]
    maximum_real_full_short_executions: Literal[1]
    long_execution_allowed: Literal[False]
    route_change_allowed: Literal[False]
    model_change_allowed: Literal[False]
    baseline_skill_change_allowed: Literal[False]
    skill_v3_production_cutover: Literal[False]
    hybrid_production_cutover: Literal[False]
    selective_production_cutover: Literal[False]
    planning_v2_production_cutover: Literal[False]
    whole_run_retry_allowed: Literal[False]


class AuthorizationUsageV1(_ClosedModel):
    probe_phase_status: Literal["unused"]
    full_short_phase_status: Literal["unused"]
    provider_requests: Literal[0]
    http_post_attempts: Literal[0]
    network_requests: Literal[0]
    model_calls: Literal[0]
    paid_calls: Literal[0]
    input_tokens: Literal[0]
    generated_output_tokens: Literal[0]
    real_full_short_executions: Literal[0]
    nonces_created: Literal[0]


class FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1(_ClosedModel):
    """Original canonical campaign value, retained without schema migration."""

    schema_name: Literal[
        "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1"
    ] = Field(alias="schema")
    version: Literal[1]
    authorization_source: AuthorizationSourceV1
    frozen_execution: FrozenExecutionV1
    probe_campaign: ProbeCampaignAuthorizationV1
    external_workload_evidence: ExternalEvidenceAuthorizationV1
    exact_ready_target: ExactReadyTargetV1
    production_bindings: ProductionBindingsV1
    budgets: CampaignBudgetsV1
    scope: CampaignScopeV1
    execution_authorized: Literal[True]
    named_approver: Literal["USER_PREAUTHORIZED_BY_THIS_MASTER"]
    usage_status: Literal["unused"]
    campaign_usage: AuthorizationUsageV1

    @model_validator(mode="after")
    def _cross_bind(self) -> "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1":
        if self.probe_campaign.plan_sha256 in {
            case.case_sha256 for case in self.probe_campaign.cases
        }:
            raise ValueError("plan identity aliases case identity")
        probe_input = sum(
            case.estimated_input_tokens for case in self.probe_campaign.cases
            if not hasattr(self, "post_message_stop_ping_recovery")
            or case.ordinal in self.post_message_stop_ping_recovery.selected_probe_ordinals
        )
        if probe_input != self.budgets.exact_probe_fixture_input_tokens:
            raise ValueError("probe input budget drift")
        exact = (
            self.budgets.maximum_typed_business_recovery_path_provider_wire_input
            + probe_input
        )
        if exact != self.budgets.exact_pre_dispatch_estimated_input_tokens:
            raise ValueError("exact pre-dispatch budget drift")
        derived = (
            exact * self.budgets.plan_derived_margin_numerator
            + self.budgets.plan_derived_margin_denominator - 1
        ) // self.budgets.plan_derived_margin_denominator
        if derived != self.budgets.plan_derived_max_input_tokens:
            raise ValueError("plan-derived budget drift")
        if self.budgets.plan_derived_max_input_tokens > self.budgets.new_absolute_max_input_tokens:
            raise ValueError("plan budget exceeds outer budget")
        if self.budgets.exact_pre_dispatch_estimated_input_tokens > self.budgets.plan_derived_max_input_tokens:
            raise ValueError("estimate exceeds plan budget")
        return self


class FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1(
    FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1
):
    """Fresh successor authority preserving every existing nested validator."""

    schema_name: Literal[
        "FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1"
    ] = Field(alias="schema")
    authorization_source: SharedUsageRecoveryAuthorizationSourceV1
    shared_protocol_usage_recovery: SharedProtocolUsageRecoveryV1


class PingRecoveryAuthorizationSourceV1(_ClosedModel):
    identity: Literal["PROBE02_POST_MESSAGE_STOP_PING_ROOT_CAUSE_FIX_REPLAY_AND_END_TO_END_CONTINUE_MASTER"]
    sha256: Literal["1a15d628ea81e3938cc4dbe99574f02b50c7a9d6f7eb59a1734e5d9328bc1cc2"]


class PingRecoveryBudgetsV1(CampaignBudgetsV1):
    exact_probe_fixture_input_tokens: Literal[123895, 156275]
    exact_pre_dispatch_estimated_input_tokens: Literal[2496971, 2529351]
    plan_derived_max_input_tokens: Literal[2996366, 3035222]
    plan_derived_max_provider_requests: Literal[102, 103]


class FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1(
    FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1
):
    schema_name: Literal["FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1"] = Field(alias="schema")
    authorization_source: PingRecoveryAuthorizationSourceV1
    post_message_stop_ping_recovery: PingRecoveryProofs
    budgets: PingRecoveryBudgetsV1

    @model_validator(mode="after")
    def _bind_successor_partition(self):
        recovery = self.post_message_stop_ping_recovery
        if self.budgets.plan_derived_max_provider_requests != 96 + len(recovery.selected_probe_ordinals):
            raise ValueError("successor call cap drift")
        by_id = {case.case_id: case for case in self.probe_campaign.cases}
        for proof in recovery.historical_cases:
            case = by_id[proof.case_id]
            if (proof.source_request_sha256 != case.request_sha256
                or proof.canonical_output_tokens > case.wire_requested_output_cap
                or proof.source_execution_head == self.frozen_execution.final_execution_head):
                raise ValueError("historical provenance/request drift")
        return self


class ErrorHardeningAuthorizationSourceV1(_ClosedModel):
    identity: Literal["PROBE02_SHARED_ANTHROPIC_COMPATIBLE_ERROR_EVENT_HARDENING_MASTER"]
    sha256: Literal["d4314e0695ec95f80662015f0a6591a735405d881cd486e8770f4a584b8d0674"]


class ErrorHardeningBudgetsV1(PingRecoveryBudgetsV1):
    exact_probe_fixture_input_tokens: Literal[123895]
    exact_pre_dispatch_estimated_input_tokens: Literal[2496971]
    plan_derived_max_input_tokens: Literal[2996366]
    plan_derived_max_provider_requests: Literal[102]


class FullShortAnthropicErrorHardeningAndSuccessorExecutionAuthorizationV1(
    FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1
):
    schema_name: Literal["FullShortAnthropicErrorHardeningAndSuccessorExecutionAuthorizationV1"] = Field(alias="schema")
    authorization_source: ErrorHardeningAuthorizationSourceV1
    post_message_stop_ping_recovery: ErrorHardeningRecoveryProofs
    budgets: ErrorHardeningBudgetsV1


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole accepted byte representation (UTF-8 JSON plus LF)."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _sha256_json(value: Any) -> str:
    compact = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(compact).hexdigest()


def _coerce(
    value: Mapping[str, Any] | FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1,
) -> FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1:
    if isinstance(value, FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1):
        return value
    try:
        model = (
            FullShortAnthropicErrorHardeningAndSuccessorExecutionAuthorizationV1
            if isinstance(value, Mapping) and value.get("schema") == ERROR_HARDENING_SCHEMA
            else
            FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1
            if isinstance(value, Mapping) and value.get("schema") == PING_RECOVERY_SCHEMA
            else
            FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1
            if isinstance(value, Mapping)
            and value.get("schema") == SHARED_USAGE_RECOVERY_SCHEMA
            else FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1
        )
        return model.model_validate(value, strict=True)
    except (ValidationError, ValueError, RuntimeError, TypeError) as exc:
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_SHAPE_OR_VALUE_INVALID") from exc


def _validate_bound_dependencies(
    value: FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1,
    *,
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_keys: Mapping[str, bytes],
) -> None:
    # This is a credential-free pre-probe consistency check.  The resulting
    # canonical bytes are deliberately not embedded in the outer document:
    # the final nested authorization must be derived once after signed probe
    # evidence exists, otherwise its evidence binding and this outer hash
    # would form an impossible cycle.
    try:
        raw = render_full_short_canonical_authorization_v1(
            policy=full_short_policy,
            public_bindings=full_short_public_bindings,
        )
        nested = validate_full_short_canonical_authorization_v1(
            raw,
            policy=full_short_policy,
            public_bindings=full_short_public_bindings,
        )
    except Exception as exc:
        raise FullShortCampaignAuthorizationError(
            "FULL_SHORT_CANONICAL_AUTHORIZATION_INVALID"
        ) from exc
    nested_policy = nested.get("policy")
    if not isinstance(nested_policy, dict):
        raise FullShortCampaignAuthorizationError("FULL_SHORT_CANONICAL_AUTHORIZATION_INVALID")
    expected_policy_bindings = {
        "execution_head": value.frozen_execution.final_execution_head,
        "branch": value.frozen_execution.branch,
        "project_id_sha256": value.exact_ready_target.project_id_sha256,
        "route_manifest_sha256": value.production_bindings.route_manifest.sha256,
        "destination_manifest_sha256": value.production_bindings.destination_manifest.sha256,
        "runtime_authority_sha256": value.production_bindings.runtime_kernel.sha256,
        "style_reference_authority_sha256": value.production_bindings.baseline_skill.sha256,
        "capacity_policy_registry_sha256": value.production_bindings.capacity_admission_policy.sha256,
        "transport_recovery_policy_sha256": value.production_bindings.transport_recovery_policy.sha256,
        "logical_stage_recovery_policy_sha256": value.production_bindings.logical_stage_recovery_policy.sha256,
        "response_capture_policy_sha256": value.production_bindings.response_capture_policy.sha256,
    }
    for field, expected in expected_policy_bindings.items():
        if nested_policy.get(field) != expected:
            raise FullShortCampaignAuthorizationError(
                f"PRODUCTION_{field.upper()}_DRIFT"
            )
    public_routes = full_short_public_bindings.get("routes")
    if not isinstance(public_routes, list) or len(public_routes) != len(
        value.production_bindings.route_model_graph
    ):
        raise FullShortCampaignAuthorizationError("PRODUCTION_ROUTE_MODEL_GRAPH_DRIFT")
    for authorized, current in zip(
        value.production_bindings.route_model_graph, public_routes, strict=True
    ):
        if not isinstance(current, Mapping) or {
            "role": current.get("role"),
            "lane": current.get("lane"),
            "provider": current.get("provider_name"),
            "operator": current.get("provider_operator"),
            "destination": current.get("destination"),
            "protocol": current.get("protocol"),
            "model": current.get("model_name"),
            "route_fingerprint": current.get("route_fingerprint"),
        } != {
            "role": authorized.role,
            "lane": authorized.lane,
            "provider": authorized.provider,
            "operator": authorized.operator,
            "destination": authorized.destination,
            "protocol": authorized.protocol,
            "model": authorized.model,
            "route_fingerprint": authorized.route_fingerprint,
        }:
            raise FullShortCampaignAuthorizationError(
                "PRODUCTION_ROUTE_MODEL_GRAPH_DRIFT"
            )
    graph_sha256 = _sha256_json([
        route.model_dump(mode="json")
        for route in value.production_bindings.route_model_graph
    ])
    if graph_sha256 != value.production_bindings.route_model_graph_sha256:
        raise FullShortCampaignAuthorizationError(
            "PRODUCTION_ROUTE_MODEL_GRAPH_DRIFT"
        )
    key = verification_keys.get(value.external_workload_evidence.verification_key.key_id)
    if not isinstance(key, bytes) or len(key) < 32:
        raise FullShortCampaignAuthorizationError("EVIDENCE_VERIFICATION_KEY_UNAVAILABLE")
    if sha256(key).hexdigest() != value.external_workload_evidence.verification_key.key_sha256:
        raise FullShortCampaignAuthorizationError("EVIDENCE_VERIFICATION_KEY_IDENTITY_DRIFT")


def render_full_short_one_round_budget_unblocked_execution_authorization_v1(
    authorization: Mapping[str, Any]
    | FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1,
    *,
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_keys: Mapping[str, bytes],
) -> bytes:
    """Validate dependencies and render the canonical authorization bytes."""

    value = _coerce(authorization)
    _validate_bound_dependencies(
        value,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys=verification_keys,
    )
    return canonical_json_bytes(value.model_dump(mode="json", by_alias=True))


def validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
    raw: bytes,
    *,
    expected: Mapping[str, Any]
    | FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1,
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_keys: Mapping[str, bytes],
    consumed_authorization_sha256s: Collection[str] = (),
    actual_usage: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate exact canonical bytes, bindings, freshness, and hard caps.

    ``expected`` is the frozen pre-dispatch value derived from current source
    truth.  Comparing against it is what makes every string/hash/ordered list an
    exact binding instead of accepting a merely well-formed self-assertion.
    """

    if not isinstance(raw, bytes):
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_MUST_BE_BYTES")
    try:
        parsed = json.loads(raw.decode("utf-8"))
        canonical = canonical_json_bytes(parsed)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_UTF8_OR_JSON_INVALID") from None
    if raw != canonical:
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_NONCANONICAL_BYTES")
    actual = _coerce(parsed)
    expected_value = _coerce(expected)
    expected_raw = render_full_short_one_round_budget_unblocked_execution_authorization_v1(
        expected_value,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys=verification_keys,
    )
    if raw != expected_raw:
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_EXACT_BINDING_DRIFT")
    _validate_bound_dependencies(
        actual,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys=verification_keys,
    )
    authorization_sha256 = sha256(raw).hexdigest()
    if authorization_sha256 in consumed_authorization_sha256s:
        raise FullShortCampaignAuthorizationError("AUTHORIZATION_REUSE_FORBIDDEN")
    if actual_usage is not None:
        required = {
            "provider_requests",
            "http_post_attempts",
            "network_requests",
            "model_calls",
            "paid_calls",
            "input_tokens",
            "generated_output_tokens",
            "real_full_short_executions",
        }
        if not isinstance(actual_usage, Mapping) or set(actual_usage) != required:
            raise FullShortCampaignAuthorizationError("ACTUAL_USAGE_SHAPE_INVALID")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in actual_usage.values()
        ):
            raise FullShortCampaignAuthorizationError("ACTUAL_USAGE_VALUE_INVALID")
        caps = {
            "provider_requests": 144,
            "http_post_attempts": 144,
            "network_requests": 144,
            "input_tokens": actual.budgets.plan_derived_max_input_tokens,
            "generated_output_tokens": 2_000_000,
            "real_full_short_executions": 1,
        }
        if isinstance(actual, FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1):
            for name in ("provider_requests", "http_post_attempts", "network_requests"):
                caps[name] = actual.budgets.plan_derived_max_provider_requests
        for name, cap in caps.items():
            if actual_usage[name] > cap:
                raise FullShortCampaignAuthorizationError(f"CAMPAIGN_{name.upper()}_CAP_EXCEEDED")
        if actual_usage["model_calls"] > actual_usage["provider_requests"]:
            raise FullShortCampaignAuthorizationError("CAMPAIGN_MODEL_CALL_ACCOUNTING_INVALID")
        if actual_usage["paid_calls"] > actual_usage["provider_requests"]:
            raise FullShortCampaignAuthorizationError("CAMPAIGN_PAID_CALL_ACCOUNTING_INVALID")
    result = actual.model_dump(mode="json", by_alias=True)
    result["authorization_sha256"] = authorization_sha256
    return result


def validate_post_probe_full_short_authorization_derivation_v1(
    *,
    outer_raw: bytes,
    expected_outer: Mapping[str, Any]
    | FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1,
    nested_raw: bytes,
    outer_full_short_policy: Mapping[str, Any],
    outer_full_short_public_bindings: Mapping[str, Any],
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_keys: Mapping[str, bytes],
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    consumed_outer_authorization_sha256s: Collection[str] = (),
    actual_usage: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Validate the sole authorized post-probe nested authorization.

    The nested bytes are accepted only when they are the canonical rendering
    of the supplied live policy/public bindings and every promoted workload
    record is an exact, reverified package bound to this outer authorization,
    frozen HEAD, route, fixture, and request family.
    """

    outer = validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
        outer_raw,
        expected=expected_outer,
        full_short_policy=outer_full_short_policy,
        full_short_public_bindings=outer_full_short_public_bindings,
        verification_keys=verification_keys,
        consumed_authorization_sha256s=consumed_outer_authorization_sha256s,
        actual_usage=actual_usage,
    )
    if full_short_public_bindings.get("authorization_eligible") is not True:
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_FULL_SHORT_NOT_AUTHORIZATION_ELIGIBLE"
        )
    # Evidence promotion may change the route manifest and elapsed-time
    # remainder only.  It cannot silently widen/rewrite the pre-probe Full
    # Short policy (plan, workload, identities, recovery, request/output caps,
    # project, run, or any other production invariant).
    if set(full_short_policy) != set(outer_full_short_policy):
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_FULL_SHORT_POLICY_DRIFT"
        )
    allowed_changes = {
        "route_manifest_sha256", "maximum_elapsed_seconds", "policy_sha256",
    }
    if any(
        full_short_policy.get(field) != outer_full_short_policy.get(field)
        for field in full_short_policy
        if field not in allowed_changes
    ) or not (
        type(full_short_policy.get("maximum_elapsed_seconds")) is int
        and 0 < full_short_policy["maximum_elapsed_seconds"]
        <= outer_full_short_policy.get("maximum_elapsed_seconds", 0)
    ):
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_FULL_SHORT_POLICY_DRIFT"
        )
    outer_graph = outer["production_bindings"]["route_model_graph"]
    current_graph = []
    for ordinal, route in enumerate(full_short_public_bindings.get("routes", []), 1):
        if not isinstance(route, Mapping):
            raise FullShortCampaignAuthorizationError(
                "PRODUCTION_ROUTE_MODEL_GRAPH_DRIFT"
            )
        current_graph.append({
            "ordinal": ordinal,
            "role": route.get("role"),
            "lane": route.get("lane"),
            "provider": route.get("provider_name"),
            "operator": route.get("provider_operator"),
            "destination": route.get("destination"),
            "protocol": route.get("protocol"),
            "model": route.get("model_name"),
            "route_fingerprint": route.get("route_fingerprint"),
        })
    if current_graph != outer_graph:
        raise FullShortCampaignAuthorizationError(
            "PRODUCTION_ROUTE_MODEL_GRAPH_DRIFT"
        )
    evidence_sha256s = validate_external_evidence_against_outer_v1(
        outer=outer,
        outer_authorization_sha256=outer["authorization_sha256"],
        verified_evidence=verified_evidence,
        verification_keys=verification_keys,
    )

    evidence_by_sha = {
        item.evidence_sha256: item for item in verified_evidence
    }
    public_evidence_sha256s: set[str] = set()
    for route in full_short_public_bindings.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        for family in route.get("external_workload_evidence_families", []):
            if not isinstance(family, Mapping):
                continue
            evidence_sha256 = str(family.get("evidence_sha256"))
            evidence = evidence_by_sha.get(evidence_sha256)
            if evidence is None or {
                "provider": route.get("provider_name"),
                "operator": route.get("provider_operator"),
                "destination": route.get("destination"),
                "protocol": route.get("protocol"),
                "model": route.get("model_name"),
                "route_fingerprint": route.get("route_fingerprint"),
            } != {
                "provider": evidence.provider,
                "operator": evidence.operator,
                "destination": evidence.destination,
                "protocol": evidence.protocol,
                "model": evidence.model,
                "route_fingerprint": evidence.route_fingerprint_sha256,
            }:
                raise FullShortCampaignAuthorizationError(
                    "POST_PROBE_PUBLIC_EVIDENCE_BINDING_DRIFT"
                )
            public_evidence_sha256s.add(evidence_sha256)
    if public_evidence_sha256s != evidence_sha256s:
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_PUBLIC_EVIDENCE_BINDING_DRIFT"
        )
    canonical_nested = render_full_short_canonical_authorization_v1(
        policy=full_short_policy,
        public_bindings=full_short_public_bindings,
    )
    if nested_raw != canonical_nested:
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_NESTED_AUTHORIZATION_SUBSTITUTION_REJECTED"
        )
    try:
        nested = validate_full_short_canonical_authorization_v1(
            nested_raw,
            policy=full_short_policy,
            public_bindings=full_short_public_bindings,
        )
    except Exception as exc:
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_NESTED_AUTHORIZATION_INVALID"
        ) from exc
    nested["outer_authorization_sha256"] = outer["authorization_sha256"]
    nested["nested_authorization_sha256"] = sha256(nested_raw).hexdigest()
    return nested


def validate_external_evidence_against_outer_v1(
    *,
    outer: Mapping[str, Any],
    outer_authorization_sha256: str,
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    verification_keys: Mapping[str, bytes],
) -> set[str]:
    """Reverify exact packages against the outer case manifest.

    Callers use this before passing any evidence to capacity collection.  It
    intentionally does not derive expectations from fields carried by the
    evidence object itself.
    """

    if not isinstance(verified_evidence, tuple) or len(verified_evidence) != 8:
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
        )
    if not _HEX64.fullmatch(outer_authorization_sha256):
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
        )
    key_id = outer["external_workload_evidence"]["verification_key"]["key_id"]
    history = historical_by_case(outer)
    expected_by_case = {
        item["case_id"]: item for item in outer["probe_campaign"]["cases"]
    }
    observed_case_ids: set[str] = set()
    observed_nonce_sha256s: set[str] = set()
    evidence_sha256s: set[str] = set()
    for item in verified_evidence:
        if not isinstance(item, VerifiedWorkloadEvidenceV1):
            raise FullShortCampaignAuthorizationError(
                "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
            )
        case = expected_by_case.get(item.case_id)
        if case is None or item.case_id in observed_case_ids:
            raise FullShortCampaignAuthorizationError(
                "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
            )
        expected = ExpectedWorkloadEvidenceV1(
            authorization_sha256=outer_authorization_sha256,
            final_execution_head=outer["frozen_execution"]["final_execution_head"],
            provider=case["route"]["provider"],
            operator=case["route"]["operator"],
            destination=case["route"]["destination"],
            protocol=case["route"]["protocol"],
            model=case["route"]["model"],
            route_fingerprint_sha256=case["route"]["route_fingerprint"],
            case_id=case["case_id"],
            fixture_sha256=case["fixture_sha256"],
            request_family_sha256=case["request_family_sha256"],
            request_sha256=case["request_sha256"],
            input_tokens=case["estimated_input_tokens"],
            requested_output_tokens=case["wire_requested_output_cap"],
            key_id=key_id,
            historical_admission_sha256=(compact_sha(history[item.case_id])
                if item.case_id in history else None),
        )
        try:
            reverified = validate_external_workload_evidence_v1(
                item.package_bytes,
                expected=expected,
                verification_keys=verification_keys,
            )
        except ExternalWorkloadEvidenceError:
            raise FullShortCampaignAuthorizationError(
                "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
            ) from None
        if reverified != item:
            raise FullShortCampaignAuthorizationError(
                "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
            )
        if item.nonce_sha256 in observed_nonce_sha256s:
            raise FullShortCampaignAuthorizationError(
                "POST_PROBE_NONCE_REUSE_FORBIDDEN"
            )
        observed_case_ids.add(item.case_id)
        observed_nonce_sha256s.add(item.nonce_sha256)
        evidence_sha256s.add(item.evidence_sha256)
    if observed_case_ids != set(expected_by_case):
        raise FullShortCampaignAuthorizationError(
            "POST_PROBE_EXTERNAL_EVIDENCE_SET_INVALID"
        )
    return evidence_sha256s


__all__ = [
    "AUTHORIZATION_SOURCE_IDENTITY",
    "AUTHORIZATION_SOURCE_SHA256",
    "AUTHORIZATION_SCHEMA",
    "EXACT_PRE_DISPATCH_ESTIMATED_INPUT_TOKENS",
    "EXACT_READY_PROJECT_ID",
    "EXACT_READY_PROJECT_ID_SHA256",
    "FullShortCampaignAuthorizationError",
    "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1",
    "FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1",
    "SharedProtocolUsageRecoveryV1",
    "SHARED_USAGE_RECOVERY_SCHEMA",
    "SHARED_USAGE_RECOVERY_SOURCE_IDENTITY",
    "SHARED_USAGE_RECOVERY_SOURCE_SHA256",
    "NAMED_APPROVER",
    "NEW_ABSOLUTE_MAX_INPUT_TOKENS",
    "PLAN_DERIVED_MAX_INPUT_TOKENS",
    "SCHEMA",
    "canonical_json_bytes",
    "render_full_short_one_round_budget_unblocked_execution_authorization_v1",
    "validate_external_evidence_against_outer_v1",
    "validate_post_probe_full_short_authorization_derivation_v1",
    "validate_full_short_one_round_budget_unblocked_execution_authorization_v1",
]
