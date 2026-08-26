# SKILL-V3 — Verbatim/selective Skill compiler shadow implementation

## Outcome

`SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_IMPLEMENTED`

`SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_OFFLINE_VALIDATED`

## Baseline and implementation

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `c661ff4d5af8e557a18e7013d37219b3e76c8de5`
- Implementation commits:
  - `b51d815c326c0cc6b81f738f1fb8a3cf7d6d1f9d Implement stable selective Skill section compiler`
  - `cc02049491056886899cf242ab31013c692e9dca Add fail-open Skill compiler shadow integration`
  - `e21f3277b04b6410b96c492fe86c1842d47b4487 Validate selective Skill compiler shadow`
  - `f8c1b206ff698f0bb123b6329edcaf1c9d8a9f05 Record auditable Skill V3 validation evidence`
  - `2c989a032654f4ea023b30c1a043f471a9cd61f0 Make Strict replay receipt head-relative`
  - `c7c54ea39fd84772d97de0388582ec6e1f03d8ec Bind all Skill V3 implementation commits`
  - `5d0b47e1dbbe52f17cec9a2e839a4c122bdf5229 Report zero external Skill V3 actions`
- Evidence-seal/final HEAD: commit containing this report; exact hash is reported after the non-self-referential seal
- Source diff: `docs/maintenance.md, src/novel_flywheel/selective_skill_compiler.py, src/novel_flywheel/workflows.py, tests/test_selective_skill_compiler.py, tools/diagnostics/build_skill_section_index.py, tools/diagnostics/materialize_skill_v3_shadow_evidence.py, vendor/novel-skills/skill-section-index-v1.json`
- Existing stage-specific routing preserved: `YES`
- Production cutover: `NOT_AUTHORIZED`

## Compiler result

- Section identity: `PASS`; 11 Short Skills / 413 indexed sections
- Selector: deterministic local; allowed inputs are sealed resolver IDs/source hashes, stage/substage, contract identity, demand enum, authority hashes, policy/index versions, and capacity facts
- Dependency closure: `PASS`; missing `0`
- Ownership filter: `PASS`; sealed wrong-layer count `18`, selected after exact exception `0`
- Exact exception: `Climax` reference `sv3-7633ad6f5c90db5e` was a sealed substring-`cli` false positive and is bound as shared creative core
- Verbatim fidelity: `PASS`; mismatches `0`
- Creative semantic reauthoring: `0`; wrapper creative summaries: `0`
- Ordering: deterministic; shuffled-catalog identity test `PASS`
- Budget/overflow: semantic token budget `PASS`; optional-only shedding, no summarization, no silent truncation, mandatory overflow typed fail-close/stage-split
- Provenance reconstructible: `YES`; cache identity/invalidation: `PASS`

## Shadow isolation

The optional observer is wired in `WorkflowService._stage` after SkillGate resolution and before SkillPromptCompactor. It is disabled by default, receives only hashes/counts/identities/capacity facts, and is observationally fail-open. Fake runs prove production Prompt and model-input call tuples are identical with observer off, on, or failing. Shadow output is used by neither model, validator, authority, router, nor retry.

## Five scenarios

- character-heavy: skills `plot-structure,character-management`; sections `9`; 2556 chars / 639 tokens; capacity `PASS`; rendered SHA `c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd`
- world-heavy: skills `plot-structure,worldbuilding`; sections `11`; 2423 chars / 606 tokens; capacity `PASS`; rendered SHA `dc980e981d70fef74d886dae0a04e0c11460020e6e6f147fa1f2f6e54db89c04`
- conflict-pacing-heavy: skills `plot-structure`; sections `5`; 1216 chars / 304 tokens; capacity `PASS`; rendered SHA `e4220b3b3fba69609bf419170f8661f55fe733a7518ce626ab1599a20cc2381e`
- setup-payoff-heavy: skills `plot-structure`; sections `9`; 1864 chars / 466 tokens; capacity `PASS`; rendered SHA `c02f3e19cabe5c7d8a47fb6b9fdb5f785316df6d88afe025c1c095b0e56b4af6`
- mixed: skills `plot-structure,character-management,worldbuilding`; sections `9`; 2285 chars / 572 tokens; capacity `PASS`; rendered SHA `2d88f401bb4ea70cecd0002382db6648d1055eeaeb5ec1cc78f459925963a2a7`

## Audits and architecture

- Exact duplicate bodies: `0`; unauthorized semantic dedup: `0`
- Semantic conflicts: `UNKNOWN_REVIEW_REQUIRED`; no LLM adjudication or runtime rewrite
- Unknown selected ownership: `0`
- Offline semantic coverage: `PASS` as deterministic identity/lexical coverage only; no literary-quality claim
- Full-verbatim gates: capacity `PASS`, safety `FAIL`, duplicate/repetition `FAIL`, stage ownership `FAIL`
- `FULL_VERBATIM_SELECTED_SKILLS_PREFERRED=NO`
- `SELECTIVE_VERBATIM_SECTIONS_PREFERRED=YES`
- The selector was not presumed mandatory; full verbatim remains an allowed future result if all four gates pass
- Multi-sample binding: character-heavy, 3 A + 3 B, max 6 calls, fresh blind evaluator contexts, critical-dimension non-inferiority rule
- `SINGLE_SAMPLE_PROMPT_HILL_CLIMBING_DEPRECATED=YES`

## Validation

- Focused tests: `15 passed in 5.95s`
- Adjacent tests: `279 passed; 1 historical sealed check-only gate blocked by intentional successor owning-source diff`
- Full suite: `3645 passed, 41 skipped, 6 xfailed, 52 failed, 72 errors in 2063.08s; failures are historical Canary/materialization, Planning Skill oracle, R0E/R0F fixed-hash, and Skill V2 sealed-evidence gates`
- Strict L3: `PASS; warnings=0; blockers=0`
- New owning-source regression count: `0`
- Privacy: `PASS`, matches `0`
- Manifest: all evidence artifacts except the manifest itself; definition/file SHA are calculated after this report and reported by the seal/final response

## External and authority state

- `CREDENTIAL_LOOKUP_COUNT=0`
- `REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
- `REAL_PROVIDER_REQUEST_ATTEMPTS=0`
- `HTTP_POST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `APPROVAL_CREATED=NO`
- `NONCE_CREATED=NO`
- `PAIR2_TO_5_EXECUTION_ALLOWED=NO`
- `SKILL_V3_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `PLANNING_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

## Next gate

`EXACT_NEXT_GATE=SKILL_V3_SELECTIVE_COMPILER_SHADOW_EVIDENCE_REVIEW_AND_REAL_PILOT_READINESS`

That gate remains offline. No approval, nonce, or real pilot packet was created.
