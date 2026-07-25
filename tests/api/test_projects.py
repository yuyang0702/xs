from fastapi.testclient import TestClient
from unittest.mock import Mock

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


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
    assert diagnostics.json()["han_characters"] == 8
    assert diagnostics.json()["characters"] > diagnostics.json()["han_characters"]
    assert published.status_code == 201
    assert (root / "manuscript" / "story.md").read_text(encoding="utf-8") == "他说：“回来。”\n她关上门。"
    assert (root / "chapters" / "chapter-01.md").is_file()


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

    assert result["han_characters"] == 6
    assert result["effective_words"] == 8


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
        "---\nname: 黑塔\ntype: building\nstatus: thriving\n---\n\n"
        "## Description\n\n终年无灯。\n\n## Notable Features\n\n"
        "| Name | Type |\n|---|---|\n| 顶层 | 禁区 |\n",
        encoding="utf-8",
    )

    materials = client.get(f"/api/projects/{project['id']}/materials").json()
    locations = next(group for group in materials["groups"] if group["id"] == "locations")
    document = next(item for item in locations["documents"] if item["path"].endswith("tower.md"))

    assert document["display"]["title"] == "黑塔"
    assert document["display"]["metadata"] == [
        {"label": "类型", "value": "建筑"}, {"label": "状态", "value": "正常"},
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


def test_project_style_sample_rejects_invalid_analysis(tmp_path) -> None:
    class InvalidStyleSamples(FakeStyleSamples):
        async def analyze(self, project, text, source_name):
            raise ValueError("范文至少需要 200 个字符")

    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=InvalidStyleSamples(),
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封失踪的信。", "target_words": 6000,
    }).json()

    response = client.post(f"/api/projects/{project['id']}/style-sample", json={"text": "短"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_style_sample"


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
