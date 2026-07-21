import json
import re
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
        self._scaffold_story_files(path, payload)
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

    def load_constraints(self, project_id: str) -> str:
        project = self.get(project_id)
        parts = []
        for raw_path in project.metadata.get("root_constraints", []):
            path = Path(raw_path)
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
        parts.append((project.path / "constraints.md").read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _scaffold_story_files(path: Path, payload: ProjectCreate) -> None:
        (path / "story.md").write_text(
            f"---\ntitle: {payload.title}\nschema-version: 2\ngenre: {payload.genre}\n"
            f"sub-genre: general\nsetting-era: unspecified\nstatus: planning\n"
            f"themes:\n  - change\npov: {payload.pov}\ntense: past\n---\n\n"
            f"# {payload.title}\n\n## Synopsis\n\n{payload.premise}\n\n"
            f"## Tone & Style\n\n{payload.tone}\n\n## Notes\n",
            encoding="utf-8",
        )
        registry_files = {
            "chapters/_index.md": "chapter-registry",
            "characters/_index.md": "character-registry",
            "continuity/promises/_index.md": "promise-registry",
            "continuity/questions/_index.md": "question-registry",
            "glossary/_index.md": "glossary-registry",
            "plot/_index.md": "plot-registry",
            "scenes/_index.md": "scene-registry",
            "worldbuilding/_index.md": "worldbuilding-registry",
        }
        for relative, kind in registry_files.items():
            (path / relative).write_text(
                f"---\ntype: {kind}\nstory: {path.name}\n---\n\n# Index\n",
                encoding="utf-8",
            )
        (path / "continuity" / "state.md").write_text(
            "---\ntype: continuity-state\n---\n\n# Current State\n", encoding="utf-8",
        )
        (path / "plot" / "timeline.md").write_text(
            "---\ntype: timeline\n---\n\n# Timeline\n", encoding="utf-8",
        )
