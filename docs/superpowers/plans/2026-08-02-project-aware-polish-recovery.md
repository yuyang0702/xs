# Project-Aware Polish Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make polish validation project-style-aware and route input overflow, output limits, transport failures, and local quality failures through distinct recovery paths without sacrificing story-wide authority.

**Architecture:** Add one deterministic prose-policy module and extend the existing prose metrics, revision assessment, context policy, and workflow orchestration. The existing StoryState, narrative ledger, candidate validation, checkpoint, fallback, and formal commit paths remain authoritative; new helpers only classify soft style evidence, build a lossless polish authority packet, and choose the existing recovery mechanisms safely.

**Tech Stack:** Python 3.12, dataclasses, pathlib/json/re/statistics from the standard library, pytest/pytest-asyncio, existing fake model gateways and SQLite test fixtures.

## Global Constraints

- Preserve story-wide causality, character and knowledge state, timeline order, relationship progression, setup/payoff coverage, protected content, and the confirmed ending in every retry, fallback, compact request, split, and resume path.
- Project style may override only generic soft style thresholds; corruption, truncation, duplication, fact conflict, event loss/escape, and continuity contradictions always block.
- If the full source plus the minimum narrative authority packet plus output reserve cannot fit, split semantically; never keep deleting authority.
- A child result is never authoritative until every child and the merged parent pass validation.
- Existing projects, formal manuscripts, model bindings, Skills, run history, and checkpoints remain readable and unchanged by default.
- Automated tests use fake gateways only and make no paid model calls.
- Update `docs/maintenance.md` in the same implementation commit because workflow, token, recovery, and validation behavior changes.

---

### Task 1: Correct and unify prose sentence metrics

**Files:**
- Modify: `src/novel_flywheel/prose_quality.py`
- Modify: `src/novel_flywheel/local_editorial.py`
- Test: `tests/test_prose_quality.py`
- Test: `tests/test_local_editorial.py`

**Interfaces:**
- Produces: `split_prose_sentences(text: str) -> list[str]`
- Produces: additional `prose_metrics()` keys `sentence_count`, `short_sentence_count`, `paragraph_count`, `one_sentence_paragraph_count`, and `one_sentence_paragraph_ratio`
- Consumes: existing `analyze_prose()` and `prose_metrics()` callers without changing existing metric names

- [ ] **Step 1: Add failing table-driven sentence-boundary tests**

```python
@pytest.mark.parametrize("text, expected", [
    ("她推开门。屋里没有人。灯却亮着。", 3),
    ("“你来了？”她问。\n\n他点头。", 3),
    ("First sentence. Second sentence! Third?", 3),
    ("第一句！）第二句？】第三句。", 3),
    ("第一句。\r\n\r\n第二句。", 2),
])
def test_split_prose_sentences_counts_common_boundaries(text, expected):
    assert len(split_prose_sentences(text)) == expected
```

- [ ] **Step 2: Add the production regression showing a multi-sentence paragraph is not a one-sentence paragraph**

```python
def test_multi_sentence_chinese_paragraph_does_not_extend_single_paragraph_run():
    text = "她停住。风从门缝钻进来。\n\n他回头。\n\n灯灭了。"
    metrics = prose_metrics(text)
    assert metrics["sentence_count"] == 4
    assert metrics["one_sentence_paragraph_run"] == 2
```

- [ ] **Step 3: Run focused tests and verify the current counter fails**

Run: `pytest tests/test_prose_quality.py tests/test_local_editorial.py -q`

Expected: the new Chinese multi-sentence cases fail because `_sentence_count()` only recognizes punctuation followed by a quote or end-of-paragraph.

- [ ] **Step 4: Implement one shared sentence splitter and derive all counts from it**

```python
SENTENCE_TERMINATOR = re.compile(r"(?:……|\.\.\.|[。！？.!?]+)(?:[”’\"'）)】》〉〕］}]*)")

def split_prose_sentences(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    start = 0
    for match in SENTENCE_TERMINATOR.finditer(normalized):
        value = normalized[start:match.end()].strip()
        if value:
            sentences.append(value)
        start = match.end()
    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences
```

Make `_sentence_count()` delegate to `split_prose_sentences()`. Make `local_editorial._sentences()` use the same helper so local review and polish validation cannot disagree on presentation variants.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_prose_quality.py tests/test_local_editorial.py -q`

Expected: PASS.

Commit:

```bash
git add src/novel_flywheel/prose_quality.py src/novel_flywheel/local_editorial.py tests/test_prose_quality.py tests/test_local_editorial.py
git commit -m "fix: unify prose sentence metrics"
```

### Task 2: Resolve project style into a conservative validation policy

**Files:**
- Create: `src/novel_flywheel/prose_policy.py`
- Test: `tests/test_prose_policy.py`

**Interfaces:**
- Produces: immutable `ProseValidationPolicy`
- Produces: `load_prose_validation_policy(project_path: Path) -> ProseValidationPolicy`
- Produces: `infer_narrative_beat_tags(narrative_context: dict[str, Any]) -> frozenset[str]`
- Consumes: existing `style-profile.md` and active `learning/prose_baseline.json`; writes neither file

- [ ] **Step 1: Add failing policy precedence and compatibility tests**

```python
def test_confirmed_baseline_authorizes_short_beats_without_rewriting_project(tmp_path):
    write_active_baseline(tmp_path, {
        "sentence_rhythm": ["在情绪转折、信息揭示和喜剧落点使用短句与留白。"],
    })
    policy = load_prose_validation_policy(tmp_path)
    assert policy.authorized_short_beats == frozenset({
        "emotion_shift", "information_reveal", "comic_turn",
    })
    assert policy.conflicts == ()

def test_market_advice_never_authorizes_soft_override(tmp_path):
    (tmp_path / "market-reference.md").write_text("大量使用短句", encoding="utf-8")
    assert load_prose_validation_policy(tmp_path).authorized_short_beats == frozenset()

def test_ambiguous_or_conflicting_rules_fail_closed(tmp_path):
    write_active_baseline(tmp_path, {
        "sentence_rhythm": ["全篇短句为主", "禁止使用短句"],
    })
    policy = load_prose_validation_policy(tmp_path)
    assert policy.authorized_short_beats == frozenset()
    assert "style_policy_conflict" in policy.conflicts
```

- [ ] **Step 2: Run the new tests and verify the module is missing**

Run: `pytest tests/test_prose_policy.py -q`

Expected: FAIL during import of `novel_flywheel.prose_policy`.

- [ ] **Step 3: Implement explicit source precedence and narrow phrase mapping**

```python
@dataclass(frozen=True)
class ProseValidationPolicy:
    source_ids: tuple[str, ...] = ()
    authorized_short_beats: frozenset[str] = frozenset()
    conflicts: tuple[str, ...] = ()
    absolute_ratio_floor: float = 0.10
    minimum_new_units: int = 3

BEAT_RULES = {
    "emotion_shift": ("情绪转折", "情绪突变", "emotional shift"),
    "information_reveal": ("信息揭示", "真相揭露", "information reveal"),
    "relationship_change": ("关系变化", "关系转折", "relationship change"),
    "suspense_turn": ("悬念建立", "悬念落点", "suspense"),
    "comic_turn": ("喜剧落点", "笑点", "comic turn"),
}
```

Only user/project style files and active confirmed prose baseline can authorize beats. Market/reference files are never read by this function. When an absolute permission and an absolute prohibition conflict, return no authorization and record `style_policy_conflict`.

- [ ] **Step 4: Implement narrative beat inference from structured state changes, promises, setups, payoffs, and relations**

```python
def infer_narrative_beat_tags(context: dict[str, Any]) -> frozenset[str]:
    tags: set[str] = set()
    if context.get("knowledge_changed") or context.get("reveals"):
        tags.add("information_reveal")
    if context.get("relationship_changed"):
        tags.add("relationship_change")
    if context.get("payoffs") or context.get("resolved_promises"):
        tags.add("suspense_turn")
    if any(scene.get("state_changes") for scene in context.get("scenes", []) if isinstance(scene, dict)):
        tags.add("emotion_shift")
    return frozenset(tags)
```

Do not inspect genre labels or free-form prose keywords to infer the current beat.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_prose_policy.py -q`

Expected: PASS.

Commit:

```bash
git add src/novel_flywheel/prose_policy.py tests/test_prose_policy.py
git commit -m "feat: add project prose validation policy"
```

### Task 3: Replace fixed polish thresholds with layered, deduplicated assessment

**Files:**
- Modify: `src/novel_flywheel/revision.py`
- Test: `tests/test_revision.py`

**Interfaces:**
- Extends: `assess_polish_candidate(..., policy: ProseValidationPolicy | None = None, history_metrics: list[dict[str, float]] | None = None, narrative_context: dict[str, Any] | None = None) -> dict[str, Any]`
- Returns compatibility fields `accepted`, `reasons`, `ratio`, `diagnostics`
- Adds `disposition`, `hard_reasons`, `soft_signals`, `signal_families`, `style_allowances`, and `baseline`

- [ ] **Step 1: Add failing tests for hard/soft separation and duplicate-signal collapse**

```python
def test_one_rhythm_evidence_is_one_signal_family():
    result = assess_polish_candidate(source, fragmented_candidate)
    assert result["signal_families"].count("rhythm") == 1
    assert not ({"style_regression", "sentence_rhythm_regression"} <= set(result["reasons"]))

def test_hard_failure_cannot_be_style_authorized():
    result = assess_polish_candidate(
        "她带着钥匙离开。", "她离开。",
        required_literals=["钥匙"],
        policy=ProseValidationPolicy(authorized_short_beats=frozenset({"emotion_shift"})),
        narrative_context={"scenes": [{"state_changes": [{"evidence": "离开"}]}]},
    )
    assert result["disposition"] == "reject"
```

- [ ] **Step 2: Add failing dynamic-baseline and project-authorization tests**

```python
def test_local_short_beat_can_pass_with_explicit_project_allowance():
    result = assess_polish_candidate(
        source, localized_short_candidate,
        policy=authorized_policy,
        narrative_context={"reveals": ["身份被揭开"]},
    )
    assert result["disposition"] == "pass_with_style_allowance"

def test_unknown_style_does_not_auto_allow_severe_fragmentation():
    result = assess_polish_candidate(source, severely_fragmented_candidate)
    assert result["disposition"] == "targeted_repair"
```

- [ ] **Step 3: Run focused tests and confirm fixed `+0.05` logic fails them**

Run: `pytest tests/test_revision.py -q`

Expected: new disposition/policy tests fail; existing hard-integrity tests remain green.

- [ ] **Step 4: Implement robust baseline and signal-family evaluation**

```python
def _robust_boundary(values: list[float], *, floor: float) -> float:
    center = median(values)
    mad = median(abs(value - center) for value in values)
    return center + max(floor, 3 * mad)

ratio_risk = (
    candidate_short_count >= source_short_count + policy.minimum_new_units
    and candidate_short_ratio > max(
        source_short_ratio + policy.absolute_ratio_floor,
        _robust_boundary(history_ratios, floor=policy.absolute_ratio_floor),
    )
)
```

Group short-sentence ratio, short-sentence run, and one-sentence paragraph run into `rhythm`. Keep dialogue, timestamp formula, length, protection, and corruption in separate families. One soft family repairs only when severe and broadly distributed; two independent soft families produce `targeted_repair`. Hard reasons always produce `reject`.

- [ ] **Step 5: Preserve compatibility and run focused tests**

`accepted` is true only for `pass` and `pass_with_style_allowance`. `reasons` remains a stable flattened list for existing workflow/UI consumers. Existing callers that omit policy/history/context receive conservative source-relative behavior.

Run: `pytest tests/test_revision.py tests/test_prose_quality.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/novel_flywheel/revision.py tests/test_revision.py
git commit -m "feat: make polish validation project aware"
```

### Task 4: Build and enforce the minimum polish authority packet

**Files:**
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_context_policy.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: `PolishAuthorityPacket`
- Produces: `build_polish_authority_packet(...) -> PolishAuthorityPacket`
- Produces: `render_polish_authority_packet(packet: PolishAuthorityPacket, *, advisory: dict[str, Any] | None = None) -> str`
- Produces: `classify_input_pressure(*, full_input_tokens: int, authority_input_tokens: int, output_reserve: int, context_window: int | None) -> Literal["full", "compact", "split"]`

- [ ] **Step 1: Add failing lossless-authority tests**

```python
def test_compact_render_keeps_every_authority_field():
    packet = build_packet_fixture()
    rendered = render_polish_authority_packet(packet)
    for value in (
        packet.source, packet.previous_exit, packet.next_entry,
        "EV-00000001", "确认结局", "钥匙不能丢失", "伏笔必须兑现",
    ):
        assert value in rendered

def test_authority_that_cannot_fit_requires_split():
    assert classify_input_pressure(
        full_input_tokens=9000, authority_input_tokens=8500,
        output_reserve=3000, context_window=12000,
    ) == "split"
```

- [ ] **Step 2: Add input-pressure boundary tests**

```python
@pytest.mark.parametrize("window, full, authority, reserve, expected", [
    (None, 50000, 30000, 8000, "full"),
    (20000, 13000, 9000, 3000, "compact"),
    (12000, 9000, 8500, 3000, "split"),
    (20000, 8000, 7000, 3000, "full"),
])
def test_input_pressure_policy(window, full, authority, reserve, expected):
    assert classify_input_pressure(
        full_input_tokens=full, authority_input_tokens=authority,
        output_reserve=reserve, context_window=window,
    ) == expected
```

- [ ] **Step 3: Run tests and verify current compact prompt truncates fields independently**

Run: `pytest tests/test_context_policy.py tests/test_workflows.py -q -k "authority or input_pressure or compact_prompt"`

Expected: new interfaces are missing and current `[:limit]` slices cannot prove full authority retention.

- [ ] **Step 4: Implement immutable packet construction and lossless rendering**

```python
@dataclass(frozen=True)
class PolishAuthorityPacket:
    source: str
    event_ids: tuple[str, ...]
    causal_goal: str
    previous_exit: str
    next_entry: str
    character_state: dict[str, Any]
    locked_facts: tuple[str, ...]
    ending_constraints: tuple[str, ...]
    promises: tuple[str, ...]
    style_rules: tuple[str, ...]
    protected_passages: tuple[dict[str, Any], ...]
    allowed_scope: dict[str, Any]
```

The renderer serializes every field without per-field character slicing. Advisory findings/examples are appended separately and may be bounded. The workflow builds the packet from StoryState, story map event ownership/handoff, narrative ledger, character fingerprints, passage locks, and project policy.

- [ ] **Step 5: Replace `_compact_polish_prompt` slices with authority rendering and add packet hash to checkpoints**

The existing full prompt may contain extra story map and findings. The compact request is `render_polish_authority_packet(packet, advisory=localized_findings)` and therefore differs only by removal of advisory/global duplication. `_save_polish_checkpoint()` stores the packet hash; `_load_polish_checkpoint()` refuses reuse when the hash changes.

- [ ] **Step 6: Run focused tests and commit**

Run: `pytest tests/test_context_policy.py tests/test_skill_prompts.py tests/test_workflows.py -q -k "authority or compact or checkpoint"`

Expected: PASS.

Commit:

```bash
git add src/novel_flywheel/context_policy.py src/novel_flywheel/workflows.py tests/test_context_policy.py tests/test_workflows.py
git commit -m "feat: preserve polish narrative authority"
```

### Task 5: Separate polish recovery paths and make semantic split atomic

**Files:**
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_context_policy.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: `classify_model_failure(exc_or_receipt: object) -> Literal["input_context_overflow", "output_limit", "transport_interrupted", "normal_invalid_output", "provider_rejection"]`
- Extends: `_stage(..., compact_input: bool = False)` without changing default callers
- Changes: `_ordinary_polish_segment()` returns a validated candidate or raises a classified recoverable exception; it no longer converts output-limit failures into compact recovery internally
- Changes: `_split_failed_polish_segment()` remains paragraph-safe and receives the same authority packet for both children

- [ ] **Step 1: Replace obsolete recovery expectations with failing state-machine tests**

```python
async def test_polish_output_limit_expands_same_route_then_splits(tmp_path):
    result = await run_gateway_sequence(
        tmp_path,
        primary=[max_token_empty(), max_token_empty(), child_ok(), child_ok()],
    )
    assert result == source
    assert event_types(result.run_id).count("polish_output_limit_retry") == 1
    assert "polish_segment_split" in event_types(result.run_id)
    assert "polish_compact_retry" not in event_types(result.run_id)

async def test_explicit_input_overflow_compacts_without_losing_authority(tmp_path):
    result = await run_gateway_sequence(tmp_path, primary=[context_overflow(), ok()])
    assert result.calls[1].compact_input is True
    assert_authority_equal(result.calls[0].user, result.calls[1].user)

async def test_transport_retries_same_route_then_configured_fallback(tmp_path):
    result = await run_gateway_sequence(
        tmp_path, primary=[connect_error(), connect_error()], fallback=[ok()],
    )
    assert result.routes == ["primary", "primary", "fallback"]
    assert "polish_segment_split" not in event_types(result.run_id)
```

- [ ] **Step 2: Add atomic split tests**

```python
async def test_one_failed_child_preserves_entire_parent(tmp_path):
    result = await run_split_gateway(tmp_path, left=ok_changed(), right=invalid())
    assert result.text == result.parent_source
    assert not result.authoritative_child_checkpoints

async def test_children_must_pass_merged_parent_validation(tmp_path):
    result = await run_split_gateway(tmp_path, left=ok_changed(), right=duplicate_of_left())
    assert result.text == result.parent_source
    assert "polish_split_parent_rejected" in event_types(result.run_id)
```

- [ ] **Step 3: Run focused tests and confirm current output-limit path compacts instead of splitting**

Run: `pytest tests/test_workflows.py tests/test_context_policy.py -q -k "output_limit or input_overflow or transport or split_parent"`

Expected: obsolete compact-recovery assertions fail and the new classified events are absent.

- [ ] **Step 4: Implement shared failure classification and explicit context-overflow recognition**

Recognize normalized provider receipts plus conservative message aliases for context length, request too large/413, output limit, transport errors, and fatal configuration. Classification must inspect nested primary/fallback exceptions and must never classify a network error as a provider ceiling observation.

- [ ] **Step 5: Make output-limit recovery use dynamic expansion, not compact prompts**

Call `_stage(..., retry_polish_output_limit=True)` for ordinary polish. Replace the fixed non-targeted 8192 retry with `expanded_output_budget()` bounded by declared route ceiling and remaining context. If the retry remains output-limited, raise `output_limit` to the parent workflow and split semantically.

- [ ] **Step 6: Make input overflow the only compact trigger**

Build the full and authority-only systems before calling a known route. Use `classify_input_pressure()` when context metadata exists. For unknown windows, call full first; on explicit context overflow retry once with the compact authority request. If the authority request still cannot fit or explicitly overflows, split. Remove the output-error compact circuit and replace it with a current-run input-overflow circuit keyed by route identity.

- [ ] **Step 7: Implement transport retry and fallback without split**

For `transport_interrupted`, retry the same route once with the identical authority packet and output budget. Then use the configured fallback once. Only a capacity/input failure on those attempts may split; exhausted network routes preserve the parent source and continue independent segments.

- [ ] **Step 8: Route local validation by disposition**

Pass `policy`, rolling accepted history metrics, and narrative context into `assess_polish_candidate()`. `pass` and `pass_with_style_allowance` checkpoint normally. `targeted_repair` sends only evidence spans plus the full applicable authority packet; one primary and one configured fallback attempt are allowed. `reject` discards the candidate immediately and preserves the parent source.

- [ ] **Step 9: Validate split children and merged parent before checkpoint authority**

Keep child files under the existing recovery suffix as non-authoritative diagnostics. After both return, run `assess_polish_candidate(parent_source, merged)`, locked-fact validation, passage protection, duplicate detection, event/scene handoff checks, and authority-hash validation. Save the normal parent checkpoint only after every check passes; otherwise save one `preserved_source` parent checkpoint.

- [ ] **Step 10: Run focused workflow tests and commit**

Run: `pytest tests/test_context_policy.py tests/test_revision.py tests/test_workflows.py -q -k "polish or output_limit or context_overflow or transport or split"`

Expected: PASS.

Commit:

```bash
git add src/novel_flywheel/context_policy.py src/novel_flywheel/workflows.py tests/test_context_policy.py tests/test_workflows.py
git commit -m "fix: separate polish recovery failure paths"
```

### Task 6: Cross-story regression matrix, observability, and complete verification

**Files:**
- Modify: `tests/test_prose_policy.py`
- Modify: `tests/test_revision.py`
- Modify: `tests/test_workflows.py`
- Modify: `tests/test_console.py`
- Modify: `docs/maintenance.md`

**Interfaces:**
- User-visible events: `polish_style_allowance`, `polish_targeted_repair`, `polish_input_compact_retry`, `polish_output_limit_retry`, `polish_transport_retry`, `polish_configured_fallback`, `polish_segment_split`, `polish_split_parent_rejected`, and existing `polish_segment_preserved`
- Event metadata includes failure class, raw metrics, baseline, policy rule/source IDs, evidence spans, recovery action, segment/child progress, and authority hash

- [ ] **Step 1: Add cross-story table tests**

```python
@pytest.mark.parametrize("genre, prose_kind", [
    ("古言宅斗", "authorized_short_reveal"),
    ("现代情感", "dialogue_dense"),
    ("悬疑", "authorized_suspense_turn"),
    ("科幻", "long_exposition"),
    ("玄幻", "scene_transition"),
    ("梦境", "ambiguous_location"),
    ("虚拟世界", "knowledge_change"),
])
def test_genre_name_does_not_change_structural_style_decision(genre, prose_kind):
    first = assess_fixture(genre=genre, prose_kind=prose_kind)
    second = assess_fixture(genre="未指定", prose_kind=prose_kind)
    assert first["disposition"] == second["disposition"]
```

- [ ] **Step 2: Add event classification and UI-copy tests**

Assert that output-limit recovery never emits the compact message, input overflow emits the compact message with `failure_class=input_context_overflow`, network retry names transport recovery, and style authorization names the exact project rule. Keep internal route/token metadata out of the short user-facing sentence while retaining it in event metadata.

- [ ] **Step 3: Update maintenance documentation**

Document:

- sentence-parser compatibility boundary;
- hard/soft validation precedence;
- optional project prose policy and old-project fallback;
- 75% advisory and 80% authority-fit context strategy;
- unknown-provider behavior;
- output-limit expansion then semantic split;
- transport retry then configured fallback;
- parent-atomic split/checkpoint rules;
- rollback by reverting code without rewriting projects or formal manuscripts.

- [ ] **Step 4: Run focused regression suite**

Run:

```bash
pytest tests/test_prose_quality.py tests/test_local_editorial.py tests/test_prose_policy.py tests/test_revision.py tests/test_context_policy.py tests/test_workflows.py tests/test_console.py -q
```

Expected: PASS with no real provider calls.

- [ ] **Step 5: Run complete test suite**

Run: `pytest -q`

Expected: all tests pass; any existing explicitly skipped integration test remains skipped; no paid API call occurs.

- [ ] **Step 6: Verify repository scope and commit**

Run:

```bash
git diff --check
git status --short
```

Confirm that pre-existing `.codex-full-pytest*` files remain untracked and are not added.

Commit:

```bash
git add src/novel_flywheel/prose_quality.py src/novel_flywheel/local_editorial.py src/novel_flywheel/prose_policy.py src/novel_flywheel/revision.py src/novel_flywheel/context_policy.py src/novel_flywheel/workflows.py tests/test_prose_quality.py tests/test_local_editorial.py tests/test_prose_policy.py tests/test_revision.py tests/test_context_policy.py tests/test_workflows.py tests/test_console.py docs/maintenance.md
git commit -m "feat: harden project-aware polish recovery"
```

