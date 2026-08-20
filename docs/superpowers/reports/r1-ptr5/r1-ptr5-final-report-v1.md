# R1-PTR5 — Planning Reasoning Output Allocation Root Cause Investigation

`R1_PTR5_ROOT_CAUSE_INVESTIGATION_READY`

## Scope and evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `7e45fb6ccd02c56eb49448f64c0a8ff38b4327ca`
- Starting worktree: clean
- Changes: only `docs/superpowers/reports/r1-ptr5/**`
- R1-PTR4 and original Full Short sealed manifests: exact
- Historical Provider Probe live parity: exact
- Current external actions: 0
- `src/**`: unchanged
- `baml_src/**`: unchanged

## Boundary 12 evidence summary

The exact probe observed the Provider response before normalization. The configured fallback returned one `thinking` block, no text block, no tool call and no unknown block. `finish_reason=max_tokens`; requested max output and reported output were both 8,798 tokens; visible characters were zero. Therefore the final artifact was absent before the adapter ran.

This rules out adapter visible-content loss, tool-argument truncation and ordinary text truncation for Boundary 12.

## Request analysis

Boundary 12 retained the `planning_semantic_v2` contract (`f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`). It requested one canonical JSON artifact with `initial_state` and one locally terminal segment containing two owned formal events. Deterministic local reconstruction estimates about 1,358 input tokens; the compact schema is 2,172 bytes.

The contract is semantically demanding: it asks for chronology, knowledge, relationships, promises, setup/payoff and ending consistency while obeying a strict output shape. That complexity can induce reasoning. It is not, however, large enough to explain 8,798 tokens of reasoning-only output by itself. The Provider-reported input count of 29 is not treated as request-size evidence because it may reflect Provider accounting or caching semantics.

## Provider configuration and allocation analysis

The Anthropic request carried one shared `max_tokens` value. It did not send an explicit thinking enablement, thinking budget, reasoning effort, final-output reserve, tool choice or structured `output_config`. No model context window or provider max-output ceiling was declared locally for this route.

Primary and fallback attempts used the same application request fields and corresponding budgets, but they did not use the same provider, model, endpoint or capability identity. The observed fallback model produced implicit/provider-default reasoning under the plain request.

For this exact call, `max_tokens` included reasoning: the Provider reported 8,798 output tokens, equal to the requested cap, and its only block was `thinking`. There were no separately configured reasoning and final budgets. The realized allocation was therefore 8,798 reasoning tokens and zero visible final output.

## Recovery chain: Boundary 3 to Boundary 12

Boundary 3 was the first unrecovered divergence: transport succeeded and a JSON candidate existed, but semantic normalization rejected it before the domain validator. Subsequent protocol retries appended regeneration guidance; capacity recovery reduced ownership from whole packet to segment and then nested segment. The contract did not change.

At fallback output-limit boundaries the runtime doubled the shared completion cap, including 4,399 to 8,798 between Boundaries 11 and 12. It did not reserve any capacity for a final artifact or constrain reasoning. Sticky output-limit state then amplified the unresolved conversion failures into terminal `ContractOutputLimitExhaustedError`.

## Root-cause decision

Immediate mechanism, confirmed for this exact route/request:

`IMPLICIT_REASONING_CONSUMES_SHARED_COMPLETION_CAP_WITHOUT_FINAL_ARTIFACT_RESERVATION`

This is valid behavior for a reasoning-capable Provider endpoint, but it violates the application contract's need for a final structured artifact. The primary application-side failure is an output-allocation/control gap at the route-capability and adapter boundary. Provider/model default reasoning behavior is the trigger. Missing reasoning semantics in route capability metadata is a strong contributor. Contract complexity is a contributor, not the root cause.

The exact Provider-internal reasoning policy remains unresolved: no explicit thinking control was sent and no sealed local evidence exposes the Provider's hidden allocation rule. The investigation is ready; systemic resolution and production recovery are not implemented.

## Required answers

1. **Why was there no final artifact?** The fallback model consumed the entire shared 8,798-token completion allowance in one reasoning block and reached `max_tokens` before emitting text or a tool call.
2. **Did thinking fill the output budget?** Yes for the observed call: output tokens equalled the cap and the sole block was `thinking`.
3. **How did `max_tokens` affect thinking/final?** It bounded the combined generated output, including thinking, without a separately protected final-artifact allowance.
4. **Did configured fallback differ from primary?** Application request fields and paired budgets were the same. Provider, model, endpoint and capability identities differed; neither route received an explicit thinking parameter.
5. **Was `planning_semantic_v2` too large or complex?** It was nontrivial but not too large in the exact nested case: about 1,358 estimated input tokens, two events and a 2,172-byte compact schema. It cannot be the sole cause.
6. **Was `reasoning_budget > final_output_budget`?** No separate configured numeric budgets existed. Observed realization was effectively 8,798 reasoning tokens versus zero visible final output.
7. **What is the minimum fix direction?** Introduce capability-bound reasoning/final allocation semantics at the shared gateway/provider boundary: keep the total cap unchanged, bound reasoning below it and reserve final-artifact capacity; if a route cannot guarantee that contract, treat it as ineligible. This is only a proposed fix family and requires separate production authorization.

## Candidate root causes and disproved hypotheses

Ranked causes:

1. Confirmed immediate cause: implicit reasoning exhausted the shared cap without final reservation.
2. Strong contributor: route capability/configuration does not describe or control reasoning allocation.
3. Runtime amplifier: budget expansion enlarged the same undifferentiated pool; sticky output-limit selected the terminal exception.
4. Secondary contributor: semantic and protocol obligations can increase reasoning demand.

Disproved for Boundary 12: adapter loss, tool truncation, normal text truncation, strict-tool conversion, input/context overflow, validator rejection of a final artifact, PTR3 finding propagation, primary ConnectError as terminal cause, and a hard 8,798-token Provider ceiling. Increasing tokens alone is also not a reliable fix: the larger cap was still entirely consumed by reasoning.

## Recommended narrow fix family

`CAPABILITY_BOUND_REASONING_FINAL_OUTPUT_RESERVATION`

The recommendation does not authorize a Prompt, Model, Route, Retry, Budget, validator or production-runtime change. It does not recommend a blanket thinking disablement or a token increase. Any implementation requires a new, separately reviewed production change.

## Verification

- Focused offline fake tests: 64 passed, 0 failed
- Privacy scan: exact; no raw Prompt, story, tool arguments, Provider content, credentials or endpoints
- Current Provider/network/model/paid calls: 0

`REAL_PROVIDER_CALLS=0`

`PRODUCTION_FIX=NOT_IMPLEMENTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`
