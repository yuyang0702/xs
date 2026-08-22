# R1-PTR12 team review V3 — failure stop report

## Result

`R1_PTR12_OBSERVER_IMPLEMENTATION_NARROW_FIX_REQUIRED`

The fresh team-sharded independent review ran against exact HEAD
`475267be5a4004cac93efb0f9aa029fc55e303e6`. Shard A returned `HARD_FAIL`.
Strict L3 then interrupted Shards B and C without conclusions. No historical
review result was reused as a V3 PASS.

## First frozen hard issue

`TOTAL_MAX_TOUCH_CALLS_BOUND_VIOLATION`

At `src/novel_flywheel/provider_output.py::capture_provider_raw_shape_v1`, an
OpenAI Chat stream containing two events, two choices in the first event, and
127 tool-call deltas in the first choice invokes the shared capture `touch()`
method 131 times. The declared upper bound is 129.

The first 128 calls successfully touch one event, one choice, and 126 tool
calls. Call 129 rejects the final tool call but exits only the tool loop. Call
130 rejects the next choice and exits only the choice loop. Call 131 rejects
the next event and finally exits the event loop.

`TOTAL_MAX_ELEMENTS_TOUCHED=128` remains true, but
`TOTAL_MAX_TOUCH_CALLS<=129` is false. The narrow fix family is to propagate a
single shared exhaustion state out of every enclosing stream loop and add an
exact multi-event/multi-choice/tool regression. This review does not authorize
or implement that fix.

## Completed evidence before stop

- Coordinator related offline matrix: `285 passed`.
- Current R0F exact/tamper/parity subset: `66 passed`.
- Six sealed evidence manifests: 66 entries checked; zero byte/hash mismatch.
- Maintenance documentation: no premature PTR12 PASS or Phase B readiness.
- Shard A: one completed independent `HARD_FAIL`.
- Shards B/C: interrupted; no result reused or inferred.

These local checks do not create an overall review PASS.

`TEAM_SHARDED_INDEPENDENT_REVIEW_COMPLETED=NO`

`COMPLETED_SHARDS=1`

`INTERRUPTED_OR_INCOMPLETE_SHARDS=2`

`UNRUN_SHARDS=0`

## Isolation and external boundary

Production source, tests, fixtures, BAML, Planning V1/V2, Skill Profile, PTR9
business behavior, and historical evidence were not modified. Only this fresh
failure-evidence directory is left uncommitted for a separate evidence seal.

`NO_AUTOMATIC_FIX=YES`

`SPLIT_REVIEW_PASS=NO`

`PHASE_B_READY=NO`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`SLICE1_PHASE_B=NOT_STARTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`
