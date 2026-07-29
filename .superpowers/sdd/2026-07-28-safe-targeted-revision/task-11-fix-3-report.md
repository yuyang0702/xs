# Task 11 Fix Round 3 Report

## Scope

Closed the final two recovery-edge findings without changing non-revision diagnostics or internal model receipt files:

- mapped truncated or otherwise invalid Unicode snapshot manifests to the existing `ValueError("Snapshot manifest is invalid")` recovery contract;
- sanitized real `_stage` and `_stage_with_role_fallback` user-visible events for `short-revision` runs only;
- omitted configured-fallback `primary_error` and role-fallback `error` metadata for targeted revision;
- retained existing detailed fallback diagnostics for every other workflow.

No real provider or paid model API was called.

## Recovery Edge

`ProjectSnapshot.load` now catches `UnicodeError` alongside I/O and JSON parsing errors. A marker-less journal containing truncated bytes such as `b'["\xe4'` is therefore treated as interrupted snapshot creation: recovery returns false, discards the journal best-effort, and leaves all five repair artifacts byte-identical. The same hash-valid interrupted run can then resume to a stable waiting or completed state.

## Event Boundary

Tests exercise the real semantic short-revision `revision_plan` stage. An all-Chinese provider sentinel containing a private path and prompt cannot appear in the run error, any event message or metadata, or API-returned tool receipts. For configured fallback results, route and model identifiers remain visible while `primary_error` is omitted. The role-fallback wrapper similarly keeps `fallback_role` and omits the raw `error` field.

The saved internal stage receipt remains unchanged because it is not returned by the run-detail API. Existing short-story fallback tests continue to require and receive `primary_error`, proving the sanitization is workflow-scoped.

## RED And GREEN Evidence

- New focused RED: `3 failed, 1 passed, 60 deselected`; the three event paths leaked the sentinel, while outer recovery already swallowed `UnicodeDecodeError` through its `ValueError` ancestry.
- The manifest test was tightened to require `ProjectSnapshot.load` to normalize the error as `Snapshot manifest is invalid`, then verify recovery and stable resume.
- New focused GREEN: `4 passed, 60 deselected, 1 warning in 3.28s`.
- Complete revisions API plus storage: `68 passed, 1 warning in 36.71s`.
- Workflow stage-focused compatibility: `2 passed, 122 deselected in 1.42s`.
- Repository suite: `881 passed, 1 skipped, 1 warning in 507.92s`.

The skip is the existing Windows symbolic-link capability case. The warning is the existing Starlette `httpx` test-client deprecation warning.
