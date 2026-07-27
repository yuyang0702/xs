# Reference Analysis Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse verified per-window model-analysis results after any window or synthesis failure, including the nine results already stored for the current reference.

**Architecture:** Keep `model_claim` as the single persisted window-result record. Add source-version, analysis-version, boundary, and content-hash metadata to new claims; migrate only structurally valid legacy claims from single-version references. Rebuild the current dynamic window list on every run and match checkpoints against that list.

**Tech Stack:** Python 3.11, FastAPI, SQLite JSON fields, vanilla JavaScript, pytest.

## Global Constraints

- Do not assume fixed window size, count, or boundaries.
- Never reuse a checkpoint whose window content hash, content type, analysis version, or result validation differs; source versions remain provenance rather than invalidating every unchanged window.
- Preserve existing local analysis, learning nodes, reference versions, model receipts, and project data.
- Do not call paid APIs from tests.
- Keep all user-visible progress and failure text in clear Simplified Chinese.

---

### Task 1: Persisted dynamic-window checkpoint matching

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Test: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: current `ReferenceLibrary` version metadata, `LearningSystem._windows()`, and existing `model_claim` nodes.
- Produces: validated claims in current window order and new claims carrying checkpoint metadata.

- [ ] Add failing tests proving a failed run reuses successful windows and calls only missing windows.
- [ ] Add a failing test proving changed dynamic boundaries or content invalidate only the affected checkpoint.
- [ ] Add a failing test proving a single-version legacy claim is reused and annotated for future runs.
- [ ] Run the focused tests and confirm the missing behavior causes failure.
- [ ] Implement checkpoint lookup, validation, legacy compatibility, and immediate per-window persistence.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Resume progress and understandable UI

**Files:**
- Modify: `src/novel_flywheel/analysis_tasks.py`
- Modify: `src/novel_flywheel/static/app.js`
- Test: `tests/test_analysis_tasks.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: progress updates containing `reused_windows` and `current_window`.
- Produces: task status fields and Chinese progress copy showing what was reused and what is running.

- [ ] Add failing tests for persisted progress fields and UI copy.
- [ ] Run the focused tests and confirm failure.
- [ ] Pass resume fields through the task manager and render them in the reference status panel.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Documentation and verification

**Files:**
- Modify: `docs/maintenance.md`

**Interfaces:**
- Consumes: implemented checkpoint contract.
- Produces: maintenance guidance describing invalidation and legacy recovery.

- [ ] Document the checkpoint and invalidation rules.
- [ ] Run `git diff --check`.
- [ ] Run the focused learning, task-manager, console, and provider regression tests.
- [ ] Run the complete `pytest -q` suite.
- [ ] Inspect the current reference records and verify the existing nine windows satisfy legacy recovery conditions without invoking a paid API.
