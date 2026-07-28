# Quality V2 And User Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a hash-safe quality v2 workflow, explainable quality workspace, user-confirmed calibration references, and protected passages for Zhihu short stories.

**Architecture:** Add focused quality record and control services around the existing workflow instead of creating a competing state store. Extend existing review JSON and candidate APIs, keep Runtime authoritative, and render the richer state in the current candidate-quality section with progressive disclosure.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, vanilla JavaScript, HTML, CSS.

## Global Constraints

- Preserve existing novels, credentials, model bindings, Skills, run history, references, StoryState, and formal manuscripts.
- Do not call paid model APIs from tests.
- `zhihu-short-v2` uses commercial/story/prose weights 40/40/20 and plain Chinese UI copy.
- Reference confirmation and protected-passage management do not call models.
- Existing projects without the profile keep the legacy scoring path.
- Every workflow behavior change updates `README.md` or `docs/maintenance.md`.

---

### Task 1: Quality Profile And Promotion Policy

**Files:**
- Create: `src/novel_flywheel/quality_profiles.py`
- Modify: `src/novel_flywheel/quality.py`
- Test: `tests/test_quality_profiles.py`

**Interfaces:**
- Produces: `profile_for_project(project)`, `score_review(review, profile_id)`, `quality_outcome_for_profile(review, profile_id)`, `compare_quality_candidates(best, candidate)`.

- [ ] Write tests for literal v2 criterion aggregation, thresholds, two-point tolerance, dimension regression, hard blockers, and incompatible judge/profile signatures.
- [ ] Run `pytest tests/test_quality_profiles.py -q` and confirm the missing module and behavior fail.
- [ ] Implement immutable profile definitions and pure scoring/comparison helpers.
- [ ] Run `pytest tests/test_quality_profiles.py tests/test_quality.py -q` and confirm they pass.

### Task 2: Quality Checkpoint And Legacy Reconciliation

**Files:**
- Create: `src/novel_flywheel/quality_records.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_quality_records.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: `load_quality_checkpoint(run_path)`, `reconcile_legacy_checkpoint(run_path)`, `write_quality_checkpoint(run_path, checkpoint)`, and candidate resolution through the protected checkpoint.

- [ ] Write tests that select `historical-best-64.75.md` over a 58.35 best candidate, preserve every file, and bind the selected hash and legacy profile.
- [ ] Write workflow tests proving success cannot return or formalize a lower comparable candidate and a regression retries from the best with its matching review.
- [ ] Run focused tests and confirm they fail for the current tuple-only checkpoint behavior.
- [ ] Implement idempotent checkpoint reconciliation and workflow promotion/return behavior.
- [ ] Run focused record, workflow, and project API tests.

### Task 3: Stable Issue Summary And Official Word Count

**Files:**
- Create: `src/novel_flywheel/quality_summary.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Modify: `src/novel_flywheel/publication.py`
- Test: `tests/test_quality_summary.py`
- Test: `tests/api/test_projects.py`
- Test: `tests/test_publication.py`

**Interfaces:**
- Produces: `effective_han_characters(text)`, `merge_quality_issues(report)`, `build_quality_summary(project, run_id, text, report)`.

- [ ] Write tests for Markdown/internal-marker removal, duplicate issue merging, stable ids, Chinese positions, manuscript state, and hash-matched formal/package blockers.
- [ ] Run focused tests and confirm current APIs lack the summary and use divergent controls.
- [ ] Implement summary aggregation and one publication authority payload.
- [ ] Run focused summary, API, and publication tests.

### Task 4: Reference Group Persistence And Recommendations

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Create: `src/novel_flywheel/quality_references.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_db.py`
- Test: `tests/test_quality_references.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces: versioned `quality_reference_groups` storage and service methods `recommend`, `confirm`, `list_group`, `remove`, and `history`.

- [ ] Write an idempotent migration test and service tests for balanced recommendations, explicit confirmation, rejection, history, and source preservation.
- [ ] Run focused tests and confirm the table and endpoints are absent.
- [ ] Add the minimal schema, database methods, recommendation service, and project-scoped API endpoints.
- [ ] Run focused database, service, and API tests.

### Task 5: Protected Passage Controls And Revision Validation

**Files:**
- Create: `src/novel_flywheel/passage_protection.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/revision.py`
- Test: `tests/test_passage_protection.py`
- Test: `tests/test_revision.py`
- Test: `tests/api/test_projects.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: paragraph-boundary validation, versioned `passage.*` story locks, soft/exact validation, allow-next-change state, and conflict metadata.

- [ ] Write tests for paragraph-only selection, soft punctuation tolerance, exact matching, inactive locks, allow-next-change, and rejected model changes.
- [ ] Run focused tests and confirm passage behavior is absent.
- [ ] Implement lock service/API and add applicable lock context plus deterministic validation to polish segments.
- [ ] Run focused passage, revision, API, and workflow tests.

### Task 6: Review Prompt And Workflow V2 Integration

**Files:**
- Modify: `src/novel_flywheel/prompts.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/incremental_review.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_incremental_review.py`

**Interfaces:**
- Consumes: quality profile, checkpoint, stable issues, and passage locks.
- Produces: criteria/evidence review JSON, matching baseline source, versioned summary/checkpoint, and Chinese events.

- [ ] Write tests proving v2 context requests criterion evidence, incremental baseline matches the revised best hash, and protected conflicts preserve the source.
- [ ] Run focused tests and confirm current prompt and baseline behavior fail them.
- [ ] Integrate profile scoring, matching issue ledger, correct baseline selection, and checkpoint writes.
- [ ] Run focused workflow and incremental review tests.

### Task 7: Progressive Quality Workspace UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/style.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: enriched candidate summary, reference endpoints, protected passage endpoints, and publication authority.
- Produces: one compact default workspace with expandable scores, issues, reference management, full manuscript preview, locks, history, and actionable states.

- [ ] Write console contract tests for Chinese labels, summary hierarchy, disabled-action reasons, reference drawer, manuscript preview, and protected passage controls.
- [ ] Run `pytest tests/test_console.py -q` and confirm the new controls are absent.
- [ ] Implement the progressive markup, plain-Chinese rendering, stable buttons, and responsive styles without adding a top-level page.
- [ ] Run console and related API tests.

### Task 8: Documentation, Migration Verification, And Visual QA

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`
- Test: complete suite

**Interfaces:**
- Produces: operator documentation, rollback notes, and verified desktop behavior.

- [ ] Document profile selection, legacy checkpoint reconciliation, reference boundaries, passage conflicts, official word count, and rollback.
- [ ] Run focused quality, workflow, project API, publication, database, and console tests.
- [ ] Run the complete pytest suite and `git diff --check`.
- [ ] Start the updated local service only after confirming no run is active.
- [ ] Inspect desktop and mobile layouts in the browser, exercise expand/collapse and disabled states, and verify no English or overlapping controls remain.
- [ ] Review the final diff for credentials and unrelated changes before committing.
