# Skill V3 multi-sample mapping reveal and engineering decision

## Outcome

`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT=NO_GO_QUALITY`

`NARRATIVE_NON_INFERIOR=NO`

`ENGINEERING_NON_INFERIOR=YES`

The sealed mapping reverses blind-side order in pairs 1 and 3 but not pair 2. After every frozen vote is translated per pair, all three critical dimensions are supported `BASELINE_BETTER` results. The pilot therefore fails narrative non-inferiority while passing the separately evaluated engineering hard-failure rule.

## Required report

1. Branch/start HEAD: `r1-ptr3/planning-repair-finding-propagation-20260817` / `3e9a012f5d826a222547cea21d80136b439adc1d`; starting worktree `CLEAN`.
2. Reveal decision commit/final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`; final worktree `CLEAN_AFTER_SEAL`. The actual immutable commit SHA is reported by the sealing command and final user response because a commit cannot contain its own hash.
3. Freeze SHAs: evaluator 1 `45927989be4cd126dd567393da3efebe59880ec239e9716a720ea2e54b66bd3b`; evaluator 2 `9c4c5ce98c78cd33c4404363476bce3a70f1b6b55be6211d82060b021f5d2dc6`; combined `c9be76be273049ec55c772298ceddb99964a1101abbc25edb2062523e93d4d4b`.
4. Blind chronology: bundle → evaluator 1 freeze → evaluator 2 independent freeze → combined freeze → reveal in this gate; mapping contamination `0`; policy drift `NO`; required votes `6/6`.
5. Mapping manifest: `3f6e7b4465a940ffa7448636c51b260ff4ec90f0baec8f0ebd3992514104618b` / `EXACT`; one-to-one `YES`.
6. Anonymous mappings:
- `blind-f72b8680d396280f` → `B1` / arm `B` / `sv3s-cd80aa5d21e790079a06` / artifact `63142020ccd19853c73dcc25204ffd7fe3fc0a08fed0d60d25cebf2be627d761`
- `blind-eeae3135bca45598` → `A1` / arm `A` / `sv3s-089dd120ad568f87e7ef` / artifact `c5f8dbc361b78208563d1511a4b4138a2d482504ea3321078f5ae0c56ac0c1b1`
- `blind-5f084ba2aa794cd5` → `A2` / arm `A` / `sv3s-689f28e6be27dd416760` / artifact `ce631e9c8b62f4b26b3dbba1e012be95916b3c033d48c4695bf284fb524390ae`
- `blind-645c2c2eadf86a6e` → `B2` / arm `B` / `sv3s-86c1bce67d1e52ec2aa6` / artifact `cb570cad8e573a7dfbb6c8d8ceda23f490fa058aae54367cfb12adab707a9e03`
- `blind-12cb88bb3573ce5c` → `B3` / arm `B` / `sv3s-bbd71244a306271cd726` / artifact `303310df6ba6e77872df3de9c54c4f6fc03aa6c6edfd2e9110dd28214dc7ed5d`
- `blind-d0a798450ae880c2` → `A3` / arm `A` / `sv3s-32d61044ab8db7c9b145` / artifact `bcf7ccadb47600092acf1a7eed264e7aa30cbf0b1ab5f61c27352364087a8bba`
7. Blind-side mapping is per pair, never global:
- `blind-pair-1`: blind A → arm `B` (B1), blind B → arm `A` (A1)
- `blind-pair-2`: blind A → arm `A` (A2), blind B → arm `B` (B2)
- `blind-pair-3`: blind A → arm `B` (B3), blind B → arm `A` (A3)
8. Arm A: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE` / context `7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc` / profile `109bb50e2e649c5841bd7c83513100caa0d93cf3c1bb5db845e489b5ae10856d`. Arm B: `VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY` / context `c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd`.
9. Selective-verbatim arm: `EXPERIMENT_ARM_B`; baseline control: `EXPERIMENT_ARM_A`.
10–13. Frozen blind counts, mapped results, criticality, and variance:
- `character_agency` (CRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 6, 'TIE_OR_EQUIVALENT': 0}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 2, 'BASELINE_BETTER': 4, 'EQUIVALENT': 0, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=False, opposed=False, evaluator_disagreement=False
- `causal_coherence` (CRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 6, 'TIE_OR_EQUIVALENT': 0}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 2, 'BASELINE_BETTER': 4, 'EQUIVALENT': 0, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=False, opposed=False, evaluator_disagreement=False
- `subtext_support` (NONCRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 5, 'TIE_OR_EQUIVALENT': 1}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 1, 'BASELINE_BETTER': 4, 'EQUIVALENT': 1, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=True, opposed=False, evaluator_disagreement=True
- `specificity` (NONCRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 6, 'TIE_OR_EQUIVALENT': 0}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 2, 'BASELINE_BETTER': 4, 'EQUIVALENT': 0, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=False, opposed=False, evaluator_disagreement=False
- `scene_pressure` (NONCRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 6, 'TIE_OR_EQUIVALENT': 0}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 2, 'BASELINE_BETTER': 4, 'EQUIVALENT': 0, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=False, opposed=False, evaluator_disagreement=False
- `setup_payoff_integrity` (CRITICAL): blind `{'BLIND_SIDE_A_BETTER': 0, 'BLIND_SIDE_B_BETTER': 5, 'TIE_OR_EQUIVALENT': 1}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 1, 'BASELINE_BETTER': 4, 'EQUIVALENT': 1, 'INCONCLUSIVE': 0}` / `BASELINE_BETTER`; variance=True, opposed=False, evaluator_disagreement=True
- `voice_readiness` (NONCRITICAL): blind `{'BLIND_SIDE_A_BETTER': 1, 'BLIND_SIDE_B_BETTER': 5, 'TIE_OR_EQUIVALENT': 0}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 3, 'BASELINE_BETTER': 3, 'EQUIVALENT': 0, 'INCONCLUSIVE': 0}` / `INCONCLUSIVE`; variance=True, opposed=True, evaluator_disagreement=True
- `anti_template_risk` (NONCRITICAL): blind `{'BLIND_SIDE_A_BETTER': 1, 'BLIND_SIDE_B_BETTER': 4, 'TIE_OR_EQUIVALENT': 1}` / `BLIND_SIDE_B_BETTER` → mapped `{'SELECTIVE_VERBATIM_BETTER': 3, 'BASELINE_BETTER': 2, 'EQUIVALENT': 1, 'INCONCLUSIVE': 0}` / `INCONCLUSIVE`; variance=True, opposed=True, evaluator_disagreement=True
14. Narrative policy SHA: `d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21`; no scalar averaging or retrospective tuning.
15. Selective critical counts: `{'better': 0, 'equivalent': 0, 'regression': 3, 'inconclusive': 0}`. Selective noncritical counts: `{'better': 0, 'equivalent': 0, 'regression': 3, 'inconclusive': 2}`.
16. `NARRATIVE_NON_INFERIOR=NO`. This is a critical-regression decision, not a generalized architecture claim.
17. Engineering campaign: `6/6 SEALED_VALID`; Provider/HTTP/network requests `6/6/6`; per sample Provider attempts `1`; retry/transport retry/fallback/route switch/resume/second dispatch all `0`; approvals/nonces all single-use and consumed.
18. Engineering comparison: both arms `3/3` valid and terminal-pipeline PASS. A/B skill-context chars `2925/2556`; token estimates `732/639`; headroom `17488/17581`. `TOKEN_COMPARISON_SUFFICIENT=NO`; `COST_COMPARISON_SUFFICIENT=NO` because A1 input tokens and most other token/finish fields were not retained and cost is unknown. A1 alone observed `output_tokens=649`, `finish_reason=end_turn`.
19. `ENGINEERING_NON_INFERIOR=YES`; all named selective-verbatim regression categories are false.
20. Final disposition: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT=NO_GO_QUALITY`.
21. This proves bounded character-heavy engineering non-inferiority and a character-heavy narrative no-go for the current Selective Verbatim context. It does not prove generalized Skill V3 behavior, other demand-class behavior, actual token/cost parity, or cutover readiness. `ONE_CHARACTER_HEAVY_MULTI_SAMPLE_PASS_DOES_NOT_PROVE_GENERALIZED_SKILL_V3_NON_INFERIORITY`.
22. Cutovers: Skill V3 `NO`; Planning V2 `NO`; production authority `false`.
23. Full Short: `NOT_EXECUTED`.
24. Tests: focused `9 passed in 0.93s; final materialized evidence rechecks 9 passed in 1.01s and 9 passed in 0.96s`; related `71 passed in 69.49s`; full offline `3809 passed, 41 skipped, 6 xfailed, 54 failed, 72 errors in 2238.38s; non-green items are historical sealed-evidence/materialization/Planning-Skill/R0E-R0F live-parity gates; no new owning-source failure`; Strict L3 `PASS; warnings=0; blockers=0; declared L3; core_paths=0`; warnings/blockers `0/0`; new owning-source regressions `0`; privacy `PASS`; manifest covers every evidence file except itself.
25. Exact next gate: `SKILL_V3_SELECTIVE_COMPILER_MULTI_SAMPLE_QUALITY_ROOT_CAUSE`.

## External and authority state

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`NEW_LITERARY_EVALUATION=NO`

`SKILL_V3_CUTOVER=NO`

`PLANNING_V2_CUTOVER=NO`

`FULL_SHORT_CANARY=NOT_EXECUTED`
