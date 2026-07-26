# Market Trends and Reference Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local, multi-platform-ready market trend dashboard backed by Zhihu Salt Selection snapshots and confirmed TXT-to-market-work links.

**Architecture:** Extend the existing SQLite authority with market tables, keep fetching/parsing/analysis in a focused `MarketService`, expose a small FastAPI router, and render dependency-free charts in the existing single-page console. Reference imports ask the service for candidates but never create a confirmed link without a user action.

**Tech Stack:** Python 3.11, SQLite, FastAPI, httpx, pytest, vanilla JavaScript, CSS and SVG.

## Global Constraints

- Do not read or store account credentials, cookies, or paid member text.
- Do not call model APIs from refresh, matching, tests, or dashboard rendering.
- Existing projects, references, StoryState, model roles, Skills, runs, and formal manuscripts remain unchanged.
- Failed or empty refreshes never replace the last successful snapshot.
- User-confirmed links and manual metadata are never overwritten by automatic matching.

---

### Task 1: Market schema and persistence

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Test: `tests/test_market_migration.py`

**Interfaces:**
- Produces database methods for data sources, snapshots, works, entries, links, and refresh status.

- [ ] Write migration tests that create an old database, migrate twice, and assert existing references plus new market tables survive.
- [ ] Run `pytest tests/test_market_migration.py -q` and verify the missing tables fail.
- [ ] Add idempotent tables, indexes, JSON decoding helpers, and focused CRUD methods.
- [ ] Run the focused test and verify it passes.

### Task 2: Parser, snapshot refresh, analysis and matching

**Files:**
- Create: `src/novel_flywheel/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Produces `MarketService.refresh`, `dashboard`, `list_works`, `match_reference`, `confirm_link`, and `unlink_reference`.

- [ ] Write failing tests using a local Zhihu HTML fixture for parsing, duplicate-work upsert, two-snapshot trends, empty-response safety, title normalization, unique exact match and ambiguous match.
- [ ] Run `pytest tests/test_market.py -q` and verify missing service failures.
- [ ] Implement minimal parser and service with an injected HTTP fetcher.
- [ ] Run the focused tests and verify they pass.

### Task 3: API integration and reference enrichment

**Files:**
- Create: `src/novel_flywheel/api/market.py`
- Modify: `src/novel_flywheel/app.py`
- Modify: `src/novel_flywheel/reference_library.py`
- Test: `tests/api/test_market.py`
- Test: `tests/api/test_references.py`

**Interfaces:**
- Produces `/api/market/dashboard`, `/api/market/works`, `/api/market/refresh`, `/api/market/references/{id}/match`, `/link`, and `/link` DELETE.

- [ ] Write failing API tests for dashboard, refresh, candidate lookup, confirmation, unlinking and public reference enrichment.
- [ ] Run the focused API tests and verify the routes or fields are missing.
- [ ] Register `MarketService`, add the router, and expose market data through reference responses without changing stored text.
- [ ] Run the focused API tests and verify they pass.

### Task 4: Market dashboard and TXT matching UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes the market API and existing reference import API.
- Produces the “市场趋势” navigation page and reference match panel.

- [ ] Write failing console assertions for navigation, filters, update controls, chart containers, boundary copy and match controls.
- [ ] Run `pytest tests/test_console.py -q` and verify the new UI assertions fail.
- [ ] Add semantic markup, state loading, native charts, filters, empty/error states, work table and link confirmation controls.
- [ ] Run the focused console test and verify it passes.

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`

**Interfaces:**
- Documents refresh behavior, safety boundaries, matching workflow and multi-platform extension contract.

- [ ] Update user and maintenance documentation.
- [ ] Run all focused market and reference tests.
- [ ] Run the complete `pytest -q` suite.
- [ ] Review `git diff --check`, `git status --short`, and the implementation against every acceptance criterion.
- [ ] Commit the verified changes and push the current branch.

