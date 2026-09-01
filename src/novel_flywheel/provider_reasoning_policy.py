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
    if (
        policy is ReasoningPolicy.FINALIZATION_FIRST
        and actual in {
            DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_V1,
            DEEPSEEK_OFFICIAL_ANTHROPIC_PLANNING_FINALIZATION_PRIMARY_V1,
        }
    ):
        return ProviderReasoningDirective.DISABLE_REASONING
    raise ReasoningPolicyCapabilityError(
        "finalization-first reasoning control is not verified for the exact route"
    )
