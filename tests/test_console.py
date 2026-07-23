from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def test_console_and_assets_are_served_locally(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    page = client.get("/")
    assert page.status_code == 200
    assert "小说飞轮" in page.text
    assert "/static/app.js" in page.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").headers["cache-control"] == "no-store"


def test_console_contains_skill_wizard_controls(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    assert 'id="start-wizard"' in html
    assert 'id="wizard-steps"' in html
    assert 'id="wizard-fields"' in html
    assert 'id="wizard-confirm"' in html
    assert 'id="migrate-project"' in html
    assert 'id="run-cancel"' in html
    assert 'id="run-log"' in html
    assert 'id="project-locations"' in html
    assert 'id="candidate-quality"' in html
    assert 'id="publish-candidate"' in html
    assert 'id="genre-options"' in html
    assert 'id="project-list"' in html
    assert 'id="trash-list"' in html
    assert 'data-view="trash"' in html
    assert 'id="interview-panel"' in html
    assert 'id="interview-start"' in html
    assert 'id="interview-messages"' in html
    assert 'id="interview-form"' in html
    assert 'id="interview-apply"' in html
    assert 'id="interview-status"' in html
    script = client.get("/static/app.js").text
    assert "loadInterview" in script
    assert "applyInterviewSuggestions" in script
    assert "formatLocalTimestamp" in script
    assert "formatLocalTimestamp(r.created_at)" in script
    assert "formatLocalTimestamp(item.created_at, true)" in script
    assert "formatLocalTimestamp(item.trashed_at)" in script
    assert "const latestRun = runs[0]" in script
    assert "showRunDetail(await api(`/api/runs/${latestRun.id}`))" in script
    assert "continueProject(button.dataset.continue)" in script
    assert 'if (project.mode === "short")' in script
    assert "run(`/api/projects/${project.id}/runs/short`)" in script
    assert "binding-primary-${role}" in script
    assert "binding-fallback-${role}" in script
    assert "使用程序默认回退" in script
    assert "fallback_provider_id" in script
    assert "fallback_model_id" in script
    assert 'scrollIntoView({behavior:"smooth",block:"start"})' in script
    assert 'catch(error) { toast(error.message); }' in script
    assert "loadProjectLocations" in script
    assert "navigator.clipboard.writeText" in script
    assert "locations/${button.dataset.openLocation}/open" in script
    assert "/candidate/publish" in script
    assert "主模型和备用模型不能相同" in script
    assert 'reader_review: "目标读者模拟"' in script
