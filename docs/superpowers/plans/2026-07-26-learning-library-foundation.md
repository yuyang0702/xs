# Learning Library Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a usable global learning-library foundation with local text storage, immutable source versions, deterministic prose diagnostics, REST APIs, and a first-class console page without calling provider APIs.

**Architecture:** Add additive SQLite tables and two focused services: `ReferenceLibrary` owns source/version lifecycle and `LocalEditorialEngine` produces deterministic evidence. A new API router exposes text import, listing, detail, analysis, and deletion; the existing static console renders the library. The phase introduces no parser, neural-model, vector, graph-service, or provider dependency.

**Tech Stack:** Python 3.11 standard library, SQLite, FastAPI/Pydantic, existing vanilla JavaScript/CSS, pytest/TestClient.

---

## Delivery Boundary

This plan is the first independently usable slice of the approved design. It supports pasted text and browser-selected UTF-8 TXT content sent as text JSON. DOCX/PDF parsing, safe URL fetching, graph abstraction, remote reference-analysis roles, project recommendation, local NLP installation, and line editing each receive a later focused plan after this storage and evidence contract is stable.

No local generative model is introduced. No provider API is called. Existing projects and workflows remain unchanged.

## File Structure

- Create `src/novel_flywheel/reference_library.py`: source/version lifecycle and filesystem persistence.
- Create `src/novel_flywheel/local_editorial.py`: deterministic metrics and evidenced findings.
- Create `src/novel_flywheel/api/references.py`: request schemas and REST endpoints.
- Create `tests/test_reference_library.py`: versioning, deduplication, deletion, and path safety.
- Create `tests/test_local_editorial.py`: metrics and diagnostic regression examples.
- Create `tests/api/test_references.py`: public API behavior and isolation.
- Modify `src/novel_flywheel/db.py`: additive tables and narrow persistence methods.
- Modify `src/novel_flywheel/app.py`: service construction and router registration.
- Modify `src/novel_flywheel/static/index.html`: learning-library navigation and page structure.
- Modify `src/novel_flywheel/static/app.js`: state, API loading, import, selection, analysis, and deletion.
- Modify `src/novel_flywheel/static/app.css`: unframed library layout and evidence presentation.
- Modify `tests/test_db.py`: additive migration contract.
- Modify `tests/test_console.py`: required menu, controls, and script hooks.
- Modify `README.md` and `docs/maintenance.md`: local storage, deletion, and no-provider-call behavior.

### Task 1: Add the Additive Learning Schema

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing schema test**

Extend `test_database_creates_foundation_tables` to require:

```python
assert {
    "reference_sources", "reference_versions", "reference_analyses",
} <= db.table_names()
```

Add a test that runs `db.migrate()` twice and verifies the new tables remain available.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py::test_database_creates_foundation_tables -q`

Expected: failure listing the three missing table names.

- [ ] **Step 3: Add minimal additive tables**

Add tables with these contracts:

```sql
CREATE TABLE IF NOT EXISTS reference_sources(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_versions(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES reference_sources(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  character_count INTEGER NOT NULL,
  storage_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(source_id, version),
  UNIQUE(source_id, content_hash)
);
CREATE TABLE IF NOT EXISTS reference_analyses(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES reference_sources(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES reference_versions(id) ON DELETE CASCADE,
  analyzer TEXT NOT NULL,
  analyzer_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(version_id, analyzer, analyzer_version, content_hash)
);
```

Add indexes for version lookup and analysis lookup. Do not change existing schema-version behavior in this slice.

- [ ] **Step 4: Run focused and database tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -q`

Expected: all database tests pass.

### Task 2: Implement Source and Version Persistence

**Files:**
- Create: `src/novel_flywheel/reference_library.py`
- Create: `tests/test_reference_library.py`
- Modify: `src/novel_flywheel/db.py`

- [ ] **Step 1: Write failing service tests**

Cover these behaviors with real temporary files and SQLite:

```python
source = library.import_text(title="雪夜", text="第一段。\n\n第二段。", source_type="paste")
assert source["latest_version"]["version"] == 1
assert library.read_text(source["id"]) == "第一段。\n\n第二段。"

same = library.import_text(title="重复", text="第一段。\n\n第二段。", source_type="paste")
assert same["id"] == source["id"]

updated = library.add_version(source["id"], "修改后的正文。")
assert updated["version"] == 2
```

Also verify whitespace-only input, unsupported source types, titles over 120 characters, and source IDs containing path separators are rejected.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_reference_library.py -q`

Expected: import failure because `ReferenceLibrary` does not exist.

- [ ] **Step 3: Add narrow database methods**

Add methods for creating/listing/getting/deleting sources, creating/listing versions, and saving/getting analysis records. Decode no arbitrary JSON except `result_json`, and always order sources by `updated_at DESC` and versions by `version DESC`.

- [ ] **Step 4: Implement `ReferenceLibrary`**

Use `hashlib.sha256`, `uuid.uuid4().hex`, atomic temporary-file replacement, and a fixed `<data_dir>/references/<source-id>/<version-id>.txt` layout. Normalize CRLF to LF and trim only outer whitespace; preserve internal paragraphs. Global content-hash deduplication returns the existing source instead of creating a duplicate.

Deletion removes the database source first inside the service call and then removes only the resolved source directory below the configured reference root. Resolve and verify containment before filesystem deletion.

- [ ] **Step 5: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_reference_library.py tests/test_db.py -q`

Expected: all focused tests pass.

### Task 3: Build the Deterministic Editorial Engine

**Files:**
- Create: `src/novel_flywheel/local_editorial.py`
- Create: `tests/test_local_editorial.py`

- [ ] **Step 1: Write failing diagnostic tests**

Use confirmed regression examples and assert stable finding IDs:

```python
report = analyze_prose("血是暗红色，静脉血。插得不深，没伤到大动脉。刀还不能拔。")
assert "checklist_judgment" in {item["rule_id"] for item in report["findings"]}

report = analyze_prose("他沉默了一会儿。\n\n她沉默了很久。\n\n两人都没有说话。")
assert "functional_repetition" in {item["rule_id"] for item in report["findings"]}
```

Also cover exact repeated n-grams, three dialogue-only paragraphs, sentence-length regularity, normal mixed prose without blocking findings, and source offsets matching the evidence substring.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_local_editorial.py -q`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement metrics with standard library only**

Expose one public function:

```python
def analyze_prose(text: str) -> dict[str, object]:
    return {"analyzer": "local-editorial", "version": "1", "metrics": {}, "findings": []}
```

Reuse or align with helpers in `prose_quality.py` where behavior already exists. Findings contain `rule_id`, `severity`, `start`, `end`, `evidence`, `message`, and `repair_goal`. Use conservative thresholds and mark style-dependent patterns as `review`, not `blocking`.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_local_editorial.py tests/test_prose_quality.py -q`

Expected: all tests pass without provider calls.

### Task 4: Connect Cached Local Analysis

**Files:**
- Modify: `src/novel_flywheel/reference_library.py`
- Modify: `tests/test_reference_library.py`

- [ ] **Step 1: Write a failing cache test**

Analyze one version twice and assert the second response has the same analysis ID and `cached=True`. Add a second source version and verify it receives a different analysis record.

- [ ] **Step 2: Run the test and verify RED**

Run the exact new test with `pytest -q`; expected failure is missing `analyze` behavior.

- [ ] **Step 3: Implement analysis caching**

Call `analyze_prose`, key the record by version ID, analyzer name/version, and content hash, save JSON through `Database`, and return a public result with `cached` but without filesystem paths.

- [ ] **Step 4: Run service and editorial tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_reference_library.py tests/test_local_editorial.py -q`

Expected: all tests pass.

### Task 5: Add the Reference REST API

**Files:**
- Create: `src/novel_flywheel/api/references.py`
- Create: `tests/api/test_references.py`
- Modify: `src/novel_flywheel/app.py`

- [ ] **Step 1: Write failing API tests**

Build a TestClient with a temporary database and data directory. Cover:

```text
POST   /api/references                 201
GET    /api/references                 200
GET    /api/references/{id}            200
GET    /api/references/{id}/content    200
POST   /api/references/{id}/analyze    200
DELETE /api/references/{id}            204
```

Verify the list never exposes `storage_path`, missing IDs return 404, invalid input returns 422, and analysis uses no `ModelGateway`.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_references.py -q`

Expected: 404 responses because the router is absent.

- [ ] **Step 3: Add the router and app service**

Define Pydantic payloads with `title` length 1-120, `source_type` literal `paste|txt`, and text length 1-1,000,000. Construct `ReferenceLibrary(db, settings.data_dir / "references")` in `create_app`, with an optional injected service for tests, and register the router.

- [ ] **Step 4: Run API and app tests**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_references.py tests/test_app.py -q`

Expected: all tests pass.

### Task 6: Add the Learning Library Console Page

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`

- [ ] **Step 1: Write failing static-contract tests**

Require a `data-view="learning"` navigation button, `#reference-form`, `#reference-list`, `#reference-detail`, and JavaScript calls for `/api/references` and `/analyze`. Require no visible claim that the system predicts popularity.

- [ ] **Step 2: Run the console tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_console.py -q`

Expected: missing learning-library selectors.

- [ ] **Step 3: Add the page markup**

Add a top-level `学习库` item and an unframed two-column working view: compact source list on the left, import/analyze/detail surface on the right. Use a real TXT file control that reads text in the browser and submits JSON, plus paste input. Do not add nested cards or explanatory marketing copy.

- [ ] **Step 4: Add behavior**

Extend state with references and activeReference. Load references in `loadAll`, render empty/loading/error states, import source text, select and load details, run local analysis, show metric values and evidence-located findings, and confirm deletion. Escape all imported source and finding content before insertion.

- [ ] **Step 5: Add responsive styling**

Use existing colors, 4px controls, full-width bands, stable source-list widths, and a single-column mobile fallback. Evidence text must wrap and never overlap actions.

- [ ] **Step 6: Run console tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_console.py -q`

Expected: all tests pass.

### Task 7: Document and Verify the Slice

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`

- [ ] **Step 1: Document behavior and boundaries**

Document local-only source storage, immutable versions, hash deduplication, deterministic analysis, deletion, supported first-slice inputs, the absence of provider calls, and the later optional NLP installation boundary.

- [ ] **Step 2: Run focused verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_reference_library.py tests/test_local_editorial.py tests/api/test_references.py tests/test_console.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass and no test calls a paid provider API.

- [ ] **Step 4: Check the diff**

Run: `git diff --check`

Expected: no whitespace errors. Review `git status --short` and keep the pre-existing final-review fix separate from this feature commit.

- [ ] **Step 5: Commit the implementation slice**

Stage only the learning-library files, their documentation, and their tests. Do not stage unrelated modifications in `src/novel_flywheel/workflows.py` or `tests/test_workflows.py`.

Commit message: `feat: add local reference learning library`

## Subsequent Approved Plans

After this slice passes acceptance, write and execute separate plans in this order:

1. document and safe public-URL import;
2. local NLP evaluator, Settings installer, CPU worker, cache, and uninstall;
3. evidenced window analysis and typed learning graph;
4. project recommendation, adoption, blueprint, and candidate outline;
5. prose baseline, character voice and epistemic state, and scene briefs;
6. targeted line edit, impact propagation, and feedback evaluation.
