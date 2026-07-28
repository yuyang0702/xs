# Quality V2 And User Control Design

## Goal

Make the short-story quality loop preserve the real best manuscript, explain every score in plain Chinese, support user-confirmed calibration references and protected passages, and expose one consistent publication state without adding routine model calls.

## Existing Capabilities Preserved

- Local full-manuscript analysis, optional LTP, originality candidate screening, first full review, incremental correction review, provider fallback, resumable window checkpoints, StoryState authority, learning artifacts, platform profiles, and Zhihu package generation remain in place.
- Models continue to produce candidates only. Runtime remains the only formal manuscript writer.
- Existing projects, run files, credentials, model bindings, references, and formal manuscripts are preserved.

## Authoritative Manuscript States

The UI and API distinguish `candidate`, `protected_best`, `formal`, and `publication`. A quality checkpoint binds manuscript hash, path, score, scoring profile, scoring model identity, review attempt, report path, and unresolved issue ledger. Legacy `historical-best-<score>.md` files are reconciled idempotently into a checkpoint without deleting or rewriting historical artifacts.

A candidate can replace the protected best only when it is comparable and materially better. A passing lower-scoring candidate never replaces or publishes over a higher-scoring protected best. A score from a different profile or judge identity is labelled non-comparable; the historical text remains protected until a new baseline is established or the new candidate fully passes the active profile.

## Zhihu Short Quality Profile V2

The profile id is `zhihu-short-v2` and the visible weights are commercial 40%, story 40%, and prose 20%. The model returns criterion scores and evidence; Runtime calculates parent dimensions and the total.

Commercial criteria cover opening pull, sustained reading motivation, obstacle-action-result escalation, climax and ending payoff, and platform fit. Story criteria cover the seven-step causal arc, character motivation and agency, timeline and knowledge boundaries, promise/setup/question payoff, and relationship or emotional change. Prose criteria cover clarity, scene and dialogue effectiveness, character voice, rhythm, repetition, and AI-like phrasing.

Full pass requires total at least 80, commercial at least 75, story at least 75, prose at least 68, no hard blocker, and no unresolved major issue. Conditional pass requires total at least 75, commercial at least 72, story at least 70, prose at least 65, and no hard blocker. A conditional pass remains a candidate and cannot generate a submission package.

Promotion requires a gain of at least two points, no parent dimension regression greater than three points, resolution of the requested repair targets, and no new major issue. A difference below two points retains the existing best unless the new candidate has fewer unresolved major issues and no dimension regression.

## Evidence And Issue Lifecycle

Every scored criterion and every deduction carries a Chinese label, manuscript position, excerpt, effect on reading, and repair direction. Hard publication blockers are separate from ordinary deductions. Duplicate cross-window findings are merged into stable issues with multiple evidence locations. Stable issue ids persist across attempts with `unresolved`, `partially_resolved`, or `resolved` status.

Correction planning uses the protected best manuscript and its own issue ledger. Resolved issues become preservation constraints. Incremental review is based on the actual source manuscript used for the correction, never a lower-scoring rejected candidate.

## Quality Reference Group

Each project and scoring profile owns a versioned reference group. Runtime recommends a balanced set from confirmed references and project run history: high-quality anchors, ordinary anchors, known-problem examples, historical baselines, and before/after pairs. Recommendations never become active without user confirmation.

Confirmation does not call a model. Routine final review does not send reference manuscripts. The group is used for manual calibration when a scoring profile or final-review model changes and for local completeness checks. The UI records role, source, reason, confirmation time, applicable profile, status, and history. Removing an item never deletes its source reference or run artifact.

## Protected Passages

Protected passages reuse versioned project locks. A user selects one or more complete consecutive paragraphs from the candidate manuscript and chooses `soft` or `exact`. Soft protection permits punctuation, whitespace, and mechanical joining changes while preserving normalized wording. Exact protection requires the original excerpt verbatim.

The system may recommend protection but never activates it automatically. Revision prompts include applicable locks and local validation rejects a violating segment. A conflict remains visible and cannot silently disable the lock. The user can keep protection, remove it, or allow the next revision once.

## Word Count And Publication Authority

Zhihu short-story length uses effective Han characters after removing Markdown headings, internal markers, whitespace, and punctuation. The UI presents one official current/target/remaining count; secondary statistics stay collapsed.

The candidate endpoint returns one publication authority object for both UI and write endpoints: whether the candidate can become formal, whether a package can be generated, and Chinese blocking reasons. Button visibility and disabled state use this object rather than duplicating local conditions in JavaScript.

## User Experience

The existing candidate-quality section becomes a progressive quality workspace rather than a new top-level page. Its default view shows manuscript state, total and three parent scores, comparison with the protected best, the three to five most important issues, official word count, and the next action.

Local checks and model review are visibly separated but remain in one workspace. Review windows are evidence scopes, not separately scored cards. Healthy windows are summarized. Scoring details, full issue evidence, reference management, protected passages, run scope, and version history are collapsed until requested. All user-facing labels and errors are Chinese.

## Failure And Recovery

The current stage, completed and total windows, elapsed time, active primary or fallback route, failure reason, and resumable next window remain visible. Any failed window keeps completed checkpoints. Invalid or stale hashes, missing review evidence, protected-passage conflicts, and non-comparable scores fail closed and preserve the protected best.

## Risks And Controls

- Model score drift is controlled by criterion evidence, a two-point tolerance, profile and judge signatures, and manual calibration.
- Reference bias is controlled by balanced roles and explicit confirmation.
- UI density is controlled through summaries and progressive disclosure.
- Excessive locking is controlled by paragraph-level selection and visible conflicts.
- Token growth is controlled by local aggregation and excluding reference manuscripts from routine review.
- Migration is idempotent and preserves every legacy artifact.

## Acceptance Criteria

- The existing 64.75 legacy artifact is discoverable as the protected historical best while lower attempts remain history.
- A lower-scoring passing candidate cannot replace a higher-scoring comparable best.
- The next correction uses the best manuscript and its matching issue ledger and review baseline.
- Candidate API and UI show profile version, model identity, parent and criterion scores, evidence, issue lifecycle, word count, comparison, and Chinese next action.
- Reference recommendations require confirmation and confirmed items remain inspectable and removable without deleting sources.
- Soft and exact passage protection survive revision validation and conflicts are actionable.
- Formal publication and Zhihu packaging use the same hash-matched quality authority.
- Existing workflows and tests remain compatible for projects not using `zhihu-short-v2`.
