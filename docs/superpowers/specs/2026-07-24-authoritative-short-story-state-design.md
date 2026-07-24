# Authoritative Short-Story State Design

## Goal

Prevent cross-model conflicts, manuscript corruption, plot drift, and repeated full-text token growth while preserving every existing project, model binding, Skill, run, and manuscript.

## Source of truth

Each project owns one versioned `StoryState` in SQLite. It contains locked and confirmed facts, world rules, character states, timeline events, unresolved issues, manuscript revision, and candidate registry metadata. Models never update it directly.

Every generation starts from a state revision. Models produce a candidate manuscript and proposed state changes. Runtime validates them and commits the candidate, state, and audit record in one transaction only when the base revision is still current. A stale task is rejected instead of overwriting newer work.

## Short-story flow

1. Ensure or migrate the project's StoryState from existing `canon.json` and manuscript files.
2. Build role-specific context from state, the relevant Skill prompt, and the current text slice.
3. Store draft and polish outputs as candidates, never as the formal manuscript.
4. Give polish calls a story map, immutable facts, segment role, adjacent boundaries, and explicit edit permissions.
5. Validate length, required locked facts, boundary continuity, and deterministic revision checks.
6. Allow at most two targeted structural repair rounds.
7. Atomically promote the accepted candidate and new state; keep rejected and best candidates for diagnosis.

## Token policy

Skills remain stage-bound and compacted. Review reports are compact structured issue lists. Polish receives one segment plus adjacent boundaries and compact story context, not the full manuscript. Claude primary polish uses 8,192 on its first request because observed relay responses repeatedly exhausted dynamic limits without visible prose; other polish routes remain dynamically sized. Final review uses 8,192 to keep structured JSON complete. Long-story retrieval remains on SQLite FTS in this phase.

## Migration and safety

Migration is additive and idempotent. Existing canon facts and current manuscript become revision 1 without rewriting project files. Uncertain imported data is `provisional`; existing confirmed canon facts remain `confirmed`. Every commit writes a history row and change audit. Failure leaves the current formal manuscript and StoryState unchanged.

## Observability

Run events identify state revision, candidate id, actual role/model route, token counts, validation result, rejection reason, and final promoted revision. Model failure, Runtime rejection, and editorial failure remain distinct statuses.

## Non-goals

No LangGraph migration, vector database, model-to-model chat memory, new provider protocol, or long-story workflow rewrite in this phase.
