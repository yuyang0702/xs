# Local Format Repair and Polish Timeout Design

## Goal

Prevent mechanical Chinese typography defects from consuming another full-manuscript model revision, while allowing the configured Claude polish provider enough time to finish long responses.

## Scope

- Normalize safe mechanical typography defects locally before deterministic revision checks.
- Keep semantic, continuity, compliance, and structural findings in the model-driven correction loop.
- Increase the current Claude polish provider timeout from 180 seconds to 300 seconds.
- Do not restart the service while a generation run is active.

## Local Repair

Add a deterministic manuscript formatter for Chinese prose. It may:

- Convert paired ASCII double quotes used as dialogue delimiters to Chinese curly double quotes.
- Remove accidental spaces between adjacent CJK characters.
- Collapse clearly duplicated Chinese punctuation without changing sentence meaning.

The formatter must preserve Markdown structure, segment separators, Latin identifiers, URLs, numbers, and intentional quoted technical strings. It runs on each revised candidate before `check_revision_constraints`.

After formatting, deterministic checks run against the formatted candidate. Mechanical formatting failures must not be passed to the chief editor as runtime structural failures and therefore cannot independently justify `critical` or `hard_fail`. If a formatting defect cannot be repaired safely, it remains a non-blocking warning in the quality report.

## Quality Behavior

Model correction remains required for substantive blockers, including:

- plot or timeline contradictions;
- character motivation or knowledge-boundary failures;
- missing causal links that break the story;
- genuine compliance or safety risks;
- explicit `rewrite` decisions supported by substantive evidence.

The existing score thresholds and best-candidate preservation remain unchanged.

## Timeout Behavior

The dedicated Claude polish provider timeout becomes 300 seconds. A connection failure may retry once after a short delay; a request that reaches the 300-second limit falls back to the configured backup model. Other providers retain their existing timeout values.

The timeout update applies to calls started after the configuration change. It does not alter or interrupt an in-flight request.

## Verification

- Unit tests cover safe quote, spacing, and punctuation normalization.
- Workflow tests prove a repaired mechanical issue does not enter the model correction loop.
- Existing semantic forbidden-text checks continue to fail when substantive forbidden content remains.
- Provider configuration is verified as 300 seconds for the Claude polish provider only.
- The full test suite must pass before restart.

