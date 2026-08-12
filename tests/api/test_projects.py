import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from unittest.mock import Mock

from novel_flywheel.api import projects as projects_api
from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.storage import ProjectSnapshot
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.project_transactions import complete_project_mutation


class FakeStyleSamples:
    def __init__(self):
        self.value = {"configured": False, "source_characters": 0, "profile": None}

    def status(self, project):
        return {**self.value, "project_id": project.id}

    async def analyze(self, project, text, source_name):
        self.value = {
            "configured": True, "source_characters": len(text),
            "profile": {"summary": "克制的动作叙事", "source_name": source_name},
        }
        return self.status(project)

    def delete(self, project):
        self.value = {"configured": False, "source_characters": 0, "profile": None}
        return self.status(project)


def test_create_and_list_projects(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    response = client.post("/api/projects", json={
        "title": "Night Train", "mode": "short", "genre": "suspense",
        "premise": "A passenger disappears.", "target_words": 6000,
    })
    assert response.status_code == 201
    assert response.json()["mode"] == "short"
    assert client.get("/api/projects").json()[0]["title"] == "Night Train"


def test_planning_ir_rollout_is_complete_and_cannot_be_disabled(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Canary", "mode": "short", "genre": "mystery",
        "premise": "A sealed room opens.", "target_words": 6000,
    }).json()
    path = f"/api/projects/{project['id']}/rollout-flags/planning-ir-first"

    enabled = client.put(path, json={
        "enabled": True, "reason": "compatibility acknowledgement",
    })
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["scope_type"] == "system"
    flags = client.get(f"/api/projects/{project['id']}/rollout-flags").json()
    assert flags["planning_ir_first"]["config"] == {
        "reason": "rollout_complete", "immutable": True,
    }

    disabled = client.put(path, json={"enabled": False, "reason": "rollback"})
    assert disabled.status_code == 409
    assert disabled.json()["detail"]["code"] == "planning_ir_rollout_complete"
    assert client.get(f"/api/projects/{project['id']}/rollout-flags").json()[
        "planning_ir_first"
    ]["enabled"] is True


def test_zhihu_publication_preview_and_create_api(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Package", "mode": "short", "genre": "suspense",
        "premise": "A friend returns.", "target_words": 6000,
    }).json()
    project = app.state.projects.apply_platform_profile(created["id"], "zhihu-salt-short")
    text = "正式正文" * 1350
    (project.path / "manuscript" / "story.md").write_text(text, encoding="utf-8")
    output = project.path / "runs" / "done" / "outputs"
    output.mkdir(parents=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (output / "quality-report.json").write_text(json.dumps({
        "status": "passed", "terminal_reviewed_hash": digest,
        "scoring_profile_id": "zhihu-short-v2",
        "review": {"score": 88, "scoring_profile_id": "zhihu-short-v2"},
    }, ensure_ascii=False), encoding="utf-8")

    preview = client.get(f"/api/projects/{project.id}/publication/zhihu/preview")
    built = client.post(f"/api/projects/{project.id}/publication/zhihu", json={
        "title": "归来", "alternate_titles": [], "selling_point": "死者敲响我的门。",
        "introduction": "死去的朋友回来了。", "content_type": "悬疑",
        "audience": "悬疑读者", "expected_manuscript_hash": preview.json()["manuscript_hash"],
    })

    assert preview.status_code == 200
    assert preview.json()["ready"] is True
    assert built.status_code == 201
    assert built.json()["version"] == "v001"


def test_platform_profile_preview_and_apply_api(tmp_path) -> None:
    app = create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    project = client.post("/api/projects", json={
        "title": "Profile", "mode": "short", "genre": "suspense",
        "premise": "A friend returns.", "target_words": 6000,
    }).json()

    preview = client.post(f"/api/projects/{project['id']}/platform-profile/preview", json={
        "profile_id": "zhihu-salt-short",
    })
    applied = client.put(f"/api/projects/{project['id']}/platform-profile", json={
        "profile_id": "zhihu-salt-short",
    })

    assert preview.json()["will_change_manuscript"] is False
    assert applied.json()["platform_profile_id"] == "zhihu-salt-short"


def test_manuscript_falls_back_to_latest_run_candidate(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Recovery", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    db.create_run("failed-archive", project["id"], "short-story", status="failed")
    output = tmp_path / "workspace" / f"recovery-{project['id'][:6]}" / "runs" / "failed-archive" / "outputs"
    output.mkdir(parents=True)
    (output / "polish.md").write_text("# Recovered manuscript", encoding="utf-8")

    response = client.get(f"/api/projects/{project['id']}/manuscript")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["id"],
        "content": "# Recovered manuscript",
        "source": "run_candidate",
        "run_id": "failed-archive",
    }


def test_project_locations_resolve_formal_draft_candidate_and_latest_run(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Files", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"files-{project['id'][:6]}"
    db.create_run("older", project["id"], "short-story", status="failed")
    older = root / "runs" / "older" / "outputs"
    older.mkdir(parents=True)
    (older / "best-candidate.md").write_text("best", encoding="utf-8")
    db.create_run("newest", project["id"], "short-story", status="failed")
    newest = root / "runs" / "newest" / "outputs"
    newest.mkdir(parents=True)
    (newest / "draft.md").write_text("draft", encoding="utf-8")

    response = client.get(f"/api/projects/{project['id']}/locations")

    assert response.status_code == 200
    locations = {item["kind"]: item for item in response.json()["locations"]}
    assert locations["project"]["exists"] is True
    assert locations["formal"]["exists"] is False
    assert locations["draft"]["path"].endswith(r"runs\newest\outputs\draft.md")
    assert locations["best_candidate"]["path"].endswith(
        r"runs\older\outputs\best-candidate.md"
    )
    assert locations["latest_run"]["path"].endswith(r"runs\newest")


def test_open_project_location_uses_server_resolved_path(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Open", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    popen = Mock()
    monkeypatch.setattr("novel_flywheel.api.projects.platform.system", lambda: "Windows")
    monkeypatch.setattr("novel_flywheel.api.projects.subprocess.Popen", popen)

    response = client.post(f"/api/projects/{project['id']}/locations/project/open")

    assert response.status_code == 200
    command = popen.call_args.args[0]
    assert command[0] == "explorer.exe"
    assert command[1].endswith(f"open-{project['id'][:6]}")
    assert client.post(f"/api/projects/{project['id']}/locations/unknown/open").status_code == 404
    assert client.post(f"/api/projects/{project['id']}/locations/formal/open").status_code == 409


def test_candidate_diagnostics_and_controlled_publication(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Publish", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"publish-{project['id'][:6]}"
    db.create_run("candidate-run", project["id"], "short-story", status="failed")
    output = root / "runs" / "candidate-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text('他说："回来。"\n她关上门。', encoding="utf-8")

    diagnostics = client.get(f"/api/projects/{project['id']}/candidate")
    published = client.post(f"/api/projects/{project['id']}/candidate/publish")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["available"] is True
    assert diagnostics.json()["run_id"] == "candidate-run"
    assert diagnostics.json()["content"] == '他说："回来。"\n她关上门。'
    assert diagnostics.json()["han_characters"] == 8
    assert diagnostics.json()["characters"] > diagnostics.json()["han_characters"]
    assert published.status_code == 201
    assert (root / "manuscript" / "story.md").read_text(encoding="utf-8") == "他说：“回来。”\n她关上门。"
    assert (root / "chapters" / "chapter-01.md").is_file()


def test_candidate_publication_rejects_active_project_writer(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Publish lease", "mode": "short", "genre": "test",
        "premise": "One writer owns promotion.", "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(
        "A complete candidate manuscript.", encoding="utf-8",
    )
    db.create_run("active-run", project.id, "short-story", status="running")

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_run_active"
    assert not (project.path / "manuscript" / "story.md").exists()


def test_candidate_publication_rolls_back_all_files_on_write_failure(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/api/projects", json={
        "title": "Publish rollback", "mode": "short", "genre": "test",
        "premise": "All formal files move together.", "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(
        "New complete candidate.", encoding="utf-8",
    )
    formal = project.path / "manuscript" / "story.md"
    chapter = project.path / "chapters" / "chapter-01.md"
    receipt = project.path / "manuscript" / "publication.json"
    formal.write_text("old formal", encoding="utf-8")
    chapter.write_text("old chapter", encoding="utf-8")
    receipt.write_text('{"version":1}', encoding="utf-8")
    real_atomic_write = projects_api.atomic_write

    def fail_chapter(path, content, *args, **kwargs):
        if Path(path).resolve() == chapter.resolve():
            raise OSError("injected chapter write failure")
        return real_atomic_write(path, content, *args, **kwargs)

    monkeypatch.setattr(projects_api, "atomic_write", fail_chapter)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 500
    assert formal.read_text(encoding="utf-8") == "old formal"
    assert chapter.read_text(encoding="utf-8") == "old chapter"
    assert receipt.read_text(encoding="utf-8") == '{"version":1}'
    assert not db.has_active_runs(project.id)


def test_candidate_publication_rejects_corpus_change_after_analysis(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    references = ReferenceLibrary(db, tmp_path / "references")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", reference_library=references,
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Corpus CAS", "mode": "short", "genre": "test",
        "premise": "Publication binds its comparison corpus.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    app.state.projects.set_optimized_local_review(project.id, True)
    source = references.import_text(
        title="Reference", text="first reference version", source_type="paste",
        content_type="reference_work", project_id=project.id,
    )
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(
        "A distinct complete candidate.", encoding="utf-8",
    )
    real_analyze = projects_api.analyze_manuscript
    changed = False

    def analyze_then_change(*args, **kwargs):
        nonlocal changed
        report = real_analyze(*args, **kwargs)
        if not changed:
            references.add_version(source["id"], "second reference version")
            changed = True
        return report

    monkeypatch.setattr(projects_api, "analyze_manuscript", analyze_then_change)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_analysis_stale"
    assert not (project.path / "manuscript" / "story.md").exists()


def test_candidate_publication_rechecks_authoritative_source_after_lease(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Candidate CAS", "mode": "short", "genre": "test",
        "premise": "The publication lease must bind the selected source.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    candidate_text = "The same complete manuscript can exist in two runs."
    db.create_run("candidate-old", project.id, "short-story", status="failed")
    old_output = project.path / "runs" / "candidate-old" / "outputs"
    old_output.mkdir(parents=True)
    (old_output / "best-candidate.md").write_text(candidate_text, encoding="utf-8")
    real_create_run_if_idle = db.create_run_if_idle

    def lease_then_supersede(run_id, project_id, workflow, status="queued"):
        acquired = real_create_run_if_idle(run_id, project_id, workflow, status)
        if acquired:
            db.create_run(
                "candidate-new", project.id, "short-story", status="failed",
            )
            new_output = project.path / "runs" / "candidate-new" / "outputs"
            new_output.mkdir(parents=True)
            (new_output / "best-candidate.md").write_text(
                candidate_text, encoding="utf-8",
            )
        return acquired

    monkeypatch.setattr(db, "create_run_if_idle", lease_then_supersede)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_analysis_stale"
    assert not (project.path / "manuscript" / "story.md").exists()
    publication = next(
        run for run in db.list_runs(project.id)
        if run["workflow"] == "candidate-publish"
    )
    assert publication["status"] == "failed"


def test_candidate_publication_rechecks_exact_source_text_hash_after_lease(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Source text CAS", "mode": "short", "genre": "test",
        "premise": "Mechanical normalization must not hide a stale source.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    candidate = outputs / "best-candidate.md"
    original_source = '他说："回来。"'
    equivalent_source = "他说：“回来。”"
    assert projects_api.normalize_chinese_prose(original_source)[0] == (
        projects_api.normalize_chinese_prose(equivalent_source)[0]
    )
    candidate.write_text(original_source, encoding="utf-8")
    real_create_run_if_idle = db.create_run_if_idle

    def lease_then_rewrite_equivalent(run_id, project_id, workflow, status="queued"):
        acquired = real_create_run_if_idle(run_id, project_id, workflow, status)
        if acquired:
            candidate.write_text(equivalent_source, encoding="utf-8")
        return acquired

    monkeypatch.setattr(db, "create_run_if_idle", lease_then_rewrite_equivalent)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_analysis_stale"
    assert not (project.path / "manuscript" / "story.md").exists()


@pytest.mark.parametrize(
    "failure_target",
    ["prepared_journal", "formal", "chapter", "receipt", "commit_journal"],
)
def test_candidate_publication_saga_rolls_back_each_precommit_write_failure(
    tmp_path, monkeypatch, failure_target,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/api/projects", json={
        "title": f"Publish failure {failure_target}", "mode": "short",
        "genre": "test", "premise": "Every saga step is recoverable.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(
        "A complete candidate for fault injection.", encoding="utf-8",
    )
    formal = project.path / "manuscript" / "story.md"
    chapter = project.path / "chapters" / "chapter-01.md"
    receipt = project.path / "manuscript" / "publication.json"
    formal.write_text("old formal", encoding="utf-8")
    chapter.write_text("old chapter", encoding="utf-8")
    receipt.write_text('{"version":1}', encoding="utf-8")
    real_atomic_write = projects_api.atomic_write
    failed = False

    def fail_selected_write(path, content, *args, **kwargs):
        nonlocal failed
        resolved = Path(path).resolve()
        is_journal = resolved.name == "candidate-publication-journal.json"
        status_marker = None
        if is_journal:
            try:
                status_marker = json.loads(content).get("status")
            except (json.JSONDecodeError, TypeError):
                pass
        selected = (
            (failure_target == "formal" and resolved == formal.resolve())
            or (failure_target == "chapter" and resolved == chapter.resolve())
            or (failure_target == "receipt" and resolved == receipt.resolve())
            or (
                failure_target == "prepared_journal"
                and is_journal and status_marker == "prepared"
            )
            or (
                failure_target == "commit_journal"
                and is_journal and status_marker == "committed"
            )
        )
        if selected and not failed:
            failed = True
            raise OSError(f"injected {failure_target} failure")
        return real_atomic_write(path, content, *args, **kwargs)

    monkeypatch.setattr(projects_api, "atomic_write", fail_selected_write)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 500
    assert failed is True
    assert formal.read_text(encoding="utf-8") == "old formal"
    assert chapter.read_text(encoding="utf-8") == "old chapter"
    assert receipt.read_text(encoding="utf-8") == '{"version":1}'
    publication = next(
        run for run in db.list_runs(project.id)
        if run["workflow"] == "candidate-publish"
    )
    assert publication["status"] == "failed"
    assert not db.has_active_runs(project.id)
    assert not (project.path / "snapshots" / publication["id"]).exists()


def test_candidate_publication_retains_committed_snapshot_until_db_terminal(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/api/projects", json={
        "title": "Durable publication terminal", "mode": "short",
        "genre": "test", "premise": "DB completion can be retried.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    candidate_text = (
        "A committed candidate survives DB completion failure.\n\n"
        "Its second paragraph proves exact Windows newline recovery."
    )
    (outputs / "best-candidate.md").write_text(candidate_text, encoding="utf-8")
    real_update_run = db.update_run
    failed_once = False

    def fail_first_completion(run_id, status, current_stage=None, error=None):
        nonlocal failed_once
        if status == "completed" and not failed_once:
            failed_once = True
            raise OSError("injected durable DB completion failure")
        return real_update_run(run_id, status, current_stage, error)

    monkeypatch.setattr(db, "update_run", fail_first_completion)

    response = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert response.status_code == 500
    publication = next(
        run for run in db.list_runs(project.id)
        if run["workflow"] == "candidate-publish"
    )
    run_id = publication["id"]
    snapshot = project.path / "snapshots" / run_id
    journal_path = (
        project.path / "runs" / run_id / "outputs"
        / "candidate-publication-journal.json"
    )
    assert failed_once is True
    assert db.get_run(run_id)["status"] == "running"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "committed"
    assert snapshot.is_dir()
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == candidate_text

    create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    assert db.get_run(run_id)["status"] == "completed"
    assert not snapshot.exists()
    assert (project.path / "manuscript" / "story.md").read_text(
        encoding="utf-8",
    ) == candidate_text
    create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    assert db.get_run(run_id)["status"] == "completed"


@pytest.mark.parametrize(
    ("artifact_name", "damage"),
    [
        ("formal", "missing"), ("formal", "tampered"),
        ("chapter", "missing"), ("chapter", "tampered"),
        ("receipt", "missing"), ("receipt", "tampered"),
    ],
)
def test_startup_rolls_back_corrupt_committed_candidate_publication(
    tmp_path, monkeypatch, artifact_name, damage,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/api/projects", json={
        "title": f"Committed integrity {artifact_name} {damage}",
        "mode": "short", "genre": "test",
        "premise": "Corrupt committed files must not become formal authority.",
        "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "candidate-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(
        "A candidate whose committed write set is fully hash bound.",
        encoding="utf-8",
    )
    real_update_run = db.update_run
    failed_once = False

    def fail_first_completion(run_id, status, current_stage=None, error=None):
        nonlocal failed_once
        if status == "completed" and not failed_once:
            failed_once = True
            raise OSError("injected terminal DB failure")
        return real_update_run(run_id, status, current_stage, error)

    monkeypatch.setattr(db, "update_run", fail_first_completion)
    response = client.post(f"/api/projects/{project.id}/candidate/publish")
    assert response.status_code == 500
    publication = next(
        run for run in db.list_runs(project.id)
        if run["workflow"] == "candidate-publish"
    )
    run_id = publication["id"]
    snapshot = project.path / "snapshots" / run_id
    paths = {
        "formal": project.path / "manuscript" / "story.md",
        "chapter": project.path / "chapters" / "chapter-01.md",
        "receipt": project.path / "manuscript" / "publication.json",
    }
    journal_path = (
        project.path / "runs" / run_id / "outputs"
        / "candidate-publication-journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["version"] == 3
    assert journal["status"] == "committed"
    assert journal["artifact_authority"]
    assert snapshot.is_dir()

    target = paths[artifact_name]
    if damage == "missing":
        target.unlink()
    else:
        target.write_text("tampered publication artifact", encoding="utf-8")

    monkeypatch.setattr(db, "update_run", real_update_run)
    create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )

    assert db.get_run(run_id)["status"] == "failed"
    assert not snapshot.exists()
    assert all(not path.exists() for path in paths.values())
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        "rolled_back"
    )


def test_startup_rolls_back_prepared_candidate_publication(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    first_app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )
    created = first_app.state.projects.create(projects_api.ProjectCreate(
        title="Crash recovery", mode="short", genre="test",
        premise="A prepared saga is recoverable.", target_words=1000,
    ))
    run_id = "candidate-publish-crash"
    db.create_run(run_id, created.id, "candidate-publish", status="running")
    formal = created.path / "manuscript" / "story.md"
    chapter = created.path / "chapters" / "chapter-01.md"
    receipt = created.path / "manuscript" / "publication.json"
    formal.write_text("old formal", encoding="utf-8")
    chapter.write_text("old chapter", encoding="utf-8")
    receipt.write_text('{"version":1}', encoding="utf-8")
    snapshot_root = created.path / "snapshots" / run_id
    ProjectSnapshot.create(
        created.path, snapshot_root, [formal, chapter, receipt],
    )
    journal = created.path / "runs" / run_id / "outputs" / (
        "candidate-publication-journal.json"
    )
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "version": 1, "status": "prepared",
        "publication_run_id": run_id,
        "snapshot_path": snapshot_root.relative_to(created.path).as_posix(),
    }), encoding="utf-8")
    formal.write_text("partial new formal", encoding="utf-8")
    chapter.write_text("partial new chapter", encoding="utf-8")

    create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )

    assert formal.read_text(encoding="utf-8") == "old formal"
    assert chapter.read_text(encoding="utf-8") == "old chapter"
    assert receipt.read_text(encoding="utf-8") == '{"version":1}'
    assert db.get_run(run_id)["status"] == "failed"


def test_candidate_api_cache_recomputes_when_reference_corpus_changes(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    app.state.references = ReferenceLibrary(db, tmp_path / "references")
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Corpus cache", "mode": "short", "genre": "suspense",
        "premise": "A reference changes.", "target_words": 6000,
    }).json()
    project = app.state.projects.get(created["id"])
    app.state.projects.set_optimized_local_review(project.id, True)
    source = app.state.references.import_text(
        title="Reference", text="雨夜里门锁被人更换。", source_type="paste",
        content_type="reference_work", project_id=project.id,
    )
    db.create_run("candidate-run", project.id, "short-story", status="failed")
    output = project.path / "runs" / "candidate-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text(
        "林晚发现门锁变了。", encoding="utf-8",
    )
    calls = []
    real_analyze = projects_api.analyze_manuscript

    def recording_analyze(*args, **kwargs):
        calls.append(kwargs["reference_corpus_sha256"])
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(projects_api, "analyze_manuscript", recording_analyze)
    assert client.get(f"/api/projects/{project.id}/candidate").status_code == 200
    assert client.get(f"/api/projects/{project.id}/candidate").status_code == 200
    app.state.references.add_version(
        source["id"], "清晨时门锁又被人更换。",
    )
    assert client.get(f"/api/projects/{project.id}/candidate").status_code == 200

    assert len(calls) == 2
    assert calls[0] != calls[1]
    cached = json.loads((output / "analysis-candidate.json").read_text(encoding="utf-8"))
    assert cached["reference_corpus_sha256"] == calls[1]


def test_candidate_analysis_does_not_recreate_project_after_trash(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Archive during analysis", "mode": "short", "genre": "suspense",
        "premise": "The analysis finishes after archival.", "target_words": 6000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("analysis-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "analysis-run" / "outputs"
    outputs.mkdir(parents=True)
    text = "candidate manuscript"
    (outputs / "best-candidate.md").write_text(text, encoding="utf-8")

    def analyze_then_trash(*_args, **_kwargs):
        app.state.projects.trash(project.id)
        return {
            "coverage": 1.0,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "originality": {},
        }

    monkeypatch.setattr(
        "novel_flywheel.api.projects.analyze_manuscript", analyze_then_trash,
    )

    response = client.get(f"/api/projects/{project.id}/candidate")

    assert response.status_code == 200
    assert response.json()["analysis_status"] == "complete"
    assert not project.path.exists()
    trash_path = tmp_path / "trash" / project.id
    assert trash_path.is_dir()
    assert not (
        trash_path / "runs" / "analysis-run" / "outputs" / "analysis-candidate.json"
    ).exists()


def test_candidate_api_reconciles_and_returns_higher_historical_best(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Historical best", "mode": "short", "genre": "suspense",
        "premise": "A protected version exists.", "target_words": 9000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("quality-run", project.id, "short-story", status="failed")
    outputs = project.path / "runs" / "quality-run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text("lower candidate", encoding="utf-8")
    (outputs / "historical-best-64.75.md").write_text(
        "protected historical best", encoding="utf-8",
    )
    (outputs / "quality-report.json").write_text(json.dumps({
        "best_score": 58.35,
        "best_attempt": 1,
        "final_attempts": [],
    }), encoding="utf-8")

    manuscript = client.get(f"/api/projects/{project.id}/manuscript").json()
    candidate = client.get(f"/api/projects/{project.id}/candidate").json()

    assert manuscript["content"] == "protected historical best"
    assert candidate["path"].endswith("historical-best-64.75.md")
    assert candidate["characters"] == len("protected historical best")


def test_candidate_publication_rejects_process_text(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Unsafe", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"unsafe-{project['id'][:6]}"
    db.create_run("bad-run", project["id"], "short-story", status="failed")
    output = root / "runs" / "bad-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text("以下是本片段的润色版本：\n正文。", encoding="utf-8")

    response = client.post(f"/api/projects/{project['id']}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_blocked"


def test_project_materials_expose_complete_character_profiles(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Profiles", "mode": "short", "genre": "suspense",
        "premise": "Seven strangers arrive.", "target_words": 20000,
    }).json()
    root = tmp_path / "workspace" / f"profiles-{project['id'][:6]}"
    (root / "characters" / "hero.md").write_text(
        '---\nname: "沈砚"\nrole: protagonist\nage: 34\nstatus: alive\n'
        'tags:\n  - 理性\n  - 疏离\narc: 看清自己\n---\n\n'
        '## Personality & Traits\n\n冷静而傲慢。\n\n## Voice & Speech Patterns\n\n很少解释。',
        encoding="utf-8",
    )

    response = client.get(f"/api/projects/{project['id']}/materials")

    assert response.status_code == 200
    profile = response.json()["characters"][0]
    assert profile["name"] == "沈砚"
    assert profile["tags"] == ["理性", "疏离"]
    assert profile["sections"][0] == {
        "title": "Personality & Traits", "content": "冷静而傲慢。",
    }


def test_project_materials_do_not_count_empty_registry_templates(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Empty materials", "mode": "short", "genre": "test",
        "premise": "Only scaffolds exist.", "target_words": 1000,
    }).json()

    result = client.get(f"/api/projects/{project['id']}/materials").json()
    groups = {item["id"]: item for item in result["groups"]}

    assert groups["plot"]["documents"] == []
    assert groups["timeline"]["documents"] == []
    assert groups["issues"]["documents"] == []
    assert groups["world"]["documents"] == []
    assert result["coverage"]["plot"]["status"] == "needs_attention"
    assert "空模板" in result["coverage"]["timeline"]["message"]


def test_project_material_coverage_uses_exact_names_and_reports_duplicates(tmp_path) -> None:
    app = create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    project_data = client.post("/api/projects", json={
        "title": "Coverage", "mode": "short", "genre": "test",
        "premise": "Names must remain distinct.", "target_words": 1000,
    }).json()
    project = app.state.projects.get(project_data["id"])
    candidate = app.state.outlines.create_candidate(project.id, """# 大纲

## 人物设定
### 女主（花穗）
### 男主（裴砚行）

## 章节大纲
### 第一幕：入府
#### 第1章·错认
""")
    app.state.outlines.apply_candidate(project.id, candidate["id"])
    (project.path / "characters" / "old-name.md").write_text(
        "---\nname: 柳春杏\nrole: protagonist\naliases:\n  - 花穗\n---\n# 柳春杏\n",
        encoding="utf-8",
    )
    for filename in ("first.md", "second.md"):
        (project.path / "worldbuilding" / "locations" / filename).write_text(
            "---\nname: 沈府\ntype: building\n---\n# 沈府\n",
            encoding="utf-8",
        )

    result = client.get(f"/api/projects/{project.id}/materials").json()

    assert [item["name"] for item in result["coverage"]["characters"]["missing"]] == [
        "花穗", "裴砚行",
    ]
    assert result["coverage"]["locations"]["duplicates"] == ["沈府"]


def test_candidate_reports_effective_word_count(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Count", "mode": "short", "genre": "test",
        "premise": "count", "target_words": 1000,
    }).json()
    db.create_run("count-run", project["id"], "short-story", status="failed")
    root = tmp_path / "workspace" / f"count-{project['id'][:6]}"
    output = root / "runs" / "count-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text("# 标题\n你好，世界！OpenAI 2026。", encoding="utf-8")

    result = client.get(f"/api/projects/{project['id']}/candidate").json()

    assert result["han_characters"] == 4
    assert result["effective_words"] == 8


def test_zhihu_candidate_exposes_one_quality_summary_and_blocks_stale_review(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "One authority", "mode": "short", "genre": "test",
        "premise": "The current text must own its review.", "target_words": 1000,
    }).json()
    project = app.state.projects.apply_platform_profile(
        created["id"], "zhihu-salt-short",
    )
    db.create_run("quality-run", project.id, "short-story", status="failed")
    output = project.path / "runs" / "quality-run" / "outputs"
    output.mkdir(parents=True)
    text = "正文" * 450
    (output / "best-candidate.md").write_text(text, encoding="utf-8")
    (output / "quality-report.json").write_text(json.dumps({
        "status": "passed",
        "terminal_reviewed_hash": hashlib.sha256("旧稿".encode("utf-8")).hexdigest(),
        "scoring_profile_id": "zhihu-short-v2",
        "final_attempts": [{
            "attempt": 1,
            "review": {
                "score": 82,
                "scoring_profile_id": "zhihu-short-v2",
                "dimensions": {"commercial": 82, "story": 82, "prose": 82},
                "issues": [],
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = client.get(f"/api/projects/{project.id}/candidate").json()
    published = client.post(f"/api/projects/{project.id}/candidate/publish")

    assert result["han_characters"] == 900
    assert result["quality_summary"]["word_count"]["current"] == 900
    authority = result["quality_summary"]["publication_authority"]
    assert authority["can_set_formal"] is False
    assert any("内容不一致" in reason for reason in authority["blocking_reasons"])
    assert published.status_code == 409
    assert published.json()["detail"]["code"] == "candidate_quality_blocked"
    assert published.json()["detail"]["reasons"] == authority["blocking_reasons"]


def test_quality_reference_group_api_requires_confirmation_and_keeps_history(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Reference controls", "mode": "short", "genre": "test",
        "premise": "References require consent.", "target_words": 8000,
    }).json()
    project = app.state.projects.apply_platform_profile(
        created["id"], "zhihu-salt-short",
    )
    source = app.state.references.import_text(
        title="已确认佳作", text="样本文本", source_type="paste",
        platform="zhihu", content_type="popular_sample",
    )

    recommendations = client.get(
        f"/api/projects/{project.id}/quality-references/recommendations",
    ).json()
    before = client.get(f"/api/projects/{project.id}/quality-references").json()
    item_id = next(
        item["id"] for item in recommendations["recommendations"]
        if item["source_id"] == source["id"]
    )
    confirmed = client.post(
        f"/api/projects/{project.id}/quality-references/confirm",
        json={"accepted_ids": [item_id], "rejected_ids": []},
    )
    removed = client.delete(
        f"/api/projects/{project.id}/quality-references/{item_id}",
    )
    history = client.get(
        f"/api/projects/{project.id}/quality-references/history",
    ).json()

    assert before["items"] == []
    assert confirmed.status_code == 200
    assert confirmed.json()["items"][0]["title"] == "已确认佳作"
    assert removed.json()["items"] == []
    assert [item["action"] for item in history["versions"]] == [
        "removed", "confirmed",
    ]


def test_passage_protection_api_uses_current_candidate_and_plain_chinese_states(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    created = client.post("/api/projects", json={
        "title": "Protect prose", "mode": "short", "genre": "test",
        "premise": "Keep a favorite paragraph.", "target_words": 1000,
    }).json()
    project = app.state.projects.get(created["id"])
    db.create_run("candidate", project.id, "short-story", status="failed")
    output = project.path / "runs" / "candidate" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text(
        "我最喜欢这一段。\n\n下一段可以修改。", encoding="utf-8",
    )

    created_lock = client.post(
        f"/api/projects/{project.id}/passage-protections",
        json={"excerpt": "我最喜欢这一段。", "mode": "exact", "label": "喜欢的开头"},
    )
    lock_id = created_lock.json()["id"]
    listed = client.get(f"/api/projects/{project.id}/passage-protections")
    allowed = client.post(
        f"/api/projects/{project.id}/passage-protections/{lock_id}/allow-next-change",
    )
    removed = client.delete(
        f"/api/projects/{project.id}/passage-protections/{lock_id}",
    )

    assert created_lock.status_code == 201
    assert listed.json()["items"][0]["mode_label"] == "一个字也不改"
    assert allowed.json()["status_label"] == "下次修改可变动一次"
    assert removed.json()["status_label"] == "已取消保护"


def test_material_documents_are_editable_and_sync_story_state(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Materials", "mode": "short", "genre": "test",
        "premise": "materials", "target_words": 1000,
    }).json()
    root = tmp_path / "workspace" / f"materials-{project['id'][:6]}"
    world = root / "worldbuilding" / "rules.md"
    world.parent.mkdir(parents=True, exist_ok=True)
    world.write_text("# 世界规则\n\n- 门只能打开一次。\n", encoding="utf-8")
    before = client.get(f"/api/projects/{project['id']}/story-state").json()
    materials = client.get(f"/api/projects/{project['id']}/materials").json()
    groups = {item["id"]: item for item in materials["groups"]}
    document = next(item for item in groups["world"]["documents"] if item["path"] == "worldbuilding/rules.md")

    response = client.put(
        f"/api/projects/{project['id']}/materials/worldbuilding/rules.md",
        json={"content": "# 世界规则\n\n- 门只能打开两次。\n", "expected_hash": document["hash"]},
    )

    assert response.status_code == 200
    assert world.read_text(encoding="utf-8").endswith("门只能打开两次。\n")
    assert response.json()["story_state_revision"] == before["revision"] + 1


def test_character_material_edit_creates_linked_material_impact(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Links", "mode": "short", "genre": "test",
        "premise": "links", "target_words": 1000,
    }).json()
    root = tmp_path / "workspace" / f"links-{project['id'][:6]}"
    profile = root / "characters" / "lin.md"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("---\nname: Lin\nrole: protagonist\n---\n\nCarries a notebook.\n", encoding="utf-8")
    materials = client.get(f"/api/projects/{project['id']}/materials").json()
    document = next(item for item in materials["groups"][0]["documents"]
                    if item["path"] == "characters/lin.md")

    response = client.put(
        f"/api/projects/{project['id']}/materials/characters/lin.md",
        json={
            "content": "---\nname: Lin\nrole: protagonist\n---\n\nTrusts her memory.\n",
            "expected_hash": document["hash"], "retire_removed_settings": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["material_impact"]["status"] == "pending"
    refreshed = client.get(f"/api/projects/{project['id']}/materials").json()
    assert refreshed["material_impacts"][0]["id"] == response.json()["material_impact"]["id"]


def test_material_edit_precommit_failure_restores_every_business_authority(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    project_data = client.post("/api/projects", json={
        "title": "Material rollback", "mode": "short", "genre": "test",
        "premise": "The edit is one transaction.", "target_words": 13_000,
    }).json()
    project = app.state.projects.get(project_data["id"])
    profile = project.path / "characters" / "lin.md"
    profile.write_text(
        "---\nname: Lin\nrole: protagonist\n---\n\nCarries a notebook.\n",
        encoding="utf-8",
    )
    app.state.learning.save_artifact(
        project.id, "voice_profiles", {"Lin": {"rule": "writes notes"}},
    )
    document = next(
        item
        for item in client.get(
            f"/api/projects/{project.id}/materials",
        ).json()["groups"][0]["documents"]
        if item["path"] == "characters/lin.md"
    )
    before_bytes = profile.read_bytes()
    before_state = StoryStateStore(db).get(project.id)

    monkeypatch.setattr(
        projects_api, "stage_project_mutation_targets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected staging failure"),
        ),
    )
    with pytest.raises(OSError, match="injected staging failure"):
        client.put(
            f"/api/projects/{project.id}/materials/characters/lin.md",
            json={
                "content": (
                    "---\nname: Lin\nrole: protagonist\n---\n\n"
                    "Trusts her memory.\n"
                ),
                "expected_hash": document["hash"],
                "retire_removed_settings": True,
            },
        )

    after_state = StoryStateStore(db).get(project.id)
    assert profile.read_bytes() == before_bytes
    assert after_state.revision == before_state.revision
    assert after_state.data == before_state.data
    assert app.state.learning.get_artifact(
        project.id, "voice_profiles",
    )["status"] == "active"
    assert app.state.material_impacts.list(project.path) == []
    run = next(
        item for item in db.list_runs(project.id)
        if item["workflow"] == "material-edit"
    )
    assert run["status"] == "failed"
    assert not (project.path / "snapshots" / run["id"]).exists()


def test_material_edit_restart_finishes_same_files_state_and_side_effects(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app)
    project_data = client.post("/api/projects", json={
        "title": "Material resume", "mode": "short", "genre": "test",
        "premise": "The accepted edit survives interruption.",
        "target_words": 13_000,
    }).json()
    project = app.state.projects.get(project_data["id"])
    profile = project.path / "characters" / "lin.md"
    profile.write_text(
        "---\nname: Lin\nrole: protagonist\n---\n\nCarries a notebook.\n",
        encoding="utf-8",
    )
    app.state.learning.save_artifact(
        project.id, "voice_profiles", {"Lin": {"rule": "writes notes"}},
    )
    document = next(
        item
        for item in client.get(
            f"/api/projects/{project.id}/materials",
        ).json()["groups"][0]["documents"]
        if item["path"] == "characters/lin.md"
    )
    before_state = StoryStateStore(db).get(project.id)

    monkeypatch.setattr(
        projects_api, "complete_project_mutation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected process interruption"),
        ),
    )
    with pytest.raises(OSError, match="injected process interruption"):
        client.put(
            f"/api/projects/{project.id}/materials/characters/lin.md",
            json={
                "content": (
                    "---\nname: Lin\nrole: protagonist\n---\n\n"
                    "Trusts her memory.\n"
                ),
                "expected_hash": document["hash"],
                "retire_removed_settings": True,
            },
        )

    run = next(
        item for item in db.list_runs(project.id)
        if item["workflow"] == "material-edit"
    )
    assert run["status"] == "running"
    assert "Trusts her memory" in profile.read_text(encoding="utf-8")
    assert StoryStateStore(db).get(project.id).revision == before_state.revision
    assert app.state.learning.get_artifact(
        project.id, "voice_profiles",
    )["status"] == "active"
    assert len(app.state.material_impacts.list(project.path)) == 1

    completed = complete_project_mutation(app.state.projects, run["id"])
    completed_again = complete_project_mutation(
        app.state.projects, run["id"],
    )

    assert completed.status == completed_again.status == "committed"
    # Character profile prose is not projected into continuity/state.md, so
    # the pre-refactor business rule intentionally leaves StoryState unchanged.
    assert StoryStateStore(db).get(project.id).revision == before_state.revision
    assert app.state.learning.get_artifact(
        project.id, "voice_profiles",
    )["status"] == "stale"
    assert len(app.state.material_impacts.list(project.path)) == 1
    assert db.get_run(run["id"])["status"] == "completed"
    assert not (project.path / "snapshots" / run["id"]).exists()


def test_confirmed_material_impact_updates_only_selected_project_material(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Apply links", "mode": "short", "genre": "test",
        "premise": "links", "target_words": 1000,
    }).json()
    root = tmp_path / "workspace" / f"apply-links-{project['id'][:6]}"
    plot = root / "plot" / "arcs" / "main.md"
    plot.parent.mkdir(parents=True, exist_ok=True)
    plot.write_text("She checks her notebook.", encoding="utf-8")
    service = client.app.state.material_impacts
    impact = service.record(
        project["id"], root, "characters/lin.md", "Carries a notebook.",
        "Trusts her memory.", retire_removed_settings=True,
    )
    stored = service.get(root, impact["id"])
    stored.update({
        "status": "ready",
        "proposals": [{
            "id": "patch-1", "path": "plot/arcs/main.md", "reason": "linked",
            "old_text": "She checks her notebook.",
            "new_text": "She recognizes the handwriting.",
            "target_hash": service.content_hash("She checks her notebook."),
        }],
    })
    service.save(root, stored)

    response = client.post(
        f"/api/projects/{project['id']}/material-impacts/{impact['id']}/apply",
        json={"proposal_ids": ["patch-1"]},
    )

    assert response.status_code == 200
    assert plot.read_text(encoding="utf-8") == "She recognizes the handwriting."
    assert client.get(f"/api/projects/{project['id']}/materials").json()["material_impacts"] == []


def _ready_character_material_impact(app, project: dict) -> tuple[Path, dict, str, str]:
    root = app.state.projects.get(project["id"]).path
    profile = root / "characters" / "lin.md"
    profile.parent.mkdir(parents=True, exist_ok=True)
    before = "---\nname: Lin\nrole: protagonist\nstatus: hidden\n---\n\nKeeps the truth private.\n"
    after = "---\nname: Lin\nrole: protagonist\nstatus: known\n---\n\nShares the truth.\n"
    profile.write_text(before, encoding="utf-8")
    service = app.state.material_impacts
    impact = service.record(
        project["id"], root, "characters/source.md", "Old setting.",
        "New setting.", retire_removed_settings=True,
    )
    stored = service.get(root, impact["id"])
    stored.update({
        "status": "ready",
        "proposals": [{
            "id": "character-patch", "path": "characters/lin.md",
            "reason": "Keep the character authority synchronized.",
            "old_text": before, "new_text": after,
            "target_hash": service.content_hash(before),
        }],
    })
    service.save(root, stored)
    return profile, impact, before, after


def test_material_impact_resolve_failure_rolls_back_files_and_story_state(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
    )
    client = TestClient(app, raise_server_exceptions=False)
    project = client.post("/api/projects", json={
        "title": "Impact rollback", "mode": "short", "genre": "test",
        "premise": "File and StoryState authority move together.",
        "target_words": 1000,
    }).json()
    profile, impact, before, _after = _ready_character_material_impact(
        app, project,
    )
    root = app.state.projects.get(project["id"]).path
    state_store = StoryStateStore(db)
    original_state = state_store.ensure(project["id"], root)

    def fail_resolve(*args, **kwargs):
        raise OSError("injected material impact status failure")

    monkeypatch.setattr(app.state.material_impacts, "resolve", fail_resolve)
    response = client.post(
        f"/api/projects/{project['id']}/material-impacts/{impact['id']}/apply",
        json={"proposal_ids": ["character-patch"]},
    )

    assert response.status_code == 500
    assert profile.read_text(encoding="utf-8") == before
    current_state = state_store.get(project["id"])
    assert current_state is not None
    assert current_state.revision == original_state.revision
    assert current_state.data == original_state.data
    assert app.state.material_impacts.get(root, impact["id"])["status"] == "ready"
    run = next(
        item for item in db.list_runs(project["id"])
        if item["workflow"] == "material-impact-apply"
    )
    assert run["status"] == "failed"
    assert not (root / "snapshots" / run["id"]).exists()


def test_material_impact_restart_completes_durable_artifacts_and_story_state(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    workspace = tmp_path / "workspace"
    app = create_app(db, MemorySecretStore(), workspace_root=workspace)
    client = TestClient(app, raise_server_exceptions=False)
    project = client.post("/api/projects", json={
        "title": "Impact resume", "mode": "short", "genre": "test",
        "premise": "A durable mutation resumes after interruption.",
        "target_words": 1000,
    }).json()
    profile, impact, _before, after = _ready_character_material_impact(
        app, project,
    )
    root = app.state.projects.get(project["id"]).path
    state_store = StoryStateStore(db)
    original_state = state_store.ensure(project["id"], root)

    def interrupt_after_artifact_commit(*args, **kwargs):
        raise OSError("injected interruption after artifact commit")

    monkeypatch.setattr(
        projects_api, "complete_project_mutation",
        interrupt_after_artifact_commit,
    )
    response = client.post(
        f"/api/projects/{project['id']}/material-impacts/{impact['id']}/apply",
        json={"proposal_ids": ["character-patch"]},
    )

    assert response.status_code == 500
    run = next(
        item for item in db.list_runs(project["id"])
        if item["workflow"] == "material-impact-apply"
    )
    assert run["status"] == "running"
    assert profile.read_text(encoding="utf-8") == after
    assert state_store.get(project["id"]).revision == original_state.revision
    assert (root / "snapshots" / run["id"]).is_dir()

    create_app(db, MemorySecretStore(), workspace_root=workspace)

    recovered_state = state_store.get(project["id"])
    assert recovered_state is not None
    assert recovered_state.revision == original_state.revision + 1
    assert recovered_state.data["character_states"]["Lin"]["status"] == "known"
    assert db.get_run(run["id"])["status"] == "completed"
    assert not (root / "snapshots" / run["id"]).exists()
    assert app.state.material_impacts.get(root, impact["id"])["status"] == "applied"


def test_material_impact_committed_authority_survives_terminal_db_failure(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    workspace = tmp_path / "workspace"
    app = create_app(db, MemorySecretStore(), workspace_root=workspace)
    client = TestClient(app, raise_server_exceptions=False)
    project = client.post("/api/projects", json={
        "title": "Impact terminal retry", "mode": "short", "genre": "test",
        "premise": "Committed authority is never rolled back by audit failure.",
        "target_words": 1000,
    }).json()
    profile, impact, _before, after = _ready_character_material_impact(
        app, project,
    )
    root = app.state.projects.get(project["id"]).path
    state_store = StoryStateStore(db)
    original_state = state_store.ensure(project["id"], root)
    real_update_run = db.update_run
    failed_once = False

    def fail_first_terminal(run_id, status, current_stage=None, error=None):
        nonlocal failed_once
        if (
            status == "completed" and str(run_id).startswith("mia-")
            and not failed_once
        ):
            failed_once = True
            raise OSError("injected material terminal persistence failure")
        return real_update_run(run_id, status, current_stage, error)

    monkeypatch.setattr(db, "update_run", fail_first_terminal)
    response = client.post(
        f"/api/projects/{project['id']}/material-impacts/{impact['id']}/apply",
        json={"proposal_ids": ["character-patch"]},
    )

    assert response.status_code == 500
    run = next(
        item for item in db.list_runs(project["id"])
        if item["workflow"] == "material-impact-apply"
    )
    committed_state = state_store.get(project["id"])
    assert failed_once is True
    assert committed_state is not None
    assert committed_state.revision == original_state.revision + 1
    assert profile.read_text(encoding="utf-8") == after
    assert db.get_run(run["id"])["status"] == "running"
    assert (root / "snapshots" / run["id"]).is_dir()

    monkeypatch.setattr(db, "update_run", real_update_run)
    create_app(db, MemorySecretStore(), workspace_root=workspace)

    assert db.get_run(run["id"])["status"] == "completed"
    assert state_store.get(project["id"]).revision == committed_state.revision
    assert profile.read_text(encoding="utf-8") == after
    assert not (root / "snapshots" / run["id"]).exists()


def test_material_documents_expose_localized_structured_display(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Display", "mode": "short", "genre": "test",
        "premise": "display", "target_words": 1000,
    }).json()
    root = tmp_path / "workspace" / f"display-{project['id'][:6]}"
    location = root / "worldbuilding" / "locations" / "tower.md"
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(
        "---\nname: 黑塔\ntype: building\nstatus: thriving\ncontrolled-by: unknown\n---\n\n"
        "## Description\n\n终年无灯。\n\n## Notable Features\n\n"
        "| Name | Type |\n|---|---|\n| 顶层 | 禁区 |\n",
        encoding="utf-8",
    )

    materials = client.get(f"/api/projects/{project['id']}/materials").json()
    locations = next(group for group in materials["groups"] if group["id"] == "locations")
    document = next(item for item in locations["documents"] if item["path"].endswith("tower.md"))

    assert document["display"]["title"] == "黑塔"
    assert document["display"]["metadata"] == [
        {"label": "类型", "value": "建筑"}, {"label": "控制者", "value": "未确认"},
        {"label": "状态", "value": "正常"},
    ]
    assert document["display"]["sections"][0]["title"] == "描述"
    assert document["display"]["sections"][0]["content"] == "终年无灯。"
    assert document["display"]["sections"][1]["columns"] == ["名称", "类型"]
    assert "type: building" in document["content"]


def test_material_edit_is_blocked_during_active_run(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(db, MemorySecretStore(), workspace_root=tmp_path / "workspace"))
    project = client.post("/api/projects", json={
        "title": "Busy", "mode": "short", "genre": "test",
        "premise": "busy", "target_words": 1000,
    }).json()
    materials = client.get(f"/api/projects/{project['id']}/materials").json()
    document = materials["groups"][-1]["documents"][0]
    db.create_run("busy-run", project["id"], "short-story", status="running")

    response = client.put(
        f"/api/projects/{project['id']}/materials/{document['path']}",
        json={"content": document["content"], "expected_hash": document["hash"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_run_active"


def test_project_trash_restore_and_permanent_delete_api(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Book", "mode": "long", "genre": "fantasy",
        "premise": "An oath.", "target_words": 100000,
    }).json()

    assert client.delete(f"/api/projects/{project['id']}").status_code == 200
    assert client.get("/api/projects").json() == []
    assert client.get("/api/projects/trash").json()[0]["id"] == project["id"]
    assert client.post(f"/api/projects/{project['id']}/restore").status_code == 200
    assert client.get("/api/projects").json()[0]["id"] == project["id"]

    client.delete(f"/api/projects/{project['id']}")
    response = client.delete(f"/api/projects/{project['id']}/permanent")
    assert response.status_code == 204
    assert client.get("/api/projects/trash").json() == []


def test_project_restore_conflict_api_explains_that_both_copies_were_kept(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Conflict", "mode": "short", "genre": "suspense",
        "premise": "Another project occupies the path.", "target_words": 8_000,
    }).json()
    original = Path(project["path"])
    client.delete(f"/api/projects/{project['id']}")
    trash_path = Path(client.get("/api/projects/trash").json()[0]["path"])
    original.mkdir()
    (original / "project.json").write_text(
        json.dumps({"id": "another-project"}), encoding="utf-8",
    )

    response = client.post(f"/api/projects/{project['id']}/restore")

    assert response.status_code == 409
    assert "原位置属于其他作品" in response.json()["detail"]["message"]
    assert original.is_dir()
    assert trash_path.is_dir()


def test_project_style_sample_status_analyze_and_delete_api(tmp_path) -> None:
    service = FakeStyleSamples()
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=service,
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封失踪的信。", "target_words": 6000,
    }).json()
    endpoint = f"/api/projects/{project['id']}/style-sample"

    assert client.get(endpoint).json()["configured"] is False
    analyzed = client.post(endpoint, json={"text": "动作与对白。" * 40, "source_name": "范文.txt"})
    assert analyzed.status_code == 201
    assert analyzed.json()["profile"]["summary"] == "克制的动作叙事"
    assert client.delete(endpoint).json()["configured"] is False


def test_project_style_sample_scope_defaults_to_polish_and_can_be_enabled_for_draft(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封信。", "target_words": 6000,
    }).json()
    endpoint = f"/api/projects/{project['id']}/style-sample"

    assert client.get(endpoint).json()["application_scope"] == "polish"
    response = client.put(f"{endpoint}/scope", json={"application_scope": "draft_and_polish"})

    assert response.status_code == 200
    assert response.json()["application_scope"] == "draft_and_polish"
    assert client.get(f"/api/projects/{project['id']}").json()["style_sample_scope"] == "draft_and_polish"


def test_project_style_sample_rejects_typed_invalid_input_before_service(tmp_path) -> None:
    class UncalledStyleSamples(FakeStyleSamples):
        async def analyze(self, project, text, source_name):
            raise AssertionError("typed API validation must run before the service")

    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=UncalledStyleSamples(),
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封失踪的信。", "target_words": 6000,
    }).json()

    response = client.post(f"/api/projects/{project['id']}/style-sample", json={"text": "短"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_style_sample",
        "message": "Style sample must contain 200 to 60000 non-blank characters.",
    }


def test_project_style_sample_redacts_parser_value_error(tmp_path) -> None:
    sentinel = "PARSER_RAW C:\\private\\parser.log API_KEY_SENTINEL"

    class InvalidStyleSamples(FakeStyleSamples):
        async def analyze(self, project, text, source_name):
            raise ValueError(sentinel)

    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=InvalidStyleSamples(),
    ))
    project = client.post("/api/projects", json={
        "title": "Safe parser error", "mode": "short", "genre": "悬疑",
        "premise": "解析失败也不得暴露内部信息。", "target_words": 6000,
    }).json()

    response = client.post(
        f"/api/projects/{project['id']}/style-sample",
        json={"text": "有效长度的范文内容。" * 30},
    )

    body = json.dumps(response.json(), ensure_ascii=False)
    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "style_analysis_failed",
        "message": "Style analysis provider is temporarily unavailable.",
    }
    assert "PARSER_RAW" not in body
    assert "parser.log" not in body
    assert "API_KEY_SENTINEL" not in body


def test_project_style_sample_redacts_provider_failure(tmp_path) -> None:
    sentinel = "PROVIDER_RAW C:\\private\\route.log API_KEY_SENTINEL"

    class FailingStyleSamples(FakeStyleSamples):
        async def analyze(self, project, text, source_name):
            raise RuntimeError(sentinel)

    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=FailingStyleSamples(),
    ))
    project = client.post("/api/projects", json={
        "title": "Safe provider error", "mode": "short", "genre": "suspense",
        "premise": "A provider fails.", "target_words": 6000,
    }).json()

    response = client.post(
        f"/api/projects/{project['id']}/style-sample",
        json={"text": "long-enough-style-sample" * 20},
    )

    body = json.dumps(response.json(), ensure_ascii=False)
    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "style_analysis_failed",
        "message": "Style analysis provider is temporarily unavailable.",
    }
    assert "PROVIDER_RAW" not in body
    assert "route.log" not in body
    assert "API_KEY_SENTINEL" not in body


def test_story_state_api_reads_edits_section_and_keeps_history(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "State", "mode": "long", "genre": "玄幻",
        "premise": "旧誓言。", "target_words": 100000,
    }).json()
    endpoint = f"/api/projects/{project['id']}/story-state"
    initial = client.get(endpoint).json()

    updated = client.put(endpoint, json={
        "expected_revision": initial["revision"],
        "section": "character_states",
        "value": {"林昼": {"location": "公司"}},
    })

    assert updated.status_code == 200
    assert updated.json()["revision"] == initial["revision"] + 1
    assert updated.json()["data"]["character_states"]["林昼"]["location"] == "公司"
    history = client.get(f"{endpoint}/history").json()
    assert [item["revision"] for item in history] == [1, 2]


def test_story_state_api_rejects_stale_manual_edit(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "State", "mode": "short", "genre": "悬疑",
        "premise": "旧信。", "target_words": 6000,
    }).json()
    endpoint = f"/api/projects/{project['id']}/story-state"
    revision = client.get(endpoint).json()["revision"]
    payload = {"expected_revision": revision, "section": "world_rules", "value": ["门只能开一次"]}

    assert client.put(endpoint, json=payload).status_code == 200
    stale = client.put(endpoint, json=payload)

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "story_state_stale"
