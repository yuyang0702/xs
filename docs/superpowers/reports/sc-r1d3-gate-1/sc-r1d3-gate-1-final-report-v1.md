# SC-R1D3-GATE-1 — Final Report

## Final gates

- `SC_R1D3_FINGERPRINT_PROFILE_SEPARATION_READY`
- `SHORT_COMPLETION_R1D3_APPROVAL_PACKET_READY`
- `SHORT_COMPLETION_CANARY_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`

No real Canary was executed. No Signed Approval or Confirmed Authorization Patch exists. The Approval is unreserved and the cohort is unused.

## Branch and commits

- Branch: `sc-r1d3-gate-1/fingerprint-profile-separation-20260816`
- Parent: `4c28b162264d15c9dc020b623782116b7d1a2b6c`
- Canary-only implementation: `e5431efbccd227774dbd7fdda27a683c5ceb007e`
- Gate 1 evidence: `302a19fb6ecff2f4e04021d5c1438494771bec37`
- Materialization source HEAD: `302a19fb6ecff2f4e04021d5c1438494771bec37`

The final evidence commit is the commit containing this report and the inert packet. It introduces no production source change.

## Exact Canary-only change

Changed implementation files:

- `tools/canary/fingerprint_profiles.py`
- `tools/canary/contracts.py`
- `tools/canary/preflight.py`
- `tools/canary/real_run.py`
- `tools/canary/semantic_rehearsal.py`
- `tools/canary/short_completion_approval.py`
- `tools/canary/short_completion_closure.py`
- `tools/canary/short_completion_materialization.py`
- `tests/canary/test_sc_r1d3_fingerprint_profiles.py`
- `tests/canary/test_short_completion_materialization.py`

Protected diff is empty for `src/novel_flywheel/**` and `baml_src/**`.

## Collection profiles and comparison rules

- R1-D3 evidence: `r1-d3-offline-fingerprint-profile-v1`.
- Short Completion execution identity: `production_mirror_short_v1`.
- Cross-profile Config/Runtime: `NOT_COMPARABLE_CROSS_COLLECTION_PROFILE` with reason `fingerprint_collection_profile_not_comparable`; never equal and never a generic runtime mismatch.
- Build, Prompt Policy, validator, retry topology, and route/model bindings still require exact parity.
- Within `production_mirror_short_v1`, Config and Runtime must be exact. Missing or unknown profile fails closed.

The old erroneous Gate is reproducible: Build and Prompt Policy were equal, but raw equality on the offline Config/Runtime versus Production-Mirror values returned false and was misclassified as runtime drift. The corrected Gate records both execution hashes as not comparable by design and separately proves same-profile exactness.

## Fingerprint evidence

| Identity | R1-D3 offline | Fresh Production-Mirror | Status |
|---|---|---|---|
| Build | `771f86c5c735fcc39cb499e9a87014b226ab20c60abf3e148393de1e4268a59a` | same | exact |
| Prompt Policy | `72282e5c12a101592d26d18d15a618afcd6b10688f4d79bac902c9337579d68c` | same | exact |
| Config | `3e0ff5f5a05ef8f7a6569cc6ecb3d92b1feb1e502e7ab3c6d51ada024b2434eb` | `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa` | not comparable by design |
| Runtime | `d502521d328722226b6b7676c2eb8b89ef9daf6b911caf179a5b60a7084f1d80` | `1efd51615c3f6274c52042eb4056402db2844ad9d02cc227b3e23ac294ec57e1` | not comparable by design |

The independent Production-Mirror rehearsal reproduced Config `272507…5faa` and Runtime `1efd51…57e1` exactly. Semantic equality is true; provenance is known and differs only by the approved V2 equivalent-provenance variation.

## Fresh inert approval packet

- R1-D3 readiness definition: `e0f3e91d63a754a69b0759a88d77c0625f7925fb0d929f031ec87f96bd800025`
- Plan: `876c941ed613adb97eae1a9f585b4bf28b807d921c00f66c4b3969fcdc0b15d5`
- Candidate: `bd37c998ffe81b5a2f4fe177e686b614fc834d667dab1ba0d0a64b8944575c03`
- Authorization Patch Template: `e7583145ccb6c159af00c6539e0eb64fa913755f21333e03ea1125d94d610908`
- Validate-only receipt: `78db589feaa6011da8cf0b9698cd5a7970a40a781d2f28182a914eb4184371aa`
- Execution Preview: `10cc2b746aa08e0c6e29e07fa008a94920aa31fc4e5c5ddb924d5b0960e8d537`
- Materialization Index: `659eb01c792af350fe46de7eedef8a85b58777490d804d33ec1797ee43616f2b`
- Pre-launch rehearsal: `c512c5dedf4e81ee05a367cf334b4769b7848cb0312e84cfdb9eaab8208500b8`
- Cohort: `short-completion-r1d3-g1-20260816t154912z`
- Window: `2026-08-16T16:05:12Z` through `2026-08-18T16:05:12Z`
- Ledger identity: `999c504fc8d923da12a696e03e22aa8ab68f1350ea382fea68780744b49fc426`
- Ledger path hash: `32bee3f0bc5f41dd15c4581489b9c7ddf1574ac5844e4c0b80d2f667c3dc07f0`
- Ledger entries: 0; status: unreserved; cohort: unused.
- Canary root identity: `4d1ef794604da3a5e2d5d4d3de3d6f71641671ebf116f7325975c2d8452a7dbe`

Candidate state is `execution_authorized=false`, `named_approver=USER_CONFIRMATION_REQUIRED`, `usage_status=unused`. The Authorization Patch is a non-executable template only.

The first materialization invocation used an invalid uppercase/overlong cohort identifier and was blocked with `single_use_cohort_id_invalid` before any formal artifact or ledger was created. The contract was not relaxed; the successful packet uses a new valid unique cohort.

## Safety, privacy, and parity

Credential lookups, Provider clients, network calls, model calls, and paid calls are all 0. Privacy scan violations are 0; no Prompt text, story text, tool arguments, credentials, headers, Provider response, absolute path, project name, or character name is stored.

Live parity before and after is `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`. DB, formal story, Canon, StoryState rows, Candidate rows, and Checkpoint rows equal the sealed R1-D3 values.

Residual `draft.retry_scope_too_broad` remains explicitly retained. It is not claimed fixed.

## Regression results

- Focused: `26 passed`.
- Compatibility matrix: `74 passed, 2 skipped`.
- All Canary: `239 passed, 2 skipped`.
- Full suite: `2842 passed, 24 skipped, 6 xfailed, 1 failed`.
- The one failure is the pre-existing R0 live DB baseline assertion; new failures: 0.

The task stops here. A new explicit final user authorization is required before any Signed Approval can be materialized or any real Short can execute.
