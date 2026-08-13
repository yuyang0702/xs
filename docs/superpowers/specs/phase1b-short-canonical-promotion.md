# Phase 1B Short Canonical Promotion Candidate Lane

Status: development candidate lane only. Short Production Authority Cutover is
NO-GO until a separately approved real-project canary. Phase 1C and Phase 1D
are out of scope.

## Change contract

Phase 1B may add one disabled-by-default, project-scoped Short lane between
publication closure and the existing Project Mutation Saga. It may reuse the
existing polish Candidate, formal targets, StoryState CAS, snapshot, Journal,
and recovery kernel. It must not add a second StoryState, database table,
commit engine, formal writer, model call, prompt, reviewer, retry, fallback, or
Long path.

Flag-off behavior is byte-for-byte characterized by the Phase 1A baseline.
The five production-acceptance tests remain strict xfail. A passing candidate
lane report does not authorize enabling production cutover.

## Pre-decision proposal inventory

The V2 input boundary is:

```text
raw Maintenance model result
-> existing protocol/parser/domain validation
-> normalized complete proposal inventory
   |-> unchanged Legacy decision path
   `-> V2 claim/evidence/identity/mutation path
```

Normal inventory is frozen before
`_partition_short_maintenance_proposal` and
`_merge_short_maintenance_authority` discard, accept, or merge a unit. Window
inventory is frozen from each validated `MaintenanceWindowEnvelopeV1` before
`project_accepted_maintenance_envelope` removes rejected units. Recursive
window bundles and reductions retain the original validated envelopes for V2;
their Legacy accepted projections are comparison inputs only.

Every structurally valid unit receives an inventory identity and disposition:
`legacy_accepted`, `legacy_rejected`, `ambiguous`, `unsupported`, or
`evidence_gap`. V2 sees all of them. Replay reports record `proposal_total`,
`legacy_accepted`, `legacy_rejected`, `v2_eligible`, `v2_hold`,
`lost_before_v2`, `legacy_accept_v2_reject`, and
`legacy_reject_v2_accept`. Candidate commit requires `lost_before_v2=0`.

## Stable story time

`story_time` and `source_artifact_hash` are independent fields. Narrative SHA
binds evidence, source bytes, publication closure, and candidate lineage; it is
never the semantic time coordinate.

Short uses `short-publication-endpoint-v1:<project-id>:edition:<n>`, where
`edition` is the base `manuscript_revision + 1`. Project ID and the integer
edition are stable business coordinates; timestamp, run ID, random UUID, and
narrative hash are forbidden. Revisions of the same logical endpoint retain
the story time and use `SUPERSEDE`. A later edition is a different transition
point even when the value is unchanged.

## Canonical eligibility and operational readiness

Canonical eligibility reads only the exact base StoryState revision/hash,
publication-closed final narrative evidence, stable slot identity, semantic
domain, and transition policy. Canon, canon_facts, chapter_states, Memory, FTS,
summary, and all other projections cannot supply `expected_current`, choose a
value, or turn unknown into absent.

Projection diagnostics are a separate `operational_readiness` result. A stale,
unknown, or conflicting projection can hold a canary with reason
`projection_environment_unreconciled`; this does not make the projection an
authority and does not change the canonical gate result. Receipts persist the
canonical result, operational result, and projection diagnostics separately.

## Batch-level hold

Any V2-owned reserved slot with an evidence gap, alias ambiguity, unsupported
reserved shape, stale base, multiple StoryState current values, unauthorized
semantic domain, source-hash mismatch, or writer-ownership ambiguity holds the
entire Short promotion before Saga `prepared`.

On hold:

- the new polish Candidate remains `pending` and is marked protected;
- no formal file changes;
- StoryState revision/hash, Canon, Memory, and projections do not change;
- no Project Mutation Journal reaches `artifacts_committed`;
- no committed receipt and no Legacy fallback are produced;
- Legacy-only fields do not promote separately;
- recovery never promotes the held Candidate.

Phase 1B does not support partial promotion.

## Leaf writer plan

Legacy and V2 each produce explicit JSON-pointer leaf patches from the same
base StoryState. The final `next_data` is constructed from that base exactly
once; a complete Legacy `next_data` may not be used as the V2 base.

V2 owns leaf paths for supported current facts only. Legacy may own all other
leaf paths, but neither a parent nor a child path may overlap a V2 path. Facts,
state, and transitions that express the same slot are normalized first and
must agree on one value. The final JSON diff and writer plan are checked in
both directions: every diff has one owner; every planned mutation yields one
diff or `no_change`; `unowned=0`; `multi_owned=0`. Parent-container replacement
and nested-object overwrite fail closed.

## Feature gate and frozen Journal lane

Candidate commit requires both:

1. process environment `NOVEL_SHORT_CANONICAL_V2=1`; and
2. an enabled `short_canonical_v2` flag whose exact scope is the current
   project (global and default scopes never authorize the lane).

The flag snapshot is taken once before the canonical gate. A later flag change
does not alter the run lane.

Before any formal or StoryState commit, the existing Journal domain-gate
payload freezes:

- `lane=short_canonical_v2` and feature snapshot;
- policy version;
- writer-plan hash and ProposedClaimBatch hash;
- accepted/held mutation IDs and EvidenceEnvelope set hash;
- base StoryState revision/hash;
- Candidate hash and final narrative hash;
- expected formal target set;
- deterministic receipt-input hash.

Recovery may only roll the frozen target forward, roll a prepared mutation
back, or rebuild the receipt from these frozen values. It must not call a
model, discover aliases, search evidence, resolve identities, re-evaluate
eligibility, or select Legacy/V2 writers.

## Receipt and rollback

`ShortCanonicalMutationCommitV1` is the formal, non-shadow wrapper around the
accepted Phase 1A mutation facts plus leaf patch values. Phase 1A
`CanonicalMutationV1` remains `shadow_only=true` and cannot itself commit.

`ShortCanonicalCommitReceiptV1` is deterministic from the frozen Journal gate
payload and the committed target revision/hash. A hold produces
`ShortCanonicalGateDecisionV1`, not a committed receipt.

Rollback is `git revert` per Phase 1B commit plus both feature gates off. The
Legacy path remains intact. A Journal already beyond `prepared` follows the
existing exact-target Saga recovery; it is never reinterpreted under a new
flag value.

## Acceptance boundaries

Candidate lane readiness requires offline tests for:

- pre-decision normal/window inventory and `lost_before_v2=0`;
- exact evidence, ambiguous identity, reserved unsupported kinds, stale base,
  source mismatch, multiple current values, and batch-level hold;
- stable story time and `SUPERSEDE` behavior;
- projection/authority separation;
- parent/child writer overlap and bidirectional diff ownership;
- flag-off Phase 1A parity and project-only dual gating;
- Candidate preservation with no formal/StoryState/Journal commit on hold;
- exactly one StoryState CAS and deterministic receipt recovery;
- no added model call or prompt/token/budget change;
- full Short flows at 13K, 20K, and 30K effective Han characters.

The final status is exactly `Short Canonical Promotion Candidate Lane Ready`
or `Short Canonical Promotion Candidate Lane NO-GO`. It must not be described
as Canary Validated without a real canary.
