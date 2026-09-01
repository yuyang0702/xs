from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel_flywheel.execution_failure_architecture import (
    ExactRecoveryViolation,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
    FailureLayer,
    FullShortExactRecoveryControllerV1,
    ObserverGuard,
    build_durable_failure_evidence,
)
from novel_flywheel.models import (
    CapabilityRoutesExhaustedError,
    ModelRoutesExhaustedError,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


def _typed(code: str, failure_class: FailureClass) -> RuntimeError:
    error = RuntimeError("PRIVATE raw message C:\\secret\\request.json")
    error.reliability_failure = ReliabilityFailure(
        code=code, failure_class=failure_class, boundary="provider.route",
    )
    return error


def test_durable_failure_graph_preserves_ordered_route_children_without_raw_text() -> None:
    first = _typed("credential_missing", FailureClass.CREDENTIAL)
    second = _typed("protocol_invalid", FailureClass.SYNTAX_PROTOCOL)
    third = _typed("transport_interrupted", FailureClass.TRANSPORT)
    wrapped = ModelRoutesExhaustedError(
        first, third,
        route_errors=[
            ("primary", "one", first),
            ("primary-retry", "two", second),
            ("fallback", "three", third),
        ],
    )

    evidence = build_durable_failure_evidence(
        wrapped, boundary="workflow.recovery",
    )
    serialized = json.dumps(evidence.model_dump(mode="json"), sort_keys=True)

    assert [child.code for child in evidence.root.children] == [
        "credential_missing", "protocol_invalid", "transport_interrupted",
    ]
    assert "PRIVATE raw message" not in serialized
    assert "C:\\\\secret" not in serialized
    assert len(evidence.failure_graph_sha256) == 64


def test_opaque_reliability_token_is_not_persisted_as_a_failure_code() -> None:
    secretlike = "secretlikealphanumericcredential987654321"
    error = RuntimeError("private")
    error.reliability_failure = SimpleNamespace(
        code=secretlike, failure_class=FailureClass.UNKNOWN,
        boundary="private-boundary", retryable=False,
    )

    evidence = build_durable_failure_evidence(error, boundary="task")

    assert evidence.root.code == "external_unknown_after_boundary"
    assert secretlike not in json.dumps(evidence.model_dump(mode="json"))


def test_hyphenated_credential_like_metadata_is_not_persisted() -> None:
    secretlike = "sk-live-private-credential-abcdef1234567890"
    error = RuntimeError("private")
    error.reliability_failure = SimpleNamespace(
        code=secretlike, failure_class=FailureClass.UNKNOWN,
        boundary=secretlike, retryable=False,
    )
    error.failure_family = secretlike
    error.recovery_action = secretlike

    serialized = json.dumps(
        build_durable_failure_evidence(error, boundary="task").model_dump(
            mode="json",
        ),
    )

    assert secretlike not in serialized


def test_untyped_nested_failure_is_explicit_unknown_child_not_transport() -> None:
    child = RuntimeError("opaque provider wrapper")
    wrapped = ModelRoutesExhaustedError(
        child, child, route_errors=[("primary", "one", child)],
    )

    evidence = build_durable_failure_evidence(
        wrapped, boundary="workflow.recovery",
    )

    assert evidence.root.children[0].code == "unknown_child"
    assert evidence.root.children[0].failure_class == FailureClass.UNKNOWN


def test_empty_capability_route_exhaustion_is_typed_not_generic_unknown() -> None:
    evidence = build_durable_failure_evidence(
        CapabilityRoutesExhaustedError([]), boundary="model_gateway",
    )

    assert evidence.root.code == "capability_routes_exhausted"
    assert evidence.root.failure_class == FailureClass.CAPABILITY
    assert evidence.root.family == "provider.capability_routes_exhausted"


def test_route_alias_preserves_order_and_hashed_lane_identity() -> None:
    shared = _typed("transport_interrupted", FailureClass.TRANSPORT)
    wrapped = ModelRoutesExhaustedError(
        shared, shared,
        route_errors=[
            ("provider-a", "model-a", shared),
            ("provider-b", "model-b", shared),
        ],
    )

    evidence = build_durable_failure_evidence(
        wrapped, boundary="workflow.recovery",
    )

    assert [item.code for item in evidence.root.children] == [
        "transport_interrupted", "transport_interrupted",
    ]
    assert [item.route_ordinal for item in evidence.root.children] == [1, 2]
    assert evidence.root.children[0].provider_id_sha256 != (
        evidence.root.children[1].provider_id_sha256
    )


def test_exact_recovery_second_slot_is_shared_and_terminal() -> None:
    controller = FullShortExactRecoveryControllerV1()
    controller.record_initial_attempt("planning-1")
    assert controller.authorize_shared_second_slot(
        "planning-1", typed_rejection_code="business_contract_incomplete",
        recovery_kind="business_recovery",
    ) == 2

    with pytest.raises(ExactRecoveryViolation, match="shared_second_slot_unavailable"):
        controller.authorize_shared_second_slot(
            "planning-1",
            typed_rejection_code="reasoning_only_final_artifact_unavailable",
            recovery_kind="reasoning_finalization",
        )


def test_recovery_registry_owns_every_failure_layer() -> None:
    defaults = FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1[
        "layer_default_policies"
    ]

    assert set(defaults) == {layer.value for layer in FailureLayer}
    assert all(bool(disposition) for disposition in defaults.values())


def test_reasoning_recovery_requires_exact_typed_rejection_and_same_route() -> None:
    controller = FullShortExactRecoveryControllerV1()
    controller.record_initial_attempt("planning-1")
    with pytest.raises(ExactRecoveryViolation):
        controller.authorize_shared_second_slot(
            "planning-1", typed_rejection_code="business_contract_incomplete",
            recovery_kind="reasoning_finalization",
        )
    with pytest.raises(ExactRecoveryViolation, match="route_switch_forbidden"):
        controller.authorize_shared_second_slot(
            "planning-1",
            typed_rejection_code="reasoning_only_final_artifact_unavailable",
            recovery_kind="reasoning_finalization", route_switch=True,
        )


def test_best_effort_observer_cannot_mask_primary_outcome() -> None:
    failures: list[str] = []
    guard = ObserverGuard(lambda exc: failures.append(type(exc).__name__))

    assert guard.emit(lambda: (_ for _ in ()).throw(RuntimeError("diagnostic"))) is False
    assert failures == ["RuntimeError"]


def test_gbk_console_emoji_failure_is_contained_as_diagnostic_only() -> None:
    guard = ObserverGuard()

    def gbk_console_sink() -> None:
        "🌊".encode("gbk")

    assert guard.emit(gbk_console_sink) is False
