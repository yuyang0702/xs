"""Physical Canary root identity and live-root separation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)


SENTINEL_NAME = ".canary-root-v1.json"
SUBDIRECTORIES = ("db", "projects", "logs", "trace", "sidecars", "reports", "approvals")


class CanaryIsolationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _assert_no_reparse_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:] if path.anchor else path.parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise CanaryIsolationError("canary_root_reparse_point")


def _sentinel_body(
    *, stable_root_identity: str, plan_sha256: str, run_namespace: str,
) -> dict:
    return {
        "schema": "CanaryRootSentinelV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "stable_root_identity": stable_root_identity,
        "plan_sha256": plan_sha256,
        "run_namespace": run_namespace,
        "creation_policy": "empty-new-root-only-v1",
    }


def create_canary_root(
    root: Path, *, stable_root_identity: str, plan_sha256: str,
    run_namespace: str, live_roots: Iterable[Path],
) -> dict:
    candidate = root.resolve(strict=False)
    for live in live_roots:
        live_resolved = live.resolve(strict=True)
        if (_is_relative_to(candidate, live_resolved)
                or _is_relative_to(live_resolved, candidate)):
            raise CanaryIsolationError("canary_live_root_overlap")
    if root.exists() and any(root.iterdir()):
        raise CanaryIsolationError("canary_root_not_empty")
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=True)
    _assert_no_reparse_components(resolved)
    for live in live_roots:
        live_resolved = live.resolve(strict=True)
        if _is_relative_to(resolved, live_resolved) or _is_relative_to(live_resolved, resolved):
            raise CanaryIsolationError("canary_live_root_overlap")
    body = _sentinel_body(
        stable_root_identity=stable_root_identity,
        plan_sha256=plan_sha256,
        run_namespace=run_namespace,
    )
    sentinel = {
        **body,
        "sentinel_sha256": domain_sha256("novel-flywheel-canary-root-v1", body),
    }
    sentinel_path = resolved / SENTINEL_NAME
    try:
        with sentinel_path.open("xb") as handle:
            handle.write(canonical_json_bytes(sentinel) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CanaryIsolationError("canary_sentinel_already_exists") from exc
    for name in SUBDIRECTORIES:
        (resolved / name).mkdir()
    return validate_canary_root(
        resolved, stable_root_identity=stable_root_identity,
        plan_sha256=plan_sha256, run_namespace=run_namespace,
        live_roots=live_roots,
    )


def validate_canary_root(
    root: Path, *, stable_root_identity: str, plan_sha256: str,
    run_namespace: str, live_roots: Iterable[Path],
) -> dict:
    resolved = root.resolve(strict=True)
    _assert_no_reparse_components(resolved)
    for live in live_roots:
        live_resolved = live.resolve(strict=True)
        if _is_relative_to(resolved, live_resolved) or _is_relative_to(live_resolved, resolved):
            raise CanaryIsolationError("canary_live_root_overlap")
    sentinel_path = resolved / SENTINEL_NAME
    if not sentinel_path.is_file() or _is_reparse_point(sentinel_path):
        raise CanaryIsolationError("canary_sentinel_missing")
    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CanaryIsolationError("canary_sentinel_invalid") from exc
    body = _sentinel_body(
        stable_root_identity=stable_root_identity,
        plan_sha256=plan_sha256,
        run_namespace=run_namespace,
    )
    expected = domain_sha256("novel-flywheel-canary-root-v1", body)
    if sentinel != {**body, "sentinel_sha256": expected}:
        raise CanaryIsolationError("canary_sentinel_mismatch")
    subdirectories: dict[str, str] = {}
    for name in SUBDIRECTORIES:
        child = resolved / name
        if not child.is_dir() or _is_reparse_point(child):
            raise CanaryIsolationError("canary_subdirectory_invalid")
        child_resolved = child.resolve(strict=True)
        if child_resolved.parent != resolved:
            raise CanaryIsolationError("canary_subdirectory_escape")
        subdirectories[name] = domain_sha256(
            "novel-flywheel-canary-path-identity-v1", {"role": name},
        )
    return {
        "schema": "CanaryRootValidationV1",
        "validation_status": "exact",
        "stable_root_identity": stable_root_identity,
        "sentinel_sha256": expected,
        "resolved_root_sha256": domain_sha256(
            "novel-flywheel-canary-resolved-root-v1",
            {"normalized": resolved.as_posix().casefold()},
        ),
        "subdirectory_identities": subdirectories,
    }
