from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    EMBEDDED_MANIFEST_NAME,
    canonical_json_bytes,
    collect_build_manifests,
    domain_sha256,
    file_manifest_definition,
    git_workspace_collection,
    make_definition,
    packaged_collection,
    verify_definition,
    write_embedded_build_manifest,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def test_canonical_json_is_order_stable_typed_and_domain_separated() -> None:
    left = {"z": None, "a": [True, 3, "text"]}
    right = {"a": [True, 3, "text"], "z": None}

    assert CANONICALIZATION_VERSION == "runtime-fingerprint-canonical-json-v1"
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert domain_sha256("domain-a", left) == domain_sha256("domain-a", right)
    assert domain_sha256("domain-a", left) != domain_sha256("domain-b", right)
    with pytest.raises(TypeError, match="floating-point"):
        canonical_json_bytes({"unsafe": 1.5})


def test_file_manifest_normalizes_dict_independent_paths_and_line_endings(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.py").write_bytes(b"print('same')\r\n")
    (second / "same.py").write_bytes(b"print('same')\n")

    left = file_manifest_definition(
        schema="RuntimeProductionSourceManifestV1", root=first,
        paths=[first / "same.py"], mode="test",
    )
    right = file_manifest_definition(
        schema="RuntimeProductionSourceManifestV1", root=second,
        paths=[second / "same.py"], mode="test",
    )

    assert left == right
    assert left["payload"]["files"][0]["path"] == "same.py"
    assert "C:/" not in json.dumps(left)


def test_definition_hash_rejects_tamper() -> None:
    definition = make_definition("RuntimeTestManifestV1", {"value": True})
    assert verify_definition(definition)

    definition["payload"]["value"] = False
    assert not verify_definition(definition)


def test_git_workspace_collects_build_input_installed_source_and_provenance() -> None:
    collection = git_workspace_collection(REPOSITORY)

    assert collection.mode == "git_workspace"
    assert collection.status == "verified_git_workspace"
    assert collection.build_input and verify_definition(collection.build_input)
    assert collection.installed_runtime and verify_definition(collection.installed_runtime)
    assert collection.production_source and verify_definition(collection.production_source)
    assert collection.provenance and verify_definition(collection.provenance)
    paths = {item["path"] for item in collection.production_source["payload"]["files"]}
    assert "pyproject.toml" in paths
    assert "start-novel-console.cmd" in paths
    assert any(path.startswith("baml_src/") for path in paths)
    assert any(path.startswith("src/novel_flywheel/") for path in paths)
    assert all("tests/" not in path and ".git/" not in path for path in paths)


def test_packaged_collection_verifies_installed_files_without_repo_roots(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "build-repository"
    package = repository / "src" / "novel_flywheel"
    package.mkdir(parents=True)
    (repository / "baml_src").mkdir()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "baml_src" / "main.baml").write_text("class A {}\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (repository / "start-novel-console.cmd").write_text("@echo off\n", encoding="utf-8")
    write_embedded_build_manifest(repository, package / EMBEDDED_MANIFEST_NAME)

    isolated = tmp_path / "isolated" / "novel_flywheel"
    isolated.mkdir(parents=True)
    for source in package.iterdir():
        (isolated / source.name).write_bytes(source.read_bytes())
    result = packaged_collection(isolated)

    assert result.mode == "packaged"
    assert result.status == "verified_packaged_manifest"
    assert result.build_input is not None
    assert result.installed_runtime is not None
    assert not (isolated.parent / "pyproject.toml").exists()
    assert not (isolated.parent / "baml_src").exists()


def test_packaged_collection_reports_unknown_without_embedded_manifest(
    tmp_path: Path,
) -> None:
    package = tmp_path / "novel_flywheel"
    package.mkdir()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = collect_build_manifests(module_file=package / "module.py")

    assert result.mode == "unknown"
    assert result.status == "unknown_runtime"
    assert result.reason_codes == ("embedded_build_manifest_missing",)


def test_real_wheel_embeds_and_revalidates_installed_runtime_without_git(
    tmp_path: Path,
) -> None:
    build_root = tmp_path / "wheel-source"
    build_root.mkdir()
    shutil.copytree(REPOSITORY / "src", build_root / "src")
    shutil.copytree(REPOSITORY / "baml_src", build_root / "baml_src")
    for relative in (
        "pyproject.toml", "start-novel-console.cmd", "hatch_build.py",
    ):
        shutil.copy2(REPOSITORY / relative, build_root / relative)

    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "wheel"],
        cwd=build_root, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    wheel = next((build_root / "dist").glob("*.whl"))
    extracted = tmp_path / "installed-no-git"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(extracted)
    package_root = extracted / "novel_flywheel"

    result = packaged_collection(package_root)

    assert not (extracted / ".git").exists()
    assert not (extracted / "pyproject.toml").exists()
    assert not (extracted / "baml_src").exists()
    assert (package_root / EMBEDDED_MANIFEST_NAME).is_file()
    assert result.mode == "packaged"
    assert result.status == "verified_packaged_manifest"
    assert result.reason_codes == ()
