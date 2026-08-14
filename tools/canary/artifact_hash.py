"""Hash-only live and Canary artifact parity manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from novel_flywheel.runtime_fingerprint_build import domain_sha256


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict:
    if not root.exists():
        body = {"status": "absent", "file_count": 0, "entries": []}
        return {**body, "tree_sha256": domain_sha256(
            "novel-flywheel-canary-tree-v1", body,
        )}
    resolved = root.resolve(strict=True)
    entries = []
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(resolved).as_posix()
        entries.append({
            "path_id": domain_sha256(
                "novel-flywheel-canary-artifact-path-v1", relative,
            ),
            "content_sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        })
    body = {"status": "present", "file_count": len(entries), "entries": entries}
    return {**body, "tree_sha256": domain_sha256(
        "novel-flywheel-canary-tree-v1", body,
    )}


def live_parity_manifest(
    *, database_path: Path, project_root: Path,
    incident_roots: Iterable[Path] = (),
) -> dict:
    db = {
        "status": "present" if database_path.is_file() else "absent",
        "content_sha256": file_sha256(database_path) if database_path.is_file() else None,
        "size_bytes": database_path.stat().st_size if database_path.is_file() else 0,
    }
    projects = tree_manifest(project_root)
    incidents = [tree_manifest(path) for path in incident_roots]
    body = {"database": db, "projects": projects, "incident_roots": incidents}
    return {
        **body,
        "parity_sha256": domain_sha256("novel-flywheel-canary-live-parity-v1", body),
    }


def parity_equal(before: dict, after: dict) -> bool:
    return before.get("parity_sha256") == after.get("parity_sha256")
