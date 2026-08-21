# SHORT-PLAN-V2-DESIGN — Planning Decomposition & Recovery Convergence Architecture

## Final gate

`SHORT_PLAN_V2_DECOMPOSITION_CONVERGENCE_DESIGN_READY`

This is a design/evidence result, not a production repair. Planning V1 remains the only production and Draft authority. The recommended V2 is a seven-stage, artifact-first shadow architecture: immutable authority snapshot; bounded event realizations; bounded semantic transitions; local dependency closure; local Draft projection; deterministic assembly; global semantic closure.

## 1. Baseline and evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `25a4eb0da51fe30fd8417488ae247973adfd3489`
- Worktree start: clean
- Worktree end: docs-only dirty, limited to the 20 new files in `docs/superpowers/reports/short-plan-v2-design/`
- R1-PTR11 manifest: 10/10 byte/hash entries exact
- R1-PTR12 manifest: 10/10 byte/hash entries exact
- `src/**` production diff: 0
- `baml_src/**` diff: 0
- Branch/HEAD stayed unchanged during design.

Read-only bindings included the current Planning semantic schema and compiler, Generated Artifact conversion boundary, Contract Runtime recovery, capacity split/packet merge, local and semantic planning repair, Planning IR/topology, causal/Manifest integration, Draft consumers, READY/Outline/StoryState/Canon interfaces, sealed real Short evidence, PTR11 Call 1–12 reconstruction and PTR12 observer design.

## 2. What the current Planning contract actually is

The provider-facing `PlanningSemanticDraftV2` contains eight scalar leaf paths, not a large number of distinct field paths:

1. `version`
2. `initial_state`
3. `segments[].kind`
4. `segments[].segment`
5. `segments[].title`
6. `segments[].events[].formal_event_ordinal`
7. `segments[].events[].narrative`
8. `segments[].exit_state` (continuation only)

All eight are currently emitted by the model. The important diagnosis is that Planning is overweight by repeated event cardinality, narrative bytes, coupled segment/state constraints and whole-object recovery atomicity—not by field-path width alone. Runtime already derives most IDs, hashes, event evidence, terminal topology, Planning IR and Manifest bookkeeping after the semantic object is accepted.

Recommended ownership over the same eight leaf paths:

| Owner | Count | Fields |
|---|---:|---|
| `AUTHORITY_COPY` | 1 | `initial_state` |
| `LOCAL_DERIVATION` | 4 | `version`, segment `kind`, segment number, formal event ordinal |
| `LLM_SEMANTIC_DECISION` | 1 | exit-state effect |
| `LLM_CREATIVE_CONTENT` | 2 | title, event narrative |
| `HYBRID` | 0 in this current-field denominator | Runtime normalization is applied around proposed transition artifacts in V2 |
| `LEGACY_REDUNDANT` | 0 | none need be called redundant to remove them from model output |

Therefore: current field count = 8; current LLM-emitted count = 8; proposed V2 model-owned count = 3; move out of the model contract = 5; authority-copy = 1; local derivation = 4; redundant/legacy = 0.

## 3. Call 1 evidence and its hard limit

Observed exactly: Call 1 was `planning_semantic_v2`, primary/plain, `finish_reason=end_turn`, 5,349 output tokens, 21,728 post-adapter visible characters, then `semantic_validation_failed`. It was both the first divergence and first unrecovered divergence. The Planning domain compiler was not reached; Draft was never entered.

The semantic failure rule, exact field/path, invariant, affected entities/scenes/events, local-vs-cross-object scope, unrelated retry mutations and later newly introduced semantic failures are all `UNKNOWN`. This is not a missing analysis step: `normalize_planning_semantic_v2_payload` catches the structured validation `ValueError` and returns `None`; the gateway persists only the generic conversion code. No raw candidate was retained. The design must not invent a character, time, causal or narrative defect.

The dependency map therefore proves a diagnostic discontinuity:

`visible candidate -> semantic normalizer rejection -> structured error vector discarded -> generic ArtifactConversionError -> domain validator not reached -> generic whole-contract regeneration`

PTR3 exact finding propagation is valuable, but it does not rescue this Call 1 boundary because its extractor/renderer path depends on a domain finding that was never reached.

## 4. Non-convergence decision

`PRIMARY_NON_CONVERGENCE_MECHANISM=LOSSY_CONVERSION_DIAGNOSTICS_PLUS_WHOLE_ARTIFACT_REGENERATION`

`NON_CONVERGENCE_ROOT_NOT_UNIQUE=YES`

The exact historical payload is absent, so no unique semantic root cause is supportable. The primary mechanism is nevertheless evidence-backed: the actionable location/rule was collapsed, subsequent recovery re-emitted the entire current contract, and no independently accepted sub-artifact existed to freeze. Calls 1, 2, 4, 5, 6, 8, 9 and 10 repeated conversion rejection; calls 3, 7, 11 and 12 encountered output limits; Call 12 ended at 8,798/8,798 tokens.

Secondary mechanisms are high-cardinality coupling, no valid-unit freeze before root acceptance, no proof of state change for generic retries, repair output not proportional to hidden scope, and sticky output-limit terminal amplification. Adjacent invariant breakage, validator conflict and stale state remain `UNKNOWN`.

Existing later recovery is not discarded: capacity packets, deterministic merges, checkpoints and monotonic issue-set/segment selection are useful and should be adapted. The defect is concentrated at the initial semantic boundary and recovery unit.

## 5. Recommended seven-stage V2

| Stage | Owner | Independent artifact | Repair unit |
|---:|---|---|---|
| 0 Authority Snapshot | local Runtime | `PlanningAuthoritySnapshotV1` | rebuild only on authority change |
| 1 Event Realization | model creative content + local envelope | `EventRealizationArtifactV1` per formal event/bounded packet | one event artifact |
| 2 Semantic Transition | hybrid proposal/local normalization | `SemanticTransitionArtifactV1` per event/dimension | one dimension or impact closure |
| 3 Dependency & time/causal closure | local Runtime | `PlanningDependencyClosureV1` | bounded graph closure |
| 4 Draft execution projection | local Runtime | `DraftMinimumExecutionContractV1` per segment | repair source artifact, then recompute |
| 5 Deterministic assembly | local Runtime | `PlanningV2AssemblyCandidateV1` | recompute; never model-merge |
| 6 Global semantic closure | local validators + existing semantic-review boundary | `PlanningV2GlobalClosureReceiptV1` | typed impact closure or escalation |

There is no new model-generated “core skeleton” stage: READY and the formal outline already own core intent and event order. Re-generating them would duplicate authority.

Every artifact has a stable ID, schema/version, bounded scope, parent authority hash, explicit dependency set/hash, revision, canonical payload hash, provenance, validation receipt, and freeze state. A prompt split without independently hash-addressable/frozen outputs does not qualify as decomposition.

## 6. Freeze, recovery and dependency closure

`VALIDATED_SUBARTIFACT_FREEZE_V1` states are `mutable`, `validated_frozen`, `thaw_pending`, `superseded`, and `rejected`. A validated artifact cannot be rewritten by a later model attempt. Thaw requires a typed finding or changed authority/upstream hash whose dependency closure explicitly includes the artifact, plus CAS over revision/payload/receipt hashes. Invalidation propagates only along reverse dependencies; deterministic downstream projections recompute, while unrelated frozen model artifacts remain byte-identical.

The recovery ladder is bounded:

0. one local deterministic normalization/repair;
1. one field/sub-artifact patch;
2. one bounded dependency-closure patch;
3. one bounded event/scene subtree regeneration;
4. one current-stage regeneration;
5. one Planning restart only for changed/invalid authority or unbounded global structure.

Whole Planning regeneration is not an ordinary fallback. A repeated finding with the same authority, closure and payload hashes stops immediately. Every model retry must change a target/dependency hash, remove the prior issue signature, and keep non-target frozen hashes unchanged.

`SEMANTIC_IMPACT_CLOSURE_V1` maps a typed finding to its owning node, minimum repair nodes, immutable context, forward/backward validation closure and stable boundary assertions. It covers actor capability/knowledge/location/relationship, temporal predecessor/successor/window/order, causal precondition/effect/consumer, and scene setup/payoff/continuity. Unknown identity or an unbounded closure escalates; Runtime does not guess a field patch.

## 7. Merge and final closure

`PLANNING_V2_DETERMINISTIC_MERGE` is local-only. It rejects mixed authority hashes, stale revisions, duplicate IDs, gaps/reorders, conflicting writes, unknown fields and authority overrides. Runtime recomputes versions, kinds, segment indexes, ordinals, event IDs, hashes, topology and guards. CAS binds the ledger head and every input revision/hash; there is no silent overwrite.

`PLANNING_V2_GLOBAL_SEMANTIC_CLOSURE` checks authority consistency, completeness, references, time, causality, actor capability/knowledge, location, relationships, scene preconditions/payoffs, ending reachability, Draft executability, and the Planning IR → causal chain → Manifest authority graph. Stage-level parsing does not substitute for global closure. Only a global PASS could become promotion-eligible in a future authorized cutover; shadow artifacts always remain non-authoritative.

## 8. Draft minimum interface and authority compatibility

Draft truly needs: segment order, exact owned event/beat IDs, actionable event/beat obligations, entry state, exit/handoff requirement, future-beat guard, a scoped heading/brief, and authority hashes. Global causal proofs, repair history, route/model provenance and bookkeeping belong to validation/provenance/audit layers, not the Draft model contract.

The current `PlanningDocumentIR` and `ShortExecutionManifest` shapes can remain compatibility projections. READY remains project execution authority. V2 only consumes READY/Outline/StoryState/Canon; it cannot rewrite Canon or mutate StoryState during Planning. Any future promotion remains behind existing authority, CAS, Saga and Maintenance boundaries.

## 9. Reuse / adapt / deprecate

- **REUSE:** Contract Runtime dispatch/diagnostics, current compiler/topology, local validators, PTR3 and R1-D3 finding propagation, causal checker, Manifest, semantic review/quality, PTR9 guard, CAS/Saga/checkpoints and trace envelopes.
- **ADAPT:** current capacity packet/checkpoint/merge into always-bounded event artifacts; monotonic candidate selection into closure-aware artifact selection; semantic normalizer to retain issue vectors in a future approved slice; recovery checkpoints into an immutable artifact ledger.
- **DEPRECATE:** generic whole semantic-object regeneration as ordinary recovery; generic protocol retry after a lossy normalizer rejection; mutable Markdown as primary Planning authority.
- **REMOVE_FROM_LLM_CONTRACT:** version, initial state, segment kind/index and formal event ordinal.

## 10. Budget and convergence policy

No production budget value is proposed or changed. V2 budget ownership is per stage + artifact complexity + repair scope. The estimator inputs are schema overhead, UTF-8/Han payload history by artifact class, event count, model-owned field count, and selected dependency-closure size. Each materialized profile sets expected cap, hard safety cap and total Planning call ceiling before dispatch. A repair cap is proportional to the affected artifact/closure, and semantic failure never automatically increases budget.

The total call ceiling is defined, not guessed:

`baseline model artifact count + min(eligible repair artifacts, configured repair ceiling) + one configured stage-regeneration allowance`

Exhaustion emits `PLANNING_V2_CONVERGENCE_EXHAUSTED` with the artifact/finding/closure ledger.

## 11. Shadow migration, replay and proof

`SHORT_PLANNING_V2_SHADOW` consumes the same authority but writes to an isolated root/ledger and can never feed Draft or mutate production. V1/V2 receipts compare exact coverage/order, Draft minimum completeness, global semantic vectors, finding sequences, repair closure sizes, frozen hashes, calls/tokens/elapsed/fallback and production mutation count.

Replay covers `planning.structure_drift`, `parser.generated_artifact_shape`, PTR3 repairs, the latest real Call 1 chronology, known targeted-repair failures and synthetic actor/time/causal/scene impact cases. Call 1’s missing field is never synthesized as historical fact; field-level dependency tests are labeled synthetic.

Success requires global correctness plus convergence and stability: zero stale findings, zero oscillation, no retry of the same failure without state change, zero unrelated frozen mutations, bounded calls, lower terminal/no-progress rates, and Draft-entry readiness. JSON parsing alone is not success.

## 12. Architecture decision answers

1. **Is current Planning overweight?** Yes by cardinality/coupling/recovery atomicity, not by field-path width.
2. **What leaves the model?** Version, entry state, segment kind/index and formal event ordinal.
3. **How many stages?** Seven, including local snapshot, assembly and global closure.
4. **Owners/artifacts?** Listed in the stage table; only stages 1 and 2 contain model proposals.
5. **Stage validators?** Closed schema, ownership, local narrative/transition constraints, hashes/provenance/freeze.
6. **Global-only validators?** Whole authority/reference/time/causal/state/ending/Draft graph closure.
7. **Smallest repair unit?** One model-owned path in one independently frozen artifact.
8. **When escalate to subtree?** When the typed dependency closure spans multiple event artifacts or cannot be safely field-bounded.
9. **When regenerate a stage?** Once, only when most of that stage is implicated and prior stages remain exact.
10. **When restart Planning?** Only authority/input invalidation or unbounded unrecoverable global structure.
11. **How preserve passed work?** Hash freeze, explicit thaw proof, CAS and reverse-dependency invalidation.
12. **What does Draft minimally need?** Scoped event/beat obligations, entry/exit state, ownership/guards and authority hashes.
13. **How compare V1/V2?** Same authority/corpus, isolated outputs and a typed structure/semantic/convergence/efficiency receipt.
14. **How prove better convergence?** Global correctness preserved, fewer no-progress/terminal events, bounded smaller repair closures, and zero unrelated frozen mutation across matched cohorts.
15. **First implementation?** `EVENT_REALIZATION_UNIT_SHADOW_V1`.

## 13. Slice 1 and PTR12 priority

`SHORT_PLAN_V2_SLICE_1=EVENT_REALIZATION_UNIT_SHADOW_V1`

The first slice extracts each formal-event narrative into a bounded artifact. Runtime supplies identity/order/authority; fake/offline model output supplies only title and narrative; errors retain exact paths; valid event units freeze; merge is deterministic. It directly tests decomposition and convergence without selecting an unsupported character/time/causal historical root and without changing V1 authority.

`PTR12_OBSERVER_IMPLEMENTATION_PRIORITY=PARALLEL`

Offline/fake Slice 1 does not depend on raw Provider shape. PTR12 should be implemented before any future real shadow/Canary so representation and guard decisions are observable, but it does not block Slice 1 planning.

## 14. Required final accounting

- Current Planning field count: 8
- Current LLM-owned/emitted field count: 8
- V2 proposed LLM-owned field count: 3
- Authority-copy count: 1
- Local-derivation count: 4
- Redundant/legacy count: 0
- Proposed stage count: 7
- Production diff: 0
- BAML diff: 0
- Privacy: exact; no secrets, raw Prompt/story/tool args/Provider content or personal data
- SHA manifest: `short-plan-v2-final-sha256-manifest-v1.json`, self-excluded, all other 19 files hash-bound
- External actions: credential 0; provider client 0; network 0; model 0; paid 0

`PRODUCTION_IMPLEMENTATION=NOT_STARTED`  
`PLANNING_V1_AUTHORITY_UNCHANGED=YES`  
`PLANNING_V2_SHADOW_ONLY=YES`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`NEW_FULL_SHORT_CANARY=NOT_EXECUTED`  
`NEXT_STEP=SHORT_PLAN_V2_SLICE1_IMPLEMENTATION_PLAN`

Stop condition reached. Slice 1, PTR12 observer, production code, Provider calls and a new Short Canary were not started.
