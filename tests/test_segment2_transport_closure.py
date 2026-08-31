from pathlib import Path

import pytest

from tools.diagnostics.materialize_segment2_transport_closure import (
    _production_matrix_receipt,
    _validate_adapter_replay,
    _validate_common_evidence_binding,
    _validated_failure_scenarios,
)


def _write_junit(path: Path, *, failed: bool = False) -> None:
    failure = '<failure message="failed" />' if failed else ""
    path.write_text(
        "<testsuite tests=\"3\">"
        '<testcase name="matrix[13000]">' + failure + "</testcase>"
        '<testcase name="matrix[20000]" />'
        '<testcase name="matrix[30000]" />'
        "</testsuite>",
        encoding="utf-8",
    )


def test_production_matrix_receipt_requires_all_three_passing_lengths(
    tmp_path: Path,
) -> None:
    junit = tmp_path / "matrix.xml"
    _write_junit(junit)

    receipt = _production_matrix_receipt(junit)

    assert receipt["13000"] == "PASS"
    assert receipt["20000"] == "PASS"
    assert receipt["30000"] == "PASS"
    assert len(receipt["junit_sha256"]) == 64


def test_production_matrix_receipt_rejects_a_failed_length(tmp_path: Path) -> None:
    junit = tmp_path / "matrix.xml"
    _write_junit(junit, failed=True)

    with pytest.raises(AssertionError):
        _production_matrix_receipt(junit)


def test_adapter_replay_requires_two_local_projections_and_one_call_plan() -> None:
    receipt = {
        "pass": True,
        "provider_request_count": 70,
        "completed_stage_count": 70,
        "adapter_failure_after_exact_capture_injected": True,
        "adapter_projection_call_count_at_injection": 2,
        "adapter_failure_recovered_by_exact_local_replay": True,
        "replay_call_count": 70,
        "final_artifact_sha256": "a" * 64,
        "replay_final_artifact_sha256": "a" * 64,
    }
    _validate_adapter_replay(receipt)
    receipt["adapter_projection_call_count_at_injection"] = 1
    with pytest.raises(AssertionError):
        _validate_adapter_replay(receipt)


def test_failure_matrix_requires_exact_b_and_c_durable_states() -> None:
    def scenario(name, state, capture_count, bytes_present):
        return {
            "scenario": name,
            "status": "PASS_EXPECTED_FAIL_CLOSED",
            "physical_dispatch_count": 1,
            "network_redispatch_count": 0,
            "attempt_state": state,
            "ledger_state": "RECONCILIATION_REQUIRED_NO_REDISPATCH",
            "provider_protocol_capture_count": capture_count,
            "response_bytes_present": bytes_present,
            "authority_sha256_unchanged": True,
            "real_network_calls": 0,
            "paid_calls": 0,
        }

    receipt = {
        "status": "PASS",
        "pass": True,
        "real_external_action_counters_all_zero": True,
        "scenarios": [
            scenario(
                "provider_unavailable_complete_response",
                "HTTP_RESPONSE_FAILED_CLOSED", 1, True,
            ),
            scenario(
                "ambiguous_external_completion",
                "OUTCOME_UNKNOWN_FAIL_CLOSED", 0, False,
            ),
        ],
    }
    scenarios = _validated_failure_scenarios(receipt)
    assert len(scenarios) == 2
    receipt["scenarios"][1]["network_redispatch_count"] = 1
    with pytest.raises(AssertionError):
        _validated_failure_scenarios(receipt)


def test_production_evidence_must_share_head_plan_and_transport_policy() -> None:
    binding = {
        "source_head": "a" * 40,
        "logical_stage_plan_sha256": "b" * 64,
        "transport_recovery_policy_sha256": "c" * 64,
    }
    _validate_common_evidence_binding(
        binding, dict(binding),
        failure_scenarios={"b": dict(binding), "c": dict(binding)},
    )
    drift = {**binding, "source_head": "d" * 40}
    with pytest.raises(AssertionError):
        _validate_common_evidence_binding(
            binding, drift,
            failure_scenarios={"b": dict(binding), "c": dict(binding)},
        )
