import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


def atomic_write(path: Path, content: str,
                 replace: Callable[[Path, Path], None] = os.replace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProjectSnapshot:
    project_root: Path
    snapshot_root: Path
    entries: list[dict]

    @classmethod
    def create(cls, project_root: Path, snapshot_root: Path,
               files: list[Path]) -> "ProjectSnapshot":
        project_root = project_root.resolve()
        snapshot_root.mkdir(parents=True, exist_ok=False)
        entries = []
        for source in files:
            source = source.resolve()
            if not source.is_relative_to(project_root):
                raise ValueError("Snapshot files must be inside the project")
            relative = source.relative_to(project_root)
            exists = source.is_file()
            entry = {"path": relative.as_posix(), "existed": exists, "sha256": None}
            if exists:
                destination = snapshot_root / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                entry["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            entries.append(entry)
        atomic_write(
            snapshot_root / "manifest.json",
            json.dumps(entries, ensure_ascii=False, indent=2),
        )
        return cls(project_root, snapshot_root, entries)

    def restore(self) -> None:
        for entry in self.entries:
            destination = self.project_root / entry["path"]
            if not entry["existed"]:
                # A failed run may leave the file absent, or a user-created
                # directory at the same path.  Only remove a file/symlink;
                # never turn recovery into a second failure or delete a tree.
                if destination.is_file() or destination.is_symlink():
                    destination.unlink()
                continue
            source = self.snapshot_root / "files" / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    @classmethod
    def load(cls, project_root: Path, snapshot_root: Path) -> "ProjectSnapshot":
        project_root = project_root.resolve()
        snapshot_root = snapshot_root.resolve()
        if not snapshot_root.is_relative_to(project_root):
            raise ValueError("Snapshot must be inside the project")
        try:
            entries = json.loads(
                (snapshot_root / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Snapshot manifest is invalid") from exc
        if not isinstance(entries, list):
            raise ValueError("Snapshot manifest is invalid")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("Snapshot manifest is invalid")
            destination = (project_root / entry["path"]).resolve()
            if not destination.is_relative_to(project_root):
                raise ValueError("Snapshot path is outside the project")
            if entry.get("existed") is not True:
                if entry.get("existed") is not False:
                    raise ValueError("Snapshot manifest is invalid")
                continue
            source = (snapshot_root / "files" / entry["path"]).resolve()
            if not source.is_relative_to(snapshot_root) or not source.is_file():
                raise ValueError("Snapshot file is invalid")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != entry.get("sha256"):
                raise ValueError("Snapshot file hash is invalid")
        return cls(project_root, snapshot_root, entries)

    def discard(self) -> None:
        shutil.rmtree(self.snapshot_root, ignore_errors=True)
