# R1-D3 — Draft Retry Finding Propagation Narrow Fix

## Gate

`R1_D3_NARROW_FIX_READY`

The verified `draft.retry_finding_not_propagated` case is fixed. This is a closed-world `case_fixed` result, not a claim that whole-scope Draft regeneration is systemically safe.

## Production delta

Only `src/novel_flywheel/workflows.py` changed. The initial Draft request, R1-D1 validator, authority allowlist, route/model bindings, output budget, retry/fallback limits, Planning, Planning Adaptation, Causal Chain, Execution Manifest, Final Review behavior, Maintenance behavior, StoryState, Canon, Phase 1B, and `baml_src` are unchanged.

The sole behavior delta is that an already-triggered same-scope Draft retry receives a bounded `DraftRetryFindingV1` block for the current `reject_unapproved_mixed_script` decisions. The next Draft is validated from scratch; old findings are not accumulated.

## Actual call graph

```text
WorkflowService._draft_short_segment_task
  -> WorkflowService._stage(role=draft)
  -> WorkflowService._draft_segment_findings
  -> prose_quality.analyze_prose
  -> mixed_script_decisions
  -> build_draft_retry_findings
  -> retry_same_scope
  -> WorkflowService._draft_short_segment_task(retry_findings=current tuple)
  -> render_actionable_draft_validation_findings
  -> WorkflowService._stage(role=draft, existing retry)
  -> recompute findings from the new Draft
  -> accept_node
  -> WorkflowService._verify_draft_semantic_node
```

The finding is produced by the unchanged local validator, bound back to the current in-memory Draft with the same tokenizer and SHA-256, passed as an immutable tuple, rendered as canonical UTF-8 JSON inside an explicitly untrusted data block, and recomputed after every attempt.

## Finding contract

`DraftRetryFindingV1` contains schema/version, finding and validator reason codes, normalized item, occurrence count, authority status, validator policy hash, authority snapshot/reference hash, retry scope ID, and deterministic identity hash. Limits are 16 unique findings, 96 characters per item, 256 occurrences per identity, and 4,096 serialized UTF-8 bytes. Unprovable binding, control characters, ambiguity, or bound overflow fails closed.

## Identity changes

| Identity | Before | After | Result |
|---|---|---|---|
| Initial Draft Prompt | `24ff78bda316093b453844cd276a8105ed1e9a79839f168d944b28883d5befad` | same | byte-identical |
| Existing generic retry Prompt | `0cd3ce0e17294da0b4347e2d47f19c55005fb8d06f25b85ba76c4f9f3eef5128` | `c1cde435c0caf77ac98f05aae9f95385f1486250384ff914b8729949283d3171` | authorized retry-only delta |
| Prompt Policy Manifest | `05f452760954a20eea76825dd82b3e47c985e8d7b21af1329e635b1927478ca4` | `72282e5c12a101592d26d18d15a618afcd6b10688f4d79bac902c9337579d68c` | future Canary must rebind |
| Build Fingerprint | `3fab2deb66d00eb5ba33d3a98292a6ef65ed11cd1a416953388b772f317b2c3f` | `771f86c5c735fcc39cb499e9a87014b226ab20c60abf3e148393de1e4268a59a` | changed |
| Execution Config | `3e0ff5f5a05ef8f7a6569cc6ecb3d92b1feb1e502e7ab3c6d51ada024b2434eb` | same | semantic parity |
| Runtime Execution | `7cc2332f0141fb25518b9d56360d8d57949b8a4d7a2e32ba4189324b5e9ea575` | `d502521d328722226b6b7676c2eb8b89ef9daf6b911caf179a5b60a7084f1d80` | changed from Build |

Final Review and Maintenance definition hashes also changed because those definitions bind the complete `workflows.py` source bytes. Their implementation and acceptance behavior did not change.

## Retry, route, validator, and replay evidence

- Same-scope retry limit: `2 -> 2`; maximum Draft attempts: `3 -> 3`.
- Short Canary total-call hard upper bound: `48 -> 48`.
- Primary/fallback schedule, Provider/model binding, output budget, and first-terminal-stop: unchanged.
- `prose_quality.py`: no diff; R1-D1 source SHA-256 remains `b56475366aa7f64edc2f65f03ebf87dc76ed454751661efd0346631888a50789`.
- Case A: current finding reached retry, corrected Draft passed unchanged validator, and the fake workflow crossed semantic review.
- Case B: a model that ignored the finding still terminated after the same two retries.
- Case C: a newly introduced item replaced the old finding on the next retry; no stale accumulation.
- Case D: authority-approved Latin never entered the finding block and remained accepted.
- Sanitized unrelated paragraph hash and event order remained unchanged in the minimal fake correction. This does not prove natural model drift is impossible.

## Tests and parity

- Pre-fix characterization: failed at import because the new contract did not exist.
- Focused: `30 passed in 4.66s`.
- Focused plus successor baseline: `33 passed in 5.17s`.
- Related: `465 passed, 1 xfailed in 426.83s`.
- Canary identity recovery after clean implementation commit: `87 passed in 338.21s`.
- Full suite: `2828 passed, 24 skipped, 6 xfailed, 1 failed in 1454.41s`; new failures `0`.
- The sole failure is the pre-existing `tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical` assertion (`5deb...` historical expectation versus current unchanged `0fcc...`).
- Live DB, formal story, Canon, Candidate, Checkpoint, Saga, StoryState row count, Candidate row count, and Checkpoint row count exactly match the before snapshot.
- Real model calls `0`; network calls `0`; paid calls `0`; Credential lookups `0`; Provider clients created `0`.

## Residual and stop

`draft.retry_scope_too_broad` remains a characterization residual. R1-D3 requests minimal edits but does not add RepairContract enforcement or restructure the owned scope.

`REAL_SHORT_COMPLETION_CANARY = NOT_EXECUTED`

`NEW_SINGLE_USE_APPROVAL_REQUIRED = YES`

No Candidate, Signed Approval, Credential access, Provider client, network/model call, Short run, retry-scope redesign, Phase 1B, or Long workflow was started.
