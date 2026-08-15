# C0B-P1.2 — Signed Smoke Approval Contract and Rematerialization

## Final gate

- Contract gate: `C0B_SMOKE_1_SIGNED_APPROVAL_CONTRACT_READY`
- Execution gate: `C0B_SMOKE_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`
- Real Smoke executed: no
- Persisted Signed Approval created: no
- Approval cohort reserved or consumed: no
- Credential lookup / provider construction / network / model / paid calls: `0 / 0 / 0 / 0 / 0`

## Branch and commits

- Branch: `c0b-p1-2/signed-smoke-approval-contract-20260815`
- Starting HEAD: `e4835a4fd59c4beb684cbec51fc088b33aa8ddda`
- `78ddc8de8de18a27928ec543ba2af777a9036abe` — Signed contract, shared dispatch, Ledger semantics, and tests
- `157f174739cc13101ceceb907dd261c69b76d389` — Patch V2 filename correction
- `f9fbd60aaef5306148312947d69cf054f0a9a98d` — explicit contract-ready / waiting-for-new-authorization gates

## Changed implementation and test files

- `tools/canary/contracts.py`: strict Patch V2 and Signed V1 contracts; deterministic materialization; source and Plan binding.
- `tools/canary/launcher.py`: exact schema/scope dispatch and required Signed source documents.
- `tools/canary/approval_closure.py`: Signed validate-only closure and three Signed lineage checks.
- `tools/canary/preflight.py`: identical Signed/source/Plan validation at every model boundary.
- `tools/canary/real_run.py`: shared real-run approval validator and Signed identity propagation.
- `tools/canary/approval_store.py`: cohort plus Signed hash reservation/consumption identity.
- `tools/canary/final_approval.py`: Patch V2 template, source-aware command preview, and readiness gates.
- `tests/canary/test_c0b_p12_signed_approval.py`: 33 Signed contract and boundary cases.
- `tests/canary/test_c0b_smoke_final_approval_v2.py`: Patch V2 characterization.
- No changes under `src/novel_flywheel/**`, `baml_src/**`, or `pyproject.toml`.

## `C0BSmoke1SignedApprovalV1`

The object is a manual, hash-bound execution approval. It is not described as a cryptographic digital signature.

Strict fields are grouped below; additional fields are rejected.

- Contract: `schema`, `version`, `canonicalization_version`, `signed_approval_sha256`.
- Source lineage: `source_candidate_sha256`, `source_authorization_patch_sha256`.
- Scope and immutable execution identity: Plan, Launcher, workload and workload manifest hashes; build/config/runtime fingerprints; runtime mode; provider, role-binding, pricing, feature-flag and stop-condition hashes; Canary root identity.
- Budgets and policy: four budget definition hashes, fixed call/token/cost/time limits, `maximum_runs=1`, `first_terminal_stop=true`, `resume_after_terminal=false`, `phase1b_enabled=false`.
- Authorization: exact execution window and expiry, cohort, non-placeholder approver, UTC approval timestamp, `approval_method=manual_user_confirmation`, all four external permissions and `execution_authorized=true`.
- Consumption: `maximum_executions=1`, `usage_status=unused`, `consumed_evidence_sha256=null`.

The Signed hash uses the existing canonical JSON and domain-separated SHA-256 implementation. The digest excludes only its own digest field.

## Candidate + Patch -> Signed conversion

`materialize_signed_smoke_approval_v1(candidate, patch)` is pure with respect to credentials, providers, network, model calls, Ledger, cohort and Smoke execution. It:

1. validates exact Candidate V2 and confirmed Patch V2 schemas;
2. verifies Candidate, Patch, Plan, Launcher, workload, build/config/runtime, scope, window, expiry and cohort bindings;
3. requires Candidate unused and externally disabled;
4. requires Patch external confirmations true, a non-placeholder approver and valid UTC timestamp within the execution window;
5. copies every protected field from Candidate, never from Patch;
6. changes only the permitted authorization fields and adds source hashes/method/timestamp;
7. canonicalizes and hashes the resulting Signed object.

`validate_signed_smoke_approval_sources_v1` deterministically rematerializes and compares all protected fields. `validate_signed_smoke_approval_plan_v1` separately binds workload, Runtime fingerprints, routes, pricing, budget definitions, stop conditions and Phase 1B state to the exact Plan.

## Scope dispatch matrix

| Schema | Accepted scope | Validate-only | Real-run | Ledger reserve |
|---|---|---:|---:|---:|
| `CanaryPlanApprovalV1` | `C0B_REAL_PROVIDER_PATH_REACHABILITY` | yes | yes | once |
| `C0BSmoke1FinalApprovalCandidateV2` | `C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1` | yes, disabled | no | no |
| `C0BSmoke1UserAuthorizationPatchV2` | `C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1` | source only | no | no |
| `C0BSmoke1SignedApprovalV1` | `C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1` | yes, with Candidate and Patch | yes, with Candidate and Patch | once |

Unknown schemas fail `approval_schema_mismatch`. Candidate and Patch fail their stable non-executable reasons. Old/new scope crossover fails `approval_scope_mismatch`.

## Launcher, Real Runner, Closure and Ledger

- Launcher, Closure, Real Runner and per-boundary preflight use the same schema/scope dispatcher and the same Signed source/Plan validators.
- Real Runner re-reads Signed, Candidate and Patch in the final authorizer and every boundary snapshot.
- Ledger reservation payload uses `signed_approval_sha256` and the cohort; the cohort-named exclusive file blocks both identical approval replay and a different Signed object in the same cohort.
- Consumption re-reads the reservation identity and binds `consumed_evidence_sha256`.
- Candidate and Patch cannot reserve and are never rewritten or marked consumed.
- Signed validate-only test fixtures are generated only in pytest temporary directories. No executable Signed fixture is persisted because a new user authorization does not yet exist.

## Test results

- Test-first baseline: collection failed because Patch V2/Signed APIs did not exist.
- P1.2 focused: `33 passed in 117.49s`.
- Related Canary suite: `133 passed, 1 skipped in 282.27s`.
- Final full suite: `2570 passed, 2 skipped, 5 xfailed, 1 failed in 1294.75s`.
- The sole full-suite failure is the pre-existing `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical` drift: expected DB `5deb7bdf...`, actual DB `0fccb8ae...`.
- The same test, expected hash and actual hash were reproduced before implementation. New failures: `0`.
- P1.1 budget exhaustion/recovery characterization remains covered by the passing Canary suite.

## Live business parity

Before and after implementation/rematerialization are identical:

| Item | SHA-256 / count |
|---|---|
| Live DB | `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3` |
| Formal narrative manifest | `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908` / 1 |
| Formal story bytes | `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745` |
| Canon manifest | `d560044730a61382b401643a8159f58e07d919b601b97e931e8785b827bd84b0` / 1 |
| Candidate manifest | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` / 0 |
| Checkpoint manifest | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` / 0 |
| Saga manifest | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` / 0 |
| StoryState / Candidate / Checkpoint rows | `6 / 11 / 917` |

The unchanged DB hash also proves the production incident corpus was not incremented. No production source file changed.

## Final rematerialized packet

- Launcher hash: `099efc8c652a19d63ac9835e2a18e6b6a453d8abf0dc40cfc5af90ed7bdca163`
- Plan hash: `7a5005c0d01c827d3af632c91cdf924ad65aceb2d10c9e2379b3f5f135c41668`
- Candidate hash: `659f4b95a3a4eed73c18c5ba3ee2d0f8ab1fe221f862c1a27c5325f2a4971bac`
- Patch template hash: `dde3722f97369625e590930bfdebf87f5d3d20bfb2e0b1879da16a4a0855eef6`
- Build/config/runtime: `bbf17ef... / 70a487fa... / eb2ed19d...`
- Window: `2026-08-15T07:35:00Z` through `2026-08-17T07:35:00Z`; expiry equals window end.
- Cohort: `c0b-smoke-1-p12-20260815t072000z-f9fbd60`.
- Candidate: `execution_authorized=false`, all external actions false, approver placeholder, usage unused.
- Patch: V2 placeholder template; it is not an executed or executable authorization.
- Candidate validate-only: `overall_status=exact`, `approval_state=disabled_candidate`, 25/25 checks exact, all external counters zero.
- Command Preview: `execution_authorized=false`, `do_not_execute=true`; it names the future Signed, Candidate and confirmed Patch inputs.

### Artifact file hashes

| Artifact | File SHA-256 |
|---|---|
| `c0b-smoke-1-final-plan-v2.json` | `1884c1d47fe552d03dab2789e5241badaa0a1d5de6c30828fbd9ce59c0254c97` |
| `c0b-smoke-1-final-approval-candidate-v2.json` | `3b3771fb83e96104709be19d558c67937ff0670d5156f0ecfa98676cd27784e3` |
| `c0b-smoke-1-user-authorization-patch-v2.json` | `b01a78d8e82ed7de89d8f59be99e8901d4c7a14b197c89cbe593a09dbb24e8c6` |
| `c0b-smoke-1-final-validate-only-receipt-v2.json` | `8f5527991e2794c13cd50fe1b6b18517319adb13e5868b8029b314a0426902ae` |
| `c0b-smoke-1-execution-command-preview-v1.json` | `2ebfba328539ec19d6db3354948484ab3e6e123f5e8d9cafb3a91d410ee51866` |
| `c0b-smoke-1-final-packet-v2.json` | `ee9e3480a8e5d2506d2196d9185dcf05501b29f412b1ac3676fc7385917e6225` |
| `c0b-smoke-1-final-materialization-index-v2.json` | `b7db79560d0677afea471a6c5ee737f6e18f02018013251ebd8529ff3c5de7f8` |

The historical Patch V1 file remains only as a superseded record and is not referenced by the new Preview. The old Plan, Candidate, Launcher hash, window and cohort are invalid for execution.

## Stop condition

P1.2 stops here. A new, explicit user confirmation is required before a confirmed Patch or Signed Approval may be created. No Smoke, R1, Phase 1C or Phase 1D work has started.
