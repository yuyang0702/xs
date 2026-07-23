# Per-Role Fallback Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently configurable fallback models for every role, with the existing workflow role fallback retained as the final safety net.

**Architecture:** The existing role-binding record remains the single configuration source. The API validates complete, distinct primary/fallback pairs; the browser edits all four fields; `ModelGateway` tries a binding's explicit fallback before propagating failure to the workflow's existing fallback-role logic.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest, vanilla JavaScript and CSS.

---

### Task 1: API Validation

**Files:**
- Modify: `src/novel_flywheel/api/providers.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing endpoint tests**

Add tests that create two providers/models and verify: a complete distinct fallback pair is stored, a partial fallback pair returns 422, and an identical primary/fallback pair returns 400 with `fallback_matches_primary`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "role_binding and fallback" -q`

Expected: the identical-pair request is accepted or partial-pair validation does not express the required contract.

- [ ] **Step 3: Implement minimal request validation**

Add a Pydantic model validator requiring fallback IDs to be both set or both null. In `update_role_binding`, reject an identical pair before resolving and saving it:

```python
if (payload.fallback_provider_id, payload.fallback_model_id) == (
    payload.primary_provider_id, payload.primary_model_id,
):
    raise HTTPException(status_code=400, detail={"code": "fallback_matches_primary"})
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "role_binding and fallback" -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```text
feat: validate role fallback models
```

### Task 2: Gateway Explicit Fallback

**Files:**
- Modify: `src/novel_flywheel/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing gateway tests**

Add adapters/registries that fail the primary model and succeed the explicit fallback. Cover both `complete` and `complete_with_tools`, assert the fallback text is returned, and assert receipt metadata contains:

```python
{
    "fallback_used": True,
    "fallback_from_provider_id": "primary-provider",
    "fallback_from_model_id": "primary-model",
}
```

Also test that no explicit fallback preserves the raised primary exception.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -k "configured_fallback" -q`

Expected: primary adapter exceptions propagate instead of selecting the configured fallback.

- [ ] **Step 3: Implement minimal fallback resolution**

Refactor each public completion method into a small binding-aware wrapper and one resolved-model execution helper. Catch ordinary completion errors around the primary call, resolve the fallback pair only when both IDs exist, retry once with identical request inputs, and annotate the successful fallback receipt. Do not catch `asyncio.CancelledError`.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -q`

Expected: all model-gateway tests pass.

- [ ] **Step 5: Commit**

```text
feat: execute configured role fallback models
```

### Task 3: Runtime Logging And Existing Default Fallback

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write failing workflow tests**

Add a gateway result with `fallback_used` receipt metadata and assert `_stage` records a `model_fallback` event naming the explicit fallback. Preserve the existing test proving `_stage_with_role_fallback` uses its fallback role when the gateway raises.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workflows.py -k "explicit_model_fallback or stage_with_role_fallback" -q`

Expected: explicit fallback succeeds silently without the required run event.

- [ ] **Step 3: Add receipt-driven run logging**

After a successful gateway completion, check `result.receipt.get("fallback_used")`. When true, add `model_fallback` with the actual provider/model IDs and a message stating that the role's configured backup was used. Leave `_stage_with_role_fallback` unchanged so a missing or failed explicit fallback still reaches the program-default role.

- [ ] **Step 4: Run workflow tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workflows.py -q`

Expected: all workflow tests pass.

- [ ] **Step 5: Commit**

```text
feat: report explicit model fallback usage
```

### Task 4: Role Binding UI

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

- [ ] **Step 1: Write a failing console contract test**

Assert the served script contains separate `binding-primary-` and `binding-fallback-` selectors, sends `fallback_provider_id` and `fallback_model_id`, restores both fields, and rejects identical selections.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_console.py -q`

Expected: the new fallback-selector assertions fail.

- [ ] **Step 3: Implement the two-selector row**

Render each row as role label, primary selector, optional fallback selector with `使用程序默认回退`, and Save. Split both selected values, send null fallback IDs for the default option, reject identical nonempty values locally, and restore saved values from `/api/role-bindings`.

- [ ] **Step 4: Update responsive grid styles**

Change the desktop binding grid to `180px minmax(220px,1fr) minmax(220px,1fr) auto`; keep the existing one-column mobile rule.

- [ ] **Step 5: Run console tests and verify GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_console.py -q`

Expected: all console tests pass.

- [ ] **Step 6: Commit**

```text
feat: configure fallback models per role
```

### Task 5: Verification And Local Delivery

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run static diff validation**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 2: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Confirm no active generation task**

Query `/api/projects/{project_id}/runs` and verify no run is `queued`, `running`, or `cancelling` before restarting.

- [ ] **Step 4: Restart against the existing data directory**

Set `NOVEL_FLYWHEEL_DATA_DIR=C:\小说\novel-flywheel-console\data` and restart `novel_flywheel.launcher` on port `64898`.

- [ ] **Step 5: Verify the live UI without changing bindings**

Reload the local console, open `模型与 API`, and assert every role row displays one primary selector and one optional fallback selector with existing primary selections preserved.
