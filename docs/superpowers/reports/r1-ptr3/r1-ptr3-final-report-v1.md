# R1-PTR3 Final Report

Gate: `R1_PTR3_PLANNING_REPAIR_FINDING_PROPAGATION_FIX_READY`

## Evidence and classification

- Parent evidence is consistent: PTR0 proves the Call 8 blind retry; PTR1
  observes absent propagation; PTR2-V1 did not naturally exercise the target.
- Verified and fixed recovery defect:
  `planning.targeted_repair_finding_not_propagated`.
- Original historical Call 7 Domain failure root cause: **unclosed**.
- Historical terminal amplifier shape: **unclosed**.
- Provider content-block/output-limit observers remain unchanged.

## Call graph

`WorkflowService._repair_short_plan_adaptation_segment` builds the existing
patch authority/extractor -> `_structured_stage_spec` binds finding metadata and
renderer -> `_stage` calls `execute_contract_runtime` -> existing conversion and
Domain validation reject -> extractor returns rule/path/invariant -> Runtime
replaces its one-hop pending set -> next same-ladder dispatch receives the
bounded finding block -> existing conversion/validator runs again -> only a
validated patch returns to the existing merge path.

The patch touches three existing owners because workflow authority construction,
the retry loop, and the established typed diagnostic contract are separate. No
fourth production owner was added.

## Finding contract and safety

`PlanningRepairRetryFindingV1` v1 records rule, field path, invariant,
validator ID/policy hash, repair target/scope identity, attempt source identity,
deterministic finding identity, optional bounded hint, and explicit
`raw_value_included=false` / `raw_story_included=false`.

Bounds: 8 findings; rule 160 chars; path 256; invariant/validator 160; hint 80;
rendered canonical UTF-8 envelope 8192 bytes. Values are validated,
deterministically ordered, deduplicated, JSON escaped and marked untrusted.
Invalid/oversize input fails closed before dispatch; nothing is truncated.
Each Domain rejection replaces the prior set and the set is consumed for one
dispatch. A->B testing produced `stale_finding_count=0`.

## Parity and request delta

- Initial Planning Prompt: unchanged.
- First `planning_repair_patch` request: unchanged with no prior rejection.
- Retry after Domain rejection: only `Actionable Planning Repair Findings` is
  appended; it binds exact rule/path/invariant/current target and keeps the
  existing formal wire shape.
- Route/model/retry/fallback/output budget: delta 0; the production-shaped test
  kept two primary attempts at max output 1977.
- Domain validator/normalizer and merge semantics: unchanged and rerun.
- Repair target/scope identity: exact and hash-bound.
- Unauthorized-field drift: none in exact-scope fixtures. Residual general proof
  remains `planning.repair_scope_mutation_not_proven`; no diff engine was added.
- Provider-shape/output-limit instrumentation: related PTR1 suite unchanged.

Prompt Policy Manifest remains
`ebc77e335347f7c6927bd7d081f6be30e3f6e544e4167ddd9c49ec8441b388fd`.
It does not cover dynamic retry-only instructions: declared coverage gap. A
future Canary must bind the retry contract identity and fresh fingerprints.

Before (PTR2-V1): Build
`6a813386e6e0200c2a8f41a118748702f3eecd3d86117ec5cb7d58d341387d6e`,
Config semantic
`2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`,
Runtime execution
`8e3fc9d5fb271ee62f835ebc27165bf0b32254bf3c1f43e2d4b121a6d514413b`.

After clean implementation HEAD collection: Build
`e97060b725a6978f7770c18ec4feb46dd88dc326609355a19d24a1741bcc8bf6`,
Config semantic unchanged, Runtime execution
`47c4806b9dd97baac1f982e90481f5ad491f89acad33c23d0408c1d946549f60`.
These hashes authorize no execution.

## Verification

- Focused PTR3 + PTR1: 22 passed.
- Related Contract Runtime/Planning: 178 passed, 17 skipped.
- Full suite: 2890 passed, 41 skipped, 6 xfailed, 5 failed, 20 errors in
  1872.16s. One R1-PTR3 protected-source successor assertion was expected
  before the successor fixture existed and is now closed. The remaining known
  failures are out of scope: two expired-approval assertions, one R1-D3 sealed
  evidence mismatch plus 20 fixture-dependent errors, and one pre-existing live
  DB parity mismatch. No Planning/PTR3 regression remains.
- Covered: convergence, exact observer status, ignored finding/retry cap, A->B
  freshness, dedupe, malicious escaping, oversize fail-closed, no-failure call
  parity, budget parity, exact scope binding and unchanged validator semantics.
- Privacy: no raw Prompt/story/payload/provider response/credential/header is
  persisted by this contract or report.
- Live parity: live DB/projects/StoryState/Canon/Candidate/Checkpoint/Saga were
  not opened or modified. Credential/network/provider/paid-call counters are 0.

`REAL_PROVIDER_CALLS=0`

`REAL_OBSERVATION=NOT_EXECUTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`NEW_SINGLE_USE_APPROVAL_REQUIRED=YES`
