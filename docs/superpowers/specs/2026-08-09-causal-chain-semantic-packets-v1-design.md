# Causal-chain semantic packet execution V1

## Change contract

- Requested outcome: permanently resolve causal-chain failures caused by fixed
  partitioning and prevent split-derived ownership, checkpoint, fallback, and
  story-logic regressions across novel genres and provider routes.
- Scope: open world. The boundary is the capacity/recovery mechanism, not the
  observed 29-event fixture, provider name, error string, or packet count.
- Allowed changes: generated causal-chain task topology, packet validation,
  output-limit dispatch, planning-route fallback, packet checkpoints, incident
  diagnostics, tests, and maintenance documentation.
- Protected behavior: formal outline and accepted plan authority, StoryState,
  existing model bindings, credentials, formal manuscript, creative wording,
  confirmed ending, run history, and Runtime-only promotion.
- Rollback: revert the semantic packet module and causal-chain executor changes.
  Existing V2 packet files are derived checkpoints and can remain ignored; no
  SQLite schema or manuscript migration is required.

## Root cause and selected mature patterns

The former implementation split the ordered formal-event list into two fixed
halves. A split could cut through a multi-event planning segment, duplicate that
whole segment in both prompts, and create child calls that had no splitter. A
second output-limited child therefore repeated the same oversized scope and
failed before any packet checkpoint was committed.

The replacement combines established patterns without introducing a competing
workflow or authority store:

1. Pydantic typed intermediate representation for immutable task contracts and
   validated packet checkpoints.
2. Boundary-aware recursive Map/Reduce over contiguous formal-event ownership.
3. Temporal-style durable execution semantics using the existing SQLite node
   checkpoints plus atomic project artifacts.
4. Content-addressed idempotency, predecessor hashes, exact-once ownership, and
   deterministic reduction.
5. Hypothesis property tests for partition invariants plus production-shaped
   fake-provider integration tests.

Temporal or LangGraph was not imported. This local application already has one
workflow and one SQLite authority; adding another runtime would increase
deployment, migration, and rollback risk. The selected implementation adopts the
relevant durable-execution semantics inside the existing single-writer boundary.

## State machine and invariants

Each packet is planned, generated, locally validated, atomically checkpointed,
deterministically reduced, whole-chain validated, and only then consumed by the
execution-manifest stage. Failed, cancelled, truncated, ambiguous, stale, or
hash-mismatched packets never replace validated authority.

Stable invariants:

- child ownership is a non-empty exact ordered partition of parent ownership;
- owned and read-only context IDs are disjoint;
- packet authority, parent, depth, predecessor, segments, and ownership are
  hash-bound;
- every accepted packet has exact coverage and closed causal cycles;
- first/last global fields are accepted only from their owning packet;
- reduction has no missing, duplicate, unknown, or reordered formal event;
- interruption retains validated prefixes; corruption invalidates only the
  affected packet and deterministic dependents;
- whole-chain validation passes before execution-manifest readiness.

## Recovery policy

- Input/context pressure: recursively split at the nearest planning-segment
  boundary, then at a contiguous event boundary.
- Output limit: try one verified-headroom retry; on a second incomplete result,
  invoke the same semantic splitter.
- Normal-finish invalid JSON: one same-scope protocol retry, then the semantic
  packet tree.
- Transport failure: try the configured fallback for the same ownership scope.
- Indivisible event failure: use the configured fallback; if it also fails,
  retain all validated upstream work and stop without partial promotion.
- Cancellation/resume: load only content-addressed, hash-valid, semantically
  valid checkpoints; restore a damaged artifact from the exact validated SQLite
  packet mirror before considering model regeneration.

## Compatibility and convergence

The shared `_stage` output-limit boundary now delegates to any declared semantic
splitter, so existing planning review and planning repair splitters gain the same
second-limit behavior. Planning repair also uses the common semantic bisection
primitive. Causal-chain fixed halves are removed and replaced by the one typed
packet protocol. Legacy numbered causal packet files remain readable as audit
files but are deliberately not promoted because they lack full authority and
predecessor binding.

No provider-specific capability, novel genre, event count, model name, response
wording, or fixed packet size is encoded as an acceptance rule.

## Acceptance evidence

- Reproduce the 29-event, six-segment, 31K-token production proportions where
  large packets repeatedly return `max_tokens` and smaller packets succeed.
- Retain real `_stage` assembly, route binding, token policy, provider receipt,
  checkpoint path, parser, validator, and execution-manifest continuation while
  replacing only the paid network boundary.
- Cover six valid packet realization topologies, unseen descriptive containers,
  malformed cycles, reordered ownership, unknown machine-control fields,
  context overflow, output limit, disconnect, primary/fallback, cancellation,
  resume, and corrupt suffix recovery.
- Property-test exact partitioning for 2-100 events and multiple semantic widths.
- Run focused tests, related workflow/context/incident tests, then the complete
  pytest suite before completion.
