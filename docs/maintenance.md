# Novel Flywheel Maintenance

## Authoritative project state

Every novel owns an independent versioned StoryState in SQLite. It records locked and confirmed facts, character state, world rules, timeline events, unresolved issues, and the formal manuscript revision. Models only produce candidates; Runtime validates and commits the accepted candidate. Failed, cancelled, rejected, or stale candidates cannot overwrite the formal manuscript.

Existing projects are imported without rewriting their files. Before the first StoryState schema upgrade, the application creates `data/app.pre-story-state.db` once. New projects receive StoryState revision 1 during creation.

## Short-story model route

The short-story workflow reuses complete planning, draft, and valid review checkpoints after a failed or cancelled run.

Polish receives one bounded manuscript segment, adjacent boundaries, a compact full-story map, authoritative facts, character state, findings, and stage-specific Skills. Ordinary expression polishing cannot change plot events. Runtime rejects abnormal length changes and removal of literal locked facts, preserving the original segment.

### Token budgets

| Stage or route | Output limit |
|---|---:|
| Planning | 12,288 |
| Draft | 8,192 |
| Review | 4,096 |
| Revision plan | 8,192 |
| Claude primary polish | 8,192 on the first request |
| Other polish routes | Dynamic, 2,048-8,192 based on segment size |
| Final review | 8,192 |
| Maintenance extraction | 4,096 |

Claude receives 8,192 immediately because observed relay responses repeatedly consumed the smaller dynamic allowance before returning visible prose. This avoids paying for the same input twice. Non-Claude routes retain dynamic budgets. A non-Claude polish response that is empty specifically because of `finish_reason=max_tokens` may retry once at 8,192; other errors fall through to the configured fallback.

HTTP `524` means the relay reached the upstream model but timed out waiting for a response. It is not a manuscript validation error. The configured fallback handles it without modifying the formal manuscript.

Input-token circuit breakers are 120,000 for initial polish, 60,000 per structural correction round, and 220,000 cumulative polish input per run. The Runtime checks actual successful-call receipts before starting the next segment. Provider-side failed calls without usage metadata cannot be counted exactly.

Structural plans must target no more than 40% of stable `scene-NN` scenes and contain literal checks for hard issues. A truncated/invalid plan does not fall back to an all-scene rewrite. It halts correction, writes the best available text to `outputs/best-candidate.md`, and leaves the formal manuscript unchanged. Exact consecutive multi-paragraph duplicates are removed locally; semantic near-duplicates remain review findings.

Revision planning compacts its Skill and constraint prompts. Empty, truncated, invalid-JSON, over-scoped, or checkless hard-issue plans retry once through the `review` role. If that result is also invalid, `revision_plan_blocked` stops correction. This is a role fallback, not a full-manuscript rewrite retry.

Ordinary polish splits around 2,000 characters and merges a trailing chunk below 800 characters when the combined chunk is at most 2,800 characters. Structural correction does not reuse those prose chunks: each targeted `scene-NN` is sent exactly once, preventing one scene-level task from being repeated over multiple fragments. Structural candidates use a 60%-180% length contract; ordinary candidates use 70%-160%. Rejection metadata includes absolute bounds and a short candidate preview. Prompt metadata always appears before `MANUSCRIPT SEGMENT`; source prose is last.

Rejected candidates are never written as polish checkpoints. A later resume can retry the rejected source instead of mistaking the preserved original for a completed edit.

## Log interpretation

- `checkpoint_reused`: prior complete artifacts were reused; generation did not restart from zero.
- `polish_max_tokens_retry`: a dynamically-budgeted non-Claude polish output was empty and received one full-budget retry.
- `model_fallback`: the primary route failed and a configured model or role fallback is running.
- `polish_circuit_opened`: a successful fallback is reused for later segments in the same pass.
- `polish_output_rejected`: local validation kept the original segment.
- `revision_plan_blocked`: the plan was invalid, truncated, over the 40% scope, or lacked deterministic checks; no scene rewrite started.
- `token_budget_exhausted`: the next polish request was blocked by the round or cumulative input-token cap.
- `quality_revision_halted`: correction stopped and `best-candidate.md` was preserved.
- `polish_checkpoint_reused`: an interrupted pass reused an identical source segment from its own checkpoint.
- `quality_assessed`: includes source, total score, dimensions, decision, and hard-fail state.
- `story_state_committed`: the candidate manuscript and authoritative state advanced together.
- `failed`: the run stopped; formal files remain at their last committed revision.

## Safe maintenance procedure

1. Check SQLite for active `queued`, `running`, or `cancelling` runs before restart.
2. Reproduce defects from run events and receipts without making a paid request.
3. Add a focused failing test before changing workflow behavior.
4. Update this document when routing, budgets, state, recovery, or log semantics change.
5. Run the focused test and full `pytest -q` suite.
6. Restart with `start-novel-console.cmd` or the same configured data directory and port.
7. Verify the home page, project count, database path, and relevant state rows.
