from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from novel_flywheel.db import Database


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    mode: Literal["short", "long"]
    genre: str = Field(min_length=1, max_length=80)
    premise: str = Field(min_length=1)
    target_words: int = Field(ge=500, le=5_000_000)
    pov: str = "third-limited"
    tone: str = "natural"
    must_include: str = ""
    must_avoid: str = ""


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    mode: str
    path: Path
    metadata: dict


class ProjectStore:
    def __init__(self, db: Database, workspace_root: Path,
                 root_constraints: list[Path] | None = None) -> None:
        self.db = db
        self.workspace_root = workspace_root.resolve()
        self.trash_root = (self.workspace_root.parent / "trash").resolve()
        self.root_constraints = [path.resolve() for path in (root_constraints or []) if path.is_file()]

    def create(self, payload: ProjectCreate) -> Project:
        slug = re.sub(r"[^\w-]+", "-", payload.title.strip(), flags=re.UNICODE).strip("-_").lower()
        if not slug or slug in {".", ".."}:
            raise ValueError("Project title must contain letters or numbers")
        project_id = uuid.uuid4().hex[:12]
        path = (self.workspace_root / f"{slug}-{project_id[:6]}").resolve()
        if not path.is_relative_to(self.workspace_root):
            raise ValueError("Invalid project path")
        path.mkdir(parents=True, exist_ok=False)
        for folder in (
            "memory", "manuscript", "runs", "snapshots", "chapters", "characters",
            "continuity/promises", "continuity/questions", "glossary/terms", "plot/arcs",
            "scenes", "worldbuilding/artifacts", "worldbuilding/factions",
            "worldbuilding/locations", "worldbuilding/systems",
        ):
            (path / folder).mkdir(parents=True, exist_ok=True)
        if payload.mode == "long":
            (path / "volumes").mkdir()
        metadata = {
            "id": project_id,
            **payload.model_dump(),
            "root_constraints": [str(item) for item in self.root_constraints],
        }
        self._write_json(path / "project.json", metadata)
        self._write_json(path / "memory" / "canon.json", {"facts": []})
        (path / "constraints.md").write_text(
            f"# Project Constraints\n\n## Must Include\n{payload.must_include or 'None'}\n\n"
            f"## Must Avoid\n{payload.must_avoid or 'None'}\n",
            encoding="utf-8",
        )
        self._scaffold_story_files(path, payload, project_id)
        self.db.save_project(project_id, payload.title, payload.mode, path)
        return Project(project_id, payload.title, payload.mode, path, metadata)

    def get(self, project_id: str) -> Project:
        row = self.db.get_project(project_id)
        if row is None:
            raise LookupError("Project not found")
        path = Path(row["path"])
        metadata = json.loads((path / "project.json").read_text(encoding="utf-8"))
        return Project(row["id"], row["title"], row["mode"], path, metadata)

    def list(self) -> list[Project]:
        return [self.get(row["id"]) for row in self.db.list_projects()]

    def trash(self, project_id: str) -> dict:
        row = self.db.get_project(project_id)
        if row is None:
            raise LookupError("Project not found")
        if self.db.has_active_runs(project_id):
            raise ValueError("Project has an active run; cancel it before moving to trash")
        source = Path(row["path"]).resolve()
        if not source.is_relative_to(self.workspace_root):
            raise ValueError("Project path is outside the workspace")
        self.trash_root.mkdir(parents=True, exist_ok=True)
        target = (self.trash_root / project_id).resolve()
        if not target.is_relative_to(self.trash_root):
            raise ValueError("Invalid trash path")
        if target.exists():
            raise ValueError("Project already exists in trash")
        shutil.move(str(source), str(target))
        try:
            self.db.trash_project(project_id, source, target)
        except Exception:
            shutil.move(str(target), str(source))
            raise
        return {"id": project_id, "title": row["title"], "mode": row["mode"],
                "path": target, "original_path": source}

    def list_trash(self) -> list[dict]:
        return [{**row, "path": Path(row["trash_path"]),
                 "original_path": Path(row["original_path"])}
                for row in self.db.list_trashed_projects()]

    def restore(self, project_id: str) -> Project:
        row = self.db.get_trashed_project(project_id)
        if row is None:
            raise LookupError("Trashed project not found")
        source = Path(row["trash_path"]).resolve()
        target = Path(row["original_path"]).resolve()
        if not source.is_relative_to(self.trash_root) or not target.is_relative_to(self.workspace_root):
            raise ValueError("Project restore path is outside managed roots")
        if target.exists():
            raise ValueError("Original project path already exists")
        shutil.move(str(source), str(target))
        try:
            self.db.restore_project(project_id, target)
        except Exception:
            shutil.move(str(target), str(source))
            raise
        return self.get(project_id)

    def delete_permanently(self, project_id: str) -> None:
        row = self.db.get_trashed_project(project_id)
        if row is None:
            raise LookupError("Trashed project not found")
        path = Path(row["trash_path"]).resolve()
        if not path.is_relative_to(self.trash_root) or path == self.trash_root:
            raise ValueError("Project path is outside the trash root")
        if path.exists():
            shutil.rmtree(path)
        self.db.delete_project_data(project_id)

    def load_constraints(self, project_id: str) -> str:
        project = self.get(project_id)
        parts = []
        for raw_path in project.metadata.get("root_constraints", []):
            path = Path(raw_path)
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
        parts.append((project.path / "constraints.md").read_text(encoding="utf-8"))
        locks_path = project.path / "continuity" / "locks.json"
        if locks_path.is_file():
            locks = json.loads(locks_path.read_text(encoding="utf-8")).get("locks", [])
            if locks:
                parts.append("# Program-enforced locked story facts\n\n" + "\n".join(
                    f"- {item['key']}: {json.dumps(item.get('value'), ensure_ascii=False)}"
                    for item in locks
                ))
        return "\n\n".join(parts)

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _scaffold_story_files(path: Path, payload: ProjectCreate, project_id: str) -> None:
        (path / "story.md").write_text(
            f"---\ntitle: {payload.title}\nstory: {project_id}\nschema-version: 2\ngenre: {payload.genre}\n"
            f"sub-genre: general\nsetting-era: unspecified\nstatus: planning\n"
            f"themes:\n  - change\npov: {payload.pov}\ntense: past\n---\n\n"
            f"# {payload.title}\n\n## Synopsis\n\n{payload.premise}\n\n"
            f"## Tone & Style\n\n{payload.tone}\n\n## Notes\n",
            encoding="utf-8",
        )
        registry_files = {
            "chapters/_index.md": ("chapter-registry", "# Chapters\n\n| # | Title | POV | Status | Word Count | File |\n|---|---|---|---|---|---|\n\n## Total Word Count: 0"),
            "characters/_index.md": ("character-registry", "# Characters\n\n| Name | Role | Status | File |\n|---|---|---|---|\n\n## Relationship Map\n\n## Family Trees"),
            "continuity/promises/_index.md": ("promise-registry", "# Story Promises\n\n| Promise | Status | Planted | Payoff | File |\n|---|---|---|---|---|"),
            "continuity/questions/_index.md": ("question-registry", "# Open Questions\n\n| Question | Status | Opened | Answered | File |\n|---|---|---|---|---|"),
            "glossary/_index.md": ("glossary-registry", "# Glossary\n\n| Term | Meaning | File |\n|---|---|---|"),
            "plot/_index.md": ("plot-registry\nstructure: three-act", "# Plot Structure\n\n## Story Structure\n\n**Model:** Three-Act Structure\n\n## Arcs\n\n| Name | Type | Status | File |\n|---|---|---|---|\n\n## Theme Tracking"),
            "scenes/_index.md": ("scene-registry", "# Scenes\n\n| Scene | Chapter | POV | Location | Status |\n|---|---|---|---|---|"),
            "worldbuilding/_index.md": ("world-registry", "# Worldbuilding\n\n## World Overview\n\n## Locations\n\n| Name | Type | Region | File |\n|---|---|---|---|\n\n## Systems\n\n| Name | Type | File |\n|---|---|---|\n\n## Factions\n\n| Name | Type | Status | File |\n|---|---|---|---|\n\n## Artifacts\n\n| Name | Type | Status | File |\n|---|---|---|---|"),
        }
        for relative, (kind, body) in registry_files.items():
            (path / relative).write_text(
                f"---\ntype: {kind}\nstory: {project_id}\n---\n\n{body}\n",
                encoding="utf-8",
            )
        (path / "continuity" / "state.md").write_text(
            f"---\ntype: continuity-state\nstory: {project_id}\ncurrent-chapter: 0\ncharacter-state: []\nobject-state: []\nknowledge-state: []\n---\n\n# Current State\n", encoding="utf-8",
        )
        (path / "continuity" / "locks.json").write_text("{\n  \"locks\": []\n}\n", encoding="utf-8")
        (path / "plot" / "timeline.md").write_text(
            f"---\ntype: timeline\nstory: {project_id}\n---\n\n# Timeline\n", encoding="utf-8",
        )
