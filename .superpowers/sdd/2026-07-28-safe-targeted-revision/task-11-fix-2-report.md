# Task 11 Fix Round 2 Report

## Scope

Closed the remaining atomicity, recovery, event-safety, and resume-scope findings without changing revision payloads or adding a state store:

- moved the single quality writer lock to `quality_records.py` as `QUALITY_CHECKPOINT_LOCK`, a process-wide `threading.RLock`;
- locked direct checkpoint writes and the complete legacy reconciliation cycle;
- kept targeted reselection, comparison, journal mutation, and marker creation under that same lock;
- made snapshot manifests atomic and discard idempotent and best-effort;
- made a valid marker authoritative before any journal parsing;
- treated an invalid marker-less journal as interrupted snapshot creation before production mutation;
- replaced every unexpected short-revision pipeline error and event with one fixed Chinese message;
- limited interrupted-run resume to a hash-validated short-revision opt-in.

No real provider or paid model API was called.

## Atomicity And Recovery

Ordinary quality save writes `best-candidate.md` and its marker while holding `QUALITY_CHECKPOINT_LOCK`. Legacy reconciliation holds the same lock from the first existing-marker read through candidate selection and marker write. Targeted promotion holds it while reloading protected authority, comparing quality, creating the journal, changing repair artifacts, and writing the commit marker. The reentrant lock is required only because reconciliation calls the public locked writer.

The snapshot manifest now uses the existing fsync-and-replace `atomic_write`. A valid targeted quality marker is commit authority even if the journal manifest is missing or corrupt: recovery first projects the completed run and event, then discards the journal without loading it. Without a marker, an invalid journal is discarded as partial snapshot creation and repair artifacts remain untouched. Discard tolerates missing paths and deletion failures.

## Safety And Resume Scope

The pipeline-level unexpected-error handler no longer inspects `str(exc)`. It stores and emits only `定向返修未完成，已保留可恢复的检查点`, so Chinese provider text, paths, prompts, and local exception details cannot enter run events. The task-manager layer retains its separate fixed revision failure summary.

`RunTaskManager.resume()` defaults to failed or cancelled runs. Its `allow_interrupted` flag is passed only by the short-revision API after contract, hash, protected-source, StoryState, lock, and promotion-journal validation. Short-story and materials resume behavior remains unchanged.

## RED And GREEN Evidence

- Storage/task RED: `4 failed, 12 deselected`; atomic manifest, idempotent discard, default interrupted rejection, and opt-in support were absent.
- API/recovery RED: `5 failed, 61 deselected`; raw pipeline event text leaked, invalid journals blocked marker authority, partial creation raised, and generic interrupted resume returned 202.
- Shared reconcile RED: `1 failed, 57 deselected`; targeted promotion was not rejected after a higher legacy checkpoint won authority.
- Combined focused GREEN: `12 passed, 71 deselected`.
- Expanded focused GREEN including discard hard-stop and interrupted revision: `15 passed, 70 deselected`.
- Complete revisions API: `60 passed, 1 warning in 32.09s`.
- Storage/tasks/runs/app/quality-records: `31 passed, 1 warning in 8.12s`.
- Repository suite: `877 passed, 1 skipped, 1 warning in 431.53s`.

The skip is the existing Windows symbolic-link capability case. The warning is the existing Starlette `httpx` test-client deprecation warning.
