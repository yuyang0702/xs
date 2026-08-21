# R1-PTR10 — Final Artifact Guard Recovery Validation Final Report

## Gate

`R1_PTR10_FINAL_ARTIFACT_GUARD_VALIDATED`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`PRODUCTION_FIX=ALREADY_IMPLEMENTED_PTR9`

## Repository and PTR9 baseline binding

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `7cdb7444902d0737f8cc9094992f7ef9bdb1e946`
- Parent: `962f0ad7ad42e629bcca309de4d43ce58a671682`
- Entry worktree: clean
- PTR6 manifest: exact, 6/6 entries
- PTR7 real-observation manifest: exact, 16/16 entries
- PTR8 manifest: exact, 7/7 entries
- PTR9 manifest: exact, 15/15 entries
- PTR9 implementation binding: exact, 9/9 entries
- PTR9 production source bytes: exact
- `baml_src/**` diff: 0

## Validation result

The sealed `REASONING_ONLY_MAX_TOKENS_GUARD_V1` behaves exactly at its declared finite boundary. When a complete, exact provider projection contains only known reasoning/thinking blocks, reports an output-limit finish, has zero provider-visible and normalized visible characters, and contains no text, tool, or unknown blocks, Runtime raises `REASONING_ONLY_FINAL_ARTIFACT_UNAVAILABLE` before strict-tool conversion, parser, JSON conversion, schema validation, or domain validation.

The typed failure persists a negative capability bound to provider, model, route fingerprint, contract identity, schema identity, and `final_artifact` execution mode. A matching second request is rejected before Provider dispatch. Contract Runtime records `model_call_delta=0` for the repeated fingerprint.

If the immutable configured schedule already contains a legal distinct route, Runtime selects it and the production-shaped `planning_semantic_v2` artifact crosses domain validation. If no legal distinct route remains, Runtime raises typed `FinalArtifactCapabilityExhaustedError`. It does not retry the failed fingerprint, broaden fallback, increase budget, or manufacture an alternate contract.

## Seven required cases

1. Reasoning-only plus `max_tokens`: passed; typed before parser/schema and remembered.
2. Normal text output: passed; guard not triggered.
3. Normal tool output: passed; guard not triggered.
4. Unknown block shape: passed; remains `UNKNOWN` and is not misclassified.
5. Negative capability persistence: passed; idempotent persistence and second-dispatch delta 0.
6. Existing alternate route: passed; distinct configured route selected and domain validation completed.
7. No alternate route: passed; same fingerprint skipped and typed fail-close raised.

Additional false-positive controls passed for reasoning-plus-text, reasoning-plus-tool, multiple text blocks, adapter projection loss, empty response, and a healthy primary route.

## Invariants and scope

PTR10 changed no production source. Prompt, Model, Route configuration, Retry, Budget, Validator, business contracts, Draft, Final Review, Maintenance, Canon, StoryState, READY authority, candidate selection, formal promotion, and SQLite schema remain unchanged. Retry count, fallback scope, and token budgets were not expanded.

The only PTR10 files are validation evidence under `docs/superpowers/reports/r1-ptr10/**`. No approval, Signed Approval, Confirmed Patch, Provider probe, Canary, or production fix was created or executed.

## Offline tests

- Focused Guard matrix: `16 passed` in 4.71 seconds.
- Related regression cluster: `163 passed`, 1 warning, in 33.39 seconds.
- Production-length matrix: `3 passed` at 13K, 20K, and 30K in 85.41 seconds.
- Offline business suite: `2651 passed, 39 skipped, 1 deselected, 6 xfailed`, 1 warning, in 1252.70 seconds.

The complete suite used the same sealed PTR9 exclusions: the old Canary real-probe module was not imported or executed, and the historical R0 live-database assertion was deselected because it binds an obsolete hash. Current authorized live parity was checked directly before and after validation.

## Privacy and live parity

The evidence contains hashes, shapes, counts, typed states, test names, and aggregate outcomes only. Raw Prompt, story, tool arguments, Provider content, reasoning content, credentials, authorization headers, and Provider request identifiers are absent.

The live database, formal manuscript manifest, Canon manifest, candidate/checkpoint/Saga manifests, and StoryState/candidate/checkpoint counts remained exact. No live authority-bearing state changed.

PTR10 recovery validation is complete at the sealed PTR9 finite guard boundary. It does not claim Provider-native reservation support or a universal solution for unknown Provider block topologies.
