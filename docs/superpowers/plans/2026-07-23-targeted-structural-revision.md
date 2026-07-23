# Targeted Structural Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make quality corrections converge by planning and applying targeted cross-segment structural revisions.

**Architecture:** Add pure helpers for compact review briefs, segment maps, and validated revision plans. Integrate one planning call before each structural pass, then revise only mapped segments with adjacent and global context.

**Tech Stack:** Python 3.11, asyncio, pytest, existing model gateway and run-event storage.

---

### Task 1: Revision plan helpers

**Files:**
- Create: `src/novel_flywheel/revision.py`
- Create: `tests/test_revision.py`

- [x] Write failing tests for complete issue preservation, compact segment maps, plan validation, and deterministic checks.
- [x] Run `python -m pytest tests/test_revision.py -q` and confirm failure.
- [x] Implement the helpers using only the standard library.
- [x] Run the focused tests and confirm they pass.

### Task 2: Targeted workflow integration

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

- [x] Write failing workflow tests proving a structural plan is requested and untouched segments are preserved.
- [x] Run the focused tests and confirm failure.
- [x] Add revision-plan generation, validated fallback, targeted prompts, adjacent context, output artifacts, and events.
- [x] Run focused workflow tests and confirm they pass.

### Task 3: Verification and activation

**Files:**
- Modify only files required by failing regression tests.

- [x] Run `python -m pytest -q`.
- [x] Run `git diff --check` and inspect the final diff.
- [x] Restart the local console on port `64898` and verify HTTP 200.
- [x] Commit the implementation.
