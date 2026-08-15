# R1-PA1 strict-tool observability and budget-lineage evidence report

## 1. Branch, implementation HEAD and commits

- Branch: `r1-pa1/strict-tool-observability-budget-lineage-20260815`
- Start HEAD: `99510300361d24f778e946d8837ea801bc0c2e71`
- Implementation HEAD before this report-only successor: `f09c6b8`
- Commits:
  - `f420a26` — characterization baseline and fixtures
  - `8e0eba5` — diagnostic schemas, privacy and fail-open primitives
  - `6adaedf` — targeted provider/Gateway/Runtime observer wiring
  - `f09c6b8` — counterfactual, parity, successor seal and Canary contracts

No real-provider Canary was materialized or executed.

## 2. Changed files and reasons

| Group | Files | Reason |
|---|---|---|
| Diagnostic contracts | `model_diagnostics.py`, `generated_artifacts.py`, `reliability_trace.py`, `runtime_fingerprint.py` | Hash-only schemas, fail-open event types, metrics and default-off flag fingerprints |
| Boundary wiring | `models.py`, `contract_runtime.py`, `workflows.py` | Pass immutable target identity, observe request/decision/budget lineage after unchanged decisions |
| Provider raw snapshots | `providers/anthropic.py`, `providers/openai_chat.py`, `providers/openai_responses.py` | Sanitize provider-visible topology before normalization and attach it without wrapping exceptions |
| Characterization | `r1_pa1_budget_characterization_v1.json`, `r1_pa1_strict_tool_shape_cases_v1.json`, `test_r1_pa1_characterization.py` | Seal R1-PA0 call/budget/Segment/Whole/checkpoint evidence |
| Regression | `test_model_diagnostics.py`, `providers/test_diagnostic_tool_shapes.py`, `test_r1_pa1_runtime_observability.py`, `test_runtime_fingerprint.py` | Schema, three adapters, three layers, failure parity, cap lineage and fingerprint tests |
| Offline closure | `r1_pa1_counterfactual.py`, `test_r1_pa1_counterfactual.py`, `test_r1_pa1_privacy_performance.py` | Test-only retained-state counterfactual, privacy scan and local overhead/storage measurement |
| Baseline successor | `r1-pa1-authorized-protected-source-successor-v1.json`, `test_r0f_baseline.py` | Preserve the historical R0F seal while explicitly binding four approved instrumentation deltas and zero business deltas |
| Canary contracts | `r1-pa-strict-tool-obs-1-canary-draft-v1.json`, `r1-pa-budget-counterfactual-1-future-contract-v1.json`, `test_r1_pa1_canary_contracts.py` | Non-executable, unapproved, mutually isolated future contracts |
| Documentation | design, forward-risk V2, human-readable allowlist, `docs/maintenance.md`, this report | Scope, operation and evidence |

## 3. StrictToolShapeObservationV1 final schema

Identity and target fields: `schema`, `version`, `canonicalization_version`, `observation_sha256`, `shape_correlation_sha256`, `run_sha256`, `stage`, `boundary`, `role`, `route_kind`, provider/model alias plus hashes, `outer_retry_id`, `contract_runtime_instance_id`, `attempt_id`, `parent_attempt_id`, expected contract/version and `target_status`.

Request fields: declared tool count, manifest/schema hashes, controlled expected tool ID, tool-choice policy, request protocol, adapter version/manifest, expected call count and requested output tokens.

Response/decision fields: nested provider snapshot, normalized counts/shapes/call-ID hashes, duplicate counts, adapter projection, Gateway match counts, registered/unknown identities, block/text/tool presence, response/request-ID hashes, finish reason, strict decision/failure code and observation status.

Canonicalization is UTF-8 sorted-key compact JSON with `allow_nan=false` and domain-separated SHA-256. No object representation, address or UUID is a lineage identity.

## 4. Request-side tool manifest schema

The observer records `request_declared_tool_count`, `request_tool_manifest_sha256`, `expected_tool_schema_sha256`, `expected_tool_contract`, `expected_tool_contract_version`, `requested_expected_tool_id`, `tool_choice_policy`, `request_protocol`, `adapter_version` and `adapter_manifest_sha256`. Tool schema and descriptions are never persisted.

## 5. Raw, normalized and Gateway mapping

| Layer | Evidence | Binding |
|---|---|---|
| Provider raw | content/tool counts, controlled or hashed identity, argument shape/length/hash/parse status, finish status, call-ID hash | Snapshot carries the same `shape_correlation_sha256` |
| Adapter normalized | normalized count, unique identities, shapes and ID hashes, dropped/duplicated/changed status | Observation parent correlation |
| Gateway decision | matching/exact counts, accept/reject, stable failure code | Observation parent correlation |

The target filter is exact IDs, not Prompt text: `review / planning_adaptation_whole_receipt / planning_adaptation_whole@1 / review / configured_fallback`. Non-target strict-tool calls only increment `strict_tool_excluded_not_target`.

## 6. Snapshot completeness matrix

| Adapter/path | Success | Malformed conversion | Partial/capacity |
|---|---|---|---|
| Anthropic | `snapshot_exact` | `adapter_exception_with_snapshot` | `snapshot_partial` tested |
| OpenAI Chat Completions | `snapshot_exact` | `adapter_exception_with_snapshot` | finish/argument variants tested |
| OpenAI Responses | `snapshot_exact` | `adapter_exception_with_snapshot` | finish/argument variants tested |

Synthetic `snapshot_unavailable` and `adapter_exception_without_snapshot` cases remain unknown. Validation forbids `zero_tool_calls` unless an exact provider/adapter snapshot explicitly contains count zero.

## 7. Provider Adapter coverage

All three production adapter classes were exercised with deterministic fake transport bodies through the real Adapter and `ModelGateway`. Each success case proves exact raw → normalized → Gateway correlation. The historical C0B real-provider Whole response was not persisted and remains `unverifiable_legacy`; Canary A exists to obtain that evidence under a future separate approval.

## 8. Privacy scan

Automatic sentinels for Prompt, narrative, tool arguments, request ID, credential and absolute path are absent from serialized snapshots/observations/lineage. Forbidden keys remain rejected by `BestEffortTraceSink`. Unknown tool names, call IDs, request IDs, arguments and provider bodies are domain-hashed. The closed non-hash string allowlist is `r1-pa1-diagnostic-human-readable-fields-v1.json`.

## 9. Fail-open results

Enabled/disabled adapter failures preserve the same exception object, type, message, traceback frame names, `__cause__`, `__context__`, model-failure classification and production incident classification. Forced sink failure preserves one provider attempt and the original `RuntimeError`. Trace failures increment dropped metrics and do not trigger retry, fallback, recovery or transaction changes.

## 10. PlanningAdaptationOutputBudgetLineageV1 final schema

The schema binds event kind, run/stage/boundary/role/contract, stable outer/runtime/inner/parent identities, original/current/previous budgets, expansion policy/trigger/request/target, target-before-cap, effective-after-policy/provider/canary cap, applied/retained/reconstructed flags, reconstruction reason, retry owner, route/finish/failure, cap source(s), verified-or-unknown provider limit, request parameter, and system/user/contract/provider/model hashes.

Lineage events are `runtime_created`, `request_dispatched`, `expansion_decided`, `runtime_closed` and `outer_runtime_reconstructed`.

## 11. Cap-before/after lineage

The controlled cap fixture records expansion target `2552`, provider cap `2000`, effective provider/canary budget `2000`, `cap_applied=true`, `cap_source=provider`, but `expansion_applied=false`. This distinguishes an observed cap from the actual current loss of cross-runtime state.

## 12. Exact `[1276,1276,1276]` explanation

Each of three workflow-owned outer Whole attempts constructs a new Contract Runtime with original budget `1276`. Inside each runtime, output-limit handling derives the ordinary expansion target, but the runtime closes and the next outer attempt reconstructs from `1276`; no expanded state is retained. The production assignment is unchanged, and the controlled Runtime test still dispatches exactly `[1276,1276,1276]` with three distinct stable runtime IDs.

## 13. Retained counterfactual

The test-only helper dynamically imports `expanded_output_budget`; its implementation contains neither `2552` nor `5104`. With the sealed actual sequence `[1276,1276,1276]`, it derives `[1276,2552,5104]`, target-before-cap `[null,2552,5104]`, first difference attempt 2, and identical before/after invariant hash `deb231529be3dd30ab26a0bbd27b433e8f166752d2199f1fbb0a0e7dc554b77c`.

Only `retain_approved_expansion_across_outer_runtime_reconstruction` changes. Prompt/contract/provider/model/route/policy/attempt/cap/context/stage/failure-trigger inputs are sealed as unchanged. Whole fallback reachability is explicitly `unknown_counterfactual`; no provider call is made.

## 14. Disabled/enabled/sink-failure parity

The production-shaped strict-tool matrix preserves success or the exact current failure `RuntimeError: strict structured tool route returned no unique artifact` for all observer states. Adapter request count, current Gateway uniqueness decision, traceback and incident family are unchanged. Sink failure does not alter the terminal result.

## 15. Segment, Whole and Checkpoint parity

The sealed R1-PA0 oracle remains:

- Segment conversion `exact_json`, domain status `valid`.
- Segment raw SHA-256 equals last legal checkpoint output SHA-256: `8b00d0065896c6f291052ec2e46aa83f38e239bc999e57b40daa59afef2fe17d`.
- Whole failure type/message unchanged; error evidence SHA-256 `0ecd653cf45cc85c893b63e05a015430fd53225e56683516bc300fb7b16dc4b2`.

The full planning-adaptation and Contract Runtime regressions pass. No checkpoint, Candidate, Canon, Saga or formal artifact is written by R1-PA1 tests.

## 16. Prompt, route, retry and call parity

No Prompt file or prompt-building expression is changed. Budget observations hash the exact system/user values passed to the unchanged call. Route order, same-route attempts, fallback attempts and current acceptance condition are unchanged. The R1-PA0 historical ledger remains 11 calls: 8 primary, 3 configured fallback. R1-PA1 paid/network model calls are 0. Historical production Prompt hashes were not captured by R1-PA0 and are therefore not retroactively claimed; the deterministic on/off fixture proves same-input hash parity.

## 17. Test results

- PA1 focused/related suite: `257 passed in 56.30s`.
- Final full suite: `1 failed, 2625 passed, 2 skipped, 5 xfailed, 1 warning in 1309.10s`.
- Pre-change full suite: `1 failed, 2577 passed, 2 skipped, 5 xfailed, 1 warning in 1313.16s`.
- Same sole failure: `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`, historical expected DB `5deb...` versus task-start/current `0fcc...`.
- New failures: 0.
- Aggregate commit-aware strict L3 change gate: passed with Forward-Risk V2 and the user-approved single-agent clean-room report; independence is explicitly not claimed.

The first post-change full run exposed the R0F protected-source seal. It was closed without editing the historical baseline: the R1-PA1 successor fixture explicitly binds the four approved instrumentation source deltas and keeps all protected business deltas zero.

## 18. Performance and storage

Local deterministic measurement after the full suite:

| Metric | Result |
|---|---:|
| Disabled flag check mean | 0.754 µs |
| Enabled canonical hash primitive mean | 4.176 µs |
| JSONL append mean | 2578.015 µs |
| JSONL append p95 | 3573.6 µs |
| Strict observation size | 2665 bytes |
| Budget lineage size | 2037 bytes |
| 100-append failures | 0 |

These are local measurements, not a production latency distribution. No async queue or service was introduced.

## 19. Build, config and runtime fingerprints

| Flags | Build | Execution config | Runtime execution |
|---|---|---|---|
| both disabled | `2c44c4a225a7d88ea94d1b7078a6125cf1f54e9cad210e2413e29d65f9c4669f` | `da011266f4db58c7fb074a25a346dd0a1d8cf0a5ae49d42f9984c19334bd16f0` | `27b9d1ff43a69211c9ed2d83b264ff806907b2d6f1bd2b068a49e27651537157` |
| strict shape enabled | same | `7987440cacf569baf3ce76f53d7260b81142816aa3ea7f94ed2c2c7577935874` | `978ae94195251e3db790a8d399639532ff719007447463fd95bed1eaaff2e843` |
| both enabled | same | `424b03a0af4692f142d792fcb4932f644008bd983b85438c73a165a00dcf3916` | `1d71a08e667ed13f9eca9df135ff451dc756338d90467fb19929398f7b363a61` |

Both flags default false. Build identity is invariant to diagnostic flag state; config/runtime identity changes as required. No prior Canary approval or cohort is reusable.

## 20. PA-STRICT-TOOL-OBS-1 Canary Draft

`r1-pa-strict-tool-obs-1-canary-draft-v1.json` is `draft_unapproved_not_executable`, one-run, production-mirror, strict-observer-only, current-budget, raw-content-forbidden and stop-on-first-target/terminal/mismatch. Approver, approval ID, signature, cohort, launcher and command are null. It requires a future complete fingerprint/approval/single-use-cohort flow.

## 21. PA-BUDGET-COUNTERFACTUAL-1 Future Contract

`r1-pa-budget-counterfactual-1-future-contract-v1.json` is `future_contract_not_executable`. The canary-only behavior override, launcher, runtime switch, Provider execution and approval are explicitly not implemented. It requires review of Canary A and a distinct build/config/approval/fingerprint/cohort.

## 22. Independent Gates

`PA_STRICT_TOOL_OBS_1_APPROVAL_READY`

Reason: all three production adapters produce exact successful snapshots through the real Gateway under fake transport; missing evidence cannot be mislabeled zero; request/raw/normalized/decision correlation, privacy, fail-open, parity, fingerprints and non-executable Canary A contract are closed. This does not authorize or execute Canary A.

`PA_BUDGET_COUNTERFACTUAL_1_OFFLINE_READY`

Reason: actual reconstruction and cap lineage are observable, the one-variable derived sequence is stable and all non-target invariants are sealed. Whole fallback reachability remains unknown and no Canary B behavior exists. This is offline evidence only.

## Live artifact parity

Task-start and final values are exact:

- `app.db`: `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`
- Formal manifest: `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908`
- Formal story: `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745`
- Canon manifest: `d560044730a61382b401643a8159f58e07d919b601b97e931e8785b827bd84b0`
- Candidate/Checkpoint/Saga: empty manifest `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
- Table counts: StoryState 6, Candidate 11, Checkpoint 917.

R1-PA1 stops here. It does not implement a repair, change a budget, execute a Canary, or enter Phase 1B/1C/1D.
