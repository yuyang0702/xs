# Style Sample Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-project reference-text style learning that feeds the existing draft and polish prompts.

**Architecture:** A focused style-sample service validates and stores source text, asks the existing planning gateway for a bounded JSON profile, and updates a delimited section in `style-profile.md`. Project API endpoints expose read/analyze/delete operations; the existing static console reads files locally and submits text as JSON.

**Tech Stack:** FastAPI, Pydantic, pathlib, vanilla JavaScript, pytest

---

### Task 1: Style sample service

**Files:** Create `src/novel_flywheel/style_samples.py`; create `tests/test_style_samples.py`.

- [ ] Write failing tests for validation, profile replacement, deletion, and analysis failure preservation.
- [ ] Run `pytest tests/test_style_samples.py -q` and confirm feature-missing failure.
- [ ] Implement bounded JSON parsing and atomic project-file updates.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Project API

**Files:** Modify `src/novel_flywheel/app.py`, `src/novel_flywheel/api/projects.py`; modify `tests/api/test_projects.py`.

- [ ] Write failing GET/POST/DELETE endpoint tests.
- [ ] Run the focused API tests and confirm failure.
- [ ] Register the service and endpoints using the existing project lookup/error pattern.
- [ ] Run the focused API tests and confirm success.

### Task 3: Console controls

**Files:** Modify `src/novel_flywheel/static/index.html`, `src/novel_flywheel/static/app.js`, `src/novel_flywheel/static/app.css`.

- [ ] Add accessible file, paste, analyze, status, and delete controls.
- [ ] Load current status with the active project and submit file/pasted content.
- [ ] Verify responsive layout and interaction in the local browser.

### Task 4: Full verification

**Files:** No production changes expected.

- [ ] Run `pytest -q`.
- [ ] Restart only after confirming no active generation.
- [ ] Verify `/api/health`, style-sample endpoints, and browser rendering.
