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


def test_console_stylesheet_has_visual_system_and_accessible_motion(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    css = client.get("/static/app.css").text

    assert "--accent:#6d5dfc" in css
    assert "--sidebar:#15182a" in css
    assert "--motion:180ms" in css
    assert ":focus-visible" in css
    assert ".status::before" in css
    assert ".project-item:hover" in css
    assert ".learning-artifact" in css
    assert "var(--shadow-sm)" in css
    assert ".market-ranking-track" in css
    assert ".market-ranking-legend" in css
    assert ".market-ranking-segment:focus-visible" in css
    assert "@media (prefers-reduced-motion:reduce)" in css


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
    assert 'id="writing-rules-summary"' in html
    assert 'id="open-learning-library"' in html
    assert 'id="style-sample-analyze"' not in html
    assert 'id="style-sample-delete"' not in html
    assert 'id="publish-candidate"' in html
    assert 'id="genre-options"' in html
    assert 'id="project-list"' in html
    assert 'id="trash-list"' in html
    assert 'data-view="trash"' in html
    assert 'data-view="materials"' in html
    assert 'data-view="learning"' in html
    assert 'data-view="market"' in html
    assert 'id="market-platform"' in html
    assert 'id="market-period"' in html
    assert 'id="market-ranking"' in html
    assert 'id="market-category"' in html
    assert 'id="market-refresh"' in html
    assert 'id="market-summary"' in html
    assert 'id="market-share-chart"' in html
    assert 'id="market-trend-chart"' in html
    assert 'id="market-heat-chart"' in html
    assert 'id="market-ranking-chart"' in html
    assert 'id="market-keywords"' in html
    assert 'id="market-length-type"' in html
    assert 'id="market-keyword-source"' in html
    assert 'id="market-keyword-category"' in html
    assert '篇幅类型' in html
    assert 'id="market-work-list"' in html
    assert 'id="market-work-mode"' in html
    assert 'id="market-rank-heading"' in html
    assert 'value="grouped"' in html
    assert 'value="combined"' in html
    assert "不代表全网市场" in html
    assert 'id="reference-form"' in html
    assert 'id="reference-list"' in html
    assert 'id="reference-detail"' in html
    assert 'id="reference-url"' in html
    assert 'id="reference-import-status"' in html
    assert 'id="learning-project"' in html
    assert 'id="learning-mechanisms"' in html
    assert 'id="learning-mechanism-view"' in html
    assert 'id="nlp-install"' in html
    assert 'id="workflow-analysis-toggle"' in html
    assert "爆款指数" not in html
    assert 'id="materials-project"' in html
    assert 'id="character-list"' in html
    assert 'id="character-detail"' in html
    assert 'id="material-tabs"' in html
    assert 'id="material-check"' in html
    assert 'id="material-impact-status"' in html
    assert 'id="project-learning-materials"' in html
    assert 'id="edit-project-learning"' in html
    assert '<details class="story-state-band">' in html
    assert html.index('id="materials"') < html.index('id="story-state-section"')
    assert 'id="interview-panel"' in html
    assert 'id="interview-start"' in html
    assert 'id="interview-messages"' in html
    assert 'id="interview-form"' in html
    assert 'id="interview-apply"' in html
    assert 'id="interview-status"' in html
    assert 'id="provider-form-title"' in html
    assert 'id="provider-cancel"' in html
    assert 'name="auth_type"' not in html
    assert 'name="timeout_seconds"' not in html
    assert 'name="extra_headers"' not in html
    script = client.get("/static/app.js").text
    assert "loadMarketDashboard" in script
    assert "renderMarketDashboard" in script
    assert "market-ranking-segment" in script
    assert "market-ranking-legend-item" in script
    assert "market-ranking-group" in script
    assert "marketWorkSortValue" in script
    assert "个榜单" in script
    assert "updateMarketWorkLength" not in script
    assert "/api/market/refresh" in script
    assert "data-market-link" in script
    assert "loadInterview" in script
    assert "data-provider-edit" in script
    assert "data-provider-delete" in script
    assert "editingProviderId" in script
    assert "含辅助脚本" in script
    assert "applyInterviewSuggestions" in script
    assert "formatLocalTimestamp" in script
    assert "formatLocalTimestamp(r.created_at)" in script
    assert "formatLocalTimestamp(item.created_at, true)" in script
    assert "formatLocalTimestamp(item.trashed_at)" in script
    assert "const latestRun = runs[0]" in script
    assert "showRunDetail(await api(`/api/runs/${latestRun.id}`))" in script
    assert "continueProject(button.dataset.continue)" in script
    assert "resumableRun" in script
    assert "run(`/api/runs/${resumableRun.id}/resume`)" in script
    assert "reference-import-status" in script
    assert "正在读取网页内容" in script
    assert "form.querySelector" in script
    assert '["failed","cancelled"].includes(item.status)' in script
    assert 'includes("token_budget_exhausted")' not in script
    assert 'if (!resumableRun) return toast("没有可继续的失败任务")' in script
    assert "const pendingFallbacks=new Set()" in script
    assert "pendingFallbacks.delete(item.stage)" in script
    assert "const fallbacks=new Set(events.filter" not in script
    assert "binding-primary-${role}" in script
    assert "binding-fallback-${role}" in script
    assert "使用程序默认回退" in script
    assert "fallback_provider_id" in script
    assert "fallback_model_id" in script
    assert 'scrollIntoView({behavior:"smooth",block:"start"})' in script
    assert 'catch(error) { toast(error.message); }' in script
    assert "loadProjectLocations" in script
    assert "正文有效字数" in script
    assert "runs/materials-audit" in script
    assert "runs/materials-repair" in script
    assert "material-table" in script
    assert "analyzeMaterialImpact" in script
    assert "applyMaterialImpact" in script
    assert "retire_removed_settings" in script
    assert "item.display?.title" in script
    assert "loadWritingRulesSummary" in script
    assert "已迁移旧范文笔感" in script
    assert "style-sample-analyze" not in script
    assert "navigator.clipboard.writeText" in script
    assert "locations/${button.dataset.openLocation}/open" in script
    assert "/candidate/publish" in script
    assert "主模型和备用模型不能相同" in script
    assert 'reader_review: "目标读者模拟"' in script
    assert 'api("/api/references")' in script
    assert '/analyze`' in script
    assert "renderReferences" in script
    assert "renderProjectLearningMaterials" in script
    assert "loadWorkflowAnalysis" in script
    assert "local_corpus_only" in script
    assert "readableLearningValue(item.data)" in script
    assert "state.references.map(item=>" in script
    assert 'api("/api/learning/mechanisms")' in script
    assert "startWizardFromReference" in script
    assert "data-reference-create" in script
