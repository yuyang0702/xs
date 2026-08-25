# Pair 1 Blind Mapping Reveal and Engineering Evaluation — Final Report

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_BLIND_MAPPING_REVEALED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_ENGINEERING_EVALUATED`

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_FINAL_DISPOSITION_EMITTED`

## Baseline and sealed inputs

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Baseline HEAD: `2a356544b1cbc5dc3b1f374334aa80c60a9fadef`
3. Reveal/evaluation seal HEAD: the single evidence-only Git commit containing this report
4. Worktree target: `clean`
5. Pair ID: `restored-character-heavy-v2`
6. Creative-demand class: `character-heavy`
7. A artifact SHA: `f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f`
8. B artifact SHA: `1dd0e31dcf01bc369cf8cee1865ae1fffdb4ad890bb1d726482048755037dc69`
9. A/B lock: `exact`; primary changed variable `SKILL_CONTEXT`
10. Criticality policy SHA: `46a90e5e60cc8977eff96d822122ddecd80ef1fe455973cc6bc745ac5625403b`
11. Blind judgments SHA: `9685e0fea67b21ff84c937146fea123ff8682728125e9adbb1e4d6c8ff72d917`
12. Blind summary SHA: `bd22b261ebe84638fd3864c8cd6195c43a03bbabe458a030ab4d4fc930acef22`
13. Blind freeze receipt SHA: `7154adab7bde0970aee5a16d764c4269496039b9c8e23542c55de547198d884f`
14. Private mapping SHA: `3b92163362e00b6f6f12c2e0cf5c51fb3add89de188c5cf7ee976ae4b57f52f9`
15. X identity: `A / CURRENT_RUNTIME_SKILL`
16. Y identity: `B / RESTORED_SKILL_V2`
17. Post-reveal re-scoring: `NO`; blind judgment files mutated: `NO`

## Revealed per-dimension judgments

| Criticality | Dimension | Revealed judgment |
|---|---|---|
| Critical | event_causal_fidelity | A_BETTER |
| Critical | character_motivation | A_BETTER |
| Critical | character_voice | A_BETTER |
| Critical | relationship_logic | B_BETTER |
| Critical | subtext_dramatization | A_BETTER |
| Critical | draft_intent_handoff | A_BETTER |
| Critical | template_flattening_risk | A_BETTER |
| Critical | authority_correctness | EQUIVALENT |
| Critical | untargeted_creative_mutation | EQUIVALENT |
| Noncritical | world_specificity | A_BETTER |
| Noncritical | sensory_realization | A_BETTER |
| Noncritical | conflict_pacing | EQUIVALENT |
| Noncritical | setup_payoff_dependency | B_BETTER |
| Noncritical | pov | A_BETTER |
| Noncritical | tense | EQUIVALENT |
| Noncritical | tone_genre | A_BETTER |

18. The table is a pure mechanical X/Y-to-A/B transform of the frozen judgment file; no rationale, confidence, or literary dimension was changed.
19. B critical regression count: `6`
20. B noncritical regression count: `4`
21. B critical better count: `1`
22. B noncritical better count: `1`
23. Equivalent count: `4`
24. Critical/noncritical inconclusive counts: `0 / 0`
25. Narrative non-inferiority: `NO`

## Engineering comparison

26. A engineering: one model/Provider/HTTP/network request; zero retry/fallback/resume/second dispatch; parse, normalization, validation, schema, freeze, audit, isolation, and persistence all PASS; StoryState/Canon/READY mutation `0/0/0`; production authority `false`; context `8927` chars.
27. B engineering: one model/Provider/HTTP/network request; zero retry/fallback/route-switch/resume/second dispatch; parse, normalization, validation, schema, freeze, audit, isolation, and persistence all PASS; StoryState/Canon/READY mutation `0/0/0`; production authority `false`; context `2742` chars.
28. Finish reason, effective output cap, input/output tokens, elapsed time, and actual cost remain `UNKNOWN_NOT_PERSISTED`; no external pricing estimate was introduced. Requested output cap was `4624` for both arms.
29. Engineering non-inferiority: `YES`; B hard regression count `0`.

## Pair and campaign decision

30. Pair disposition: `PAIR_NO_GO_QUALITY_REGRESSION`
31. Pair-level non-inferiority: `NO`
32. Generalized production non-inferiority: `NOT_YET_PROVEN`
33. Campaign consequence: `CAMPAIGN_CONTINUE=NO`
34. Pair 2–5: `BLOCKED`; execution allowed `NO`
35. Skill V2 production cutover: `NOT_AUTHORIZED`
36. Planning V2 production cutover: `NOT_AUTHORIZED`
37. Manifest definition SHA: `05430ea9169aa4ada9f05eb9b9ee9faf443d182d936f129eba2c7f1ad4b1da1a`
38. Manifest file SHA: reported after the self-excluded manifest is materialized
39. Manifest coverage: all regular files in this evidence root except the manifest itself
40. Privacy: `PASS`; match count `0`
41. External counters in this task: credential lookup `0`, real Provider client `0`, Provider request `0`, HTTP POST `0`, network `0`, model `0`, paid `0`; Full Short `NOT_EXECUTED`

## Exact next gate

`SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_QUALITY_REGRESSION_ROOT_CAUSE`
