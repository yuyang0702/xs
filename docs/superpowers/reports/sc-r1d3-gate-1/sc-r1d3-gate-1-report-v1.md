# SC-R1D3-GATE-1 — Fingerprint Collection-Profile Separation

Gate: `SC_R1D3_FINGERPRINT_PROFILE_SEPARATION_READY`

## Scope

The implementation is confined to `tools/canary/**` and `tests/canary/**`. No file under `src/novel_flywheel/**` or `baml_src/**` changed. No production Prompt, route, model, retry, fallback, budget, Final Review, Maintenance, StoryState, Canon, or Phase 1B behavior changed.

## Root cause and corrected semantics

The old Gate compared R1-D3 offline execution hashes with Production-Mirror execution hashes as though both had the same collection domain. Build and Prompt Policy were exact, but Config and Runtime were collected under different effective configuration sources. Their inequality was therefore evidence of different collection profiles, not runtime drift.

The corrected contract defines:

- `r1-d3-offline-fingerprint-profile-v1`: code/change evidence collected with the R1-D3 offline environment.
- `production_mirror_short_v1`: Short Completion materialization, rehearsal, and runner preflight collected from the isolated Production-Mirror environment.
- Cross-profile Config/Runtime status: `NOT_COMPARABLE_CROSS_COLLECTION_PROFILE`.
- Stable reason: `fingerprint_collection_profile_not_comparable`.
- Cross-profile Build and Prompt Policy remain exact comparisons.
- Same-profile Config or Runtime drift remains fail-closed.
- Missing or unknown profile remains fail-closed.

This is not an equality waiver. It is a typed declaration that the two execution identities have different collection domains. The materializer, independent rehearsal subprocess, and future runner must all use `production_mirror_short_v1` and match exactly within that profile.

## Evidence

| Identity | R1-D3 offline | Fresh Production-Mirror | Result |
|---|---|---|---|
| Build | `771f86c5c735fcc39cb499e9a87014b226ab20c60abf3e148393de1e4268a59a` | same | exact |
| Prompt Policy | `72282e5c12a101592d26d18d15a618afcd6b10688f4d79bac902c9337579d68c` | same | exact |
| Execution Config | `3e0ff5f5a05ef8f7a6569cc6ecb3d92b1feb1e502e7ab3c6d51ada024b2434eb` | `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa` | not comparable by design |
| Runtime Execution | `d502521d328722226b6b7676c2eb8b89ef9daf6b911caf179a5b60a7084f1d80` | `1efd51615c3f6274c52042eb4056402db2844ad9d02cc227b3e23ac294ec57e1` | not comparable by design |

R1-D3 V1 evidence remained readable and its SHA-256 manifest validated 13/13 exact. The new `R1D3ProductionMirrorReadinessBindingV1` binds the sealed R1-D3 evidence identity to a fresh Production-Mirror Plan without treating cross-profile Config/Runtime hashes as equal. Candidate and future Signed Approval validate-only carry the readiness definition hash. Old V1 Short Completion Plans without the new receipt remain readable.

## Tests

- Focused: `26 passed`.
- Compatibility matrix: `74 passed, 2 skipped`.
- All Canary: `239 passed, 2 skipped`.
- Full suite: `2842 passed, 24 skipped, 6 xfailed, 1 failed` in 1465.69 seconds.
- The only failure is the pre-existing R0 baseline assertion `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`; new failures: 0.

## Safety and parity

Credential lookups, Provider clients, network calls, model calls, and paid calls were all 0. No Signed Approval or Confirmed Authorization Patch was created. No Approval was reserved and no real Canary ran.

Live DB, formal story, Canon, StoryState row count, Candidate row count, and Checkpoint row count remain equal to the sealed R1-D3 evidence values.

Gate 1 is READY. Fresh inert Short Completion rematerialization is permitted; real execution remains prohibited.
