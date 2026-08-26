# Pair 1 residual V3 blind mapping reveal and engineering evaluation

`SKILL_V2_PAIR_1_RESIDUAL_V3_REVALIDATION_BLIND_MAPPING_REVEALED`

`SKILL_V2_PAIR_1_RESIDUAL_V3_REVALIDATION_ENGINEERING_EVALUATED`

`SKILL_V2_PAIR_1_RESIDUAL_V3_REVALIDATION_FINAL_DISPOSITION_EMITTED`

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `181abf11edb0d2964da04da3d9d6d587a83ed09f`
3. Reveal/evaluation seal HEAD: recorded by the enclosing evidence-only commit and final operator report; omitted here to avoid Git commit self-reference.
4. Worktree: required clean after seal.
5. Pair ID / creative-demand class: `restored-character-heavy-v2-residual-v3` / `character-heavy`.
6. A artifact SHA: `f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f`
7. V3 B artifact SHA: `b5833ba6faf2fdb69b74a9f073c25ece537cc13e01694648e97f4dddda5d0bce`
8. Successor V3 A/B lock: `817d88552c273fc2a9521423725af7460fd09b83b9d3eb558d2bd3cacaee75cf` / exact / unintended diff 0.
9. Criticality-policy SHAs: `{"criticality-policy-v1.json": "46a90e5e60cc8977eff96d822122ddecd80ef1fe455973cc6bc745ac5625403b", "demand-criticality-map-v1.json": "f68666c0587c8150d17bcebb3738dd4e7770643d5513e8d6015b696242d2585f", "narrative-non-inferiority-rule-v1.json": "cbd8fee2d2be718b2abd40b31fee523efb12c7a4a10a5592e4e26163623c71ec", "pair-disposition-priority-v1.json": "668366d89685cd1c2dc0f17d6f2e601fad529e162a91ec2869fe179671806eba", "pair1-criticality-resolution-v1.json": "1771121f38882dbc3693e717c13cb17b366d02e63b14e0dfb02c2ffeacff0b0e", "policy-manifest-v1.json": "096198d4ac5466ac3b266e8a194fe7e10f3bed88f951b1cdf27dbcaf69e29e32", "policy-provenance-v1.json": "e7f90f0302e363c5cf2b4858b8416459c57baa13d878791ed10d687581c9a9e2"}`
10. Blind judgments SHA: `b5f62ba59e2667041b62a4db1fcca90f991b94bb1d48334e57995fe186c9114d`
11. Blind summary SHA: `623824f61a4feefa1839ac07832b9cc1e900bf81217d9f1c149c072501a88ed9`
12. Blind freeze receipt SHA: `653ca614f52dc4ed7c692a597bb8879de67da96877cd8133d1b922ae8b607951`
13. Private mapping SHA: `d85704bbeb166d19a547d9d7504888d785c1bc006c827f10aa91f8708bf9e996`
14. X identity: `B_ARM / RESTORED_SKILL_V2_CHARACTER_CORE_V3`.
15. Y identity: `A_ARM / CURRENT_RUNTIME_SKILL`.
16. No post-reveal re-scoring: frozen evidence fields were copied mechanically; pre/post blind hashes are identical.
17. All 16 revealed A/B judgments:

| Dimension | Criticality | Revealed judgment |
|---|---|---|
| event_causal_fidelity | CRITICAL | `A_BETTER` |
| character_motivation | CRITICAL | `A_BETTER` |
| character_voice | CRITICAL | `A_BETTER` |
| relationship_logic | CRITICAL | `A_BETTER` |
| world_specificity | NONCRITICAL | `A_BETTER` |
| sensory_realization | NONCRITICAL | `A_BETTER` |
| conflict_pacing | NONCRITICAL | `A_BETTER` |
| setup_payoff_dependency | NONCRITICAL | `A_BETTER` |
| pov | NONCRITICAL | `A_BETTER` |
| tense | NONCRITICAL | `EQUIVALENT` |
| tone_genre | NONCRITICAL | `EQUIVALENT` |
| subtext_dramatization | CRITICAL | `A_BETTER` |
| draft_intent_handoff | CRITICAL | `A_BETTER` |
| template_flattening_risk | CRITICAL | `A_BETTER` |
| authority_correctness | CRITICAL | `A_BETTER` |
| untargeted_creative_mutation | CRITICAL | `A_BETTER` |

18. B critical regression count: `9`.
19. B noncritical regression count: `5`.
20. B critical better count: `0`.
21. B noncritical better count: `0`.
22. Critical equivalent count: `0`.
23. Noncritical equivalent count: `2`.
24. Critical true-inconclusive count: `0`.
25. Noncritical true-inconclusive count: `0`.
26. Revealed counts reconcile with all 16 rows: `YES`.
27. Narrative non-inferiority: `NO`.
28. A engineering: one logical/Provider/HTTP/network request; retry/fallback/resume/second dispatch 0; parse, normalization, Event Realization validation, schema, freeze, audit, isolation, persistence PASS; StoryState/Canon/READY mutation 0/0/0; production authority false; sealed context 8927 chars. Route-switch, paid count, finish reason, effective cap, tokens, elapsed, and actual cost remain unknown where not separately persisted.
29. V3 B engineering: one logical/Provider/HTTP/network request; retry/fallback/route-switch/resume/second dispatch 0; terminal local tail PASS; StoryState/Canon/READY mutation 0/0/0; production authority false; context 2998 chars. Paid count, finish reason, effective cap, tokens, elapsed, and actual cost remain unknown where not separately persisted.
30. Engineering non-inferiority: `YES`; hard regression count 0.
31. Pair disposition: `PAIR_NO_GO_QUALITY_REGRESSION`.
32. Pair-level non-inferiority: `NO`.
33. Generalized production non-inferiority: `NOT_YET_PROVEN`.
34. B-version quality progression: OLD_RESTORED_B: critical regression 6, noncritical regression 4, critical better 1, noncritical better 1, equivalent 4, engineering YES, disposition PAIR_NO_GO_QUALITY_REGRESSION; DEMAND_AWARE_V2_B: critical regression 2, noncritical regression 2, critical better 3, noncritical better 1, equivalent 8, engineering YES, disposition PAIR_NO_GO_QUALITY_REGRESSION; RESIDUAL_V3_B: critical regression 9, noncritical regression 5, critical better 0, noncritical better 0, equivalent 2, engineering YES, disposition PAIR_NO_GO_QUALITY_REGRESSION.
35. Campaign consequence: Pair 1 residual V3 revalidation pass `NO`; campaign continue `NO`.
36. Pair 2–5: execution allowed `NO`.
37. Skill V2 production cutover: `NOT_AUTHORIZED`.
38. Planning V2 production cutover: `NOT_AUTHORIZED`.
39. Manifest definition SHA: `00de1fe94057871d9915e70b2e36bfc86cd264f3048ca0e3e0205d10788b8693`
40. Manifest file SHA: reported after generation by the final operator report; self-reference excluded.
41. Manifest coverage: all regular files in this root except `sha256-manifest-v1.json` itself.
42. Privacy: `PASS`; match count 0.
43. External counters in this task: credential lookup 0, Provider client 0, Provider request 0, HTTP POST 0, network 0, model 0, paid 0.
44. Full Short: `NOT_EXECUTED`.
45. Exact next gate: `SKILL_V2_PAIR_1_RESIDUAL_V3_REVALIDATION_QUALITY_REGRESSION_ROOT_CAUSE`.
