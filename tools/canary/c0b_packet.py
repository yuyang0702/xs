"""Prepare the exact, disabled-by-default C0B-SMOKE-1 approval packet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .artifact_hash import file_sha256
from .contracts import build_canary_experiment_plan_v1, build_canary_plan_approval_v1
from .descriptors import (
    C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH,
    approved_production_routes, copy_production_execution_config,
    production_route_identity, production_route_manifest_hashes,
)
from .environment import c0a_environment
from .hash_manifest import validate_import_closure
from .packet import APPROVED_THIRD_PARTY
from .provider_matrix import (
    production_mirror_manifest, production_price_catalog,
    validate_production_mirror,
)
from .topology import C0BElapsedBudgetV1, c0b_short_call_topology_v1


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _fixture(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "SanitizedCanaryShortWorkloadV1"
        or value.get("workload_id") != "short-normal-v1"
        or int(value.get("target_words") or 0) != 6000
    ):
        raise ValueError("c0b_smoke_workload_invalid")
    return value


def _actual_semantic_routes(db: Database) -> list[dict]:
    rows = []
    for route in production_mirror_manifest()["routes"]:
        role = route["role"]
        primary = production_route_identity(db, role, "primary")
        fallback = production_route_identity(db, role, "fallback")
        rows.append({
            "role": role,
            "primary_provider": primary["provider_alias"],
            "primary_model": primary["model_alias"],
            "fallback_provider": fallback["provider_alias"],
            "fallback_model": fallback["model_alias"],
            "protocol": primary["protocol"],
            "relay_group": (
                "default" if "happy" in {
                    primary["provider_alias"], fallback["provider_alias"],
                } else "not_applicable"
            ),
        })
    return rows


def prepare_c0b_smoke_packet(
    *, live_database_path: Path, fixture_path: Path, plan_path: Path,
    approval_path: Path, packet_path: Path, cohort_id: str,
    run_namespace: str, now: datetime | None = None,
) -> tuple[dict, dict, dict]:
    """Copy metadata only; do not touch keyring, registry resolution, or network."""

    fixture = _fixture(fixture_path)
    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=APPROVED_THIRD_PARTY,
    )
    fixture_sha = file_sha256(fixture_path)
    topology = c0b_short_call_topology_v1()
    elapsed = C0BElapsedBudgetV1.from_topology(topology).definition()
    catalog = production_price_catalog()
    price_definitions = catalog.definitions()
    price_catalog_sha = domain_sha256(
        "novel-flywheel-c0b-price-catalog-v1", price_definitions,
    )
    with tempfile.TemporaryDirectory(prefix="novel-c0b-plan-") as temporary:
        root = Path(temporary)
        cloned_db = root / "app.db"
        with c0a_environment(root):
            db = Database(cloned_db)
            db.migrate()
            copy_production_execution_config(Database(live_database_path), db)
            store = ProjectStore(db, root / "projects")
            project = store.create(ProjectCreate(
                title=str(fixture["title"]), mode="short",
                genre=str(fixture["genre"]), premise=str(fixture["premise"]),
                target_words=int(fixture["target_words"]),
            ))
            db.set_feature_flag(
                "short_canonical_v2", False,
                scope_type="project", scope_id=project.id,
            )
            actual_routes = _actual_semantic_routes(db)
            drift = validate_production_mirror(actual_routes)
            if drift["status"] != "EXACT_MATCH":
                raise ValueError("production_mirror_route_drift")
            routes = approved_production_routes(db)
            route_hashes = production_route_manifest_hashes(db)
            runtime = collect_runtime_fingerprint_v2(db, project_id=project.id)
    workload_manifest = {
        "schema": "CanaryWorkloadManifestV1",
        "fixture_sha256": fixture_sha,
        "workload_id": fixture["workload_id"],
        "expected_stages": fixture["expected_stages"],
    }
    workload_hash = domain_sha256(
        "novel-flywheel-canary-workload-manifest-v1", workload_manifest,
    )
    prompt_policy_hash = domain_sha256(
        "novel-flywheel-canary-prompt-policy-v1", {
            "build_fingerprint": runtime.build_fingerprint_sha256,
            "fixture_sha256": fixture_sha, "prompt_mutation_allowed": False,
        },
    )
    flags = {
        "NOVEL_SHORT_CANONICAL_V2": False,
        "project_short_canonical_v2": False,
        "NOVEL_CANONICAL_SHADOW_V1": False,
        "NOVEL_RELIABILITY_TRACE": True,
        "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1": False,
    }
    approval_budget_body = {
        "maximum_model_calls_per_run": 48,
        "maximum_total_model_calls": 48,
        "maximum_input_tokens": 2_000_000,
        "maximum_output_tokens": 2_000_000,
        "maximum_usd_cost_microunits": 60_000_000,
        "maximum_cny_cost_microunits": 120_000_000,
        "maximum_elapsed_seconds": elapsed["hard_launcher_timeout_seconds"],
    }
    approval_budget = {
        **approval_budget_body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-approved-budget-v1", approval_budget_body,
        ),
    }
    plan = build_canary_experiment_plan_v1({
        "canary_mode": "c0b_real_path_reachability",
        "runtime_mode": str(runtime.build["payload"]["mode"]),
        "approved_build_fingerprint": runtime.build_fingerprint_sha256,
        "approved_execution_config_fingerprint": runtime.execution_config_fingerprint_sha256,
        "expected_runtime_execution_fingerprint": runtime.execution_fingerprint_sha256,
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v2",
        "approved_execution_config_components": (
            runtime.execution_config_component_binding
        ),
        "launcher_sha256": launcher["launcher_sha256"],
        "workload_manifest_hash": workload_hash,
        "workloads": [{
            "workload_id": fixture["workload_id"], "fixture_sha256": fixture_sha,
            "weight": 1, "prompt_policy_manifest_sha256": prompt_policy_hash,
            "expected_stage_reachability": list(fixture["expected_stages"]),
            "maximum_model_calls": topology["maximum_total_paid_dispatches"],
            "estimated_input_tokens": 36_715,
            "maximum_output_tokens": 2_000_000,
            "success_definition": "workflow_completed_or_controlled_provider_capability_outcome",
            "controlled_outcomes": [
                "waiting_provider", "waiting_user",
                "CONTROLLED_PROVIDER_CAPABILITY_OUTCOME",
            ],
            "terminal_outcomes": ["workflow_terminal"],
        }],
        **route_hashes,
        "approved_routes": routes,
        "feature_flag_snapshot": flags,
        "isolation": {
            "data_root_kind": "canary_ephemeral",
            "stable_root_identity": domain_sha256(
                "novel-flywheel-canary-stable-root-v1", run_namespace,
            ),
            "db_path_hash": domain_sha256("novel-flywheel-canary-path-role-v1", "db"),
            "project_root_hash": domain_sha256(
                "novel-flywheel-canary-path-role-v1", "projects",
            ),
            "approval_ledger_identity": domain_sha256(
                "novel-flywheel-canary-approval-ledger-v1", cohort_id,
            ),
            "run_namespace": run_namespace,
        },
        "budgets": {
            "maximum_runs": 1,
            "maximum_model_calls_per_run": topology["maximum_total_paid_dispatches"],
            "maximum_total_model_calls": topology["maximum_total_paid_dispatches"],
            "maximum_input_tokens": 2_000_000,
            "maximum_output_tokens": 2_000_000,
            "pricing_status": "verified_identity_price_bounded_capability_unknown",
            "currency": "MULTI_CURRENCY_NO_FX",
            "maximum_estimated_cost_microunits": 0,
            "maximum_elapsed_seconds": elapsed["hard_launcher_timeout_seconds"],
            "gate_wait_timeout_seconds": 120,
            "monetary_budget": {
                "schema": "CanaryMonetaryBudgetV1",
                "maximum_usd_cost_microunits": 60_000_000,
                "maximum_cny_cost_microunits": 120_000_000,
                "approved_fx_snapshot": None,
            },
            "price_catalog_sha256": price_catalog_sha,
            "call_topology_sha256": topology["definition_sha256"],
            "elapsed_budget_sha256": elapsed["definition_sha256"],
            "worst_case_chargeable": True,
        },
        "stop_conditions": [
            "first_terminal_failure", "first_controlled_provider_capability_outcome",
            "fingerprint_mismatch", "budget_exceeded", "route_mismatch",
            "price_schedule_mismatch", "approval_expired",
        ],
        "report_policy": {
            "raw_content_included": False, "hash_only": True,
            "machine_specific_paths_included": False,
        },
        "approved_dependency_manifest": {
            "stdlib": True, "production_package": True,
            "third_party": list(APPROVED_THIRD_PARTY),
        },
    })
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approval = build_canary_plan_approval_v1({
        "approval_scope": "C0B_REAL_PROVIDER_PATH_REACHABILITY",
        "approved_plan_sha256": plan["plan_sha256"],
        "approved_launcher_sha256": plan["launcher_sha256"],
        "single_use_cohort_id": cohort_id,
        "approval_expiry": _utc(current + timedelta(days=7)),
        "execution_window": {
            "not_before": _utc(current),
            "not_after": _utc(current + timedelta(days=7) - timedelta(minutes=15)),
        },
        "maximum_executions": 1, "usage_status": "unused",
        "consumed_evidence_sha256": None, "named_approver": None,
        "approved_budget": approval_budget,
        "authorized_actions": {
            "credential_lookup": False, "provider_client_creation": False,
            "network": False, "paid_model_calls": False,
            "fake_boundary": False,
        },
    })
    packet = {
        "schema": "C0BSmoke1ApprovalPacketV1", "version": 1,
        "status": "C0B_SMOKE_1_READY_FOR_USER_APPROVAL",
        "execution_performed": False,
        "plan_sha256": plan["plan_sha256"],
        "approval_draft_sha256": approval["approval_sha256"],
        "launcher_sha256": launcher["launcher_sha256"],
        "workload_sha256": fixture_sha,
        "build_fingerprint": runtime.build_fingerprint_sha256,
        "execution_config_fingerprint": runtime.execution_config_fingerprint_sha256,
        "runtime_execution_fingerprint": runtime.execution_fingerprint_sha256,
        **route_hashes,
        "call_topology": topology,
        "elapsed_budget": elapsed,
        "price_catalog": price_definitions,
        "monetary_hard_caps": plan["budgets"]["monetary_budget"],
        "expected_budget": {
            "input_tokens": 36_715, "output_tokens": 46_197,
            "usd_cost_microunits": 136_066,
            "cny_cost_microunits": 123_821,
            "basis": "current deterministic 16-boundary primary-route reservation",
        },
        "hard_budget": {
            "input_tokens": 2_000_000, "output_tokens": 2_000_000,
            "maximum_output_tokens_per_dispatch": (
                C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH
            ),
            "model_calls": topology["maximum_total_paid_dispatches"],
            "usd_cost_microunits": 60_000_000,
            "cny_cost_microunits": 120_000_000,
            "elapsed_seconds": elapsed["hard_launcher_timeout_seconds"],
        },
        "approval_budget": approval_budget,
        "authorization_required": True,
        "hard_blockers": [],
    }
    _write_json(plan_path, plan)
    _write_json(approval_path, approval)
    _write_json(packet_path, packet)
    return plan, approval, packet
