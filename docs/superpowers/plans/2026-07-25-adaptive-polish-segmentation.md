# Adaptive Polish Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Claude polish output at 8,192 tokens while reducing oversized input requests and recovering from relay failures by splitting only the failed prose segment.

**Architecture:** Extend the existing paragraph-aware splitter and polish loop. Estimate complete request size conservatively without a tokenizer dependency, shrink optional context through the existing context builder, and recursively split recoverable failures at paragraph boundaries. Existing checkpoints and candidate validation remain authoritative.

**Tech Stack:** Python 3.11, asyncio, pytest, existing FastAPI workflow and model gateway.

---

### Task 1: Adaptive request sizing

**Files:**
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_context_policy.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write failing tests**

Add tests proving that the estimator treats Chinese prose conservatively, optional context is reduced before manuscript prose, safe splits preserve paragraph order, and Claude polish output remains 8,192.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_context_policy.py tests/test_workflows.py -k "adaptive or input_size or output_budget"
```

Expected: new tests fail because adaptive sizing does not exist.

- [ ] **Step 3: Implement minimal adaptive sizing**

Add a conservative standard-library estimator and make `polish_context` accept bounded adjacent-window and optional-context limits. Change ordinary polish chunks to the 1,200-1,800 character range, then split again at a paragraph boundary when the complete estimated request is too large. Never truncate manuscript prose or locked facts.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2 and expect all selected tests to pass.

### Task 2: Recoverable failed-segment splitting

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write failing workflow tests**

Add gateway fixtures proving that `502`, `504`, `524`, connection failure, and timeout split only the failed segment; successful child segments are checkpointed; authentication and validation errors propagate; and configured Claude exhaustion never calls the Draft role.

- [ ] **Step 2: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflows.py -k "recoverable_polish or no_draft_fallback"
```

Expected: failures show the current Draft-role fallback.

- [ ] **Step 3: Implement bounded recovery**

Replace `fallback_only` with a helper that calls the existing configured routes, recognizes only recoverable transport and gateway failures, splits the failed prose near its midpoint at a blank-line boundary, and retries children to a bounded depth. Reuse the existing source-hash checkpoint functions for every successful leaf. Raise the original error at minimum safe size.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2 and expect all selected tests to pass.

### Task 3: Documentation and verification

**Files:**
- Modify: `docs/maintenance.md`
- Test: full test suite and one authorized provider smoke call

- [ ] **Step 1: Document runtime behavior**

Document adaptive input sizing, preserved 8,192 output budget, recoverable split events, checkpoint reuse, minimum-size halt, and prohibition of Draft fallback after configured Claude exhaustion.

- [ ] **Step 2: Run the full automated suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with only the existing Starlette deprecation warning.

- [ ] **Step 3: Run one authorized real-provider smoke validation**

After confirming no active run, invoke one small polish segment through the configured role. Verify the receipt reports a Claude model, the request succeeds or fails transparently through configured Claude routes, and no Draft-role receipt is created. Do not print credentials or headers.

- [ ] **Step 4: Restart and health-check**

Restart only when there are no `queued`, `running`, or `cancelling` runs. Verify `GET /api/health` returns HTTP 200 at the existing local URL.

- [ ] **Step 5: Commit implementation**

Stage only files related to this feature and the already-tested pending style/rhythm fixes, review the staged diff for secrets, then create a local commit.
