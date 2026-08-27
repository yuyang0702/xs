# Skill V3 A1 real execution boundary realization — pre-approval final report

`SKILL_V3_A1_REAL_BOUNDARY_FRESH_APPROVAL_AWAITING_USER_AUTHORIZATION`

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`.
2. Baseline HEAD: `12ae672583edd45313fe082efd11807f61aa6df6`; implementation source HEAD before evidence seal: `ccee27cd278b974e0fc48c8e13e7569bc62ea95d`.
3. Historical A1 block remains exact: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_REAL_EXECUTION_BLOCKED_PRE_DISPATCH`; nonce/credential/provider/network/model/paid counts were all zero.
4. Root blockers closed offline: approval no longer contains an inline executable nonce; launcher binds the durable nonce protocol; `RealPilotDispatcherV1` is bound to the frozen production-shaped route path.
5. Approval/nonce lifecycle: permission -> signed Approval V2 -> exact locks -> durable reserve -> post-nonce preflight -> credential lookup -> one dispatch. Approval Phase A does not create a nonce.
6. Durable ledger: `DurablePilotNonceStoreV1`, schema `SkillV3PilotDurableNonceV1`, policy `skill-v3-pilot-durable-nonce-policy-v1`, worktree-external user runtime storage, exclusive create, advisory lock, atomic replace, restart/concurrency/non-reuse fail-close. No real nonce was created.
7. Dispatcher: `tools/canary/skill_v3_real_execution_boundary.py::RealPilotDispatcherV1`, version `skill-v3-real-pilot-dispatcher-v1`; canonical environment `RealPilotExecutionEnvironmentV1`; canonical entry `launch_real_a1_once_v1`.
8. Route/provider/model: `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0` / `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f` / `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff`; primary only; output cap `4624`; route drift fails before credential lookup.
9. Credential boundary: constructor and metadata preflight perform zero credential lookup; lookup is deferred to the authorized dispatch call after nonce and post-nonce preflight.
10. Lowest outbound hard guard: `HttpProvider._before_http_post_attempt`; logical/provider/HTTP/network caps are each exactly one. Pilot retry, transport retry, fallback, route switch, resume, and second dispatch are disabled. Ordinary runtime retry remains unchanged.
11. Offline production-shaped dispatcher simulation: PASS; six frozen samples A1/B1/A2/B2/A3/B3 each reached the real dispatcher code path through a local counting transport with one fake outbound and zero real outbound attempts.
12. Failure matrix: PASS for route drift, credential absence, timeout, HTTP error, empty output, parse/schema/local validation failure, retry/fallback/switch/resume/second-dispatch attempts, restart points, and concurrent double launch; no case exceeded one fake outbound and no attempted nonce/approval became reusable.
13. Prior A1 remains blocked pre-dispatch, is not a literary sample/provider request/blind-eval artifact, and did not consume the A1 prose slot.
14. Old approval `skill-v3-a1-successor-519ac176-b439-4f91-8490-b3094367a438` / `679c7d5ea54407f2d79284ef4e7657b51aa71914641123db9ad4ebbc2cb0fa2c` remains historical, stale, unused, not consumed, non-reusable, provider requests `0`.
15. Experiment identity: sample `sv3s-089dd120ad568f87e7ef`; sample/parent/component/wire/Skill/non-Skill hashes remain exact. Prompt, route semantics, sampling, validator, and output cap are unchanged; `baml_src/**` diff is `0`.
16. Implementation commits: `6dfd964` and `ccee27c`.
17. Tests: focused `77 passed`; related `256 passed, 1 existing warning`; import-closure regression `92 passed`; full suite `3764 passed, 41 skipped, 6 xfailed, 54 failed, 72 errors, 1 warning in 2600.96s` with non-green items classified as pre-existing historical sealed-evidence/planning-skill-oracle/live-parity gates and owning-source regressions `0`.
18. Strict L3: PASS; warnings `0`; blockers `0`. Privacy: PASS; raw Prompt/story/Skill/provider content/credential values `0`. SHA manifest is `sha256-manifest-pre-approval-v1.json`.
19. Fresh approval readiness: A1 real boundary `PASS`; durable nonce binding `PASS`; real dispatcher binding `PASS`; exactly one request maximum; A1 remains next eligible and unexecuted.
20. Evidence seal commit becomes the exact `REAL_BOUNDARY_SUCCESSOR_HEAD`; after sealing, readiness is rechecked on that clean HEAD without repo writes.

No fresh signed approval was created in this task. No real nonce was created or reserved.

Required new authorization sentence:

> 我明确授权基于当前 real-boundary successor HEAD 的 A1（sv3s-089dd120ad568f87e7ef）执行所需的凭据读取、网络访问、必要请求数据外发，以及最多 1 次付费 Provider/模型请求；不授权重试、transport retry、fallback、route switch、resume dispatch、第二次请求，也不授权其他样本、Skill V3 cutover、Planning V2 cutover 或 Full Short。

`REAL_EXECUTION_NONCE_CREATED=NO`  
`CREDENTIAL_LOOKUP_COUNT=0`  
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`A1_REAL_EXECUTION=NOT_EXECUTED`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
