# R1-PTR4-PROBE-MAT — Fresh Provider Capability Probe Approval Packet

## Final Gate

`R1_PTR4_PROVIDER_CAPABILITY_PROBE_APPROVAL_PACKET_READY`

`R1_PTR4_PROVIDER_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION`

This is an inert, disabled, single-use control-plane packet. It is not a Signed Approval, confirmed patch, executable command, Provider capability observation, Full Short run, or Production Fix.

## Repository and parent evidence

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Materialization parent HEAD: `f7f67095a72ede2bce62a583fac1cf43fb620e80`
- Starting worktree: clean
- R1-PTR4 evidence commit: `ddcc0965ba8cbf6accb932d8898a77232ee8a13c`
- Historical probe-materialization NO-GO commit: `b7d3f5c9c724e2ec6a02fab0c9acc9ab6777c921` — preserved unchanged
- R1-PTR4-V1 contract commit: `f7f67095a72ede2bce62a583fac1cf43fb620e80`
- R1-PTR4 canonical SHA: `e7806b206edbdddf21a1ea74c7d0ebbb327ccedf7216f528c281c4ac2edfdf4c`
- R1-PTR4-V1 canonical SHA: `844516d3d45a472134d8c724b817ab2c3a1f9c0f73f95d2b9b4b30322eed2181`
- Both parent manifests: exact
- Both parent privacy scans: exact, zero violations
- `src/novel_flywheel/**` diff: 0 files
- `baml_src/**` diff: 0 files
- Live parity before/after: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` / same

## Probe contract bindings

- Probe Definition SHA: `6f201a3687d46d7be83f7c9797b03b26abdd346cc897f0f1ef87f0ab57ae5aee`
- Fixture SHA: `22ac37e6494de79f542596cd16d5c14b8b25229af5cc1f451957e101b1c87e64`
- Observer Schema SHA: `d88652767f2d5fe72fce529cdc51c51e7897daa9b16fd869092aa20b30d7dfa3`
- Boundary identity SHA: `851b447afba31d2296ebafc223ea4189464920e332693a5a03d5cf0b821675f0`
- Boundary: 12
- Stage/substage: `planning` / `planning-semantic-v2-segment-01-packet-000001-0`
- Contract: `planning_semantic_v2` v2
- Contract SHA: `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`
- Route/protocol/mode: `configured_fallback` / `anthropic` / `plain`
- Provider descriptor hash: `98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6`
- Model binding hash: `fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998`
- Request wire schema SHA: `6098e362b6370cbb0d63710f56f355561af549188e1eeaa5d267862f290c95be`
- Tool schema SHA: `5424046dc2054fb588e161be0ef09b4badc53b150c78dc9f6ca3866cca590311`
- Requested/local effective output: 8,798 / 8,798
- Effective Provider maximum and raw content-block shape: UNKNOWN

Provider/model identities are hash-bound and cannot be manually replaced. The fixture embeds no Prompt, story, tool arguments, or Provider content. A future separately authorized execution must reconstruct the request and match all sealed hashes before any external action.

## Fresh packet identity

- Cohort: `r1-ptr4-probe-20260820t110721z-001`
- Run namespace: same as cohort
- Cohort status: unused
- Approval reservation: unreserved
- Execution window: `2026-08-20T11:22:21Z` → `2026-08-22T11:22:21Z`
- Plan SHA: `6bc5672575098fcd94fe873de4e5fb880c5e396d76f0c49b87b406c1aa899749`
- Candidate SHA: `f8e25a05cf8d8f8fa35e4d14f81f6ac4c24d523bedd31de5e39fec4d79677bf3`
- Authorization Patch Template SHA: `27167c4eea1c401bd63ecac1d8843e731c479bfa96a3c49327aec31e4d6dd716`
- Validate-only Receipt SHA: `8d83290ae0558a3d24705d8e72dd9b425d052ff3a2cd33acc86133e808c481a6`
- Execution Preview SHA: `f67160870d8bd31fb029383754fe2e54e40ace1fcad6afddec1ebdd2f7d46b7b`
- Materialization Index SHA: `2c21368a54eef4312223e130b5db42d1a9d8fce3a97ab142d0619d87f65385dc`
- Operational Readiness SHA: `2e67497f15c7a1431df602b512f9e03a54193e883997917fe71f08f6d69522eb`
- Pre-launch Rehearsal SHA: `05aa7ad113eea3ea3ca3396154e0e8fba3157bea5e76459f74b17d3d4bf7ee72`

## Ledger and Canary root

- Ledger identity SHA: `56e8afd9ffb032742d04f0a31464defc36a4aea69e83239a7b778172470df3e1`
- Ledger status: exact
- Ledger entry count: 0
- Ledger reservation status: unreserved
- Canary root identity SHA: `c63fdb13eb2857549d247dd676dacc7295670f5e839ceb6dc793631caa5cbb01`
- Canary root status: unused
- Canary root entry count: 0

## Budget and stop policy

The sealed formal probe contract is stricter than the fallback defaults, so the packet uses:

- maximum runs: 1
- expected/maximum total model calls: 1 / 1
- maximum input tokens: 128,000
- maximum output tokens per call and total: 8,798 / 8,798
- maximum USD/CNY: 5 / 10
- maximum elapsed seconds: 1,800
- first terminal stop: true
- retry, implicit primary/fallback, expansion, resume, and second run: false
- Full Short, Draft, Final Review, Maintenance, and Production Fix: forbidden

## Validate-only and rehearsal

- Candidate: `execution_authorized=false`, `usage_status=unused`, disabled
- Authorization Patch Template: inert and unconfirmed
- Signed Approval: absent
- Confirmed Patch: absent
- Validate-only overall status: exact
- Fake rehearsal: exact, `fake_rehearsal_only`
- Fake observer receipt generated: yes
- Goal-stop/control-plane/privacy checks: exact
- Final packet privacy scan: exact, zero violations
- Fake evidence counted as Provider capability evidence: no
- External action counters: credentials/provider client/network/model/paid = `0/0/0/0/0`

## Tests

- Focused materialization suite: 15 passed, 0 failed
- Related suite without historical expired approval fixtures: 65 passed, 2 skipped, 0 failed
- Extended related suite: 95 passed, 2 skipped, then one pre-existing `approval_outside_execution_window`
- Complete suite fail-fast: 261 passed, then one pre-existing `approval_expired`
- Novel Development Council strict L3 gate: passed, zero warnings/blockers

The two clock-sensitive failures belong to historical PA/C0B authorization fixtures outside this task. They were not renewed, re-dated, or modified.

## Files changed

- `tools/canary/provider_capability_probe_materialization.py`
- `tests/canary/test_provider_capability_probe_materialization.py`
- New cohort directory `docs/superpowers/reports/r1-ptr4-probe-mat/r1-ptr4-probe-20260820t110721z-001/**`

No existing R1-PTR4, R1-PTR4-V1, or historical NO-GO evidence file was modified.

## Explicit stop state

`REAL_PROVIDER_PROBE = NOT_EXECUTED`

`FULL_SHORT_CANARY = NOT_EXECUTED`

`SIGNED_APPROVAL = ABSENT`

`CONFIRMED_PATCH = ABSENT`

`PRODUCTION_FIX = NOT_IMPLEMENTED`

`NEW_SINGLE_USE_APPROVAL_REQUIRED = YES`

Work stops at the disabled packet gate. No Signed Approval, confirmed patch, executable command, Provider call, network/model/paid action, Full Short, or Production Runtime change was materialized or performed.
