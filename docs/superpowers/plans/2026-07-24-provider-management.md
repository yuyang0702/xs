# Provider Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users edit and delete existing providers without recreating model mappings.

**Architecture:** Reuse the database provider upsert and existing delete route. Add one registry update method, one API update route, and small stateful form behavior in the existing static application.

**Tech Stack:** FastAPI, Pydantic, SQLite, vanilla JavaScript, pytest

---

### Task 1: Provider update API

**Files:**
- Modify: `tests/api/test_providers.py`
- Modify: `src/novel_flywheel/providers/registry.py`
- Modify: `src/novel_flywheel/api/providers.py`

- [ ] Write API tests for preserving and replacing API keys, validation, and missing providers.
- [ ] Run the focused tests and confirm they fail because the update route does not exist.
- [ ] Add `ProviderUpdate`, `ProviderRegistry.update_provider`, and `PUT /api/providers/{provider_id}`.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Provider deletion regression

**Files:**
- Modify: `tests/api/test_providers.py`

- [ ] Add a test proving provider deletion removes its model mappings and secret.
- [ ] Run the focused test and confirm the existing route satisfies it.

### Task 3: Provider management UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`

- [ ] Add a hidden provider ID, editable form state, cancel control, and Edit/Delete commands.
- [ ] Make API Key required only for provider creation.
- [ ] Reload all dependent selects after update or deletion.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`

- [ ] Document provider editing, optional key replacement, and cascading model deletion.
- [ ] Run provider API tests.
- [ ] Run the complete test suite.
- [ ] Verify the provider page in a browser and restart only when no run is active.
