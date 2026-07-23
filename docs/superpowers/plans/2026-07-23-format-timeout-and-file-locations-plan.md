# Format Repair, Polish Timeout, and File Locations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair safe typography locally, wait up to 300 seconds for the Claude polish provider, and expose all relevant project files with controlled Explorer actions.

**Architecture:** A focused text normalizer runs immediately before deterministic revision checks. Project artifact resolution lives in the projects API and exposes only server-derived artifact kinds. The existing frontend renders these resolved locations and calls a controlled open endpoint.

**Tech Stack:** Python 3.12, FastAPI, SQLite, vanilla JavaScript/CSS, pytest.

---

### Task 1: Local Mechanical Formatting

**Files:**
- Modify: `src/novel_flywheel/revision.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_revision.py`
- Test: `tests/test_workflows.py`

- [ ] Add failing tests proving paired ASCII dialogue quotes are converted, CJK-only spacing is removed, duplicate Chinese punctuation is collapsed, Markdown separators and URLs remain unchanged, and formatting failures do not enter final-review runtime failures.
- [ ] Run `pytest tests/test_revision.py tests/test_workflows.py -q` and confirm the new tests fail for missing normalization.
- [ ] Add `normalize_chinese_prose(text: str) -> tuple[str, list[str]]` and invoke it before `check_revision_constraints` writes `revision-checks*.json`.
- [ ] Filter safely repairable typography checks from model-generated forbidden-text checks so a literal ASCII quote cannot independently trigger full-manuscript correction.
- [ ] Run the focused tests and commit the formatter.

### Task 2: Claude Polish Timeout

**Files:**
- Modify data: `data/app.db`
- Test: verify with a read-only SQLite query.

- [ ] Confirm the `polish` primary binding points to the dedicated Claude provider.
- [ ] Update only that provider's `timeout_seconds` from 180 to 300.
- [ ] Query the binding/provider join and confirm the primary polish timeout is 300 while other providers are unchanged.
- [ ] Do not restart until no run is queued, running, or cancelling.

### Task 3: Project Artifact Resolver and API

**Files:**
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/api/test_projects.py`

- [ ] Add failing API tests for project root, formal manuscript, latest draft, best candidate, recovered polish candidate, latest run, missing artifacts, unknown kinds, and project-boundary validation.
- [ ] Run the focused API tests and confirm failure.
- [ ] Add a server-side `resolve_project_locations(project, store)` helper returning fixed artifact kinds and absolute paths.
- [ ] Add `GET /api/projects/{project_id}/locations`.
- [ ] Add `POST /api/projects/{project_id}/locations/{kind}/open` using `explorer.exe /select,<file>` for files and `explorer.exe <directory>` for directories, without a command shell.
- [ ] Mock `subprocess.Popen` in tests, run focused tests, and commit the API.

### Task 4: File Locations UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

- [ ] Add failing console assertions for the locations panel, copy controls, and controlled open requests.
- [ ] Add an unframed `文件位置` band below the active-project summary.
- [ ] Load locations when the active project changes and after a run completes.
- [ ] Render missing artifacts as `尚未生成`; copy existing paths with `navigator.clipboard.writeText`; call the controlled open endpoint for Explorer actions.
- [ ] Ensure long paths wrap without overlap on desktop and mobile widths.
- [ ] Run console tests and commit the UI.

### Task 5: Verification and Restart

**Files:**
- Verify all modified files and runtime data.

- [ ] Run `pytest -q` and require the complete suite to pass.
- [ ] Confirm no active generation task exists.
- [ ] Restart the local service on port 64898 with the configured data directory.
- [ ] Verify health, locations API, recovered candidate path, and Claude timeout.
- [ ] Reload the local console and visually verify desktop and narrow layouts.
- [ ] Commit any final test-only correction and leave the worktree clean.

