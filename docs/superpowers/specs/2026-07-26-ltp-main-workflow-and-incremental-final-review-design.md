# LTP Main Workflow and Incremental Final Review Design

## Goal

Integrate the already installed and enabled LTP backend into the authoritative writing workflow so deterministic local analysis does more work, while preserving the existing model roles, first full-manuscript final review, StoryState authority, candidate validation, and formal-write controls.

After the first complete final review, correction rounds review changed, adjacent, and causally related windows instead of automatically repeating every unchanged window. Any uncertainty or structural change falls back to the current complete final-review path.

## Confirmed Scope

This delivery includes all of the following:

| Area | Required behavior |
|---|---|
| Local rules | Scan the complete manuscript after draft generation, after every revision, and before publication. |
| LTP | Analyze manuscript structure, support revision-impact discovery, and produce originality candidates. |
| Editorial review | Continue using labeled excerpts, augmented by a complete-manuscript local summary. |
| Reader review | Preserve the current excerpt-based target-reader simulation. |
| Polish | Preserve segmented revision and record structured source-to-candidate changes. |
| First final review | Preserve complete-manuscript review and global adjudication. |
| Later final review | Review changed, adjacent, and related windows. |
| Global integrity | Combine the first-review baseline, LTP relations, StoryState, and a deterministic full-text gate. |
| Full-review fallback | Repeat complete review for structural, broad, uncertain, or failed impact analysis. |
| Token evidence | Record reviewed scope, selection reasons, cache use, model tokens, and estimated savings. |

No row in this table may be deferred to a later feature.

## Non-goals

- No new model role or provider protocol.
- No change to the user's existing role bindings or fallbacks.
- No vector database, external graph service, local generative model, or model training.
- No internet-wide plagiarism claim. Originality checks compare only project manuscripts, imported references, and locally available learning-library material.
- No automatic semantic rewrite by LTP.
- No direct write from a model or NLP worker to the formal manuscript.

## Existing Behavior Preserved

The following contracts remain authoritative:

- `planning` creates the story or chapter plan.
- `draft` creates prose from the approved plan.
- `review` performs excerpt-based editorial review.
- `reader_review` performs excerpt-based target-reader simulation when the enhanced route is selected.
- `polish` revises bounded prose segments.
- `final_review` performs independent quality judgment.
- `maintenance` extracts durable facts after quality acceptance.
- StoryState candidates, revision checks, snapshots, quality gates, and Runtime-controlled formal writes remain unchanged in authority.
- Provider primary/fallback behavior and Skill loading remain unchanged.

## Local Analysis Architecture

### One canonical manuscript analysis service

Add one workflow-facing analysis service that composes:

1. the existing deterministic prose diagnostics;
2. LTP output when enabled and available;
3. rule-only fallback when LTP is disabled, unavailable, times out, or returns invalid data;
4. originality candidate generation against local comparison sources;
5. a stable JSON artifact used by review, polish, final review, and publication checks.

This service must reuse `LocalNLPManager`; it must not create a second LTP lifecycle or cache.

### Analysis artifact

Each analysis records:

- manuscript SHA-256;
- analyzer and LTP versions;
- paragraph and review-window boundaries;
- deterministic prose findings and metrics;
- first-three-line and opening-zone findings;
- entities: people, places, organizations, and salient objects;
- action and semantic-role candidates;
- event, goal, conflict, anomaly, and scene-change candidates;
- timeline and causal-link candidates;
- question, promise, setup, and payoff candidates;
- repeated passages and similar-name candidates;
- setting, key-plot, and distinctive-expression originality candidates;
- degraded or failed components;
- cache keys and cache-hit state.

LTP output is evidence, not authoritative fact. StoryState remains authoritative.

### Full-text scan points

The complete manuscript is analyzed:

1. immediately after the draft is assembled;
2. after initial polish;
3. after every structural correction round;
4. before the candidate is accepted;
5. again before publication if the candidate hash differs from the last accepted analysis.

Identical text and analyzer versions reuse cached results.

## Review Roles and Input Scope

### `review`

`review` remains excerpt-based. It receives:

- the existing labeled opening, paid-region, climax, and ending excerpts;
- manuscript length;
- compact full-manuscript local metrics;
- event-density and scene-change summary;
- opening-zone signals;
- highest-priority local and LTP candidates with locations.

It does not receive the whole manuscript merely because LTP is enabled.

### `reader_review`

No behavior change. It continues to read labeled excerpts and simulate the target reader. It does not become a continuity checker.

### `polish`

`polish` continues to receive one segment, adjacent context, StoryState facts, the compact story map, and relevant findings.

For every segment attempt, record:

- source and candidate hashes;
- original and resulting character ranges;
- length delta;
- changed entities;
- changed action/event candidates;
- changed time, causal, question, setup, and payoff candidates;
- applicable revision-plan task and deterministic checks;
- accepted, retried, or preserved status.

This record describes impact; it does not authorize a formal write.

### First `final_review`

The first final review remains unchanged in coverage:

- manuscripts at or below the existing single-request threshold are reviewed in one complete request;
- longer short manuscripts use all paragraph-aligned overlapping review windows;
- a final adjudication reconciles the ordered evidence and every prior issue.

The result becomes the immutable baseline for the current manuscript revision.

The baseline contains:

- manuscript and window hashes;
- ordered window summaries and structured evidence;
- character states and knowledge;
- timeline and causal relations;
- relationship transitions;
- setup, promise, question, and payoff relations;
- issue ledger and reconciliations;
- coverage and provider receipts.

## Incremental Final Review

### Change detection

After a correction, compare the accepted first-review baseline text with the corrected candidate. Rebuild review windows for the candidate and map old to new windows using:

1. unchanged content hashes;
2. paragraph anchors;
3. character-range overlap;
4. entity and event overlap.

A mapping that cannot be established conservatively triggers complete review.

### Required incremental scope

The next final-review call set contains:

- every changed window;
- the immediate previous and next window;
- windows sharing changed people, places, organizations, or salient objects;
- cause and consequence windows for changed events;
- setup and payoff windows for changed promises or questions;
- windows affected by changed character knowledge or timeline candidates;
- protected opening, climax, and ending windows when their promises or consequences are implicated.

Every selected window records one or more machine-readable selection reasons.

### Incremental adjudication

The existing `final_review` role receives:

- the first full-review baseline;
- the prior issue ledger;
- local and LTP change evidence;
- selected current windows;
- related unchanged baseline evidence;
- deterministic gate failures, if any.

It must reconcile every prior issue and report new issues. Omission never means resolved.

Incremental adjudication cannot raise confidence above the evidence it received. If it reports insufficient context or cross-window uncertainty, the workflow repeats complete review.

## Mandatory Complete-review Triggers

Repeat complete-manuscript final review when any condition is true:

- changed characters exceed 20% of the manuscript;
- selected or affected windows exceed 40% of all windows;
- scene or event order changes;
- a principal character's goal, motivation, identity, knowledge boundary, or ending changes;
- a principal character or key event is added or removed;
- a major reversal, setup, promise, payoff, climax, opening promise, or ending changes;
- timeline or causal relations change across windows;
- deterministic or LTP analysis fails, degrades unexpectedly, or produces invalid evidence;
- old-to-new window mapping is incomplete or ambiguous;
- the local gate finds a new blocking issue;
- the incremental final reviewer requests broader evidence;
- any required baseline or receipt is missing.

These thresholds are fixed in the first delivery and are not exposed as user settings.

## Originality Candidate Screening

The local comparison corpus consists only of:

- the current project's earlier drafts and formal manuscript;
- imported reference sources;
- locally stored learning-library text selected for the project.

Local rules produce:

- exact and near-exact continuous-passage candidates;
- similar-name candidates.

LTP assists candidate retrieval for:

- setting similarity;
- key-plot similarity;
- distinctive-expression similarity.

These are candidates, not infringement judgments. Only high-risk candidates that cannot be resolved deterministically are included in the existing final-review evidence. No new originality model role is introduced.

## Deterministic Global Gate

Before accepting an incrementally reviewed candidate, the workflow verifies the complete text:

- manuscript hash matches the analyzed candidate;
- no blocking prose contamination is present;
- all revision-plan required/forbidden checks pass;
- every changed range belongs to a recorded polish attempt;
- all prior issues are reconciled;
- baseline and selected-window coverage are complete;
- no changed entity, event, timeline, causal, setup, or payoff candidate lacks either related-window review or a full-review fallback;
- StoryState locked and confirmed facts remain present where required.

Failure preserves the best candidate and prevents formal commit.

## Publication Gate

Publication reuses the latest complete analysis only when its manuscript hash and analyzer versions match the candidate. Otherwise it runs the full local analysis again.

Publication remains blocked by existing blocking prose findings and by any new unresolved global-gate failure. It does not independently invoke a paid model unless the candidate changed after the accepted terminal review.

## Failure and Recovery

- LTP absence or failure never blocks rule-only drafting or reference analysis, but it disables incremental approval and forces complete final review for that correction.
- Provider failure preserves the best candidate and reports `final_review_incomplete`.
- Invalid incremental evidence falls back to complete review; it is never treated as approval.
- Checkpoints are keyed by manuscript, window, analyzer, prompt-contract, role binding, and model identity hashes.
- Resume reuses only matching successful checkpoints.
- Existing formal manuscripts, StoryState, role bindings, run history, reference sources, and credentials are never migrated destructively.

## Token and Scope Accounting

Each quality report records:

- first full-review input/output tokens;
- correction-round selected windows;
- selection reasons;
- complete and reviewed window counts;
- LTP and local-analysis cache hits;
- incremental-review input/output tokens;
- estimated equivalent full-review input;
- estimated saved input tokens;
- whether a full-review fallback occurred and why.

Token savings are reported as evidence, not guaranteed in advance. The first final review is never reduced.

## User-visible Reporting

The console should distinguish:

- local full scan complete;
- LTP analysis complete or degraded;
- first complete final review;
- incremental related-window review;
- mandatory complete-review fallback;
- model/provider failure;
- deterministic rejection;
- quality failure;
- successful candidate and formal commit.

The quality view shows coverage, reviewed windows, related-window reasons, unresolved issues, fallback reason, and estimated token savings.

## Compatibility and Rollback

The optimized path is project-scoped and reversible. Existing projects retain the current path until enabled or migrated through an idempotent setting update. Disabling it:

- keeps all analysis artifacts and history;
- restores the current complete-final-review behavior;
- does not change role bindings or delete LTP caches;
- does not alter formal manuscripts or StoryState.

Until comparative tests pass, the existing complete-review method remains the tested fallback.

## Acceptance Criteria

1. Draft, every correction, and publication execute or reuse a hash-matching complete local scan.
2. Enabled LTP is invoked from the manuscript workflow and cached by text and version.
3. Disabled or failed LTP produces explicit degraded evidence and complete-review fallback.
4. `review` remains excerpt-based and receives a bounded full-manuscript local summary.
5. `reader_review` input behavior remains unchanged.
6. Every polish attempt produces a structured diff and acceptance record.
7. The first final review covers 100% of the manuscript using the existing role.
8. A small prose-only correction reviews changed, adjacent, and related windows without calling every unchanged window.
9. Structural, broad, ambiguous, or failed analysis repeats the complete final review.
10. Incremental approval cannot occur with missing issue reconciliation, missing related evidence, stale hashes, or failed deterministic checks.
11. Originality screening reports only local-corpus candidates and never claims internet-wide clearance.
12. Quality reports expose scope, cache, token, savings, and fallback evidence.
13. No role binding, credential, formal manuscript, StoryState, Skill behavior, or run history is lost.
14. Focused workflow, NLP, quality, revision, candidate, migration, and API tests pass, followed by the complete test suite.

