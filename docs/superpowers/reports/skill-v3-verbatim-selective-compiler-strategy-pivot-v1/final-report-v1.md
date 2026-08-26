# SKILL-V3 — Verbatim/selective Skill compiler strategy pivot

## Outcome

`SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_STRATEGY_PIVOT_DESIGNED`

`SELECTIVE_COMPILER_ARCHITECTURE_READY_FOR_SHADOW_IMPLEMENTATION=YES`

The Selective Compiler was not treated as required in advance. The priority baseline injected the complete original Skills selected by the existing Planning resolver. It passed capacity, but failed safety, repetition, and stage ownership; therefore the evidence-backed decision is `SELECTIVE_VERBATIM_SECTIONS_PREFERRED`. `FULL_VERBATIM_SELECTED_SKILLS_PREFERRED` remains an explicitly permitted outcome if all four gates pass in a future source state.

## Baseline and scope

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `16d5bd7e8088a29581d46feff1b3d040fcbac0b1`
- Design/evidence commit: recorded after sealing
- Source implementation diff: `0`
- Production cutover: not authorized
- Existing stage-specific Skill routing confirmed: `YES`
- Repo Skill project source-of-truth target: `YES`; current bundle runtime reachability remains `NONE`

## Priority full-verbatim baseline

- Selected complete Skills: `story-init, plot-structure, character-management, worldbuilding`
- Rendered size: 21491 chars / 5373 estimated tokens
- Capacity: `PASS`
- Safety: `FAIL` (4 exact finding groups)
- Repetition: `FAIL` (4 exact overlap groups)
- Stage ownership: `FAIL` (18 wrong-layer Planning sections)
- Decision: `SELECTIVE_VERBATIM_SECTIONS_PREFERRED`

## Reconstructed current architecture

The current stage registry selects different Skills deterministically. Planning resolves story-init, plot-structure, character-management and worldbuilding. Draft resolves chapter-writing, novel-writing and dialogue, with better-writing optional. Review/final review resolve revision-continuity; polish resolves humanizer-zh, dialogue and novel-writing, with better-writing optional; maintenance executes story-maintenance locally. The current active scanner roots do not include the checked-in vendor bundle, so project-local authority remains a migration target rather than a falsely claimed runtime fact.

Original semantics cross seven boundaries: line selection, mandatory-clause extraction, advisory de-duplication/capping, pressure-driven advisory removal, compressed `_RuleSpec` rewriting, demand-aware V2/V3 rewriting, and the maintenance executable path. T5/T6 are actual paraphrase boundaries; T1–T4 can also lose ordering, examples, caveats or interactions.

## Successor architecture

- Section identity: checked-in immutable opaque IDs plus exact file/section hashes, heading path, AST/span and order; no line-number-only or fuzzy matching.
- Selector: deterministic local function of resolved Skills, stage/substage, contract identity, demand enum, authority selection facts, index/policy versions and capacity profile. It never reads prose output or quality results.
- Rendering: exact source text with LF normalization, enumerated metadata removal and neutral delimiters only.
- `NO_LLM_SUMMARIZATION_IN_SKILL_COMPILER=YES`
- `RUNTIME_PARAPHRASE_OF_SELECTED_SKILL_SOURCE=NO`
- `CREATIVE_SEMANTIC_REAUTHORING_COUNT=0`
- Wrong-layer section count: `72`
- Unknown ownership count: `0`
- Subtext/surface cadence belongs to Draft; anti-template detection belongs to Quality Review; motive/tactic/cost/dependency causal structure stays in Planning.

## Budget and five offline scenarios

The 3000-char target is not an architecture invariant. The successor policy measures the exact safe context window, non-Skill input and output reserve in conservative tokens. It drops optional support first; mandatory overflow uses an already-contracted stage split or fails closed. It never paraphrases or silently truncates to fit.

- character-heavy: 4647 chars / 1162 estimated tokens / PASS
- world-heavy: 5653 chars / 1414 estimated tokens / PASS
- conflict-pacing-heavy: 2728 chars / 682 estimated tokens / PASS
- setup-payoff-heavy: 3500 chars / 875 estimated tokens / PASS
- mixed: 5571 chars / 1393 estimated tokens / PASS

The complete four-Skill baseline also fits the conservative scenario budget; it was rejected only by the three non-capacity gates.

## Provenance, caching and shadow path

Each output binds compiler/resolver/index/policy versions, ordered Skill and section identities/hashes, omissions, rendered hash/size, capacity inputs and overflow decision. The cache key includes every semantic input and exact source hash, preventing stale reuse after Skill edits.

S1 integrates shadow-only after `SkillGate` resolution/load and before `SkillPromptCompactor` in `WorkflowService._stage`. It records section IDs, hash-only rendered identity, size, provenance and coverage. It does not change production model input, authority, route, prompt, retry/fallback or budget.

## Validation methodology and migration

Single-sample prompt hill-climbing is deprecated for architecture decisions. The first real pilot, only after separate materialization and approvals, is character-heavy with three A and three B samples (maximum six requests), two fresh independent blind evaluator contexts and a prospectively authorized third only for tie-breaking. Evaluation stays dimension-level: no scalar averaging; supported critical regression or inconclusive critical evidence blocks non-inferiority.

Phases S0–S3 are offline; S4 is the separately approved 3+3 pilot; S5 covers other demand classes only after S4 passes; S6 decides generalization; S7 is a separate cutover candidate; S8 is later Planning V2/Full Short work. No phase transition is automatic.

Demand-aware V2 remains `KEEP_AS_PRODUCTION_BASELINE_ONLY` and last-known-best. Residual V3 remains `SEALED_NEGATIVE_EVIDENCE`.

## Validation and safety

- Focused/related tests: `95 passed in 4.54s`
- Strict L3: `PASS; warnings=0; blockers=0`
- Privacy: `PASS`, matches `0`
- Manifest: covers every evidence artifact except the manifest itself; definition and file SHA are reported after seal
- `SOURCE_IMPLEMENTATION_DIFF=0`
- `NEW_OWNING_SOURCE_REGRESSION_COUNT=0`
- `PAIR2_TO_5_EXECUTION_ALLOWED=NO`
- `SKILL_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `SKILL_V3_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `PLANNING_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `CREDENTIAL_LOOKUP_COUNT=0`
- `REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
- `REAL_PROVIDER_REQUEST_ATTEMPTS=0`
- `HTTP_POST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `APPROVAL_CREATED=NO`
- `NONCE_CREATED=NO`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

## Exact next gate

`EXACT_NEXT_GATE=SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_IMPLEMENTATION`

This report stops at design readiness; it does not enter that gate.
