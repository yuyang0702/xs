# Project Maintenance Rules

- Preserve existing novels, model bindings, Skills, run history, and formal manuscripts during migrations.
- Do not call paid model APIs from automated tests or maintenance checks.
- Any behavior change to workflows, model routing, token budgets, StoryState, quality gates, recovery, or project files must update `README.md` or `docs/maintenance.md` in the same commit.
- Schema or state changes must update the applicable design document under `docs/superpowers/specs` and include an idempotent migration test.
- User-visible run events must distinguish model failure, Runtime rejection, quality failure, fallback, and successful commit.
- Run the focused regression test first, then the complete test suite before restarting the console.
- Never restart while a run is `queued`, `running`, or `cancelling` unless the user explicitly authorizes termination.

## Generated-Output Parsing Compatibility Gate

- Every new or changed parser for model-generated, imported, or user-authored semi-structured text MUST normalize presentation variants at one shared boundary before semantic validation. Cover CRLF/LF, surrounding whitespace, common Markdown or HTML wrappers, fenced/unfenced blocks, full-width punctuation or digits, and documented label aliases when applicable.
- Normalize identifiers and labels with Unicode-aware comparison (including NFKC when safe), but never rewrite free-form prose merely to make parsing easier.
- Preserve every previously accepted representation unless an explicit migration and rollback path is documented. Formatting differences alone must not become semantic hard failures.
- Separate deterministic syntax normalization from semantic validation. Repair harmless wrappers locally; reserve blocking errors for malformed data, multiple JSON-object payloads, canon conflicts, or narrative contradictions. Never silently choose the first or last payload when more than one valid candidate exists.
- New JSON-object parsers MUST reuse `novel_flywheel.model_output.parse_json_object`; a custom parser is allowed only for a documented schema-specific repair and must still reject multiple valid payloads.
- Markdown semantic scanners MUST ignore ordinary HTML comments, fenced examples, and templates unless a parser-owned sentinel explicitly claims the block. Extract owned protocol blocks before sanitizing the remaining visible Markdown.
- A parser change is incomplete without table-driven tests for the canonical form, at least two realistic variants, malformed and ambiguous input that fail closed, and a regression fixture or minimal reproduction for any production failure that prompted the change.
- Update `docs/maintenance.md` whenever this compatibility contract gains a new accepted representation or changes failure behavior.

## New Feature Integration Gate

- New features must preserve the existing StoryState authority, Runtime-controlled formal writes, model roles and fallbacks, Skill behavior, candidate validation, quality gates, credentials, project files, and run history by default.
- Do not introduce a second authoritative state store, competing workflow, or direct model/Skill write path. Extend existing modules and contracts with the smallest compatible change.
- Existing projects and default behavior must remain unchanged unless the user explicitly enables the feature. Prefer project-scoped, reversible feature flags for optional behavior.
- Before adopting external code, prompts, Skills, or workflows, document overlap, prompt/Skill conflicts, data ownership, migration and rollback, security boundaries, and license obligations.
- A change may alter a core path only when it can materially improve writing quality, consistency, or user control. The proposal must state measurable acceptance criteria and preserve the old path as a tested fallback until comparative evidence confirms the improvement.
- New generated content must continue through the existing candidate, validation, review, and commit flow. No feature may overwrite a formal manuscript directly.
