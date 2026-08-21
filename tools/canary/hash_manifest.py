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

GENERIC_CANARY_IMPORT_SCOPE_ID = "generic_canary_launcher_v1"
PTR4_PROVIDER_PROBE_IMPORT_SCOPE_ID = "r1_ptr4_provider_capability_probe_1"
PTR7_REASONING_PROBE_IMPORT_SCOPE_ID = (
    "r1_ptr7_provider_reasoning_capability_probe_1"
)
_PROBE_ONLY_ENTRYPOINTS = {
    PTR4_PROVIDER_PROBE_IMPORT_SCOPE_ID: "provider_capability_probe_real.py",
    PTR7_REASONING_PROBE_IMPORT_SCOPE_ID: (
        "provider_reasoning_capability_probe_real.py"
    ),
}
_PROFILE_APPROVED_THIRD_PARTY = {
    PTR4_PROVIDER_PROBE_IMPORT_SCOPE_ID: (),
    PTR7_REASONING_PROBE_IMPORT_SCOPE_ID: ("httpx",),
}


class CanaryDependencyError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail = detail


def _files(
    root: Path, *, excluded_relative_paths: Iterable[str] = (),
) -> list[Path]:
    resolved_root = root.resolve(strict=True)
    excluded = frozenset(excluded_relative_paths)
    result: list[Path] = []
    for path in resolved_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise CanaryDependencyError("launcher_symlink_forbidden", str(path))
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise CanaryDependencyError("launcher_path_escape", str(path)) from exc
        if relative in excluded:
            continue
        result.append(resolved)
    return sorted(result, key=lambda item: item.relative_to(resolved_root).as_posix())


def canary_import_scope_definition(profile_id: str) -> dict:
    if profile_id == GENERIC_CANARY_IMPORT_SCOPE_ID:
        included_probe_entrypoint = None
        excluded = sorted(_PROBE_ONLY_ENTRYPOINTS.values())
        approved = []
    elif profile_id in _PROBE_ONLY_ENTRYPOINTS:
        included_probe_entrypoint = _PROBE_ONLY_ENTRYPOINTS[profile_id]
        excluded = sorted(
            value for key, value in _PROBE_ONLY_ENTRYPOINTS.items()
            if key != profile_id
        )
        approved = list(_PROFILE_APPROVED_THIRD_PARTY[profile_id])
    else:
        raise CanaryDependencyError("import_closure_profile_unknown", profile_id)
    return {
        "scope_id": profile_id,
        "included_probe_entrypoint": included_probe_entrypoint,
        "excluded_probe_entrypoints": excluded,
        "approved_third_party": approved,
    }


def launcher_dependency_manifest(
    root: Path, *, approved_third_party: Iterable[str] = (),
    excluded_relative_paths: Iterable[str] = (),
    import_scope_id: str = GENERIC_CANARY_IMPORT_SCOPE_ID,
) -> dict:
    resolved_root = root.resolve(strict=True)
    approved = sorted(set(approved_third_party))
    excluded = sorted(set(excluded_relative_paths))
    entries = [{
        "path": path.relative_to(resolved_root).as_posix(),
        "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    } for path in _files(
        resolved_root, excluded_relative_paths=excluded,
    )]
    body = {
        "schema": MANIFEST_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "path_normalization": "launcher-root-relative-posix-v1",
        "files": entries,
        "allowed_local_roots": ["tools.canary", "novel_flywheel"],
        "approved_third_party": approved,
        "import_scope_id": import_scope_id,
        "excluded_probe_entrypoints": excluded,
    }
    return {
        **body,
        "launcher_sha256": domain_sha256(
            "novel-flywheel-canary-launcher-v1", body,
        ),
    }


def _root_module(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def _references_excluded_module(
    node: ast.Import | ast.ImportFrom, excluded_module_names: frozenset[str],
) -> bool:
    if isinstance(node, ast.Import):
        names = [part for alias in node.names for part in alias.name.split(".")]
    else:
        names = (node.module or "").split(".")
        names.extend(alias.name for alias in node.names)
    return bool(excluded_module_names.intersection(names))


def validate_import_closure(
    root: Path, *, approved_third_party: Iterable[str] = (),
    excluded_relative_paths: Iterable[str] | None = None,
    import_scope_id: str = GENERIC_CANARY_IMPORT_SCOPE_ID,
) -> dict:
    if excluded_relative_paths is None:
        scope = canary_import_scope_definition(GENERIC_CANARY_IMPORT_SCOPE_ID)
        excluded_relative_paths = scope["excluded_probe_entrypoints"]
    excluded = frozenset(excluded_relative_paths)
    excluded_module_names = frozenset(Path(item).stem for item in excluded)
    approved = set(approved_third_party)
    stdlib = set(sys.stdlib_module_names)
    violations: list[dict[str, str]] = []
    for path in _files(root, excluded_relative_paths=excluded):
        relative = path.relative_to(root.resolve(strict=True)).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                if _references_excluded_module(node, excluded_module_names):
                    violations.append({
                        "path": relative, "code": "excluded_module_reachable",
                    })
                for alias in node.names:
                    module = _root_module(alias.name)
                    if module in _FORBIDDEN_DYNAMIC_MODULES:
                        violations.append({"path": relative, "code": "dynamic_import_forbidden"})
                    elif module not in stdlib | approved | {"novel_flywheel", "tools"}:
                        violations.append({"path": relative, "code": "dependency_not_approved"})
            elif isinstance(node, ast.ImportFrom):
                if _references_excluded_module(node, excluded_module_names):
                    violations.append({
                        "path": relative, "code": "excluded_module_reachable",
                    })
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
    return launcher_dependency_manifest(
        root, approved_third_party=approved,
        excluded_relative_paths=excluded,
        import_scope_id=import_scope_id,
    )


def validate_profile_import_closure(root: Path, *, profile_id: str) -> dict:
    scope = canary_import_scope_definition(profile_id)
    return validate_import_closure(
        root,
        approved_third_party=scope["approved_third_party"],
        excluded_relative_paths=scope["excluded_probe_entrypoints"],
        import_scope_id=profile_id,
    )
