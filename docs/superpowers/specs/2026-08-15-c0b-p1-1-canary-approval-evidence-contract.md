# C0B-P1.1 Canary Approval Evidence Contract

## Scope

This patch is confined to the Canary control plane. It does not change Production Runtime, prompts, routes, retry/fallback, parsing, validation, StoryState, Canon, Candidate, Checkpoint, Saga, or incident classification.

## Outcome contract

`CanaryBoundaryAbort.kind` is the stable mapping input:

- `preflight` maps to `CANARY_BLOCKED_PRE_PROVIDER`.
- `budget_exhausted` maps to `CANARY_BUDGET_EXHAUSTED`.

The mapping never parses exception text. Both outcomes have `workflow_terminal_counted=false` and `production_incident_counted=false`.

## CanaryBudgetStopEvidenceV1

The receipt is emitted before the refused paid boundary. It contains only hashes, typed metadata, integer ceilings/reservations, and binding states.

Required identity and attempt fields are `run_identifier_hash`, `workload_identifier_hash`, `stage`, `role`, `attempt_ordinal`, `route_kind`, `provider_descriptor_hash`, `model_binding_hash`, and `current_executor_epoch`.

Required budget fields are `budget_dimension_exhausted`, `approved_ceiling`, `already_reserved_amount`, `requested_reservation`, `remaining_amount_before_request`, `ledger_receipt_hash`, `stop_reason_code`, and `stop_receipt_hash`.

Checkpoint and artifact bindings each expose `kind`, `reference`, `identity_sha256`, `revision`, `execution_epoch`, `authority_boundary`, `binding_receipt_sha256`, and `binding_status`. Binding status is one of `exact`, `none_available`, or `unverifiable`.

`exact` requires an existing formally validated/local-semantic checkpoint whose payload binds both the current executor epoch and runtime-execution fingerprint. Missing evidence is never inferred. No checkpoint or business artifact is created by this observer.

Prior causality is retained through `previous_attempt_receipt_hash`, `previous_successful_model_boundary_receipt_hash`, `underlying_previous_failure`, `previous_route_kind`, and `current_requested_next_action`.

Raw prompts, prose, model output, credentials, headers, and absolute user paths are forbidden. References that are not SHA-256 identities are discarded, and an otherwise `exact` binding becomes `unverifiable`.

## Budget reservation semantics

The token ledger emits typed dimensions for `per_run_calls`, `cohort_calls`, `input_tokens`, `output_tokens`, `elapsed_seconds`, and legacy cost. The monetary ledger emits independent `USD` and `CNY` dimensions without FX conversion.

The gateway performs a joint preview under a Canary-local asynchronous lock, commits the elapsed-sensitive token reservation first, then commits the unchanged monetary preview. Budget refusal occurs before final authorization and therefore before credential lookup, provider-client construction, network dispatch, or paid-call accounting.

The launcher Plan retains the C0B-P1 outer ceiling of 144 calls. The Approval carries a hash-bound `approved_budget`; C0B-SMOKE-1 authorizes a 48-call cohort sub-ceiling. The runner enforces the minimum of Plan and Approval ceilings.

## C0BApprovalClosureValidationReceiptV1

Validate-only performs the following ordered checks using only local and hash-bound evidence:

1. Plan canonical/hash
2. Approval canonical/hash
3. Launcher bytes/hash
4. Workload bytes/hash
5. Production source byte revalidation
6. Build fingerprint
7. Build child manifests
8. Execution Config fingerprint
9. Runtime Execution fingerprint
10. Provider Descriptor manifest
11. Role/Route Binding manifest
12. Protocol Route evidence
13. Feature Flag snapshot
14. Phase 1B disabled
15. Pricing Evidence manifest
16. Happy relay group and qwen-max-thinking default-group price
17. Monetary Budget definition
18. Call Budget definition
19. Token Budget definition
20. Elapsed Budget definition
21. Stop Condition manifest
22. Canary root candidate identity/layout
23. Approval execution window
24. Approval cohort/single-use state
25. External action authorization state

The receipt contains the ordered check results, reason codes, definition hashes, a validation receipt SHA-256, and five zero-valued external-action counters. Early canonical failures still return a structured blocked receipt; downstream checks are `not_evaluated` rather than guessed.

Validate-only accepts either a coherent disabled Approval candidate or a coherent named authorized candidate, but it never materializes, reserves, consumes, or executes either one.

## Fail-closed invariants

- Build/config/runtime/route/price/budget/stop/feature/replay drift blocks closure.
- Happy `qwen-max-thinking` must remain on the `default` group at USD 1/M input and USD 4/M output; the test group is not interchangeable.
- A budget stop cannot create or update production incidents or business state.
- Runtime retry/fallback/repair intent is observed, not rescheduled.
- Real Smoke, credentials, provider clients, network, models, and paid calls remain outside this patch.
