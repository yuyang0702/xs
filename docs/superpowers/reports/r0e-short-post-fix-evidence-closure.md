# R0E — Short Post-Fix Evidence Closure & Controlled Exposure

## Result

R0E evidence work is complete and stops here. Production source and behavior are
unchanged. Real-provider canary remains **BLOCKED_BY_FINGERPRINT**. No historical
residual family receives `DEVELOPMENT_GO`, and no global Runtime Development GO
is emitted.

- Branch: `r0e/short-post-fix-evidence-closure-20260814`.
- Parent: `5a152b097732447d4a5e1db2f9ef0215815bcb91`.
- R0E commits before this report: `d8a5f7f`, `84fa5dd`, `9677584`.
- `src/novel_flywheel` diff from parent: none.
- Phase 1B flags: environment false, project false.
- Paid LLM calls: 0.

## 1. R0 parent evidence seal

`tests/fixtures/reliability/r0e/r0-parent-evidence-seal-v1.json` binds the R0
HEAD, all eight parent reports/spec hashes, 123 historical incidents, 44
residual families, 97 residual incidents, and the pre-R0E focused baseline of
31 passes. The seal test remained green after all R0E changes.

## 2. Residual Prioritization Matrix

`r0e-residual-prioritization-matrix.json` contains all 44 residual families and
97 incidents with historical count, current short reachability, evidence class,
executable oracle, Runtime boundary, terminal risk, priority/reason, expected
policy outcome, actual outcome, policy source, policy-violation status, and gate.

Evidence remains C for 25 families and D for 19. R0E did not create an exact or
incident-bound structural replay for a residual historical row. Gates are:

- `DEVELOPMENT_NO_GO`: 31 families;
- `NOT_CURRENTLY_REACHABLE`: 10 families;
- `NEEDS_PRODUCTION_EXPOSURE`: 3 provider families;
- historical `DEVELOPMENT_GO`: 0.

Every historical `policy_violation` remains `null` when the incident cannot be
executed against its exact contract. Credentials, connection, route rejection,
capacity, and route exhaustion are not called defects merely because a
controlled failure was injected.

## 3–4. Maintenance coverage and paired controls

`r0e-maintenance-recovery-coverage-matrix.json` records 16 current-workflow and
paired-control cases: eight variants on normal and window paths. All current
cases enter `WorkflowService.run_short` and the real Maintenance boundary; only
the paid network boundary is deterministic.

| Result | Cases | Evidence |
| --- | ---: | --- |
| `BYPASS_CAUSAL` | 4 | malformed JSON and provider-boundary truncation on normal/window terminate after post-stage conversion; the same payload under Contract Runtime retries and crosses the same domain merge |
| `NO_DIFFERENTIAL_EFFECT` | 12 | fenced, missing field, wrong container, version mismatch, domain-invalid, and double-route exhaustion do not show a worse bypass outcome in this fixture |
| `BYPASS_CORRELATED` | 0 | none |
| `EVIDENCE_GAP` | 0 | none for the tested representations |

Provider truncation is injected with partial output, `finish_reason=max_tokens`,
output-token metadata, and provider-completeness metadata. The current path
records the output as independently complete because it is non-empty, then
terminates with `ArtifactConversionError`; causal ordering is therefore
`TRUNCATED_OUTPUT → PROTOCOL_INVALID_AS_CONSEQUENCE`. Primary/fallback double
failure terminates in both paths and is not attributed to the bypass.

These are non-historical mechanism probes. They do not change the 123-row
corpus, residual recovery rate, or a historical evidence class. Gate:
`MECHANISM_FIX_CANDIDATE`.

## 5–6. Repair re-entry and Best Candidate containment

Static AST evidence confirms:

- short planning local/capacity/adaptation repairs and short-revision semantic
  group Repair supply `execution_spec`;
- polish semantic Repair and Maintenance normal/window repairs do not uniformly
  re-enter the same Contract Runtime.

Seven provider-boundary probes cover malformed output, wrapper output,
domain-invalid output, truncation, primary/fallback exhaustion, repair-A-break-B,
and cleanup secondary exception. In all seven:

- prior best Candidate bytes/hash remain unchanged;
- failed Repair never overwrites the best Candidate;
- quality checkpoint bytes remain unchanged;
- production resume selection returns `best-candidate.md` at the same hash.

The Repair-A-break-B case is rejected by the locked-fact check, then a second
candidate is semantically revalidated before acceptance. This is controlled
containment evidence, not proof that every semantic dimension has a validator.

## 7. Generic root-cause masking

A deterministic cleanup-boundary injection reproduces this chain:

`ModelRoutesExhaustedError → TargetedGroupError →
polish_semantic_repair_unavailable event append → OSError`.

The outer exception is `OSError`; the Repair failure remains only in the
exception chain. Root-cause preservation is false. The protected Candidate and
checkpoint are nevertheless contained. Because no exact historical incident is
bound to this topology, the result is `MECHANISM_FIX_CANDIDATE`, not
`HISTORICAL_FAMILY_CONFIRMED`; historical `runtime.primary_error_masked` remains
`DEVELOPMENT_NO_GO`.

## 8–9. Residual conversion and six unclassified incidents

No residual family moved from C/D to A/B. The six primary-scope unclassified
rows retain their historical identity. Typed first failures support only
non-destructive candidate mappings:

- normal invalid planning output → candidate
  `parser.generated_artifact_shape`;
- output limit/truncation → candidate `model.output_truncated`;
- planning-adaptation capacity → candidate
  `model.context_capacity_preflight`.

All six remain `candidate_mapping_unverified`, evidence C,
`DEVELOPMENT_NO_GO`, because raw output binding is ambiguous and the terminal
attempt is not tied to one response/checkpoint lineage. See
`r0e-six-unclassified-follow-up.json`.

## 10. Runtime fingerprint availability

`r0e-runtime-fingerprint-availability.json` records:

- control-plane Git commit: available outside a run;
- run-bound Git commit/build ID: unavailable;
- global Contract Runtime and RecoveryPolicy versions: unavailable;
- incident catalog and current flags: derivable, but not frozen together with
  the exact executing source;
- fingerprint instrumentation: `NOT_IMPLEMENTED`;
- real-provider canary: `BLOCKED_BY_FINGERPRINT`.

A hash-only `RuntimeBuildFingerprintV1` shape is proposed but not implemented.
The workstation HEAD is not treated as proof of a future run's source.

## 11. Controlled Production Exposure Plan

`r0e-controlled-production-exposure-plan.md` defines isolated project/DB/run
namespace, seven workload strata, frozen route/budget/prompt/fingerprint
evidence, token/currency formulas, stop conditions, and conservative reporting.
No provider/model is selected and no call is made.

For zero failures at one-sided 95% confidence:

- 59 runs: upper bound 4.95%, estimated 861 calls at the R0 average;
- 99 runs: upper bound 2.98%, estimated 1,444 calls;
- 299 runs: upper bound 1.00%, estimated 4,359 calls.

Without proved production weights, this is only a canary-mixture terminal-rate
bound, never a production terminal-rate bound.

## 12. Per-family Development Gate

There is no global Runtime gate. The only development-relevant results are the
two non-historical mechanism candidates:

1. Maintenance malformed/truncated response recovery differs when conversion is
   inside Contract Runtime.
2. Repair cleanup event failure can mask the primary typed failure.

Neither is authorized for implementation by R0E. All historical family gates
remain as listed in the prioritization matrix.

## 13–14. Live parity and paid calls

Before and after the full suite:

- live `data/app.db` SHA-256:
  `5deb7bdf811c90366ee1342de108c53355cea1c39aff72670bacd99cd5ffab87`;
- formal story SHA-256:
  `101221ae2af393e514b2d73c921d97689611de3339e584b1b0ded819a940c745`;
- Canon SHA-256:
  `5361f3729dd191e987f2494cb7bac1ebf15d9a9837465208262e3ee3f24f49fc`;
- Candidate/Checkpoint/Saga counts: 0/0/0;
- StoryState/story-candidate/workflow-checkpoint rows: 6/11/917;
- all before/after manifests: identical;
- paid LLM calls: 0.

## 15. Tests

- Pre-R0E R0 focused baseline: `31 passed in 67.35s`.
- R0E + R0 focused: `72 passed in 126.59s`.
- Maintenance related: `15 passed`.
- Repair/checkpoint related: `70 passed` plus 16 selected workflow tests.
- Supervisor policy selected tests: `6 passed`.
- R0 pre-change full suite: `2367 passed, 1 skipped, 5 xfailed`.
- R0E final full suite: `2409 passed, 1 skipped, 5 xfailed` in 1147.92s.
- New failures: 0.

## 16. Next narrow candidate tasks

R0E recommends separate approval, in this order:

1. implement and verify fail-open, hash-only `RuntimeBuildFingerprintV1`; this is
   the hard precondition for any paid canary;
2. produce a narrow Maintenance Contract Runtime convergence plan for only the
   four `BYPASS_CAUSAL` malformed/truncation cases, preserving current domain,
   retry, fallback, Candidate, checkpoint, and promotion semantics;
3. produce a narrow root-cause-preservation plan for cleanup/reporting failures,
   with an exact SafeFailureEnvelope causal chain and no recovery-policy change.

Do not start R1, Phase 1C/1D, Phase 1B production cutover, real canary, or any
Maintenance/Repair behavior change from this report.

## Final gate

**R0E COMPLETE. HISTORICAL DEVELOPMENT NO-GO. REAL CANARY
BLOCKED_BY_FINGERPRINT.**
