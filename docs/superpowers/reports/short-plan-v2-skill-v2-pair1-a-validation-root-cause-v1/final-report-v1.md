# SKILL-V2 Pair 1 A terminal validation rejection root cause

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `1a38c976d34207dcbae4f2879b088945bcd7c35b`
3. Evidence seal/final HEAD: recorded after evidence-only commit
4. Worktree target: clean after seal
5. Pair/case/arm/Skill: `restored-character-heavy-v1` / `A_ARM` / `CURRENT_RUNTIME_SKILL`
6. Sealed execution evidence: 9/9 exact; definition SHA `11f51c1151e4d3499c537b1724dafd1d60ab7f76dc5cce2e271a3536ad2837fd`; file SHA `7d9041e927a75be6d65c50e62be473a7f93e195472ac869489670ee0c4583f33`
7. Actual rejected candidate availability: content `NO`; structural fields `NO`; candidate hash `ABSENT`
8. Exact underlying finding availability: absent from sealed evidence; recovered by exact source parity plus deterministic fixture replay
9. Validator call graph: Provider text -> generated-artifact conversion -> strict candidate schema -> local artifact build -> referential/authority validation -> Planning event compiler -> aggregate reject -> freeze not reached
10. Umbrella invariant: `slice1_generated_candidate_rejected` is an aggregate wrapper, not a direct semantic rule
11. Last successful pipeline stage: referential/authority validation
12. Parser/conversion: `PASS` by exclusive control flow; actual-content semantic drift remains `INCONCLUSIVE` but is causally irrelevant
13. Candidate schema: `PASS` by exclusive control flow
14. Referential result: `PASS` by deterministic builder equality
15. Event Realization semantic result: `FAIL`
16. Exact failed rule code: `SLICE1_EVENT_REALIZATION_INVALID`
17. Exact failed field path: `/narrative`
18. Failed-field ownership: reported path is model-owned, but the root-causing `formal_event_id` is fixture-owned and authority-copied
19. Expected contract: authority identity must be accepted by the downstream Planning event topology adapter; its recognized grammar is `EV-[0-9A-F]{8}`
20. Current Skill instruction coverage: sufficient for title/narrative shape and event realization; it correctly does not own authority IDs
21. Main Prompt/task contract: model owns only title and narrative and must not modify authority; no model instruction can repair this identity mismatch
22. Fixture consistency: `NO`; it supplies `AB-CHARACTER-0001`, which the downstream adapter cannot normalize
23. Validator known-good audit: 41 focused tests passed; existing 20-case corpus remains exact; deterministic Pair 1 minimal candidate reproduces one exact rejection
24. Validation order: validator is not fail-fast and computes a receipt; launcher persists zero child findings and raises only the umbrella string
25. Parser/conversion drift: `INCONCLUSIVE_FOR_ACTUAL_CONTENT`, disproved as the primary cause
26. Local derivation/stage order: matches Slice1 design; not causal
27. Campaign coverage: `PARTIAL`; the prior 20-case corpus uses canonical `EV-*` identities and did not cover an authority-accepted noncanonical ID
28. Primary root-cause class: `AUTHORITY_OR_FIXTURE_INCONSISTENCY`
29. Confidence: `HIGH`
30. Secondary causes: campaign fixture design defect; overbroad diagnostic attribution of compiler ValueError to narrative; missing persisted child receipt
31. Pair 1 A valid for A/B comparison: `NO`
32. Pair 1 B authorization: `NO`
33. Campaign state: `STOPPED_PENDING_ROOT_CAUSE`
34. Minimum next action: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_FIXTURE_NARROW_FIX`
35. Observability closure: designed only as future hardening; persist rule/path/ownership/constraint and content hashes before aggregate closure
36. Manifest definition SHA: recorded in `sha256-manifest-v1.json`
37. Manifest file SHA: reported after seal
38. Manifest coverage: all non-manifest files in this root
39. Privacy: exact, match count 0
40. Investigation external actions: credential/provider/network/model/paid all 0; frozen historical request counters remain 1/1/1/1/1
41. Exact next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_FIXTURE_NARROW_FIX`

`PRIMARY_ROOT_CAUSE_CLASS=AUTHORITY_OR_FIXTURE_INCONSISTENCY`

`ROOT_CAUSE_CONFIDENCE=HIGH`

`PAIR_1_A_SAMPLE_VALID_FOR_AB_COMPARISON=NO`

`PAIR_1_B_ARM_AUTHORIZED=NO`

`CAMPAIGN_CONTINUE=NO`

`REAL_PROVIDER_REQUESTS_REMAIN=1`

`HTTP_POST_ATTEMPTS_REMAIN=1`

`NETWORK_CALLS_REMAIN=1`

`MODEL_CALLS_REMAIN=1`

`PAID_CALLS_REMAIN=1`

`RETRY_ATTEMPTS_REMAIN=0`

`FALLBACK_ATTEMPTS_REMAIN=0`

`SECOND_DISPATCH_REMAIN=0`

`EXECUTION_AUTHORIZED=NO_FOR_NEW_REQUEST`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_TERMINAL_VALIDATION_REJECTION_ROOT_CAUSE_IDENTIFIED`
