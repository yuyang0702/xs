# Slice1 Phase B CURRENT Skill Baseline Materialization Final Report

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_MATERIALIZED`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_READY_FOR_USER_APPROVAL=YES`

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `033867472f23535ce2abc685934fd2a2b8e63586`
- Materialization HEAD: `b77eeb27425d9abef897f94e39c518774d3701c3`
- Initial implementation commit: `2c671259d6397104ae1205e6baac8ec9c098ab52`
- Evidence-successor gate implementation commit: `b77eeb27425d9abef897f94e39c518774d3701c3`
- Final evidence seal commit: `the commit containing this self-referential report; exact hash reported after seal`
- Final worktree target: `clean`
- Changed implementation/test files: `tools/canary/slice1_phase_b_current_skill.py`, `tests/canary/test_slice1_phase_b_current_skill_materialization.py`
- Evidence files: `18` direct files including the self-excluded SHA manifest
- PTR12 reviewed production HEAD: `28d0fcc0190e7ada8c68e0f7013cb390d7b55c66`
- PTR12 evidence seal HEAD: `033867472f23535ce2abc685934fd2a2b8e63586`
- Production source diff: `0`
- Skill arm: `CURRENT_RUNTIME_SKILL`
- Skill V2 active: `NO`
- Cohort: `slice1-phase-b-current-skill-033867472f23-001`
- Case IDs: `valid-canonical`
- Fixture SHA-256: `a1442835a44471b9be5c87c4feb4ec89853a3b4348d7215185de62ced4a4fab4`
- Authority input SHA-256: `5f1bf760e5f9201bc18d2e7b65efba7867e02f756e50f8ed73cce683a82d55e8`
- Slice1 authority binding SHA-256: `12a026ccaac25e095b7b84448633110a93d63e54ed98010b93b660330ff97455`
- Current Skill profile SHA-256: `4a9fd1d20c248ed3dae1815eb99605b094842d1e953e96d31d6ba7d1a4bf52c6`
- Model input assembly SHA-256: `50ceb8b6862c0d31252ced8e46f6ca0d87d6ec8ccc86c2a3c2c131d4f532f927`
- Route binding SHA-256: `c3b9bef17be892c4de4107707f2a5dc03f4dce8438bb74a0452c095a7e87f621`
- Route/provider/model/adapter: primary and configured fallback are hash-bound; both use `anthropic` / `AnthropicAdapter`; aliases and private endpoints are not persisted
- Primary provider/model/route: `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f` / `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff` / `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`
- Fallback provider/model/route: `98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6` / `fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998` / `04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31`
- Call graph SHA-256: `63d3005e1b120f956bfc99d7ac0cdc9bc9189baa6f7548a776d1ac19b44bcc03`
- Exact call graph: `one primary creative dispatch -> deterministic conversion -> Slice1 validation -> exact freeze or typed terminal failure`; model repair calls `0`; whole-Slice model regeneration `0`; whole-Planning regeneration `0`
- Expected / hard model calls: `1 / 1`
- Expected / hard input tokens: `2625 / 32768`
- Expected / hard output tokens: `2048 / 4624`
- Per-call output hard cap: `4624`
- Expected / hard elapsed seconds: `240 / 900`
- Expected / hard cost: `UNKNOWN / UNKNOWN` (no locally trusted current price authority)
- Budget SHA-256: `5955d151fc9c6642380feda81125365f58631f3d89f6d4b92691c4b26fca7559`
- Approval template SHA-256: `50590091c2b8d4ea93b53752afbdeb7ec9b65a6accf1ddd7292feaee9cfe77da`
- Launcher binding SHA-256: `bbdf5844de6cc4b2d8c9c4c29b11fc44d9eb176be7e27a2689ba31a3056901ad`
- Output isolation SHA-256: `3aa00463373b4afc00da15ef388930cdd525795d277023be3ba00ab860bf03b5`
- Quality capture SHA-256: `8850ac9dabfd1b7a44a8c5ca457317a0ea27e92f742fb8cafee58e8b0e2e0a0a`
- A/B comparison lock SHA-256: `ac7e3cd770c41d62a6dc750786f35593c757580d893636a168b83c09c71c6e04`
- Packet definition SHA-256: `bc8a68e9e9b3727413a99f7ce536771db8e60a5aef6c0a367cfd1497db16d16e`
- PTR12 manifest SHA-256: `78b637fac9227447e604e497f327616e23a5d2b3f03dbc30e790ed30eb1b3101`
- PTR12 manifest coverage: `11/11 exact`
- Phase B manifest definition SHA-256: `8faedf9ba4f2b71508b50d6b7769f72912006ad7a99df2e97e345c29f37a96a9`
- Phase B manifest file SHA-256: `self-excluded and reported after evidence seal`
- CURRENT Skill resolution: `story-init, plot-structure, character-management, worldbuilding`; two local runs exact
- Source classes: `GLOBAL_CODEX, GLOBAL_CODEX, GLOBAL_CODEX, GLOBAL_CODEX`
- Planning V1 production authority: `YES`
- Slice1 Phase B shadow-only: `YES`
- Whole Planning regeneration allowed: `NO`
- Output isolation: experiment artifact only; PTR12 trace remains hash/shape-only
- Quality capture: exact title/narrative plus validator, authority, causal, character, world, setup/payoff, POV/tense/tone/genre, convergence, no-progress, duplicate and whole-Planning-regeneration signals; unsupported dimensions remain `UNKNOWN`; no rigid literary score
- A/B lock: only `SKILL_CONTEXT_ARM` may differ; cohort, authority, contract, prompt body, route/model/provider/adapter, budget, call cap, retry, validators, PTR12, isolation and rubric are frozen
- Offline tests: focused Phase B `21 passed`; focused + Slice1/Skill/PTR12 adjacency `75 passed`; deterministic whole-packet rebuild `2 runs / 17 documents / exact bytes and metadata`; full canary matrix `339 passed, 2 skipped, 19 failed, 31 errors`
- Full canary non-green attribution: historical fixed-HEAD, consumed/expired approval, old materialization-parent and sealed successor gates; no new Phase B test failed and no historical evidence was rewritten
- Strict L3: `PASS`, warnings `0`, blockers `0`
- Privacy: `exact`, materialization matches `0`
- Exact next gate: `SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_USER_APPROVAL`

`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`APPROVAL_REUSE_ALLOWED=NO`  
`FULL_SHORT_AUTHORIZED=NO`  
`SKILL_V2_AUTHORIZED=NO`  
`DRAFT_AUTHORIZED=NO`  
`STORYSTATE_MUTATION_ALLOWED=NO`  
`CANON_MUTATION_ALLOWED=NO`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`SLICE1_PHASE_B=NOT_STARTED`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
