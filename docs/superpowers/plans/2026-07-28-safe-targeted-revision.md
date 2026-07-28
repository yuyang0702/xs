# Safe Targeted Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, patch-based short-story revision flow that fixes selected issues without plan-external prose changes, blocks invalid candidates before model review, and never overwrites the protected best or formal manuscript.

**Architecture:** Extend the existing `WorkflowService`, `StoryState`, run-task, candidate, quality-checkpoint, and provider-role paths. Pure functions in `revision.py`, `manuscript_analysis.py`, `incremental_review.py`, and a focused `repair_gate.py` validate exact patches and review scope; `repair_records.py` stores only hash-bound run artifacts, never authoritative story state. A new API module and compact UI expose the same run, checkpoint, adoption, and resume operations in plain Chinese.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest/pytest-asyncio, standard-library `difflib`, `hashlib`, `json`, `urllib`, HTML/CSS/vanilla JavaScript, existing LTP integration and model gateway.

## Global Constraints

- Preserve existing novels, model bindings, credentials, Skills, learning data, run history, protected best manuscripts, and formal manuscripts.
- Do not call paid model APIs from automated tests or verification commands; use fakes and monkeypatches only.
- Do not add a second authoritative state store, direct model write path, new mandatory model role, graph database, machine-learning training, or version experiment.
- The authority order remains: user locks and protected passages; formal outline and `StoryState.locked_facts`; protected best; local extracted candidates; model suggestions.
- Every revision writes a candidate and run artifacts first. Only user-adopted, gate-passing candidates may compete with the protected best; formalization remains a separate user action.
- Automatic prose changes are limited to meaning-preserving mechanical repairs. Every semantic patch requires user review.
- A patch group is atomic: all member patches pass and apply together, or the complete group rolls back. Independent groups may succeed independently.
- The candidate, source, analysis, contract, checkpoint, and final-review hashes must match exactly before promotion.
- First terminal review is full manuscript. Later review is incremental only when all local gates pass and no full-review trigger applies.
- Full review is mandatory when changed text exceeds 20%, affected windows exceed 40%, a scene is inserted/deleted/moved/merged, or opening 500 characters, climax, ending 500 characters, event order, timeline, causality, seven-step structure, protagonist goal, key choice, life/death, identity, relationship, knowledge, key evidence, setup, promise, question, payoff, locked fact, world rule, or protected passage changes.
- Full review is also mandatory for stale hashes, non-unique anchors, ambiguous window mapping, semantic changes without LTP, reviewer uncertainty, unresolved/uncertain major issues, new local blockers, or partially applied groups.
- White-listed punctuation, spacing, control-character, and exact consecutive-duplicate repairs do not require LTP, but still run a full local scan.
- A comparable candidate must use the same scoring profile and judge signature, improve total score by at least 2 points, regress no dimension by more than 3 points, add no unresolved major issue, and resolve every mandatory issue.
- Reaching the same output ceiling must never cause an identical retry. Malformed JSON retries repair structure only and do not resend the full manuscript.
- User-visible copy and run events must be simple Chinese and distinguish model failure, Runtime rejection, quality failure, fallback, and successful commit.
- The original full-review path remains tested and available when the project feature is explicitly disabled.
- Focused tests run before the complete suite. Do not restart the console while any run is `queued`, `running`, or `cancelling`.

## File Map

- `src/novel_flywheel/revision.py`: mechanical whitelist, repair-contract normalization, exact patch and atomic-group application.
- `src/novel_flywheel/manuscript_analysis.py`: stable paragraph/scene identifiers and lightweight entity/event/object/relation impact index.
- `src/novel_flywheel/narrative_ledger.py`: stable evidence IDs and explicit source positions/confidence boundaries.
- `src/novel_flywheel/incremental_review.py`: strict hash binding, impact scope, hierarchical long-text diff, and full-review triggers.
- `src/novel_flywheel/repair_gate.py`: pure whole-candidate gate; no persistence and no model calls.
- `src/novel_flywheel/repair_records.py`: atomic read/write of the five revision-run artifacts.
- `src/novel_flywheel/passage_protection.py`: full-candidate validation of every active protection.
- `src/novel_flywheel/story_state.py`: authoritative-fact snapshot and post-candidate conflict check.
- `src/novel_flywheel/context_policy.py`: bounded patch context, output budget, and retry decision.
- `src/novel_flywheel/quality.py`: stable issue statuses and user preservation state.
- `src/novel_flywheel/quality_profiles.py`: mandatory-issue and promotion checks.
- `src/novel_flywheel/workflows.py`: `run_short_revision`, expansion branch, checkpoints, local gate, incremental/full review routing.
- `src/novel_flywheel/api/revisions.py`: start, inspect, adopt, reject, and retry revision operations.
- `src/novel_flywheel/api/runs.py`: resume `short-revision` and expose its report.
- `src/novel_flywheel/tasks.py`: preserve partial completion semantics when a revision run stops.
- `src/novel_flywheel/projects.py`: new-short defaults and idempotent existing-project metadata migration.
- `src/novel_flywheel/app.py`: register the revision router and expose a data-directory health fingerprint.
- `src/novel_flywheel/launcher.py`: single-instance behavior on port 8765.
- `src/novel_flywheel/static/index.html`: containers for issue selection, progress, and group confirmation.
- `src/novel_flywheel/static/app.js`: Chinese revision interaction and polling.
- `src/novel_flywheel/static/app.css`: compact, readable revision workspace.
- `README.md`, `docs/maintenance.md`: operational contract, recovery, rollback, and event meanings.

---

### Task 1: Safe Mechanical Repairs and Atomic Patch Groups

**Files:**
- Modify: `src/novel_flywheel/revision.py`
- Test: `tests/test_revision.py`

**Interfaces:**
- Consumes: existing `normalize_chinese_prose(text: str)` and issue-ledger IDs.
- Produces: `normalize_repair_contract(value: dict, manuscript: str, issue_ids: set[str]) -> dict`, `apply_patch_group(manuscript: str, group: dict, source_hash: str) -> dict`, and `repair_mechanical_text(text: str) -> dict`.

- [ ] **Step 1: Write failing tests for the mechanical whitelist, exact anchors, and atomic rollback**

```python
def test_mechanical_repairs_leave_ambiguous_quotes_and_report_them() -> None:
    result = repair_mechanical_text('他说："门开了。\n她没有回答。')
    assert result["text"] == '他说："门开了。\n她没有回答。'
    assert result["applied"] == []
    assert result["blocked"][0]["code"] == "unpaired_quote"


def test_patch_group_rolls_back_when_second_anchor_is_not_unique() -> None:
    source = "银锁第一次出现。\n\n证人看见银锁。\n\n证人看见银锁。"
    group = {
        "group_id": "issue-lock",
        "issue_ids": ["issue-lock"],
        "patches": [
            {"operation": "replace", "old_text": "银锁第一次出现。", "new_text": "父亲交出银锁。"},
            {"operation": "replace", "old_text": "证人看见银锁。", "new_text": "民警登记了银锁。"},
        ],
    }
    result = apply_patch_group(source, group, hashlib.sha256(source.encode()).hexdigest())
    assert result["accepted"] is False
    assert result["text"] == source
    assert result["failures"] == [{"patch": 2, "code": "anchor_not_unique"}]
```

- [ ] **Step 2: Run the tests and verify the new interfaces are missing**

Run: `pytest tests/test_revision.py::test_mechanical_repairs_leave_ambiguous_quotes_and_report_them tests/test_revision.py::test_patch_group_rolls_back_when_second_anchor_is_not_unique -v`

Expected: FAIL during import because `repair_mechanical_text` and `apply_patch_group` do not exist.

- [ ] **Step 3: Implement the smallest exact-patch engine and whitelist**

```python
def apply_patch_group(manuscript: str, group: dict, source_hash: str) -> dict:
    if hashlib.sha256(manuscript.encode("utf-8")).hexdigest() != source_hash:
        return {"accepted": False, "text": manuscript,
                "failures": [{"patch": 0, "code": "source_hash_changed"}], "diffs": []}
    candidate = manuscript
    diffs = []
    for number, patch in enumerate(group.get("patches", []), 1):
        old = str(patch.get("old_text") or "")
        new = str(patch.get("new_text") or "")
        operation = patch.get("operation")
        if not old or candidate.count(old) != 1:
            return {"accepted": False, "text": manuscript,
                    "failures": [{"patch": number, "code": "anchor_not_unique"}], "diffs": []}
        if operation == "replace":
            replacement = new
        elif operation == "insert_before":
            replacement = new + old
        elif operation == "insert_after":
            replacement = old + new
        else:
            return {"accepted": False, "text": manuscript,
                    "failures": [{"patch": number, "code": "operation_invalid"}], "diffs": []}
        start = candidate.index(old)
        candidate = candidate[:start] + replacement + candidate[start + len(old):]
        diffs.append({"patch": number, "start": start, "old_text": old, "new_text": replacement})
    return {"accepted": True, "text": candidate, "failures": [], "diffs": diffs}
```

Keep `normalize_chinese_prose()` backward compatible, but implement `repair_mechanical_text()` as the authoritative whitelist: paired simple ASCII dialogue quotes only, Han-to-Han spaces, three-or-more repeated Chinese punctuation, C0 controls except `\n` and `\t`, and exact consecutive duplicate blocks. Every applied or blocked repair records a Chinese-facing code mapping; truncated sentences and non-unique quote pairs are report-only.

- [ ] **Step 4: Add contract validation and rerun the focused file**

`normalize_repair_contract()` must reject unknown issue IDs, a stale `manuscript_hash`, empty groups, empty patches, unsupported operations, non-unique `old_text`, groups mixing unrelated issue IDs, and semantic groups without `requires_user_confirmation=True`. It must preserve `required_text`, `forbidden_text`, related entities/events/relations, target word delta, and `requires_full_review`.

Run: `pytest tests/test_revision.py -v`

Expected: all revision tests PASS, including existing polish-plan and duplicate-block tests.

- [ ] **Step 5: Commit the independent patch engine**

```bash
git add src/novel_flywheel/revision.py tests/test_revision.py
git commit -m "feat: add atomic targeted revision patches"
```

### Task 2: Stable Narrative Units and Lightweight Impact Index

**Files:**
- Modify: `src/novel_flywheel/manuscript_analysis.py`
- Modify: `src/novel_flywheel/narrative_ledger.py`
- Test: `tests/test_manuscript_analysis.py`
- Test: `tests/test_narrative_ledger.py`

**Interfaces:**
- Consumes: full manuscript text and existing optional LTP result.
- Produces: `stable_text_units(text: str) -> dict`, `build_impact_index(report: dict) -> dict`, `stable_key(kind: str, text: str, occurrence: int) -> str`; adds `units`, `impact_index`, `source`, and `confidence` fields to analysis without promoting extracted data to `StoryState`.

- [ ] **Step 1: Write failing tests for stable IDs, object links, and source positions**

```python
def test_stable_unit_ids_survive_unrelated_prefix_insertion() -> None:
    before = analyze_manuscript("甲段。\n\n父亲把银锁交给林晚。", nlp_analyze=None)
    after = analyze_manuscript("新增开头。\n\n甲段。\n\n父亲把银锁交给林晚。", nlp_analyze=None)
    before_id = before["units"]["paragraphs"][1]["stable_id"]
    after_id = after["units"]["paragraphs"][2]["stable_id"]
    assert before_id == after_id


def test_impact_index_keeps_evidence_location_and_confidence() -> None:
    report = analyze_manuscript("林晚拿到银锁。\n\n民警登记银锁。", nlp_analyze=None)
    entries = report["impact_index"]["terms"]["银锁"]
    assert [item["paragraph"] for item in entries] == [1, 2]
    assert all(item["source"] in {"rules", "ltp"} for item in entries)
    assert all(0 <= item["confidence"] <= 1 for item in entries)
```

- [ ] **Step 2: Run focused tests and verify the analysis lacks the new structures**

Run: `pytest tests/test_manuscript_analysis.py tests/test_narrative_ledger.py -k "stable_unit or impact_index" -v`

Expected: FAIL with missing `units` or `impact_index`.

- [ ] **Step 3: Add content-derived stable units and evidence provenance**

```python
def stable_key(kind: str, text: str, occurrence: int) -> str:
    normalized = re.sub(r"\s+", "", text)
    digest = hashlib.sha256(f"{kind}\0{normalized}\0{occurrence}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"
```

Build paragraph and scene records with current `start`, `end`, `text_hash`, content-based `stable_id`, and duplicate occurrence ordinal. Keep current offsets for display, but stop using offsets inside relation identity. Each question, promise, setup, payoff, entity, event, and repeated object term must include its source range, unit ID, extractor (`rules` or `ltp`), and confidence.

- [ ] **Step 4: Build the impact index without a new database**

`build_impact_index()` returns JSON-only maps for `entities`, `events`, `terms`, and `relations`; each value is a list of source locations. Add both relation endpoints. Use existing LTP entities/events when available and conservative repeated 2-6 Han-character anchors from ledger items when unavailable. Do not write to `StoryState` or SQLite.

Run: `pytest tests/test_manuscript_analysis.py tests/test_narrative_ledger.py -v`

Expected: PASS, including existing coverage, promises, payoff, and source-hash tests.

- [ ] **Step 5: Commit stable analysis evidence**

```bash
git add src/novel_flywheel/manuscript_analysis.py src/novel_flywheel/narrative_ledger.py tests/test_manuscript_analysis.py tests/test_narrative_ledger.py
git commit -m "feat: add stable narrative impact evidence"
```

### Task 3: Strict Incremental Review Safety and Full-Review Triggers

**Files:**
- Modify: `src/novel_flywheel/incremental_review.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_incremental_review.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `build_impact_index()` output, patch-group metadata, exact current manuscript.
- Produces: `diff_manuscripts(..., mode: str = "short") -> dict`, `select_review_scope(...) -> dict`, `requires_full_review(scope, changes, current_analysis, patch_groups=()) -> tuple[bool, list[str]]`, and `apply_incremental_gate(..., current_manuscript: str, reconciliations: list[dict]) -> tuple[dict, list[str]]`.

- [ ] **Step 1: Write failing hash, empty-scope, relation, and structural-trigger tests**

```python
def test_incremental_gate_rejects_valid_but_stale_analysis_hash() -> None:
    current = "已经修改的正文"
    analysis = _analysis("旧正文")
    baseline = {"coverage": 1.0, "issue_ledger": []}
    review, reasons = apply_incremental_gate(
        {"hard_fail": False}, baseline, {"coverage": 1.0}, analysis,
        current_manuscript=current, reconciliations=[],
    )
    assert review["hard_fail"] is True
    assert "current_analysis_hash_mismatch" in reasons


@pytest.mark.parametrize("flag", [
    "scene_inserted", "scene_deleted", "scene_moved", "climax_changed",
    "principal_goal_changed", "knowledge_state_changed", "key_evidence_changed",
    "locked_fact_changed", "protected_passage_changed",
])
def test_semantic_structure_flags_force_full_review(flag: str) -> None:
    required, reasons = requires_full_review(
        {"selected_ratio": 0.1, "ambiguous": [], "selected_windows": [2]},
        {"changed_ratio": 0.01, flag: True},
        {"nlp": {"available": True}, "prose": {"blocking_count": 0}},
    )
    assert required is True
    assert flag in reasons
```

- [ ] **Step 2: Run focused tests and verify stale 64-character hashes currently pass**

Run: `pytest tests/test_incremental_review.py -v`

Expected: the stale-hash test FAILS because the existing gate validates only hexadecimal shape; new trigger cases also FAIL.

- [ ] **Step 3: Compare the exact current hash and require non-empty, fully explained scope**

```python
expected_hash = hashlib.sha256(current_manuscript.encode("utf-8")).hexdigest()
if current_analysis.get("text_hash") != expected_hash:
    reasons.append("current_analysis_hash_mismatch")
if changes_present and not scope.get("selected_windows"):
    reasons.append("empty_incremental_scope")
if set(scope.get("selected_windows", [])) - {int(key) for key in scope.get("reasons", {})}:
    reasons.append("unexplained_review_window")
```

Pass `manuscript` from `_incremental_manuscript_review()` into the gate. Validate baseline analysis hash against baseline manuscript as well as baseline manuscript hash against the exact revision source hash.

- [ ] **Step 4: Add complete trigger coverage and hierarchical long-mode diff**

For short text retain exact `SequenceMatcher`. For `mode="long"`, compare chapter markers first, then stable scenes, then paragraphs only inside changed scenes; never run unbounded whole-novel character diff. Add reasons for all Global Constraints triggers. A semantic patch with unavailable LTP forces full review; a group containing only `mechanical=True` does not.

Run: `pytest tests/test_incremental_review.py tests/test_workflows.py -k "incremental or full_review" -v`

Expected: PASS; the existing middle-prose-change test still uses fewer than all windows, while every structural case reports `full_fallback` with a specific reason.

- [ ] **Step 5: Commit strict incremental safety**

```bash
git add src/novel_flywheel/incremental_review.py src/novel_flywheel/workflows.py tests/test_incremental_review.py tests/test_workflows.py
git commit -m "fix: enforce safe incremental review scope"
```

### Task 4: Whole-Candidate Gate, StoryState Facts, and Passage Protections

**Files:**
- Create: `src/novel_flywheel/repair_gate.py`
- Modify: `src/novel_flywheel/story_state.py`
- Modify: `src/novel_flywheel/passage_protection.py`
- Create: `tests/test_repair_gate.py`
- Modify: `tests/test_story_state.py`
- Modify: `tests/test_passage_protection.py`

**Interfaces:**
- Consumes: source/candidate text, contract, patch results, current analysis, StoryState data, active passage locks, platform word bounds.
- Produces: `authoritative_fact_snapshot(state: dict) -> dict`, `validate_candidate_protections(candidate: str, locks: list[dict]) -> dict`, and `evaluate_candidate_gate(...) -> dict` with `passed`, `blocking`, `checks`, and `review_mode_hint`.

- [ ] **Step 1: Write failing tests proving the gate blocks model review prerequisites**

```python
def test_candidate_gate_reports_all_blockers_without_mutating_source() -> None:
    source = "父亲留下银锁。\n\n必须删除这句。"
    candidate = "父亲留下银锁。\n\n必须删除这句。"
    result = evaluate_candidate_gate(
        source=source, candidate=candidate,
        source_hash=hashlib.sha256(source.encode()).hexdigest(),
        analysis={"text_hash": hashlib.sha256(candidate.encode()).hexdigest(),
                  "coverage": 1.0, "prose": {"blocking_count": 0}},
        contract={"required_text": ["父亲留下银锁"],
                  "forbidden_text": ["必须删除这句"]},
        patch_results=[{"accepted": True}], story_state={"locked_facts": []},
        passage_locks=[], minimum_han=1, maximum_han=100,
    )
    assert result["passed"] is False
    assert "forbidden_text_remains" in {item["code"] for item in result["blocking"]}
    assert candidate == "父亲留下银锁。\n\n必须删除这句。"


def test_all_active_protections_are_checked_against_complete_candidate(tmp_path) -> None:
    db, service = service(tmp_path)
    source = "喜欢的开头。\n\n中段。\n\n喜欢的结尾。"
    service.create("p", source, excerpt="喜欢的开头。", mode="exact", label="开头")
    service.create("p", source, excerpt="喜欢的结尾。", mode="exact", label="结尾")
    result = validate_candidate_protections("喜欢的开头。\n\n中段改了。", db.list_locks("p"))
    assert [item["label"] for item in result["conflicts"]] == ["结尾"]
```

- [ ] **Step 2: Run focused tests and verify `repair_gate.py` is absent**

Run: `pytest tests/test_repair_gate.py tests/test_story_state.py tests/test_passage_protection.py -v`

Expected: FAIL importing `novel_flywheel.repair_gate` and `validate_candidate_protections`.

- [ ] **Step 3: Implement a pure gate that accumulates, rather than hides, failures**

```python
def _check(code: str, passed: bool, message: str) -> dict:
    return {"code": code, "passed": passed, "message": message}


def evaluate_candidate_gate(*, source: str, candidate: str, source_hash: str,
                            analysis: dict, contract: dict, patch_results: list[dict],
                            story_state: dict, passage_locks: list[dict],
                            minimum_han: int, maximum_han: int) -> dict:
    checks = []
    checks.append(_check("source_hash_matches",
        hashlib.sha256(source.encode("utf-8")).hexdigest() == source_hash,
        "修改来源仍然是本轮开始时的稿件"))
    checks.append(_check("analysis_hash_matches",
        analysis.get("text_hash") == hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        "本地分析对应当前候选稿"))
    checks.extend(_literal_checks(candidate, contract))
    checks.extend(_patch_group_checks(patch_results))
    checks.extend(_story_state_checks(source, candidate, story_state))
    checks.extend(_protection_checks(candidate, passage_locks))
    checks.extend(_length_and_prose_checks(candidate, analysis, minimum_han, maximum_han))
    blocking = [item for item in checks if not item["passed"]]
    return {"passed": not blocking, "blocking": blocking, "checks": checks,
            "review_mode_hint": "blocked" if blocking else "incremental_candidate"}
```

Use existing `effective_han_characters()` rather than `len()`. The gate must check coverage `1.0`, zero local blockers, zero plan-external diff, zero partial groups, required and forbidden text, protections, locked facts, and bounds. It must not call a model or write a file.

- [ ] **Step 4: Make whole-candidate protection and fact checks authoritative**

`authoritative_fact_snapshot()` returns only locked facts, confirmed facts, world rules, character states, and timeline events. `validate_candidate_protections()` reads all active locks, locates exact or soft-normalized text in the complete candidate, honors `allow_next_change`, and reports ambiguous/missing/mutated content without consuming permissions. Permission is consumed only after the user adopts the group.

Run: `pytest tests/test_repair_gate.py tests/test_story_state.py tests/test_passage_protection.py -v`

Expected: PASS; existing segment-level protection behavior remains compatible.

- [ ] **Step 5: Commit the local candidate gate**

```bash
git add src/novel_flywheel/repair_gate.py src/novel_flywheel/story_state.py src/novel_flywheel/passage_protection.py tests/test_repair_gate.py tests/test_story_state.py tests/test_passage_protection.py
git commit -m "feat: gate revision candidates before review"
```

### Task 5: Stable Issue States and Promotion Rules

**Files:**
- Modify: `src/novel_flywheel/quality.py`
- Modify: `src/novel_flywheel/quality_profiles.py`
- Modify: `src/novel_flywheel/quality_summary.py`
- Test: `tests/test_quality.py`
- Test: `tests/test_quality_profiles.py`
- Test: `tests/test_quality_summary.py`

**Interfaces:**
- Consumes: current issue ledger, reconciliation results, user decision.
- Produces: `update_issue_status(ledger: list[dict], issue_id: str, status: str, evidence: str = "") -> list[dict]`; statuses `resolved`, `partially_resolved`, `unresolved`, `uncertain`, and `preserved`; mandatory issues accept only `resolved`.

- [ ] **Step 1: Write failing tests for user preservation and mandatory blockers**

```python
def test_advisory_issue_can_be_preserved_but_mandatory_issue_cannot() -> None:
    advisory = issue_ledger([{"category": "style", "severity": "low", "action": "换一种表达"}])
    kept = update_issue_status(advisory, advisory[0]["issue_id"], "preserved")
    assert kept[0]["status"] == "preserved"

    mandatory = issue_ledger([{"category": "production_text", "severity": "critical",
                               "action": "删除残留"}])
    with pytest.raises(ValueError, match="必须处理"):
        update_issue_status(mandatory, mandatory[0]["issue_id"], "preserved")


def test_unresolved_mandatory_issue_blocks_candidate_promotion() -> None:
    result = compare_quality_candidates(best_review(), {
        **better_review(),
        "issues": [{"issue_id": "hard-1", "severity_class": "blocking", "status": "unresolved"}],
    })
    assert result["promote"] is False
    assert "unresolved_mandatory_issue" in result["reasons"]
```

- [ ] **Step 2: Run focused quality tests and verify missing status behavior**

Run: `pytest tests/test_quality.py tests/test_quality_profiles.py tests/test_quality_summary.py -k "preserved or mandatory" -v`

Expected: FAIL because `update_issue_status` and mandatory-promotion checks are absent.

- [ ] **Step 3: Implement stable status updates without changing issue identity**

```python
ALLOWED_ISSUE_STATUSES = {
    "resolved", "partially_resolved", "unresolved", "uncertain", "preserved",
}

def update_issue_status(ledger: list[dict], issue_id: str, status: str,
                        evidence: str = "") -> list[dict]:
    if status not in ALLOWED_ISSUE_STATUSES:
        raise ValueError("问题状态无效")
    result = []
    for item in ledger:
        if item.get("issue_id") != issue_id:
            result.append(dict(item))
            continue
        if status == "preserved" and item.get("severity_class") == "blocking":
            raise ValueError("必须处理的问题不能保留原写法")
        result.append({**item, "status": status, "reconciliation_evidence": evidence})
    return result
```

Keep the existing content-derived `issue_id` when status, evidence, or user decision changes. Treat `partially_resolved`, `unresolved`, and `uncertain` major issues as full-review or promotion blockers. UI summaries must label these states in Chinese.

- [ ] **Step 4: Verify scoring-profile and judge comparability remain intact**

Run: `pytest tests/test_quality.py tests/test_quality_profiles.py tests/test_quality_summary.py -v`

Expected: PASS, including existing 2-point gain, 3-point dimension regression, and new-major-issue tests.

- [ ] **Step 5: Commit issue-state rules**

```bash
git add src/novel_flywheel/quality.py src/novel_flywheel/quality_profiles.py src/novel_flywheel/quality_summary.py tests/test_quality.py tests/test_quality_profiles.py tests/test_quality_summary.py
git commit -m "feat: track targeted revision issue decisions"
```

### Task 6: Patch Context, Output Budgets, and Non-Repeating Retry Decisions

**Files:**
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_context_policy.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: patch size, provider ceiling, current output limit, failure kind, attempt number.
- Produces: `revision_patch_context(...) -> str`, `patch_output_budget(allowed_characters: int, provider_limit: int) -> int`, and `next_retry_action(...) -> dict` returning `retry_larger`, `split`, `schema_repair`, `fallback`, or `stop`.

- [ ] **Step 1: Write failing tests for output-ceiling and JSON-only repair**

```python
def test_retry_at_provider_ceiling_splits_instead_of_repeating() -> None:
    decision = next_retry_action(
        failure_kind="output_limit", attempt=1,
        current_limit=8192, provider_limit=8192,
    )
    assert decision == {"action": "split", "next_limit": 8192}


def test_invalid_json_retry_does_not_resend_manuscript() -> None:
    decision = next_retry_action(
        failure_kind="invalid_json", attempt=1,
        current_limit=4096, provider_limit=8192,
    )
    assert decision["action"] == "schema_repair"
    prompt = schema_repair_prompt('{"patches": [', "repair_patch_v1")
    assert "MANUSCRIPT SEGMENT" not in prompt
```

- [ ] **Step 2: Run focused tests and demonstrate the current fixed-limit behavior**

Run: `pytest tests/test_context_policy.py tests/test_workflows.py -k "output_ceiling or invalid_json_retry" -v`

Expected: FAIL because retry decisions are currently embedded in workflow behavior and the same 8192 ceiling can recur.

- [ ] **Step 3: Implement deterministic retry decisions**

```python
def next_retry_action(*, failure_kind: str, attempt: int,
                      current_limit: int, provider_limit: int) -> dict:
    if failure_kind == "invalid_json":
        return {"action": "schema_repair", "next_limit": min(current_limit, 4096)}
    if failure_kind == "output_limit" and current_limit < provider_limit:
        return {"action": "retry_larger", "next_limit": provider_limit}
    if failure_kind == "output_limit":
        return {"action": "split", "next_limit": current_limit}
    if attempt == 1:
        return {"action": "fallback", "next_limit": current_limit}
    return {"action": "stop", "next_limit": current_limit}
```

`revision_patch_context()` includes only the issue, target paragraph, one paragraph on each side, linked evidence summaries, seven-step position, authoritative facts, protected-passage summaries, allowed range, and word target. `patch_output_budget()` derives from allowed output size and the real provider ceiling; it never reports a higher retry when the numeric limit is unchanged.

- [ ] **Step 4: Route existing structural retries through the new decision**

Update `_stage`, `_polish_short_segments`, and revision-plan parsing call sites so malformed JSON uses a short schema-repair prompt, output-limit failures split the current patch, the second execution failure uses the configured role fallback, and both routes failing stop only that group.

Run: `pytest tests/test_context_policy.py tests/test_workflows.py -k "token or retry or fallback or split" -v`

Expected: PASS; no test makes an external network request.

- [ ] **Step 5: Commit retry policy**

```bash
git add src/novel_flywheel/context_policy.py src/novel_flywheel/workflows.py tests/test_context_policy.py tests/test_workflows.py
git commit -m "fix: prevent ineffective model retries"
```

### Task 7: Hash-Bound Repair Run Records and Checkpoints

**Files:**
- Create: `src/novel_flywheel/repair_records.py`
- Create: `tests/test_repair_records.py`

**Interfaces:**
- Consumes: a current run output directory and JSON-compatible contract/groups/checkpoint/report values.
- Produces: `RepairRunStore(run_path: Path)` with `write_contract`, `write_groups`, `write_checkpoint`, `write_candidate`, `write_report`, and `load_resume_state(source_hash: str) -> dict`.

- [ ] **Step 1: Write failing artifact and stale-resume tests**

```python
def test_repair_store_writes_exact_named_artifacts_atomically(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    store.write_contract({"manuscript_hash": "a" * 64})
    store.write_groups({"groups": []})
    store.write_checkpoint({"source_hash": "a" * 64, "completed_groups": []})
    store.write_candidate("候选稿")
    store.write_report({"status": "waiting_confirmation"})
    assert {path.name for path in (tmp_path / "run" / "outputs").iterdir()} == {
        "repair-contract.json", "patch-groups.json", "repair-checkpoint.json",
        "candidate.md", "repair-report.json",
    }


def test_resume_rejects_changed_protected_best_hash(tmp_path) -> None:
    store = RepairRunStore(tmp_path / "run")
    store.write_checkpoint({"source_hash": "a" * 64, "completed_groups": ["g1"]})
    with pytest.raises(ValueError, match="最佳稿已经变化"):
        store.load_resume_state("b" * 64)
```

- [ ] **Step 2: Run the tests and verify the module is absent**

Run: `pytest tests/test_repair_records.py -v`

Expected: FAIL importing `novel_flywheel.repair_records`.

- [ ] **Step 3: Implement the focused run-artifact store using existing atomic writes**

```python
class RepairRunStore:
    def __init__(self, run_path: Path) -> None:
        self.output = run_path / "outputs"
        self.output.mkdir(parents=True, exist_ok=True)

    def _write_json(self, name: str, value: dict) -> None:
        atomic_write(self.output / name, json.dumps(value, ensure_ascii=False, indent=2))

    def write_candidate(self, text: str) -> None:
        atomic_write(self.output / "candidate.md", text)

    def load_resume_state(self, source_hash: str) -> dict:
        value = json.loads((self.output / "repair-checkpoint.json").read_text(encoding="utf-8"))
        if value.get("source_hash") != source_hash:
            raise ValueError("最佳稿已经变化，请重新确认需要处理的问题")
        return value
```

Add explicit methods for the four JSON files. Reject invalid JSON, missing source hash, candidate hash mismatch, duplicate group IDs, or completed IDs absent from `patch-groups.json`. This module does not write SQLite, formal prose, best-candidate files, or StoryState.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_repair_records.py -v`

Expected: PASS.

- [ ] **Step 5: Commit repair record persistence**

```bash
git add src/novel_flywheel/repair_records.py tests/test_repair_records.py
git commit -m "feat: persist resumable repair checkpoints"
```

### Task 8: Targeted Short-Revision Workflow and Pre-Review Gate

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/tasks.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Consumes: selected `issue_ids`, current protected-best checkpoint, `RepairRunStore`, patch engine, whole-candidate gate, existing `revision_plan`, `polish`, `draft`, `final_review` roles.
- Produces: `WorkflowService.run_short_revision(project_id: str, issue_ids: list[str], run_id: str | None = None) -> dict` and a `short-revision` run whose partial checkpoints remain resumable.

- [ ] **Step 1: Write failing workflow tests for zero-review gate and independent-group preservation**

```python
@pytest.mark.asyncio
async def test_failed_local_gate_makes_zero_final_review_calls(tmp_path) -> None:
    service, project, calls = repair_service(tmp_path, source="必须删除这句。")
    service._stage = stage_recorder(calls, patch_text="必须删除这句。")
    result = await service.run_short_revision(project.id, ["issue-delete"], run_id="repair-1")
    assert result["status"] == "waiting_local_fix"
    assert "final_review" not in calls
    assert (project.path / "runs" / "repair-1" / "outputs" / "candidate.md").is_file()


@pytest.mark.asyncio
async def test_independent_successful_group_survives_other_group_failure(tmp_path) -> None:
    service, project, _calls = repair_service(tmp_path, source="甲问题。\n\n乙问题。\n\n乙问题。")
    result = await service.run_short_revision(project.id, ["issue-a", "issue-b"], run_id="repair-2")
    report = json.loads((project.path / "runs" / "repair-2" / "outputs" / "repair-report.json").read_text(encoding="utf-8"))
    assert report["groups"]["issue-a"]["status"] == "ready_for_confirmation"
    assert report["groups"]["issue-b"]["status"] == "failed"
    assert "甲已修复" in result["candidate"]
    assert result["protected_best_unchanged"] is True
```

- [ ] **Step 2: Run focused tests and verify `run_short_revision` is missing**

Run: `pytest tests/test_workflows.py tests/test_tasks.py -k "short_revision or local_gate" -v`

Expected: FAIL with missing workflow method and workflow type.

- [ ] **Step 3: Implement the revision orchestration in the existing service**

The method must:

1. Resolve the hash-bound protected best and matching terminal issue ledger.
2. Validate selected IDs and freeze StoryState revision, locks, review, source hash, and analysis.
3. Write `repair-contract.json` before any model call.
4. Apply mechanical groups locally and request structured plans only for semantic groups.
5. Generate and validate one atomic group at a time, checkpointing after each result.
6. Analyze the complete temporary candidate and call `evaluate_candidate_gate()` as a preflight check.
7. Stop with a Chinese event and zero terminal-review calls when the preflight gate fails.
8. Write `candidate.md` and `repair-report.json` with status `waiting_confirmation`; do not call terminal review until the user has adopted or rejected every semantic group.
9. Do not write `manuscript/story.md`, `best-candidate.md`, or StoryState.

Use an explicit signature:

```python
async def run_short_revision(self, project_id: str, issue_ids: list[str],
                             run_id: str | None = None) -> dict:
    project = self.projects.get(project_id)
    if project.mode != "short":
        raise ValueError("定向返修目前只支持短篇作品")
    return await self._short_revision_pipeline(project, issue_ids, run_id)
```

- [ ] **Step 4: Preserve partial completion and resume from the first unfinished group**

On cancellation/provider failure, write completed groups and the current failure before re-raising. `RunTaskManager` keeps the run `failed` or `cancelled`, not `completed`; resume reuses the same run ID and calls `RepairRunStore.load_resume_state()` against the current protected-best hash. A changed best stops before a model call.

Run: `pytest tests/test_workflows.py tests/test_tasks.py -k "short_revision or repair_checkpoint or protected_best" -v`

Expected: PASS; existing failed-short-run resume and best-candidate restoration tests also remain green.

- [ ] **Step 5: Commit the targeted workflow**

```bash
git add src/novel_flywheel/workflows.py src/novel_flywheel/tasks.py tests/test_workflows.py tests/test_tasks.py
git commit -m "feat: add resumable targeted short revision"
```

### Task 9: Expansion Is a Drafted Scene Patch, Not Ordinary Polish

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prompts.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_skill_prompts.py`

**Interfaces:**
- Consumes: platform minimum Han count, seven-step causal-chain artifact, selected structural issues, existing `revision_plan` and `draft` role bindings.
- Produces: expansion contracts with `purpose`, `target_han`, `entry_state`, `exit_state`, `anchor`, and `requires_full_review=True`; generated scenes remain normal patch groups.

- [ ] **Step 1: Write a failing test proving a length deficit bypasses ordinary polish**

```python
@pytest.mark.asyncio
async def test_length_deficit_routes_to_draft_scene_patch_and_full_review(tmp_path) -> None:
    service, project, calls = expansion_service(tmp_path, current_han=7000, minimum_han=9000)
    await service.run_short_revision(project.id, ["issue-length"], run_id="expand-1")
    assert calls[:2] == ["revision_plan", "draft"]
    assert "polish" not in calls
    report = read_repair_report(project, "expand-1")
    assert report["review_mode"] == "full"
    assert report["full_review_reasons"] == ["scene_inserted"]
```

- [ ] **Step 2: Run the focused expansion test and verify current structural polish is used**

Run: `pytest tests/test_workflows.py -k "length_deficit_routes" -v`

Expected: FAIL because no dedicated scene-expansion branch exists.

- [ ] **Step 3: Add the expansion planning contract and draft prompt**

```python
EXPANSION_CONTRACT = (
    "为每个新增场景返回 purpose、target_han、entry_state、exit_state、old_text、operation。"
    "优先补充调查受阻、选择代价、证据验证、关系变化和结尾兑现；不得用背景说明凑字数。"
)
```

Compute the exact deficit locally. `revision_plan` chooses one or more anchors and allocates target Han characters; `draft` generates each scene separately using the existing role and skill set. Validate entry/exit character state, time, evidence source, transition, new facts, word bounds, and atomic group application.

- [ ] **Step 4: Force full review and verify no direct formal write**

Every inserted/deleted/moved/merged scene sets the structural flags consumed by Task 3. Even if the final length is valid, the candidate must perform one complete terminal review. Assert `manuscript/story.md` and the protected checkpoint remain byte-identical before user adoption.

Run: `pytest tests/test_workflows.py tests/test_skill_prompts.py -k "expansion or length_deficit or structural" -v`

Expected: PASS.

- [ ] **Step 5: Commit scene expansion routing**

```bash
git add src/novel_flywheel/workflows.py src/novel_flywheel/prompts.py tests/test_workflows.py tests/test_skill_prompts.py
git commit -m "feat: route short-story expansion through draft"
```

### Task 10: Default Enablement and Idempotent Existing-Project Migration

**Files:**
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Test: `tests/test_projects.py`
- Test: `tests/api/test_learning.py`

**Interfaces:**
- Consumes: project mode and existing `project.json` metadata.
- Produces: new short projects with `optimized_local_review_enabled=True`; existing short projects missing the key receive `True` once; explicit `False` remains `False`; long projects remain unchanged.

- [ ] **Step 1: Write failing migration/default tests**

```python
def test_new_short_defaults_to_optimized_review(tmp_path) -> None:
    store = ProjectStore(Database(tmp_path / "app.db"), tmp_path / "projects")
    project = store.create(ProjectCreate(
        title="短篇", mode="short", genre="悬疑", premise="失踪", target_words=10000,
    ))
    assert project.metadata["optimized_local_review_enabled"] is True


def test_existing_missing_flag_migrates_once_but_explicit_false_is_preserved(tmp_path) -> None:
    store, missing, disabled = existing_short_projects(tmp_path)
    assert store.get(missing).metadata["optimized_local_review_enabled"] is True
    assert store.get(disabled).metadata["optimized_local_review_enabled"] is False
    first = (store.get(missing).path / "project.json").read_bytes()
    ProjectStore(store.db, store.workspace_root)
    assert (store.get(missing).path / "project.json").read_bytes() == first
```

- [ ] **Step 2: Run focused project tests and verify current default is false/missing**

Run: `pytest tests/test_projects.py tests/api/test_learning.py -k "optimized_review or workflow_analysis" -v`

Expected: FAIL because `ProjectStore.create()` currently omits the field and API defaults missing values to false.

- [ ] **Step 3: Implement the narrow, reversible metadata migration**

Add the field during new short creation. During `ProjectStore` initialization, update only short projects where the key is absent. Before the first write create an idempotent `snapshots/optimized-review-default/project.json` copy through `ProjectSnapshot`; use `atomic_write` for updated JSON. Never alter explicit false, long projects, or other metadata.

```python
if payload.mode == "short":
    metadata["optimized_local_review_enabled"] = True
```

- [ ] **Step 4: Keep the explicit feature toggle and old full-review path**

The existing GET/PUT workflow-analysis endpoints return the stored value. A user setting false remains false after process restart and routes later revisions to the existing full-review behavior.

Run: `pytest tests/test_projects.py tests/api/test_learning.py -v`

Expected: PASS, including idempotence and explicit-disable tests.

- [ ] **Step 5: Commit the migration**

```bash
git add src/novel_flywheel/projects.py src/novel_flywheel/api/learning.py tests/test_projects.py tests/api/test_learning.py
git commit -m "feat: enable safe local review for short projects"
```

### Task 11: Revision API, Adoption, Rejection, and Resume

**Files:**
- Create: `src/novel_flywheel/api/revisions.py`
- Modify: `src/novel_flywheel/api/runs.py`
- Modify: `src/novel_flywheel/app.py`
- Create: `tests/api/test_revisions.py`
- Modify: `tests/api/test_runs.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `WorkflowService.run_short_revision`, existing run task manager, repair artifacts, current StoryState revision and quality checkpoint.
- Produces:
  - `POST /api/projects/{project_id}/revisions` with `{"issue_ids": [str]}`.
  - `GET /api/runs/{run_id}/revision`.
  - `POST /api/runs/{run_id}/revision/groups/{group_id}/adopt`.
  - `POST /api/runs/{run_id}/revision/groups/{group_id}/reject`.
  - `POST /api/runs/{run_id}/revision/finalize` after every semantic group has a user decision.
  - existing `POST /api/runs/{run_id}/resume` supports `short-revision`.

- [ ] **Step 1: Write failing API tests for selection, adoption, rejection, and resume**

```python
def test_start_revision_requires_selected_known_issues(client, project_with_issues) -> None:
    response = client.post(f"/api/projects/{project_with_issues}/revisions", json={"issue_ids": []})
    assert response.status_code == 422


def test_adopt_group_requires_matching_candidate_hash(client, revision_run) -> None:
    response = client.post(
        f"/api/runs/{revision_run}/revision/groups/group-1/adopt",
        json={"candidate_hash": "0" * 64},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_candidate_changed"


def test_failed_short_revision_resumes_same_run_id(client, db, project_id) -> None:
    db.create_run("repair-failed", project_id, "short-revision", status="failed")
    response = client.post("/api/runs/repair-failed/resume")
    assert response.status_code == 202
    assert response.json()["id"] == "repair-failed"


def test_finalize_refuses_undecided_semantic_group(client, revision_run) -> None:
    response = client.post(f"/api/runs/{revision_run}/revision/finalize")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_decisions_incomplete"
```

- [ ] **Step 2: Run API tests and verify all new routes return 404**

Run: `pytest tests/api/test_revisions.py tests/api/test_runs.py tests/test_app.py -k "revision" -v`

Expected: FAIL because the revision router is not registered and resume rejects `short-revision`.

- [ ] **Step 3: Implement typed payloads and start/read routes**

```python
class StartRevisionPayload(BaseModel):
    issue_ids: list[str] = Field(min_length=1, max_length=50)


class GroupDecisionPayload(BaseModel):
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
```

The start route verifies the current candidate and selected issue IDs before creating a `short-revision` task. The read route returns plain fields from `repair-report.json`, group summaries, and run status; it does not expose raw provider errors or internal prompts.

- [ ] **Step 4: Implement decision and resume semantics through existing candidate authority**

Adoption verifies source/candidate hashes and group readiness, then records the user decision; rejection records only that group as rejected and returns its issue to `unresolved`. Neither decision calls terminal review. `finalize` requires every semantic group to be adopted or rejected, reconstructs the candidate from the frozen source plus adopted groups, reruns the whole-candidate gate, and only then routes the exact final hash to incremental/full review and quality comparison. Resume accepts `short-revision`, reloads the selected IDs from the contract, and reuses the same run ID.

Run: `pytest tests/api/test_revisions.py tests/api/test_runs.py tests/test_app.py -k "revision" -v`

Expected: PASS.

- [ ] **Step 5: Commit API integration**

```bash
git add src/novel_flywheel/api/revisions.py src/novel_flywheel/api/runs.py src/novel_flywheel/app.py tests/api/test_revisions.py tests/api/test_runs.py tests/test_app.py
git commit -m "feat: expose targeted revision operations"
```

### Task 12: Compact Chinese Revision Workspace

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`

**Interfaces:**
- Consumes: Task 11 API responses and existing candidate-quality workspace.
- Produces: issue selection, five-stage progress, collapsed group comparisons, adopt/reject/preserve actions, and explicit incremental/full-review reason text.

- [ ] **Step 1: Write failing static-contract tests for Chinese copy and controls**

```python
def test_revision_workspace_has_plain_chinese_controls(tmp_path) -> None:
    html, script, _css = console_assets()
    assert "修复已选问题" in script
    assert "正在确认修改位置" in script
    assert "正在检查是否影响其他剧情" in script
    assert "采用这组修改" in script
    assert "拒绝这组修改" in script
    assert "保留原写法" in script
    for forbidden in ("RAG", "hash", "patch transaction", "reconciliation"):
        assert forbidden not in html + script


def test_revision_progress_keeps_failure_and_next_action_visible(tmp_path) -> None:
    _html, script, _css = console_assets()
    assert "已保留当前最佳稿" in script
    assert "可以从失败的问题继续" in script
```

- [ ] **Step 2: Run the console tests and verify the controls are absent**

Run: `pytest tests/test_console.py -k "revision_workspace or revision_progress" -v`

Expected: FAIL on missing copy and control hooks.

- [ ] **Step 3: Add one compact section inside the existing quality workspace**

Add `#quality-revision-workspace` below the current priority issues. Each issue row shows category badge, status, title, plain-language impact, evidence location, suggested change, and affected-position count. Details remain collapsed. Mandatory issues are selected initially; advice is not. The primary label is exactly `修复已选问题（N项）`.

Use semantic buttons and stable dimensions:

```html
<section id="quality-revision-workspace" aria-live="polite" hidden>
  <div id="revision-issue-selection"></div>
  <div id="revision-operation-status" class="operation-status"></div>
  <div id="revision-group-results"></div>
</section>
```

- [ ] **Step 4: Implement polling and group confirmation without English leakage**

Map phases to the five design labels. Completed progress must stop animation. Failure cards say which issue failed, what was preserved, and the next available action. Render before/after in two readable unframed columns on desktop and stacked blocks on mobile; show local checks and related positions behind one details control. Disable adopt until the group is ready and candidate hash is current.

Run: `pytest tests/test_console.py -v`

Expected: PASS, including existing candidate-quality, rejected-node, and progress-state tests.

- [ ] **Step 5: Commit the UI**

```bash
git add src/novel_flywheel/static/index.html src/novel_flywheel/static/app.js src/novel_flywheel/static/app.css tests/test_console.py
git commit -m "feat: add clear targeted revision workspace"
```

### Task 13: Single Console Instance on Port 8765

**Files:**
- Modify: `src/novel_flywheel/launcher.py`
- Modify: `src/novel_flywheel/app.py`
- Modify: `tests/test_launcher.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: preferred port and resolved data directory.
- Produces: `data_dir_fingerprint(path: Path) -> str`, `probe_existing_console(port: int, fingerprint: str) -> bool`; `/api/health` returns service identity and fingerprint; no random fallback port.

- [ ] **Step 1: Write failing tests for same-service reuse and foreign-port refusal**

```python
def test_launcher_reuses_same_console_instead_of_random_port(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe_existing_console", lambda port, fingerprint: True)
    opened = []
    result = launcher.resolve_launch(8765, tmp_path, opened.append)
    assert result == {"action": "reuse", "url": "http://127.0.0.1:8765"}
    assert opened == ["http://127.0.0.1:8765"]


def test_launcher_refuses_foreign_process_on_8765(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe_existing_console", lambda port, fingerprint: False)
    with pytest.raises(SystemExit, match="8765端口已被其他程序占用"):
        launcher.resolve_launch(8765, tmp_path, lambda url: None)
```

- [ ] **Step 2: Run launcher tests and verify current random-port fallback**

Run: `pytest tests/test_launcher.py tests/test_app.py -k "launcher or health" -v`

Expected: FAIL because `find_free_port()` currently binds a random port when 8765 is occupied.

- [ ] **Step 3: Add a non-sensitive data-directory fingerprint and health response**

```python
def data_dir_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
```

Return `{"status":"ok","service":"novel-flywheel-console","data_dir_fingerprint":...}` from health without exposing the absolute path. Probe with standard-library `urllib.request` and a short timeout; do not add a dependency.

- [ ] **Step 4: Replace random fallback with reuse-or-stop**

When 8765 is free, launch normally. When occupied by the same service and same fingerprint, open the existing URL and exit without creating an app or touching active runs. When occupied by any other process or data directory, print the Chinese conflict and exit non-zero. Keep `--port` for explicit test/operator override, but never silently choose another port.

Run: `pytest tests/test_launcher.py tests/test_app.py -k "launcher or health" -v`

Expected: PASS.

- [ ] **Step 5: Commit single-instance behavior**

```bash
git add src/novel_flywheel/launcher.py src/novel_flywheel/app.py tests/test_launcher.py tests/test_app.py
git commit -m "fix: keep one console instance per data directory"
```

### Task 14: Documentation, No-API Regression, and Complete Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`
- Modify: `docs/superpowers/specs/2026-07-28-safe-targeted-revision-design.md` only if implementation changed a named interface or persisted field.

**Interfaces:**
- Consumes: behavior and event names delivered by Tasks 1-13.
- Produces: operator-facing workflow, artifact, rollback, recovery, trigger, and single-instance documentation.

- [ ] **Step 1: Add an executable documentation contract test**

Add to `tests/test_console.py`:

```python
def test_targeted_revision_documentation_names_recovery_and_artifacts() -> None:
    root = Path(__file__).parents[1]
    text = (root / "docs" / "maintenance.md").read_text(encoding="utf-8")
    for required in (
        "repair-contract.json", "patch-groups.json", "repair-checkpoint.json",
        "candidate.md", "repair-report.json", "short-revision", "全文终审",
        "已保留当前最佳稿",
    ):
        assert required in text
```

- [ ] **Step 2: Run the documentation contract and verify it fails before the docs update**

Run: `pytest tests/test_console.py::test_targeted_revision_documentation_names_recovery_and_artifacts -v`

Expected: FAIL on the first missing repair artifact or workflow name.

- [ ] **Step 3: Document the exact operational behavior**

Update README with the user workflow: select problems, local mechanical repairs, semantic group confirmation, candidate gate, incremental/full review, and separate formalization. Update maintenance docs with the five artifact meanings, source-hash resume rule, every full-review trigger, retry decisions, event categories, explicit-disable fallback, migration idempotence, and 8765 reuse/foreign-process behavior. State that extracted ledger evidence is advisory and model APIs are not used by local gates or automated tests.

- [ ] **Step 4: Run all focused suites without external model calls**

Run:

```bash
pytest tests/test_revision.py tests/test_manuscript_analysis.py tests/test_narrative_ledger.py tests/test_incremental_review.py tests/test_repair_gate.py tests/test_repair_records.py tests/test_context_policy.py tests/test_quality.py tests/test_quality_profiles.py tests/test_quality_summary.py tests/test_story_state.py tests/test_passage_protection.py tests/test_workflows.py tests/test_tasks.py tests/test_projects.py tests/test_launcher.py tests/test_console.py tests/test_app.py tests/api/test_learning.py tests/api/test_revisions.py tests/api/test_runs.py -v
```

Expected: PASS with only previously documented framework deprecation warnings; fake gateways show no HTTP traffic.

- [ ] **Step 5: Run the complete regression suite**

Run: `pytest -q`

Expected: all tests PASS. Before any console restart, query the database and verify there are zero `queued`, `running`, or `cancelling` runs.

- [ ] **Step 6: Inspect repository status and commit documentation/tests**

Run: `git status --short`

Expected: only files intentionally changed by this plan are listed; no data, credentials, real manuscripts, run history, or generated provider output appears.

```bash
git add README.md docs/maintenance.md docs/superpowers/specs/2026-07-28-safe-targeted-revision-design.md tests/test_console.py
git commit -m "docs: describe safe targeted revision workflow"
```

## Final Acceptance Matrix

| Acceptance case | Primary automated proof |
|---|---|
| One punctuation repair changes no other prose | `tests/test_revision.py` mechanical diff test |
| Remaining production text makes zero terminal-review calls | `tests/test_workflows.py` local-gate call recorder |
| Character motivation includes same-character and related-event windows | `tests/test_manuscript_analysis.py` and `tests/test_incremental_review.py` impact tests |
| One failed setup/payoff patch rolls back the whole group | `tests/test_revision.py` atomic rollback test |
| Protected passage changes reject candidate and preserve best | `tests/test_repair_gate.py` plus workflow best-hash assertion |
| Opening, climax, ending, ordering, or structural change forces full review | parameterized `tests/test_incremental_review.py` triggers |
| Stale hash, ambiguous mapping, or missing reconciliation cannot pass incrementally | incremental gate tests |
| Independent successful groups survive another group failure | revision workflow checkpoint test |
| Output ceiling splits rather than repeats 8192 unchanged | context-policy and workflow retry tests |
| API interruption/invalid JSON resumes at first unfinished group | repair-record and workflow resume tests |
| Length deficit uses `revision_plan + draft`, never ordinary polish | expansion call-order test |
| UI shows understandable Chinese progress, result, preservation, and next action | `tests/test_console.py` static contract |
| Second launch reuses 8765 or stops; never starts random shared-database service | `tests/test_launcher.py` |
| Existing explicit disable, models, credentials, Skills, data, history, best and formal manuscripts remain usable | migration, app, workflow, and complete regression suites |
