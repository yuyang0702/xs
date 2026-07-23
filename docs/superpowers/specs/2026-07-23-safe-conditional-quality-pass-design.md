# Safe Conditional Quality Pass Design

## Goal

Stop the editorial flywheel from rejecting every commercially usable manuscript or degrading a near-publishable best candidate through unnecessary full-manuscript revisions.

## Quality Decisions

The final editorial gate has three outcomes:

- `passed`: weighted score is at least 80 and all existing safety checks pass.
- `conditional_pass`: weighted score is 75 through 79.99 and every safety condition below passes.
- `failed`: score is below 75 or any safety condition fails.

A conditional pass requires all of the following:

- commercial score at least 75;
- story score at least 70;
- prose score at least 65;
- `hard_fail` is false;
- decision is `pass` or `revise`, never `rewrite`;
- no normalized issue has severity `critical`.

Platform/compliance violations, canon-breaking contradictions, and other hard failures remain blocking regardless of total score.

## Flywheel Behavior

Each final-review attempt is evaluated immediately. A full pass or conditional pass stops further structural revision and returns the corresponding candidate. Failed revisions continue only within the existing correction limit.

The run report records `passed` or `conditional_pass` rather than collapsing both outcomes. The formal manuscript is archived in either case. A conditional pass preserves its remaining noncritical issues in the quality report for optional later editing.

The existing best-candidate protection remains active for failures: later lower scores never replace the highest-scoring candidate. Because a safe score of 75 or higher exits immediately, the system does not risk a broad rewrite after reaching publishable quality.

## User Feedback

Run logs distinguish `质量审核通过` from `质量条件通过，建议小修` and include score and dimensions. The console treats both as successful completed runs; the report retains the exact decision for inspection.

## Compatibility

No database or project migration is required. Existing failed reports remain historical records. Resume behavior continues to use the prior best candidate, which may pass under the new policy after a fresh independent final review.

## Testing

- Score 80 or higher passes under existing dimension and hard-fail rules.
- Score 75 through 79.99 conditionally passes only with clear dimensions, no hard fail, no rewrite decision, and no critical issue.
- Score below 75 fails.
- Critical issues block an otherwise eligible conditional pass.
- The workflow stops after the first conditional pass, archives that candidate, and records `conditional_pass`.
- The complete test suite remains green.
