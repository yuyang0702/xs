# PA-STRICT-TOOL-OBS-1 Real-provider Execution Report

日期：2026-08-16（执行时间为 UTC 2026-08-15）  
Branch：`pa-auth-1/registered-approval-profiles-20260815`  
执行 HEAD：`6405b3b806d88c56accc99d5152ce7461656e33b`  
Single-use cohort：`pa-strict-tool-obs-1-20260815t151500z-4ab0d6e`

## 1. Outcomes

- `observation_goal_outcome = TARGET_STRICT_TOOL_SHAPE_OBSERVED`
- `workflow_final_outcome = WORKFLOW_TERMINAL`
- Workflow reason：`isolated_short_workflow_terminal`
- Final run status：`failed`
- Whole final exception：`ValueError`
- Safe failure class：`normal_invalid_output`
- Production incident counted：`false`
- Mechanism classification：`MIXED_OR_OTHER`
- Next-stage recommendation：`NARROW_FIX_READY`

The target observation succeeded independently of the later workflow terminal.
The exact target response contained one tool call, the adapter preserved one
call, and the Gateway accepted the unique expected tool. The later terminal
occurred at Draft after three `prose_invalid` realizations. It is not evidence
of a strict-tool shape defect.

`NARROW_FIX_READY` is limited to the Canary control plane: enforce the already
approved target-captured stop condition and add an exact retry-call counter.
It does not authorize a Runtime, Prompt, Route, adapter, validator, retry,
fallback, Planning Adaptation, Draft, or Budget Counterfactual change.

## 2. Approval materialization and validate-only

| Artifact | Canonical/self SHA-256 | File-byte SHA-256 | Result |
|---|---|---|---|
| Confirmed Authorization Patch V1 | `322f6e5701543ef7e7766629845d9bd7a298ef7b823beb5c7ba5aa0626e47138` | `e4319bd4817a1973cd827c7aff7f1d159e10a0cc0ece8bac5f13853b8e2ba420` | New file; Template unchanged |
| `PAStrictToolObsSignedApprovalV1` | `ae2add3ed517e01c90aa32b4ac5148eeb340c2ff3b6f381e83a7d110d4a06a93` | `b50ebd8d62f35af25cb42b9efa665823d7304d35b06b44faf6e32ec12520808c` | Exact and executable before reservation |
| Signed validate-only receipt | `c3011b478c6935e0fdee9a3b8cd47452776054869f6c8db3e9b015dc84cd0a20` | `09084c82f0655990d5610aef566b9de3708d1833017e567617198ffb2cf72092` | 28/28 exact |
| Evidence package | `8fcaadd61ff15bedb5033054494074adcd3da26bff728782bb4684b20cbff9f1` | `b0922be96a1360d31a77937e122e9b26a483f8dcd995b143c34e6f5d93b9d94c` | Recomputed exact |

Validate-only state was `signed_approval_exact_and_executable`; Approval
ledger was `unused`; credential lookup, Provider client creation, network,
model and paid-call counters were all zero.

## 3. Approval reserve and consume

| State | Definition SHA-256 | File SHA-256 |
|---|---|---|
| Reserved | `73b946403cc686ffa52ac81f8e2cf6dd97d109ce7ea28174eef6a83e1bf6548d` | `9f69120209f405f943509d1747f01d585de6b9884d6332737b6b7b2fd40ce33e` |
| Consumed | `5b04e7e0e7cdb860c34f151aa826139c75cde38e98e71345352db0d2499ec1ae` | `5fb54afa351df0c4bf88579609e9ba998bbbc3d9141482e4c6f760ce8ec1300a` |

Final ledger state is `consumed`. A second execution is not permitted and was
not attempted.

## 4. Exact preflight bindings

- Build fingerprint：`2c44c4a225a7d88ea94d1b7078a6125cf1f54e9cad210e2413e29d65f9c4669f`
- Execution config fingerprint：`4fb2e591c61c077784f8153b956a99c04ef509bcafe04b1c3ae0e82668f42e1b`
- Runtime execution fingerprint：`eaf6810e81a52a10c60e32862926c5fc99810a698e425dfc930b6fa054c1a24a`
- Target Filter：exact, `b92a6a13ff71ae123c694628e22d729f62a3796e0dca3c42c4958ad333366239`
- Observation Schema：exact, `a7cc00954b501fb4c41eb30aed8090af2702c969e35955a9606514bf71a083e9`
- Origin/Executor binding：exact, conflict count `0`
- Per-boundary preflight：22/22 exact
- Strict-tool trace：enabled
- Budget lineage：disabled
- Phase 1B / Short Canonical V2：disabled

## 5. Target Whole fallback observation

Target call count：`1`. It was Provider boundary ordinal `10`, route attempt
`1` on `configured_fallback`.

| Field | Observed value |
|---|---|
| Provider / model | `lingsuan_gpt` / `gpt-5.6-sol` |
| Stage / role / boundary | `review` / `review` / `planning_adaptation_whole_receipt` |
| Contract | `planning_adaptation_whole@1` |
| Requested max output | `1276` |
| Finish reason | `tool_use` |
| Request declared tools | `1` |
| Expected registered tool ID | `planning_adaptation_whole` |
| Tool-choice policy / protocol | `forced_exact_tool` / `anthropic` |
| Request tool manifest SHA-256 | `611203ce02a04af6728d8e03b5b6598a54dc90eeb4541f9ea75e3f362db2cec8` |
| Expected tool schema SHA-256 | `f839cc2f35f1dbc26b2e077910afae7eb4d58c2c1465b1bf0b62d150f06f0dda` |
| Adapter manifest / version | `1f10c5ecd040b021be476bb0f274181b3af176a70290e13bdeb65063b6d480f5` / `1` |
| Snapshot status | `snapshot_exact` |
| Raw content blocks / tool calls / unique identities | `1 / 1 / 1` |
| Raw tool-call ID hash | `eee06746e6eec104368cb16a6a2b351313628c1940f7e056b367785de40a819a` |
| Raw argument shape / parse | `object` / `native_object` |
| Normalized tool calls / unique identities | `1 / 1` |
| Normalized registered identity | `planning_adaptation_whole` |
| Drop / duplicate count | `0 / 0` |
| Exact expected-tool matches | `1` |
| Strict-tool decision / failure | `accept_unique_expected` / `null` |
| Shape correlation SHA-256 | `e57c0cc60ba7e4cfadaa11380f2ab380eba4405f2ed558dd363a14e1f6ca4ef1` |
| Observation SHA-256 | `8707ead549684ade12c804aed81e995f8d22d733a9669201d0fdda7cc89cdf58` |

The raw provider identity was retained only as a hash before adapter
projection. The same tool-call ID hash and one native-object argument survived
normalization. This falsifies, for this observed call, zero-tool, multiple-tool,
wrong-tool, malformed-argument, adapter-drop, adapter-duplication and Gateway
uniqueness-defect classifications.

## 6. Model calls, tokens, cost and elapsed time

| Metric | Result |
|---|---:|
| Model boundary / network / paid / credential / client calls | `22 / 22 / 22 / 22 / 22` |
| Primary / configured fallback calls | `18 / 4` |
| Explicit protocol-route failures / fallback decisions | `6 / 2` |
| Explicit output-limit expansion decisions | `2` |
| Explicit Draft scope-retry decisions | `2` |
| Exact normalized retry-call total | `unknown` — current evidence has no authoritative counter |
| Reported input / output tokens | `110,847 / 61,258` |
| Cached input / reasoning tokens | `unknown / unknown` for all calls |
| Cumulative reserved input / output tokens | `144,521 / 106,736` |
| Actual USD cost | `317,969` µUSD = `$0.317969` |
| Actual CNY cost | `95,598` µCNY = `¥0.095598` |
| Full elapsed time | `1,339.951449 s` |
| Budget stop | none |

All totals stayed below the authorized 24 calls, 500,000 input tokens,
500,000 output tokens, USD 10, CNY 25 and 7,200 seconds.

## 7. Segment fallback, merge and last legal binding

- Segment receipt fallback：success; `route=configured_fallback`, `outcome=valid`.
- Segment output hash：`8c500a04297fa7d7a0acbf9f5c51608e3552083cfec5751292aecb87c8e7b928`.
- Capacity split：completed with `packet_count=1`.
- Whole fallback：success; exact resume binding, output hash
  `5767b8f041dfe4af39cd5923bf0a21ee680c74ee62fb5873b7095b3fc647378e`.
- Planning Adaptation merge：ready; `equivalent=2`, protocol repairs `6`,
  semantic repairs `0`.
- Last observed legal artifact：`review-execution-segment-01-initial-1`, hash
  `6b3cc15f4bb54a2c70ff03c7f5c4302af177aee2efb239e7478a596f6da7436b`.
- Last checkpoint identity：
  `4ca339c5a53e9b26de40be728b927f508f15b778fbbbc58b9a6282e7f8fada13`.
- Checkpoint and last-legal-artifact execution binding：`unverifiable`.

No resumability claim is made. The Signed Approval has
`resume_after_terminal=false` and the Cohort is consumed.

## 8. Workflow terminal causal chain

The target whole fallback was accepted at `16:08:31Z`. The workflow then
continued into causal-chain generation, execution-manifest review and Draft.
Draft returned three normal-finish outputs. The first two emitted bounded
scope-retry decisions and all three failed the leaf prose gate with
`issue_codes=[prose_invalid]`. The workflow ended at `16:22:51Z` with outer
`ValueError`, safe class `normal_invalid_output`, and isolated incident family
`unclassified.8bff54965de2f818`.

The precise inner Draft validation reason is not present in the sanitized
evidence and remains unverified. No repair is authorized or performed.

## 9. Prompt, Route and retry parity

- Prompt source/config：unchanged; source-byte, Build, Config and Runtime
  fingerprints were exact. Per-call system/user prompt hashes are retained in
  the evidence package; raw Prompt is not persisted.
- Target request budget sequence：the three whole-receipt primary attempts and
  the fallback each requested `1276`; no counterfactual budget retention was
  enabled.
- Route policy：22/22 preflight receipts exact; actual primary/fallback route
  identities matched the approved Plan.
- Retry/fallback implementation：unchanged production Runtime. The evidence
  records the actual attempt chain but lacks one normalized exact retry-call
  total, so that value remains `unknown` rather than inferred.

## 10. Live parity and isolation

Before and after were exact:

- Live parity SHA-256：`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`
- Live DB bytes：`0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`
- Live project tree：`e8ba00afd255b1500caca5605535b66c98c0436b9b271c4a26652c72b86e94db`
- Formal business artifact set：
  `7cd33f5db7446160fb25d73d0cf6832297b0265d3b1a3429d9601bb1eaa9d059`
- StoryState manifest：
  `5b8edeffbc0a040d11ca3c7306ecdc1a943f3ba2c87f9fc29b3004ac23faa184`
- StoryState / Candidate / Checkpoint rows：`6 / 11 / 917`
- Live active runs before/after：`0 / 0`
- Phase 0 before/after comparison：equal, differences `[]`
- `src/novel_flywheel/**` and `baml_src/**`：unchanged

Canary DB, project, logs, trace, sidecars, reports and approval ledger remained
inside the isolated single-use namespace. The isolated terminal did not enter
the production incident catalog.

## 11. Privacy scan

- Status：`exact`
- Evidence package canonical hash revalidated：yes
- Reliability trace lines：`53`
- Damaged lines：`0`
- Target observations：`1`
- Raw-content flags：all false
- Absolute path, credential, header, Prompt/prose, raw argument/response and
  fixture title/premise/outline violations：`0`
- Privacy scan file SHA-256：
  `74a643aea243e329c777be203047714d49c831a3c9156beddbe2d205cea25384`

## 12. Confirmed Canary control-plane defect

The approved stop condition `target_strict_tool_shape_exact_captured` was not
enforced during execution. The target was captured at boundary ordinal `10`,
but ordinals `11` through `22` were still dispatched.

Code evidence: `tools/canary/real_run.py` waits for the full workflow at line
488 and only reads `_strict_tool_observation_summary` after the workflow at
line 583. The Plan declares the target stop condition, but the real runner has
no in-flight observer-to-cancellation latch.

Impact:

- 12 Provider/paid calls occurred after the observation goal was already met.
- The calls remained inside the broad 24-call and monetary limits, but violated
  the narrower user authorization forbidding unnecessary downstream calls.
- Live business state was unchanged; the impact is isolated Canary progression
  and cost, not production StoryState/Canon/Candidate mutation.

This is a confirmed narrow control-plane issue. It is not repaired in this
execution task.

## 13. Coverage gaps

- `relay_upstream_exact_version_unknown`
- `relay_public_max_output_unknown`
- `packaged_runtime_not_executed` (`git_workspace` was the approved mode)
- Cached-input and reasoning-token usage were not reported.
- Exact normalized retry-call total is absent from the evidence schema.
- Last checkpoint execution binding is `unverifiable`.
- The sanitized terminal projection does not expose the precise inner Draft
  `ValueError`; only the stable `prose_invalid` retry chain is available.
- One real observation does not establish population-wide Provider behavior.

No missing evidence was filled by inference.

## 14. Final gate

`NARROW_FIX_READY`

Allowed next design scope, requiring a new implementation authorization:

1. Make target observation a synchronous Canary stop latch before another
   Provider dispatch, while allowing the current target boundary to seal its
   result.
2. Add an authoritative retry-call counter distinct from primary, fallback and
   recovery-event counts.
3. Add deterministic tests proving zero post-target Provider calls and exact
   reserve/consume/live-parity behavior.

This report does not authorize a second observation, Budget Counterfactual,
Runtime repair, Prompt/Route/budget change, Pilot-5, Phase 1B, Phase 1C or
Phase 1D. Execution stops here.
