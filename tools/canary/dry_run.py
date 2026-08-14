"""Isolated, official-API C0A fake Short dry run and hash-only evidence."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from typing import Any, Iterable

from novel_flywheel.app import create_app
from novel_flywheel.db import ACTIVE_RUN_STATUSES, Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.projects import ProjectCreate
from novel_flywheel.runtime_fingerprint import (
    DefinitionStore,
    canonical_runtime_bindings,
    collect_runtime_fingerprint,
    process_captured_build_fingerprint,
    runtime_source_revalidation,
    verify_runtime_binding_sidecars,
)
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.workflows import WorkflowService

from .approval_store import ApprovalConsumptionStore
from .artifact_hash import file_sha256, live_parity_manifest, parity_equal, tree_manifest
from .budget import AtomicBudgetLedger, BudgetLimits
from .contracts import (
    validate_canary_experiment_plan_v1,
    validate_canary_plan_approval_v1,
)
from .descriptors import configure_fake_routes, fake_route_identity
from .environment import c0a_environment
from .evidence import build_canary_evidence_package_v1
from .fake_boundary import DeterministicShortBoundary, write_sanitized_skill_fixtures
from .gate import CanaryBoundaryAbort, PreflightGatedGateway, TwoPhaseGate
from .hash_manifest import validate_import_closure
from .isolation import create_canary_root, validate_canary_root
from .network_sentinel import FailClosedNetworkSentinel
from .outcomes import CanaryOutcome
from .packet import APPROVED_THIRD_PARTY
from .preflight import ExactBoundaryVerifier
from .route_policy import ApprovedRoutePolicy


TERMINAL_STATUSES = frozenset({
    "completed", "failed", "cancelled", "interrupted", "waiting_user",
    "waiting_provider",
})


@asynccontextmanager
async def _local_execution_scope():
    yield


class NoCredentialStore:
    """A counting tripwire; C0A never stores or returns credential material."""

    def __init__(self) -> None:
        self.lookup_count = 0
        self.mutation_count = 0

    def set(self, provider_id: str, value: str) -> None:
        self.mutation_count += 1
        raise RuntimeError("credential_mutation_blocked_in_c0a")

    def get(self, provider_id: str) -> str | None:
        self.lookup_count += 1
        raise RuntimeError("credential_lookup_blocked_in_c0a")

    def delete(self, provider_id: str) -> None:
        self.mutation_count += 1
        raise RuntimeError("credential_mutation_blocked_in_c0a")


class C0AFakeWorkflowService(WorkflowService):
    """Keep the real Short pipeline while excluding CrewAI's external wrapper."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.canary_stage_failure_types: list[str] = []

    async def _stage(self, *args: Any, **kwargs: Any):
        try:
            return await super()._stage(*args, **kwargs)
        except BaseException as exc:
            types = [type(exc).__name__]
            for attribute in ("primary_error", "fallback_error"):
                nested = getattr(exc, attribute, None)
                if nested is not None:
                    types.append(type(nested).__name__)
            self.canary_stage_failure_types.append("/".join(types))
            raise

    async def run_short(
        self, project_id: str, use_crewai: bool = True,
        run_id: str | None = None,
    ) -> dict:
        self.canary_last_exception: BaseException | None = None
        try:
            return await super().run_short(
                project_id, use_crewai=False, run_id=run_id,
            )
        except BaseException as exc:
            self.canary_last_exception = exc
            raise


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("canary_json_object_required")
    return value


def _hash_identifier(kind: str, value: str) -> str:
    return domain_sha256(f"novel-flywheel-canary-identifier-v1:{kind}", value)


def _percentiles(samples: list[int]) -> dict[str, int]:
    ordered = sorted(samples)
    if not ordered:
        return {"count": 0, "p50_micros": 0, "p95_micros": 0, "max_micros": 0}

    def pick(fraction: float) -> int:
        return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]

    return {
        "count": len(ordered), "p50_micros": pick(0.50),
        "p95_micros": pick(0.95), "max_micros": ordered[-1],
    }


def _live_active_run_count(database_path: Path) -> int:
    if not database_path.is_file():
        return 0
    uri = database_path.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
            row = connection.execute(
                f"SELECT COUNT(*) FROM runs WHERE status IN ({placeholders})",
                tuple(ACTIVE_RUN_STATUSES),
            ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError("live_run_state_unverifiable") from exc
    return int(row[0]) if row else 0


@contextmanager
def _provider_resolution_tripwire(app: Any):
    calls = {"count": 0}
    original = app.state.registry.resolve

    def blocked(*args: Any, **kwargs: Any):
        calls["count"] += 1
        raise RuntimeError("provider_client_creation_blocked_in_c0a")

    app.state.registry.resolve = blocked
    try:
        yield calls
    finally:
        app.state.registry.resolve = original


def _binding_pair(db: Database, run_id: str) -> tuple[dict | None, dict | None, dict]:
    bindings = canonical_runtime_bindings(db, run_id)
    origin = next(
        (item for item in bindings["bindings"] if item.get("binding_kind") == "origin"),
        None,
    )
    executor = next(
        (item for item in reversed(bindings["bindings"])
         if item.get("binding_kind") == "executor"),
        None,
    )
    return origin, executor, bindings


def _effective_routes(app: Any) -> list[Any]:
    routes: list[Any] = []
    for item in app.routes:
        original = getattr(item, "original_router", None)
        if original is not None:
            routes.extend(list(original.routes))
        else:
            routes.append(item)
    return routes


def _create_project_and_outline(fixture: dict, app: Any) -> str:
    project = app.state.projects.create(ProjectCreate(
        title=fixture["title"], mode="short", genre=fixture["genre"],
        premise=fixture["premise"], target_words=fixture["target_words"],
    ))
    project_id = project.id
    # Canary preparation uses the same production OutlineService directly.
    # Only the execution route under test must cross the public HTTP boundary;
    # keeping preparation out of the transport avoids conflating ASGI/threadpool
    # setup with Short Runtime reachability.
    candidate = app.state.outlines.create_candidate(
        project_id, fixture["outline"], title="Controlled Formal Outline",
    )
    comparison = app.state.outlines.compare_candidate(project_id, candidate["id"])
    app.state.outlines.apply_candidate(
        project_id, candidate["id"], change_ids=None,
        expected_revision=comparison["state_revision"],
    )
    return project_id


async def run_c0a_dry_run(
    *, plan_path: Path, approval_path: Path, approved_plan_sha256: str,
    workload_fixture_path: Path, canary_root: Path,
    approval_ledger_root: Path, live_database_path: Path,
    live_project_root: Path, live_incident_roots: Iterable[Path] = (),
) -> dict:
    """Run one 6K fake Short through the public API with no external boundary."""

    started_ns = time.perf_counter_ns()
    if os.name == "nt" and len(str(canary_root.resolve(strict=False))) > 96:
        raise RuntimeError("canary_root_path_budget_exceeded")
    plan = validate_canary_experiment_plan_v1(_read_json(plan_path))
    if plan["plan_sha256"] != approved_plan_sha256:
        raise ValueError("cli_approved_plan_hash_mismatch")
    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=plan["approved_dependency_manifest"]["third_party"],
    )
    if launcher["launcher_sha256"] != plan["launcher_sha256"]:
        raise ValueError("launcher_changed_during_canary")
    approval = validate_canary_plan_approval_v1(
        _read_json(approval_path), expected_scope="C0A_FAKE_DRY_RUN",
        expected_plan_sha256=plan["plan_sha256"],
        expected_launcher_sha256=plan["launcher_sha256"],
    )
    if _live_active_run_count(live_database_path):
        raise RuntimeError("live_active_run_present")
    incident_roots = tuple(live_incident_roots)
    all_live_roots = (live_database_path.parent, live_project_root, *incident_roots)
    before = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
        incident_roots=incident_roots,
    )
    create_canary_root(
        canary_root,
        stable_root_identity=plan["isolation"]["stable_root_identity"],
        plan_sha256=plan["plan_sha256"],
        run_namespace=plan["isolation"]["run_namespace"],
        live_roots=all_live_roots,
    )
    store = ApprovalConsumptionStore(approval_ledger_root)
    reservation_receipt = store.reserve(approval)
    fixture = _read_json(workload_fixture_path)
    fixture_sha = file_sha256(workload_fixture_path)
    workload_hash = domain_sha256(
        "novel-flywheel-canary-workload-manifest-v1", {
            "schema": "CanaryWorkloadManifestV1",
            "fixture_sha256": fixture_sha,
            "workload_id": fixture["workload_id"],
            "expected_stages": fixture["expected_stages"],
        },
    )
    skill_root = canary_root / "skills"
    write_sanitized_skill_fixtures(skill_root)
    constraint = canary_root / "constraints-source.md"
    constraint.write_text("# Canary Constraint\n\nUse only the confirmed formal outline.\n", encoding="utf-8")
    secrets = NoCredentialStore()
    sentinel = FailClosedNetworkSentinel()
    boundary_capture_micros: list[int] = []
    gate_started_ns = 0
    gate_elapsed_micros = 0
    run_id = ""
    project_id = ""
    final_run: dict[str, Any] = {}
    workflow_exception: BaseException | None = None
    gated: PreflightGatedGateway | None = None
    verifier: ExactBoundaryVerifier | None = None
    bindings_observed: dict[str, Any] = {}
    with c0a_environment(canary_root), sentinel:
        db = Database(canary_root / "db" / "app.db")
        db.migrate()
        configure_fake_routes(db)
        references = ReferenceLibrary(db, canary_root / "references")
        app = create_app(
            db, secrets, skill_roots=[skill_root],
            workspace_root=canary_root / "projects",
            root_constraints=[constraint], reference_library=references,
        )
        with _provider_resolution_tripwire(app) as provider_calls:
            async with app.router.lifespan_context(app):
                async with _local_execution_scope():
                    project_id = _create_project_and_outline(fixture, app)
                    db.set_feature_flag(
                        "short_canonical_v2", False,
                        scope_type="project", scope_id=project_id,
                    )
                    current = collect_runtime_fingerprint(db, project_id=project_id)
                    if current.build_fingerprint_sha256 != plan["approved_build_fingerprint"]:
                        raise RuntimeError("build_changed_before_launch")
                    if current.execution_config_fingerprint_sha256 != plan[
                        "approved_execution_config_fingerprint"
                    ]:
                        raise RuntimeError("execution_config_changed_before_launch")
                    process_build, process_children = process_captured_build_fingerprint()
                    run_holder: dict[str, str] = {}

                    def stage_resolver(role: str) -> tuple[str, str]:
                        selected = run_holder.get("run_id")
                        run = db.get_run(selected) if selected else None
                        if run is None:
                            candidates = [
                                item for item in db.list_runs(project_id)
                                if item.get("workflow") == "short-story"
                                and item.get("status") not in {
                                    "completed", "failed", "cancelled", "interrupted",
                                }
                            ]
                            run = candidates[0] if len(candidates) == 1 else None
                        if run is None:
                            raise RuntimeError("canary_run_identity_unavailable")
                        selected = str(run["id"])
                        run_holder["run_id"] = selected
                        return str(run.get("current_stage") or role), _hash_identifier("run", selected)

                    def route_resolver(role: str, kind: str) -> dict[str, str]:
                        return dict(fake_route_identity())

                    def snapshot_supplier() -> dict:
                        capture_started = time.perf_counter_ns()
                        selected = run_holder.get("run_id")
                        if not selected:
                            raise RuntimeError("canary_run_identity_unavailable")
                        current_runtime = collect_runtime_fingerprint(
                            db, project_id=project_id,
                        )
                        current_build = current_runtime.build
                        current_children = current_runtime.children
                        origin, executor, binding_set = _binding_pair(db, selected)
                        sidecars = (
                            verify_runtime_binding_sidecars(
                                DefinitionStore(db.path.parent), executor,
                            ) if executor is not None else {
                                "valid": False, "validation_status": "invalid",
                                "reason_codes": ["executor_binding_missing"],
                            }
                        )
                        route_definition = next(
                            item for item in current_runtime.children
                            if item.get("schema") == "RuntimeRouteRoleBindingManifestV1"
                        )
                        result = {
                            "plan": _read_json(plan_path),
                            "approval": _read_json(approval_path),
                            "launcher_sha256": validate_import_closure(
                                Path(__file__).resolve().parent,
                                approved_third_party=APPROVED_THIRD_PARTY,
                            )["launcher_sha256"],
                            "workload_manifest_hash": workload_hash,
                            "workload_fixture_hashes": {
                                fixture["workload_id"]: file_sha256(workload_fixture_path),
                            },
                            "provider_descriptor_definition_sha256": (
                                fake_route_identity()["provider_descriptor_hash"]
                            ),
                            "role_binding_manifest_definition_sha256": (
                                route_definition["definition_sha256"]
                            ),
                            "feature_flag_snapshot": {
                                "NOVEL_SHORT_CANONICAL_V2": (
                                    os.environ.get("NOVEL_SHORT_CANONICAL_V2", "0") == "1"
                                ),
                                "project_short_canonical_v2": bool(
                                    db.feature_flag(
                                        "short_canonical_v2", project_id=project_id,
                                        default=False,
                                    )["enabled"]
                                ),
                                "NOVEL_CANONICAL_SHADOW_V1": (
                                    os.environ.get("NOVEL_CANONICAL_SHADOW_V1", "0") == "1"
                                ),
                                "NOVEL_RELIABILITY_TRACE": (
                                    os.environ.get("NOVEL_RELIABILITY_TRACE", "0") == "1"
                                ),
                            },
                            "build_fingerprint": current_runtime.build_fingerprint_sha256,
                            "execution_config_fingerprint": (
                                current_runtime.execution_config_fingerprint_sha256
                            ),
                            "runtime_execution_fingerprint": (
                                current_runtime.execution_fingerprint_sha256
                            ),
                            "origin_binding": origin,
                            "executor_binding": executor,
                            "current_source_revalidation": runtime_source_revalidation(
                                process_build, current_build,
                                process_children=process_children,
                                current_children=current_children,
                            ),
                            "sidecar_validation": sidecars,
                            "contradictory_binding": bool(binding_set["conflicts"]),
                            "canary_root_validation": validate_canary_root(
                                canary_root,
                                stable_root_identity=plan["isolation"]["stable_root_identity"],
                                plan_sha256=plan["plan_sha256"],
                                run_namespace=plan["isolation"]["run_namespace"],
                                live_roots=all_live_roots,
                            ),
                        }
                        boundary_capture_micros.append(
                            (time.perf_counter_ns() - capture_started) // 1000
                        )
                        return result

                    verifier = ExactBoundaryVerifier(
                        snapshot_supplier=snapshot_supplier,
                        cli_approved_plan_sha256=approved_plan_sha256,
                        initial_plan_sha256=plan["plan_sha256"],
                        initial_approval_sha256=approval["approval_sha256"],
                        initial_launcher_sha256=plan["launcher_sha256"],
                        initial_workload_manifest_hash=plan["workload_manifest_hash"],
                    )
                    limits = BudgetLimits(
                        maximum_model_calls_per_run=plan["budgets"]["maximum_model_calls_per_run"],
                        maximum_total_model_calls=plan["budgets"]["maximum_total_model_calls"],
                        maximum_input_tokens=plan["budgets"]["maximum_input_tokens"],
                        maximum_output_tokens=plan["budgets"]["maximum_output_tokens"],
                        maximum_estimated_cost_microunits=(
                            plan["budgets"]["maximum_estimated_cost_microunits"]
                        ),
                        maximum_elapsed_seconds=plan["budgets"]["maximum_elapsed_seconds"],
                    )
                    budget = AtomicBudgetLedger(limits)
                    gate = TwoPhaseGate(
                        wait_timeout_seconds=plan["budgets"]["gate_wait_timeout_seconds"],
                    )
                    gated = PreflightGatedGateway(
                        DeterministicShortBoundary(), gate=gate, verifier=verifier,
                        budget_ledger=budget,
                        route_policy=ApprovedRoutePolicy(plan["approved_routes"]),
                        route_resolver=route_resolver, stage_resolver=stage_resolver,
                    )
                    canary_service = C0AFakeWorkflowService(
                        db, app.state.projects, gated, app.state.skill_gate,
                        canary_root / "crewai", local_nlp=app.state.local_nlp,
                        references=app.state.references,
                    )
                    app.state.workflows = canary_service
                    public_route = next(
                        route for route in _effective_routes(app)
                        if getattr(route, "name", None) == "start_short_run"
                    )
                    if not str(getattr(public_route, "path", "")).endswith(
                        "/projects/{project_id}/runs/short"
                    ):
                        raise RuntimeError("official_short_api_route_changed")
                    if getattr(public_route, "status_code", None) != 202:
                        raise RuntimeError("official_short_api_status_changed")
                    accepted = await public_route.endpoint(
                        project_id, SimpleNamespace(app=app),
                    )
                    run_id = str(accepted["id"])
                    run_holder["run_id"] = run_id
                    gate_started_ns = time.perf_counter_ns()
                    try:
                        await gated.run_initial_preflight()
                        gate_elapsed_micros = (
                            time.perf_counter_ns() - gate_started_ns
                        ) // 1000
                        final_run = await asyncio.wait_for(
                            app.state.run_tasks.wait(run_id),
                            timeout=plan["budgets"]["maximum_elapsed_seconds"],
                        )
                        if (
                            final_run.get("status") != "completed"
                            and canary_service.canary_last_exception is not None
                        ):
                            workflow_exception = canary_service.canary_last_exception
                    except BaseException as exc:
                        workflow_exception = exc
                        final_run = db.get_run(run_id) or {}
                        if final_run.get("status") not in TERMINAL_STATUSES:
                            app.state.run_tasks.cancel(run_id)
                            try:
                                await app.state.run_tasks.wait(run_id)
                            except BaseException:
                                pass
                    origin, executor, binding_set = _binding_pair(db, run_id)
                    bindings_observed = {
                        "binding_status": binding_set["binding_status"],
                        "origin_definition_sha256": (
                            origin or {}
                        ).get("binding_definition_sha256"),
                        "executor_definition_sha256": (
                            executor or {}
                        ).get("binding_definition_sha256"),
                        "runtime_execution_fingerprint": (
                            executor or {}
                        ).get("runtime_execution_fingerprint"),
                        "conflict_count": len(binding_set["conflicts"]),
                    }
            provider_client_count = provider_calls["count"]
        gated.credential_lookup_count = secrets.lookup_count
        gated.provider_client_creation_count = provider_client_count
        gated.network_call_count = sentinel.network_call_count
        counters = gated.counters()
        budget_snapshot = budget.snapshot()
    after = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
        incident_roots=incident_roots,
    )
    if not parity_equal(before, after):
        raise RuntimeError("live_artifact_parity_changed")
    status = str(final_run.get("status") or "unknown")
    if status == "completed":
        outcome = CanaryOutcome.WORKFLOW_COMPLETED.value
        reason_code = "official_short_api_fake_workflow_completed"
    elif isinstance(workflow_exception, CanaryBoundaryAbort):
        outcome = CanaryOutcome.CANARY_BLOCKED_PRE_PROVIDER.value
        reason_code = workflow_exception.reason_code
    elif status in {"waiting_provider", "waiting_user"}:
        outcome = CanaryOutcome.CONTROLLED_NONTERMINAL.value
        reason_code = f"controlled_{status}"
    elif workflow_exception is not None:
        outcome = CanaryOutcome.WORKFLOW_TERMINAL.value
        reason_code = "isolated_short_workflow_terminal"
    else:
        outcome = CanaryOutcome.CANARY_INFRASTRUCTURE_FAILURE.value
        reason_code = "canary_outcome_unknown"
    project = app.state.projects.get(project_id)
    artifacts = tree_manifest(project.path)
    full_elapsed_micros = (time.perf_counter_ns() - started_ns) // 1000
    evidence = build_canary_evidence_package_v1({
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval["approval_sha256"],
        "launcher_sha256": launcher["launcher_sha256"],
        "outcome": {
            "value": outcome, "reason_code": reason_code,
            "final_run_status": status,
            "workflow_terminal_counted": outcome == CanaryOutcome.WORKFLOW_TERMINAL.value,
            "production_incident_counted": False,
            "exception_type": (
                type(workflow_exception).__name__
                if workflow_exception is not None else None
            ),
            "stage_failure_types": list(
                canary_service.canary_stage_failure_types
            ),
        },
        "runtime_fingerprints": {
            "build": plan["approved_build_fingerprint"],
            "execution_config": plan["approved_execution_config_fingerprint"],
            "runtime_execution": plan["expected_runtime_execution_fingerprint"],
            "per_boundary_status": "exact" if verifier and verifier.receipts else "unknown",
        },
        "origin_executor_binding": bindings_observed,
        "preflight_receipts": list(verifier.receipts if verifier else []),
        "model_boundary_ledger": list(gated.boundary_ledger if gated else []),
        "budget_ledger": budget_snapshot,
        "counters": counters,
        "live_parity": {
            "status": "exact", "before_sha256": before["parity_sha256"],
            "after_sha256": after["parity_sha256"],
            "live_active_run_count_before": 0,
        },
        "canary_artifacts": {
            "tree_sha256": artifacts["tree_sha256"],
            "file_count": artifacts["file_count"],
            "official_api_status": 202,
            "run_id_hash": _hash_identifier("run", run_id),
            "project_id_hash": _hash_identifier("project", project_id),
        },
        "performance": {
            "full_run_micros": full_elapsed_micros,
            "initial_gate_micros": gate_elapsed_micros,
            "boundary_fingerprint_capture": _percentiles(boundary_capture_micros),
        },
        "coverage_gaps": [
            "real_provider_capability_unverified",
            "real_provider_pricing_unverified",
            "packaged_runtime_not_executed",
            "crewai_outer_wrapper_not_executed",
            "13k_20k_30k_capacity_not_claimed",
        ],
        "approval_reservation_definition_sha256": reservation_receipt[
            "definition_sha256"
        ],
        "raw_content_included": False,
    })
    report_path = canary_root / "reports" / "c0a-evidence-v1.json"
    report_path.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    consumption = store.consume(approval, evidence["evidence_sha256"])
    return {
        "evidence": evidence,
        "consumption_receipt": consumption,
        "report_path": report_path,
    }
