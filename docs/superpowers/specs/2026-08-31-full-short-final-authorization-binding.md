# Full Short final authorization identity closure

## Decision

`FullShortExecutionPolicyV1` keeps its public schema name but advances its
policy contract to `full-short-trustworthy-execution-v2`. V2 is intentionally
incompatible with pre-existing authorization packets: a fresh candidate and a
fresh user activation are required after the final clean execution HEAD.

The policy owns two canonical identities:

1. `logical_stage_plan` plus its domain-separated SHA-256. The ordered plan
   records every logical occurrence, workflow node, role, contract/schema,
   Contract Runtime input policy, and requested output-token cap. Count and
   distinct-role equivalence are insufficient.
2. `FullShortTransportRecoveryPolicyV1` plus its canonical SHA-256. Its identity
   is `EXACT_REPLAY_ONLY`; its four ordered outcome classes are
   `complete_valid`, `explicit_provider_error`, `proven_pre_response`, and
   `ambiguous`. Network retry count is zero and fresh nonce, redispatch, and
   route switching are false.

Both identities are copied into the live public binding, canonical candidate,
disabled preflight, permission, JIT signed approval, nonce, ledger, and terminal
completion closure. Observer validation compares the next exact plan entry at
the local stage, route, and model-request boundaries before HTTP dispatch.
Completion reconstructs the ordered plan from successful ledger attempts and
requires byte-equivalent canonical identity.

## Compatibility and migration

There is no durable database or project-file migration. The migration rule is
fail-closed packet replacement: V1 policy-version packets, or packets missing
either canonical identity, are rejected before approval, nonce, credentials, or
network access. Re-validating a V2 document is idempotent and preserves both
hashes. Rollback is the single scoped source/test/documentation commit; it does
not alter formal manuscripts, StoryState, providers, credentials, or reports.

## Verification

Offline tests cover exact candidate/preflight acceptance, same-count/same-role
plan reordering, every immutable preflight hash drift, old-packet rejection,
signed-chain identity propagation, stage-order rejection with zero dispatch,
exact completion reconstruction, live public-binding collection, and existing
transport/capture/replay behavior. No credential, Provider client, network, or
paid model call is permitted.
