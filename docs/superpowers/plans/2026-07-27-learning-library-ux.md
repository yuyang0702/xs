# Learning Library UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make learning results understandable to writers and make every analysis action visibly trackable from start to completion or failure.

**Architecture:** Keep local analysis behavior unchanged, but add a small in-process task manager for model analysis so the UI can poll truthful window-level progress. Reshape existing mechanism data only at the presentation layer into plain-language summaries, stage coverage, representative evidence, and explicit decisions.

**Tech Stack:** FastAPI, asyncio, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Do not add a model role or make additional paid model calls.
- Do not change the extracted mechanism schema or adoption rules.
- Progress must report only completed work; never simulate percentages.
- Every decision surface must explain what the item is, why it matters, what the user is deciding, and what each action changes.
- Desktop and mobile layouts must remain readable without horizontal overflow.

---

### Task 1: Persistent model-analysis task status

**Files:**
- Create: `src/novel_flywheel/analysis_tasks.py`
- Modify: `src/novel_flywheel/app.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Modify: `src/novel_flywheel/learning.py`
- Test: `tests/api/test_learning.py`
- Test: `tests/test_learning_system.py`

**Interfaces:**
- Produces `ReferenceAnalysisTaskManager.start(source_id, operation)`, `get_for_source(source_id)`, and `cancel(task_id)`.
- `LearningSystem.model_analyze_reference(source_id, progress=None)` reports `phase`, `completed_windows`, and `total_windows` after each completed window.
- `POST /api/references/{source_id}/model-learn` returns HTTP 202 task state; `GET /api/references/{source_id}/model-learn/status` returns the latest state.

- [ ] Write failing API and learning-system tests for queued/running/completed/failed progress and per-window callbacks.
- [ ] Run the focused tests and confirm they fail because task status does not exist.
- [ ] Implement the in-process manager and progress callback without changing model prompts or call count.
- [ ] Run focused tests and confirm they pass.

### Task 2: Understandable mechanism summaries

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Add presentation helpers that convert positions to opening/early/middle/late/ending groups.
- Render four plain-language sections: `原文是怎么写的`, `为什么值得学习`, `你的作品可以怎么用`, `什么时候不要用`.

- [ ] Write a failing console asset test for the new labels, coverage summary, and decision explanation.
- [ ] Run it and confirm the current abstract labels fail.
- [ ] Implement stage grouping, representative evidence, collapsed evidence groups, and explicit action copy.
- [ ] Run console tests and confirm they pass.

### Task 2B: Plain-language local diagnostics

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Render every local finding as `发现了什么`, `为什么可能影响阅读`, `建议你检查什么`, and `原文证据`.
- Keep `rule_id` and severity inside a collapsed `技术详情`; never use them as the visible heading.
- Translate known rule IDs into concrete reader-facing explanations and fall back to the existing message without inventing a diagnosis.

- [ ] Write a failing console asset test for the four plain-language diagnostic sections and collapsed technical details.
- [ ] Run it and confirm the current rule-oriented presentation fails.
- [ ] Implement diagnostic copy mapping and the compact evidence-first card.
- [ ] Run console tests and confirm they pass.

### Task 3: Visible task feedback and state-aware save action

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Render a fixed `reference-task-status` region below the analysis actions.
- Poll model task status while queued/running and restore the latest source task when reopening a reference.
- Hide the save button when clean; show `保存修改` only when dirty; show saving, failure, and retry states inline.

- [ ] Write failing tests for status-region copy, polling hooks, and clean/dirty save states.
- [ ] Run tests and confirm they fail on the existing toast-only flow.
- [ ] Implement truthful task states and state-aware save controls.
- [ ] Run console tests and JavaScript syntax validation.

### Task 4: End-to-end verification and delivery

**Files:**
- Modify: `README.md` only if user-visible behavior needs documentation.

- [ ] Run learning API, learning-system, and console regression suites.
- [ ] Run the complete pytest suite and JavaScript syntax check.
- [ ] Verify desktop and mobile layouts in the local browser, including task failure and completed-state rendering without paid API calls.
- [ ] Run `git diff --check` and inspect the final scoped diff.
- [ ] Commit and push `main`.
