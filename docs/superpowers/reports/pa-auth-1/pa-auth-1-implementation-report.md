# PA-AUTH-1 — Registered Approval Profiles

Gate:

- `PA_STRICT_TOOL_OBS_1_SIGNED_APPROVAL_PROFILE_READY`
- `PA_STRICT_TOOL_OBS_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`

Implementation commits: `dd60cb4`, `4ab0d6e` on branch
`pa-auth-1/registered-approval-profiles-20260815`.

The immutable registry contains exactly `c0b_smoke_1` and
`pa_strict_tool_obs_1`. The generic dispatcher selects a profile by registered
mode/schema; Candidate, authorization Patch/Template, and Signed Approval use
separate schemas and validators. Candidate and Patch are rejected before a
real run and by the single-use approval ledger. Reservation and consumption
bind profile ID, Signed Approval hash and cohort ID.

The PA runner reuses the production-mirror Short path only after exact Signed
Approval validation. Its evidence keeps observation-goal outcome separate from
workflow outcome and stores only sanitized diagnostic hashes. This task did
not create a Signed Approval or execute that path.

## New inert materialization

- Plan SHA-256: `b8dbbf257a63ab7b9c6c5f2d4b0312fc3b3c33b7d2dbf6b2bd72de0b2b0343a8`
- Candidate SHA-256: `bb39d72a5e5a9c636f675ce229ab2a824f11fa030fb37abc937d208968b79504`
- Launcher SHA-256: `75c92b7fb4a4d9fccc5b9e5c17dfd79f898c4e7fc152e5d5ac45e676cc291909`
- Cohort: `pa-strict-tool-obs-1-20260815t151500z-4ab0d6e`
- Validate-only: `exact` with 28/28 checks
- Live parity/privacy: `exact`
- Credential/provider/network/model/paid calls: `0/0/0/0/0`
- Signed Approval materialized: `false`
- Execution performed: `false`

All earlier PA Plan/Candidate/Launcher/Cohort materials are historical and are
not valid authorization for this profile. The new Candidate and Patch Template
are also not authorization. A later Signed Approval requires a new explicit
final user authorization bound to the hashes and window in this directory.

## Regression evidence

- PA-AUTH contract suite: 32 passed.
- Canary suite: 165 passed, 1 skipped.
- Full suite: 1 failed, 2657 passed, 2 skipped, 5 xfailed.
- The sole failure is the pre-existing `tests/test_r0e_reports.py` live DB
  baseline mismatch (`expected 5deb...`, current `0fcc...`); no new failure.
- `src/novel_flywheel/**`: unchanged.
- `baml_src/**`: unchanged.

No Prompt, Runtime, provider route, retry/fallback, parser, adapter, validator,
budget behavior, business state, credential, network, or model-call behavior
was changed or exercised.
