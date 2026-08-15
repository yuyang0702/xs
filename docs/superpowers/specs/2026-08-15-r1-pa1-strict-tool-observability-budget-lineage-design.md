# R1-PA1 strict-tool observability and budget-lineage change contract

## Authorization and scope

- Requested outcome: add hash-only strict-tool request/raw/normalized/gateway observations, output-budget lineage, an offline retained-budget counterfactual, regression evidence, and unapproved Canary drafts.
- Authorization: implementation, restricted to R1-PA1A through R1-PA1D.
- Risk: L3 because the observations cross model routing, generated-output parsing, fallback, and output-budget boundaries.
- Scope classification: closed-world instrumentation of the registered `planning_adaptation_whole` fallback boundary. The observer is not a general strict-tool policy change.
- Resolution status: unresolved. This phase closes evidence gaps and does not repair either production mechanism.

## Current evidence

- R1-PA0 evidence canonical SHA-256: `73b4da607fd400d90fa81d6460da886297ccdd48760c4b1c12f301c015c49be3`.
- The three Whole primary requests used `[1276, 1276, 1276]` because each outer receipt attempt constructed a new Contract Runtime.
- Whole fallback raised `RuntimeError: strict structured tool route returned no unique artifact` before parser, local normalization, schema, adapter, or domain validation.
- The provider raw shape was not persisted and remains unverifiable.

## Allowed change

- Disabled-by-default diagnostic flags and their fingerprint registration.
- Sanitized provider snapshots, fail-open observer callbacks, deterministic lineage identities, physically isolated trace events, test-only counterfactual code, tests, reports, and Canary contracts.

## Protected unchanged behavior

- Provider requests, prompts, schemas, tool declarations, routes, retry/fallback counts, output budgets, acceptance/rejection logic, exception identity and chaining, checkpoint behavior, Segment deterministic merge, StoryState, Canon, Candidate, Saga, formal prose, Phase 1B, and live incident records.
- No paid/network model call and no Canary execution.

## Authority impact

- Formal manuscript, Candidate, protected best, StoryState, Canon, narrative receipts, SQLite rows/schema, credentials, UI/API, resume and formal rollback: read-only or not involved.
- Provider/model binding and Runtime route decisions: read-only.
- Reliability trace and test/Canary diagnostic artifacts: changed, non-authoritative, hash-only, physically isolated, and reversible.

## Selected approach

1. Preserve the provider-visible raw topology as sanitized hash-only metadata before adapter normalization.
2. Correlate request, raw, normalized, and Gateway layers with one deterministic shape correlation hash.
3. Emit only at the controlled Whole fallback target; count all other strict-tool calls as excluded without full shape records.
4. Observe Runtime construction, dispatch, expansion decision and outer reconstruction without carrying expansion state into a later request.
5. Derive the retained-budget counterfactual from the production expansion policy in test code only.

Rejected alternatives include persisting raw provider content, changing `ToolCall.arguments`, parsing provider state centrally after adapter loss, wrapping adapter exceptions, matching Prompt text, or implementing a Canary B behavior switch in this phase.

## Rollback

Both flags default off. Commits are independently revertible in reverse order. There is no migration, database write, project artifact, or alternate authority path to roll back.

## Verification

- Focused request/raw/normalized/gateway shape matrix for all approved cases and all three production adapters.
- Exception type, message, traceback, cause/context, failure classification and route-exhaustion parity.
- Exact Segment/Whole/checkpoint, Prompt, route, retry, call, artifact and live parity.
- Dynamic counterfactual, cap lineage, privacy scan, sink-failure test, performance/storage measurement, related tests and full suite.
