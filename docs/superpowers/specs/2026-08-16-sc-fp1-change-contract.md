# SC-FP1 Change Contract

## Requested outcome

Version the Runtime execution-config identity so equivalent effective feature-flag
values have one behavior hash while source provenance remains independently
hash-bound; preserve fail-closed behavior for real semantic drift; expose typed
pre-provider Canary failures; then materialize a new inert Short Completion packet
with operational Ledger readiness and an offline subprocess rehearsal.

## Scope and authorization

- Scope classification: `open_world`, bounded by a versioned controlled-flag
  registry. Unknown or missing registry members fail closed.
- Authorization: implementation plus offline operational materialization.
- Risk level: `L2`. Runtime identity and Canary diagnostics change; story
  authority, production workflows, prompts, routes, retry/fallback, validators,
  Final Review, Maintenance, credentials, and paid boundaries remain unchanged.
- Resolution target: `systemically_resolved` for controlled typed boolean flags,
  not a two-name exception.

## Current evidence

- SC-OPS-1 materialization observed `defaulted=false`; the real runner observed
  `set=false` for the same two disabled diagnostic flags.
- V1 included presence in the execution behavior hash and blocked before Provider.
- The old Approval is reserved, not consumed, and permanently replay-blocked.
- All external-action counters were zero and live parity remained exact.

## Allowed behavior change

- New V2 semantic fingerprints collapse source-presence differences only after
  the shared typed resolver proves the effective value equal.
- V2 provenance definitions remain different when source presence differs.
- Genuine value, parser, registry, policy, precedence, or integrity drift remains
  a pre-provider block with a stable typed reason.
- Canary launcher preserves typed preflight failures instead of replacing them
  with a generic infrastructure outcome.

## Protected unchanged behavior

- No change to model prompts, calls, routes, retry/fallback, output budgets,
  narrative validators, StoryState, Canon, candidates, checkpoints, Final Review,
  Maintenance, or formal manuscripts.
- No old approval, reservation, Cohort, Plan, Candidate, Patch, or Signed Approval
  is modified, released, reset, deleted, reused, or reauthorized.
- V1 definitions remain readable and independently verifiable.
- New Candidate remains non-executable and creates no credential, client,
  network, model, or paid action.

## Selected approach

- Add an immutable controlled-flag registry with versioned default, parser, and
  precedence policy hashes.
- Add `EffectiveFeatureFlagSnapshotV2`,
  `FeatureFlagProvenanceSnapshotV1`,
  `RuntimeExecutionConfigFingerprintV2`, and
  `RuntimeExecutionFingerprintV2`.
- Make the V2 execution-config fingerprint depend only on semantic child hashes;
  keep provenance in the parent definition graph and definition hash.
- Route Materialization and real-run capture through the same resolver.
- Add a typed, hash-only preflight component diff.
- Add a formal empty-ledger initializer/readiness receipt and subprocess
  pre-launch rehearsal before emitting the new Candidate packet.

## Rejected alternatives

- Ignore presence for two named flags: forbidden sample-specific narrowing.
- Change V1 hashing in place: would reinterpret historical evidence.
- Remove provenance: would destroy diagnostic lineage.
- Treat all malformed strings as false: would conceal unknown behavior.
- Release the old reservation: would weaken single-use safety.

## Rollback

Revert SC-FP1 source commits and remove only the newly materialized SC-FP1
inert packet and its empty operational roots. Historical V1 evidence and the old
reserved Ledger remain untouched. No production-data rollback is required.

## Test contract

- Focused: V2 resolver equivalence/drift/integrity, V1 readability, typed outcome.
- Adjacent: C0B, PA, and Short profiles; approval closure; preflight and goal-stop.
- Production-shaped offline: reproduce Materialization-defaulted versus
  runner-explicit-false and reach a fake paid boundary with all external counters
  zero.
- Parity: Prompt/Route/Retry/validator/final-review/maintenance source hashes and
  live business artifacts remain exact.
- Full suite: no new hard failures relative to the task baseline.

## Requirement traceability

| Requirement | Implementation boundary | Acceptance evidence |
|---|---|---|
| Semantic/provenance split | `runtime_fingerprint.py` V2 definitions | distinct provenance, equal semantic/config/runtime hashes |
| Versioned default/parser/precedence | controlled registry and policy manifests | policy hash and mutation tests |
| Shared resolver | Runtime collection used by packet and runner | subprocess rehearsal |
| True/false/unknown fail closed | strict typed resolver and preflight | mutation matrix |
| Typed preflight outcome | Canary preflight and launcher mapping | zero-boundary failure tests |
| V1 compatibility | unchanged V1 definitions/store verification | historical graph tests |
| Single-use preservation | unchanged reservation semantics | locked-old-cohort tests |
| Operational readiness | formal Ledger initializer/readiness receipt | empty/sentinel/identity tests |
| No business behavior change | source/hash parity checks | strict gate and full suite |

## Model-output and downstream risk

No model-output parser, prompt, generated artifact, narrative validator, or formal
promotion boundary changes. Planning through Maintenance consume the same model
and business paths; only the pre-provider Canary identity gate changes.
