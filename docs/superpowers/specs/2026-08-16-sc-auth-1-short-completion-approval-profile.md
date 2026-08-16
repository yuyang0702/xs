# SC-AUTH-1 Short Completion Approval Profile

## Change contract

SC-AUTH-1 adds a third closed-world Canary approval profile,
`short_completion_1`, and a hash-only post-run verifier. It changes only
Canary registration, approval contracts, validate-only closure, the existing
Production-Mirror Short runner's post-run observation, tests, and audit
materialization.

It does not change the Short workflow, Prompt, routes, retry/fallback,
Planning Adaptation, Draft validation, Final Review, Maintenance, StoryState,
Canon, or Phase 1B. The rollback unit is the SC-AUTH-1 commit set.

## Registered scope

- Profile: `short_completion_1`
- Scope: `SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY`
- Mode: `short_completion`
- Workload: sanitized `short-normal-v1`
- Maximum runs: 1
- Maximum paid/model calls: 48
- Maximum input/output tokens: 1,000,000 / 1,000,000
- Maximum output tokens per call: 32,000
- Maximum USD/CNY: 20.00 / 50.00
- Maximum elapsed time: 7,200 seconds
- Resume and second run: disabled

The registry remains finite. Unknown profile, mode, scope, or schema fails
closed. Candidate and authorization patch documents are not executable. Only
a profile-specific Signed Approval may reserve and consume a cohort.

## Completion contract

`SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED` requires all of:

1. workflow status `completed`;
2. non-empty formal `manuscript/story.md`;
3. final Draft/prose integrity status `passed` for the exact publication;
4. production quality report status `passed`, terminal review complete, and
   terminal reviewed hash equal to the formal manuscript hash;
5. a loadable production `quality-checkpoint.json` with outcome `passed` and
   both manuscript hashes equal to the formal manuscript hash;
6. at least one valid production Maintenance inventory/reduction receipt;
7. committed Project Mutation Journal binding the formal artifact;
8. no unresolved terminal outcome; and
9. exact live isolation parity.

The verifier records hashes, versions, status codes, and controlled aliases
only. It never records manuscript, Prompt, provider response, credentials,
headers, project names, character names, or absolute paths.

## Product semantics used as read-only authority

- Final Review acceptance is the existing `quality-report.json` status
  `passed` plus `terminal_review_complete=true` and exact
  `terminal_reviewed_hash` binding.
- Checkpoint closure is the existing `QualityCheckpointV1` loader contract
  (`CHECKPOINT_VERSION=1`) and exact manuscript hash binding.
- Maintenance completion is the existing Short Maintenance inventory or
  sealed reduction, followed by the existing committed
  `ProjectMutationJournalV1` transaction.
- Phase 1B remains false and is not a completion prerequisite.

## Stop and failure semantics

The profile owns an independent, hash-bound stop manifest covering terminal,
fingerprint/source/route/protocol/budget/approval/cohort/isolation/Phase 1B,
Prompt/pricing/policy/Final Review/Maintenance/artifact/checkpoint/root-cause
failures. Existing C0B and PA manifests are unchanged.

The runner exposes two independent outcomes:

- `workflow_final_outcome`
- `short_completion_goal_outcome`

Only the exact completion goal is Canary success. A completed workflow with a
stale review, incomplete Maintenance, unbound artifact, or unclosed checkpoint
is not success.

## Materialization boundary

SC-AUTH-1 may materialize only a Plan, inert Candidate, inert Patch Template,
validate-only receipt, execution preview, and index. It must not create a real
Signed Approval, query credentials, create a provider client, access the
network, call a model, or run the workflow.
