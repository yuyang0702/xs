# Production Incident Memory Design

Date: 2026-08-04

## Goal

Prevent the console and its maintainers from treating recurring production failures as unrelated new defects merely because a novel name, path, segment number, provider message, or count changed. Preserve the existing run history as the only authoritative operational record and do not create a second workflow state store.

## Authority and storage

Terminal failures remain ordinary `run_events`. New events add compatible metadata: stable incident key, root-cause family, title, known recovery path, same-key occurrence count, cross-stage family count, and first/last-seen timestamps. Existing databases require no migration. When the aggregation API encounters an older terminal event without metadata, it classifies that event in memory from its workflow, stage, and message. If an older failed run has no unified terminal event, aggregation derives one read-only occurrence from the stored run error and latest error-stage event. Neither compatibility path rewrites historical rows.

The incident catalog is code-owned diagnostic policy, not story authority. It may identify the recovery implementation that owns a failure, but it cannot mutate project materials, StoryState, candidates, plans, drafts, or manuscripts. Automatic recovery remains inside the applicable initialization, planning, drafting, polish, revision, review, or promotion boundary and must pass that boundary's existing validation closure.

## Stable classification

Known production families use explicit matchers for previously observed root causes. Unknown failures are fingerprinted only after Unicode NFKC normalization and removal of volatile run IDs, absolute paths, segment numbers, and bounded count values. Workflow and stage remain part of the incident key so operationally distinct boundaries stay separate; `incident_family` and `family_occurrence_count` expose recurrence across boundaries. Materially different unknown messages retain different hashes.

Every newly discovered family must add:

- one catalog entry with a concrete recovery path;
- a minimal or production-shaped fixture;
- a successful recovery test that crosses the next authoritative boundary;
- a no-regression test for previously registered hard incidents;
- documentation of retained authority, retry/fallback scope, and terminal behavior.

The first post-catalog capacity family is `model.context_capacity_preflight`, based on production run `dd0d6d2d981b4316a0c81d901bd38dc1`. It covers a request that was correctly identified as requiring `topology=split` but was previously stopped before the semantic split topology ran. The retained authority is the complete accepted plan and pending adaptation-review checkpoint. Recovery recursively divides only contiguous formal-event ownership inside the affected segment, persists hash-bound packet receipts, merges all events in original order, and must pass the original full-segment validator plus whole-plan review.

`model.context_capacity_indivisible_scope`, based on production run `e86225d9d6664243b4d8c4e45295144f`, is deliberately separate. In that failure, reducing seven events to one removed almost none of the prompt because the complete parent plan and global Story Skeleton were repeated. Recovery transports only the exact event-owned plan blocks, binds them to the unchanged parent evidence IDs and hashes, splits the event's validation into complete invariant facets, and uses hash-bound overlapping evidence windows when a facet still exceeds capacity. Closed JSON receipts use a protocol-sized output reserve rather than a creative Review-stage floor. The merged result must re-enter parent-segment and whole-plan validation before downstream work. No event is split into invented story ownership, and no formal or narrative authority is truncated.

Run `d785dd5c711c4bc785caec10977cf6bb` remains in the generic `model.context_capacity_preflight` family because the root cause is a missing execution contract at a later planning-repair boundary, not an indivisible event. Earlier adaptation review packets completed, then a closed JSON evidence patch inherited the full planning stage's 12,288-token creative reserve. The repair boundary now declares either a bounded protocol-output contract for exact-anchor JSON patches or a scope-aware creative contract for one complete formal-segment rebuild. Primary and configured fallback routes are both sized under that declaration. A remaining preflight, truncated output, malformed candidate, or transport failure is recorded as a rejected recovery candidate while the prior best plan and full issue ledger stay intact; only a locally, adjacently, and globally revalidated plan may continue to causal-chain generation.

Historical rows that already contain the older generic preflight metadata remain immutable. When their original terminal message proves the more specific singleton condition, aggregation refines the in-memory family, title, incident key, and known resolution. Counts, timestamps, run history, and stored metadata are not rewritten.

## Runtime behavior

`RunTaskManager` classifies the raw exception before any workflow-specific user-facing redaction. The direct short-revision finalization boundary uses the same recorder because it is not dispatched as a background task. The database records recurrence metadata and, when history exists, emits `production_incident_recognized` before the normal terminal failure. Short-revision errors therefore remain safely summarized to the user while preserving a useful incident family without storing the raw exception in new metadata.

`GET /api/projects/{project_id}/production-incidents` returns aggregated project occurrences and the registered known-family catalog. Repeated terminal events increment counts; unrelated families remain separate; legacy events remain readable. Recognition alone never changes a failed run to completed and is never described as resolution.

## Team-review control

Development team review is explicitly opt-in. No product, novel-business, technical, test, or other review subagent may be created unless the user explicitly requests **团队评审** for the current task. Risk level still controls regression depth, rollback design, and full-suite requirements, but it does not broaden collaboration authorization. A single-agent clean-room diff review is the default final inspection.
