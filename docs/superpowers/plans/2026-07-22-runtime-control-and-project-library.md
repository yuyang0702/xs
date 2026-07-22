# Runtime Control and Project Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add model probes, cancellable background generation, detailed run logs, editable genre presets, resumable project listing, and recoverable deletion to the local novel console.

**Architecture:** SQLite stores runs, ordered events, and trash metadata. A small in-process `asyncio.Task` manager starts workflows and cancels active tasks, while workflow snapshots preserve formal-file boundaries. Existing FastAPI endpoints and the plain HTML/CSS/JavaScript console remain the delivery surface.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, SQLite, Pydantic, plain JavaScript and CSS, pytest.

## Global Constraints

- Run only on the user's local Windows computer.
- Do not add Redis, Celery, cloud services, accounts, or new frontend dependencies.
- Never store API keys, authorization headers, or complete private prompts in logs.
- Cancelled work keeps the project and completed checkpoints; incomplete stages do not write partial formal files.
- Project deletion is recoverable before explicit permanent deletion.

---

### Task 1: Persisted Runs, Events, And Task Manager

**Files:**
- Create: `src/novel_flywheel/tasks.py`
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/app.py`
- Test: `tests/test_tasks.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `RunTaskManager.start(project_id, workflow, operation) -> dict`, `RunTaskManager.cancel(run_id) -> dict`.
- Produces: `Database.add_run_event(...)`, `Database.list_run_events(run_id)`, and `Database.interrupt_active_runs()`.

- [ ] Write tests proving ordered events, startup interruption recovery, immediate queued response, completion, failure, and idempotent cancellation.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest -q tests/test_tasks.py tests/test_db.py` and confirm the new tests fail for missing interfaces.
- [ ] Add `run_events` to `SCHEMA`, implement the database methods, and create a task manager whose worker records queued/running/completed/failed/cancelled events.
- [ ] Wire the manager into `create_app` and mark stale active runs interrupted at startup.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Workflow Cancellation Boundaries And Detailed Events

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/models.py`
- Modify: `src/novel_flywheel/skills.py`
- Modify: `src/novel_flywheel/skill_runtime.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_models.py`
- Test: `tests/test_skill_runtime.py`

**Interfaces:**
- Consumes: task-manager-created `run_id` and `Database.add_run_event`.
- Produces: `run_short(..., run_id=None)`, `run_long_setup(..., run_id=None)`, and `run_chapter(..., run_id=None)`.

- [ ] Add tests proving an injected run ID is used, stages emit model and Skill details, cancellation restores pre-commit snapshots, and recoverable tool errors return to the model.
- [ ] Run the focused workflow, model, and Skill Runtime tests and confirm the new cancellation/event assertions fail.
- [ ] Refactor pipeline setup to accept a pre-created run ID, emit stage events, catch `asyncio.CancelledError` separately, restore snapshots before commit, and preserve a committed chapter if cancellation occurs during a later audit.
- [ ] Capture bounded executable-Skill stderr in failures and keep the Story CLI command schema restricted to maintenance subcommands.
- [ ] Re-run focused tests and confirm they pass.

### Task 3: Background Run APIs And Initialization Tracking

**Files:**
- Modify: `src/novel_flywheel/api/runs.py`
- Modify: `src/novel_flywheel/api/wizards.py`
- Test: `tests/api/test_runs.py`
- Test: `tests/api/test_wizards.py`

**Interfaces:**
- Consumes: `RunTaskManager.start` and `RunTaskManager.cancel`.
- Produces: `202` start responses, `POST /api/runs/{run_id}/cancel`, and run details containing `events` and `tool_receipts`.

- [ ] Update API tests to expect immediate queued/running records, cancellation, ordered events, and initialization Skills represented as a tracked `initialize-skills` run.
- [ ] Run the two API test files and confirm the background-contract tests fail.
- [ ] Route short/setup/chapter/initialization starts through the task manager and add cancellation and enriched detail endpoints.
- [ ] Re-run focused API tests and confirm they pass.

### Task 4: Recoverable Project Trash

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_projects.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces: `ProjectStore.trash`, `restore`, `list_trash`, and `delete_permanently`.
- Produces: trash list, restore, move-to-trash, and permanent-delete HTTP endpoints.

- [ ] Add tests for hiding trashed projects, continuing an active project after a cancelled run, restoring all files/history, rejecting unsafe paths, and permanent deletion only from trash.
- [ ] Run focused project tests and confirm they fail for missing trash behavior.
- [ ] Add `project_trash` metadata, resolved-root checks, native `shutil.move`, restore collision protection, and guarded `shutil.rmtree`.
- [ ] Expose project trash endpoints and re-run focused tests.

### Task 5: Console Controls, Probes, Presets, Logs, And Browser Verification

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `tests/test_console.py`
- Test: `tests/api/test_providers.py`

**Interfaces:**
- Consumes: existing model probe endpoint, background run endpoints, enriched run detail, and project trash endpoints.
- Produces: probe buttons/results, editable genre/sub-genre comboboxes, active-run polling and stop control, event log, continue-writing actions, and trash view.

- [ ] Add console assertions for probe actions, genre datalists, stop control, event log, project actions, and trash controls; retain provider probe API coverage.
- [ ] Run console/provider tests and confirm the new UI assertions fail.
- [ ] Implement the approved task/log two-column layout, fixed controls, model probe result rendering, local genre maps with unrestricted custom input, run polling, cancellation, and trash/restore/permanent-delete actions.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest -q` and `node --check src/novel_flywheel/static/app.js`; confirm all checks pass.
- [ ] Restart the local server, test the model probe and cancellation/log UI in the browser without spending unnecessary model tokens, and verify desktop and narrow viewport layouts do not overlap.
