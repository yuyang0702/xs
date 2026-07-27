# Reference, Platform, and Publication Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn imported references and the Zhihu Salt short-story target into one understandable, evidence-backed flow from import through generation and publication export.

**Architecture:** Extend existing reference metadata with one classification snapshot, derive usage and trust state through a focused policy module, and reuse the current market links, wizard answers, project metadata, learning artifacts, workflow constraints, and formal manuscript authority. Add a deterministic publication exporter that reads only the formal manuscript and completed review artifacts.

**Tech Stack:** Python, FastAPI, SQLite, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Do not call model APIs during import, classification, matching, routing, export, or tests.
- Do not auto-adopt writing mechanisms or modify formal manuscripts.
- Only `zhihu-salt-short` is a supported platform writing profile in this release.
- User-facing copy must explain meaning and effect in plain Chinese; internal identifiers stay out of primary UI.
- Existing projects, references, market history, model bindings, learning nodes, adoptions, and manuscripts must remain intact.

---

### Task 1: Classification Snapshot and Usage Policy

**Files:**
- Create: `src/novel_flywheel/reference_policy.py`
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/reference_classification.py`
- Modify: `src/novel_flywheel/reference_library.py`
- Test: `tests/test_reference_policy.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Produces `build_classification_snapshot(...) -> dict`, `reference_usage(source, market_context) -> dict`, and `reference_receipt(source, market_match, projects) -> dict`.
- Adds nullable `classification_json` to `reference_sources` through the existing idempotent migration path.

- [ ] Write failing tests for inferred, user-confirmed, market-verified, self-described popular, competitor, tutorial, and platform-rule states.
- [ ] Verify the focused tests fail because the policy module and column do not exist.
- [ ] Implement the smallest policy module and store a snapshot at import and metadata confirmation.
- [ ] Add an idempotent migration test that preserves a legacy row and backfills a readable default snapshot.
- [ ] Run `tests/test_reference_policy.py`, `tests/test_reference_classification.py`, `tests/test_reference_library.py`, and `tests/test_migration.py`.
- [ ] Commit as `feat: add reference trust and usage policy`.

### Task 2: Safe Market Auto-Association and Weighted Cohorts

**Files:**
- Modify: `src/novel_flywheel/market.py`
- Modify: `src/novel_flywheel/api/market.py`
- Test: `tests/test_market.py`
- Test: `tests/test_market_baseline.py`

**Interfaces:**
- Produces `auto_associate_reference(reference_id) -> dict` and adds explainable `weight` and `weight_reasons` to market baseline samples.
- Reuses `reference_market_links`; no new authority table.

- [ ] Write failing tests for unique exact title plus opening match, ambiguous title, no market evidence, self-described popular exclusion, short/long isolation, and ranking-history weighting.
- [ ] Verify RED on existing match-only behavior.
- [ ] Implement auto-confirm only for one high-confidence candidate with both title and opening evidence; otherwise return recommendations.
- [ ] Compute local sample weights from recency, observation days, rank, and interactions while retaining raw sample counts.
- [ ] Run market tests and commit as `feat: safely associate verified market samples`.

### Task 3: Zhihu Salt Short-Story Project Profile

**Files:**
- Create: `src/novel_flywheel/platform_profiles.py`
- Modify: `src/novel_flywheel/wizard.py`
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_platform_profiles.py`
- Test: `tests/test_wizard.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces `resolve_platform_profile(profile_id, project, baseline) -> dict` and project methods to preview/apply a profile with impact details.
- Stores the selected profile and version in `project.json`; constraints receive separate `hard_rules` and `market_advice` sections.

- [ ] Write failing tests for profile selection, preview, safe fallback without a market cohort, inclusion in planning/draft/review context, and platform switching without manuscript writes.
- [ ] Implement the single supported `zhihu-salt-short` profile and clear wizard options.
- [ ] Reuse `market_baseline_key`; recommend rather than force a cohort.
- [ ] Ensure workflow prompts distinguish hard rules from advisory market guidance.
- [ ] Run focused project, wizard, and workflow tests; commit as `feat: add zhihu short story profile`.

### Task 4: Deterministic Zhihu Submission Package

**Files:**
- Create: `src/novel_flywheel/publication.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_publication.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces `preview_zhihu_package(project) -> dict` and `build_zhihu_package(project, metadata) -> dict`.
- Writes versioned files beneath `publication/zhihu/<version>/` and never writes `manuscript/story.md`.

- [ ] Write failing tests for missing formal manuscript, wrong profile, missing user-facing metadata, hash mismatch, successful versioned export, and repeat export history.
- [ ] Implement export from formal manuscript, project metadata, local analysis and latest quality report only.
- [ ] Add preview and create API endpoints with plain validation messages.
- [ ] Verify the exported manuscript hash equals the formal manuscript hash and no model gateway is touched.
- [ ] Run publication tests; commit as `feat: export zhihu submission packages`.

### Task 5: Import Receipt and Human-Centered UI

**Files:**
- Modify: `src/novel_flywheel/api/references.py`
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `README.md`
- Test: `tests/api/test_references.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Reference responses expose `classification`, `usage`, and `import_receipt` objects.
- UI renders one responsive result band with status, evidence, purpose, next step, Token effect, and direct actions.

- [ ] Write failing API and static UI tests for readable labels and action availability.
- [ ] Add import receipt data to reference responses and run local market auto-association after import without blocking a successful TXT save.
- [ ] Render compact result band, trust badge, usage list, next-step actions, match confirmation/undo, profile summary, platform-impact confirmation, and publication export form.
- [ ] Use stable responsive grids, visible working/success/failure states, and no nested cards or technical field names.
- [ ] Update README with the complete behavior and safety boundaries.
- [ ] Run focused API/UI tests and commit as `feat: connect reference import to publication`.

### Task 6: Complete Verification and Delivery

**Files:**
- Verify all changed files and runtime state.

- [ ] Run `.venv/Scripts/python.exe -m pytest -q` and require zero failures.
- [ ] Run `git diff --check` and static JavaScript checks available in the workspace.
- [ ] Confirm no queued/running/cancelling work before restart.
- [ ] Restart the service, verify `/api/health`, and inspect desktop/mobile UI using the available browser if possible.
- [ ] Commit any verification-driven corrections, push `main`, and verify local and remote hashes match.
