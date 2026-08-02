# Review Refresh and Semantic Split Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI re-review atomically refresh the actionable issue list and make every recursive prose split carry one current target and pass leaf, parent, segment, and whole-story integrity gates.

**Architecture:** Extend the existing quality review/checkpoint path with deterministic reconciliation and active/history projections; do not add another authority store. Introduce a focused draft split contract module that rebuilds each child prompt from immutable parent authority, validates every normal or limited response, dynamically assigns residual targets, and requires exact parent/whole-draft manifests before downstream stages.

**Tech Stack:** Python 3.12, FastAPI, vanilla JavaScript, JSON checkpoints, pytest.

## Global Constraints

- Preserve StoryState, formal outline, causal chain, execution index, quality checkpoints, model bindings, Skills, run history, project files, and formal manuscripts.
- A failed, truncated, stale, ambiguous, or incomplete re-review must not replace the last valid quality authority.
- Resolved and preserved issues leave the actionable list but remain available as history.
- A generated child prompt contains one current numeric target and one current event scope; it must not inherit a conflicting parent target.
- Normal terminal responses and output-limited responses pass the same artifact validation.
- Leaf success never substitutes for parent, full-segment, or whole-story validation.
- Token pressure may change review topology but never reduce full-manuscript coverage to sampling.
- Never mechanically truncate prose to satisfy a target.
- Automated tests must not call paid model APIs or mutate existing user projects.

---

## File Structure

- Create `src/novel_flywheel/draft_split.py`: immutable draft subtask contracts, prompt construction, target bounds, residual-target calculation, and exact event partition checks.
- Modify `src/novel_flywheel/quality.py`: merge complete prior-issue reconciliations into the current review while preserving stable issue identities and resolution evidence.
- Modify `src/novel_flywheel/quality_summary.py`: project one authoritative review into actionable issues and resolved/preserved history.
- Modify `src/novel_flywheel/workflows.py`: apply issue reconciliation before checkpoints; use structured recursive split tasks; validate every leaf, combined node, segment manifest, and whole draft.
- Modify `src/novel_flywheel/prose_quality.py`: reject Unicode replacement characters and invalid control characters as corrupted prose.
- Modify `src/novel_flywheel/static/app.js`: render only actionable issues under “最需要处理的问题” and render history separately.
- Modify `AGENTS.md` and `docs/maintenance.md`: add the generated-subtask integrity gate and operational behavior.
- Modify `tests/test_quality.py`, `tests/test_quality_summary.py`, `tests/test_prose_quality.py`, `tests/test_workflows.py`, and `tests/test_console.py`: cover every new contract and the production recursive split regression.

---

### Task 1: Reconcile AI Review Issues Into Active and Historical State

**Files:**
- Modify: `src/novel_flywheel/quality.py`
- Modify: `src/novel_flywheel/quality_summary.py`
- Test: `tests/test_quality.py`
- Test: `tests/test_quality_summary.py`

**Interfaces:**
- Consumes: existing `issue_ledger(issues, source="final_review")`, `issue_is_resolved(issue)`, and checkpoint-bound `review` dictionaries.
- Produces: `reconcile_review_issues(review: dict, prior_issues: list[dict], reconciliations: list[dict], *, reviewed_at: str = "") -> dict`; `build_quality_summary(...)` fields `issues` (actionable only) and `resolved_issues` (history).

- [ ] **Step 1: Write failing reconciliation tests**

Add tests proving that exact reconciliations merge old stable IDs into the new review, resolved evidence is retained, unresolved old issues cannot disappear, new issues remain, and missing/duplicate reconciliations return the original untrusted review plus an explicit incomplete marker instead of silently resolving anything.

```python
def test_reconcile_review_issues_preserves_resolved_history_and_new_issues() -> None:
    prior = issue_ledger([{
        "issue_id": "old-1", "category": "story", "severity": "high",
        "status": "unresolved", "evidence": "旧证据", "action": "补足选择",
    }])
    review = {"issues": [{
        "issue_id": "new-1", "category": "prose", "severity": "medium",
        "status": "unresolved", "evidence": "新证据", "action": "调整句子",
    }]}
    result = reconcile_review_issues(review, prior, [{
        "issue_id": "old-1", "status": "resolved", "evidence": "当前稿已补足选择",
    }], reviewed_at="2026-08-02T16:00:00+08:00")
    assert {item["issue_id"] for item in result["issues"]} == {"old-1", "new-1"}
    assert next(item for item in result["issues"] if item["issue_id"] == "old-1")["status"] == "resolved"
    assert result["issue_reconciliation_complete"] is True
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_quality.py tests/test_quality_summary.py -q`

Expected: FAIL because `reconcile_review_issues` and `resolved_issues` do not exist and summary still includes resolved entries in `issues`.

- [ ] **Step 3: Implement deterministic reconciliation**

Implement exact-ID validation. Canonicalize allowed statuses through the existing status rules. For a complete reconciliation, merge each prior item with its reconciliation status/evidence and any current-review copy, then append genuinely new review issues. For an incomplete or duplicate reconciliation, set `issue_reconciliation_complete=False` and leave prior issues unresolved; do not infer resolution from omission.

- [ ] **Step 4: Project active and historical issues in the summary**

Use the same merged list for both projections:

```python
all_issues = merge_quality_issues(report, review)
issues = [item for item in all_issues if item["status"] in {
    "unresolved", "partially_resolved", "uncertain", "open", "not_found",
}]
resolved_issues = [item for item in all_issues if item["status"] in {
    "resolved", "closed", "preserved",
}]
```

Make `issue_counts.total`, `mandatory`, and `unresolved` count only actionable issues; add `issue_counts.historical`.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_quality.py tests/test_quality_summary.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the issue-state unit**

```powershell
git add src/novel_flywheel/quality.py src/novel_flywheel/quality_summary.py tests/test_quality.py tests/test_quality_summary.py
git commit -m "fix: refresh actionable review issues"
```

---

### Task 2: Bind Reconciled Issues to Checkpoints and Render History

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/static/app.js`
- Test: `tests/test_workflows.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `reconcile_review_issues(...)` from Task 1 and existing full/incremental review audits.
- Produces: checkpoint `review.issues` containing exact reconciled statuses; UI section “已解决记录”; failure behavior that retains the prior checkpoint.

- [ ] **Step 1: Write failing workflow and UI tests**

Cover full review and incremental review. A prior issue returned only in `reconciliations` as resolved must be stored in `review.issues` with its stable ID and evidence. Missing reconciliation must cause the review gate to remain failing and must not write a replacement quality checkpoint. Assert that the JavaScript uses `summary.resolved_issues`, and that the priority heading uses `summary.issues.length` only.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "reconciliation or quality_checkpoint" tests/test_console.py -q`

Expected: FAIL because audit reconciliations are not merged into the returned review and the history drawer is absent.

- [ ] **Step 3: Reconcile before evidence gates and checkpoint writes**

In `_full_manuscript_review` and `_incremental_manuscript_review`, merge reconciliations before returning the review. Preserve the current evidence gate: incomplete reconciliation sets hard failure and cannot be promoted. In short-revision promotion, apply rejected user decisions after reconciliation so explicitly rejected issues remain unresolved.

- [ ] **Step 4: Render history separately**

Add a collapsed history drawer below the actionable section. It must show status, title, latest evidence, and review time when present. It must not feed `state.revisionIssues`, selection counts, publication blockers, or the “最需要处理的问题” count.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "reconciliation or quality_checkpoint" tests/test_console.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the checkpoint/UI unit**

```powershell
git add src/novel_flywheel/workflows.py src/novel_flywheel/static/app.js tests/test_workflows.py tests/test_console.py
git commit -m "feat: preserve resolved review history"
```

---

### Task 3: Introduce a Structured Draft Split Contract

**Files:**
- Create: `src/novel_flywheel/draft_split.py`
- Test: `tests/test_draft_split.py`

**Interfaces:**
- Produces: `DraftTaskContract`, `draft_task_prompt(base_authority: str, contract: DraftTaskContract) -> str`, `target_bounds(target: int) -> tuple[int, int]`, `residual_target(parent_target: int, first_han: int, floor: int = 400) -> int`, and `partition_is_exact(parent_ids, child_groups) -> bool`.

- [ ] **Step 1: Write failing pure-unit tests**

```python
def test_child_prompt_contains_only_current_target_and_scope() -> None:
    contract = DraftTaskContract(
        task_id="part-02.1.1", parent_id="part-02.1", depth=2,
        target=541, event_ids=("EV-00000001", "EV-00000002"),
        instruction="只完成前半因果推进", accepted_prefix="",
    )
    prompt = draft_task_prompt("父级权威资料，不含执行目标", contract)
    assert "目标约 541 个正文汉字" in prompt
    assert "目标约 1083" not in prompt
    assert "目标约 2167" not in prompt
    assert prompt.count("本任务唯一负责的正式事件 ID") == 1
```

Also test residual targets, minimum floors, exact event coverage, duplicates, missing events, and ordering reversals.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_draft_split.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the immutable contract and helpers**

Use a frozen dataclass. Reject non-positive targets, duplicate event IDs, unsupported depth, and a base authority string containing an executable `目标约 N 个正文汉字` instruction. Keep informational outline numbers allowed; only the current contract emits the executable target phrase.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_draft_split.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contract unit**

```powershell
git add src/novel_flywheel/draft_split.py tests/test_draft_split.py
git commit -m "feat: add semantic draft split contracts"
```

---

### Task 4: Rebuild Recursive Draft Calls and Validate Every Leaf

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prose_quality.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_prose_quality.py`

**Interfaces:**
- Consumes: Task 3 split-contract functions.
- Produces: `_draft_short_segment_task(...)` that builds a fresh prompt per call, validates all terminal results, retries an indivisible invalid leaf once, and dynamically computes the second child target.

- [ ] **Step 1: Add the production regression as a failing test**

Simulate the exact sequence: target 2167 returns 625 Han; child target 1083 returns 339 Han; recursive children return 1027 and 1132 Han with `finish_reason=end_turn`. Assert that every recursive prompt contains its actual 1083, 541, or residual target rather than 2167, and that an overlong leaf is retried before parent concatenation.

- [ ] **Step 2: Add terminal-state and corruption tests**

Cover `stop`, `end_turn`, `completed`, `max_tokens`, transport interruption, a single indivisible event, Unicode `\ufffd`, and invalid control characters. Normal completion must not bypass overlength, duplication, or prose-corruption checks.

- [ ] **Step 3: Run tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "draft_segment or draft_task_split or normal_finish" tests/test_prose_quality.py -q`

Expected: FAIL because recursive prompts inherit parent targets and normal terminal overlength is checked only after concatenation.

- [ ] **Step 4: Rebuild prompts from immutable authority**

Remove the numeric target from `_draft_short_in_segments` base authority. Construct a `DraftTaskContract` for every call and generate the provider prompt through `draft_task_prompt`. Pass the immutable base authority to recursive calls; never pass an already rendered child prompt back into recursion.

- [ ] **Step 5: Validate and recover each leaf**

After every `_stage` return, run `_draft_segment_findings` regardless of terminal reason. For an invalid indivisible leaf or maximum-depth leaf, retry once with the same event scope, explicit current target range, and failure evidence. If the retry remains invalid, raise a scoped error and preserve upstream checkpoints. Do not trim prose.

- [ ] **Step 6: Compute the second child from actual remaining space**

After accepting child 1, use `residual_target(parent_target, effective_han_characters(first))` for child 2. Preserve exact event partition and include child 1’s accepted text and exit tail in child 2’s contract. Validate the combined parent against the parent target and prior accepted prose.

- [ ] **Step 7: Reject corrupted prose locally**

Add blocking findings for Unicode replacement characters and invalid non-whitespace control characters. Keep ordinary Unicode punctuation and multilingual prose valid.

- [ ] **Step 8: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "draft_segment or draft_task_split or normal_finish" tests/test_prose_quality.py -q`

Expected: PASS.

- [ ] **Step 9: Commit the recursive execution unit**

```powershell
git add src/novel_flywheel/workflows.py src/novel_flywheel/prose_quality.py tests/test_workflows.py tests/test_prose_quality.py
git commit -m "fix: validate recursive draft splits"
```

---

### Task 5: Enforce Parent, Segment, Whole-Draft, and Token-Safe Review Gates

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: accepted child contracts and existing final-review window/evidence infrastructure.
- Produces: `_draft_manifest_issues(...) -> list[str]`; whole-draft failure events; no downstream polish before deterministic draft authority passes.

- [ ] **Step 1: Write failing manifest and downstream-stop tests**

Test missing, duplicate, and reversed event assignments; a successful set of child calls whose parent has duplicate prose; a six-segment draft missing one formal event; and a whole-draft failure that makes zero polish/review model calls. Verify a valid prior segment checkpoint remains reusable.

- [ ] **Step 2: Write token-safe full-coverage tests**

Use fake gateways to force multi-window review, truncated window output, truncated adjudication, and configured fallback. Assert every character range is covered, each window is hash-bound, missing evidence prevents checkpoint promotion, and successful hierarchical review preserves cross-window reconciliations.

- [ ] **Step 3: Run tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "draft_manifest or whole_draft or full_manuscript_review" -q`

Expected: FAIL because whole-draft event assignments are not gated before downstream stages and split artifacts have no exact parent manifest.

- [ ] **Step 4: Implement exact parent and whole-draft manifests**

Compare each plan segment’s expected event IDs with the accepted assignment, require one ordered occurrence of every formal event, verify segment count and checkpoint hashes, run prose corruption/duplicate checks across the joined draft, and emit explicit `draft_parent_gate_failed`, `draft_segment_gate_failed`, or `draft_whole_gate_failed` events.

- [ ] **Step 5: Preserve full-coverage review behavior under token pressure**

Reuse the existing paragraph-aligned review windows and global adjudication. Tighten promotion conditions so incomplete window coverage, stale hashes, missing reconciliation, truncated adjudication, or unresolved cross-window evidence cannot write a quality checkpoint. A configured larger-context fallback may retry; otherwise stop with validated evidence preserved.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "draft_manifest or whole_draft or full_manuscript_review" -q`

Expected: PASS.

- [ ] **Step 7: Commit the aggregate integrity unit**

```powershell
git add src/novel_flywheel/workflows.py tests/test_workflows.py
git commit -m "feat: gate merged draft integrity"
```

---

### Task 6: Add Forced Constraints, Documentation, and Final Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/maintenance.md`
- Modify: `docs/superpowers/specs/2026-08-02-review-refresh-and-semantic-split-integrity-design.md`
- Test: all focused suites and full pytest suite.

**Interfaces:**
- Produces: repository-level Generated Subtask Integrity Gate and documented operational semantics.

- [ ] **Step 1: Add the mandatory repository gate**

Add an `## Generated Subtask Integrity Gate` section to `AGENTS.md` requiring fresh child contracts, one active target/scope, identical validation for all terminal states, recursive parent/segment/whole-story checks, full coverage under token pressure, atomic authority commits, and regression fixtures for stale targets and recursive overlength.

- [ ] **Step 2: Document user-visible behavior**

Update `docs/maintenance.md` with active/history review semantics, failed-recheck preservation, semantic split targets, dynamic residual targets, leaf/parent/whole-draft validation, token-safe hierarchical review, and the new event meanings.

- [ ] **Step 3: Self-review the implementation against the specification**

Check every design requirement has code or a test. Run:

```powershell
rg -n "T[B]D|T[O]DO|implement[ ]later|fill[ ]in" docs/superpowers/specs/2026-08-02-review-refresh-and-semantic-split-integrity-design.md docs/superpowers/plans/2026-08-02-review-refresh-and-semantic-split-integrity.md
git diff --check
```

Expected: no placeholders and no whitespace errors.

- [ ] **Step 4: Run focused regression suites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_draft_split.py tests/test_quality.py tests/test_quality_summary.py tests/test_prose_quality.py tests/test_console.py tests/test_workflows.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the complete suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass; the existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 6: Commit all remaining documentation and verification changes**

```powershell
git add AGENTS.md docs/maintenance.md docs/superpowers/specs/2026-08-02-review-refresh-and-semantic-split-integrity-design.md docs/superpowers/plans/2026-08-02-review-refresh-and-semantic-split-integrity.md
git commit -m "docs: require generated subtask integrity"
```

- [ ] **Step 7: Integrate and publish**

Merge the implementation branch into local `main`, rerun the focused smoke tests on the merged tree, and push `main` to `origin/main`. Do not stage or remove `.codex-full-pytest*` user log files.
