# R1-D0 Draft Prose Validation Root Cause Verification

## Outcome

The first divergent node is confirmed: the deterministic `MIXED_SCRIPT` rule
in `src/novel_flywheel/prose_quality.py:17` classifies an upstream-approved
Latin term adjacent to Chinese text as `mixed_script_corruption`. The Draft
leaf gate then discards that concrete code and evidence, exposes only
`prose_invalid`, performs two full owned-unit regenerations, and terminates
after the same false-positive class remains in the third output.

This result is not a production fix. R1-D0 changes no Runtime, Prompt, route,
retry, parser, adapter, validator, checkpoint, candidate or business code and
makes zero real or paid model calls.

Suggested incident family:
`draft.validator_false_positive / authority_approved_latin_term_misclassified`.

## Exact execution path

1. `WorkflowService._draft_short_in_segments` creates the Draft task.
2. `WorkflowService._draft_short_segment_task` renders the existing contract
   and calls `WorkflowService._stage`.
3. `_stage` returns the current Provider response as transport-complete. Calls
   20, 21 and 22 all have `finish_reason=end_turn`, closed sentence boundaries,
   and 6,957 / 6,830 / 6,084 effective Han characters inside the configured
   2,700–8,700 range.
4. `_draft_short_segment_task` calls `_draft_segment_findings` on that exact
   returned object.
5. `_draft_segment_findings` calls `analyze_prose`; `MIXED_SCRIPT.finditer`
   emits `mixed_script_corruption` 6 / 7 / 1 times.
6. `_draft_segment_findings` collapses every blocking prose-quality finding
   into one `prose_invalid` item and removes the concrete code/evidence.
7. `retry_same_scope` recursively regenerates the entire owned Draft unit.
   Calls 20→21 retain zero exact paragraphs; calls 21→22 retain three.
8. On the third rejection, `retry_same_scope` raises `ValueError`. The outer
   SafeFailure becomes `unknown / unclassified.8bff54965de2f818`.

The first-person invariant check and Draft semantic reviewer are after the
leaf gate and were never reached. No Draft semantic receipt, segment
checkpoint, candidate, `draft.md`, or protected Best Candidate exists.

## Validator contract map

| Layer | Caller | Callee | State read | State write | Incident result |
|---|---|---|---|---|---|
| Draft orchestration | `_draft_short_in_segments` | `_draft_short_segment_task` | execution manifest, beat/event scope, prior parts | task-local node sinks | entered |
| Model boundary | `_draft_short_segment_task` | `_stage` | StoryState revision/hash, contract, Prompt inputs, route receipt | stage output and transport observation | complete |
| Local leaf gate | `_draft_short_segment_task` | `_draft_segment_findings` | exact returned Draft, target range, prior prose, location catalog | local findings only | rejected |
| Prose analyzer | `_draft_segment_findings` | `analyze_prose` | current Draft text only | finding list | false positive |
| Mixed-script rule | `analyze_prose` | `MIXED_SCRIPT.finditer` | adjacent Unicode code-point shape | `mixed_script_corruption` | first divergence |
| Retry | leaf gate | `retry_same_scope` | collapsed issue, existing contract, retry_count | warning event, recursively changed exit requirement | exhausted |
| Semantic acceptance | `accept_node` | `first_person_prose_issues`, `_verify_draft_semantic_node` | accepted Draft and contract | semantic receipt, accepted node | not reached |
| Promotion/resume | short workflow | checkpoint/candidate writers | legal accepted Draft | checkpoint/candidate/formal draft | not reached |

The analyzer does not read the execution Manifest, authority vocabulary,
semantic receipts or an allow-list. The final blocking token appears 83 times
in 16 upstream planning/manifest derivative artifacts. A sanitized minimal
pair proves that a known corrupted mixed-script name and an approved term such
as `SignalKey` receive the same finding. Adding quotation punctuation around
the unchanged term removes the finding. The decision therefore depends on
surface adjacency, not authority or semantics.

## Scope retry closure

The current contract defines the whole ownership unit as retry scope. It keeps
authority hash, task identity, target length, event/beat ids, execution
manifest hash, entry state and narrative fields stable. It changes the stage
suffix and appends the generic collapsed issue message to `exit_requirement`.

It does not bind a formal Issue Receipt, previous Draft hash, validator
version, allowed edit span or immutable prose region. Therefore the observed
whole rewrites are broad but not out of bounds under the current contract.
The target count changes 6→7→1: the final retry partially reduces, but does not
eliminate, the current blocker. No new deterministic blocker is observed.
Whether narrative semantics changed is unknown because semantic validation
was never reached.

## Best Candidate and recovery containment

Call 22 is only the diagnostically least-blocked output. It is not a formal
Candidate and cannot be promoted or resumed as Draft. The last legal artifact
is the upstream Review output with normalized SHA-256
`6b3cc15f4bb54a2c70ff03c7f5c4302af177aee2efb239e7478a596f6da7436b`.
The last observed checkpoint identity is
`4ca339c5a53e9b26de40be728b927f508f15b778fbbbc58b9a6282e7f8fada13`,
but its execution binding is `unverifiable_legacy`.

`_short_checkpoint_manuscript` accepts only a complete `draft.md` or a
quality-protected `best-candidate.md`; stage-output filenames are not legal
resume manuscripts. Existing upstream planning/review authority is
recoverable, but no legal Draft is. Treating call 22 as contained would change
acceptance and checkpoint policy and is outside R1-D0.

## Hypothesis disposition

| Hypothesis | Disposition | Confidence |
|---|---|---|
| H1 truncation | contradicted | High |
| H2 retry left its current scope | contradicted under the current whole-unit contract | High |
| H3 retry did not remove target issue | supported | High |
| H4 fixing A introduced unchecked blocking B | not supported; semantic B remains unknown | Medium |
| H5 validator false positive / over-strict rule | confirmed | High |
| H6 stale Draft/Manifest/Receipt was validated | contradicted as root cause | High |
| H7 candidate selector defect | contradicted; selector not reached | High |
| H8 recovery should contain least-blocked output | unresolved policy question | Medium |
| H9 output-budget loss caused first divergence | contradicted | High |
| H10 random model quality only | contradicted | High |

## Exact offline replay

An isolated database copy, isolated project copy, replay-only run namespace
and deterministic fake gateway returned the exact historical raw outputs for
calls 20–22. The current real `_draft_short_in_segments`,
`_draft_short_segment_task`, `_stage`, leaf analyzer and recursive retry path
made exactly three fake Draft boundaries and reproduced the same direct
`ValueError`. The exception has no chained cause or context. The workflow
attempt state is `irrecoverable / automatic_recovery_exhausted`.

The reconstructed environment did not reproduce the historical Prompt hashes,
so this report does not claim exact Prompt replay parity. The causal replay is
exact at the historical-output-to-current-validator boundary. Git parity is
used separately to prove R1-D0 did not modify Prompt assembly.

## Future regression plan — not implemented as a fix

1. Add a deterministic authority-approved Latin-term case that passes while
   the existing genuine corruption case still fails.
2. Add boundary cases for CJK/Latin adjacency, punctuation, identifiers,
   acronyms, Latin-only paragraphs and malformed mixed-script names.
3. Inventory every caller of `analyze_prose` before changing the shared rule;
   assert Draft, review and maintenance siblings retain intended behavior.
4. Preserve the concrete analyzer issue code, validator version, Draft hash
   and evidence hash through the leaf result and scope-retry receipt.
5. Replay the exact three historical outputs: the corrected leaf should no
   longer terminal on the approved term, while unrelated blockers remain.
6. With a deterministic fake semantic reviewer, prove the accepted Draft next
   reaches first-person and semantic validation rather than skipping them.
7. Prove an accepted Draft writes the ordinary segment checkpoint, Candidate
   and resume binding; do not promote a locally rejected stage output.
8. Assert Provider/Prompt/route/retry counts are unchanged and no additional
   model boundary is introduced.
9. Re-run all prose-quality and Short workflow regression suites, then the
   full repository suite with live artifact parity.

## Gate

`R1_D0_DEVELOPMENT_GO`

The gate is limited to a future narrow validator/diagnostic fix. Evidence is
sufficient because the first divergent code path is unique, deterministic,
reproduced with exact historical outputs, and covered by a sanitized failing
oracle. A future change must remain limited to the Draft prose-quality rule and
its evidence propagation/tests; it must not change Prompt, route, retry count,
model selection, Contract Runtime, checkpoint policy or Recovery Policy.

R1-D0 stops here. No implementation fix or real Canary is authorized.
