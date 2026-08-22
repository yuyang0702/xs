# R1-PTR12 team review V2 — failure stop report

## Result

`R1_PTR12_OBSERVER_IMPLEMENTATION_NARROW_FIX_REQUIRED`

The fresh `TEAM_SHARDED_INDEPENDENT_REVIEW` completed against HEAD
`f79edfc078aecad9a0b654448416ee258c8923de`. Three shards completed and none
were left unrun. Shard A returned `PASS`; Shards B and C independently returned
`HARD_FAIL`. No prior review result was reused as PASS.

## First frozen hard issue

`STREAM_REASONING_USAGE_LINEAGE_MISMATCH`

At `src/novel_flywheel/provider_output.py:445`,
`capture_provider_raw_shape_v1` does not preserve formally exposed reasoning
usage on OpenAI Chat and OpenAI Responses stream paths. Equivalent body
metadata records aggregate output tokens 10 and reasoning tokens 4 as
`KNOWN/4`; the stream path records the reasoning usage as `NOT_EXPOSED/null`.
The failure class is
`PROVIDER_FORMAL_USAGE_LINEAGE_DROPPED_ON_STREAM_PATH`. Aggregate usage is not
used to infer reasoning usage. The affected surface includes OpenAI Chat,
OpenAI Responses, and the DeepSeek route that reuses the OpenAI Chat adapter
path.

The separately authorized next fix family is
`PTR12_STREAM_REASONING_USAGE_LINEAGE_FIX_V1`.

## Second independent hard issue

`DIAGNOSTIC_CONTEXT_CONSTRUCTION_FAIL_OPEN`

At `src/novel_flywheel/workflows.py:27184`, `WorkflowService._stage` performs
observer-only diagnostic-context construction through `db.get_role_binding`,
`db.get_provider`, and `diagnostic_domain_sha256`. Those operations are not
fully fail-open. With the observer enabled, one of these failures can stop
business execution before Provider dispatch; with the observer disabled, the
operations are skipped and execution continues.

`OBSERVER_FAIL_OPEN=NO`

`OBSERVER_ON_OFF_BUSINESS_DIFF_COUNT=NONZERO_FOR_CONTEXT_CONSTRUCTION_FAILURE`

This finding remains open. It was not fixed or bundled into the first fix
family. Its later fix family is
`PTR12_DIAGNOSTIC_CONTEXT_CONSTRUCTION_FAIL_OPEN_V1`.

## Preserved local passes

- Shard A passed bounded work, nested-tail truthfulness, privacy, and its
  scoped fail-open/parity review.
- Bounds remain 128 inspected elements, 128 touched elements, 129 maximum
  touch calls where the final call refuses before reading, 128 controlled
  details, 32 unknown details, and 512 hash-input bytes.
- Full topology precollection, unbounded dedup state, and unbounded unknown
  hashing remain absent.
- `RAW_NORMALIZED_GUARD_DECISION_INPUT_BINDING=PASS`.
- `TAIL_TRUTHFULNESS_FOR_UNINSPECTED_NESTED_TOPOLOGY=PASS`.
- `ANTHROPIC_EFFECTIVE_CAP_OBSERVABILITY=PASS`.
- Anthropic default lineage remains requested null, effective route cap 8192,
  and Provider-accepted cap `UNKNOWN`.
- PTR9 predicate and business-input source are unchanged. Negative-capability,
  correlation, R0F successor, Planning/Skill isolation, and maintenance
  documentation checks remain passing or exact within the upstream review.

These local passes do not produce an overall review pass.

## Upstream offline review evidence

- Coordinator unified matrix: `199 passed`.
- Shard A: `85 passed`, plus bounded/cancellation probes PASS.
- Shard B: `143 passed, 3 deselected`; independent body/stream probe reproduced
  the hard failure.
- Shard C: `148 passed`; independent `_stage` context-construction probe
  reproduced the hard failure.

These are sealed upstream review results. They were not rerun by this
evidence-only task.

## Isolation and stop state

Only `docs/superpowers/reports/r1-ptr12-review-v2-failure/**` was created.
Production source, tests, fixtures, BAML, Planning V1/V2, Skill Profile, PTR9
business predicates, and historical evidence are unchanged. Raw content
persisted and privacy matches are both zero. No credentials, Provider client,
network, model, paid call, Full Short Canary, or Slice1 Phase B action occurred.

`TEAM_SHARDED_INDEPENDENT_REVIEW_COMPLETED=YES`

`SPLIT_REVIEW_PASS=NO`

`PHASE_B_READY=NO`

`NO_AUTOMATIC_FIX=YES`
