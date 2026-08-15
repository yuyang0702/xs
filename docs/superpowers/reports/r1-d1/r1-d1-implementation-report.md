# R1-D1 — Authority-aware Mixed-script Validator Narrow Fix

## Final Gate

`R1_D1_NARROW_FIX_READY`

Implementation source head: `3745732` on branch
`r1-d1/authority-aware-mixed-script-narrow-fix-20260816`, based on
`caa3c0fd07b19ed0806a28f94a1184cf3d697a6d`.

The exact replay refines one R1-D0 assumption. Calls 20 and 21 contain six and
seven unapproved mixed-script candidates and must still fail. The authority
term is present in call 22; that one finding is now exempted and the unchanged
call-22 Draft crosses the prose boundary. The narrow fix therefore removes the
terminal false positive without weakening the two earlier true positives.

## Production change

Only two production modules changed:

- `src/novel_flywheel/prose_quality.py`: versioned term-set contract, frozen
  token normalization, exact decision logic, and hash-only diagnostics;
- `src/novel_flywheel/workflows.py`: current-segment projection and context
  threading through fresh, cached, split-child, combined, and final Draft
  validation plus a best-effort receipt.

`baml_src`, Prompt definitions, providers, models, Contract Runtime,
CompletionSupervisor, route selection, output-budget policy, retry/fallback
counts, Planning Adaptation, Semantic Review, Maintenance, StoryState, Canon,
Phase 1B, and Long Workflow did not change. `docs/maintenance.md` records the
new operator contract. All other changed files are tests, sanitized fixtures,
the R0F successor evidence, the approved spec, or this report set.

## AuthorityApprovedLatinTermSetV1

The in-memory schema contains:

- `schema`, `version`, `normalization_version`;
- `draft_authority_revision`, `draft_authority_sha256`;
- `source_artifacts[]`: kind, SHA-256, contract/version, authority status;
- `approved_terms[]`: normalized term (memory only), term SHA-256, source
  artifact SHA-256, field-path SHA-256, segment-binding SHA-256;
- deterministic `term_set_sha256`.

Diagnostics replace normalized terms with hash, length, character class,
source kind/hash, field-path hash, binding, revision/hash, policy version and
decision code. They never persist term text, Draft text, Prompt text, tool
arguments, credentials, or headers.

## Source map and provenance

The projection receives already parsed objects and opens no directory:

| Source | Included fields | Excluded examples |
|---|---|---|
| Current `PlanningSegmentIR` | heading, outline, opening, event_body, handoff | Planning Markdown, Prompt, summaries |
| Matching `ShortExecutionManifest` segment | owned beat action/actor/location, pre/postconditions, knowledge/relationship deltas, entry/exit state | source evidence, semantic summary, other segments |

Every field requires a source artifact present in the exact source set and the
same segment binding. Manifest hash, beat ownership, planning segment number,
Draft authority revision/hash, normalization version, and source status are
rechecked. Construction or receipt failure fails closed to the old behavior.

The private historical authority contains the target term hash at 16 exact
field paths: 15 in the current Manifest and one in the current Planning
segment. The term-set hash is
`f79019a9563e07b70cb0fa94afa56a63eef2831fbda0c8bc0618134e1c5f7759`.
No term text is in Git.

## Normalization V1

Policy identifier: `nfkc-case-sensitive-exact-token-v1`.

- NFKC width normalization;
- case-sensitive exact matching;
- letters/digits with internal `.`, `_`, `/`, `-`, and optional terminal
  `+`/`++`;
- at least two Latin letters, preserving the old detector threshold;
- digits and version components are part of the token;
- surrounding normal punctuation is not part of the token;
- ambiguous Unicode connectors fail closed;
- no substring, prefix, suffix, fuzzy, or case-folded approval.

The canonical policy hash is
`7e9875e3341f811fc3882b8161de6ca9f4e81243ce0262a0b1c72cb54353c940`.

## Decision table

| Condition | Decision | Business result |
|---|---|---|
| Exact term, current hashes/revision/source/binding | `exempt_authority_approved_term` | Suppress this one `mixed_script_corruption` |
| Exact token absent or extension/subtoken only | `reject_unapproved_mixed_script` | Preserve blocker |
| Authority/source status or hash set stale/missing | `reject_stale_authority` | Preserve blocker |
| Token or normalization boundary ambiguous/unknown | `reject_ambiguous_term` | Preserve blocker |
| Context unavailable | no exemption | Exact legacy behavior |

The candidate set remains the original `MIXED_SCRIPT` regex. An initial
implementation expanded two historical candidate counts by one; exact replay
caught it, and the final implementation anchors extraction to legacy spans.

## Historical exact replay

Private evidence is read by `tests/r1_d1_historical_replay.py`; only the
hash-only result fixture is committed. Fixture and private run matched exactly
with canonical result hash
`657cc71af13986b8ea94309ec0fed904abbd943e827004a8bb55283f430c1afb`.

| Call | Response hash prefix | Before mixed | After mixed | Target exemptions | Leaf result |
|---|---:|---:|---:|---:|---|
| 20 | `85f3a3ea` | 6 | 6 | 0 | true positive retained |
| 21 | `4ad43318` | 7 | 7 | 0 | true positive retained |
| 22 | `1ddbcf4c` | 1 | 0 | 1 | prose boundary passed |

All three response hashes, stored-file hashes, character counts, and all
non-MIXED_SCRIPT findings are unchanged. No punctuation or Draft byte was
changed. Historical mixed-script regeneration count was two; current
reclassification proves both were true-positive regeneration. False-positive
regeneration after the fix is zero; total regeneration remains two. The
previous terminal false positive disappears.

## Regression and workflow evidence

- legal matrix: direct adjacency, two-sided CJK, punctuation, case, NFKC
  width, digits, hyphens, dotted versions, repeats, multiple terms, duplicate
  provenance, stable ordering/hash, revision change and removal;
- true-positive matrix: unapproved, substring/prefix/suffix, wrong segment,
  stale hash, missing provenance, unknown normalization, ambiguous connector,
  random/repeated Latin, mojibake, control character and excluded adapter
  evidence;
- fake-gateway workflow: one Draft call and one Semantic Review call, accepted
  receipt, no scope retry;
- receipt sink failure: business output and call sequence unchanged;
- context on/off parity: ordered roles, system/user bytes and max-output
  budgets are exact;
- Manifest, ownership, Draft receipt, checkpoint and 13K/20K/30K
  production-shaped Short tests pass.

Focused results: 60 passed, 1 existing xfail. Related results: 155 passed, 1
existing xfail. Workflow subset: 14 passed, 364 deselected. Production length
matrix: 3 passed in 78.91 seconds.

Final full suite: **2732 passed, 2 skipped, 6 xfailed, 1 failed** in 1395.18
seconds. The sole failure is the pre-existing
`test_live_db_and_formal_artifact_baseline_remains_r0_identical` mismatch
(`5deb…` historical expectation versus current `0fcc…`). New failures: zero.

## Prompt, route, retry and budget parity

The context-on/context-off deterministic run produced exact equality:

| Boundary | System SHA-256 | User SHA-256 | Max output |
|---|---|---|---:|
| Draft | `41394e4b315fe4a9dfbbad2145931b43a4b1a4e9cc82d0eedd1342d976aa4710` | `750afca9140f07faa9cd1381435c73dfe1406b5a1ed12c11fb05e63854bd9dd9` | 8192 |
| Review | `b39a0035cc468c6184e46def9124a9597597f67a1fc2204769e65832f89a90c9` | `8702c36ff39ac08dff0f8da8e127869fa97996d077f1f12edcf0c286cdcf4d9f` | 980 |

Ordered roles remain `[draft, review]`; protocol retry delta and configured
fallback delta are both zero. Real Provider calls and paid calls are zero.

## Performance

For an 8,820-character synthetic segment over 250 iterations:

| Path | p50 | p95 | max |
|---|---:|---:|---:|
| Legacy | 3.612 ms | 4.7892 ms | 8.2075 ms |
| Authority-aware | 7.3688 ms | 8.5972 ms | 13.3678 ms |

p50 delta is 3.7568 ms. On the three exact historical segments (450 samples),
p50/p95/max are 9.6809/11.147/16.5351 ms. Term-set hash and lookup are built
once per segment; there is no network, model, database schema, service, queue,
or asynchronous worker.

## Live parity and privacy

Before and after snapshot hash:
`1ec9d4ef5f6455d20dcce97acaf6cbbd41f2da252c91cd308b2a734e314e9788`.

- live DB: `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`;
- formal story: `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745`;
- Canon: `5361f3729dd191e987f2494cb7bac1ebf15d9a9837465208262e3ee3f24f49fc`;
- Candidate, Checkpoint and Saga manifests: empty-manifest hash `4f53cda1…`;
- StoryState/Candidate/Workflow checkpoint rows: 6/11/917;
- production terminal event count: 1 before and after.

Private raw evidence remains ignored outside Git. Committed fixtures and
reports contain no raw story, Prompt, real term, project identifier, absolute
private path, tool arguments, credential or header.

## Incident mapping and residual risk

Suggested family: `draft.validator_false_positive`; subtype:
`authority_approved_latin_term_misclassified`. Preserve
`mixed_script_corruption` as the historical validator issue code. Incident
Catalog was not modified.

Residual facts are explicit: calls 20/21 remain valid true-positive failures;
no real post-fix Short Canary was run; a structured natural-language authority
field can contain incidental Latin words, though any approval remains exact,
current, source-hash-bound and segment-local.

R1-D1 stops here. It does not execute a real Canary, produce Signed Approval,
enable Phase 1B, or enter Long/Phase 1C/Phase 1D work.
