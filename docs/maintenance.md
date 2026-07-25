# Novel Flywheel Maintenance

## Provider maintenance

The **模型与 API** page supports in-place updates to a provider's name, protocol, Base URL, and API Key. Provider IDs and model mappings remain stable. Internal authentication, timeout, and extra-header settings are preserved rather than exposed in the ordinary form. A blank API Key during editing preserves the secret already stored in the system credential store.

Provider secrets remain in the Windows credential store. Runtime startup and CrewAI execution must never override `LOCALAPPDATA`: doing so changes the credential-store context and makes existing keys appear missing even though provider rows remain intact. Only `NOVEL_FLYWHEEL_DATA_DIR`, `CREWAI_STORAGE_DIR`, and telemetry settings are scoped by the launcher.

Deleting a provider is permanent and also removes its model mappings and stored secret. Role bindings that use the provider as primary are deleted; bindings that use it only as fallback retain their primary route and clear the fallback fields. These changes do not alter project files or committed manuscripts.

## Skill classification

The Skill page distinguishes executable Skills from prompt Skills that merely bundle auxiliary validation or development scripts. A script requires approval only when `SKILL.md` explicitly references its `scripts/...` path. Auxiliary scripts remain visible in the UI but are not executable through the writing workflow.

Skill conflict warnings are read-only heuristics. They currently flag explicit fragmented-prose instructions, named-author imitation, and direct formal-manuscript writes. They do not change approval or execution state.

## Authoritative project state

Every novel owns an independent versioned StoryState in SQLite. It records locked and confirmed facts, character state, world rules, timeline events, unresolved issues, and the formal manuscript revision. Models only produce candidates; Runtime validates and commits the accepted candidate. Failed, cancelled, rejected, or stale candidates cannot overwrite the formal manuscript.

Existing projects are imported without rewriting their files. The one-time import fills empty StoryState sections from `project.json` world rules, `memory/canon.json` facts and state, `continuity/state.md`, and `plot/timeline.md`; it never replaces non-empty sections. An empty provisional-facts or issue-ledger section means the project has not recorded such items yet. Before the first StoryState schema upgrade, the application creates `data/app.pre-story-state.db` once. New projects receive StoryState revision 1 during creation.

Manual project-data edits update one allowlisted StoryState section through the existing candidate and optimistic revision commit. They are blocked while a project run is active and cannot edit `manuscript_revision`. History remains available for inspection; normal post-write extraction continues automatically.

Wizard interviews persist the user's answer before calling the planning model. Retrying the same unanswered message resumes the model call without duplicating history, and provider connection failures are returned as readable `interview_model_failed` responses.

For short stories, the project-list `Continue writing` action resumes the most recent `token_budget_exhausted` failed run with the same run ID. Existing polish source-hash checkpoints are reused, so completed segments are not sent again. When no such run exists, the action only opens the workbench; starting a new complete story remains an explicit workbench command.

Style-sample analysis keeps failures visible in the workbench. If the planning model's first response is not the required JSON profile, the service makes one bounded formatting-repair call before rejecting it.

The style-sample application scope is stored in the existing `project.json` as `style_sample_scope`. Missing values mean `polish`, preserving old behavior. `draft_and_polish` adds the same project `style-profile.md` to draft system context. Run context display is derived from existing events and receipts and stores no duplicate prompt, secret, or header data.

## Short-story model route

The short-story workflow reuses complete planning, draft, and valid review checkpoints after a failed or cancelled run.

Initial short-story planning uses the complete wizard/project brief directly and does not call StoryToolbox while StoryState is still at revision 1. Those lookups are empty before a manuscript has been committed and would add a second provider round without adding evidence. Planning for an established project retains StoryToolbox access once authoritative state has advanced.

Polish receives one bounded manuscript segment, adjacent boundaries, a compact full-story map, authoritative facts, character state, findings, and stage-specific Skills. Ordinary expression polishing cannot change plot events. Runtime rejects abnormal length changes and removal of literal locked facts, preserving the original segment.

Three or more consecutive short sentences or one-sentence paragraphs are reported to polish as rhythm issues. Polish merges fragments that belong to one continuous action while preserving intentional dialogue, emphasis, suspense, and scene changes. Runtime does not mechanically join sentences, but rejects a polish candidate that makes the short-sentence ratio, longest short-sentence run, or one-sentence-paragraph run materially worse than its source.

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

Configured Claude polish routes receive 8,192 immediately because observed relay responses repeatedly consumed the smaller dynamic allowance before returning visible prose. This applies to both the primary and configured Claude fallback; non-Claude routes retain dynamic budgets. A non-Claude polish response that is empty specifically because of `finish_reason=max_tokens` may retry once at 8,192.

An empty polish response with `finish_reason=max_tokens` retries once even when the route already used the full 8,192 output budget. Some relays report 8,192 generated tokens while returning no visible text; this malformed response is not accepted as a completed segment.

HTTP `524` means the relay reached the upstream model but timed out waiting for a response. It is not a manuscript validation error. The configured fallback handles it without modifying the formal manuscript.

The initial-polish input circuit breaker is the larger of 120,000 or 20,000 per generated segment, so smaller adaptive segments do not exhaust the legacy round cap before the manuscript is complete. Structural correction remains capped at 60,000 per round, and cumulative polish input remains capped at 220,000 per run. Runtime checks actual successful-call receipts before starting the next segment. Provider-side failed calls without usage metadata cannot be counted exactly.

Structural plans must target no more than 40% of stable `scene-NN` scenes and contain literal checks for hard issues. A truncated/invalid plan does not fall back to an all-scene rewrite. It halts correction, writes the best available text to `outputs/best-candidate.md`, and leaves the formal manuscript unchanged. Exact consecutive multi-paragraph duplicates are removed locally; semantic near-duplicates remain review findings.

Revision planning compacts its Skill and constraint prompts. Empty, truncated, invalid-JSON, over-scoped, or checkless hard-issue plans retry once through the `review` role. If that result is also invalid, `revision_plan_blocked` stops correction. This is a role fallback, not a full-manuscript rewrite retry.

Ordinary polish targets about 1,400 characters and normally stays below 1,800, splitting only at existing paragraph boundaries. A single oversized paragraph is preserved instead of being cut mechanically. Before each provider call, Runtime estimates the complete system and user input; if it is unusually large, repeated Skill and constraint context is compacted further while manuscript prose, locked facts, relevant character state, and the current task remain intact. Structural correction does not reuse ordinary prose chunks: each targeted `scene-NN` is sent exactly once unless a recoverable relay failure requires safe paragraph splitting. Structural candidates use a 60%-180% length contract; ordinary candidates use 70%-160%. Rejection metadata includes absolute bounds and a short candidate preview. Prompt metadata always appears before `MANUSCRIPT SEGMENT`; source prose is last.

After configured Claude routes return a recoverable `502`, `504`, `524`, timeout, or connection failure, Runtime splits only the failed segment near a paragraph boundary and retries its children to a bounded depth. Successful children use source-hash checkpoints. Authentication, configuration, validation, and minimum-size failures stop transparently. Polish never silently switches to the Draft role.

Rejected candidates are never written as polish checkpoints. A later resume can retry the rejected source instead of mistaking the preserved original for a completed edit.

Structural correction has two length thresholds: a preferred floor of 60% and a hard rejection floor of 50%. Candidates between them emit `polish_conditional_length` and continue only to final review; they are not auto-committed. Before executing a structural plan, Runtime also re-checks each `forbidden_text` against the full manuscript and can move that repair task to the scene that actually contains the text, logging `revision_targets_aligned`.

## Full-manuscript final review

Short manuscripts up to one 6,000-character window are sent to `final_review` in full. Longer short stories are split into paragraph-aligned 4,000-6,000 character windows with overlap. Each window extracts ordered events, character state and knowledge, timeline, promises, payoffs, and evidenced issues; it does not assign the book's final score. Final adjudication receives the merged evidence and performs cross-window consistency checks.

Initial editorial issues receive stable IDs. Final adjudication must mark each one `resolved`, `partially_resolved`, `unresolved`, or `not_found` with evidence. Missing reconciliation, incomplete coverage, or insufficient evidence invalidates approval. An unresolved major issue caps the score at 74; multiple unresolved moderate issues cap it at 79.

Final review uses only the `final_review` role and its configured provider fallback. It never switches to `planning`. If both configured routes fail, Runtime writes `best-candidate.md`, reports `final_review_incomplete`, and leaves the formal manuscript unchanged. The output limit remains 8,192 tokens. A typical 20,000-character story uses several 6,000-12,000 input-token requests and roughly 40,000-70,000 cumulative input tokens.

The run detail context can expose manuscript coverage, reviewed window count, reconciliation counts, and local gate reasons from `quality-report.json`.

## Log interpretation

- `checkpoint_reused`: prior complete artifacts were reused; generation did not restart from zero.
- `polish_max_tokens_retry`: a dynamically-budgeted non-Claude polish output was empty and received one full-budget retry.
- `model_fallback`: the primary route failed and a configured model or role fallback is running.
- `polish_circuit_opened`: a successful fallback is reused for later segments in the same pass.
- `polish_input_sized`: estimated complete input size recorded before a provider call.
- `polish_segment_split`: a recoverable relay failure caused only the failed segment to be split and retried.
- `polish_output_rejected`: local validation kept the original segment.
- `revision_plan_blocked`: the plan was invalid, truncated, over the 40% scope, or lacked deterministic checks; no scene rewrite started.
- `token_budget_exhausted`: the next polish request was blocked by the round or cumulative input-token cap.
- `quality_revision_halted`: correction stopped and `best-candidate.md` was preserved.
- `polish_checkpoint_reused`: an interrupted pass reused an identical source segment from its own checkpoint.
- `quality_assessed`: includes source, total score, dimensions, decision, and hard-fail state.
- `final_review_incomplete`: configured terminal-review routes failed; the best candidate was preserved without a fabricated score.
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

## New feature compatibility gate

New capabilities are additive by default. They must not replace or bypass StoryState, Runtime-controlled formal writes, model routing and fallback, stage-specific Skills, candidate validation, quality gates, credential storage, project files, or run history. External projects are design references unless a scoped integration has passed overlap, prompt/Skill conflict, data ownership, migration, rollback, security, and license review.

Optional behavior should be project-scoped, disabled for existing projects, reversible, and implemented through existing contracts. A core workflow may change only when the proposal defines measurable gains in writing quality, consistency, or user control and retains the previous path as a tested fallback until comparative evidence supports removal. Generated content always remains a candidate until the existing validation, review, and commit flow accepts it.
