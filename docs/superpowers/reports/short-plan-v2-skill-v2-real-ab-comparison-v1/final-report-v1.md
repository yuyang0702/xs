# Skill V2 REAL A/B comparison — final report v1

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `7e1a2b66bddc8ebc68fa09e7c60690f63664f85e`
- AB pair: `skill-v2-real-ab-20260824-v4-001`
- A-arm validity: `SEALED_PASS`; artifact SHA `b3588452679d0d5c39c4b86db63c98dc440868cdb2cd951d1262f426b234cb67`
- B-arm validity: `SEALED_PASS`; artifact SHA `559724e4944f51715c634a3653dffdaf19bd946f6127f64cb64f941fb7f6f450`
- A/B lock: `exact`; comparison lock SHA `8185d3e964b9e6a4834c01ed6c83d4c7ca219ccac800cdb3384086331840426c`
- Blind procedure: deterministic X/Y mapping; engineering hidden; judgment file frozen at `a4460327962be75ec926cfcbd82ee66760aed08447113207bfb6e216c92c7c82` before reveal; mapping `X=B`, `Y=A`
- A/B comparison view SHAs: `15eb95214b37908123cf322e5d8948dae0f93feddc55aacc1a036d66f48f11f8` / `f6bb598b0cf03014ed34789b3aa8b7aeb515346fc2c85d0634c2b82d33f61ddc`

| Narrative dimension | Judgment | Critical |
|---|---|---|
| EVENT_CAUSAL_FIDELITY | EQUIVALENT | YES |
| CHARACTER_MOTIVATION | A_BETTER | YES |
| CHARACTER_VOICE | A_BETTER | NO |
| RELATIONSHIP_LOGIC | A_BETTER | NO |
| WORLD_SPECIFICITY | A_BETTER | NO |
| SENSORY_REALIZATION | A_BETTER | NO |
| CONFLICT_AND_PACING | A_BETTER | NO |
| SETUP_PAYOFF_DEPENDENCY | A_BETTER | YES |
| POV_CONSISTENCY | EQUIVALENT | YES |
| TENSE_CONSISTENCY | EQUIVALENT | YES |
| TONE_GENRE_FIDELITY | INSUFFICIENT_EVIDENCE | YES |
| SUBTEXT_DRAMATIZATION | A_BETTER | NO |
| DRAFT_INTENT_HANDOFF | A_BETTER | YES |
| TEMPLATE_FLATTENING_RISK | A_BETTER | YES |
| AUTHORITY_CORRECTNESS | EQUIVALENT | YES |
| UNTARGETED_CREATIVE_MUTATION | INSUFFICIENT_EVIDENCE | NO |

- Critical B regressions: `4` — character motivation, setup/payoff/dependency, Draft-intent handoff, template-flattening risk
- Noncritical B regressions: `6`
- B better/equivalent/insufficient dimensions: `0/4/2`
- Narrative non-inferiority: `NO`
- Engineering non-inferiority: `YES`; both arms first-pass `PASS`, one request, no repair, frozen/persisted artifact, no authority mutation
- A engineering: output `529`, visible provider chars `1957`, cap `4624`, finish `end_turn`, estimated input `2625`
- B engineering: output `720`, visible provider chars `UNKNOWN`, isolated artifact text chars `2110`, cap `4624`, finish `end_turn`, estimated input `790`, elapsed `17.36s`
- Secondary efficiency: Skill context `8927 -> 1587` chars (`82.22%` reduction); estimated model input `2625 -> 790` tokens (`69.90%` reduction)
- Token reduction alone sufficient: `NO`
- Combined disposition: `NO_GO_QUALITY_REGRESSION`
- Pair-level non-inferiority: `NO`
- Generalized production non-inferiority: `NOT_YET_PROVEN`
- Cutover candidate ready: `NO`; production cutover authorized: `NO`
- More real A/B pairs now: `NO`; defer until quality-regression root cause and narrow fix close, then require a bounded repeated set before any cutover
- Privacy: `PASS`; reports contain hashes, paths, dimension labels, and concise references only
- External counters: credential/client/provider/HTTP/network/model/paid = `0/0/0/0/0/0`
- Full Short Canary: `NOT_EXECUTED`
- Exact next gate: `SKILL_V2_PROFILE_QUALITY_REGRESSION_ROOT_CAUSE`

`SKILL_V2_REAL_AB_COMPARISON_EVALUATED`
`SKILL_V2_REAL_AB_PAIR_NON_INFERIOR=NO`
`SKILL_V2_RUNTIME_CUTOVER_CANDIDATE_READY=NO`
