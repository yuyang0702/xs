import json
import uuid
from pathlib import Path
from typing import Callable

from novel_flywheel.projects import Project
from novel_flywheel.storage import ProjectSnapshot, atomic_write


class ProjectMigrator:
    def __init__(self, story_command: Callable[[Project, str], object]) -> None:
        self.story_command = story_command

    def dry_run(self, project: Project) -> dict:
        outline = project.path / "outline.md"
        canon_path = project.path / "memory" / "canon.json"
        canon = json.loads(canon_path.read_text(encoding="utf-8")) if canon_path.is_file() else {"facts": []}
        mapped = []
        ambiguous = []
        for fact in canon.get("facts", []):
            if isinstance(fact, dict) and fact.get("fact_key") and ("value" in fact or "fact" in fact):
                mapped.append({"key": str(fact["fact_key"]), "value": fact.get("value", fact.get("fact"))})
            else:
                ambiguous.append(fact)
        return {
            "project_id": project.id,
            "status": "dry-run",
            "outline_found": outline.is_file(),
            "mapped_facts": mapped,
            "ambiguous_facts": ambiguous,
            "preserved_files": [item for item in ("outline.md", "memory/canon.json") if (project.path / item).is_file()],
        }

    def migrate(self, project: Project) -> dict:
        report = self.dry_run(project)
        story_path = project.path / "story.md"
        canon_notes = project.path / "continuity" / "migrated-canon.md"
        report_path = project.path / "migration-report.json"
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / f"migration-{uuid.uuid4().hex}",
            [story_path, canon_notes, report_path],
        )
        try:
            story = story_path.read_text(encoding="utf-8")
            outline = project.path / "outline.md"
            if outline.is_file() and "## Migrated Legacy Outline" not in story:
                story += "\n\n## Migrated Legacy Outline\n\n" + outline.read_text(encoding="utf-8")
                atomic_write(story_path, story)
            facts = report["mapped_facts"]
            notes = (
                "---\ntype: migrated-canon\nstatus: review\n---\n\n# Migrated Canon\n\n" +
                "\n".join(f"- **{item['key']}**: {item['value']}" for item in facts) +
                "\n\n## Ambiguous Facts\n\n" +
                "\n".join(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in report["ambiguous_facts"])
            )
            atomic_write(canon_notes, notes)
            completed = {**report, "status": "completed"}
            atomic_write(report_path, json.dumps(completed, ensure_ascii=False, indent=2))
            for command in ("reindex", "links", "validate"):
                self.story_command(project, command)
            return completed
        except Exception:
            snapshot.restore()
            raise
