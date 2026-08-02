# Normal Underlength and Cross-Story Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a normally terminated but incomplete short-story segment recover through semantic subtasks, and replace genre-specific greedy location matching with project-scoped, confidence-gated continuity validation.

**Architecture:** Add one focused `scene_continuity` module that builds a canonical location catalog from existing project files and classifies only high-confidence transitions as blocking. Keep orchestration in `WorkflowService`: structured draft findings drive ordinary gate messages and cause normal underlength responses to enter the existing recursive semantic-split path.

**Tech Stack:** Python 3.11+, standard library, pytest, existing `WorkflowService`, StoryState, run events, and checkpoint files.

## Global Constraints

- Do not call paid model APIs from tests or maintenance checks.
- Do not lower the existing hard prose length gate.
- Do not hard-code one novel, historical-fiction suffixes, or a fixed genre vocabulary.
- Unknown or ambiguous location inference cannot block by itself.
- Failed candidates never become accepted context or checkpoints.
- Reuse the existing task, causal chain, event assignments, constraints, and checkpoint authority.

---

### Task 1: Project-scoped scene continuity

**Files:**
- Create: `src/novel_flywheel/scene_continuity.py`
- Create: `tests/test_scene_continuity.py`

**Interfaces:**
- Produces: `build_location_catalog(project_path: Path, state: dict) -> dict[str, LocationRef]`
- Produces: `assess_scene_transition(previous_text: str, current_text: str, catalog: dict[str, LocationRef]) -> list[dict]`
- `LocationRef` exposes `name: str` and `root: str`.

- [x] **Step 1: Write failing production-fixture and cross-genre tests**

```python
def test_same_residence_warehouse_handoff_is_not_a_transition_error(tmp_path):
    catalog = {"沈府": LocationRef("沈府", "沈府"), "库房": LocationRef("库房", "沈府")}
    findings = assess_scene_transition(
        "她在库房查清账册，随后与裴砚行站在回廊说话。",
        "库房案刚刚平息，花穗在沈府里逐渐站稳脚跟。",
        catalog,
    )
    assert not any(item["blocking"] for item in findings)

def test_distinct_known_scifi_locations_without_bridge_block():
    catalog = {"远航号": LocationRef("远航号", "远航号"), "月面基地": LocationRef("月面基地", "月面基地")}
    findings = assess_scene_transition("她留在远航号舰桥。", "月面基地的警报突然响起。", catalog)
    assert [item["code"] for item in findings if item["blocking"]] == ["scene_transition_missing"]
```

- [x] **Step 2: Run the new test file and verify RED**

Run: `pytest -q tests/test_scene_continuity.py`
Expected: collection fails because `novel_flywheel.scene_continuity` does not exist.

- [x] **Step 3: Implement catalog parsing and confidence-gated transition assessment**

Use Unicode NFKC and exact project aliases. Parse frontmatter `name` and optional `aliases`; parse bold names in `## Notable Features` as children of the file location. Resolve nested location documents by the longest formal-name prefix. Select the last canonical mention in previous text and first canonical mention in the current opening paragraph. Return no finding for identical locations, a nonblocking `scene_transition_uncertain` for same-root movement without a bridge, and blocking `scene_transition_missing` only for distinct roots without a time/movement/plane bridge.

- [x] **Step 4: Run scene-continuity tests and verify GREEN**

Run: `pytest -q tests/test_scene_continuity.py`
Expected: all tests pass.

### Task 2: Structured draft findings and compatible gate behavior

**Files:**
- Modify: `src/novel_flywheel/workflows.py:4275-4324`
- Modify: `tests/test_workflows.py:1790-1810`

**Interfaces:**
- Produces: `WorkflowService._draft_segment_findings(part, target, previous_parts, location_catalog=None) -> list[dict]`
- Preserves: `WorkflowService._draft_segment_issues(...) -> list[str]` as the blocking-message compatibility wrapper.

- [x] **Step 1: Write failing tests for structured severity and unknown-location compatibility**

```python
def test_draft_findings_keep_underlength_blocking_but_unknown_location_nonblocking():
    findings = WorkflowService._draft_segment_findings(
        "月面基地的灯亮了。" * 5, 1000, ["她留在远航号。" * 20], {}
    )
    assert "underlength" in {item["code"] for item in findings if item["blocking"]}
    assert "scene_transition_missing" not in {item["code"] for item in findings if item["blocking"]}
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/test_workflows.py -k "draft_segment and (findings or transition)"`
Expected: fail because `_draft_segment_findings` does not exist or old greedy matching still blocks.

- [x] **Step 3: Implement the compatibility wrapper and catalog-aware findings**

Move length, prose, duplication, and transition results into dictionaries with `code`, `message`, and `blocking`. The existing `_draft_segment_issues` returns only blocking messages so current callers remain compatible. Remove the greedy suffix regex completely. The workflow builds one catalog from the current project/StoryState and passes it to all draft validations; nonblocking continuity findings generate a warning event but never stop progress alone.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_scene_continuity.py tests/test_workflows.py -k "scene_continuity or draft_segment or transition"`
Expected: all selected tests pass.

### Task 3: Normal-finish underlength semantic splitting

**Files:**
- Modify: `src/novel_flywheel/workflows.py:4804-4998`
- Modify: `tests/test_workflows.py`
- Modify: `docs/maintenance.md`

**Interfaces:**
- Extend: `_draft_short_segment_task(..., event_ids: list[str] | None = None, location_catalog=None, depth: int = 0) -> str`
- Preserve: existing `draft_task_split` event and add metadata `reason`, `event_ids`, `han_characters`, and `target_characters`.

- [x] **Step 1: Write a failing async test for normal terminal underlength**

Use the real `WorkflowService` with the existing fake gateway. Return a normally completed short segment below the hard floor on the parent call, then valid prose for two children. Assert that two semantic child suffixes are requested, the child prompts own contiguous event-ID ranges, the merged text passes the parent gate, and the failed parent candidate is not written as a checkpoint.

- [x] **Step 2: Run the single regression and verify RED**

Run: `pytest -q tests/test_workflows.py -k "normal_finish_underlength_splits_semantically"`
Expected: fail because normal terminal underlength currently returns to the outer one-shot rewrite path.

- [x] **Step 3: Route severe normal underlength into the existing split path**

After `_stage` returns, call structured findings. If `underlength` is blocking, classify the reason as `normal_finish_underlength` and enter the same recursive split path used by `IncompleteModelOutputError`. Split event IDs contiguously; if only one event remains, use entry/conflict and state-change/exit beat ownership. Pass the accepted first child and its ending to the second. Revalidate the merged parent with the same catalog and previous accepted segments.

- [x] **Step 4: Make retry and failure events exact**

Log actual Han characters, target, issue codes, semantic event ownership, and whether the trigger was output limit or normal terminal underlength. Keep the user-visible run as one task.

- [x] **Step 5: Run focused workflow tests**

Run: `pytest -q tests/test_scene_continuity.py tests/test_workflows.py -k "normal_finish_underlength or draft_segment or transition or checkpoint"`
Expected: all selected tests pass.

- [x] **Step 6: Run broader regressions and static checks**

Run: `pytest -q tests/test_context_policy.py tests/test_models.py tests/test_db.py tests/test_workflows.py tests/test_scene_continuity.py`
Expected: all tests pass without real model calls.

Run: `python -m compileall -q src`
Expected: exit code 0.

Run: `git diff --check`
Expected: exit code 0; line-ending notices are non-fatal.

- [x] **Step 7: Run the complete suite**

Run: `pytest -q`
Expected: all tests pass, aside from documented skips and pre-existing deprecation warnings.
