# C0B-SMOKE-1 Final Approval Materialization V2 report

> Gate: `C0B_SMOKE_1_WAITING_FOR_FINAL_USER_AUTHORIZATION`. This package is not an executable Approval. Do not run the command preview until the candidate is revalidated inside its UTC window and the user-signed Approval is separately materialized.

## Result

The disabled C0B-SMOKE-1 Final Approval Candidate was materialized against the current Canary launcher and production-mirror configuration. Full CLI validate-only closure is `25/25 exact`. No credential lookup, provider-client construction, network request, model call, paid call, Approval reservation, Approval consumption, or Smoke execution occurred.

The scope is exactly `C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1`, with one `short-normal-v1` workload and Phase 1B disabled. The Plan retains the 144-call outer ceiling; the candidate binds the stricter 48-call single-use cohort ceiling.

## Approval package

| Artifact | Purpose | Contract hash |
| --- | --- | --- |
| `c0b-smoke-1-final-plan-v2.json` | Final hash-bound Plan | `20cc492ebca200ee9d3cfe42a3f09d6ad5d63e908031457b055e34833263da11` |
| `c0b-smoke-1-final-approval-candidate-v2.json` | Disabled Final Approval Candidate | `8428668102b0e7ea359ef04148d550e22359175a38380a37a77c1c5905e4bc06` |
| `c0b-smoke-1-user-authorization-patch-v1.json` | Future user authorization fields, unapplied | `8f70676b6545caabc6f76bb6750ec7ecfc8fc2cd7ca2d170d1c59e1d24d357e5` |
| `c0b-smoke-1-final-validate-only-receipt-v2.json` | Complete offline closure | `6501e0bfb0f9fc42b59ce664df8161b660bfa440c0a8786c7a80ae2af61c21c4` |
| `c0b-smoke-1-execution-command-preview-v1.json` | Non-executed, credential-free preview | `2eb72cbbe5f1f50c80a3aa11898cfaa39b227f19f7f6a44eba779164d528bc93` |
| `c0b-smoke-1-final-packet-v2.json` | Cross-bound evidence packet | See materialization index for file SHA-256 |
| `c0b-smoke-1-final-materialization-index-v2.json` | File inventory and counters | `8fc07c1929f77c525d5af0cfd5d1cd4d554b668d33d3728b4f6d153b597fce04` |

The User Authorization Patch contains only future user confirmation fields and action switches. It is bound to the Plan, Candidate, launcher, workload, Build, Execution Config, and Runtime Execution hashes. It has not been applied.

## Exact bindings

| Binding | SHA-256 |
| --- | --- |
| Launcher | `d31e48812986b41ac3ee43fa26baa655625f5d6b0503f05d875f4ba43b060a34` |
| Workload bytes | `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1` |
| Workload manifest | `80a37d9270f7d0dc5f4260e391b0c53d4232c1abda4b859d8dbaf11a07a018ae` |
| Production Build Fingerprint | `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0` |
| Execution Config Fingerprint | `70a487fa8f2152e14923aa82560ace39c83a052e4556e03eb1b54ba4976bff13` |
| Runtime Execution Fingerprint | `eb2ed19dd0b6b9a7517f6044f4a8aecb0aadfcb9f2e1303f3ba77567a8b710a5` |
| Provider Descriptor manifest | `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f` |
| Role/Route Binding manifest | `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e` |
| Pricing Evidence manifest | `053fbf7d5fe203257dfb200e019c0ac4bdb811f09e244db4f37c906c7667649a` |
| Feature Flag Snapshot | `84c9b4c8e118bb14fe177bb3aabc29866710cec8b50bc37c1b9ba9c4cda39a05` |
| Call Budget definition | `1a6e5ee9ccae3ba31e0f945bc43a8ff8bffa23744d78905fd039e461faab9572` |
| Token Budget definition | `34acc16519f866a9b07318e1a85c18616f345d5dc7d336717837eb04c406db7e` |
| Monetary Budget definition | `e0e8c7080e1cbb4ccdaccda1ab336a14d692271539afb325c9951b999eceef18` |
| Elapsed Budget definition | `0b7fe3382a03755ae163999b4836256612827c60090169442b93577086b4bbf8` |
| Combined Approval Budget | `7d1d7d5c60bc11d6191dcc026dd6737adf52e186cd54abcfb1e424640287ea77` |
| Stop Condition manifest | `b50e7bbf835fe1fa4f10565e11a0ab9ec645e045ae11cf48718707d8ca9d1d51` |
| Canary root identity candidate | `99e494ce07309d4c72eac7151a427deea3a1fa56f1e70972d215b8bde15aec4f` |

Production-mirror validation covered the approved primary/fallback bindings for planning, draft, review, reader review, final review, polish, line edit, and maintenance. Route comparison was exact; no route was repaired or rewritten. Pricing remained the existing no-FX USD/CNY catalog, including the approved Happy `default` relay group.

## Window, cohort, and budgets

| Field | Exact value |
| --- | --- |
| Materialized at | `2026-08-15T05:19:34Z` |
| Window start | `2026-08-15T05:34:34Z` |
| Window end / expiry | `2026-08-17T05:34:34Z` |
| Cohort | `c0b-smoke-1-v2-20260815t051934z-3947ac6` |
| Runs | `1` |
| Expected model calls | `16` |
| Maximum cohort model calls | `48` |
| Input/output tokens | `1,000,000 / 1,000,000` |
| Per-call output cap | `32,000` |
| USD/CNY caps | `$20.00 / ¥50.00`, independent, no FX |
| Elapsed cap | `7,200 seconds` |
| Terminal policy | first terminal stops; no resume after terminal |

Candidate authorization is false for credential lookup, provider client creation, network, paid model calls, and execution. `named_approver` remains `USER_CONFIRMATION_REQUIRED`; cohort status remains `unused`.

## Validation and regression evidence

### E-001

- title: Full CLI validate-only closure
- observed_at: `2026-08-15T05:19Z`
- source_type: command
- source_ref: `python -m tools.canary.launcher --validate-only ...`
- content_hash: receipt `6501e0bfb0f9fc42b59ce664df8161b660bfa440c0a8786c7a80ae2af61c21c4`
- repro_command: use the paths and Plan hash in `c0b-smoke-1-execution-command-preview-v1.json`, replacing `--real-run` with `--validate-only` and supplying empty temporary Canary/ledger roots.
- raw_excerpt: `overall_status=exact; ordered_checks=25; external counters=0/0/0/0/0`
- linked_workitem: C0B-SMOKE-1
- supersedes: none

### E-002

- title: Canary regression suite
- observed_at: `2026-08-15`
- source_type: command
- source_ref: `.venv/Scripts/python.exe -m pytest tests/canary -q`
- content_hash: n/a
- repro_command: `.venv/Scripts/python.exe -m pytest tests/canary -q`
- raw_excerpt: `98 passed, 1 skipped`
- linked_workitem: C0B-SMOKE-1
- supersedes: none

### E-003

- title: Pre-existing R0E failure unchanged after materialization
- observed_at: `2026-08-15`
- source_type: command
- source_ref: `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`
- content_hash: live DB `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`
- repro_command: `.venv/Scripts/python.exe -m pytest tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical -q`
- raw_excerpt: expected historical R0 DB `5deb7bdf…`; observed task-start and post-materialization DB `0fccb8ae…`
- linked_workitem: R0E baseline drift
- supersedes: none

### E-004

- title: Live business artifact parity
- observed_at: `2026-08-15`
- source_type: file
- source_ref: `data/app.db` and latest live project artifacts
- content_hash: formal manifest `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908`
- repro_command: `.venv/Scripts/python.exe -c "from pathlib import Path; from tests.r0e_report_evidence import live_parity_snapshot; print(live_parity_snapshot(Path('.').resolve()))"`
- raw_excerpt: DB `0fccb8ae…`; StoryState 6; Candidate 11; Checkpoint 917; Canon manifest `d5600447…`; Candidate/Checkpoint/Saga file manifests empty `4f53cda1…`
- linked_workitem: C0B-SMOKE-1
- supersedes: none

### F-001

- title: Final Approval Candidate is complete but non-executable
- severity: info
- category: design
- status: validated
- evidence_ids: [E-001, E-002]
- location: `tools.canary.final_approval.materialize_c0b_smoke_1_final_approval_v2`
- impact: The user can review exact hashes and authorization scope without exposing credentials or triggering a paid boundary.
- confidence: high
- repro_steps: materialize into an isolated output directory, then run validate-only with empty temporary roots.
- remediation: A future signed Approval must be separately created and revalidated; this candidate must never be passed to real execution.

### F-002

- title: Materialization did not mutate live business state
- severity: info
- category: design
- status: validated
- evidence_ids: [E-003, E-004]
- location: `data/app.db`, latest live project StoryState/Canon/Candidate/Checkpoint/Saga artifacts
- impact: The approval package is control-plane evidence only.
- confidence: high
- repro_steps: compare the task-start hashes and row counts to a post-materialization `live_parity_snapshot`.
- remediation: none.

### P-001

- title: Final Approval materialization call flow
- path_type: callflow
- start: current launcher bytes and production-mirror metadata
- goal: disabled, exact, user-reviewable Approval Candidate
- steps:
  1. Recalculate launcher, workload, source/build/config/runtime, route, price, budget, flag, stop, and root hashes — evidence: E-001 — finding: F-001.
  2. Build Candidate with every external action false and build an unapplied authorization patch — evidence: E-001 — finding: F-001.
  3. Run the 25-check closure under a fail-closed network sentinel and read-only cohort status — evidence: E-001 — finding: F-001.
  4. Recheck live DB and formal artifacts — evidence: E-003, E-004 — finding: F-002.
- residual_risks: A real-provider run remains untested and unauthorized. Window expiry or any bound hash drift requires rematerialization.

## Test status and parity

- Focused Candidate + legacy closure/Launcher: `24 passed`.
- Full Canary suite: `100 passed, 1 skipped`.
- Full suite: `2537 passed, 2 skipped, 5 xfailed, 1 failed` in `1159.05s`.
- Pre-materialization known failure: the R0E live DB fixed-hash assertion failed with actual `0fccb8ae…` versus historical expected `5deb7bdf…`.
- Post-materialization known failure: identical test and identical actual/expected hashes.
- New failures: `0`.
- `src/novel_flywheel/**`, `baml_src/**`, Prompt, Route, retry/fallback, and Phase 1B behavior changed: no.
- Live DB, formal narrative, StoryState, Canon, Candidate, Checkpoint, and Saga parity: exact against task start.
- External action counters: credential/provider-client/network/model/paid = `0/0/0/0/0`.
- Approval reserved/consumed: no/no.
- Command preview executed: no.
- C0B-SMOKE-1 executed: no.

## Next authorized action

The next action requires new user authorization. If authorization is not completed within `2026-08-15T05:34:34Z` through `2026-08-17T05:34:34Z`, or any bound file/hash/config changes, discard this candidate and rematerialize it. Do not extend the existing window.

**C0B_SMOKE_1_WAITING_FOR_FINAL_USER_AUTHORIZATION**
