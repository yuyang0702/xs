# Safe Conditional Quality Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept safe manuscripts scoring 75–79.99 as conditional passes and stop risky revisions once a publishable candidate exists.

**Architecture:** Extend the pure quality-gate result with an explicit outcome while retaining the existing boolean compatibility wrapper. The workflow records the outcome in reports/events and exits on either full or conditional pass, archiving the reviewed candidate.

**Tech Stack:** Python 3.11, pytest, existing FastAPI/SQLite workflow service.

---

### Task 1: Quality Policy

**Files:**
- Modify: `src/novel_flywheel/quality.py`
- Modify: `tests/test_quality.py`

- [ ] Add failing tests for full pass, safe conditional pass at 75, below-75 failure, critical-issue failure, rewrite failure, and hard-fail failure.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_quality.py -q` and verify the new cases fail.
- [ ] Add `quality_outcome(review) -> tuple[str, list[str]]`, returning `passed`, `conditional_pass`, or `failed`. Keep `quality_gate` as `(outcome != "failed", reasons)` for existing callers.
- [ ] Run the focused tests and verify they pass.
- [ ] Commit as `feat: add safe conditional quality outcome`.

### Task 2: Workflow Outcome And Early Stop

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

- [ ] Add a failing short-story workflow test whose first final review scores exactly 75 with clear dimensions and only medium issues.
- [ ] Assert the run completes without a corrective polish call, archives that candidate, records report status `conditional_pass`, and emits a successful quality event with outcome metadata.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_workflows.py -k "conditional_pass" -q` and verify RED.
- [ ] Replace the final gate call with `quality_outcome`, treat both success outcomes as terminal, set the report status to the exact outcome, preserve noncritical issues, and emit `质量条件通过，建议小修` for conditional passes.
- [ ] Run all workflow tests and verify GREEN.
- [ ] Commit as `feat: stop revisions on safe conditional pass`.

### Task 3: Verification And Delivery

**Files:**
- Verify all modified files.

- [ ] Run `git diff --check`.
- [ ] Run `.venv/Scripts/python.exe -m pytest -q` and verify zero failures.
- [ ] Confirm no run is queued, running, or cancelling.
- [ ] Restart port `64898` with `NOVEL_FLYWHEEL_DATA_DIR=C:\小说\novel-flywheel-console\data`.
- [ ] Verify `/api/health` returns 200 and the existing project/run history remains present.
