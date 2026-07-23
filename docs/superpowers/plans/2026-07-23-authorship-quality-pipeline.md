# Authorship Quality Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local authorship-quality diagnostics, targeted validation, style context, review severity normalization, long-fiction drift monitoring, and controlled candidate publication.

**Architecture:** Add focused pure-Python modules for prose diagnostics and style context, then integrate them at workflow and API boundaries. Keep model calls unchanged except for compact prompt context and targeted segment selection. Expose read-only diagnostics plus a controlled publish command in the existing console.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, vanilla JavaScript/CSS, pytest.

---

### Task 1: Local prose diagnostics

**Files:** Create `src/novel_flywheel/prose_quality.py`; create `tests/test_prose_quality.py`.

- [ ] Write failing tests for production text, formulaic patterns, ending summaries, segment locations, naturalness score, and safe clean prose.
- [ ] Run `pytest tests/test_prose_quality.py -v` and verify the missing-module failure.
- [ ] Implement immutable diagnostic results and bounded regex/statistical checks.
- [ ] Run the focused tests and commit.

### Task 2: Style profiles and character fingerprints

**Files:** Create `src/novel_flywheel/style_context.py`; create `tests/test_style_context.py`; modify `src/novel_flywheel/projects.py`.

- [ ] Write failing tests for deterministic profile creation and relevant-character-only fingerprints.
- [ ] Run the focused tests and verify failure.
- [ ] Implement profile creation, loading, and compact voice extraction.
- [ ] Run focused tests and commit.

### Task 3: Review severity normalization

**Files:** Modify `src/novel_flywheel/quality.py`; modify `src/novel_flywheel/prompts.py`; modify `tests/test_quality.py`.

- [ ] Write failing tests showing prose/style/history critical labels do not hard-fail while compliance and manuscript corruption do.
- [ ] Run the tests and verify failure.
- [ ] Implement runtime issue classes and authoritative blocker normalization.
- [ ] Update review prompts with the same contract, run tests, and commit.

### Task 4: Segment acceptance and workflow integration

**Files:** Modify `src/novel_flywheel/revision.py`; modify `src/novel_flywheel/workflows.py`; modify `tests/test_revision.py`; modify `tests/test_workflows.py`.

- [ ] Write failing tests for production-text rejection, fact/name preservation, diagnostic regression, unaffected segments, and unconditional typography normalization.
- [ ] Run focused tests and verify failure.
- [ ] Implement the acceptance report and integrate local diagnostics, style context, targeted selection, logging, and normalization.
- [ ] Run focused tests and commit.

### Task 5: Long-fiction drift metrics

**Files:** Extend `src/novel_flywheel/prose_quality.py`; modify `src/novel_flywheel/workflows.py`; extend `tests/test_prose_quality.py` and `tests/test_workflows.py`.

- [ ] Write failing tests for stable voice, material rhythm/dialogue drift, five-chapter comparison, and advisory-only logging.
- [ ] Run focused tests and verify failure.
- [ ] Implement metrics, comparison, persistence, and workflow events.
- [ ] Run focused tests and commit.

### Task 6: Candidate diagnostics and controlled publication API

**Files:** Modify `src/novel_flywheel/api/projects.py`; modify `tests/api/test_projects.py`.

- [ ] Write failing API tests for inspection, safe short-story publication, production-text rejection, missing candidate, and path confinement.
- [ ] Run focused tests and verify failure.
- [ ] Implement candidate resolution, diagnostics response, atomic publication, chapter mirror, and publication metadata.
- [ ] Run focused tests and commit.

### Task 7: Console controls

**Files:** Modify `src/novel_flywheel/static/index.html`, `app.js`, and `app.css`; modify `tests/test_console.py`.

- [ ] Write failing console contract tests for the quality panel and publish action.
- [ ] Run tests and verify failure.
- [ ] Add compact diagnostic display, confirmation, publish button, responsive layout, and refresh behavior.
- [ ] Run console tests and commit.

### Task 8: Verification and runtime rollout

- [ ] Run `pytest` and require zero failures.
- [ ] Inspect the existing best candidate through the new API without model calls.
- [ ] Confirm no active generation run, restart the local service, and verify `/api/health`.
- [ ] Test desktop and 390px layouts, then leave the console open for the user.
