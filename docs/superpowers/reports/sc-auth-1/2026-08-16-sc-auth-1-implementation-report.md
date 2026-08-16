# SC-AUTH-1 Implementation Report

## Final gate

`SHORT_COMPLETION_APPROVAL_PROFILE_READY`

`SHORT_COMPLETION_CANARY_WAITING_FOR_FINAL_USER_AUTHORIZATION`

No real Signed Approval was created. No workflow or provider was executed.

## Branch and commits

- Branch: `sc-auth-1/short-completion-profile-20260816`
- Base: `ea31fa5f1b46d73a0b38f867a456c58080d50497`
- Contract/implementation commit: `233f5ac43acc610d9da25f7762eac83ed6c140eb`
- This report and the inert materialized packet are sealed by the following
  audit-material commit.

## Changed files and scope

Production source is unchanged: the diff from the base under
`src/novel_flywheel/**`, `baml_src/**`, and `pyproject.toml` is empty.

The implementation changes are limited to:

- Canary registry/dispatch/plan/launcher/runner integration:
  `tools/canary/approval_profiles.py`, `approval_dispatch.py`, `contracts.py`,
  `launcher.py`, and `real_run.py`;
- new Short Completion definitions, approval contracts, closure, materializer,
  and verifier under `tools/canary/short_completion*.py`;
- Canary-only tests under `tests/canary/**`;
- the SC-AUTH-1 specification and hash-only reports under
  `docs/superpowers/**`.

No Prompt, production route, provider/model, retry/fallback, output budget,
Planning Adaptation, Draft validator, Final Review business logic,
Maintenance business logic, StoryState, Canon, or Phase 1B code changed.

## Registered profile

The closed-world registry is exactly:

1. `c0b_smoke_1`
2. `pa_strict_tool_obs_1`
3. `short_completion_1`

The new profile has:

- profile id: `short_completion_1`
- scope: `SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY`
- mode: `short_completion`
- definition hash:
  `91735e0fa33629efd98158189f6272902e95605b7b0ee03c034ac6aa745f7bf8`
- workload: `short-normal-v1`
- production runner: existing `production_mirror_short_v1`
- completion goal:
  `SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED`

Unknown profile, scope, mode, and schema fail closed. The existing C0B and PA
profile definitions and stop manifests were not changed.

## Completion definitions

The definition bundle is
`ShortCompletionDefinitionBundleV1`. Its key hashes are:

- Completion Goal:
  `af51e8ac730270cd99a6f3ead9e0d9dfebabcc7e13ab48ec6c53b3d1e018fd23`
- Final Review:
  `6f3502224b72f4d5946854b12756122e4a5cd8e78a2464748a597e6880b1faca`
- Maintenance:
  `7f9713049b613165f6b56cacb6d0063b20545684ca125abcc72277e62e7aee1b`
- Final Artifact:
  `370dfcfa8e90a00e083b0e2520f66783e51857cc549739416fb6396e3c680efb`
- Final Checkpoint:
  `504e83d56d9640d1d3fa9dd6227a92faa0b14d3e1ae21cae291994f383f61086`
- Draft Validator:
  `7e9f52cf3c5600423c6abe63a7de6d8449db81bfcd7260585da5d8b59e22fdac`
- authority-aware mixed-script:
  `11c8a15e84c7c76154b60b047f9048468c93d60ee6c383b5b66dadd2c1066d1d`
- Stop Conditions:
  `a9af4766c7a5e80b5a8a69dfcd2c97b825d55d4d27889a9166b96b54ad63f027`

Final Review semantics are read from the current production path:
`quality-report.json` must have status `passed`, terminal review must be
complete, and `terminal_reviewed_hash` must equal the exact UTF-8 SHA-256 of
the formal manuscript. The production `QualityCheckpointV1` loader must also
accept the checkpoint, whose outcome is `passed` and both manuscript hashes
equal the formal manuscript hash.

Maintenance semantics are also read from the production path: at least one
Maintenance inventory or reduction must pass the current production Pydantic
contract, and the current `ProjectMutationJournalV1` must validate with status
`committed` and bind `manuscript/story.md` to the exact formal hash. Phase 1B
Candidate Lane is not required and remains disabled.

## ShortCompletionVerificationV1

The verifier is post-run and read-only. It records controlled identities,
hashes, contract versions, validation/binding statuses, and a typed completion
outcome. It does not retain manuscript, Prompt, provider response, tool
arguments, credentials, headers, project names, character names, or absolute
paths.

It distinguishes workflow outcome from completion outcome. A
`WORKFLOW_COMPLETED` run still exits non-success for this profile when the
completion result is review-not-accepted, review-binding-invalid,
Maintenance-incomplete, artifact-unbound, checkpoint-unclosed, or
verification-insufficient. Only the exact completion goal is success.

The runner wiring is implemented but was not exercised with a real workflow,
as explicitly prohibited. Therefore the SC-AUTH-1 runner result is
`NOT_EXECUTED`; its post-run verifier and exit mapping are covered by
deterministic tests.

## Approval and ledger contracts

- Candidate: `ShortCompletionFinalApprovalCandidateV1`
- Patch Template: `ShortCompletionUserAuthorizationPatchTemplateV1`
- Confirmed Patch fixture: `ShortCompletionUserAuthorizationPatchV1`
- Signed Approval fixture: `ShortCompletionSignedApprovalV1`

Candidate and Patch Template are inert and cannot execute or reserve. A
confirmed Patch can change only named approver, timestamp, window/expiry/cohort
confirmation, external-action authorization, and `execution_authorized`.
Protected policy, fingerprint, route, workload, budget, and completion fields
remain Candidate-bound. Tests prove a valid Signed fixture can reserve only
once and consume only with an Evidence Package hash; cross-profile cohort
reuse remains prevented by the shared cohort ledger.

No Signed Approval fixture was committed or included in the materialized
packet.

## Validate-only closure

`ShortCompletionApprovalClosureValidationV1` evaluates 36 ordered checks. The
final independent CLI run returned:

- overall status: `exact`
- approval state: `disabled_candidate`
- ledger state: `unused`
- validation receipt:
  `13e0e8fae78e8d5c2f10ed385382aa92041d9796d33fcf5ec881abdbe3c3b411`
- Credential lookup: 0
- Provider client creation: 0
- Network calls: 0
- Model calls: 0
- Paid model calls: 0

An initial CLI attempt was correctly blocked before provider because its empty
temporary ledger directory had not yet been created. Repeating with an
existing isolated empty ledger produced the exact result above. No contract
or policy was relaxed.

## Materialized identities

- Build: `a3134c453f37791580c98021bf9a42a59a084117216c08a2435ad3438261c25d`
- Execution Config:
  `6f047d7fac61794f704b92397addd00475980c3bafab0f21b3ccb8d4e72b2277`
- Runtime Execution:
  `c43ad3e4e58f95e8945982df4b6c089b42f8f9c72dc1dd2040ba018e21025cae`
- Launcher: `7cfd457d4c1e2cf3a4a33e906dfea618d852f0f979c13c8d002636c3e0ad89a5`
- Workload: `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1`
- Workload Manifest:
  `80a37d9270f7d0dc5f4260e391b0c53d4232c1abda4b859d8dbaf11a07a018ae`
- Plan: `64e121b26d241ce2571f3cbb9ed47e750f3fb22dad542863dce3c97c3bd9adec`
- Candidate:
  `e62b836c13f2de47309bbe1d6a2f9a1222e8b09a6317a7065238b359551fc479`
- Cohort: `short-completion-1-20260816t061700z`
- Window: `2026-08-16T06:32:00Z` through `2026-08-18T06:32:00Z`

Feature flags are exact:

- `NOVEL_SHORT_CANONICAL_V2=false`
- `project_short_canonical_v2=false`
- `NOVEL_CANONICAL_SHADOW_V1=false`
- `NOVEL_RELIABILITY_TRACE=true`
- `NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1=false`
- `NOVEL_STRICT_TOOL_SHAPE_TRACE_V1=false`

Budgets are exact:

- runs: 1
- expected calls: 16, based on the current deterministic nominal topology
- model calls: 48
- input/output tokens: 1,000,000 / 1,000,000
- output tokens per call: 32,000
- USD/CNY: 20.00 / 50.00
- elapsed: 7,200 seconds
- first terminal stop: true
- resume after terminal: false
- second run: false

## Compatibility, tests, and parity

- SC-AUTH-1 acceptance cases: 33 (32 new parameterized test cases plus the
  updated exact-registry characterization)
- focused Short Completion: passed
- C0B/PA compatibility cluster: `88 passed`
- final Canary suite: `217 passed, 1 skipped`
- strict L3 change gate: passed, zero warnings/blockers
- final full suite: `2764 passed, 2 skipped, 6 xfailed, 1 failed`

The one full-suite failure is pre-existing and unchanged:
`tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`
still expects the 2026-08-14 R0E database hash
`5deb7bdf...`, while the live database is `0fccb8ae...`. The database file's
last-write timestamp is `2026-08-15T00:41:47+08:00`, before SC-AUTH-1. Neither
the database nor that test is in this task's diff, and isolated reproduction
returns the same mismatch. No new failures were added.

The materializer's live parity hash is identical before and after:
`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
This covers the live database and project tree, including StoryState, Canon,
Candidate, Checkpoint, Saga, and formal artifacts. Production incident count
was not touched. Credential/provider/network/model/paid counts are all zero.

## Materialized files

- `short-completion-1-final-plan-v1.json`
- `short-completion-1-final-approval-candidate-v1.json`
- `short-completion-1-authorization-patch-template-v1.json`
- `short-completion-1-validate-only-receipt-v1.json`
- `short-completion-1-execution-preview-v1.json`
- `short-completion-1-definitions-v1.json`
- `short-completion-1-materialization-index-v1.json`

The index status is
`SHORT_COMPLETION_CANARY_WAITING_FOR_FINAL_USER_AUTHORIZATION`. Execution is
not authorized and was not performed.
