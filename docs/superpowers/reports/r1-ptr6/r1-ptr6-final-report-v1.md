# R1-PTR6 — Reasoning Final Output Reservation Narrow Fix Design

`R1_PTR6_NARROW_FIX_DESIGN_READY`

## Evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `ad3ef1b510b816f27abb252fbd0e7cfbdf5d0b06`
- Starting worktree: clean
- R1-PTR5, R1-PTR4 root-cause, capability-contract and real-observation manifests: exact
- Changes: only `docs/superpowers/reports/r1-ptr6/**`
- `src/**`: unchanged
- `baml_src/**`: unchanged
- External actions: 0

## Root-cause reference

PTR5 confirmed `IMPLICIT_REASONING_CONSUMES_SHARED_COMPLETION_CAP_WITHOUT_FINAL_ARTIFACT_RESERVATION`. Boundary 12 returned one pre-adapter `thinking` block, `finish_reason=max_tokens`, 8,798 reported output tokens, zero visible characters and zero tool calls.

## Current output-budget model

The application sends one `max_tokens` value. For the exact observed fallback call, reasoning and final output shared that cap. There is no reasoning budget and no final-artifact reservation. Budget expansion increases the same undifferentiated pool; primary and fallback use the same request fields and paired attempt budgets but different provider/model/endpoint/capability identities.

The sealed evidence proves that this route can emit implicit reasoning. It does **not** prove that the endpoint supports a reasoning-budget parameter, maximum reasoning tokens, or native final-output reservation. The current `ModelRequest` and `AnthropicAdapter` expose none of those controls. Protocol compatibility alone is not capability evidence.

## Recommended narrow fix

Use `FINAL_ARTIFACT_RESERVATION_WITH_CAPABILITY_GUARD_V1`, which combines Candidate A with Candidate C:

1. Keep the existing per-attempt total output ceiling `T` unchanged.
2. Derive a deterministic final-artifact reserve `F` from the existing `expected_output_characters` and registered contract schema/topology. Do not use the 160-character business-incompleteness floor as the reserve.
3. Set the maximum reasoning allowance `R = T - F`.
4. Dispatch only when a fresh route-fingerprint-bound capability proves that the Provider accepts and enforces the typed reasoning cap.
5. Send `T` as the unchanged total cap and no more than `R` as the reasoning cap.
6. Treat unknown, stale, unsupported, rejected or violated capability as typed route ineligibility/quarantine. Never silently remove the reservation, increase tokens or add a continuation call.

This guarantees that reasoning cannot consume the reserved region only when Provider enforcement is freshly proven. Without that proof, safety is guaranteed by making no Provider call. The reservation does not guarantee valid semantics; canonical conversion and planning validators remain mandatory.

## Exact owner files and functions

- `src/novel_flywheel/context_policy.py`: new `final_artifact_reserve_tokens()` beside `scoped_creative_output_budget()`; owns deterministic reserve sizing without changing total tokens.
- `src/novel_flywheel/domain/models.py`: `ModelRequest`; carries a typed, provider-independent allocation contract.
- `src/novel_flywheel/contract_runtime.py`: `execute_contract_runtime()` and `_dispatch_explicit_route()`; bind contract identity, expected artifact size and T/F/R while retaining the existing attempt schedule.
- `src/novel_flywheel/models.py`: `ModelGateway._complete_resolved()` and `complete_route()`; enforce route capability before adapter invocation.
- `src/novel_flywheel/providers/registry.py`: `ProviderRegistry._effective_capabilities()`; makes allocation capability route-bound, expiring and stale-safe.
- `src/novel_flywheel/providers/anthropic.py`: `AnthropicAdapter.complete()`; only serializes a verified typed cap and keeps `max_tokens=T`.

The shared contract-to-provider allocation boundary is the smallest correct modification location. An adapter-only constant cannot know the artifact requirement; a Contract-Runtime-only change cannot constrain Provider reasoning.

## Candidate comparison

### A — Reasoning budget plus final reservation

Recommended core. It directly partitions the unchanged total cap. Its risk is the authority-critical request boundary, so capability qualification and production-shaped tests are mandatory.

### B — Contract output restructuring

Rejected. Splitting or redesigning `planning_semantic_v2` changes Prompt/schema/merge authority and still leaves every subcall vulnerable to reasoning exhaustion.

### C — Fallback capability boundary

Required guard, but not a standalone fix. It safely prevents calls through unknown or incapable routes; without a capable route it only contains the failure and cannot produce the artifact.

### D — Force strict tool/JSON or add a final-only continuation

Rejected. Strict output shape does not reserve tokens against reasoning. A continuation changes Prompt, Retry, call count, cost and authority handling.

## Expected behavior impact

- Primary route: unchanged when its capability proves no shared reasoning consumption or proves reservation enforcement; otherwise typed ineligible for reservation-required calls.
- Configured fallback: same route and model only if a fresh probe proves enforcement. If unsupported, replacing it is a separate authorization.
- Retry/fallback counts: unchanged; no extra retry or continuation.
- Prompt, Model identity and route configuration: unchanged.
- Total token ceilings and call budget: unchanged.
- Cost: cannot increase by design; realized usage may decrease but is not assumed.
- Latency: no added call; capability refusal may stop earlier.

## Invariants preserved

Prompt bytes, model and route identities, attempt ordering, total token ceilings, `planning_semantic_v2` schema, canonical conversion, domain validators, StoryState/formal authority, checkpoints, resume and promotion gates all remain unchanged. No raw Prompt, story, tool arguments or Provider content enters capability receipts.

## Required implementation tests

Before any production enablement:

- Property tests for `R + F = T`, invalid allocations and unchanged total ceilings.
- Whole/segment/nested `planning_semantic_v2` reserve calibration using sanitized valid artifacts.
- Unknown/stale/unsupported capability refusal before adapter/client/network access.
- Adapter wire tests proving the exact cap is emitted only for a verified allocation contract.
- Parameter rejection, ignored-cap, reasoning-only, mixed, text-only, tool-only, interrupted-stream and incomplete-final cases.
- Production-shaped Boundary 12 fake-provider recovery through canonical conversion and planning domain validation.
- Current-project isolated snapshot plus sanitized isomorphic fixture.
- For a systemic planning implementation, complete offline 13K/20K/30K workflow acceptance through downstream gates.

Current read-only baseline tests: 80 passed, 0 failed; all offline.

## Approval boundary

A fresh production-change approval is required before code/config changes. Because the existing probe did not test reasoning-control enforcement, any real capability qualification needs a new disabled single-use packet and separate final user authorization. A later Full Short Canary also requires its own fresh approval.

`REAL_PROVIDER_CALLS=0`

`PRODUCTION_FIX=NOT_IMPLEMENTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`
