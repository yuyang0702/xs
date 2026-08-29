# Skill V3 Hybrid Character-heavy Architecture Disposition — Final Report

## Baseline and disposition

- Branch/start HEAD: `r1-ptr3/planning-repair-finding-propagation-20260817` / `358c850b5a0fc4c063813576f868baae477f575b`
- Final pilot binding: `ENGINEERING_NON_INFERIOR=YES`, `NARRATIVE_NON_INFERIOR=NO`, `NO_GO_QUALITY`
- Stop-loss: `HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE`
- Supported critical regression: `setup_payoff_integrity`; `character_agency` and `causal_coherence` remain inconclusive.
- Noncritical result: all five recorded dimensions are better, but no scalar averaging was used to override the critical gate.

## Independent reviews

Agent A concludes that Hybrid improved scene-local enactment while Skill-section closure failed to preserve concrete story-instance custody, consequence, and payoff state. It recommends no further model-visible microtuning and retaining only the offline engineering mechanisms.

Agent B concludes that the safest production path is the current `SkillGate -> SkillPromptCompactor -> Planning V1` control. The first unrecovered Full Short divergence remains Planning Call 1 semantic conversion/recovery, not Skill resolution or PTR9. It recommends freezing current Runtime Skill bytes and moving directly to lossless typed Planning recovery and deterministic global closure.

## Architecture disposition

`MODEL_VISIBLE_SKILL_V3_DISPOSITION=RETAIN_CURRENT_BASELINE_RETIRE_SKILL_V3_MODEL_VISIBLE_AUGMENTATION`

`PRODUCTION_SKILL_PATH=CURRENT_BASELINE_SKILL_GATE_PLUS_SKILL_PROMPT_COMPACTOR`

Selective replacement and the current Hybrid model-visible supplement are retired for the current Short path. Typed closure, protected budgets, actionability, provenance, shadow/failure observability, approval/nonce controls, and blind-evaluation infrastructure remain default-disabled offline assets. No source route can accidentally enable Hybrid through normal app construction, so no production guard edit was necessary.

## Short source truth and blocker reduction

Already satisfied: current Skill identity/control, PTR9 reasoning-only guard, PTR12 hash-only observer, exact Draft finding propagation, StoryState/Canon/READY writer boundaries, runtime fingerprint, final artifact/checkpoint mechanics, and single-use execution controls.

Must close: (1) Planning typed semantic findings plus bounded repair/freeze and deterministic assembly/global closure; (2) Draft repair ownership so localized findings cannot rewrite unrelated accepted prose; and (3), only when a style/reference is explicitly selected, exact provenance through polish/Final Review and a deterministic fidelity check. Canonical V2 cutover, remaining Hybrid campaigns, generalized Skill research, long-fiction work, and cost optimization can wait until after the first trustworthy Full Short.

The blockers share a production-shaped full-flow acceptance matrix, so the next gate is one consolidated master rather than another Skill-prompt loop:

`EXACT_NEXT_GATE=SHORT_TRUSTWORTHY_FULL_FLOW_READINESS_AND_CUTOVER_MASTER`

That gate is offline-first. It may materialize a fresh disabled single-use Full Short packet only after exact readiness; a later real Full Short still requires a new explicit user authorization.

## Invariants and final state

`HYBRID_STOP_LOSS_ACTIVE=YES`

`SELECTIVE_REPLACEMENT_RETIRED=YES`

`HYBRID_MODEL_VISIBLE_SUPPLEMENT_RETIRED_FOR_CURRENT_SHORT_PATH=YES`

`NO_REMAINING_DEMAND_CLASS_VALIDATION_FOR_CURRENT_HYBRID=YES`

`PRODUCTION_BASELINE_PROMPT_BYTES_UNCHANGED=YES`

`PRODUCTION_MODEL_INPUT_IDENTITY_UNCHANGED=YES`

`FAILED_SKILL_V3_PATH_ACCIDENTAL_CUTOVER_COUNT=0`

`SKILL_V3_PRODUCTION_CUTOVER=NO`

`PLANNING_V2_PRODUCTION_CUTOVER=NO`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT=NOT_EXECUTED`
