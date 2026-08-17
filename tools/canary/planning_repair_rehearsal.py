"""Independent fake-boundary rehearsal for the R1-PTR2 packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
from novel_flywheel.planning_repair_diagnostics import (
    DiagnosticDomainFindingV1,
    build_domain_validation_snapshot,
    build_finding_propagation_snapshot,
    build_output_limit_observation,
    capture_provider_content_block_snapshot,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .approval_profiles import (
    PLANNING_REPAIR_OBSERVATION_PROFILE_ID,
    approval_profile,
)
from .descriptors import copy_production_execution_config
from .environment import c0a_environment
from .network_sentinel import FailClosedNetworkSentinel
from .preflight import validate_execution_config_prelaunch_v2


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("planning_repair_rehearsal_input_invalid")
    return value


def run_rehearsal(
    *, plan_path: Path, fixture_path: Path, live_database_path: Path,
    isolated_root: Path,
) -> dict:
    plan = _read(plan_path)
    fixture = _read(fixture_path)
    profile = approval_profile(PLANNING_REPAIR_OBSERVATION_PROFILE_ID)
    sentinel = FailClosedNetworkSentinel()
    with c0a_environment(
        isolated_root, feature_flags=profile.required_flags(),
    ), sentinel:
        db = Database(isolated_root / "db" / "app.db")
        db.migrate()
        copy_production_execution_config(Database(live_database_path), db)
        project = ProjectStore(db, isolated_root / "projects").create(
            ProjectCreate(
                title=str(fixture["title"]), mode="short",
                genre=str(fixture["genre"]), premise=str(fixture["premise"]),
                target_words=int(fixture["target_words"]),
            )
        )
        db.set_feature_flag(
            "short_canonical_v2", False,
            scope_type="project", scope_id=project.id,
        )
        runtime = collect_runtime_fingerprint_v2(db, project_id=project.id)
        comparison = validate_execution_config_prelaunch_v2(
            plan, runtime.execution_config_component_binding or {},
        )
        context = ModelDiagnosticContextV1(
            project_root=isolated_root / "trace",
            run_id="synthetic-fake-boundary",
            stage="planning", boundary="planning_repair_patch",
            role="planning", route_kind="primary",
            contract_id="planning_repair_patch", contract_version=1,
            outer_retry_ordinal=1, inner_attempt_ordinal=1,
            provider_binding_sha256="a" * 64,
            model_binding_sha256="b" * 64,
            request_parameter_name="max_tokens",
        )
        finding = DiagnosticDomainFindingV1(
            rule_code="planning_repair_patch.authority_mismatch",
            field_path="$.authority_sha256",
            invariant_id="repair_authority_fresh",
            value_type="string", structural_shape="scalar",
        )
        metadata = {
            "repair_target_identity_sha256": "c" * 64,
            "repair_target_sha256": "d" * 64,
            "canonical_repair_target_paths": ["$.replacements[*].replacement"],
            "domain_validator_id": "planning_repair_patch.normalize.v1",
            "domain_validator_policy_sha256": "e" * 64,
        }
        domain = build_domain_validation_snapshot(
            context, payload={"authority_sha256": "f" * 64},
            domain_result="failed", findings=[finding], metadata=metadata,
        )
        next_context = ModelDiagnosticContextV1(
            **{
                **context.__dict__, "inner_attempt_ordinal": 2,
                "parent_attempt_ordinal": 1,
            }
        )
        propagation = build_finding_propagation_snapshot(
            source=domain, target_context=next_context,
            system="synthetic-system", user="synthetic-user",
            propagated_findings=[finding],
            propagated_finding_receipt_sha256=domain.receipt_sha256,
        )
        fallback_context = ModelDiagnosticContextV1(
            **{
                **context.__dict__, "route_kind": "configured_fallback",
                "inner_attempt_ordinal": 3, "parent_attempt_ordinal": 2,
            }
        )
        provider = capture_provider_content_block_snapshot(
            fallback_context,
            adapter_id="fake", adapter_version=1, protocol="fake-boundary",
            provider_response={"synthetic": True},
            request_max_output_tokens=1977, finish_reason="max_tokens",
            output_tokens=1977, block_types=[], text_values=[],
            tool_arguments=[], reasoning_block_count=0,
        )
        output_limit = build_output_limit_observation(
            fallback_context, provider_snapshot=provider,
            requested_budget=1977, effective_budget=1977,
            output_tokens=1977, stop_reason="max_tokens", zero_visible=True,
            parser_reached=True, strict_tool_reached=False,
            domain_validator_reached=False,
            truncation_classifier_reason="empty_output",
            contract_output_limit_action="fallback_exhausted",
            expansion_before=1977, expansion_after=3954,
            next_route_action="terminal",
        )
        fake_boundary_count = 1
    counters = {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": sentinel.network_call_count,
        "model_call_count": 0,
        "paid_model_call_count": 0,
        "fake_boundary_count": fake_boundary_count,
    }
    observer_receipts = {
        "domain_validation": domain.receipt_sha256,
        "finding_propagation": propagation.receipt_sha256,
        "provider_content_block_shape": provider.snapshot_sha256,
        "output_limit": output_limit.receipt_sha256,
    }
    body = {
        "schema": "PlanningRepairPreLaunchSemanticRehearsalV1",
        "version": 1,
        "status": "exact",
        "process_isolation": "independent_subprocess",
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v2",
        "materialization_semantic_sha256": plan[
            "approved_execution_config_fingerprint"
        ],
        "subprocess_semantic_sha256": (
            runtime.execution_config_fingerprint_sha256
        ),
        "materialization_runtime_execution_sha256": plan[
            "expected_runtime_execution_fingerprint"
        ],
        "subprocess_runtime_execution_sha256": runtime.execution_fingerprint_sha256,
        "observation_status": comparison["status"],
        "component_diff": comparison["component_diff"],
        "observer_coverage": {name: "typed" for name in observer_receipts},
        "observer_receipt_sha256s": observer_receipts,
        "model_request_semantic_status": "unchanged",
        "retry_fallback_status": "unchanged",
        "production_output_budget_status": "unchanged",
        "terminal_behavior_status": "unchanged",
        "external_action_counters": counters,
        "synthetic_evidence_only": True,
        "production_target_claimed": False,
        "raw_values_included": False,
    }
    return {
        **body,
        "receipt_sha256": domain_sha256(
            "novel-flywheel-planning-repair-prelaunch-rehearsal-v1", body,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--isolated-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = run_rehearsal(
        plan_path=args.plan, fixture_path=args.fixture,
        live_database_path=args.live_database,
        isolated_root=args.isolated_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

