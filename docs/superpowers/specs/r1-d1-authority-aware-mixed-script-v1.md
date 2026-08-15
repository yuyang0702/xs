# R1-D1 Authority-aware Mixed-script Narrow Fix — Change Contract

## Classification and authorization

- Requested outcome: exempt only exact Latin terms already present in the
  current Draft segment's accepted, hash-bound authority; retain every genuine
  mixed-script corruption rejection.
- Authorization: implementation.
- Risk level: L3 because the change affects a generated Draft validation and
  retry boundary.
- Scope classification: closed world. The finite source contract is the
  current `PlanningSegmentIR` plus the matching `ShortExecutionManifest`
  segment and its owned beats. No project corpus or generated Draft scan is a
  source of approval.
- Resolution target: `systemically_resolved` for the declared finite authority
  projection, not a claim that arbitrary natural-language terminology can be
  inferred.

## Current behavior and evidence

The R1-D0 exact replay bound calls 20–22 to complete, in-range Draft outputs.
The first divergent node is `analyze_prose` / `MIXED_SCRIPT`; the concrete
blocking counts are 6, 7 and 1 before the outer Draft gate collapses them to
`prose_invalid` and exhausts two whole-scope retries.

The private source scan does not expose the real term. Its SHA-256 is
`1c34f88707b55e6104c4eb20e71ffa3d33e414b71ef689a15fad0640d0ac58cb`
and its length is eight ASCII letters. Exact hash-only evidence places it in:

- `PlanningSegmentIR.event_body`, field-path SHA-256
  `3e221cb46a7ea1c0b3b9403175b59945c320d393694600f525c95b9ee50046d4`;
- current-segment Manifest beat preconditions, postconditions, knowledge and
  relationship deltas; and
- current-segment exit state.

This proves a bounded structured projection is available. It does not justify
scanning Planning Markdown, Prompt text, Memory, FTS, references, Candidate,
Draft output or arbitrary project files.

## Allowed behavior change

For a CJK-adjacent exact Latin token, `analyze_prose` may suppress only the
`mixed_script_corruption` finding when all of the following are exact:

1. normalization policy version;
2. Draft authority revision and hash;
3. current segment binding;
4. complete current source-artifact hash set;
5. term hash and exact normalized token; and
6. term provenance to an accepted structured field in that segment.

The same check emits a hash-only decision receipt. No other prose finding,
semantic validator, ownership rule, Manifest coverage rule or workflow policy
changes.

## Protected unchanged behavior

- Prompt system/user bytes and generation output bytes;
- Provider, model, route, output budget and retry/fallback counts;
- Planning Adaptation, causal-chain and Execution Manifest semantics;
- Draft generation and semantic-review policy;
- StoryState, Canon, Candidate, Checkpoint, Saga and Phase 1B;
- Long workflow;
- every non-`MIXED_SCRIPT` prose validator; and
- default `analyze_prose(text)` behavior for non-Draft callers.

Real Provider and paid-model calls remain zero.

## Authority impact map

| Boundary | Disposition |
|---|---|
| Formal manuscript, Canon, StoryState | Read-only parity only |
| Current/protected Candidate | Not involved |
| Planning IR and Execution Manifest | Read-only exact authority sources |
| Draft validator | Changed only for exact authority-approved Latin terms |
| Draft retry/recovery | Policy unchanged; a removed false finding no longer consumes it |
| Semantic Review and later stages | Not changed; used as next-boundary proof |
| SQLite schema/rows | No schema change; isolated diagnostic run events only |
| Provider/model/credentials | Not involved |
| Checkpoint/resume | Business contract unchanged |

## Source-field allow-list

The projection receives already parsed objects; it never opens a directory.

`PlanningSegmentIR` current segment:

- `heading`, `outline`, `opening`, `event_body`, `handoff`.

`ShortExecutionManifest` current segment only:

- owned beat `action`, `actor`, `location`, `preconditions`,
  `postconditions`, `knowledge_delta`, `relationship_delta`;
- segment `entry_state[].state` and `exit_state[].state`.

Excluded fields include raw source evidence, semantic summaries, adapter audit
text, Prompt text and all artifacts outside the current segment binding.

## Normalization policy V1

- Unicode: NFKC;
- case: sensitive after NFKC;
- width: full-width Latin letters, digits and supported punctuation normalize
  to their ASCII equivalents;
- exact token grammar: a Latin letter, followed by Latin letters/digits,
  optionally joined by `.`, `_`, `/` or `-`, with an optional terminal `+` or
  `++`;
- at least two Latin letters are required to preserve the existing detector's
  threshold;
- digits and version components are part of the exact token;
- surrounding punctuation is outside the token;
- Unicode dash/connector variants not normalized by NFKC are ambiguous and
  fail closed;
- no substring, prefix, suffix, fuzzy or case-folded match.

The policy identifier is part of every term-set and decision hash.

## Rejected alternatives

- disabling `MIXED_SCRIPT` or weakening global prose thresholds;
- allowing acronyms, ASCII, uppercase terms, or terms by length alone;
- hard-coding the incident term or inserting punctuation;
- scanning Prompt, Draft, Memory, FTS, references, summaries or the project;
- adding a database, service, queue, model call, retry or fallback;
- using a third-party tokenizer. The finite ASCII technical-token grammar plus
  Unicode NFKC is smaller, deterministic, dependency-free and fail-closed for
  this exact authority contract.

## Rollback

Revert the validator implementation commit. The default analyzer path and all
persisted business schemas remain compatible; no migration or data rollback is
required.

## Verification ladder

1. R1-D0 characterization remains red/xfail before implementation.
2. Unit matrix covers approved/unapproved, exact boundaries, stale/missing
   provenance, wrong segment, normalization, deterministic hashing and privacy.
3. Exact private replay applies unchanged calls 20–22 bytes to the real current
   analyzer and Draft leaf path.
4. Production-shaped fake-gateway Draft integration crosses local prose,
   first-person and semantic validation without a false scope retry.
5. Related prose/Draft/checkpoint tests and the full suite pass with no new
   failures.
6. Prompt/route/retry source trees and live business artifacts remain exact.

## Material requirement traceability

The V2 forward-risk report must map the finite authority projection, fail-closed
decisions, exact matching, true-positive preservation, historical replay,
next-boundary continuation, privacy, performance, parity and zero-paid-call
requirements to their source and test paths. Any missing private replay or
next-boundary proof downgrades the result to `unresolved` or `case_fixed`.
