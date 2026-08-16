"""Isolated C0B Short runner delegating to the production ModelGateway.

Importing this module is inert. Credential and provider resolution occur only
after the first boundary has passed budget, Runtime preflight, and exact final
authorization.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Iterable
from datetime import datetime

from novel_flywheel.app import create_app
from novel_flywheel.context_policy import classify_model_failure
from novel_flywheel.db import Database
from novel_flywheel.models import ModelGateway
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.runtime_fingerprint import (
    DefinitionStore, canonical_runtime_bindings, collect_runtime_fingerprint,
    collect_runtime_fingerprint_v2,
    process_captured_build_fingerprint, runtime_source_revalidation,
    verify_runtime_binding_sidecars,
)
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.secrets import KeyringSecretStore

from .approval_store import ApprovalConsumptionStore
from .artifact_binding import observe_last_legal_bindings
from .artifact_hash import file_sha256, live_parity_manifest, parity_equal, tree_manifest
from .budget import AtomicBudgetLedger, BudgetLimits
from .contracts import (
    SMOKE_SIGNED_APPROVAL_SCHEMA, SMOKE_APPROVAL_SCOPE,
    validate_canary_approval_document, validate_canary_experiment_plan_v1,
    validate_signed_smoke_approval_plan_v1,
    validate_signed_smoke_approval_sources_v1,
)
from .approval_dispatch import (
    profile_for_plan, validate_registered_approval_document,
    validate_registered_signed_plan, validate_registered_signed_sources,
)
from .approval_profiles import SHORT_COMPLETION_PROFILE_ID
from .descriptors import (
    copy_production_execution_config, production_route_identity,
    production_route_manifest_hashes,
)
from .dry_run import (
    C0AFakeWorkflowService, TERMINAL_STATUSES, _binding_pair,
    _create_project_and_outline, _effective_routes, _hash_identifier,
    _live_active_run_count, _local_execution_scope, _percentiles, _read_json,
    write_sanitized_skill_fixtures,
)
from .environment import c0a_environment
from .evidence import build_canary_evidence_package_v1
from .gate import (
    CanaryAbortKind, CanaryBoundaryAbort, PreflightGatedGateway, TwoPhaseGate,
)
from .goal_stop import (
    ObservationGoalLatch, STOP_OUTCOME, STOP_REASON,
    capture_reliability_trace_goal,
)
from .hash_manifest import validate_import_closure
from .isolation import create_canary_root, validate_canary_root
from .monetary import CanaryMonetaryBudgetV1
from .outcomes import CanaryOutcome, outcome_for_boundary_abort
from .packet import APPROVED_THIRD_PARTY
from .preflight import (
    CanaryPreflightBlocked, ExactBoundaryVerifier,
    validate_execution_config_prelaunch_v2,
)
from .provider_matrix import production_price_catalog
from .real_boundary import (
    classify_provider_capability_failure,
    FinalAuthorizationLatch, GuardedCredentialStore, GuardedProductionGateway,
    GuardedProviderRegistry, RealBoundaryCounters,
)
from .route_policy import ApprovedRoutePolicy


def _strict_tool_observation_summary(root: Path, profile) -> dict[str, Any] | None:
    if not profile.required_target_filter:
        return None
    matches: list[dict[str, Any]] = []
    damaged = 0
    for path in root.rglob("_reliability-trace-v1.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                damaged += 1
                continue
            if event.get("event_type") != "diagnostic_strict_tool_shape":
                continue
            payload = event.get("payload") or {}
            if payload.get("target_status") != "target":
                continue
            matches.append({
                "observation_sha256": payload.get("observation_sha256"),
                "shape_correlation_sha256": payload.get("shape_correlation_sha256"),
                "observation_status": payload.get("observation_status"),
                "strict_tool_decision": payload.get("strict_tool_decision"),
                "strict_tool_failure_code": payload.get("strict_tool_failure_code"),
                "stage_id": event.get("stage_id"),
            })
    outcome = (
        "TARGET_STRICT_TOOL_SHAPE_OBSERVED" if matches
        else "TARGET_OBSERVATION_UNAVAILABLE" if damaged
        else "TARGET_NOT_REACHED"
    )
    return {
        "observation_goal_outcome": outcome,
        "target_observation_count": len(matches),
        "damaged_trace_line_count": damaged,
        "observations": matches,
        "raw_content_included": False,
    }


def validate_c0b_real_run_approval(
    *, plan_path: Path, approval_path: Path, approved_plan_sha256: str,
    source_candidate_path: Path | None = None,
    source_authorization_patch_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Validate an exact executable Approval without crossing a paid boundary."""
    plan = validate_canary_experiment_plan_v1(_read_json(plan_path))
    if plan["plan_sha256"] != approved_plan_sha256:
        raise ValueError("cli_approved_plan_hash_mismatch")
    profile = profile_for_plan(plan)
    approval, identity, kind, _document_profile = validate_registered_approval_document(
        _read_json(approval_path), expected_profile_id=profile.profile_id,
        expected_scope=profile.approval_scope,
        expected_plan_sha256=plan["plan_sha256"],
        expected_launcher_sha256=plan["launcher_sha256"], now=now,
    )
    if kind == "final_approval_candidate":
        raise PermissionError("approval_candidate_not_executable")
    if kind in {"signed_smoke_approval", "signed_approval"}:
        if source_candidate_path is None or source_authorization_patch_path is None:
            raise PermissionError("signed_approval_source_document_missing")
        validate_registered_signed_sources(
            profile.profile_id, approval, _read_json(source_candidate_path),
            _read_json(source_authorization_patch_path), now=now,
        )
        validate_registered_signed_plan(profile.profile_id, approval, plan, now=now)
    actions = approval["authorized_actions"]
    if any(actions.get(name) is not True for name in (
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls",
    )) or actions.get("fake_boundary") is not False or not approval.get("named_approver"):
        raise PermissionError("real_mode_final_authorization_missing")
    return approval, identity


async def run_registered_real_run(
    *, plan_path: Path, approval_path: Path, approved_plan_sha256: str,
    source_candidate_path: Path | None = None,
    source_authorization_patch_path: Path | None = None,
    workload_fixture_path: Path, canary_root: Path,
    approval_ledger_root: Path, live_database_path: Path,
    live_project_root: Path, live_incident_roots: Iterable[Path] = (),
) -> dict:
    started_ns = time.perf_counter_ns()
    plan = validate_canary_experiment_plan_v1(_read_json(plan_path))

    def collect_for_plan(db: Database, project_id: str):
        if plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2":
            return collect_runtime_fingerprint_v2(db, project_id=project_id)
        return collect_runtime_fingerprint(db, project_id=project_id)
    profile = profile_for_plan(plan)
    approval, approval_identity = validate_c0b_real_run_approval(
        plan_path=plan_path, approval_path=approval_path,
        source_candidate_path=source_candidate_path,
        source_authorization_patch_path=source_authorization_patch_path,
        approved_plan_sha256=approved_plan_sha256,
    )
    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=plan["approved_dependency_manifest"]["third_party"],
    )
    if launcher["launcher_sha256"] != plan["launcher_sha256"]:
        raise ValueError("launcher_changed_during_canary")
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
            "schema": "CanaryWorkloadManifestV1", "fixture_sha256": fixture_sha,
            "workload_id": fixture["workload_id"],
            "expected_stages": fixture["expected_stages"],
        },
    )
    skill_root = canary_root / "skills"
    write_sanitized_skill_fixtures(skill_root)
    constraint = canary_root / "constraints-source.md"
    constraint.write_text(
        "# Canary Constraint\n\nUse only the confirmed formal outline.\n",
        encoding="utf-8",
    )
    latch = FinalAuthorizationLatch()
    guarded_secrets = GuardedCredentialStore(KeyringSecretStore(), latch=latch)
    capture_micros: list[int] = []
    workflow_exception: BaseException | None = None
    final_run: dict[str, Any] = {}
    run_id = ""
    project_id = ""
    bindings_observed: dict[str, Any] = {}
    gated: PreflightGatedGateway | None = None
    verifier: ExactBoundaryVerifier | None = None
    observation_goal_latch = (
        ObservationGoalLatch(
            receipt_path=canary_root / "reports" / "observation-goal-receipt-v1.json",
        )
        if "target_strict_tool_shape_exact_captured" in profile.stop_condition_policy
        else None
    )
    with (
        c0a_environment(canary_root, feature_flags=profile.required_flags()),
        capture_reliability_trace_goal(observation_goal_latch),
    ):
        db = Database(canary_root / "db" / "app.db")
        db.migrate()
        copy_production_execution_config(Database(live_database_path), db)
        references = ReferenceLibrary(db, canary_root / "references")
        app = create_app(
            db, guarded_secrets, skill_roots=[skill_root],
            workspace_root=canary_root / "projects",
            root_constraints=[constraint], reference_library=references,
        )
        async with app.router.lifespan_context(app):
            async with _local_execution_scope():
                project_id = _create_project_and_outline(fixture, app)
                db.set_feature_flag(
                    "short_canonical_v2", False,
                    scope_type="project", scope_id=project_id,
                )
                current = collect_for_plan(db, project_id)
                if current.build_fingerprint_sha256 != plan["approved_build_fingerprint"]:
                    raise RuntimeError("build_changed_before_launch")
                if plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2":
                    validate_execution_config_prelaunch_v2(
                        plan, current.execution_config_component_binding or {},
                    )
                elif current.execution_config_fingerprint_sha256 != plan[
                    "approved_execution_config_fingerprint"
                ]:
                    raise CanaryPreflightBlocked(
                        "execution_config_fingerprint_mismatch"
                    )
                manifest_hashes = production_route_manifest_hashes(db)
                for field, actual in manifest_hashes.items():
                    if actual != plan[field]:
                        raise RuntimeError(f"{field}_changed_before_launch")
                process_build, process_children = process_captured_build_fingerprint()
                run_holder: dict[str, str] = {}

                def stage_resolver(role: str) -> tuple[str, str]:
                    selected = run_holder.get("run_id")
                    run = db.get_run(selected) if selected else None
                    if run is None:
                        candidates = [
                            item for item in db.list_runs(project_id)
                            if item.get("workflow") == "short-story"
                            and item.get("status") not in TERMINAL_STATUSES
                        ]
                        run = candidates[0] if len(candidates) == 1 else None
                    if run is None:
                        raise RuntimeError("canary_run_identity_unavailable")
                    selected = str(run["id"])
                    run_holder["run_id"] = selected
                    return str(run.get("current_stage") or role), _hash_identifier("run", selected)

                def route_resolver(role: str, kind: str) -> dict[str, str]:
                    identity = production_route_identity(db, role, kind)
                    return {
                        key: identity[key] for key in (
                            "provider_descriptor_hash", "model_binding_hash", "protocol",
                        )
                    }

                def snapshot_supplier() -> dict:
                    capture_started = time.perf_counter_ns()
                    selected = run_holder.get("run_id")
                    if not selected:
                        raise RuntimeError("canary_run_identity_unavailable")
                    current_runtime = collect_for_plan(db, project_id)
                    origin, executor, binding_set = _binding_pair(db, selected)
                    sidecars = verify_runtime_binding_sidecars(
                        DefinitionStore(db.path.parent), executor,
                    ) if executor is not None else {
                        "valid": False, "validation_status": "invalid",
                        "reason_codes": ["executor_binding_missing"],
                    }
                    route_hashes = production_route_manifest_hashes(db)
                    expected_flags = profile.required_flags()
                    observed_flags = {
                        name: (
                            bool(db.feature_flag(
                                "short_canonical_v2", project_id=project_id,
                                default=False,
                            )["enabled"])
                            if name == "project_short_canonical_v2"
                            else os.environ.get(name, "0") == "1"
                        )
                        for name in expected_flags
                    }
                    result = {
                        "plan": _read_json(plan_path),
                        "approval": _read_json(approval_path),
                        **({
                            "approval_candidate": _read_json(source_candidate_path),
                            "authorization_patch": _read_json(
                                source_authorization_patch_path
                            ),
                        } if approval.get("schema") == profile.signed_approval_schema else {}),
                        "launcher_sha256": validate_import_closure(
                            Path(__file__).resolve().parent,
                            approved_third_party=APPROVED_THIRD_PARTY,
                        )["launcher_sha256"],
                        "workload_manifest_hash": workload_hash,
                        "workload_fixture_hashes": {
                            fixture["workload_id"]: file_sha256(workload_fixture_path),
                        },
                        **route_hashes,
                        "feature_flag_snapshot": observed_flags,
                        "build_fingerprint": current_runtime.build_fingerprint_sha256,
                        "execution_config_fingerprint": current_runtime.execution_config_fingerprint_sha256,
                        "runtime_execution_fingerprint": current_runtime.execution_fingerprint_sha256,
                        "execution_config_components": (
                            current_runtime.execution_config_component_binding
                        ),
                        "origin_binding": origin, "executor_binding": executor,
                        "current_source_revalidation": runtime_source_revalidation(
                            process_build, current_runtime.build,
                            process_children=process_children,
                            current_children=current_runtime.children,
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
                    capture_micros.append(
                        (time.perf_counter_ns() - capture_started) // 1000
                    )
                    return result

                verifier = ExactBoundaryVerifier(
                    snapshot_supplier=snapshot_supplier,
                    cli_approved_plan_sha256=approved_plan_sha256,
                    initial_plan_sha256=plan["plan_sha256"],
                    initial_approval_sha256=approval_identity,
                    initial_launcher_sha256=plan["launcher_sha256"],
                    initial_workload_manifest_hash=plan["workload_manifest_hash"],
                    expected_scope=profile.approval_scope,
                    expected_profile_id=profile.profile_id,
                )
                approved_budget = approval.get("approved_budget") or {}
                limits = BudgetLimits(
                    maximum_model_calls_per_run=min(
                        plan["budgets"]["maximum_model_calls_per_run"],
                        approved_budget.get("maximum_model_calls_per_run", 10**18),
                    ),
                    maximum_total_model_calls=min(
                        plan["budgets"]["maximum_total_model_calls"],
                        approved_budget.get("maximum_total_model_calls", 10**18),
                    ),
                    maximum_input_tokens=min(
                        plan["budgets"]["maximum_input_tokens"],
                        approved_budget.get("maximum_input_tokens", 10**18),
                    ),
                    maximum_output_tokens=min(
                        plan["budgets"]["maximum_output_tokens"],
                        approved_budget.get("maximum_output_tokens", 10**18),
                    ),
                    maximum_estimated_cost_microunits=0,
                    maximum_elapsed_seconds=min(
                        plan["budgets"]["maximum_elapsed_seconds"],
                        approved_budget.get("maximum_elapsed_seconds", 10**18),
                    ),
                )
                token_budget = AtomicBudgetLedger(limits)
                money = plan["budgets"]["monetary_budget"]
                monetary_budget = CanaryMonetaryBudgetV1(
                    maximum_usd_microunits=min(
                        money["maximum_usd_cost_microunits"],
                        approved_budget.get("maximum_usd_cost_microunits", 10**18),
                    ),
                    maximum_cny_microunits=min(
                        money["maximum_cny_cost_microunits"],
                        approved_budget.get("maximum_cny_cost_microunits", 10**18),
                    ),
                )
                catalog = production_price_catalog()

                def selected_price(request):
                    identity = production_route_identity(
                        db, request.role, request.route_kind,
                    )
                    group = "default"
                    return catalog.require(
                        identity["provider_alias"], identity["model_alias"], group,
                    )

                def estimated_cost(request):
                    price = selected_price(request)
                    return {price.currency: price.cost_microunits(
                        input_tokens=request.input_tokens, cached_input_tokens=0,
                        output_tokens=request.output_tokens, reasoning_tokens=0,
                    )}

                def actual_cost(request, receipt):
                    input_tokens = receipt.get("input_tokens")
                    output_tokens = receipt.get("output_tokens")
                    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
                        return None, False
                    cached = receipt.get("cached_input_tokens", 0)
                    reasoning = receipt.get("reasoning_tokens", 0)
                    if not isinstance(cached, int) or not isinstance(reasoning, int):
                        return None, False
                    price = selected_price(request)
                    return {price.currency: price.cost_microunits(
                        input_tokens=input_tokens, cached_input_tokens=cached,
                        output_tokens=output_tokens, reasoning_tokens=reasoning,
                    )}, True

                def final_authorizer(_request) -> None:
                    current_approval, current_identity = validate_c0b_real_run_approval(
                        plan_path=plan_path, approval_path=approval_path,
                        source_candidate_path=source_candidate_path,
                        source_authorization_patch_path=source_authorization_patch_path,
                        approved_plan_sha256=plan["plan_sha256"],
                    )
                    latch.authorize(current_identity)

                def budget_stop_context(_request) -> dict[str, Any]:
                    selected = run_holder.get("run_id")
                    if not selected:
                        return {
                            "current_executor_epoch": None,
                            "checkpoint": {"binding_status": "none_available"},
                            "last_legal_artifact": {"binding_status": "none_available"},
                        }
                    _origin, executor, _bindings = _binding_pair(db, selected)
                    return observe_last_legal_bindings(
                        db, run_id=selected, executor_binding=executor,
                    )

                boundary_counters = RealBoundaryCounters()

                def production_gateway() -> ModelGateway:
                    registry = GuardedProviderRegistry(
                        ProviderRegistry(db, guarded_secrets), latch=latch,
                        counters=boundary_counters,
                    )
                    return ModelGateway(db, registry)

                production = GuardedProductionGateway(
                    production_gateway, latch=latch,
                    counters=boundary_counters,
                )
                gated = PreflightGatedGateway(
                    production,
                    gate=TwoPhaseGate(
                        wait_timeout_seconds=plan["budgets"]["gate_wait_timeout_seconds"],
                    ),
                    verifier=verifier, final_authorizer=final_authorizer,
                    budget_ledger=token_budget, monetary_budget=monetary_budget,
                    route_policy=ApprovedRoutePolicy(plan["approved_routes"]),
                    route_resolver=route_resolver, stage_resolver=stage_resolver,
                    estimated_cost=estimated_cost, actual_cost=actual_cost,
                    workload_identifier_hash=workload_hash,
                    budget_stop_context_supplier=budget_stop_context,
                    observation_goal_latch=observation_goal_latch,
                )
                service = C0AFakeWorkflowService(
                    db, app.state.projects, gated, app.state.skill_gate,
                    canary_root / "crewai", local_nlp=app.state.local_nlp,
                    references=app.state.references,
                )
                app.state.workflows = service
                public_route = next(
                    route for route in _effective_routes(app)
                    if getattr(route, "name", None) == "start_short_run"
                )
                accepted = await public_route.endpoint(
                    project_id, SimpleNamespace(app=app),
                )
                run_id = str(accepted["id"])
                run_holder["run_id"] = run_id
                try:
                    await gated.run_initial_preflight()
                    final_run = await asyncio.wait_for(
                        app.state.run_tasks.wait(run_id),
                        timeout=plan["budgets"]["maximum_elapsed_seconds"],
                    )
                    if final_run.get("status") != "completed" and service.canary_last_exception:
                        workflow_exception = service.canary_last_exception
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
                    "origin_definition_sha256": (origin or {}).get("binding_definition_sha256"),
                    "executor_definition_sha256": (executor or {}).get("binding_definition_sha256"),
                    "conflict_count": len(binding_set["conflicts"]),
                }
        gated.credential_lookup_count = guarded_secrets.lookup_count
        gated.provider_client_creation_count = production.provider_client_creation_count
        gated.network_call_count = production.network_call_count
        gated.paid_model_call_count = production.paid_model_call_count
        counters = gated.counters()
        token_snapshot = token_budget.snapshot()
        monetary_snapshot = monetary_budget.snapshot()
    after = live_parity_manifest(
        database_path=live_database_path, project_root=live_project_root,
        incident_roots=incident_roots,
    )
    if not parity_equal(before, after):
        raise RuntimeError("live_artifact_parity_changed")
    status = str(final_run.get("status") or "unknown")
    failure_class = (
        classify_model_failure(workflow_exception)
        if isinstance(workflow_exception, Exception) else ""
    )
    capability_types = {
        "ContextCapacityPreflightError", "StructuredOutputCapabilityError",
        "ToolCapabilityError", "IncompleteModelOutputError",
    }
    controlled_capability: dict[str, Any] | None = None
    if observation_goal_latch is not None and observation_goal_latch.reached:
        outcome = STOP_OUTCOME
        reason_code = STOP_REASON
    elif status == "completed":
        outcome = CanaryOutcome.WORKFLOW_COMPLETED.value
        reason_code = "production_mirror_short_completed"
    elif workflow_exception is not None and (
        type(workflow_exception).__name__ in capability_types
        or failure_class == "provider_rejection"
    ):
        outcome = CanaryOutcome.CONTROLLED_NONTERMINAL.value
        reason_code = "CONTROLLED_PROVIDER_CAPABILITY_OUTCOME"
        last_boundary = gated.boundary_ledger[-1] if gated and gated.boundary_ledger else {}
        identity = production_route_identity(
            db, str(last_boundary.get("role") or "review"),
            str(last_boundary.get("route_kind") or "primary"),
        )
        controlled_capability = asdict(classify_provider_capability_failure(
            provider=identity["provider_alias"], model=identity["model_alias"],
            stage=str(last_boundary.get("stage") or "unknown"),
            role=str(last_boundary.get("role") or "unknown"),
            typed_status=type(workflow_exception).__name__,
            request_budget_sha256=domain_sha256(
                "novel-flywheel-c0b-request-budget-v1", {
                    "input_tokens": last_boundary.get("input_tokens"),
                    "output_tokens": last_boundary.get("output_tokens"),
                    "contract_sha256": last_boundary.get("contract_sha256"),
                },
            ),
            runtime_reaction=f"workflow_status:{status}",
            retry_fallback_outcome=(
                "last_observed_route:" + str(
                    last_boundary.get("route_kind") or "unknown"
                )
            ),
            first_divergent_boundary_ordinal=last_boundary.get("ordinal"),
        ))
    elif isinstance(workflow_exception, CanaryBoundaryAbort):
        mapped = outcome_for_boundary_abort(
            workflow_exception.kind.value, workflow_exception.reason_code,
        )
        outcome = mapped.outcome.value
        reason_code = mapped.reason_code
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
    short_completion_verification = None
    if profile.profile_id == SHORT_COMPLETION_PROFILE_ID:
        from .short_completion_verification import verify_short_completion_v1

        short_completion_verification = verify_short_completion_v1(
            project_root=project.path,
            run_root=project.path / "runs" / run_id,
            run_identity=run_id,
            workload_sha256=fixture_sha,
            workflow_final_status=status,
            live_parity_status="exact",
        )
    strict_tool_observation = _strict_tool_observation_summary(
        canary_root, profile,
    )
    if observation_goal_latch is not None:
        strict_tool_observation = observation_goal_latch.observation_summary(
            strict_tool_observation,
        )
    evidence = build_canary_evidence_package_v1({
        "profile_id": profile.profile_id,
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval_identity,
        "launcher_sha256": launcher["launcher_sha256"],
        "outcome": {
            "value": outcome, "reason_code": reason_code,
            "workflow_final_outcome": outcome,
            "short_completion_goal_outcome": (
                short_completion_verification.get("completion_goal_outcome")
                if short_completion_verification is not None else None
            ),
            "final_run_status": status,
            "workflow_terminal_counted": outcome == CanaryOutcome.WORKFLOW_TERMINAL.value,
            "production_incident_counted": False,
            "exception_type": type(workflow_exception).__name__ if workflow_exception else None,
            "safe_failure_class": failure_class or None,
        },
        "controlled_provider_capability": controlled_capability,
        "strict_tool_observation": strict_tool_observation,
        "canary_observation_goal": (
            observation_goal_latch.snapshot()
            if observation_goal_latch is not None else None
        ),
        "short_completion_verification": short_completion_verification,
        "runtime_fingerprints": {
            "build": plan["approved_build_fingerprint"],
            "execution_config": plan["approved_execution_config_fingerprint"],
            "runtime_execution": plan["expected_runtime_execution_fingerprint"],
            "per_boundary_status": "exact" if verifier and verifier.receipts else "unknown",
        },
        "origin_executor_binding": bindings_observed,
        "preflight_receipts": list(verifier.receipts if verifier else []),
        "model_boundary_ledger": list(gated.boundary_ledger if gated else []),
        "budget_ledger": {
            "tokens": token_snapshot, "monetary": monetary_snapshot,
        },
        "budget_stop": (
            workflow_exception.budget_stop_evidence
            if isinstance(workflow_exception, CanaryBoundaryAbort)
            and workflow_exception.kind == CanaryAbortKind.BUDGET_EXHAUSTED
            else None
        ),
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
            "full_run_micros": (time.perf_counter_ns() - started_ns) // 1000,
            "boundary_fingerprint_capture": _percentiles(capture_micros),
        },
        "coverage_gaps": [
            "relay_upstream_exact_version_unknown",
            "relay_public_max_output_unknown",
            "packaged_runtime_not_executed",
        ],
        "approval_reservation_definition_sha256": reservation_receipt["definition_sha256"],
        "raw_content_included": False,
    })
    report_path = canary_root / "reports" / f"{profile.profile_id}-real-evidence-v1.json"
    report_path.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    consumption = store.consume(approval, evidence["evidence_sha256"])
    return {"evidence": evidence, "consumption_receipt": consumption, "report_path": report_path}


async def run_c0b_real_run(**kwargs: Any) -> dict:
    """Backward-compatible C0B entry point over the registered runner."""
    return await run_registered_real_run(**kwargs)
