# R1-PTR0 — Planning Targeted-Repair Root-Cause Verification

## Gate

`R1_PTR0_ROOT_CAUSE_NOT_CLOSED`

The first terminal-chain divergence is verified at Call 7, but the exact
`planning_repair_patch` payload and the exact Domain rule/path that rejected it
were not persisted.  The analysis therefore does not invent a Call 7/8 finding
set or claim a unique primary root cause.

What is closed:

- Call 7 and Call 8 both crossed Provider transport, unique strict-tool shape,
  JSON conversion, and wire-schema shape before failing Domain Validation.
- Call 8 was a blind domain retry: its system and user Prompt hashes are exactly
  the same as Call 7, and no Call 7 Domain finding was added.
- Calls 9 and 10 remained a bounded `planning_repair_patch` request.  They were
  not whole-Planning regeneration.
- The 1977 → 3954 expansion reached the Provider boundary exactly.  The prior
  hypothesis that the expansion was lost is falsified for this execution.
- Calls 9 and 10 consumed the exact requested token ceilings while producing
  zero visible characters; parser, schema, and Domain validation did not run.

What remains open:

- The exact field/path/invariant rejected in Call 7 and Call 8.
- Whether Call 8 removed, retained, transformed, or introduced any precise
  Domain finding.
- The Provider content-block shape behind the zero-visible-character fallback
  responses.

## Change contract and boundaries

- Authorization: root-cause verification, offline characterization, tests,
  task-local diagnostics, and documentation only.
- Risk level: L3 because the inspected boundary owns Planning repair, route
  fallback, generated-output Domain validation, and output budgets.
- Production behavior changed: none.
- Read-only boundaries: formal manuscript, Candidate, protected best candidate,
  StoryState, outline, Planning authority, route/model bindings, Runtime Skills,
  run history, checkpoints, resume state, approval ledger, live database, live
  project artifacts, and consumed Cohort.
- Modified boundaries: diagnostics, sanitized fixture, characterization tests,
  and this report only.
- Rollback: remove the R1-PTR0 diagnostic/test/report files; no business artifact
  or migration rollback exists because no production state changed.

The repository-required `scripts/check_project_scope.py` and
`scripts/inspect_change_gate.py` are absent at this commit.  Equivalent
fail-closed checks bound the Git root and sentinels, clean starting tree, parent
commit, protected-path diff, tests, and final diff.  This tooling absence is not
treated as evidence that the root cause is closed.

## Parent evidence Gate

| Evidence | Result |
|---|---|
| Evidence-only commit | `d0d9427af9c191aa09f9b1da4fb9881a253f4efc`, exact |
| Evidence canonical hash | `d431e377a9924ad8fa1fde8ab3cd278e612ae563adc2e0eca53444284b7c29ab`, exact |
| Manifest hash | `c22cecee6d83b52e1a2662c3a3753201f6fb44e3c82a2164b6b2d627f5f3e295`, exact |
| Manifest entries | 14/14 file hashes exact |
| Model Boundary Ledger | `57daca7a97d7a689aed5b79c704040bbb7d79e2885c5ad57c0262aaeb61f56b7`, exact |
| First Divergence Receipt | `c838d73de7628bfcc2b84f45b09cffe48a6050724adb07c455bf4506be8838ce`, exact |
| Completion Closure | `882fcff2e9e715e3b361663aab14a1367ce414716dfbb79b7377810ac07453a2`, exact |
| Signed Approval | `a793b1794bcad50a622af60ec79aa507af1565a71fc3267473678786629dc574`, exact |
| Validate-only Receipt | `3edbff96abc9c849f8a49acab7891b5840edcf6679f96eb35509c1f8c0b75013`, exact |
| Cohort | consumed; consumption `f421dba432121b12f3a8fae96454c2c963ab20c7e55232044d1a2609383692fc` |
| Live parity | before = after = `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` |

## Call 1–10 execution timeline

Provider and model values below are aliases from the isolated Canary database;
credentials, URLs, headers, request IDs, Prompt text, and response content are
not included.

| # | Stage / substage | Role | Route / execution | Provider / model | Attempt | Effective output budget | Finish / visible chars | Validation and next dispatch |
|---:|---|---|---|---|---:|---:|---|---|
| 1 | Planning / `planning_semantic_v2` | planning | primary / strict-tool | `lingsuan_gpt` / `gpt-5.6-sol` | 1 | 7774 | `tool_use`, 2507 | JSON/schema/Domain pass; compile Planning IR, start adaptation review |
| 2 | Review / initial adaptation review | review | primary / plain | `deepseek` / `deepseek-v4-pro` | 1 | 1276 | `max_tokens`, 0 | no parser; request capacity split |
| 3 | Review / adaptation segment | review | primary / plain | `deepseek` / `deepseek-v4-pro` | 1 | 1276 | `max_tokens`, 0 | protocol truncation; same-route retry |
| 4 | Review / adaptation segment | review | primary / plain | `deepseek` / `deepseek-v4-pro` | 2 | 1276 | `max_tokens`, 0 | protocol truncation; same-route retry |
| 5 | Review / adaptation segment | review | primary / plain | `deepseek` / `deepseek-v4-pro` | 3 | 1276 | `max_tokens`, 0 | protocol truncation; configured fallback |
| 6 | Review / adaptation segment | review | fallback / strict-tool | `lingsuan_gpt` / `gpt-5.6-sol` | 4 | 1276 | `tool_use`, 2250 | exact JSON/Domain pass; capacity packet merged; targeted repair requested |
| 7 | Planning / `planning_repair_patch` | planning | primary / strict-tool | `lingsuan_gpt` / `gpt-5.6-sol` | 1 | 1977 | `tool_use`, 1409 | exact JSON and wire shape pass; Domain `ValueError`; retry |
| 8 | Planning / `planning_repair_patch` | planning | primary / strict-tool | `lingsuan_gpt` / `gpt-5.6-sol` | 2 | 1977 | `tool_use`, 1378 | exact JSON and wire shape pass; Domain `ValueError`; fallback |
| 9 | Planning / `planning_repair_patch` | planning | fallback / plain | `deepseek` / `deepseek-v4-pro` | 3 | 1977 | `max_tokens`, 0 | no visible artifact/parser; expand budget |
| 10 | Planning / `planning_repair_patch` | planning | fallback / plain | `deepseek` / `deepseek-v4-pro` | 4 | 3954 | `max_tokens`, 0 | no visible artifact/parser; `ContractOutputLimitExhaustedError` |

Calls 1–6 contain an earlier recovered capacity divergence, but no masked Domain
or contract failure on the terminal chain.  Call 6 produced a valid fallback
adaptation receipt.  Call 7 is therefore the first verified terminal-chain
business divergence.

## Call 7 / 8 Domain closure

### Initial repair authority

- Input best-plan hash:
  `95c577f72345e2083e9e9524b75ba7da880a8de0317fcda395bb9b4caa93d49c`.
- Repair contract: `planning_repair_patch.v1`.
- Authorized scope: two exact evidence anchors in segment 1.
- Initial reviewer issue set:
  - `planning:segment-01:EV-A8353187:invariant:event_function`
  - `planning:segment-01:EV-A8353187:invariant:exit_state`
  - `planning:segment-01:EV-A8353187:invariant:knowledge_state`
  - `planning:segment-01:EV-A8353187:invariant:promise_ending`
  - `planning:segment-01:planning_formal_direction`
- Initial issue-set hash:
  `1e59e39cab2c154cf68bf329d384ad312e118f74089d74e122e89ff4f8ba8f32`.

The initial semantic-review findings were actionable and present in the repair
Prompt.  The missing information is specifically the new Domain failure from
Call 7 and then Call 8.

### Stored Call evidence

| Evidence | Call 7 | Call 8 |
|---|---|---|
| Provider response hash | `fbdb402de68ec4c6db6616cd1397e7e936232dc4291f7ccf85be80d43b27f209` | `67759d7b0453548ba44bedf931866f93a66cea2439ac5e65b722c05746e18a1f` |
| Canonical conversion hash | `c07a722956ba6f97458288f43ed18e3a1066354b451aba291189fdc2e0f6aaca` | `6ec59c897e198d7be6e2c9174be11184a4a1fb013ad19b1f19d2c11d82e4f588` |
| Adapter result | exact JSON, candidate count 1, semantic-valid conversion | exact JSON, candidate count 1, semantic-valid conversion |
| Runtime result | `domain_failure / ValueError` | `domain_failure / ValueError` |
| Exact Domain code/path | `unverifiable_not_persisted` | `unverifiable_not_persisted` |

The conversion audit intentionally stores hashes, method, and status, not the
normalized payload.  The database observation stores token/finish/visible-size
metadata, not tool arguments.  ReliabilityTrace stores only
`domain_validation / ValueError`.  Consequently, a true offline replay of the
two exact payloads is impossible from the sealed inventory.

### Finding propagation and set diff

- Call 7 and Call 8 system Prompt hashes: equal.
- Call 7 and Call 8 user Prompt hashes: equal.
- Call 7 exact Domain finding passed to Call 8: no.
- Stored generic set on both calls:
  `[domain_validation, ValueError]`, set hash
  `98da710214abbcee940f436c1f3163e9234e8bd59f9c217bb82b46555884cdd0`.
- Generic set diff: 2 persisted, 0 removed, 0 introduced, 0 transformed.
- Exact set diff: persisted/removed/introduced/transformed all `unknown`.

Therefore:

- `TARGETED_REPAIR_FINDING_PROPAGATION = partial`
- `TARGETED_REPAIR_SCOPE = field`

“Partial” is deliberate: the initial review findings and anchor authority were
precise, while the Domain retry findings were absent.

### Code path

```text
WorkflowService._repair_short_plan_adaptation_segment
  -> _stage(execution_spec=planning_repair_patch)
  -> execute_contract_runtime
  -> GeneratedArtifactGateway.convert_object          # exact JSON succeeds
  -> ExecutableContractSpec.domain_validator
  -> completion_check / normalized_patch
  -> normalize_planning_repair_patch                   # precise ValueError occurs
  -> normalized_patch catches ValueError and returns None
  -> generic "failed authoritative domain contract"
  -> same immutable Prompt is retried
```

Concrete source evidence:

- `workflows.py:11243–11249` requests only an exact evidence patch and forbids
  returning the full segment.
- `workflows.py:11252–11264` includes issue keys, authorized anchors, formal
  contracts, completion checklist, and the initial structural findings.
- `workflows.py:11320–11352` catches the precise normalization exceptions and
  converts them to `None`.
- `workflows.py:918–968` converts a false completion predicate into one generic
  Domain `ValueError`.
- `contract_runtime.py:1004–1010` changes retry Prompt only for conversion or
  business-incomplete errors, not Domain `ValueError`.
- `contract_runtime.py:1184–1197` observes only `domain_validation` plus the
  exception class and retries without a typed rule/path finding.

This proves the finding-propagation defect.  It does not prove which underlying
patch field first failed, so it cannot by itself close the primary root cause.

## Call 9 / 10 output-limit closure

| Property | Call 9 | Call 10 |
|---|---:|---:|
| Contract | `planning_repair_patch.v1` | same |
| Scope | targeted anchor patch | targeted anchor patch |
| Route capability / mode | plain-text / plain | plain-text / plain |
| Runtime requested budget | 1977 | 3954 |
| Provider effective budget | 1977 | 3954 |
| Observed output tokens | 1977 | 3954 |
| Visible characters | 0 | 0 |
| Finish reason | `max_tokens` | `max_tokens` |
| Parser / schema / Domain | not reached | not reached |
| Visible JSON/tool/object closure | absent | absent |

The Call 9 → Call 10 expansion multiplier is exactly 2 with an absolute delta of
1977 tokens.  Call 10 hit the new requested ceiling exactly.

- `OUTPUT_BUDGET_EXPANSION_EFFECTIVE = YES`
- `FALLBACK_SCOPE = targeted_patch`
- `FALLBACK_FINDING_PROPAGATION = partial`

Call 9 inherited the original exact reviewer findings but not Call 7/8 Domain
findings.  Call 10 added only the generic “return the registered JSON contract”
protocol regeneration system delta.

The Anthropic adapter constructs the request with `max_tokens` from Runtime and
extracts visible output only from `text` blocks.  The sealed evidence does not
contain the Provider content-block types.  Zero visible characters is therefore
verified, but “reasoning-only response” remains an unverified interpretation.

Provider-cap status:

- No configured model output cap is present in the isolated DB.
- The Provider honored both 1977 and 3954 as observable output-token ceilings.
- A hidden cap at or below 1977 is disproved by Call 10.
- A hidden cap above 3954 remains unknown.

## Minimum valid output counterfactual

The estimator is the current Runtime estimator
`novel_flywheel.context_policy.estimate_input_tokens`.

| Object | Canonical JSON bytes | Estimated tokens |
|---|---:|---:|
| Minimum wire-schema-valid patch | 130 | 33 |
| Minimum Runtime Domain-valid one-anchor patch | 167 | 42 |
| Two-anchor compact Domain-valid patch with the four current invariant labels | 265 | 67 |
| Call 9 budget / observed tokens | — | 1977 / 1977 |
| Call 10 budget / observed tokens | — | 3954 / 3954 |

The current patch schema is not structurally close to either output budget.  A
test-only one-anchor patch passes `normalize_planning_repair_patch`, applies to
only that anchor, and leaves adjacent content byte-identical.

Classification: theoretical valid output is far smaller than the budgets.  The
terminal is not explained by schema size or by whole-object regeneration.

Budget-only counterfactual:

- 2× is no longer hypothetical: Call 10 executed it and still returned
  `max_tokens` with zero visible characters.
- 4× (7908) may be long enough only in a length sense; without a saved content
  shape it is unproven and says nothing about Domain validity.
- No recommendation is made to increase max tokens.

## Primary cause versus terminal amplifier

```text
FIRST_DIVERGENT_NODE = Call 7 / planning_repair_patch.domain_validator

PRIMARY_ROOT_CAUSE = unresolved_exact_call_7_domain_rejection

STRONGEST_VERIFIED_PRIMARY_CONTRIBUTOR =
planning.targeted_repair_finding_not_propagated

TERMINAL_AMPLIFIER =
other:planning.fallback_plain_mode_zero_visible_output_limit
```

The two mechanisms are distinct.  The business divergence occurs on complete
strict-tool responses.  The terminal amplifier occurs later on a plain fallback
that never exposes a parseable patch.

Secondary contributors:

1. The Domain wrapper collapses the precise normalization reason to a boolean
   and then a generic `ValueError`.
2. The conversion audit cannot replay the normalized payload because it retains
   only hashes and shape status.
3. The fallback route has only plain-text structured-output capability.

## Exclusions

| Hypothesis | Disposition | Evidence |
|---|---|---|
| Network/transport | excluded for Calls 7–10 | all four observations are transport-complete |
| Credential | excluded | exact preflight and ten dispatched calls |
| Route drift | excluded | Runtime fingerprint and role/route binding exact |
| Fingerprint mismatch | excluded | parent Gate exact |
| Strict-tool uniqueness | excluded for Calls 7/8 | unique required tool accepted; exact conversion followed |
| Parser failure before Domain | excluded for Calls 7/8 | exact JSON conversion |
| Schema failure before Domain | excluded for Calls 7/8 | strict-tool wire shape accepted |
| Stale Planning artifact | retained as low-confidence unknown | authority hash exists, but exact returned payload is unavailable |
| Stale Candidate | not involved | Draft/Candidate not reached |
| Output-budget expansion loss | excluded | Provider effective budget changed 1977 → 3954 |
| Provider hidden cap | unknown above 3954 | no configured cap; actual output doubled with request |
| Prompt policy mismatch | excluded | signed preflight policy exact |
| Live contamination | excluded | full live parity exact |
| R1-D3 | not involved | Draft not reached |
| Final Review | not involved | not reached |
| Maintenance | not involved | not reached |

## Offline counterfactual matrix

| Counterfactual | Result |
|---|---|
| A. Exact Call 7/8 validator replay | blocked: payloads and exact Domain findings were not persisted; generic failure replay only |
| B. Minimal field patch | passes current patch Domain validator and deterministic anchor merge |
| C. Minimum whole contract object | 33 schema-valid / 42 Domain-valid estimated tokens; contract is a patch, not whole Planning |
| D. Budget-only | observed 2× still terminal; 4× possible only by length and Domain outcome unknown |
| E. Generic versus exact finding | exact shape adds rule code, field path, invariant, and repair scope; current retry has none of these |

## Falsification

This report must be revised if any of the following evidence appears:

1. A hash-bound Call 7 or Call 8 tool-argument/normalized payload matching the
   sealed response and canonical hashes.  Replaying it may identify a specific
   validator defect, stale authority, or model error and close the exact set
   diff.
2. A persisted retry envelope proving Call 8 received a typed Call 7 rule/path
   finding despite the equal complete Prompt hashes.
3. A Provider content-block snapshot proving Calls 9/10 contained visible JSON
   that the adapter dropped.  That would move the amplifier from Provider/plain
   behavior to adapter extraction.
4. Repository-bound Provider capability evidence proving an effective cap above
   or at 3954.  Current evidence neither proves nor excludes it.

## Recommended narrow evidence/fix surface — not implemented

The next production change should not begin by raising output budgets.

1. Persist a private, hash-bound normalized-payload receipt for rejected
   structured artifacts, plus a redacted typed Domain finding containing stable
   rule code, field path, invariant, and allowed repair scope.  Do not commit raw
   tool arguments or story content.
2. Feed that exact typed finding into the next Domain retry and configured
   fallback while preserving the immutable authority, exact anchor set, and
   current patch contract.
3. Preserve field-anchor patch scope and deterministic local merge.  No evidence
   supports reverting to a whole-segment or whole-Planning response.
4. Capture hash-only Provider content-block shape for plain fallbacks so
   zero-visible output can be separated into Provider reasoning/content,
   adapter extraction, and true empty-output families.

Expected deltas for a future narrow fix candidate:

- Initial Planning Prompt delta: 0.
- Repair/retry-only Prompt delta: add typed exact Domain finding; contents must
  remain hash/redaction safe.
- Route delta: 0 unless later Provider capability evidence requires a separately
  approved change.
- Retry/fallback count delta: 0.
- Model-call hard-cap delta: 0.
- Output-budget delta: 0.
- Provider capability evidence required: yes, to close the terminal amplifier.
- Another real Canary required: eventually yes, but only after offline
  production-shaped recovery crosses the next authoritative boundary and a new
  single-use approval is separately granted.

## Tests and operational parity

- Focused R1-PTR0 tests: `23 passed in 0.89s`.
- Related Contract/Adapter/Planning cluster: `236 passed in 55.92s`.
  The test runner remained open after printing its completed summary and was
  stopped; no test failure was reported in that cluster.
- Full suite: `2865 passed, 24 skipped, 6 xfailed, 1 failed` in 1550.06s.
- Sole failure:
  `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`.
  It expects the historical R0 DB hash `5deb7b...`; the existing current DB and
  sealed parent evidence are `0fccb8...`.  This exact stale-oracle failure is
  documented by earlier R1-PA0, C0B, R1-D0/D1/D2/D3, and SC-R1D3 reports and
  reproduces alone.  R1-PTR0 did not modify that test or the live database.
- New failures: 0.
- Offline replay external actions: model 0, Provider 0, network 0, paid calls 0,
  Canary runs 0.
- No second Canary; consumed Cohort untouched.
- `src/novel_flywheel/**`, `baml_src/**`, `tools/canary/**`, and
  `pyproject.toml`: unchanged.

## Final decision

`R1_PTR0_ROOT_CAUSE_NOT_CLOSED`

The finding-propagation defect and terminal amplifier are verified, but the
exact first Domain rejection cannot be uniquely attributed without the two
missing normalized payloads and typed rule/path findings.  Production fix,
Canary rematerialization, Approval, Provider call, output-budget change, and all
downstream phases remain stopped.
