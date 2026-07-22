# Adaptive Editorial Flywheel Design

## Goal

Upgrade the existing review-polish-final-review workflow into a cost-aware editorial flywheel. Commercial appeal and paid conversion are the primary quality target, while story integrity, emotional impact, natural prose, continuity, and compliance remain mandatory.

The system must improve quality without sending every chapter through every model or repeatedly loading the full manuscript.

## Quality Model

Every editorial review returns three independent scores from 0 to 100:

- `commercial`: hook strength, reader promise, payoff density, chapter-end pull, and paid-reading motivation.
- `story`: causality, character motivation, emotional escalation, continuity, and payoff.
- `prose`: readability, character voice, scene specificity, dialogue, repetition, and AI-like phrasing.

The application computes the overall score locally:

```text
overall = commercial * 0.45 + story * 0.35 + prose * 0.20
```

A manuscript passes only when:

- overall score is at least 80;
- commercial is at least 75;
- story is at least 70;
- prose is at least 65;
- `hard_fail` is false.

Compliance and canon violations are hard failures. They do not add quality points.

For compatibility, legacy reviews containing only `score` are accepted by applying that score to all three dimensions.

## Adaptive Routing

### Standard route

Ordinary long-form chapters use:

1. planning;
2. drafting;
3. combined commercial, story, continuity, and compliance review;
4. targeted polish using the structured findings;
5. independent final review;
6. at most one corrective polish and final-review retry;
7. maintenance and archive.

### Enhanced route

The enhanced route applies to:

- all short stories;
- chapters 1 through 3;
- volume endings;
- chapter goals containing markers such as opening, paid point, climax, ending, key reveal, or volume ending;
- drafts whose first review requests a rewrite or has a commercial score below 60.

Enhanced runs add a target-reader simulation before polish. The reader model receives a bounded sample rather than the full long manuscript. Enhanced runs allow at most two corrective polish cycles.

No new provider role is required. The configured `review` model performs both editorial review and reader simulation with different prompts. The configured `final_review` model remains the chief editor.

## Reader Sampling

Short stories are sampled from four commercial checkpoints:

- opening;
- expected paid cutoff area;
- climax;
- ending.

The combined sample is capped so the reader simulation does not reload the entire story. Long chapters use a smaller opening, middle, and ending sample. Sample labels make omissions explicit so the model does not mistake the excerpt for the complete manuscript.

## Revision Policy

Review findings must identify category, severity, evidence, and action. Polish prompts instruct the model to preserve accepted plot facts and revise only the passages needed to resolve findings.

If the first review requests a full rewrite or commercial score is below 60, the route is escalated. The existing draft remains evidence; automatic repeated full redrafting is not allowed. Corrective cycles operate on the polished manuscript and stop at the route limit.

If the final quality gate still fails, the run fails without overwriting formal manuscript files. All draft outputs and quality reports remain available for diagnosis and a later retry.

## Token Controls

- Planning and interview-like reasoning receive enough output budget for reasoning models.
- Review, reader simulation, final review, and maintenance use bounded output budgets because they return structured data.
- Draft and polish retain larger output budgets needed for prose.
- Retrieved long-form context remains project-scoped and relevance-based.
- Reader simulations use local excerpts.
- Existing run outputs, receipts, and memory are reused; no model is called merely to recreate cached artifacts.
- Retry limits are fixed in code: one standard correction and two enhanced corrections.

## Persistence And Observability

Each run writes `outputs/quality-report.json` containing:

- route and escalation reasons;
- editorial review;
- optional reader simulation;
- every final review attempt;
- locally computed scores and pass/fail reasons;
- final status.

Run events include route selection, quality assessment, escalation, revision attempts, and final gate status. The existing console log displays these events without requiring a new model configuration screen.

## Error Handling

- Malformed review JSON fails the current stage and preserves its raw archived output.
- Missing dimension scores use the legacy compatibility rule.
- Invalid scores or issue shapes are rejected before they influence routing.
- Cancellation continues to restore snapshots when formal files have not been committed.
- A failed quality gate never writes a new formal manuscript.

## Testing

Tests cover:

- weighted score calculation and dimension gates;
- legacy review compatibility;
- standard versus enhanced route selection;
- reader sample size and checkpoint labels;
- standard and enhanced retry limits;
- quality report persistence and run events;
- existing cancellation, snapshots, memory maintenance, and volume audits.

