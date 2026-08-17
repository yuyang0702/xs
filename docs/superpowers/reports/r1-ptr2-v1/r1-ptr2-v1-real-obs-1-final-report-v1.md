# R1-PTR2-V1-REAL-OBS-1 Final Report

## Final gate

`R1_PTR2_V1_OBSERVATION_TARGET_NOT_EXERCISED`

The one authorized real observation was executed once and stopped. The target
Planning targeted-repair boundary did not occur naturally. The Canary goal-stop
blocked the next Provider boundary before Planning Review dispatch.

## Authorization and signed closure

- Authorized branch: `r1-ptr2-v1/validate-only-handler-fresh-packet-20260817`
- Authorized HEAD: `daaae4350bb97a658a84b74286e33ced594d6622`
- User authorization file SHA-256: `579c57f0d3351be81068b210ef641d598d0c31fcef0398192f8e3ab565b32ca0`
- Confirmed Patch canonical SHA-256: `09ca9401fe7f951a8885325ace0eff25193c7bcaeb99318638d3b68bb4599816`
- Signed Approval canonical SHA-256: `30e125fa2e3ec0b3b1e6020625fad55debbada72f45dd87b4f74a6fefd9f12b5`
- Signed validate-only receipt SHA-256: `33745870fa549764afd4936a0a985930904c6c412261f217f8e23d4076cf1953`
- Closure profile: `planning_repair_observation_closure_v1`
- Closure definition: `be85eb380988eb0edc7e04a9277e136c33a61d1195bc39d9cf62487ebd4d6ab9`
- Closure result: 43/43 exact; schema `PlanningRepairObservationApprovalClosureValidationV1`
- Before validate-only: credential, Provider client, network, model, and paid counters were all 0.

## Execution outcome

- Runner outcome: `CANARY_OBSERVATION_GOAL_REACHED_STOPPED`
- Reason: `planning_repair_observation_goal_safe_stop`
- Observation goal outcome: `PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED`
- Target exercised: no
- Primary evidence status: `not_exercised`
- Workflow terminal counted: no
- Production incident counted: no
- Final run status: cancelled by Canary-only goal-stop
- Evidence canonical SHA-256: `02a20c331ecc15f34607b45d9f4866cf9e5616f4e7c035bc206984e219d7fd7b`
- Goal receipt SHA-256: `4096facc14fbe5ac7bab9a1f7a3aee85ee477391bb26bda06efcaacce46539a9`

The initial Planning boundary produced a valid contract result. No Domain failure
was observed and no targeted repair was scheduled. The goal controller therefore
marked the target not exercised and blocked boundary ordinal 2 before its Provider
dispatch. `blocked_dispatch_count=1`; there was no budget reservation, credential
lookup, Provider-client creation, network call, or paid call after goal reach.

## Calls, tokens, cost, and elapsed time

- Credential lookups: 1
- Provider clients created: 1
- Network calls: 1
- Paid model calls: 1
- Route: Planning primary
- Protocol: `anthropic`
- Model binding hash: `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff`
- Provider descriptor hash: `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f`
- Finish reason: `tool_use`
- Reserved input/output tokens: 1,837 / 7,774
- Provider-reported input/output tokens: 0 / 863
- Actual recorded cost: CNY 0.005903; USD 0
- Full run elapsed: 36.787309 seconds

The Provider did not expose a usable input-token count; the report preserves 0 as
reported and separately records the conservative 1,837-token reservation.

## Runtime and policy binding

- Build: `6a813386e6e0200c2a8f41a118748702f3eecd3d86117ec5cb7d58d341387d6e`
- Config: `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`
- Runtime Execution: `8e3fc9d5fb271ee62f835ebc27165bf0b32254bf3c1f43e2d4b121a6d514413b`
- Launcher: `5c38d3be4d72f806bb8ee22879fbe99d2d1f12290d793a8bff993c58cc507c28`
- Boundary preflight receipt: `ab51a157c210d0c881bdd96e9d4b00d78091ac2f658b295b3911bf4cfbac8b6e`
- Prompt/request parity: `273aac3fc1ed12d58b7a487a7a88ff13414d621ea15532f4c43616bf77cb0523`
- System Prompt hash: `d92cd3d498e6c528b0712f4eda1ad5b0581eb7d61e19402d57051ffae058d3ca`
- User Prompt hash: `bc7cbc6151c698d3e827b37eb2f40836166c10b938827c957264e9dbe013b5bb`
- Role/Route binding: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`
- Provider descriptor manifest: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`
- Domain Validator policy: `77111523e334421e7165af4af5fe59176ddd2e575ebb5fe7d2429e9cab05477a`
- Target filter: `3e7e25963eea65e85cabf20dc4da160e16448594981d8129956d018d0fd9a9e3`
- Observation goal: `d9f4b956d9b9dd6906889830eb4e9d9dc3284c431a14c90124df6d798e91dd71`

Feature flags remained exact: reliability trace and Planning repair evidence trace
enabled; strict-tool observation, PA budget counterfactual, Canonical V2, and
Phase 1B disabled. Production repair budgets remained
`1977, 1977, 1977, 3954`; counterfactual remained false. Prompt, route, retry,
fallback, and production budget behavior were not changed.

## Evidence A/B/C/D

- Evidence A — first real Domain failure: not produced; no Domain failure occurred.
- Evidence B — Finding Propagation: not produced; no targeted repair followed.
- Evidence C — Provider fallback shape: not produced; fallback was not reached.
- Evidence D — output-limit observation: not produced; output limit was not reached.
- Terminal amplifier: `not_reexercised`.

The four offline pre-launch observer rehearsal receipt SHAs remain:

- Domain validation: `739ab95b15aac228f1d66dc12d0733c7a0a39f6b71161217bd15c1da35317783`
- Finding propagation: `d48ab7fd9aeb5e6c7943ad2de7880af98176590b3cbab425d8c5a3cd930130d4`
- Provider content-block shape: `809e147ae3758936dec1e86f63452d6d96757e6a2e673c19339f43539036fb61`
- Output limit: `782441ad2e033fd4b3e0dc11b01632ef68a72300898806b64ca000701cee5afb`

These are rehearsal receipts, not fabricated real-observation receipts. Because the
target was not exercised, there are no exact Domain rule paths, invariant IDs, or
Finding Propagation status to report.

## Ledger, cohort, safety, and parity

- Cohort: `planning-repair-observation-1-20260817t052829z-v1`
- Reservation SHA-256: `36d39afb90853a33c9de13adf25db7fa58184a1613aa134683b6f49a125fb956`
- Consumption SHA-256: `a6e15ad4154590be4d2f1d385d7ec66dc7cd5c677e6864682eb3f42e26dda21e`
- Cohort state: consumed; replay is forbidden.
- Post-goal next-stage budget reservations: 0
- Post-goal Provider-client creation delta: 0
- Post-goal Provider dispatch delta: 0
- Privacy: hash/shape/count only; raw Prompt, model output, tool arguments, credentials, headers, and Provider response are excluded.
- Live parity: exact, before/after `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
- Coverage gaps retained: relay upstream exact version unknown; relay public max output unknown; packaged runtime not executed.

## Reliability conclusion

No `PRIMARY_ROOT_CAUSE`, secondary contributor, or terminal amplifier may be
assigned from this observation. The canary proves the target was not naturally
reachable in this single exposure and proves goal-stop enforcement. It does not
prove that the historical Planning repair failure is fixed or absent.

No production fix was implemented. No second observation, approval, Short
Completion, Draft completion, Final Review, Maintenance, Pilot, Phase 1B, or
long-form run was started.
