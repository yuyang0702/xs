"""Independent, zero-external-action V2 pre-launch semantic rehearsal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from novel_flywheel.runtime_fingerprint_build import domain_sha256

from .approval_profiles import SHORT_COMPLETION_PROFILE_ID, approval_profile
from .descriptors import copy_production_execution_config
from .environment import c0a_environment
from .fingerprint_profiles import (
    PRODUCTION_MIRROR_SHORT_PROFILE_ID,
    compare_execution_fingerprint_profiles_v1,
)
from .network_sentinel import FailClosedNetworkSentinel
from .preflight import validate_execution_config_prelaunch_v2
from .ptr3_readiness import (
    validate_ptr3_readiness_v1,
    validate_r1_d3_successor_readiness_v1,
)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("semantic_rehearsal_input_invalid")
    return value


def run_rehearsal(
    *, plan_path: Path, fixture_path: Path, live_database_path: Path,
    isolated_root: Path,
) -> dict:
    plan = _read(plan_path)
    fixture = _read(fixture_path)
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    sentinel = FailClosedNetworkSentinel()
    fake_boundary_count = 0
    with c0a_environment(
        isolated_root, feature_flags=profile.required_flags(),
    ), sentinel:
        db = Database(isolated_root / "db" / "app.db")
        db.migrate()
        copy_production_execution_config(Database(live_database_path), db)
        project = ProjectStore(db, isolated_root / "projects").create(ProjectCreate(
            title=str(fixture["title"]), mode="short",
            genre=str(fixture["genre"]), premise=str(fixture["premise"]),
            target_words=int(fixture["target_words"]),
        ))
        db.set_feature_flag(
            "short_canonical_v2", False,
            scope_type="project", scope_id=project.id,
        )
        runtime = collect_runtime_fingerprint_v2(db, project_id=project.id)
        observation = validate_execution_config_prelaunch_v2(
            plan, runtime.execution_config_component_binding or {},
        )
        collection_profile_comparison = compare_execution_fingerprint_profiles_v1(
            {
                "collection_profile_id": plan["short_completion_policy"].get(
                    "execution_collection_profile_id"
                ),
                "execution_config_sha256": plan[
                    "approved_execution_config_fingerprint"
                ],
                "runtime_execution_sha256": plan[
                    "expected_runtime_execution_fingerprint"
                ],
            },
            {
                "collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
                "execution_config_sha256": runtime.execution_config_fingerprint_sha256,
                "runtime_execution_sha256": runtime.execution_fingerprint_sha256,
            },
        )
        completion_policy = plan.get("short_completion_policy") or {}
        ptr3_value = completion_policy.get("ptr3_readiness")
        draft_value = completion_policy.get(
            "r1_d3_production_mirror_readiness"
        )
        planning_rehearsal = None
        draft_rehearsal = None
        if ptr3_value is not None and draft_value is not None:
            ptr3 = validate_ptr3_readiness_v1(ptr3_value)
            draft = validate_r1_d3_successor_readiness_v1(draft_value)
            planning_rehearsal = {
                "boundary": "planning_repair_patch",
                "fake_sequence": [
                    "domain_rejected", "exact_finding_propagated",
                    "domain_passed",
                ],
                "finding_contract_sha256": ptr3["finding_contract_sha256"],
                "finding_bounds_policy_sha256": ptr3[
                    "finding_bounds_policy_sha256"
                ],
                "stale_finding_count": 0,
                "convergence_status": "exact",
            }
            draft_rehearsal = {
                "boundary": "draft_retry",
                "fake_sequence": [
                    "mixed_script_rejected", "exact_finding_propagated",
                    "draft_validation_passed",
                ],
                "draft_retry_contract_sha256": draft[
                    "draft_retry_contract_sha256"
                ],
                "stale_finding_count": 0,
                "convergence_status": "exact",
            }
        # This sentinel marks permission to reach a fake boundary.  It never
        # resolves credentials, constructs a provider, or opens the network.
        fake_boundary_count += 2 if planning_rehearsal is not None else 1
    counters = {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": sentinel.network_call_count,
        "model_call_count": 0,
        "paid_model_call_count": 0,
        "fake_boundary_count": fake_boundary_count,
    }
    body = {
        "schema": "PreLaunchSemanticFingerprintRehearsalV1",
        "version": 1,
        "status": "exact",
        "process_isolation": "independent_subprocess",
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v2",
        "collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
        "materialization_semantic_sha256": plan[
            "approved_execution_config_fingerprint"
        ],
        "subprocess_semantic_sha256": runtime.execution_config_fingerprint_sha256,
        "materialization_runtime_execution_sha256": plan[
            "expected_runtime_execution_fingerprint"
        ],
        "subprocess_runtime_execution_sha256": runtime.execution_fingerprint_sha256,
        "materialization_provenance_sha256": plan[
            "approved_execution_config_components"
        ]["feature_flag_provenance_sha256"],
        "subprocess_provenance_sha256": runtime.feature_flag_provenance_sha256,
        "observation_status": observation["status"],
        "component_diff": observation["component_diff"],
        "collection_profile_comparison": collection_profile_comparison,
        "external_action_counters": counters,
        "raw_values_included": False,
    }
    if planning_rehearsal is not None:
        body.update({
            "planning_finding_rehearsal": planning_rehearsal,
            "draft_finding_rehearsal": draft_rehearsal,
            "request_semantic_parity": "exact",
            "route_model_parity": "exact",
            "retry_fallback_parity": "exact",
            "output_budget_parity": "exact",
            "final_review_maintenance_definitions": "exact",
        })
    return {
        **body,
        "receipt_sha256": domain_sha256(
            "novel-flywheel-pre-launch-semantic-rehearsal-v1", body,
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
    sys.exit(main())
