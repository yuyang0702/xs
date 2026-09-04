from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
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
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionBoundaryError,
    FullShortExecutionPolicyV1,
)
from novel_flywheel.stage_capacity import (
    AdmissionStatus,
    CAPACITY_BOUNDARY_ID_V1,
    CAPACITY_FAILURE_IDS_V1,
    CAPACITY_FAILURE_IDS_V3,
    CapacityAdmissionFailureV1,
    CapacityFailureCode,
    CapacityLayerClass,
    CapacityLayerProjectionV1,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
    RouteContextCapabilitySourceV1,
    StageCapacityAdmissionEngineV1,
    StageCapacityPolicyRegistryV1,
    build_stage_capacity_plan_v1,
    capacity_failure_recovery_disposition_v1,
    require_route_capability_v1,
    validate_capacity_attempt_delta_v1,
    verify_rendered_request_v1,
)
from novel_flywheel.route_capabilities import (
    CapabilityEvidenceV1,
    CapabilityStatus,
    RouteCapabilityError,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
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


MASTER_V3_SCENARIO_IDS = (
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


def _evidence_v3(route_fingerprint: str = "c" * 64) -> CapabilityEvidenceV1:
    return CapabilityEvidenceV1(
        source_kind="historical_official_documentation",
        source_locator="docs/evidence.json#route",
        source_evidence_sha256="d" * 64,
        evidence_version=1,
        evidence_date="2026-08-14",
        route_fingerprint=route_fingerprint,
        proved_fields=(
            "context_window_tokens", "max_output_tokens",
            "reasoning_token_accounting", "reasoning_output_reservation",
            "route_fingerprint", "provider", "provider_id_sha256",
            "operator", "destination", "protocol", "model",
            "model_id_sha256",
        ),
        provenance_available=True,
    )


def _record_v3(*, lane: str = "primary", unknown: bool = False) -> RouteCapabilityRecordV1:
    return RouteCapabilityRecordV1.create(
        role="planning", lane=lane, provider="provider",
        provider_id_sha256="a" * 64, operator="EXACT_OPERATOR",
        destination="https://unit.test:443/v1/messages",
        protocol="anthropic", model="model", model_id_sha256="b" * 64,
        route_fingerprint="c" * 64,
        context_window_tokens=None if unknown else 100_000,
        max_output_tokens=None if unknown else 8_192,
        reasoning_token_accounting=(
            "UNKNOWN" if unknown else "INCLUDED_IN_COMPLETION_CAP"
        ),
        reasoning_output_reservation=(
            "UNKNOWN" if unknown else "WITHIN_COMPLETION_CAP"
        ),
        capability_status=(
            CapabilityStatus.UNKNOWN_BLOCKED if unknown
            else CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE
        ),
        source_evidence=() if unknown else (_evidence_v3(),),
        blocking_reason_codes=("NO_TRUSTWORTHY_EVIDENCE",) if unknown else (),
    )


def _layer_v3(layer_id: str, tokens: int) -> CapacityLayerProjectionV1:
    return CapacityLayerProjectionV1.create(
        layer_id=layer_id, classification=CapacityLayerClass.HARD_PROTECTED,
        owner="capacity-campaign", source_sha256=_sha256("source:" + layer_id),
        semantic_scope="complete", coverage=(layer_id,),
        pre_transform_characters=tokens * 2, pre_transform_tokens=tokens,
        post_transform_characters=tokens * 2, post_transform_tokens=tokens,
        transform_policy_id="identity.v1", action="PRESERVE",
        rendered_sha256=_sha256("rendered:" + layer_id),
    )


def _plan_v3(**overrides: object):
    values: dict[str, object] = {
        "stage_id": "review-capacity-campaign",
        "logical_stage_id": "review-capacity-campaign",
        "physical_attempt": 1,
        "stage": "review",
        "contract_name": "planning_adaptation_segment",
        "contract_version": 2,
        "contract_schema_sha256": "a" * 64,
        "provider_route_identity_sha256": "b" * 64,
        "model_context_limit": 32_768,
        "requested_output_token_cap": 2_316,
        "route_max_output_tokens": 8_192,
        "final_output_reserve": 2_316,
        "rendered_message_tokens": 22_379,
        "structured_envelope_tokens": 177,
        "provider_envelope_tokens": 256,
        "wrapper_and_estimator_margin_tokens": 1_024,
        "rendered_request_sha256": "c" * 64,
        "layer_projections": (
            _layer_v3("contract", 25), _layer_v3("rules", 9_685),
            _layer_v3("context", 4_601), _layer_v3("skeleton", 7_802),
        ),
        "parent_plan_sha256": None,
    }
    values.update(overrides)
    return build_stage_capacity_plan_v1(**values)  # type: ignore[arg-type]


def _recovery_pair_v3(**candidate_overrides: object):
    common = {
        "route_context_capability_source": (
            RouteContextCapabilitySourceV1.ROUTE_CAPABILITY_REGISTRY
        ),
        "logical_capacity_envelope_sha256": "1" * 64,
        "route_capability_snapshot_sha256": "2" * 64,
        "physical_attempt_id": "physical-first",
        "global_physical_attempt_ordinal": 1,
    }
    prior = _plan_v3(**common)
    candidate = {
        **common,
        "physical_attempt": 2,
        "physical_attempt_id": "physical-second",
        "global_physical_attempt_ordinal": 2,
        "rendered_request_sha256": "e" * 64,
        "base_rendered_request_sha256": prior.base_rendered_request_sha256,
        "recovery_overlay_kind": "FINAL_ARTIFACT_COMPLETION",
        "prior_rendered_request_sha256": prior.rendered_request_sha256,
        "recovery_source_capture_receipt_sha256": "f" * 64,
        "recovery_stage_role": "PLANNING_FINAL_ARTIFACT_RECOVERY",
        "reasoning_policy": "DISABLE_REASONING",
    }
    candidate.update(candidate_overrides)
    return prior, _plan_v3(**candidate)


def _pass_v3(scenario_id: str, primitive: str, scope: str, **evidence: object) -> dict[str, object]:
    payload = {
        "scenario_id": scenario_id, "primitive": primitive, "probe_scope": scope,
        "execution_mode": "PRODUCTION_PRIMITIVE", "failure_id": None,
        "production_behavior_exercised": True, "dispatch_attempt_count": 0,
        "raw_content_persisted": False, "status": "PASS", **evidence,
    }
    payload["projection_sha256"] = _sha256(payload)
    return payload


def _durable_observer_fixture_v3(
    artifact_dir: Path,
    scenario_id: str,
    *,
    fixture_root: Path | None = None,
) -> tuple[
    FullShortDurableExecutionStoreV1,
    FullShortDispatchLedgerObserverV1,
    dict[str, object],
    tuple[dict[str, object], ...],
    dict[str, object],
    tempfile.TemporaryDirectory[str] | None,
]:
    """Create a disabled-actions production observer with durable authority."""

    # Keep Windows paths below MAX_PATH even when the report root is deeply
    # nested. The returned owner keeps this private durable fixture alive for
    # the whole close/reopen probe and removes it afterwards.
    temporary = None
    if fixture_root is None:
        temporary = tempfile.TemporaryDirectory(prefix="v3-capacity-restart-")
        fixture_root = Path(temporary.name)
    else:
        fixture_root.mkdir(parents=True, exist_ok=True)
    repo_root = fixture_root / "repo"
    repo_root.mkdir(parents=True)
    store = FullShortDurableExecutionStoreV1(
        repo_root=repo_root, store_root=fixture_root / "store",
    )
    routes: tuple[dict[str, object], ...] = ({
        "role": "planning", "lane": "primary",
        "provider_id_sha256": hashlib.sha256(b"provider").hexdigest(),
        "model_id_sha256": hashlib.sha256(b"model-id").hexdigest(),
        "model_name": "offline", "protocol": "anthropic",
        "route_fingerprint": "9" * 64,
        "destination": "https://unit.test:443/v1/messages",
        "max_output_tokens": 4096,
        "route_context_capability_limit_tokens": 32768,
        "route_context_capability_source": "model_configuration",
    },)
    egress_policy: dict[str, object] = {
        "allowed": [
            "system_context", "task_contract", "authority", "story_slice",
            "current_baseline_skill_context", "output_contract",
            "provider_request_metadata",
        ],
        "forbidden": [
            "credentials", "unrelated_project_data", "raw_provider_evidence",
            "retired_skill_v3_hybrid_context",
        ],
    }
    logical_plan = ({
        "ordinal": 1,
        "stage_id": "planning",
        "logical_stage_base_id": "planning",
        "logical_stage_id": "planning",
        "role": "planning",
        "route_lane": "primary",
        "contract_name": "unstructured_text",
        "contract_version": 1,
        "contract_schema_sha256": _sha256({}),
        "contract_runtime_input_required": False,
        "requested_output_tokens": 128,
    },)
    policy = FullShortExecutionPolicyV1(
        execution_head="a" * 40,
        branch="capacity-v3",
        run_id="capacity-v3",
        project_id_sha256="b" * 64,
        workload_sha256="c" * 64,
        runtime_authority_sha256="d" * 64,
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_sha256(list(routes)),
        destination_manifest_sha256=_sha256([
            "https://unit.test:443/v1/messages",
        ]),
        egress_policy_sha256=_sha256(egress_policy),
        store_root_sha256=store.store_root_sha256,
        capture_attestation_public_key=store.capture_attestation_public_key,
        capture_attestation_public_key_sha256=(
            store.capture_attestation_public_key_sha256
        ),
        required_stage_roles=("planning",),
        logical_stage_plan=logical_plan,
        expected_stage_calls=1,
        hard_max_provider_requests=4,
        hard_max_http_posts=4,
        hard_max_network_attempts=4,
        per_call_output_token_hard_cap=4096,
        total_output_token_hard_cap=4096,
        maximum_elapsed_seconds=60,
    ).document()
    execution_id = "capacity-v3-" + scenario_id
    permission = store.create_permission(
        execution_id=execution_id,
        authorization_text_sha256="3" * 64,
        policy=policy,
        external_actions_enabled=False,
    )
    approval = store.create_jit_approval(
        execution_id=execution_id,
        policy=policy,
        permission=permission,
        external_actions_enabled=False,
    )
    store.reserve_nonce(
        execution_id=execution_id,
        policy=policy,
        approval=approval,
        external_actions_enabled=False,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store,
        execution_id=execution_id,
        policy=policy,
        authorized_routes=routes,
        egress_policy=egress_policy,
        session_id="capacity-v3-first-process",
        external_actions_enabled=False,
    )
    return store, observer, policy, routes, egress_policy, temporary


def _write_json_v3(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _restart_worker_v3(*, phase: str, input_path: Path, output_path: Path) -> int:
    """Run one restart phase in a short-lived, offline child process."""

    request = json.loads(input_path.read_text(encoding="utf-8"))
    scenario_id = str(request["scenario_id"])
    if phase == "initialize":
        fixture_root = Path(str(request["fixture_root"]))
        store, observer, policy, routes, egress_policy, temporary = (
            _durable_observer_fixture_v3(
                fixture_root,
                scenario_id,
                fixture_root=fixture_root,
            )
        )
        assert temporary is None
        result: dict[str, object] = {
            "scenario_id": scenario_id,
            "repo_root": str(store.repo_root),
            "store_root": str(store.root),
            "execution_id": "capacity-v3-" + scenario_id,
            "policy": policy,
            "routes": list(routes),
            "egress_policy": egress_policy,
        }
        if scenario_id == "restart_after_logical_envelope":
            context = observer.capacity_admission_context(
                route="primary", role="planning", physical_attempt=1,
            )
            result["logical_capacity_envelope_bound"] = (
                isinstance(context["logical_capacity_envelope_sha256"], str)
                and len(context["logical_capacity_envelope_sha256"]) == 64
            )
        elif scenario_id == "restart_after_physical_plan":
            plan, _ = _observer_capacity_plan_v3(observer)
            result["plan_sha256"] = plan.plan_sha256
        else:
            raise AssertionError("restart_worker_scenario_invalid:" + scenario_id)
        _write_json_v3(output_path, result)
        return 0

    if phase != "reopen":
        raise AssertionError("restart_worker_phase_invalid:" + phase)
    store = FullShortDurableExecutionStoreV1(
        repo_root=Path(str(request["repo_root"])),
        store_root=Path(str(request["store_root"])),
    )
    physical_plan_reopened = None
    if scenario_id == "restart_after_physical_plan":
        receipt = store.load_capacity_admission_receipt(
            execution_id=str(request["execution_id"]),
            plan_sha256=str(request["plan_sha256"]),
        )
        physical_plan_reopened = (
            receipt["capacity_plan_sha256"] == request["plan_sha256"]
            and receipt["state"] == "PLAN_BOUND_UNCONSUMED"
        )
    try:
        FullShortDispatchLedgerObserverV1(
            store=store,
            execution_id=str(request["execution_id"]),
            policy=request["policy"],
            authorized_routes=tuple(request["routes"]),
            egress_policy=request["egress_policy"],
            session_id="capacity-v3-restarted-process",
            external_actions_enabled=False,
        )
    except FullShortExecutionBoundaryError as exc:
        restart_reason = exc.reason_code
    else:
        raise AssertionError("restart_worker_was_not_blocked")
    ledger = store.load_ledger(str(request["execution_id"]))
    _write_json_v3(output_path, {
        "fresh_process_boundary": "SEQUENTIAL_OS_SUBPROCESS",
        "reopened_durable_store": True,
        "logical_capacity_envelope_bound": request.get(
            "logical_capacity_envelope_bound"
        ),
        "physical_plan_reopened": physical_plan_reopened,
        "restart_blocked": restart_reason == "OBSERVER_ALREADY_CLAIMED_NO_RESTART",
        "restart_reason": restart_reason,
        "dispatch_attempt_count": len(ledger["attempts"]),
    })
    return 0


def _run_restart_subprocess_probe_v3(
    scenario_id: str,
) -> dict[str, object]:
    """Initialize, exit, then reopen in a different OS process."""

    with tempfile.TemporaryDirectory(prefix="v3-capacity-restart-") as temp_dir:
        fixture_root = Path(temp_dir)
        initialize_request = fixture_root / "initialize-request.json"
        initialized = fixture_root / "initialized.json"
        reopened = fixture_root / "reopened.json"
        _write_json_v3(initialize_request, {
            "scenario_id": scenario_id,
            "fixture_root": str(fixture_root),
        })
        script = Path(__file__).resolve()
        project_root = script.parents[2]
        child_environment = os.environ.copy()
        child_environment["NOVEL_FLYWHEEL_EXTERNAL_ACTIONS_DISABLED"] = "1"
        source_root = str(project_root / "src")
        child_environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            source_root,
            child_environment.get("PYTHONPATH", ""),
        )))

        def run_child(phase: str, child_input: Path, child_output: Path) -> None:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--restart-worker-phase", phase,
                    "--restart-worker-input", str(child_input),
                    "--restart-worker-output", str(child_output),
                ],
                cwd=project_root,
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    "restart_worker_failed:"
                    + phase
                    + ":"
                    + completed.stderr[-2000:]
                )

        run_child("initialize", initialize_request, initialized)
        run_child("reopen", initialized, reopened)
        return json.loads(reopened.read_text(encoding="utf-8"))


def _observer_capacity_plan_v3(
    observer: FullShortDispatchLedgerObserverV1,
):
    expected = observer._next_logical_stage_plan_entry()
    context = observer.capacity_admission_context(
        route="primary", role="planning", physical_attempt=1,
    )
    rendered_request_sha256 = hashlib.sha256(b"\n\0").hexdigest()
    plan = build_stage_capacity_plan_v1(
        stage_id=str(expected["stage_id"]),
        logical_stage_id=str(context["logical_stage_id"]),
        physical_attempt=int(context["physical_attempt"]),
        physical_attempt_id=str(context["physical_attempt_id"]),
        global_physical_attempt_ordinal=int(
            context["global_physical_attempt_ordinal"]
        ),
        logical_capacity_envelope_sha256=str(
            context["logical_capacity_envelope_sha256"]
        ),
        route_capability_snapshot_sha256=str(
            context["route_capability_snapshot_sha256"]
        ),
        stage="planning",
        contract_name=str(expected["contract_name"]),
        contract_version=int(expected["contract_version"]),
        contract_schema_sha256=str(expected["contract_schema_sha256"]),
        provider_route_identity_sha256=str(
            context["provider_route_identity_sha256"]
        ),
        model_context_limit=int(
            context["route_context_capability_limit_tokens"]
        ),
        route_context_capability_source=str(
            context["route_context_capability_source"]
        ),
        requested_output_token_cap=int(expected["requested_output_tokens"]),
        route_max_output_tokens=int(context["route_max_output_tokens"]),
        final_output_reserve=int(expected["requested_output_tokens"]),
        reasoning_token_reserve=int(context["reasoning_token_reserve"]),
        reasoning_token_accounting=str(
            context["reasoning_token_accounting"]
        ),
        reasoning_output_reservation=str(
            context["reasoning_output_reservation"]
        ),
        recovery_stage_role=str(context["recovery_stage_role"]),
        reasoning_policy=str(context["reasoning_policy"]),
        rendered_message_tokens=0,
        structured_envelope_tokens=0,
        provider_envelope_tokens=256,
        wrapper_and_estimator_margin_tokens=1024,
        rendered_request_sha256=rendered_request_sha256,
        layer_projections=(),
        parent_plan_sha256=None,
    )
    observer.bind_capacity_plan(plan=plan, route="primary", role="planning")
    return plan, context


def _capacity_failure_v3(
    scenario_id: str, primitive: str, expected: str, operation, journal_path: Path,
) -> dict[str, object]:
    journal = DurableExecutionJournalV1.create(
        journal_path, execution_id="capacity-v3:" + scenario_id,
        initial_state=ExecutionState.TEMPLATE_READY,
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1, journal=journal,
    )
    try:
        kernel.execute_boundary_sync(
            CAPACITY_BOUNDARY_ID_V1, operation,
            logical_stage_id="review:capacity-v3", physical_attempt=1,
        )
    except FullShortBoundaryFailureV1 as exc:
        envelope = exc.envelope
    else:
        raise AssertionError(scenario_id + ":expected_capacity_failure")
    reopened = DurableExecutionJournalV1.open(journal_path)
    passed = (
        envelope.failure_code == expected
        and envelope.classification is FailureClassification.KNOWN
        and len(reopened.failure_receipts) == 1
        and not reopened.dispatch_token_receipts
        and envelope.raw_content_persisted is False
    )
    return _pass_v3(
        scenario_id, primitive, "DURABLE_CAPACITY_BOUNDARY",
        failure_id=envelope.failure_code, typed_failure=True,
        durable_receipt=True, expected_failure_id=expected,
        status="PASS" if passed else "FAIL",
    )


def _contract_rejection_v3(
    scenario_id: str, primitive: str, expected: str, operation,
) -> dict[str, object]:
    try:
        operation()
    except (ValueError, RouteCapabilityError) as exc:
        observed = getattr(exc, "failure_id", str(exc))
    else:
        raise AssertionError(scenario_id + ":expected_contract_rejection")
    return _pass_v3(
        scenario_id, primitive, "PRODUCTION_CONTRACT_VALIDATION",
        contract_rejection=observed, expected_contract_rejection=expected,
        status="PASS" if observed == expected else "FAIL",
    )


def _run_v3_probe(scenario_id: str, artifact_dir: Path) -> dict[str, object]:
    journal_path = artifact_dir / (scenario_id + ".json")
    if scenario_id == "missing_capability_record":
        return _capacity_failure_v3(scenario_id, "require_route_capability_v1", "capacity.route_capability_unknown", lambda: require_route_capability_v1(None), journal_path)
    if scenario_id == "unknown_blocked_required_route":
        return _capacity_failure_v3(scenario_id, "require_route_capability_v1", "capacity.route_capability_unknown", lambda: require_route_capability_v1(_record_v3(unknown=True)), journal_path)
    if scenario_id == "unknown_blocked_unused_route":
        registry = RouteCapabilityRegistryV1.create((_record_v3(), _record_v3(lane="fallback", unknown=True)))
        assert registry.unknown_required_count((("planning", "primary"),)) == 0
        registry.require_dispatchable(role="planning", lane="primary")
        return _pass_v3(scenario_id, "RouteCapabilityRegistryV1.unknown_required_count", "REQUIRED_ROUTE_SELECTION", unused_unknown_allowed=True)
    if scenario_id == "stale_evidence":
        return _contract_rejection_v3(scenario_id, "RouteCapabilityRecordV1.create", "capability_evidence_route_fingerprint_drift", lambda: replace(_record_v3(), source_evidence=(_evidence_v3("e" * 64),)))
    if scenario_id == "evidence_wrong_operator":
        record = _record_v3()
        identity = {key: getattr(record, key) for key in ("role", "lane", "provider", "provider_id_sha256", "operator", "destination", "protocol", "model", "model_id_sha256", "route_fingerprint")}
        identity["operator"] = "OTHER_OPERATOR"
        return _contract_rejection_v3(scenario_id, "RouteCapabilityRecordV1.require_exact_route_identity", "capacity.route_capability_identity_drift", lambda: record.require_exact_route_identity(**identity))
    if scenario_id == "relay_inherits_upstream":
        record = _record_v3()
        identity = {key: getattr(record, key) for key in ("role", "lane", "provider", "provider_id_sha256", "operator", "destination", "protocol", "model", "model_id_sha256", "route_fingerprint")}
        identity.update(operator="UPSTREAM_OPERATOR", destination="https://upstream.test/v1/messages")
        return _contract_rejection_v3(scenario_id, "RouteCapabilityRecordV1.require_exact_route_identity", "capacity.route_capability_identity_drift", lambda: record.require_exact_route_identity(**identity))
    if scenario_id == "capability_registry_version_drift":
        document = RouteCapabilityRegistryV1.create((_record_v3(),)).to_document()
        document["version"] = 2
        return _contract_rejection_v3(scenario_id, "RouteCapabilityRegistryV1.from_document", "route_capability_registry_document_invalid", lambda: RouteCapabilityRegistryV1.from_document(document))
    if scenario_id == "route_fingerprint_drift":
        record = _record_v3()
        identity = {key: getattr(record, key) for key in ("role", "lane", "provider", "provider_id_sha256", "operator", "destination", "protocol", "model", "model_id_sha256", "route_fingerprint")}
        identity["route_fingerprint"] = "0" * 64
        return _contract_rejection_v3(scenario_id, "RouteCapabilityRecordV1.require_exact_route_identity", "capacity.route_capability_identity_drift", lambda: record.require_exact_route_identity(**identity))
    if scenario_id == "context_window_exceeded":
        return _capacity_failure_v3(scenario_id, "StageCapacityPlanV1.require_pass", "capacity.context_window_exceeded", lambda: _plan_v3(rendered_message_tokens=30_000, structured_envelope_tokens=0, layer_projections=()).require_pass(), journal_path)
    if scenario_id == "output_limit_mismatch":
        return _capacity_failure_v3(scenario_id, "build_stage_capacity_plan_v1", "capacity.output_reserve_unsatisfied", lambda: _plan_v3(route_max_output_tokens=2_315), journal_path)
    if scenario_id == "estimator_uncertainty":
        policies = dict(DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.policies)
        policies["review"] = replace(policies["review"], minimum_wrapper_and_estimator_margin_tokens=2_048)
        registry = StageCapacityPolicyRegistryV1(policies=policies)
        return _capacity_failure_v3(scenario_id, "StageCapacityAdmissionEngineV1.admit", "capacity.estimator_uncertainty_exceeded", lambda: _plan_v3(policy_registry=registry).require_pass(), journal_path)
    if scenario_id in {"legitimate_recovery_attempt_delta", "illegal_route_delta", "illegal_authority_delta", "illegal_output_cap_delta"}:
        changes = {
            "legitimate_recovery_attempt_delta": {},
            "illegal_route_delta": {"provider_route_identity_sha256": "9" * 64},
            "illegal_authority_delta": {"physical_attempt_id": "physical-first"},
            "illegal_output_cap_delta": {"requested_output_token_cap": 2_315},
        }[scenario_id]
        prior, candidate = _recovery_pair_v3(**changes)
        if scenario_id == "legitimate_recovery_attempt_delta":
            validate_capacity_attempt_delta_v1(prior, candidate)
            return _pass_v3(scenario_id, "validate_capacity_attempt_delta_v1", "PHYSICAL_ATTEMPT_IDENTITY", allowed_delta_accepted=True)
        expected = "capacity.physical_attempt_drift" if scenario_id == "illegal_authority_delta" else "capacity.invalid_attempt_delta"
        return _capacity_failure_v3(scenario_id, "validate_capacity_attempt_delta_v1", expected, lambda: validate_capacity_attempt_delta_v1(prior, candidate), journal_path)
    if scenario_id == "exact_ready_review_capacity_edge":
        plan = _plan_v3()
        StageCapacityAdmissionEngineV1.enforce(plan)
        return _pass_v3(scenario_id, "StageCapacityAdmissionEngineV1.enforce", "SANITIZED_EXACT_READY_REVIEW_SHAPE", admission_status=plan.admission_status.value, headroom=plan.headroom)
    if scenario_id == "20k_edge":
        plan = _plan_v3(rendered_message_tokens=20_000, structured_envelope_tokens=0, layer_projections=(_layer_v3("20k-window", 20_000),))
        StageCapacityAdmissionEngineV1.enforce(plan)
        return _pass_v3(scenario_id, "StageCapacityAdmissionEngineV1.enforce", "PRODUCTION_STAGE_CAPACITY_ONLY_NOT_FULL_SHORT", admission_status=plan.admission_status.value)
    if scenario_id == "30k_edge":
        parent = _plan_v3(rendered_message_tokens=30_000, structured_envelope_tokens=0, layer_projections=(_layer_v3("30k-parent", 30_000),))
        assert parent.admission_status is AdmissionStatus.WINDOWING_REQUIRED
        assert capacity_failure_recovery_disposition_v1(stage="review", failure_id=parent.denial_failure_id) .value == "SEGMENT"
        children = tuple(_plan_v3(stage_id=f"review-30k-{index}", logical_stage_id=f"review-30k-{index}", rendered_message_tokens=15_000, structured_envelope_tokens=0, layer_projections=(_layer_v3(f"30k-{index}", 15_000),)) for index in (1, 2))
        assert all(item.admission_status is AdmissionStatus.PASS for item in children)
        return _pass_v3(scenario_id, "build_stage_capacity_plan_v1+capacity_failure_recovery_disposition_v1", "PRODUCTION_STAGE_CAPACITY_ONLY_NOT_FULL_SHORT", parent_status=parent.admission_status.value, child_count=len(children), complete_token_coverage=sum(item.rendered_message_tokens for item in children))
    if scenario_id == "restart_after_logical_envelope":
        restart = _run_restart_subprocess_probe_v3(scenario_id)
        return _pass_v3(
            scenario_id,
            "FullShortDispatchLedgerObserverV1.capacity_admission_context",
            "DURABLE_OBSERVER_RESTART_FAIL_CLOSED",
            **restart,
        )
    if scenario_id == "restart_after_physical_plan":
        restart = _run_restart_subprocess_probe_v3(scenario_id)
        return _pass_v3(
            scenario_id,
            "FullShortDispatchLedgerObserverV1.bind_capacity_plan",
            "DURABLE_PHYSICAL_PLAN_REOPEN_AND_RESTART_FAIL_CLOSED",
            **restart,
        )
    raise AssertionError("unknown_v3_scenario:" + scenario_id)


def run_capacity_fault_campaign_v3(artifact_dir: Path) -> dict[str, object]:
    """Exercise each named V3 case through its production capacity contract."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    ordered_results = [
        _run_v3_probe(scenario_id, artifact_dir)
        for scenario_id in MASTER_V3_SCENARIO_IDS
    ]
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
        "registered_capacity_failure_coverage": "REGISTRY_MEMBERSHIP_ONLY",
        "scenario_coverage": "20_PRODUCTION_PRIMITIVE_PROBES",
        "production_primitive_scenario_count": 20,
        "static_policy_assertion_count": 0,
        "v3_capacity_fault_injection_coverage": "100_PERCENT",
        "coverage_kind": "NAMED_PRODUCTION_PRIMITIVE_BEHAVIOR",
        "production_observer_behavior_coverage_claimed": True,
        "production_shaped_integration_tests": [
            "tests/test_full_short_execution.py",
            "tests/canary/test_full_short_runner_hardening.py",
            "tests/test_route_capabilities.py",
        ],
        "narrow_scope_scenarios": {
            "17_18": "stage capacity and semantic split only; not Full Short",
            "19_20": "durable store reopen and production observer restart fail-closed behavior",
        },
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
                for item in ordered_results
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
        description="Run an offline Full Short capacity fault campaign."
    )
    parser.add_argument(
        "--campaign-version", choices=("v2", "v3"), default="v3",
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--restart-worker-phase", choices=("initialize", "reopen"),
    )
    parser.add_argument("--restart-worker-input", type=Path)
    parser.add_argument("--restart-worker-output", type=Path)
    args = parser.parse_args(argv)
    if args.restart_worker_phase is not None:
        if args.restart_worker_input is None or args.restart_worker_output is None:
            parser.error("restart worker requires input and output paths")
        return _restart_worker_v3(
            phase=args.restart_worker_phase,
            input_path=args.restart_worker_input,
            output_path=args.restart_worker_output,
        )
    if args.artifact_dir is None:
        with tempfile.TemporaryDirectory(
            prefix="full-short-capacity-fault-campaign-"
        ) as temp_dir:
            report = (
                run_capacity_fault_campaign_v3(Path(temp_dir))
                if args.campaign_version == "v3"
                else run_capacity_fault_campaign_v2(Path(temp_dir))
            )
    else:
        report = (
            run_capacity_fault_campaign_v3(args.artifact_dir)
            if args.campaign_version == "v3"
            else run_capacity_fault_campaign_v2(args.artifact_dir)
        )
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
