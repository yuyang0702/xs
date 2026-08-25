# Corrected Pair 1 Skill V2 Quality Regression — Root-Cause Report

Gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_CORRECTED_QUALITY_REGRESSION_ROOT_CAUSE_IDENTIFIED`

## Baseline and frozen result

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `ea3dedab7ff770894985f06a6df5716105ffbe23`
- Pair: `restored-character-heavy-v2`
- A / B: `CURRENT_RUNTIME_SKILL` / `RESTORED_SKILL_V2`
- A artifact: `f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f`
- B artifact: `1dd0e31dcf01bc369cf8cee1865ae1fffdb4ad890bb1d726482048755037dc69`
- A/B lock: `31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80`
- Frozen mapping: `X=A`, `Y=B`; no rescoring was performed.
- Frozen outcome: B has `6` critical and `4` noncritical regressions, while improving `relationship_logic` and `setup_payoff_dependency`. Narrative non-inferiority is `NO`; engineering non-inferiority is `YES`.

## Root cause

Primary class: `MULTI_FACTOR_WITH_PRIMARY_CHARACTER_HEAVY_UNDERSPECIFICATION`

Restoration diagnosis: `INSUFFICIENT_DEPTH`

Causality confidence: `MEDIUM`

The restored profile is not missing its eight intended cores. All 20 rules are present, ordered, and untruncated in a 2,742-character context. The failure is the difference between capability presence and execution depth: for a character-heavy scene, B does not require the complete chain from formative pressure to present want/concealed need, opposed tactic, costly choice, observable reaction, and next-beat consequence. Its voice, handoff, and anti-template rules likewise enumerate useful ingredients without consistently requiring behavior before interpretive summary.

This explains the asymmetry in the frozen result. B wins relationship logic because its rule directly makes relationship pressure change available actions. B wins setup/payoff because that rule explicitly requires plant, dependency, and later action payoff. Those successful semantics must remain intact. The critical regressions cluster where the restored wording is less continuously executable: motivation, voice, subtext, character-causal fidelity, Draft handoff, and semantic anti-template behavior.

General context overcompression is secondary, not the new primary cause. Tail priority, truncation, missing restoration items, resolver false-negative, schema/authority drift, and stochastic dominance are disproved as primary explanations. One-pair stochastic variance remains material, so this is mechanism-supported Pair 1 causality rather than generalized production proof.

## Minimal restoration V2 design

No production change is implemented here. The narrow design rewrites four existing character-heavy mandatory rules in place: `MOTIVE_ACTION`, `VOICE_RELATION`, `DRAFT_SCENE`, and `ANTI_TAXONOMY`. The exact estimated delta is `+183` characters, producing `2,925/3,000` characters with `75` characters of headroom. `SETUP_PAYOFF`, `CHARACTER_RELATIONSHIP_NUANCE`, and every non-target rule remain unchanged, preserving B's two observed gains.

The resolver strategy is deterministic and demand-aware. Only sealed `character-heavy` demand selects the V2 rewrite; unknown demand fails closed. It does not use an LLM to classify demand and does not pre-judge Pair 2-5.

## Scope and next gate

- Production diff: `0`
- Skill/Prompt/fixture/validator/launcher/A/B artifact changes: `0`
- Parent manifests: `6/6 EXACT`; nested blind manifest: `4/4 EXACT`
- Focused tests: `68 passed`
- Evidence contract: `PASS` (`24` required artifacts, `20` B units, `10` regression rows, `8` restoration cores)
- Related matrix: `197 passed, 14 failed, 26 errors`; all non-green cases are consumed/terminal historical approval and execution-root expectations with task-diff involvement `NONE`. Historical sealed state was not rewritten.
- Strict L3: `PASS`, warnings `0`, blockers `0`
- Single-agent clean-room final-diff review: `PASS`, independence claimed `false`, hard issues `0`
- Pair 2-5: `NOT_EXECUTED`
- Skill V2 cutover: `NO`
- Planning V2 cutover: `NO`
- Full Short Canary: `NOT_EXECUTED`
- External calls: all `0`

Exact next gate, not started: `SKILL_V2_PROFILE_DEMAND_AWARE_CREATIVE_CORE_NARROW_FIX`.

`MINIMAL_CREATIVE_RESTORATION_V2_SET_DEFINED=YES`

`PRESERVE_B_GAINS=YES`

`PAIR_2_5_EXECUTED=NO`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`
