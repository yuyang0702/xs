# Reference Model Output Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent malformed model JSON from being reported as a successful reference analysis with zero candidate mechanisms.

**Architecture:** Add small protocol validators at the existing `LearningSystem` model boundary and route protocol failures through the existing configured fallback path. Keep task storage, model roles, learning nodes, and adoption behavior unchanged; adjust the existing frontend summary so a legitimate empty result is explained rather than presented as an ambiguous zero.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, vanilla JavaScript, pytest.

## Global Constraints

- Preserve existing reference data, learning nodes, adoptions, model bindings, and local analysis results.
- Use only the existing `reference_analysis` and `reference_synthesis` roles and their configured fallbacks.
- Automated tests must use `FakeGateway` and must not call paid model APIs.
- A failed synthesis must retain already saved window claims.
- Candidate mechanisms remain user-confirmed and never modify formal manuscripts directly.

---

### Task 1: Validate Model Protocols and Reuse Configured Fallbacks

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Test: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: `LearningSystem._json_object(text: str) -> dict` and the existing `gateway.complete_configured_fallback(...)` method.
- Produces: `LearningSystem._window_result(text: str) -> dict` and `LearningSystem._synthesis_result(text: str) -> dict`, both raising `ValueError` with a specific protocol reason.

- [ ] **Step 1: Write failing window protocol fallback test**

Add an async test whose primary `reference_analysis` response is `{"start":0,"end":10,"fact":"x"}`, whose configured fallback returns all six required list fields, and whose synthesis returns a valid empty `mechanisms` plus a complete minimal `attraction_map`. Assert that `reference_analysis` appears in `fallback_roles` and one claim is saved.

- [ ] **Step 2: Run the window test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_learning_system.py::test_model_analysis_uses_fallback_for_wrong_window_shape -q`

Expected: FAIL because the primary object is currently accepted and the fallback is not called.

- [ ] **Step 3: Write failing synthesis protocol fallback test**

Add an async test whose primary window response is valid, whose primary synthesis response is `{"start":0,"fact":"summary"}`, and whose configured `reference_synthesis` fallback returns `{"mechanisms": [], "attraction_map": <complete minimal map>}`. Assert that `reference_synthesis` appears in `fallback_roles` and the result contains an attraction map.

- [ ] **Step 4: Run the synthesis test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_learning_system.py::test_model_analysis_uses_fallback_for_wrong_synthesis_shape -q`

Expected: FAIL because malformed synthesis is currently treated as a successful result with zero mechanisms.

- [ ] **Step 5: Implement minimal protocol validators**

In `LearningSystem`, add validators that:

```python
WINDOW_FIELDS = (
    "events", "state_changes", "reader_questions", "turning_points",
    "relationship_changes", "style_evidence",
)

@classmethod
def _window_result(cls, text: str) -> dict:
    value = cls._json_object(text)
    missing = [key for key in WINDOW_FIELDS if not isinstance(value.get(key), list)]
    if missing:
        raise ValueError("窗口分析缺少列表字段：" + "、".join(missing))
    return value

@classmethod
def _synthesis_result(cls, text: str) -> dict:
    value = cls._json_object(text)
    if not isinstance(value.get("mechanisms"), list):
        raise ValueError("全文汇总缺少 mechanisms 列表")
    if not isinstance(value.get("attraction_map"), dict):
        raise ValueError("全文汇总缺少 attraction_map 对象")
    return value
```

Use `_window_result` and `_synthesis_result` for both primary and fallback responses. Require each mechanism to have `name`, non-empty `supporting_windows`, and `transfer_guidance`; raise a protocol error instead of silently skipping malformed entries. Update the window prompt to request at most three items per list and set window `max_output_tokens=2048`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_learning_system.py -q`

Expected: all learning-system tests pass.

- [ ] **Step 7: Commit backend fix**

```powershell
git add src/novel_flywheel/learning.py tests/test_learning_system.py
git commit -m "fix: validate reference model output contracts"
```

### Task 2: Explain Empty Results and Verify the Complete Flow

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `README.md`
- Test: `tests/api/test_learning.py`

**Interfaces:**
- Consumes: completed reference-analysis task result containing validated `mechanisms` and `attraction_map` values.
- Produces: unambiguous completion copy for non-empty and legitimate empty results; no API contract change.

- [ ] **Step 1: Add API regression coverage for protocol failure status**

Extend the reference learning API test with a fake gateway returning the wrong synthesis shape. Poll the task and assert it ends in `failed`, includes `全文汇总` and `mechanisms` in the error, and does not expose a completed zero-candidate result.

- [ ] **Step 2: Run API test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_learning.py -q`

Expected: the new assertion fails before the backend validator is active, then passes with Task 1.

- [ ] **Step 3: Update frontend completion copy**

In `pollReferenceAnalysisTask`, use:

```javascript
const count = task.result?.mechanisms?.length || 0;
task.summary = count
  ? `全文模型分析完成，得到 ${count} 个候选写法`
  : "全文模型分析完成；模型未形成可逐条采纳的候选写法，剧情吸引力报告仍可查看";
```

Do not change the existing failed-task rendering because it already displays `task.error`.

- [ ] **Step 4: Update runtime documentation**

Document in `README.md` that reference model responses are schema-validated, configured fallbacks handle malformed JSON structures, completed window claims survive synthesis failure, and a valid empty candidate list is explicitly explained.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

Expected: all tests pass and `git diff --check` returns no output.

- [ ] **Step 6: Restart only after checking active runs**

Query the service for active work. If no task or run is `queued`, `running`, or `cancelling`, restart the console and verify `GET /api/health` returns `{"status":"ok"}`. Do not call a paid model API during verification.

- [ ] **Step 7: Commit and push**

```powershell
git add src/novel_flywheel/static/app.js README.md tests/api/test_learning.py
git commit -m "fix: explain reference analysis results"
git push origin main
```
