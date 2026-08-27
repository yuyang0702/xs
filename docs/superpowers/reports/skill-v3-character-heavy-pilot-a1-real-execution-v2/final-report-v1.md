# Skill V3 A1 Real Execution V2 — blocked pre-dispatch

`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_REAL_EXECUTION_V2_BLOCKED_PRE_DISPATCH`

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`.
2. Pre-execution HEAD/worktree: `be43a7ff70a3f4722daf8a610571185c68f08866 / CLEAN`.
3. Pilot/sample/arm/index: `skill-v3-character-heavy-multi-sample-v1-4d47410b0144360d / sv3s-089dd120ad568f87e7ef / A / 1`.
4. Same-chat permission covered the general A1 single-request actions and prohibitions, but did not explicitly name the concrete network destination required by the outbound safety boundary.
5. Approval V2: `skill-v3-a1-real-boundary-20260827t134753z-5ef85b99b9335fc5`; SHA `ac322e6182e6b4ae0cb1c20f4663ca6d170cf81877dfa75bb79ac3c34cda55d5`; authorization SHA `a40caf98c973fad7e654117533590f0e5eecbd5064ccb77592172626f7482972`; window `2026-08-27T13:47:53Z` to `2026-08-27T15:47:53Z`; state `unused`.
6. Sample/parent/component/wire locks: `8bc9c05794e1dbecb095a9a1b9937d9a277c5efa462b83c6b7e1e49495b862a7` / `8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b` / `d215fdf2590b39e43f63e28944a09f244b55177f09039acb67ebb87008acae85` / `47d7e240783edf70528dc05b1c6694271a4228677fee2ef358db398d35a406f5`.
7. Skill/non-Skill/provider/model/route/validator bindings were exact; route fingerprint `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`; output cap `4624`.
8. Dispatcher/nonce policy: `skill-v3-real-pilot-dispatcher-v1` / `skill-v3-pilot-durable-nonce-policy-v1`.
9. Capacity `PASS`; advisory truncation/shedding `false/false`; actual egress count `0`.
10. First failing invariant: `EXPLICIT_CONCRETE_DESTINATION_AUTHORIZATION_NOT_PROVABLE`.
11. The execution command was rejected before process creation. No workaround or indirect dispatch was attempted.
12. Nonce created/reserved/consumed/invalidated/closed: `0/0/0/0/0`; final state `NOT_CREATED`.
13. Credential lookup / Provider client creation: `0 / 0`.
14. Logical / Provider / HTTP / network / paid attempts: `0 / 0 / 0 / 0 / 0`.
15. Retry / transport retry / fallback / route switch / resume / second dispatch: `0 / 0 / 0 / 0 / 0 / 0`.
16. Input/output tokens: `0 / 0`; finish reason `BLOCKED_PRE_DISPATCH`.
17. Provider result shape, parse, conversion, schema, domain, and local terminal pipeline: `NOT_REACHED`.
18. Sample validity: `NOT_EXECUTED`; literary artifact absent; blind evaluation ineligible.
19. StoryState/Canon/READY mutations: `0/0/0`; production authority `false`.
20. Production source diff and `baml_src/**` diff: `0 / 0`.
21. Approval remains unused and unconsumed; automatic reuse or renewal was not performed.
22. B1 auto-advance: `NO`; Skill V3/Planning V2 cutover: `NO`; Full Short: `NOT_EXECUTED`.
23. Focused offline validation: `99 passed in 95.88s`; Provider replay count `0`; new owning-source regressions `0`.
24. Strict L3: `PASS`, warnings `0`, blockers `0`; privacy: `PASS`, matches `0`; manifest verified exact after materialization.
25. Post-outcome commit message: `Seal Skill V3 character-heavy A1 real execution V2`; the resulting commit/final HEAD and clean worktree are reported after commit creation because a commit cannot embed its own hash without changing that hash.

`EXACT_NEXT_GATE=SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_A1_INVALID_OR_BLOCKED_DISPOSITION`
