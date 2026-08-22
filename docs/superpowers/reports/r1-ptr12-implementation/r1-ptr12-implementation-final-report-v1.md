# R1-PTR12 Observer Implementation — Gate Report

## Gate

`R1_PTR12_OBSERVER_IMPLEMENTATION_NARROW_FIX_REQUIRED`

The observer implementation is not accepted. An authorized independent review
shard found a hard implementation issue: malformed or high-cardinality raw
block topology is fully collected and processed before persistence truncation.
The remaining review shards were stopped without a sealed result. This report
does not claim implementation pass, split-review pass, or Phase B readiness.

## Baseline and implementation

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Start HEAD: `a264ee200c99c6c0a5d03a7aeb398773b4d3f3f5`
- Implementation commit: `ef2eb22bfad85be5e04855bbf4464318745737ae`
- Protected-source successor closure: `0a203088939690c64be7f0169ca2bc54d4d6e0b2`
- Sealed design gate: `R1_PTR12_RAW_SHAPE_GUARD_DECISION_OBSERVER_DESIGN_READY`
- Design family: `E_ADD_HASH_ONLY_RAW_SHAPE_AND_GUARD_DECISION_OBSERVER`
- Design compatibility: exact; historical design evidence was not rewritten.

Production files changed:

- `src/novel_flywheel/contract_runtime.py`
- `src/novel_flywheel/generated_artifacts.py`
- `src/novel_flywheel/model_diagnostics.py`
- `src/novel_flywheel/models.py`
- `src/novel_flywheel/provider_output.py`
- `src/novel_flywheel/providers/anthropic.py`
- `src/novel_flywheel/providers/openai_chat.py`
- `src/novel_flywheel/providers/openai_responses.py`
- `src/novel_flywheel/reliability_trace.py`
- `src/novel_flywheel/runtime_fingerprint.py`
- `src/novel_flywheel/workflows.py`
- `tools/canary/gate.py`

Implementation tests changed:

- `tests/canary/test_gate_budget.py`
- `tests/test_final_artifact_guard.py`
- `tests/test_r1_ptr12_guard_decision_observability.py`
- `tests/test_r1_ptr12_provider_output_observer.py`
- `tests/test_runtime_fingerprint.py`

Fresh protected-source successor staging:

- `tests/test_r0f_baseline.py`
- `tests/fixtures/reliability/r0f/r1-ptr12-observer-authorized-protected-source-successor-v1.json`

## Implemented observation contract

- Raw shape: `ProviderRawShapeObservationV1`, schema SHA `02d3107f39ed2c5af41cfa63e3d29ab7d8f8de9b285bdb0cb6134fe50d8cb5e4`.
- Shape delta: `RawToNormalizedShapeDeltaV1`, schema SHA `fe575d7b017a5b24138241f34e380faf7b72c8459edeeac724aff2f64834e631`.
- Guard decision: `PTR9GuardDecisionObserverV1`, schema SHA `ca95d410ecc1ab773ab3e70d551eae085594eb152c4fb9831214f13c417dfe9b`.
- Output-limit classification: `ContractOutputLimitClassificationObservationV1`, schema SHA `c6f101c0f7d9520574351434341b4a1da424bf17e6e42201d5ebf967ebc35dc3`.
- Feature flag: `NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1`, default off.
- ReliabilityTrace events: raw shape, raw-to-normalized delta, guard decision/recovery, and output-limit classification are diagnostic-only and do not change the historical Phase 0 coverage denominator.
- Correlation: all events reuse exact `ModelDiagnosticContextV1.inner_attempt_id`; Canary uses its existing external call ordinal through a scoped context binding.
- Adapter coverage: Anthropic, OpenAI Chat, and OpenAI Responses body and stream paths, including routes that reuse those protocols.

## Behavior and privacy results

- Reasoning-only + `max_tokens` + zero visible + no tool: exact PTR9 trigger.
- Non-trigger reasons: exact predicate-level coverage for finish mismatch, visible/final presence, reasoning absence, tool presence, unknown/projection/shape unavailability.
- Negative capability persistence/dedup: observer on/off exact.
- Alternate route and typed fail-close: observer on/off exact.
- Exception type/message/propagation: exact under observer, schema, hash, emitter, and sink failure.
- `OBSERVER_ON_OFF_BUSINESS_DIFF_COUNT=0`.
- `RAW_CONTENT_PERSISTED_COUNT=0`.
- `SECRET_FINDING_COUNT=0`.
- Synthetic performance, mocked sink, 1000 bounded-fixture iterations: off
  p50/p95/max `2.0/3.4/1207.6 µs`; on raw-bind-guard primitive
  `5082.05/6465.7/7514.4 µs`. This benchmark does not establish a CPU or
  working-memory bound for malformed/high-cardinality topology.

## Isolation and tests

- `baml_src/**` diff: 0.
- Prompt, route/model, retry, fallback, output budget, validator, Canon, StoryState, READY: unchanged.
- Planning V1 behavior diff: 0.
- Planning V2 source diff: 0; Phase B not started.
- Runtime Skill source/evidence diff: 0.
- Focused: `66 passed`.
- Related cluster: `291 passed`; separately re-run wheel-build test: `1 passed`.
- Full supported offline suite: `2770 passed, 39 skipped, 1 deselected, 6 xfailed, 1 warning` in `1237.94s`.
- Static checks: `git diff --check`, `py_compile`, project-scope check all pass.

## First failing hard invariant

- Invariant: `BOUNDED_SINGLE_PASS_RAW_SHAPE_CAPTURE`.
- Failure class: `UNBOUNDED_PRE_TRUNCATION_OBSERVER_WORK`.
- Location: `src/novel_flywheel/provider_output.py:77`.
- Case: malformed/high-cardinality block topology.
- Expected: single-pass capture with bounded memory and bounded CPU.
- Actual: the observer collects the complete block topology, processes and
  hashes all unknown types, and only then truncates persisted sequences.
- Risk: synchronous CPU and working-memory amplification can affect latency,
  cancellation, and extreme-path fail-open or exception parity.
- Privacy impact: no raw-content leak found.
- PTR9 predicate affected: no.
- Planning/Skill affected: no.
- Recommended narrow fix: `BOUNDED_SINGLE_PASS_RAW_SHAPE_CAPTURE_V1`.
- `NO_AUTOMATIC_FIX=YES`.

## Split-review execution truth

- Review mode: `TEAM_SHARDED_INDEPENDENT_REVIEW`.
- Review started: yes.
- Review completed: no.
- Completed independent shards: 1, with a failing result.
- Unrun or incomplete shards: 2; neither has a sealed result.
- Review stopped on first hard issue: yes.
- `SPLIT_REVIEW_PASS=NO`.
- `IMPLEMENTATION_PASS=NO`.
- `PHASE_B_READY=NO`.

An additional observation at `src/novel_flywheel/providers/anthropic.py:28`
remains `PENDING_INDEPENDENT_REVIEW_CLOSURE`: the default request sends
`max_tokens=8192`, while the observer effective cap is currently `UNKNOWN`.
This evidence-only seal neither classifies nor repairs that finding.

## Historical and external-action status

- `HISTORICAL_BOUNDARY12_RAW_SHAPE=UNKNOWN`
- `HISTORICAL_SAME_FAILURE_SHAPE_AS_PTR4=UNKNOWN`
- `CREDENTIAL_LOOKUP_COUNT=0`
- `PROVIDER_CLIENT_CREATION_COUNT=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `REAL_PROVIDER_CALLS=0`
- `SLICE1_PHASE_B=NOT_STARTED`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

The failure evidence is sealed without changing implementation or historical
evidence. The next authorized task may address only the bounded single-pass
capture hard issue. Phase B remains blocked, and the Anthropic effective-cap
finding remains pending as a separate review item.
