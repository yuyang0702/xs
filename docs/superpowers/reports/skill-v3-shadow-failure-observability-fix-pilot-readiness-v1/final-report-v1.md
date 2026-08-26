# Skill V3 shadow failure observability fix and pilot readiness recheck

`SKILL_V3_SELECTIVE_COMPILER_SHADOW_FAILURE_OBSERVABILITY_FIXED`

`SKILL_V3_SELECTIVE_COMPILER_REAL_PILOT_READY=YES`

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `248f786ffadb60224244343778fe6ca2ff3ab37e`
3. Implementation commit: `a0a06ba`
4. Validation/readiness commit: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_EVIDENCE`
5. Final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_EVIDENCE`
6. Final worktree: `CLEAN_AFTER_SEAL`
7. Silent sites before: `1`
8. Source symbols: `ReliabilityTraceEventType`, `ReliabilityTraceEnvelopeV1.REQUIRED_PAYLOAD`, `WorkflowService.__init__`, `WorkflowService._record_skill_v3_shadow_failure`, `WorkflowService._stage`
9. Reused observer contract: `ReliabilityTraceEnvelopeV1`, `emit_observation`, `failure_evidence_sha256`
10. Failure schema: `SkillV3ShadowFailureObservationV1@1`
11. Error hash: raw exception contributes only to SHA256 and is not persisted
12. Counter: instance-local, exactly +1 per failed invocation; local record deque max `64`
13. Runtime evidence: `TRACE_EVENT_WITH_BOUNDED_IN_MEMORY_FALLBACK`
14. Sink failure: fail-open, one drop increment, no recursive emit
15. Negative matrix: `7/7 PASS`
16. Direct silent swallow after: `0`
17. Production prompt SHA before/after: `414c5e37e182d65e1a4647b332127182fd37067156687bef12e5188e266c8f70` / `414c5e37e182d65e1a4647b332127182fd37067156687bef12e5188e266c8f70`
18. Production model-input SHA before/after: `5fe3b02b9a3fa4d7c333210ec3c5ba1f779ce1b705634f48fecae8074ba1b1e4` / `5fe3b02b9a3fa4d7c333210ec3c5ba1f779ce1b705634f48fecae8074ba1b1e4`
19. Production identity: `PASS`
20. Five-scenario output parity: `5/5 PASS`
21. Shadow failure blocks production: `NO`
22. Shadow failure observable: `YES`
23. Evidence bounded: `YES`
24. Privacy: `PASS`, matches `0`
25. Readiness delta: only `SHADOW_FAIL_OPEN FAIL -> PASS`
26. New failed readiness dimensions: `0`
27. Multi-sample policy unchanged: `YES`, source `b99184e3e262f64e386f73efb76d2e2175cd1297f7a339e2b199a66e1c46fdce`
28. Real-pilot readiness: `YES`
29. Pilot ID: `skill-v3-character-heavy-multi-sample-v1-4d47410b0144360d`
30. A arm: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE`
31. B arm: `VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY`
32. Samples per A/B: `3/3`
33. Maximum real requests: `6`
34. Experiment-lock SHA: `8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b`
35. Stop conditions: exact sealed list in `real-pilot-plan-v1.json`
36. Pilot plan materialized: `YES`
37. Pilot plan disabled: `YES`
38. Packet template: `ee4e5add7b09bd5b74cee2e9f31bb57a884d0f709e5abcfa075c480acda6ad4c`
39. Execution authorized: `false`
40. Signed approval: `ABSENT`
41. Nonce: `NOT_CREATED/NOT_RESERVED/NOT_CONSUMED`
42. Focused tests: `25 passed`
43. Adjacent tests: `115 passed`
44. Strict L3: `PASS`, warnings `0`, blockers `0`
45. Owning-source regressions: `0`
46. Production/source diff: observability only; no Prompt/route/model/validator/authority/retry/fallback/Skill selection change
47. Manifest definition SHA: computed in `sha256-manifest-v1.json`
48. Manifest file SHA: computed after this report
49. Manifest coverage: all evidence files except manifest itself
50. External counters: credential/client/request/HTTP/network/model/paid = `0/0/0/0/0/0/0`
51. Pair 2–5: `NOT_EXECUTED`, authorization `NO`
52. Cutovers: Skill V3 `NO`; Skill V2 `NO`; Planning V2 `NO`
53. Full Short: `NOT_EXECUTED`
54. Exact next gate: `SKILL_V3_SELECTIVE_COMPILER_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS`

## Full-suite classification

The complete offline suite produced 124 non-green nodes: 96 legacy Canary/materialization/approval or parent-evidence gates, 17 historical Planning Skill oracle/materialized-evidence gates, 2 R0E/R0F live-parity/fixed-hash gates, and 9 Skill V2 sealed-source/evidence gates. None belongs to the Skill V3 observability, selective compiler, generated trace contract, reliability trace, or failure-boundary owning-source matrix. Exact family counts are sealed in `full-suite-classification-v1.json`; historical evidence and live data were not rewritten.

`EXECUTION_AUTHORIZED=false`

`SIGNED_APPROVAL_CREATED=NO`

`REAL_EXECUTION_NONCE_CREATED=NO`

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`
