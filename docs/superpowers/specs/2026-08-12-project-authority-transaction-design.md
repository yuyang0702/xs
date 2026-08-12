# Project Authority Transaction Design

## Purpose

Project mutations sometimes span ordinary files, a material-impact record,
and the SQLite-backed `StoryState`. A file snapshot alone cannot roll back a
database commit, and a database transaction cannot atomically replace project
files. This design introduces one reusable Saga boundary for those mixed
authority writes without changing their novel-business rules.

## Protected business behavior

- Proposal selection, exact old-text matching, target-hash checks, and material
  replacement order remain owned by `MaterialImpactService.prepare_apply`.
- Material-to-StoryState projection remains owned by `_synced_material_state`.
- Narrative graph validation and optimistic StoryState revision checks remain
  owned by `StoryStateStore.commit`.
- No model output, prose, planning, canon, quality, or formal-promotion rule is
  added, removed, weakened, or reinterpreted by this transaction layer.

The migration order is `wrap -> parity -> switch -> delete`. A business path
is not switched until all of its side effects can be replayed idempotently.
Learning invalidation is therefore a typed, exact row ledger rather than a
best-effort loop, and material-impact creation is a staged target artifact
rather than an untracked post-commit write.

## State machine

`ProjectMutationJournalV1` is a versioned, Pydantic-validated journal:

1. `prepared` binds the project, operation, source authority, expected
   StoryState revision, managed paths, and rollback snapshot.
2. `artifacts_committed` binds exact target bytes, staged target copies, the
   optional candidate StoryState transition, and exact learning-artifact
   invalidation effects.
3. `committed` proves the target files and optional StoryState revision are
   both authoritative. The run row may still need idempotent finalization.
4. `rolled_back` proves the mutation never crossed the durable artifact commit
   point and the old file set was restored.

A journal may declare one hash-bound post-commit business gate. In that case
`committed` deliberately leaves the run and rollback snapshot open. The domain
owner must persist and validate a project-relative receipt, bind its exact bytes
and passed/blocked status into the journal, and only then call the generic
finalizer. The transaction kernel never interprets or fabricates a quality
decision, and it refuses an absent, pending, blocked, or tampered gate receipt.

Normal execution and startup recovery call the same completion function.
Recovery may roll forward only when a file contains either its snapshotted old
hash or its journal-bound target hash. A third hash is treated as an unknown
concurrent edit and is never overwritten.

## Failure behavior

- Failure before `artifacts_committed`: restore the complete snapshot, reject
  pending StoryState candidates owned by the operation, and fail the run.
- Interruption after `artifacts_committed`: retain target copies and finish the
  exact StoryState transition during normal or startup recovery.
- Failure after StoryState commit but before the terminal run update: retain
  the committed business authority and retry only terminal bookkeeping.
- Corrupt target copy, stale StoryState, or an unknown third file hash: stop
  without guessing or overwriting unrelated authority.

## Current rollout

The switched consumers are material-impact application, manual material edit,
formal outline application, the material-audit report plus issue-ledger
commit, and long-form book setup files plus Canon-memory facts. All five use
the same Saga completion and startup recovery path. Their
business validators and response projections stay in their domain services;
only commit/recovery ownership is shared.

## Convergence inventory

| Business boundary | Current authority mechanism | Rollout decision |
|---|---|---|
| Material-impact application | `ProjectMutationJournalV1` | Switched after parity and restart tests. |
| Manual material editing | `ProjectMutationJournalV1` plus exact learning invalidation ledger and staged material-impact artifact | Switched after API parity, pre-commit rollback, and post-commit restart tests. |
| Formal outline application | `ProjectMutationJournalV1` plus exact latest-derived-artifact invalidation ledger | Switched after existing outline behavior and fault-recovery tests. |
| Material audit report and issue ledger | `ProjectMutationJournalV1` over one exact report artifact and the unchanged incremental issue-ledger projection | Switched after business-parity, pre-write rollback, and post-stage restart tests. |
| Long-form book setup | `ProjectMutationJournalV1` over book-plan/Canon/optional volume files plus idempotent Canon-memory effects | Switched after normal-output parity and post-stage restart tests. |
| Long-form chapter publication | `ProjectMutationJournalV1` plus a hash-bound post-commit gate | Switched after pre-publication rollback, blocked-volume preservation, and artifact-stage resume tests. The existing volume audit remains the sole business finalizer. |
| API candidate publication | Existing candidate-publication journal and snapshot | Preserve while the generic Saga runs in parity; migrate only after artifact and startup-recovery equivalence. |
| Short-story formal promotion | Existing hash-bound formal-promotion journal and StoryState CAS | Preserve as protected formal authority; it is the final migration target, not an experimental consumer. |
| Style sample analysis/deletion | Common file-only snapshot transaction | Already converged for file-only mutations; no StoryState transition is involved. |
| Learning artifact sidecars | SQLite authority plus typed invalidation plan and monotonic sidecar projection | Shared by material and outline flows; sidecar remains a readable projection, never a second authority. |

The convergence budget permits one generic mixed-authority state machine and
temporary compatibility wrappers. It does not permit new feature-specific
rollback loops. Existing dedicated publication journals are deleted only after
the generic state machine proves byte, revision, recovery, and UI-status parity
on the protected complete-flow gates.

## Verification

Offline tests cover normal business parity, pre-commit rollback, interruption
after target staging, restart completion, terminal database-write failure,
exact byte replay, staged-target corruption, and unknown concurrent edits.
The full repository suite and the current-project plus 13K/20K/30K acceptance
matrix remain required before the old paths can be removed or the project-level
refactor can be called complete.
