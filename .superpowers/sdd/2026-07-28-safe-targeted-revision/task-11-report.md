# Task 11 Report: Revision API, Decisions, Finalization, and Resume

## Scope

Implemented the Task 11 operational surface:

- `POST /api/projects/{project_id}/revisions`
- `GET /api/runs/{run_id}/revision`
- group `adopt` and `reject` endpoints with exact candidate-hash binding
- `POST /api/runs/{run_id}/revision/finalize`
- same-run `short-revision` resume through the existing run task manager

The router delegates authority checks to `RevisionOperations` and the existing
`WorkflowService`. No second workflow, model role, state store, or formal-manuscript write path was
added. Automated verification used only fakes and monkeypatches; no real or paid model API was
called.

## Persisted Contract

The existing five repair artifacts remain authoritative for the run:

- `repair-contract.json`
- `patch-groups.json`
- `repair-checkpoint.json`
- `candidate.md`
- `repair-report.json`

User decisions persist as `decision` and `decision_candidate_hash` in the matching patch-group
record. A rejected group also persists `issue_status=unresolved`. The repair checkpoint continues
to bind contract, groups, source, and candidate hashes. The public read endpoint returns only safe
status, gate, review-mode, fallback, next-action, and group-summary fields; it does not expose raw
provider errors or internal prompts.

## Finalization Safety

Finalization reconstructs the exact candidate from the frozen source plus adopted groups, leaves
rejected issues unresolved, reruns the whole-candidate gate, then uses the existing incremental/full
review router and strict quality comparison. Promotion requires the same profile and judge, at
least two score points of improvement, no dimension regression beyond three points, no new
unresolved major issue, and no unresolved mandatory issue.

The run is atomically claimed with the existing `running` status, so it remains covered by active
run, interruption, maintenance, and restart behavior. Duplicate or concurrent finalize requests
cannot both review. After the awaited review returns, Runtime reloads and rechecks the protected
run/hash, StoryState revision, locks, contract hash, groups hash, candidate hash, and decisions
before quality comparison or checkpoint writes. A later lower-scoring checkpoint cannot displace
the highest-scoring valid protected checkpoint.

Unexpected analysis, constraints, review, or checkpoint-write failure preserves decisions and
leaves the same run retryable. Project snapshots roll back partial repair/quality artifact writes.
Tests verify that the prior protected best, formal manuscript, StoryState, and locks remain
unchanged.

Group decision read-modify-write is serialized by a per-run process lock. This is the smallest
compatible fix for concurrent API threads; SQLite run-status compare-and-set remains responsible
for finalize ownership.

## Focused Verification

- Known stale `decision_candidate_hash` regression: `1 passed`
- Complete revision API file: `40 passed, 1 warning in 16.83s`
- Brief API revision selection: `41 passed, 9 deselected, 1 warning in 17.58s`
- Workflow, incremental review, quality, storage, StoryState, passage protection, tasks, repair
  records/gate, and revision compatibility: `388 passed in 652.85s`
- Complete run API file after fixture correction: `8 passed, 1 warning in 9.40s`

The existing warning is Starlette's `httpx` test-client deprecation warning.

Coverage includes incremental routing, full and uncertainty fallback, same-run review retry,
strict quality rejection, duplicate/concurrent finalize, concurrent decisions, checkpoint-write
rollback, protected/formal/StoryState/lock preservation, and source/candidate/decision/StoryState/
lock staleness before model review and after the awaited review.

## Full-Suite Correction

The first repository-wide run produced:

```text
4 failed, 848 passed, 1 skipped, 1 warning in 1151.43s
```

All four failures were old `tests/api/test_runs.py` fixtures that registered `tmp_path/book` while
constructing `ProjectStore` with the default workspace or `tmp_path/workspace`. The Task 10 full
suite baseline of 806 tests preceded its later containment fixes; those review rounds ran only
their related suites. Task 11 changed neither `ProjectStore` nor `create_app` construction beyond
router registration.

Production containment was retained unchanged, including tests for registered paths and symlink/
junction targets outside the workspace. The four run-API fixtures now register `workspace/book`
and pass that explicit workspace root.

## Final Verification

```text
852 passed, 1 skipped, 1 warning in 709.65s
```

The skip is the existing Windows symbolic-link capability case. `compileall` passed.
`git diff --check` passed with only the repository's LF-to-CRLF conversion notices.

## Minimality Review

The implementation reuses the existing candidate replay, whole-candidate gate, local analysis,
incremental/full terminal review, quality comparison, quality checkpoint writer, run task manager,
database status claim, and `ProjectSnapshot`. The existing quality checkpoint helper that also
writes `best-candidate.md` was intentionally not reused because Task 11 promotion is
checkpoint-only. Moving the finalize state machine into another module would add parameter and
authority plumbing without removing behavior, so it remains in `WorkflowService`.
