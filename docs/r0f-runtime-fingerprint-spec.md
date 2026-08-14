# R0F Runtime Fingerprint Specification

R0F is evidence-only infrastructure. It may observe runtime identity and bind
that identity to run lifecycle events, but it must not change model, prompt,
route, retry, fallback, repair, maintenance, canonical, or artifact decisions.

## Required identity domains

- Build identity and execution-configuration identity are distinct.
- Canonical JSON is UTF-8, key-sorted, compact, deterministic, and domain
  separated before SHA-256.
- Git workspace, packaged runtime, and unknown runtime are explicit modes.
- Packaged identity separates build inputs from installed runtime files.
- Parent definitions reference content-addressed, sanitized child definitions.
  A reader must re-hash stored children and parents without importing current
  application registries.

## Binding semantics

- Only creation of a new run may emit `origin`; activation, retry, resume, and
  startup recovery may emit only `executor`.
- Missing legacy origin remains `unverifiable_legacy` with a null origin.
- Exact duplicate bindings collapse logically. Contradictory fingerprints for
  the same run, kind, and execution epoch are conflicts; last-write-wins is
  forbidden.
- Collection and event emission occur after business transactions and fail
  open. A trace failure never changes run state, exception, timeout, retry, or
  recovery behavior.

## Revalidation and canary boundary

- A process-captured workspace identity is historical observation, not proof
  that editable source remains unchanged. Preflight re-hashes actual bytes.
- Source changes after process start make runtime status non-exact and block a
  future canary.
- `CanaryRuntimeFingerprintPreflightV1` is a side-effect-free production pure
  function. R0F does not connect it to a provider boundary or execute a real
  canary.
- Git-workspace and packaged-runtime readiness are separate, default-NO-GO
  gates. One deployment mode cannot authorize the other.

## Side effects and isolation

- Fingerprinting reads descriptors already present in configuration and the
  database. It must not access credentials, instantiate provider clients,
  perform health/network calls, or invoke a model.
- Sidecars live under the application data directory's dedicated
  `runtime/runtime-fingerprints-v1` tree, outside project artifacts and all
  Prompt, Memory, FTS, Candidate, Canon, StoryState, Checkpoint, Saga, Snapshot,
  Export, migration, and indexing inputs.
- Stored payloads contain no prompt, manuscript, complete business object,
  credential, absolute project path, random UUID, timestamp, or memory address.

## Change classification

Comparison reports distinguish build changes, execution-config changes,
provenance-only changes, and unknown comparisons. Any unapproved build/config
change blocks a future canary; ordinary workflows remain fail-open.
