# Phase 1A Canonical Shadow Contracts

Status: development shadow only. Production Authority Cutover remains NO-GO.

## Authority boundary

Phase 1A contracts may produce diagnostics only. They do not enter StoryState,
Canon, Project Mutation journals, StoryMemory projections, candidates,
checkpoints, prompts, or formal publication artifacts. The only supported fact
kinds are `character.location`, `character.knowledge`, and
`character.relationship`.

Mutation `expected_current` is resolved only from the exact StoryState revision
and authority hash named by the claim batch. Canon, StoryMemory, FTS, chapter
state, summaries, projections, Planning IR, manifests, and reviewer inference
are diagnostic inputs only and can never make a mutation eligible.

## Canonicalization

`canonical-shadow-json-v1` serializes an envelope containing
`canonicalization_version`, `schema`, and `value` as UTF-8 JSON with sorted keys,
compact separators, JSON null/boolean/number semantics, and finite numbers only.
Dictionary insertion order is irrelevant. Volatile timestamps, trace/run IDs,
and random UUID fields are excluded. Absolute paths normalize to
`<ABS>/<basename>` and paths under an explicit root normalize to `<ROOT>/...`.
Unsupported Python values and non-finite floats are rejected; object repr and
memory addresses are never used.

Stable IDs use SHA-256 over canonical bytes:

- `claim_id = claim-<sha256(ProposedClaimV2 unsigned)[:32]>`
- `batch_id = batch-<sha256(ProposedClaimBatchV2 unsigned)[:32]>`
- `slot_id = slot-<sha256(ShadowSlotIdentityV1 structural dimensions)[:32]>`
- `competition_key = compete-<sha256(slot_id + comparable story_time)[:32]>`
- `evidence_hash = sha256(EvidenceEnvelopeV2 unsigned)`
- `mutation_id = mutation-<sha256(CanonicalMutationV1 unsigned)[:32]>`
- `receipt_hash = sha256(ShadowCanonicalCommitReceiptV1 unsigned)`
- `source_commit_id = commit-<sha256(committed journal identity)[:32]>`
- `projection_hash = sha256(ProjectionProvenanceV1 projection object)`

Trace event IDs may be random but are excluded from every stable identity.

## Evidence coordinates

Narrative evidence binds the publication-closed final source bytes. Offsets are
zero-based UTF-8 byte offsets `[byte_start, byte_end)`, never Python character
indices. Each span binds the final source artifact SHA-256, exact byte-slice
SHA-256, covered range, and `final-bytes-extractor-v1`.

Draft, summary, normalized text, Memory, snippets, and context packets cannot be
evidence sources. If newline or formatting normalization occurs, the final
published bytes are selected before matching. Zero matches are `ungrounded`;
multiple matches, unstable offsets, and source-hash mismatch are `ambiguous`.
No implementation may select the first of multiple matches.

## Shadow receipt safety

`ShadowCanonicalCommitReceiptV1` requires `shadow_only=true`,
`commit_performed=false`, `outcome=shadow_not_committed`, null target revision
and hash, and empty projection effects. It is not a Project Mutation effect and
no production commit consumer accepts it.

## Migration boundary

New exact-bound artifacts are classified `exact_v2`. Legacy review/resume
artifacts remain `unverifiable_legacy` and continue in the legacy lane during
Phase 1A. Unknown is never treated as fresh. No lane cutover is implemented in
this phase.
