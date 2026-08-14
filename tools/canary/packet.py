"""Prepare an exact, sanitized C0A Plan and single-use approval packet."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint
from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .artifact_hash import file_sha256
from .contracts import (
    build_canary_experiment_plan_v1,
    build_canary_plan_approval_v1,
)
from .descriptors import approved_fake_routes, configure_fake_routes, fake_route_identity
from .environment import c0a_environment
from .hash_manifest import validate_import_closure


APPROVED_THIRD_PARTY: tuple[str, ...] = ()


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _fixture(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "SanitizedCanaryShortWorkloadV1":
        raise ValueError("canary_workload_fixture_invalid")
    if value.get("mode") != "short" or int(value.get("target_words") or 0) != 6000:
        raise ValueError("canary_workload_fixture_out_of_scope")
    return value


def prepare_c0a_packet(
    *, fixture_path: Path, plan_path: Path, approval_path: Path,
    cohort_id: str, run_namespace: str = "c0a-short-v1",
    now: datetime | None = None,
) -> tuple[dict, dict]:
    """Use an isolated throw-away DB to bind the exact execution config."""

    fixture = _fixture(fixture_path)
    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=APPROVED_THIRD_PARTY,
    )
    fixture_sha = file_sha256(fixture_path)
    flags = {
        "NOVEL_SHORT_CANONICAL_V2": False,
        "project_short_canonical_v2": False,
        "NOVEL_CANONICAL_SHADOW_V1": False,
        "NOVEL_RELIABILITY_TRACE": True,
    }
    with tempfile.TemporaryDirectory(prefix="novel-c0a-plan-") as temporary:
        root = Path(temporary)
        with c0a_environment(root):
            db = Database(root / "app.db")
            db.migrate()
            configure_fake_routes(db)
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
            runtime = collect_runtime_fingerprint(db, project_id=project.id)
    route_definition = next(
        item for item in runtime.children
        if item.get("schema") == "RuntimeRouteRoleBindingManifestV1"
    )
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
            "fixture_sha256": fixture_sha,
            "prompt_mutation_allowed": False,
        },
    )
    route_identity = fake_route_identity()
    plan = build_canary_experiment_plan_v1({
        "canary_mode": "c0a_fake_dry_run",
        "runtime_mode": str(runtime.build["payload"]["mode"]),
        "approved_build_fingerprint": runtime.build_fingerprint_sha256,
        "approved_execution_config_fingerprint": runtime.execution_config_fingerprint_sha256,
        "expected_runtime_execution_fingerprint": runtime.execution_fingerprint_sha256,
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v1",
        "launcher_sha256": launcher["launcher_sha256"],
        "workload_manifest_hash": workload_hash,
        "workloads": [{
            "workload_id": fixture["workload_id"],
            "fixture_sha256": fixture_sha,
            "weight": 1,
            "prompt_policy_manifest_sha256": prompt_policy_hash,
            "expected_stage_reachability": list(fixture["expected_stages"]),
            "maximum_model_calls": 20,
            "estimated_input_tokens": 2_000_000,
            "maximum_output_tokens": 2_000_000,
            "success_definition": "workflow_completed",
            "controlled_outcomes": ["waiting_provider", "waiting_user"],
            "terminal_outcomes": ["workflow_terminal"],
        }],
        "provider_descriptor_definition_sha256": route_identity["provider_descriptor_hash"],
        "role_binding_manifest_definition_sha256": route_definition["definition_sha256"],
        "approved_routes": approved_fake_routes(),
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
            "maximum_model_calls_per_run": 20,
            "maximum_total_model_calls": 20,
            "maximum_input_tokens": 2_000_000,
            "maximum_output_tokens": 2_000_000,
            "pricing_status": "not_applicable_fake",
            "currency": "NONE",
            "maximum_estimated_cost_microunits": 0,
            "maximum_elapsed_seconds": 600,
            "gate_wait_timeout_seconds": 60,
        },
        "stop_conditions": [
            "first_terminal_failure", "fingerprint_mismatch", "budget_exceeded",
            "network_attempt", "credential_lookup", "provider_client_creation",
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
        "approval_scope": "C0A_FAKE_DRY_RUN",
        "approved_plan_sha256": plan["plan_sha256"],
        "approved_launcher_sha256": plan["launcher_sha256"],
        "single_use_cohort_id": cohort_id,
        "approval_expiry": _utc(current + timedelta(hours=2)),
        "execution_window": {
            "not_before": _utc(current - timedelta(minutes=5)),
            "not_after": _utc(current + timedelta(hours=1)),
        },
        "maximum_executions": 1,
        "usage_status": "unused",
        "consumed_evidence_sha256": None,
        "authorized_actions": {
            "credential_lookup": False,
            "provider_client_creation": False,
            "network": False,
            "paid_model_calls": False,
            "fake_boundary": True,
        },
    })
    _write_json(plan_path, plan)
    _write_json(approval_path, approval)
    return plan, approval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare an exact C0A Canary packet")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--run-namespace", default="c0a-short-v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan, approval = prepare_c0a_packet(
        fixture_path=args.fixture, plan_path=args.plan,
        approval_path=args.approval, cohort_id=args.cohort_id,
        run_namespace=args.run_namespace,
    )
    print(json.dumps({
        "schema": "CanaryPacketPreparationResultV1",
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval["approval_sha256"],
        "launcher_sha256": plan["launcher_sha256"],
        "approval_scope": approval["approval_scope"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
