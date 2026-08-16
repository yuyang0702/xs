# SHORT-COMPLETION-R1D3-FINAL — Execution Report

## Final outcome

- `workflow_final_outcome`: `WORKFLOW_TERMINAL`
- `short_completion_goal_outcome`: `WORKFLOW_TERMINAL`
- Next gate: `NARROW_FIX_REQUIRED`
- Exactly one real `short-normal-v1` workflow executed.
- The single-use Cohort is consumed and must not be replayed.
- No second run, Pilot, Phase 1B, Long workflow, Prompt change, route change, retry increase, validator change, or code fix was performed.

The R1-D3 Draft retry path was not reached. This execution therefore does not validate or invalidate R1-D3 finding propagation in production; it records `R1_D3_RETRY_PATH_NOT_EXERCISED_BY_THIS_RUN`.

## Approval and execution identity

- Authorized branch: `sc-r1d3-gate-1/fingerprint-profile-separation-20260816`
- Authorized execution HEAD: `b94063b1c0a53950d8d452c2ac68d98594c2b761`
- Profile: `short_completion_1`
- Scope: `SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY`
- Collection profile: `production_mirror_short_v1`
- Runtime fingerprint policy: `runtime-fingerprint-v2`
- Cohort: `short-completion-r1d3-g1-20260816t154912z`
- Plan: `876c941ed613adb97eae1a9f585b4bf28b807d921c00f66c4b3969fcdc0b15d5`
- Candidate: `bd37c998ffe81b5a2f4fe177e686b614fc834d667dab1ba0d0a64b8944575c03`
- Confirmed Authorization Patch: `5b5ba34e08b834667f7f76c897cd8209a03c7a83caa13a7562e4494adb77177d`
- Signed Approval: `a793b1794bcad50a622af60ec79aa507af1565a71fc3267473678786629dc574`
- Signed Approval validate-only receipt: `3edbff96abc9c849f8a49acab7891b5840edcf6679f96eb35509c1f8c0b75013`
- Reservation receipt: `40c279a62c22c006c94d387e197b5f5e19121fae1286e1c8ef2133d1071b6192`
- Consumption receipt: `f421dba432121b12f3a8fae96454c2c963ab20c7e55232044d1a2609383692fc`
- Evidence Package: `d431e377a9924ad8fa1fde8ab3cd278e612ae563adc2e0eca53444284b7c29ab`

Before validate-only, Credential, Provider client, network, model, and paid-call counts were all zero. Validate-only returned `signed_approval_exact_and_executable`; the Ledger and Cohort were both unused.

## Same-profile Production-Mirror gate

- Build: `771f86c5c735fcc39cb499e9a87014b226ab20c60abf3e148393de1e4268a59a`
- Execution Config: `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa`
- Runtime Execution: `1efd51615c3f6274c52042eb4056402db2844ad9d02cc227b3e23ac294ec57e1`
- R1-D3 Production-Mirror readiness: `e0f3e91d63a754a69b0759a88d77c0625f7925fb0d929f031ec87f96bd800025`
- Independent rehearsal receipt: `c512c5dedf4e81ee05a367cf334b4769b7848cb0312e84cfdb9eaab8208500b8`
- Same-profile Config comparison: `exact`
- Same-profile Runtime comparison: `exact`
- Semantic equality: `true`
- Provenance known: `true`
- Provenance equality: `false`
- Typed status: `equivalent_provenance_variation`

All 10 Provider boundaries independently passed the same-profile Runtime preflight. No fingerprint mismatch or source drift occurred.

## Model boundaries and budget

- Real Provider boundaries: 10
- Credential lookups: 10
- Provider clients: 10
- Network calls: 10
- Paid model calls: 10
- Primary-route calls: 7
- Configured-fallback calls: 3
- `protocol_receipt_route_failed` events: 3
- `protocol_receipt_model_fallback` events: 1
- Output-limit expansions: 1
- Planning targeted-repair model calls: 4, ordinals 7–10
- Draft regeneration calls: 0
- Separate Repair-stage calls: 0
- Reported input tokens: 20,225
- Reported output tokens: 13,258
- Cached input tokens: not reported
- Reasoning tokens: not reported
- Actual USD cost: 0.070399
- Actual CNY cost: 0.015206
- Elapsed: 244.251454 seconds
- Budget stop: none

The exact hash-only 10-row boundary ledger, including route kind, protocol, contract hash, Provider/model binding hashes, requested budgets, finish reasons, usage, response hashes, and system/user Prompt hashes, is sealed as `ShortCompletionR1D3FinalModelBoundaryLedgerV1` with definition SHA `57daca7a97d7a689aed5b79c704040bbb7d79e2885c5ad57c0262aaeb61f56b7`.

## First divergence and terminal causal chain

An earlier capacity divergence was recovered:

1. Boundary 2, Planning Adaptation Review, returned `max_tokens`.
2. Runtime requested a capacity split.
3. Boundaries 3–5, `planning_adaptation_segment` primary route, each ended at `max_tokens` and produced `protocol_route_output_limit`.
4. Boundary 6, configured fallback, returned a valid exact-JSON segment receipt and created a `generated_complete` checkpoint.

The terminal chain then began:

1. Boundary 7, `planning_repair_patch`, returned exact JSON and passed conversion semantics, but failed Domain Validation with `ValueError`.
2. Boundary 8 repeated the same typed Domain Validation failure.
3. Boundary 9 moved to configured fallback and ended at `max_tokens`.
4. Runtime expanded the repair-patch output budget from 1,977 to 3,954.
5. Boundary 10 again ended at `max_tokens`.
6. Contract Runtime raised `ContractOutputLimitExhaustedError`; workflow status became failed.

The first terminal-chain divergent node is therefore boundary 7, not the recovered boundary-2 capacity event. The suggested narrow family is observation-only:

`planning_adaptation_targeted_repair_domain_rejection_then_output_limit_exhausted`

The inner chain retained typed evidence, but the stage projection became `provider.request_failed / stage.execution_failed` and the stored incident projection became `unclassified.aa7850af19977c6b`. This is classified as `typed_inner_chain_outer_unclassified`; no incident-classification code was changed.

First-divergence receipt: `c838d73de7628bfcc2b84f45b09cffe48a6050724adb07c455bf4506be8838ce`.

## Checkpoint and resumability

Last legal artifacts:

- `planning-semantic-v2`: output `acd1f31e46dcb92261d6ddf3493d657da9fa42fcbe2a7bddcca46f54ab524465`, status `generated_complete`.
- fallback Planning Adaptation segment receipt: output `853d1a28b6436c9689be6bc5fa70a831795e14d63a663c3a01827b43dc08a526`, status `generated_complete`.

Terminal checkpoint:

- node: `planning-adaptation-segment-01-attempt-1`
- input: `7b73e336f90625b1348b9db4d5757c3b8f4d7ff140eea6a2a9a0dddc9238c8df`
- output: absent
- status: `failed`
- validation stage: `transport`

The stage envelope advertised `resume_stage`, but workflow supervision persisted `automatic_recovery_exhausted / irrecoverable`. Exact safe automatic resume is therefore `unproven_not_authorized`; no resume was attempted.

## R1-D3 Draft retry closure

- Draft stage reached: false
- Mixed-script rejection observed: false
- Structured Draft finding generated: not applicable
- Exact actionable finding propagated to retry: not applicable
- Same-scope retry convergence: not applicable
- Observation status: `R1_D3_RETRY_PATH_NOT_EXERCISED_BY_THIS_RUN`

R1-D3 retry closure definition: `008292c5c79db9b9ff3786eea39951874974cfcde12d44df53a5bf97a6bffb3f`.

## Final Review, Maintenance, artifact, and checkpoint closure

- Final manuscript: absent
- Draft validation: `unverifiable_or_not_passed`
- Final Review contract: `short_formal_quality_authority v1`
- Final Review verdict: `missing`
- Final Review binding: `unknown`
- Quality checkpoint: absent; closure `unclosed`
- Maintenance executed: false
- Maintenance receipt: absent
- ProjectMutationJournal for Short Maintenance: absent
- Final artifact binding: `unbound`
- Unresolved terminal: present

Completion closure definition: `882fcff2e9e715e3b361663aab14a1367ce414716dfbb79b7377810ac07453a2`.

## Prompt, route, retry, privacy, and live parity

- Prompt Policy: `72282e5c12a101592d26d18d15a618afcd6b10688f4d79bac902c9337579d68c`
- Initial Draft Prompt: `24ff78bda316093b453844cd276a8105ed1e9a79839f168d944b28883d5befad`
- Retry-only Draft Prompt: `c1cde435c0caf77ac98f05aae9f95385f1486250384ff914b8729949283d3171`
- Prompt Policy remained exact. Neither Draft Prompt was dispatched because Draft was not reached.
- Route/model/protocol bindings remained exact at every boundary.
- Runtime-owned retries/fallbacks were not increased or changed by the Canary.
- Raw Prompt, story prose, tool arguments, Credential, Header, complete Provider response, absolute path, live project identifier, project name, and character name are excluded from committed evidence.
- Provider/model identities are represented only by approved hashes.
- Live parity before/after: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` / same.
- Live DB: `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3` / unchanged.
- Formal story: `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745` / unchanged.
- Canon: `5361f3729dd191e987f2494cb7bac1ebf15d9a9837465208262e3ee3f24f49fc` / unchanged.
- StoryState rows: 6 / unchanged.
- Candidate rows: 11 / unchanged.
- Checkpoint rows: 917 / unchanged.
- Production incident count: unchanged, proven by full live DB parity and `production_incident_counted=false`.

Live-parity receipt: `eacaf67d37ce6f827e4b29489acc7325e9d7abbea2a6526df24b7a3c925e732b`.

## Final gate

`NARROW_FIX_REQUIRED`

The next task must remain narrowly scoped to the Planning Adaptation targeted-repair chain: why exact-JSON `planning_repair_patch` candidates at boundaries 7 and 8 fail Domain Validation, and why the configured fallback then exhausts its output limit despite one bounded expansion. Do not modify R1-D3 Draft behavior based on this run because that path was not exercised.
