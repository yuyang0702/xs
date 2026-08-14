# Runtime Fingerprint V1 Operations

## Storage and privacy

Definitions are written under:

`<data_dir>/runtime/runtime-fingerprints-v1/`

The store has `source-manifests`, `definitions`, `builds`,
`execution-configs`, and `executions` subdirectories. Files are named by their
definition SHA-256 and are never placed below a project. They are not Prompt,
Memory, FTS, Candidate, Canon, StoryState, Checkpoint, Saga, Snapshot, Export,
migration, indexing, or publication inputs.

Every definition contains `schema`, `canonicalization_version`, `payload`, and
`definition_sha256`. Parent payloads contain typed child references. Verification
re-hashes stored children and parents; it does not import the current registry to
reconstruct historical definitions.

## Canonicalization and hash formula

- Version: `runtime-fingerprint-canonical-json-v1`.
- Encoding: UTF-8; JSON keys sorted; separators are `,` and `:`; null, boolean,
  integer, string, object, and array retain JSON types. Floats and unknown Python
  objects are rejected.
- Paths: root-relative POSIX form. Absolute paths, `..`, and symlinks are
  rejected. Text source is UTF-8 with LF normalization; binary content is raw.
- Excluded: timestamps, mtime, process/memory addresses, credentials, prompt or
  manuscript text, random IDs, and absolute project paths.
- Formula:

  `SHA256(ASCII(domain) || NUL || canonical_json_utf8(value))`

Definition domains include the schema. Build, execution-config, execution,
identifier, and preflight receipt hashes use separate fixed domains.

## Build modes

- `git_workspace`: build input, editable installed package, production source,
  Git commit/tree/dirty provenance, Python runtime, dependencies, registries,
  recovery policy, and incident catalog are observed.
- `packaged`: the wheel embeds build-input and expected installed-runtime
  manifests. Runtime byte-level verification reads only files actually present
  in the installed package; missing repository-only `pyproject.toml`, launcher,
  or BAML source is not treated as installed-package drift.
- `unknown`: missing/unreadable/invalid embedded evidence produces reason codes;
  ordinary workflows continue, while future canary eligibility is blocked.

Production source includes `src/novel_flywheel/**`, `baml_src/**`,
`pyproject.toml`, and `start-novel-console.cmd`. It excludes `.git`, `.venv`,
tests, docs, caches, `build`, `dist`, bytecode, and the generated embedded
manifest itself.

## Run binding semantics

Only `create_run`, successful `create_run_if_idle`, or the new-run branch of
`activate_supervised_run` can emit `origin`. Existing-run activation and worker
entry emit `executor`. All callbacks run after the database transaction has
committed and are fail-open.

`canonical_runtime_bindings` collapses exact duplicates by binding definition.
Different execution fingerprints for the same `(binding_kind, execution_epoch)`
produce `conflict`; last-write-wins is forbidden. A legacy run without origin
remains `unverifiable_legacy`, even when a current executor is known.

## Verification and damaged evidence

`verify_runtime_binding_sidecars` verifies the binding, execution, build,
execution config, and their stored child graphs. Missing, malformed, or tampered
definitions return `invalid` reason codes. They are coverage gaps; readers must
not invent an origin or causal edge.

`runtime_source_revalidation` compares actual current content manifests with the
process-captured build. It distinguishes build change, execution-config change,
source change after process start, and provenance-only change. It never relies
on mtime.

`canary_runtime_fingerprint_preflight_v1` is a pure function. It performs no I/O,
credential lookup, provider construction, network call, model call, or run
mutation. R0F does not connect it to a Provider and does not execute a canary.

## Rollback

Revert R0F-D, R0F-C, R0F-B, then R0F-A in reverse order. R0F-C alone removes all
production wiring. Sidecars are diagnostic and may be left in place; ordinary
runtime readers ignore them. No database migration or business artifact rollback
is required.
