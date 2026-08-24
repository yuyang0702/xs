
# SKILL-V2-PROFILE-QUALITY-REGRESSION-ROOT-CAUSE — Final Report

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`.
2. Baseline HEAD: `f96d47a12254bab83295024f163f2dcb5cb3f414`.
3. Evidence commit/final HEAD: assigned by Git after this self-excluding report/manifest set is sealed; exact value is reported in the final handoff.
4. Worktree: clean before investigation; required clean after the evidence-only seal.
5. A/B pair verification: `skill-v2-real-ab-20260824-v4-001`, exact lock, `SKILL_CONTEXT` is the only semantic variable; zero drift dimensions.
6. Exact A Skill context/source: compacted context `c7916de36e67f380f2e10f30f169bcdbe04440cc8bd01bbf2626d26a7cdf49b7`; source canonical SHAs are sealed in `docs/superpowers/reports/short-plan-v2-slice1-phase-b-current-skill-materialization-v5/phase-b-current-skill-v5-skill-profile-v1.json`.
7. Exact B Skill V2 context/source: rendered context `a77ca32533e7e480ab3b0ff53d55dde5bed4ff837b8b68f53b7aba59a8d6fd15`; runtime source `103b92403fdfb3ecba59a91bc28fdae146c8d87c975a12ca037e0b19350b9a93`.
8. Context size: A 8,927 chars; B 1,587 chars; reduction 82.22%. B output was longer (720 vs 529 tokens), so short output is not a sufficient cause.
9. A-only semantic instruction counts: `{"AUTHORITY/VALIDATION": 4, "CREATIVE_SEMANTIC": 15, "FILE/CLI/TOOL_INSTRUCTION": 9, "LITERARY_TECHNIQUE": 2, "OPERATIONAL_BOOKKEEPING": 10, "REDUNDANT": 2, "STORY_REASONING": 15, "UNKNOWN": 0}` across 57 absent/partial residual units.
10. A-only creative matrix: 32 creative/literary/story-reasoning residual units; critical regression mapping complete.
11. Capability re-audit: deterministic rule IDs are present, but semantic strength and scene-realization sufficiency are not preserved. The prior audit is a false positive only for that stronger claim.
12. Conditional resolver: exact missing actor/world metadata triggered fail-safe inclusion for both components; plot is always loaded.
13. Character profile load: `YES` (4 rules).
14. World profile load: `YES` (5 rules).
15. Plot profile load: `YES` (3 rules); story-init load is `NO` by event-profile design.
16. Narrative bridge: exact event profile has `narrative_bridge=None`; generic rules provide partial abstract coverage but no confirmed scene bridge. `NARRATIVE_BRIDGE_ABSTRACTION_LOSS=YES` as a secondary contributor.
17. Context truncation/priority: both contexts occupy the same system-tail boundary, user JSON is identical, A is complete after compaction, B truncation status is `NONE`, zero excluded rules. Priority/truncation is not causal.
18. Regression attribution: all ten sealed regressions are mapped in `regression-attribution-matrix-v1.json`; strongest direct link is template-taxonomy leakage, while other links are medium/low and preserve alternatives.
19. Critical regression confidence: motivation `MEDIUM`, setup/payoff `MEDIUM`, Draft handoff `MEDIUM`, template flattening `HIGH`.
20. Stochastic variance: one pair prevents high/generalized confidence; exact lock and clustered richness regressions support profile causality above chance-only. Result `MEDIUM`.
21. Primary root cause: `MULTI_FACTOR_WITH_PRIMARY_OVER_COMPRESSION_OF_CREATIVE_GUIDANCE`.
22. Secondary causes: creative instruction decomposition loss; offline semantic-strength audit false positive; narrative-bridge abstraction/absence; residual single-sample variance.
23. Profile causality confidence: `MEDIUM`; generalized production non-inferiority remains unproven.
24. Do-not-restore: filesystem/CLI/registry/schema/authority/validation/repair/evidence bookkeeping remain local/runtime-owned.
25. Minimal restoration: eight capability-level items add action-level motivation/voice/relationship, causal affordances, pressure beats, concrete dependency payoff, confirmed narrative bridge, Draft handoff, and anti-taxonomy guidance.
26. Resolver correction: `NO`; preserve fail-safe resolver and add the smallest creative core at profile level.
27. Estimated context increase: 1,355 chars; estimated total 2,942 chars, below the current 3,000-character context maximum before final render verification.
28. Creative presence gate: ten deterministic semantic-presence checks with removal, label-only, truncation, and operational-leak tamper cases; it does not claim to score prose quality.
29. Repeated A/B plan: five bounded pairs after offline fix/materialization/approval: character, world, conflict/pacing, setup/payoff, and mixed.
30. Manifest definition SHA: computed in `sha256-manifest-v1.json` from the frozen manifest definition.
31. Manifest file SHA: computed after report materialization and reported in the final handoff; the manifest self-excludes to avoid recursion.
32. Manifest coverage: every evidence file except the manifest itself.
33. Privacy: `PRIVACY_MATCH_COUNT=0`; no credentials, headers, secret URLs, raw payloads, reasoning text, or full duplicated A/B prose.
34. External counters: credential lookup 0; provider client 0; provider attempts 0; HTTP POST 0; network 0; model 0; paid 0.
35. Exact next gate: `SKILL_V2_PROFILE_CREATIVE_SEMANTIC_RESTORATION_NARROW_FIX`.

`PRIMARY_ROOT_CAUSE_CLASS=MULTI_FACTOR_WITH_PRIMARY_OVER_COMPRESSION_OF_CREATIVE_GUIDANCE`
`PROFILE_CAUSALITY_CONFIDENCE=MEDIUM`
`CRITICAL_REGRESSION_INSTRUCTION_MAPPING_COMPLETE=YES`
`DO_NOT_RESTORE_OPERATIONAL_CONTENT_DEFINED=YES`
`MINIMAL_CREATIVE_RESTORATION_SET_DEFINED=YES`
`EXECUTION_AUTHORIZED=NO`
`SIGNED_APPROVAL=ABSENT_FOR_NEW_EXECUTION`
`SINGLE_USE_NONCE=ABSENT`
`CREDENTIAL_LOOKUP_COUNT=0`
`REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`
`HTTP_POST_ATTEMPTS=0`
`NETWORK_CALLS=0`
`MODEL_CALLS=0`
`PAID_CALLS=0`
`SKILL_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
`PLANNING_V2_CUTOVER_AUTHORIZED=NO`
`FULL_SHORT_CANARY=NOT_EXECUTED`

## Final Gate

`SKILL_V2_PROFILE_QUALITY_REGRESSION_ROOT_CAUSE_IDENTIFIED`
