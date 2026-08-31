from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def test_skill_api_lists_and_approves_executable_skill(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = root / "maintenance"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: maintenance\n---\nRun scripts/run.py.", encoding="utf-8",
    )
    (folder / "scripts" / "run.py").write_text("print('ok')", encoding="utf-8")
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[root],
    ))

    skill = client.get("/api/skills").json()[0]
    assert skill["name"] == "maintenance"
    assert skill["executable"] is True
    assert skill["approved"] is False

    response = client.post("/api/skills/maintenance/approve", json={"content_hash": skill["content_hash"]})
    assert response.status_code == 200
    assert response.json()["approved"] is True


def test_skill_api_distinguishes_auxiliary_scripts_from_executable_skill(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = root / "better-writing"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: better-writing\n---\nImprove prose.", encoding="utf-8",
    )
    (folder / "scripts" / "validate.py").write_text("print('ok')", encoding="utf-8")
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[root],
    ))

    skill = client.get("/api/skills").json()[0]

    assert skill["executable"] is False
    assert skill["has_scripts"] is True
    assert skill["approved"] is True


def test_skill_api_reports_conservative_prompt_conflicts(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = root / "style"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: style\n---\n多用短句，模仿指定作者风格。",
        encoding="utf-8",
    )
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[root],
    ))

    skill = client.get("/api/skills").json()[0]

    assert {item["code"] for item in skill["conflicts"]} == {
        "fragmented_prose", "author_imitation",
    }


def test_stage_api_runs_required_prompt_skill(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = root / "humanizer"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: humanizer\n---\nRemove AI patterns.", encoding="utf-8")
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[root],
    ))

    response = client.post("/api/skill-stages/polish/run", json={"required": ["humanizer"]})

    assert response.status_code == 200
    assert "Remove AI patterns." in response.json()["prompt"]
    assert response.json()["receipts"][0]["status"] == "succeeded"


def _write_prompt_skill(root, name: str, content: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n{content}", encoding="utf-8",
    )


def test_skill_api_reports_project_aware_effective_source_and_hashes(tmp_path) -> None:
    global_root = tmp_path / "global"
    repo_root = tmp_path / "repo"
    _write_prompt_skill(global_root, "dialogue", "Global voice")
    _write_prompt_skill(repo_root, "dialogue", "Repo voice")
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[global_root, repo_root],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Source Truth", "mode": "short", "genre": "mystery",
        "premise": "A source changes.", "target_words": 6000,
    }).json()
    # The API returns an absolute project path; use the production store rather
    # than guessing slug formatting on another platform.
    project_root = client.app.state.projects.get(project["id"]).path

    repo_skill = client.get(
        f"/api/skills?project_id={project['id']}",
    ).json()[0]
    assert repo_skill["effective_source_kind"] == "repo"
    assert repo_skill["fallback_used"] is False
    assert repo_skill["effective_resolved_path"] == str(repo_root / "dialogue")
    assert repo_skill["resolved_source_sha256"] == repo_skill["content_hash"]
    assert len(repo_skill["primary_document_sha256"]) == 64
    assert repo_skill["selective_or_hybrid_production_active"] is False

    _write_prompt_skill(
        project_root / ".agents" / "skills", "dialogue", "Project voice",
    )
    project_skill = client.get(
        f"/api/skills?project_id={project['id']}",
    ).json()[0]
    assert project_skill["effective_source_kind"] == "project_override"
    assert project_skill["project_candidate_exists"] is True
    assert project_skill["effective_resolved_path"] == str(
        project_root / ".agents" / "skills" / "dialogue"
    )


def test_skill_api_labels_global_only_as_explicit_fallback(tmp_path) -> None:
    global_root = tmp_path / "global"
    repo_root = tmp_path / "repo"
    _write_prompt_skill(global_root, "story-init", "Initialize story")
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[global_root, repo_root],
    ))

    skill = client.get("/api/skills").json()[0]

    assert skill["effective_source_kind"] == "global_fallback"
    assert skill["fallback_used"] is True
    assert skill["repo_candidate_exists"] is False
    assert skill["used_by_current_production"] is True


def test_skill_page_labels_configured_roots_and_effective_source() -> None:
    script = (
        __import__("pathlib").Path(__file__).parents[2]
        / "src" / "novel_flywheel" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    for label in (
        "全局 Skill 根目录", "仓库 Skill 根目录", "项目 Skill 根目录",
        "当前实际来源", "来源类型", "是否使用回退",
    ):
        assert label in script
    assert "loadEffectiveSkills" in script
    assert "selective_or_hybrid_production_active" not in script
