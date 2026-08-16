# R1-D2 — Draft Mixed-Script Rejection Closure

## Final Gate

`R1_D2_ROOT_CAUSE_VERIFIED`

`PRIMARY_ROOT_CAUSE = draft.retry_finding_not_propagated`

`SECONDARY_CONTRIBUTORS = [draft.retry_scope_too_broad]`

`R1_D1_REGRESSION = NO`

Validator correctness: `correct`. Retry closure correctness: `incorrect`.
Local deterministic repair safe: `no`.

No production code, Prompt, route, provider/model binding, retry/fallback
limit, output budget, live data, consumed cohort, Final Review, Maintenance,
StoryState, Canon or Phase 1B behavior was changed. This task made zero model,
paid-provider and network calls.

## Parent evidence gate

The task began at exact HEAD
`b20897757f6eec15640ff020256e2163eb91848c`. Evidence Package
`e4f229b8416d40fdde94050a9ba08ee629aebcb42ca340dd6c9540e9a5ef2601`
and Evidence Manifest
`5b4e4ee101c979691f73d464df38dcd60e102a8b288539b26e31b60758eeb29d`
recomputed exactly. The 22-boundary ledger, first-divergence receipt, Signed
Approval and validate-only receipt remained manifest-bound. The actual ledger
state and committed consume receipt both prove the cohort is `consumed`.
Live parity remained exact at
`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.

## Finding 1 — Call 20 remains the first divergent node

### Evidence

Calls 20, 21 and 22 were the same Draft primary route, model alias and
Anthropic protocol. All returned `end_turn`; output tokens were well below the
requested 11,524-token limit. Transport accepted all three responses and
wrote exact transport checkpoints. The first local rejection appears only
after call 20 at event 70. No earlier event contains an authority-aware Draft
prose rejection.

| Call | Response SHA-256 | Receipt event | Rejects | Result |
|---:|---|---:|---:|---|
| 20 | `aa627570…7461f` | 70 | 3 | same-scope retry |
| 21 | `aa04c886…1cab5` | 75 | 1 | same-scope retry |
| 22 | `44b53f70…40f1e` | 80 | 2 | retry exhausted / terminal |

### Execution Path

`_draft_short_segment_task` → `_stage` → saved transport artifact →
`_draft_segment_findings` → `analyze_prose` → `_mixed_script_decision` →
`retry_same_scope`.

### Why It Matters

This excludes Provider transport, truncation, strict-tool, parser and Contract
Runtime output shape as the first failure mechanism.

### Confidence

High.

### Falsification

An earlier run event or artifact bound to a pre-20 boundary with the same
validator rejection would falsify the ordinal claim. The sealed DB has none.

### Fix Recommendation

None at this node; the validator result is correct under the declared policy.

## Finding 2 — R1-D1 correctly rejected all four unique terms

### Evidence

The three receipts bind revision 2, Draft authority hash `3cb371b…fde6`,
segment binding `ef14b0…2e18` and term-set hash `0a5eb7…dfa`. The term-set has
14 distinct approved terms. None of the four rejected token hashes occurs in
that inventory. All are NFKC identity, exact-case tokens; no stale-source,
wrong-revision, ambiguous connector, lookup miss or normalization drift was
observed. The same authority and term set were used for all retries.

Private semantic review classified every item, exactly once, as
`LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT`. Three first appear in Draft
call 20. The remaining two-letter shape appears earlier only in a local
Planning Markdown control label after boundary 1; it is absent from
`PlanningSegmentIR`, Planning Adaptation, Causal Chain, Execution Manifest and
the approved inventory, so that control label is not semantic authority for
its later narrative use. Exact token text remains outside Git.

### Execution Path

`_draft_prose_authority_context` projects the current `PlanningSegmentIR` and
matching `ShortExecutionManifest` fields →
`build_authority_approved_latin_term_set` → exact hash lookup in
`_mixed_script_decision`.

### Why It Matters

Expanding the allowlist would change R1-D1's closed-world policy and convert
new Draft terminology into authority. The failure is not a validator
regression.

### Confidence

High.

### Falsification

Any rejected hash appearing in the exact current term inventory, or a receipt
showing a stale/mismatched revision/source/binding, would falsify this finding.

### Fix Recommendation

Do not widen the allowlist and do not weaken the uniqueness rule.

## Finding 3 — Precise failure evidence is lost before retry

### Evidence

`analyze_prose` produces a decision per rejected occurrence and
`_record_draft_prose_validation_decisions` persists those decisions hash-only.
However `_draft_segment_findings` collapses every blocking prose finding to
one `prose_invalid` item with a generic message. `retry_same_scope` receives
that collapsed list, appends only the generic message to `exit_requirement`,
and recursively regenerates the entire owned event scope.

The retry receives neither rejected token nor mixed-script reason, has no
explicit approved/unapproved distinction, has no explicit allowlist, has no
instruction to remove the unapproved term while preserving other prose, and
does not use the rejected Draft as an edit baseline.

### Execution Path

Detailed local decisions → diagnostic DB event only; independently,
blocking findings → generic `prose_invalid` → whole-scope recursive Draft call.

### Why It Matters

The observed set evolution is exactly what this contract permits:

- 20→21: all 3 prior hashes disappear, but 1 new hash appears;
- 21→22: the distinct hash is retained and its occurrence count increases
  from 1 to 2.

The recovery topology can consume both retries without communicating the
condition it must satisfy.

### Confidence

High.

### Falsification

A captured retry input containing the exact rejected item/reason and an
actionable correction instruction would falsify the primary mechanism. Both
input hashes and source construction show only the generic finding.

### Fix Recommendation

In a separately approved implementation, preserve hash-only persistence but
carry a bounded, process-local precise Draft finding into the retry contract.
The first-attempt Prompt remains unchanged. Do not change route or retry
limits. Treat whole-scope regeneration as a secondary risk and require tests
that unrelated prose does not drift.

## Counterfactual matrix

| Variant | Calls 20/21/22 rejects | Interpretation |
|---|---:|---|
| Original validator + original authority | 3 / 1 / 2 | Exact reproduction |
| Add rejected token to authority, test-only | 0 / 0 / 0 | Passes only by policy relaxation |
| NFKC normalization only | 3 / 1 / 2 | Not a normalization bug |
| Change punctuation/adjacency only | 0 / 0 / 0 | Evades the surface candidate rule; grants no authority |
| Replace by Chinese placeholder | 0 / 0 / 0 | Changes meaning; unsafe as an automatic repair |
| Latest visible authority | 3 / 1 / 2 | Not stale authority |
| Retry-before/after authority | 3 / 1 / 2 | Authority did not drift across retries |

Therefore `LOCAL_DETERMINISTIC_REPAIR_UNSAFE`: the four terms are meaningful,
and neither deletion, alias replacement nor punctuation insertion has an
authority-backed semantic mapping.

## Excluded mechanisms

Evidence excludes provider truncation, max-token exhaustion, abnormal finish,
strict-tool, parser failure, Contract Runtime output shape, stale Candidate,
stale Draft bytes, budget exhaustion, fingerprint mismatch, route drift,
Prompt policy drift, live-data contamination, Final Review and Maintenance.
Final Review and Maintenance were never reached.

## Narrow future fix contract

- Suggested files: `src/novel_flywheel/prose_quality.py`,
  `src/novel_flywheel/workflows.py`, and focused tests.
- Prompt delta: retry-only bounded actionable finding; initial Prompt unchanged.
- Route delta: 0.
- Model-call limit delta: 0.
- Retry-count limit delta: 0.
- Expected actual call delta: 0 to -2 when recovery converges.
- A new single-use, newly approved real Canary is required after any fix.

The stable incident family is `draft.retry_finding_propagation`.

## Verification

The operator harness is
`tools/diagnostics/r1_d2_draft_mixed_script.py`; committed output is hash-only.
The characterization suite contains 28 tests, including exact private replay
for calls 20/21/22, authority inventory, first appearance, set diffs,
R1-D1 policy, stale/normalization/punctuation counterfactuals, retry contract,
zero invocation, privacy and live parity.

Focused: **28 passed**. Related: **89 passed, 1 xfailed**. Full suite:
**2819 passed, 3 skipped, 6 xfailed, 1 failed, 1 warning in 1648.05s**.
The sole failure is the known pre-existing
`tests/test_r0e_reports.py::test_live_db_and_formal_artifact_baseline_remains_r0_identical`;
new failures: **0**.

Post-suite live parity remains exact against the R1-D2 pre-run baseline:
live DB `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`,
formal story file
`101221aebf7b8f5270f5f7dc254281b64454cac89bc7d05cf5bbb8eb601ec745`,
Canon file
`5361f3729a06b702e0424e29236ac5baf8be4a778b44b7bb55e784ee448149fc`,
and the empty Candidate/Checkpoint/Saga manifest
`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e13b16b8967640b8da6b945`.
Production source remains unchanged; real Provider, paid model and network
call counts are all **0**.
