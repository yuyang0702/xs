# Narrative Reliability Kernel V4

## Change contract

- Requested outcome: implement P0-P4 so known planning failures recover and structurally similar future parser, narrative-state, provider, capacity, and checkpoint failures cannot corrupt formal work.
- Original MUST requirements: completely address the currently observed failures; automatically handle rather than merely reject recoverable faults; work across novel genres and the user's third-party OpenAI, Gemini-backed, and Claude routes; preserve logic and prose quality; locate route or credential configuration again after a misleading not-found response.
- Scope classification: `open_world`.
- Operational definition: production-shaped and unseen structural variants recover without fixture-specific branches, cross the next authoritative boundary, and retain the last accepted complete candidate on exhaustion.
- Forbidden narrowing: no branch keyed to one run ID, event ID, provider name, Chinese phrase, wrapper name, or exact error string; containment is not resolution.
- Authorization: L3 implementation plus one real-provider acceptance after offline gates. Paid calls are never part of automated tests or maintenance checks.
- Current evidence: run `93075987b1374e53bb13d13ecb53bc68` lost an unnumbered continuation from an event projection, retained a real identity/knowledge contradiction, and exhausted distributed repair/capacity retries.
- Allowed changes: generated Markdown parsing, StoryState additive schema, execution-state assertions, recovery policies, incident typing, route capability observations, durable node checkpoints, diagnostics, documentation, and tests.
- Protected behavior: one StoryState authority; current candidate/best/formal promotion; formal outline and manuscript files; model bindings and secrets; existing projects and run history; Runtime-only formal writes; exact unaffected prose.
- Authority impact: candidates, best candidates, StoryState, planning receipts, execution manifests, run events/checkpoints, route capabilities, and diagnostic API are changed. Formal manuscript promotion remains read-only to the new kernel and continues through the existing writer.
- Selected approach: canonical Markdown AST/source map, typed narrative fact graph inside StoryState, composable invariant/genre rules, one monotonic RecoveryController, route-fingerprint capability registry, and hash-bound workflow node envelopes.
- Rejected alternatives: regex accumulation, a second story database, direct formal writes, an all-at-once LangGraph/Temporal migration, provider-specific aliases as the primary compatibility boundary, and quality repair by deletion.
- Rollback: additive schema readers, legacy manifest support, old workflow entry points, project-scoped kernel feature flag, and immutable prior candidates/checkpoints.
- Focused tests: narrative document projection, StoryState v3 migration, claim/rule contradictions, recovery monotonicity, provider capability invalidation, checkpoint idempotence.
- Related tests: planning adaptation/workflow, execution manifest, incidents, providers/models/context capacity, API/UI state, migration, draft/polish/revision integrity.
- Full suite: `pytest -q` before live acceptance or completion.
- Historical incident mechanisms: parser ambiguity, evidence binding, event-body integrity, obligation ownership, packet merge, latent issue attribution, structure drift, output truncation, connection/credentials, context capacity, stale authority, partial/conflicting checkpoints, merge and narrative regression.
- Model-output variants: canonical, numbered plus unnumbered continuation, nested list, prose paragraph, table/blockquote wrapper, unknown wrapper names, malformed ambiguity, duplicate ownership, truncated output, and interrupted transport. Stable invariants are ordered ownership, exact source spans/hashes, claim consistency, no new hard issue, unchanged-scope hashes, and next-boundary continuation.
- Resolution status before implementation: `unresolved`.
- Why prior tests missed production: ownership repair was tested independently, while event projection still split on blank lines and no production-shaped test passed the repaired continuation through semantic review and the causal-chain boundary.
- Unresolved user decisions: none.

## Validation closure

Every generated mutation runs: syntax/schema -> ownership/evidence -> local narrative invariants -> adjacent handoff -> whole-story integrity -> quality non-regression -> atomic candidate promotion.

## Rollout

P0 replaces planning transport projection and records the production fixture. P1 adds schema-v3 narrative claims and typed manifest assertions. P2 centralizes failure codes and monotonic recovery. P3 composes genre packs above non-disableable core rules. P4 persists workflow node envelopes, expires route observations by route fingerprint, and exposes read-only automatic diagnostics. The legacy path remains available until comparison and full-suite evidence pass.
