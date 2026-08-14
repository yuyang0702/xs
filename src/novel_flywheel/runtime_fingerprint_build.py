"""Deterministic, side-effect-free build identity primitives.

This module intentionally uses only the Python standard library so the wheel
build hook can import it before project dependencies are installed.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


CANONICALIZATION_VERSION = "runtime-fingerprint-canonical-json-v1"
UTF8 = "utf-8"
EMBEDDED_MANIFEST_NAME = "_runtime-build-manifest-v1.json"
TEXT_SUFFIXES = frozenset({
    ".baml", ".cmd", ".css", ".html", ".js", ".json", ".md", ".py",
    ".toml", ".txt", ".yaml", ".yml",
})
EXCLUDED_PARTS = frozenset({
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "dist",
})
PRODUCTION_ROOTS = ("src/novel_flywheel", "baml_src")
PRODUCTION_FILES = ("pyproject.toml", "start-novel-console.cmd")


class FingerprintUnavailable(RuntimeError):
    """Raised when runtime identity cannot be established without guessing."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = detail or reason_code


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise TypeError("floating-point values are forbidden in fingerprint definitions")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("fingerprint object keys must be strings")
            result[key] = _canonicalize(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    raise TypeError(f"unsupported fingerprint value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonicalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode(UTF8)


def domain_sha256(domain: str, value: Any) -> str:
    if not domain or "\x00" in domain:
        raise ValueError("hash domain must be non-empty and NUL-free")
    return hashlib.sha256(
        domain.encode("ascii") + b"\x00" + canonical_json_bytes(value)
    ).hexdigest()


def make_definition(schema: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema": schema,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload": _canonicalize(payload),
    }
    return {
        **body,
        "definition_sha256": domain_sha256(
            f"novel-flywheel-definition-v1:{schema}", body,
        ),
    }


def verify_definition(definition: Mapping[str, Any]) -> bool:
    try:
        schema = str(definition["schema"])
        body = {
            "schema": schema,
            "canonicalization_version": definition["canonicalization_version"],
            "payload": definition["payload"],
        }
        expected = domain_sha256(
            f"novel-flywheel-definition-v1:{schema}", body,
        )
        return (
            definition["canonicalization_version"] == CANONICALIZATION_VERSION
            and definition["definition_sha256"] == expected
        )
    except (KeyError, TypeError, ValueError):
        return False


def _relative_posix(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FingerprintUnavailable(
            "path_outside_identity_root", str(path),
        ) from exc
    normalized = PurePosixPath(*relative.parts)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise FingerprintUnavailable("unsafe_relative_path", str(path))
    return normalized.as_posix()


def _content_bytes(path: Path) -> tuple[str, bytes]:
    if path.is_symlink():
        raise FingerprintUnavailable("symlink_not_supported", str(path))
    raw = path.read_bytes()
    if path.suffix.casefold() in TEXT_SUFFIXES:
        try:
            text = raw.decode(UTF8)
        except UnicodeDecodeError as exc:
            raise FingerprintUnavailable("invalid_utf8_source", str(path)) from exc
        return "utf8_lf", text.replace("\r\n", "\n").replace("\r", "\n").encode(UTF8)
    return "binary", raw


def file_manifest_definition(
    *, schema: str, root: Path, paths: Iterable[Path], mode: str,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(paths, key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = _relative_posix(path, root)
        if relative in seen:
            continue
        seen.add(relative)
        encoding, content = _content_bytes(path)
        entries.append({
            "path": relative,
            "encoding": encoding,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "canonical_size": len(content),
        })
    return make_definition(schema, {
        "mode": mode,
        "path_normalization": "root-relative-posix-v1",
        "text_normalization": "utf8-lf-v1",
        "files": entries,
    })


def _walk_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        path for path in root.rglob("*")
        if path.is_file()
        and path.name != EMBEDDED_MANIFEST_NAME
        and not any(part in EXCLUDED_PARTS for part in path.parts)
        and path.suffix.casefold() not in {".pyc", ".pyo"}
    ]


def production_source_paths(repository: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in PRODUCTION_ROOTS:
        paths.extend(_walk_files(repository / relative))
    paths.extend(
        repository / relative for relative in PRODUCTION_FILES
        if (repository / relative).is_file()
    )
    return paths


def installed_runtime_paths(package_root: Path) -> list[Path]:
    return _walk_files(package_root)


def find_git_repository(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repository, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding=UTF8, errors="strict",
    )
    # Porcelain status uses a meaningful leading space for worktree-only
    # changes (`` M path``). Strip line endings only; trimming the beginning
    # corrupts the XY status columns and therefore the changed path.
    return completed.stdout.rstrip("\r\n")


def git_provenance_definition(repository: Path) -> dict[str, Any]:
    try:
        commit = _git(repository, "rev-parse", "HEAD")
        tree = _git(repository, "rev-parse", "HEAD^{tree}")
        porcelain = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise FingerprintUnavailable("git_provenance_unavailable", str(exc)) from exc
    changed_paths = sorted({
        line[3:].replace("\\", "/") for line in porcelain.splitlines()
        if len(line) >= 4
    })
    production = {
        _relative_posix(path, repository)
        for path in production_source_paths(repository)
    }
    return make_definition("RuntimeGitProvenanceV1", {
        "commit": commit,
        "tree": tree,
        "workspace_dirty": bool(changed_paths),
        "production_source_dirty": bool(production.intersection(changed_paths)),
        "changed_path_count": len(changed_paths),
    })


def python_runtime_definition() -> dict[str, Any]:
    return make_definition("RuntimePythonManifestV1", {
        "implementation": platform.python_implementation().casefold(),
        "version": platform.python_version(),
        "cache_tag": str(sys.implementation.cache_tag or "unknown"),
        "byteorder": sys.byteorder,
        "platform_system": platform.system().casefold() or "unknown",
        "platform_machine": platform.machine().casefold() or "unknown",
    })


def installed_dependency_definition() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip().casefold()
        if name:
            packages[name] = str(distribution.version)
    return make_definition("RuntimeInstalledDependencyManifestV1", {
        "packages": [
            {"name": name, "version": packages[name]}
            for name in sorted(packages)
        ],
        "lock_status": "unavailable_no_lockfile",
    })


@dataclass(frozen=True)
class BuildManifestCollection:
    mode: str
    status: str
    build_input: dict[str, Any] | None
    installed_runtime: dict[str, Any] | None
    production_source: dict[str, Any] | None
    provenance: dict[str, Any] | None
    reason_codes: tuple[str, ...] = ()


def build_input_definition(repository: Path) -> dict[str, Any]:
    return file_manifest_definition(
        schema="RuntimeBuildInputManifestV1", root=repository,
        paths=production_source_paths(repository), mode="build_input",
    )


def git_workspace_collection(repository: Path) -> BuildManifestCollection:
    source = file_manifest_definition(
        schema="RuntimeProductionSourceManifestV1", root=repository,
        paths=production_source_paths(repository), mode="git_workspace",
    )
    installed = file_manifest_definition(
        schema="RuntimeInstalledRuntimeManifestV1", root=repository / "src",
        paths=installed_runtime_paths(repository / "src" / "novel_flywheel"),
        mode="editable_source",
    )
    return BuildManifestCollection(
        mode="git_workspace", status="verified_git_workspace",
        build_input=build_input_definition(repository),
        installed_runtime=installed, production_source=source,
        provenance=git_provenance_definition(repository),
    )


def embedded_build_manifest(repository: Path) -> dict[str, Any]:
    package_root = repository / "src" / "novel_flywheel"
    build_input = build_input_definition(repository)
    installed = file_manifest_definition(
        schema="RuntimeInstalledRuntimeManifestV1", root=repository / "src",
        paths=installed_runtime_paths(package_root), mode="packaged_source_files",
    )
    return make_definition("RuntimeEmbeddedBuildManifestV1", {
        "build_input_definition": build_input,
        "installed_runtime_definition": installed,
        "human_summary": {
            "build_input_file_count": len(build_input["payload"]["files"]),
            "installed_runtime_file_count": len(installed["payload"]["files"]),
            "includes_credentials": False,
        },
    })


def packaged_collection(package_root: Path) -> BuildManifestCollection:
    embedded_path = package_root / EMBEDDED_MANIFEST_NAME
    if not embedded_path.is_file():
        return BuildManifestCollection(
            mode="unknown", status="unknown_runtime", build_input=None,
            installed_runtime=None, production_source=None, provenance=None,
            reason_codes=("embedded_build_manifest_missing",),
        )
    try:
        embedded = json.loads(embedded_path.read_text(encoding=UTF8))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return BuildManifestCollection(
            mode="unknown", status="unknown_runtime", build_input=None,
            installed_runtime=None, production_source=None, provenance=None,
            reason_codes=("embedded_build_manifest_unreadable",),
        )
    if not verify_definition(embedded):
        return BuildManifestCollection(
            mode="unknown", status="unknown_runtime", build_input=None,
            installed_runtime=None, production_source=None, provenance=None,
            reason_codes=("embedded_build_manifest_invalid",),
        )
    payload = embedded["payload"]
    expected_installed = payload.get("installed_runtime_definition")
    build_input = payload.get("build_input_definition")
    if not isinstance(expected_installed, dict) or not verify_definition(expected_installed):
        raise FingerprintUnavailable("embedded_installed_manifest_invalid")
    if not isinstance(build_input, dict) or not verify_definition(build_input):
        raise FingerprintUnavailable("embedded_build_input_manifest_invalid")
    actual_installed = file_manifest_definition(
        schema="RuntimeInstalledRuntimeManifestV1", root=package_root.parent,
        paths=installed_runtime_paths(package_root), mode="packaged_source_files",
    )
    exact = (
        actual_installed["definition_sha256"]
        == expected_installed["definition_sha256"]
    )
    return BuildManifestCollection(
        mode="packaged", status=(
            "verified_packaged_manifest" if exact else "packaged_manifest_mismatch"
        ),
        build_input=build_input, installed_runtime=actual_installed,
        production_source=None, provenance=embedded,
        reason_codes=() if exact else ("installed_runtime_manifest_mismatch",),
    )


def collect_build_manifests(
    *, module_file: Path | None = None,
) -> BuildManifestCollection:
    package_root = (module_file or Path(__file__)).resolve().parent
    repository = find_git_repository(package_root)
    if repository is not None:
        return git_workspace_collection(repository)
    return packaged_collection(package_root)


def write_embedded_build_manifest(repository: Path, target: Path) -> None:
    definition = embedded_build_manifest(repository)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(definition, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding=UTF8, newline="\n",
    )
