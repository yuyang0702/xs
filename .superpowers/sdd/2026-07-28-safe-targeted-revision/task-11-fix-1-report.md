# Task 11 Fix Round 1 Report

## Scope

Closed the targeted review findings without changing the Task 11 API contract or adding a new state authority:

- serialized protected-quality selection and promotion with one process lock;
- persisted a run-scoped promotion journal and recovered hard stops idempotently;
- made promotion recovery share the promotion lock so it cannot consume an active journal;
- replaced the per-run decision-lock registry with one bounded process lock;
- projected nested revision group records through explicit public allowlists;
- returned a fixed Chinese validation error for revision payloads only;
- hid raw exceptions from background `short-revision` task failures;
- allowed interrupted runs to resume and returned an already recovered completed run directly.

No real provider or paid model API was called.

## Recovery And Concurrency

`revision-promotion-<run_id>` snapshots cover the candidate, repair checkpoint, repair report, and quality checkpoint. The hash-validated quality checkpoint bound to `outputs/candidate.md` is the commit marker. Recovery restores and discards an incomplete journal, or completes a marker-backed promotion without rerunning review.

Ordinary quality checkpoint writes, targeted promotion, and promotion recovery use the same process lock. The finalize commit reselects the current protected checkpoint inside that lock before comparison. Recovery is not called from either lock-owning commit path, so the existing non-reentrant lock does not introduce recursive acquisition.

A focused RED test held the promotion lock around a journal-created, marker-absent intermediate state. Before the fix, recovery completed early and consumed the active journal. After recovery entered the shared lock, the promotion/recovery group passed all seven cases.

## Safety Boundaries

The public revision summary retains the existing top-level contract while nested issue, failure, position, and local-check objects are allowlisted by field and type. Revision request validation is matched by the resolved FastAPI route template, so unrelated `422` responses keep FastAPI's normal structured detail. Background short-revision task failures store only the fixed recoverable Chinese message and event code.

Snapshots validate that their manifest and files remain inside the project, require exact boolean existence markers, and verify copied-file hashes before recovery. Prior protected best text, formal manuscript, StoryState, and passage locks remain outside the promotion write set.

## Verification

- Initial storage/tasks/runs/app group: `22 passed, 1 warning in 19.57s`.
- Initial workflow/quality/revision group: `299 passed, 1 warning in 918.99s`.
- Recovery-lock RED: `1 failed, 52 deselected`; recovery completed while the promotion lock was held.
- Promotion/recovery GREEN: `7 passed, 46 deselected, 1 warning in 10.62s`.
- Complete revisions API after the fix: `53 passed, 1 warning in 88.91s`.
- Final storage/tasks/runs/app group: `22 passed, 1 warning in 11.49s`.
- Repository suite: `865 passed, 1 skipped, 1 warning in 667.40s`.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed; only repository line-ending conversion notices were emitted.

The skip is the existing Windows symbolic-link capability case. The warning is the existing Starlette `httpx` test-client deprecation warning.
