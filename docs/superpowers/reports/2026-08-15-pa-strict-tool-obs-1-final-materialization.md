# PA-STRICT-TOOL-OBS-1 Final Canary Materialization

## Result

The independent single-use approval package is materialized and validate-only is
`exact`. No Signed Approval exists and no real Provider Canary was executed.

Final Gate:

`PA_STRICT_TOOL_OBS_1_WAITING_FOR_FINAL_USER_AUTHORIZATION`

## 1–4. Repository identity

1. Branch: `pa-strict-tool-obs-1/final-materialization-20260815`.
2. Task-start HEAD: `c0ee9f6c120fad9657cee0298eddbf8355d8890f`.
3. Control-plane implementation commit:
   `c4261ae90c9a1b4e200ec21cad41c7e2d4bc6e4c`.
4. Materialized-artifact commit:
   `312a3741e64c70708c1a844bb39af710a65f98d8`.
   The final report commit is recorded in the handoff because a report cannot
   contain its own Git object ID. The handoff worktree must be clean.

No file under `src/novel_flywheel` changed. Production Runtime, Contract Runtime,
normalizers, parsers, adapters, validators, Prompt, retry/fallback, provider/model
route, Whole fallback, Phase 1B, formal artifacts and incident classification are
unchanged.

## 5–7. Current fingerprints

5. Build Fingerprint:
   `2c44c4a225a7d88ea94d1b7078a6125cf1f54e9cad210e2413e29d65f9c4669f`.
6. Execution Config Fingerprint:
   `4fb2e591c61c077784f8153b956a99c04ef509bcafe04b1c3ae0e82668f42e1b`.
7. Runtime Execution Fingerprint:
   `eaf6810e81a52a10c60e32862926c5fc99810a698e425dfc930b6fa054c1a24a`.

These were recomputed with strict-tool observation enabled, budget-lineage
observation disabled, and Phase 1B disabled. No C0B fingerprint was reused.

## 8–13. Plan and authorization documents

8. Plan: `pa-strict-tool-obs-1/pa-strict-tool-obs-1-plan-v1.json`.
9. Plan canonical SHA-256:
   `2ddd144c67518848c25014726a6a74a89d234e73c2341a9dfe8dc1b30fed071d`.
10. Inert Approval Candidate:
    `pa-strict-tool-obs-1/pa-strict-tool-obs-1-final-approval-candidate-v1.json`.
11. Candidate canonical SHA-256:
    `c0f4128818f2827828aa41809f101e40b6ac3a24f59ac7c7814a8d2684d1635a`.
12. Non-authorizing User Authorization Patch Template:
    `pa-strict-tool-obs-1/pa-strict-tool-obs-1-user-authorization-patch-template-v1.json`;
    canonical SHA-256
    `fd78af0f9d2a0e985fe818bf0d9eaac344614ec1ee143b31d5c431adc1e4b520`.
13. Launcher SHA-256:
    `a4de4ca22694768e39ac13a2018c802e6a1bfc92809f75a37644a9a4706c64d5`.

Candidate fields are exactly false for credential lookup, provider-client
creation, network, paid model calls and execution. `named_approver` remains
`USER_CONFIRMATION_REQUIRED`. The patch contains confirmation placeholders,
keeps `execution_authorized=false`, and cannot materialize a Signed Approval.

## 14–18. Bound workload, route and observation definitions

14. Workload SHA-256:
    `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1`.
15. Provider Descriptor Manifest:
    `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`;
    Role/Route Binding Manifest:
    `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`.
16. Feature Flag Snapshot definition:
    `0a425b4d6fb8f4c97e6bc2c279b03c6bbfe790afe04469f845f38a8d97c74f92`.
    Snapshot values are:
    `NOVEL_STRICT_TOOL_SHAPE_TRACE_V1=true`,
    `NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1=false`,
    `NOVEL_SHORT_CANONICAL_V2=false`,
    `project_short_canonical_v2=false`,
    `NOVEL_CANONICAL_SHADOW_V1=false`, and
    `NOVEL_RELIABILITY_TRACE=true`.
17. Exact Target Filter SHA-256:
    `b92a6a13ff71ae123c694628e22d729f62a3796e0dca3c42c4958ad333366239`.
    Target is the equality tuple
    `review / planning_adaptation_whole_receipt /
    planning_adaptation_whole@1 / review / configured_fallback / strict-tool`.
    Prompt text is not used. Non-target strict boundaries are
    `excluded_not_target` count-only.
18. `StrictToolShapeObservationV1` JSON-schema SHA-256:
    `a7cc00954b501fb4c41eb30aed8090af2702c969e35955a9606514bf71a083e9`.
    The future evidence contract requires one correlation over request
    declaration, provider raw shape, adapter-normalized shape and Gateway
    decision. Missing snapshots remain unknown and cannot imply zero calls.

## 19–21. Budget and single-use window

19. Exact approval candidate budget:

    - maximum runs: 1
    - expected model calls: 11
    - maximum total/per-run model calls: 24
    - maximum input tokens: 500,000
    - maximum output tokens: 500,000
    - maximum output tokens per call: 32,000
    - maximum USD: 10.00
    - maximum CNY: 25.00
    - maximum elapsed: 7,200 seconds

    Budget definition SHA-256:
    `db6a4241651f61ac3da36f08cde3c00432e552ff456e3d0def6a0757feea6d78`.
    The prior real smoke reached the target boundary at calls 10–11; 24 is more
    than twice that observed reachability while remaining below every prior C0B
    cap. It does not add Runtime retries. If the target is not reached, the
    outcome is `TARGET_NOT_REACHED` and a second run is forbidden.
20. Single-use cohort:
    `pa-strict-tool-obs-1-20260815t133000z-c4261ae`.
    It is new, unused, has `maximum_executions=1`, and does not reuse C0B state.
21. Execution window: `2026-08-15T13:45:00Z` through
    `2026-08-17T13:45:00Z`; approval expiry is
    `2026-08-17T13:45:00Z`.

## 22–26. Offline closure

22. Validate-only Receipt:
    `pa-strict-tool-obs-1/pa-strict-tool-obs-1-validate-only-receipt-v1.json`;
    28/28 ordered checks are `exact`; receipt SHA-256
    `50b122714be07c7359d1e9967d59e7cea1bd62f607a28ccd97dd0446952eeea3`.
23. Execution Preview:
    `pa-strict-tool-obs-1/pa-strict-tool-obs-1-execution-command-preview-v1.json`;
    preview SHA-256
    `6ce1f7510411c2c5d2984258846389a68f26ef716e37fbad0bbe982ef55a4660`.
    It binds future schema `PAStrictToolObs1SignedApprovalV1` through a
    placeholder, has `do_not_execute=true`, and is not bound to the Candidate as
    an executable Approval.
24. External action counters:
    credential lookup 0; provider-client creation 0; network 0; model calls 0;
    paid calls 0. `execution_performed=false`.
25. Privacy result: `exact`, violation count 0. No Prompt, prose, raw arguments,
    unknown tool names, full response, credential/header, full provider request
    ID, absolute path, project or entity name is stored.
26. Live parity result: `exact`.
    Before and after parity SHA-256 are both
    `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
    Live DB, project tree and formal artifacts were not changed.

## 27. Tests and gates

- Focused: `7 passed in 149.00s`.
- Related Canary/R1-PA1 regression: `52 passed in 115.97s`.
- L3 strict change gate: passed; blockers 0, warnings 0.
- Full suite: `2632 passed, 2 skipped, 5 xfailed, 1 failed in 1441.99s`.
- The only failure is the pre-existing
  `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`:
  its historical expected DB hash is `5deb7bdf…`, while task-start and final live
  DB hash remain `0fccb8ae…`. New failures: 0.

## 28. Final Gate

`PA_STRICT_TOOL_OBS_1_WAITING_FOR_FINAL_USER_AUTHORIZATION`

This is approval readiness only, not real-provider evidence. Canary B remains
frozen. No Provider Smoke, Signed Approval, Pilot-5, Phase 1B, production fix or
second C0B Smoke was performed.
