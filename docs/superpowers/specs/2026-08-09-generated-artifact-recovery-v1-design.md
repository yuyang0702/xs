# Generated Artifact Recovery V1 — P0–P6 decision contract

## Outcome and non-negotiable constraints

All model-produced machine-readable artifacts cross one versioned conversion
boundary before entering planning, writing, quality, or persistence code. The
program must handle presentation drift and recover the smallest complete unit;
stopping accurately is not counted as recovery. Runtime remains authoritative
for event ownership, state, causality, viewpoint, timeline, relationships,
promises, and the confirmed ending. Existing formal manuscripts are immutable.

Provider-specific aliases, regexes, and parser branches are not a root fix.
BAML's Schema-Aligned Parsing is the mature alignment layer for open structural
drift, JSON Repair is limited to syntax, and Pydantic plus existing domain
validators make the final decision. The application continues to call models
through `ModelGateway`; BAML never owns credentials, routing, retries, or calls.

## P0 inventory and convergence

`generated_artifacts.ARTIFACT_CONTRACT_REGISTRY` registers planning adaptation,
causal packets, execution manifests, draft receipts, polish/revision/final
review, maintenance, interview, outline, style, learning, material, and provider
probe artifacts. Every entry declares its semantic authority, field authority
classes, parser strategy, and recovery ladder.

The only remaining direct calls to the strict JSON reader are:

- the exact fast path inside the shared conversion gateway;
- three output-completeness checks that must reject transport truncation;
- two hash-bound stored-checkpoint readers that must not repair persisted data.

All other model-output consumers use the registry gateway. A source scan test
fails if another parser authority is introduced.

## P1 conversion boundary

The boundary records raw and canonical SHA-256 hashes, conversion method,
transformations, quarantined paths, candidate count, and final validation state.
It never stores raw output or credentials. Descriptive metadata is open;
machine-control fields are closed; narrative invariants are Runtime-owned.

Causal drift is handled topology-first: local code identifies exactly one
cycle-shaped array without naming its container, BAML aligns only the selected
elements, ordered event ownership is compared to the immutable packet contract,
and Pydantic/domain validation accepts or rejects the canonical result. Multiple
candidates, foreign ownership, and unknown control fields fail into bounded
recovery rather than being guessed.

## P2–P3 migration

Planning adaptation receipts, causal chains, execution manifests, manifest
receipts, planning repair packets, draft semantic receipts, structural revision
plans, material audits, maintenance facts, and final-review JSON use the shared
gateway. Local semantic validators remain unchanged and execute after conversion.
Prose and creative Markdown are not rewritten by the gateway.

## P4 recovery

Typed recovery separates transport, capacity, truncation, syntax/protocol,
ownership/evidence, semantic invariant, quality regression, and stale authority.
The ladder supports local normalization, receipt-only retry, capable route
fallback, minimal regeneration, semantic split, checkpoint resume, and restoration
of the best validated candidate. A protocol repair never consumes semantic repair
budget, and semantic split preserves exact ordered ownership and predecessor hashes.

## P5 verification

Acceptance includes at least six genre realizations over root, renamed, nested,
double-nested, fenced, and malformed-but-complete topology classes; unseen
container names; ambiguous candidates; reordered, duplicate, and foreign
ownership; unknown nested machine control; output truncation; connection
interruption; checkpoint resume; and production-shaped `steps`/`causal_cycles`
responses. Tests must prove continuation across the next authoritative boundary.

## P6 canary and retirement gate

Real third-party API validation runs only after local and strict change gates.
It uses the configured Windows-user service and credential lookup without
printing, copying, or logging secrets. The canary is bounded to a non-formal
artifact/resume path and must cross the artifact's authoritative domain validator.
The production-shaped offline gate separately must cross causal validation into
an execution manifest, so live credential verification never requires exposing an
existing novel merely to repeat deterministic downstream coverage.
Duplicate legacy parser authority may be deleted only after the canary and full
suite pass; strict checkpoint readers and transport-completeness checks remain by
design. No Git commit or push is part of this contract.

## Implementation verification and clean-room review

- BAML generation/checking passed, and the full repository suite passed with
  `1788 passed, 1 skipped`; the one warning is an existing Starlette/httpx
  deprecation warning.
- The strict L3 forward-risk gate reports no blocker. Its sole procedural warning
  is that more than two authority-critical modules changed. A multi-agent council
  was not requested, so a single-agent clean-room review was performed from the
  original P0-P6 requirement, pre-task baseline, complete task-local diff, source
  parser inventory, production failure fixtures, forward-risk matrix, full suite,
  live evidence, and before/after formal-file hashes. The warning is recorded and
  not bypassed.
- Eight unique models in active role bindings completed secret-free real API chat
  probes. Three routes observed `strict_tool`; five observed `plain_text`, proving
  the runtime must honor measured capability rather than provider/model branding.
- The isolated synthetic materials-audit canary resumed the same failed run and
  completed through the real third-party GPT route and `material_audit` domain
  boundary. Its conversion receipt used `exact_json`, was semantically valid, and
  contained hashes rather than raw model output or prompts. The synthetic project
  was permanently removed after verification.
- The protected project's root `story.md` and `chapters/_index.md` SHA-256 values
  exactly match their pre-canary baseline, and no formal manuscript was created.
