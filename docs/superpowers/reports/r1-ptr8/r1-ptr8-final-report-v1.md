# R1-PTR8 — Final Artifact Reservation Guard Implementation Design

Gate: `R1_PTR8_FINAL_ARTIFACT_GUARD_DESIGN_READY`

## Repository and evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `d68b0f7c5566fca9cb2898e14bfdda06f4480a6b`
- Worktree at entry: clean
- PTR5 manifest: exact, 6/6 entries
- PTR6 manifest: exact, 6/6 entries
- PTR7 real-observation manifest: exact, 16/16 entries
- Production diff: `0`
- Changed scope: `docs/superpowers/reports/r1-ptr8/**` only

## Root-cause reference

PTR5 established that fallback implicit reasoning consumed the shared completion cap without a final-artifact reservation. PTR7 then observed a second provider-level `REASONING_ONLY` result: `finish_reason=max_tokens`, 16,000 output tokens, one thinking block, zero text blocks, zero tool blocks, and zero visible characters. The requested reasoning cap and final-output reservation were accepted at the request surface but behaviorally `IGNORED`; reasoning/output token separation remained `UNKNOWN`.

Therefore the target route cannot be protected by trusting Provider-native reasoning controls.

## Recommended implementation

`FINAL_ARTIFACT_RESERVATION_WITH_CAPABILITY_GUARD_V1` is a provider-neutral, post-response capability guard:

1. Every adapter emits a typed privacy-safe output-shape envelope before normalization.
2. `ModelGateway._complete_resolved` recognizes the exact structured-contract failure only when reasoning exists, text/tool/final-visible content does not, the finish reason is `max_tokens`, the block shape is fully known, and adapter projection is exact.
3. It raises `ReasoningOnlyFinalArtifactError` before conversion and records `reasoning_only_output_limit` against the exact structured route qualification key.
4. `execute_contract_runtime` must not expand the output budget or repeat that fingerprint. It may advance only to a distinct eligible attempt already present in the unchanged route schedule.
5. If no such route exists, it raises `FinalArtifactCapabilityExhaustedError` and preserves accepted checkpoints and authority state.

This is an honest guard boundary: Runtime cannot force token partitioning inside a Provider generation after PTR7 proved the Provider controls are ignored. The design prevents a known-incapable fingerprint from becoming a sticky generic output-limit loop. It avoids terminal failure only when the existing schedule already contains another eligible route; otherwise typed fail-close is required.

## Exact owners

- `src/novel_flywheel/domain/models.py` — `ModelResponse`: typed `ProviderOutputShapeV1` envelope.
- `src/novel_flywheel/providers/anthropic.py` — `AnthropicAdapter.complete`: pre-normalization shape capture only.
- `src/novel_flywheel/providers/openai_chat.py` — `OpenAIChatAdapter.complete`: provider-parity shape capture.
- `src/novel_flywheel/providers/openai_responses.py` — `OpenAIResponsesAdapter.complete`: provider-parity shape capture.
- `src/novel_flywheel/models.py` — `ModelGateway._complete_resolved`: smallest shared typed-detection point.
- `src/novel_flywheel/contract_runtime.py` — `execute_contract_runtime`: recovery and typed terminal owner.
- `src/novel_flywheel/context_policy.py` — `classify_model_failure`: distinct failure classification.
- `src/novel_flywheel/db.py` — `Database.save_structured_route_outcome`: exact negative capability memory.

The Provider adapter must observe but not decide recovery. Contract Runtime and recovery policy require narrow changes. The output validator does not change and remains authoritative whenever text or tool content exists.

## Recovery decision

- Typed fail-close: required baseline.
- Controlled retry: allowed only as advancement to a distinct, already-configured eligible route; it cannot add an attempt, repeat the incapable route, or change the budget.
- Alternate contract: rejected because it changes contract semantics and canonical authority.
- Fallback capability boundary: recommended together with typed fail-close.

No new capability registry or database table is required. Reuse `structured_route_qualifications`, add a typed negative outcome, and bind it to provider, model, route fingerprint, execution mode, contract name, and schema SHA. Parameter acceptance must never create a positive capability claim. PTR7 sealed evidence must not be imported automatically; any live qualification seed is a separate approved state mutation.

## False-positive controls

Reasoning plus text, reasoning plus tool, ordinary truncation with visible content, empty content, adapter projection loss, and unknown block shapes are all separate states. Unknown shapes and projection mismatches fail closed under their own typed classifications; they are not labeled reasoning-only. A complete artifact still follows the existing converter and validators.

## Invariants preserved

Primary-route normal output, Draft, Final Review, Maintenance, Canon, StoryState, and READY authority are unaffected. Prompt, model identity, route configuration, retry schedule, budget, and validators remain unchanged. Only hashes, shapes, counts, typed statuses, and identity bindings may be persisted.

## Required tests

The implementation approval must cover normal text, normal tool, exact reasoning-only/max-tokens, empty response, adapter content loss, unknown block shape, primary-route equivalence, fallback capability boundary, reasoning-plus-text/tool, route-fingerprint and contract/schema isolation, no-route typed terminal, adapter parity, privacy, and external-action-zero tests. A systemic claim additionally requires production-shaped isolated Boundary 12 replay, sanitized isomorphic recovery, and complete 13k/20k/30k planning workflow regression evidence.

## Approval boundary and terminal declarations

- Fresh implementation approval required: `YES`
- `REAL_PROVIDER_CALLS=0`
- `PRODUCTION_FIX=NOT_IMPLEMENTED`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

This report is design-only. No Signed Approval, production modification, qualification seed, Provider call, or Short Canary was performed.
