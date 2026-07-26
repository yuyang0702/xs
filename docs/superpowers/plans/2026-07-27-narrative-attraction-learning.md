# Narrative Attraction Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build evidence-backed cross-text narrative attraction learning and use confirmed guidance in the existing 3,000-word short-story workflow.

**Architecture:** Add one deterministic analysis module that produces local candidates and validates model-synthesized attraction maps. Extend `LearningSystem` to pass candidates into existing model roles, save one proposed attraction-map node, and convert confirmed map guidance into the existing creative blueprint. Extend the existing causal-chain prompt and final-review checks; do not add another workflow or model role.

**Tech Stack:** Python 3.12, FastAPI, SQLite, vanilla JavaScript, pytest.

## Global Constraints

- Preserve full-source sentence-safe 3,000-5,000 character windows.
- Never auto-adopt model conclusions or copy source names, settings, plot packaging, distinctive expressions, or consecutive source passages.
- A seven-step fit may be `strong`, `partial`, or `not_applicable`; uncertainty must remain explicit.
- For 3,000 target words, request two to three state-changing cycles.
- Reuse `reference_analysis`, `reference_synthesis`, `creative_blueprint`, `short_causal_chain`, and the existing final-review workflow.
- Missing credentials must fail before paid analysis dispatch with no secret exposure.

---

### Task 1: Deterministic Attraction Candidates And Validation

**Files:**
- Create: `src/novel_flywheel/narrative_attraction.py`
- Create: `tests/test_narrative_attraction.py`

**Interfaces:**
- Produces: `local_attraction_candidates(text: str) -> dict`
- Produces: `normalize_attraction_map(value: dict, text_length: int) -> dict`
- Produces: `compact_attraction_guidance(value: dict) -> dict`

- [ ] **Step 1: Write failing tests for absolute offsets, opening signals, generic wording, accident/reversal separation, and unsupported-map uncertainty**

```python
def test_local_candidates_cover_non_labelled_actions_with_absolute_offsets():
    text = "雨夜里，她把唯一的钥匙递给仇人。\n" + "平静叙述。" * 900 + "门后的人接过钥匙，城门从此失守。"
    result = local_attraction_candidates(text)
    assert result["coverage_percent"] == 100.0
    assert any(item["start"] == text.index("她把唯一的钥匙") for item in result["opening"]["anomaly"])
    assert any(item["start"] > 3000 for item in result["consequences"])

def test_normalizer_does_not_turn_accident_into_reversal_without_prior_evidence():
    value = {"fit":{"level":"partial"}, "accidents":[{"content":"停电"}],
             "reversal":{"content":"停电者是同伴","prior_evidence":[]}}
    result = normalize_attraction_map(value, 1000)
    assert result["reversal"] is None
    assert "反转缺少可回看的前置证据" in result["uncertainties"]
```

- [ ] **Step 2: Run `\.venv\Scripts\python.exe -m pytest -q tests/test_narrative_attraction.py` and verify failure because the module is missing**

- [ ] **Step 3: Implement bounded sentence evidence extraction and strict map normalization**

```python
def local_attraction_candidates(text: str) -> dict:
    return {
        "coverage_percent": 100.0 if text else 0.0,
        "opening": _opening_candidates(text[:500]),
        "questions": _evidence(text, QUESTION_PATTERN),
        "decisions": _evidence(text, DECISION_PATTERN),
        "consequences": _evidence(text, CONSEQUENCE_PATTERN),
        "turns": _evidence(text, TURN_PATTERN),
        "relationship_changes": _evidence(text, RELATIONSHIP_PATTERN),
        "payoffs": _evidence(text, PAYOFF_PATTERN),
        "boundary": "本地结果是候选证据，不等于已确认的七步结构",
    }
```

- [ ] **Step 4: Run the focused tests and verify they pass**

- [ ] **Step 5: Commit with `feat: add evidence-backed attraction candidates`**

### Task 2: Reference Model Synthesis And Proposed Map

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Modify: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: `local_attraction_candidates`, `normalize_attraction_map`
- Produces: `LearningSystem.attraction_map(source_id: str) -> dict | None`
- Produces: one `attraction_map` learning node with `review_state="proposal"`

- [ ] **Step 1: Write failing tests proving local candidates enter window prompts, synthesis returns a proposed map, invalid maps remain uncertain, and absolute window offsets are restored**

```python
async def test_model_analysis_saves_proposed_attraction_map(tmp_path):
    gateway = FakeGateway([WINDOW_JSON, SYNTHESIS_WITH_ATTRACTION_MAP])
    system = make_system(tmp_path, gateway)
    result = await system.model_analyze_reference(import_source(system))
    assert result["attraction_map"]["status"] == "proposed"
    assert "LOCAL CANDIDATES" in gateway.users[0]
    assert result["attraction_map"]["data"]["fit"]["level"] == "strong"
```

- [ ] **Step 2: Run the focused test and verify it fails because no attraction map is produced**

- [ ] **Step 3: Extend window and synthesis prompts, normalize offsets, and save a proposed node only for a valid normalized object**

- [ ] **Step 4: Run `tests/test_learning_system.py` and verify it passes**

- [ ] **Step 5: Commit with `feat: synthesize reference attraction maps`**

### Task 3: Adoption Into Existing Creative Blueprint

**Files:**
- Modify: `src/novel_flywheel/learning.py`
- Modify: `src/novel_flywheel/projects.py`
- Modify: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: confirmed `attraction_map` nodes
- Produces: `creative_blueprint.attraction_guidance: list[dict]`

- [ ] **Step 1: Write a failing test that confirms and adopts a map, then asserts abstract guidance enters constraints while source names and excerpts do not**

```python
def test_adopted_attraction_map_adds_abstract_guidance_only(tmp_path):
    node = save_confirmed_map(source_name="周海晏", excerpt="十块钱保护十年")
    system.adopt(project.id, node["id"])
    constraints = projects.load_constraints(project.id)
    assert "opening_pressure_anomaly_future_promise" in constraints
    assert "周海晏" not in constraints
    assert "十块钱保护十年" not in constraints
```

- [ ] **Step 2: Run the focused test and verify it fails because maps are treated as ordinary mechanisms**

- [ ] **Step 3: Add explicit attraction-map adoption sanitization and blueprint bucket generation**

- [ ] **Step 4: Run learning and project tests and verify they pass**

- [ ] **Step 5: Commit with `feat: adopt abstract attraction guidance`**

### Task 4: Short Planning, Drafting, And Final Review Integration

**Files:**
- Modify: `src/novel_flywheel/causal_chain.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_causal_chain.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `creative_blueprint.attraction_guidance`
- Produces: stronger `short_causal_chain` diagnostics and prompt checks

- [ ] **Step 1: Write failing tests for a 3,000-word two-to-three-cycle range, duplicate outcomes with unchanged state, opening contract, question continuity, relationship progression, and ending cost checks**

```python
def test_three_thousand_word_chain_requires_two_or_three_changing_cycles():
    report = analyze_short_causal_chain(chain_with_two_changes(), 3000)
    assert report["target_cycle_range"] == [2, 3]
    assert report["status"] == "valid"
```

- [ ] **Step 2: Run causal-chain and workflow focused tests and verify the new assertions fail**

- [ ] **Step 3: Extend diagnostics and the existing planning/final-review prompt contracts without adding a new stage**

- [ ] **Step 4: Run causal-chain and workflow suites and verify they pass**

- [ ] **Step 5: Commit with `feat: enforce reader-pull causal checks`**

### Task 5: Human-Readable Learning UI And Credential Preflight

**Files:**
- Modify: `src/novel_flywheel/api/learning.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/api/test_learning.py`
- Modify: `tests/test_console.py`

**Interfaces:**
- Produces: readable attraction-map cards and `422` credential preflight errors

- [ ] **Step 1: Write failing API and console tests for preflight failure and plain-language attraction-map rendering**

```python
def test_model_analysis_preflights_reference_roles(client):
    response = client.post(f"/api/references/{source_id}/model-learn")
    assert response.status_code == 422
    assert "参考分析主模型缺少 API Key" in response.json()["detail"]
```

- [ ] **Step 2: Run the focused tests and verify failure**

- [ ] **Step 3: Add registry preflight and compact cards with collapsed evidence and visible uncertainty**

- [ ] **Step 4: Run API and console tests and verify they pass**

- [ ] **Step 5: Commit with `feat: explain attraction analysis and model readiness`**

### Task 6: End-To-End 3,000-Word Acceptance Run

**Files:**
- Create through API: one short project under `data/projects/`
- Create through workflow: run outputs, formal manuscript, causal chain, quality and originality evidence
- Modify: `README.md`

**Interfaces:**
- Consumes: existing learning-library source `108cdfd34f1f411898c1efd8d63e4e60`
- Produces: one approximately 3,000-word accepted original manuscript

- [ ] **Step 1: Verify the source has 100% local coverage and confirm only abstract attraction guidance**

- [ ] **Step 2: Verify `reference_analysis`, `reference_synthesis`, `planning`, `draft`, `review`, `polish`, `final_review`, and `maintenance` roles resolve with usable credentials**

- [ ] **Step 3: Create a 3,000-word short project with an original premise and run the normal short workflow**

- [ ] **Step 4: Verify manuscript length, causal-chain validity, opening signals, question/payoff ledger, final-review decision, local full-text gate, and originality evidence**

- [ ] **Step 5: If a runtime or model failure occurs, reproduce it, add a failing regression test, implement the smallest fix, rerun from the preserved checkpoint, and repeat the acceptance checks**

- [ ] **Step 6: Document the feature and acceptance workflow in README**

- [ ] **Step 7: Run the complete test suite, `git diff --check`, and server health checks**

- [ ] **Step 8: Commit with `docs: document narrative attraction workflow`, push `main`, and record the final commit and artifact paths**
