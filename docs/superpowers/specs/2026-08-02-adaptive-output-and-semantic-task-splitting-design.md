# Adaptive Output, Semantic Recovery, and Cross-Story Continuity Design

## Goal

Prevent provider limits, network interruptions, normal-but-incomplete model responses, and heuristic continuity false positives from corrupting story authority. A user-visible run may contain multiple internal semantic subtasks; they remain checkpoints inside the existing workflow, not independent product tasks or a second outline/state system.

The implementation must preserve whole-story causality, character and knowledge state, timeline order, relationship progression, setup/payoff coverage, target ending, and accepted prose. No incomplete or ambiguous artifact may become downstream authority.

## Non-goals and compatibility constraints

- Do not lower prose or schema gates merely to keep a run moving.
- Do not treat `max_tokens` as a quality target or spending limit.
- Do not split text at arbitrary character offsets when a narrative boundary exists.
- Do not hard-code one novel, historical-fiction location suffixes, or a fixed genre vocabulary.
- Do not create a second scheduler, StoryState, outline, or authoritative database.
- Do not rewrite existing project files, completed runs, or accepted checkpoints during migration.
- Automated tests must use fake adapters and must not call paid model APIs.

## Route identity and observations

The additive `model_output_observations` table stores provider ID, model ID, a secret-free route fingerprint, execution mode, requested allowance, actual output tokens when reported, visible characters, normalized finish reason, transport completion, and timestamp. The fingerprint covers protocol, base URL, auth type, extra-header names, model capabilities, and execution mode; it never stores keys or header values.

Migration is additive and idempotent. A normal terminal response proves only an observed lower bound. Repeated token-limited responses may establish a conservative suspected route ceiling. Transport failures and normal-but-short responses never lower the inferred physical ceiling.

## Unified result classification

Every model call is classified independently along three axes:

1. Transport: complete, interrupted, timeout, provider disconnect, or safety rejection.
2. Terminal reason: normal, output limit, incomplete tool protocol, invalid terminal state, or unknown.
3. Artifact validity: complete, repairable, recoverable partial, or invalid.

Artifact validators return stable issue codes and structured evidence rather than requiring callers to parse Chinese messages. Initial issue codes include underlength, overlength, missing or reordered events, duplicate prose, event-boundary escape, invalid format, commentary/meta prose, corrupted text, explicit continuity contradiction, and uncertain continuity.

A normal provider finish never proves semantic completeness. Normal-underlength recovery requires explicit terminal evidence (`stop`, `end_turn`, or `completed`); missing terminal metadata remains unknown instead of being guessed normal. A token-limit finish is risk evidence, not automatic failure or success. Only an artifact-specific validator may promote output into authority.

## Dynamic allowance and transport recovery

Existing per-stage allowances remain baselines. Expected artifact size adds headroom, bounded only by a declared provider output ceiling or remaining context. Unknown routes use a conservative discovery guardrail learned from real work, without paid probe calls.

- Transport interruption: retry the same route once, then use the configured fallback; do not change capacity observations.
- First incomplete output-limit result: retry the same actual route with more allowance.
- Second incomplete output-limit result: split by semantic ownership.
- Normal finish with invalid content: run artifact-specific repair; do not misclassify it as provider truncation.

## Normal-finish underlength recovery

Underlength is measured against the owned artifact target, event density, and remaining whole-story word budget. Length never overrides event coverage or continuity.

- A mildly short artifact that otherwise passes semantic gates receives one focused expansion pass. The pass may add missing action, conflict, dialogue, and state change, but may not rewrite accepted events or enter the next ownership range.
- A severely short response, summary-like prose, or a repeated underlength result discards that candidate from authority and triggers semantic splitting.
- Han-character thresholds trigger only after the response contains measurable Chinese prose; other-language artifacts stay with their applicable prose and quality validators.
- Failed candidates remain diagnostic outputs only. They are never supplied as accepted story history.

## Semantic task splitting

Splitting chooses the first available stable boundary:

1. contiguous formal event IDs;
2. validated causal-chain cycles;
3. planned scene boundaries;
4. entry, conflict, state-change, and exit beats inside one atomic event.

Each child receives the same applicable formal authority plus only its owned event range. The second child receives the first child's accepted exit state and ending, not a failed candidate. Splitting may recurse only while a meaningful semantic boundary remains; an atomic unit that still cannot pass stops the run instead of fragmenting prose indefinitely.

The merged parent must re-pass length, prose, duplication, event order and coverage, entry/exit state, transition, and handoff validation before a checkpoint is written.

## Cross-story scene continuity

The current greedy location-suffix comparison is not authoritative and must not hard-fail a run. Continuity uses a project-scoped canonical location index built at runtime from existing location files, StoryState, confirmed outline, character location references, and plan entry/exit evidence. Existing IDs and names are primary; explicit aliases and parent/child relationships are used when available. No project migration is required to add missing aliases.

Normalization applies Unicode NFKC, whitespace and punctuation cleanup, and safe exact alias matching. Location Markdown ignores fenced templates and HTML comments, accepts block and inline aliases plus documented English/Chinese feature headings, rejects malformed inline aliases, and removes aliases claimed by multiple canonical places. It never rewrites free-form prose. Mere dialogue, memory, or speculation about a place does not prove the current scene moved there.

The scene state contains, when known, canonical location ID, parent location, scene plane (ordinary, memory, dream, virtual, or other), time relation, present characters, point of view, action, and knowledge state.

Continuity decisions are confidence-gated:

- Same canonical location: pass.
- Parent/child or adjacent location with a movement/action bridge: pass.
- Different canonical locations with time, movement, memory, dream, virtual, or viewpoint transition evidence: pass.
- Two distinct high-confidence canonical locations with no bridge: blocking contradiction.
- Missing, ambiguous, same-named, or unknown locations: warning only; uncertainty cannot block by itself.

This rule must work for historical residences, modern offices and hospitals, schools, vehicles, spacecraft, virtual worlds, dreams, secret realms, and projects without complete location files. Legacy checkpoints without scene-state fields use compatibility mode: known contradictions still block, uncertain inference only warns.

## Execution index and checkpoints

`short-execution-index.json` remains a transient artifact derived from confirmed StoryState, constraints, validated plan, causal chain, and segment count. It is not an alternate outline. Drafting requires `ready` authority.

Accepted checkpoints bind project ID, StoryState revision, outline hash, constraint hash, plan hash, causal-chain hash, segment-plan hash, preceding accepted text hash, event ownership, handoff, canonical location-index hash, entry/exit scene state, and text hash.

Cross-run recovery considers only the same run or prior failed/cancelled runs, revalidates authority, and reuses only a continuous accepted prefix. A stale or missing segment invalidates that segment and every dependent successor. Completed, queued, or active runs are never accidental recovery sources. Legacy checkpoint hashes are accepted only when the current canonical location catalog is empty; projects with formal locations require the catalog-aware authority hash.

## Downstream workflow policy

- Planning: split contiguous event ranges; merged output must cover every formal event in order with valid handoffs.
- Causal chain: split event/cycle ranges; no drafting starts until exact event coverage and causal closure pass.
- Draft: split events, causal cycles, or scene beats; merged prose must preserve entry/exit state and full-story targets.
- Polish: retain existing windows; compare event evidence and state against the accepted source so polish cannot delete facts or break handoffs.
- Review: retain existing windows; no final score is authoritative until every owned window completes and the merged report validates.
- Canon, StoryState, and timelines: partial facts never commit; batch extraction merges with source evidence and conflict checks, then writes atomically.
- Long chapters: use chapter-plan scenes and volume events as ownership boundaries, preserving prior chapter state, volume targets, and unresolved promises.

Only explicitly advisory material may degrade and continue. Causal chains, event assignments, locations, knowledge state, timelines, canon, promises, and ending constraints are never advisory.

## User-visible events

Events must state the exact class and evidence, for example: normal finish but 880 of approximately 2167 Han characters; automatic split over a named event range; uncertain location recorded as a warning; or explicit unbridged movement between two canonical locations. The UI continues to show one task while reporting internal subtask progress.

## Production-failure behavior

For the observed segment-4 failure, a retry revalidates and reuses accepted segments 1-3. The two failed segment-4 candidates remain diagnostics. Segment 4 is regenerated through contiguous event/causal ownership, merged, and fully validated before segments 5-6 begin. The phrase about the warehouse case settling and remaining inside the same residence no longer triggers a greedy-regex false positive; actual underlength still triggers recovery and cannot pass silently.

## Acceptance coverage

Tests must prove:

- additive migration idempotence and secret-free route isolation;
- network retry does not change capacity inference;
- output-limit expansion and semantic splitting;
- normal terminal underlength triggers expansion or semantic splitting;
- the production segment-4 location fixture no longer false-fails;
- real unbridged high-confidence transitions still block;
- historical, modern, mystery, science-fiction, fantasy, dream/virtual, alias, hierarchy, missing-data, and ambiguous-location cases behave correctly;
- invalid candidates never become authority;
- valid checkpoint prefixes remain reusable and stale successors do not;
- planning, causal, draft, polish, review, canon, and long-form boundaries reject partial authority;
- the complete test suite passes without paid model calls.
