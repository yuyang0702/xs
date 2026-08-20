# R1-PTR4 — Planning ContractOutputLimitExhausted Root-Cause Closure

## Gate

`R1_PTR4_PROVIDER_CAPABILITY_EVIDENCE_REQUIRED`

This offline pass closes the causal ordering but cannot close the pre-adapter Provider content-block family. No Provider, network, model, paid, credential, production-fix, resume, or second-Canary action was performed.

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Parent/evidence HEAD: `eedfe33f00effb31c269fe9808fbc607f91a29a0`
- Parent evidence canonical SHA: `12603909cc4df1edc5419d2fba6a58c789965843328f7cf5fdafc23488ce4e60`
- Parent manifest: `exact`
- Parent privacy: `exact`, violations `0`
- Live parity: `exact`, current hash `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`
- Parent evidence commit source diff: `src/**=0`, `baml_src/**=0`
- Consumed cohort: one reservation and one consumption; replay forbidden
- Current-task external counters: credential/provider/network/model/paid = `0/0/0/0/0`

### Closure field matrix

| # | Field | Evidence-bound value |
|---:|---|---|
| 1 | task | `R1-PTR4` |
| 2 | analysis mode | offline sealed-evidence reconstruction |
| 3 | final Gate | `R1_PTR4_PROVIDER_CAPABILITY_EVIDENCE_REQUIRED` |
| 4 | branch | `r1-ptr3/planning-repair-finding-propagation-20260817` |
| 5 | parent HEAD | `eedfe33f00effb31c269fe9808fbc607f91a29a0` |
| 6 | parent evidence SHA | `12603909cc4df1edc5419d2fba6a58c789965843328f7cf5fdafc23488ce4e60` |
| 7 | parent manifest | exact |
| 8 | parent privacy | exact; 0 violations |
| 9 | live parity | exact |
| 10 | reconstructed boundaries | 12 |
| 11 | first transport divergence | boundary 1 `ConnectError` |
| 12 | transport divergence recovery | yes, boundary 3 fallback completed transport |
| 13 | ConnectError causal role | recovered route-escalation trigger |
| 14 | first unrecovered divergence | boundary 3 semantic-normalizer rejection |
| 15 | first unrecovered family | `PLANNING_SEMANTIC_V2_PLAIN_MODE_SEMANTIC_VALIDATION_FAILED` |
| 16 | terminal boundary | 12 |
| 17 | terminal exception | `ContractOutputLimitExhaustedError` |
| 18 | terminal amplifier | sticky output-limit masks conversion/business failure |
| 19 | execution mode | plain for boundaries 3–12 |
| 20 | Provider capability at execution | expired/stale; effective plain text |
| 21 | Provider content-block shape | `UNKNOWN` |
| 22 | observable terminal phenotype | `ZERO_VISIBLE_MAX_TOKENS` |
| 23 | parser reached | yes on boundaries 3–12 |
| 24 | JSON candidate reached | boundaries 3, 5, 6, 8, 9, 10 |
| 25 | strict tool reached | no |
| 26 | Domain validator reached | no |
| 27 | PTR3 Planning repair path | not exercised |
| 28 | semantic scopes | whole → segment packet → nested packet |
| 29 | actual local budget groups | `[7774×4]`, `[7774×3,15548]`, `[4399×3,8798]` |
| 30 | Provider effective ceiling | `UNKNOWN` |
| 31 | primary root cause | not uniquely closed |
| 32 | recommended fix family | deferred pending Provider evidence |
| 33 | production fix | not implemented |
| 34 | future probe | defined but not executed |
| 35 | real Provider/network/model/paid actions in PTR4 | `0/0/0/0` |
| 36 | focused offline verification | 90 passed |

## Three-layer causal distinction

### A. FIRST_TRANSPORT_DIVERGENCE

Boundary 1, Planning primary, `ConnectError`.

It was retried once on the same route at boundary 2. Boundary 3 then completed transport on the configured fallback, so the primary transport failure was recovered. It is not the final root cause.

ConnectError role:

- provider/model: Planning primary descriptor `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f`, model binding `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff`
- retry policy: two primary attempts, then configured fallback
- business/domain attempt consumed: `no`
- Planning repair attempt consumed: `no`
- model/call budget consumed: `yes`, two calls
- subsequent request mutation: `no`; boundaries 1–3 retain the same system/user hashes
- route impact: triggered configured fallback
- output-budget ordinal impact: none; budget remained `7,774`
- classification: `ROUTE_ESCALATION_TRIGGER` and recovered budget-consuming contributor, not primary root cause

### B. FIRST_UNRECOVERED_BUSINESS_OR_PROTOCOL_DIVERGENCE

Boundary 3, `planning_semantic_v2`, configured fallback, transport complete, `finish_reason=end_turn`, one JSON candidate, then `semantic_validation_failed` in the authoritative semantic normalizer. The domain validator was not reached and no legal Planning artifact or patch was produced.

Stable observed family: `PLANNING_SEMANTIC_V2_PLAIN_MODE_SEMANTIC_VALIDATION_FAILED`.

This family recurred at boundaries 5, 6, 8, 9, and 10 after the workflow reduced semantic scope. Boundary 8 is particularly important: it used the expanded `15,548` local budget, ended normally with `13,066` reported output tokens, and still failed semantic normalization. Therefore simple output-budget insufficiency is disproved as the sole root cause.

### C. TERMINAL_AMPLIFIER / TERMINAL_CAUSE

Boundary 12 is a projected zero-visible, `max_tokens` fallback response at local budget `8,798`. Parser entry occurred, but no JSON candidate was available; the conversion audit recorded `output_truncated`. The terminal exception was `ContractOutputLimitExhaustedError`.

`execute_contract_runtime` raises that exception whenever any attempt in the four-attempt group set `output_limit_seen` and the final error is an `ArtifactConversionError` or business-incomplete result. This sticky rule also affected the prior group: boundary 7 set output-limit state, boundary 8 ended normally but failed semantic normalization, and the group was still surfaced as `ContractOutputLimitExhaustedError`. The exception therefore masks earlier protocol/semantic divergence and is a terminal amplifier, not proof that budget is the primary root cause.

`TERMINAL_AMPLIFIER=STICKY_OUTPUT_LIMIT_COLLAPSES_FINAL_ARTIFACT_CONVERSION_FAILURE`

## Boundary 1–12 reconstruction

Contract for all boundaries: `planning_semantic_v2` v2, contract SHA `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`.

Provider/model aliases below are privacy-safe stable hashes:

- `P`: primary provider `121cc6b0...a600f`, model `5fd92d58...6b1ff`
- `F`: fallback provider `98190f8a...705a6`, model `fa876d17...f0998`

`Effective` means local post-policy dispatch budget. Provider-declared/effective ceiling was not captured and remains `UNKNOWN`.

| B | Substage / semantic scope | Route / attempt / reason | Requested / effective | Finish; output; adapter-visible | Block shape | Parser / strict-tool / domain | Result |
|---:|---|---|---:|---|---|---|---|
| 1 | `planning-semantic-v2` / whole | P/1 initial | 7,774 / 7,774 | `ConnectError` | not reached | no / no / no | transport retry |
| 2 | same / whole | P/2 same-route retry | 7,774 / 7,774 | `ConnectError` | not reached | no / no / no | fallback selected |
| 3 | same / whole | F/1 after primary transport exhaustion | 7,774 / 7,774 | `end_turn`; 7,204; 1,734 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | `semantic_validation_failed`; first unrecovered |
| 4 | same / whole | F/2 protocol retry | 7,774 / 7,774 | `max_tokens`; 7,774; 551 chars | projected text truncation; topology absent | yes, candidate=0 / no / no | `output_truncated`; capacity split |
| 5 | `...segment-01-packet-000001` / segment packet | P/1 after split | 7,774 / 7,774 | `end_turn`; 7,936; 27,500 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | `semantic_validation_failed` |
| 6 | same / segment packet | P/2 protocol retry | 7,774 / 7,774 | `end_turn`; 2,751; 6,819 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | `semantic_validation_failed` |
| 7 | same / segment packet | F/1 after primary protocol exhaustion | 7,774 / 7,774 | `max_tokens`; 7,774; 0 chars | topology absent; zero-visible projection | yes, candidate=0 / no / no | `output_truncated`; expand |
| 8 | same / segment packet | F/2 expanded fallback | 15,548 / 15,548 | `end_turn`; 13,066; 9,847 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | semantic rejection; sticky output-limit; capacity split |
| 9 | `...packet-000001-0` / nested packet | P/1 after nested split | 4,399 / 4,399 | `end_turn`; 1,784; 4,261 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | `semantic_validation_failed` |
| 10 | same / nested packet | P/2 protocol retry | 4,399 / 4,399 | `end_turn`; 1,422; 2,243 chars | snapshot absent; visible projection | yes, candidate=1 / no / no | `semantic_validation_failed` |
| 11 | same / nested packet | F/1 after primary protocol exhaustion | 4,399 / 4,399 | `max_tokens`; 4,399; 0 chars | topology absent; zero-visible projection | yes, candidate=0 / no / no | `output_truncated`; expand |
| 12 | same / nested packet | F/2 expanded fallback | 8,798 / 8,798 | `max_tokens`; 8,798; 0 chars | topology absent; zero-visible projection | yes, candidate=0 / no / no | terminal `ContractOutputLimitExhaustedError` |

The full machine-readable table, including request hashes and provider/model identities, is in `r1-ptr4-boundary-reconstruction-v1.json`.

Markers across the table:

- ConnectError: boundaries 1–2
- transport success: boundaries 3–12
- schema-valid: none
- semantic-normalizer rejected: boundaries 3, 5, 6, 8, 9, 10
- structurally output-truncated: boundaries 4, 7, 11, 12
- fallback: boundaries 3–4, 7–8, 11–12
- max_tokens: boundaries 4, 7, 11, 12
- adapter zero-visible: boundaries 7, 11, 12
- strict tool/tool call: not reached; all successful dispatches used plain mode
- Domain validator/finding propagation: not reached

## PTR3 real path

`PTR3_PLANNING_RETRY_PATH_EXERCISED_BY_THIS_RUN=NO`

The real contract was `planning_semantic_v2`, not `planning_repair_patch`. Although `NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1=true`, the target filter requires `planning_repair_patch`; consequently no Domain snapshot or finding-propagation snapshot exists.

- exact rule codes/field paths/invariant IDs: not produced
- source/target repair attempts: none
- finding count: `0` because the path was not reached, not because Domain passed
- finding propagation: `not_reached`
- stale finding count: not observed
- repair scope: not applicable
- old finding removed/new finding introduced/convergence: not observed

ConnectError is not counted as a Domain finding. `planning.repair_scope_mutation_not_proven` is not directly causal here because no targeted Planning repair occurred.

## Provider content-block shape

All ten transport-success observations used protocol `anthropic` and execution mode `plain`. At execution time both stored capability probes had expired:

- primary stored capability `strict_tool`, probe expiry `2026-08-19T14:18:03.058240Z`; effective capability became `plain_text/expired`
- fallback stored capability `plain_text`, probe expiry `2026-08-19T12:50:49.526495Z`; effective capability became `plain_text/expired`

The Provider adapter joins only raw `text` blocks into `ModelResponse.text`; tool-use and thinking/reasoning blocks remain outside that projection. The general `planning_semantic_v2` run did not satisfy the `planning_repair_patch` diagnostic target, so `ProviderContentBlockShapeSnapshotV1` was never persisted.

For fallback boundaries 3, 4, 7, 8, 11, and 12:

- block count/type order/text-block count/tool-use count/tool argument bytes/reasoning count/unknown count: `UNKNOWN`
- raw content: omitted
- boundary 3: projected visible text, `end_turn`, semantic-invalid
- boundary 4: projected visible text, `max_tokens`, structural truncation
- boundary 7: zero-visible projection, `max_tokens`, expanded to 15,548
- boundary 8: projected visible text, `end_turn`, semantic-invalid after expansion
- boundary 11: zero-visible projection, `max_tokens`, expanded to 8,798
- boundary 12: zero-visible projection, `max_tokens`, terminal

Observable boundary-12 phenotype: `ZERO_VISIBLE_MAX_TOKENS` at the adapter projection.

Unique Provider-shape classification: `UNKNOWN`. The sealed evidence cannot exclude `TOOL_ONLY`, `REASONING_ONLY`, `EMPTY_PROVIDER_RESPONSE`, `ADAPTER_VISIBLE_CONTENT_LOSS`, unknown blocks, or a mixed/truncated block sequence.

## Output-limit observations and actual budgets

Actual groups—not the historical 1,977/3,954 sequence:

1. Whole Planning: `[7,774, 7,774, 7,774, 7,774]`; boundary 4 hit max_tokens; next action semantic capacity split.
2. Segment packet: `[7,774, 7,774, 7,774, 15,548]`; boundary 7 expanded `7,774→15,548`; boundary 8 ended normally but was semantic-invalid; next action nested capacity split.
3. Nested packet: `[4,399, 4,399, 4,399, 8,798]`; boundary 11 expanded `4,399→8,798`; boundary 12 hit max_tokens and terminated. A computed next expansion would be 17,596, but it was not dispatched because retry/fallback remaining was zero.

For the terminal chain:

- source boundary: 11, then 12
- production repair budget ordinal: not applicable; this was not `planning_repair_patch`
- requested/local effective: `4,399→8,798`
- Provider effective ceiling: `UNKNOWN`; model declarations were absent
- boundary 12 output: `8,798`, finish `max_tokens`, projected visible `0`
- Provider shape receipt SHA: absent
- parser reached: yes
- strict tool reached: no
- JSON conversion reached: no candidate
- wire/semantic normalizer reached: no
- Domain validator reached: no
- next recovery action: none; route schedule exhausted
- terminal exception: `ContractOutputLimitExhaustedError`

The criteria for `planning.repair_output_budget_insufficient` are not met. There is no evidence of a meaningful targeted patch cut off at a verified Provider ceiling; adapter parity, targeted scope, and raw block shape are unproven. No budget increase is recommended.

## Scope and request identity

This was not `planning_repair_patch`. It was whole `planning_semantic_v2`, then semantic capacity split into `segment-01-packet-000001`, then nested packet `...-0`.

- whole checkpoint input SHA: `e7c4b9fbece227dc2b95cf45c000c8cc221309a77cd26bb98a32384607926637`
- segment packet input SHA: `7fcea91bca0be1b5b54994b6ee1954735bcda746badbc4a6e82bdd74998e7fa7`
- nested packet input SHA: `9c24d35328cab4d3780b832dd9f24c71de76c19bf23a8440e3f753e6054ae414`
- immutable authority SHA for all three: `538f9131989a1b1ae50878f4a32917ff569f35b83c781326782d30fca5d3aa07`
- context authority tokens reduced `1,461→979`; local output topology reduced `7,774→4,399` before bounded expansion
- legal checkpoint/artifact: none; all three failure checkpoints have empty output SHA and typed error `ContractOutputLimitExhaustedError`

The workflow narrowed semantic ownership, not a targeted repair field/subtree. Therefore `planning.repair_scope_mutation_not_proven` is not established as a direct terminal cause.

## Candidates disproved or unresolved

- `PRIMARY_UNRECOVERED_TRANSPORT_ROOT_CAUSE`: disproved by boundary 3 transport success.
- budget insufficiency as sole cause: disproved by boundary 8 normal finish after 2× expansion followed by semantic rejection.
- PTR3 Domain finding propagation defect: not exercised; cannot be causal in this run.
- targeted repair scope mutation: not exercised; cannot be direct cause.
- global/canary 32K budget exhaustion: disproved; the largest local dispatch was 15,548 and total budgets remained inside approval.
- strict-tool argument truncation: not observed because execution mode was plain; spontaneous tool blocks cannot be excluded without shape snapshot.
- hidden Provider ceiling: unresolved; no declared/effective Provider output ceiling was captured.
- reasoning-only/tool-only/empty/mixed/adapter-loss terminal shape: unresolved and mutually indistinguishable from sealed evidence.
- semantic schema incompatibility versus Provider block projection loss: unresolved at the exact field/block level because raw content was omitted and audits intentionally retain only `semantic_validation_failed`.

## Why Provider capability evidence is required

The missing evidence is specific and causal: a pre-adapter content-block snapshot plus post-adapter projection for the same Planning configured fallback. Without it, increasing budget, changing adapter projection, changing execution mode, or altering contract normalization would be speculation.

Future minimal probe contract—defined only, not executed:

1. Fresh single-use approval/cohort; old cohort cannot be reused.
2. Exactly one explicit configured-fallback call; no implicit primary, retry, fallback, expansion, resume, or full Short workflow.
3. Same approved fallback provider/model hashes and `anthropic` protocol.
4. Production Planning request assembly with sanitized isomorphic authority/payload proportions matching the nested packet; plain mode; requested max output `8,798`.
5. Stop after the first response or transport failure.
6. Capture `ProviderContentBlockShapeSnapshotV1` before adapter projection and bind it to a post-adapter receipt: ordered block types, text count/chars, tool-use count, tool argument presence/bytes/partial count, thinking/reasoning count, unknown count, empty/zero-visible, finish reason, usage tokens, requested/effective Provider budget, adapter projection status, and hashes only.
7. Run the existing converter once offline on the projected output and record candidate count, failure code, semantic-normalizer/domain reachability; never persist raw prompt, story, headers, response, or tool arguments.
8. Maximum Provider/model/network/paid calls: `1`; no second attempt if the shape does not reproduce.

Fresh approval is required because this probe uses Provider/network/paid actions and the prior cohort is consumed.

## Narrow fix decision

`RECOMMENDED_NARROW_FIX_FAMILY=DEFERRED_PENDING_PROVIDER_CONTENT_BLOCK_SHAPE_AND_FRESH_CAPABILITY_EVIDENCE`

No production fix can be selected safely yet. Conditional owners after future evidence:

- Capture scope/receipt: `src/novel_flywheel/planning_repair_diagnostics.py::{safe_capture_provider_content_block_snapshot,observe_provider_content_block_shape}`
- Anthropic pre/post projection: `src/novel_flywheel/providers/anthropic.py::AnthropicAdapter.complete`
- capability expiry/downgrade: `src/novel_flywheel/providers/registry.py::ProviderRegistry._effective_capabilities`
- execution-mode selection: `src/novel_flywheel/models.py::ModelGateway._complete_resolved`
- terminal cause preservation: `src/novel_flywheel/contract_runtime.py::execute_contract_runtime`
- capacity split propagation: `src/novel_flywheel/workflows.py::WorkflowService._stage`

Any future fix must preserve authority hashes, semantic ownership, parser ambiguity safety, domain validation, retry/fallback counts, budgets, Prompt/Route/Model bindings, last accepted artifact, privacy, and live isolation. Required offline tests must cover text/tool/thinking/empty/mixed/unknown block topologies, adapter projection exactness, stale capability downgrade, sticky output-limit cause preservation, semantic splitting, and the next authoritative Planning boundary. Build/Prompt/Route/Retry/Budget/Provider adapter changes are `NOT AUTHORIZED` in this pass.

`PRODUCTION_FIX=NOT_IMPLEMENTED`

`PROVIDER_PROBE=NOT_EXECUTED`

## Verification and sealing

- Focused offline tests: generated-artifact conversion, PTR1 observability, model execution-mode behavior, and real-stage Planning protocol recovery; `90 passed`.
- No historical evidence or manifest was changed.
- Current-task files are confined to `docs/superpowers/reports/r1-ptr4/**`.
- Current-task external counters remain `0`.
- Evidence SHA and manifest are materialized alongside this report.
- Evidence-only commit: the commit containing this report; its commit ID is reported after sealing because a commit cannot self-contain its own hash.

`R1_PTR4_PROVIDER_CAPABILITY_EVIDENCE_REQUIRED`
