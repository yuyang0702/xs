import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.migration import ProjectMigrator
from novel_flywheel.projects import ProjectCreate, ProjectStore


def make_project(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Legacy", mode="long", genre="fantasy", premise="Old.", target_words=100000,
    ))
    (project.path / "outline.md").write_text("# Old Outline\nEnding.", encoding="utf-8")
    (project.path / "memory" / "canon.json").write_text(json.dumps({"facts": [
        {"fact_key": "ending", "value": "The oath ends"},
        {"subject": "unknown", "fact": "Ambiguous note"},
    ]}), encoding="utf-8")
    return project


def test_migration_dry_run_and_apply_preserve_legacy_files(tmp_path) -> None:
    project = make_project(tmp_path)
    commands = []
    migrator = ProjectMigrator(lambda project, command: commands.append(command))
    report = migrator.dry_run(project)
    assert report["ambiguous_facts"]

    result = migrator.migrate(project)

    assert (project.path / "outline.md").is_file()
    assert "Old Outline" in (project.path / "story.md").read_text(encoding="utf-8")
    assert (project.path / "migration-report.json").is_file()
    assert commands == ["reindex", "links", "validate"]
    assert result["status"] == "completed"


def test_migration_rolls_back_on_validation_failure(tmp_path) -> None:
    project = make_project(tmp_path)
    original = (project.path / "story.md").read_text(encoding="utf-8")
    def fail(project, command):
        if command == "validate":
            raise RuntimeError("invalid")
    with pytest.raises(RuntimeError, match="invalid"):
        ProjectMigrator(fail).migrate(project)
    assert (project.path / "story.md").read_text(encoding="utf-8") == original
