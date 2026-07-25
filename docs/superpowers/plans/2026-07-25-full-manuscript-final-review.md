# Full-Manuscript Final Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make final review cover the complete manuscript, preserve issue history, and fail honestly when the final-review role is unavailable.

**Architecture:** Add small deterministic helpers in `quality.py` for windowing, issue reconciliation and score caps. Orchestrate evidence extraction and adjudication from `WorkflowService` using only the existing final-review role and its configured fallback. Extend the existing JSON report instead of adding a new persistence layer.

**Tech Stack:** Python, asyncio, pytest, existing model gateway and JSON report storage.

---

### Task 1: Deterministic Review Evidence

**Files:**
- Modify: `src/novel_flywheel/quality.py`
- Test: `tests/test_quality.py`

- [ ] Write failing tests for paragraph-aligned overlapping windows, complete coverage, stable issue IDs, reconciliation validation, and score caps.
- [ ] Run `pytest tests/test_quality.py -q` and confirm the new tests fail for missing behavior.
- [ ] Implement the smallest pure helpers that satisfy the tests.
- [ ] Run `pytest tests/test_quality.py -q` and confirm it passes.

### Task 2: Final Review Orchestration

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prompts.py`
- Test: `tests/test_workflows.py`

- [ ] Write failing workflow tests proving `planning` is never called, every manuscript window is audited, prior issues require explicit reconciliation, and provider failure becomes `final_review_incomplete`.
- [ ] Run the focused workflow tests and confirm expected failures.
- [ ] Add story-map extraction, local evidence audit, cross-window audit and final adjudication using the existing `_stage` path with `allow_tools=False`.
- [ ] Apply deterministic validation before `quality_outcome` and preserve the best candidate on incomplete terminal review.
- [ ] Run focused workflow tests and confirm they pass.

### Task 3: Report And Documentation

**Files:**
- Modify: `docs/maintenance.md`
- Modify: `src/novel_flywheel/static/app.js` only if existing report rendering needs additive labels
- Test: relevant frontend or API tests already present in `tests/`

- [ ] Document full-manuscript coverage, issue statuses, score caps, provider failure behavior and token expectations.
- [ ] Add only the report labels required by the existing UI data path.
- [ ] Run relevant tests.

### Task 4: Verification

**Files:**
- No production changes expected.

- [ ] Run `pytest -q`.
- [ ] Confirm `WorkflowService._stage_output_budget("final_review") == 8192` remains true.
- [ ] Restart the local service and verify `http://127.0.0.1:64898` responds.
- [ ] Inspect `git diff --check` and `git status --short`.
- [ ] Commit the implementation and synchronized documentation locally.
