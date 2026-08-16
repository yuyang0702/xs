# R1-PTR1 Planning Repair Evidence Closure — Change Contract

## Decision boundary

R1-PTR1 adds fail-open, hash-only observations around the existing Planning
targeted-repair execution path. It does not alter Prompt text, repair scope,
wire schema, parser/adapter semantics, Domain pass/fail rules, strict-tool
acceptance, routes, retry/fallback topology, output budgets, or artifact writes.

The feature flag is
`NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1`, default `false`. It participates in
the V2 execution-config and Runtime fingerprints. Existing Canary profiles bind
it explicitly to `false` and forbid enabling it; a future real observation must
therefore use a new, separately approved profile/packet. This phase creates no
approval and executes no Canary.

## Typed diagnostic contracts

All four contracts use UTF-8, sorted-key canonical JSON under
`r1-ptr1-diagnostic-canonical-json-v1` and carry a sealed SHA-256. Raw Prompt,
story text, normalized payload, tool arguments, Provider response, credentials,
headers, project names, and character names are omitted.

### PlanningRepairDomainValidationSnapshotV1

Records the normalized payload hash and structural-shape hash, repair target
hashes, exact canonical field paths, unchanged validator-source hash, result,
stable rule/invariant codes, value type/shape, count, and omission flags. The
authoritative validator runs first; typed extraction runs only after its
unchanged `ValueError`/`TypeError` decision.

### PlanningRepairFindingPropagationSnapshotV1

Binds the source rejection receipt to the next attempt, records its exact
rule/path set and a hash of the next request semantics, then classifies the
actual propagation as `exact`, `partial`, `generic`, or `absent`. R1-PTR1 never
injects the finding into a Prompt. The current blind retry is therefore emitted
as `absent`.

### ProviderContentBlockShapeSnapshotV1

Captured inside Anthropic, OpenAI Chat, and OpenAI Responses adapters after the
Provider body is available and before `ModelResponse` projection. It records
controlled block types, counts, text length, tool-argument presence/byte length,
partial argument count, reasoning count, finish/usage/budget metadata, and a
Provider-body hash. A post-projection comparison records whether adapter
conversion changed visible text/tool-call counts without storing content.

### PlanningRepairOutputLimitObservationV1

Binds the Contract output-limit action to the exact Provider shape snapshot,
requested and actual Provider-effective budgets, observed tokens/finish reason,
boundary reachability, expansion before/after, and the unchanged next-route
action.

## Fail-open and concurrency policy

Observers return without effect when the flag or exact Planning-repair target
does not match. Hashing, extraction, trace emission, sink failures, malformed
diagnostic input, and snapshot lookup failures are caught and dropped. The
existing business exception remains authoritative. Provider snapshots use a
bounded, lock-protected diagnostic registry keyed by logical attempt id; they do
not participate in business state, transactions, retry decisions, or artifact
acceptance.

## Call graph

```text
WorkflowService._repair_short_plan_adaptation_segments
  -> WorkflowService._stage(planning_repair_patch)
  -> execute_contract_runtime
  -> Provider adapter.complete
  -> safe_capture_provider_content_block_snapshot (pre-projection)
  -> ModelGateway strict-tool/conversion boundary
  -> observe_provider_content_block_shape
  -> GeneratedArtifactGateway wire conversion
  -> unchanged domain_validator
  -> observe_domain_validation_snapshot
  -> unchanged retry/fallback decision
  -> observe_finding_propagation (observation only; no Prompt injection)
  -> next Provider attempt
  -> observe_output_limit (when the existing classifier fires)
```

## Rollback

Remove the R1-PTR1 diagnostic module and four trace registrations, remove the
observer call sites and optional diagnostic fields, remove the flag from the
fingerprint registry and bind it absent from Canary profiles. There is no data
migration or business-artifact rollback because the observer is default-off and
trace-only.
