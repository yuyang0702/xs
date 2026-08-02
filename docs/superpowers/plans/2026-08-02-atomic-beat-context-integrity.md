# Atomic Beat and Context Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent cross-segment event conflicts and instruction dilution by validating an atomic-beat execution manifest before prose generation and by using one lossless, stage-aware context assembly path throughout drafting, polish, review, and repair.

**Architecture:** Add a focused execution-manifest module for atomic beats and segment state ownership, then extend the existing run-scoped `short-execution-index.json` instead of creating a new authority store. Add a lossless mandatory-rule registry and stage context packet around the existing prompt compactors. Workflows generate, verify, repair, and checkpoint these contracts before drafting; semantic failures rewrite only the current invalid scope.

**Tech Stack:** Python 3.12, FastAPI workflow runtime, JSON run artifacts, vanilla JavaScript run events, pytest with fake gateways.

## Global Constraints

- Never modify the confirmed formal outline, StoryState, locked facts, confirmed ending, project files, or formal manuscript while repairing run-scoped planning.
- Planning repair may change only atomic beat decomposition, segment ownership, entry state, and exit state, and is bounded to two attempts.
- Every atomic beat has one owner segment; every new exit assertion is produced by a beat owned by that segment.
- Hard narrative rules are deduplicated but never truncated or omitted; advisory content may be filtered by stage and scope.
- Token pressure may change context topology, never story authority or output quality targets.
- Semantic prose repair rewrites the complete current scope and revalidates it; it never appends a sentence to manufacture compliance.
- A failed or stale artifact cannot replace a valid execution index, segment checkpoint, draft, quality checkpoint, candidate, or formal manuscript.
- Automated tests must not call paid model APIs or mutate existing user projects.

---

## File Structure

- Create `src/novel_flywheel/execution_manifest.py`: versioned atomic beats, segment contracts, structural validation, hashes, and repair diagnostics.
- Create `src/novel_flywheel/context_packet.py`: mandatory rule registry, stage-aware lossless prompt layers, rule coverage validation, and context metrics.
- Modify `src/novel_flywheel/draft_split.py`: bind draft tasks and semantic receipts to atomic beat IDs, viewpoint, and execution-manifest hash.
- Modify `src/novel_flywheel/workflows.py`: generate and repair execution manifests, invalidate legacy indexes/checkpoints, assemble context packets, retry semantic failures, and reuse only validated upstream work.
- Modify `src/novel_flywheel/skill_prompts.py`: expose exact rule extraction helpers without letting existing compactors silently drop mandatory rules.
- Modify `src/novel_flywheel/prose_quality.py`: add high-confidence viewpoint-drift findings used before semantic review.
- Modify `src/novel_flywheel/static/app.js`: render complete planning/context/semantic failure reasons and automatic recovery progress.
- Modify `AGENTS.md` and `docs/maintenance.md`: make atomic ownership and mandatory-rule coverage repository-wide workflow invariants.
- Create `tests/test_execution_manifest.py` and `tests/test_context_packet.py`; modify `tests/test_draft_split.py`, `tests/test_prose_quality.py`, `tests/test_workflows.py`, and `tests/test_console.py`.

---

### Task 1: Atomic Beat Execution Manifest

**Files:**
- Create: `src/novel_flywheel/execution_manifest.py`
- Create: `tests/test_execution_manifest.py`

**Interfaces:**
- Produces `AtomicBeat`, `SegmentBeatContract`, `ShortExecutionManifest` frozen dataclasses.
- Produces `parse_execution_manifest(value: object) -> ShortExecutionManifest`.
- Produces `execution_manifest_issues(manifest, *, expected_event_ids, segment_count, authority_hashes) -> list[dict]`.
- Produces `execution_manifest_sha256(manifest) -> str` and `legacy_execution_index_requires_rebuild(index: object) -> bool`.

- [ ] **Step 1: Write failing production-reproduction tests**

Create a manifest fixture where `EV-8E4BBA17/01` (“沈老夫人派人外出核实身份”) is owned by segment 1 and `EV-8E4BBA17/02` (“花穗发现二十两提前支取”) is owned by segment 2. Assert zero issues. Create the production-broken variant where segment 1 exit is produced by `/01` but `/01` is owned by segment 2; assert `exit_producer_not_owned` with segment, beat, actor/action, and source evidence.

- [ ] **Step 2: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_execution_manifest.py -q`

Expected: FAIL because `novel_flywheel.execution_manifest` does not exist.

- [ ] **Step 3: Implement versioned dataclasses and parser**

Require version 2, normalized uppercase source event IDs, `EV-XXXXXXXX/NN` beat IDs, positive global order, one owner, non-empty action/evidence, ordered segment numbers, explicit entry/exit assertions, and SHA-256 authority hashes. Reject unknown fields only when they create ambiguity; preserve documented presentation variants through the shared JSON-object parser at the workflow boundary.

- [ ] **Step 4: Implement exact structural validation**

Return all issues in one pass: missing source event, duplicate beat, non-contiguous global order, missing/duplicate owner, segment reversal, exit producer owned elsewhere, next-entry mismatch, stale authority hash, and legacy version. Do not stop at the first issue.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_execution_manifest.py -q`

Expected: PASS.

---

### Task 2: Lossless Mandatory-Rule and Context Packet Assembly

**Files:**
- Create: `src/novel_flywheel/context_packet.py`
- Modify: `src/novel_flywheel/skill_prompts.py`
- Create: `tests/test_context_packet.py`
- Modify: `tests/test_skill_prompts.py`

**Interfaces:**
- Produces `MandatoryRule`, `ContextLayer`, and `StageContextPacket`.
- Produces `extract_mandatory_rules(constraints, skill_prompt, *, stage, explicit_invariants) -> tuple[MandatoryRule, ...]`.
- Produces `build_stage_context_packet(...) -> StageContextPacket` and `validate_rule_coverage(packet) -> list[dict]`.
- Produces packet rendering with one current contract, one hard-rule registry, relevant source excerpts, global skeleton, and advisory material last.

- [ ] **Step 1: Write failing rule-preservation tests**

Use 41,000 characters of repeated constraints and four overlapping Skill prompts. Include `视角：第一人称`, a confirmed ending, knowledge boundary, current beat contract, and repeated generic examples. Assert every mandatory value occurs once, all mandatory rule IDs validate, examples are absent, and advisory removal never changes the packet authority hash.

- [ ] **Step 2: Write failing cross-stage tests**

Parametrize `draft`, `polish`, `review`, `revision_plan`, and `final_review`. Assert viewpoint, locked facts, ending, current ownership, previous exit, and prohibited future beats survive every applicable packet. Assert a packet missing one required rule fails before provider execution.

- [ ] **Step 3: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_context_packet.py tests/test_skill_prompts.py -q`

Expected: FAIL because the lossless registry and packet API do not exist.

- [ ] **Step 4: Implement exact rule registration and deduplication**

Derive stable IDs from normalized rule text plus source kind. Preserve exact original text. Classify explicit StoryState/outline invariants and contract fields as mandatory without relying only on words such as “must”. Deduplicate identical rules by normalized fingerprint and retain all source hashes.

- [ ] **Step 5: Implement stage packet rendering and metrics**

Render mandatory layers before advisory content. Use existing compactors only on advisory material. Record characters and estimated tokens per layer, removed duplicate count, filtered advisory count, and output reserve. Unknown provider windows do not trigger guessed truncation; known physical pressure triggers topology change at the workflow layer.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_context_packet.py tests/test_skill_prompts.py -q`

Expected: PASS.

---

### Task 3: Generate, Verify, and Automatically Repair Run-Scoped Planning

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes Task 1 manifest API and the existing planning/review routes.
- Produces `_build_short_execution_manifest(...)`, `_verify_short_execution_manifest(...)`, and `_repair_short_execution_manifest(...)`.
- Writes version 2 `outputs/short-execution-index.json` only after local and independent semantic validation.

- [ ] **Step 1: Write failing planning preflight tests**

Use fake planning outputs for the production conflict, missing beats, duplicate ownership, changed actor, stale outline hash, and a valid split. Assert the draft gateway receives zero calls until the valid version 2 index exists.

- [ ] **Step 2: Write failing bounded-repair tests**

Assert the first invalid manifest triggers repair attempt 1 with all issue codes, the second invalid candidate triggers attempt 2, and a third invalid candidate stops in planning. Assert repairs cannot change the formal outline hash or confirmed outline content. Assert a valid causal chain is reused.

- [ ] **Step 3: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_workflows.py -k "execution_manifest or planning_ownership" -q`

Expected: FAIL because drafting currently reads Markdown event groups without a validated atomic manifest.

- [ ] **Step 4: Add manifest generation and semantic verification prompts**

Require JSON-only manifest output bound to formal outline, planning, causal-chain, and authority hashes. Parse through `novel_flywheel.model_output.parse_json_object`. The independent review returns exact source excerpts per beat and adjacent-boundary verdicts. Runtime proves every excerpt belongs to the supplied authority before promotion.

- [ ] **Step 5: Add automatic repair and legacy invalidation**

Repair only run-scoped beats, ownership, and boundaries. Version 1 indexes and version 2 indexes missing semantic receipts revalidate or rebuild. Emit distinct `planning_manifest_conflict`, `planning_manifest_repair`, `planning_manifest_ready`, and `planning_manifest_failed` events with all issue details.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_execution_manifest.py tests/test_workflows.py -k "execution_manifest or planning_ownership" -q`

Expected: PASS.

---

### Task 4: Bind Draft Contracts, Checkpoints, and Semantic Retry to Atomic Beats

**Files:**
- Modify: `src/novel_flywheel/draft_split.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prose_quality.py`
- Modify: `tests/test_draft_split.py`
- Modify: `tests/test_prose_quality.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Extends `DraftTaskContract` with `execution_manifest_sha256`, `beat_ids`, `viewpoint`, and prohibited future beat IDs.
- Extends semantic receipt validation with beat evidence, viewpoint, actor/action identity, location/time/knowledge state, and all failure reasons.
- Produces checkpoint version 3.

- [ ] **Step 1: Write failing contract and receipt tests**

Assert a contract cannot cite an exit producer outside its owned beats, a checkpoint with an old manifest hash is stale, first-person prose narrated consistently as `她/花穗` fails viewpoint validation, and one receipt can report both missing exit and invalid causal order instead of losing the second error.

- [ ] **Step 2: Write failing automatic semantic-rewrite tests**

Fake the exact production sequence: first prose changes the investigator from 沈老夫人 to 裴砚行 and moves 花穗 from banquet to gate and back; review reports actor, exit, viewpoint, and order failures. Assert no segment 2 call occurs, the complete segment 1 is regenerated once with the structured failure packet, and only the revalidated replacement is checkpointed.

- [ ] **Step 3: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_draft_split.py tests/test_prose_quality.py tests/test_workflows.py -k "atomic_beat or semantic_rewrite or viewpoint" -q`

Expected: FAIL because semantic receipt failure currently raises immediately and checkpoints use coarse event IDs.

- [ ] **Step 4: Implement atomic draft contracts and complete issue collection**

Render the current beat actions and state assertions as the only executable scope. Validate every beat and state with exact prose evidence. Collect all receipt failures before raising so logs expose every independent issue.

- [ ] **Step 5: Implement root-cause recovery**

Classify contract/manifest failures separately from prose noncompliance. Contract failures return to Task 3 repair without spending prose retries. Prose failures perform at most two complete same-scope rewrites using the original authority plus structured evidence; never append or patch. Preserve prior accepted segments.

- [ ] **Step 6: Implement checkpoint version 3**

Store manifest hash, beat IDs, semantic receipt, previous exit hash, and prose hash. Legacy checkpoints revalidate only when a compatible version 2 manifest can prove identical authority; otherwise regenerate from the first stale segment.

- [ ] **Step 7: Run tests and verify GREEN**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_draft_split.py tests/test_prose_quality.py tests/test_workflows.py -k "atomic_beat or semantic_rewrite or viewpoint" -q`

Expected: PASS.

---

### Task 5: Apply the Same Context and Narrative Invariants Downstream

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/context_policy.py`
- Modify: `tests/test_context_policy.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Consumes Task 2 context packets and Task 4 semantic receipts.
- Applies rule coverage and atomic-beat invariants to draft, polish, review, revision plan, final review, and targeted repair calls.

- [ ] **Step 1: Write failing downstream-preservation tests**

For each prose-affecting stage, assert the provider receives mandatory viewpoint, ending, knowledge, current beat IDs, and boundary state exactly once. Make a polish response change viewpoint or consume a future beat; assert the original segment remains and downstream review does not promote the invalid result.

- [ ] **Step 2: Write failing token-pressure topology tests**

Use known and unknown context windows. Assert known physical pressure produces complete hash-bound windows or semantic task splits, unknown windows retain authority without guessing a truncation ceiling, and mandatory-rule overflow stops before provider execution rather than slicing rules.

- [ ] **Step 3: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_context_policy.py tests/test_workflows.py -k "context_packet or downstream_invariant or mandatory_rule" -q`

Expected: FAIL because draft/review currently use full unstructured constraints and downstream stages do not share mandatory rule coverage.

- [ ] **Step 4: Route prose-affecting stages through context packets**

Integrate packet rendering at the central `_stage` boundary while allowing schema-repair and maintenance calls to keep their narrow existing behavior. Log layer metrics and validate mandatory IDs before calling the gateway.

- [ ] **Step 5: Revalidate downstream prose mutations**

Compare polish/repair results with the accepted beat and boundary manifest. On semantic drift, retry the whole current window within its allowed scope or preserve the accepted source. Whole-manuscript review uses segment receipts and the global beat skeleton in every window and adjudication layer.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_context_packet.py tests/test_context_policy.py tests/test_workflows.py -k "context_packet or downstream_invariant or mandatory_rule" -q`

Expected: PASS.

---

### Task 6: User-Visible Diagnostics, Documentation, and Complete Verification

**Files:**
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `tests/test_console.py`
- Modify: `AGENTS.md`
- Modify: `docs/maintenance.md`
- Modify: `docs/superpowers/specs/2026-08-02-atomic-beat-context-integrity-design.md`

**Interfaces:**
- Produces complete user-visible issue lists and repository-wide invariants.

- [ ] **Step 1: Write failing UI/log tests**

Assert the UI can show all planning or semantic issue messages, current automatic repair attempt, context layer metrics, preserved checkpoint count, and restart segment. It must not collapse multiple failures to the first field.

- [ ] **Step 2: Run tests and verify RED**

Run: `C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_console.py -k "manifest or semantic or context" -q`

Expected: FAIL because the current UI has only the generic first semantic error.

- [ ] **Step 3: Implement diagnostics and documentation**

Render the structured metadata already emitted by workflow events. Add repository and maintenance rules for atomic beat ownership, immutable formal authority, mandatory-rule coverage, bounded automatic planning repair, complete-scope semantic rewrite, and downstream invariant revalidation.

- [ ] **Step 4: Run focused regression suites**

Run:

`C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest tests/test_execution_manifest.py tests/test_context_packet.py tests/test_draft_split.py tests/test_skill_prompts.py tests/test_context_policy.py tests/test_prose_quality.py tests/test_console.py tests/test_workflows.py -q`

Expected: PASS without paid model calls.

- [ ] **Step 5: Run repository checks and complete suite**

Run `git diff --check`, then:

`C:\小说\novel-flywheel-console\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass; the existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 6: Commit, integrate, and publish**

Stage only the files listed in this plan. Commit the implementation, merge the feature branch into local `main`, verify the merged tree, and push `main` to `origin/main`. Do not stage, delete, or modify `.codex-full-pytest*` user log files.
