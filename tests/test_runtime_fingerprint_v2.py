from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.runtime_fingerprint import (
    FEATURE_FLAG_REGISTRY_POLICY_VERSION_V2,
    RUNTIME_FINGERPRINT_POLICY_V1,
    RUNTIME_FINGERPRINT_POLICY_V2,
    RuntimeFeatureFlagResolutionError,
    collect_runtime_fingerprint_v2,
    collect_runtime_fingerprint_v1,
    feature_flag_registry_definition_v2,
    resolve_feature_flag_snapshots_v2,
    runtime_execution_config_component_diff_v2,
)
from novel_flywheel.runtime_fingerprint_build import verify_definition


ENV_FLAGS = (
    "NOVEL_CANONICAL_SHADOW_V1",
    "NOVEL_RELIABILITY_TRACE",
    "NOVEL_SHORT_CANONICAL_V2",
    "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1",
    "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1",
)


def make_database(tmp_path: Path) -> tuple[Database, str]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "projects")
    project = store.create(ProjectCreate(
        title="Controlled Fixture", mode="short", genre="suspense",
        premise="A controlled fixture.", target_words=6000,
    ))
    return db, project.id


def clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_FLAGS:
        monkeypatch.delenv(name, raising=False)


def explicit_false_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_FLAGS:
        monkeypatch.setenv(name, "0")


def test_v1_reproduces_false_presence_mismatch_and_v2_collapses_only_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    legacy_defaulted = collect_runtime_fingerprint_v1(db, project_id=project_id)
    semantic_defaulted = collect_runtime_fingerprint_v2(db, project_id=project_id)

    explicit_false_environment(monkeypatch)
    legacy_set = collect_runtime_fingerprint_v1(db, project_id=project_id)
    semantic_set = collect_runtime_fingerprint_v2(db, project_id=project_id)

    assert legacy_defaulted.execution_config_fingerprint_sha256 != (
        legacy_set.execution_config_fingerprint_sha256
    )
    assert semantic_defaulted.execution_config_fingerprint_sha256 == (
        semantic_set.execution_config_fingerprint_sha256
    )
    assert semantic_defaulted.execution_fingerprint_sha256 == (
        semantic_set.execution_fingerprint_sha256
    )
    assert semantic_defaulted.feature_flag_semantic_sha256 == (
        semantic_set.feature_flag_semantic_sha256
    )
    assert semantic_defaulted.feature_flag_provenance_sha256 != (
        semantic_set.feature_flag_provenance_sha256
    )
    assert semantic_defaulted.execution_config["definition_sha256"] != (
        semantic_set.execution_config["definition_sha256"]
    )


@pytest.mark.parametrize("flag", ENV_FLAGS)
def test_explicit_true_is_real_semantic_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    baseline = collect_runtime_fingerprint_v2(db, project_id=project_id)
    monkeypatch.setenv(flag, "1")
    changed = collect_runtime_fingerprint_v2(db, project_id=project_id)

    assert baseline.feature_flag_semantic_sha256 != changed.feature_flag_semantic_sha256
    assert baseline.execution_config_fingerprint_sha256 != (
        changed.execution_config_fingerprint_sha256
    )
    assert baseline.execution_fingerprint_sha256 != changed.execution_fingerprint_sha256


@pytest.mark.parametrize("raw", ["", "false", "true", "2", "unknown"])
def test_malformed_or_unknown_environment_boolean_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", raw)

    with pytest.raises(
        RuntimeFeatureFlagResolutionError,
        match="feature_flag_boolean_value_invalid",
    ):
        collect_runtime_fingerprint_v2(db, project_id=project_id)


def test_database_default_global_and_project_false_share_semantics_but_not_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    defaulted = collect_runtime_fingerprint_v2(db, project_id=project_id)
    db.set_feature_flag("short_canonical_v2", False)
    global_false = collect_runtime_fingerprint_v2(db, project_id=project_id)
    db.set_feature_flag(
        "short_canonical_v2", False,
        scope_type="project", scope_id=project_id,
    )
    project_false = collect_runtime_fingerprint_v2(db, project_id=project_id)

    assert len({
        defaulted.feature_flag_semantic_sha256,
        global_false.feature_flag_semantic_sha256,
        project_false.feature_flag_semantic_sha256,
    }) == 1
    assert len({
        defaulted.feature_flag_provenance_sha256,
        global_false.feature_flag_provenance_sha256,
        project_false.feature_flag_provenance_sha256,
    }) == 3


def test_project_metadata_absent_and_explicit_false_are_semantically_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    absent = collect_runtime_fingerprint_v2(db, project_id=project_id)
    project = db.get_project(project_id)
    assert project is not None
    metadata_path = Path(project["path"]) / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_path.write_text(json.dumps({
        **metadata, "market_baseline_enabled": False,
    }), encoding="utf-8")
    explicit = collect_runtime_fingerprint_v2(db, project_id=project_id)

    assert absent.feature_flag_semantic_sha256 == explicit.feature_flag_semantic_sha256
    assert absent.feature_flag_provenance_sha256 != explicit.feature_flag_provenance_sha256


def test_registry_is_complete_versioned_and_default_policy_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    registry = feature_flag_registry_definition_v2()
    effective, provenance, observed_registry = resolve_feature_flag_snapshots_v2(
        db, project_id=project_id,
    )

    assert registry == observed_registry
    assert registry["payload"]["registry_policy_version"] == (
        FEATURE_FLAG_REGISTRY_POLICY_VERSION_V2
    )
    assert all(item["default_policy_sha256"] for item in registry["payload"]["flags"])
    assert verify_definition(registry)
    assert verify_definition(effective)
    assert verify_definition(provenance)


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "feature_flag_registry_incomplete"),
    ("extra", "feature_flag_unregistered"),
    ("policy", "feature_flag_registry_policy_unknown"),
])
def test_registry_missing_extra_or_unknown_policy_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    mutation: str, reason: str,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    registry = deepcopy(feature_flag_registry_definition_v2()["payload"])
    if mutation == "missing":
        registry["flags"] = registry["flags"][:-1]
    elif mutation == "extra":
        registry["flags"].append({**registry["flags"][0], "flag_id": "UNKNOWN_FLAG"})
    else:
        registry["registry_policy_version"] = "unknown-policy"

    with pytest.raises(RuntimeFeatureFlagResolutionError, match=reason):
        resolve_feature_flag_snapshots_v2(
            db, project_id=project_id, registry_payload=registry,
        )


def test_component_diff_distinguishes_equivalent_provenance_from_semantic_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    defaulted = collect_runtime_fingerprint_v2(db, project_id=project_id)
    explicit_false_environment(monkeypatch)
    explicit = collect_runtime_fingerprint_v2(db, project_id=project_id)
    equivalent = runtime_execution_config_component_diff_v2(defaulted, explicit)
    assert equivalent["semantic_equal"] is True
    assert equivalent["provenance_equal"] is False
    assert equivalent["differing_component_ids"] == ["feature_flag_provenance"]

    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    changed = collect_runtime_fingerprint_v2(db, project_id=project_id)
    drift = runtime_execution_config_component_diff_v2(defaulted, changed)
    assert drift["semantic_equal"] is False
    assert "effective_feature_flags" in drift["differing_component_ids"]


def test_v1_definitions_remain_readable_and_v1_v2_policies_do_not_cross(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, project_id = make_database(tmp_path)
    clear_environment(monkeypatch)
    legacy = collect_runtime_fingerprint_v1(db, project_id=project_id)
    current = collect_runtime_fingerprint_v2(db, project_id=project_id)

    assert legacy.policy_version == RUNTIME_FINGERPRINT_POLICY_V1
    assert current.policy_version == RUNTIME_FINGERPRINT_POLICY_V2
    assert legacy.execution_config["schema"] == "RuntimeExecutionConfigFingerprintV1"
    assert current.execution_config["schema"] == "RuntimeExecutionConfigFingerprintV2"
    assert verify_definition(legacy.execution_config)
    assert verify_definition(legacy.execution)
    assert legacy.execution_config_fingerprint_sha256 != (
        current.execution_config_fingerprint_sha256
    )
