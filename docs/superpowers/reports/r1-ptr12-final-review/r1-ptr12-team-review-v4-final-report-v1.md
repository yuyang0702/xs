# R1-PTR12 Team-Sharded Independent Review V4 — Final Report

## Result

`R1_PTR12_RAW_SHAPE_GUARD_DECISION_OBSERVER_IMPLEMENTED`

`R1_PTR12_TEAM_SHARDED_INDEPENDENT_REVIEW_PASS`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_MATERIALIZATION_READY=YES`

The fresh V4 review bound branch
`r1-ptr3/planning-repair-finding-propagation-20260817` and frozen reviewed
HEAD `28d0fcc0190e7ada8c68e0f7013cb390d7b55c66`. The worktree was clean before
review. Previous review conclusions were not reused as V4 PASS evidence.

## Independent shards

- Shard A (`ptr12_v4_shard_a`): PASS. The frozen V3 adversarial case produced
  129 total touches, 128 successful touches, one rejected touch, and zero
  post-exhaustion redundant calls. Shared-budget, nested-tail, large-topology,
  unsafe-iterator, bounded-hash and privacy invariants passed.
- Shard B (`ptr12_v4_shard_b`): PASS. Chat/Responses body-stream reasoning
  lineage, aggregate-only, explicit zero, malformed/missing/multiple usage,
  DeepSeek compatibility, and Anthropic omitted/4096/8192 cap lineage passed.
- Shard C (`ptr12_v4_shard_c`): PASS. Diagnostic-context construction is
  globally fail-open without dispatch, argument, retry, fallback, result,
  exception, cancellation, negative-capability, PTR9, correlation, or ON/OFF
  business differences.

`TEAM_SHARDED_INDEPENDENT_REVIEW_COMPLETED=YES`

`COMPLETED_SHARDS=3`

`INTERRUPTED_OR_INCOMPLETE_SHARDS=0`

`UNRUN_SHARDS=0`

## Structural and truthfulness decision

`TOTAL_MAX_TOUCH_CALLS_BOUND=PASS`

`MAX_SUCCESSFUL_TOUCHES=128`

`MAX_REJECTED_TOUCH_CALLS<=1`

`MAX_TOTAL_TOUCH_CALLS<=129`

`POST_EXHAUSTION_REDUNDANT_TOUCH_CALLS=0`

`TOTAL_MAX_ELEMENTS_TOUCHED=128`

`SHARED_CAPTURE_BUDGET_COUNT=1`

`PER_CONTAINER_INDEPENDENT_BUDGET_COUNT=0`

`BOUNDED_SINGLE_PASS_RAW_SHAPE_CAPTURE=PASS`

`FULL_TOPOLOGY_PRECOLLECTION=NO`

`UNBOUNDED_DEDUP_STATE=NO`

`UNBOUNDED_UNKNOWN_HASHING=NO`

`UNBOUNDED_EXHAUSTION_TRACKING_STATE=NO`

`TAIL_TRUTHFULNESS_FOR_UNINSPECTED_NESTED_TOPOLOGY=PASS`

`NESTED_UNSAFE_ITERATOR_CONSUMPTION_COUNT=0`

`FALSE_ABSENCE_FROM_UNINSPECTED_TAIL_COUNT=0`

`FALSE_TOPOLOGY_EXACT_FROM_UNINSPECTED_NESTED_COUNT=0`

## Provider lineage and guard decision

`RAW_NORMALIZED_GUARD_DECISION_INPUT_BINDING=PASS`

`STREAM_REASONING_USAGE_LINEAGE=PASS`

`CHAT_BODY_STREAM_REASONING_LINEAGE_PARITY=PASS`

`RESPONSES_BODY_STREAM_REASONING_LINEAGE_PARITY=PASS`

`REASONING_USAGE_INFERRED_FROM_AGGREGATE_COUNT=0`

`ANTHROPIC_EFFECTIVE_CAP_OBSERVABILITY=PASS`

`REQUESTED_MAX_OUTPUT_DEFAULT_CASE=null`

`EFFECTIVE_ROUTE_CAP_DEFAULT_CASE=8192`

`PROVIDER_ACCEPTED_CAP_DEFAULT_CASE=UNKNOWN`

`PROVIDER_ACCEPTED_CAP_INFERRED_FROM_REQUEST=NO`

`ANTHROPIC_DEFAULT_MAX_TOKENS_CHANGED=NO`

`ANTHROPIC_REQUEST_KWARGS_DIFF_COUNT=0`

## Fail-open, PTR9, and business parity

`OBSERVER_IMPLEMENTATION=COMPLETE`

`DIAGNOSTIC_CONTEXT_CONSTRUCTION_FAIL_OPEN=PASS`

`GLOBAL_OBSERVER_FAIL_OPEN=YES`

`POST_FIX_CONTEXT_FAILURE_DISPATCH_DIFF_COUNT=0`

`PROVIDER_DISPATCH_ARGUMENT_DIFF_COUNT=0`

`ORIGINAL_PROVIDER_EXCEPTION_PRESERVED=YES`

`CANCELLATION_BEHAVIOR_CHANGED=NO`

`OBSERVER_CONTEXT_FAILURE_RETRY_COUNT=0`

`OBSERVER_CONTEXT_FAILURE_FALLBACK_COUNT=0`

`NEGATIVE_CAPABILITY_MUTATION_FROM_CONTEXT_FAILURE=NO`

`OBSERVER_ON_OFF_BUSINESS_DIFF_COUNT=0`

`PTR9_GUARD_PREDICATE_CHANGED=NO`

`PTR9_BUSINESS_INPUT_SOURCE_CHANGED=NO`

## Tests, provenance, isolation, and privacy

The lead cross-shard matrix passed 175 tests; the extended related PTR12/PTR9,
ReliabilityTrace, provider and R0F matrix passed 311 tests; R0F exact/tamper
parity passed 75 tests. Five PTR12 manifests with 57 entries were byte-exact.
The exact reviewed-HEAD full suite was not rerun during V4; its existing result
was 3226 passed, 41 skipped, 6 xfailed, 22 failed and 46 errors, with non-green
items confined to historical Canary/materialization evidence, Planning Skill
oracles, and the R0E live-parity fixed-hash gate. No new PTR12 acceptance
failure family was present, and no historical evidence or live database was
altered to obtain green results.

`RETRY_POLICY_CHANGED=NO`

`FALLBACK_POLICY_CHANGED=NO`

`OUTPUT_BUDGET_POLICY_CHANGED=NO`

`ROUTE_MODEL_CHANGED=NO`

`PROMPT_CHANGED=NO`

`PLANNING_V1_CHANGED=NO`

`PLANNING_V2_CHANGED=NO`

`SKILL_PROFILE_CHANGED=NO`

`RAW_CONTENT_PERSISTED_COUNT=0`

`HISTORICAL_EVIDENCE_REWRITTEN=NO`

`TEST_POLICY_WEAKENING=NO`

Maintenance documentation accurately describes the observer and still states
that Phase B is not implemented. No Runtime authority is redefined.

## External boundary and next gate

`CREDENTIAL_LOOKUP_COUNT=0`

`PROVIDER_CLIENT_CREATION_COUNT=0`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`SLICE1_PHASE_B=NOT_STARTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`SPLIT_REVIEW_PASS=YES`

`PHASE_B_READY=YES`

The next task is only
`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_MATERIALIZATION`. It requires a fresh,
single-use approval packet and does not authorize a Provider call in this V4
review or by this evidence seal.
