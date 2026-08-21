# R1-PTR12 — Hash-Only Raw Provider Shape + Guard Decision Observer Design

## Final gate

`R1_PTR12_RAW_SHAPE_GUARD_DECISION_OBSERVER_DESIGN_READY`

A behavior-neutral observation design is closed. A safe raw observation point exists in each supported Provider adapter immediately after `HttpProvider.post_stream` returns and before stream aggregation, response projection, or `ModelResponse` construction. The design then reuses the existing provider-neutral projection, PTR9 predicate owner, Contract Runtime recovery owner, Reliability Trace sink, and canonical `inner_attempt_id` rather than introducing a parallel trace identity.

`PRODUCTION_FIX=NOT_IMPLEMENTED`  
`OBSERVER_IMPLEMENTATION=NOT_IMPLEMENTED`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`NEW_FULL_SHORT_CANARY=NOT_EXECUTED`  
`NEXT_BUSINESS_ROOT_AFTER_OBSERVER=PLANNING_CALL1_SEMANTIC_FAILURE_AND_RECOVERY_CONVERGENCE`

## Baseline and evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `af73f0b520dac7392227cce9e40badcc5b8b63e1`
- Worktree at start: clean
- Worktree at end: only the 11 new `docs/superpowers/reports/r1-ptr12/**` design-evidence files are untracked; no pre-existing or unrelated change
- PTR11 manifest: 10/10 exact
- PTR11 gate: `R1_PTR11_PROVIDER_OUTPUT_EVIDENCE_SEALED`
- PTR11 conclusions retained: `ROOT_CAUSE_CLOSED=NO`, `RAW_PROVIDER_SHAPE=UNKNOWN`, `GUARD_MISS_CLASSIFICATION=OBSERVABILITY_GAP`, `SAME_FAILURE_SHAPE_AS_PTR4=UNKNOWN`
- Production source diff: 0
- `baml_src/**` diff: 0
- Live baseline: exact by branch, HEAD, parent manifest, and production/BAML bytes

The design does not reinterpret the consumed Canary. Boundary 12 remains known only as normalized zero-visible, `max_tokens`, and 8,798/8,798 output tokens. It does not infer a reasoning block from that evidence.

## Exact owners and call order

Raw point A is protocol-local because transport event shapes differ:

- `src/novel_flywheel/providers/anthropic.py::AnthropicAdapter.complete`: after `post_stream`, before `_aggregate_stream` or `content` projection.
- `src/novel_flywheel/providers/openai_chat.py::OpenAIChatAdapter.complete`: after `post_stream`, before `_aggregate_stream` or `choice/message` projection.
- `src/novel_flywheel/providers/openai_responses.py::OpenAIResponsesAdapter.complete`: after `post_stream`, before `_aggregate_stream`, `_output_text`, or `output` projection.

The common metadata builder belongs in `src/novel_flywheel/provider_output.py`. It accepts protocol-specific structural iterators and never accepts a prompt, response body for persistence, or content-bearing serialization target. `ModelGateway` opens a per-attempt execution-local capture slot; the adapter deposits one immutable metadata-only snapshot before normalization, and `ModelGateway` emits it under the canonical correlation after adapter return. On adapter failure it emits best-effort and re-raises the exact exception. The slot is reset in `finally`, and `ModelResponse` is not mutated.

Normalized point B remains `src/novel_flywheel/provider_output.py::provider_output_shape_from_response`, called by `src/novel_flywheel/models.py::ModelGateway._complete_resolved` after adapter return. It creates `ProviderOutputShapeV1`; the proposed hook then creates `RawToNormalizedShapeDeltaV1` before the Guard.

Decision point C is `ModelGateway._complete_resolved`, immediately around the existing `src/novel_flywheel/models.py::_reasoning_only_final_artifact_unavailable` call. Guard scope/applicability and negative-capability initiation are owned by that method. The persistence owner remains `src/novel_flywheel/db.py::Database.save_structured_route_outcome`.

Alternate-route selection, typed fail-close, and sticky output-limit classification are owned by `src/novel_flywheel/contract_runtime.py::execute_contract_runtime`. It emits the recovery-disposition phase under the same decision receipt. Parser/schema/domain processing and local `output_limit_seen` behavior remain unchanged.

The complete order is:

`ModelGateway capture scope → Provider response → raw point A capture → adapter normalization → A emission → normalized/delta point B → PTR9 predicate → decision point C → strict-tool/parser/schema/domain → existing recovery → sticky output-limit classification → terminal exception if any → capture-scope reset`.

## Raw-shape contract

`ProviderRawShapeObservationV1` records only controlled types, block counts and bounded type sequence, reasoning/text/tool/unknown counts, character counts, classified finish/status, token/cap counts, completeness, route/provider/model/contract/schema fingerprints, and a digest of that metadata. Unknown class/type values are represented by bounded hashes of the type token only.

It explicitly forbids prompt, manuscript, Canon/StoryState, final/reasoning text, tool arguments/results, Provider bodies/events, credentials, headers, query secrets, raw request IDs, exception messages, and hashes of any such content. Visible length is computed with `len()` on already-present strings or summed stream delta lengths; the strings are neither copied nor hashed for telemetry.

The sequence is bounded at 128 items and unknown hashes at 32. Over-bound inputs retain totals and a streaming metadata digest, mark the sequence omitted, and downgrade completeness to `partial`; they never allocate memory proportional to content bytes.

## Guard-decision contract

`PTR9GuardDecisionObserverV1` records the exact existing scope and predicate inputs:

- scope eligible and Guard reached;
- reasoning exists;
- finish is output-limit;
- raw and normalized visibility are zero;
- final text and tool call are absent;
- unknown blocks are absent;
- content is all reasoning;
- projection exact and transport complete;
- aggregate predicate, Guard result, and negative-capability write result.

It also records the existing alternate-route/fail-close disposition. Because that disposition is decided after `ModelGateway` raises the typed failure, the contract has two phases with one deterministic `decision_receipt_sha256`: `guard_evaluation` at `ModelGateway`, then `recovery_disposition` at Contract Runtime. Nullable inputs remain `null`; unavailable evidence is never silently converted to `false`.

`GUARD_MISS_REASON` is a closed enum with deterministic precedence. It includes `SCOPE_INELIGIBLE`, `GUARD_NOT_REACHED`, `SHAPE_UNAVAILABLE`, each exact false predicate, `REPRESENTATION_CHANGED`, `NEGATIVE_CAPABILITY_WRITE_NOT_REQUIRED`, and `UNKNOWN`. There is no free-text cause field.

The observer snapshots inputs but does not replace the current predicate. Equivalence tests require observed `predicate_all_true` to match the existing Guard result. The Guard itself may still fail closed; only observer failures are fail open.

## Representation delta

`RawToNormalizedShapeDeltaV1` mechanically compares block sequence/multiset, reasoning/text/tool counts, visible characters, finish reason, and transport completeness. It returns `REPRESENTATION_CHANGED=YES|NO|UNKNOWN` plus closed changed/unavailable dimension enums.

This distinguishes a concrete predicate miss from a raw-to-normalized mismatch. Missing raw or normalized shape yields `UNKNOWN`, never `NO` and never an inferred reasoning-only shape.

## Correlation

The canonical identity is the existing `ModelDiagnosticContextV1.inner_attempt_id`, already used as `ReliabilityTraceEnvelopeV1.correlation_id`. The design adds no second identity. Run/stage/boundary/contract/schema and route/provider/model fingerprints remain deterministic bindings.

During an instrumented Canary only, the existing `BoundaryRequest.ordinal` and budget reservation ordinal are attached as locators by an execution-local context variable set around `CanaryGateway._dispatch_open` and reset in `finally`. Outside Canary they are `null`. They do not participate as an alternative trace identity and are never derived from a Provider request ID or payload.

This joins external call number, raw shape, normalized shape, Guard decision, negative-capability result, recovery disposition, output-limit classification, and terminal exception to one attempt.

## Fail-open and performance boundary

`OBSERVER_FAILURE_BEHAVIOR=FAIL_OPEN`

Every capture, model validation, hash, and emission is contained by a non-mutating best-effort wrapper. The existing `emit_observation`/`BestEffortTraceSink` returns false on validation, lock, serialization, or I/O failure. On adapter normalization exceptions, a metadata-only snapshot may be attached for best-effort emission, after which the exact original exception is re-raised. No observer result feeds adapter return values, parser input, Guard predicates, capability decisions, retry/fallback, error classification, budgets, or timeouts.

- CPU: `O(blocks + stream events)`; no content-byte digest.
- Memory: bounded structural sequence/hash state plus counters; no telemetry content concatenation.
- I/O: at most one small A record, one B delta, one C1 decision, and when required one C2 recovery/classification record per provider attempt; existing best-effort JSONL only.
- External effects: no added network, model, or Provider dispatch; no token or timeout change.

## Coverage and compatibility

Coverage is based on adapter protocol and route context, not an incident, Provider, model, or boundary literal. It covers Planning primary, Planning repair, configured fallback, plain/structured response, adapter-supported tool mode, and current PTR9 structured scope. Observation outside Guard scope remains useful and records `SCOPE_INELIGIBLE`; behavior remains unchanged.

The historical PTR4 shape is exactly expressible: reasoning/thinking count 1, text/final count 0, tool count 0, visible characters 0, finish `max_tokens`, with exact raw/normalized equality. The PTR11 condition is also exactly expressible as raw unavailable plus normalized zero-visible, producing delta `UNKNOWN` and typed `SHAPE_UNAVAILABLE`. With a future exact observation, a field-wise comparator can return `SAME_FAILURE_SHAPE_AS_PTR4=YES` or `NO` mechanically.

## Narrow proposed implementation scope

The next separately authorized implementation should be limited to:

- `src/novel_flywheel/domain/models.py` — metadata-only observation models or the existing Provider shape model extension;
- `src/novel_flywheel/provider_output.py` — raw capture and raw/normalized delta helpers;
- `src/novel_flywheel/providers/anthropic.py`;
- `src/novel_flywheel/providers/openai_chat.py`;
- `src/novel_flywheel/providers/openai_responses.py`;
- `src/novel_flywheel/models.py` — point B/C hooks without predicate change;
- `src/novel_flywheel/contract_runtime.py` — recovery/classification observation only;
- `src/novel_flywheel/model_diagnostics.py` — reuse/transport of canonical correlation plus optional existing Canary locator;
- `src/novel_flywheel/generated_artifacts.py` and `src/novel_flywheel/reliability_trace.py` — typed diagnostic event registration and privacy requirements;
- `tools/canary/gate.py` — bind the existing external boundary ordinal as a locator only;
- `tests/test_provider_output_observer.py`, `tests/test_final_artifact_guard.py`, `tests/test_r1_ptr12_guard_decision_observability.py`, and `tests/canary/test_r1_ptr12_correlation.py`.

No `workflows.py`, Prompt, BAML, Model, Route configuration, retry/fallback configuration, token budget, validator, StoryState, Canon, or READY authority change is needed. Therefore `R1_PTR12_NO_GO_OBSERVER_REQUIRES_BEHAVIOR_CHANGE` does not apply.

## Test design

The offline design contains 32 cases. It includes every required historical/partial/tool/text/empty/unknown/mismatch/scope/decision/write/fail-open/privacy/route/side-effect/correlation case, plus protocol streaming, bounded-memory, alternate-route, fail-close, PTR11 unknown, output-limit binding, and adapter-exception cases. Observer-on/off behavior equivalence is required at adapter return, parser input, dispatch count, route choice, typed Guard error, and final Runtime error.

No tests were added or executed as production validation in this design-only turn. The parent PTR11 focused receipt remains sealed; PTR12 validates document structure, parent hashes, privacy, SHA manifest, and source/BAML scope only.

## Evidence validation

- Evidence files: 11, including the self-excluded SHA manifest.
- JSON parse: 10/10 exact.
- SHA manifest: 10/10 entries exact by byte count and SHA-256.
- Forward-risk schema: accepted by the repository council validator; status remains honestly `contained` because implementation is deferred.
- Privacy scan: exact; prohibited-content instance counts are all zero.
- Scope: only `docs/superpowers/reports/r1-ptr12/**`; no out-of-scope path.
- Production diff: 0.
- `baml_src/**` diff: 0.
- External action counters: credential 0, Provider client 0, network 0, model 0, paid 0.

## Business limitation and stop state

PTR12 closes the observer design, not the production observability gap and not Short success. It does not repair the first or first-unrecovered divergence, Call 1 `semantic_validation_failed`; it only makes a future Provider shape and Guard miss mechanically diagnosable. Observability work must not expand indefinitely.

After PTR13 implementation/validation closes this gap, the business root returns to:

`NEXT_BUSINESS_ROOT_AFTER_OBSERVER=PLANNING_CALL1_SEMANTIC_FAILURE_AND_RECOVERY_CONVERGENCE`

The next engineering step is `R1-PTR13 — Implement Raw Shape + Guard Decision Observer`, not a real probe or another Full Short Canary.
