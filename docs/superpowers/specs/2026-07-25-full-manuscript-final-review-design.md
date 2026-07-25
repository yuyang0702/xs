# Full-Manuscript Final Review Design

## Goal

Replace sampled final review with an evidence-based full-manuscript audit that cannot silently lose prior issues or fall back to a planning model.

## Review Flow

1. Split the manuscript into 4,000-6,000 character windows with small paragraph-aligned overlap.
2. Extract an ordered story map from every window: events, character state and knowledge, timeline, promises, setups and payoffs.
3. Audit every window with the compact global story map, adjacent summaries and the initial issue ledger.
4. Run a cross-window consistency audit over the merged evidence.
5. Ask the configured `final_review` role to adjudicate the evidence. Its configured fallback is allowed; the `planning` role is not.
6. Reconcile every initial issue as `resolved`, `partially_resolved`, `unresolved`, or `not_found`, with evidence.
7. Apply deterministic local gates before accepting the model decision.

## Local Gates

- A major unresolved logic or continuity issue blocks approval and caps the score at 74.
- Multiple unresolved moderate issues cap the score at 79.
- Missing reconciliation entries, empty evidence, implausibly short review output, or incomplete window coverage invalidate approval.
- If final-review providers fail, preserve the best candidate and report `final_review_incomplete`; never manufacture a score.

## Reporting

`quality-report.json` records manuscript coverage, window count, issue reconciliation counts, blocking issues, score caps, and terminal-review completeness. Existing manuscript and polish behavior remain unchanged, including the 8192 output budget.

## Compatibility

No new dependency or provider role is introduced. Existing quality report fields remain available. The new evidence fields are additive, and formal manuscript files are written only after a valid terminal review.
