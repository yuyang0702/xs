"""Profile-aware deterministic dispatch for real-Canary approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from .approval_profiles import (
    C0B_PROFILE_ID,
    PA_PROFILE_ID,
    CanaryApprovalProfileError,
    CanaryApprovalProfileV1,
    approval_profile,
    approval_profile_for_mode,
    approval_profile_for_schema,
)
from .contracts import (
    CanaryContractError,
    materialize_signed_smoke_approval_v1,
    validate_c0b_smoke_1_final_approval_candidate_v2,
    validate_c0b_smoke_1_signed_approval_v1,
    validate_c0b_smoke_1_user_authorization_patch_v1,
    validate_c0b_smoke_1_user_authorization_patch_v2,
    validate_signed_smoke_approval_plan_v1,
    validate_signed_smoke_approval_sources_v1,
)
from .pa_approval import (
    materialize_pa_signed_approval_v1,
    validate_pa_authorization_patch_template_v2,
    validate_pa_authorization_patch_v1,
    validate_pa_final_approval_candidate_v1,
    validate_pa_signed_approval_plan_v1,
    validate_pa_signed_approval_sources_v1,
    validate_pa_signed_approval_v1,
)


_SIGNERS: Mapping[str, Callable[..., dict[str, Any]]] = {
    C0B_PROFILE_ID: materialize_signed_smoke_approval_v1,
    PA_PROFILE_ID: materialize_pa_signed_approval_v1,
}

_SOURCE_VALIDATORS: Mapping[str, Callable[..., dict[str, Any]]] = {
    C0B_PROFILE_ID: validate_signed_smoke_approval_sources_v1,
    PA_PROFILE_ID: validate_pa_signed_approval_sources_v1,
}

_PLAN_VALIDATORS: Mapping[str, Callable[..., dict[str, Any]]] = {
    C0B_PROFILE_ID: validate_signed_smoke_approval_plan_v1,
    PA_PROFILE_ID: validate_pa_signed_approval_plan_v1,
}


def _profile_and_kind(value: Mapping[str, Any]) -> tuple[CanaryApprovalProfileV1, str]:
    schema = value.get("schema")
    if not isinstance(schema, str):
        raise CanaryContractError("approval_schema_mismatch")
    try:
        profile, kind = approval_profile_for_schema(schema)
    except CanaryApprovalProfileError as exc:
        profile_id = value.get("profile_id")
        if profile_id is not None:
            try:
                approval_profile(str(profile_id))
            except CanaryApprovalProfileError as profile_exc:
                raise CanaryContractError("approval_profile_unknown") from profile_exc
        raise CanaryContractError("approval_schema_mismatch") from exc
    declared = value.get("profile_id")
    if declared is not None and declared != profile.profile_id:
        raise CanaryContractError("approval_profile_unknown")
    return profile, kind


def profile_for_plan(plan: Mapping[str, Any]) -> CanaryApprovalProfileV1:
    try:
        profile = approval_profile_for_mode(str(plan.get("canary_mode") or ""))
    except CanaryApprovalProfileError as exc:
        raise CanaryContractError(exc.reason_code) from exc
    policy = plan.get("pa_strict_tool_observation_policy")
    if profile.profile_id == PA_PROFILE_ID:
        if not isinstance(policy, Mapping):
            raise CanaryContractError("approval_profile_scope_mismatch")
        if policy.get("profile_id") != profile.profile_id:
            raise CanaryContractError("approval_profile_scope_mismatch")
        if policy.get("approval_scope") != profile.approval_scope:
            raise CanaryContractError("approval_profile_scope_mismatch")
        if policy.get("profile_definition_sha256") != (
            profile.profile_definition_sha256
        ):
            raise CanaryContractError("approval_profile_hash_mismatch")
    return profile


def validate_registered_approval_document(
    value: Mapping[str, Any], *, expected_profile_id: str,
    expected_scope: str, expected_plan_sha256: str,
    expected_launcher_sha256: str, now: datetime | None = None,
    enforce_time: bool = True,
) -> tuple[dict[str, Any], str, str, CanaryApprovalProfileV1]:
    profile, kind = _profile_and_kind(value)
    if profile.profile_id != expected_profile_id:
        raise CanaryContractError("approval_profile_scope_mismatch")
    if profile.approval_scope != expected_scope:
        raise CanaryContractError("approval_profile_scope_mismatch")
    if value.get("approval_scope") != expected_scope:
        raise CanaryContractError("approval_scope_mismatch")
    if kind == "candidate":
        if profile.profile_id == C0B_PROFILE_ID:
            validated = validate_c0b_smoke_1_final_approval_candidate_v2(
                value,
                expected_plan_sha256=expected_plan_sha256,
                expected_launcher_sha256=expected_launcher_sha256,
                now=now,
                enforce_time=enforce_time,
            )
        else:
            validated = validate_pa_final_approval_candidate_v1(
                value,
                expected_plan_sha256=expected_plan_sha256,
                expected_launcher_sha256=expected_launcher_sha256,
                now=now,
                enforce_time=enforce_time,
            )
        return (
            validated,
            str(validated["approval_candidate_sha256"]),
            "final_approval_candidate",
            profile,
        )
    if kind in {"authorization_patch", "authorization_patch_template"}:
        if profile.profile_id == C0B_PROFILE_ID:
            if value.get("version") == 1:
                validate_c0b_smoke_1_user_authorization_patch_v1(value)
            else:
                validate_c0b_smoke_1_user_authorization_patch_v2(value)
        elif kind == "authorization_patch_template":
            validate_pa_authorization_patch_template_v2(value)
        else:
            validate_pa_authorization_patch_v1(
                value, now=now, enforce_time=enforce_time,
            )
        raise CanaryContractError("authorization_patch_not_executable")
    if kind != "signed_approval":
        raise CanaryContractError("approval_schema_mismatch")
    if profile.profile_id == C0B_PROFILE_ID:
        validated = validate_c0b_smoke_1_signed_approval_v1(
            value,
            expected_plan_sha256=expected_plan_sha256,
            expected_launcher_sha256=expected_launcher_sha256,
            now=now,
            enforce_time=enforce_time,
        )
    else:
        validated = validate_pa_signed_approval_v1(
            value,
            expected_plan_sha256=expected_plan_sha256,
            expected_launcher_sha256=expected_launcher_sha256,
            now=now,
            enforce_time=enforce_time,
        )
    return validated, str(validated["signed_approval_sha256"]), (
        "signed_smoke_approval"
        if profile.profile_id == C0B_PROFILE_ID
        else "signed_approval"
    ), profile


def materialize_signed_canary_approval(
    profile_id: str, candidate: Mapping[str, Any],
    authorization_patch: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    profile = approval_profile(profile_id)
    candidate_profile, candidate_kind = _profile_and_kind(candidate)
    patch_profile, patch_kind = _profile_and_kind(authorization_patch)
    if candidate_kind != "candidate":
        raise CanaryContractError("approval_schema_mismatch")
    if patch_kind != "authorization_patch":
        raise CanaryContractError("approval_schema_mismatch")
    if candidate_profile != profile or patch_profile != profile:
        raise CanaryContractError("approval_profile_scope_mismatch")
    signer = _SIGNERS.get(profile.profile_id)
    if signer is None:
        raise CanaryContractError("runner_profile_not_supported")
    return signer(candidate, authorization_patch, now=now)


def validate_registered_signed_sources(
    profile_id: str, signed_approval: Mapping[str, Any],
    candidate: Mapping[str, Any], authorization_patch: Mapping[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    validator = _SOURCE_VALIDATORS.get(profile_id)
    if validator is None:
        raise CanaryContractError("approval_profile_unknown")
    return validator(
        signed_approval, candidate, authorization_patch, now=now,
    )


def validate_registered_signed_plan(
    profile_id: str, signed_approval: Mapping[str, Any],
    plan: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    validator = _PLAN_VALIDATORS.get(profile_id)
    if validator is None:
        raise CanaryContractError("approval_profile_unknown")
    return validator(signed_approval, plan, now=now)
