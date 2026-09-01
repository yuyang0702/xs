from __future__ import annotations

import hashlib
import json

import pytest

from novel_flywheel.contract_runtime import (
    ContractBusinessOutputIncompleteError,
    ExecutableContractSpec,
    FinalArtifactCapabilityExhaustedError,
    ReasoningOnlyFinalizationRecoveryPolicyV1,
    execute_contract_runtime,
)
from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest, ModelResponse
from novel_flywheel.full_short_execution import _expected_provider_payload_v1
from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
from novel_flywheel.models import (
    ModelGateway,
    ModelResult,
    ReasoningOnlyFinalArtifactUnavailableError,
)
from novel_flywheel.provider_payloads import anthropic_payload_v1
from novel_flywheel.provider_reasoning_policy import (
    PLANNING_FINAL_ARTIFACT_RECOVERY,
    ProviderReasoningDirective,
    ReasoningPolicy,
    ReasoningPolicyCapabilityError,
    resolve_provider_reasoning_directive_v1,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from novel_flywheel.providers.registry import ResolvedModel


OFFLINE_RECOVERY_MATRIX_V1 = {
    "normal_planning_valid_attempt_1": "test_normal_success_does_not_dispatch_recovery",
    "historical_segment_2_typed_rejection": "test_reasoning_only_recovery_is_same_route_fresh_attempt_and_validated",
    "same_logical_fresh_physical_attempt": "test_reasoning_only_recovery_is_same_route_fresh_attempt_and_validated",
    "official_deepseek_recovery_payload": "test_anthropic_payload_default_is_byte_identical_and_recovery_is_exact",
    "normal_deepseek_planning_payload": "test_all_normal_stage_payloads_preserve_provider_default",
    "deepseek_draft_payload": "test_all_normal_stage_payloads_preserve_provider_default",
    "other_anthropic_provider_payload": "test_unverified_routes_fail_closed_without_wire_injection",
    "third_party_deepseek_payload": "test_unverified_routes_fail_closed_without_wire_injection",
    "openai_format_payload": "test_openai_payloads_ignore_anthropic_reasoning_extension",
    "recovery_valid_exactly_one_accept": "test_reasoning_only_recovery_is_same_route_fresh_attempt_and_validated",
    "recovery_reasoning_only_terminal": "test_attempt_two_failure_is_terminal_with_no_third_call",
    "recovery_business_incomplete_terminal": "test_attempt_two_failure_is_terminal_with_no_third_call",
    "recovery_malformed_terminal": "tests/test_contract_runtime.py",
    "provider_explicit_error_not_reasoning": "tests/test_final_artifact_guard.py",
    "ambiguous_transport_no_redispatch": "tests/test_full_short_execution.py",
    "restart_after_rejection_no_dispatch": "tests/test_full_short_execution.py",
    "restart_after_dispatch_reconcile": "tests/test_full_short_execution.py",
    "duplicate_attempt_id_rejected": "tests/test_full_short_execution.py",
    "two_accepted_artifacts_impossible": "tests/test_full_short_execution.py",
    "physical_request_hard_cap": "tests/test_full_short_execution.py",
    "total_output_cap": "tests/test_full_short_execution.py",
    "elapsed_cap": "tests/test_full_short_execution.py",
    "exact_capture_both_attempts": "tests/test_provider_response_capture.py",
    "rejected_provenance_in_acceptance": "tests/test_full_short_execution.py",
}


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _request(*, directive: str = "current_provider_default") -> ModelRequest:
    return ModelRequest(
        model="deepseek-v4-pro",
        messages=[
            Message(role="system", content="SYSTEM"),
            Message(role="user", content="USER"),
        ],
        max_output_tokens=3724,
        response_schema={
            "name": "planning_semantic_v2",
            "schema": {"type": "object"},
        },
        reasoning_directive=directive,
        stage_role=(
            PLANNING_FINAL_ARTIFACT_RECOVERY
            if directive == "disable_reasoning" else "NORMAL"
        ),
    )


def test_anthropic_payload_default_is_byte_identical_and_recovery_is_exact() -> None:
    normal = anthropic_payload_v1(_request())
    recovery = anthropic_payload_v1(_request(directive="disable_reasoning"))
    assert "reasoning" not in normal
    assert _sha(normal) == (
        "702529430d9c7954aa15fd725073e1e1778e9f042cc66b08892a7c15b6b10596"
    )
    assert recovery == {**normal, "reasoning": {"effort": "none"}}
    assert set(recovery).symmetric_difference(normal) == {"reasoning"}


@pytest.mark.parametrize(
    "stage_role",
    [
        "NORMAL_PLANNING", "DRAFT", "SEMANTIC_VERIFICATION",
        "READER_REVIEW", "POLISH", "QUALITY_FINAL_REVIEW", "MAINTENANCE",
    ],
)
def test_all_normal_stage_payloads_preserve_provider_default(stage_role) -> None:
    request = _request().model_copy(update={"stage_role": stage_role})
    assert request.reasoning_directive == "current_provider_default"
    assert "reasoning" not in anthropic_payload_v1(request)


def test_unverified_routes_fail_closed_without_wire_injection() -> None:
    normal = anthropic_payload_v1(_request())
    for changes in (
        {
            "operator": "THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY",
            "destination": "https://relay.test:443/anthropic/v1/messages",
        },
        {
            "provider_id": "third-party-deepseek",
            "operator": "THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY",
        },
    ):
        with pytest.raises(ReasoningPolicyCapabilityError):
            resolve_provider_reasoning_directive_v1(
                ReasoningPolicy.FINALIZATION_FIRST,
                **_capability_args(**changes),
            )
    assert "reasoning" not in normal


def test_openai_payloads_ignore_anthropic_reasoning_extension() -> None:
    normal = _request()
    recovery = _request(directive="disable_reasoning")
    for protocol in ("openai-chat", "openai-responses"):
        assert _expected_provider_payload_v1(
            protocol, normal, destination="https://relay.test/v1",
        ) == _expected_provider_payload_v1(
            protocol, recovery, destination="https://relay.test/v1",
        )


def test_offline_recovery_matrix_has_all_24_required_unique_cases() -> None:
    assert len(OFFLINE_RECOVERY_MATRIX_V1) == 24
    assert len(set(OFFLINE_RECOVERY_MATRIX_V1)) == 24
    assert all(OFFLINE_RECOVERY_MATRIX_V1.values())


def _capability_args(**changes):
    values = {
        "provider_id": "0e6a5627-5882-40df-bca5-7d98b97fdd0b",
        "operator": "DEEPSEEK_OFFICIAL",
        "destination": "https://api.deepseek.com:443/anthropic/v1/messages",
        "protocol": "anthropic",
        "model_id": "e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
        "model": "deepseek-v4-pro",
        "route_fingerprint": (
            "04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31"
        ),
        "lane": "fallback",
        "stage": "planning",
        "contract_name": "planning_semantic_v2",
        "contract_version": 2,
        "model_role": "planning",
        "stage_role": PLANNING_FINAL_ARTIFACT_RECOVERY,
    }
    values.update(changes)
    return values


def test_exact_official_deepseek_capability_resolves_and_every_key_is_closed() -> None:
    assert resolve_provider_reasoning_directive_v1(
        ReasoningPolicy.FINALIZATION_FIRST, **_capability_args()
    ) is ProviderReasoningDirective.DISABLE_REASONING
    assert resolve_provider_reasoning_directive_v1(
        ReasoningPolicy.FINALIZATION_FIRST,
        **_capability_args(lane="primary"),
    ) is ProviderReasoningDirective.DISABLE_REASONING
    mutations = {
        "provider_id": "other",
        "operator": "THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY",
        "destination": "https://relay.test:443/anthropic/v1/messages",
        "protocol": "openai-responses",
        "model_id": "other",
        "model": "deepseek-v4-pro-third-party",
        "route_fingerprint": "f" * 64,
        "lane": "unverified_lane",
        "stage": "review",
        "contract_name": "other",
        "contract_version": 1,
        "model_role": "review",
        "stage_role": "NORMAL",
    }
    for key, value in mutations.items():
        with pytest.raises(ReasoningPolicyCapabilityError):
            resolve_provider_reasoning_directive_v1(
                ReasoningPolicy.FINALIZATION_FIRST,
                **_capability_args(**{key: value}),
            )
    assert resolve_provider_reasoning_directive_v1(
        ReasoningPolicy.CURRENT_PROVIDER_DEFAULT,
        **_capability_args(operator="THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY"),
    ) is ProviderReasoningDirective.CURRENT_PROVIDER_DEFAULT


@pytest.mark.asyncio
async def test_gateway_binds_recovery_directive_before_adapter_without_network(
    tmp_path,
) -> None:
    class CapturingAdapter:
        def __init__(self):
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            return ModelResponse(
                text='{"ok":true}', finish_reason="stop",
                provider_state={"transport_complete": True},
            )

    adapter = CapturingAdapter()
    resolved = ResolvedModel(
        provider_id="0e6a5627-5882-40df-bca5-7d98b97fdd0b",
        model_id="e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
        model_name="deepseek-v4-pro",
        adapter=adapter,
        capabilities={"structured_output": "plain_text"},
        route_fingerprint=(
            "04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31"
        ),
        provider_operator="DEEPSEEK_OFFICIAL",
        protocol="anthropic",
        destination="https://api.deepseek.com:443/anthropic/v1/messages",
        route_lane="fallback",
    )
    db = Database(tmp_path / "app.db")
    db.migrate()
    gateway = ModelGateway(db, object())
    result = await gateway._complete_resolved(
        "planning", "SYSTEM", "USER", resolved, 3724,
        reasoning_policy=ReasoningPolicy.FINALIZATION_FIRST,
        stage_role=PLANNING_FINAL_ARTIFACT_RECOVERY,
        stage="planning",
        contract_name="planning_semantic_v2",
        contract_version=2,
    )
    assert result.receipt["reasoning_directive"] == "disable_reasoning"
    assert adapter.requests[0].reasoning_directive == "disable_reasoning"
    assert anthropic_payload_v1(adapter.requests[0])["reasoning"] == {
        "effort": "none"
    }


def _contract() -> StructuredArtifactContract:
    return StructuredArtifactContract(
        name="interview_planning",
        version=1,
        schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        runtime_authority={"frozen": True},
    )


def _spec() -> ExecutableContractSpec:
    contract = _contract()
    return ExecutableContractSpec(
        contract_name=contract.name,
        structured_contract=contract,
        semantic_normalizer=lambda value: dict(value),
        domain_validator=lambda payload: (
            payload if len(str(payload.get("message") or "")) >= 12
            else (_ for _ in ()).throw(ValueError("incomplete"))
        ),
    )


def _context(tmp_path) -> ModelDiagnosticContextV1:
    return ModelDiagnosticContextV1(
        project_root=tmp_path,
        run_id="offline-reasoning-recovery",
        stage="planning",
        boundary="planning_semantic_v2",
        role="planning",
        route_kind="configured_fallback",
        contract_id="interview_planning",
        contract_version=1,
        outer_retry_ordinal=1,
    )


def _reasoning_error() -> ReasoningOnlyFinalArtifactUnavailableError:
    return ReasoningOnlyFinalArtifactUnavailableError(receipt={
        "finish_reason": "max_tokens",
        "transport_complete": True,
        "route_fingerprint": "a" * 64,
        "provider_call_executed": True,
        "provider_output_shape": {"shape_sha256": "b" * 64},
    })


class _Gateway:
    @staticmethod
    def has_configured_fallback(role: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_normal_success_does_not_dispatch_recovery(tmp_path) -> None:
    calls = []

    async def execute(
        attempt, role, system, user, budget, contract,
        *, reasoning_policy, stage_role,
    ):
        calls.append((attempt.attempt_index, reasoning_policy, stage_role, budget))
        return ModelResult(
            '{"message":"正常 Planning 首次调用直接返回完整最终业务产物"}',
            {"finish_reason": "stop", "transport_complete": True},
        )

    result = await execute_contract_runtime(
        _Gateway(),
        role="planning",
        system="SYSTEM",
        user="USER",
        execution_spec=_spec(),
        max_output_tokens=3724,
        attempt_routes=("configured_fallback", "configured_fallback"),
        attempt_executor=execute,
        diagnostic_context=_context(tmp_path),
        finalization_recovery_policy=ReasoningOnlyFinalizationRecoveryPolicyV1(),
    )
    assert result.attempt.attempt_index == 1
    assert calls == [(
        1, ReasoningPolicy.CURRENT_PROVIDER_DEFAULT, "NORMAL", 3724,
    )]


@pytest.mark.asyncio
async def test_non_reasoning_runtime_schedule_preserves_configured_fallback(
    tmp_path,
) -> None:
    calls = []

    async def execute(
        attempt, role, system, user, budget, contract,
        *, reasoning_policy, stage_role,
    ):
        calls.append((attempt.attempt_index, attempt.route, stage_role))
        if attempt.attempt_index < 3:
            return ModelResult(
                '{}', {"finish_reason": "stop", "transport_complete": True},
            )
        return ModelResult(
            '{"message":"普通业务恢复仍可到达既有 configured fallback 路由"}',
            {"finish_reason": "stop", "transport_complete": True},
        )

    result = await execute_contract_runtime(
        _Gateway(),
        role="planning", system="SYSTEM", user="USER",
        execution_spec=_spec(), max_output_tokens=3724,
        attempt_executor=execute,
        diagnostic_context=_context(tmp_path),
        finalization_recovery_policy=ReasoningOnlyFinalizationRecoveryPolicyV1(),
    )
    assert calls == [
        (1, "primary", "NORMAL"),
        (2, "primary", "NORMAL"),
        (3, "configured_fallback", "NORMAL"),
    ]
    assert result.attempt.route == "configured_fallback"


@pytest.mark.asyncio
async def test_reasoning_only_recovery_is_same_route_fresh_attempt_and_validated(
    tmp_path,
) -> None:
    calls = []
    rejections = []

    async def execute(
        attempt, role, system, user, budget, contract,
        *, reasoning_policy, stage_role,
    ):
        calls.append({
            "attempt": attempt,
            "role": role,
            "system": system,
            "user": user,
            "budget": budget,
            "contract": contract,
            "reasoning_policy": reasoning_policy,
            "stage_role": stage_role,
        })
        if len(calls) == 1:
            raise _reasoning_error()
        return ModelResult(
            '{"message":"同一冻结权威下完整且可验证的最终业务产物"}',
            {"finish_reason": "stop", "transport_complete": True},
        )

    result = await execute_contract_runtime(
        _Gateway(),
        role="planning",
        system="SYSTEM",
        user="USER",
        execution_spec=_spec(),
        max_output_tokens=3724,
        attempt_routes=("configured_fallback", "configured_fallback"),
        attempt_executor=execute,
        local_rejection_sink=rejections.append,
        diagnostic_context=_context(tmp_path),
        finalization_recovery_policy=(
            ReasoningOnlyFinalizationRecoveryPolicyV1()
        ),
    )
    assert len(calls) == 2
    assert calls[0]["attempt"].route == calls[1]["attempt"].route
    assert calls[0]["attempt"].attempt_index == 1
    assert calls[1]["attempt"].attempt_index == 2
    assert calls[0]["reasoning_policy"] is ReasoningPolicy.CURRENT_PROVIDER_DEFAULT
    assert calls[1]["reasoning_policy"] is ReasoningPolicy.FINALIZATION_FIRST
    assert calls[1]["stage_role"] == PLANNING_FINAL_ARTIFACT_RECOVERY
    assert calls[1]["budget"] == 3724
    assert calls[0]["user"] == calls[1]["user"] == "USER"
    assert "same frozen Planning logical stage" in calls[1]["system"]
    assert result.attempt.attempt_index == 2
    assert result.domain_value["message"].startswith("同一冻结权威")
    assert len(rejections) == 1
    assert rejections[0]["failure_code"] == (
        "reasoning_only_final_artifact_unavailable"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("second_outcome", ["reasoning_only", "business_incomplete"])
async def test_attempt_two_failure_is_terminal_with_no_third_call(
    tmp_path, second_outcome,
) -> None:
    calls = []

    async def execute(
        attempt, role, system, user, budget, contract,
        *, reasoning_policy, stage_role,
    ):
        calls.append(attempt.attempt_index)
        if len(calls) == 1 or second_outcome == "reasoning_only":
            raise _reasoning_error()
        return ModelResult(
            '{}',
            {"finish_reason": "stop", "transport_complete": True},
        )

    expected = (
        FinalArtifactCapabilityExhaustedError
        if second_outcome == "reasoning_only"
        else ContractBusinessOutputIncompleteError
    )
    with pytest.raises(expected):
        await execute_contract_runtime(
            _Gateway(),
            role="planning",
            system="SYSTEM",
            user="USER",
            execution_spec=_spec(),
            max_output_tokens=3724,
            attempt_routes=("configured_fallback", "configured_fallback"),
            attempt_executor=execute,
            diagnostic_context=_context(tmp_path),
            finalization_recovery_policy=(
                ReasoningOnlyFinalizationRecoveryPolicyV1()
            ),
        )
    assert calls == [1, 2]
