# Reader Model Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately configurable `reader_review` model role with automatic fallback to `review`.

**Architecture:** Keep review Skills and stage behavior unchanged while allowing `_stage` to route a call through an explicit model role. Select that role locally from existing SQLite bindings and record the selection in run events.

**Tech Stack:** Python, SQLite, vanilla JavaScript, pytest.

## Global Constraints

- No database migration or new dependency.
- Dedicated reader binding is optional.
- Missing reader binding must fall back to `review`.
- External reader models remain read-only and cannot write project files.

---

### Task 1: Route Reader Calls Independently

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

- [ ] Add failing tests proving a `reader_review` binding changes only the reader call role and proving the missing-binding event records fallback.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\test_workflows.py -q` and confirm the new assertions fail.
- [ ] Add optional `model_role: str | None = None` to `_stage`; pass `model_role or stage` to the gateway.
- [ ] In `_reader_review`, select `reader_review` only when `db.get_role_binding("reader_review")` exists; otherwise select `review`.
- [ ] Include `model_role` and `fallback_used` in `quality_escalated` event metadata.
- [ ] Run workflow tests and commit with `feat: add dedicated reader model role`.

### Task 2: Expose Reader Binding In The Console

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `tests/test_console.py`

- [ ] Add a failing console test asserting the JavaScript contains `reader_review` and `目标读者模拟`.
- [ ] Add `reader_review: "目标读者模拟"` to `ROLE_LABELS`.
- [ ] Run console tests and the full suite.
- [ ] Verify JavaScript syntax, restart the local server, and commit with `feat: expose reader model configuration`.

