import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.wizard import SkillFormCatalog, WizardService


def write_skill(root, name, body="Instructions", form=None):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}", encoding="utf-8")
    if form:
        (folder / "forms").mkdir()
        (folder / "forms" / "project.json").write_text(json.dumps(form), encoding="utf-8")


def test_catalog_combines_core_known_and_sidecar_forms(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "story-init")
    write_skill(root, "character-management")
    sidecar = {"title": "Custom", "fields": [{"id": "custom.rule", "label": "Rule", "type": "text"}]}
    write_skill(root, "custom-init", form=sidecar)
    gate = SkillGate(Database(tmp_path / "app.db"), SkillScanner([root]))
    gate.db.migrate()
    catalog = SkillFormCatalog(gate, tmp_path / "cache")

    schema = catalog.build("long", ["story-init", "character-management", "custom-init"])

    ids = {field["id"] for step in schema["steps"] for field in step["fields"]}
    assert {"title", "market_baseline_enabled", "market_baseline_key", "protagonist.name", "custom.rule"} <= ids
    assert any(step.get("skill_name") == "character-management" for step in schema["steps"])


def test_generated_form_cache_is_keyed_by_skill_hash(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "unknown-init", "First")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))
    calls = []
    generator = lambda skill: calls.append(skill.content_hash) or {
        "title": "Generated", "fields": [{"id": "generated.note", "label": "Note", "type": "textarea"}],
    }
    catalog = SkillFormCatalog(gate, tmp_path / "cache", generator)

    catalog.build("long", ["unknown-init"])
    catalog.build("long", ["unknown-init"])
    assert len(calls) == 1
    (root / "unknown-init" / "SKILL.md").write_text("---\nname: unknown-init\n---\nSecond", encoding="utf-8")
    catalog.build("long", ["unknown-init"])
    assert len(calls) == 2


def test_initialization_skill_is_auto_discovered(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "genre-init", "Start a new story.\n- Locked genre convention\n- Required opening image")
    db = Database(tmp_path / "app.db")
    db.migrate()
    catalog = SkillFormCatalog(SkillGate(db, SkillScanner([root])), tmp_path / "cache")
    schema = catalog.build("short")
    assert any(step.get("skill_name") == "genre-init" for step in schema["steps"])


def test_wizard_autosaves_and_confirms_locked_canonical_project(tmp_path) -> None:
    root = tmp_path / "skills"
    for name in ("story-init", "character-management", "worldbuilding", "plot-structure"):
        write_skill(root, name)
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))
    store = ProjectStore(db, tmp_path / "workspace")
    service = WizardService(db, store, SkillFormCatalog(gate, tmp_path / "cache"))
    wizard = service.create("long")
    answers = {
        "title": {"value": "Locked Book", "policy": "locked"},
        "genre": {"value": "fantasy", "policy": "locked"},
        "premise": {"value": "An oath survives.", "policy": "locked"},
        "target_words": {"value": 500000, "policy": "suggestible"},
        "ending": {"value": "The oath is fulfilled.", "policy": "locked"},
    }
    service.save_answers(wizard["id"], answers)

    project = service.confirm(wizard["id"])

    assert service.get(wizard["id"])["status"] == "completed"
    assert (project.path / "continuity" / "locks.json").is_file()
    locks = json.loads((project.path / "continuity" / "locks.json").read_text(encoding="utf-8"))
    assert any(item["key"] == "ending" for item in locks["locks"])
    assert "The oath is fulfilled" in (project.path / "story.md").read_text(encoding="utf-8")
    assert (project.path / "worldbuilding" / "_index.md").is_file()
    assert "Program-enforced locked story facts" in service.projects.load_constraints(project.id)


def test_wizard_rejects_missing_required_answers(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([]))
    service = WizardService(db, ProjectStore(db, tmp_path / "workspace"), SkillFormCatalog(gate, tmp_path / "cache"))
    wizard = service.create("short")
    with pytest.raises(ValueError, match="required"):
        service.confirm(wizard["id"])
