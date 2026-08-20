# R1-PTR9 — Final Artifact Guard Implementation Final Report

## Gate

`R1_PTR9_FINAL_ARTIFACT_GUARD_IMPLEMENTED`

`REAL_PROVIDER_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`

## Repository binding

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `d68b0f7c5566fca9cb2898e14bfdda06f4480a6b`
- Risk: L3
- Strict change gate: exact, zero warnings, zero blockers
- Project-scope gate: exact
- Entry state: the pre-existing untracked `docs/superpowers/reports/r1-ptr8/**` evidence was preserved and not rewritten.

## Result

The Runtime now detects the finite, provider-neutral failure shape required by PTR9:

- known reasoning/thinking block count is greater than zero;
- known final text and tool-call counts are zero;
- provider-visible and adapter-normalized visible characters are zero;
- finish reason is an output-limit terminal form;
- the adapter projection is exact and transport is complete;
- unknown block count is zero; and
- every observed content block is a known reasoning block.

The exact shape raises `ReasoningOnlyFinalArtifactUnavailableError` before strict-tool conversion, parser execution, JSON conversion, schema validation, or domain validation. It therefore cannot degrade into parser/schema failure or the generic `ContractOutputLimitExhaustedError` path.

This is a finite case fix, not a claim that all future provider block topologies are solved. Unknown or projection-mismatched shapes are deliberately not inferred.

## Exact owner files and functions

- `src/novel_flywheel/provider_output.py::provider_output_shape_from_response` centrally projects retained raw state from the three production adapter families into `ProviderOutputShapeV1` without retaining raw content.
- `src/novel_flywheel/models.py::_reasoning_only_final_artifact_unavailable` owns the exact detector.
- `src/novel_flywheel/models.py::ModelGateway._complete_resolved` owns preflight negative-capability enforcement, safe receipt construction, qualification recording, and the typed pre-parser failure.
- `src/novel_flywheel/db.py::Database.save_structured_route_outcome` persists the exact severe `reasoning_only_output_limit` outcome in the existing qualification table; no schema migration was added.
- `src/novel_flywheel/contract_runtime.py::execute_contract_runtime` owns same-fingerprint suppression, existing-distinct-route continuation, and typed exhaustion.

## Recovery decision

PTR9 implements a narrow combination of A and B:

1. Exclude the exact failed fingerprint from the remainder of the immutable execution schedule.
2. If an already-configured distinct route exists, continue to that route without changing route identity, route order, retry count, fallback count, or budget.
3. If no distinct route succeeds, raise `FinalArtifactCapabilityExhaustedError` and fail closed.

The alternate-contract option was rejected because it would change the business contract. Same-route controlled retry was rejected because PTR7 showed the provider controls were ignored and repeating the fingerprint would amplify a known terminal failure.

## Capability memory

Negative memory is bound to:

- provider id;
- model id;
- route fingerprint;
- contract name;
- schema SHA-256; and
- execution mode `final_artifact`.

The stored typed reason is `reasoning_only_max_tokens`, with state `unsupported_or_unreliable`. A later matching Gateway request is rejected before provider dispatch; a duplicate route entry in the current Contract Runtime schedule records `model_call_delta=0` and is skipped.

## Invariants preserved

- Prompt unchanged.
- Provider and model identities unchanged.
- Route identities and configured ordering unchanged.
- Retry/fallback limits unchanged and not expanded.
- Output budget and reasoning settings unchanged.
- Business contracts and validators unchanged.
- Normal text, normal tool output, reasoning-plus-text, reasoning-plus-tool, and multiple-text output remain accepted by their prior paths.
- Draft, Final Review, Maintenance, Canon, StoryState, READY authority, candidate selection, and formal manuscript promotion are unchanged.
- No new SQLite schema or migration.

## Files changed

Production/runtime:

- `src/novel_flywheel/provider_output.py`
- `src/novel_flywheel/domain/models.py`
- `src/novel_flywheel/models.py`
- `src/novel_flywheel/db.py`
- `src/novel_flywheel/contract_runtime.py`
- `src/novel_flywheel/production_incidents.py`

Tests and protected-source successor evidence:

- `tests/test_final_artifact_guard.py`
- `tests/providers/test_diagnostic_tool_shapes.py`
- `tests/test_r0f_baseline.py`
- `tests/test_runtime_fingerprint.py`
- `tests/fixtures/reliability/r0f/r1-ptr9-authorized-protected-source-successor-v1.json`

Documentation and PTR9 validation evidence:

- `docs/maintenance.md`
- `docs/superpowers/specs/2026-08-12-structured-output-runtime-v3-design.md`
- `docs/superpowers/reports/r1-ptr9/**`

Production source diff is limited to the six runtime files listed above. There is no `baml_src/**` diff and no Prompt, model configuration, route configuration, validator, StoryState, Canon, or READY authority diff.

## Offline validation

- Related regression cluster: `163 passed`, 1 warning.
- Production-length offline matrix: `3 passed` at 13K, 20K, and 30K target sizes.
- Offline business suite: `2651 passed, 39 skipped, 1 deselected, 6 xfailed`, 1 warning, in 1267.53 seconds.
- Strict L3 change gate: passed with zero warnings and zero blockers.
- Project-scope gate: passed.

The one deselected assertion binds the live database to an obsolete R0 hash. PTR9 entry and final snapshots instead bind the same current authorized hash, `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`.

The unfiltered suite also encounters a pre-existing Canary import-closure failure in the old real Provider Reasoning Capability Probe module. PTR9 neither modified nor executed Canary, as required.

## Privacy and live parity

Receipts retain only controlled identities, hashes, shapes, counts, and typed status. Raw Prompt, story, tool arguments, Provider content, reasoning content, headers, request id, and credentials are absent. Synthetic tests use only reserved `.invalid` endpoints and non-secret markers.

The live database SHA-256, formal story manifest, Canon manifest, and StoryState/candidate/checkpoint counts are identical to the PTR9 entry snapshot. No live authority-bearing state changed.

## External action closure

- Credential access: 0
- Provider client calls: 0
- Network calls: 0
- Model calls: 0
- Paid calls: 0
- Provider probe: not executed
- Full Short Canary: not executed
- Signed Approval: not created

Implementation and offline production-change validation are complete. A future real Provider or Full Short execution requires a separate fresh approval and is outside PTR9.
