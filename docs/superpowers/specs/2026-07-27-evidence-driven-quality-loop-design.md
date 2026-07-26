# Evidence-Driven Quality Loop Design

## Goal

Improve final manuscript quality by connecting five currently separate capabilities into one local-first evidence loop: full-reference extraction, market cohort baselines, project guidance, narrative ledgers, and issue-led revision verification.

## Product Decisions

- Extend the existing reference library, market service, project learning artifacts, manuscript analysis, and incremental final review. Do not create parallel authoritative stores.
- Preserve StoryState, Runtime-controlled formal writes, existing model roles and fallbacks, first full-manuscript final review, and conservative full-review fallback.
- Use deterministic rules and enabled LTP automatically. Reuse the existing `final_review` role only for important semantic uncertainty.
- Market baselines are advisory. A market deviation is never a blocking quality failure by itself.
- Preserve source text, project files, model bindings, run history, accepted artifacts, and user revisions during migration.

## 1. Complete Local Reference Extraction

Reference windows target 3,000-5,000 characters, prefer blank-line and paragraph boundaries, fall back to complete sentence boundaries for long paragraphs, and use a bounded character fallback only for punctuation-free text. Adjacent windows overlap without duplicating stored mechanisms.

Local extraction scans every window and records multiple located matches per mechanism family. Equivalent matches are folded into one candidate with all evidence locations, occurrence count, and normalized whole-document positions. The result reports window count, analyzed count, coverage ranges, coverage percentage, degraded ranges, and analyzer version.

The UI shows a compact summary first. Evidence is collapsed to a short excerpt and expands on demand. It never renders a whole manuscript as the default evidence block.

Rejected mechanisms remain recoverable in the rejected view. A rejected mechanism may be permanently deleted after explicit confirmation. Deletion removes its evidence, edges, and revisions. A mechanism with any project adoption cannot be deleted until the adoption is removed. Source text and other mechanisms are unaffected. Batch deletion accepts rejected, unadopted nodes only and reports skipped records.

## 2. Market Cohort Baselines

A cohort key contains platform, ranking name, unified category, and length type. Only references with confirmed ranking links contribute work-level prose evidence. Each work counts once per cohort even if it appears in multiple snapshots.

Baseline observations include sample count, date range, opening signals, causal-cycle count, mechanism prevalence, normalized position distributions, event density, turning-point distribution, and ending payoff signals. Claims use descriptive language only.

- Fewer than 5 works: insufficient sample; display observations but do not provide a baseline.
- 5-9 works: preliminary baseline.
- 10 or more works: advisory project baseline.

Unknown category or length remains explicit and is never silently mixed with a known cohort. User-confirmed length overrides inferred length.

## 3. Project Guidance Integration

Projects may select an advisory market cohort through the existing wizard and project metadata. Automatic recommendation uses the chosen platform, genre/category, and mode/length. The user can disable or replace it.

The active baseline becomes a versioned `market_baseline` learning artifact. Planning receives a compact advisory summary. Outline checks compare causal-chain positions and cycle counts without rejecting coherent deviations. Manuscript analysis reports local metrics against baseline ranges while retaining raw metrics and deterministic blocking rules.

Changing a cohort marks the prior artifact stale and never rewrites an outline or manuscript.

## 4. Narrative Ledger

Each analyzed manuscript produces a hash-bound narrative ledger containing questions, promises, setups, candidate payoffs, scene boundaries, and scene entry/exit state changes. Every item records source ranges, entities, confidence, source (`rules`, `ltp`, or `final_review`), and relationship status.

Rules identify explicit questions, repeated anchors, transition signals, and located answers. LTP supplies entities, actions, semantic roles, and event relations when enabled. High-confidence explicit relationships are accepted locally; uncertain relationships remain candidates. Important uncertainty involving the opening promise, reversal, climax, ending, locked facts, or principal-character state is included in the existing final-review evidence.

The ledger is evidence, not authority. StoryState remains authoritative. The workbench shows a compact timeline, unresolved items first, expandable evidence, analysis source, and current confidence.

## 5. Issue-Led Revision Closure

Every review issue receives a stable `issue_id`, source, severity, manuscript range, evidence, repair goal, and status. Revision tasks reference issue IDs. Structured polish diffs record which issues they attempted to solve and which ranges changed.

After revision, the complete local manuscript analysis verifies deterministic repair goals and rebuilds the narrative ledger. Incremental final review must reconcile every open prior issue as `resolved`, `unresolved`, or `uncertain`; omission never resolves an issue. New issues receive new IDs.

Changed, adjacent, entity-related, causal, setup/payoff, and state-related windows are selected automatically. Existing broad, structural, unreliable, or important semantic changes trigger the current full-review fallback. A failed or incomplete review preserves the best candidate and blocks formal commit.

## User Experience

- Reuse existing navigation. Add focused tabs or sections inside Reference Detail, Market Trends, Project Wizard, Workbench, and Quality Report.
- Show summary before detail: coverage and counts first, evidence on expansion.
- Use explicit states: locally confirmed, candidate, model-reviewed, stale, unresolved, and degraded.
- Keep primary actions singular per surface. Avoid long button rows and nested cards.
- Long lists use search/filter, pagination, batch selection where appropriate, and preserved scroll/selection state.
- All destructive actions identify the exact affected records and require confirmation.

## Failure And Rollback

- LTP failure falls back to rules, records degradation, and forces conservative final-review scope when semantic relations matter.
- Missing or insufficient market data disables baseline guidance without blocking creation or writing.
- Stale baseline, ledger, or analysis hashes cannot approve a candidate.
- Existing complete final-review behavior remains the fallback.
- Schema changes are additive and migrated idempotently.

## Acceptance Criteria

1. Single-line and blank-line TXT manuscripts receive sentence-safe complete window coverage.
2. Local extraction stores multiple located matches and folds equivalent mechanisms without losing evidence.
3. Reference UI reports coverage and keeps evidence compact by default.
4. Rejected, unadopted mechanisms can be deleted individually or in a batch; adopted nodes are protected.
5. Confirmed ranking-linked references form deduplicated cohorts with honest sample thresholds.
6. A selected market baseline reaches wizard guidance, planning context, outline checks, and manuscript analysis without becoming a blocker.
7. Manuscript analysis produces a hash-bound narrative ledger and scene state-change candidates using rules and optional LTP.
8. Important uncertain relationships are routed through the existing final review, not a new model role.
9. Stable issue IDs persist across revision rounds and every prior issue is explicitly reconciled.
10. Structural or uncertain revisions retain the tested complete-review fallback.
11. Existing projects, formal manuscripts, StoryState, learning decisions, credentials, model bindings, and run history remain intact.
12. Focused tests and the complete test suite pass without paid API calls.

## Implementation Status

Implemented on 2026-07-27. The five capabilities extend the existing learning, market, project, manuscript-analysis, revision, and final-review contracts. No model role, provider dependency, authoritative state store, or direct manuscript write path was added. Release verification and exact test count are recorded in the delivering commit/run output rather than hard-coded here.
