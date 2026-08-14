"""Content manifests and import-closure checks for the Canary launcher."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import sys
from typing import Iterable

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


MANIFEST_SCHEMA = "CanaryLauncherDependencyManifestV1"
_FORBIDDEN_DYNAMIC_MODULES = frozenset({"importlib", "pkgutil", "runpy"})
_FORBIDDEN_CALLS = frozenset({"__import__", "compile", "eval", "exec"})


class CanaryDependencyError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail = detail


def _files(root: Path) -> list[Path]:
    resolved_root = root.resolve(strict=True)
    result: list[Path] = []
    for path in resolved_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise CanaryDependencyError("launcher_symlink_forbidden", str(path))
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise CanaryDependencyError("launcher_path_escape", str(path)) from exc
        result.append(resolved)
    return sorted(result, key=lambda item: item.relative_to(resolved_root).as_posix())


def launcher_dependency_manifest(
    root: Path, *, approved_third_party: Iterable[str] = (),
) -> dict:
    resolved_root = root.resolve(strict=True)
    approved = sorted(set(approved_third_party))
    entries = [{
        "path": path.relative_to(resolved_root).as_posix(),
        "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    } for path in _files(resolved_root)]
    body = {
        "schema": MANIFEST_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "path_normalization": "launcher-root-relative-posix-v1",
        "files": entries,
        "allowed_local_roots": ["tools.canary", "novel_flywheel"],
        "approved_third_party": approved,
    }
    return {
        **body,
        "launcher_sha256": domain_sha256(
            "novel-flywheel-canary-launcher-v1", body,
        ),
    }


def _root_module(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def validate_import_closure(
    root: Path, *, approved_third_party: Iterable[str] = (),
) -> dict:
    approved = set(approved_third_party)
    stdlib = set(sys.stdlib_module_names)
    violations: list[dict[str, str]] = []
    for path in _files(root):
        relative = path.relative_to(root.resolve(strict=True)).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = _root_module(alias.name)
                    if module in _FORBIDDEN_DYNAMIC_MODULES:
                        violations.append({"path": relative, "code": "dynamic_import_forbidden"})
                    elif module not in stdlib | approved | {"novel_flywheel", "tools"}:
                        violations.append({"path": relative, "code": "dependency_not_approved"})
            elif isinstance(node, ast.ImportFrom):
                module = _root_module(node.module)
                if node.level:
                    continue
                if module in _FORBIDDEN_DYNAMIC_MODULES:
                    violations.append({"path": relative, "code": "dynamic_import_forbidden"})
                elif module not in stdlib | approved | {"novel_flywheel", "tools"}:
                    violations.append({"path": relative, "code": "dependency_not_approved"})
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_CALLS:
                    violations.append({"path": relative, "code": "dynamic_code_forbidden"})
        if "tests" in relative.split("/"):
            violations.append({"path": relative, "code": "test_helper_in_launcher"})
    if violations:
        first = sorted(violations, key=lambda item: (item["path"], item["code"]))[0]
        raise CanaryDependencyError(first["code"], first["path"])
    return launcher_dependency_manifest(root, approved_third_party=approved)
