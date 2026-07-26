# Market Keywords and Length Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace noisy title/summary fragments with explainable cross-work keyword analysis, and classify/filter ranked works as long, short, anthology, or unknown.

**Architecture:** Keep collection deterministic and local. Persist length classification and its evidence on each market work; derive platform classifications during refresh and allow an explicit user override. Build keyword statistics from distinct works, use LTP tokens when enabled, fall back to conservative dictionaries and platform tags, and return evidence-rich title/summary/combined views to the existing dashboard.

**Tech Stack:** Python 3.11, FastAPI, SQLite, vanilla JavaScript/CSS, pytest.

## Global Constraints

- No paid model calls.
- Existing snapshots, references, and confirmed links must remain intact.
- Database migration must be idempotent.
- Keyword counts are distinct-work counts and require at least two matching works.
- Length priority is user override, platform field, long-form ranking, confirmed TXT inference, then unknown.

---

### Task 1: Persist and Resolve Length Type

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/market.py`
- Test: `tests/test_market_migration.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Produces: `length_type`, `length_source`, `length_evidence`, and `length_override` on market work responses.

- [ ] Write failing migration and parser/priority tests.
- [ ] Run the focused tests and confirm failures are caused by missing columns and behavior.
- [ ] Add the idempotent columns, parse `space_type`, and implement the priority resolver.
- [ ] Run the focused tests to green.

### Task 2: Add Length API and Filters

**Files:**
- Modify: `src/novel_flywheel/api/market.py`
- Modify: `src/novel_flywheel/market.py`
- Test: `tests/api/test_market.py`

**Interfaces:**
- Produces: `PUT /api/market/works/{work_id}/length`; dashboard and work-list `length_type` filters.

- [ ] Write failing API tests for manual override, reset, validation, and filtering.
- [ ] Run the focused tests and verify expected failures.
- [ ] Implement the minimal service and API methods.
- [ ] Run the focused tests to green.

### Task 3: Build Explainable Keyword Analysis

**Files:**
- Modify: `src/novel_flywheel/market.py`
- Modify: `src/novel_flywheel/app.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: optional `LocalNLPManager.analyze(text)`.
- Produces: `keywords.combined`, `keywords.title`, and `keywords.summary`, each containing category, coverage, score, and matching-work evidence.

- [ ] Write failing tests for distinct-work thresholding, title/summary separation, synonym normalization, scoring, and evidence.
- [ ] Run the focused tests and verify the old regex output fails them.
- [ ] Implement conservative extraction with optional LTP tokens and no model calls.
- [ ] Inject the existing local NLP manager into the default market service.
- [ ] Run the focused tests to green.

### Task 4: Update Dashboard UI and Documentation

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`
- Modify: `docs/maintenance.md`

**Interfaces:**
- Consumes: enriched dashboard JSON and length update API.
- Produces: length filter/table editor plus keyword source/category controls and expandable evidence.

- [ ] Write failing console contract tests for the new controls and columns.
- [ ] Run the focused test and verify the controls are absent.
- [ ] Add the controls, rendering, interaction, and responsive styling; reduce chart whitespace,
      align panel density, and show insufficient trend data as an explicit state.
- [ ] Document the local-only method, evidence, thresholds, and classification priority.
- [ ] Run console and market tests to green.

### Task 5: Verification and Delivery

**Files:**
- Verify: all changed source, test, static, and documentation files.

- [ ] Run the full test suite.
- [ ] Inspect the diff and confirm no unrelated or sensitive files are included.
- [ ] Commit the completed feature.
- [ ] Push `main` and verify local/remote commit equality.
