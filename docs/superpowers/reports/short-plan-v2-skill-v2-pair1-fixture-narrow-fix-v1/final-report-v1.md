# Pair 1 fixture narrow fix — final report

The historical Pair 1 authority used `AB-CHARACTER-0001`, which the Planning event compiler rejects. A versioned fixture-only successor now deterministically derives `EV-3D3AE01E` and rewrites the four active authority references. Historical evidence remains byte-exact.

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `ffbeef39c90d45a0f43c295ba0ed3dd6b4fa4874`
3. Implementation commits: `e95bdde682e1b9591b2470afffa4e7cdd2b7e50e`, `3edf338c859b683445d23c86397d743abae02140`, plus the final risk-closure source/test successor reported by the containing seal handoff.
4. Evidence/materialization seal HEAD: the commit containing this self-excluded manifest; exact hash is reported after commit creation.
5. Final HEAD: evidence seal HEAD; reported after commit creation.
6. Worktree: required `clean` after the evidence seal.
7. Root-cause binding: `AUTHORITY_OR_FIXTURE_INCONSISTENCY`, confidence `HIGH`, rule `SLICE1_EVENT_REALIZATION_INVALID`.
8. Canonical Pair 1 fixture source: `tools/diagnostics/skill_v2_bounded_repeated_ab.py`; exact SHA is in `fixture-source-binding-v1.json`.
9. Old formal event ID: `AB-CHARACTER-0001`.
10. New formal event ID: `EV-3D3AE01E`.
11. Event-ID policy: `canonical-json-sha256(semantic-fixture-identity)[:8].upper()`; no time or randomness.
12. Dependent rewrites: `4` at authority formal ID, formal list, segment list, and story slice.
13. Historical sealed mutation count: `0`.
14. Pair 2–5 audit: all four share the invalid historical ID class; read-only, unmodified, and blocked from progression.
15. Pair 1 fixture self-consistency: `PASS`.
16. Validator reproduction: old `REJECTED_WITH_SLICE1_EVENT_REALIZATION_INVALID`; corrected same candidate `PASS`.
17. Old Pair 1 A sample reuse: `NO`.
18. Current Skill parity: unchanged.
19. Restored Skill V2 parity: unchanged.
20. Validator semantics parity: unchanged.
21. Model/route/output-cap parity: unchanged; bound through the old exact lock and new packet.
22. Corrected authority-input SHA: `91e5fe89ae741233b983f344bb0aa517974a4341dab56c8341669a5233c2e3d4`.
23. Corrected story-slice SHA: `7134e84052d6e15bdd0f3bbb75de41a45c9e8c083d09e896004f8228b71c47c7`.
24. Corrected A/B lock SHA: `31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80`.
25. Corrected A packet SHA/root: `271a24c16c83c83e9555427f66af214d4b53e3a178661efdcaae846425919b53` / `docs/superpowers/reports/short-plan-v2-skill-v2-pair1-fixture-narrow-fix-v1/corrected-pair1/a-arm`.
26. Corrected B packet SHA/root: `46953023632e8dcbebba452b9a60c550689778985bf3ed2a210f2674b7e3f0f7` / `docs/superpowers/reports/short-plan-v2-skill-v2-pair1-fixture-narrow-fix-v1/corrected-pair1/b-arm`.
27. Corrected A/B states: `DISABLED`, `unused`, `unreserved`.
28. Old approval/nonce nonreuse: four identity mismatches; old nonce remains consumed and non-reusable.
29. Historical-root result: `CLOSED_WORLD`; failed execution and corrected roots accepted; arbitrary root rejected.
30. R0F: `NOT_REQUIRED` because `src/**` and protected production source are unchanged.
31. Corrected A unsigned approval dry-run: `READY`; approval and nonce remain absent.
32. Tests: focused `15 passed in 1.39s`; related `54 passed in 3.71s`; Strict L3 `PASS; warnings=0; blockers=0`.
33. Full suite: `3460 passed, 41 skipped, 6 xfailed, 29 failed, 72 errors in 1798.91s; non-green paths are pre-existing sealed-gate/oracle/live-parity families and not task-local`; existing non-green historical gates were not modified or retried.
34. Manifest definition SHA: recorded in `sha256-manifest-v1.json`.
35. Manifest file SHA: computed and reported after final materialization.
36. Manifest coverage: every materialized file except the manifest itself.
37. Privacy: exact, match count `0`, no raw failed Provider output, reasoning, credentials, or machine paths.
38. Historical real-call counters unchanged: Provider/HTTP/network/model/paid `1/1/1/1/1`; retry/fallback/second-dispatch `0/0/0`.
39. Pair 1 B authorization: `NO`; blocked until corrected A PASS.
40. Campaign successor state: `READY_FOR_PAIR1_CORRECTED_A_FRESH_APPROVAL`; real execution not resumed.
41. Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_ARM_FRESH_USER_APPROVAL`.

`src/** DIFF=0`
`baml_src/** DIFF=0`
`CURRENT_SKILL_CHANGED=NO`
`RESTORED_SKILL_V2_CHANGED=NO`
`VALIDATOR_SEMANTICS_CHANGED=NO`
`EXECUTION_AUTHORIZED=NO`
`SIGNED_APPROVAL=ABSENT`
`SINGLE_USE_NONCE=ABSENT`
`FULL_SHORT_CANARY=NOT_EXECUTED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_FIXTURE_NARROW_FIX_COMPLETED`
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_AB_PACKETS_MATERIALIZED`
`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_A_APPROVAL_READY=YES`
