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
        (snapshot_root / "manifest.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return cls(project_root, snapshot_root, entries)

    def restore(self) -> None:
        for entry in self.entries:
            destination = self.project_root / entry["path"]
            if not entry["existed"]:
                destination.unlink(missing_ok=True)
                continue
            source = self.snapshot_root / "files" / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
