# SC-FP1 Final Report V1

## Outcome

`SC_FP1_SEMANTIC_FINGERPRINT_FIX_READY`

`SHORT_COMPLETION_CANARY_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`

No real Provider Canary was executed. No Signed Approval or Confirmed
Authorization Patch was created. Credential lookup, Provider client creation,
network, model, and paid-model counters are all zero.

## Repository and commits

- Branch: `sc-fp1/semantic-feature-flag-fingerprint-20260816`
- Parent evidence HEAD: `beaf2bb7f80d6203ba64e8b6d9a462f7b7a5f73b`
- Parent seal/change contract: `b07332f`
- Semantic fingerprint and Canary patch: `3b49340`
- V2 drift-fixture compatibility: `51a8233`
- Ledger operational-readiness hardening: `c1c8725`
- Change-contract formatting: `0dc29bb`

The strict scope diff from the parent contains only the approved paths:
`src/novel_flywheel/runtime_fingerprint.py`, `tools/canary/**`, `tests/**`, and
`docs/superpowers/**`. There are no changes to Prompt, Route selection,
Retry/Fallback, validators, Final Review, Maintenance, StoryState, Canon,
`workflows.py`, `contract_runtime.py`, `models.py`, or `baml_src/**`.

## Parent evidence and root cause

The sealed SC-OPS-1 evidence remained byte-exact:

| Evidence | File SHA-256 |
| --- | --- |
| Execution report | `5c819a59d683645630df1f25a8b48fdb8749a6489def44f4ced74d037f66025e` |
| Evidence manifest | `5cf8338a9dcb1898a84edd2545f78723587b9d677a0348c955d74d037f66025e` |
| Old Signed Approval | `db59a4876c8054363b1e21c1fedf09a34ec00ad824adfc0068c0ef97e037d63e` |
| Old Confirmed Patch | `496cb819541db90662f40a172c2c1362d33d5ddc3828c92ddafab9991caf9e1b` |

The old cohort `short-completion-1-20260816t061700z` remains reserved,
unconsumed, and replay-locked. It was not released, reset, deleted, or reused.

The old mismatch was reproduced exactly:

| Component | Materialization | Real-run pre-launch | V1 effect |
| --- | --- | --- | --- |
| `NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1` | `defaulted=false` | `set=false` | different config identity |
| `NOVEL_STRICT_TOOL_SHAPE_TRACE_V1` | `defaulted=false` | `set=false` | different config identity |

- Old expected config: `6f047d7fac61794f704b92397addd00475980c3bafab0f21b3ccb8d4e72b2277`
- Old actual config: `0a5b452c6d5f081ebeedc9b6c49f8049c9f07eb0ad39cb21432e570d0b8879f3`
- Old expected runtime: `c43ad3e4e58f95e8945982df4b6c089b42f8f9c72dc1dd2040ba018e21025cae`
- Old actual runtime: `e2090775927ddeb8a3ae13200d74d3693495b9ad5f95699d13afcbaab31f701e`

The first divergent node was `execution_config_fingerprint_pre_launch`.
There was no effective Boolean behavior difference; V1 mixed source presence
provenance into behavior identity.

## Versioned fingerprint contract

V1 remains explicitly collectible, readable, hash-verifiable, and is never
cross-authorized with V2. New materialization uses policy
`runtime-fingerprint-v2`.

### EffectiveFeatureFlagSnapshotV2

Behavior identity contains, per registered flag:

- controlled `flag_id`;
- typed `effective_value` and `value_type`;
- default, parser, and precedence policy hashes;
- registry policy/version and registry definition hash.

It contains no source presence, raw environment value, or secret.

### FeatureFlagProvenanceSnapshotV1

Diagnostic integrity identity contains:

- source kind, presence state, and selected source;
- parse status;
- raw-value-presence Boolean only;
- shadowed-source count and hash.

It never stores raw flag values. `defaulted=false` and `set=false` therefore
have different provenance hashes but the same effective semantic hash.

### RuntimeExecutionConfigFingerprintV2

The frozen behavior formula is:

```text
execution_config_fingerprint_sha256 = domain_sha256(
  "novel-flywheel-runtime-execution-config-semantics-v2",
  {
    policy_version: "runtime-fingerprint-v2",
    semantic_components: {
      effective_feature_flags,
      feature_flag_registry,
      installed_dependencies,
      python_runtime,
      route_role_bindings
    }
  }
)
```

`definition_sha256` additionally covers provenance and all child references.
Consequently behavior can be exact while definition/provenance identity differs.

The registry is closed-world and uses:

- registry policy: `feature-flag-registry-v2`;
- Boolean parser: `strict-production-bool-0-1-v2`;
- precedence policy: `controlled-source-precedence-v2`;
- registry definition SHA-256:
  `68cc48d8fc9f027ef77a738671546cbe2c4cb20550918ca10aa84cae10cf0113`.

Missing flags, extra/unregistered flags, malformed or unknown Boolean values,
unknown registry policy, policy mutation, unresolved precedence, incomplete
source snapshots, damaged parent references, V1/V2 mixing, and semantic hash
drift all fail closed.

## Shared resolver and typed failure mapping

Materialization, Runtime recording, the real runner, and boundary snapshot
suppliers use `collect_runtime_fingerprint_v2` and
`resolve_feature_flag_snapshots_v2`. Test helpers do not reimplement the
resolver.

When semantic config differs, the preserved result is:

- workflow outcome: `CANARY_BLOCKED_PRE_PROVIDER`;
- reason: `execution_config_fingerprint_mismatch`;
- Provider boundary entered: `false`;
- component diff: hash-only, with semantic/provenance equality and differing
  component IDs.

The launcher catches the typed preflight exception separately; it no longer
rewrites this cause as `canary_launcher_unhandled_failure`. Semantic equality
with known provenance inequality passes and records
`equivalent_provenance_variation`. Unknown provenance remains blocked.

## Verification

### Incident replay

- V1 `defaulted=false` versus `set=false`: mismatch reproduced.
- V2 effective flag semantic hash: exact.
- V2 execution config hash: exact.
- V2 runtime execution hash: exact.
- V2 provenance hash: intentionally different.
- Explicit `true` versus `false`: typed pre-provider block.
- Malformed/unknown Boolean: fail closed.
- DB/project precedence causing a different effective value: semantic drift.

### Test results

| Suite | Result |
| --- | --- |
| Baseline focused suite before implementation | `65 passed` |
| V2 Runtime/fingerprint focused suite | `45 passed` |
| SC-FP1 + C0B/PA/Short focused suite | `71 passed, 2 skipped` |
| Complete Canary suite | `225 passed, 2 skipped` |
| Full suite | `1 failed, 2791 passed, 3 skipped, 6 xfailed` |

The only full-suite failure is the pre-existing
`tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`:
expected live DB SHA-256 `5deb7bdf...`, actual `0fccb8ae...`. It is the same
test and the same expected/actual pair as the before baseline. New failures: 0.

Live business parity stayed exact at
`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.

## New inert Short Completion materialization

- Policy: `runtime-fingerprint-v2`
- Build: `3fab2deb66d00eb5ba33d3a98292a6ef65ed11cd1a416953388b772f317b2c3f`
- Execution config: `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa`
- Runtime execution: `65c3d484677a35ad69d3ccae5988be5dc6bfdef49e982632518d965ebc212b3e`
- Launcher: `ee54bea7193f2ffdb56864338e9dd336956303d93ca2a05ec3fe3876756cc78e`
- Plan: `3ccc41d80341860b72c41d9578b70e882375f266f422135157a6d946c7171bbb`
- Candidate: `33809ba01c978e38d439a24c46d28bd2a9ab9e22dc5110836047517ecde60ee2`
- Patch template: `2c8f0a1be6e5880e1e86eb7f56d417fb588e657dbf67c7a52ab870bef7bd18f4`
- Validate-only receipt: `d9ffc4d7288211745fd1aa12d010f47bff7f19e153f2fe6ce69d9366da6c06a3`
- Execution preview: `4df52042fa286cfaa4b1d4903482dbf387772b5aab515db0a5cc5d1fe92fb683`
- Materialization index: `93af4a5d22e646a8141b743743ce165e4afc03a403ddcc8deee8cbba44c400c8`
- Cohort: `short-completion-1-sc-fp1-20260816t160000z`
- Window: `2026-08-16T16:15:00Z` through `2026-08-18T16:15:00Z`
- Canary root identity: `d22b8a2a10e165a4c8a0459618e5045e17e9b295e2a5dec5a6c6e09f9748c73e`

The Candidate is inert: `execution_authorized=false`, named approver is
`USER_CONFIRMATION_REQUIRED`, usage is `unused`, and all authorized actions are
false. Signed Approval and Confirmed Patch are absent.

## Ledger operational readiness

- Ledger identity: `2fae64969d33c12a2a7229fbd3bb66e09186a72c203cdbfce1f5165708459737`
- Ledger path hash: `c3158449b59c8869691698500a3e0bf9f10a8ddea76ca0c10c648aadc0830bd4`
- Identity sentinel definition:
  `31af6beddd6f0d5c3f59a9436742c2196fc59e8f6f0091059a4f81a3ce934423`
- Initial business entry count: 0
- Cohort state: unused
- Approval state: unreserved
- Operational-readiness status: exact
- Credential/Provider/network/model/paid counters: 0/0/0/0/0

The ledger is outside the repository and live roots. Symlink/junction/reparse,
identity mismatch, missing sentinel, wrong identity, and non-empty roots fail
closed.

## Independent pre-launch rehearsal

- Receipt: `9c9b7741489023c1f1d333a54a2ceb80e7bc218e0e4e3b2d9f6d190922495d3b`
- Process isolation: independent subprocess
- Materialization semantic hash:
  `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa`
- Subprocess pre-launch semantic hash:
  `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa`
- Observation: `equivalent_provenance_variation`
- Provenance equal: false, known: true
- Fake boundary count: 1
- Credential/Provider/network/model/paid counters: 0/0/0/0/0

The privacy scan found zero fixture title/premise, absolute Windows paths,
credentials, authorization headers, or bearer material in the committed packet.

## Materialized file byte hashes

| File | SHA-256 |
| --- | --- |
| `short-completion-1-authorization-patch-template-v1.json` | `359a8c7c80135f8f835cbc4aa3b3040c58f45dee1cd04aa7e6f2c307fc65d497` |
| `short-completion-1-definitions-v1.json` | `8679578d07eba1bf201a64869d5e17d29dfb1aedafe7d1fccb6fb7f894d40420` |
| `short-completion-1-execution-preview-v1.json` | `fbf66d089af2306ecf37ed8a955f5d077616dff57ad53869c5d5b45d5f9cf3c0` |
| `short-completion-1-final-approval-candidate-v1.json` | `9d42fc3538ff03f0e4f97adea0caed6cfb8e0a665e24e6f8cdf99264a1927a05` |
| `short-completion-1-final-plan-v1.json` | `a4fe5b33c84fc26d061beccfc0e14f3bfd31fa313f3a06dc49ec89eabac35558` |
| `short-completion-1-ledger-operational-readiness-v1.json` | `c557631f0e6a7e03a3ed4bc4a91047289b5883f389acd9b7696a6499203b6771` |
| `short-completion-1-materialization-index-v1.json` | `70a932d91678efb646ede365072488d0588770e63aed45fd045d510ddc30218b` |
| `short-completion-1-pre-launch-semantic-rehearsal-v1.json` | `a353efa4e2280f5693955d3430b864b876920563ab4c34f1b015dc31247351c4` |
| `short-completion-1-validate-only-receipt-v1.json` | `a98e27d875e3fe057d2c6439fa363e49febf2df660e81344049b1c579724ced6` |

SC-FP1 stops here. A new, exact user authorization is required before any real
Provider execution. No downstream phase or Canary has been started.
