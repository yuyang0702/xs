# Regression shield

## Baseline before change

Capture:

- current Git status and unrelated user changes;
- the production-shaped reproduction or current accepted behavior;
- focused test result before modification;
- exact authority hashes, state revisions, or output files when relevant;
- behaviors allowed to change and behaviors locked against change.

Do not hide a missing reproduction by immediately adding fallback behavior.

## Change sizing

Prefer one behavioral objective and one authoritative boundary per patch. Treat a change as oversized when it simultaneously alters multiple stages such as planning, generation, review, repair, recovery, and promotion, or when a central orchestrator absorbs unrelated helpers and policies.

For an oversized change:

1. extract a sequence of independently testable slices;
2. keep old behavior available until the replacement slice passes;
3. run focused tests after each slice;
4. stop opportunistic cleanup outside the accepted scope.

## Test ladder

Run tests in this order:

1. a failing regression reproduction;
2. direct unit tests for the changed boundary;
3. adjacent-boundary or API/workflow tests;
4. production-shaped recovery tests;
5. related test cluster;
6. complete `pytest -q` suite before restart or completion when required by project policy;
7. UI smoke verification when user-visible behavior changed.

Tests must prove the corrected artifact proceeds successfully through the next authoritative boundary. Rejection, safe stop, log emission, checkpoint retention, or rollback alone proves containment only.

## Mandatory failure families

Select applicable cases for every L2/L3 change:

- canonical and previously accepted variants;
- malformed, ambiguous, duplicate, wrapped, Unicode-width, or fenced model output;
- empty response, normal finish with incomplete content, output limit, timeout, and disconnected stream;
- primary route failure and configured fallback failure;
- stale candidate hash, stale StoryState, changed binding, changed authority, and concurrent run;
- cancellation, interruption during write, resume, partial checkpoint, and corrupt later segment;
- local segment success with adjacent-boundary or whole-story failure;
- later repair reintroducing an earlier schema or semantic defect;
- old project with missing new metadata;
- API success followed by UI refresh failure, and UI/API status disagreement;
- user-selected independent changes that conflict only after combination.

Use fake providers and deterministic fixtures. Do not make paid capability probes or production model calls.

## Monotonic acceptance

Accept the implementation only when:

- the target failure is resolved or the requested behavior is demonstrated;
- the stable hard-issue set strictly shrinks or reaches zero;
- no new hard issue appears;
- unaffected deterministic material remains unchanged;
- prose-quality floors and user-control boundaries do not regress;
- the corrected path crosses its next authoritative boundary;
- the prior accepted state remains recoverable.

Reject and restore the prior best state when A is fixed by breaking B.

## Incident conversion

For every newly discovered production failure, retain:

- root cause and affected boundary;
- minimal or production-shaped reproduction;
- regression fixture and test;
- why existing tests missed it;
- successful recovery path;
- prevention rule added to the appropriate contract.

The same incident family should not depend on human memory twice.

## Forward incident projection

For every L2/L3 source change, scan the complete historical incident catalog before acceptance. Do not search only for the current error string. Translate each applicable incident into its underlying mechanism, including context/input capacity, output truncation, transport interruption, parser ambiguity, semantic ownership granularity, stale authority, partial checkpoint, conflicting checkpoint, merge conflict, and narrative regression.

Project each applicable mechanism across every structurally similar call site and every later workflow boundary: initialization, planning, causal chain, execution manifest, drafting, split/merge, polish, targeted/manual revision, AI issue refresh, final review, and formal promotion. Each boundary must be either fixed and tested, tested not susceptible, or marked not applicable with concrete code evidence.

Record the scan in a version 1 JSON report containing:

- `historical_incident_families_checked`;
- `projected_failure_mechanisms`;
- `why_previous_tests_missed`;
- `sibling_boundaries` with `boundary`, `disposition`, and concrete `evidence`;
- `model_output_boundary_changed`;
- when true, `model_output_variants_tested` with at least six materially different valid realizations, `invalid_output_variants_tested` with at least two malformed or semantically invalid realizations, `transport_capacity_variants_tested` with at least two faults, and `invariant_test_paths` whose assertions do not depend on exact prose;
- when false, `model_output_not_applicable_evidence` with concrete code evidence;
- `production_shaped_tests`;
- `next_authoritative_boundary_tests`;
- `remaining_risks`.

The strict change gate rejects an L2/L3 source change without this evidence. A green idealized fake-provider test, a single canned model output, a new rejection, a retained checkpoint, or a clean local parser result cannot satisfy the report by itself.

## Non-deterministic model output

Model-generated prose and semi-structured receipts are open sets, not fixed fixtures. Test stable contracts instead of one expected article: ordered event ownership, actor-action-result binding, entry/exit state, viewpoint, hashes, exact evidence presence, issue identity, no duplicate ownership, and whole-story causality. Do not assert exact wording unless the wording itself is authoritative input.

For every changed generated-output boundary, cover at least six materially different valid realizations, at least two malformed/incomplete/contradictory realizations, and at least two capacity or transport faults. Include applicable duplicated, reordered, wrapped, verbose, terse, multilingual, and provider-envelope variants. Prefer deterministic parameterized, metamorphic, mutation, or property-based cases with recorded seeds over flaky live randomness. A variant matrix must prove that creative wording can change freely while invariants remain stable, and that semantically invalid output is repaired or rejected for the same reason regardless of surface form.
