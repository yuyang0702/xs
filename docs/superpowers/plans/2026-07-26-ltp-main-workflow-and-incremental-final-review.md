# LTP Main Workflow and Incremental Final Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing LTP backend to the complete manuscript workflow and replace repeated correction-round full reviews with safe changed, adjacent, and related-window review plus deterministic full-review fallback.

**Architecture:** Add one local manuscript-analysis boundary and one incremental-review boundary, both producing versioned JSON artifacts under the existing run output tree. `WorkflowService` remains the orchestrator, existing model roles remain unchanged, StoryState remains authoritative, and the current `_full_manuscript_review` method remains the mandatory fallback.

**Tech Stack:** Python 3.11, FastAPI, SQLite, existing LTP 4.x worker, standard-library hashing/diff/JSON/regex, vanilla JavaScript console, pytest.

## Global Constraints

- Deliver every optimization row in the approved design in this implementation.
- Do not add a model role, provider protocol, vector database, graph service, local generative model, or training pipeline.
- Preserve all existing role bindings, provider fallbacks, credentials, Skills, StoryState data, run history, candidates, and formal manuscripts.
- LTP evidence is advisory; StoryState remains authoritative.
- The first terminal final review always covers 100% of the manuscript.
- Missing, stale, invalid, degraded, or ambiguous incremental evidence always falls back to the existing full final review.
- Originality reporting is limited to locally available project manuscripts, imported references, and selected learning-library material.
- Models and NLP workers never write formal manuscripts directly.
- Run focused tests first and the complete suite before completion.

---

## File Structure

- Create `src/novel_flywheel/manuscript_analysis.py`: canonical local full-text analysis, opening diagnostics, LTP normalization, local originality candidate screening, compact review summary, and artifact serialization.
- Create `src/novel_flywheel/incremental_review.py`: baseline representation, old/new window mapping, structured polish diff, related-window selection, full-review triggers, and deterministic incremental gate.
- Modify `src/novel_flywheel/nlp_backend.py`: expose a stable backend version and include it in cache identity/results.
- Modify `src/novel_flywheel/workflows.py`: call full analysis at required scan points, enrich `review`, record polish diffs, preserve the first baseline, route later rounds through incremental or full review, and account for tokens/scope.
- Modify `src/novel_flywheel/api/projects.py`: reuse or refresh hash-matching local analysis at candidate view/publication and block stale or failed gates.
- Modify `src/novel_flywheel/api/learning.py`: expose project-scoped workflow enable/disable state without changing global LTP lifecycle controls.
- Modify `src/novel_flywheel/projects.py`: persist the reversible project-scoped workflow flag in existing project metadata.
- Modify `src/novel_flywheel/static/index.html`: add the project-scoped optimized-analysis control and incremental-review evidence labels.
- Modify `src/novel_flywheel/static/app.js`: load/update the project flag and display scan, fallback, coverage, related-window, and token evidence.
- Modify `src/novel_flywheel/static/app.css`: style the bounded evidence display using existing console primitives.
- Modify `README.md` and `docs/maintenance.md`: document activation, fallback, artifacts, originality limits, and recovery.
- Modify `docs/superpowers/specs/2026-07-26-ltp-main-workflow-and-incremental-final-review-design.md`: record any implementation-level contract clarifications without changing scope.
- Create `tests/test_manuscript_analysis.py`: deterministic analysis, LTP normalization/fallback/cache, and originality tests.
- Create `tests/test_incremental_review.py`: mapping, relation selection, thresholds, and gate tests.
- Modify `tests/test_workflows.py`: end-to-end role scope, first full review, incremental correction review, and fallback tests.
- Modify `tests/test_projects.py` and `tests/api/test_projects_api.py` if present; otherwise use the existing project API test module discovered by `rg --files tests`: project flag and publication-gate tests.
- Modify `tests/test_console.py`: visible project control and evidence rendering contract.
- Modify `tests/test_nlp_backend.py`: versioned cache and degraded result contract.

---

### Task 1: Versioned Local Manuscript Analysis

**Files:**
- Create: `src/novel_flywheel/manuscript_analysis.py`
- Modify: `src/novel_flywheel/nlp_backend.py`
- Create: `tests/test_manuscript_analysis.py`
- Modify: `tests/test_nlp_backend.py`

**Interfaces:**
- Consumes: `prose_quality.analyze_prose(text)`, `quality.review_windows(text)`, and `LocalNLPManager.analyze(text)`.
- Produces:
  - `ANALYSIS_VERSION: str`
  - `analyze_manuscript(text: str, *, nlp_analyze: Callable[[str], dict] | None, comparison_sources: list[dict[str, str]] = []) -> dict`
  - `compact_analysis(report: dict, *, max_findings: int = 12) -> dict`
  - `analysis_matches(report: dict, text: str) -> bool`
  - `LocalNLPManager.BACKEND_VERSION: str`

- [ ] **Step 1: Write failing deterministic full-analysis tests**

```python
def test_analysis_covers_complete_text_and_opening_zone():
    text = "第一行。\n第二行。\n第三行。\n\n林晚发现门锁被换了。" + "中段事件。" * 700
    report = analyze_manuscript(text, nlp_analyze=None)
    assert report["text_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert report["coverage"] == 1.0
    assert report["opening"]["first_three_lines"]
    assert report["opening"]["zone_characters"] == min(500, len(text))
    assert report["windows"][-1]["end"] == len(text)


def test_analysis_normalizes_ltp_entities_events_and_relations():
    fake = lambda text: {
        "backend": "ltp",
        "available": True,
        "backend_version": "ltp-v2",
        "result": {
            "cws": [["林晚", "打开", "木盒"]],
            "pos": [["nh", "v", "n"]],
            "ner": [[["Nh", 0, 0]]],
            "srl": [[[(1, [("A0", 0, 0), ("A1", 2, 2)])]]],
            "dep": [[{"head": [2, 0, 2], "label": ["SBV", "HED", "VOB"]}]],
        },
    }
    report = analyze_manuscript("林晚打开木盒。", nlp_analyze=fake)
    assert report["nlp"]["available"] is True
    assert any(item["text"] == "林晚" for item in report["entities"])
    assert report["events"]
```

- [ ] **Step 2: Run the new tests and verify missing interfaces fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_manuscript_analysis.py tests/test_nlp_backend.py
```

Expected: collection or import failure for `novel_flywheel.manuscript_analysis`.

- [ ] **Step 3: Implement the canonical report with standard-library rules**

Implement `analyze_manuscript` to:

- hash the exact input;
- reuse `review_windows` for complete paragraph-aligned coverage;
- call `analyze_prose` once on the complete text;
- calculate first-three-line and first-500-character signals;
- extract exact continuous repeated passages with conservative six-Han-character minimum and location pairs;
- extract person-name candidates from LTP NER and conservative local patterns;
- normalize LTP `cws`, `pos`, `ner`, `srl`, and `dep` shapes without assuming GPU or persistent workers;
- create evidence candidates for entities, actions/events, semantic roles, goals/conflicts/anomalies, scene changes, time expressions, questions/promises, and setup/payoff keywords;
- preserve `nlp.available=False` and its reason instead of raising;
- return `coverage=1.0` only when the final window ends at `len(text)`;
- keep every finding tied to start/end offsets or a review-window index.

- [ ] **Step 4: Implement local-corpus originality candidates**

For `comparison_sources=[{"id": ..., "title": ..., "text": ...}]`, produce only:

```python
{
    "continuous_passages": [
        {"source_id": "...", "manuscript_start": 10, "source_start": 24,
         "text": "连续相似文本", "characters": 8}
    ],
    "similar_names": [
        {"source_id": "...", "manuscript_name": "林知晚",
         "source_name": "林之晚", "similarity": 0.833}
    ],
    "semantic_candidates": [
        {"kind": "setting|key_plot|distinctive_expression",
         "source_id": "...", "manuscript_window": 2, "source_excerpt": "...",
         "shared_terms": ["..."], "requires_model_review": True}
    ],
    "scope": "local_corpus_only",
}
```

Use `difflib.SequenceMatcher` for name similarity and bounded keyword/signature overlap for semantic candidate retrieval. Do not label a candidate plagiarism or infringement.

- [ ] **Step 5: Version the LTP cache contract**

Set `LocalNLPManager.BACKEND_VERSION = "ltp-v2"`, use it in the cache digest, and include `backend_version` in successful and degraded results. Preserve the independent subprocess, 300-second timeout, and rule fallback.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_manuscript_analysis.py tests/test_nlp_backend.py tests/test_prose_quality.py tests/test_local_editorial.py
```

Expected: all pass without provider calls.

- [ ] **Step 7: Commit**

```powershell
git add src/novel_flywheel/manuscript_analysis.py src/novel_flywheel/nlp_backend.py tests/test_manuscript_analysis.py tests/test_nlp_backend.py
git commit -m "feat: add versioned full manuscript analysis"
```

---

### Task 2: Incremental Review Mapping, Relations, and Safety Gate

**Files:**
- Create: `src/novel_flywheel/incremental_review.py`
- Create: `tests/test_incremental_review.py`

**Interfaces:**
- Consumes: analysis reports from Task 1 and `quality.review_windows`.
- Produces:
  - `build_review_baseline(manuscript: str, analysis: dict, evidence: list[dict], review: dict) -> dict`
  - `diff_manuscripts(before: str, after: str, before_analysis: dict, after_analysis: dict) -> dict`
  - `select_review_scope(baseline: dict, current_analysis: dict, changes: dict) -> dict`
  - `requires_full_review(scope: dict, changes: dict, current_analysis: dict) -> tuple[bool, list[str]]`
  - `apply_incremental_gate(review: dict, baseline: dict, scope: dict, current_analysis: dict, reconciliations: list[dict]) -> tuple[dict, list[str]]`

- [ ] **Step 1: Write failing scope-selection tests**

```python
def test_small_prose_change_selects_changed_adjacent_and_shared_entity_windows():
    baseline = baseline_fixture(["林晚进入仓库。", "周衡留在车里。", "林晚打开木盒。", "第二天离开。"])
    current = current_fixture(["林晚走进仓库。", "周衡留在车里。", "林晚打开木盒。", "第二天离开。"])
    changes = diff_manuscripts(baseline["manuscript"], current["text"],
                               baseline["analysis"], current)
    scope = select_review_scope(baseline, current, changes)
    assert 1 in scope["selected_windows"]
    assert 2 in scope["selected_windows"]
    assert 3 in scope["selected_windows"]
    assert "changed" in scope["reasons"]["1"]
    assert "shared_entity:林晚" in scope["reasons"]["3"]


def test_structural_change_requires_full_review():
    changes = {"changed_ratio": 0.08, "event_order_changed": True,
               "changed_entities": [], "changed_events": []}
    required, reasons = requires_full_review({"selected_ratio": 0.2}, changes,
                                             {"nlp": {"available": True}})
    assert required is True
    assert "event_order_changed" in reasons
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_incremental_review.py
```

Expected: import failure for `novel_flywheel.incremental_review`.

- [ ] **Step 3: Implement conservative old/new window mapping**

Map windows in this order:

1. exact content hash;
2. paragraph-anchor overlap;
3. character-range overlap;
4. shared entity and event signatures.

Return explicit `unmapped_old`, `unmapped_new`, and `ambiguous` arrays. Never silently map one old window to multiple incompatible new windows.

- [ ] **Step 4: Implement structured manuscript and polish diff**

Use `difflib.SequenceMatcher.get_opcodes()` to record changed ranges and ratios. Compare normalized analysis evidence to record added/removed entities, events, time candidates, causal candidates, questions, promises, setups, and payoffs.

- [ ] **Step 5: Implement related-window selection**

Always select:

- changed windows;
- immediate previous and next windows;
- windows sharing changed entities or salient objects;
- windows linked by event/cause/consequence signatures;
- setup/payoff and question/answer partners;
- opening, climax, or ending protection windows when implicated.

Every selected window must have at least one reason in `scope["reasons"]`.

- [ ] **Step 6: Implement mandatory full-review triggers**

Return full-review reasons for:

- `changed_ratio > 0.20`;
- `selected_ratio > 0.40`;
- scene/event order changes;
- principal-character goal, motivation, identity, knowledge, or ending changes;
- key character/event/reversal/setup/payoff additions or removals;
- opening promise, climax, or ending changes;
- cross-window timeline/causal changes;
- unavailable/degraded LTP;
- incomplete or ambiguous mapping;
- a new local blocking issue;
- missing baseline/receipts;
- explicit reviewer request for broader evidence.

- [ ] **Step 7: Implement the deterministic incremental gate**

Reject incremental approval when:

- current text hash differs from the analyzed hash;
- a changed range has no recorded polish change;
- any prior issue lacks reconciliation;
- a related changed entity/event/setup/payoff lacks reviewed evidence;
- a revision check fails;
- a new blocking prose finding exists;
- scope or baseline coverage is incomplete.

Return machine-readable gate reasons and use the existing review normalization conventions.

- [ ] **Step 8: Run focused tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_incremental_review.py tests/test_quality.py tests/test_revision.py
```

Expected: all pass.

Commit:

```powershell
git add src/novel_flywheel/incremental_review.py tests/test_incremental_review.py
git commit -m "feat: add safe incremental review scope"
```

---

### Task 3: Project-scoped Activation and Local Comparison Corpus

**Files:**
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Modify: `src/novel_flywheel/reference_library.py`
- Modify: existing project and learning API test modules found with `rg --files tests`

**Interfaces:**
- Consumes: existing project metadata persistence and `ReferenceLibrary.read_text`.
- Produces:
  - project metadata key `optimized_local_review_enabled: bool`
  - `GET /api/projects/{project_id}/learning/workflow-analysis`
  - `PUT /api/projects/{project_id}/learning/workflow-analysis`
  - `ReferenceLibrary.comparison_sources(project_id: str | None = None) -> list[dict[str, str]]`

- [ ] **Step 1: Write failing API and persistence tests**

```python
def test_project_analysis_flag_is_reversible_and_preserves_other_metadata(client, project):
    response = client.put(
        f"/api/projects/{project.id}/learning/workflow-analysis",
        json={"enabled": True},
    )
    assert response.json()["enabled"] is True
    saved = client.get(f"/api/projects/{project.id}").json()
    assert saved["metadata"]["optimized_local_review_enabled"] is True
```

Also assert disabling keeps learning artifacts, manuscripts, StoryState revision, and role bindings unchanged.

- [ ] **Step 2: Run the focused API tests and verify failure**

Run the exact discovered test module, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_learning.py tests/test_projects.py
```

Expected: 404 for the new endpoint or missing metadata key.

- [ ] **Step 3: Implement project-scoped activation**

Use the existing project metadata write path. Do not add a new database authority. New projects default to `False`; existing project files remain unchanged until the user enables the feature.

- [ ] **Step 4: Implement bounded local comparison-source assembly**

Return:

- imported reference text with stable source/version IDs;
- prior run drafts and best candidates for the selected project;
- the existing formal manuscript only when it is not byte-identical to the candidate.

Deduplicate by SHA-256 and impose a documented total character cap before analysis. Never access the internet.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_learning.py tests/api/test_references.py tests/test_projects.py tests/test_story_state.py
git add src/novel_flywheel/projects.py src/novel_flywheel/api/learning.py src/novel_flywheel/reference_library.py tests
git commit -m "feat: add project-scoped optimized review control"
```

Before committing, stage only files changed by this task rather than every file under `tests`.

---

### Task 4: Connect Analysis to Draft, Review, and Polish

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `tests/test_workflows.py`
- Modify: `tests/test_context_policy.py`

**Interfaces:**
- Consumes: `analyze_manuscript`, `compact_analysis`, `analysis_matches`, and `diff_manuscripts`.
- Produces:
  - `WorkflowService._analyze_manuscript(...) -> dict`
  - run artifacts `outputs/analysis-draft.json`, `outputs/analysis-polish.json`, and `outputs/analysis-polish-N.json`
  - structured polish checkpoint field `change_evidence`

- [ ] **Step 1: Write failing workflow tests**

Add tests proving:

- complete analysis runs after the assembled draft;
- `review` still receives `LABELED EXCERPTS`, not the complete manuscript;
- `review` additionally receives `LOCAL FULL MANUSCRIPT SUMMARY`;
- `reader_review` prompt is unchanged;
- analysis runs after initial polish and each correction;
- identical text reuses the analysis artifact;
- every accepted/retried/preserved polish segment records structured change evidence.

- [ ] **Step 2: Run targeted tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflows.py tests/test_context_policy.py -k "local_analysis or review_summary or polish_change"
```

Expected: missing artifacts and prompt marker assertions fail.

- [ ] **Step 3: Inject the existing LocalNLPManager into WorkflowService**

Extend constructor injection with an optional `local_nlp` and reference source provider. Update `create_app` to pass `app.state.local_nlp` and `app.state.references`. Preserve test construction with rule-only defaults.

- [ ] **Step 4: Add hash-matching analysis artifact reuse**

`_analyze_manuscript` must:

- load an artifact only when text hash, analysis version, and LTP backend version match;
- otherwise run complete local analysis;
- write with `atomic_write`;
- add distinct run events for local completion, LTP completion, LTP degradation, and cache reuse.

- [ ] **Step 5: Enrich only the editorial review prompt**

Append a bounded `compact_analysis(report)` JSON block to the existing excerpt input. Assert the exact draft body outside labeled excerpts is not added.

- [ ] **Step 6: Record structured polish changes**

After every candidate assessment, call `diff_manuscripts` for the source and candidate segment analyses and persist it in the existing checkpoint JSON. Preserved source segments record an empty accepted diff and the rejection reasons.

- [ ] **Step 7: Analyze after every assembled revision**

Run or reuse complete analysis:

- after draft assembly;
- after initial polish assembly;
- after every structural correction assembly.

Do not call LTP once per tiny polish segment; segment diffs may use normalized local evidence while full LTP runs once on the assembled candidate.

- [ ] **Step 8: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflows.py tests/test_context_policy.py tests/test_manuscript_analysis.py -k "local_analysis or review or reader or polish"
git add src/novel_flywheel/app.py src/novel_flywheel/workflows.py src/novel_flywheel/context_policy.py tests/test_workflows.py tests/test_context_policy.py
git commit -m "feat: connect local analysis to writing workflow"
```

---

### Task 5: Preserve First Full Review and Add Incremental Correction Review

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/quality.py`
- Modify: `tests/test_workflows.py`
- Modify: `tests/test_quality.py`

**Interfaces:**
- Consumes: all Task 2 interfaces and Task 4 analysis artifacts.
- Produces:
  - `outputs/final-review-baseline.json`
  - `outputs/incremental-review-N.json`
  - `WorkflowService._incremental_manuscript_review(...) -> tuple[dict, dict]`
  - additive `quality-report.json["review_scope_history"]`

- [ ] **Step 1: Write failing first-review preservation tests**

Assert:

- first review of a long short story still calls `final_review` once per complete window plus adjudication;
- first-review coverage remains `1.0`;
- baseline hashes, window evidence, issue ledger, reconciliations, and receipts are saved;
- no `planning` or new role is called.

- [ ] **Step 2: Write failing incremental-review tests**

Use a manuscript with at least six review windows. Change prose only in one middle window and assert:

- the second terminal review does not call every window;
- changed, previous, next, and a distant shared-entity window are called;
- every called window has a reason;
- final adjudication uses baseline and current selected evidence;
- all prior issues require reconciliation.

- [ ] **Step 3: Write failing mandatory fallback tests**

Parametrize:

```python
[
    "changed_ratio",
    "selected_ratio",
    "event_order_changed",
    "opening_promise_changed",
    "ending_changed",
    "ltp_unavailable",
    "ambiguous_mapping",
    "new_blocking_issue",
    "reviewer_requested_full",
]
```

For each condition, assert the correction round calls the existing complete `_full_manuscript_review`, records the reason, and never accepts an incremental result.

- [ ] **Step 4: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflows.py tests/test_quality.py -k "first_review_baseline or incremental or mandatory_full"
```

- [ ] **Step 5: Persist the first immutable baseline**

After the first valid `_full_manuscript_review`, combine the manuscript, complete analysis, window evidence, normalized review, issue ledger, coverage, and model receipts into `final-review-baseline.json`. Never overwrite it for the same base manuscript revision.

- [ ] **Step 6: Implement incremental window evidence extraction**

Call the existing `final_review` role for each selected current window using:

- selection reasons;
- previous baseline summary;
- related baseline evidence;
- local/LTP change evidence;
- prior issue ledger.

Require the same structured evidence fields as full review and reject empty summaries.

- [ ] **Step 7: Implement incremental adjudication and gate**

Use the existing role and strict review JSON. Apply `apply_incremental_gate` before `quality_outcome`. A gate failure must either:

- invoke complete review when evidence can be recovered; or
- preserve the best candidate and report `final_review_incomplete` when providers fail.

- [ ] **Step 8: Add token and scope accounting**

For every first/full/incremental request, use existing receipts to record:

- input/output tokens;
- selected/reviewed/total windows;
- selection reasons;
- equivalent full-review input estimate;
- estimated saved input tokens;
- local/LTP cache hits;
- fallback flag and reasons.

- [ ] **Step 9: Run focused workflow tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflows.py tests/test_quality.py tests/test_incremental_review.py
git add src/novel_flywheel/workflows.py src/novel_flywheel/quality.py tests/test_workflows.py tests/test_quality.py
git commit -m "feat: add incremental correction final review"
```

---

### Task 6: Candidate, Publication, and Console Evidence

**Files:**
- Modify: `src/novel_flywheel/api/projects.py`
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`
- Modify: the existing candidate/project API test module discovered with `rg --files tests`

**Interfaces:**
- Consumes: latest hash-matching analysis and `quality-report.json`.
- Produces: additive candidate response fields `analysis`, `analysis_status`, and `review_scope`.

- [ ] **Step 1: Write failing candidate and publication tests**

Assert:

- candidate GET returns full-analysis status and local-corpus originality scope;
- publication reuses a matching complete analysis;
- changed candidate text forces a new complete local analysis;
- stale hashes, blocking findings, or unresolved incremental-gate failures block publication;
- publication does not call a provider when the terminal-reviewed candidate hash is unchanged.

- [ ] **Step 2: Write failing console contract tests**

Assert visible controls/text for:

- project optimized-analysis enable/disable;
- local scan complete;
- LTP complete/degraded;
- first full review;
- incremental related-window review;
- full-review fallback reason;
- reviewed/total windows;
- estimated token savings;
- local-corpus-only originality notice.

- [ ] **Step 3: Run focused tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_console.py tests/api/test_projects.py tests/api/test_learning.py
```

Use the discovered module names if they differ.

- [ ] **Step 4: Implement hash-safe candidate analysis**

Resolve the candidate text, load the latest matching artifact, or call the canonical local analyzer. Do not introduce a second analyzer implementation in the API.

- [ ] **Step 5: Extend publication gate**

Require:

- matching candidate and analysis hashes;
- no local blocking finding;
- no unresolved incremental/global gate reason;
- terminal-reviewed candidate hash match.

Preserve the current formal-file and publication metadata write path.

- [ ] **Step 6: Add bounded console evidence**

Reuse existing metric and context-tool components. Show concise evidence rather than raw LTP output. The control updates only the active project's metadata and does not install/uninstall LTP.

- [ ] **Step 7: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_console.py tests/api/test_projects.py tests/api/test_learning.py tests/test_projects.py
git add src/novel_flywheel/api/projects.py src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py tests/api tests/test_projects.py
git commit -m "feat: expose safe local and incremental review evidence"
```

Stage only the exact changed API test files.

---

### Task 7: Compatibility, Migration, Documentation, and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`
- Modify: `docs/superpowers/specs/2026-07-26-ltp-main-workflow-and-incremental-final-review-design.md`
- Modify: existing migration tests if project metadata defaults require migration coverage

**Interfaces:**
- Consumes: all prior task contracts.
- Produces: documented activation, rollback, artifact, fallback, and recovery procedures.

- [ ] **Step 1: Add compatibility and idempotence tests**

Prove:

- opening an existing project does not enable the new path silently;
- enabling and disabling repeatedly is idempotent;
- disabling restores repeated complete-final-review behavior;
- no role binding, provider, credential reference, StoryState revision, formal manuscript, reference, or run history is deleted;
- old quality reports without new fields remain readable.

- [ ] **Step 2: Run compatibility tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_migration.py tests/test_projects.py tests/test_story_state.py tests/test_db.py
```

Expected: all pass.

- [ ] **Step 3: Update user and maintenance documentation**

Document:

- project-scoped activation;
- required global LTP installed/enabled state;
- exact full-scan points;
- excerpt scope of `review` and `reader_review`;
- first full and later incremental terminal review behavior;
- all mandatory full-review triggers;
- local-corpus-only originality limitation;
- analysis, baseline, incremental, and quality-report artifact locations;
- safe rollback and cache deletion/rebuild;
- provider failure versus deterministic rejection versus quality failure events.

- [ ] **Step 4: Run formatting and focused regression checks**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest -q tests/test_manuscript_analysis.py tests/test_incremental_review.py tests/test_nlp_backend.py tests/test_quality.py tests/test_revision.py tests/test_workflows.py tests/test_console.py
```

Expected: no whitespace errors and all focused tests pass.

- [ ] **Step 5: Run the complete test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass and no test performs a paid provider call.

- [ ] **Step 6: Verify runtime state before any restart**

Read active runs from the application database. Do not restart when a run is `queued`, `running`, or `cancelling`. If no active run exists, start the console through `start-novel-console.cmd`, verify `/api/health`, project flag state, LTP status, and candidate quality response without invoking a paid workflow.

- [ ] **Step 7: Review the final diff for secrets and scope**

```powershell
git status --short
git diff --check
git diff --stat
git diff
```

Confirm:

- no API keys, request headers, or reference source text entered the diff;
- no model binding changed;
- no confirmed feature row is missing;
- no unrelated visual or learning feature changed.

- [ ] **Step 8: Commit the final integration**

```powershell
git add README.md docs/maintenance.md docs/superpowers/specs/2026-07-26-ltp-main-workflow-and-incremental-final-review-design.md tests
git commit -m "docs: document LTP and incremental review workflow"
```

Stage only files changed by this implementation.

## Completion Evidence

Before reporting completion, capture:

- focused and complete pytest totals;
- one test receipt proving the first review covers all windows;
- one test receipt proving a small correction reviews fewer than all windows;
- one test receipt proving structural change falls back to all windows;
- one test receipt proving disabled/failed LTP cannot incrementally approve;
- one candidate publication test proving no unchanged terminal-reviewed candidate invokes a provider;
- final `git status --short`;
- commit list for all tasks.

