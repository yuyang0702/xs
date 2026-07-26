# Evidence-Driven Quality Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect local reference evidence, ranking cohorts, project guidance, narrative relations, and issue reconciliation into one quality-improvement loop.

**Architecture:** Extend the existing SQLite-backed learning and market services with focused analysis modules. Persist versioned artifacts through existing project learning and run-output paths, then expose compact APIs and UI sections without creating another authoritative workflow.

**Tech Stack:** Python 3.12, FastAPI, SQLite, deterministic regex/statistical analysis, optional existing LTP worker, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Do not add a model role, provider dependency, vector database, or local generative model.
- Market observations are advisory and never block writing or publication by themselves.
- StoryState and Runtime remain authoritative; models and LTP cannot write formal manuscripts.
- Preserve the first complete final review and all existing conservative full-review triggers.
- Do not call paid APIs from tests.
- Schema changes must be additive and idempotent.

---

### Task 1: Reference windows, folded evidence, and rejected deletion

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_learning_system.py`
- Test: `tests/api/test_learning.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Produces: `LearningSystem.analyze_reference()` coverage metadata and folded mechanisms with multiple evidence rows.
- Produces: `LearningSystem.delete_rejected_nodes(node_ids: list[str]) -> dict`.

- [ ] Write failing tests for sentence-safe windows on single-line text, complete coverage, repeated mechanism evidence folding, adopted-node deletion protection, and rejected batch deletion.
- [ ] Run the focused tests and confirm failure because the new behavior and API do not exist.
- [ ] Implement boundary-safe windows, multi-match extraction, fold keys, coverage calculation, and analyzer-version cache invalidation.
- [ ] Implement rejected-node deletion in one SQLite transaction with adoption checks and explicit skipped IDs.
- [ ] Add the delete endpoint and compact coverage/evidence UI with rejected multi-select actions.
- [ ] Run focused learning, API, and console tests until green.

### Task 2: Market cohort baseline service

**Files:**
- Create: `src/novel_flywheel/market_baseline.py`
- Modify: `src/novel_flywheel/market.py`
- Modify: `src/novel_flywheel/api/market.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_market_baseline.py`
- Test: `tests/api/test_market.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Produces: `MarketBaselineService.list_cohorts()` and `build_baseline(cohort_key)`.
- Consumes: confirmed `reference_market_links`, market history, and folded local mechanisms.

- [ ] Write failing tests for cohort isolation, one-work-one-vote deduplication, date range, unknown-field isolation, and 5/10 sample thresholds.
- [ ] Run focused tests and confirm the service is absent.
- [ ] Implement deterministic aggregation with descriptive outputs and no popularity prediction.
- [ ] Expose cohort list and detail APIs with platform/ranking/category/length filters.
- [ ] Add a Market Trends baseline view showing sample scope, confidence level, common ranges, and supporting works.
- [ ] Run focused market and console tests until green.

### Task 3: Advisory baseline in project creation and analysis

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/wizard.py`
- Modify: `src/novel_flywheel/api/wizards.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Modify: `src/novel_flywheel/manuscript_analysis.py`
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/static/app.js`
- Test: `tests/test_db.py`
- Test: `tests/test_wizard.py`
- Test: `tests/test_manuscript_analysis.py`
- Test: `tests/api/test_wizards.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces: versioned `market_baseline` project learning artifact.
- Produces: `baseline_comparison` inside manuscript analysis while preserving raw metrics.

- [ ] Write failing migration tests and project-isolation tests for selected cohort metadata and stale artifact behavior.
- [ ] Write failing wizard tests for automatic recommendation, explicit override, and disabled guidance.
- [ ] Write failing manuscript-analysis tests for advisory comparisons that never create blocking findings.
- [ ] Implement additive persistence and project artifact creation through existing learning storage.
- [ ] Pass a compact baseline summary into project constraints and planning context.
- [ ] Add wizard and outline-check UI with a visible enable switch, provenance, and non-blocking deviation copy.
- [ ] Run focused database, wizard, project, and manuscript tests until green.

### Task 4: Narrative ledger and scene state changes

**Files:**
- Create: `src/novel_flywheel/narrative_ledger.py`
- Modify: `src/novel_flywheel/manuscript_analysis.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_narrative_ledger.py`
- Test: `tests/test_manuscript_analysis.py`
- Test: `tests/test_workflows.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces: `build_narrative_ledger(text, nlp=None) -> dict` bound to manuscript hash.
- Produces: compact unresolved and important-uncertainty evidence for existing `final_review` prompts.

- [ ] Write failing tests for explicit question/answer links, setup/payoff candidates, scene entry/exit state changes, stable offsets, and manuscript hashes.
- [ ] Write failing workflow tests proving important uncertainty reaches existing final review while ordinary local relations do not create extra model calls.
- [ ] Implement deterministic ledger extraction and optional LTP evidence composition.
- [ ] Add ledger output to canonical manuscript analysis and final-review evidence summaries.
- [ ] Add a workbench timeline with unresolved-first filtering and expandable source evidence.
- [ ] Run focused ledger, manuscript, workflow, API, and console tests until green.

### Task 5: Stable issue reconciliation through revision

**Files:**
- Modify: `src/novel_flywheel/quality.py`
- Modify: `src/novel_flywheel/revision.py`
- Modify: `src/novel_flywheel/incremental_review.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_quality.py`
- Test: `tests/test_revision.py`
- Test: `tests/test_incremental_review.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Produces: stable deterministic issue IDs and status transitions.
- Consumes: structured polish diffs, full local analysis, narrative ledger, and prior issue ledger.

- [ ] Write failing tests that normalize review issues to stable IDs and reject omitted prior issues.
- [ ] Write failing tests that link revision tasks and changed ranges to attempted issue IDs.
- [ ] Write failing tests for local revalidation, related-window selection, new-issue creation, and complete-review fallback.
- [ ] Implement issue normalization and persistence in quality reports.
- [ ] Extend revision and incremental evidence contracts without changing formal-write authority.
- [ ] Add a quality-report issue table with status, evidence, repair goal, attempted changes, verification, and review scope.
- [ ] Run focused quality, revision, workflow, and console tests until green.

### Task 6: Documentation, compatibility, and release verification

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`
- Modify: `docs/superpowers/specs/2026-07-27-evidence-driven-quality-loop-design.md`

**Interfaces:**
- Consumes all prior task interfaces.
- Produces operator documentation and verified backward compatibility.

- [ ] Update README and maintenance documentation with analysis versions, cache invalidation, UI states, fallback rules, and deletion behavior.
- [ ] Run focused regression suites for each task.
- [ ] Run the complete test suite and record the exact passing count.
- [ ] Inspect `git diff --check`, `git status`, and the final diff for unrelated or sensitive changes.
- [ ] Start the console only after confirming no run is queued, running, or cancelling; visually verify desktop and mobile layouts.
- [ ] Commit the scoped changes and push the current branch.
