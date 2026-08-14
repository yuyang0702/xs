"""Generate the hash-exact C0B-P1 review artifacts without executing C0B."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .c0b_packet import prepare_c0b_smoke_packet
from .provider_matrix import (
    production_mirror_manifest, production_price_catalog,
    protocol_evidence_matrix,
)
from .topology import C0BElapsedBudgetV1, c0b_short_call_topology_v1


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def generate_c0b_p1_deliverables(
    *, live_database_path: Path, fixture_path: Path, output_root: Path,
    cohort_id: str, run_namespace: str, now: datetime | None = None,
) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    plan_path = output_root / "c0b-smoke-1-plan-v1.json"
    approval_path = output_root / "c0b-smoke-1-approval-draft-v1.json"
    packet_path = output_root / "c0b-smoke-1-approval-packet-v1.json"
    plan, approval, packet = prepare_c0b_smoke_packet(
        live_database_path=live_database_path, fixture_path=fixture_path,
        plan_path=plan_path, approval_path=approval_path,
        packet_path=packet_path, cohort_id=cohort_id,
        run_namespace=run_namespace, now=current,
    )
    mirror = production_mirror_manifest()
    catalog = production_price_catalog().definitions()
    topology = c0b_short_call_topology_v1()
    elapsed = C0BElapsedBudgetV1.from_topology(topology).definition()
    provider_evidence = {
        "schema": "ProductionMirrorProviderEvidenceMatrixV1", "version": 1,
        "generated_at": current.isoformat(),
        "routes": mirror["routes"],
        "capability_evidence": mirror["capability_evidence"],
        "price_evidence": catalog,
        "official_sources": {
            "deepseek": "https://api-docs.deepseek.com/quick_start/pricing/",
            "doubao_pricing": "https://www.volcengine.com/docs/84458/1585097?lang=zh&redirect=1",
            "doubao_character": "https://www.volcengine.com/product/doubao",
        },
        "relay_evidence_policy": (
            "Lingsuan/Happy evidence is user-supplied relay-console evidence; "
            "it is not upstream-vendor identity proof."
        ),
        "hard_blockers": [],
    }
    route_protocol = protocol_evidence_matrix(mirror["routes"])
    monetary = {
        "schema": "CanaryMonetaryBudgetV1", "version": 1,
        "currency_conversion": "none", "approved_fx_snapshot": None,
        "expected": packet["expected_budget"],
        "hard": packet["hard_budget"],
        "price_catalog_sha256": plan["budgets"]["price_catalog_sha256"],
        "price_rules": catalog,
    }
    boundary = {
        "schema": "C0BRealProviderBoundaryDesignV1", "version": 1,
        "delegate": "novel_flywheel.models.ModelGateway",
        "provider_registry": "novel_flywheel.providers.registry.ProviderRegistry",
        "provider_protocol_reimplementation": False,
        "credential_store": "GuardedCredentialStore(KeyringSecretStore)",
        "default_execution_enabled": False,
        "test_boundary": "fake production-shaped delegate only",
        "production_source_changes": 0,
    }
    ordering = {
        "schema": "C0BCredentialClientNetworkOrderingEvidenceV1", "version": 1,
        "order": [
            "load_plan", "validate_approval", "rehash_launcher",
            "rehash_workload", "source_revalidation", "build_validation",
            "execution_config_validation", "runtime_execution_validation",
            "origin_binding_validation", "executor_binding_validation",
            "sidecar_validation", "route_manifest_validation",
            "phase1b_validation", "canary_root_validation", "budget_reservation",
            "CanaryRuntimeFingerprintPreflightV1", "approval_authorization",
            "credential_lookup", "provider_client_construction", "network_model_dispatch",
        ],
        "test": "tests/canary/test_c0b_budget_boundary.py::test_credential_client_and_network_follow_final_authorization",
        "p1_observed_counts": {
            "credential_lookup": 0, "provider_client_creation": 0,
            "network": 0, "model": 0, "paid": 0,
        },
    }
    billing = {
        "schema": "C0BProviderBillingConservativePolicyV1", "version": 1,
        "pre_reserve": [
            "call", "estimated_input_tokens", "configured_output_cap",
            "worst_case_currency_cost", "remaining_elapsed_budget",
        ],
        "worst_case_chargeable": True,
        "failure_without_reliable_billing_receipt": "reservation_retained",
        "missing_usage": "reservation_retained",
        "refund_policy": "no_refund_in_canary_ledger",
        "reconcile_fields": [
            "input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_tokens", "provider_billing_fields_if_present",
        ],
    }
    bounded = {
        "schema": "C0BBoundedUnknownCapabilityMatrixV1", "version": 1,
        "policy": "VerifiedIdentityPrice_BoundedCapabilityUnknown",
        "entries": mirror["capability_evidence"],
        "controlled_family": "CONTROLLED_PROVIDER_CAPABILITY_OUTCOME",
        "maximum_output_tokens_per_dispatch": packet["hard_budget"][
            "maximum_output_tokens_per_dispatch"
        ],
        "hard_blockers": [],
    }
    hashes = {
        "schema": "C0BExactHashMatrixV1", "version": 1,
        "plan_sha256": plan["plan_sha256"],
        "approval_draft_sha256": approval["approval_sha256"],
        "launcher_sha256": plan["launcher_sha256"],
        "workload_sha256": packet["workload_sha256"],
        "build_fingerprint": plan["approved_build_fingerprint"],
        "execution_config_fingerprint": plan["approved_execution_config_fingerprint"],
        "runtime_execution_fingerprint": plan["expected_runtime_execution_fingerprint"],
        "provider_descriptor_manifest_sha256": plan[
            "provider_descriptor_definition_sha256"
        ],
        "role_binding_manifest_sha256": plan[
            "role_binding_manifest_definition_sha256"
        ],
        "call_topology_sha256": topology["definition_sha256"],
        "elapsed_budget_sha256": elapsed["definition_sha256"],
        "price_catalog_sha256": plan["budgets"]["price_catalog_sha256"],
    }
    files = {
        "c0b-p1-production-mirror-provider-evidence-matrix.json": provider_evidence,
        "c0b-p1-route-protocol-evidence-matrix-v1.json": route_protocol,
        "c0b-p1-short-call-topology-v1.json": topology,
        "c0b-p1-canary-monetary-budget-v1.json": monetary,
        "c0b-p1-elapsed-budget-v1.json": elapsed,
        "c0b-p1-real-provider-boundary-v1.json": boundary,
        "c0b-p1-ordering-evidence-v1.json": ordering,
        "c0b-p1-provider-billing-policy-v1.json": billing,
        "c0b-p1-bounded-unknown-capability-matrix-v1.json": bounded,
        "c0b-p1-exact-hash-matrix-v1.json": hashes,
    }
    for name, value in files.items():
        _write(output_root / name, value)
    index_body = {
        "schema": "C0BP1DeliverableIndexV1", "version": 1,
        "status": "C0B_SMOKE_1_READY_FOR_USER_APPROVAL",
        "execution_performed": False,
        "files": sorted([*files, plan_path.name, approval_path.name, packet_path.name]),
        "hard_blockers": [],
    }
    index = {
        **index_body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-p1-deliverable-index-v1", index_body,
        ),
    }
    _write(output_root / "c0b-p1-deliverable-index-v1.json", index)
    return {"plan": plan, "approval": approval, "packet": packet, "index": index}
