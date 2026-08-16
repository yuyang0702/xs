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
from .network_sentinel import FailClosedNetworkSentinel
from .preflight import validate_execution_config_prelaunch_v2


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
        # This sentinel marks permission to reach a fake boundary.  It never
        # resolves credentials, constructs a provider, or opens the network.
        fake_boundary_count += 1
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
        "materialization_semantic_sha256": plan[
            "approved_execution_config_fingerprint"
        ],
        "subprocess_semantic_sha256": runtime.execution_config_fingerprint_sha256,
        "materialization_provenance_sha256": plan[
            "approved_execution_config_components"
        ]["feature_flag_provenance_sha256"],
        "subprocess_provenance_sha256": runtime.feature_flag_provenance_sha256,
        "observation_status": observation["status"],
        "component_diff": observation["component_diff"],
        "external_action_counters": counters,
        "raw_values_included": False,
    }
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
