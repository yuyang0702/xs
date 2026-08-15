# R1-PA0 — Planning Adaptation Receipt Route Exhaustion Root Cause Verification

## Scope and outcome

This investigation changed no production source and made no provider call. It sealed the C0B-SMOKE-1 evidence, replayed every persisted candidate through the current local boundaries, characterized the exact retry topology, and stopped before a fix.

**Gate: `R1_PA0_DEVELOPMENT_NO_GO`.** The failure is a compound boundary failure, not one proven capacity-only defect. The primary route repeatedly loses Contract Runtime's expanded-budget state; the terminal fallback responses fail strict-tool uniqueness before conversion. Because the two fallback raw tool-call shapes were not persisted, the terminal output cannot be replayed exactly and no single production repair is yet justified.

Machine-readable deliverables:

- `r1-pa0-planning-adaptation-failure-timeline-v1.json`
- `r1-pa0-segment-to-whole-receipt-closure-map-v1.json`
- `r1-pa0-output-replay-results-v1.json`

## Evidence seal

- Evidence-only commit: `4bd70ed880a00a836dc2ecb843312ed4923917de`
- Parent execution HEAD: `3be39a6d61da31b864b13c99cb687adacd8047fd`
- Evidence canonical SHA-256: `73b4da607fd400d90fa81d6460da886297ccdd48760c4b1c12f301c015c49be3`
- Signed approval SHA-256: `1ec4be7f8d4a8beb64da47c9b9af44ea9e705b75b8e5007353f553d74fb032f5`
- Validate-only receipt canonical SHA-256: `e9ea016b405b10dc85e6f230922ec22113188ec8ed59e72bf7d6b938c94f5e83`
- Evidence privacy scan: zero matches for credentials, secrets, endpoint/header keys, raw prompts and story-body fields.
- Evidence files were committed without semantic rewriting. The only added seal artifact is the per-file SHA-256 manifest.

The original provider output used for the successful Segment replay remains in the ignored isolated canary root. It was not copied into Git. Only its hash and non-content metrics appear here.

## Exact execution path

```text
WorkflowService._review_short_plan_adaptations
  -> _review_short_plan_adaptation_segment
     -> _stage(execution_spec=planning_adaptation_segment)
        -> execute_contract_runtime
           -> dispatch_explicit_model_route
              -> ModelGateway.complete_route
                 -> ModelGateway._complete_resolved
     -> initial primary max_tokens
     -> _review_short_plan_adaptation_capacity_split
        -> _review_short_plan_adaptation_segment(_capacity_split=False)
        -> deterministic packet merge
        -> planning_adaptation_receipt_issues(full segment)
  -> _review_short_plan_adaptation_whole
     -> _stage(execution_spec=planning_adaptation_whole)
        -> the same Contract Runtime and ModelGateway
     -> ProtocolReceiptRouteExhaustedError
```

Code anchors:

- `src/novel_flywheel/workflows.py:9539` owns the Segment-to-Whole sequence.
- `src/novel_flywheel/workflows.py:6293` owns Segment receipt acquisition.
- `src/novel_flywheel/workflows.py:8040` owns capacity packet review and deterministic Segment merge.
- `src/novel_flywheel/workflows.py:9265` owns Whole closure.
- `src/novel_flywheel/workflows.py:26076` is the shared stage entry.
- `src/novel_flywheel/contract_runtime.py:803` is the shared Contract Runtime.
- `src/novel_flywheel/models.py:429` adapts the selected provider response.
- `src/novel_flywheel/models.py:554-560` requires exactly one expected strict-tool artifact.

## Finding 1 — Primary retries discard the existing output-expansion state

### Evidence

All six Review primary calls ended at exactly 1276 output tokens with `finish_reason=max_tokens` and zero visible characters. The budget comes from `bounded_protocol_output_budget(expected_output_characters=1200)`, not model configuration or the canary cap. Both review models had `max_output_tokens=NULL`; the public provider ceiling remains unknown.

`execute_contract_runtime` initializes `attempt_output_tokens` once and expands it after an output-limited conversion (`contract_runtime.py:848,951`). But the receipt loop calls `_stage` once per outer route attempt with `primary_only=True` or `prefer_configured_fallback=True`. `_stage` compiles that into a single-element `requested_routes` tuple and passes it to Contract Runtime (`workflows.py:26651,26752`). Therefore the Runtime invocation ends before it can make the expanded attempt, and the next outer invocation starts again at 1276.

The offline differential test proves the mechanism:

- current outer isolation: `[1276, 1276, 1276]`, all truncated;
- one retained Contract Runtime with two primary attempts: `[1276, 2552]`, controlled complete Whole receipt accepted.

### Execution Path

`_review_short_plan_adaptation_whole` -> outer `ProtocolReceiptAttempt` -> `_stage(primary_only=True)` -> `execute_contract_runtime(attempt_routes=("primary",))` -> output-truncated -> Runtime raises -> next outer iteration creates a new Runtime.

### Why It Matters

The system issues repeated capacity-equivalent primary attempts while an already-implemented local recovery mechanism is unable to retain its state. This explains the repeated max-token family at Segment and Whole boundaries without requiring a global retry or prompt theory.

### Confidence

High that expansion state is discarded. Medium that retaining it would recover this provider in production; no real larger-budget counterfactual exists.

### Falsification

Instrument a future separately approved canary so a same-route Planning Adaptation attempt records budgets across one Contract Runtime. This finding is false if the actual second attempt already exceeds 1276 or if the outer attempts share the expanded state.

### Fix Recommendation

Candidate only: make the Planning Adaptation receipt coordinator let one boundary-local Contract Runtime own its same-route attempts and budget state. Do not change global Runtime defaults or global retry counts. This is not approved for implementation by this report.

## Finding 2 — The terminal fallback failure occurs before local conversion

### Evidence

Whole fallback ordinals 10 and 11 have the same failure digest, `0ecd653c...`. Recomputing `failure_evidence_sha256` for `RuntimeError("strict structured tool route returned no unique artifact")` at `protocol_route.normal_invalid_output` reproduces that digest exactly.

In `ModelGateway._complete_resolved`, strict-tool mode raises when the response does not contain exactly one tool call and exactly one call with the expected contract name. That happens before the response is converted to text, before a model-output observation is saved, and before `GeneratedArtifactGateway` can run exact JSON, local syntax repair, schema adaptation, or domain validation.

The same strict-tool route produced one valid Segment receipt at ordinal 6, so the route is not universally incapable of structured output.

### Execution Path

`_review_short_plan_adaptation_whole` -> `_stage` -> Contract Runtime -> `ModelGateway._complete_resolved` -> strict-tool uniqueness check -> `RuntimeError` -> `_execute_protocol_receipt_attempt` classifies `normal_invalid_output` -> two fallback attempts -> route exhausted.

### Why It Matters

Calling this a generic “bad JSON” or claiming local repair failed would be false. No candidate reached local repair. It also means a parser-only fix cannot affect this incident.

### Confidence

High for the failing boundary and error text. Low for the exact provider shape: zero calls, multiple calls, a wrong-name call, and expected-plus-extra calls all produce the same error.

### Falsification

Capture privacy-safe strict-tool shape metadata (tool-call count and expected-name match count, with names hashed) on a future approved run. This finding is false if a unique expected artifact existed and was discarded later.

### Fix Recommendation

First add boundary-local, hash-only shape observation. Do not alter tool matching until the exact shape is known. Preserve prompt and story text exclusions.

## Finding 3 — Segment success was real, merged, persisted and reused

### Evidence

The hash-bound Segment fallback output (`8b00d006...`, 3065 bytes, 2343 visible characters, 1270 output tokens) replays under current code as one `exact_json` candidate. Normalization and `planning_adaptation_receipt_issues` produce zero issues for both expected events. Segment order and formal direction are true.

The capacity splitter validates every event exactly once, restores the parent Segment authority hash, validates the merged receipt against the full ordered event list, emits `planning_adaptation_capacity_split_completed`, and writes the packet checkpoint. Whole authority `de547721...` is computed from the validated Segment receipts, which are also included in the Whole context.

### Execution Path

Segment fallback -> current converter -> Segment domain validator -> packet checkpoint -> deterministic Segment merge -> full Segment revalidation -> Whole authority/context assembly.

### Why It Matters

H3 (“the successful Segment was discarded”) is false. Replacing the merge or restoring the same checkpoint cannot address the terminal failure.

### Confidence

High.

### Falsification

Recompute Whole authority after removing or changing the persisted Segment receipt. The finding is false if the authority or Whole context remains unchanged.

### Fix Recommendation

No merge fix is recommended. Add an oracle that the accepted Segment hash remains the last legal checkpoint after any Whole failure.

## Finding 4 — Whole is a different semantic closure, not the same object regenerated

### Evidence

Segment and Whole use registry version 1, the same 600-character calibration, the same converter family, and the same recovery ladder. Their wire schemas and domain validators intentionally differ. Segment owns per-event invariant reviews; Whole asks new questions about combined causal order, adjacent handoffs, knowledge and relationship progression, viewpoint/timeline, promises/ending, and formal direction.

A compact controlled valid Whole receipt for the observed one-segment/two-event authority is 623 characters and approximately 156 estimated tokens. It fits comfortably inside 1276. Therefore the Whole wire object is not intrinsically too large.

Feeding a valid Segment-shaped object to the Whole validator leaves Whole fields absent. A reducer could mechanically copy identifiers and set booleans, but the booleans would be new unproved semantic judgments. Even in this single-segment case there are two events whose combined state progression is not logically entailed by each event's local verdict.

### Execution Path

Validated Segment receipts -> `planning_adaptation_whole_authority_sha256` -> `_planning_adaptation_whole_context` -> `planning_adaptation_whole` contract -> Whole domain validator.

### Why It Matters

H8 is not proven. Cancelling Whole or asserting all Whole booleans from local booleans would change business authority, which R1-PA0 forbids.

### Confidence

High that the current contracts differ intentionally; Medium that every Whole invariant is indispensable for a one-segment story. That narrower product question needs a semantic specification, not this incident replay.

### Falsification

Provide a formal reducer proof showing that each Whole field is derivable from existing Segment fields for all allowed inputs, including cross-event contradictions. Schema conformance alone is not a proof.

### Fix Recommendation

Do not remove Whole in the incident fix. If redundancy is reconsidered later, treat it as a separately approved semantic change with equivalence tests.

## Exact replay closure

| Output | Current replay result | Exactness |
|---|---|---|
| Primary max-token output | Empty SHA `e3b0...`; converter classifies `output_truncated`; no semantic normalizer/schema/domain | Exact for persisted visible output and receipt |
| Segment fallback | `exact_json`, one candidate, zero domain issues, deterministic merge eligible | Exact, hash-bound private evidence |
| Whole fallback #1 | Exact error digest binds to strict-tool no-unique-artifact | Raw shape unavailable |
| Whole fallback #2 | Same exact error digest and boundary | Raw shape unavailable |

The request to replay each Whole fallback's raw shape cannot be completed honestly: neither response was persisted, and both failed before output observation. This is an explicit evidence gap, not a synthesized result.

## Hypothesis table

| Hypothesis | Supporting evidence | Contradicting evidence | Confidence / verdict | Falsification experiment |
|---|---|---|---|---|
| H1 Primary output budget insufficient | Six primary calls hit exactly 1276; Runtime expansion is reset; controlled retained attempt succeeds at 2552 | Valid Whole wire object is ~156 estimated tokens; no real larger-budget counterfactual | Medium contributor; not sole root | Same provider/input with one approved retained expanded attempt |
| H2 Whole object exceeds budget | Whole primary reaches max tokens | Minimal valid Whole object is 623 chars; successful Segment output is larger | High-confidence rejected | Produce a validator-required lower bound above 1276 tokens |
| H3 Segment result not merged/reused | None | Exact merge, checkpoint, Whole authority and context binding observed | High-confidence rejected | Change Segment hash and show Whole authority/context unchanged |
| H4 Contract drift/inconsistency | Schemas and semantic questions differ | Same registered version, wrapper family, calibration and recovery ladder; differences match domain roles | High-confidence rejected as accidental drift | Show an incompatible version/wrapper/evidence requirement not represented by registry |
| H5 Whole bypasses local-first Runtime | Strict-tool error never reaches converter | Whole enters the same `_stage` and Contract Runtime; the gateway raises earlier | High-confidence rejected as sibling bypass; confirmed pre-converter gap | Trace a Whole candidate around Contract Runtime or show converter received the failed response |
| H6 fallback model does not follow Whole contract | Both Whole fallbacks lack a unique expected tool artifact | Same route succeeds for Segment; relay/model attribution and raw shapes unknown | Medium for observed behavior, Low for model-only attribution | Capture tool-call shape and replay it through the adapter |
| H7 classification/schedule causes premature exhaustion | One-route outer isolation resets output expansion; fallback is classified generic unknown | Primary truncation class itself is correct; fallback still receives both allowed attempts | High for retry-state loss; Low that classification alone is root | Retain expansion with unchanged task and compare boundary completion |
| H8 Whole is removable | All observed Segment invariants are valid | Whole asks emergent combined judgments not derivable without new authority | Medium-to-high rejected for incident fix | Formal total reducer proof plus equivalence corpus |

## First divergent node and root-cause conclusion

Two notions must not be conflated:

- First wrong candidate: ordinal 2, Segment primary returns zero visible candidate at max tokens. It is recovered by capacity split and fallback.
- First unrecovered divergent node: ordinal 10, Whole strict-tool result fails the unique expected artifact condition in `ModelGateway._complete_resolved`.

The terminal causal family is compound:

1. Primary retries at this boundary repeatedly restart at the same bounded budget, so the existing expansion rung cannot execute across outer attempts.
2. The configured fallback then returns a non-unique strict-tool shape twice, before local repair can inspect it.

The first unrecovered node is unique, but its exact input shape is not. Consequently the evidence does not yet identify one repair that is both necessary and sufficient.

## Minimal repair candidates (not implemented)

1. **Planning Adaptation receipt-local retry ownership:** retain Contract Runtime budget state across its existing same-route attempts. Keep total attempts and route order unchanged.
2. **Strict-tool shape instrumentation:** before raising, record only call count, expected-name match count, hashed names, finish reason and usage if available. Never record arguments, prompt or prose.
3. **Stage-specific output preflight:** only if a controlled provider counterfactual proves the primary needs more than the current initial reserve. Do not globally raise limits.
4. **Adapter correction:** only after shape evidence distinguishes wrong name, multiple calls, or mixed calls. No speculative permissive matching.

Allowed future source scope: Planning Adaptation receipt orchestration, its boundary-local instrumentation, and its tests. Forbidden: global Prompt, global Runtime/retry/fallback, provider selection, model selection, Draft or later stages, StoryState, Canon, Long, Maintenance, canary/approval contracts, and validation weakening.

## Regression test plan

| # | Oracle | R1-PA0 status |
|---:|---|---|
| 1 | Primary `max_tokens` + empty visible candidate => output truncation | Implemented |
| 2 | Closed syntax defect can local-repair; empty/unclosed truncation cannot | Existing gateway coverage + R1 characterization |
| 3 | Segment fallback exact candidate passes converter and domain | Exact private replay; hash-bound evidence |
| 4 | Segment packet merge covers every event once and revalidates parent authority | Planned workflow fixture |
| 5 | Whole invalid JSON stays protocol-invalid | Planned |
| 6 | Whole wrong wrapper cannot become an authorized object | Planned |
| 7 | Whole missing required field fails wire/domain closure | Characterized; expand to field matrix |
| 8 | Whole truncation remains output-truncation | Implemented |
| 9 | Valid Whole output re-enters current converter/schema/domain path | Implemented controlled fixture |
| 10 | Three primary + two fallback failures preserve full causal chain | Evidence-ledger characterization; planned workflow test |
| 11 | Successful Segment hash remains bound after Whole failure | Planned checkpoint test |
| 12 | Deterministic Segment merge cannot silently assert Whole judgments | Implemented shape/domain characterization; future expected-failure acceptance |
| 13 | Last legal checkpoint is the validated Segment receipt | Planned isolated DB test |
| 14 | Replay creates no production incident | Planned isolated DB parity test |
| 15 | Replay/provider call counter remains zero | Report assertion + future test harness counter |
| 16 | Prompt hashes, route order and retry counts unchanged by any narrow fix | Future parity oracle |
| 17 | Full deterministic Short workflow crosses the receipt boundary | Future acceptance oracle; must prove workflow-level, not parser-only, success |

R1-PA0 added seven test-only characterization tests covering evidence cardinality, truncation classification, retry-state reset, Segment-versus-Whole closure, valid Whole closure, contract differential, and exact fallback error binding.

## Verification results

- New R1-PA0 characterization file: **7 passed**.
- Contract Runtime + Generated Artifact + Planning focused suite: **136 passed**.
- Planning Adaptation workflow selection: **25 passed, 52 deselected**.
- Full suite: **2577 passed, 2 skipped, 5 expected-failed, 1 failed** in 22m26s.
- The sole full-suite failure is `test_live_db_and_formal_artifact_baseline_remains_r0_identical`: it expects the historical R0 DB hash `5deb7b...`, while the already-existing current live DB hash is `0fccb8...`. The DB timestamp is 2026-08-14, before R1-PA0 began; R1-PA0 changed only docs/tests and did not write `data/app.db`. Re-running that test alone produces the same mismatch. It is therefore recorded as a pre-existing stale R0 baseline oracle, not repaired in this phase.
- Strict project change gate: passed at declared L3; automatic source-risk level L1; zero changed production/source paths and zero blockers.
- `src/novel_flywheel` diff: empty.
- `git diff --check`: clean.

## Performance and token implications

- Investigation provider/network calls: 0.
- Production code changes: 0.
- Initial receipt budget origin: Runtime formula, 1276 tokens for 1200 expected characters.
- Model-config ceiling: unknown (`NULL` for both Review routes).
- Canary per-call cap: not binding.
- A retained expansion candidate would change the second same-route reservation from 1276 to 2552 in the controlled experiment, without adding attempts. Production token/cost impact remains unverified until a separately approved provider run.
- Removing Whole could save calls but would alter semantic authority and is not an incident-safe optimization.

## Final gate

`R1_PA0_DEVELOPMENT_NO_GO`

Reasons:

1. Primary retry-state loss is proven, but production recovery at a larger retained budget is not.
2. Whole fallback failures are bound to one strict-tool error, but their raw shapes are unverifiable.
3. Two causal contributors remain; a single necessary-and-sufficient fix is not proven.
4. The exact Whole fallback replay requirement and Root Cause Gate item 1 are therefore not closed.

Next evidence step: add privacy-safe, Planning-Adaptation-local strict-tool shape observation and obtain a separately authorized controlled exposure that preserves expanded-budget state. Do not implement a business repair or run another Smoke from this task.
