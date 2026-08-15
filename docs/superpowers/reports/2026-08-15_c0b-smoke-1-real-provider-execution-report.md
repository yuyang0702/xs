# C0B-SMOKE-1 Real-provider Execution Report

日期：2026-08-15  
Branch：`c0b-p1-2/signed-smoke-approval-contract-20260815`  
执行 HEAD：`3be39a6d61da31b864b13c99cb687adacd8047fd`  
Single-use cohort：`c0b-smoke-1-p12-20260815t072000z-f9fbd60`

## 1. Final Outcome

**WORKFLOW_TERMINAL**

- Reason code：`isolated_short_workflow_terminal`
- Final run status：`failed`
- Typed outer exception：`ProtocolReceiptRouteExhaustedError`
- Safe failure class：`normal_invalid_output`
- Production incident counted：`false`
- Budget stop：无
- Controlled provider capability outcome：无；现有证据不足以把本次结果改标为 provider capability outcome
- 下一步：**NARROW_FIX_REQUIRED**

本次只执行了一个 run。首次 terminal 后未重跑，Cohort 已消费，且 `resume_after_terminal=false`。未启动 C0B-PILOT-5、R1、Phase 1C 或 Phase 1D。

## 2. Approval Materialization and Closure

| Artifact | Canonical/self SHA-256 | File-byte SHA-256 | Result |
|---|---|---|---|
| Confirmed Authorization Patch V2 | `ff0a8ed656ab4d5ee5432f2574d03026b3e7d9902ebce41fb5f5bec3cc7fe3fe` | `8ab7b98bdff21bf80ffcf4b1037ebabb5a8f4088cc4dfabc9b29578cd5eb02b9` | Materialized as a new file; template unchanged |
| C0BSmoke1SignedApprovalV1 | `1ec4be7f8d4a8beb64da47c9b9af44ea9e705b75b8e5007353f553d74fb032f5` | `ab7d130f597029f80c2d729e6a4cdcc74faa5fe68eea427bb4f199971b74dfcb` | Exact and executable before reservation |
| Signed validate-only receipt | `e9ea016b405b10dc85e6f230922ec22113188ec8ed59e72bf7d6b938c94f5e83` | `87dbbc175dec18189c8ae6a4af837688a2533ac077b13085adc2583823c5af45` | `28/28` exact; all external counters remained zero during validate-only |
| Canary evidence package | `73b4da607fd400d90fa81d6460da886297ccdd48760c4b1c12f301c015c49be3` | `58bcf22b59f0327f0f3ca63b44d8f2a93d4a4d759caf583181def873a627e8d3` | Valid, sanitized, `raw_content_included=false` |

Canonical/self hashes use the artifact's declared canonicalization; file-byte hashes are ordinary SHA-256 over the stored JSON bytes. They are intentionally reported separately.

The signed closure bound the approved Plan, Candidate, Patch template, Launcher, Workload, Workload Manifest, Build, Config, Runtime, Provider Descriptor, Role/Route Binding, Pricing, Cohort, budget, stop conditions, and execution window exactly. No Plan, Route, Prompt, model, Runtime, fallback, budget, or feature flag was changed.

## 3. Approval Reserve and Consume

| State | Schema | Definition SHA-256 | File SHA-256 | Binding |
|---|---|---|---|---|
| Reserved | `CanaryApprovalReservationV1` | `7dafe944d659b4c65203bc7b41002e979b5ba4e3bb8780116db45e2075184c0c` | `a4fcc1126a039a8c9b231551af2f6520951028246d96aab9d9a5179abc5e9973` | Plan, Signed Approval, Cohort exact |
| Consumed | `CanaryApprovalConsumptionV1` | `b5beaa00e134f726d53e91cbd7d0f5df9b31737f8dff2b9c9e083f055d4d592c` | `eac45be4933c9f2230b705e12b3385f0109c7a4214a07886cb002dd2ed3ddb3f` | Evidence `73b4da…`, Signed Approval exact |

消费记录已存在，因此该 Single-use Cohort 不可再次执行。

## 4. Origin / Executor Fingerprint

- Binding status：`exact`
- Conflict count：`0`
- Origin definition SHA-256：`9b079a7887cadf374f332620774053e9deec2a67499cc55501a6c193685fa13a`
- Executor definition SHA-256：`d40bc6f1aac37aa449f668d73ce76590030135eb0a77c557aa3d084c2d24a986`
- Build fingerprint：`bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0`
- Execution config fingerprint：`70a487fa8f2152e14923aa82560ace39c83a052e4556e03eb1b54ba4976bff13`
- Runtime execution fingerprint：`eb2ed19dd0b6b9a7517f6044f4a8aecb0aadfcb9f2e1303f3ba77567a8b710a5`
- Per-boundary runtime fingerprint status：`exact` for all 11 boundaries
- Preflight receipt status：`exact` for all 11 boundaries

## 5. Real Model Boundary Ledger

All boundaries used the frozen Anthropic-compatible protocol. Provider aliases and model aliases are reported without endpoint URLs. `—` means the provider did not report the field; it is not treated as zero.

| # | Stage / role | Route | Provider / model alias | Attempt | Finish | Input | Cached | Output | Reasoning | Observed cost | Outcome |
|---:|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 1 | planning / planning | Primary | `lingsuan_gpt` / `gpt-5.6-sol` | 1 | `tool_use` | 0 | — | 461 | — | CNY 3,154 µ | completed |
| 2 | review / review, initial capacity | Primary | `deepseek` / `deepseek-v4-pro` | initial | `max_tokens` | 5,637 | — | 1,276 | — | USD 12,494 µ | completed; split requested |
| 3 | review / review, segment receipt | Primary | `deepseek` / `deepseek-v4-pro` | 1 | `max_tokens` | 2,935 | — | 1,276 | — | USD 8,928 µ | output truncation |
| 4 | review / review, segment receipt | Primary | `deepseek` / `deepseek-v4-pro` | 2 | `max_tokens` | 2,994 | — | 1,276 | — | USD 9,006 µ | output truncation |
| 5 | review / review, segment receipt | Primary | `deepseek` / `deepseek-v4-pro` | 3 | `max_tokens` | 50 | — | 1,276 | — | USD 5,119 µ | output truncation |
| 6 | review / review, segment receipt | Fallback | `lingsuan_gpt` / `gpt-5.6-sol` | fallback 1 | `tool_use` | 0 | — | 1,270 | — | CNY 8,687 µ | completed; valid receipt |
| 7 | review / review, whole receipt | Primary | `deepseek` / `deepseek-v4-pro` | 1 | `max_tokens` | 4,545 | — | 1,276 | — | USD 11,053 µ | output truncation |
| 8 | review / review, whole receipt | Primary | `deepseek` / `deepseek-v4-pro` | 2 | `max_tokens` | 4,602 | — | 1,276 | — | USD 11,128 µ | output truncation |
| 9 | review / review, whole receipt | Primary | `deepseek` / `deepseek-v4-pro` | 3 | `max_tokens` | 122 | — | 1,276 | — | USD 5,214 µ | output truncation |
| 10 | review / review, whole receipt | Fallback | `lingsuan_gpt` / `gpt-5.6-sol` | fallback 1 | — | — | — | — | — | billing unknown; CNY 13,691 µ reservation retained | failed `RuntimeError` |
| 11 | review / review, whole receipt | Fallback | `lingsuan_gpt` / `gpt-5.6-sol` | fallback 2 | — | — | — | — | — | billing unknown; CNY 13,690 µ reservation retained | failed `RuntimeError` |

Each provider observation records `raw_content_included=false`. No prompt text, story text, credential, endpoint URL, or raw provider error is included in this report or the evidence package.

## 6. Totals and Budget Accounting

| Metric | Observed result |
|---|---:|
| Provider client creations | 11 |
| Credential lookups | 11 |
| Network calls | 11 |
| Paid model calls | 11 |
| Primary calls | 8 |
| Configured fallback calls | 3 |
| Protocol route failure events | 8 |
| Repeated receipt attempts beyond first attempt | 7 |
| Capacity split requested / completed | 1 / 1 |
| Known actual input tokens | 20,885 |
| Known actual output tokens | 10,663 |
| Cached input tokens | unknown for all reported calls |
| Reasoning tokens | unknown for all reported calls |
| Conservatively reserved input / output tokens | 40,156 / 20,534 |
| Known observed actual USD cost | USD 62,942 µ = **$0.062942** |
| Known observed actual CNY cost | CNY 11,841 µ = **¥0.011841** |
| CNY reservation retained for unknown billing | CNY 27,381 µ = **¥0.027381** |
| Total conservative reserved USD ceiling consumed | USD 72,301 µ = **$0.072301** |
| Total conservative reserved CNY ceiling consumed | CNY 94,686 µ = **¥0.094686** |
| Full elapsed time | 246.685313 s |

The two failed fallback calls did not report usage or final billing. The ledger therefore retained their reservations. The values above are evidence-ledger observations, not a claim about the provider's eventual invoice.

- Local normalize attempts/success：**unverifiable coverage gap**. The current canary evidence has no separate counter/event for this operation; no value is inferred.
- Scoped repairs：0 observed.
- Regenerations：0 observed.
- Draft, Repair, and Maintenance were not reached.
- Reliability trace contains 12 `recovery_attempt` observations: one startup failure with model-call delta 0 and eleven real model boundaries. It also contains 11 `authority_read`, 2 `resume_binding`, and 1 `promotion_write` observations.

## 7. Failure Causal Chain

First divergent node：**Review — planning adaptation receipt capacity/recovery path**.

1. Planning completed successfully and produced an exact semantic checkpoint.
2. Review initial-capacity output ended with `max_tokens` at the requested 1,276 output-token limit; Runtime emitted `stage_capacity_split_requested`.
3. Segment receipt primary attempts 1–3 each ended in `ContractOutputLimitExhaustedError` / `output_truncation`.
4. The configured fallback for the segment returned `tool_use`, passed the bound V2 receipt path, and completed the split segment.
5. Whole-receipt primary attempts 1–3 again ended in `ContractOutputLimitExhaustedError` / output limit.
6. Whole-receipt fallback attempts 1–2 failed with typed `RuntimeError` and `normal_invalid_output`; the last failure was non-retryable.
7. The receipt route exhausted and surfaced as outer `ProtocolReceiptRouteExhaustedError`; the isolated workflow became terminal.

Root failure：the whole Review receipt could not be obtained after repeated primary output-limit exhaustion and invalid fallback outputs.  
Outer failure：`ProtocolReceiptRouteExhaustedError`.  
Budget relation：not budget-exhausted; only 11 of the approved 48 maximum calls were dispatched.  
Generic wrapper masking：**yes at the outer run projection**. The run row/final run event uses a generic safe message, while the isolated evidence package and causal events retain the typed exception and complete route-attempt chain.  
Different-family terminal transition：not established; the observable chain stays within Review receipt exhaustion ending in `normal_invalid_output`.

## 8. Checkpoint, Last Legal Artifact, and Resumability

- Planning checkpoint：exact, `generated_complete/local_semantics`, output hash `67f79de06b30bbb2b423d39f74d2fa824caa72bc137f118ab62862150345a5af`.
- Last legal checkpoint：`review-plan-adaptation-segment-01-initial-capacity-9910c8b2105a-4-fallback`.
- Last legal artifact hash：`8b00d0065896c6f291052ec2e46aa83f38e239bc999e57b40daa59afef2fe17d`.
- Binding：the successful segment fallback has an exact resume binding.
- Whole-receipt attempts 1–5 produced failed transport/checkpoint records and no legal output hash.
- Workflow supervision state：`irrecoverable`; automatic recovery exhausted.
- Resumability：**not resumable for this canary**. A legal upstream segment remains available for diagnosis, but there is no legal whole-receipt continuation checkpoint, and the signed approval explicitly sets `resume_after_terminal=false`.

## 9. Live Parity and Isolation

Canary evidence reports live parity before/after SHA-256 `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`, status `exact`, with zero live active runs before execution.

Independent pre/post artifact characterization also remained byte-for-byte stable:

| Live surface | Before | After | Result |
|---|---|---|---|
| `app.db` bytes | `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3` | same | exact |
| Formal artifact manifest | `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908` | same | exact |
| Formal story artifacts | `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745` | same | exact |
| Canon | `d560044730a61382b401643a8159f58e07d919b601b97e931e8785b827bd84b0` | same | exact |
| Candidate | empty-manifest `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | same | exact |
| Checkpoint artifact files | empty-manifest `4f53cda1…` | same | exact |
| Saga artifact files | empty-manifest `4f53cda1…` | same | exact |
| StoryState rows | 6 | 6 | exact |
| Candidate rows | 11 | 11 | exact |
| Workflow checkpoint rows | 917 | 917 | exact |
| Production incident corpus | unchanged DB; isolated incident not counted | unchanged | exact |

The isolated canary generated incident key `short-story:failed:unclassified.f502cbe50de905af` only in its temporary DB. It did not increment or mutate the live production incident catalog. All canary project, DB, logs, trace, report, and approval-ledger writes stayed under the isolated run namespace.

## 10. Evidence Coverage Gaps

The evidence package explicitly retains these unresolved gaps:

- `relay_upstream_exact_version_unknown`
- `relay_public_max_output_unknown`
- `packaged_runtime_not_executed` (this smoke used the approved `git_workspace` runtime mode)
- Local normalize attempts/success are not separately observable in this evidence version.
- Cached-input and reasoning-token usage were not reported.
- Usage and provider billing for model boundaries 10 and 11 remain unknown; reservations were retained rather than converted into invented actuals.

No missing evidence was backfilled by inference.

## 11. Reliability Assessment

### Confirmed

- The approved real-provider path was reached under exact Origin/Executor/Runtime bindings.
- Planning completed, and the Review segment fallback demonstrated one successful capacity-split recovery.
- The whole Review receipt path nevertheless terminated after three primary output-limit failures followed by two invalid fallback outputs.
- The terminal was not caused by canary budget exhaustion.
- The outer run projection masks the precise root with a generic safe message, but the isolated evidence preserves the causal chain.
- Isolation held: live DB, projects, StoryState, Canon, Candidate, Checkpoint, Saga, and production incident count were unchanged.

### Not established

- This single smoke does not prove broad provider or runtime reliability.
- It does not prove a provider capability defect because the relevant public/upstream capability limits remain unknown and the observed terminal included normal invalid fallback output.
- It does not validate Draft, Semantic Review beyond this planning-adaptation receipt path, Quality, Maintenance, or Repair.

## 12. Gate Decision

**NARROW_FIX_REQUIRED**

The smallest evidence-supported next scope is diagnosis and a separately approved narrow fix for the Review planning-adaptation receipt capacity/recovery path, including why whole-receipt fallback produced invalid outputs and why the terminal projection loses the typed root at its user-facing boundary. This report does not authorize or implement that fix.

No second Smoke, Pilot-5, cohort expansion, Runtime change, Route change, Prompt change, Maintenance/Repair change, Phase 1B enablement, R1, Phase 1C, or Phase 1D is started from this result.
