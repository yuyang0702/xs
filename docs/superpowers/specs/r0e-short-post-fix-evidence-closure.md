# R0E — Short Post-Fix Evidence Closure & Controlled Exposure

## Change contract

Requested outcome: close the remaining offline evidence gaps from R0 without
changing production behavior, then define (but do not execute) an isolated,
fingerprint-bound real-provider canary.

Original material MUST requirements:

- keep `src/novel_flywheel` byte-for-byte unchanged;
- use only tests, sanitized fixtures, documentation, and evidence reports;
- preserve the 123-row historical corpus and the R0 44-family/97-incident
  residual denominator;
- prove bypass causality only through comparable paired controls and a unique
  first-divergent node;
- distinguish expected controlled outcomes from policy violations;
- keep non-historical mechanism probes outside historical recovery metrics;
- require three independent databases/runs and representation diversity before
  any historical family can receive `DEVELOPMENT_GO`;
- report boundary, stage, workflow, controlled-nonterminal, and final outcomes
  separately;
- verify protected best Candidate and checkpoint/resume containment on Repair
  failures;
- inject truncation at the provider-result boundary with finish metadata;
- keep real-provider canary blocked until `RuntimeBuildFingerprintV1` exists;
- make no paid model call.

Scope classification: open_world evidence characterization; no behavior fix is
authorized.

Operational definition: R0E may classify current reachability, reproduce a
failure with an offline deterministic gateway, compare an existing bypass with
a Contract Runtime control, and report the result. It may not change the path
under test or reinterpret an expected `waiting_provider`, `waiting_user`,
resumable, or explicit-terminal policy outcome as a defect.

Forbidden narrowing: a parser-only call is not a workflow reproduction; one
identical fixture called three times is not family representation coverage; a
bypass observed without a paired differential is not a causal root; a
mechanism probe is not a historical incident; a canary-mixture rate bound is
not a production-distribution rate bound.

Authorization: implementation, limited to tests, sanitized fixtures, docs, and
reports. Real-provider operation is not authorized.

Current behavior and evidence: R0 HEAD
`5a152b097732447d4a5e1db2f9ef0215815bcb91` has 123 manifest rows, 26
high-frequency offline workflow recoveries, and 44 residual families covering
97 incidents. Maintenance normal/window and polish semantic Repair contain
sibling calls without an executable structured Contract Runtime specification.
That static fact is correlation only until R0E paired evidence is available.

Allowed changes: `tests/r0e_*`, `tests/test_r0e_*`, sanitized fixtures beneath
`tests/fixtures/reliability/r0e`, this spec, and reports prefixed `r0e-`.

Protected unchanged behavior: Runtime, GeneratedArtifactGateway, model routing,
prompt bytes, budgets, retries/fallbacks, Supervisor policy, incident catalog,
checkpoint/resume, Maintenance/Repair decisions, Phase 1B flags, live database,
live project artifacts, and all source files.

Authority impact:

- formal manuscript, current/protected Candidate, StoryState, Canon, outline,
  receipts, project artifacts, SQLite schema/rows, model bindings, Runtime
  Skills, checkpoints/resume, API/UI, credentials: read-only evidence or not
  involved;
- test temporary databases/projects: changed and disposable;
- R0E reports and sanitized fixtures: changed, hash-only or synthetic.

Selected approach: four independently reversible commits: R0E-A parent seal and
prioritization; R0E-B Maintenance boundary/paired controls; R0E-C Repair and
residual closure; R0E-D fingerprint characterization, controlled-exposure plan,
gates, parity, and final reports.

Rejected alternatives: production instrumentation (outside approval), parser
unit tests as workflow evidence, modifying Maintenance/Repair to create the
desired comparison, paid canary without a run fingerprint, and global Runtime
development approval.

Rollback path: revert the four R0E commits newest-first. No production state or
schema rollback is required. Any detected `src/novel_flywheel` diff stops the
phase before commit.

Focused tests: the matching `tests/test_r0e_*.py` file before each commit.
Related tests: R0 report/manifest/replay tests, Maintenance and workflow tests,
Repair/checkpoint/resume tests, CompletionSupervisor/task policy tests.
Full-suite requirement: `python -m pytest -q`; no new failures relative to the
R0 baseline. Every command uses `.venv/Scripts/python.exe` in this workspace.

Historical incident families checked: all 44 residual families. Mechanism probes
for Maintenance normal/window and Repair secondary output have historical count
zero and remain a separate evidence namespace.

Projected sibling and downstream risks: completeness classification, local
normalization, conversion, adapter/domain validation, protocol retry, configured
fallback, Candidate overwrite, checkpoint binding, resume selection, secondary
cleanup masking, and Supervisor terminal projection.

Model-output variants and stable invariants: malformed JSON, fenced JSON,
missing field, wrong container, version mismatch, schema-valid/domain-invalid,
provider-boundary truncation, and primary/fallback exhaustion. Stable oracles are
typed first failure, attempt order, hash-bound Candidate/checkpoint, workflow
status, and causal-chain preservation; no creative wording is asserted.

Model-output topology classes: canonical object, fenced/wrapped object,
wrong-container object, partial/truncated provider envelope, and route exception.

Unseen valid variants: evidence work does not expand accepted representations.
Unknown-variant behavior is reported from the current path, never changed.

Requirement-to-code/test/evidence traceability is recorded in
`r0e-residual-prioritization-matrix.json` and the final R0E report.

Resolution status: unresolved until all four evidence commits and full-suite
verification are complete. R0E does not claim a systemic behavior resolution.

Why previous tests missed the production shape: R0 closed the high-frequency
planning families but had no incident-bound Maintenance/Repair executions, no
paired bypass controls, incomplete legacy typed chains, and no run-level source
fingerprint.

Forward-risk report: this phase changes no model-output or authority boundary;
it characterizes them with offline workflow tests. The final report must keep
deterministic fault coverage, structural reachability, real-provider exposure,
and production-distribution exposure separate.

Unresolved user decisions: implementation of `RuntimeBuildFingerprintV1` and
any real-provider canary require a separate approval.

## Evidence classification

- A: exact/hybrid incident-bound replay through the current workflow.
- B: incident-specific structurally isomorphic replay through the current
  workflow.
- C: current static path proof without an incident-bound executable oracle.
- D: legacy evidence insufficient to determine the typed causal chain.

An upgrade to A/B must name the historical incident, typed boundary, contract,
failure topology, retry/fallback schedule, terminal signature, independent run
identities, and representation set. Mechanism probes cannot upgrade historical
evidence on their own.

## Paired bypass classification

- `BYPASS_CAUSAL`: comparable inputs and policies have one first-divergent node,
  and only the bypass reaches the adverse workflow outcome.
- `BYPASS_CORRELATED`: the bypass exists, but another material difference or
  missing downstream oracle prevents causal attribution.
- `NO_DIFFERENTIAL_EFFECT`: the paired paths have the same recovery/outcome.
- `EVIDENCE_GAP`: no honest comparable control can be constructed.

## Per-family gate

The only values are `DEVELOPMENT_GO`, `DEVELOPMENT_NO_GO`, `MONITOR_ONLY`,
`NEEDS_PRODUCTION_EXPOSURE`, `NOT_CURRENTLY_REACHABLE`, and
`MECHANISM_FIX_CANDIDATE`. `DEVELOPMENT_GO` additionally requires a policy
violation, workflow-level terminal oracle, paired causal control when a bypass
is alleged, and three independent reproductions spanning an exact/hybrid plus a
structural payload, two structurally different same-family payloads, or three
historical incident oracles.

## Runtime fingerprint and canary hard gate

R0E only characterizes current availability. Until a run itself records and
binds `RuntimeBuildFingerprintV1`, the final status is:

- fingerprint instrumentation: `NOT_IMPLEMENTED`;
- real-provider canary: `BLOCKED_BY_FINGERPRINT`;
- paid calls: `0`.

The exposure design uses the one-sided 95% zero-failure upper bound
`1 - 0.05 ** (1 / N)` (approximately `3/N`). It reports a canary-mixture bound
unless workload weights are demonstrated to match production distribution.
