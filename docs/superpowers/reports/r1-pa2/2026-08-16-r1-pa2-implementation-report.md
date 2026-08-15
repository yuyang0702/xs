# R1-PA2 Implementation Report

## Scope and commits

- Source execution HEAD: `6405b3b806d88c56accc99d5152ce7461656e33b`
- Evidence-only commit: `7ff424eefeb7056f7696a07a477be9802e86accd`
- Development branch: `r1-pa2/post-accepted-receipt-goal-stop-20260816`
- Canary patch commit: `a6311e98010e018a83fa8e333b63c80c2e97e773`
- Production Provider calls during R1-PA2 implementation: `0`
- Paid model calls during R1-PA2 implementation: `0`

No file under `src/novel_flywheel/**` or `baml_src/**` was modified. The patch
is limited to `tools/canary/**`, `tests/canary/**` and this report directory.

## Workstream A — Evidence seal

The consumed PA-STRICT-TOOL-OBS-1 run was sealed before code changes. The
commit contains the execution report, Evidence Package, Privacy Scan, Signed
Approval, signed Validate-only Receipt, Confirmed Authorization Patch, a
hash-only reserve/consume and call/cost binding, live parity binding, and a
seven-row byte-level SHA-256 manifest. Private raw evidence remains outside
Git; the commit contains only hashes and sanitized bindings.

Evidence canonical SHA-256:
`8fcaadd61ff15bedb5033054494074adcd3da26bff728782bb4684b20cbff9f1`.

## Workstream B — Canary goal-stop contract

The PA profile now installs an isolated, process-local
`ObservationGoalLatch`. The reliability sink interceptor evaluates only the
hash-only `diagnostic_strict_tool_shape` envelope. An exact target atomically
sets `observation_goal_reached=true` before the original best-effort append.
The first exact target wins; repeated events increment a duplicate counter.

The current Provider boundary is allowed to return and its Provider receipt,
budget reconciliation and business result or exception are retained. A
gateway-local dispatch lock then prevents the next boundary from passing the
goal check. The stop occurs before verification, budget reservation, final
authorization or delegate invocation, so the blocked boundary performs zero
credential lookups, Provider-client constructions, network calls and paid
calls.

The typed cancellation-shaped result is:
`CANARY_OBSERVATION_GOAL_REACHED_STOPPED`. It is not a workflow terminal,
Provider failure, Runtime defect, production incident or budget exhaustion.
Trace sink or sidecar receipt write failure cannot reopen the goal latch.

C0B Smoke has no goal latch. `NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1` remains false
and forbidden for the PA profile.

## Workstream C — Calls 10 through 22

`PostAcceptedReceiptCallTimelineV1` proves:

- Call 10 completed and accepted the Planning Adaptation Whole artifact
  `5767b8f041dfe4af39cd5923bf0a21ee680c74ee62fb5873b7095b3fc647378e`.
- Call 11 was normal downstream causal-chain generation, not another Whole
  fallback attempt.
- Calls 11–14 were causal-chain recovery/capacity-split attempts.
- Calls 15–17 produced causal-chain packets and an execution manifest.
- Calls 18–19 performed manifest review and one receipt-only retry.
- Calls 20–22 were Draft plus two bounded scope retries.
- The workflow terminal occurred after call 22 returned, at the Draft leaf
  prose gate with `prose_invalid`.

No exact per-call checkpoint binding exists. The report therefore records
`unknown`/`unverifiable` rather than constructing a causal edge.

## Workstream D — Accepted Whole Receipt closure

Gateway uniqueness acceptance was only the first layer. Independent trace and
receipt evidence proves native-object argument extraction, exact adapter
projection, valid Contract/Domain outcome, Planning Adaptation merge-ready,
and accepted artifact materialization. The Planning Adaptation boundary
closed; the Short workflow did not.

Two limitations remain explicit:

- Schema success is supported by the valid Contract Runtime receipt but lacks
  an independently signed per-validator receipt.
- The accepted artifact's exact checkpoint binding is unverifiable.

## Test results

- Goal-stop and evidence focused suite: `20 passed in 0.64s`.
- Full Canary suite: `183 passed, 1 skipped in 546.79s`.
- Full repository suite: `2677 passed, 2 skipped, 5 xfailed, 1 failed`
  in `1335.70s`.
- The one failure is the pre-existing
  `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`:
  the test expects the historical DB hash `5deb7bdf...`, while the already
  accepted live baseline is `0fccb8ae...`. R1-PA2 neither caused nor repairs
  that mismatch. New failures: `0`.
- No real Provider or paid-model test was run.

Post-test live characterization remains:

- DB SHA-256:
  `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`
- Formal story artifact SHA-256:
  `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745`
- Canon artifact SHA-256:
  `5361f3729dd191e987f2494cb7bac1ebf15d9a9837465208262e3ee3f24f49fc`
- StoryState / Candidate / Checkpoint rows: `6 / 11 / 917`

No new Canary execution is authorized by this report.
