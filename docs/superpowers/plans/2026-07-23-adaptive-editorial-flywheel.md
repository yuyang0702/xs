# Adaptive Editorial Flywheel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add commercial-first quality scoring, adaptive reader-review escalation, bounded correction cycles, and durable quality reports to short-story and long-chapter workflows.

**Architecture:** Put deterministic scoring, routing, sampling, and report state in a focused `quality.py` module. Keep provider calls and file transactions in `WorkflowService`, using the existing review and final-review roles so users do not need new model bindings. Persist one JSON report per run and surface decisions through existing run events.

**Tech Stack:** Python 3.11+, Pydantic, FastAPI service layer, SQLite run events, pytest.

## Global Constraints

- Quality weights are commercial `0.45`, story `0.35`, and prose `0.20`.
- Passing requires overall `>= 80`, commercial `>= 75`, story `>= 70`, prose `>= 65`, and `hard_fail == false`.
- Ordinary long chapters allow one corrective cycle; enhanced runs allow two.
- All short stories, chapters 1-3, volume endings, marked key chapters, and severe first reviews use the enhanced route.
- Reader simulation reuses the configured `review` role and receives bounded excerpts.
- Compliance and canon violations remain hard failures and never add quality points.
- No new runtime dependency or model-role configuration is introduced.

---

### Task 1: Deterministic Quality Policy

**Files:**
- Create: `src/novel_flywheel/quality.py`
- Create: `tests/test_quality.py`

**Interfaces:**
- Produces: `normalize_review(value: dict) -> dict`, `quality_gate(review: dict) -> tuple[bool, list[str]]`, `select_route(mode: str, chapter_number: int | None, chapter_goal: str, volume_end: bool, review: dict | None = None) -> dict`, and `reader_sample(text: str, mode: str, limit: int = 9000) -> str`.
- Consumes: plain dictionaries returned by existing model-review parsing.

- [ ] **Step 1: Write failing quality-policy tests**

```python
def test_normalize_review_computes_weighted_score():
    review = normalize_review({
        "dimensions": {"commercial": 90, "story": 80, "prose": 70},
        "hard_fail": False, "issues": [],
    })
    assert review["score"] == 82.5

def test_gate_enforces_each_dimension():
    review = normalize_review({
        "dimensions": {"commercial": 74, "story": 95, "prose": 95},
        "hard_fail": False, "issues": [],
    })
    passed, reasons = quality_gate(review)
    assert not passed
    assert "commercial_below_75" in reasons

def test_legacy_score_populates_dimensions():
    review = normalize_review({"score": 86, "hard_fail": False, "issues": []})
    assert review["dimensions"] == {"commercial": 86.0, "story": 86.0, "prose": 86.0}
```

- [ ] **Step 2: Run policy tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_quality.py -q`

Expected: collection fails because `novel_flywheel.quality` does not exist.

- [ ] **Step 3: Implement score normalization and gates**

```python
WEIGHTS = {"commercial": 0.45, "story": 0.35, "prose": 0.20}
MINIMUMS = {"commercial": 75.0, "story": 70.0, "prose": 65.0}

def normalize_review(value: dict) -> dict:
    result = dict(value)
    dimensions = result.get("dimensions")
    if dimensions is None:
        dimensions = {name: float(result["score"]) for name in WEIGHTS}
    normalized = {name: float(dimensions[name]) for name in WEIGHTS}
    if any(not 0 <= score <= 100 for score in normalized.values()):
        raise ValueError("Quality dimensions must be between 0 and 100")
    result["dimensions"] = normalized
    result["score"] = round(sum(normalized[name] * WEIGHTS[name] for name in WEIGHTS), 2)
    result.setdefault("hard_fail", False)
    result.setdefault("decision", "revise")
    result.setdefault("issues", [])
    return result

def quality_gate(review: dict) -> tuple[bool, list[str]]:
    reasons = []
    if review["score"] < 80:
        reasons.append("overall_below_80")
    for name, minimum in MINIMUMS.items():
        if review["dimensions"][name] < minimum:
            reasons.append(f"{name}_below_{int(minimum)}")
    if review.get("hard_fail"):
        reasons.append("hard_fail")
    return not reasons, reasons
```

- [ ] **Step 4: Add failing route and sample tests**

```python
def test_route_enhances_short_opening_and_severe_review():
    assert select_route("short", None, "", False)["enhanced"]
    assert select_route("long", 2, "ordinary", False)["enhanced"]
    severe = normalize_review({"dimensions": {"commercial": 55, "story": 80, "prose": 80}})
    assert select_route("long", 8, "ordinary", False, severe)["enhanced"]

def test_reader_sample_is_bounded_and_labels_checkpoints():
    sample = reader_sample("x" * 30000, "short", limit=9000)
    assert len(sample) <= 9200
    assert "OPENING" in sample
    assert "PAID CUTOFF" in sample
    assert "ENDING" in sample
```

- [ ] **Step 5: Implement route selection and bounded sampling**

```python
KEY_MARKERS = ("开篇", "前三章", "付费", "高潮", "结局", "关键", "揭晓", "卷末")

def select_route(mode: str, chapter_number: int | None, chapter_goal: str,
                 volume_end: bool, review: dict | None = None) -> dict:
    reasons = []
    if mode == "short": reasons.append("short_story")
    if chapter_number is not None and chapter_number <= 3: reasons.append("opening_chapter")
    if volume_end: reasons.append("volume_end")
    if any(marker in chapter_goal for marker in KEY_MARKERS): reasons.append("key_goal")
    if review and (review.get("decision") == "rewrite"
                   or review["dimensions"]["commercial"] < 60):
        reasons.append("severe_first_review")
    enhanced = bool(reasons)
    return {"enhanced": enhanced, "max_corrections": 2 if enhanced else 1,
            "reasons": reasons or ["ordinary_chapter"]}

def reader_sample(text: str, mode: str, limit: int = 9000) -> str:
    labels = (["OPENING", "PAID CUTOFF", "CLIMAX", "ENDING"] if mode == "short"
              else ["OPENING", "MIDDLE", "ENDING"])
    width = max(1, (limit - sum(len(label) + 8 for label in labels)) // len(labels))
    last = max(0, len(text) - width)
    points = ([0, int(len(text) * 0.35), int(len(text) * 0.75), last] if mode == "short"
              else [0, int(len(text) * 0.5), last])
    return "\n\n".join(
        f"--- {label} ---\n{text[min(point, last):min(point, last) + width]}"
        for label, point in zip(labels, points)
    )[:limit]
```

- [ ] **Step 6: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_quality.py -q`

Expected: all quality-policy tests pass.

Commit:

```powershell
git add src/novel_flywheel/quality.py tests/test_quality.py
git commit -m "feat: add adaptive editorial quality policy"
```

### Task 2: Editorial Prompts And Adaptive Workflow

**Files:**
- Modify: `src/novel_flywheel/prompts.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: Task 1 functions from `novel_flywheel.quality`.
- Produces: `_reader_review(run_id: str, run_path: Path, project: Project, constraints: str, text: str, suffix: str = "") -> dict`, `_quality_report_path(run_path: Path) -> Path`, and adaptive behavior in `_short_pipeline` and `_chapter_pipeline`.

- [ ] **Step 1: Write a failing enhanced short-workflow test**

Use a fake gateway returning planning, draft, structured editorial review, structured reader review, polish, passing final review, and maintenance. Assert the role sequence is:

```python
["planning", "draft", "review", "review", "polish", "final_review", "maintenance"]
```

Also assert `outputs/quality-report.json` records `route.enhanced == true`, a reader review, and final status `passed`.

- [ ] **Step 2: Write failing standard and enhanced retry-limit tests**

For chapter 8 with a normal goal, return a failed final review followed by one correction and passing final review. Assert exactly two polish calls and two final-review calls. For chapter 1, return two failed final reviews followed by a passing third review and assert three polish calls and three final-review calls.

- [ ] **Step 3: Run workflow tests and verify failures**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflows.py -q`

Expected: failures show missing reader-review stage, fixed three-round policy, and missing quality report.

- [ ] **Step 4: Strengthen review prompts**

Change review and final-review system prompts to require strict JSON shaped as:

```json
{
  "dimensions": {"commercial": 0, "story": 0, "prose": 0},
  "hard_fail": false,
  "decision": "pass",
  "issues": [
    {"category": "commercial", "severity": "medium", "evidence": "quoted location", "action": "specific revision"}
  ]
}
```

The prompt must state that compliance or canon violations set `hard_fail=true`, and that scores measure quality rather than compliance.

- [ ] **Step 5: Replace fixed review loops with adaptive policy**

In each content pipeline:

```python
review = normalize_review(self._review(raw_review))
route = select_route(project.mode, chapter_number, chapter_goal, volume_end, review)
reader_review = await self._reader_review(
    run_id, run_path, project, constraints, draft,
) if route["enhanced"] else None
findings = {"editorial": review, "reader": reader_review}
polished = await self._stage(
    run_id, run_path, project, "polish", constraints,
    f"DRAFT:\n{draft}\n\nFINDINGS:\n{json.dumps(findings, ensure_ascii=False)}",
)
for correction in range(route["max_corrections"] + 1):
    raw_final = await self._stage(
        run_id, run_path, project, "final_review", constraints, polished,
        suffix=f"-{correction + 1}" if correction else "",
    )
    final_review = normalize_review(self._review(raw_final))
    passed, reasons = quality_gate(final_review)
    if passed:
        break
    if correction < route["max_corrections"]:
        polished = await self._stage(
            run_id, run_path, project, "polish", constraints,
            f"MANUSCRIPT:\n{polished}\n\nFINAL REVIEW:\n"
            f"{json.dumps(final_review, ensure_ascii=False)}",
            suffix=f"-{correction + 2}",
        )
```

Use `reader_sample` for reader-review input. Keep formal-file writes after the final gate.

- [ ] **Step 6: Pass bounded model-output budgets through `_stage`**

Add `_stage_output_budget(stage: str) -> int | None` returning `4096` for planning, `1800` for review/final review/maintenance, and `None` for draft/polish. Pass the value to both `complete_with_tools` and `complete`.

- [ ] **Step 7: Run workflow and full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflows.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: workflow tests pass and the full suite has zero failures.

- [ ] **Step 8: Commit workflow integration**

```powershell
git add src/novel_flywheel/prompts.py src/novel_flywheel/workflows.py tests/test_workflows.py
git commit -m "feat: add adaptive editorial review workflow"
```

### Task 3: Quality Events And Failure Evidence

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: normalized reviews, route dictionaries, and `Database.add_run_event`.
- Produces: durable `quality-report.json` updates and event types `quality_route`, `quality_assessed`, `quality_escalated`, `quality_revision`, and `quality_gate`.

- [ ] **Step 1: Write failing observability tests**

Assert a completed enhanced run contains the event sequence `quality_route`, `quality_assessed`, `quality_escalated`, and a successful `quality_gate`. Assert a final-gate failure leaves `quality-report.json` with status `failed`, reasons, and all attempts while formal manuscript files remain absent.

- [ ] **Step 2: Run the targeted tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_workflows.py -k "quality_event or failed_quality_report" -q`

Expected: assertions fail because quality events and failure-state report updates are missing.

- [ ] **Step 3: Add incremental report persistence**

Create a report dictionary at route selection, update it after every review and correction, and atomically write it after each update. Before raising a final-gate error, set:

```python
report["status"] = "failed"
report["failure_reasons"] = reasons
```

On success set `status` to `passed`. Store scores, reasons, provider-independent review data, and route reasons only; never store API keys or provider secrets.

- [ ] **Step 4: Add concise run events**

Emit Chinese event messages with metadata containing the local score, dimension scores, route, attempt number, and failure reasons. Reuse the existing console run log; no frontend schema change is required.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflows.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with no failures.

Commit:

```powershell
git add src/novel_flywheel/workflows.py tests/test_workflows.py
git commit -m "feat: persist editorial quality decisions"
```

### Task 4: Final Runtime Verification

**Files:**
- No production file changes expected.

**Interfaces:**
- Consumes: completed implementation.
- Produces: verified local console with clean worktree.

- [ ] **Step 1: Run static and automated verification**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
node --check src\novel_flywheel\static\app.js
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: compilation and JavaScript syntax exit zero, tests have zero failures, and `git diff --check` reports no errors.

- [ ] **Step 2: Restart and probe the local console**

Restart `start-novel-console.cmd` outside the network sandbox, then request `http://127.0.0.1:8765/api/health`.

Expected response:

```json
{"status":"ok"}
```

- [ ] **Step 3: Confirm repository state**

Run: `git status --short`

Expected: no output.
