# Reference Receipt And Rejected Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the import receipt and correct rejected-mechanism deletion protection.

**Architecture:** Keep the existing API and UI flows. Add deletion eligibility to the learning-node projection, use the same active-status predicate during deletion, and render compact receipt and rejected-card states from those fields.

**Tech Stack:** Python, FastAPI, SQLite, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Do not alter manuscripts, source files, model bindings, or adopted creative blueprints.
- Do not call paid models.
- Preserve deletion protection for active and metadata-review adoption states.

---

### Task 1: Deletion Eligibility

- [ ] Add failing API tests for historical rejected adoption deletion and active adoption protection.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Expose `deletable`/`delete_reason`/`active_project_ids` and share the active adoption predicate with deletion.
- [ ] Rebuild the creative blueprint when a project adoption is removed.
- [ ] Run the focused tests and verify they pass.

### Task 2: Readable UI

- [ ] Add failing page-contract tests for compact receipt details and protected deletion controls.
- [ ] Render a conclusion-first receipt with collapsed details.
- [ ] Disable protected selections, remove contradictory actions, and provide an explicit remove-from-project action.
- [ ] Run focused UI tests.

### Task 3: Verification

- [ ] Run the complete test suite.
- [ ] Check the page at desktop and narrow viewport sizes.
- [ ] Confirm no model request or manuscript write occurs.
