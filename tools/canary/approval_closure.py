"""Complete, inert C0B-SMOKE-1 Approval evidence closure."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import (
    collect_runtime_fingerprint,
    process_captured_build_fingerprint,
    runtime_source_revalidation,
)
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
    verify_definition,
)

from .approval_store import ApprovalConsumptionStore
from .artifact_hash import file_sha256
from .contracts import (
    SMOKE_APPROVAL_CANDIDATE_SCHEMA,
    SMOKE_APPROVAL_SCOPE,
    validate_canary_approval_document,
    validate_canary_experiment_plan_v1,
)
from .descriptors import (
    copy_production_execution_config,
    production_route_identity,
    production_route_manifest_hashes,
)
from .environment import c0a_environment
from .hash_manifest import validate_import_closure
from .provider_matrix import (
    production_mirror_manifest,
    production_price_catalog,
    protocol_evidence_matrix,
    validate_production_mirror,
)
from .topology import C0BElapsedBudgetV1, c0b_short_call_topology_v1


SCHEMA = "C0BApprovalClosureValidationReceiptV1"
DOMAIN = "novel-flywheel-c0b-approval-closure-validation-v1"
CHECK_NAMES = (
    "plan_canonical_hash", "approval_canonical_hash", "launcher_bytes_hash",
    "workload_bytes_hash", "production_source_byte_revalidation",
    "build_fingerprint", "build_child_manifests", "execution_config_fingerprint",
    "runtime_execution_fingerprint", "provider_descriptor_manifest",
    "role_route_binding_manifest", "protocol_route_evidence",
    "feature_flag_snapshot", "phase1b_disabled", "pricing_evidence_manifest",
    "happy_relay_group", "monetary_budget_definition", "call_budget_definition",
    "token_budget_definition", "elapsed_budget_definition",
    "stop_condition_manifest", "canary_root_identity_layout",
    "approval_execution_window", "approval_cohort_single_use",
    "external_action_authorization",
)
EXPECTED_STOPS = (
    "first_terminal_failure", "first_controlled_provider_capability_outcome",
    "fingerprint_mismatch", "budget_exceeded", "route_mismatch",
    "price_schedule_mismatch", "approval_expired",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("closure_input_not_object")
    return value


def _actual_semantic_routes(db: Database) -> list[dict[str, str]]:
    rows = []
    for route in production_mirror_manifest()["routes"]:
        role = str(route["role"])
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


def _root_candidate_status(
    root: Path, *, live_database_path: Path, live_project_root: Path,
) -> str:
    candidate = root.resolve(strict=False)
    for live in (live_database_path.parent.resolve(), live_project_root.resolve()):
        try:
            candidate.relative_to(live)
            return "overlap"
        except ValueError:
            pass
        try:
            live.relative_to(candidate)
            return "overlap"
        except ValueError:
            pass
    if not root.exists():
        return "valid_absent_candidate"
    return "valid_empty_candidate" if not any(root.iterdir()) else "occupied"


def _result(name: str, exact: bool, reason: str, definition_hash: str | None = None) -> dict:
    return {
        "name": name,
        "status": "exact" if exact else "blocked",
        "reason_code": "exact" if exact else reason,
        "definition_sha256": definition_hash,
    }


def _validate_c0b_approval_closure(
    *, plan_path: Path, approval_path: Path, packet_path: Path,
    workload_fixture_path: Path, live_database_path: Path,
    live_project_root: Path, canary_root: Path,
    approval_ledger_root: Path, cli_approved_plan_sha256: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate all local evidence without resolving credentials/providers/network."""

    checks: list[dict[str, Any]] = []
    plan = validate_canary_experiment_plan_v1(_read(plan_path))
    checks.append(_result(
        CHECK_NAMES[0], plan["plan_sha256"] == cli_approved_plan_sha256,
        "cli_approved_plan_hash_mismatch", plan["plan_sha256"],
    ))
    approval_input = _read(approval_path)
    candidate_document = (
        approval_input.get("schema") == SMOKE_APPROVAL_CANDIDATE_SCHEMA
    )
    expected_scope = (
        SMOKE_APPROVAL_SCOPE if candidate_document
        else "C0B_REAL_PROVIDER_PATH_REACHABILITY"
    )
    approval, approval_identity, approval_kind = validate_canary_approval_document(
        approval_input,
        expected_scope=expected_scope,
        expected_plan_sha256=plan["plan_sha256"],
        expected_launcher_sha256=plan["launcher_sha256"],
        now=now,
    )
    checks.append(_result(
        CHECK_NAMES[1], True, "approval_hash_mismatch", approval_identity,
    ))
    packet = _read(packet_path)
    launcher = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=plan["approved_dependency_manifest"]["third_party"],
    )
    checks.append(_result(
        CHECK_NAMES[2], launcher["launcher_sha256"] == plan["launcher_sha256"],
        "launcher_changed_during_canary", launcher["launcher_sha256"],
    ))
    fixture_hash = file_sha256(workload_fixture_path)
    workload = plan["workloads"][0]
    checks.append(_result(
        CHECK_NAMES[3], fixture_hash == workload["fixture_sha256"]
        == packet.get("workload_sha256"), "workload_hash_mismatch", fixture_hash,
    ))

    fixture = _read(workload_fixture_path)
    with tempfile.TemporaryDirectory(prefix="novel-c0b-closure-") as temporary:
        root = Path(temporary)
        with c0a_environment(root):
            db = Database(root / "app.db")
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
            runtime = collect_runtime_fingerprint(db, project_id=project.id)
            process_build, process_children = process_captured_build_fingerprint()
            source = runtime_source_revalidation(
                process_build, runtime.build,
                process_children=process_children,
                current_children=runtime.children,
            )
            route_hashes = production_route_manifest_hashes(db)
            semantic_routes = _actual_semantic_routes(db)

    checks.append(_result(
        CHECK_NAMES[4], source["comparison_status"] == "exact"
        and source.get("production_source_clean") is not False,
        "production_source_revalidation_failed",
        runtime.build_fingerprint_sha256,
    ))
    checks.append(_result(
        CHECK_NAMES[5], runtime.build_fingerprint_sha256
        == plan["approved_build_fingerprint"] == packet.get("build_fingerprint"),
        "build_fingerprint_mismatch", runtime.build_fingerprint_sha256,
    ))
    child_exact = all(verify_definition(item) for item in runtime.children)
    refs = runtime.build["payload"]["child_definitions"]
    child_index = {(item["schema"], item["definition_sha256"]) for item in runtime.children}
    child_exact = child_exact and all(
        (ref["schema"], ref["definition_sha256"]) in child_index
        for ref in refs.values()
    )
    child_hash = domain_sha256(
        "novel-flywheel-c0b-build-child-manifests-v1",
        sorted(refs.values(), key=lambda item: (item["schema"], item["definition_sha256"])),
    )
    checks.append(_result(CHECK_NAMES[6], child_exact, "build_child_manifest_mismatch", child_hash))
    checks.append(_result(
        CHECK_NAMES[7], runtime.execution_config_fingerprint_sha256
        == plan["approved_execution_config_fingerprint"]
        == packet.get("execution_config_fingerprint"),
        "execution_config_fingerprint_mismatch",
        runtime.execution_config_fingerprint_sha256,
    ))
    checks.append(_result(
        CHECK_NAMES[8], runtime.execution_fingerprint_sha256
        == plan["expected_runtime_execution_fingerprint"]
        == packet.get("runtime_execution_fingerprint"),
        "runtime_execution_fingerprint_mismatch", runtime.execution_fingerprint_sha256,
    ))
    checks.append(_result(
        CHECK_NAMES[9], route_hashes["provider_descriptor_definition_sha256"]
        == plan["provider_descriptor_definition_sha256"],
        "provider_descriptor_manifest_mismatch",
        route_hashes["provider_descriptor_definition_sha256"],
    ))
    checks.append(_result(
        CHECK_NAMES[10], route_hashes["role_binding_manifest_definition_sha256"]
        == plan["role_binding_manifest_definition_sha256"],
        "role_route_binding_manifest_mismatch",
        route_hashes["role_binding_manifest_definition_sha256"],
    ))
    route_validation = validate_production_mirror(semantic_routes)
    protocol = protocol_evidence_matrix(semantic_routes)
    checks.append(_result(
        CHECK_NAMES[11], route_validation["status"] == "EXACT_MATCH"
        and all(item["status"] in {"EXACT_MATCH", "PARTIAL_EVIDENCE"}
                for item in protocol["entries"]),
        "protocol_route_evidence_blocked",
        route_validation["expected_definition_sha256"],
    ))
    expected_flags = {
        "NOVEL_SHORT_CANONICAL_V2": False,
        "project_short_canonical_v2": False,
        "NOVEL_CANONICAL_SHADOW_V1": False,
        "NOVEL_RELIABILITY_TRACE": True,
    }
    checks.append(_result(
        CHECK_NAMES[12], plan["feature_flag_snapshot"] == expected_flags,
        "feature_flag_snapshot_mismatch",
        domain_sha256("novel-flywheel-c0b-feature-flags-v1", expected_flags),
    ))
    flags = plan["feature_flag_snapshot"]
    checks.append(_result(
        CHECK_NAMES[13], flags.get("NOVEL_SHORT_CANONICAL_V2") is False
        and flags.get("project_short_canonical_v2") is False,
        "phase1b_enabled",
    ))
    prices = production_price_catalog().definitions()
    price_hash = domain_sha256("novel-flywheel-c0b-price-catalog-v1", prices)
    checks.append(_result(
        CHECK_NAMES[14], price_hash == plan["budgets"]["price_catalog_sha256"]
        and prices == packet.get("price_catalog"),
        "pricing_evidence_manifest_mismatch", price_hash,
    ))
    happy = [item for item in prices if item["provider"] == "happy"
             and item["model"] == "qwen-max-thinking"]
    happy_exact = len(happy) == 1 and all((
        happy[0]["relay_group"] == "default",
        happy[0]["currency"] == "USD",
        happy[0]["input_rate_per_unit"] == "1",
        happy[0]["output_rate_per_unit"] == "4",
        happy[0]["reasoning_token_rule"] == "separate_if_reported",
    ))
    checks.append(_result(CHECK_NAMES[15], happy_exact, "happy_relay_group_or_price_mismatch", happy[0]["evidence_sha256"] if happy else None))

    approved_budget = approval.get("approved_budget") or {}
    budget_hash = approved_budget.get("definition_sha256")
    outer = plan["budgets"]
    money = outer["monetary_budget"]
    packet_budget = packet.get("approval_budget")
    monetary_exact = bool(approved_budget) and packet_budget == approved_budget and all((
        approved_budget["maximum_usd_cost_microunits"] <= money["maximum_usd_cost_microunits"],
        approved_budget["maximum_cny_cost_microunits"] <= money["maximum_cny_cost_microunits"],
    ))
    if candidate_document:
        monetary_exact = monetary_exact and all((
            approved_budget["maximum_usd_cost_microunits"] == 20_000_000,
            approved_budget["maximum_cny_cost_microunits"] == 50_000_000,
        ))
    monetary_hash = (
        approval["monetary_budget_definition_sha256"]
        if candidate_document else budget_hash
    )
    checks.append(_result(
        CHECK_NAMES[16], monetary_exact,
        "monetary_budget_definition_mismatch", monetary_hash,
    ))
    call_exact = bool(approved_budget) and all((
        approved_budget["maximum_model_calls_per_run"] == 48,
        approved_budget["maximum_total_model_calls"] == 48,
        approved_budget["maximum_model_calls_per_run"] <= outer["maximum_model_calls_per_run"],
        approved_budget["maximum_total_model_calls"] <= outer["maximum_total_model_calls"],
    ))
    call_hash = (
        approval["call_budget_definition_sha256"]
        if candidate_document else budget_hash
    )
    checks.append(_result(
        CHECK_NAMES[17], call_exact, "call_budget_definition_mismatch", call_hash,
    ))
    token_exact = bool(approved_budget) and all((
        approved_budget["maximum_input_tokens"] <= outer["maximum_input_tokens"],
        approved_budget["maximum_output_tokens"] <= outer["maximum_output_tokens"],
    ))
    if candidate_document:
        token_exact = token_exact and all((
            approved_budget["maximum_input_tokens"] == 1_000_000,
            approved_budget["maximum_output_tokens"] == 1_000_000,
            approval["maximum_output_tokens_per_call"] == 32_000,
        ))
    token_hash = (
        approval["token_budget_definition_sha256"]
        if candidate_document else budget_hash
    )
    checks.append(_result(
        CHECK_NAMES[18], token_exact,
        "token_budget_definition_mismatch", token_hash,
    ))
    topology = c0b_short_call_topology_v1()
    elapsed = C0BElapsedBudgetV1.from_topology(topology).definition()
    elapsed_exact = bool(approved_budget) and all((
        outer["call_topology_sha256"] == topology["definition_sha256"],
        outer["elapsed_budget_sha256"] == elapsed["definition_sha256"],
        approved_budget["maximum_elapsed_seconds"] <= outer["maximum_elapsed_seconds"],
    ))
    if candidate_document:
        elapsed_exact = elapsed_exact and (
            approved_budget["maximum_elapsed_seconds"] == 7_200
        )
    elapsed_hash = (
        approval["elapsed_budget_definition_sha256"]
        if candidate_document else elapsed["definition_sha256"]
    )
    checks.append(_result(
        CHECK_NAMES[19], elapsed_exact,
        "elapsed_budget_definition_mismatch", elapsed_hash,
    ))
    stop_hash = domain_sha256("novel-flywheel-c0b-stop-conditions-v1", list(EXPECTED_STOPS))
    checks.append(_result(
        CHECK_NAMES[20], tuple(plan["stop_conditions"]) == EXPECTED_STOPS,
        "stop_condition_manifest_mismatch", stop_hash,
    ))
    root_status = _root_candidate_status(
        canary_root, live_database_path=live_database_path,
        live_project_root=live_project_root,
    )
    checks.append(_result(
        CHECK_NAMES[21], root_status in {"valid_absent_candidate", "valid_empty_candidate"},
        "canary_root_candidate_invalid",
        plan["isolation"]["stable_root_identity"],
    ))
    checks.append(_result(
        CHECK_NAMES[22], True, "approval_execution_window_invalid",
        approval_identity,
    ))
    replay = ApprovalConsumptionStore(approval_ledger_root).status(approval)
    replay_exact = replay["status"] == "unused" and approval["usage_status"] == "unused"
    checks.append(_result(
        CHECK_NAMES[23], replay_exact, "approval_replayed", approval_identity,
    ))
    actions = approval["authorized_actions"]
    names = ("credential_lookup", "provider_client_creation", "network", "paid_model_calls")
    all_false = all(actions.get(name) is False for name in names) and actions.get("fake_boundary") is False
    all_true = all(actions.get(name) is True for name in names) and actions.get("fake_boundary") is False and bool(approval.get("named_approver"))
    candidate_bindings_exact = True
    if candidate_document:
        policy = plan.get("smoke_1_policy") or {}
        budget_definitions = packet.get("budget_definitions") or {}
        candidate_bindings_exact = all((
            approval["approval_scope"] == SMOKE_APPROVAL_SCOPE,
            approval["approved_workload_sha256"] == fixture_hash,
            approval["approved_workload_manifest_hash"] == plan["workload_manifest_hash"],
            approval["approved_build_fingerprint"] == runtime.build_fingerprint_sha256,
            approval["approved_execution_config_fingerprint"] == runtime.execution_config_fingerprint_sha256,
            approval["approved_runtime_execution_fingerprint"] == runtime.execution_fingerprint_sha256,
            approval["provider_descriptor_hash"] == route_hashes["provider_descriptor_definition_sha256"],
            approval["model_role_binding_manifest_hash"] == route_hashes["role_binding_manifest_definition_sha256"],
            approval["pricing_evidence_manifest_hash"] == price_hash,
            approval["feature_flag_snapshot_hash"] == domain_sha256(
                "novel-flywheel-c0b-feature-flags-v1", expected_flags,
            ),
            approval["stop_condition_manifest_hash"] == stop_hash,
            approval["canary_root_identity_candidate"] == plan["isolation"]["stable_root_identity"],
            approval["expected_model_calls"] == 16,
            approval["maximum_total_model_calls"] == 48,
            approval["first_terminal_stop"] is True,
            approval["resume_after_terminal"] is False,
            approval["phase1b_enabled"] is False,
            approval["execution_authorized"] is False,
            packet.get("plan_sha256") == plan["plan_sha256"],
            packet.get("approval_candidate_sha256") == approval_identity,
            packet.get("feature_flag_snapshot_hash") == approval["feature_flag_snapshot_hash"],
            packet.get("stop_condition_manifest_hash") == approval["stop_condition_manifest_hash"],
            policy.get("approval_scope") == SMOKE_APPROVAL_SCOPE,
            policy.get("expected_model_calls") == 16,
            policy.get("maximum_total_model_calls") == 48,
            policy.get("maximum_input_tokens") == 1_000_000,
            policy.get("maximum_output_tokens") == 1_000_000,
            policy.get("maximum_output_tokens_per_call") == 32_000,
            policy.get("maximum_usd_cost_microunits") == 20_000_000,
            policy.get("maximum_cny_cost_microunits") == 50_000_000,
            policy.get("maximum_elapsed_seconds") == 7_200,
            policy.get("first_terminal_stop") is True,
            policy.get("resume_after_terminal") is False,
            policy.get("budget_definition_hashes") == {
                name: budget_definitions.get(name, {}).get("definition_sha256")
                for name in ("call", "token", "monetary", "elapsed")
            },
            approval["call_budget_definition_sha256"] == budget_definitions.get("call", {}).get("definition_sha256"),
            approval["token_budget_definition_sha256"] == budget_definitions.get("token", {}).get("definition_sha256"),
            approval["monetary_budget_definition_sha256"] == budget_definitions.get("monetary", {}).get("definition_sha256"),
            approval["elapsed_budget_definition_sha256"] == budget_definitions.get("elapsed", {}).get("definition_sha256"),
        ))
    checks.append(_result(
        CHECK_NAMES[24], (all_false or all_true) and candidate_bindings_exact,
        "external_action_authorization_incoherent",
        domain_sha256("novel-flywheel-c0b-external-actions-v1", actions),
    ))
    if [item["name"] for item in checks] != list(CHECK_NAMES):
        raise AssertionError("closure_check_order_invalid")
    counters = {
        "credential_lookup_count": 0, "provider_client_creation_count": 0,
        "network_call_count": 0, "model_call_count": 0,
        "paid_model_call_count": 0,
    }
    body = {
        "schema": SCHEMA, "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "overall_status": "exact" if all(item["status"] == "exact" for item in checks) else "blocked",
        "ordered_checks": checks,
        "definition_hashes": {
            item["name"]: item["definition_sha256"] for item in checks
            if item["definition_sha256"] is not None
        },
        "external_action_counters": counters,
        "approval_document_kind": approval_kind,
        "approval_identity_sha256": approval_identity,
        "approval_state": "disabled_candidate" if all_false else "authorized_candidate",
        "canary_root_candidate_status": root_status,
        "validated_at_policy": "caller_supplied_or_current_utc",
    }
    body["validation_receipt_sha256"] = domain_sha256(DOMAIN, body)
    return body


def validate_c0b_approval_closure(**kwargs: Any) -> dict[str, Any]:
    """Return a receipt even when an early canonical/authorization check fails."""

    try:
        return _validate_c0b_approval_closure(**kwargs)
    except Exception as exc:
        stable_reason = getattr(exc, "reason_code", None)
        known_targets = {
            "plan_hash_mismatch": "plan_canonical_hash",
            "cli_approved_plan_hash_mismatch": "plan_canonical_hash",
            "phase1b_environment_flag_enabled": "phase1b_disabled",
            "phase1b_project_flag_enabled": "phase1b_disabled",
            "approval_hash_mismatch": "approval_canonical_hash",
            "approval_candidate_hash_mismatch": "approval_canonical_hash",
            "approval_candidate_plan_mismatch": "plan_canonical_hash",
            "approval_candidate_launcher_mismatch": "launcher_bytes_hash",
            "approval_candidate_scope_mismatch": "external_action_authorization",
            "approval_candidate_window_already_started": "approval_execution_window",
            "approval_expired": "approval_execution_window",
            "approval_outside_execution_window": "approval_execution_window",
            "approval_already_used": "approval_cohort_single_use",
            "approval_already_reserved": "approval_cohort_single_use",
            "approval_already_consumed": "approval_cohort_single_use",
            "launcher_changed_during_canary": "launcher_bytes_hash",
        }
        reason = (
            str(stable_reason) if stable_reason in known_targets
            else f"closure_validation_failed:{type(exc).__name__}"
        )
        target = known_targets.get(str(stable_reason), "production_source_byte_revalidation")
        checks = [{
            "name": name,
            "status": "blocked" if name == target else "not_evaluated",
            "reason_code": reason if name == target else "upstream_check_blocked",
            "definition_sha256": None,
        } for name in CHECK_NAMES]
        counters = {
            "credential_lookup_count": 0, "provider_client_creation_count": 0,
            "network_call_count": 0, "model_call_count": 0,
            "paid_model_call_count": 0,
        }
        body = {
            "schema": SCHEMA, "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "overall_status": "blocked", "ordered_checks": checks,
            "definition_hashes": {}, "external_action_counters": counters,
            "approval_document_kind": "unknown",
            "approval_identity_sha256": None,
            "approval_state": "unknown", "canary_root_candidate_status": "unknown",
            "validated_at_policy": "caller_supplied_or_current_utc",
        }
        body["validation_receipt_sha256"] = domain_sha256(DOMAIN, body)
        return body
