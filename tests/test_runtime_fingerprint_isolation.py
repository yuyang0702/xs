from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.models import ModelGateway
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.runtime_fingerprint import (
    RuntimeFingerprintRecorderV1,
    canonical_runtime_bindings,
    collect_build_fingerprint,
    verify_runtime_binding_sidecars,
)


class CountingSecrets:
    def __init__(self) -> None:
        self.get_count = 0

    def get(self, _provider_id: str) -> None:
        self.get_count += 1
        return None

    def set(self, _provider_id: str, _value: str) -> None:
        raise AssertionError("fingerprinting must not write credentials")

    def delete(self, _provider_id: str) -> None:
        raise AssertionError("fingerprinting must not delete credentials")


def make_database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "projects" / "book"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"id": "book", "mode": "long"}), encoding="utf-8",
    )
    (project / "story.md").write_text("formal artifact", encoding="utf-8")
    db.save_project("book", "Book", "long", project)
    return db


def test_app_wiring_collects_without_credential_provider_network_or_model_side_effect(
    tmp_path: Path, monkeypatch,
) -> None:
    db = make_database(tmp_path)
    secrets = CountingSecrets()
    counters = {"provider": 0, "network": 0, "model": 0}

    def forbidden_provider(*_args, **_kwargs):
        counters["provider"] += 1
        raise AssertionError("provider client creation is forbidden")

    async def forbidden_model(*_args, **_kwargs):
        counters["model"] += 1
        raise AssertionError("model call is forbidden")

    def forbidden_network(*_args, **_kwargs):
        counters["network"] += 1
        raise AssertionError("network call is forbidden")

    monkeypatch.setattr(ProviderRegistry, "resolve", forbidden_provider)
    monkeypatch.setattr(ModelGateway, "complete", forbidden_model)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)

    app = create_app(
        db=db, secrets=secrets, workspace_root=tmp_path / "projects",
        root_constraints=[tmp_path],
    )
    db.create_run("run", "book", "material-edit", status="running")

    assert app.state.runtime_fingerprint_status == "available"
    assert secrets.get_count == 0
    assert counters == {"provider": 0, "network": 0, "model": 0}


def test_sidecar_is_physically_outside_project_and_contains_no_business_text(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    build, children = collect_build_fingerprint()
    recorder = RuntimeFingerprintRecorderV1(
        db, tmp_path, process_build=build, build_children=children,
    )
    db.set_run_lifecycle_observer(recorder)
    db.create_run("run", "book", "material-edit", status="running")

    sidecar_root = tmp_path / "runtime" / "runtime-fingerprints-v1"
    project_root = tmp_path / "projects" / "book"
    assert sidecar_root.is_dir()
    assert not sidecar_root.is_relative_to(project_root)
    assert set(project_root.rglob("*")) == {
        project_root / "project.json", project_root / "story.md",
    }
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in sidecar_root.rglob("*.json")
    )
    assert "formal artifact" not in serialized
    assert "api_key" not in serialized.casefold()


def test_sidecar_reader_rehashes_complete_binding_graph(tmp_path: Path) -> None:
    db = make_database(tmp_path)
    build, children = collect_build_fingerprint()
    recorder = RuntimeFingerprintRecorderV1(
        db, tmp_path, process_build=build, build_children=children,
    )
    db.set_run_lifecycle_observer(recorder)
    db.create_run("run", "book", "material-edit", status="running")
    executor = next(
        item for item in canonical_runtime_bindings(db, "run")["bindings"]
        if item["binding_kind"] == "executor"
    )

    validation = verify_runtime_binding_sidecars(recorder.store, executor)

    assert validation == {
        "valid": True, "validation_status": "exact", "reason_codes": [],
    }


def test_concurrent_identical_append_is_valid_json_and_logically_idempotent(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    db.create_run("run", "book", "material-edit", status="running")
    build, children = collect_build_fingerprint()
    recorder = RuntimeFingerprintRecorderV1(
        db, tmp_path, process_build=build, build_children=children,
    )
    observation = {
        "run_id": "run", "project_id": "book", "workflow": "material-edit",
        "binding_kind": "origin", "execution_epoch": "origin:1",
    }

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _index: recorder(observation), range(12)))

    result = canonical_runtime_bindings(db, "run")
    assert result["origin_count"] == 1
    assert result["logical_binding_count"] == 1
    for path in recorder.store.root.rglob("*.json"):
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
