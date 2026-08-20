# SC-PTR3-REFRESH — Full Real Short Completion Canary Final Report

## Decision

`NARROW_FIX_REQUIRED`

Exactly one authorized Full Real Short Completion Canary was executed. It stopped at the first workflow terminal and was not retried or resumed.

- `workflow_final_outcome=WORKFLOW_TERMINAL`
- `short_completion_goal_outcome=WORKFLOW_TERMINAL`
- `reason_code=isolated_short_workflow_terminal`
- `typed_root_cause=ContractOutputLimitExhaustedError`
- `safe_failure_class=output_limit`
- `executed_run_count=1`
- `resume_performed=false`
- `second_run_performed=false`

The formal success condition `SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED` was not reached.

## Authorization and single-use consumption

- Confirmed Authorization Patch canonical SHA: `336eb1c4290b4e6bb60af69031d089e7f17709fb9b11cd989ef38ea306d36333`
- Signed Approval canonical SHA: `452843ee1b969ac643917aff9090c42db863300961351adb7260171b6d6d92a5`
- Signed validate-only receipt SHA: `a7365ae888d1e6ba606b8cc3a7695f8a456586471ca861fa1b0a0cc666e69ecc`
- Signed validate-only: `overall_status=exact`; credential/provider/network/model/paid counters all `0`
- Approval reservation receipt definition SHA: `bd74c52e6108845cf4faed728842045733e941dd24fceba5f549ca1c7063f7db`
- Approval consumption receipt definition SHA: `a4475f890c49bf126906ee87eccba78eb4a1841dcc7b2424485baaead1f03377`
- Consumed evidence SHA: `12603909cc4df1edc5419d2fba6a58c789965843328f7cf5fdafc23488ce4e60`
- Cohort `short-completion-ptr3-20260820t041340z-003`: `consumed`
- Approval: `reserved_then_consumed`

## Exact execution identity

- Production Build: `e97060b725a6978f7770c18ec4feb46dd88dc326609355a19d24a1741bcc8bf6`
- Execution Config semantic: `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`
- Runtime Execution: `47c4806b9dd97baac1f982e90481f5ad491f89acad33c23d0408c1d946549f60`
- Launcher: `0eda89a41138ed8996999b1e57b58b8ee03bc1a862ff50f1c1281840a8415faa`
- Collection profile: `production_mirror_short_v1`
- Same-profile preflight: `exact`
- Per-boundary runtime fingerprint status: `exact`
- Prompt Policy: `c341eb13abace08e1f658b1aa1be728de71a5ffc3d32991e493e43ef35fdfabe`
- Provider Descriptor manifest: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`
- Role/Route manifest: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`
- Pricing manifest: `053fbf7d5fe203257dfb200e019c0ac4bdb811f09e244db4f37c906c7667649a`
- PTR3 readiness: `efe2ab7808905d74ca4212e3b8db0646f3c0252f55ac2449d6ef2261e391f943`
- R1-D3 readiness: `63c35701c9edc960010874d4d4f4e13d257561461e007bbdbe0735d5048e6fcc`
- Origin/executor binding: `exact`; conflict count `0`

Prompt, Route/Model, retry/fallback, validators, completion contracts, output budget, and outer budget remained byte/semantic bound to the approved Plan. No production source or configuration was changed.

## Provider/model boundaries

Planning primary identity: provider `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f`, model binding `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff`.

Planning configured fallback identity: provider `98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6`, model binding `fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998`.

| Ordinal | Stage | Route | Request input/output cap | Provider observation | Reported input/output |
|---:|---|---|---:|---|---:|
| 1 | planning | primary | 1,828 / 7,774 | `ConnectError` | unknown / unknown |
| 2 | planning | primary retry | 1,828 / 7,774 | `ConnectError` | unknown / unknown |
| 3 | planning | configured fallback | 1,828 / 7,774 | `end_turn` | 2,253 / 7,204 |
| 4 | planning | configured fallback retry | 1,886 / 7,774 | `max_tokens` | 2,296 / 7,774 |
| 5 | planning | primary | 1,346 / 7,774 | `end_turn` | 0 / 7,936 |
| 6 | planning | primary retry | 1,403 / 7,774 | `end_turn` | 0 / 2,751 |
| 7 | planning | configured fallback | 1,403 / 7,774 | `max_tokens`; no extractable response bytes | 1,880 / 7,774 |
| 8 | planning | configured fallback retry | 1,403 / 15,548 | `end_turn` | 88 / 13,066 |
| 9 | planning | primary | 1,300 / 4,399 | `end_turn` | 0 / 1,784 |
| 10 | planning | primary retry | 1,358 / 4,399 | `end_turn` | 0 / 1,422 |
| 11 | planning | configured fallback | 1,358 / 4,399 | `max_tokens`; no extractable response bytes | 1,821 / 4,399 |
| 12 | planning | configured fallback retry | 1,358 / 8,798 | `max_tokens`; no extractable response bytes | 29 / 8,798 |

Counts: primary `6`; configured fallback `6`; paid/network/model boundaries `12`; targeted Planning domain repair `0`; Draft boundaries `0`.

The reliability trace records three Planning structured/protocol groups, each bounded to two primary-route attempts and two configured-fallback attempts. Eight conversion audits were written: six `semantic_validation_failed` candidates and two `output_truncated` results. No parsed candidate reached a successful Planning domain validation.

## First divergence and terminal cause

- First divergent node: boundary ordinal `1`, `planning / planning-semantic-v2 / primary`, typed failure `ConnectError`.
- Initial masking: the authorized same-route retry and configured fallback masked the transport divergence and allowed observation to continue.
- Terminal divergent node: boundary ordinal `12`, `planning / planning-semantic-v2 / configured_fallback`, `finish_reason=max_tokens`, no extractable response bytes, followed by `ContractOutputLimitExhaustedError`.
- Terminal masking status: `unmasked_terminal`.
- Validator/parser/normalize result: structured/protocol conversion did not produce a domain-valid Planning artifact; aggregate conversion result was six semantic validation failures plus two output-truncated failures.
- Last legal workflow checkpoint: `none_available`.
- Last legal workflow artifact: `none_available`.
- Resumability: `false` by authorization and unavailable checkpoint binding.

Recommended narrow family: Planning structured-output provider boundary normalization and terminal output-limit/content-block handling. The evidence does not justify changing Prompt, Route/Model, retry/fallback counts, budgets, validators, Final Review, or Maintenance. No fix was applied in this run.

## PTR3 and R1-D3 natural-path observations

- Planning PTR3 targeted domain-repair path exercised: `no`.
- Marker: `PTR3_PLANNING_RETRY_PATH_NOT_EXERCISED_BY_THIS_RUN`.
- Finding propagation: not evaluated by this real run because no Planning candidate crossed the protocol/conversion boundary into the targeted domain-repair path.
- `stale_finding_count`: not observed; the approved expected value remains `0` but is not claimed as real-run convergence evidence.
- PTR3 convergence: not demonstrated by this run.
- Natural Provider fallback/output-limit shape reached: `yes`; see boundaries 3-4, 7-8, and 11-12.
- Historical `provider_terminal_amplifier_shape=residual_unclosed`: naturally reproduced as a narrow terminal-output family and remains unclosed.
- Draft R1-D3 path exercised: `no`; Draft was never reached.
- Marker: `R1_D3_RETRY_PATH_NOT_EXERCISED_BY_THIS_RUN`.
- Draft convergence/finding replacement/stale finding evidence: not observed.
- `draft.retry_scope_too_broad=residual` remains unchanged and unexercised.

## Budget and usage

- Elapsed: `1,402.283713 seconds` (`1,402,283,713 µs`), within `7,200 seconds`.
- Calls: `12 / 48`; expected topology was `16`, but the first terminal stopped execution.
- Reserved token envelope: input `18,299`; output `91,961`.
- Provider-reported known usage: input `8,367`; output `62,908`.
- Two transport-failed calls have unknown reported input/output usage.
- Cached-input and reasoning-token values were not supplied by Provider receipts and remain `unknown`; they are not asserted as zero.
- Known reconciled cost: `USD 0.205146`; `CNY 0.095030`.
- Conservative retained reservations: `USD 0.220161`; `CNY 0.283211`.
- All token, elapsed, call, USD, and CNY limits remained within the approved budget.

## Completion verifier

- Workflow status: `failed`.
- Final manuscript SHA: `null`; formal final manuscript unbound.
- Draft validator: `unverifiable_or_not_passed`.
- Final Review: verdict `missing`, accepted status `not_accepted`, binding `unknown`.
- QualityCheckpointV1: missing; outcome/hashes `null`.
- Maintenance: not executed; receipt/journal missing.
- Final artifact binding: `unbound`.
- Final checkpoint closure: `unclosed`.
- Unresolved terminal status: `present`.
- Completion verification receipt SHA: `c88d7dd6310bbbd27d2eb37e75206d23ab713a45e1c053477e0fe65b7ad04015`.

Because the workflow terminal occurred in Planning, absence of downstream Draft, Final Review, Maintenance, final artifact, and final checkpoint evidence is causal rather than a separate verifier defect. Therefore the Gate is `NARROW_FIX_REQUIRED`, not `SHORT_COMPLETION_VERIFICATION_FAILED`.

## Isolation, privacy, and sealing

- Live parity: `exact`.
- Live parity before/after SHA: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
- Live active run count before execution: `0`.
- Production incident counted: `false`.
- Evidence package includes raw content: `false`.
- Canary evidence privacy scan: `exact`; credentials, headers, raw prompt, and raw story are absent.
- Official evidence canonical SHA: `12603909cc4df1edc5419d2fba6a58c789965843328f7cf5fdafc23488ce4e60`.
- SHA-256 file manifest: `sc-ptr3-refresh-real-short-sha256-manifest-v1.json`.
- Evidence-only commit: the Git commit containing this report and manifest; its immutable commit ID is reported after sealing because a commit cannot self-contain its own hash.

## Stop

No second Canary, new approval, automatic production fix, Pilot, Phase1B, or long-form execution is authorized or performed.

`NARROW_FIX_REQUIRED`
