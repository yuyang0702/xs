# R0F RuntimeBuildFingerprintV1 Readiness Report

## Outcome

R0F implements build/config identity and run lineage only. It does not execute a
real canary or authorize Phase 1B cutover. Both deployment-mode gates remain
NO-GO until a specific approved build/config and exact origin/executor binding
are supplied to the preflight verifier.

## Evidence summary

1. Build, execution config, execution, and run binding use separate versioned
   definitions. Build approval compares content identity; Git provenance remains
   independently diagnosable.
2. Stored child schemas are `RuntimeContractRegistryManifestV1`,
   `RuntimeAdapterManifestV1`, `RuntimeRecoveryPolicyManifestV1`,
   `RuntimeIncidentCatalogManifestV1`, `RuntimeFeatureFlagManifestV1`,
   `RuntimeRouteRoleBindingManifestV1`, `RuntimePythonManifestV1`,
   `RuntimeInstalledDependencyManifestV1`, `RuntimeBuildInputManifestV1`,
   `RuntimeInstalledRuntimeManifestV1`, `RuntimeProductionSourceManifestV1`,
   `RuntimeGitProvenanceV1`, and `RuntimeEmbeddedBuildManifestV1`.
3. A true Hatch wheel was built, extracted into a directory with no `.git`,
   `pyproject.toml`, or `baml_src`, and revalidated as
   `verified_packaged_manifest` from installed files plus embedded evidence.
4. Missing embedded evidence yields `unknown_runtime`; no identity is guessed.
5. New supervised and sibling-created runs receive origin evidence. Worker entry
   and resume receive executor evidence. Legacy resume never backfills origin.
6. Exact duplicate bindings canonicalize to one. Contradictory same-epoch
   bindings report conflict and block future eligibility.
7. Current source is re-hashed from content. A post-start source change makes the
   runtime non-exact; a commit/tree-only change is reported as
   `provenance_changed_only`.
8. Sidecar tamper is detected through stored child and parent re-hashing.
9. Credential lookup, provider resolve/client creation, network, and model-call
   counters are all zero in instrumentation tests.
10. Business run projection remains `queued → started → completed`; diagnostic
    events are excluded only by explicit event type. Protected Prompt, Model,
    Contract Runtime, CompletionSupervisor, workflow, repair/maintenance, and
    provider-registry source hashes remain equal to the accepted R0E baseline.

## Performance and storage

Measured on Windows/Python 3.12 with 30 direct queued-run observations:

- cold build capture: 1223.806 ms;
- second uncached build capture: 1073.860 ms;
- trace/binding disabled create p50/p95: 4.390 / 4.994 ms;
- binding enabled create p50/p95: 21.495 / 23.156 ms;
- enabled-minus-disabled p95: 18.162 ms;
- sidecar footprint after 30 bindings: 45 files, 187,994 bytes;
- binding write failures: 0/30; observed coverage gaps: 0.

The binding p95 is below the planned 25 ms target and callbacks occur after DB
commit. Cold process capture exceeds the planned 250 ms target; it is process
scoped, does not extend a run transaction, and remains an explicit operational
risk rather than being hidden. No asynchronous queue or service was introduced.

## Regression result

- pre-change full suite: 2409 passed, 1 skipped, 5 xfailed, 0 failed;
- post-change full suite: 2438 passed, 1 skipped, 5 xfailed, 0 failed;
- delta: 29 newly passing R0F tests, no new failure, skip, or xfail;
- focused/related suite: 223 passed before final full-suite execution;
- paid LLM calls: 0;
- Phase 1B environment and project flags: false.

The first post-change full-suite run found one stale R0E characterization that
still expected the fingerprint schema to be absent. Only that test-only evidence
was updated to `IMPLEMENTED_R0F` while keeping real canary
`BLOCKED_BY_APPROVAL_AND_EXACT_BINDING`; the complete suite was then rerun from
the start and passed.

Final clean-room review added a real editable-workspace mutation test. It exposed
that trimming the leading porcelain status space could misparse ` M path` as
`rc/...` and falsely report production source clean. The Git helper now removes
line endings only. The test performs an actual temporary Git commit, changes
production source bytes after process capture, re-collects, and proves source
change plus dirty status. The complete suite was rerun again after this
instrumentation-only correction and passed with the counts above.

## Gate status

### GIT_WORKSPACE_CANARY_READINESS — NO-GO

The verifier and Git evidence path are implemented and tested, but R0F has no
approved canary build/config pair and did not create an authorized canary run.
Eligibility therefore remains false by default. A future explicitly authorized
canary must provide approved hashes, clean/current byte revalidation, one exact
origin, a current exact executor, and valid sidecar graphs.

### PACKAGED_CANARY_READINESS — NO-GO

The build/extract/revalidate fixture passes, but the currently running deployment
is an editable Git workspace, not the wheel fixture, and no packaged build/config
has been approved. Git verification cannot authorize a packaged canary.

## Coverage gaps and residual risks

- No real Provider canary was executed, by scope.
- No approved build/config registry exists; R0F accepts approved hashes only as
  explicit preflight inputs and adds no database table.
- A double failure of sidecar storage and unavailable-event append is observable
  only as a missing binding coverage gap; ordinary business remains fail-open.
- Existing legacy runs without origin remain `unverifiable_legacy`.
- Cold process capture is slower than the planned target.
- Multi-process callbacks can lose diagnostics on SQLite lock failure; readers
  do not fabricate missing causality.

## Next-stage recommendation

Development of an explicitly authorized, fake-boundary canary launcher may use
the existing pure verifier. Do not duplicate its rules. Real canary execution,
Provider/model selection, R1, Phase 1B cutover, Phase 1C, and Phase 1D remain out
of scope and must be separately approved.
