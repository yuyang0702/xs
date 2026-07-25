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

The sidebar **项目资料** view is separate from the writing workbench. Its character browser reads the existing `characters/*.md` files directly and exposes their frontmatter, appearance, personality, backstory, motivations, voice, arc, and timeline. The dynamic StoryState editor remains versioned below it. Character files and StoryState keep their existing responsibilities; the page does not create a second source of truth.

The materials view also enumerates existing worldbuilding, location, plot, timeline, continuity, and constraint Markdown files. Read mode localizes known template labels and renders sections and tables without exposing YAML or Markdown syntax; raw source appears only in edit mode. Editing uses the original project-relative file, a content hash to reject stale saves, and atomic replacement. Saves are blocked while a project run is active. Character state, timeline, world-rule, and constraint edits synchronize only their owned StoryState sections and create a new revision; static appearance, personality, motivation, and voice remain solely in the character profile. The raw StoryState JSON editor is collapsed under **高级数据与版本历史** for exceptional manual correction.

`materials-audit` compares paragraph-aligned manuscript windows against the current project materials through the configured final-review route. Each completed window writes a source-hashed checkpoint. Restarting the check resumes the latest failed or cancelled audit, reuses unchanged windows, and rechecks windows whose manuscript, constraints, or project reference changed. If the primary route fails and its configured fallback completes a window, the remaining windows in that audit use the fallback directly; that circuit state survives a resume and resets for the next new audit. It records evidenced contradictions in `conflict-report.json` and the versioned issue ledger, but never edits prose. `materials-repair` consumes the latest completed audit, uses structural targeted polish, runs the full-manuscript terminal review, and writes `best-candidate.md`. It never replaces the formal manuscript; publication remains an explicit user action.

Candidate quality displays `effective_words` as its primary count: each Han character, contiguous Latin word, or contiguous numeric token counts once; punctuation, whitespace, and Markdown punctuation are excluded. Pure `han_characters` and total Unicode-code-point `characters` remain visible as secondary metrics and remain available in the API for compatibility.

Wizard interviews persist the user's answer before calling the planning model. Retrying the same unanswered message resumes the model call without duplicating history, and provider connection failures are returned as readable `interview_model_failed` responses.

For short stories, the project-list `Continue writing` action resumes the most recent failed or cancelled run with the same run ID. Recovery checks that run's own complete planning, draft, review, and source-hash polish checkpoints before older runs. Completed stages are not regenerated; `polish_resume_ready` reports the first missing or source-mismatched polish segment and the count of valid checkpoints, even when accepted checkpoints are non-contiguous. Only a missing or structurally incomplete artifact is regenerated. When no resumable run exists, the action only opens the workbench; starting a new complete story remains an explicit workbench command.

Style-sample analysis keeps failures visible in the workbench. If the planning model's first response is not the required JSON profile, the service makes one bounded formatting-repair call before rejecting it.

The style-sample application scope is stored in the existing `project.json` as `style_sample_scope`. Missing values mean `polish`, preserving old behavior. `draft_and_polish` adds the same project `style-profile.md` to draft system context. Run context display is derived from existing events and receipts and stores no duplicate prompt, secret, or header data.

## Short-story model route

Capability probing uses the provider's structured-output request for JSON and requests a specific probe tool for tools. Moonshot OpenAI Chat requests disable thinking when structured output or a specific tool is required, matching the provider's compatibility contract and the same requests used by real workflow stages. Other thinking models that explicitly reject forced `tool_choice` are retried once with automatic tool selection; unrelated tool errors remain visible.

The short-story workflow reuses complete planning, draft, and valid review checkpoints after a failed or cancelled run.

Initial short-story planning uses the complete wizard/project brief directly and does not call StoryToolbox while StoryState is still at revision 1. Those lookups are empty before a manuscript has been committed and would add a second provider round without adding evidence. Planning for an established project retains StoryToolbox access once authoritative state has advanced.

Polish receives one bounded manuscript segment, adjacent boundaries, a compact full-story map, authoritative facts, character state, findings, and stage-specific Skills. Ordinary expression polishing cannot change plot events. Runtime rejects abnormal length changes and removal of literal locked facts, preserving the original segment.

Four or more consecutive short narrative sentences are reported to polish as rhythm issues. Headings and quoted dialogue are excluded from narrative short-sentence metrics; dialogue-only runs and timestamp scene fragments remain separate findings. Polish merges fragments that belong to one continuous action while preserving intentional dialogue, emphasis, suspense, and scene changes. A candidate passes when its longest narrative short-sentence run or short-sentence ratio improves materially, and Runtime still rejects material regression.

Rhythm retry logs name the actual finding: narrative fragments, dialogue-only exchange, or scene fragmentation. Each source segment receives at most one ordinary polish and one targeted rhythm retry for the same polish role configuration and rhythm-policy version. If both fail local validation, Runtime checkpoints the preserved source as `preserved_after_retry`; resume reuses it without another paid call. A source edit, polish provider/model change, or policy-version change invalidates that preservation checkpoint and permits a new attempt.

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

An empty polish response with `finish_reason=max_tokens` retries once even when the route already used the full 8,192 output budget. If that full-budget retry is also empty and token-limited, Runtime treats it as a recoverable segment failure and splits only the current paragraph-aligned segment under the existing depth limit. Some relays report 8,192 generated tokens while returning no visible text; this malformed response is never accepted as a completed segment.

Review starts with its normal 4,096 output limit. An empty Review response with `finish_reason=max_tokens` retries the same model route once at 8,192 with compact JSON-only instructions. If it remains empty, only the Review role's configured fallback is used. Planning is never used as an editorial-review substitute. If both Review routes fail, `review_incomplete` preserves the draft and existing polish checkpoints without creating an editorial score.

HTTP `524` means the relay reached the upstream model but timed out waiting for a response. It is not a manuscript validation error. The configured fallback handles it without modifying the formal manuscript.

Provider calls use streaming transport for Anthropic, OpenAI Chat, and OpenAI Responses protocols. Each adapter consumes provider-native SSE events and aggregates them into the existing `ModelResponse`, so workflow and browser behavior remain unchanged. OpenAI Chat retries streaming without `stream_options` when a relay rejects that optional parameter; providers that explicitly reject `stream` fall back to the existing non-streaming request. A stream that disconnects after partial output is treated as failed rather than accepting an incomplete manuscript.

## Linked project-material updates

When a character profile is saved with "retire removed settings" enabled, the application stores the before/after change under `.novel-flywheel/material-impacts/`. Saving the profile and syncing its basic StoryState fields complete before model analysis starts. A failed or interrupted analysis can be retried and does not roll back the profile edit.

The `maintenance` role compares the change with project material files only. Candidate patches must identify a project-relative file and an exact existing excerpt. The API rejects paths outside the project, model excerpts that do not exist, empty replacements, unchanged replacements, files modified since analysis, and empty selections. Applying selected patches creates a project snapshot, writes only the selected material excerpts, synchronizes affected StoryState sections, and resolves the candidate. Formal manuscripts and run candidates are outside this operation.

The initial-polish input circuit breaker is the larger of 120,000 or 20,000 per generated segment, so smaller adaptive segments can complete the manuscript. Structural correction remains capped at 60,000 per round, and correction count remains bounded by the quality route. There is no conflicting fixed cumulative cap across resumed and corrective rounds. Runtime checks actual successful-call receipts before starting the next segment. Provider-side failed calls without usage metadata cannot be counted exactly.

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
- `polish_segment_split`: a recoverable relay or repeated `max_tokens` failure caused only the failed segment to be split and retried.
- `polish_output_rejected`: local validation kept the original segment.
- `revision_plan_blocked`: the plan was invalid, truncated, over the 40% scope, or lacked deterministic checks; no scene rewrite started.
- `token_budget_exhausted`: the next polish request was blocked by the round or cumulative input-token cap.
- `quality_revision_halted`: correction stopped and `best-candidate.md` was preserved.
- `polish_checkpoint_reused`: an interrupted pass reused an identical source segment from its own checkpoint.
- `polish_resume_ready`: the current run's planning, complete draft, review, and polish checkpoint position were accepted for resume.
- `review_max_tokens_retry`: an empty token-limited Review response is retrying the same route at 8,192.
- `review_configured_fallback`: the same-route Review retry stayed empty and the Review role fallback is running.
- `review_incomplete`: neither Review route produced usable output; no editorial score was fabricated.
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
