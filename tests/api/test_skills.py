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
