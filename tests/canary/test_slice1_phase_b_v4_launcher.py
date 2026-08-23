from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import tools.canary.slice1_phase_b_single_dispatch as legacy
import tools.canary.slice1_phase_b_v4_single_dispatch as current


ROOT = Path(__file__).resolve().parents[2]
NORMALIZATION_SHA = (
    "6775a251e3fece7225e4ddb2a780e18ceccb5a3ccfff785004837a44dbc5805a"
)


def _binding():
    guard = current.transport_guard_contract(ROOT)
    accounting = current.attempt_accounting_contract(guard)
    binding = current.launcher_binding(
        ROOT,
        implementation_head="a" * 40,
        authority_normalization_sha256=NORMALIZATION_SHA,
        guard=guard,
        accounting=accounting,
    )
    return binding, guard, accounting


def _validate(value):
    _, guard, accounting = _binding()
    return current.validate_launcher_binding(
        value,
        repo_root=ROOT,
        implementation_head="a" * 40,
        authority_normalization_sha256=NORMALIZATION_SHA,
        guard=guard,
        accounting=accounting,
    )


def test_v4_profile_is_one_closed_packet() -> None:
    profile = current.packet_profile()
    assert profile["approval_scope"] == current.APPROVAL_SCOPE
    assert profile["cohort_id"] == current.COHORT_ID
    assert profile["materialization_relative_root"] == current.MATERIALIZATION_RELATIVE_ROOT
    assert profile["execution_relative_root"] == current.EXECUTION_RELATIVE_ROOT
    assert profile["arbitrary_scope_acceptance"] is False
    assert profile["arbitrary_cohort_acceptance"] is False
    assert profile["arbitrary_report_root_acceptance"] is False
    assert profile["unknown_packet_fails_closed"] is True
    assert current.ZERO_COUNTERS["real_provider_request_attempts"] == 0
    assert current.ZERO_COUNTERS["http_post_attempts"] == 0
    assert current.ZERO_COUNTERS["network_request_attempts"] == 0


def test_exact_launcher_binding_is_deterministic_and_accepted() -> None:
    first, _, _ = _binding()
    second, _, _ = _binding()
    assert first == second
    assert _validate(first) == first


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("approval_scope",), legacy.APPROVAL_SCOPE),
        (("approval_scope",), "ARBITRARY_SCOPE"),
        (("cohort_id",), legacy.COHORT_ID),
        (("cohort_id",), "unknown-cohort"),
        (("materialization_relative_root",), legacy.REPORT_RELATIVE_ROOT),
        (("execution_relative_root",), "docs/superpowers/reports/arbitrary"),
        (("authority_tuple_normalization_sha256",), "0" * 64),
        (("transport_guard_sha256",), "1" * 64),
        (("attempt_accounting_sha256",), "2" * 64),
        (("launcher_profile", "profile_id"), "UNKNOWN_PACKET"),
        (("entrypoint_source", "sha256"), "3" * 64),
        (("launcher_profile", "unknown_packet_fails_closed"), False),
    ],
)
def test_launcher_binding_negative_matrix(path, replacement) -> None:
    value, _, _ = _binding()
    changed = deepcopy(value)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(current.Slice1PhaseBV4LauncherError) as caught:
        _validate(changed)
    assert caught.value.reason_code == "launcher_binding_mismatch"


def test_missing_launcher_binding_rejected() -> None:
    with pytest.raises(current.Slice1PhaseBV4LauncherError):
        _validate({})


def test_historical_v2_profile_constants_are_unchanged() -> None:
    assert legacy.APPROVAL_SCOPE == (
        "SLICE1_PHASE_B_CURRENT_SKILL_SINGLE_DISPATCH_BASELINE_ONLY"
    )
    assert legacy.COHORT_ID == (
        "slice1-phase-b-current-skill-single-dispatch-v2-20260823t045907z-001"
    )
    assert legacy.REPORT_RELATIVE_ROOT.endswith(
        "short-plan-v2-slice1-phase-b-current-skill-materialization-v2"
    )


def test_transport_and_attempt_caps_remain_single_dispatch() -> None:
    _, guard, accounting = _binding()
    assert guard["max_http_post_attempts"] == 1
    assert guard["max_real_provider_request_attempts"] == 1
    assert guard["sdk_retries_disabled_for_phase_b"] is True
    assert guard["transport_request_retries_disabled_for_phase_b"] is True
    assert guard["workflow_model_retry_allowed"] is False
    assert guard["route_fallback_after_dispatch_allowed"] is False
    assert guard["application_second_dispatch_allowed"] is False
    assert guard["unknown_guard_state_fails_closed"] is True
    assert accounting["hard_max_model_logical_calls"] == 1
    assert accounting["hard_max_http_post_attempts"] == 1
    assert accounting["hard_max_real_provider_request_attempts"] == 1
    assert accounting["hard_max_network_request_attempts"] == 1


def test_committed_v4_packet_validate_only_when_present() -> None:
    packet_root = ROOT / current.MATERIALIZATION_RELATIVE_ROOT
    if not packet_root.exists():
        return
    assert current.validate_materialized_packet(ROOT, packet_root)["status"] == "exact"
