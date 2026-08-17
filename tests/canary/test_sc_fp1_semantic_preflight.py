from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from tools.canary.approval_profiles import (
    SHORT_COMPLETION_PROFILE_ID, approval_profile,
)
from tools.canary.contracts import (
    CanaryContractError, build_canary_experiment_plan_v1,
)
from tools.canary.environment import c0a_environment
from tools.canary.launcher import main
from tools.canary.preflight import (
    CanaryPreflightBlocked, validate_execution_config_prelaunch_v2,
)


def _database(tmp_path: Path) -> tuple[Database, str]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = ProjectStore(db, tmp_path / "projects").create(ProjectCreate(
        title="Semantic Fixture", mode="short", genre="suspense",
        premise="A controlled fixture.", target_words=6000,
    ))
    db.set_feature_flag(
        "short_canonical_v2", False,
        scope_type="project", scope_id=project.id,
    )
    return db, project.id


def _minimal_v2_plan(binding: dict) -> dict:
    hashes = {key: "1" * 64 for key in (
        "approved_build_fingerprint", "expected_runtime_execution_fingerprint",
        "launcher_sha256", "workload_manifest_hash",
        "provider_descriptor_definition_sha256",
        "role_binding_manifest_definition_sha256",
    )}
    return build_canary_experiment_plan_v1({
        "canary_mode": "c0a_fake_dry_run", "runtime_mode": "git_workspace",
        **hashes,
        "approved_execution_config_fingerprint": binding["semantic_sha256"],
        "runtime_fingerprint_policy_version": "runtime-fingerprint-v2",
        "approved_execution_config_components": binding,
        "workloads": [{
            "workload_id": "short-normal-v1", "fixture_sha256": "1" * 64,
            "weight": 1, "prompt_policy_manifest_sha256": "1" * 64,
            "expected_stage_reachability": ["planning"],
            "maximum_model_calls": 1, "estimated_input_tokens": 1,
            "maximum_output_tokens": 1, "success_definition": "controlled",
            "controlled_outcomes": [], "terminal_outcomes": [],
        }],
        "approved_routes": [{
            "role": "planning", "allowed_stages": ["planning"],
            "primary": {
                "provider_descriptor_hash": "1" * 64,
                "model_binding_hash": "1" * 64, "protocol": "fake",
            },
            "fallback": None,
        }],
        "feature_flag_snapshot": {
            "NOVEL_SHORT_CANONICAL_V2": False,
            "project_short_canonical_v2": False,
            "NOVEL_CANONICAL_SHADOW_V1": False,
            "NOVEL_RELIABILITY_TRACE": True,
        },
        "isolation": {},
        "budgets": {
            "maximum_runs": 1, "maximum_model_calls_per_run": 1,
            "maximum_total_model_calls": 1, "maximum_input_tokens": 1,
            "maximum_output_tokens": 1, "pricing_status": "fake",
            "currency": "NONE", "maximum_estimated_cost_microunits": 0,
            "maximum_elapsed_seconds": 1, "gate_wait_timeout_seconds": 1,
        },
        "stop_conditions": ["fingerprint_mismatch"],
        "report_policy": {},
        "approved_dependency_manifest": {
            "stdlib": True, "production_package": True, "third_party": [],
        },
    })


def test_incident_replay_defaulted_and_explicit_false_are_semantically_exact(
    tmp_path: Path,
) -> None:
    db, project_id = _database(tmp_path)
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    with c0a_environment(
        tmp_path / "materializer", feature_flags=profile.required_flags(),
    ):
        materialized = collect_runtime_fingerprint_v2(db, project_id=project_id)
    with c0a_environment(
        tmp_path / "runner", feature_flags=profile.required_flags(),
    ):
        runner = collect_runtime_fingerprint_v2(db, project_id=project_id)
    plan = _minimal_v2_plan(materialized.execution_config_component_binding or {})
    result = validate_execution_config_prelaunch_v2(
        plan, runner.execution_config_component_binding or {},
    )
    assert result["status"] == "exact"
    assert result["component_diff"]["semantic_equal"] is True
    assert result["component_diff"]["provenance_equal"] is True
    assert materialized.execution_config_fingerprint_sha256 == (
        runner.execution_config_fingerprint_sha256
    )
    assert materialized.execution_fingerprint_sha256 == (
        runner.execution_fingerprint_sha256
    )


def test_true_drift_is_typed_hash_only_pre_provider_block(tmp_path: Path) -> None:
    db, project_id = _database(tmp_path)
    with c0a_environment(tmp_path / "expected"):
        expected = collect_runtime_fingerprint_v2(db, project_id=project_id)
    flags = approval_profile(SHORT_COMPLETION_PROFILE_ID).required_flags()
    flags["NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"] = True
    with c0a_environment(tmp_path / "actual", feature_flags=flags):
        actual = collect_runtime_fingerprint_v2(db, project_id=project_id)
    plan = _minimal_v2_plan(expected.execution_config_component_binding or {})
    with pytest.raises(CanaryPreflightBlocked) as caught:
        validate_execution_config_prelaunch_v2(
            plan, actual.execution_config_component_binding or {},
        )
    assert caught.value.reason_code == "execution_config_fingerprint_mismatch"
    assert caught.value.component_diff["semantic_equal"] is False
    assert caught.value.component_diff["hash_only"] is True
    assert "effective_feature_flags" in (
        caught.value.component_diff["differing_component_ids"]
    )
    serialized = json.dumps(caught.value.component_diff)
    assert "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1" not in serialized
    assert "raw_value" not in serialized


def test_unknown_provenance_does_not_masquerade_as_equivalent(tmp_path: Path) -> None:
    db, project_id = _database(tmp_path)
    with c0a_environment(tmp_path / "expected"):
        runtime = collect_runtime_fingerprint_v2(db, project_id=project_id)
    plan = _minimal_v2_plan(runtime.execution_config_component_binding or {})
    observed = deepcopy(runtime.execution_config_component_binding or {})
    observed["feature_flag_provenance_sha256"] = None
    with pytest.raises(
        CanaryPreflightBlocked, match="execution_config_provenance_unknown",
    ):
        validate_execution_config_prelaunch_v2(plan, observed)


def test_database_precedence_behavior_change_remains_semantic_drift(
    tmp_path: Path,
) -> None:
    db, project_id = _database(tmp_path)
    db.set_feature_flag("short_canonical_v2", True)
    with c0a_environment(tmp_path / "global"):
        # Project false wins over global true.
        project_false = collect_runtime_fingerprint_v2(db, project_id=project_id)
    other = ProjectStore(db, tmp_path / "projects").create(ProjectCreate(
        title="Other Fixture", mode="short", genre="suspense",
        premise="Another controlled fixture.", target_words=6000,
    ))
    with c0a_environment(tmp_path / "global"):
        global_true = collect_runtime_fingerprint_v2(db, project_id=other.id)
    assert project_false.execution_config_fingerprint_sha256 != (
        global_true.execution_config_fingerprint_sha256
    )


def test_unknown_or_cross_policy_plan_fails_closed(tmp_path: Path) -> None:
    db, project_id = _database(tmp_path)
    with c0a_environment(tmp_path / "runtime"):
        runtime = collect_runtime_fingerprint_v2(db, project_id=project_id)
    plan = _minimal_v2_plan(runtime.execution_config_component_binding or {})
    unknown = deepcopy(plan)
    unknown["runtime_fingerprint_policy_version"] = "runtime-fingerprint-v99"
    unknown["plan_sha256"] = "2" * 64
    with pytest.raises(CanaryContractError, match="policy_unsupported"):
        build_canary_experiment_plan_v1({
            key: value for key, value in unknown.items()
            if key not in {"schema", "version", "canonicalization_version", "plan_sha256"}
        })
    crossed = deepcopy(plan)
    crossed["runtime_fingerprint_policy_version"] = "runtime-fingerprint-v1"
    crossed.pop("plan_sha256")
    with pytest.raises(CanaryContractError, match="policy_cross_authorization"):
        build_canary_experiment_plan_v1({
            key: value for key, value in crossed.items()
            if key not in {"schema", "version", "canonicalization_version"}
        })


def test_launcher_preserves_typed_preflight_root_cause(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.canary import launcher

    monkeypatch.setattr(
        launcher, "validate_packet",
        lambda **_kwargs: (_ for _ in ()).throw(CanaryPreflightBlocked(
            "execution_config_fingerprint_mismatch",
            component_diff={"hash_only": True, "semantic_equal": False},
        )),
    )
    code = main([
        "--plan", "missing-plan.json", "--approval", "missing-approval.json",
        "--approved-plan-sha256", "1" * 64, "--validate-only",
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 2
    assert result["outcome"] == "CANARY_BLOCKED_PRE_PROVIDER"
    assert result["reason_code"] == "execution_config_fingerprint_mismatch"
    assert result["provider_boundary_entered"] is False
    assert result["network_call_count"] == 0
    assert result["execution_config_component_diff"]["hash_only"] is True
