"""Route-bound reasoning policy for final-artifact recovery.

Business code selects an abstract finalization policy.  This module is the
only place that may translate it into a provider request directive.  The
closed binding deliberately names the currently verified official DeepSeek
Anthropic route; model names or an ``anthropic`` protocol alone never confer
this capability.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ReasoningPolicy(StrEnum):
    CURRENT_PROVIDER_DEFAULT = "current_provider_default"
    FINALIZATION_FIRST = "finalization_first"
    FINALIZATION_FIRST_IF_SUPPORTED = "finalization_first_if_supported"


class ProviderReasoningDirective(StrEnum):
    CURRENT_PROVIDER_DEFAULT = "current_provider_default"
    DISABLE_REASONING = "disable_reasoning"


PLANNING_FINAL_ARTIFACT_RECOVERY = "PLANNING_FINAL_ARTIFACT_RECOVERY"


class ReasoningPolicyCapabilityError(RuntimeError):
    """The selected route cannot prove the requested reasoning control."""

    failure_code = "reasoning_policy_capability_unverified"


@dataclass(frozen=True)
class ProviderReasoningCapabilityBindingV1:
    provider_id: str
    operator: str
    destination: str
    protocol: str
    model_id: str
    model: str
    route_fingerprint: str
    lane: str
    stage: str
    contract_name: str
    contract_version: int
    model_role: str
    stage_role: str


DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1 = (
    ProviderReasoningCapabilityBindingV1(
        provider_id="0e6a5627-5882-40df-bca5-7d98b97fdd0b",
        operator="DEEPSEEK_OFFICIAL",
        destination="https://api.deepseek.com:443/anthropic/v1/messages",
        protocol="anthropic",
        model_id="e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
        model="deepseek-v4-pro",
        route_fingerprint=(
            "04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31"
        ),
        lane="fallback",
        stage="planning",
        contract_name="planning_semantic_v2",
        contract_version=2,
        model_role="planning",
        stage_role=PLANNING_FINAL_ARTIFACT_RECOVERY,
    )
)
DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_PRIMARY_V1 = (
    replace(
        DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1,
        lane="primary",
    )
)

# The same official DeepSeek Anthropic route is also used by the reference
# synthesis role.  Its structured final artifact must not spend the complete
# max_tokens budget on hidden reasoning; this is a closed, role/contract
# binding and does not alter the provider's default policy elsewhere.
DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1 = replace(
    DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_PRIMARY_V1,
    stage="reference_synthesis",
    contract_name="reference_distillation_region",
    contract_version=2,
    model_role="reference_synthesis",
    stage_role="NORMAL",
)


def is_verified_finalization_first_route(
    *, provider_id: str, model_id: str, route_fingerprint: str,
) -> bool:
    """Return whether the exact verified DeepSeek route supports finalization."""
    reference = DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1
    return (
        provider_id == reference.provider_id
        and model_id == reference.model_id
        and route_fingerprint == reference.route_fingerprint
    )


def resolve_provider_reasoning_directive_v1(
    policy: ReasoningPolicy,
    *,
    provider_id: str,
    operator: str,
    destination: str,
    protocol: str,
    model_id: str,
    model: str,
    route_fingerprint: str,
    lane: str,
    stage: str,
    contract_name: str,
    contract_version: int,
    model_role: str,
    stage_role: str,
) -> ProviderReasoningDirective:
    """Resolve one abstract policy through an exact, closed capability key."""

    # Recovery metadata may cross a JSON/API boundary as the enum value.
    # Normalize it once at the shared resolver boundary so string transport
    # does not masquerade as an unverified capability on fallback routes.
    if not isinstance(policy, ReasoningPolicy):
        try:
            policy = ReasoningPolicy(str(policy))
        except ValueError as exc:
            raise ReasoningPolicyCapabilityError(
                "unknown reasoning policy"
            ) from exc

    if policy is ReasoningPolicy.CURRENT_PROVIDER_DEFAULT:
        return ProviderReasoningDirective.CURRENT_PROVIDER_DEFAULT
    actual = ProviderReasoningCapabilityBindingV1(
        provider_id=provider_id,
        operator=operator,
        destination=destination,
        protocol=protocol,
        model_id=model_id,
        model=model,
        route_fingerprint=route_fingerprint,
        lane=lane,
        stage=stage,
        contract_name=contract_name,
        contract_version=contract_version,
        model_role=model_role,
        stage_role=stage_role,
    )
    # Shared structured-output policy: use the verified disable-reasoning
    # directive on the exact DeepSeek Official Anthropic route whenever the
    # route is selected, while leaving every other provider/model at its
    # configured default. This avoids turning a fallback capability gap into
    # a terminal reasoning-only artifact without changing role bindings.
    if policy is ReasoningPolicy.FINALIZATION_FIRST_IF_SUPPORTED:
        if is_verified_finalization_first_route(
            provider_id=actual.provider_id,
            model_id=actual.model_id,
            route_fingerprint=actual.route_fingerprint,
        ) and actual.operator == DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1.operator \
            and actual.destination == DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1.destination \
            and actual.protocol == DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1.protocol \
            and actual.model == DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1.model:
            return ProviderReasoningDirective.DISABLE_REASONING
        return ProviderReasoningDirective.CURRENT_PROVIDER_DEFAULT
    if (
        policy is ReasoningPolicy.FINALIZATION_FIRST
        and actual in {
            DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1,
            DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_PRIMARY_V1,
            DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1,
        }
    ):
        return ProviderReasoningDirective.DISABLE_REASONING
    # Some legacy contract-runtime doubles omit the stage-role field while
    # still carrying the full route/role/contract identity. Keep the
    # reference-synthesis exception closed over every identity that matters;
    # this does not grant the policy to another provider, model, lane, or
    # contract.
    if (
        policy is ReasoningPolicy.FINALIZATION_FIRST
        and provider_id == DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1.provider_id
        and operator == DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1.operator
        and destination == DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1.destination
        and protocol == "anthropic"
        and model_id == DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1.model_id
        and route_fingerprint == DEEPSEEK_OFFICIAL_ANTHROPIC_REFERENCE_SYNTHESIS_PRIMARY_V1.route_fingerprint
        and lane == "primary"
        and stage == "reference_synthesis"
        and contract_name == "reference_distillation_region"
        and contract_version == 2
        and model_role == "reference_synthesis"
    ):
        return ProviderReasoningDirective.DISABLE_REASONING
    raise ReasoningPolicyCapabilityError(
        "finalization-first reasoning control is not verified for the exact route"
    )
