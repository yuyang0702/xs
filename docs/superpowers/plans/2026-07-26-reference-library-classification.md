# Reference Library Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic and editable reference classification, searchable project/platform organization, type-specific local analysis, intentional-repetition protection, and evidence-backed learning mechanisms without adding automatic model calls.

**Architecture:** Extend the existing SQLite `reference_sources` record and `ReferenceLibrary` contract instead of adding a second store. Put deterministic classification and popular-sample analysis in focused modules, then route existing local analysis and learning through the stored content type. Keep adoption, StoryState authority, formal-write gates, model roles, and the existing final-review fallback unchanged.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Preserve existing novels, model bindings, Skills, run history, formal manuscripts, reference versions, learning nodes, and project adoptions.
- Automatic classification and popular-sample analysis must not call a model or paid API.
- `competitor_work` is manual-only and is the only reference content type used by originality comparison.
- Low-confidence mechanisms require confirmation before adoption.
- Existing final review remains available when no matching platform-rule references exist.
- Every schema migration must be idempotent and tested against a legacy database.

---

### Task 1: Reference metadata schema and deterministic classification

**Files:**
- Create: `src/novel_flywheel/reference_classification.py`
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/reference_library.py`
- Test: `tests/test_db.py`
- Test: `tests/test_reference_classification.py`
- Test: `tests/test_reference_library.py`

**Interfaces:**
- Produces: `classify_reference(title: str, text: str, source_uri: str | None = None) -> dict[str, str | float]`.
- Produces: `ReferenceLibrary.update_metadata(source_id, *, platform, content_type, project_id) -> dict`.
- Extends: `ReferenceLibrary.import_text(..., platform=None, content_type=None, project_id=None)`.

- [ ] **Step 1: Write failing migration and classifier tests**

```python
def test_legacy_reference_columns_are_added_idempotently(tmp_path):
    db = legacy_database_with_reference(tmp_path)
    db.migrate()
    db.migrate()
    row = db.get_reference_source("legacy")
    assert row["platform"] is None
    assert row["content_type"] == "reference_work"
    assert row["project_id"] is None

def test_classifier_never_auto_selects_competitor():
    values = classify_reference("知乎高赞投稿要求", "禁止抄袭，字数不得少于三千字")
    assert values["content_type"] == "platform_rule"
    assert values["content_type"] != "competitor_work"
```

- [ ] **Step 2: Run focused tests and verify expected failures**

Run: `pytest tests/test_db.py tests/test_reference_classification.py tests/test_reference_library.py -q`

Expected: failures for missing columns/module/import parameters.

- [ ] **Step 3: Implement the idempotent migration and classifier**

```python
CONTENT_TYPES = {
    "reference_work", "platform_rule", "popular_sample",
    "writing_tutorial", "competitor_work",
}

def classify_reference(title, text, source_uri=None):
    sample = f"{title}\n{source_uri or ''}\n{text[:4000]}"
    # platform_rule > writing_tutorial > popular_sample > reference_work
    # return {"platform": inferred_or_empty, "content_type": value, "confidence": score}
```

Use `PRAGMA table_info(reference_sources)` before `ALTER TABLE`; add `platform TEXT`, `content_type TEXT NOT NULL DEFAULT 'reference_work'`, and `project_id TEXT REFERENCES projects(id) ON DELETE SET NULL`.

- [ ] **Step 4: Run focused tests and verify pass**

Run: `pytest tests/test_db.py tests/test_reference_classification.py tests/test_reference_library.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/novel_flywheel/reference_classification.py src/novel_flywheel/db.py src/novel_flywheel/reference_library.py tests/test_db.py tests/test_reference_classification.py tests/test_reference_library.py
git commit -m "feat: classify and organize reference sources"
```

### Task 2: Reference metadata API and type-safe updates

**Files:**
- Modify: `src/novel_flywheel/api/references.py`
- Test: `tests/api/test_references.py`

**Interfaces:**
- Consumes: extended `ReferenceLibrary.import_text` and `update_metadata`.
- Produces: `PATCH /api/references/{source_id}/metadata`.

- [ ] **Step 1: Write failing API tests**

```python
def test_reference_metadata_can_be_overridden_and_updated(client):
    created = client.post("/api/references", json={
        "title": "循环样本", "source_type": "paste", "text": "第一天重新开始。",
        "platform": "知乎", "content_type": "popular_sample",
    }).json()
    updated = client.patch(f"/api/references/{created['id']}/metadata", json={
        "platform": "番茄", "content_type": "competitor_work", "project_id": None,
    })
    assert updated.json()["content_type"] == "competitor_work"

def test_unknown_content_type_is_rejected_without_partial_write(client):
    response = client.patch("/api/references/source/metadata", json={"content_type": "unknown"})
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests and verify route/field failures**

Run: `pytest tests/api/test_references.py -q`

- [ ] **Step 3: Add optional import fields, recommendation metadata, and PATCH validation**

```python
class ReferenceMetadataUpdate(BaseModel):
    platform: str | None = Field(default=None, max_length=80)
    content_type: Literal[
        "reference_work", "platform_rule", "popular_sample",
        "writing_tutorial", "competitor_work",
    ]
    project_id: str | None = None
```

Validate `project_id` through the existing project store before writing.

- [ ] **Step 4: Run API tests and verify pass**

Run: `pytest tests/api/test_references.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/novel_flywheel/api/references.py tests/api/test_references.py
git commit -m "feat: expose reference metadata controls"
```

### Task 3: Popular-sample local analysis

**Files:**
- Create: `src/novel_flywheel/popular_analysis.py`
- Modify: `src/novel_flywheel/reference_library.py`
- Modify: `src/novel_flywheel/api/references.py`
- Test: `tests/test_popular_analysis.py`
- Test: `tests/api/test_references.py`

**Interfaces:**
- Produces: `analyze_popular_sample(title: str, text: str, nlp: dict | None = None) -> dict`.
- Produces: `POST /api/references/{source_id}/popular-analysis`.

- [ ] **Step 1: Write failing behavior tests with literal expected sections**

```python
def test_popular_report_covers_full_reader_retention_arc():
    report = analyze_popular_sample(
        "我死后凶手来参加葬礼",
        "我死后的第三天，凶手参加了我的葬礼。\n"
        "他为什么敢来？\n\n我决定跟上他。" + "推进事件。" * 80 + "\n\n真相终于揭开。",
    )
    assert set(report["sections"]) == {
        "title", "first_three_lines", "opening_500",
        "middle", "turning_points", "ending",
    }
    assert report["sections"]["opening_500"]["evidence"]
    assert all({"start", "end", "excerpt"} <= item.keys()
               for item in report["sections"]["opening_500"]["evidence"])
```

- [ ] **Step 2: Run tests and verify missing-module failure**

Run: `pytest tests/test_popular_analysis.py tests/api/test_references.py -q`

- [ ] **Step 3: Implement deterministic section metrics and evidence offsets**

Split lines/paragraphs/sentences with offsets; calculate first-three-line lengths, opening signals, middle event density, transition markers, explicit questions, and ending payoff candidates. Return `analyzer="popular-sample-local"` and `model_calls=0`.

- [ ] **Step 4: Add cached library/API execution only for `popular_sample`**

Return 422 for other content types with a message asking the user to change the type or use regular diagnosis.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_popular_analysis.py tests/api/test_references.py -q`

```bash
git add src/novel_flywheel/popular_analysis.py src/novel_flywheel/reference_library.py src/novel_flywheel/api/references.py tests/test_popular_analysis.py tests/api/test_references.py
git commit -m "feat: add local popular sample analysis"
```

### Task 4: Evidence-backed local mechanism extraction

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Test: `tests/api/test_learning.py`
- Test: `tests/test_learning.py`

**Interfaces:**
- Produces: zero-or-more mechanism candidates per window with `structural_position`, `fact`, `interpretation`, `transfer_guidance`, `incompatible_conditions`, `confidence`, and exact evidence.
- Changes: `LearningSystem.adopt` rejects unconfirmed candidates with confidence below `0.7`.

- [ ] **Step 1: Write failing tests for actual evidence and adoption gate**

```python
def test_local_mechanism_evidence_contains_trigger_text(learning, source):
    result = learning.analyze_reference(source["id"])
    mechanism = next(item for item in result["mechanisms"] if item["data"]["name"] == "预期反转并重释既有信息")
    assert "原来" in mechanism["evidence"][0]["excerpt"]
    assert mechanism["evidence"][0]["start_offset"] < mechanism["evidence"][0]["end_offset"]

def test_low_confidence_proposal_must_be_confirmed_before_adoption(learning, project, node):
    with pytest.raises(ValueError, match="确认"):
        learning.adopt(project.id, node["id"])
```

- [ ] **Step 2: Run focused tests and verify current first-sentence/template behavior fails**

Run: `pytest tests/test_learning.py tests/api/test_learning.py -q`

- [ ] **Step 3: Replace `_abstract` with evidence-triggered candidate extraction**

Generate a candidate only when a trigger sentence can be located. Assign structural position from absolute offsets and source length. Platform rules produce rule candidates; writing tutorials produce method candidates; popular samples use the popular report; reference and competitor works use narrative mechanisms.

- [ ] **Step 4: Add confirmation gate without changing confirmed/adopted history**

Existing adopted nodes remain adopted. Only new low-confidence `proposed` nodes are blocked.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_learning.py tests/api/test_learning.py -q`

```bash
git add src/novel_flywheel/learning.py src/novel_flywheel/api/learning.py tests/test_learning.py tests/api/test_learning.py
git commit -m "feat: ground learning mechanisms in evidence"
```

### Task 5: Originality scope and platform-rule final-review context

**Files:**
- Modify: `src/novel_flywheel/reference_library.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_reference_library.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: `ReferenceLibrary.comparison_sources(project_id)` restricted to competitor references with no project or matching project.
- Produces: `ReferenceLibrary.platform_rules(platform: str) -> list[dict[str, str]]`.

- [ ] **Step 1: Write failing scope tests**

```python
def test_originality_sources_only_include_relevant_competitors(references, projects):
    references.import_text(title="普通参考", text="普通内容", source_type="paste")
    rival = references.import_text(
        title="竞品", text="竞品内容", source_type="paste",
        content_type="competitor_work", project_id=projects[0].id,
    )
    assert [item["title"] for item in references.comparison_sources(projects[0].id)] == [rival["title"]]
    assert references.comparison_sources(projects[1].id) == []
```

- [ ] **Step 2: Run focused tests and verify current global inclusion fails**

Run: `pytest tests/test_reference_library.py tests/test_workflows.py -q`

- [ ] **Step 3: Implement restricted comparison and same-platform rule lookup**

Inject compact platform rules into the existing final-review constraints only. Do not create a new model role or bypass the existing full/incremental review selection.

- [ ] **Step 4: Run focused tests and commit**

Run: `pytest tests/test_reference_library.py tests/test_workflows.py -q`

```bash
git add src/novel_flywheel/reference_library.py src/novel_flywheel/workflows.py tests/test_reference_library.py tests/test_workflows.py
git commit -m "feat: route references by safety and platform purpose"
```

### Task 6: Intentional repetition metadata and review messaging

**Files:**
- Modify: `src/novel_flywheel/local_editorial.py`
- Modify: `src/novel_flywheel/manuscript_analysis.py`
- Test: `tests/test_local_editorial.py`
- Test: `tests/test_manuscript_analysis.py`

**Interfaces:**
- Extends repetition findings with `intentional_repetition_candidate: bool` and a non-destructive repair goal when nearby state-change signals exist.

- [ ] **Step 1: Write failing contrast tests**

```python
def test_changed_loop_anchor_is_marked_as_intentional_candidate():
    text = "第一轮，电梯门在十二点打开，他死了。\n\n第二轮，电梯门在十二点打开，但死者换了位置。"
    finding = next(item for item in analyze_prose(text)["findings"] if item["rule_id"] == "repeated_phrase")
    assert finding["intentional_repetition_candidate"] is True
    assert "叙事作用" in finding["repair_goal"]

def test_unchanged_duplicate_remains_plain_review():
    text = "夜色已经沉了下来。夜色已经沉了下来。"
    finding = next(item for item in analyze_prose(text)["findings"] if item["rule_id"] == "repeated_phrase")
    assert finding["intentional_repetition_candidate"] is False
```

- [ ] **Step 2: Run tests and verify metadata is absent**

Run: `pytest tests/test_local_editorial.py tests/test_manuscript_analysis.py -q`

- [ ] **Step 3: Implement local neighboring-change signals and preserve severity `review`**

Use loop/time markers and contrast/change markers around the second occurrence. No automatic rewrite and no additional model invocation.

- [ ] **Step 4: Run focused tests and commit**

Run: `pytest tests/test_local_editorial.py tests/test_manuscript_analysis.py -q`

```bash
git add src/novel_flywheel/local_editorial.py src/novel_flywheel/manuscript_analysis.py tests/test_local_editorial.py tests/test_manuscript_analysis.py
git commit -m "feat: protect intentional narrative repetition"
```

### Task 7: Searchable and editable learning-library UI

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`

**Interfaces:**
- Consumes: reference metadata fields, PATCH endpoint, and popular-analysis endpoint.
- Produces: import selectors, recommendation label, combined client-side filters, detail metadata editor, type badges, and popular-analysis rendering.

- [ ] **Step 1: Write failing browser-contract test**

Use TestClient to load the real HTML/JS and assert the rendered import controls exist, then exercise the API-backed data shape through existing console integration tests.

- [ ] **Step 2: Run console tests and verify missing controls**

Run: `pytest tests/test_console.py -q`

- [ ] **Step 3: Implement minimal controls and combined filtering**

Add `reference-platform`, `reference-content-type`, `reference-project`, `reference-search`, and three filter selects. Render explicit type labels and show “系统推荐” only when the user has not overridden the value.

- [ ] **Step 4: Render evidence-backed cards and popular report**

Keep Confirm/Adopt/Reject actions. Disable adoption for low-confidence proposals until confirmed and show the reason in the button title.

- [ ] **Step 5: Run console tests and commit**

Run: `pytest tests/test_console.py -q`

```bash
git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py
git commit -m "feat: organize and inspect the reference library"
```

### Task 8: Documentation, regression, and delivery

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-26-reference-library-classification-design.md`

- [ ] **Step 1: Document the final behavior and migration**

Document content types, automatic recommendation, manual override, popular analysis versus final review, originality scope, and intentional-repetition review semantics.

- [ ] **Step 2: Run focused regression**

Run: `pytest tests/test_db.py tests/test_reference_classification.py tests/test_reference_library.py tests/test_popular_analysis.py tests/test_learning.py tests/test_local_editorial.py tests/api/test_references.py tests/api/test_learning.py tests/test_console.py -q`

- [ ] **Step 3: Run complete suite**

Run: `pytest -q`

- [ ] **Step 4: Inspect repository state and commit docs**

```bash
git status --short
git diff --check
git add README.md docs/superpowers/specs/2026-07-26-reference-library-classification-design.md docs/superpowers/plans/2026-07-26-reference-library-classification.md
git commit -m "docs: explain classified reference workflows"
```

- [ ] **Step 5: Verify local and remote readiness**

Confirm no run is `queued`, `running`, or `cancelling`; do not restart or push unless already authorized for this delivery.
