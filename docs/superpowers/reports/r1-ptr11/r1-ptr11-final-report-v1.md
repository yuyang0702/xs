# R1-PTR11 — Planning Boundary 12 Guard-Miss Root Cause Investigation

## Final gate

`R1_PTR11_PROVIDER_OUTPUT_EVIDENCE_REQUIRED`

The sealed evidence does not uniquely distinguish an exact predicate mismatch from a raw-to-Runtime representation mismatch. Boundary 12 is proven to be `max_tokens`, transport-complete, `8,798/8,798`, and zero-visible after adapter normalization. Its raw content-block topology, normalized tool count, `ProviderOutputShapeV1`, and per-predicate guard decision were not persisted. The investigation therefore does not infer `REASONING_ONLY` from the terminal exception.

`MISSING_EVIDENCE=guard_input_shape_available,shape_sha256,content_block_count,content_block_type_sequence,reasoning_block_count,text_block_count,provider_visible_text_chars,tool_call_count,unknown_block_count,unknown_type_hashes,normalized_tool_call_count,adapter_projection_status,per_predicate_decision_vector,raw_shape_to_attempt_lineage`

`PRODUCTION_FIX=NOT_IMPLEMENTED`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`NEW_FULL_SHORT_CANARY=NOT_EXECUTED`

## Baseline and evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Parent HEAD: `373b566d99770f060a4b2e0f479dfd54bc1357d7`
- Current HEAD: `f3b31a57cdf9adc2f888c3582858d8f25b3230cb`
- Execution evidence commit: `f3b31a57cdf9adc2f888c3582858d8f25b3230cb`
- Worktree at start: clean
- Worktree at end: R1-PTR11 evidence-only report files uncommitted; no pre-existing or unrelated changes
- Execution manifest: 19/19 entries exact against working bytes and evidence-commit blobs
- Evidence package SHA-256: `0bf558fba6a6ff2eec512bd4711eb12422b8a16b5b91ac33b1e578a5ce028`
- Run count: 1; second run: no; resume: no
- Production diff: 0
- `baml_src/**` diff: 0
- Live parity: exact

The investigation read the sealed final report, SHA manifest, call ledger, PTR9 observation, preflight and authorization binding, stage progression, budget/cost, canonical package, isolated read-only model observations, run events, reliability trace, conversion audits, PTR4/PTR7 observations, and the sealed PTR9 implementation.

## Calls 1–12

All calls were Planning, contract `planning_semantic_v2`, request mode `plain`. The sequence comprises three separately constructed Contract Runtime instances, each with primary×2 followed by configured-fallback×2.

| Calls | Route sequence | Output/finish sequence | Conversion result | Runtime result |
|---|---|---|---|---|
| 1–4 | primary, primary, fallback, fallback | 5349/end_turn; 3309/end_turn; 7774/max_tokens; 11008/end_turn | semantic fail; semantic fail; output truncated; semantic fail | local sticky output-limit reclassification, then workflow capacity split |
| 5–8 | primary, primary, fallback, fallback | 6025/end_turn; 4908/end_turn; 7774/max_tokens; 8195/end_turn | semantic fail; semantic fail; output truncated; semantic fail | local sticky output-limit reclassification, then workflow capacity split |
| 9–12 | primary, primary, fallback, fallback | 1620/end_turn; 1833/end_turn; 4399/max_tokens; 8798/max_tokens | semantic fail; semantic fail; output truncated; output truncated | unrecovered `ContractOutputLimitExhaustedError` |

- First divergence: Call 1, `semantic_validation_failed`.
- First unrecovered divergence: Call 1. No later call produced or restored an accepted Planning artifact.
- First output-limit signal: Call 3.
- Final Runtime amplifier set: Call 11 set `output_limit_seen=true` in the last Runtime instance.
- Terminal amplifier: Call 12 combined another empty `max_tokens` conversion failure with the already-set local flag.
- Terminal boundary: Call 12.

The exact per-call caps, token counts, normalized visibility, state transitions, exceptions, and recovery disposition are in `r1-ptr11-call-1-12-reconstruction-v1.json`.

## Boundary 12 shape and exact predicate

Three layers are intentionally separated:

1. Provider raw response: `RAW_PROVIDER_SHAPE=UNKNOWN`. No raw block sequence or safe shape receipt was retained.
2. Adapter-normalized response: finish `max_tokens`, transport complete, output tokens 8,798, normalized text length 0. Normalized tool-call count is unknown.
3. Contract Runtime input: empty-byte SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`; conversion rejected with `output_truncated`, candidate count 0.

Predicate results:

| Exact condition | Boundary 12 |
|---|---|
| reasoning/thinking block exists | UNKNOWN |
| finish_reason=max_tokens | TRUE |
| visible chars zero before adapter | UNKNOWN |
| visible chars zero after adapter | TRUE |
| final text absent | TRUE post-adapter only; raw text-block presence UNKNOWN |
| tool call absent | UNKNOWN |
| unknown block count zero | UNKNOWN |
| content count equals reasoning count | UNKNOWN |
| adapter projection exact | UNKNOWN |
| transport complete | TRUE |

Consequently, at least one of shape availability or the exact shape predicates was false at Runtime, but the missing decision receipt prevents identifying which condition. `GUARD_BEHAVIOR=UNKNOWN`.

## Guard-miss classification and wiring

Primary classification: `OBSERVABILITY_GAP`.

- `GUARD_NOT_REACHED` is disproved for the normal response path. The post-guard model observation exists, and the control flow evaluates the guard before returning to Contract Runtime.
- `SCOPE_BINDING_MISS` is disproved. Boundary 12 carries a structured `planning_semantic_v2` response schema, which is the guard applicability condition.
- `finish_reason` mismatch is disproved; `max_tokens` normalizes to an accepted value.
- `PREDICATE_NOT_MATCHED` remains possible but unproved.
- `REPRESENTATION_MISMATCH` remains possible but unproved.

The exact owner is `src/novel_flywheel/models.py::ModelGateway._complete_resolved`; the predicate is `_reasoning_only_final_artifact_unavailable`; provider-neutral projection is `src/novel_flywheel/provider_output.py::provider_output_shape_from_response`. Both primary and fallback explicit routes traverse this owner. Strict-tool extraction, when applicable, occurs after the guard. Boundary 12 used plain mode, which does not bypass the guard.

The Anthropic adapter normally retains content in transient `ModelResponse.provider_state`, and `provider_output_shape_from_response` projects it after normalization. The projection returns `None` on unsupported family or shape-validation failure. Neither the transient content topology nor the projected shape/decision vector was persisted in the consumed run. The separate planning-repair diagnostic observer was flag- and target-gated; the real Short preflight kept PA diagnostic flags disabled.

## Sticky output-limit result

`OUTPUT_LIMIT_STICKY_STATE=YES_WITHIN_EACH_CONTRACT_RUNTIME_INSTANCE`

`CROSS_INSTANCE_STICKINESS=NO`

`TERMINAL_ERROR_PRIMARY=NO`

`execute_contract_runtime` initializes `output_limit_seen=false` for each of the three Runtime instances. Calls 3, 7, and 11 independently set it in their respective instances. Calls 4 and 8 then ended normally at the provider layer but failed semantic conversion; the local sticky flag reclassified each exhausted inner Runtime as `ContractOutputLimitExhaustedError`, after which the workflow performed its allowed capacity split. Call 12 was itself output-limited and empty, so the last instance terminated with the same reclassification. The terminal type is an amplifier over an unresolved Planning artifact chain, not proof of the PTR4 raw shape.

Secondary amplifier: `CONTRACT_RUNTIME_LOCAL_STICKY_OUTPUT_LIMIT_TERMINAL_RECLASSIFICATION`.

## PTR4/PTR7 comparison

`SAME_FAILURE_SHAPE_AS_PTR4=UNKNOWN`

The historical PTR4 observation and Boundary 12 match on hashed provider/model identity, configured-fallback route kind, Anthropic protocol, `max_tokens`, 8,798 output tokens, and post-adapter zero visibility. PTR4 additionally proves one `thinking` block, zero text blocks, zero tool blocks, zero unknown blocks, and exact adapter projection. Every one of those raw/topology dimensions is missing for Boundary 12. The failure families cannot be merged from terminal type or normalized emptiness alone.

## Design-only decision

Recommended narrow family: `E_ADD_HASH_ONLY_RAW_SHAPE_AND_GUARD_DECISION_OBSERVER`.

The observation owner should be `ModelGateway._complete_resolved`, bound to `provider_output_shape_from_response` and the Canary evidence collector. It should persist only shape availability, shape hash, block classes/counts, pre/post visible counts, normalized tool count, projection status, transport status, and the per-predicate boolean vector; it must retain no prompt, story, tool arguments, Provider content, request ID, credential, or reasoning text.

This is an observation design, not an authorized production change. It does not change primary routing, normal text/tool responses, retry/fallback, output budgets, capability-registry semantics, Prompt, Model, Route, validators, StoryState, Canon, or READY authority. If the missing transient Boundary 12 state cannot be recovered—which current sealed storage indicates—it requires separately authorized, production-shaped provider evidence after the observer is independently approved. A generic probe cannot retroactively prove Boundary 12.

## Validation

- Focused offline tests: `32 passed in 7.45s` (`tests/test_final_artifact_guard.py`, `tests/test_r1_ptr1_planning_repair_observability.py`).
- Static reconstruction: exact join of sealed ledger, read-only model observations, run events, reliability trace, and conversion audits.
- Strict L3 structural result: blocker count 0; one expected strict warning because the forward-risk status is `contained`. The strict command therefore returns nonzero and is not misreported as exact completion.
- Privacy: exact; prohibited-content counts all zero.
- SHA manifest: self-excluded manifest covers the other 10 R1-PTR11 outputs and is verified after generation.
- Production source diff: 0.
- BAML diff: 0.
- Investigation external actions: credential 0, provider client 0, network 0, model 0, paid 0.

## Stop state

`PRIMARY_ROOT_CAUSE_STATUS=UNRESOLVED`

`SECONDARY_AMPLIFIER=CONTRACT_RUNTIME_LOCAL_STICKY_OUTPUT_LIMIT_TERMINAL_RECLASSIFICATION`

`FRESH_PROVIDER_EVIDENCE_REQUIRED=YES`

`PRODUCTION_FIX_AUTHORIZED=NO`

No production fix, Provider call, Short rerun, resume, second run, token/retry expansion, or downstream stage execution was performed.
