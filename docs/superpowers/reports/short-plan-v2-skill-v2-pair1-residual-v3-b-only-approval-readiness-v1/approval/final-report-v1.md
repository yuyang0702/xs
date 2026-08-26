# Pair 1 residual V3 B-only fresh user approval — final report

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `5e575babc4cc7c411c645ecb8b0fc9c14a3531b2`
3. Approval/evidence commit(s): `evidence-only seal commit containing this report`
4. Final HEAD: `the evidence-only seal commit reported by Git after sealing`
5. Worktree: `clean after evidence-only seal commit`
6. Readiness packet SHA: `1ed7d0eb79127c2ffa74f449770bec6d3a9ce1d320a34b517e9df6d249c4416e`
7. Candidate SHA: `c3b8562c359328148e34215db3c5b36e432e6bfe3bdd061740f0ab9299d30bdd`
8. Case ID: `restored-character-heavy-v2-residual-v3`
9. V3 Skill arm: `RESTORED_SKILL_V2_CHARACTER_CORE_V3` / `B_ARM`
10. V3 profile SHA: `82a4542326e9b20771efc5f05e080ff0ac56438bef8288d61f30e6d905af708a`
11. V3 context SHA/chars: `98c5adc38074f442a986764fb140baf4d3bf3fa1ab58e34ba7f82b7ddc8888ba` / `2998`
12. Successor V3 A/B lock SHA: `817d88552c273fc2a9521423725af7460fd09b83b9d3eb558d2bd3cacaee75cf`
13. A-control isolation: `PASS_SEALED`; artifact prose input/egress `NO`; artifact SHA `f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f`
14. Historical-B isolation: treatment/input/egress all `NO`
15. Blind-evidence isolation: input/egress both `NO`
16. Approval ID/domain: `skill-v2-pair1-residual-v3-b-only-approval-20260826t123511z-4c189e07` / `skill-v2-pair1-demand-aware-b-only-signed-approval-v1`
17. Approval identity/binding SHA: `7474413750f385018f414a563b57552e414b83917243a8f2130c7648c8ae15bd` / `f1c6f785eca0e955ac63fb4cec4f15782d55b4e42813679bbf8ede79c46806b4`
18. Signed approval SHA/file SHA: `a66d136ca756f3fbd6759411e90c8d88a0c87bac1c5f88ce5ca107f5c86c3a9e` / `109a0a7cef03926cec5521c182498568015205104d62a291a6e01f61180d1806`
19. Approval created/expires: `2026-08-26T12:35:11Z` / `2026-08-28T12:35:11Z`
20. Phase B result: `PASS`; receipt SHA `fc1a4ebb7547a4ec912fb8f9499d3a60d06c3fb025af1219c970cd6557f42103`
21. Approval-time stop state: `CONTINUE_ALLOWED_FOR_LATER_EXECUTION_GATE`
22. Nonce ID/state: `skill-v2-pair1-residual-v3-b-only-nonce-20260826t123511z-5ea50d97` / `FRESH_UNRESERVED_UNCONSUMED`
23. Nonce reserved/consumed: `NO` / `NO`
24. Current-chat external permission state: `NOT_GRANTED_BY_THIS_TASK`
25. Future permission-before-nonce gate: `PASS`; reconfirmation required `YES`
26. Future egress scope: only new V3 B packet required data `YES`; A/prior-B/blind evidence egress `NO`
27. Negative matrix: `68/68 PASS`
28. Offline approved-boundary dry-run: `PASS`; external permission blocks before credentials and nonce reservation
29. Focused/adjacent tests: `pre-approval focused 45 passed; post-approval approval-independent focused 42 passed, 3 deselected; adjacent 10 passed, 76 deselected; approval-aware core verification PASS; negative approval matrix 68/68 PASS`
30. Strict L3: `PASS`; warnings `0`; blockers `0`
31. Owning-source regression count: `0`
32. Production/source diff: `0`; `src/**=0`; `baml_src/**=0`; Skill profile/context and candidate semantics unchanged
33. Privacy: `PASS`; match count `0`
34. Manifest definition/file SHA + coverage: `b0eff729cf914325a960915d3228c12237d95adf52221ef765427a39b5b2e776` / `ff9775c2310877454a41bf17707308fb88e47f0b94578f5dbfea860e785cc890` / `25/25 exact`
35. External counters: credential/client/provider/HTTP/network/model/paid/real-execution all `0`
36. Pair 2–5 state: execution allowed `NO`
37. Cutover states: Skill V2 `NO`; Planning V2 `NO`
38. Full Short state: `NOT_EXECUTED`
39. Exact next gate: `SKILL_V2_PAIR_1_RESIDUAL_V3_B_ONLY_REVALIDATION_SINGLE_DISPATCH_EXECUTE_ONCE`

`SKILL_V2_PAIR_1_RESIDUAL_V3_B_ONLY_REVALIDATION_FRESH_USER_APPROVED`
`SKILL_V2_PAIR_1_RESIDUAL_V3_B_ONLY_REVALIDATION_SINGLE_DISPATCH_EXECUTE_ONCE_READY=YES`

`SIGNED_APPROVAL_PRESENT=YES`
`PHASE_B_APPROVAL_TIME_SIGNED_PREFLIGHT=PASS`
`NONCE_RESERVED=NO`
`NONCE_CONSUMED=NO`
`FUTURE_EXECUTION_PERMISSION_MUST_BE_RECONFIRMED=YES`
`PERMISSION_CHECK_BEFORE_NONCE_RESERVATION=YES`
`REAL_EXECUTION_ATTEMPTS=0`
`CREDENTIAL_LOOKUP_COUNT=0`
`REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`
`HTTP_POST_ATTEMPTS=0`
`NETWORK_CALLS=0`
`MODEL_CALLS=0`
`PAID_CALLS=0`
`PAIR2_TO_5_EXECUTION_ALLOWED=NO`
`SKILL_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
`PLANNING_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
`FULL_SHORT_CANARY=NOT_EXECUTED`
`NO_AUTOMATIC_REAL_EXECUTION=YES`
