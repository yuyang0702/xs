# AI Story Interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persisted, planning-model-driven interview that produces user-approved wizard field suggestions.

**Architecture:** A focused `WizardInterviewService` owns model prompting, response validation, and suggestion application. SQLite stores interview messages; FastAPI exposes history, turn, and apply endpoints; the existing wizard UI renders the conversational panel and writes accepted suggestions back through the canonical wizard answer service.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, vanilla JavaScript, pytest, respx.

## Global Constraints

- External models receive no filesystem, shell, MCP, or Story tools.
- Only explicit user confirmation may mutate wizard answers.
- Locked answers must never be overwritten by interview suggestions.
- Existing form autosave, Skill discovery, and project confirmation behavior must remain compatible.
- No new runtime dependency is allowed.

---

### Task 1: Interview Persistence

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces: `save_interview_message(...)`, `list_interview_messages(wizard_id)`, and `update_interview_message_status(...)`.

- [ ] Write failing database tests for ordered user/assistant messages and status updates.
- [ ] Run `python -m pytest tests/test_db.py -q` and verify the new tests fail because the methods do not exist.
- [ ] Add `wizard_interview_messages` with JSON suggestions and implement the three database methods.
- [ ] Re-run `python -m pytest tests/test_db.py -q` and verify it passes.

### Task 2: Interview Domain Service

**Files:**
- Create: `src/novel_flywheel/interviews.py`
- Create: `tests/test_interviews.py`
- Modify: `src/novel_flywheel/wizard.py`

**Interfaces:**
- Consumes: `ModelGateway.complete("planning", system, user)` and `WizardService.save_answers(...)`.
- Produces: `WizardInterviewService.history`, `turn`, and `apply`.

- [ ] Write failing service tests using a fake model gateway for kickoff, a normal turn, fenced JSON, unknown-field filtering, locked-field filtering, and selective application.
- [ ] Run `python -m pytest tests/test_interviews.py -q` and verify the expected failures.
- [ ] Implement strict response models, prompt construction, JSON extraction, validated persistence, and explicit application.
- [ ] Add a narrow wizard helper for applying suggestible answers without bypassing existing validation.
- [ ] Re-run service tests and verify they pass.

### Task 3: Interview API

**Files:**
- Modify: `src/novel_flywheel/app.py`
- Modify: `src/novel_flywheel/api/wizards.py`
- Modify: `tests/api/test_wizards.py`

**Interfaces:**
- Consumes: `app.state.interviews`.
- Produces: `GET/POST /api/wizards/{id}/interview` and `POST /api/wizards/{id}/interview/{message_id}/apply`.

- [ ] Write failing API tests for history, turn creation, selective apply, missing wizard, completed wizard, and provider error mapping.
- [ ] Run the focused API test file and confirm the routes fail before implementation.
- [ ] Register the interview service and implement Pydantic request bodies and error translation.
- [ ] Re-run API tests and verify they pass.

### Task 4: Wizard Interview UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `tests/test_console.py`

**Interfaces:**
- Consumes: the three interview API endpoints.
- Produces: an interview panel with start/resume, history, message input, pending suggestions, and apply controls.

- [ ] Add failing console assertions for interview controls and client functions.
- [ ] Run `python -m pytest tests/test_console.py -q` and confirm failure.
- [ ] Add semantic HTML for the interview panel and responsive two-column wizard layout.
- [ ] Implement loading history, sending turns, busy/error states, suggestion selection, apply, and form refresh.
- [ ] Run console tests and the bundled Node syntax checker.

### Task 5: End-To-End Verification

**Files:**
- Modify only files required by discovered defects.

**Interfaces:**
- Validates the complete wizard-to-interview-to-form flow.

- [ ] Run `python -m pytest -q`, Python compilation, JavaScript syntax checking, and `git diff --check`.
- [ ] Start the local server at `http://127.0.0.1:8765/`.
- [ ] Verify desktop and mobile wizard layouts in the in-app browser and confirm no console errors or overflow.
- [ ] Commit implementation as `feat: add AI story interview`.

