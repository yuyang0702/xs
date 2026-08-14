# C0A — Controlled Short Canary Launcher & Approval Packet Report

## Decision

`GIT_WORKSPACE_CANARY_LAUNCHER_READINESS = READY_FOR_C0B_APPROVAL_PACKET`

`PACKAGED_CANARY_LAUNCHER_READINESS = NO-GO`

`REAL_PROVIDER_CANARY_READY = NO`

C0A is complete and stops here. It proves that a fake-boundary Short workflow
can be parked, independently preflighted, released, revalidated at every model
boundary, budgeted, isolated, and evidenced without reading credentials,
creating provider clients, using the network, making paid calls, or changing
live artifacts. It does not approve C0B or C0C.

## Implementation and commit boundaries

- Branch: `c0a/controlled-short-canary-launcher-20260814`.
- C0A-1: `710e232` — contracts, canonical hashes, approval schema, dependency
  closure tests.
- C0A-2: `bbc63a0` — launcher gate, isolation, approval ledger, atomic budget,
  route policy, blocked matrix.
- C0A-3: the commit containing this report — full fake Short dry run, evidence,
  packet and operations documentation.

No file under `src/novel_flywheel/**` or `baml_src/**`, and no
`pyproject.toml`, is changed by C0A.

## Delivered files and purpose

- `tools/canary/contracts.py`: strict Plan and Approval contracts.
- `tools/canary/hash_manifest.py`: launcher hash and import/dependency closure.
- `tools/canary/approval_store.py`: exclusive reservation and evidence-bound
  single-use consumption.
- `tools/canary/gate.py`: bounded two-phase gate and per-boundary wrapper.
- `tools/canary/preflight.py`: exact revalidation matrix.
- `tools/canary/budget.py`: atomic conservative budget reservations.
- `tools/canary/isolation.py`: real-path root sentinel and overlap controls.
- `tools/canary/network_sentinel.py`: fail-closed DNS/socket sentinel.
- `tools/canary/route_policy.py`: exact approved role/stage/route checks.
- `tools/canary/outcomes.py`: Canary-only outcome taxonomy.
- `tools/canary/descriptors.py`: deterministic fake provider/model bindings.
- `tools/canary/fake_boundary.py`: sanitized deterministic Short outputs.
- `tools/canary/environment.py`: isolated data roots and forced-off production
  feature flags.
- `tools/canary/artifact_hash.py`: hash-only live and isolated artifact parity.
- `tools/canary/evidence.py`: sanitized `CanaryEvidencePackageV1`.
- `tools/canary/packet.py`: exact fake Plan/Approval preparation.
- `tools/canary/dry_run.py`: registered API handler plus real Short workflow
  orchestration.
- `tools/canary/launcher.py`: validate-only and fake dry-run CLI entry point.
- `tests/canary/**`: contract, closure, gate, concurrency, budget, root,
  approval, network, mismatch matrix, evidence and full workflow tests.
- `tests/fixtures/canary/short-normal-v1.json`: sanitized deterministic 6,000
  word-target workload descriptor; it contains no novel text.

## Contracts and dependency manifest

The final `CanaryExperimentPlanV1`, `CanaryPlanApprovalV1`, and
`CanaryEvidencePackageV1` schemas are defined in the companion spec. All use
`runtime-fingerprint-canonical-json-v1`, UTF-8 canonical JSON and domain hashes.
Plan, Approval, CLI-approved Plan hash, launcher manifest, workload fixture,
workload manifest, descriptors and bindings must agree exactly.

The launcher dependency manifest includes `tools/canary/**/*.py`, the captured
production package, and the Python standard library. Its C0A third-party list is
empty. Tests demonstrate rejection of dynamic imports/code, unapproved modules,
test helpers, and executable files from outside the manifest.

## Gate, dispatch, budget, and outcomes

The first boundary used `PARKED -> PREFLIGHT_RUNNING -> APPROVED -> RELEASED`.
The alternate blocked path is tested. Events provide bounded coordination
without busy waiting; cancellation and timeout release waiters.

At each of 16 fake boundaries, the actual requested stage, role, ordinal,
provider/model binding hash, protocol, route kind, output budget, and retry or
fallback reason were checked before delegation. All were approved primary
routes. There were 17 exact preflight receipts: one independent initial release
receipt plus one receipt for each boundary.

The budget ledger atomically reserved 16 calls, 36,708 estimated input tokens,
46,197 maximum output tokens, and zero cost microunits. Concurrent oversell,
retry/fallback re-reservation, missing usage retention, call/token/cost/time
exhaustion, and first-terminal stop behavior are characterized in focused tests.

Outcomes remain separate: pre-provider blocks and launcher infrastructure
failures do not count as workflow terminal or production incidents. The observed
result was `WORKFLOW_COMPLETED` with reason
`official_short_api_fake_workflow_completed`.

## Exact fake Short run

The run invoked the registered FastAPI Short start endpoint handler, received
its declared 202 response, and let the production `RunTaskManager` execute the
real Short `WorkflowService`, `_stage`, Contract Runtime, parsers, adapters,
validators, writers, maintenance path, and completion state. Only the paid
provider boundary was replaced by the deterministic fake gateway. The optional
CrewAI outer wrapper was intentionally disabled and remains a coverage gap.

Ordered boundaries were:

1. planning/planning
2. review/review
3. review/review
4. planning/planning
5. planning/planning
6. review/review
7. draft/draft
8. review/review
9. review/review
10. review/review
11. review/reader_review
12. polish/polish
13. review/review
14. review/review
15. final_review/final_review
16. maintenance/maintenance

All routes were primary; no protocol retry or fallback was induced in the normal
run. The ledger stores only system/user hashes and budget metadata, not prompt
or output text. Prompt mutation was disabled. Runtime prompt construction,
Contract Runtime, retry/fallback decisions and output budgets were not changed.

## Fingerprints, binding, approval and parity

- Plan: `668ebb9b7be09ed098d87a779d8566dc52c0e89a1cd5af7b551bbc311938cf8b`.
- Approval: `29c2495a9243b21e8436d94ba93f67b7a53ddc1bac4f51b29198724fc360cd18`.
- Launcher: `2f9a6e2c052f05ae811444de7772c5ca29afda9166dd8b8d60af85be61b5e3f1`.
- Build: `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0`.
- Execution config: `c899efe5d937cedec73fbf55bd2f5155f86889ff8b6f5c2abb3ca50a6d32a25e`.
- Runtime execution: `9f0bb89dd5fe2c83ad52e5436777fc7731b66a1f7bcbd446dab868c65a585f5d`.
- Per-boundary fingerprint status: exact.
- Origin/executor binding: exact, zero conflicts.
- Evidence: `476d45e95de353782a041848a1af027b32bb85e8f1258128e662b83aa3480e07`.
- Approval consumption: consumed once and bound to the evidence hash.

The live database had zero active runs. The combined live database, project and
incident manifest hash was
`3bdb81626f7f51cbe593b4a2283a39e036d6877f75237601e82ae206f8a35add`
both before and after. Status is exact. The isolated run produced 107 files with
tree hash `bb3883f9e9ef3a9d41854d6145bb4fdc1ecb967fc2f322e18956a38be6bd8d7f`.

The run counters were: credential lookup 0, provider-client creation 0, network
calls 0, paid model calls 0, fake boundaries 16. No credential value or provider
client was created. The network sentinel remained armed for the entire
application/model interval.

## Failure-injection and characterization matrix

Focused tests block build, execution config, Runtime execution, source bytes,
launcher, plan, approval, workload, fixture, provider descriptor, model binding,
role, stage, fallback, feature flag, origin, executor, sidecar, root identity,
path overlap, path length, expiry, replay, window, and budget mutations before
delegation. They also cover gate timeout, worker cancel, launcher abort, network
attempt, approval reservation/consumption, concurrent budget access, malformed
evidence, and root link/reparse behavior. Actual Windows symlink creation may be
unavailable without OS privilege; a deterministic reparse-point simulation is
therefore the executable proof, while the environment-dependent creation test
is skipped.

## Performance

- Full isolated Short run: 33.478185 seconds.
- Initial gate: 1.190757 seconds.
- Per-boundary fingerprint capture, 17 samples: p50 1.050059 seconds, p95
  1.097632 seconds, maximum 1.139257 seconds.

These figures describe C0A's synchronous safety harness. They are not a real
provider latency or production throughput claim.

## Provider/model matrix and exposure candidates

The draft approval packet records the current route candidates, but capability,
context/output limits, structured-output support and prices lack verified source
evidence. Therefore no candidate is selected or approved.

A possible pilot is five runs, 73 expected calls and a 100-call hard cap, with
2,000,000 input and 750,000 output token caps. Cost remains unknown, so this is
not executable. Statistical candidates are 59/99/299 runs with 861/1,444/4,359
expected calls and 1,180/1,980/5,980 hard caps. If they observed zero failures,
their approximate one-sided 95% upper failure bounds would be 4.951%, 2.981%,
and 0.997%. Token, time and monetary caps still require calibration and explicit
approval.

## Tests

Before C0A, the full suite was `2438 passed, 1 skipped, 5 xfailed` with no
failures. C0A focused tests completed with `47 passed, 1 skipped`; the combined
Canary/Runtime-fingerprint/Phase-1B regression selection completed with
`77 passed, 1 skipped`. The final full suite completed with `2485 passed,
2 skipped, 5 xfailed, 1 warning` in 1,054.40 seconds. Relative to baseline this
is 47 additional passes, one additional environment-dependent skip, and zero
new failures.

## Coverage gaps and C0B gate

The remaining gaps are explicit:

- real provider capability and price evidence are unverified;
- packaged Runtime was not executed;
- the CrewAI outer wrapper was not executed;
- HTTP transport scheduling was not exercised separately from the exact
  registered endpoint handler because the first-boundary external gate must run
  independently of the application background task;
- 13k/20k/30k output capacity is not claimed;
- normal-run fallback/retry branches are covered by deterministic tests, not by
  this successful workflow instance.

Consequently, the packaged launcher remains NO-GO and real-provider Canary is
not ready. C0B requires a new, exact approval containing verified provider
capabilities and prices, full budgets, exact fingerprints/hashes, an execution
window, cohort, stop conditions, network/credential scope, and a named approver.
The draft packet grants none of those actions.
