# REAL ZERO-TO-FINAL SHORT V11 Receipt-Recovery Closure

## Scope

This change is limited to the existing campaign/run recovery boundary. It does
not create a campaign, reference, Short run, receipt, fragment checkpoint, or
Provider request. The pending artifact is a native candidate binding, not an
acceptance artifact.

## Implemented contract

- `WorkflowCoordinator.resume_short_receipt` is the public selector for the
  receipt-only operation.
- `prepare_short_receipt_resume` reconstructs the exact `segment-01/sub-1`
  contract from the existing planning IR, causal chain, execution manifest,
  StoryState, style authority, and the historical native exhaustion event.
- Candidate raw bytes and normalized prose SHA-256 are checked before and after
  semantic validation. Any drift fails closed.
- `ModelDispatchOperationScope` is bound before Runtime dispatch and permits
  only `review / draft_atomic_semantic_receipt`; Draft is outside the scope.
- `ModelDispatchBudgetExhaustedError` and other local admission errors are
  classified as local pre-dispatch rejection. They do not increment Provider
  counters, open a Provider route circuit, or become `normal_invalid_output`.
- A validated pending child is consumed by the same Short segment coordinator;
  it continues with child 2 and the parent semantic receipt without replaying
  child 1 Draft generation.
- `tools/canary/short_receipt_resume.py` is the actual launcher. Its default
  command is zero-dispatch preflight; execution requires an explicit positive
  dispatch bound.

## Current live binding evidence

- Campaign: `real-zero-to-final-short-campaign-20260907-v1`
- Run: `real-short-98ddfa210856ffd1`
- Candidate: `outputs/draft-part-01-sub-1.md`
- Raw bytes: 6,930; SHA-256 `a97940be84dfc6b941256394c26a60abaa6a794a6b398a7deb527441dbcdbc0b`
- Runtime prose SHA-256: `85f5d42556912f70bf8fbccda07aaf304fde543d8c9c425e37f0333d23f311f8`
- Pending state: `outputs/draft-pending-candidates/85f5d42556912f70bf8fbccda07aaf304fde543d8c9c425e37f0333d23f311f8.json`
- Next operation: `review / draft_atomic_semantic_receipt`
- Draft request count for the next operation: `0`
- Provider counter before and after preflight: `266/266`

## Validation

Focused validation passed:

```text
56 passed
```

This includes the adapter-boundary observer regression, operation-scope Draft
rejection, local budget rejection before observer/adapter, coordinator routing,
contract-runtime tests, context-policy tests, and the actual launcher-to-public
resume-entry harness.

The live campaign was only run through the zero-dispatch launcher preflight;
no Provider request was attempted and no accepted fragment/checkpoint was
claimed.
