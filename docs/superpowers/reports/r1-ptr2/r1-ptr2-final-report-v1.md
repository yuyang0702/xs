# R1-PTR2-MAT Final Report

## Outcome

The fresh, disabled Planning Repair observation packet is materialized and
validated. It is not executable without a new, exact, single-use user
authorization. No real Provider, network, model, or paid call was made.

- Contract gate: `R1_PTR2_OBSERVATION_APPROVAL_PACKET_READY`
- Execution gate: `R1_PTR2_REAL_OBSERVATION_WAITING_FOR_FINAL_USER_AUTHORIZATION`
- `REAL_PROVIDER_OBSERVATION=NOT_EXECUTED`
- `SIGNED_APPROVAL=ABSENT`
- `CONFIRMED_PATCH=ABSENT`
- `NEW_SINGLE_USE_APPROVAL_REQUIRED=YES`

## 1. Branch, materialization HEAD, and commits

- Branch: `r1-ptr2-mat/planning-repair-observation-packet-20260817`
- Base: `745485f0fb4dfc25cd7aafa139922aba0eda9260`
- Materialization HEAD: `50933794249d19fb8be0bc2a0216a6b311c9c9e6`
- Implementation: `cff944a` (`feat(canary): add planning repair observation packet`)
- CLI exposure: `5093379` (`chore(canary): expose PTR2 materializer command`)
- The later evidence-sealing commit is not part of the bound production Build;
  its identity is reported at handoff.

## 2. Source diff scope

The base-to-materialization diff contains 15 files: 11 under
`tools/canary/**` and four under `tests/canary/**`, with 2,731 insertions and
24 deletions. There are no changes under `src/**` or `baml_src/**`. No Prompt,
Domain validator, parser/normalizer, route/model, retry/fallback, production
budget policy, StoryState/Canon, Final Review, or Maintenance implementation
was changed.

## 3-11. Fresh identity closure

| Identity | SHA-256 / value |
|---|---|
| Production Build | `6a813386e6e0200c2a8f41a118748702f3eecd3d86117ec5cb7d58d341387d6e` |
| Execution Config semantic | `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b` |
| Runtime Execution | `8e3fc9d5fb271ee62f835ebc27165bf0b32254bf3c1f43e2d4b121a6d514413b` |
| Runtime policy / mode | `runtime-fingerprint-v2` / `git_workspace` |
| Execution collection | fresh Production-Mirror execution environment; direct current-runtime snapshot (no legacy cross-profile comparison) |
| Launcher | `ab4f36affb09b44ef99c344fd137af9922fa64743a92e4e869bf6addefd5878f` |
| Diagnostic feature snapshot | `8de583b519cae87fd6114d24558ba49f2f964f33d6bf244bebba9a8f6f3e410c` |
| Feature provenance | `3fc004c10d4c98a06c26ecd925dcf54adadc44d63ef6da7447c236514b52af2c` |
| Prompt policy manifest | `ebc77e335347f7c6927bd7d081f6be30e3f6e544e4167ddd9c49ec8441b388fd` |
| PTR1 request manifest | `7f4d224c1c81e98e0b1b95b217414b8678b08ab8ca949cb399837236e363b852` |
| Prompt/request parity definition | `273aac3fc1ed12d58b7a487a7a88ff13414d621ea15532f4c43616bf77cb0523` |
| Provider descriptor manifest | `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f` |
| Role/route binding manifest | `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e` |
| Pricing evidence | `053fbf7d5fe203257dfb200e019c0ac4bdb811f09e244db4f37c906c7667649a` |
| Domain validator policy | `77111523e334421e7165af4af5fe59176ddd2e575ebb5fe7d2429e9cab05477a` |

`NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1=true` is the only target diagnostic
flag. `NOVEL_RELIABILITY_TRACE=true`; Canonical V2, Phase 1B shadow,
strict-tool observation, and PA budget-counterfactual flags are false. PTR1
parity proves the diagnostic flag has no ModelRequest semantic delta; the
independent rehearsal reproduced the exact Config and Runtime identities.

Four observation definitions:

| Observation | Definition SHA-256 |
|---|---|
| Domain Validation Snapshot | `ce59173e45281e7ae403767dda0f1af90789f07ba9e8dd85f8d841c5f70269ec` |
| Finding Propagation Snapshot | `0440345f993297956bda2cbf3f0141e75da33b56fef86fa46498762320727b94` |
| Provider Content-Block Shape Snapshot | `d1c66891f0cdaf4758bde9b0c16f9cce06f0d7c0189cd8450f0676d64a463939` |
| Output-Limit Observation | `40554c086d28d266e2bd43eb4b89d71abb9e0d8be7698ee0679c54fde98eb2c7` |

Instrumentation bundle:
`f8053582e21c7b2f7904d251e28e8707ba93f2b8b012b300b7186977dabcdc06`.

## 12-18. Materialized object identities

| Object | Domain SHA-256 |
|---|---|
| Observation Goal Definition | `d9f4b956d9b9dd6906889830eb4e9d9dc3284c431a14c90124df6d798e91dd71` |
| Observation Plan | `e430faf5dbfdd64d96adbdc1af2c57707d2ed4230b0d60422d25111e810ed962` |
| Final Approval Candidate | `ff88de76566b296e11a046a15e6808a5c4ef565c6bf02509ca8e09c473801294` |
| Authorization Patch Template | `d391c7ef83fd9438fb50efb9437742fe6a2dc0be51701066d05954a2b8e3ae99` |
| Validate-only Receipt | `0953ff3fc13990ff9e3c2a8c245c7bd631b66ea5621184ab02fb09e805c79529` |
| Execution Preview | `929431dc70cb6a6a2bc56e15d1b899392295e643100423d824d09fba4cd7fb83` |
| Materialization Index | `596f3184bf0840c0cf9f8537d74bd76902e564a903808f16e25d0430eb46154f` |

Validate-only `overall_status=exact`. The preview has
`do_not_execute=true`, `execution_authorized=false`, and placeholder paths for
future Signed Approval and Confirmed Patch; it is not an execution command.

## 19-24. Single-use state

- Cohort: `planning-repair-observation-1-20260817t003633z-a4f10e1`
- Window: `2026-08-17T00:51:33Z` through `2026-08-19T00:51:33Z`
- Ledger identity:
  `47642ae3ef765830e9d7821fd6d3e8b73c562486d06dca9eafff2e0a136504e0`
- Ledger path identity:
  `d67bd5d795bf3dd066ae3429399efa4995c4529df2e0c7e0c62dd6304a35e98c`
- Ledger initial entry count: `0`; reservation: `unreserved`; cohort: `unused`
- Canary root identity:
  `ba89976dacc62dee9aea07dd80ad359410c294b2a183f4a94cddc0f435803811`
- Independent pre-launch rehearsal:
  `e3a12635555778315ae5f72ff7e8c9beea7bb589e8bda96229f0085c8997c1f9`
- Candidate: disabled, `execution_authorized=false`,
  `named_approver=USER_CONFIRMATION_REQUIRED`, `usage_status=unused`,
  `signed_approval_materialized=false`.

The rehearsal ran in an independent subprocess using one fake boundary. It
produced all four typed observer receipts, while Config semantic and Runtime
Execution fingerprints remained exact. It is capability evidence only and
does not claim that the real target occurred.

## 25-26. Budgets and production parity

Canary outer caps are one run, 16 calls total/per-run, 500,000 input tokens,
500,000 output tokens, 32,000 output tokens per call, USD 10, CNY 20, and 3,600
seconds. Expected calls are eight. First-terminal stop is enabled; resume and a
second run are disabled.

These outer caps do not modify production per-attempt behavior. The sealed
production repair budget policy is
`a4afb20d6c93a9586f8b5f96b3457b1bc1eecfe22458fefcbdde956b2395325a`;
its characterization sequence remains `1977, 1977, 1977, 3954`, with budget
counterfactual disabled.

## 27. Tests

- Focused PTR1/PTR2 and Canary identity/materialization cluster: `70 passed`
- Related planning, contract, Provider-observer, runtime-fingerprint, and
  semantic-preflight cluster: `209 passed, 1 warning`
- Full clean-HEAD suite: `2855 passed, 2 failed, 20 errors, 41 skipped,
  6 xfailed, 1 warning` in `1509.00s`. Compared with the PTR1 baseline, the
  pass count increased from 2,844 to 2,855; the two failures and 20 errors
  remain the same two historical fail-closed families. No new failure/error
  family appeared, and neither fixture nor historical manifest was relaxed.

## 28-32. Privacy, parity, known failures, counters, and gate

Privacy status is exact: no raw Prompt, story, normalized payload, tool
arguments, Provider response, credential/header, endpoint, or machine-specific
path is present. Only hashes, shapes, counts, field paths, rule/invariant IDs,
budgets, and typed statuses are stored.

Live parity is exact:
`before=after=1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
No live business mutation was observed.

The two preserved historical full-suite families are:

1. the pre-existing R0 live-DB stale oracle;
2. the R1-D3 historical source-manifest fail-closed fixture family caused by
   the later diagnostic-only production byte change.

Neither old identity is rewritten or bypassed.

External counters are all zero: credential lookup, Provider-client creation,
network, model, and paid model calls.

Final state:

```text
R1_PTR2_OBSERVATION_APPROVAL_PACKET_READY
R1_PTR2_REAL_OBSERVATION_WAITING_FOR_FINAL_USER_AUTHORIZATION
REAL_PROVIDER_OBSERVATION=NOT_EXECUTED
SIGNED_APPROVAL=ABSENT
CONFIRMED_PATCH=ABSENT
NEW_SINGLE_USE_APPROVAL_REQUIRED=YES
```

Work stops at materialization. No Signed Approval, Confirmed Patch, real
Provider observation, second run, Short Completion, Draft completion, Pilot,
Phase 1B, or long-form work was started.
