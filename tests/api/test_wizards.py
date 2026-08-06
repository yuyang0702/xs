import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import MemorySecretStore


class FakeInterviews:
    def __init__(self):
        self.messages = []

    def history(self, wizard_id):
        return self.messages

    async def turn(self, wizard_id, message=None):
        result = {"id": "assistant", "wizard_id": wizard_id, "role": "assistant",
                  "content": "主角最害怕失去什么？", "suggestions": [],
                  "suggestion_status": "none"}
        self.messages.append(result)
        return result

    def apply(self, wizard_id, message_id, field_ids):
        return {"wizard": {"id": wizard_id}, "applied_fields": field_ids}


class FailingInterviews(FakeInterviews):
    async def turn(self, wizard_id, message=None):
        raise ConnectionError("planning provider disconnected")


class MissingWizardInterviews(FakeInterviews):
    async def turn(self, wizard_id, message=None):
        raise LookupError("Wizard not found")


def wizard_client(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    return TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))


def add_confirmed_mechanisms(
    client: TestClient, source_id: str, count: int,
) -> list[dict]:
    return [
        client.app.state.learning._save_node(
            "mechanism",
            {
                "name": f"写法 {index + 1}",
                "transfer_guidance": f"使用方法 {index + 1}",
                "confidence": 0.9,
            },
            source_id=source_id,
            status="confirmed",
        )
        for index in range(count)
    ]


def confirmed_source(
    client: TestClient, title: str, content_type: str, count: int = 1,
) -> tuple[dict, list[dict]]:
    source = client.post("/api/references", json={
        "title": title,
        "source_type": "paste",
        "text": f"{title}的正文内容。",
        "content_type": content_type,
    }).json()
    return source, add_confirmed_mechanisms(client, source["id"], count)


def create_completed_wizard(client: TestClient) -> tuple[dict, dict]:
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "已创建作品", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    project = client.post(f"/api/wizards/{wizard['id']}/confirm").json()
    return wizard, project


def test_delete_unfinished_wizard_api_does_not_delete_projects(tmp_path) -> None:
    client = wizard_client(tmp_path)
    project = client.post("/api/projects", json={
        "title": "保留的作品", "mode": "short", "genre": "悬疑",
        "premise": "一扇门打开。", "target_words": 6000,
    }).json()
    keep = client.post("/api/wizards", json={"mode": "long"}).json()
    removed = client.post("/api/wizards", json={"mode": "short"}).json()
    projects_before = client.get("/api/projects").json()

    response = client.delete(f"/api/wizards/{removed['id']}")

    assert response.status_code == 200
    assert response.json() == {"id": removed["id"], "deleted": True}
    assert [item["id"] for item in client.get("/api/wizards").json()] == [keep["id"]]
    assert client.get("/api/projects").json() == projects_before
    assert client.get(f"/api/projects/{project['id']}").status_code == 200


def test_delete_missing_wizard_api_returns_chinese_not_found(tmp_path) -> None:
    response = wizard_client(tmp_path).delete("/api/wizards/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "wizard_not_found",
        "message": "草稿不存在或已经删除。",
    }


def test_delete_completed_wizard_api_returns_chinese_conflict(tmp_path) -> None:
    client = wizard_client(tmp_path)
    unrelated = client.post("/api/wizards", json={"mode": "long"}).json()
    wizard, project = create_completed_wizard(client)
    project_count = len(client.get("/api/projects").json())
    wizard_count = len(client.get("/api/wizards").json())

    response = client.delete(f"/api/wizards/{wizard['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "wizard_has_project",
        "message": "这份开书资料已经创建作品，不能从草稿列表删除。",
    }
    assert client.get(f"/api/projects/{project['id']}").status_code == 200
    assert len(client.get("/api/projects").json()) == project_count
    assert len(client.get("/api/wizards").json()) == wizard_count
    assert client.get(f"/api/wizards/{unrelated['id']}").status_code == 200


def test_wizard_create_autosave_resume_and_confirm(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "long"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "Web Book", "policy": "locked"},
        "genre": {"value": "fantasy", "policy": "locked"},
        "premise": {"value": "An oath.", "policy": "locked"},
        "target_words": {"value": 500000, "policy": "suggestible"},
    }})
    assert response.status_code == 200
    assert client.get(f"/api/wizards/{wizard['id']}").json()["answers"]["title"]["value"] == "Web Book"
    project = client.post(f"/api/wizards/{wizard['id']}/confirm").json()
    assert project["title"] == "Web Book"
    assert project["wizard_id"] == wizard["id"]


def test_wizard_rejects_unknown_answer_field(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "filesystem_path": {"value": "../x", "policy": "locked"},
    }})
    assert response.status_code == 400


def test_wizard_confirm_rejects_invalid_market_baseline_key(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "短篇", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一扇门。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
        "market_baseline_enabled": {"value": "enabled", "policy": "suggestible"},
        "market_baseline_key": {"value": "not-json", "policy": "suggestible"},
    }})
    assert response.status_code == 200

    confirmed = client.post(f"/api/wizards/{wizard['id']}/confirm")

    assert confirmed.status_code == 400
    assert confirmed.json()["detail"]["code"] == "invalid_market_baseline"


def test_initialize_skills_returns_tracked_background_run(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "Short", "policy": "locked"},
        "genre": {"value": "suspense", "policy": "suggestible"},
        "premise": {"value": "A door opens.", "policy": "locked"},
        "target_words": {"value": 5000, "policy": "suggestible"},
    }})
    project = client.post(f"/api/wizards/{wizard['id']}/confirm").json()

    blocked = client.post(f"/api/projects/{project['id']}/initialize-skills")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "outline_confirmation_required"

    candidate = client.post(
        f"/api/projects/{project['id']}/learning/outline-candidates",
        json={"title": "第一版", "outline": "# 正式大纲\n\n## 开头\n门被推开。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project['id']}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    applied = client.post(
        f"/api/projects/{project['id']}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    assert applied.status_code == 200

    response = client.post(f"/api/projects/{project['id']}/initialize-skills")

    assert response.status_code == 202
    assert response.json()["workflow"] == "initialize-skills"


def test_initialization_freezes_learning_versions_and_skips_completed_stage(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    _wizard, project_data = create_completed_wizard(client)
    project_id = project_data["id"]
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "正式版", "outline": "# 正式大纲\n\n## 开头\n门被推开。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    learning = client.app.state.learning
    learning.build_prose_baseline(project_id, {
        "dialogue": ["让回应改变关系。"],
        "psychology": ["先写动作，再写判断。"],
    })
    learning.save_artifact(project_id, "creative_blueprint", {
        "mechanisms": [{
            "name": "递进冲突", "transfer_guidance": "每轮冲突都改变状态。",
            "applicable_modes": ["short"],
        }],
    })
    project = client.app.state.projects.get(project_id)
    metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = [
        "story-init", "character-management", "worldbuilding", "plot-structure",
    ]
    (project.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    skills = {
        name: SimpleNamespace(name=name, content_hash=f"hash-{name}")
        for name in metadata["initialization_skills"]
    }
    db.create_skill_execution(
        "completed-story", project_id, "story-init", "hash-story-init", "completed",
    )

    class Runtime:
        calls = []

        async def run(self, requested_project_id, skill_name, answers, bootstrap=False):
            self.calls.append((skill_name, answers["confirmed_learning_context"]))
            assert answers["confirmed_outline"]["content"].startswith("# 正式大纲")
            if skill_name == "character-management":
                learning.build_prose_baseline(project_id, {"dialogue": ["任务启动后新增的规则。"]})
            return {"status": "completed", "proposals": []}

    class CapturingTasks:
        operation = None

        def start(self, requested_project_id, workflow, operation):
            db.create_run("initialization-run", requested_project_id, workflow, status="queued")
            self.operation = operation
            return db.get_run("initialization-run")

    runtime = Runtime()
    tasks = CapturingTasks()
    client.app.state.skill_gate = SimpleNamespace(skills=lambda _path: skills)
    client.app.state.skill_runtime = runtime
    client.app.state.run_tasks = tasks
    outline_before = client.app.state.outlines.current(project_id)

    response = client.post(f"/api/projects/{project_id}/initialize-skills")
    asyncio.run(tasks.operation("initialization-run"))

    assert response.status_code == 202
    assert [name for name, _context in runtime.calls] == [
        "character-management", "worldbuilding", "plot-structure",
    ]
    assert {context["source_versions"]["prose_baseline"] for _name, context in runtime.calls} == {1}
    assert len(runtime.calls[0][1]["prose_rules"]) == 2
    assert runtime.calls[1][1]["prose_rules"] == []
    assert len(runtime.calls[2][1]["creative_methods"]) == 1
    assert learning.get_artifact(project_id, "prose_baseline")["version"] == 2
    assert client.app.state.outlines.current(project_id) == outline_before
    events = db.list_run_events("initialization-run")
    snapshot = next(item for item in events if item["event_type"] == "initialization_learning_snapshot")
    assert snapshot["metadata"]["prose_baseline"] == 1
    assert snapshot["metadata"]["creative_blueprint"] == 1


def test_initialization_skips_complete_stage_without_execution_history(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    _wizard, project_data = create_completed_wizard(client)
    project_id = project_data["id"]
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "正式版", "outline": "# 正式大纲\n\n## 开头\n门被推开。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    project = client.app.state.projects.get(project_id)
    metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = ["story-init"]
    (project.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    skill = SimpleNamespace(name="story-init", content_hash="hash-story-init")

    class Runtime:
        calls = []

        async def run(self, requested_project_id, skill_name, answers, bootstrap=False):
            self.calls.append(skill_name)
            raise AssertionError("complete formal materials must not be regenerated")

    class CapturingTasks:
        operation = None

        def start(self, requested_project_id, workflow, operation):
            db.create_run("complete-materials-run", requested_project_id, workflow, status="queued")
            self.operation = operation
            return db.get_run("complete-materials-run")

    async def material_manifest(_project_id):
        return {"_review": {"status": "local_only", "message": "local"}}

    runtime = Runtime()
    tasks = CapturingTasks()
    client.app.state.skill_gate = SimpleNamespace(skills=lambda _path: {"story-init": skill})
    client.app.state.skill_runtime = runtime
    client.app.state.run_tasks = tasks
    client.app.state.outlines.material_manifest = material_manifest

    response = client.post(f"/api/projects/{project_id}/initialize-skills")
    result = asyncio.run(tasks.operation("complete-materials-run"))

    assert response.status_code == 202
    assert result == []
    assert runtime.calls == []
    skipped = next(
        item for item in db.list_run_events("complete-materials-run")
        if item["event_type"] == "skill_skipped"
    )
    assert "资料已经完整" in skipped["message"]


def test_initialization_rolls_back_all_earlier_stages_when_a_later_stage_fails(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    _wizard, project_data = create_completed_wizard(client)
    project_id = project_data["id"]
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "正式版", "outline": "# 正式大纲\n\n## 开头\n门被推开。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    project = client.app.state.projects.get(project_id)
    rollback_indexes = [
        project.path / "chapters" / "_index.md",
        project.path / "glossary" / "_index.md",
        project.path / "scenes" / "_index.md",
    ]
    original_indexes = {path: path.read_text(encoding="utf-8") for path in rollback_indexes}
    metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = ["character-management", "worldbuilding"]
    (project.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    skills = {
        name: SimpleNamespace(name=name, content_hash=f"hash-{name}")
        for name in metadata["initialization_skills"]
    }

    class Runtime:
        async def run(self, requested_project_id, skill_name, answers, bootstrap=False):
            if skill_name == "character-management":
                generated = project.path / "characters" / "generated.md"
                content = "---\nname: 临时人物\nrole: protagonist\n---\n# 临时人物\n"
                generated.write_text(
                    content,
                    encoding="utf-8",
                )
                for path in rollback_indexes:
                    path.write_text("changed by reindex", encoding="utf-8")
                db.create_skill_execution(
                    "character-execution", project.id, skill_name,
                    skills[skill_name].content_hash, "completed",
                )
                db.save_file_proposal(
                    "character-proposal", "character-execution",
                    "characters/generated.md", content, "applied",
                )
                return {
                    "id": "character-execution", "status": "completed",
                    "proposals": [],
                }
            error = RuntimeError("世界设定生成失败")
            error.proposal_summary = {
                "execution_id": "worldbuilding-execution",
                "retainable_count": 2,
                "repair_count": 1,
                "duplicate_count": 1,
                "missing_count": 1,
                "missing_items": ["这些故事地点还没有资料：镇子集市"],
                "formal_unchanged": True,
            }
            raise error

    class CapturingTasks:
        operation = None

        def start(self, requested_project_id, workflow, operation):
            db.create_run("rollback-run", requested_project_id, workflow, status="queued")
            self.operation = operation
            return db.get_run("rollback-run")

    tasks = CapturingTasks()
    client.app.state.skill_gate = SimpleNamespace(skills=lambda _path: skills)
    client.app.state.skill_runtime = Runtime()
    client.app.state.run_tasks = tasks

    assert client.post(f"/api/projects/{project_id}/initialize-skills").status_code == 202
    with pytest.raises(RuntimeError, match="世界设定生成失败"):
        asyncio.run(tasks.operation("rollback-run"))

    assert not (project.path / "characters" / "generated.md").exists()
    assert all(
        path.read_text(encoding="utf-8") == original_indexes[path]
        for path in rollback_indexes
    )
    assert db.get_skill_execution("character-execution")["status"] == "recoverable"
    assert db.list_file_proposals("character-execution")[0]["status"] == "retained"
    assert any(
        item["event_type"] == "initialization_rolled_back"
        for item in db.list_run_events("rollback-run")
    )
    failed = next(
        item for item in db.list_run_events("rollback-run")
        if item["event_type"] == "skill_failed"
    )
    assert failed["metadata"]["proposal_summary"]["retainable_count"] == 2
    assert failed["metadata"]["proposal_summary"]["formal_unchanged"] is True


def test_cancelling_initialization_restores_formal_materials(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    _wizard, project_data = create_completed_wizard(client)
    project_id = project_data["id"]
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "正式版", "outline": "# 正式大纲\n\n## 开头\n门被推开。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    project = client.app.state.projects.get(project_id)
    metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = ["character-management"]
    (project.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    skill = SimpleNamespace(name="character-management", content_hash="hash-character")

    class Runtime:
        def __init__(self):
            self.started = asyncio.Event()

        async def run(self, requested_project_id, skill_name, answers, bootstrap=False):
            generated = project.path / "characters" / "cancelled.md"
            generated.write_text(
                "---\nname: 临时人物\nrole: protagonist\n---\n# 临时人物\n",
                encoding="utf-8",
            )
            self.started.set()
            await asyncio.Event().wait()

    class CapturingTasks:
        operation = None

        def start(self, requested_project_id, workflow, operation):
            db.create_run("cancel-run", requested_project_id, workflow, status="queued")
            self.operation = operation
            return db.get_run("cancel-run")

    runtime = Runtime()
    tasks = CapturingTasks()
    client.app.state.skill_gate = SimpleNamespace(
        skills=lambda _path: {"character-management": skill},
    )
    client.app.state.skill_runtime = runtime
    client.app.state.run_tasks = tasks

    assert client.post(f"/api/projects/{project_id}/initialize-skills").status_code == 202

    async def cancel_operation() -> None:
        task = asyncio.create_task(tasks.operation("cancel-run"))
        await runtime.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_operation())

    assert not (project.path / "characters" / "cancelled.md").exists()
    assert any(
        item["event_type"] == "initialization_rolled_back"
        for item in db.list_run_events("cancel-run")
    )


def test_wizard_interview_history_turn_and_apply_routes(tmp_path) -> None:
    interviews = FakeInterviews()
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", interview_service=interviews,
    ))
    wizard = client.post("/api/wizards", json={"mode": "long"}).json()

    turn = client.post(f"/api/wizards/{wizard['id']}/interview", json={
        "message": "我不知道怎么设计人物弧光",
    })
    history = client.get(f"/api/wizards/{wizard['id']}/interview")
    applied = client.post(f"/api/wizards/{wizard['id']}/interview/assistant/apply", json={
        "field_ids": ["protagonist.arc"],
    })

    assert turn.status_code == 201
    assert turn.json()["content"] == "主角最害怕失去什么？"
    assert history.json()[0]["id"] == "assistant"
    assert applied.json()["applied_fields"] == ["protagonist.arc"]


def test_wizard_interview_returns_provider_connection_error(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", interview_service=FailingInterviews(),
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()

    response = client.post(f"/api/wizards/{wizard['id']}/interview", json={"message": "outline"})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "interview_model_failed", "message": "planning provider disconnected",
    }


def test_wizard_interview_returns_not_found_when_draft_was_deleted(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", interview_service=MissingWizardInterviews(),
    ))

    response = client.post("/api/wizards/deleted/interview", json={"message": "outline"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "wizard_not_found"


def test_wizard_lists_safe_confirmed_methods_and_adopts_only_selected_items(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))
    source = client.post("/api/references", json={
        "title": "可学习样本", "source_type": "paste", "text": "他推门后却发现真相。",
    }).json()
    mechanism = client.post(f"/api/references/{source['id']}/learn").json()["mechanisms"][0]
    client.post(
        f"/api/learning/nodes/{mechanism['id']}/revisions",
        json={"action": "confirm", "data": {}},
    )
    competitor = client.post("/api/references", json={
        "title": "竞品", "source_type": "paste", "text": "她转身后门外传来枪声。",
    }).json()
    client.patch(f"/api/references/{competitor['id']}/metadata", json={
        "platform": "知乎", "content_type": "competitor_work", "project_id": None,
    })
    competitor_node = client.post(
        f"/api/references/{competitor['id']}/learn",
    ).json()["mechanisms"][0]
    client.post(
        f"/api/learning/nodes/{competitor_node['id']}/revisions",
        json={"action": "confirm", "data": {}},
    )
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "选择写法", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})

    choices = client.get(f"/api/wizards/{wizard['id']}/confirmed-mechanisms")
    project = client.post(
        f"/api/wizards/{wizard['id']}/confirm",
        json={"selected_mechanism_ids": [mechanism["id"]]},
    )

    assert choices.status_code == 200
    assert [item["id"] for item in choices.json()] == [mechanism["id"]]
    assert len(choices.json()) <= 12
    assert project.status_code == 201
    learning = client.get(f"/api/projects/{project.json()['id']}/learning").json()
    assert [item["node_id"] for item in learning["adoptions"]] == [mechanism["id"]]


def test_scoped_wizard_lists_all_confirmed_methods_from_selected_sources(tmp_path) -> None:
    client = wizard_client(tmp_path)
    first, first_nodes = confirmed_source(client, "第一篇", "reference_work", count=8)
    second, second_nodes = confirmed_source(client, "第二篇", "popular_sample", count=7)
    _, ignored_nodes = confirmed_source(client, "教程", "writing_tutorial", count=1)

    wizard = client.post("/api/wizards", json={
        "mode": "short",
        "reference_source_ids": [first["id"], second["id"], first["id"]],
    }).json()
    choices = client.get(
        f"/api/wizards/{wizard['id']}/confirmed-mechanisms",
    ).json()
    repeated_choices = client.get(
        f"/api/wizards/{wizard['id']}/confirmed-mechanisms",
    ).json()

    assert repeated_choices == choices
    assert wizard["schema"]["creation_context"]["reference_source_ids"] == [
        first["id"], second["id"],
    ]
    assert [item["source_id"] for item in choices] == [
        *([first["id"]] * len(first_nodes)),
        *([second["id"]] * len(second_nodes)),
    ]
    assert {item["id"] for item in choices[:len(first_nodes)]} == {
        node["id"] for node in first_nodes
    }
    assert {item["id"] for item in choices[len(first_nodes):]} == {
        node["id"] for node in second_nodes
    }
    assert {item["source_id"] for item in choices} == {first["id"], second["id"]}
    assert {item["source_title"] for item in choices} == {"第一篇", "第二篇"}
    assert ignored_nodes[0]["id"] not in {item["id"] for item in choices}


def test_wizard_selection_order_survives_deduplication_adoptions_and_blueprint(tmp_path) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "乱序写法", "reference_work", count=3)
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "保持选择顺序", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    selected = [
        nodes[2]["id"], nodes[0]["id"], nodes[2]["id"],
        nodes[1]["id"], nodes[0]["id"],
    ]
    expected = [nodes[2]["id"], nodes[0]["id"], nodes[1]["id"]]

    response = client.post(
        f"/api/wizards/{wizard['id']}/confirm",
        json={"selected_mechanism_ids": selected},
    )

    assert response.status_code == 201
    project_id = response.json()["id"]
    completed = client.get(f"/api/wizards/{wizard['id']}").json()
    assert completed["schema"]["creation_context"]["selected_mechanism_ids"] == expected
    learning = client.app.state.learning
    assert [item["node_id"] for item in learning.list_adoptions(project_id)] == expected
    blueprint = learning.get_artifact(project_id, "creative_blueprint")
    assert [item["provenance"]["node_id"] for item in blueprint["data"]["mechanisms"]] == expected


def test_wizard_rejects_missing_reference_creation_source(tmp_path) -> None:
    response = wizard_client(tmp_path).post("/api/wizards", json={
        "mode": "short",
        "reference_source_ids": ["missing"],
    })

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "reference_not_found",
        "message": "有一篇所选资料不存在，请重新选择。",
    }


def test_wizard_rejects_unsupported_reference_creation_source(tmp_path) -> None:
    client = wizard_client(tmp_path)
    tutorial, _ = confirmed_source(client, "教程", "writing_tutorial")

    response = client.post("/api/wizards", json={
        "mode": "short",
        "reference_source_ids": [tutorial["id"]],
    })

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "reference_type_not_supported",
        "message": "所选资料不能用于创建作品，请选择参考作品或爆款样本。",
    }


def test_scoped_wizard_requires_confirmed_method_from_every_source(tmp_path) -> None:
    client = wizard_client(tmp_path)
    ready, _ = confirmed_source(client, "已准备", "reference_work")
    waiting, _ = confirmed_source(client, "待确认", "popular_sample", count=0)
    wizard = client.post("/api/wizards", json={
        "mode": "short",
        "reference_source_ids": [ready["id"], waiting["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "尚未创建", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})

    response = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "reference_learning_not_ready",
        "message": "有一篇所选资料还没有已确认写法，请先确认候选写法。",
    }
    assert client.get("/api/projects").json() == []


def test_scoped_wizard_rejects_too_many_unique_methods(tmp_path) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "很多写法", "reference_work", count=13)
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()

    response = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [
            *(node["id"] for node in nodes),
            nodes[0]["id"],
        ],
    })

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_learning_selection",
        "message": "一次最多选择 12 条已确认写法。",
    }


def test_scoped_wizard_rejects_out_of_scope_or_stale_method(tmp_path) -> None:
    client = wizard_client(tmp_path)
    selected, selected_nodes = confirmed_source(client, "选中资料", "reference_work", count=2)
    _, outside_nodes = confirmed_source(client, "范围外资料", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [selected["id"]],
    }).json()

    outside = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [outside_nodes[0]["id"]],
    })
    client.post(
        f"/api/learning/nodes/{selected_nodes[0]['id']}/revisions",
        json={"action": "reject", "data": {}},
    )
    stale = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [selected_nodes[0]["id"]],
    })

    for response in (outside, stale):
        assert response.status_code == 400
        assert response.json()["detail"] == {
            "code": "invalid_learning_selection",
            "message": "所选写法已失效，请返回确认页重新选择。",
        }
    assert client.get("/api/projects").json() == []


def test_rejected_high_confidence_method_cannot_be_adopted_directly(tmp_path) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "已拒绝资料", "reference_work")
    _, project = create_completed_wizard(client)
    rejected = client.post(
        f"/api/learning/nodes/{nodes[0]['id']}/revisions",
        json={"action": "reject", "data": {}},
    )
    assert rejected.status_code == 200

    response = client.post(
        f"/api/projects/{project['id']}/learning/adoptions/{nodes[0]['id']}",
        json={"edits": {}},
    )

    assert response.status_code == 422
    assert "重新确认后才能应用到作品" in response.json()["detail"]
    assert client.get(f"/api/projects/{project['id']}/learning").json()["adoptions"] == []


def test_confirm_serializes_learning_rejection_and_delete_after_selection_snapshot(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "并发资料", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "并发确认", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    learning = client.app.state.learning
    original_list = learning.list_mechanisms
    snapshot_ready = Event()
    release_snapshot = Event()
    rejection_attempted = Event()
    rejection_finished = Event()

    def paused_list(*args, **kwargs):
        result = original_list(*args, **kwargs)
        snapshot_ready.set()
        assert release_snapshot.wait(2)
        return result

    def reject_and_delete_node():
        rejection_attempted.set()
        rejected = learning.revise_node(nodes[0]["id"], "reject", {})
        deletion = learning.delete_rejected_nodes([nodes[0]["id"]])
        rejection_finished.set()
        return rejected, deletion

    monkeypatch.setattr(learning, "list_mechanisms", paused_list)
    with ThreadPoolExecutor(max_workers=2) as executor:
        confirmation = executor.submit(
            client.post,
            f"/api/wizards/{wizard['id']}/confirm",
            json={"selected_mechanism_ids": [nodes[0]["id"]]},
        )
        assert snapshot_ready.wait(2)
        rejection = executor.submit(reject_and_delete_node)
        assert rejection_attempted.wait(2)
        assert not rejection_finished.wait(0.1)
        release_snapshot.set()
        response = confirmation.result(timeout=5)
        rejected, deletion = rejection.result(timeout=5)

    assert response.status_code == 201
    assert rejected["status"] == "rejected"
    assert deletion["deleted_ids"] == []
    project_learning = client.get(
        f"/api/projects/{response.json()['id']}/learning",
    ).json()
    assert [item["node_id"] for item in project_learning["adoptions"]] == [nodes[0]["id"]]


def test_completed_scoped_wizard_retry_returns_original_project_after_sources_change(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "重试资料", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "可重试创建", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    payload = {"selected_mechanism_ids": [nodes[0]["id"]]}

    first = client.post(f"/api/wizards/{wizard['id']}/confirm", json=payload)
    assert first.status_code == 201
    learning = client.app.state.learning
    monkeypatch.setattr(
        learning, "ensure_adoptions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completed retry must not rerun confirmation effects")
        ),
    )
    changed = client.patch(f"/api/references/{source['id']}/metadata", json={
        "platform": None,
        "content_type": "writing_tutorial",
        "project_id": None,
    })
    assert changed.status_code == 200
    client.post(
        f"/api/learning/nodes/{nodes[0]['id']}/revisions",
        json={"action": "reject", "data": {}},
    )

    changed_retry = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [],
    })
    assert changed_retry.status_code == 201
    assert changed_retry.json()["id"] == first.json()["id"]
    assert client.delete(f"/api/references/{source['id']}").status_code == 204
    deleted_retry = client.post(f"/api/wizards/{wizard['id']}/confirm", json=payload)

    assert deleted_retry.status_code == 201
    assert deleted_retry.json()["id"] == first.json()["id"]
    assert len(client.get("/api/projects").json()) == 1
    completed = client.get(f"/api/wizards/{wizard['id']}").json()
    assert completed["schema"]["creation_context"]["selected_mechanism_ids"] == [
        nodes[0]["id"],
    ]
    assert completed["schema"]["creation_context"]["confirmation_effects_completed"] is True


def test_completed_wizard_retry_fills_missing_adoptions_in_original_order(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "两条写法", "reference_work", count=2)
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "中断后续跑", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
        "market_baseline_enabled": {"value": "enabled", "policy": "suggestible"},
        "market_baseline_key": {
            "value": json.dumps({"platform": "test"}, ensure_ascii=False),
            "policy": "suggestible",
        },
    }})
    learning = client.app.state.learning
    monkeypatch.setattr(
        client.app.state.market_baselines,
        "build_baseline",
        lambda key: {"key": key, "sample_count": 1},
    )
    original_adopt = learning._adopt
    adoption_calls = 0

    def fail_second_adoption(project_id, node_id, edits=None):
        nonlocal adoption_calls
        adoption_calls += 1
        if adoption_calls == 2:
            raise OSError("forced adoption interruption")
        return original_adopt(project_id, node_id, edits)

    monkeypatch.setattr(learning, "_adopt", fail_second_adoption)
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    failed = failing_client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [nodes[0]["id"], nodes[1]["id"]],
    })

    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "code": "wizard_confirmation_incomplete",
        "message": "作品已经保留，但创建收尾还没有完成。请再次点击确认继续。",
    }
    assert "forced adoption interruption" not in failed.text

    interrupted = client.get(f"/api/wizards/{wizard['id']}").json()
    assert interrupted["status"] == "completed"
    assert interrupted["schema"]["creation_context"] == {
        "reference_source_ids": [source["id"]],
        "selected_mechanism_ids": [nodes[0]["id"], nodes[1]["id"]],
        "confirmation_effects_completed": False,
    }
    project_id = interrupted["project_id"]
    assert [item["node_id"] for item in learning.list_adoptions(project_id)] == [
        nodes[0]["id"],
    ]
    assert len(learning.artifact_history(project_id, "market_baseline")) == 1
    assert len(learning.artifact_history(project_id, "creative_blueprint")) == 1

    monkeypatch.setattr(learning, "_adopt", original_adopt)
    resumed = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [],
    })

    assert resumed.status_code == 201
    assert resumed.json()["id"] == project_id
    assert len(client.get("/api/projects").json()) == 1
    assert [item["node_id"] for item in learning.list_adoptions(project_id)] == [
        nodes[0]["id"], nodes[1]["id"],
    ]
    assert len(learning.artifact_history(project_id, "market_baseline")) == 1
    assert len(learning.artifact_history(project_id, "creative_blueprint")) == 2
    completed = client.get(f"/api/wizards/{wizard['id']}").json()
    assert completed["schema"]["creation_context"]["confirmation_effects_completed"] is True


def test_completed_wizard_retry_rebuilds_blueprint_after_adoption_write(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "蓝图恢复", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "蓝图恢复", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    learning = client.app.state.learning
    original_save = learning._save_creative_blueprint

    def fail_blueprint(_project_id):
        raise OSError("forced blueprint interruption")

    monkeypatch.setattr(learning, "_save_creative_blueprint", fail_blueprint)
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    failed = failing_client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [nodes[0]["id"]],
    })

    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "code": "wizard_confirmation_incomplete",
        "message": "作品已经保留，但创建收尾还没有完成。请再次点击确认继续。",
    }
    assert "forced blueprint interruption" not in failed.text

    interrupted = client.get(f"/api/wizards/{wizard['id']}").json()
    project_id = interrupted["project_id"]
    assert interrupted["schema"]["creation_context"]["confirmation_effects_completed"] is False
    assert [item["node_id"] for item in learning.list_adoptions(project_id)] == [
        nodes[0]["id"],
    ]
    assert learning.get_artifact(project_id, "creative_blueprint") is None

    monkeypatch.setattr(learning, "_save_creative_blueprint", original_save)
    resumed = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert resumed.status_code == 201
    blueprint = learning.get_artifact(project_id, "creative_blueprint")
    assert blueprint is not None
    assert [item["provenance"]["node_id"] for item in blueprint["data"]["mechanisms"]] == [
        nodes[0]["id"],
    ]
    completed = client.get(f"/api/wizards/{wizard['id']}").json()
    assert completed["schema"]["creation_context"]["confirmation_effects_completed"] is True


def test_creative_blueprint_repairs_non_object_and_invalid_utf8_files(tmp_path) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "蓝图磁盘修复", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "蓝图磁盘修复", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    project = client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [nodes[0]["id"]],
    }).json()
    learning = client.app.state.learning
    path = (
        client.app.state.projects.get(project["id"]).path
        / "learning"
        / "creative_blueprint.json"
    )

    path.write_text("[]", encoding="utf-8")
    learning._save_creative_blueprint(project["id"])
    repaired_non_object = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(repaired_non_object, dict)
    assert repaired_non_object["version"] == 2

    path.write_bytes(b"\xff\xfe")
    learning._save_creative_blueprint(project["id"])
    repaired_encoding = json.loads(path.read_text(encoding="utf-8"))

    assert repaired_encoding["version"] == 3
    assert len(learning.artifact_history(project["id"], "creative_blueprint")) == 3


def test_completed_wizard_retry_fills_feedback_after_feedback_write_failure(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "反馈恢复", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "反馈恢复", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    learning = client.app.state.learning
    original_feedback = learning.record_feedback

    def fail_feedback(*_args, **_kwargs):
        raise RuntimeError("forced feedback interruption")

    monkeypatch.setattr(learning, "record_feedback", fail_feedback)
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    failed = failing_client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [nodes[0]["id"]],
    })

    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "wizard_confirmation_incomplete"
    assert "forced feedback interruption" not in failed.text
    interrupted = client.get(f"/api/wizards/{wizard['id']}").json()
    project_id = interrupted["project_id"]
    assert interrupted["schema"]["creation_context"]["confirmation_effects_completed"] is False
    assert [item["node_id"] for item in learning.list_adoptions(project_id)] == [
        nodes[0]["id"],
    ]

    monkeypatch.setattr(learning, "record_feedback", original_feedback)
    resumed = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert resumed.status_code == 201
    with learning.db.connect() as connection:
        feedback_count = connection.execute(
            "SELECT COUNT(*) FROM learning_feedback "
            "WHERE project_id=? AND subject_id=? AND action='adopted'",
            (project_id, nodes[0]["id"]),
        ).fetchone()[0]
    assert feedback_count == 1
    completed = client.get(f"/api/wizards/{wizard['id']}").json()
    assert completed["schema"]["creation_context"]["confirmation_effects_completed"] is True


def test_incomplete_confirmation_reports_changed_source_in_chinese(
    tmp_path, monkeypatch,
) -> None:
    client = wizard_client(tmp_path)
    source, nodes = confirmed_source(client, "失效恢复", "reference_work")
    wizard = client.post("/api/wizards", json={
        "mode": "short", "reference_source_ids": [source["id"]],
    }).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "失效恢复", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})
    learning = client.app.state.learning
    original_adopt = learning._adopt
    monkeypatch.setattr(
        learning, "_adopt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("forced interruption")),
    )
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    failed = failing_client.post(f"/api/wizards/{wizard['id']}/confirm", json={
        "selected_mechanism_ids": [nodes[0]["id"]],
    })
    assert failed.status_code == 503
    monkeypatch.setattr(learning, "_adopt", original_adopt)
    assert client.delete(f"/api/references/{source['id']}").status_code == 204

    resumed = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert resumed.status_code == 409
    assert resumed.json()["detail"] == {
        "code": "wizard_confirmation_recovery_blocked",
        "message": "作品和已落地写法已保留；请前往学习库为该作品重新选择补充写法。",
    }
    incomplete = client.get(f"/api/wizards/{wizard['id']}").json()
    assert incomplete["schema"]["creation_context"]["confirmation_effects_completed"] is False


def test_unscoped_wizard_still_lists_only_first_twelve_confirmed_methods(tmp_path) -> None:
    client = wizard_client(tmp_path)
    first, first_nodes = confirmed_source(client, "全局一", "reference_work", count=8)
    second, second_nodes = confirmed_source(client, "全局二", "popular_sample", count=7)
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()

    choices = client.get(
        f"/api/wizards/{wizard['id']}/confirmed-mechanisms",
    ).json()

    all_ids = {node["id"] for node in [*first_nodes, *second_nodes]}
    assert len(choices) == 12
    assert {item["id"] for item in choices} <= all_ids
    assert {
        item["source_id"] for item in choices
    } <= {first["id"], second["id"]}


def test_wizard_does_not_adopt_confirmed_methods_without_explicit_selection(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))
    source = client.post("/api/references", json={
        "title": "样本", "source_type": "paste", "text": "他推门后却发现真相。",
    }).json()
    mechanism = client.post(f"/api/references/{source['id']}/learn").json()["mechanisms"][0]
    client.post(f"/api/learning/nodes/{mechanism['id']}/revisions", json={"action": "confirm", "data": {}})
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "默认不选", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一扇门。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})

    project = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert client.get(f"/api/projects/{project.json()['id']}/learning").json()["adoptions"] == []
    assert client.app.state.learning.get_artifact(
        project.json()["id"], "creative_blueprint",
    ) is None
