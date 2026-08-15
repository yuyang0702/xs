"""Finite, immutable registry for executable real-Canary approval profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


PROFILE_SCHEMA = "CanaryApprovalProfileV1"
PROFILE_DOMAIN = "novel-flywheel-canary-approval-profile-v1"

C0B_PROFILE_ID = "c0b_smoke_1"
C0B_SCOPE = "C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1"
C0B_CANDIDATE_SCHEMA = "C0BSmoke1FinalApprovalCandidateV2"
C0B_PATCH_SCHEMA = "C0BSmoke1UserAuthorizationPatchV2"
C0B_PATCH_TEMPLATE_SCHEMA = C0B_PATCH_SCHEMA
C0B_SIGNED_SCHEMA = "C0BSmoke1SignedApprovalV1"

PA_PROFILE_ID = "pa_strict_tool_obs_1"
PA_SCOPE = "PA_STRICT_TOOL_OBS_1_SINGLE_REAL_PROVIDER_OBSERVATION"
PA_CANDIDATE_SCHEMA = "PAStrictToolObs1FinalApprovalCandidateV1"
PA_PATCH_SCHEMA = "PAStrictToolObsUserAuthorizationPatchV1"
PA_PATCH_TEMPLATE_SCHEMA = "PAStrictToolObs1UserAuthorizationPatchTemplateV2"
PA_SIGNED_SCHEMA = "PAStrictToolObsSignedApprovalV1"

PA_TARGET_FILTER = (
    ("stage", "review"),
    ("boundary", "planning_adaptation_whole_receipt"),
    ("contract_id", "planning_adaptation_whole"),
    ("contract_version", 1),
    ("role", "review"),
    ("route_kind", "configured_fallback"),
    ("strict_tool_route", True),
    ("target_selection_method", "exact_metadata_tuple_not_prompt_text"),
    ("non_target_policy", "excluded_not_target_count_only"),
)


class CanaryApprovalProfileError(ValueError):
    """Stable fail-closed profile registry error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CanaryApprovalProfileV1:
    profile_id: str
    approval_scope: str
    canary_mode: str
    candidate_schema: str
    authorization_patch_schema: str
    authorization_patch_template_schema: str
    signed_approval_schema: str
    validate_only_profile: str
    launcher_mode: str
    real_runner_handler: str
    required_feature_flags: tuple[tuple[str, bool], ...]
    forbidden_feature_flags: tuple[str, ...]
    required_target_filter: tuple[tuple[str, Any], ...]
    required_observation_schema: tuple[tuple[str, Any], ...]
    allowed_workload_ids: tuple[str, ...]
    budget_policy: tuple[tuple[str, int], ...]
    stop_condition_policy: tuple[str, ...]
    observation_goal_outcomes: tuple[str, ...]
    workflow_outcomes: tuple[str, ...]
    ledger_policy: tuple[tuple[str, Any], ...]
    profile_definition_sha256: str

    def definition(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("profile_definition_sha256")
        payload.update({
            "schema": PROFILE_SCHEMA,
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "required_feature_flags": dict(self.required_feature_flags),
            "required_target_filter": dict(self.required_target_filter),
            "required_observation_schema": dict(
                self.required_observation_schema
            ),
            "budget_policy": dict(self.budget_policy),
            "ledger_policy": dict(self.ledger_policy),
        })
        return {
            **payload,
            "profile_definition_sha256": self.profile_definition_sha256,
        }

    def required_flags(self) -> dict[str, bool]:
        return dict(self.required_feature_flags)

    def target_filter(self) -> dict[str, Any]:
        return dict(self.required_target_filter)

    def budget(self) -> dict[str, int]:
        return dict(self.budget_policy)


def _profile(**values: Any) -> CanaryApprovalProfileV1:
    provisional = CanaryApprovalProfileV1(
        **values, profile_definition_sha256="0" * 64,
    )
    body = provisional.definition()
    body.pop("profile_definition_sha256")
    return replace(
        provisional,
        profile_definition_sha256=domain_sha256(PROFILE_DOMAIN, body),
    )


_C0B = _profile(
    profile_id=C0B_PROFILE_ID,
    approval_scope=C0B_SCOPE,
    canary_mode="c0b_real_path_reachability",
    candidate_schema=C0B_CANDIDATE_SCHEMA,
    authorization_patch_schema=C0B_PATCH_SCHEMA,
    authorization_patch_template_schema=C0B_PATCH_TEMPLATE_SCHEMA,
    signed_approval_schema=C0B_SIGNED_SCHEMA,
    validate_only_profile="c0b_approval_closure_v1",
    launcher_mode="real_single_use",
    real_runner_handler="production_mirror_short_v1",
    required_feature_flags=(
        ("NOVEL_SHORT_CANONICAL_V2", False),
        ("project_short_canonical_v2", False),
        ("NOVEL_CANONICAL_SHADOW_V1", False),
        ("NOVEL_RELIABILITY_TRACE", True),
    ),
    forbidden_feature_flags=("NOVEL_SHORT_CANONICAL_V2",),
    required_target_filter=(),
    required_observation_schema=(),
    allowed_workload_ids=("short-normal-v1",),
    budget_policy=(
        ("maximum_runs", 1),
        ("maximum_model_calls_per_run", 48),
        ("maximum_total_model_calls", 48),
        ("maximum_input_tokens", 1_000_000),
        ("maximum_output_tokens", 1_000_000),
        ("maximum_output_tokens_per_call", 32_000),
        ("maximum_usd_cost_microunits", 20_000_000),
        ("maximum_cny_cost_microunits", 50_000_000),
        ("maximum_elapsed_seconds", 7_200),
    ),
    stop_condition_policy=(
        "first_terminal_failure",
        "first_controlled_provider_capability_outcome",
        "fingerprint_mismatch",
        "budget_exceeded",
        "route_mismatch",
        "price_schedule_mismatch",
        "approval_expired",
    ),
    observation_goal_outcomes=(),
    workflow_outcomes=(
        "WORKFLOW_COMPLETED", "WORKFLOW_TERMINAL", "CONTROLLED_NONTERMINAL",
    ),
    ledger_policy=(
        ("maximum_reservations", 1),
        ("identity_fields", "profile_id,signed_approval_sha256,cohort_id"),
        ("cross_profile_cohort_reuse_allowed", False),
        ("consume_requires_evidence_sha256", True),
    ),
)

_PA = _profile(
    profile_id=PA_PROFILE_ID,
    approval_scope=PA_SCOPE,
    canary_mode="pa_strict_tool_observation",
    candidate_schema=PA_CANDIDATE_SCHEMA,
    authorization_patch_schema=PA_PATCH_SCHEMA,
    authorization_patch_template_schema=PA_PATCH_TEMPLATE_SCHEMA,
    signed_approval_schema=PA_SIGNED_SCHEMA,
    validate_only_profile="pa_strict_tool_observation_closure_v1",
    launcher_mode="real_single_use_observation",
    real_runner_handler="production_mirror_short_strict_tool_observation_v1",
    required_feature_flags=(
        ("NOVEL_SHORT_CANONICAL_V2", False),
        ("project_short_canonical_v2", False),
        ("NOVEL_CANONICAL_SHADOW_V1", False),
        ("NOVEL_RELIABILITY_TRACE", True),
        ("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", True),
        ("NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1", False),
    ),
    forbidden_feature_flags=(
        "NOVEL_SHORT_CANONICAL_V2", "project_short_canonical_v2",
        "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1",
    ),
    required_target_filter=PA_TARGET_FILTER,
    required_observation_schema=(
        ("schema", "StrictToolShapeObservationV1"),
        ("version", 1),
        ("missing_snapshot_zero_inference_allowed", False),
        ("three_layer_correlation_required", True),
    ),
    allowed_workload_ids=("short-normal-v1",),
    budget_policy=(
        ("maximum_runs", 1),
        ("expected_model_calls", 11),
        ("maximum_model_calls_per_run", 24),
        ("maximum_total_model_calls", 24),
        ("maximum_input_tokens", 500_000),
        ("maximum_output_tokens", 500_000),
        ("maximum_output_tokens_per_call", 32_000),
        ("maximum_usd_cost_microunits", 10_000_000),
        ("maximum_cny_cost_microunits", 25_000_000),
        ("maximum_elapsed_seconds", 7_200),
    ),
    stop_condition_policy=(
        "target_strict_tool_shape_exact_captured",
        "first_workflow_terminal",
        "fingerprint_mismatch",
        "production_source_dirty_or_changed",
        "route_mismatch",
        "observation_privacy_violation",
        "observation_unavailable_at_target_boundary",
        "budget_exhausted",
        "controlled_provider_capability_outcome",
        "approval_expired",
        "live_isolation_violation",
    ),
    observation_goal_outcomes=(
        "TARGET_STRICT_TOOL_SHAPE_OBSERVED",
        "TARGET_NOT_REACHED",
        "TARGET_OBSERVATION_UNAVAILABLE",
    ),
    workflow_outcomes=(
        "WORKFLOW_COMPLETED", "WORKFLOW_TERMINAL", "CONTROLLED_NONTERMINAL",
        "CANARY_OBSERVATION_GOAL_REACHED_STOPPED",
    ),
    ledger_policy=(
        ("maximum_reservations", 1),
        ("identity_fields", "profile_id,signed_approval_sha256,cohort_id"),
        ("cross_profile_cohort_reuse_allowed", False),
        ("consume_requires_evidence_sha256", True),
    ),
)

_REGISTRY = MappingProxyType({
    C0B_PROFILE_ID: _C0B,
    PA_PROFILE_ID: _PA,
})


def approval_profile_registry_v1() -> Mapping[str, CanaryApprovalProfileV1]:
    return _REGISTRY


def approval_profile(profile_id: str) -> CanaryApprovalProfileV1:
    try:
        return _REGISTRY[profile_id]
    except KeyError as exc:
        raise CanaryApprovalProfileError("approval_profile_unknown") from exc


def approval_profile_for_scope(scope: str) -> CanaryApprovalProfileV1:
    matches = [item for item in _REGISTRY.values() if item.approval_scope == scope]
    if len(matches) != 1:
        raise CanaryApprovalProfileError("approval_profile_unknown")
    return matches[0]


def approval_profile_for_mode(mode: str) -> CanaryApprovalProfileV1:
    matches = [item for item in _REGISTRY.values() if item.canary_mode == mode]
    if len(matches) != 1:
        raise CanaryApprovalProfileError("runner_profile_not_supported")
    return matches[0]


def approval_profile_for_schema(
    schema: str,
) -> tuple[CanaryApprovalProfileV1, str]:
    for profile in _REGISTRY.values():
        kinds = {
            profile.candidate_schema: "candidate",
            profile.authorization_patch_schema: "authorization_patch",
            profile.authorization_patch_template_schema: "authorization_patch_template",
            profile.signed_approval_schema: "signed_approval",
        }
        if schema in kinds:
            return profile, kinds[schema]
    raise CanaryApprovalProfileError("approval_profile_unknown")


def validate_profile_definition(
    profile: CanaryApprovalProfileV1,
) -> CanaryApprovalProfileV1:
    expected = _profile(**{
        key: value for key, value in asdict(profile).items()
        if key != "profile_definition_sha256"
    })
    if expected.profile_definition_sha256 != profile.profile_definition_sha256:
        raise CanaryApprovalProfileError("approval_profile_hash_mismatch")
    return profile
