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


def test_console_navigation_has_four_groups_without_removing_old_views(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert html.count('class="nav-group"') == 4
    for group in ("创作", "资料与学习", "市场", "设置"):
        assert f">{group}<" in html
    for group_id in ("creation", "learning", "market", "settings"):
        assert f'data-nav-group="{group_id}"' in html
        assert f'aria-controls="nav-group-{group_id}"' in html
        assert f'id="nav-group-{group_id}"' in html
    for view in (
        "workbench",
        "projects",
        "materials",
        "learning",
        "market",
        "models",
        "skills",
        "trash",
    ):
        assert f'id="{view}"' in html
        assert f'data-view="{view}"' in html

    compact_script = script.replace(" ", "")
    assert 'workbench:"creation"' in compact_script
    assert 'projects:"creation"' in compact_script
    assert 'materials:"learning"' in compact_script
    assert 'learning:"learning"' in compact_script
    assert 'market:"market"' in compact_script
    assert 'models:"settings"' in compact_script
    assert 'skills:"settings"' in compact_script
    assert 'trash:"settings"' in compact_script
    assert "async function navigateToView" in script
    assert 'setAttribute("aria-current","page")' in compact_script
    assert ".sidebar-nav" in css
    assert ".nav-group-toggle:focus-visible" in css


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
    assert 'id="market-work-pagination"' in html
    assert 'id="market-baseline-cohort"' in html
    assert 'id="market-baseline-detail"' in html
    assert 'value="grouped"' in html
    assert 'value="combined"' in html
    assert "不代表全网市场" in html
    assert 'id="reference-form"' in html


def test_console_assets_include_narrative_and_issue_ledger_views(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    assert "叙事账本" in script
    assert "问题返修台账" in script
    assert "detail_analysis" in script
    assert "summary.resolved_issues" in script
    assert "已解决记录" in script
    assert "reconciled_at" in script
    assert "已单独复核" in script
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
    assert "data-market-keyword-close" in script
    assert 'event.key==="Escape"' in script
    assert "activeMarketKeyword" in script
    assert "daily_best" in script
    assert "period_best" in script
    assert "market-ranking-toggle" in script
    assert "marketWorkPage" in script
    assert "MARKET_WORK_PAGE_SIZE" in script
    assert "loadMarketBaseline" in script
    assert "updateMarketWorkLength" not in script
    assert "/api/market/refresh" in script
    assert "data-market-link" in script
    assert "loadInterview" in script
    assert "data-provider-edit" in script
    assert "data-provider-delete" in script
    assert "editingProviderId" in script
    assert 'new Set(["planning"])' in script
    assert "需要工具" in script
    assert "不需要工具" in script
    assert ".role-tool-note.required" in client.get("/static/app.css").text
    assert "含辅助脚本" in script
    assert "applyInterviewSuggestions" in script
    assert "formatLocalTimestamp" in script
    assert "formatLocalTimestamp(r.created_at)" in script
    assert "formatLocalTimestamp(item.created_at, true)" in script
    assert "formatLocalTimestamp(item.trashed_at)" in script
    assert "learningReport" in script
    assert "全文覆盖率" in script
    assert "data-mechanism-delete" in script
    assert "deleteRejectedMechanisms" in script
    assert "查看全部证据" in script
    assert "const latestRun = runs[0]" in script
    assert "const detail=await api(`/api/runs/${latestRun.id}`)" in script
    assert "if(detail&&workbenchContextMatches(projectId,generation))showRunDetail(detail)" in script
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
    assert "原创检查仅限本地资料库" in script
    assert "local_corpus_only" not in script
    assert "readableLearningValue(item.data)" in script
    assert 'first:"第一人称"' in script
    assert "readableViewpoint(defaults.viewpoint)" in script
    assert "map((item,index)=>`<li><b>${index+1}</b>" in script
    assert "state.references.map(item=>" in script
    assert 'api("/api/learning/mechanisms?view=all")' in script
    assert "startWizardFromReference" in script
    assert "data-reference-create" in script


def test_reference_metadata_save_action_only_appears_for_changes(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'class="reference-metadata-action"' in script
    assert "data-reference-metadata-save hidden" in script
    assert "button.hidden=!dirty" in script
    assert "✓ 已保存" in script
    assert ".reference-save-state" in css


def test_reference_import_receipt_uses_plain_language_and_direct_actions(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'id="reference-import-receipt"' in html
    for label in ("系统判断", "判断依据", "可以用于", "不会用于", "下一步"):
        assert label in script
    assert "data-receipt-action" in script
    assert ".reference-import-receipt" in css
    assert "正在保存资料" in script
    assert "资料已保存" in script
    assert 'class="receipt-purpose"' in script
    assert 'class="receipt-details"' in script
    assert "receipt-primary-action" in script


def test_learning_library_is_split_into_plain_language_task_views(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text

    for view in ("references", "mechanisms", "application"):
        assert f'data-learning-view="{view}"' in html
        assert f'data-learning-panel="{view}"' in html
    assert "本地诊断是找问题" in html
    assert "本地提炼是找写法" in html
    assert "switchLearningView" in script


def test_learning_library_supports_multi_reference_creation_with_readable_states(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        'id="reference-selection-status"',
        'id="create-from-selected-references"',
        "data-reference-select",
    ):
        assert control in html + script
    for phrase in (
        "已选择 0 篇资料",
        "用所选资料创建新作品",
        "正在检查所选资料",
        "正在完成本地提炼",
        "还需要确认这些资料的候选写法",
        "所选资料会继续保留",
    ):
        assert phrase in script
    compact_script = script.replace(" ", "")
    assert "selectedReferenceIds:newSet()" in compact_script
    assert "reference_source_ids:referenceIds" in compact_script
    assert "startWizardFromReference([source.id])" in script
    assert "startWizardFromReference([...state.selectedReferenceIds])" in script
    assert "reference_work" in script and "popular_sample" in script
    assert "这类资料只用于查阅，不能直接创建作品" in script
    assert 'api("/api/learning/mechanisms?view=all")' in script
    assert 'rejectedView?item.status==="rejected":item.status!=="rejected"' in script
    creation = script.split("async function startWizardFromReference", 1)[1].split(
        '$("#start-wizard")', 1,
    )[0]
    mechanism_assignments = [
        line for line in script.splitlines() if "state.mechanisms=await api" in line
    ]
    assert mechanism_assignments
    assert all("?view=all" in line for line in mechanism_assignments)
    assert '(item.data.analysis_origin||"local")!=="model"' in creation
    assert creation.count("/learn`") == 1
    assert "/model-learn" not in creation
    assert "Promise.allSettled" in creation
    assert creation.index("Promise.allSettled") < creation.index(
        'state.mechanisms=await api("/api/learning/mechanisms?view=all")'
    ) < creation.index("if(localPreparationFailed)")
    assert creation.index('api("/api/wizards"') < creation.index(
        "referenceIds.forEach(id=>state.selectedReferenceIds.delete(id))"
    )
    assert "finally" in creation
    assert "state.referenceSelectionBusy=false" in creation
    assert '基于《${source' not in script
    assert "const guidance=" not in script
    assert ".reference-selection-bar" in css
    assert ".reference-select-control" in css
    assert ".reference-selection-status.success" in css
    assert ".reference-selection-status.error" in css


def test_confirmed_learning_can_create_first_project_without_existing_projects(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text

    assert 'data-mechanism-create-reference="${escapeHtml(item.source_id)}"' in script
    assert "用这篇资料创建新作品" in script
    assert "当前还没有作品，可以直接用这篇资料开始创建。" in script
    assert "startWizardFromReference([button.dataset.mechanismCreateReference])" in script
    assert 'id="learning-application-empty"' in html
    assert 'id="learning-project-content"' in html
    assert 'id="learning-empty-reference"' in html
    assert 'id="learning-empty-new"' in html
    assert "state.projectLearning=null;state.effectiveRules=null;state.outlines=null" in script
    assert '$("#learning-application-empty").hidden=hasProjects' in script
    assert '$("#learning-project-content").hidden=!hasProjects' in script
    assert 'switchLearningView("references")' in script
    assert 'navigateToView("projects")' in script


def test_learning_library_explains_results_and_tracks_actions(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for label in (
        "原文是怎么写的", "为什么值得学习", "你的作品可以怎么用", "什么时候不要用",
        "发现了什么", "为什么可能影响阅读", "建议你检查什么", "技术详情",
        "这是什么", "你需要决定",
    ):
        assert label in script
    assert "reference-task-status" in script
    assert "pollReferenceAnalysisTask" in script
    assert "模型未形成有充分证据的候选内容" in script
    assert "referenceTask" in script
    assert "showIndeterminate" in script
    assert "正在使用已配置的备用模型" in script
    assert "剧情吸引力" in script
    assert "目前只能确定到这里" in script
    assert "renderAttractionMap" in script
    assert "本地吸引力候选" in script
    assert "✓ 已保存" in script
    assert "item.deletable!==false" in script
    assert "delete_reason" in script
    assert "data-mechanism-release" in script
    assert 'class="mechanism-details"' in script
    assert "查看详情" in script
    for label in ("核心目标", "阻碍升级", "阶段结果", "状态变化", "结局设计", "开头设计", "技术详情"):
        assert label in script
    assert 'short_causal_chain:"七步剧情结构"' in script
    for label in ("仍在当前作品中使用", "需要你确认", "继续使用", "从作品移除"):
        assert label in script
    assert 'class="learning-review-reason"' in script
    assert 'class="learning-review-intro"' not in script
    assert "keepLearningReview" in script
    assert "removeLearningReview" in script
    assert ".reference-task-status" in css
    assert ".mechanism-stage-summary" in css
    assert ".learning-review-reason" in css
    assert "learning-review-rules { grid-template-columns:1fr" in css
    assert ".learning-review-item footer button { flex:1" in css


def test_project_application_keeps_title_and_review_actions_easy_to_find(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert "当前作品的创作设置" in html
    assert "正在使用的写法和规则" in html
    assert '<p class="eyebrow">大纲版本</p>' not in html
    assert 'class="learning-review-details"' in script
    assert "查看具体规则" in script
    assert 'class="learning-review-actions"' in script
    assert ".application-overview" in css
    assert ".application-section-heading" in css
    assert ".learning-review-details" in css


def test_outline_workspace_uses_plain_language_and_visible_operation_states(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        "outline-workspace", "outline-current", "outline-generate-form",
        "outline-operation-status", "outline-candidates", "outline-editor",
        "outline-comparison", "outline-history",
    ):
        assert f'id="{control}"' in html
    for label in (
        "不会修改已经写好的正文", "查看并编辑全文", "比较变化",
        "应用勾选的变化", "整体采用这个版本", "请模型判断",
        "恢复这个版本", "正在生成候选大纲", "生成失败",
        "按当前大纲创建新作品", "新作品重新生成人物和设定",
        "原作品、原资料和运行记录都会保留",
    ):
        assert label in html + script
    assert 'id="outline-candidate-form"' not in html
    assert "loadOutlineWorkspace" in script
    assert "renderOutlineWorkspace" in script
    assert "setOutlineOperationStatus" in script
    assert "createProjectFromCurrentOutline" in script
    assert ".outline-operation-status.busy" in css
    assert ".outline-change-list" in css
    assert ".outline-generate-form,.outline-layout,.outline-canon-item { grid-template-columns:1fr" in css
    assert 'id="wizard-confirmed-methods"' in html
    assert "可选：带入已确认写法" in html
    assert "只有最终勾选的写法才会用于新作品" in html
    assert "loadWizardConfirmedMethods" in script
    assert "selected_mechanism_ids" in script


def test_reference_wizard_groups_methods_and_enforces_explicit_twelve_limit(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'id="wizard-method-count"' in html
    assert 'id="wizard-method-selection-status"' in html
    assert "已选 0/12 条写法" in html
    for phrase in (
        "一次最多带入 12 条写法，可以取消一条后再选。",
        "请明确选择最多 12 条",
    ):
        assert phrase in script

    renderer = script.split("function renderWizardConfirmedMethods", 1)[1].split(
        "function updateMarketBaselineWizardState", 1,
    )[0]
    assert "item.source_id" in renderer
    assert "item.source_title" in renderer
    assert 'class="wizard-method-group"' in renderer
    assert "<details" in renderer
    assert "state.selectedWizardMethods.size" in renderer
    assert "input.disabled=atLimit&&!input.checked" in renderer
    assert ".slice(" not in renderer

    loader = script.split("async function loadWizardConfirmedMethods", 1)[1].split(
        "function renderWizardConfirmedMethods", 1,
    )[0]
    assert "methods.length<=12" in loader
    assert "new Set(methods.map(item=>item.id))" in loader
    assert "读取写法失败，请稍后重试。" in loader
    assert "error.message" not in loader

    creation = script.split("async function startWizardFromReference", 1)[1].split(
        '$("#start-wizard")', 1,
    )[0]
    assert "selectedWizardMethods=new Set(confirmedFromSources)" not in creation
    assert "selectedWizardMethods=new Set()" in creation
    draft_resume = script.split(
        '$("#wizard-drafts").addEventListener("change"', 1,
    )[1].split('$("#wizard-back")', 1)[0]
    assert "creation_context?.reference_source_ids?.[0]" in draft_resume
    assert 'item.use||"用于后续创作安排"' in renderer
    assert ".wizard-method-group" in css
    assert ".wizard-method-selection" in css
    assert "overflow-wrap:anywhere" in css


def test_reference_created_outline_failure_keeps_project_and_offers_retry_path(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'id="outline-generate-form"' in html
    assert 'tabindex="-1"' in html
    assert "作品已经创建，可以稍后重试" in script
    assert "前往作品应用重新生成" in script
    assert "openProjectOutlineGenerator" in script
    helper = script.split("async function openProjectOutlineGenerator", 1)[1].split(
        "async function generateInitialOutline", 1,
    )[0]
    for call in (
        'await navigateToView("learning")',
        'switchLearningView("application")',
        "select.value=projectId",
        "await loadProjectLearning()",
        "form.focus",
    ):
        assert call in helper
    assert helper.index('await navigateToView("learning")') < helper.index(
        'switchLearningView("application")'
    ) < helper.index("select.value=projectId") < helper.index(
        "await loadProjectLearning()"
    ) < helper.index("form.focus")

    generation = script.split("async function generateInitialOutline", 1)[1].split(
        "function clearConfirmedWizard", 1,
    )[0]
    assert "error.message" not in generation
    assert "showInitialOutlineFailure(projectId)" in generation
    manual_generation = script.split(
        '$("#outline-generate-form").addEventListener("submit"', 1,
    )[1].split('$("#outline-save")', 1)[0]
    assert "error.message" in manual_generation
    assert 'error.code==="outline_generation_not_ready"' in manual_generation
    assert "现有作品、大纲和正文不会改变" in manual_generation
    assert "候选已经保存，但页面没有刷新" in manual_generation
    assert "不需要重新生成" in manual_generation

    confirmation = script.split(
        '$("#wizard-confirm").addEventListener("click"', 1,
    )[1].split("async function run", 1)[0]
    assert confirmation.index("clearConfirmedWizard") < confirmation.index(
        "await refreshProjectsAfterConfirmation"
    ) < confirmation.index("await generateInitialOutline")
    assert "new Map" in script.split(
        "async function refreshProjectsAfterConfirmation", 1,
    )[1].split("async function openProjectOutlineGenerator", 1)[0]
    assert "wizardSelectionErrorMessage(error)" in confirmation
    assert 'setWizardMethodSelectionStatus(message,"error")' in confirmation
    assert "error.message" not in confirmation
    assert "/initialize-skills" not in confirmation
    assert "monitorRun(" not in confirmation
    assert "作品已创建，请先确认正式大纲" in confirmation
    safe_error = script.split("function wizardSelectionErrorMessage", 1)[1].split(
        "async function startWizardFromReference", 1,
    )[0]
    assert "invalid_learning_selection" in safe_error
    assert "作品创建没有完成，请稍后重试。" in safe_error
    assert "!/[A-Za-z]/.test(message)" in safe_error
    assert ".outline-retry-action" in css
    assert "animation:" not in css.split(".outline-retry-action", 1)[1].split(
        "\n", 1,
    )[0]


def test_workbench_is_task_first_and_keeps_old_tools_in_details(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        "workbench-current-project",
        "workbench-current-stage",
        "workbench-priority-issues",
        "workbench-primary-action",
        "workbench-new-project",
        "workbench-details",
    ):
        assert f'id="{control}"' in html
    for label in (
        "从样本开始",
        "继续初始化",
        "查看当前进度",
        "从失败项继续",
        "生成完整短篇",
        "修复已选问题",
        "继续确认修改",
        "设为正式稿",
        "准备投稿",
        "查看稿件质量",
    ):
        assert label in script
    assert "<summary>查看详细信息</summary>" in html
    details = html.split('id="workbench-details"', 1)[1].split("</details>", 1)[0]
    for old_control in (
        "project-summary",
        "project-locations",
        "candidate-quality",
        "writing-rules-summary",
        "platform-profile-panel",
        "initialize-project",
        "run-short",
        "run-list",
        "project-list",
        "manuscript-panel",
    ):
        assert f'id="{old_control}"' in details
        assert html.count(f'id="{old_control}"') == 1
    assert ".workbench-task-summary" in css
    assert ".workbench-primary-action" in css
    assert "正在处理的作品" in html
    assert "开始新作品" in html
    assert "从样本开始" in script
    assert 'action==="references"' in script


def test_run_context_explains_confirmed_inputs_and_retained_initialization_files(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    assert "本阶段参考" in script
    assert "confirmed_context" in script
    assert '["stage_completed","skill_completed"]' in script
    assert '["skills_loaded","learning_context_loaded"]' in script
    assert "失败前生成的资料已经保留" in script
    assert "正式人物、设定和剧情资料没有被修改" in script
    assert "proposal_summary" in script


def test_workbench_task_priority_is_deterministic_and_shows_at_most_three_issues(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    decision = script.split("function deriveWorkbenchTaskState", 1)[1].split(
        "function renderWorkbenchTaskState", 1,
    )[0]

    for branch in (
        "!snapshot.project",
        "!snapshot.hasFormalOutline&&!activeRun",
        "!snapshot.initialized&&!activeRun",
        "if(activeRun)",
        "resumableRevision",
        'snapshot.candidateLoadState==="missing"',
        "hasBlockingIssues",
        "snapshot.revisionRun?.status",
        "snapshot.canSetFormal&&!snapshot.formalMatchesCandidate",
        "snapshot.publicationPreview?.ready",
    ):
        assert branch in decision
    assert decision.index("if(activeRun)") < decision.index("if(resumableRevision)")
    assert decision.index("!snapshot.hasFormalOutline&&!activeRun") < decision.index(
        "!snapshot.initialized&&!activeRun"
    )
    assert decision.index("if(resumableRevision)") < decision.index(
        'snapshot.candidateLoadState==="missing"'
    )
    assert decision.index("if(hasBlockingIssues") < decision.index(
        "snapshot.publicationPreview?.ready"
    )
    assert "issues.slice(0,3)" in decision.replace(" ", "")
    assert 'snapshot.project?.mode==="short"' in decision
    loading_branch = decision.split(
        'if(snapshot.candidateLoadState==="loading")', 1,
    )[1].split(";", 1)[0]
    assert 'kind:"quality"' in loading_branch
    assert 'kind:"generate-short"' not in loading_branch
    error_branch = decision.split(
        'if(snapshot.candidateLoadState==="error")', 1,
    )[1].split(";", 1)[0]
    assert 'kind:"reload"' in error_branch


def test_workbench_async_state_is_project_scoped_and_candidate_load_is_explicit(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    assert "candidateLoadState:" in script
    for status in ('"loading"', '"available"', '"missing"', '"error"'):
        assert status in script
    assert "workbenchRuns:" in script
    assert "workbenchGeneration:" in script
    assert "activeRunProjectId:" in script
    assert "runMonitorGeneration:" in script
    assert "function workbenchContextMatches" in script
    render = script.split("async function renderActiveProject", 1)[1].split(
        '$("#active-project")', 1,
    )[0]
    assert "const generation=++state.workbenchGeneration" in render
    assert "workbenchContextMatches(projectId,generation)" in render
    assert "state.workbenchRuns=runs" in render
    assert "state.workbenchOutline=results[6]" in render
    assert "!hasFormalOutline || initialized || initializing" in render
    monitor = script.split("async function monitorRun", 1)[1].split(
        '$("#initialize-project")', 1,
    )[0]
    assert "activeRunProjectId" in monitor
    assert "runMonitorGeneration" in monitor
    assert "workbenchContextMatches(projectId,workbenchGeneration)" in monitor
    starter = script.split("async function run(path, body)", 1)[1].split(
        "function renderRunLog", 1,
    )[0]
    assert "const projectId=state.activeProject.id" in starter
    assert "workbenchContextMatches(projectId,workbenchGeneration)" in starter
    assert "catch(error)" in starter
    assert "任务没有启动：${message}" in starter
    assert "toast(message)" in starter
    assert "renderProjects();" not in script.split(
        "async function continueProject", 1,
    )[1].split("async function loadProjectLocations", 1)[0]


def test_console_explains_polish_recovery_in_plain_chinese(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    for event_type in (
        "polish_compact_retry",
        "polish_compact_fallback",
        "polish_input_compact_retry",
        "polish_output_limit_retry",
        "polish_transport_retry",
        "polish_configured_fallback",
        "polish_segment_split",
        "polish_targeted_repair",
        "polish_style_allowance",
        "polish_capacity_preserved",
        "polish_segment_preserved",
        "polish_segment_progress",
    ):
        assert event_type in script
    for label in (
        "正在精简要求后重新润色本段",
        "首选模型没有返回正文，正在使用备用模型",
        "输入超出当前模型上下文，正在保留叙事权威后压缩建议重试",
        "供应商截断了本段输出，正在同一路由扩大输出空间重试",
        "润色请求遇到网络波动，正在同一路由重试",
        "本段出现有证据的局部问题，正在进行小范围定向修复",
        "本段局部节奏符合项目文风规则，已通过验收",
        "本段未完成精修，已保留原文并继续",
        "继续运行时只处理未完成片段",
    ):
        assert label in script
    assert "已完成 ${completed} / ${total} 段，其中 ${preserved} 段保留原文" in script


def test_console_polish_run_progress_stops_busy_and_polling_at_terminal_statuses(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    active_status = script.split("const isActiveRunStatus", 1)[1].split(";", 1)[0]
    assert '["queued","running","cancelling"].includes(status)' in active_status
    for terminal in ("completed", "failed", "cancelled", "interrupted"):
        assert terminal not in active_status

    show_detail = script.split("function showRunDetail", 1)[1].split(
        "async function monitorRun", 1,
    )[0]
    monitor = script.split("async function monitorRun", 1)[1].split(
        '$("#run-cancel").addEventListener', 1,
    )[0]
    assert "const active=isActiveRunStatus(detail.status)" in show_detail
    assert "const active=isActiveRunStatus(detail.status)" in monitor
    assert "polishRunProgress(detail.events || [],detail.status)" in show_detail
    assert "polishRunProgress(detail.events || [],detail.status)" in monitor
    assert "if (active) state.pollTimer=setTimeout(poll,900)" in monitor

    progress = script.split("function polishRunProgress", 1)[1].split(
        "function polishRunEventMessage", 1,
    )[0]
    assert progress.startswith("(events,status)")
    assert "if(isActiveRunStatus(status)" in progress
    assert '["failed","cancelled","interrupted"].includes(status)' in progress
    assert 'resumable&&preserved>0' in progress


def test_console_validates_polish_progress_and_hides_internal_events(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    validation = script.split("function polishProgressMetadata", 1)[1].split(
        "function polishRunProgress", 1,
    )[0]
    assert "Number.isFinite" in validation
    for invalid in ("completed<0", "total<=0", "preserved<0", "completed>total"):
        assert invalid in validation

    event_message = script.split("function polishRunEventMessage", 1)[1].split(
        "function renderRunLog", 1,
    )[0]
    assert "polishProgressMetadata(item)" in event_message
    assert "readableRunMessage(item.message)" in event_message

    hidden = script.split("const hiddenRunEventTypes", 1)[1].split(";", 1)[0]
    for event_type in (
        "polish_segment_route",
        "polish_circuit_opened",
        "polish_max_tokens_retry",
    ):
        assert event_type in hidden
    run_log = script.split("function renderRunLog", 1)[1].split(
        "function renderRunContext", 1,
    )[0]
    assert ".filter(item=>!hiddenRunEventTypes.has(item.event_type))" in run_log
    assert "escapeHtml(polishRunEventMessage(item))" in run_log
    assert "runEventDetails(item)" in run_log
    details = script.split("function runEventDetails", 1)[1].split(
        "function renderRunLog", 1,
    )[0]
    for diagnostic in (
        "metadata.issues", "metadata.repair_attempt", "metadata.context_layers",
        "metadata.preserved_segments", "metadata.restart_segment",
    ):
        assert diagnostic in details
    assert 'class="log-details"' in run_log
    assert 'items[index-1].severity!=="error"' in run_log
    assert "Skill completed without file proposals" in script
    assert "再次初始化只会继续未完成阶段" in script
    assert '"character-management":"人物资料"' in script
    assert "本次参考的文笔和创作方法" in script
    assert "正式大纲和已确认设定优先，不会在这里被改写" in script
    show_detail = script.split("function showRunDetail", 1)[1].split(
        "async function monitorRun", 1,
    )[0]
    monitor = script.split("async function monitorRun", 1)[1].split(
        '$("#run-cancel").addEventListener', 1,
    )[0]
    assert '.textContent=progress?' in show_detail
    assert '.textContent=progress?' in monitor


def test_wizard_draft_controls_are_plain_and_delete_only_unfinished_drafts(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in ("continue-wizard-draft", "delete-wizard-draft", "wizard-draft-status"):
        assert f'id="{control}"' in html
    assert "只删除这份未完成的开书资料，不会删除任何作品。" in script
    assert "wizard_not_found" in script and "wizard_has_project" in script
    assert '["draft", "gathering_input", "ready"].includes(item.status)' in script
    assert "!item.project_id" in script
    assert "result?.id!==wizardId" in script
    assert ".wizard-draft-picker" in css


def test_legacy_outline_does_not_render_as_numbered_old_version(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    assert "旧项目已有版本" in script
    assert 'current.outline_version||"旧"' not in script


def test_learning_candidates_explain_local_and_model_sources_in_chinese(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for label in (
        "本地提炼", "模型新增", "本地发现 + 模型确认", "本地与模型意见不同",
        "等待模型判断", "模型全文分析", "综合判断", "来源资料",
    ):
        assert label in html + script
    assert 'id="learning-mechanism-origin"' in html
    assert "mechanismSourceMeta" in script
    assert "readableModelText" in script
    assert "模型返回的旧结果没有完成中文化" in script
    assert ".mechanism-source-badges" in css
    assert ".reference-analysis-guide" in css
    assert "const listValue=value=>Array.isArray(value)" in script
    assert "listValue(item.data.applicable_modes).map" in script
    for label in (
        "从优秀样本学到的表达方式", "确认这条文笔", "加入当前作品",
        "什么时候适合用", "不要怎么用", "文笔和剧情写法分开显示",
    ):
        assert label in script or label in html
    assert "/api/learning/style-candidates?view=all" in script
    assert "/learning/style-candidates/${id}" in script
    assert ".style-candidate-section" in css
    for label in (
        "当前基础文笔", "作品基础方向", "系统默认规则",
        "从样本确认并加入的规则", "系统默认文笔 · 尚未加入样本规则",
    ):
        assert label in script
    assert ".prose-baseline-overview" in css
    for old_label in (
        "LOCAL WRITING SYSTEM", "LOCAL MARKET INTELLIGENCE", "SKILL-DRIVEN SETUP",
        "PLANNING MODEL", "MODEL ROUTING", "EXECUTION GATES", "RECOVERABLE PROJECTS",
        "MARKET LINK", "MARKET MATCH", "CORE REQUIREMENTS",
    ):
        assert old_label not in html + script


def test_reference_model_analysis_explains_resumed_windows(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    assert "已复用" in script
    assert "正在分析第" in script
    assert "再次运行会复用已经完成的窗口" in script


def test_learning_rules_are_visible_removable_and_recoverable(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for label in (
        "本次创作会使用什么", "从当前作品移除", "查看和恢复旧版本",
        "恢复这个版本", "没有发现明确冲突", "检查已有正文是否体现补充写法",
        "什么时候适合使用", "具体怎么使用", "来源资料",
    ):
        assert label in html + script
    assert 'id="learning-effective-rules"' in html
    assert 'id="wizard-auto-outline"' in html
    assert "effectiveRulesMarkup" in script
    assert "loadArtifactHistory" in script
    assert "removeAdoption" in script
    assert 'escapeHtml(item.title||"需要确认的写法")' in script
    assert ".effective-rule-warning-item" in css
    assert ".effective-rule-layers" in css
    assert ".blueprint-rule-row" in css
    assert "准备建立第一版正式大纲" in script
    assert "设为第一版正式大纲" in script
    assert "整体采用后，这份候选会成为第一版正式大纲" in script


def test_outline_generation_explains_missing_methods_and_saved_refresh_failure(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    for label in (
        "还不能生成大纲",
        "去选择写法",
        "候选已经保存，但页面没有刷新",
        "不需要重新生成，请重新读取候选列表",
        "重新读取",
    ):
        assert label in script
    assert "catch(error)" in script
    assert 'state.activeOutlineCandidateId=created?.id||null' in script
    assert 'error.code==="outline_generation_not_ready"' in script


def test_outline_comparison_keeps_market_reference_short_and_folded(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    market_markup = script.split("function outlineMarketReferenceMarkup", 1)[1].split(
        "function renderOutlineComparison", 1,
    )[0]
    assert "同类市场参考" in market_markup
    assert "市场数据只供参考，不影响候选大纲的应用" in market_markup
    assert "<details>" in market_markup
    assert "<details open" not in market_markup
    assert "outline-market-reference" in css


def test_candidate_quality_is_one_plain_chinese_progressive_workspace(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        "candidate-quality", "candidate-operation-status", "publish-candidate",
    ):
        assert f'id="{control}"' in html
    for label in (
        "稿件质量与发布", "最需要处理的问题", "查看本地扫描",
        "查看详细评分", "评分参考组", "查看完整正文与保护片段",
        "下一步", "终审模型",
    ):
        assert label in html + script
    for phrase in (
        "系统只会推荐，确认后才用于人工评分校准",
        "当前可推荐资料还缺", "不影响终审",
        "一个字也不改", "尽量不改文字", "下次修改可变动一次",
        "为什么现在不能设为正式稿",
        "正在设为正式稿", "正式稿已更新", "设为正式稿失败",
        "当前还不能生成投稿包",
        "页面已更新",
    ):
        assert phrase in script
    assert "renderCandidateQualityWorkspace" in script
    assert "loadCandidateQualityControls" in script
    assert "protectSelectedCandidatePassage" in script
    assert "/quality-references/recommendations" in script
    assert "/passage-protections" in script
    assert "publish.disabled" in script
    assert "publicationPreview?.ready" in script
    assert ".candidate-quality-workspace" in css
    assert ".quality-score-strip" in css
    assert ".quality-manuscript-preview" in css
    assert ".quality-reference-list" in css
    assert "@media (max-width:800px)" in css


def test_revision_workspace_has_plain_chinese_controls(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text

    for control in (
        "quality-revision-template", "quality-revision-workspace",
        "revision-issue-selection", "revision-operation-status",
        "revision-group-results",
    ):
        assert f'id="{control}"' in html
    for label in (
        "修复已选问题", "正在确认修改位置", "正在修改第",
        "正在检查是否影响其他剧情", "正在进行局部复核或全文复核",
        "采用这组修改", "拒绝这组修改", "保留原写法",
        "修改前", "修改后", "查看检查详情",
    ):
        assert label in script
    for forbidden in ("RAG", "补丁事务", "状态图", "哈希"):
        assert forbidden not in html
    assert "/revisions`" in script
    assert "/revision/groups/${encodeURIComponent(groupId)}/" in script
    assert "/revision/finalize" in script


def test_revision_progress_keeps_failure_and_next_action_visible(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for label in (
        "已保留当前最佳稿", "可以从失败的问题继续", "继续这次返修",
        "需要全文复核", "只复核改动及关联位置", "本地检查没有通过",
        "等待你确认", "需要人工处理", "意外中断，可继续",
    ):
        assert label in script
    assert "revisionSafeError" in script
    assert "revisionReasonLabel" in script
    assert '}[run.status] || run.status' not in script
    assert "clearTimeout(state.revisionPollTimer)" in script
    assert ".revision-comparison" in css
    assert ".revision-progress.complete" in css
    assert "grid-template-columns:1fr" in css


def test_revision_local_gate_lists_plain_reasons_without_false_resume(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    actions = script.split("function revisionActionsMarkup", 1)[1].split(
        "function renderRevisionWorkspace", 1,
    )[0]
    assert actions.index('detail.status==="waiting_local_fix"') < actions.index(
        '["failed","cancelled","interrupted"]'
    )
    assert "这次任务不能直接续跑" in actions
    assert "返回问题清单" in actions
    assert "data-revision-return" in actions
    for label in (
        "本地分析没有覆盖全文", "受保护片段被改动",
        "本地扫描仍发现必须处理的文字问题",
        "正文有效字数低于当前作品下限",
    ):
        assert label in script
    revision_handlers = script.split("async function startTargetedRevision", 1)[1].split(
        "function qualityCriteriaMarkup", 1,
    )[0]
    assert "error.message" not in revision_handlers


def test_revision_progress_distinguishes_stopped_from_success(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    progress = script.split("function setRevisionOperationStatus", 1)[1].split(
        "function revisionPhase", 1,
    )[0]
    assert 'const success=kind==="success"&&settled' in progress
    assert 'success&&step===phase?"done"' in progress
    assert 'settled?"settled":""' in progress
    assert 'kind==="error"?"failed":"waiting"' in progress
    assert ".revision-progress.settled li.active > span" in css
    assert ".revision-progress.failed li.active > span" in css


def test_revision_async_updates_stay_with_their_project_and_run(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text
    handlers = script.split("async function startTargetedRevision", 1)[1].split(
        "function qualityCriteriaMarkup", 1,
    )[0]

    assert "function revisionContextMatches" in script
    assert handlers.count("revisionContextMatches(projectId,runId)") >= 8
    assert "state.revisionFinalizing=true" in handlers
    assert "if(state.revisionFinalizing)return" in handlers
    assert "state.revisionFinalizing=false" in handlers
    assert 'data-revision-finalize disabled' in script
    assert 'button.textContent="检查已确认的修改"' in handlers
    assert 'revisionRefreshGeneration:0' in script
    refresh = handlers.split("async function refreshRevisionRun", 1)[1].split(
        "async function decideRevisionGroup", 1,
    )[0]
    assert "generation=state.revisionRefreshGeneration" in refresh
    assert refresh.count("revisionContextMatches(projectId,runId,generation)") >= 4
    assert "refreshRevisionRun(runId,true,projectId,generation)" in refresh
    assert "const generation=++state.revisionRefreshGeneration" in handlers
    assert "state.revisionRefreshGeneration+=1" in handlers
    assert '"正在保存你的决定，正文和最佳稿暂时不会改变。",5,false' in handlers
    assert script.count("stopRunMonitor();resetRevisionWorkspace();") >= 2
    finalize_catch = handlers.split("async function finalizeTargetedRevision", 1)[1].split(
        "}finally{", 1,
    )[0].split("}catch(error){", 1)[1]
    assert finalize_catch.index("await refreshRevisionRun") < finalize_catch.index(
        'if(state.revisionRun?.status==="completed"){'
    ) < finalize_catch.index(
        'setRevisionOperationStatus("error","终审没有完成"'
    )
    assert "state.revisionFinalizing=false;renderRevisionWorkspace(state.revisionRun,state.revisionReport);return;" in finalize_catch


def test_revision_workspace_requires_enabled_short_project_and_local_fix_can_restart(
    tmp_path,
) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    script = client.get("/static/app.js").text

    assert "function revisionWorkspaceEnabled" in script
    assert 'project?.mode==="short"' in script
    assert "project?.optimized_local_review_enabled===true" in script
    assert "project?.metadata?.optimized_local_review_enabled===true" in script
    assert "if(!revisionWorkspaceEnabled(project))" in script
    assert '["completed","waiting_local_fix"].includes(run.status)' in script
    assert "qualityReadOnlyIssuesMarkup" in script
