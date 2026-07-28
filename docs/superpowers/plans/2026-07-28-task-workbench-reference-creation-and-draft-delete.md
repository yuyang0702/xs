# Task Workbench, Reference Creation, And Wizard Draft Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing console into a four-group, task-first workspace; let users create a project and an original outline candidate from several confirmed references; and let users safely delete unfinished creation wizards.

**Architecture:** Keep the current single-page views, project store, learning library, outline workflow, run manager, and StoryState authoritative. Add only one backend operation (`DELETE /api/wizards/{id}`), extend wizard creation with a source-scoped context stored in the existing wizard schema JSON, and compose the task homepage from existing project, run, candidate-quality, publication, and safe-revision state. No second project, outline, draft, or manuscript state is introduced.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, vanilla JavaScript, HTML, CSS.

## Global Constraints

- Preserve all existing projects, credentials, model bindings, Skills, references, learning nodes, outline candidates, run history, protected-best manuscripts, and formal manuscripts.
- Do not add a database table or migration for reference-scoped wizards; store `reference_source_ids` under the existing `schema_json["creation_context"]` object.
- Only `reference_work` and `popular_sample` sources may enter reference-based creation. Reject `competitor_work`, `platform_rule`, and `writing_tutorial` with a Chinese explanation.
- Never send source reference prose to the planning model. Planning receives only project requirements, user-confirmed transferable mechanisms, market advice, and the user's brief.
- Keep ordinary self-directed creation compatible: without `reference_source_ids`, the wizard continues to recommend only the first 12 globally confirmed safe mechanisms.
- A reference-scoped wizard exposes every confirmed mechanism from its selected sources, but the final confirmation accepts at most 12 unique mechanism IDs and never truncates silently.
- Do not call paid model APIs from tests. Use local learning and fake gateways for outline generation tests.
- New async UI operations must have a visible terminal state: `正在准备`, `正在处理`, `已完成`, or `失败`. A completed or failed operation must stop animating.
- All new user-facing labels, error messages, recovery instructions, and progress descriptions are plain Chinese. Internal codes and provider exception text stay out of the page.
- Keep the safe targeted-revision implementation in its own companion plan. This plan consumes its public task state and actions; it does not duplicate revision logic on the homepage.
- Each task below is committed separately during implementation. This planning task itself does not commit or push anything.

---

### Task 1: Add Safe Backend Deletion For Unfinished Wizard Drafts

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/wizard.py`
- Modify: `src/novel_flywheel/api/wizards.py`
- Test: `tests/test_db.py`
- Test: `tests/test_wizard.py`
- Test: `tests/api/test_wizards.py`

**Consumes:** Existing `wizard_sessions`, `wizard_interview_messages`, `Database.get_wizard()`, and `WizardService.get()`.

**Produces:** `Database.delete_wizard(wizard_id) -> bool`, `WizardService.delete(wizard_id) -> dict`, and `DELETE /api/wizards/{wizard_id}`.

- [ ] Add database tests proving an existing wizard is deleted, its interview messages are removed by the existing `ON DELETE CASCADE`, and a missing ID returns `False`:

```python
def test_delete_wizard_cascades_interview_messages(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("draft-1", "draft", "short", {"steps": []}, {})
    db.save_interview_message(
        "message-1", "draft-1", "assistant", "先确定主角目标。", [],
    )

    assert db.delete_wizard("draft-1") is True
    assert db.get_wizard("draft-1") is None
    assert db.list_interview_messages("draft-1") == []
    assert db.delete_wizard("draft-1") is False
```

- [ ] Add service tests proving only unfinished, project-less wizards may be deleted:

```python
def test_wizard_service_deletes_only_unfinished_projectless_draft(tmp_path) -> None:
    service = wizard_service_for(tmp_path)
    draft = service.create("short")

    deleted = service.delete(draft["id"])

    assert deleted == {"id": draft["id"], "deleted": True}
    with pytest.raises(LookupError, match="Wizard not found"):
        service.get(draft["id"])


def test_wizard_service_refuses_completed_or_project_linked_wizard(tmp_path) -> None:
    service = wizard_service_for(tmp_path)
    draft = service.create("short")
    service.db.save_wizard(
        draft["id"], "completed", "short", draft["schema"], draft["answers"],
        project_id="project-1",
    )

    with pytest.raises(ValueError, match="已经创建作品"):
        service.delete(draft["id"])
```

- [ ] Add API tests for success, missing wizard, and conflict. Assert Chinese messages and verify the project count and unrelated wizard count do not change:

```python
def test_delete_unfinished_wizard_api_does_not_delete_projects(tmp_path) -> None:
    client = wizard_client(tmp_path)
    keep = client.post("/api/wizards", json={"mode": "long"}).json()
    removed = client.post("/api/wizards", json={"mode": "short"}).json()

    response = client.delete(f"/api/wizards/{removed['id']}")

    assert response.status_code == 200
    assert response.json() == {"id": removed["id"], "deleted": True}
    assert [item["id"] for item in client.get("/api/wizards").json()] == [keep["id"]]


def test_delete_completed_wizard_api_returns_chinese_conflict(tmp_path) -> None:
    client = wizard_client(tmp_path)
    wizard, project = create_completed_wizard(client)

    response = client.delete(f"/api/wizards/{wizard['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "wizard_has_project",
        "message": "这份开书资料已经创建作品，不能从草稿列表删除。",
    }
    assert client.get(f"/api/projects/{project['id']}").status_code == 200
```

- [ ] Run `pytest tests/test_db.py tests/test_wizard.py tests/api/test_wizards.py -q` and confirm the deletion tests fail because the methods and route do not exist.
- [ ] Implement `Database.delete_wizard()` as one parameterized `DELETE` inside `with self.connect() as connection`, returning `cursor.rowcount == 1`. Do not manually delete interview rows.
- [ ] Implement `WizardService.delete()` by loading the wizard first, raising `LookupError` when absent, raising `ValueError("这份开书资料已经创建作品，不能从草稿列表删除。")` when `project_id` exists or status is `completed`, and then deleting it.
- [ ] Add `DELETE /api/wizards/{wizard_id}`. Map absence to HTTP 404 with `wizard_not_found` and `草稿不存在或已经删除。`; map the completed/project-linked case to HTTP 409 with `wizard_has_project`.
- [ ] Run `pytest tests/test_db.py tests/test_wizard.py tests/api/test_wizards.py -q` and confirm all focused tests pass.
- [ ] Commit with `git add src/novel_flywheel/db.py src/novel_flywheel/wizard.py src/novel_flywheel/api/wizards.py tests/test_db.py tests/test_wizard.py tests/api/test_wizards.py && git commit -m "feat: allow deleting unfinished wizard drafts"`.

---

### Task 2: Scope Wizard Learning Choices To Several Selected References

**Files:**
- Modify: `src/novel_flywheel/api/wizards.py`
- Modify: `src/novel_flywheel/wizard.py`
- Test: `tests/test_wizard.py`
- Test: `tests/api/test_wizards.py`

**Consumes:** `POST /api/wizards`, the existing reference library, confirmed learning mechanisms, and `WizardService.create()`.

**Produces:** Optional `WizardCreate.reference_source_ids`, persisted `schema.creation_context.reference_source_ids`, source-grouped mechanism choices, and source-aware confirmation validation.

- [ ] Add a service persistence test:

```python
def test_wizard_persists_reference_creation_context_in_schema(tmp_path) -> None:
    service = wizard_service_for(tmp_path)

    wizard = service.create("short", reference_source_ids=["source-b", "source-a", "source-b"])

    assert wizard["schema"]["creation_context"] == {
        "reference_source_ids": ["source-b", "source-a"],
    }
```

- [ ] Add API tests that create two allowed sources and one rejected source, confirm mechanisms for each, and verify a scoped wizard returns all mechanisms only from the two selected sources with grouping metadata:

```python
def test_scoped_wizard_lists_all_confirmed_methods_from_selected_sources(tmp_path) -> None:
    client = wizard_client(tmp_path)
    first, first_nodes = confirmed_source(client, "第一篇", "reference_work", count=8)
    second, second_nodes = confirmed_source(client, "第二篇", "popular_sample", count=7)
    ignored, ignored_nodes = confirmed_source(client, "教程", "writing_tutorial", count=1)

    wizard = client.post("/api/wizards", json={
        "mode": "short",
        "reference_source_ids": [first["id"], second["id"]],
    }).json()
    choices = client.get(f"/api/wizards/{wizard['id']}/confirmed-mechanisms").json()

    assert {item["id"] for item in choices} == {
        *(node["id"] for node in first_nodes),
        *(node["id"] for node in second_nodes),
    }
    assert {item["source_id"] for item in choices} == {first["id"], second["id"]}
    assert {item["source_title"] for item in choices} == {"第一篇", "第二篇"}
    assert ignored_nodes[0]["id"] not in {item["id"] for item in choices}
```

- [ ] Add validation tests for an invalid content type, a missing source, a selected source with no confirmed mechanism, 13 selected mechanisms, and a mechanism outside the scoped sources. Use these exact public error codes and Chinese messages:

```python
@pytest.mark.parametrize(
    ("payload", "code", "message"),
    [
        ({"reference_source_ids": ["missing"]}, "reference_not_found", "有一篇所选资料不存在，请重新选择。"),
        ({"reference_source_ids": ["tutorial"]}, "reference_type_not_supported", "所选资料不能用于创建作品，请选择参考作品或爆款样本。"),
    ],
)
def test_wizard_rejects_invalid_reference_creation_sources(
    tmp_path, payload, code, message,
) -> None:
    client = prepared_reference_client(tmp_path)
    response = client.post("/api/wizards", json={"mode": "short", **payload})
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": code, "message": message}
```

- [ ] Add a compatibility test proving a wizard without sources still returns no more than the first 12 globally safe confirmed mechanisms.
- [ ] Run `pytest tests/test_wizard.py tests/api/test_wizards.py -q` and confirm the new scope and validation tests fail.
- [ ] Extend `WizardCreate` with `reference_source_ids: list[str] = []`. Normalize it with order-preserving de-duplication and reject unsupported or missing references before creating the wizard.
- [ ] Extend `WizardService.create(mode, skill_names=None, reference_source_ids=None)` and place the normalized list in `schema["creation_context"]`; do not add a table column.
- [ ] Replace `_confirmed_mechanisms(request)` with `_confirmed_mechanisms(request, wizard)`. When the wizard has scoped source IDs, return every valid confirmed mechanism from those sources and include `source_id` and `source_title`. When no scope exists, preserve the global limit of 12.
- [ ] At confirmation, derive allowed mechanism IDs from the wizard's source scope. Reject more than 12 unique IDs with `invalid_learning_selection`; reject out-of-scope or stale IDs instead of silently dropping them. Confirm that each scoped source has at least one confirmed mechanism before project creation.
- [ ] Run `pytest tests/test_wizard.py tests/api/test_wizards.py -q` and confirm the focused suite passes.
- [ ] Commit with `git add src/novel_flywheel/api/wizards.py src/novel_flywheel/wizard.py tests/test_wizard.py tests/api/test_wizards.py && git commit -m "feat: scope creation wizard to selected references"`.

---

### Task 3: Add Stable Multi-Selection And Local Readiness Checks To The Learning Library

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Consumes:** `GET /api/references`, `POST /api/references/{id}/learn`, `GET /api/learning/mechanisms`, and the extended `POST /api/wizards`.

**Produces:** Persistent in-page reference selection, a readiness summary, one shared reference-to-wizard entry point, and plain-Chinese recovery states.

- [ ] Add console contract tests before changing the markup:

```python
def test_learning_library_supports_multi_reference_creation_with_readable_states(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        'id="reference-selection-status"',
        'id="create-from-selected-references"',
        'data-reference-select',
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
    assert "selectedReferenceIds:new Set()" in script.replace(" ", "")
    assert "reference_work" in script and "popular_sample" in script
    assert ".reference-selection-bar" in css
    assert ".reference-select-control" in css
```

- [ ] Run `pytest tests/test_console.py -q` and confirm the controls and status copy are absent.
- [ ] Add `state.selectedReferenceIds = new Set()` and render one checkbox per eligible reference row. Filtering, searching, pagination, and detail refresh must not clear this set; remove only IDs that no longer exist after `loadReferences()`.
- [ ] Add a compact sticky selection bar below the filters. It shows `已选择 N 篇资料`, `清除选择`, and the primary `用所选资料创建新作品` command. Disable the primary command at zero selections and while preparing.
- [ ] Keep unsupported source types visible in the library but omit or disable their selection checkbox with the tooltip `这类资料只用于查阅，不能直接创建作品`.
- [ ] Refactor `startWizardFromReference()` into one function accepting an ordered ID array. Keep the existing single-reference button by passing `[state.activeReference.id]` into the same function.
- [ ] Before creating a wizard, inspect `state.mechanisms` per selected source. For a source without any local learning nodes, call its existing local `POST /api/references/{id}/learn` exactly once; do not call model analysis.
- [ ] Reload mechanisms after preparation. If any selected source still has no confirmed mechanism, preserve the selection, switch to the candidate-writing view, list the affected source titles, and show `确认完成后，可以继续用刚才选择的资料创建作品。`
- [ ] When all sources are ready, create the wizard with `reference_source_ids`, keep the selection until the create response succeeds, then initialize `state.selectedWizardMethods` from confirmed mechanisms belonging to those sources.
- [ ] Give the status block a stable minimum height and terminal classes. `finally` must clear the busy state so a completed or failed action never leaves a moving progress indicator.
- [ ] Run `pytest tests/test_console.py -q` and confirm the complete console suite passes.
- [ ] Commit with `git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py && git commit -m "feat: create projects from selected references"`.

---

### Task 4: Group Wizard Mechanisms And Make Initial Outline Generation Recoverable

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`
- Test: `tests/api/test_wizards.py`
- Test: `tests/api/test_learning.py`

**Consumes:** Source-aware confirmed mechanisms, `POST /api/wizards/{id}/confirm`, project learning adoptions, and `POST /api/projects/{id}/learning/generate-outline`.

**Produces:** Source-grouped mechanism selection with a hard 12-item limit, an original-outline prompt without reference prose, and a visible retry path after outline failure.

- [ ] Add a backend integration test proving the confirmed project contains only explicitly selected confirmed mechanisms from the scoped sources and that selection order is preserved.
- [ ] Add a fake-gateway test proving outline generation uses the adopted mechanism and project brief but does not contain either source text:

```python
def test_reference_created_outline_prompt_excludes_source_prose(tmp_path) -> None:
    client = client_for(tmp_path)
    first = create_confirmed_reference(client, "第一篇", "绝不能发送的第一篇原文")
    second = create_confirmed_reference(client, "第二篇", "绝不能发送的第二篇原文")
    project_id = create_project_from_references(client, [first, second])

    class RecordingGateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return SimpleNamespace(
                text='{"title":"原创大纲","outline":"# 原创故事\\n\\n## 开头\\n陌生人带来坏消息。"}',
                receipt={"role": role},
            )

    gateway = RecordingGateway()
    client.app.state.outlines.gateway = gateway
    response = client.post(
        f"/api/projects/{project_id}/learning/generate-outline",
        json={"brief": "写一个全新的悬疑故事。"},
    )

    assert response.status_code == 201
    sent = "\n".join(str(part) for part in gateway.calls[0])
    assert "绝不能发送的第一篇原文" not in sent
    assert "绝不能发送的第二篇原文" not in sent
    assert "写一个全新的悬疑故事" in sent
```

- [ ] Add a failure test with a fake gateway that raises `RuntimeError("模型暂时不可用")`. Assert the project still exists, selected adoptions still exist, no formal outline is overwritten, and a later call with a successful fake gateway creates the candidate.
- [ ] Add console contract tests for `已选 N/12 条写法`, grouped source headings, disabling unchecked choices at 12, `作品已经创建，可以稍后重试`, and `前往作品应用重新生成`.
- [ ] Run `pytest tests/api/test_wizards.py tests/api/test_learning.py tests/test_console.py -q` and confirm the new grouping and recovery assertions fail.
- [ ] Render confirmed mechanisms in one `<details>` group per `source_id`, using `source_title` as the summary. Show a fixed count near the confirmation action; when 12 are selected, disable only the remaining unchecked boxes and explain `一次最多带入 12 条写法，可以取消一条后再选。`
- [ ] Never slice `selectedWizardMethods` in JavaScript. Submit the explicit selection and surface the backend validation message if stale data changed between loading and confirmation.
- [ ] Keep project confirmation and outline generation as separate operations. After project confirmation succeeds, clear the wizard and update the project list before starting outline generation.
- [ ] On outline failure, retain the project ID and adoptions, stop progress animation, render an error card with `作品已经创建，可以稍后重试`, and provide a button that opens `学习库 > 作品应用`, selects the project, and focuses the existing generate-outline form.
- [ ] Keep the existing outline view, edit, local comparison, semantic review, partial/whole apply, abandon, and history-restore flow unchanged.
- [ ] Run `pytest tests/api/test_wizards.py tests/api/test_learning.py tests/test_console.py -q` and confirm all focused tests pass without an external model call.
- [ ] Commit with `git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py tests/api/test_wizards.py tests/api/test_learning.py && git commit -m "feat: recover reference outline creation"`.

---

### Task 5: Replace Eight Flat Navigation Items With Four Stable Groups

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Consumes:** Existing `.view` sections and `showView(view, title)`.

**Produces:** Four primary groups, accessible secondary links to every old view, and correct parent-group highlighting on desktop and mobile.

- [ ] Add a failing console contract test:

```python
def test_console_navigation_has_four_groups_without_removing_old_views(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text

    assert html.count('class="nav-group"') == 4
    for group in ("创作", "资料与学习", "市场", "设置"):
        assert f">{group}<" in html
    for view in (
        "workbench", "projects", "materials", "learning", "market",
        "models", "skills", "trash",
    ):
        assert f'id="{view}"' in html
        assert f'data-view="{view}"' in html
    assert 'projects:"creation"' in script.replace(" ", "")
    assert 'learning:"learning"' in script.replace(" ", "")
    assert 'trash:"settings"' in script.replace(" ", "")
```

- [ ] Run `pytest tests/test_console.py -q` and confirm the four-group contract fails against the current flat navigation.
- [ ] Restructure only the sidebar controls. Use these exact mappings:
  - `workbench`, `projects` -> `creation`
  - `materials`, `learning` -> `learning`
  - `market` -> `market`
  - `models`, `skills`, `trash` -> `settings`
- [ ] Keep every old `.view` section and existing DOM ID. Do not rename API-facing element IDs or remove the old page content.
- [ ] Add `VIEW_GROUPS` and make `showView()` activate both the exact secondary item and its parent group. Opening a child programmatically must expand its group before scrolling or focusing.
- [ ] Use actual buttons for group toggles with `aria-expanded` and `aria-controls`. Preserve keyboard focus and make only one compact group open on mobile; desktop may remember open groups in in-memory state.
- [ ] Give icons and labels stable tracks in CSS. Long Chinese labels wrap only in the secondary list and never resize the sidebar or move the active indicator.
- [ ] Run `pytest tests/test_console.py -q` and confirm legacy console assertions and the four-group contract pass.
- [ ] Commit with `git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py && git commit -m "feat: group console navigation by task"`.

---

### Task 6: Build The Task-First Home State And Single Primary Action

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Consumes:** `state.activeProject`, existing run status and events, `candidate.quality_summary`, `publicationPreview`, outline/initialization state, and the companion safe-revision state for `short-revision` runs.

**Produces:** `deriveWorkbenchTaskState(snapshot)`, a maximum of three priority issues, and one deterministic primary command.

- [ ] Add static contract tests for the task-home regions and priority labels:

```python
def test_workbench_is_task_first_and_keeps_detail_progressively_disclosed(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    for control in (
        'id="workbench-current-project"',
        'id="workbench-current-stage"',
        'id="workbench-priority-issues"',
        'id="workbench-primary-action"',
        'id="workbench-details"',
    ):
        assert control in html
    for label in (
        "新建作品", "继续初始化", "查看当前进度", "从失败项继续",
        "生成完整短篇", "修复已选问题", "设为正式稿", "准备投稿",
    ):
        assert label in script
    assert "deriveWorkbenchTaskState" in script
    assert "slice(0,3)" in script.replace(" ", "")
    assert ".workbench-task-summary" in css
    assert ".workbench-primary-action" in css
```

- [ ] Add a source-level priority-order test that asserts the decision function evaluates active runs before draft generation, unresolved blocking issues before publication, and resumable failed `short-revision` before starting a new repair. This guards accidental branch reordering without introducing a JavaScript test dependency.
- [ ] Run `pytest tests/test_console.py -q` and confirm the new task-home contract fails.
- [ ] Implement `deriveWorkbenchTaskState(snapshot)` as a pure function returning `{stage, issues, action, detail}`. Use this exact priority:
  1. No project -> `新建作品`.
  2. Project initialization incomplete -> `继续初始化`.
  3. Any `queued`, `running`, or `cancelling` run -> `查看当前进度` and never start a duplicate.
  4. Failed resumable `short-revision` -> `从失败项继续`.
  5. No manuscript candidate -> the existing `生成完整短篇` action.
  6. Local blockers or unresolved required issues -> `修复已选问题` in the existing quality/safe-revision workspace.
  7. Quality authority allows formalization but manuscript is not formal -> `设为正式稿`.
  8. Publication preview is ready -> `准备投稿`.
  9. Otherwise -> `查看稿件质量`.
- [ ] Render at most three issues from the existing merged issue ledger; do not calculate a second score. Each item shows a short Chinese title, why it matters, and its existing status.
- [ ] Make the primary action route to the existing operation or view. The home page must not duplicate outline editing, revision comparison, formalization checks, or package generation.
- [ ] Put file locations, full score evidence, full manuscript, protected passages, writing rules, publication settings, run logs, and the project list under the existing `查看详细信息` region. Active or failed task progress remains outside and visible.
- [ ] Give the project selector, stage block, issue rows, and primary button stable responsive dimensions. At widths below 800px, use one column and full-width commands; long Chinese errors use `overflow-wrap:anywhere` and cannot cover the next section.
- [ ] Run `pytest tests/test_console.py -q` and confirm all console tests pass.
- [ ] Commit with `git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py && git commit -m "feat: make workbench task first"`.

---

### Task 7: Add Wizard Draft Deletion UI And Consistent Chinese Async States

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`
- Test: `tests/api/test_wizards.py`

**Consumes:** `GET /api/wizards`, `DELETE /api/wizards/{wizard_id}`, `state.wizards`, `state.activeWizard`, and the existing status/toast helpers.

**Produces:** A guarded delete command beside `继续草稿`, immediate local-state reconciliation, and stable terminal feedback.

- [ ] Add a failing console contract test:

```python
def test_wizard_draft_controls_explain_delete_scope_and_terminal_states(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    html = client.get("/").text
    script = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'id="delete-wizard-draft"' in html
    for phrase in (
        "删除草稿",
        "只删除这份未完成的开书资料，不会删除任何作品",
        "正在删除草稿",
        "草稿已删除",
        "草稿不存在或已经删除",
        "当前输入仍然保留，可以重新尝试",
    ):
        assert phrase in html + script
    assert "method:\"DELETE\"" in script.replace(" ", "")
    assert ".wizard-draft-actions" in css
```

- [ ] Add or extend the API test to delete the currently selected draft while retaining a second draft and all existing projects. This verifies the UI's expected reconciliation contract.
- [ ] Run `pytest tests/test_console.py tests/api/test_wizards.py -q` and confirm the delete control test fails while backend tests from Task 1 still pass.
- [ ] Place `删除草稿` beside `继续草稿`, not inside the wizard form. Disable both until a draft is selected, and keep the destructive button visually secondary.
- [ ] On click, show a confirmation containing the selected draft title or `未命名草稿` and the exact sentence `只删除这份未完成的开书资料，不会删除任何作品。`
- [ ] During the request, disable the two draft actions and display `正在删除草稿`. On success, remove the ID from `state.wizards`; if it equals `state.activeWizard.id`, clear the active wizard, close the wizard shell, reset wizard-only selections, and restore the create launcher.
- [ ] On failure, leave `state.wizards`, `state.activeWizard`, and the current form untouched. Translate known API codes into Chinese and show what remains plus the next action. Never display raw paths, stack traces, or internal enums.
- [ ] Consolidate the new multi-reference, outline-generation, and draft-deletion statuses around the same four UI phases. Every async path must set `completed` or `failed` in `try/catch/finally`; terminal phases remove the animated class.
- [ ] Add `aria-live="polite"` to nonblocking status text and `role="alert"` only to actionable failure text. Keep status containers at stable height to prevent the action row from jumping.
- [ ] Run `pytest tests/test_console.py tests/api/test_wizards.py -q` and confirm all focused tests pass.
- [ ] Commit with `git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py tests/api/test_wizards.py && git commit -m "feat: manage unfinished wizard drafts"`.

---

### Task 8: Document, Run Full Regression, And Verify Desktop And Mobile UX

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`
- Verify: `src/novel_flywheel/static/index.html`
- Verify: `src/novel_flywheel/static/app.js`
- Verify: `src/novel_flywheel/static/app.css`
- Test: complete test suite

**Consumes:** All completed backend, workflow, and UI changes from Tasks 1-7.

**Produces:** Operator documentation, complete automated evidence, and desktop/mobile visual evidence without tracked screenshots.

- [ ] Document the four navigation groups, task-home priority, eligible reference types, local-only preparation, the 12-mechanism limit, outline retry behavior, and the exact boundary between an unfinished wizard draft and a project/manuscript draft.
- [ ] Document recovery behavior: refresh resumes unfinished wizards; outline failure preserves the project and adoptions; safe revision resumes from its checkpoint; deleting a wizard never deletes a project.
- [ ] Run focused backend tests:

```powershell
pytest tests/test_db.py tests/test_wizard.py tests/api/test_wizards.py tests/api/test_learning.py -q
```

- [ ] Run the console contract suite:

```powershell
pytest tests/test_console.py -q
```

- [ ] Run the complete suite and whitespace validation:

```powershell
pytest -q
git diff --check
```

- [ ] Before starting the application, query the current service and database for runs in `queued`, `running`, or `cancelling`. If any exist, do not restart the service; use the existing instance for visual checks.
- [ ] If no active run exists and port 8765 is free, start the documented local service. If port 8765 already serves this workspace, reuse it instead of starting another instance or random port.
- [ ] At `1440x900`, verify all of these states in the browser:
  - Four main navigation groups; each old child page opens and highlights the correct parent.
  - No project -> one `新建作品` action.
  - Initialization incomplete -> one `继续初始化` action.
  - Active run -> visible stage/progress and no duplicate-start action.
  - Failed resumable revision -> `从失败项继续` and retained progress.
  - Unresolved issues -> no more than three on the home page, with the complete report reachable.
  - Formalizable and publication-ready states -> the correct single next action.
  - Multi-reference selection survives filtering and shows a compact selection bar.
  - More than 12 available mechanisms are grouped by source; selecting the twelfth disables only unchecked choices.
  - Outline failure shows the preserved-project message and working route to `作品应用`.
  - Draft deletion succeeds, conflict fails without losing the form, and the other drafts remain.
- [ ] Repeat the interaction checks at `390x844`. Confirm there is no horizontal scrollbar, clipped Chinese text, overlapping controls, shifted save/delete buttons, nested-card clutter, or layout movement when status text changes.
- [ ] Check a deliberately long Chinese failure message. It must wrap inside its status container and leave the next action visible.
- [ ] Confirm completed and failed statuses no longer animate and that keyboard focus remains visible after navigation-group toggles, outline retry, and draft deletion.
- [ ] Do not add browser screenshots to Git. Record viewport, state, and pass/fail notes in the implementation handoff.
- [ ] Review `git diff --stat`, `git diff`, and `git status --short` for credentials, generated run artifacts, database files, screenshots, or unrelated edits.
- [ ] Commit documentation and any verification-only corrections with `git add README.md docs/maintenance.md src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests && git commit -m "docs: explain task workbench reference creation"`.

## Final Acceptance Checklist

- [ ] The sidebar exposes exactly four primary groups and every prior view remains reachable.
- [ ] The home page shows the active project, current stage, at most three important issues, and one deterministic primary action.
- [ ] Several eligible references can create one wizard; local preparation never calls a model.
- [ ] Each selected reference has at least one confirmed mechanism before project creation.
- [ ] Source-scoped choices are grouped, final selection is explicit, and the 12-item limit never truncates silently.
- [ ] Planning input contains no source prose, source characters, source settings, source plot, or unique source expressions.
- [ ] Outline-generation failure preserves the new project and adopted mechanisms and exposes a working retry path.
- [ ] An unfinished wizard and its interview messages can be deleted; a completed or project-linked wizard cannot.
- [ ] All new progress, completion, failure, and recovery text is plain Chinese and ends in a stable terminal state.
- [ ] Desktop and mobile layouts pass the stated visual checks without overflow, overlap, button drift, or hidden active-task state.
- [ ] `pytest -q` and `git diff --check` pass without external model calls.
