# SHORT-PLAN-V2-SLICE1-IMPLEMENTATION-PLAN — Final Report

## Decision

`SHORT_PLAN_V2_SLICE1_IMPLEMENTATION_PLAN_READY`

The next implementation can proceed as an isolated, offline-first, shadow-only Slice 1. It does not require a Planning V1 authority change, production workflow wiring, BAML change, Prompt change, or real model call. The exact unit is one narrative realization for one formal event; the model/fixture owns only `title` and `narrative`, while Runtime copies authority fields and deterministically derives identity, order, hashes, dependencies, lifecycle, validation and provenance.

The recommended first implementation does not modify `workflows.py` or `contract_runtime.py`. It adds an isolated Slice1 module and offline replay runner, and adds one disabled/unreferenced strict candidate registration to `generated_artifacts.py`. Existing `compile_planning_event_artifact` remains the local semantic owner after Runtime injects the authority event ID. No shadow artifact can become Planning or Draft authority.

## Parent Evidence Gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `5503beba9138fc21a157c072d047cea4b2bff43c`
- Worktree at start: clean
- Sealed parent manifest: 19 entries recomputed, 19 exact, 0 mismatches
- Production `src/**` diff at gate: 0
- `baml_src/**` diff at gate: 0

The plan binds the sealed final report, current contract map, field ownership, seven-stage architecture, artifact contracts, freeze/thaw, recovery ladder, semantic impact closure, deterministic merge, global closure, Draft minimum contract, shadow migration, replay plan, success metrics, Slice1 recommendation, forward risks and SHA manifest. It also inspected the current Planning domain model, generation owner, GeneratedArtifact conversion boundary, semantic compiler/validators, targeted repair, PTR3 finding projection, Planning recovery, Canonical Shadow conventions, READY inputs and Draft-facing workflow seams.

No baseline or evidence drift was found, so neither baseline nor semantic-boundary NO-GO applies.

## Required 33-Item Accounting

### 1. Branch

`r1-ptr3/planning-repair-finding-propagation-20260817`

### 2. HEAD

`5503beba9138fc21a157c072d047cea4b2bff43c`

### 3. Worktree start/end

Start: clean. End: contains only the 22 new plan/evidence files in `docs/superpowers/reports/short-plan-v2-slice1-plan/`; no production or BAML edits. This is the expected plan-materialization state.

### 4. Exact Slice 1 semantic boundary

`EVENT_REALIZATION_UNIT_SHADOW_V1` represents one non-authoritative narrative realization for exactly one formal Planning event inside a bounded segment packet. It carries the existing event identity/order context, event-level narrative realization, bounded predecessor/causal context and relevant segment intent. It does not own event/segment IDs, ordering, hashes, dependencies, `exit_state`, beat or scene allocation, global closure, Planning authority or Draft authority.

Event relation is 1:1. Beat and scene decomposition remain future stages. It consumes causal preconditions but does not author the state transition in Slice1. Its only downstream consumers are deterministic Slice1 assembly, offline comparison and replay metrics.

### 5. Slice 1 field count

26 flattened artifact fields, including the two nested provenance leaves.

### 6. LLM-owned count

2, both `LLM_CREATIVE_CONTENT`: `title`, `narrative`. `LLM_SEMANTIC_DECISION=0` inside this slice.

### 7. Authority-copy count

4: `parent_authority_sha256`, `formal_event_id`, `formal_event_contract_sha256`, `predecessor_boundary_sha256`.

### 8. Local-derivation count

20. `HYBRID=0`. This remains consistent with the sealed V2 design: its third future LLM field, `exit_state`, belongs to a later stage and is intentionally absent here.

### 9. Shadow artifact model

Add frozen models in `src/novel_flywheel/planning_v2_slice1.py`:

- `EventRealizationCandidateV1`: closed strict `{title, narrative}`.
- `EventRealizationInputAuthorityV1`: read-only bounded authority projection.
- `EventRealizationArtifactV1`: versioned, hash-bound, dependency-explicit, validated and frozen shadow artifact.
- `EventRealizationShadowSetV1`: exact ordered deterministic assembly.
- `LosslessSliceDiagnosticV1`: typed path-preserving finding.
- `Slice1ComparisonReceiptV1`: non-mutating comparison evidence.

Identity is derived from canonical schema/version/parent/event/event-contract bytes. Serialization is canonical UTF-8 JSON with sorted keys and compact separators. Phase A persists only caller-selected evidence output; it writes no Planning, StoryState, Canon, READY or Draft state.

### 10. Input authority

Minimum input is the exact parent Planning authority hash, one exact formal-event contract and ordinal, relevant bounded READY/StoryState/Canon projections, predecessor boundary or first-event sentinel, relevant ending/downstream obligation projection, and source/dependency hashes. Projections must be lossless for the selected event; a truncated or unknown dependency refuses local repair.

### 11. Generation boundary

Phase A has no LLM step: it reads authority, projects one unit, accepts a sanitized offline candidate, locally derives metadata, validates, freezes, assembles, compares and measures. Phase B may later add a new shadow-only narrow contract emitting `title` and `narrative` only. It must not reuse the full Planning prompt as an executable contract and must not ask the model to echo authority or bookkeeping.

Current V1 Planning runs unchanged. Shadow failure is strict and typed internally but `FAIL_OPEN_WITH_RESPECT_TO_V1_PRODUCTION`.

### 12. Validator stack

- A Structural: exact closed candidate, strict strings and canonical artifact shape.
- B Referential: exact event existence, order, scope uniqueness and 1:1 coverage.
- C Authority consistency: parent/event/predecessor/dependency hashes exact; model authority echoes rejected.
- D Local semantic: Runtime injects `formal_event_id`, then the existing event compiler validates one meaningful realization and fixture-labelled obligations.
- E Cross-artifact: exact ordered coverage, no duplicate/gap/mixed parent, immediate predecessor binding.
- F Deferred global: actor/world/global-time/setup-payoff/ending/Draft-executability constraints remain future, nonblocking Slice1 closure.

Every blocking validator emits the lossless finding shape and declares repairability, impact and owner. No literary taste is hardcoded.

### 13. Lossless diagnostic design

`LosslessSliceDiagnosticV1` preserves rule code, exact JSON Pointer, invariant, artifact identity, parent hash/revision, dependency hints, validator identity/policy hash, type, structural shape, observed-value hash, repair eligibility, severity and exactness. Raw values, story, prompts and provider output are absent. Syntax, object, multiple-candidate and unknown-field failures remain distinct. A deterministic projection into existing `DiagnosticDomainFindingV1` supplies PTR3 compatibility without refactoring PTR3.

### 14. Freeze/thaw

Freeze occurs after A–D pass and before assembly/comparison. Metadata binds revision, payload/dependency/receipt/policy hashes and logical sequence. Thaw is allowed only for exact parent/event/predecessor changes or a CAS-bound exact finding. Revision increments once. Stale findings reject without mutation. Only closure members and derived assembly/comparison receipts invalidate; unrelated frozen hashes remain exact.

### 15. Recovery ladder

- L0: one deterministic wrapper/bookkeeping repair; creative bytes unchanged.
- L1: one title or narrative patch on one artifact.
- L2: one proven dependency-closure patch, maximum current plus immediate predecessor (two artifacts).
- L3: one complete Slice1 event-set regeneration.

Whole Planning regeneration is forbidden. The no-progress signature binds authority, candidate payload, canonical findings and closure. A repeated signature without artifact/finding change stops immediately with `PLANNING_V2_SLICE1_CONVERGENCE_EXHAUSTED`; it never dispatches blindly.

### 16. Semantic impact closure

The minimum graph has `authority_snapshot`, `formal_event_contract`, `predecessor_boundary` and `event_realization_artifact` nodes, with `binds_authority`, `realizes_event`, `depends_on_predecessor` and `immediate_adjacency` edges. Title and local narrative findings close over one artifact; an explicit continuity finding closes over current plus immediate predecessor. Unknown, non-adjacent or larger impact escalates to L3.

### 17. V1 comparison

Internal assembly sorts exact validated coverage by formal ordinal and creates only `EventRealizationShadowSetV1`; it does not create a Planning draft, Markdown, IR, Manifest or Draft input. Comparison uses normalized identity/coverage, validity, narrative presence/richness and explicit fixture obligations. It does not compare raw bytes or equate a V1 segment title with a per-event title. Divergence is classified as equivalent, neutral creative, proven structural improvement, regression, or uncomparable historical evidence. The receipt is read-only.

### 18. Replay corpus

The minimum corpus includes: latest real Short Call1 sealed metadata/hashes only; PTR3 repair/finding cases; known planning domain failures; relevant structure drift; GeneratedArtifact wrapper/shape cases; synthetic local/adjacent/unbounded impact cases; and successful one/multi-event, multilingual, terse and verbose controls. Call1 raw content is unavailable, so its result must be `uncomparable_historical_evidence_missing`, never invented reconstruction.

The output-boundary matrix includes at least six valid realizations over four topology classes, two unseen valid wrappers, two invalid shapes and two capacity/transport cases. A private-project replay uses only a read-only hash/shape snapshot plus a sanitized isomorphic fixture.

### 19. Metrics

Collect first-pass pass rate, bounded convergence, LLM calls/success, deterministic repair count, already-valid mutation, freeze violation, same-failure without state change, closure size, Slice1 regeneration, semantic regression, V1 divergence, later token I/O and later elapsed time. Phase A model metrics are null/not-applicable and calls are zero. Hard zero gates include already-valid mutation, freeze violation, stale finding and same-failure dispatch. No unsupported percentage threshold is asserted before baseline collection.

### 20. Exact implementation commit sequence

1. Add isolated models, identity and serialization; gate `SLICE1_CONTRACT_IDENTITY_EXACT`.
2. Add strict candidate registration, conversion, validators and lossless PTR3-compatible findings; gate `SLICE1_LOSSLESS_VALIDATION_EXACT`.
3. Add freeze, bounded recovery, assembly and comparison; gate `SLICE1_RECOVERY_ISOLATION_EXACT`.
4. Add offline runner, sanitized corpus and metrics; gate `SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_VALIDATED`.
5. Document, run the strict L3/full regression gate and seal implementation evidence; gate `SHORT_PLAN_V2_SLICE1_IMPLEMENTED_SHADOW_ONLY`.

Each commit is independently reviewable and reversible; none performs cutover.

### 21. Exact proposed file scope

Add:

- `src/novel_flywheel/planning_v2_slice1.py`
- `tools/diagnostics/short_plan_v2_slice1.py`
- `tests/test_planning_v2_slice1.py`
- `tests/test_short_plan_v2_slice1_replay.py`
- `tests/fixtures/reliability/short_plan_v2_slice1/event-realization-shadow-corpus-v1.json`
- implementation evidence under `docs/superpowers/reports/short-plan-v2-slice1/**`

Modify only:

- `src/novel_flywheel/generated_artifacts.py`
- `tests/test_generated_artifacts.py`
- `docs/maintenance.md`

Explicitly do not modify `workflows.py`, `contract_runtime.py`, `planning_semantics.py`, `planning_compiler.py`, `canonical_shadow.py`, PTR3/recovery/trace owners, `baml_src/**`, or current prompts/routes/models/retries/fallbacks/budgets/validators.

### 22. V1 isolation proof

The design has no workflow invocation, no Draft consumer and no production state writer. The registered candidate name is disabled/unreferenced except by the offline exact-scope runner. Tests snapshot V1 Planning bytes, Draft input, StoryState, Canon and V1 outcomes before/after shadow success and failure. `commit_performed=false`, `promotion_eligible=false`, and `shadow_only=true` are immutable. If isolation requires a workflow/runtime behavior change, implementation stops at `SHORT_PLAN_V2_SLICE1_PLAN_NO_GO_SHADOW_ISOLATION_NOT_POSSIBLE`.

### 23. Narrative quality preservation

Creative content stays model/fixture-owned. Offline checks use explicit sanitized obligation labels for motivation, conflict, intent, agency and causal preparation, plus descriptive richness signals and varied genre/voice/language controls. They detect loss without turning taste into rigid validation. Slice1 does not feed Draft; any future cutover must separately prove the sealed Draft minimum contract.

### 24. PTR12 parallel sequencing

Phase A is independent of PTR12 and can be implemented in disjoint files. PTR12 remains a separate owner and approval stream. Before any real model-backed Slice1 run or next real Full Short, PTR12 must be reassessed; the default is that its observer implementation and validation are required. PTR12 is not implemented in this task.

### 25. Phase A / Phase B strategy

Phase A is offline deterministic/replay shadow and is the only recommended next implementation. Phase B is optional model-backed shadow after Phase A data model, diagnostics, recovery and metrics stabilize. Phase B requires a new narrow contract, PTR12 gate, fresh single-use external-call approval, explicit budget and terminal stop conditions.

### 26. Test plan

Tests cover artifact identity/serialization/authority/staleness; ownership; all validator layers; lossless findings and PTR3 projection; L0–L3 recovery and no-progress; freeze/thaw/CAS; V1/Draft/StoryState/Canon isolation; replay failures and controls; quality preservation; privacy and zero external actions. Run focused new tests, adjacent Planning/compiler/PTR3/shadow tests, full `pytest -q`, then the strict L3 change gate with forward-risk evidence.

### 27. Implementation acceptance Gate

First: `SHORT_PLAN_V2_SLICE1_IMPLEMENTED_SHADOW_ONLY`. It requires V1 authority unchanged, disabled parity exact, strict shadow validation, V1 fail-open behavior, deterministic derivation, lossless diagnostics, freeze/recovery tests, no whole Planning regeneration, functional offline replay/metrics, and zero external actions.

Second and separate: `SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_VALIDATED`. Neither gate authorizes a real canary or production cutover.

### 28. Forward risks

The risk report covers creative context loss, duplicate authority, under-closed dependencies, over-rigid freeze, over-escalation, premature global validators, false V1/V2 regressions, hidden semantic derivation, production mutation, later doubled cost, GeneratedArtifact closure regressions and overly coarse compiler semantics. Each has a concrete detection, containment and rollback. Slice1 cannot claim full Planning/Draft/Short convergence.

### 29. Production diff

0. This task added evidence only under `docs/superpowers/reports/short-plan-v2-slice1-plan/`.

### 30. BAML diff

0.

### 31. Privacy

Exact. No credentials, API keys, raw prompt, manuscript/story text, Provider content, raw tool arguments or personal data are present. Future diagnostics are hash/shape/count/status only.

### 32. SHA manifest

`short-plan-v2-slice1-final-sha256-manifest-v1.json` binds all other 21 evidence files by bytes and SHA-256 and excludes itself. It is generated only after content and privacy validation.

### 33. External action counters

- credential: 0
- provider client: 0
- network: 0
- model: 0
- paid: 0
- Full Short Canary: not executed

## Terminal Markers

`PRODUCTION_IMPLEMENTATION=NOT_STARTED`

`SLICE1_IMPLEMENTATION=NOT_STARTED`

`PLANNING_V1_AUTHORITY_UNCHANGED=YES`

`PLANNING_V2_SLICE1_SHADOW_ONLY=YES`

`PTR12_OBSERVER_IMPLEMENTATION=NOT_STARTED`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`NEW_FULL_SHORT_CANARY=NOT_EXECUTED`

`NEXT_STEP=SHORT_PLAN_V2_SLICE1_IMPLEMENTATION`
