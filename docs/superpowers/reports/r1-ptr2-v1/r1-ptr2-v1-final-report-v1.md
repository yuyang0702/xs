# R1-PTR2-V1 Final Report

## Outcome

- `R1_PTR2_VALIDATE_ONLY_PROFILE_FIX_READY`
- `R1_PTR2_FRESH_OBSERVATION_APPROVAL_PACKET_READY`
- `R1_PTR2_REAL_OBSERVATION_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`
- `REAL_PROVIDER_OBSERVATION = NOT_EXECUTED`
- `PRODUCTION_BUSINESS_FIX = NOT_IMPLEMENTED`
- `SIGNED_APPROVAL = ABSENT`
- `CONFIRMED_PATCH = ABSENT`
- `NEW_SINGLE_USE_APPROVAL_REQUIRED = YES`

## 1. Branch, baseline, and commits

- Branch: `r1-ptr2-v1/validate-only-handler-fresh-packet-20260817`
- Parent evidence commit: `92955e069728ecf728c094b830cc8e905077498e`
- Implementation commit: `22dee434ae2041bab38d2bc924444bd2a0c4ba94`
- Evidence/report files are sealed by the commit containing this report.

Parent evidence remained exact: blocked evidence canonical hash
`65af39170b02e2acb7a102e65b6c29bf871639ceac39add525f328681fbb9e68`,
old Confirmed Patch canonical hash
`885176ec6e96b0749e0c94ffe9bcd3e53994f54a079ada45b7744cc92de52a92`,
and old Signed Approval canonical hash
`18e50ab7daf4eb5baa883382e19cade8971fe6d450152acea4bb55f58279a645`.

## 2–5. Narrow fix and exact root cause

Changed production-control files:

- `tools/canary/launcher.py`: register the exact closure profile.
- `tools/canary/planning_repair_closure.py`: profile-specific, validation-only closure.
- `tools/canary/planning_repair_observation.py`: bind the closure definition and run an offline signed fixture rehearsal.
- `tests/canary/test_planning_repair_approval_closure.py`: exact, fail-closed, and tamper matrix.

No file under `src/novel_flywheel/**` or `baml_src/**` changed.

Root cause: `canary.validate_only_profile_dispatch_missing_handler`. The profile,
Candidate, patch, and Signed Approval contracts already existed. The missing edge was:

`validate_packet` → signed approval parser → closure selector →
`_validate_registered_closure` → missing
`planning_repair_observation_closure_v1` case →
`validate_only_profile_not_supported`.

The registered edge is now `tools/canary/launcher.py:77`; the profile definition is
`tools/canary/planning_repair_closure.py:104`; the 43-check validator begins at line
252 and its typed public wrapper is at line 620. It does not delegate to the Short
Completion closure.

Closure definition SHA-256:
`be85eb380988eb0edc7e04a9277e136c33a61d1195bc39d9cf62487ebd4d6ab9`.
The successful typed receipt is
`PlanningRepairObservationApprovalClosureValidationV1`, `overall_status=exact`.
Unknown, missing, malformed, mismatched, and version-mismatched profiles remain
fail-closed.

## 6–10. Fresh identities

| Identity | Before | After |
| --- | --- | --- |
| Production Build | `6a813386e6e0200c2a8f41a118748702f3eecd3d86117ec5cb7d58d341387d6e` | same |
| Config semantic | `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b` | same |
| Runtime Execution | `8e3fc9d5fb271ee62f835ebc27165bf0b32254bf3c1f43e2d4b121a6d514413b` | same |
| Launcher | `ab4f36affb09b44ef99c344fd137af9922fa64743a92e4e869bf6addefd5878f` | `5c38d3be4d72f806bb8ee22879fbe99d2d1f12290d793a8bff993c58cc507c28` |

Profile definition SHA-256:
`531ba08c399cae3d2fa4625c0eb02c6e64ce77f94c7ef99a359d2fb80a3b6d40`.
The changed Launcher identity proves that the historical Signed Approval cannot bind
the repaired control plane.

## 11–21. Fresh inert approval packet

- Plan canonical SHA-256: `c5fdeb3e2f8fa35296172f28ac0637dd65ee4dfe111b9db63e9a4d8b4f96b43d`
- Candidate canonical SHA-256: `d2ec832380b76e2bdeb2987cf22906f50f9dfcfb7f604280bcee3b3adef2040d`
- Patch Template canonical SHA-256: `b3c1d92c889b4ded6e152bf642fb59406cdf44df1acef313a29e1207dd219865`
- Candidate validate-only receipt SHA-256: `cf5904a4a948f82bfe13176d3fedbcc8a36d694f5384163e414969beaa99d0ad`
- Execution Preview canonical SHA-256: `a9fba595b8f3d0d2a12f10376a5b656b43f943fccb30d909efaacb0925fc4f10`
- Materialization Index file SHA-256: `b5e5a1bed4764fb990b3b7503854e977dc83d6a3d8d7b3fa1b6365d9214367ad`
- Cohort/run namespace: `planning-repair-observation-1-20260817t052829z-v1`
- Window: `2026-08-17T05:43:29Z` through `2026-08-19T05:43:29Z`
- Ledger identity: `b486bd0298b6ce9a3bb12f9be60126172687d6d724508b2ea6b7304690bc3cc8`
- Ledger path is the isolated cohort directory under `data/canary-approval-ledgers/`; business entry count is 0 and state is unused.
- Canary root stable identity: `ad603fa69a8e30db25b3b157dc50c0d5930bc8ae17eb42c84e77858d44293fb8`; root was not created.
- Pre-launch rehearsal receipt SHA-256: `e3a12635555778315ae5f72ff7e8c9beea7bb589e8bda96229f0085c8997c1f9`; status exact.
- Offline synthetic Signed Approval closure rehearsal SHA-256: `7bb236850d882ea9631a799ea4b1a0bee857aede86edb5750bb16bc494f5408b`; 43/43 checks exact. The synthetic object was temporary and was not materialized in the packet.

Candidate state is `execution_authorized=false`,
`named_approver=USER_CONFIRMATION_REQUIRED`, and `usage_status=unused`.

## 22–25. Budget and behavior parity

Outer caps: one run, 16 total/per-run model calls, 500,000 input tokens,
500,000 output tokens, 32,000 output tokens per call, 3,600 seconds,
USD 10.00, CNY 20.00; expected model calls 8. These are inert approval
limits, not usage.

Production repair output budgets remain `[1977, 1977, 1977, 3954]` and the
counterfactual flag remains false. Prompt/request semantics, retry/fallback,
route/model/provider bindings, target filter, observation goal, domain validator,
and four observer definitions all validated exact. Synthetic target injection is
forbidden.

## 26. Tests

- Pre-fix integration reproduction: failed with
  `validate_only_profile_not_supported`, all external counters zero.
- New exact/tamper/fail-closed matrix: 32 passed.
- Existing PTR2 materialization/goal characterization: 11 passed.
- Related Canary closure/profile/launcher cluster: 100 passed.
- Post-materialization PTR2 cluster: 43 passed in 191.12s.
- Compileall and `git diff --check`: passed.
- Full suite: 2,885 passed, 41 skipped, 6 xfailed, 4 failed, 20 errors.

The full-suite non-green families are pre-existing/environmental, not introduced by
this change: R0 stale live-DB oracle; R1-D3 historical manifest fail-closed (one
failure plus 20 setup errors); and two expired C0B approval-window tests. The two
expiration failures were reproduced unchanged on detached parent commit `92955e0`.
No new failure/error family was found.

The project council's referenced automation scripts
`scripts/check_project_scope.py` and `scripts/inspect_change_gate.py` are absent in
this repository. Their scope, diff, focused-test, full-suite, and self-review gates
were performed manually and recorded here rather than silently skipped.

## 27–31. Safety closure and final gate

- Privacy scan: exact; no raw Prompt, novel text, credential, header, provider response, absolute machine path, project name, or character name is stored.
- Live parity: exact, before/after observation hash `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`; live DB SHA-256 remains `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`.
- External counters: credential lookup 0; provider client 0; network 0; model 0; paid model 0.
- Historical Confirmed Patch and Signed Approval remain unchanged and read-only. Their file hashes remain `512ed01b653b2f27d5fc77b1dbad310f4e915f83f61c8325e30b839457d9387f` and `089d849300802105f7b8a4fbfbaa7b46321cadc56c98997dd8aa9ca685b90384`. They are not valid for the new Launcher/Plan/Cohort.
- No Signed Approval or Confirmed Patch exists in the fresh packet. A new, single-use, explicitly authorized approval is required before any real observation.

Work stops at the three READY/WAITING gates stated above.
