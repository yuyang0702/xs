from __future__ import annotations

import ast
import json
from pathlib import Path
import re
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
from novel_flywheel.full_short_reason_catalog import (
    FULL_SHORT_LITERAL_REASON_CATEGORY_V1,
)
from novel_flywheel.full_short_execution import FullShortExecutionBoundaryError
from novel_flywheel.models import (
    CapabilityRoutesExhaustedError,
    ModelRoutesExhaustedError,
    ReasoningOnlyFinalArtifactUnavailableError,
    TransportInterruptedError,
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
    assert evidence.root.layer == FailureLayer.PROVIDER_ROUTE


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ConnectionError("socket included a private token"), "connection_error"),
        (
            TransportInterruptedError(
                {"raw": "must never persist"}, partial_text="private story",
            ),
            "transport_interrupted",
        ),
    ],
)
def test_transport_source_exceptions_have_safe_transport_ownership(
    error: BaseException, expected_code: str,
) -> None:
    evidence = build_durable_failure_evidence(
        error, boundary="workflow.recovery",
    )

    assert evidence.root.code == expected_code
    assert evidence.root.layer == FailureLayer.PROVIDER_TRANSPORT
    assert evidence.root.failure_class == FailureClass.TRANSPORT
    assert evidence.root.family == "provider.transport_interrupted"
    assert evidence.root.source_exception_class == type(error).__name__
    assert "private" not in json.dumps(evidence.model_dump(mode="json"))


def test_route_exhaustion_preserves_nested_transport_layers_and_order() -> None:
    connection = ConnectionError("private endpoint")
    interrupted = TransportInterruptedError(
        {"raw": "private provider body"}, partial_text="private story",
    )
    wrapped = ModelRoutesExhaustedError(
        connection, interrupted,
        route_errors=[
            ("primary", "one", connection),
            ("configured_fallback", "two", interrupted),
        ],
    )

    evidence = build_durable_failure_evidence(
        wrapped, boundary="workflow.recovery",
    )

    assert [child.code for child in evidence.root.children] == [
        "connection_error", "transport_interrupted",
    ]
    assert [child.layer for child in evidence.root.children] == [
        FailureLayer.PROVIDER_TRANSPORT, FailureLayer.PROVIDER_TRANSPORT,
    ]
    assert [child.source_exception_class for child in evidence.root.children] == [
        "ConnectionError", "TransportInterruptedError",
    ]


def test_nonempty_untyped_route_graph_is_conservatively_network_ambiguous() -> None:
    child = RuntimeError("opaque route failure")
    for wrapped in (
        ModelRoutesExhaustedError(
            child, child, route_errors=[("provider", "model", child)],
        ),
        CapabilityRoutesExhaustedError([
            ("provider", "model", child),
        ]),
    ):
        evidence = build_durable_failure_evidence(
            wrapped, boundary="workflow.recovery",
        )
        assert evidence.root.dispatch_state.value == "network_ambiguous"

    empty = build_durable_failure_evidence(
        CapabilityRoutesExhaustedError([]), boundary="workflow.recovery",
    )
    assert empty.root.dispatch_state.value == "not_reached"


@pytest.mark.parametrize(
    ("reason", "dispatch_state"),
    [
        ("HTTP_METHOD_NOT_AUTHORIZED", "ready_not_committed"),
        ("PROVIDER_REQUEST_CAP_EXHAUSTED", "ready_not_committed"),
        ("NO_RESPONSE_TO_COMPLETE", "network_ambiguous"),
        ("NO_CAPTURED_RESPONSE_TO_CLOSE", "network_ambiguous"),
        ("RESPONSE_NOT_RECEIVED", "network_ambiguous"),
        ("DISPATCH_ACCOUNTING_TYPE_INVALID", "not_reached"),
        ("RESPONSE_CAPTURE_POLICY_NOT_ENFORCED", "ready_not_committed"),
        ("PREDISPATCH_STAGE_CONTEXT_NOT_BOUND", "ready_not_committed"),
        ("PREDISPATCH_LEDGER_CREATED_AT_INVALID", "ready_not_committed"),
        ("PREDISPATCH_MAXIMUM_ELAPSED_EXPIRED", "ready_not_committed"),
        ("CAPTURE_ROUTE_NOT_BOUND", "response_captured"),
        ("CAPTURE_STAGE_CONTEXT_NOT_BOUND", "response_captured"),
        ("COMPLETION_LEDGER_CREATED_AT_INVALID", "not_reached"),
        ("COMPLETION_MAXIMUM_ELAPSED_EXPIRED", "not_reached"),
        ("EXPECTED_STAGE_CALL_COUNT_MISMATCH", "not_reached"),
        ("COMPLETION_CALL_CAP_EXCEEDED", "not_reached"),
        ("EXACT_REPLAY_CREATED_PHYSICAL_DISPATCH", "not_reached"),
    ],
)
def test_literal_reason_semantics_do_not_invent_external_progress(
    reason: str, dispatch_state: str,
) -> None:
    evidence = build_durable_failure_evidence(
        FullShortExecutionBoundaryError(reason),
        boundary="full_short.execution",
    )
    assert evidence.root.dispatch_state.value == dispatch_state


def test_reasoning_only_final_artifact_is_owned_by_final_artifact_layer() -> None:
    error = ReasoningOnlyFinalArtifactUnavailableError(receipt={
        "provider_body": "private reasoning",
    })

    evidence = build_durable_failure_evidence(
        error, boundary="workflow.recovery",
    )

    assert evidence.root.code == "reasoning_only_final_artifact_unavailable"
    assert evidence.root.layer == FailureLayer.PROVIDER_FINAL_ARTIFACT
    assert evidence.root.failure_class == FailureClass.OUTPUT_TRUNCATION
    assert evidence.root.family == (
        "provider.reasoning_only_final_artifact_unavailable"
    )
    assert "private reasoning" not in json.dumps(evidence.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("reason_code", "layer", "family", "failure_class"),
    [
        (
            "CREDENTIAL_ABSENT", FailureLayer.PROVIDER_CREDENTIAL,
            "provider.credential_absent", FailureClass.CREDENTIAL,
        ),
        (
            "PROVIDER_ROUTE_CONFIG_MISSING", FailureLayer.PROVIDER_ROUTE,
            "provider.route_config_missing", FailureClass.CAPABILITY,
        ),
        (
            "REQUEST_BUILD_FAILED", FailureLayer.PROVIDER_REQUEST_BUILD,
            "provider.request_build_failed", FailureClass.SYNTAX_PROTOCOL,
        ),
    ],
)
def test_full_short_boundary_uses_closed_explicit_taxonomy_before_token_guessing(
    reason_code: str, layer: FailureLayer, family: str,
    failure_class: FailureClass,
) -> None:
    error = FullShortExecutionBoundaryError(reason_code)

    evidence = build_durable_failure_evidence(error, boundary="full_short")

    assert evidence.root.code == reason_code.casefold()
    assert evidence.root.layer == layer
    assert evidence.root.family == family
    assert evidence.root.failure_class == failure_class


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA" + "IOSFODNN7EXAMPLE",
        "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyz",
        "password=" + "correct-horse-battery-staple",
        "token=" + "sensitive-token-value",
        "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        + "c2lnbmF0dXJl",
        "0f4c9a8e73b21d65" + "c087fa349db821c0",
    ],
)
def test_safe_failure_graph_redacts_common_and_high_entropy_secrets(
    secret: str,
) -> None:
    error = RuntimeError("private")
    error.reliability_failure = SimpleNamespace(
        code=secret,
        failure_class=FailureClass.UNKNOWN,
        boundary=secret,
        retryable=False,
    )
    error.failure_family = secret
    error.recovery_action = secret

    first = build_durable_failure_evidence(error, boundary=secret)
    second = build_durable_failure_evidence(error, boundary=secret)
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)

    assert secret.casefold() not in serialized.casefold()
    assert first.failure_graph_sha256 == second.failure_graph_sha256


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


def test_full_short_literal_reason_catalog_is_ast_closed_and_mapped() -> None:
    root = Path(__file__).parents[1]
    sources = (
        root / "src" / "novel_flywheel" / "full_short_execution.py",
        root / "tools" / "canary" / "first_trustworthy_full_short_runner.py",
    )
    literal_reasons: set[str] = set()
    nodes = (
        node
        for source in sources
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
    )
    for node in nodes:
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for argument in node.exc.args[:1]:
                for child in ast.walk(argument):
                    if not (
                        isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                    ):
                        continue
                    match = re.match(
                        r"^([A-Z][A-Z0-9_]+)(?::|$)", child.value,
                    )
                    if match:
                        literal_reasons.add(match.group(1))
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "reason"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                literal_reasons.add(keyword.value.value)
        if not isinstance(node.func, ast.Name):
            continue
        argument = None
        if node.func.id == "_require" and len(node.args) > 1:
            argument = node.args[1]
        elif node.func.id == "FullShortExecutionBoundaryError" and node.args:
            argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            literal_reasons.add(argument.value)

    literal_reasons.update({
        "APPROVAL_NOT_FOUND_OR_CORRUPT",
        "LEDGER_NOT_FOUND_OR_CORRUPT",
        "NONCE_NOT_FOUND_OR_CORRUPT",
        "PERMISSION_NOT_FOUND_OR_CORRUPT",
    })

    assert literal_reasons == set(FULL_SHORT_LITERAL_REASON_CATEGORY_V1)
    assert all(
        not FullShortExecutionBoundaryError(code).reliability_failure.code.startswith(
            "unmapped_"
        )
        for code in literal_reasons
    )
    runner_tree = ast.parse(sources[1].read_text(encoding="utf-8"))
    native_machine_raises: list[int] = []
    for node in ast.walk(runner_tree):
        if not (
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id in {"RuntimeError", "ValueError"}
            and node.exc.args
        ):
            continue
        if any(
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and re.match(r"^[A-Z][A-Z0-9_]+(?::|$)", child.value)
            for child in ast.walk(node.exc.args[0])
        ):
            native_machine_raises.append(node.lineno)
    assert native_machine_raises == []
