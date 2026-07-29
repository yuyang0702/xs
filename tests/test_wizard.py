import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

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


def wizard_service_for(tmp_path) -> WizardService:
    db = Database(tmp_path / "app.db")
    db.migrate()
    return WizardService(
        db,
        ProjectStore(db, tmp_path / "workspace"),
        SkillFormCatalog(SkillGate(db, SkillScanner([])), tmp_path / "cache"),
    )


def ready_short_wizard(service: WizardService) -> dict:
    wizard = service.create("short")
    service.save_answers(wizard["id"], {
        "title": {"value": "并发测试", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    })
    return wizard


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
    assert {"title", "platform_profile_id", "market_baseline_enabled", "market_baseline_key", "protagonist.name", "custom.rule"} <= ids
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


def test_wizard_service_deletes_only_unfinished_projectless_draft(tmp_path) -> None:
    service = wizard_service_for(tmp_path)
    draft = service.create("short")

    deleted = service.delete(draft["id"])

    assert deleted == {"id": draft["id"], "deleted": True}
    with pytest.raises(LookupError, match="Wizard not found"):
        service.get(draft["id"])


@pytest.mark.parametrize(
    ("status", "project_id"),
    [("completed", None), ("draft", "project-1")],
)
def test_wizard_service_refuses_completed_or_project_linked_wizard(
    tmp_path, status, project_id,
) -> None:
    service = wizard_service_for(tmp_path)
    draft = service.create("short")
    service.db.save_wizard(
        draft["id"], status, "short", draft["schema"], draft["answers"],
        project_id=project_id,
    )

    with pytest.raises(ValueError, match="已经创建作品"):
        service.delete(draft["id"])

    assert service.get(draft["id"])["status"] == status
    assert service.get(draft["id"])["project_id"] == project_id


def test_confirm_then_delete_serializes_to_project_and_conflict(tmp_path, monkeypatch) -> None:
    service = wizard_service_for(tmp_path)
    wizard = ready_short_wizard(service)
    confirm_paused = Event()
    release_confirm = Event()
    delete_attempted = Event()
    delete_finished = Event()
    original_create = service.projects.create

    def paused_create(payload):
        confirm_paused.set()
        assert release_confirm.wait(5)
        return original_create(payload)

    def delete():
        delete_attempted.set()
        try:
            return service.delete(wizard["id"])
        finally:
            delete_finished.set()

    monkeypatch.setattr(service.projects, "create", paused_create)
    with ThreadPoolExecutor(max_workers=2) as executor:
        confirmed = executor.submit(service.confirm, wizard["id"])
        assert confirm_paused.wait(5)
        deleted = executor.submit(delete)
        assert delete_attempted.wait(5)
        assert not delete_finished.wait(0.1)
        release_confirm.set()
        project = confirmed.result(timeout=5)
        with pytest.raises(ValueError, match="已经创建作品"):
            deleted.result(timeout=5)

    assert delete_finished.is_set()
    assert len(service.projects.list()) == 1
    assert service.get(wizard["id"])["project_id"] == project.id


def test_delete_then_confirm_serializes_to_deletion_without_project(tmp_path, monkeypatch) -> None:
    service = wizard_service_for(tmp_path)
    wizard = ready_short_wizard(service)
    delete_paused = Event()
    release_delete = Event()
    confirm_attempted = Event()
    confirm_finished = Event()
    original_delete = service.db.delete_wizard

    def paused_delete(wizard_id):
        delete_paused.set()
        assert release_delete.wait(5)
        return original_delete(wizard_id)

    def confirm():
        confirm_attempted.set()
        try:
            return service.confirm(wizard["id"])
        finally:
            confirm_finished.set()

    monkeypatch.setattr(service.db, "delete_wizard", paused_delete)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleted = executor.submit(service.delete, wizard["id"])
        assert delete_paused.wait(5)
        confirmed = executor.submit(confirm)
        assert confirm_attempted.wait(5)
        assert not confirm_finished.wait(0.1)
        release_delete.set()
        assert deleted.result(timeout=5) == {"id": wizard["id"], "deleted": True}
        with pytest.raises(LookupError, match="Wizard not found"):
            confirmed.result(timeout=5)

    assert confirm_finished.is_set()
    assert service.db.get_wizard(wizard["id"]) is None
    assert service.projects.list() == []


def test_delete_then_autosave_does_not_recreate_wizard(tmp_path, monkeypatch) -> None:
    service = wizard_service_for(tmp_path)
    wizard = service.create("short")
    delete_paused = Event()
    release_delete = Event()
    save_attempted = Event()
    save_finished = Event()
    original_delete = service.db.delete_wizard

    def paused_delete(wizard_id):
        delete_paused.set()
        assert release_delete.wait(5)
        return original_delete(wizard_id)

    def autosave():
        save_attempted.set()
        try:
            return service.save_answers(wizard["id"], {
                "title": {"value": "不能复活", "policy": "locked"},
            })
        finally:
            save_finished.set()

    monkeypatch.setattr(service.db, "delete_wizard", paused_delete)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleted = executor.submit(service.delete, wizard["id"])
        assert delete_paused.wait(5)
        saved = executor.submit(autosave)
        assert save_attempted.wait(5)
        assert not save_finished.wait(0.1)
        release_delete.set()
        assert deleted.result(timeout=5) == {"id": wizard["id"], "deleted": True}
        with pytest.raises(LookupError, match="Wizard not found"):
            saved.result(timeout=5)

    assert save_finished.is_set()
    assert service.db.get_wizard(wizard["id"]) is None
