# Project Maintenance Rules

- Preserve existing novels, model bindings, Skills, run history, and formal manuscripts during migrations.
- Do not call paid model APIs from automated tests or maintenance checks.
- Any behavior change to workflows, model routing, token budgets, StoryState, quality gates, recovery, or project files must update `README.md` or `docs/maintenance.md` in the same commit.
- Schema or state changes must update the applicable design document under `docs/superpowers/specs` and include an idempotent migration test.
- User-visible run events must distinguish model failure, Runtime rejection, quality failure, fallback, and successful commit.
- Run the focused regression test first, then the complete test suite before restarting the console.
- Never restart while a run is `queued`, `running`, or `cancelling` unless the user explicitly authorizes termination.

