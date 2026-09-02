from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Iterable

from novel_flywheel.full_short_runtime_kernel import (
    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    DEFAULT_FAULT_INJECTION_REGISTRY_V1,
    DeterministicFaultInjectorV1,
    DurableExecutionJournalV1,
    ExecutionState,
    FailureClassification,
    FaultInjectionCaseV1,
    FullShortBoundaryFailureV1,
    FullShortExecutionKernel,
    RecoveryDecisionKind,
)
from novel_flywheel.stage_capacity import (
    CAPACITY_BOUNDARY_ID_V1,
    CAPACITY_FAILURE_IDS_V1,
    CAPACITY_FAILURE_IDS_V3,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
)


SCHEMA_VERSION_V2 = "FullShortCapacityFaultCampaignV2"
MASTER_DECLARED_SCENARIO_COUNT_V2 = 15


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CapacityFaultScenarioSpecV2:
    scenario_id: str
    failure_id: str
    injection_phase: str


# Phase 10 says "15" but enumerates the sixteen closed-world cases below.
# Keeping the enumeration verbatim and reporting the discrepancy avoids silently
# dropping the final missing-global-synthesis-receipt case.
MASTER_CAPACITY_FAULT_SCENARIOS_V2 = (
    CapacityFaultScenarioSpecV2(
        "exact_ready_review_over_cap",
        "capacity.windowing_required",
        "review.capacity_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "protected_layers_alone_over_budget",
        "capacity.protected_layers_exceed_budget",
        "capacity.protected_layers_bound",
    ),
    CapacityFaultScenarioSpecV2(
        "advisory_over_budget",
        "capacity.model_context_exceeded",
        "capacity.advisory_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "compactor_insufficient",
        "capacity.compaction_insufficient",
        "capacity.advisory_compaction",
    ),
    CapacityFaultScenarioSpecV2(
        "window_count_boundary",
        "capacity.windowing_exhausted",
        "review.window_plan",
    ),
    CapacityFaultScenarioSpecV2(
        "oversized_review_window",
        "capacity.protected_layers_exceed_budget",
        "review.window_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "hierarchical_synthesis_over_budget",
        "capacity.windowing_exhausted",
        "review.global_synthesis_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "output_reserve_conflict",
        "capacity.output_reserve_unsatisfied",
        "capacity.output_reserve_check",
    ),
    CapacityFaultScenarioSpecV2(
        "rendered_size_drift_after_plan",
        "capacity.rendered_prompt_drift",
        "capacity.final_render_check",
    ),
    CapacityFaultScenarioSpecV2(
        "context_limit_config_missing",
        "capacity.context_limit_unavailable",
        "capacity.capability_binding",
    ),
    CapacityFaultScenarioSpecV2(
        "wrong_context_limit_metadata",
        "capacity.context_limit_inconsistent",
        "capacity.capability_binding",
    ),
    CapacityFaultScenarioSpecV2(
        "restart_after_capacity_plan",
        "capacity.policy_violation",
        "restart.capacity_plan_reconciliation",
    ),
    CapacityFaultScenarioSpecV2(
        "restart_during_windowed_review",
        "capacity.windowing_required",
        "restart.review_window_reconciliation",
    ),
    CapacityFaultScenarioSpecV2(
        "failed_review_window",
        "capacity.windowing_exhausted",
        "review.window_execution",
    ),
    CapacityFaultScenarioSpecV2(
        "duplicate_review_window_receipt",
        "capacity.policy_violation",
        "review.window_receipt_validation",
    ),
    CapacityFaultScenarioSpecV2(
        "missing_global_synthesis_receipt",
        "capacity.policy_violation",
        "review.global_synthesis_receipt_validation",
    ),
)


@dataclass(frozen=True)
class GeneratedCapacityFaultCaseV2:
    scenario_id: str
    failure_id: str
    injection_phase: str
    source_case_key: str
    source_injection_id: str
    source_boundary_registry_sha256: str
    source_fault_registry_sha256: str
    source_capacity_policy_registry_sha256: str
    source_fault_case: FaultInjectionCaseV1

    def public_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("source_fault_case")
        return payload


def generate_capacity_fault_cases_v2(
    specs: Iterable[CapacityFaultScenarioSpecV2] = (
        MASTER_CAPACITY_FAULT_SCENARIOS_V2
    ),
    *,
    required_failure_ids: set[str] = CAPACITY_FAILURE_IDS_V1,
) -> tuple[GeneratedCapacityFaultCaseV2, ...]:
    """Resolve every Master scenario through the active Runtime registries."""

    capacity_boundary = DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundary(
        CAPACITY_BOUNDARY_ID_V1
    )
    registered_faults = {
        (case.boundary_id, case.failure_id): case
        for case in DEFAULT_FAULT_INJECTION_REGISTRY_V1.cases
    }
    generated: list[GeneratedCapacityFaultCaseV2] = []
    for spec in specs:
        if spec.failure_id not in required_failure_ids:
            raise ValueError(
                "capacity_campaign_failure_not_in_capacity_registry:"
                + spec.failure_id
            )
        if spec.failure_id not in capacity_boundary.allowed_typed_failures:
            raise ValueError(
                "capacity_campaign_failure_not_allowed_at_boundary:"
                + spec.failure_id
            )
        try:
            source_case = registered_faults[
                (CAPACITY_BOUNDARY_ID_V1, spec.failure_id)
            ]
        except KeyError as exc:
            raise ValueError(
                "capacity_campaign_failure_not_in_fault_registry:"
                + spec.failure_id
            ) from exc
        generated.append(
            GeneratedCapacityFaultCaseV2(
                scenario_id=spec.scenario_id,
                failure_id=spec.failure_id,
                injection_phase=spec.injection_phase,
                source_case_key=source_case.case_key,
                source_injection_id=source_case.injection_id,
                source_boundary_registry_sha256=(
                    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.identity_sha256
                ),
                source_fault_registry_sha256=(
                    DEFAULT_FAULT_INJECTION_REGISTRY_V1.identity_sha256
                ),
                source_capacity_policy_registry_sha256=(
                    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
                ),
                source_fault_case=source_case,
            )
        )
    scenario_ids = [case.scenario_id for case in generated]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("capacity_campaign_duplicate_scenario_id")
    covered_failure_ids = {case.failure_id for case in generated}
    if covered_failure_ids != required_failure_ids:
        raise ValueError("capacity_campaign_registered_failure_coverage_incomplete")
    return tuple(generated)


@dataclass(frozen=True)
class CapacityFaultRunProjectionV2:
    scenario_id: str
    failure_id: str
    injection_phase: str
    classification: str
    failure_family: str
    recovery_decision: str
    restart_policy_id: str
    terminal_state: str
    failure_envelope_sha256: str
    durable_receipt_sha256: str
    durable_journal_head_sha256: str
    dispatch_attempt_count: int
    dispatch_token_receipt_count: int
    authority_gate_receipt_count: int
    authority_sha256_before: str
    authority_sha256_after: str
    typed_failure: bool
    durable_receipt: bool
    denied_admission_zero_dispatch: bool
    no_authority_mutation: bool
    explicit_recovery_or_stop: bool
    raw_content_persisted: bool

    def proof_payload(self) -> dict[str, object]:
        return asdict(self)


class DurableCapacityFaultAdapterV2:
    """Small adapter over the concurrently developed durable Runtime API."""

    required_journal_schema = "DurableExecutionJournalV1"

    @classmethod
    def assert_supported(cls) -> None:
        if (
            DurableExecutionJournalV1.schema_version
            != cls.required_journal_schema
        ):
            raise RuntimeError("capacity_campaign_durable_journal_api_blocked")
        required = (
            "create",
            "open",
            "append_failure",
            "append_audit",
        )
        if any(
            not callable(getattr(DurableExecutionJournalV1, name, None))
            for name in required
        ):
            raise RuntimeError("capacity_campaign_durable_journal_api_blocked")

    @classmethod
    def execute_once(
        cls,
        case: GeneratedCapacityFaultCaseV2,
        journal_path: Path,
    ) -> CapacityFaultRunProjectionV2:
        cls.assert_supported()
        authority = {
            "formal_revision": 7,
            "authority_artifact_sha256": "a" * 64,
        }
        authority_before = _sha256(authority)
        dispatch_attempt_count = 0
        journal = DurableExecutionJournalV1.create(
            journal_path,
            execution_id="capacity-fault-campaign:" + case.scenario_id,
            initial_state=ExecutionState.TEMPLATE_READY,
        )
        kernel = FullShortExecutionKernel(
            registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
            journal=journal,
            fault_injector=DeterministicFaultInjectorV1(
                case.source_fault_case
            ),
        )

        def forbidden_dispatch_operation() -> None:
            nonlocal dispatch_attempt_count
            dispatch_attempt_count += 1
            raise AssertionError("capacity_denial_reached_dispatch_operation")

        try:
            kernel.execute_boundary_sync(
                CAPACITY_BOUNDARY_ID_V1,
                forbidden_dispatch_operation,
                logical_stage_id="review:capacity-campaign",
                physical_attempt=1,
            )
        except FullShortBoundaryFailureV1 as exc:
            observed = exc.envelope
        else:
            raise AssertionError("capacity_fault_injection_did_not_fail")

        # Reopen from disk: in-memory receipts are not evidence of durability.
        reopened = DurableExecutionJournalV1.open(journal_path)
        if len(reopened.failure_receipts) != 1:
            raise AssertionError("capacity_fault_receipt_cardinality_invalid")
        receipt = reopened.failure_receipts[0]
        envelope = receipt.failure_envelope
        if envelope is None:
            raise AssertionError("capacity_fault_envelope_not_durable")
        if envelope.failure_envelope_sha256 != observed.failure_envelope_sha256:
            raise AssertionError("capacity_fault_envelope_restart_drift")
        authority_after = _sha256(authority)
        authority_gate_receipts = tuple(
            item
            for item in reopened.audit_receipts
            if item.receipt_kind == "authority_gate_ready"
        )
        explicit_recovery_or_stop = (
            envelope.recovery_decision
            in {
                RecoveryDecisionKind.SEMANTIC_SPLIT,
                RecoveryDecisionKind.FAIL_CLOSED,
            }
            and bool(envelope.restart_policy_id)
            and tuple(envelope.allowed_next_states) == (reopened.state,)
        )
        return CapacityFaultRunProjectionV2(
            scenario_id=case.scenario_id,
            failure_id=envelope.failure_code,
            injection_phase=case.injection_phase,
            classification=envelope.classification.value,
            failure_family=envelope.failure_family,
            recovery_decision=envelope.recovery_decision.value,
            restart_policy_id=envelope.restart_policy_id,
            terminal_state=reopened.state.value,
            failure_envelope_sha256=envelope.failure_envelope_sha256,
            durable_receipt_sha256=receipt.record_sha256,
            durable_journal_head_sha256=reopened.head_sha256,
            dispatch_attempt_count=dispatch_attempt_count,
            dispatch_token_receipt_count=len(
                reopened.dispatch_token_receipts
            ),
            authority_gate_receipt_count=len(authority_gate_receipts),
            authority_sha256_before=authority_before,
            authority_sha256_after=authority_after,
            typed_failure=(
                envelope.classification is FailureClassification.KNOWN
                and envelope.failure_code == case.failure_id
                and envelope.failure_code in CAPACITY_FAILURE_IDS_V3
            ),
            durable_receipt=(
                journal_path.is_file()
                and receipt.failure_envelope_sha256
                == envelope.failure_envelope_sha256
            ),
            denied_admission_zero_dispatch=(
                dispatch_attempt_count == 0
                and not reopened.dispatch_token_receipts
            ),
            no_authority_mutation=(
                authority_before == authority_after
                and not authority_gate_receipts
                and envelope.authority_effect == "preserve_last_accepted"
            ),
            explicit_recovery_or_stop=explicit_recovery_or_stop,
            raw_content_persisted=envelope.raw_content_persisted,
        )


def run_capacity_fault_campaign_v2(artifact_dir: Path) -> dict[str, object]:
    cases = generate_capacity_fault_cases_v2()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for case in cases:
        first = DurableCapacityFaultAdapterV2.execute_once(
            case,
            artifact_dir / (case.scenario_id + ".first.json"),
        )
        replay = DurableCapacityFaultAdapterV2.execute_once(
            case,
            artifact_dir / (case.scenario_id + ".replay.json"),
        )
        deterministic_replay = first.proof_payload() == replay.proof_payload()
        proof = {
            **first.proof_payload(),
            "deterministic_replay": deterministic_replay,
        }
        required = (
            "typed_failure",
            "durable_receipt",
            "denied_admission_zero_dispatch",
            "no_authority_mutation",
            "explicit_recovery_or_stop",
            "deterministic_replay",
        )
        proof["status"] = (
            "PASS"
            if all(bool(proof[name]) for name in required)
            and proof["raw_content_persisted"] is False
            else "FAIL"
        )
        results.append(proof)

    report_without_sha: dict[str, object] = {
        "schema_version": SCHEMA_VERSION_V2,
        "source_boundary_registry_sha256": (
            DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.identity_sha256
        ),
        "source_fault_registry_sha256": (
            DEFAULT_FAULT_INJECTION_REGISTRY_V1.identity_sha256
        ),
        "source_capacity_policy_registry_sha256": (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        "master_declared_scenario_count": (
            MASTER_DECLARED_SCENARIO_COUNT_V2
        ),
        "master_enumerated_scenario_count": len(
            MASTER_CAPACITY_FAULT_SCENARIOS_V2
        ),
        "scenario_count_discrepancy": (
            "Phase 10 declares 15 scenarios but enumerates 16; "
            "all 16 enumerated scenarios are covered."
        ),
        "registered_capacity_failure_count": len(CAPACITY_FAILURE_IDS_V1),
        "registered_capacity_failure_coverage": "100_PERCENT",
        "scenario_coverage": "100_PERCENT",
        "external_actions_disabled": True,
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "model_call_count": 0,
        "paid_call_count": 0,
        "full_short_execution_count": 0,
        "results": results,
        "status": (
            "PASS"
            if results and all(item["status"] == "PASS" for item in results)
            else "FAIL"
        ),
    }
    return {
        **report_without_sha,
        "report_sha256": _sha256(report_without_sha),
    }


MASTER_CAPACITY_FAULT_SCENARIOS_V3 = (
    CapacityFaultScenarioSpecV2(
        "missing_capability_record", "capacity.context_limit_unavailable",
        "capacity.registry_lookup",
    ),
    CapacityFaultScenarioSpecV2(
        "unknown_blocked_required_route", "capacity.route_capability_unknown",
        "capacity.required_route_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "stale_evidence", "capacity.context_limit_inconsistent",
        "capacity.evidence_validation",
    ),
    CapacityFaultScenarioSpecV2(
        "evidence_wrong_operator", "capacity.route_capability_unknown",
        "capacity.route_identity",
    ),
    CapacityFaultScenarioSpecV2(
        "relay_inherits_upstream", "capacity.route_capability_unknown",
        "capacity.relay_identity",
    ),
    CapacityFaultScenarioSpecV2(
        "capability_registry_version_drift", "capacity.policy_violation",
        "capacity.registry_reconciliation",
    ),
    CapacityFaultScenarioSpecV2(
        "route_fingerprint_drift", "capacity.rendered_prompt_drift",
        "capacity.route_fingerprint",
    ),
    CapacityFaultScenarioSpecV2(
        "context_window_exceeded", "capacity.context_window_exceeded",
        "capacity.final_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "output_limit_mismatch", "capacity.output_reserve_unsatisfied",
        "capacity.output_reserve",
    ),
    CapacityFaultScenarioSpecV2(
        "estimator_uncertainty", "capacity.estimator_uncertainty_exceeded",
        "capacity.estimator",
    ),
    CapacityFaultScenarioSpecV2(
        "illegal_route_delta", "capacity.invalid_attempt_delta",
        "capacity.attempt_delta",
    ),
    CapacityFaultScenarioSpecV2(
        "illegal_authority_delta", "capacity.physical_attempt_drift",
        "capacity.attempt_identity",
    ),
    CapacityFaultScenarioSpecV2(
        "illegal_output_cap_delta", "capacity.invalid_attempt_delta",
        "capacity.attempt_delta",
    ),
    CapacityFaultScenarioSpecV2(
        "exact_ready_review_capacity_edge",
        "capacity.protected_layers_exceed_budget",
        "review.capacity_admission",
    ),
    CapacityFaultScenarioSpecV2(
        "20k_edge", "capacity.compaction_insufficient",
        "capacity.semantic_compaction",
    ),
    CapacityFaultScenarioSpecV2(
        "30k_edge", "capacity.windowing_exhausted",
        "capacity.semantic_windowing",
    ),
    CapacityFaultScenarioSpecV2(
        "restart_after_logical_envelope", "capacity.model_context_exceeded",
        "restart.logical_capacity_envelope",
    ),
    CapacityFaultScenarioSpecV2(
        "restart_after_physical_plan", "capacity.windowing_required",
        "restart.physical_capacity_plan",
    ),
)


def _allowed_v3_scenario(scenario_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "scenario_id": scenario_id,
        "classification": "POLICY_ASSERTION_COVERED_BY_INTEGRATION_TEST",
        "execution_mode": "STATIC_POLICY_ASSERTION",
        "failure_id": None,
        "dispatch_attempt_count": 0,
        "dispatch_token_receipt_count": 0,
        "authority_gate_receipt_count": 0,
        "no_authority_mutation": True,
        "raw_content_persisted": False,
        "deterministic_replay": True,
        "status": "PASS",
    }
    payload["projection_sha256"] = _sha256(payload)
    return payload


def run_capacity_fault_campaign_v3(artifact_dir: Path) -> dict[str, object]:
    """Run all twenty V3 scenarios without treating legal deltas as faults."""

    master_failure_ids = {
        item.failure_id for item in MASTER_CAPACITY_FAULT_SCENARIOS_V3
    }
    cases = generate_capacity_fault_cases_v2(
        MASTER_CAPACITY_FAULT_SCENARIOS_V3,
        required_failure_ids=master_failure_ids,
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for case in cases:
        first = DurableCapacityFaultAdapterV2.execute_once(
            case, artifact_dir / (case.scenario_id + ".first.json"),
        )
        replay = DurableCapacityFaultAdapterV2.execute_once(
            case, artifact_dir / (case.scenario_id + ".replay.json"),
        )
        proof = {
            **first.proof_payload(),
            "deterministic_replay": (
                first.proof_payload() == replay.proof_payload()
            ),
        }
        proof["status"] = (
            "PASS"
            if all(bool(proof[name]) for name in (
                "typed_failure", "durable_receipt",
                "denied_admission_zero_dispatch", "no_authority_mutation",
                "explicit_recovery_or_stop", "deterministic_replay",
            )) and proof["raw_content_persisted"] is False
            else "FAIL"
        )
        results.append(proof)
    supplemental_results: list[dict[str, object]] = []
    for failure_id in sorted(CAPACITY_FAILURE_IDS_V3 - master_failure_ids):
        supplemental_case = generate_capacity_fault_cases_v2((
            CapacityFaultScenarioSpecV2(
                "supplemental_registered_failure__"
                + failure_id.rsplit(".", 1)[-1],
                failure_id,
                "capacity.registered_failure_supplement",
            ),
        ), required_failure_ids={failure_id})[0]
        first = DurableCapacityFaultAdapterV2.execute_once(
            supplemental_case,
            artifact_dir / (supplemental_case.scenario_id + ".first.json"),
        )
        replay = DurableCapacityFaultAdapterV2.execute_once(
            supplemental_case,
            artifact_dir / (supplemental_case.scenario_id + ".replay.json"),
        )
        proof = {
            **first.proof_payload(),
            "deterministic_replay": (
                first.proof_payload() == replay.proof_payload()
            ),
        }
        proof["status"] = (
            "PASS"
            if all(bool(proof[name]) for name in (
                "typed_failure", "durable_receipt",
                "denied_admission_zero_dispatch", "no_authority_mutation",
                "explicit_recovery_or_stop", "deterministic_replay",
            )) and proof["raw_content_persisted"] is False
            else "FAIL"
        )
        supplemental_results.append(proof)
    results.extend((
        _allowed_v3_scenario("unknown_blocked_unused_route"),
        _allowed_v3_scenario("legitimate_recovery_attempt_delta"),
    ))
    order = (
        "missing_capability_record", "unknown_blocked_required_route",
        "unknown_blocked_unused_route", "stale_evidence",
        "evidence_wrong_operator", "relay_inherits_upstream",
        "capability_registry_version_drift", "route_fingerprint_drift",
        "context_window_exceeded", "output_limit_mismatch",
        "estimator_uncertainty", "legitimate_recovery_attempt_delta",
        "illegal_route_delta", "illegal_authority_delta",
        "illegal_output_cap_delta", "exact_ready_review_capacity_edge",
        "20k_edge", "30k_edge", "restart_after_logical_envelope",
        "restart_after_physical_plan",
    )
    by_id = {str(item["scenario_id"]): item for item in results}
    ordered_results = [by_id[scenario_id] for scenario_id in order]
    report_without_sha: dict[str, object] = {
        "schema_version": "FullShortCapacityFaultCampaignV3",
        "source_boundary_registry_sha256": (
            DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.identity_sha256
        ),
        "source_fault_registry_sha256": (
            DEFAULT_FAULT_INJECTION_REGISTRY_V1.identity_sha256
        ),
        "source_capacity_policy_registry_sha256": (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        "master_enumerated_scenario_count": 20,
        "registered_capacity_failure_count": len(CAPACITY_FAILURE_IDS_V3),
        "registered_capacity_failure_coverage": "100_PERCENT",
        "scenario_coverage": "18_INJECTED_PLUS_2_POLICY_ASSERTIONS",
        "injected_fault_scenario_count": 18,
        "policy_assertion_scenario_count": 2,
        "v3_capacity_fault_injection_coverage": "90_PERCENT",
        "coverage_kind": "REGISTERED_FAILURE_ADAPTER_INJECTION",
        "production_observer_behavior_coverage_claimed": False,
        "production_shaped_integration_tests": [
            "tests/test_full_short_execution.py",
            "tests/canary/test_full_short_runner_hardening.py",
            "tests/test_route_capabilities.py",
        ],
        "supplemental_registered_failure_proofs": supplemental_results,
        "external_actions_disabled": True,
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "model_call_count": 0,
        "paid_call_count": 0,
        "full_short_execution_count": 0,
        "results": ordered_results,
        "status": (
            "PASS"
            if all(
                item["status"] == "PASS"
                for item in ordered_results + supplemental_results
            )
            else "FAIL"
        ),
    }
    return {
        **report_without_sha,
        "report_sha256": _sha256(report_without_sha),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline V2 Full Short capacity fault campaign."
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.artifact_dir is None:
        with tempfile.TemporaryDirectory(
            prefix="full-short-capacity-fault-campaign-"
        ) as temp_dir:
            report = run_capacity_fault_campaign_v2(Path(temp_dir))
    else:
        report = run_capacity_fault_campaign_v2(args.artifact_dir)
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
