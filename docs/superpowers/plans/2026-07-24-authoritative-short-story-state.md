# Authoritative Short-Story State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned authoritative StoryState and connect it to the existing short-story workflow without changing existing project files until a validated candidate is committed.

**Architecture:** Extend the existing SQLite database and `StoryMemory`; keep workflow orchestration in `WorkflowService`. Runtime owns validation and atomic state commits, while models continue to provide role-specific candidate outputs through existing Skills and provider bindings.

**Tech Stack:** Python 3.11, SQLite, FastAPI, Pydantic, pytest

---

### Task 1: Versioned StoryState storage

**Files:**
- Create: `src/novel_flywheel/story_state.py`
- Modify: `src/novel_flywheel/db.py`
- Test: `tests/test_story_state.py`

- [ ] Write failing tests for project isolation, idempotent initialization, history, and stale revision rejection.
- [ ] Run `pytest tests/test_story_state.py -q` and verify the missing API fails.
- [ ] Add the three additive tables and minimal transactional store.
- [ ] Run `pytest tests/test_story_state.py -q` and verify it passes.

### Task 2: Existing-project migration and candidates

**Files:**
- Modify: `src/novel_flywheel/story_state.py`
- Modify: `src/novel_flywheel/projects.py`
- Test: `tests/test_story_state.py`

- [ ] Write failing tests for importing existing canon/manuscript without modifying files.
- [ ] Run the focused tests and verify failure.
- [ ] Implement idempotent migration and candidate lifecycle records.
- [ ] Run the focused tests and verify success.

### Task 3: Role context and token budgets

**Files:**
- Create: `src/novel_flywheel/context_policy.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_context_policy.py`

- [ ] Write failing tests for bounded polish context, adjacent boundaries, immutable facts, and dynamic output limits.
- [ ] Run the focused tests and verify failure.
- [ ] Implement deterministic context assembly and dynamic budgets.
- [ ] Run the focused tests and verify success.

### Task 4: Short-story candidate commit

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_workflows.py`

- [ ] Write failing workflow tests proving failed candidates do not change formal files and successful candidates advance state revision.
- [ ] Run the focused tests and verify failure.
- [ ] Connect migration, candidate recording, validation, atomic file/state promotion, and run events.
- [ ] Run the focused tests and verify success.

### Task 5: Compatibility verification

**Files:**
- Modify only files required by regression failures.

- [ ] Run `pytest -q`.
- [ ] Inspect schema migration against a copied current database.
- [ ] Confirm no paid provider calls were made.
- [ ] Start the console with the existing launcher and verify the health endpoint.

