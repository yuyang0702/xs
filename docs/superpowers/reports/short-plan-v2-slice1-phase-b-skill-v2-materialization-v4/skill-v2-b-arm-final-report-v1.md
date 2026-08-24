# Skill V2 REAL A/B B-arm Materialization v4

`SKILL_V2_B_ARM_POST_SEAL_TEST_MATERIALIZATION_PARENT_FIXED`

`SKILL_V2_REAL_AB_B_ARM_REMATERIALIZED_V4_AFTER_POST_SEAL_TEST_FIX`

`SKILL_V2_REAL_AB_B_ARM_READY_FOR_FRESH_USER_APPROVAL=YES`

## Required delivery fields

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `1f6e9a715e96b41e1e4ebf70039f392a63bcf15b`
3. Implementation/support commit: `cf8788060fd6ae0101ad05424ef157945bce983c`
4. R0F successor: `NOT_REQUIRED` (`src/**` and protected production source diff `0`)
5. B-arm materialization seal commit: `REPORTED_AFTER_EVIDENCE_ONLY_SEAL`
6. Final HEAD: `REPORTED_AFTER_EVIDENCE_ONLY_SEAL`
7. Final worktree target: `clean`
8. A-arm baseline verification: `SEALED_PASS`; materialization `22/22` exact; execution `15/15` exact
9. A-arm artifact SHA-256: `b3588452679d0d5c39c4b86db63c98dc440868cdb2cd951d1262f426b234cb67`
10. A-arm quality baseline SHA-256: `7591bbb790b3d038b9a7a3948654984ebe9c54688c4206813cf19aac6b018968`
11. AB_PAIR_ID: `skill-v2-real-ab-20260824-v4-001`; predecessor `skill-v2-real-ab-20260824-v3-001`
12. B-arm cohort: `slice1-phase-b-skill-v2-real-ab-v4-20260824t121408z-001`
13. Exact B-arm approval scope: `SLICE1_PHASE_B_SKILL_V2_REAL_AB_B_ARM_SINGLE_DISPATCH_V4_ONLY`
14. Skill V2 design artifact/hash: `docs/superpowers/reports/planning-skill-profile-shadow-v1/runtime-skill-profile-schema-v1.json` / `a8788372fd23a1ccf970315519ed94fa1c449d34c8420b300241024de4fbb9c8`
15. Skill V2 profile artifact/hash: `docs/superpowers/reports/planning-skill-profile-shadow-v1/planning-v2-event-realization-profile-v1.json` / `0eb3b0f928f2b2a5fe182b632dc80b3a1573e51f1ff2f4c9997a3a8587185f58`; sealed fixture canonical profile `743a9a94aa609c6cab1dd322ccbd2be4439316fe87abc3ca273cfe3f14526629`
16. Skill V2 offline-quality artifact/hash: `docs/superpowers/reports/planning-skill-profile-offline-quality-v1/final-report-v1.md` / `95cb58598d5aba45e6b5cfabff72c3607619fabe93d7283858e612e8df88a154` / `VALIDATED`
17. Skill V2 runtime profile source/hash: `src/novel_flywheel/runtime_skill_profiles.py` / `103b92403fdfb3ecba59a91bc28fdae146c8d87c975a12ca037e0b19350b9a93`
18. Rendered Skill V2 context SHA-256: `a77ca32533e7e480ab3b0ff53d55dde5bed4ff837b8b68f53b7aba59a8d6fd15`; characters `1587`; token estimate `397`
19. Current Skill A-arm profile SHA-256: `4a9fd1d20c248ed3dae1815eb99605b094842d1e953e96d31d6ba7d1a4bf52c6`
20. B-arm Skill V2 profile SHA-256: `7a6022faa3d0db198a28727d44067cd56d83649536a6b37fee27e91ee170d082` (`PLANNING_V2_EVENT_REALIZATION_PROFILE_V1@1`)
21. A-arm model-input SHA-256: `8b94aab84342063b6f172f21a68feb5d21bf132857d8aae1fe6685c0dc720725`
22. B-arm model-input SHA-256: `387380e61ac4ed098b00a4b45f3299035c0455a9963a58a56f489e3f3e15dc94`
23. Non-Skill prompt equality: `YES` / `26c789b6bc96e406337ef6a545818eeaec48165adcde9adb2310c5b047c31e85`
24. Authority-input equality: `YES` / `017e64fc8e33e84d8ca3b43ba9c9e035d47e58cc06a28c64a853cea95637a8c4`
25. Task-contract equality: `YES` / `84bed63082c9b4abd588790f9292d29aa466ee14e8b085c403ebb47ded2ab0ad`
26. Route/model/client equality: `YES` / `c3b9bef17be892c4de4107707f2a5dc03f4dce8438bb74a0452c095a7e87f621`
27. Output-cap equality: `YES` / `4624` tokens
28. Transport-policy equality: `YES` / `c5d6166cfd262d86e9a7efa854d8c27ff4274f50fee7061833361435d103735d`
29. Validator-policy equality: `YES` / `a41e1918b26cc23414067c162142b78166838a61a7fee04a114d9fbf034d6f83`
30. PTR12 equality: `YES` / `fa020549b398e003c4c3d2f07621d26272688096285a09a7b47b0309665a4424`
31. Output-isolation policy equality: `YES`; B namespace binding `8836c2793770d6acc975e6dcc6801a67276ad8a4373f428e948babbcd54ee9d0`
32. Quality-rubric equality: `YES` / `3d65d91e369afdf43dfc0926d3a0605ab6f389ab6ee1da65e4712da981091e10`; no scalar score
33. Engineering-rubric equality: `YES` / `f33e782e51e0bf46a6a6285df7010502e7d9d11ebc45ec8d4757b7b1dc1dacf4`; unknown remains unknown
34. B-arm launcher source/binding SHA-256: `251065266527cf23651ba496138608d424f0c79e99733e44448827510a51c167` / `6d109dbc53e1d57fd0ca3d6d4bdbff86c9b9fee495e4053fea82b9dc69d3441d`
35. Authority tuple binding: `PASS` / `6775a251e3fece7225e4ddb2a780e18ceccb5a3ccfff785004837a44dbc5805a`
36. Audit serialization binding: `PASS` / `ac37cdd64d1660195bce25a91cc76c3b425cde56ada5e5d915a96b1cd3d8aa21` / `model_dump(mode="json")`
37. Transport guard binding: `PASS` / `9b40e09f83a130eab8ac410ff705d020b7923748e423c440912ffd7d74fa829d`
38. Attempt-accounting binding: `381d20e6dba5c9e254c0c176fc71db0e0ec003a04afb2b1b943642a2dd985dc8` / hard caps `1/1/1/1`
39. Budget binding: `ecde9e0bd216100df9cb3578dca82367215e44f941d4cf26ad94b739c441431f` / output cap `4624` / elapsed `900`
40. Output-isolation SHA-256: `8836c2793770d6acc975e6dcc6801a67276ad8a4373f428e948babbcd54ee9d0`
41. PTR12 SHA-256: `fa020549b398e003c4c3d2f07621d26272688096285a09a7b47b0309665a4424`
42. Quality-rubric SHA-256: `3d65d91e369afdf43dfc0926d3a0605ab6f389ab6ee1da65e4712da981091e10`
43. Engineering-rubric SHA-256: `f33e782e51e0bf46a6a6285df7010502e7d9d11ebc45ec8d4757b7b1dc1dacf4`
44. A/B comparison-lock SHA-256: `8185d3e964b9e6a4834c01ed6c83d4c7ca219ccac800cdb3384086331840426c`
45. Approval HEAD successor contract SHA-256: `5132ebceb462a11bafb8ed969a0db65c6ff2a748d87916cf6a6ca90028c687d2`
46. Ancestry typed fail-close SHA-256: `0f036421608e882f5ef02c8c5fb2553ca80defea179cd6044db1c6554263fd3c`
47. Approval HEAD successor validator SHA-256: `c76a9eb16275e463fa5940ca71d2806e2bc81ee0d82c56a8d7099448c37e06f0`
48. Historical roots binding: `PASS` / `c9a1f1886a29b5d968c172282addd83fabfca9224c4724c5bd139571f97c39f8` / exact v1+v2+v3 only / writes `0`
49. Committed-path baseline policy: `PASS` / `0d39ede37f93609b45fdeb72bf1dd93641108d80b3843ce91eaf941e6caa476b` / prefix acceptance `NO`
50. Offline B-arm tests: focused `PASS`; related `PASS`; full suite `RECORDED_SEPARATELY`; Strict L3 `PASS`
51. Synthetic full success-tail: `PASS` through parser -> model_validate -> local derivation -> validator -> FROZEN -> audit -> write -> persistence
52. Manifest definition SHA-256: `SEE_SELF_EXCLUDED_SHA256_MANIFEST_AND_FINAL_SEAL_REPORT`
53. Manifest file SHA-256: `SEE_FINAL_SEAL_REPORT`
54. Manifest coverage: `ALL_NON_MANIFEST_FILES_EXACT`; exact count is bound in self-excluded manifest
55. Privacy: `EXACT`; credential/raw Provider/raw story/private absolute path matches `0`
56. External counters: credential `0`, Provider client `0`, Provider request `0`, HTTP POST `0`, network `0`, model `0`, paid `0`
57. Exact next gate: `SKILL_V2_REAL_AB_B_ARM_FRESH_USER_APPROVAL_AFTER_POST_SEAL_TEST_FIX`
58. Post-seal test parent binding: `PASS` / `d9e2fa5e43a3bb017663b1604822817e03bb08c76a3052abf71743c972ab724d` / source `SEALED_SIGNED_APPROVAL_OR_CANONICAL_BINDING`
59. Old v3 approval: `INVALIDATED`; nonce `INVALIDATED_UNCONSUMED_UNRESERVED_NOT_EXECUTABLE`; reuse `NO`

## Closed-world conclusion

The A/B model input uses the same sanitized authority, task contract, non-Skill
prompt body, route/model/client, output cap, transport, validator, PTR12, audit,
freeze, quality, engineering, and mutation policies. The only semantic model-input
variable is the rendered Skill Context. The B profile remains shadow-only and is
not production active.

`A_ARM_STATUS=SEALED_PASS`  
`B_ARM_STATUS=MATERIALIZED_NOT_EXECUTED`  
`PRIMARY_CHANGED_VARIABLE=SKILL_CONTEXT`  
`SKILL_ARM=SKILL_CONTEXT_V2`  
`SKILL_V2_PRODUCTION_ACTIVE=NO`  
`NON_SKILL_PROMPT_EQUAL=YES`  
`AUTHORITY_INPUT_EQUAL=YES`  
`TASK_CONTRACT_EQUAL=YES`  
`ROUTE_MODEL_EQUAL=YES`  
`OUTPUT_CAP_EQUAL=YES`  
`TRANSPORT_POLICY_EQUAL=YES`  
`VALIDATOR_POLICY_EQUAL=YES`  
`PTR12_EQUAL=YES`  
`OUTPUT_ISOLATION_POLICY_EQUAL=YES`  
`QUALITY_RUBRIC_EQUAL=YES`  
`ENGINEERING_RUBRIC_EQUAL=YES`  
`SINGLE_DISPATCH_TRANSPORT_GUARD=PASS`  
`AUTHORITY_TUPLE_NORMALIZATION=PASS`  
`AUDIT_SERIALIZATION=PASS`  
`FULL_SUCCESS_TAIL_OFFLINE=PASS`  
`APPROVAL_PARENT_HEAD_VALIDATION=PASS`
`ANCESTRY_FAILURE_TERMINATES_IMMEDIATELY=YES`
`APPROVAL_PARENT_HEAD_MISMATCH_TYPED=YES`
`RAW_SUBPROCESS_ERROR_LEAKED=NO`
`GIT_DIFF_AFTER_ANCESTRY_FAILURE=NO`
`CURRENT_HEAD_SUCCESSOR_VALIDATION=PASS`
`WRONG_HEAD_REJECTED=YES`
`EVIDENCE_ONLY_SUCCESSOR_ACCEPTED=YES`
`ARBITRARY_DESCENDANT_REJECTED=YES`
`SOURCE_MUTATION_SUCCESSOR_REJECTED=YES`
`HEAD_VALIDATION_BEFORE_NONCE_RESERVATION=YES`
`HISTORICAL_ROOTS_V1_V2_V3_EXACT=YES`
`HISTORICAL_ROOTS_READ_ONLY=YES`
`ARBITRARY_HISTORICAL_ROOT_ACCEPTANCE=NO`
`POST_SEAL_FOCUSED_HEAD_SUCCESSOR_TEST_MATRIX_EXACT=PASS`
`TEST_APPROVAL_PARENT_SOURCE=SEALED_SIGNED_APPROVAL_OR_CANONICAL_BINDING`
`INVALIDATED_APPROVAL_REJECTED=YES`
`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`SIGNED_APPROVAL=ABSENT`  
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`HTTP_POST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
