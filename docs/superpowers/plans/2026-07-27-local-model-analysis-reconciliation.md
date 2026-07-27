# Local And Model Analysis Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge local extraction and model review into traceable candidate records with Chinese-only user-facing output and a clearer learning-library interface.

**Architecture:** Reuse `learning_nodes.data_json` to store provenance and model review details. Run cached local extraction before full model analysis, let synthesis reference local candidate IDs, update matched nodes in place, and save only unmatched findings as model-only nodes. Render the normalized provenance through the existing candidate cards.

**Tech Stack:** Python 3.12, FastAPI, SQLite JSON data, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Do not add a database table, model role, dependency, or parallel candidate workflow.
- All model-generated user-facing fields must be Simplified Chinese or be rejected before storage.
- Preserve local confidence, model verdict, evidence, and user decision as separate facts.
- Full model analysis must remain able to discover findings absent from local extraction.
- Never auto-adopt a model conclusion or modify existing prose, formal outlines, or locked project facts.
- Work in the current checkout because this feature depends on the existing uncommitted learning-library changes; do not stage or commit unrelated user work.

---

### Task 1: Provenance Contract

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Test: `tests/test_learning_system.py`
- Test: `tests/api/test_learning.py`

**Interfaces:**
- Produces: mechanism `data.analysis_origin` values `local`, `model`, or `hybrid`
- Produces: public `analysis` with `state`, `local`, `model`, and `source_title`

- [ ] Add failing tests proving local mechanisms expose `local_only`, historical mechanisms are inferred safely, and source titles are returned.
- [ ] Run the focused tests and confirm they fail because provenance is absent.
- [ ] Store local provenance and derive one public analysis summary without changing the schema.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Independent Model Review And Reconciliation

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Test: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: local mechanism IDs from cached `analyze_reference`
- Produces: `model_review.verdict` values `confirmed`, `rejected`, `uncertain`, or `new`

- [ ] Add failing tests for independent-first prompts, Chinese output requirements, matched-node updates, model-only findings, and rejection of English visible fields.
- [ ] Run the focused tests and confirm failures come from the missing reconciliation behavior.
- [ ] Include compact local candidates in synthesis, validate returned IDs and Chinese fields, update matches in place, and deduplicate exact model-only findings.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Plain-Chinese Candidate Interface

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: mechanism `analysis` summaries
- Produces: provenance badges, source filter, readable confidence states, Chinese fallbacks, and analysis-scope guidance

- [ ] Add failing console tests for source badges, Chinese fallback handling, model-result labeling, and the provenance filter.
- [ ] Run the focused tests and confirm the new UI contract is missing.
- [ ] Update the existing cards and learning page using native HTML/CSS controls without adding another page or modal.
- [ ] Run console tests and JavaScript syntax validation.

### Task 4: Regression And Visual Verification

**Files:**
- Modify only files required by failures found during verification.

- [ ] Run learning, API, and console test groups.
- [ ] Run the complete pytest suite, Python compilation, JavaScript syntax validation, and `git diff --check`.
- [ ] Restart the local service and verify desktop and 375 px mobile layouts in the browser.
- [ ] Confirm browser errors are empty and leave `http://127.0.0.1:8765` open for the user.
