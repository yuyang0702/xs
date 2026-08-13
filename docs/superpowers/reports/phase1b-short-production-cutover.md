# Phase 1B Short Production Cutover Report

Candidate lane status: **Short Canonical Promotion Candidate Lane Ready**

Canary status: **Not validated**

Short Production Authority Cutover: **NO-GO**

Phase 1C / Phase 1D: **Not started**

## Scope and protected boundaries

Phase 1B adds only a disabled-by-default, exact-project-gated Short lane from
pre-decision Maintenance inventory through the existing Candidate, Project
Mutation Journal, formal targets, StoryState CAS, and Saga recovery. Long,
Context Assembly, Prompt, model routes, retry/fallback budgets, Repair,
Legacy Resume, database schema, and the five production acceptance failures
remain unchanged.

The lane requires both `NOVEL_SHORT_CANONICAL_V2=1` and an exact-project
`short_canonical_v2` flag. A global flag does not authorize it. No flag is
enabled by default and this report does not authorize a production canary.

## Replay corpus

The committed deterministic corpus contains 24 normal/window samples and four
identity gold pairs. It covers location, knowledge, relationship, transition,
no-change, exact/missing/duplicate evidence, ambiguous identity, stale
expected current, multiple current values, `future_normative`, Legacy-only,
and unsupported reserved shapes.

Final hash-only report:

| Measure | Result |
|---|---:|
| Proposal units | 32 |
| Supported claims | 20 |
| Exact evidence | 16 / 32 (50.0%) |
| Ungrounded/ambiguous evidence | 4 / 32 (12.5%) |
| Held batches | 14 / 24 (58.33%) |
| Ambiguous identity | 2 / 32 (6.25%) |
| False split / false merge gold pairs | 0 / 0 |
| Legacy accepted / rejected | 26 / 6 |
| V2 eligible / held units | 14 / 14 |
| Legacy accept, V2 reject | 8 |
| Legacy reject, V2 accept | 0 |
| Legacy-only / shadow-only | 2 / 0 |
| No-change / future normative | 2 / 2 |
| Lost before V2 | 0 |

Normal and window pairs have identical V2 evidence qualification, slot
identity, and mutation eligibility. Legacy asymmetry remains a strict expected
failure; Phase 1B does not change Legacy policy.

## Commit, hold, and recovery evidence

- V2 input is frozen before Legacy accept/reject/merge. Legacy string facts are
  counted using the existing stable Legacy key rule and remain Legacy-only.
- `future_normative`, unknown domains, stale base, source mismatch, ambiguous
  identity/evidence, multiple current values, unsupported reserved shapes, and
  writer overlap hold the whole batch before Saga preparation.
- Hold keeps the polish Candidate pending/protected while formal files,
  StoryState revision/hash, projections, and Journal remain unchanged.
- Eligible batches produce one leaf-level writer plan from one base, one
  StoryState CAS, and one formal receipt bound to accepted/rejected/held sets
  and the frozen Journal/Saga ID.
- An injected pre-artifact interruption rolls the prepared Saga back without a
  formal or StoryState change. An injected receipt failure recovers from the
  frozen committed Journal with zero model calls and no semantic re-evaluation.
- Hash-only `promotion_write` trace events distinguish V2 hold from commit;
  trace failure is not part of any business condition.

## Production-shaped offline evidence

The real Short workflow orchestration ran with deterministic gateways at all
required sizes. Only the paid network boundary was replaced.

| Target | Status | Mutations | State commits | Lost before V2 | Elapsed |
|---:|---|---:|---:|---:|---:|
| 13,000 | committed | 1 | 1 | 0 | 14.17 s |
| 20,000 | committed | 1 | 1 | 0 | 24.34 s |
| 30,000 | committed | 1 | 1 | 0 | 45.63 s |

Every run crossed planning, causal chain, execution manifest, drafting,
split/merge, polish, final review, Candidate, formal Project Mutation Saga,
and StoryState N+1. Paid model calls were zero.

## Parity and overhead

On the same project/stage input, enabled and disabled flags produce identical
system prompt, user prompt, output budget, and ordered model calls. The
deterministic empty-claim complete Short comparison produced identical formal
artifacts, StoryState data, checkpoint topology, and Candidate lifecycle.

One local complete-run measurement recorded 1.965 s disabled and 2.001 s
enabled (35.8 ms observed delta), with 4,736 additional run-artifact bytes.
This is a single-machine characterization, not a latency guarantee. It added
zero calls, prompt tokens, output budget, timeout, retry, or fallback attempts.

## Private snapshot gate

A fresh copy of `data/app.db` and the only available completed historical
normal Maintenance artifact was replayed outside the repository and without
writing live project data. Live database and source artifact hashes were
unchanged after replay.

The artifact contains 35 Legacy string facts but predates pre-decision
inventory metadata. It is therefore `unverifiable_legacy` with
`legacy_predecision_inventory_unverifiable`, and is held without commit. A
committed sanitized 35-unit isomorphic fixture proves the current adapter
counts the topology with `lost_before_v2=0`. No real capacity/window snapshot
was available. This evidence is compatibility characterization, not a canary.

## Verification

- Phase 1B focused suite: `32 passed, 5 xfailed`.
- Related authority/recovery suites: `100 passed`; Short workflow adjacency:
  `3 passed, 375 deselected`; API startup/recovery: `7 passed, 49 deselected`.
- Full suite: `2336 passed, 1 skipped, 5 xfailed` in 939.19 s, compared with
  the Phase 1A baseline `2303 passed, 1 skipped, 5 xfailed`. There are 33 new
  passing tests, no new failure, and no XPASS.
- Paid LLM/API calls: `0`.
- Strict expected failures: all five remain xfailed; no XPASS.

## Cutover decision

**NO-GO** for Short Production Authority Cutover because no explicitly
authorized real canary has committed, the only real normal artifact is legacy
and cannot prove its pre-decision inventory, and no real window/capacity
snapshot is available. The candidate lane itself is ready for a separately
approved, exact-project canary. Even a future passing canary requires a new
cutover decision; this report does not enable the flag or start Phase 1C/1D.
