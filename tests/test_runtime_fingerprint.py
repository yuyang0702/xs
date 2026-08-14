from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint import (
    DefinitionStore,
    collect_runtime_fingerprint,
    compare_runtime_fingerprints,
    persist_runtime_fingerprint,
)


def make_database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "short", tmp_path / "book")
    db.save_provider(
        provider_id="provider-secret-id", name="Fixture", protocol="openai",
        base_url="https://user:credential@example.invalid/v1?token=secret",
        auth_type="bearer", enabled=True, timeout_seconds=90,
        extra_headers={"X-Secret-Token": "do-not-store"},
    )
    db.save_model(
        model_id="model-secret-id", provider_id="provider-secret-id",
        display_name="Fixture Model", model_name="secret-model-name",
        context_window=32000, max_output_tokens=8000,
        capabilities={"structured": True},
    )
    db.save_role_binding(
        "draft", "provider-secret-id", "model-secret-id", None, None,
    )
    return db


def test_runtime_fingerprint_persists_independently_verifiable_child_graph(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    snapshot = collect_runtime_fingerprint(db, project_id="book")
    store = DefinitionStore(tmp_path / "data")

    persist_runtime_fingerprint(store, snapshot)

    assert store.verify_graph(snapshot.build) == {"valid": True, "reason_codes": []}
    assert store.verify_graph(snapshot.execution_config) == {
        "valid": True, "reason_codes": [],
    }
    assert store.verify_graph(snapshot.execution) == {"valid": True, "reason_codes": []}
    assert snapshot.build["payload"]["human_summary"]["contract_count"] == 40
    assert snapshot.build["payload"]["human_summary"]["incident_family_count"] == 40
    assert snapshot.execution_config["payload"]["human_summary"][
        "credential_material_included"
    ] is False


def test_runtime_fingerprint_store_detects_child_tamper(tmp_path: Path) -> None:
    db = make_database(tmp_path)
    snapshot = collect_runtime_fingerprint(db, project_id="book")
    store = DefinitionStore(tmp_path / "data")
    persist_runtime_fingerprint(store, snapshot)
    child = snapshot.children[0]
    path = store.path_for(child["schema"], child["definition_sha256"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"] = {"tampered": True}
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = store.verify_graph(snapshot.build)

    assert result["valid"] is False
    assert any(code.startswith("child_definition_invalid:") for code in result["reason_codes"])


def test_runtime_fingerprint_never_stores_credentials_or_raw_route_identifiers(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    snapshot = collect_runtime_fingerprint(db, project_id="book")
    serialized = json.dumps(
        [snapshot.build, snapshot.execution_config, snapshot.execution, *snapshot.children],
        ensure_ascii=False,
    )

    for forbidden in (
        "credential@example", "token=secret", "do-not-store",
        "provider-secret-id", "model-secret-id", "secret-model-name",
    ):
        assert forbidden not in serialized
    assert "bearer" in serialized
    assert "openai" in serialized


def test_runtime_change_classification_separates_build_config_and_provenance(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    first = collect_runtime_fingerprint(db, project_id="book")
    same = collect_runtime_fingerprint(db, project_id="book")
    assert compare_runtime_fingerprints(first, same) == {
        "comparison_status": "exact",
        "runtime_changed_during_run": False,
        "build_changed_during_run": False,
        "execution_config_changed_during_run": False,
        "provenance_changed_only": False,
    }

    db.set_feature_flag("short_canonical_v2", True)
    changed = collect_runtime_fingerprint(db, project_id="book")
    comparison = compare_runtime_fingerprints(first, changed)
    assert comparison["build_changed_during_run"] is False
    assert comparison["execution_config_changed_during_run"] is True
    assert comparison["runtime_changed_during_run"] is True
