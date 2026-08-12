# Structured Output Runtime V3 — business-wide convergence contract

## Outcome and user contract

The recurring planning and reference-distillation incidents are one architecture
family: a model returned usable story or analysis semantics in a representation
that did not match the current Pydantic wire shape.  The Runtime treated the
representation defect as a semantic defect, repeated or rewrote a larger unit,
and eventually failed even though validated upstream work remained available.

This change must solve that family across every reachable business entry, not
add aliases for the two observed payloads.  It must preserve story quality,
logic, event ownership, evidence, StoryState, Canon, and formal-promotion gates.
Accurate rejection alone is containment, not completion.  The program must first
perform every provable local conversion, then a bounded same-task protocol
retry, then an explicit capable-route fallback, and only regenerate the
smallest semantic unit when the canonical semantic contract itself is invalid.

The short-fiction operating recommendation remains at most 30,000 effective Han
characters without becoming an API hard limit.  Workflow acceptance uses full
production-shaped 13,000, 20,000, and 30,000-character flows.  The user-designated
current project/reference data is replayed from a secret-free, read-only snapshot
in an isolated project/database copy.  No live formal manuscript, Canon,
StoryState, reference source, credential, run history, or checkpoint is changed.

## Audit before implementation

### Measured concentration and duplication

- Python business source: 62,654 lines across 118 files.
- `workflows.py`: 25,427 lines (40.6% of business source), about 312 methods,
  51 `_stage` call sites, and 410 checkpoint references.
- The generated-artifact registry contains 25 business contract names (27
  constructor occurrences including type declarations), but the versioned
  adapter registry covers only four contract families.
- `ArtifactContractRegistration.recovery_ladder`, `semantic_authority`, and the
  authority-class declarations are descriptive.  The execution path does not
  consume them to select conversion, routing, retry, checkpoint, or repair.
- Registered adapters are invoked manually at a few planning/compiler call
  sites. `GeneratedArtifactGateway.convert_object` does not generally execute
  the registered adapter chain.
- Route-specific `complete_primary` and `complete_configured_fallback` cannot
  carry a structured schema/requirement.  A caller currently has to choose
  between explicit route ownership and native structured-output enforcement.

The result is a central catalogue plus several local execution systems, not one
runtime.  Prior P0–P6 documentation correctly established valuable parser,
checkpoint, and recovery primitives, but its business-wide coverage claim is
stronger than the reachable code.  The source-count gate proves the number of
strict-parser calls; it does not prove that every registered recovery ladder is
executable, every adapter is reached, or every user entry uses the same route
and checkpoint boundary.

### Reachable business-risk matrix

| User/business path | Current strengths | Current architecture gap | V3 disposition |
| --- | --- | --- | --- |
| Short planning semantic IR | Pydantic V2 IR, JSON Schema, strict-capability call, exact event/terminal topology, new semantic packets | Root/open-wrapper drift is handled by a one-off envelope path; runtime-owned extra fields can still fail the Pydantic wire shape | Migrate first; canonical proposal plus Runtime envelope; registered adapters execute automatically |
| Legacy/local planning repair | Monotonic best candidate, segment checkpoints, scoped event repair | Markdown/JSON rewrap and receipt recovery are spread across workflow methods; some completion checks use a separate parser | Migrate to the same protocol executor; retain monotonic semantic gates |
| Causal chain | BAML SAP, event coverage, packet split/checkpoint | Explicit route packets use plain output; protocol repair can still regenerate a complete semantic packet | Use route-specific schema/SAP executor and immutable semantic proposal |
| Execution manifest | Strong ownership/evidence adapter and downstream semantic receipt | Adapter is invoked manually; initial syntax/protocol failures can rewrite a fragment | Automatic adapter chain; model returns proposal IDs, Runtime binds evidence/envelope |
| Segment/whole draft receipts | Semantic freeze, explicit route schedule, capacity split, exact evidence | Logic is mature but workflow-local rather than contract-runtime owned | Preserve behavior and migrate orchestration to shared executor |
| Final review and reader simulation | Typed review gates and hierarchical long-input review | Final-review retries may reopen all semantic verdicts; `_reader_json_object` is a second ad-hoc model-output parser | Remove parser bypass; freeze semantic verdict on protocol-only retry |
| Short maintenance and promotion | Typed window map/reduce, evidence offsets, checkpoints, Runtime seal, StoryState and corpus CAS, promotion Saga | Whole fast path and window path still expose different local orchestration | Register both as one contract policy; retain current formal gates |
| Reference-analysis windows | Per-window model claims are reusable | Generic primary call can hide fallback; parser/retry is local | Shared route/contract executor; preserve completed windows |
| Reference distillation/final synthesis | Route-bound hierarchy, exact child coverage and attribution Pydantic model, validated region cache | No registered representation adapter; identical full prompt is retried after validation; error is classified as semantic; final task state is memory-only | Primary incident target; deterministic V2 legacy-shape adapter, protocol-only repair, durable task/checkpoint resume |
| Wizard interview | Pydantic domain model, locked-field recheck, DB messages | Plain call followed by a second model that rewrites a truncated raw response; raw errors reach API | Shared structured executor and safe error projection; no model-authored Runtime controls |
| Style sample | Domain validation and managed profile block | Plain full repair, no durable checkpoint, multiple project files are written without one snapshot/Saga | Shared executor; atomic managed-artifact commit |
| Outline material manifest | Local extraction and provenance validation | Model/parser failure is silently swallowed into a cached local-only result | Typed degraded state plus bounded recovery; never present containment as model-confirmed |
| Outline semantic review | Allowed change IDs and post-parse filtering | No structured route, protocol retry, or checkpoint; invalid entries are silently skipped | Typed proposal, exact ID coverage, smallest review retry |
| Material impact analysis | Exact old-text binding and snapshot on apply | Input is silently truncated, malformed proposals are skipped, raw exception text is persisted, analysis task is not durable | Capacity packets, typed proposal ledger, safe incident, durable analysis checkpoint |
| Long setup/chapter | Existing StoryState and formal-write checks | Structured planning/review/maintenance remain substantially less mature | Must use the shared V3 kernel; full long-fiction capacity acceptance is explicitly deferred, not claimed |
| Provider probes | Capability measurement and expiry are already route-local | Diagnostic rather than story authority | Reuse V3 schema route primitive; no story-task migration required |

### Production-shaped evidence retained for regression

1. Planning V2: a complete semantic document with an extra root
   `exit_state`, while the canonical segment topology remains recoverable from
   Runtime authority.
2. Reference distillation: five completed windows followed by a final receipt
   whose child ledger uses a prior/alternate representation: missing descriptive
   reasons, `merged` placed in dispositions, `related_child_ids` placed beside a
   disposition, `attribution_type` instead of `relation`, and `/semantic/...`
   pointers instead of pointers rooted at the semantic object.

The private fixture preserves hashes, counts, topology, field/type layout, route
capability, and payload proportions.  Public tests use a sanitized derived
fixture and must not contain story prose, provider errors, credentials, absolute
paths, source titles, or project/entity identifiers.

## Selected mature patterns

V3 combines existing maintained components rather than importing a competing
workflow or state authority:

- Pydantic V2 strict models and discriminated unions are the canonical typed
  boundary.  Descriptive model proposals and Runtime-owned envelopes are
  separate types.
- JSON Schema Draft 2020-12 is rendered from the canonical proposal model for
  routes that have actually demonstrated compatible structured output.
  `additionalProperties`/`unevaluatedProperties` close machine-control objects;
  open descriptive maps are explicit rather than accidental.
- JSON Repair remains syntax-only.  It cannot add a missing semantic claim,
  choose an identity, or authorize an operation.
- BAML Schema-Aligned Parsing remains available for genuinely open container
  topology.  Pydantic plus Runtime ownership validators still decide acceptance.
- Deterministic, versioned contract adapters may change representation only when
  their proof obligation is unique and auditable.  Ambiguous or contradictory
  candidates enter protocol repair, not guessed normalization.
- The existing SQLite supervision/checkpoint and Saga patterns remain the
  durable-execution substrate.  Temporal-style replay semantics are adopted as
  a pattern (persist intent, input authority, validated result, and next node),
  but introducing Temporal itself would create a second operational authority
  and is rejected for this repository.

## Target architecture

### 1. Executable contract registry

Replace descriptive-only recovery declarations with one executable
`ArtifactContractSpec` per model-produced machine artifact.  A spec owns:

- stable name and version;
- strict Pydantic proposal type and provider JSON Schema;
- parser strategy (`json`, syntax repair, optional SAP);
- ordered deterministic adapter descriptors and adapter context factory;
- Runtime-envelope binder and domain validator;
- protocol/ownership/semantic error classifier;
- immutable semantic projection used for protocol-only retry;
- route/capacity policy, retry budget, and checkpoint policy;
- safe public/incident error projection.

Registry construction fails when a contract names an adapter/recovery step with
no executable implementation.  A source/reachability test fails when a model
structured call does not name a registered executable spec.

### 2. One conversion pipeline

The sole acceptance pipeline is:

1. verify terminal transport/finish metadata;
2. parse exact JSON;
3. apply syntax-only JSON repair when structurally complete;
4. optionally perform registered SAP topology alignment;
5. execute every registered deterministic representation adapter;
6. validate the strict proposal model;
7. bind Runtime IDs, hashes, evidence, topology, and source authority;
8. run domain semantic/quality validation;
9. persist one canonical, hash-bound artifact and secret-free conversion audit.

`semantic_validation_failed` is split into shape/protocol, ownership/evidence,
and story semantic failures using typed exceptions and Pydantic error locations.
An extra key, renamed field, wrong envelope, or missing Runtime echo is not a
story-semantic failure.

### 3. Explicit structured route executor

Extend route-specific gateway calls so primary and configured fallback can both
receive `response_schema` and `StructuredOutputRequirement`.  The executor owns
an immutable schedule such as primary/primary/fallback/fallback and never calls
the gateway's hidden auto-fallback path during an explicitly scheduled attempt.
Each route uses its observed capability: strict tool/schema when proven,
`json_object` when proven, otherwise plain text plus the same local conversion
pipeline.  Capability changes alter the route/checkpoint fingerprint.

### 4. Proved adaptation, semantic freeze, and smallest repair

After syntax/adaptation, a complete semantic proposal receives a hash.  A
deterministic registered adapter may rewrap it only when its proof obligation
uniquely preserves the canonical semantic projection.  The generic Runtime
does not send an invalid raw candidate to a model and trust an instruction that
claims “format only”; without a Runtime-verifiable projection, that would allow
silent semantic drift.  If local conversion cannot prove the candidate, the
same immutable task and authority are retried and the new result must cross the
complete canonical and business validators again.

Specialized receipt paths may keep an already validated semantic verdict frozen
while repairing Runtime-owned identity/evidence fields, but only when the
pre-retry semantic hash is independently available and equality is enforced.

Only an authoritative receipt with an explicit negative semantic verdict,
or a canonical proposal that fails domain semantics, may spend a semantic repair
budget.  The repair scope is one child, event, segment, window, or final ledger—
never the whole story/reference merely because JSON shape was wrong.

### 5. Durable task and artifact lifecycle

Reference analysis moves from `ReferenceAnalysisTaskManager`'s in-memory state
to the existing versioned workflow-supervision/checkpoint substrate (or one
generic resource-task extension of it).  Restart reconstructs the operation
from a secret-free frozen payload, reuses validated windows/regions, and resumes
the next missing node.  Cancellation, provider wait, waiting-user, failure, and
completion preserve their intended terminal state atomically.

Every multi-file business mutation (including managed style artifacts) uses a
project snapshot/Saga or a single DB/file projection commit.  Raw provider or
parser exceptions never enter API responses, task status, impact files, or run
events; only a stable code, class, boundary, safe summary, and hash are stored.

## Convergence and deletion budget

The change is incomplete if it only adds V3 beside the old implementations.

- Delete `_reader_json_object` after final review migrates.
- Make `GeneratedArtifactGateway` execute registered adapters; remove manual
  adapter dispatch from workflows/compiler after equivalence tests.
- Replace interview/style full-response repair prompts with the shared
  protocol-only executor.
- Replace direct structured `gateway.complete` calls in reference, outline, and
  material services with named specs.
- Replace declarative `recovery_ladder` tuples with executable policies, or fail
  registry startup when a declared step is not bound.
- Extract route execution, protocol recovery, and checkpoint orchestration from
  `workflows.py`; it may retain story sequencing but not parser/route kernels.
- Keep persisted legacy readers read-only and versioned.  They do not become a
  second model-output parser and are removed only after their retention window.

The initial target is to reduce authoritative structured-output orchestration in
`workflows.py`, not to reach an arbitrary line-count goal.  Completion evidence
must show fewer authoritative parser, adapter-dispatch, and retry implementations
than the baseline, with no new business branch keyed to provider, model, genre,
project, source title, entity ID, prose, or observed error text.

## Implementation sequence

### P0 — reachability and failing fixtures

Freeze the business matrix, executable-registry inventory, and current-project
secret-free snapshots.  Add failing tests for the two incidents and for every
structured entry that bypasses the executable registry.

### P1 — V3 kernel

Implement executable specs, typed failure classification, automatic adapter
execution, proposal/envelope separation, explicit structured primary/fallback
routes, protocol semantic freeze, audit, and canonical checkpoint envelopes.

### P2 — incident and short-story migration

Migrate planning semantic V2, planning recovery, causal packets, execution
manifest/receipt, draft receipts, final review/reader, short maintenance, and
formal pre-promotion verification.  Existing semantic and quality validators
remain authoritative.

### P3 — reference and adjacent business migration

Migrate reference windows/final distillation and durable restart, then wizard
interview, style analysis, outline material/semantic review, and material impact.
Remove silent item skipping unless a Runtime ledger explicitly records every
accepted/rejected input item and proves complete coverage.

### P4 — convergence and compatibility

Delegate/delete duplicate parsers, repair loops, route selection, raw error
projection, and manual adapter calls.  V1/V2 persisted artifacts use explicit
read-only migrations and hash-bound invalidation; no silent checkpoint rewrite.

### P5 — open-world and capacity verification

For every affected contract: at least six valid structural realizations, two
malformed/incomplete/contradictory realizations, two transport/capacity faults,
adapter idempotence, ambiguity rejection, multilingual and unknown descriptive
fields, route capability differences, primary/fallback schedule, cancellation,
restart, checkpoint tamper, and next-authoritative-boundary continuation.

Run complete 13K/20K/30K short-fiction flows through planning, causal chain,
manifest, drafting, split/merge, polish, final review, maintenance, corpus and
StoryState CAS, and formal promotion.  A parser pass, packet pass, checkpoint,
or fail-closed result is not an end-to-end pass.

### P6 — isolated current-project and optional real-provider canary

Replay the current project/reference snapshots in an isolated copy.  The
planning payload must convert and continue into causal/manifest.  The five
reference windows must be reused and the alternate final receipt representation
must convert or receive a protocol-only repair, then persist a validated final
synthesis.  Formal production files remain byte-identical during this replay.
Only after all offline gates pass may a separately authorized bounded real API
canary run without displaying, copying, or recording credentials.

## Acceptance and rollback

Passing requires:

- every reachable structured-output call is owned by one executable spec;
- no unregistered parser/adapter/retry route can accept model authority;
- the two current incidents recover through their next business boundary;
- protocol-only retries preserve the semantic hash;
- validated children/windows/segments survive restart and sibling failure;
- 13K/20K/30K short flows produce quality-gated formal candidates;
- full suite and project strict gates pass on the same frozen tree;
- the real private snapshots pass in isolation with a hash/count-only report;
- formal files and credentials are unchanged unless an explicitly authorized
  canary passes every promotion gate.

Rollback disables V3 dispatch at the executable-spec selection boundary and
restores the pre-task code while retaining legacy persisted artifacts.  V3
checkpoint versions are additive and are never interpreted by V2 readers.
Rollback must not delete validated windows, best candidates, StoryState,
conversion audits, or incident hashes.

## Implementation evidence (in progress)

This section records observed evidence, not a completion declaration.

| Boundary | Evidence | Current classification | Remaining path |
| --- | --- | --- | --- |
| Executable conversion and route kernel | Registered recovery steps are startup-validated; business model calls cannot directly dispatch outside the workflow/tool owners; parser source gate leaves one central parser owner | Implemented and focused-tested | Freeze full-tree evidence and remove compatibility shadows only after deletion gates |
| Planning representation incident | Private production packet SHA matched the incident manifest; automatic root projection preserved all 4 packet ordinals; compiler proved 4/4 formal IDs and terminal closure | Recovered through PlanningDocumentIR for the observed packet | Complete all real plan packets in isolation and continue into causal chain and manifest |
| Five-window distillation incident | Private source length and content SHA matched the database; alternate five-child ledger became 5/5 ordered canonical coverage with relations claim/claim/claim/merged/merged and passed the existing synthesis validator | Representation class and current topology recovered | Persist validated final synthesis on the isolated copy and prove restart reuse |
| Reference window calls | Both primary and fallback window calls use `reference_analysis_window` v2; final synthesis uses `reference_distillation_region` v2 | Migrated | Extend the specific-contract inventory to any remaining generic business artifacts |
| Style managed artifacts | Normal write behavior preserved; injected failure after the first file restores all three old artifacts; delete failure restores the removed folder and managed profile | Transaction boundary implemented | Full suite and final compatibility-shadow deletion gate |
| Short-fiction capacity | Complete deterministic 13K, 20K, and 30K runs passed planning through formal promotion with quality and StoryState assertions | Passing on current intermediate tree | Rerun on the final frozen tree |

The active rollout is therefore not yet `systemically_resolved`. Until the
remaining path is complete, old read-only compatibility readers stay available,
live formal files remain untouched, and no real-provider canary is used as a
substitute for offline evidence.
