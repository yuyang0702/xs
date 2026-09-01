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

## Durable dispatch readiness and closed-ledger rule

Nonce reservation through the production predispatch path requires one exact
`FullShortDispatchReadinessReceiptV1`. The receipt is closed to unknown fields
and binds the policy, logical stage plan, permission, signed approval, current
predispatch ledger, observer session, first logical/physical attempt, request,
route, destination and egress hashes, all dispatch/token/elapsed caps, and the
zero-before-commit provider, HTTP, network, response and completed-stage
counters. Validation occurs under the store lock against the re-read sealed
ledger before the exclusive nonce write. The sealed readiness body is retained
inside the nonce record and must match the first durable attempt before nonce
consumption.

Closed attempt records are immutable even when their state is unchanged. An
ordinary mutation cannot revise a failure code, hash, capture evidence,
rejection receipt, response status, or terminal metadata. The only narrower
mutation class is `CAPTURE_RECEIPT_RECONCILIATION`: after exact offline envelope
audit and replay, it may change one absent capture receipt to a valid SHA-256
and its paired absent completeness value to `true`. It cannot change state,
failure provenance, other evidence, counters, stage receipts, or authority.

## Compatibility and migration

There is no durable database or project-file migration. The migration rule is
fail-closed packet replacement: V1 policy-version packets, packets missing
either canonical identity, and old or partial dispatch-readiness bodies are
rejected before approval or nonce reservation as applicable. Re-validating a
current policy or readiness document is idempotent and preserves its complete
canonical body and hashes. A nonce already left in the pending crash state is
never migrated or resumed. Rollback is the single scoped
source/test/documentation change; it does not alter formal manuscripts,
StoryState, providers, credentials, or reports.

## Verification

Offline tests cover exact candidate/preflight acceptance, same-count/same-role
plan reordering, every immutable preflight hash drift, old-packet rejection,
signed-chain identity propagation, stage-order rejection with zero dispatch,
exact completion reconstruction, live public-binding collection, and existing
transport/capture/replay behavior. No credential, Provider client, network, or
paid model call is permitted.

Readiness tests additionally cover empty and missing documents, wrong counter
types, policy/session/ledger/counter/cap drift, validation idempotence, first
attempt mismatch, and successful nonce-to-dispatch continuation. Ledger tests
cover closed failure/evidence overwrite attempts plus exact capture receipt
completion on an already closed attempt.
