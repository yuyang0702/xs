# R1-PTR1 — Planning Repair Evidence Closure Instrumentation

## Gate

`R1_PTR1_OBSERVABILITY_READY`

The four requested evidence boundaries are implemented behind a default-off,
fingerprinted flag and are verified offline without changing the request,
Prompt, route/model, retry/fallback topology, budget sequence, Domain result, or
terminal exception. This is an observability Gate only. No real Call 7–10 has
been rerun, no primary root cause has been selected, and no production fix has
been implemented.

```text
REAL_PROVIDER_OBSERVATION = NOT_EXECUTED
PRODUCTION_FIX = NOT_IMPLEMENTED
NEW_SINGLE_USE_APPROVAL_REQUIRED_FOR_OBSERVATION = YES
```

## Parent evidence Gate

| Check | Result |
|---|---|
| Parent HEAD | `4305858dee4843ce2f83a2cc1ebf1f02f58a3804`, exact |
| R1-PTR0 manifest | `0d458efdda2f1e176bdca9e3bb87e9e90e8de444264954c6dc95380d53c83a57`, exact |
| Parent live parity | before = after = `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` |
| Parent external actions | all zero |
| Implementation branch | `r1-ptr1/planning-repair-evidence-closure-20260817` |
| Implementation commit | `97158ccd9cec26506965e784a0d975cf4ba45a13` |

The repository-required `scripts/check_project_scope.py` and
`scripts/inspect_change_gate.py` do not exist at this commit. Equivalent checks
bound the Git root, exact parent, parent evidence hash, protected path diff,
clean source, compile/test results, privacy scan, and final manifest. No
independent reviewer is claimed.

## Production and operational files changed

| File | Diagnostic-only reason |
|---|---|
| `src/novel_flywheel/planning_repair_diagnostics.py` | Four immutable schemas, canonical hashing, bounded attempt snapshot registry, and fail-open emitters |
| `src/novel_flywheel/planning_adaptation.py` | Maps an already-issued validator rejection to stable rule/path/invariant codes; the authority function executes first and is unchanged |
| `src/novel_flywheel/model_diagnostics.py` | Read-only access to the active immutable diagnostic context |
| `src/novel_flywheel/providers/anthropic.py` | Hash/shape capture before `ModelResponse` projection |
| `src/novel_flywheel/providers/openai_chat.py` | Hash/shape capture before `ModelResponse` projection |
| `src/novel_flywheel/providers/openai_responses.py` | Hash/shape capture before `ModelResponse` projection |
| `src/novel_flywheel/models.py` | Emits the adapter-attached shape after the Provider boundary and before strict-tool replacement/decision |
| `src/novel_flywheel/contract_runtime.py` | Emits propagation, Domain decision, and output-limit observations around unchanged decisions |
| `src/novel_flywheel/workflows.py` | Targets only `planning_repair_patch`; wiring is constructed only when the new flag is true |
| `src/novel_flywheel/generated_artifacts.py` | Registers four diagnostic event payload contracts |
| `src/novel_flywheel/reliability_trace.py` | Classifies the four events as diagnostic trace types |
| `src/novel_flywheel/runtime_fingerprint.py` | Adds the default-off flag to the V2 feature registry |

The eight `tools/canary/*` changes do not create an approval or enable the
observer. They bind the new flag to `false` in existing C0B, PA, and Short
Completion plans and add it to each forbidden set. This preserves old profile
behavior and ensures a future observation cannot reuse an existing approval.

No `baml_src/**`, Prompt module, Provider/model binding, pricing, approval
ledger, live database, live project, or business artifact file changed.

## Schemas

All contracts use canonicalization
`r1-ptr1-diagnostic-canonical-json-v1`: UTF-8, sorted JSON keys, deterministic
JSON scalar handling, no Python `repr`, no absolute paths, and a domain-separated
sealed SHA-256.

### PlanningRepairDomainValidationSnapshotV1

Minimum identity and decision payload:

- run/attempt/model-boundary and repair-attempt ordinals;
- normalized payload SHA and structural-shape SHA;
- repair target identity/hash and canonical target paths;
- Domain validator id and exact unchanged validator-source SHA;
- result, rule codes, field paths, invariant ids, finding count;
- value type and structural shape only;
- raw value/story/payload omission flags and receipt SHA.

The authoritative `normalize_planning_repair_patch` runs first. Only after its
existing `TypeError`/`ValueError` is caught does the diagnostic extractor rerun
the same function to classify the already-made rejection. Extractor failure is
dropped and cannot replace the original exception.

### PlanningRepairFindingPropagationSnapshotV1

Records source/target attempt ordinals, source finding receipt SHA, exact source
rule/path set, serialized finding-envelope SHA, request semantic SHA, target
scope identity, and `exact|partial|generic|absent`. R1-PTR1 always observes the
actual current request. It does not inject findings. The current blind retry is
therefore faithfully emitted as `absent`.

### ProviderContentBlockShapeSnapshotV1

Records Provider family/protocol, binding hash, route and boundary ordinals,
requested/effective output ceilings, controlled finish reason, usage tokens,
Provider-body hash, flattened block-type sequence, visible text/tool/reasoning/
unknown counts, tool-argument presence/UTF-8 byte length/partial count,
empty/zero-visible/max-token flags, and pre/post adapter projection counts.
Original text, arguments, body, headers, and credentials are omitted.

### PlanningRepairOutputLimitObservationV1

Binds the exact Provider shape SHA to requested and actual Provider-effective
budgets, output tokens, finish reason, parser/strict-tool/Domain reachability,
existing truncation reason, existing Contract action, expansion before/after,
and unchanged next-route action.

## Call graph proof

```text
workflows.py:11078  WorkflowService._repair_short_plan_adaptation_segments
  -> workflows.py:26585  WorkflowService._stage
  -> contract_runtime.py:823  execute_contract_runtime
  -> contract_runtime.py:600  _dispatch_explicit_route
  -> provider adapter.complete
       anthropic.py:22 / openai_chat.py:22 / openai_responses.py:33
  -> pre-projection shape capture
       anthropic.py:63 / openai_chat.py:62 / openai_responses.py:77
  -> models.py:550,592  shape emission before/after Gateway conversion boundary
  -> contract wire conversion
  -> unchanged Domain validator
  -> contract_runtime.py:1292,1366  Domain snapshot
  -> unchanged retry/fallback decision
  -> contract_runtime.py:1036  finding propagation observation
  -> next attempt
  -> contract_runtime.py:1131,1219  output-limit observation
```

Observer implementations are at
`planning_repair_diagnostics.py:676,752,785,819,860`. All return without effect
when the flag or exact Planning-repair target does not match.

## Diagnostic-only proof

The production-shaped deterministic test executes two primary strict-tool
Domain failures followed by two plain fallbacks ending at output limit. Flag-off
and flag-on results are byte/hash equivalent outside ReliabilityTrace.

| Property | Before | After | Result |
|---|---|---|---|
| Request manifest SHA | `7f4d224c…363b852` | same | exact |
| Prompt attempt SHAs | `b69eea99…`, `b69eea99…`, `b69eea99…`, `ff24a9b3…` | same | exact |
| Route sequence | primary, primary, fallback, fallback | same | exact |
| Model aliases | primary ×2, fallback ×2 | same | exact |
| Output budgets | 1977, 1977, 1977, 3954 | same | exact |
| Terminal exception | `ContractOutputLimitExhaustedError` | same | exact |
| Terminal message SHA | `6a8de9ac…ecda` | same | exact |
| Diagnostic event count | 0 | 11 | expected trace-only delta |

The 11 events are: 2 Domain snapshots, 3 absent propagation snapshots, 4
Provider shapes, and 2 output-limit observations. A forced trace sink exception
preserves the same four dispatches, budgets, and terminal exception.

The Domain authority source SHA before and after is exactly
`a8c8c366033136494460b3ce65dda072d3a4505fcafe85281d4006c4b0381e3f`.
No Domain rule or pass/fail behavior changed.

## Feature flag and fingerprints

`NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1` defaults false. Existing Canary
profiles explicitly require false and forbid true.

| Snapshot | Build | Execution Config | Runtime Execution |
|---|---|---|---|
| Parent before R1-PTR1 | `771f86c5…8a59a` | `3e0ff5f5…34eb` | `d502521d…1d80` |
| R1-PTR1 flag false | `6a813386…7d6e` | `71ddad70…9760` | `4f9c0287…7944` |
| R1-PTR1 flag true | `6a813386…7d6e` | `23885f69…aeb7` | `539adc71…b72d` |

The source change intentionally changes Build identity. Enabling the flag does
not change Build identity but does change Execution Config and Runtime Execution
identity according to the formal formula.

## Tests

| Suite | Result |
|---|---|
| Focused R1-PTR1 | 16 passed |
| Related Contract/Provider/Planning/Trace/Fingerprint | 330 passed in 105.24s |
| Identity/successor/profile cluster | 72 passed in 51.60s |
| Clean C0A/C0B/PA validate-only cluster | 90 passed in 331.05s |
| Full clean-HEAD suite | 2844 passed, 2 failed, 20 errors, 41 skipped, 6 xfailed in 1431.62s |

The full-suite non-passes comprise two evidence families, not Runtime behavior
regressions:

1. `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`
   is the parent-known stale R0 oracle (`5deb…` expected, current sealed/live
   `0fcc…`). R1-PTR1 did not access or change the live DB.
2. `tests/canary/test_sc_r1d3_fingerprint_profiles.py::test_r1_d3_v1_evidence_remains_readable_and_manifest_bound`
   correctly detects that the historical R1-D3 manifest binds the old
   `workflows.py`. The same mismatch causes 20 shared-fixture setup errors in
   `test_short_completion_materialization.py`. Updating or bypassing that old
   evidence would silently authorize new production source and is prohibited.

The latter is a new fail-closed identity consequence of this authorized source
change, not a new workflow failure. A future observation requires fresh build,
config, Runtime, plan, Candidate, approval, and Cohort identities.

## Privacy and live parity

Committed evidence includes only hashes, controlled aliases, shapes, counts,
lengths, enum statuses, and source-relative paths. It contains no Prompt text,
story text, normalized payload, tool arguments, Provider body, credential,
header, user project name, or character name.

Current live hashes remain:

- live DB: `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`;
- formal manifest: `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908`;
- Canon manifest: `d560044730a61382b401643a8159f58e07d919b601b97e931e8785b827bd84b0`;
- Candidate/Checkpoint/Saga empty manifests: each `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

External action counters are all zero: real Provider 0, network 0, paid model 0,
real Canary 0, Signed Approval materialization 0, consumed Cohort reuse 0.

## Remaining evidence gap and falsification

R1-PTR1 does not close the R1-PTR0 root cause. A new real observation is still
required to capture:

- Call 7 exact normalized-payload hash/shape and Domain rule/path;
- Call 8 exact payload hash/shape and comparison to Call 7;
- Call 9/10 pre-projection Provider content-block topology and output-limit
  binding, if those fallbacks occur naturally.

The current conclusions are falsified if flag-on/off requests, Prompt hashes,
route/model sequence, budget sequence, Domain source hash, terminal exception,
or business artifacts differ; if a sink failure adds a dispatch; or if raw
business/provider content appears in a diagnostic record. The tests exercise
each of those boundaries and currently show no such difference.

No claim is made that finding non-propagation is the unique primary root cause.
Model patch error, validator false positive, stale authority/state, wrong target,
patch merge interaction, and other mechanisms remain open until real evidence
exists. No Provider hidden cap is claimed.

## Final decision

`R1_PTR1_OBSERVABILITY_READY`

The observer is ready for a separately authorized single Production-Mirror
observation. This phase stops here: no approval packet, Signed Approval,
Provider call, Canary execution, Prompt change, budget change, or production
repair was performed.
