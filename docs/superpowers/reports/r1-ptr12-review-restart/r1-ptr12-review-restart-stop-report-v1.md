# R1-PTR12 fresh team review restart — failure stop report

## Result

`R1_PTR12_OBSERVER_IMPLEMENTATION_NARROW_FIX_REQUIRED`

The fresh `TEAM_SHARDED_INDEPENDENT_REVIEW` completed against HEAD
`3d3fd185ba9a6027ac6c33aa861a869e415a40c6`. All three independent shards
returned `HARD_FAIL`; no prior failed review was reused as PASS.

## Frozen review truth

- Shard A: `TAIL_TRUTHFULNESS_FOR_UNINSPECTED_NESTED_TOPOLOGY`
- Shard B: `ANTHROPIC_EFFECTIVE_CAP_OBSERVABILITY`
- Shard C: `RAW_NORMALIZED_GUARD_DECISION_INPUT_BINDING`
- Completed shards: 3
- Unrun shards: 0
- Split review pass: no
- Phase B ready: no
- Automatic fix: no

The first frozen hard issue is Shard C. Raw visibility was false while
normalized visibility was true, but the decision telemetry recorded both as
true and produced `predicate_all_true=true`. The production PTR9 business
predicate itself was not changed.

Shard A confirms that the bounded work limits are present, but an uninspected
nested topology can still be described as exact with a false absence claim.
Therefore bounded capture does not receive an overall review pass and tail
truthfulness remains open.

Shard B formally classifies the Anthropic effective-cap finding as
`HARD_OBSERVABILITY_DEFECT`. With no caller override, the outgoing effective
cap is deterministically 8192; requested output remains null and Provider
acceptance remains unknown.

## Preserved invariants

- Structural limits remain 128 inspected, 128 touched, 128 controlled details,
  32 unknown details, and 512 hash-input bytes.
- Raw content persisted: 0.
- Observer ON/OFF covered-case business differences: 0.
- PTR9 production predicate changed: no.
- Existing negative-capability, correlation, and R0F successor tests pass.
- Prompt, Planning V1/V2, Skill Profile, route/model, retry/fallback, and output
  budget policy are unchanged.
- Historical evidence and test policy are unchanged.

## Stop state

This seal contains failure evidence only. No source, test, fixture, BAML,
historical evidence, Provider call, model call, Full Short Canary, or Slice1
Phase B action was performed.

`SPLIT_REVIEW_PASS=NO`

`PHASE_B_READY=NO`

`NO_AUTOMATIC_FIX=YES`

The next separately authorized task is
`RAW_NORMALIZED_GUARD_DECISION_INPUT_BINDING_FIX_V1`.
