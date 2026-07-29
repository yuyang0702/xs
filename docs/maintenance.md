# Novel Flywheel Maintenance

## Market trend snapshots

Market data uses the existing SQLite database as its only authority. The relevant tables are
`market_sources`, `market_snapshots`, `market_works`, `market_entries`, and
`reference_market_links`. `Database.migrate()` creates them idempotently and must continue to
preserve existing reference and project rows.

The built-in source id is `zhihu-salt`. Refresh is user-triggered through
`POST /api/market/refresh`; automated tests must inject static HTML into `MarketService` and
must never contact Zhihu or a paid model. A successful non-empty parse creates a snapshot.
HTTP failures, empty results, or incompatible markup only update the source failure status and
must not delete or replace prior snapshots.

The source keeps the user-facing page URL, while its adapter reads the same public
`api.zhihu.com/km-vip-zhihu-web/vip_tab/svip_story?modules=billboard` endpoint used by that page.
The HTML response itself contains ranking skeletons rather than the completed ranking cards.
Parser tests therefore cover both the public API's snake-case response and the older embedded
JSON shape.

Market keyword analysis is local-only. It counts distinct works rather than raw occurrences,
requires a term to appear in at least two works, separates title, summary, and combined views,
and exposes matching works as evidence. When LTP is enabled, cached local tokens are used before
the conservative dictionary fallback; this feature never calls a paid model.

Each ranked work stores an effective `length_type` (`long`, `short`, `anthology`, or `unknown`)
together with its source and evidence. Resolution priority is a user override, an explicit
platform `space_type`, a long-form ranking, confirmed TXT inference, and finally `unknown`.
Clearing a user override restores the best available automatic result. Dashboard filters keep
different length types from being mixed in market summaries.

Platform adapters return the normalized work contract used by `MarketService.refresh`: platform
work id, title, optional author/summary/cover/detail URL, ranking name, original category, rank,
tags, and a platform-specific metrics object. Preserve raw categories and metrics. Cross-platform
reports may normalize relative rank or category mappings but must not compare unlike raw units.

Reference links are explicit user decisions. Refresh and matching may suggest candidates but
must not overwrite a confirmed link, reference metadata, text versions, learning decisions,
originality reports, model analysis, or final-review results. Removing a link only deletes the
`reference_market_links` row.

When a platform page changes:

1. Add a static regression fixture that reproduces the new visible page state.
2. Make the parser test fail for the expected missing works.
3. Update only the platform parser.
4. Run focused market, reference, migration, API, and console tests before the full suite.

## Provider maintenance

The **模型与 API** page supports in-place updates to a provider's name, protocol, Base URL, and API Key. Provider IDs and model mappings remain stable. Internal authentication, timeout, and extra-header settings are preserved rather than exposed in the ordinary form. A blank API Key during editing preserves the secret already stored in the system credential store.

Provider secrets remain in the Windows credential store. Runtime startup and CrewAI execution must never override `LOCALAPPDATA`: doing so changes the credential-store context and makes existing keys appear missing even though provider rows remain intact. Only `NOVEL_FLYWHEEL_DATA_DIR`, `CREWAI_STORAGE_DIR`, and telemetry settings are scoped by the launcher.

## Optimized local review artifacts

The project-scoped `optimized_local_review_enabled` key is stored in `project.json`. New short projects store `true`; long projects do not receive the key. On `ProjectStore` initialization, an existing short project that completely lacks the key is migrated once. Before the atomic metadata write, Runtime creates `snapshots/optimized-review-default/` through `ProjectSnapshot`; explicit `false` or `true` values and long projects are never rewritten. A pre-existing interrupted snapshot is reused only when its manifest, hash, JSON content, and the current project file agree exactly. A damaged or mismatched snapshot stops startup migration without overwriting either side. Repeated initialization changes neither bytes nor modification times.

Disable the workflow-analysis setting to store `false` and return that project to the complete-review path. The snapshot is an audit and recovery artifact, not the live feature toggle; restoring a missing-key file under the current version will run the default migration again. No database or StoryState schema migration is required, and this metadata migration does not alter StoryState, role bindings, providers, credentials, references, run history, or manuscripts. The global LTP install/enable controls remain separate.

Run outputs may contain:

- `analysis-draft.json`: complete assembled-draft local analysis;
- `analysis-polish.json` and `analysis-polish-N.json`: complete post-revision analysis;
- `analysis-candidate.json`: publication-time hash-matching analysis;
- `final-review-baseline.json`: first complete terminal-review baseline;
- `incremental-review-N.json`: correction changes, selection reasons, evidence, and token-scope estimates;
- `quality-report.json.review_scope_history`: full, incremental, and fallback scope history.

LTP failure is fail-safe: rules still run, but correction approval returns to complete final review. Missing or invalid analysis hashes, incomplete issue reconciliation, ambiguous window mapping, or a structural-change trigger must never be converted into incremental approval.

To roll back, disable the feature for the project. Existing artifacts remain available for audit, while subsequent correction rounds use the previous complete-final-review path. Cached NLP JSON can be removed only when no run is active; it will be rebuilt by text and backend-version hash.

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

## Reference library maintenance

Short stories may carry an active short_causal_chain project artifact. It is a whole-story causal index, not a replacement outline and not a per-chapter template. It stores the core goal, repeatable obstacle-effort-result cycles, accidents, reversal evidence, and ending payoff. Planning may append this JSON between SHORT_CAUSAL_CHAIN_JSON_START and SHORT_CAUSAL_CHAIN_JSON_END; Runtime extracts it, saves diagnostics, rewrites planning.md back to ordinary outline text, and continues even when extraction fails. The compact chain is added to draft and final-review context so the manuscript can be checked for goal setup, state-changing cycles, accident, reversal evidence, and ending payoff.

Learning mechanisms with mechanism_type="causal_structure" are stored in creative_blueprint.causal_structure. They are abstract structure advice only: they cannot directly change project facts, formal outlines, or manuscripts, and must not transfer source names, settings, concrete plot packaging, or unique expression.

Reference sources are not project facts and never write StoryState. Pasted text and browser-read UTF-8 TXT content are stored under `data/references/<source-id>/` with immutable version files; SQLite stores titles, hashes, version metadata, and local-analysis results. Identical normalized content resolves to the existing source rather than creating another copy. API responses omit storage paths and expose source text only through the controlled content endpoint.

DOCX extraction uses the standard library; PDF extraction uses `pypdf`; public URLs use bounded `httpx` requests with public-address checks before every redirect. Imported page text remains untrusted data. Scanned PDFs are rejected rather than silently returning empty prose.

The typed graph lives in `learning_nodes`, `learning_edges`, `learning_evidence`, and `learning_revisions`. Project decisions and versioned derivatives live separately in `project_adoptions` and `project_learning_artifacts`. Deleting a source marks graph nodes and existing adoptions for review before deleting source versions. It never rewrites project files.

Active project artifacts are appended by `ProjectStore.load_constraints()` and therefore use the existing planning, draft, review, and polish routes. Stale artifacts are excluded. Candidate outlines and line edits stay below `<project>/learning/`; formal outlines and manuscripts are never direct targets.

`reference_analysis`, `reference_synthesis`, and `line_edit` are normal role bindings with configured fallbacks. Only explicit UI actions call them. Regression examples in `src/novel_flywheel/quality_regression.json` and all automated tests remain provider-free.

Optional LTP lifecycle endpoints are under `/api/settings/local-nlp`. Installation never runs during startup or migration. Enabled analysis launches `novel_flywheel.nlp_worker` as a bounded process, caches results by text/version hash, and returns rule-only fallback metadata on failure.

The `local-editorial` analyzer is deterministic and provider-free. Reports are cached by source version, content hash, analyzer name, and analyzer version. Current findings are advisory `review` items: exact phrase reuse, functional repetition, long dialogue-only runs, unusually regular sentence rhythm, and short checklist-style judgment chains. A source deletion cascades its versions and analysis rows, then removes only its verified directory below the reference root.

No local generative model is installed or supported by this feature. A later optional Chinese NLP backend requires an explicit Settings installation action, runs one CPU analysis job at a time outside the FastAPI process, and must fall back to these standard-library rules when absent or unhealthy.

`materials-audit` compares paragraph-aligned manuscript windows against the current project materials through the configured final-review route. Each completed window writes a source-hashed checkpoint. Restarting the check resumes the latest failed or cancelled audit, reuses unchanged windows, and rechecks windows whose manuscript, constraints, or project reference changed. If the primary route fails and its configured fallback completes a window, the remaining windows in that audit use the fallback directly; that circuit state survives a resume and resets for the next new audit. It records evidenced contradictions in `conflict-report.json` and the versioned issue ledger, but never edits prose. `materials-repair` consumes the latest completed audit, uses structural targeted polish, runs the full-manuscript terminal review, and writes `best-candidate.md`. It never replaces the formal manuscript; publication remains an explicit user action.

Short-story scene separators remain internal to drafting and targeted revision. Local manuscript analysis, full or incremental final review, and the terminal reviewed hash use the clean reader-visible text, so workflow markers cannot enter editorial findings or publication eligibility.

When a primary polish response fails local length, prose, or locked-fact validation, Runtime tries the configured polish fallback once before preserving the source segment. Both the retry and a failed retry are visible run events; an invalid fallback can never replace the source text.

Every full-review window, incremental-review window, and final adjudication is parsed locally before it is accepted. A malformed or truncated JSON response retries only that request through the final-review role's configured fallback and records `final_review_json_fallback`; completed windows and the preserved best candidate are not discarded.

If final adjudication returns a readable reconciliation summary object instead of the required item list, Runtime recovers only issue entries whose stable IDs match the prior ledger and records `final_review_reconciliation_recovered`. Missing IDs still trigger the existing conservative evidence cap; recovery never treats an omitted issue as resolved and does not call a model again.

Candidate quality displays `effective_words` as its primary count: each Han character, contiguous Latin word, or contiguous numeric token counts once; punctuation, whitespace, and Markdown punctuation are excluded. Pure `han_characters` and total Unicode-code-point `characters` remain visible as secondary metrics and remain available in the API for compatibility.

Wizard interviews persist the user's answer before calling the planning model. Retrying the same unanswered message resumes the model call without duplicating history, and provider connection failures are returned as readable `interview_model_failed` responses.

For short stories, the project-list `Continue writing` action resumes the most recent failed or cancelled run with the same run ID. Recovery checks that run's own complete planning, draft, review, and source-hash polish checkpoints before older runs. Completed stages are not regenerated; `polish_resume_ready` reports the first missing or source-mismatched polish segment and the count of valid checkpoints, even when accepted checkpoints are non-contiguous. Only a missing or structurally incomplete artifact is regenerated. When no resumable run exists, the action only opens the workbench; starting a new complete story remains an explicit workbench command.

Style-sample analysis keeps failures visible in the workbench. If the planning model's first response is not the required JSON profile, the service makes one bounded formatting-repair call before rejecting it.

The legacy style-sample endpoints and files remain for compatibility, but their workbench uploader is retired. Reading `/api/projects/{id}/learning` lazily converts an existing `style-samples/profile.json` into the first `prose_baseline` version without deleting legacy files. Once migrated, `ensure_style_profile()` omits the managed `STYLE_SAMPLE` block from assembled runtime context so the baseline is not injected twice. The workbench is read-only and all later changes belong in the learning library.

Run context display is derived from existing events and receipts and stores no duplicate prompt, secret, or header data.

## Short-story model route

Capability probing uses the provider's structured-output request for JSON and requests a specific probe tool for tools. OpenAI Responses forwards that specific tool through its native `tool_choice` shape. Moonshot OpenAI Chat requests disable thinking when structured output or a specific tool is required, matching the provider's compatibility contract and the same requests used by real workflow stages. Providers that reject or ignore forced `tool_choice` are retried once with automatic tool selection, so lack of forced-choice support is not misreported as lack of tool support; unrelated tool errors remain visible.

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
| Configured polish route | Stage default capped by selected model's `max_output_tokens` |
| Legacy polish route without a ceiling | Dynamic, 2,048-8,192 based on segment size |
| Final review | 8,192 |
| Maintenance extraction | 4,096 |

Ordinary output budgets use the stage-derived default capped by the selected primary or configured fallback model's numeric ceiling; a ceiling never enlarges an ordinary request. Legacy model records without a ceiling retain the stage-derived default. A targeted patch without a configured ceiling treats that actual stage budget as its ceiling. It may retry only when the next numeric limit is larger; at the ceiling Runtime raises into the current-segment split path instead of guessing 8,192 or repeating an identical request. Primary and automatic fallback calls are independently capped by their own configured ceilings. Ordinary polish and Review retain their established compatibility retries, also capped when the route has a numeric ceiling.

Review starts with its normal 4,096 output limit. An empty Review response with `finish_reason=max_tokens` retries the same model route once at 8,192 with compact JSON-only instructions. If it remains empty, only the Review role's configured fallback is used. Planning is never used as an editorial-review substitute. If both Review routes fail, `review_incomplete` preserves the draft and existing polish checkpoints without creating an editorial score.

HTTP `524` means the relay reached the upstream model but timed out waiting for a response. It is not a manuscript validation error. The configured fallback handles it without modifying the formal manuscript.

Provider calls use streaming transport for Anthropic, OpenAI Chat, and OpenAI Responses protocols. Each adapter consumes provider-native SSE events and aggregates them into the existing `ModelResponse`, so workflow and browser behavior remain unchanged. OpenAI Chat retries streaming without `stream_options` when a relay rejects that optional parameter; providers that explicitly reject `stream` fall back to the existing non-streaming request. A stream that disconnects after partial output is treated as failed rather than accepting an incomplete manuscript.

## Linked project-material updates

When a character profile is saved with "retire removed settings" enabled, the application stores the before/after change under `.novel-flywheel/material-impacts/`. Saving the profile and syncing its basic StoryState fields complete before model analysis starts. A failed or interrupted analysis can be retried and does not roll back the profile edit.

The `maintenance` role compares the change with project material files only. Candidate patches must identify a project-relative file and an exact existing excerpt. The API rejects paths outside the project, model excerpts that do not exist, empty replacements, unchanged replacements, files modified since analysis, and empty selections. Applying selected patches creates a project snapshot, writes only the selected material excerpts, synchronizes affected StoryState sections, and resolves the candidate. Formal manuscripts and run candidates are outside this operation.

The initial-polish input circuit breaker is the larger of 120,000 or 20,000 per generated segment, so smaller adaptive segments can complete the manuscript. Structural correction remains capped at 60,000 per round, and correction count remains bounded by the quality route. There is no conflicting fixed cumulative cap across resumed and corrective rounds. Runtime checks actual successful-call receipts before starting the next segment. Provider-side failed calls without usage metadata cannot be counted exactly.

Structural plans contain literal checks for hard issues and preserve the model's task priority. Runtime applies no more than 40% of stable `scene-NN` scenes in one batch; valid targets beyond that limit retain their tasks and continue in later batches under the same correction-round token budget before final review. A truncated or otherwise invalid plan does not fall back to an all-scene rewrite. It halts correction, writes the best available text to `outputs/best-candidate.md`, and leaves the formal manuscript unchanged. Exact consecutive multi-paragraph duplicates are removed locally; semantic near-duplicates remain review findings.

Before a resumed quality pass rewrites `quality-report.json`, Runtime reads the existing `best_score` together with `best-candidate.md`. That pair becomes the new pass's minimum checkpoint. Lower-scoring retries may be recorded for diagnosis, but failure, provider interruption, or invalid revision planning restores the earlier higher-scoring text. The `quality_best_restored` event tells the UI which score is protected.

Revision planning compacts its Skill and constraint prompts. Malformed JSON first receives a schema-only repair request containing only the malformed output and schema identifier. Empty, truncated, semantically invalid, or still-invalid repaired plans retry through the `review` role. A valid plan that covers too many scenes is batched locally and does not spend a fallback model call. If the fallback result is also invalid, `revision_plan_blocked` stops correction. This is a role fallback, not a full-manuscript rewrite retry.

Ordinary polish targets about 1,400 characters and normally stays below 1,800, splitting only at existing paragraph boundaries. A single oversized paragraph is preserved instead of being cut mechanically. Before each provider call, Runtime estimates the complete system and user input; if it is unusually large, repeated Skill and constraint context is compacted further while manuscript prose, locked facts, relevant character state, and the current task remain intact. Structural correction does not reuse ordinary prose chunks: each targeted `scene-NN` is sent exactly once unless a recoverable relay failure requires safe paragraph splitting. Structural candidates use a 60%-180% length contract; ordinary candidates use 70%-160%. Rejection metadata includes absolute bounds and a short candidate preview. Prompt metadata always appears before `MANUSCRIPT SEGMENT`; source prose is last.

After configured Claude routes return a recoverable `502`, `504`, `524`, timeout, or connection failure, Runtime splits only the failed segment near a paragraph boundary and retries its children to a bounded depth. Successful children use source-hash checkpoints. Authentication, configuration, validation, and minimum-size failures stop transparently. Polish never silently switches to the Draft role.

Rejected candidates are never written as polish checkpoints. A later resume can retry the rejected source instead of mistaking the preserved original for a completed edit.

Structural correction has two length thresholds: a preferred floor of 60% and a hard rejection floor of 50%. Candidates between them emit `polish_conditional_length` and continue only to final review; they are not auto-committed. Before executing a structural plan, Runtime also re-checks each `forbidden_text` against the full manuscript and can move that repair task to the scene that actually contains the text, logging `revision_targets_aligned`.

## Full-manuscript final review

Short manuscripts up to one 6,000-character window are sent to `final_review` in full. Longer short stories are split into paragraph-aligned 4,000-6,000 character windows with overlap. Each window extracts ordered events, character state and knowledge, timeline, promises, payoffs, and evidenced issues; it does not assign the book's final score. Final adjudication receives the merged evidence and performs cross-window consistency checks.

Initial editorial issues receive content-derived stable IDs plus source, repair goal, and status. Revision-plan tasks preserve related `issue_ids`. Incremental adjudication must mark every prior issue exactly `resolved`, `unresolved`, or `uncertain` with evidence. Missing or invalid reconciliation, incomplete coverage, or insufficient evidence triggers the complete-review fallback. An unresolved or uncertain major issue cannot pass incrementally.

Final review uses only the `final_review` role and its configured provider fallback. It never switches to `planning`. A provider failure records `final_review_model_failed`; a model response rejected by local JSON or score validation records `final_review_result_rejected`. Both paths write `best-candidate.md` and leave the formal manuscript unchanged. A complete `zhihu-short-v2` criteria set is authoritative and is scored locally without requiring legacy `score` or `dimensions` fields. The output limit remains 8,192 tokens. A typical 20,000-character story uses several 6,000-12,000 input-token requests and roughly 40,000-70,000 cumulative input tokens.

The run detail context can expose manuscript coverage, reviewed window count, reconciliation counts, and local gate reasons from `quality-report.json`.

### Zhihu short quality v2 and protected checkpoints

`profile_for_project()` selects `zhihu-short-v2` only when the project is short and its platform profile is `zhihu-salt-short`. Other projects keep `legacy-v1`. The v2 profile contains 15 literal criteria. Runtime calculates the commercial, story, and prose dimensions and the `40 / 40 / 20` total; provider-supplied aggregate scores cannot override that calculation. A pass requires total `>= 80` and dimension minimums `75 / 75 / 68`. A conditional pass requires total `>= 75` and minimums `72 / 70 / 65`, but remains a candidate and has no formal-manuscript or package authority.

`outputs/quality-checkpoint.json` binds one manuscript path and SHA-256 hash to its score, profile, judge signature, matching review, outcome, and terminal-reviewed hash. A valid explicit checkpoint is authoritative. When it is absent, reconciliation inspects the legacy `best-candidate.md` report and every `historical-best-<score>.md`, writes one idempotent checkpoint for the highest valid legacy candidate, and leaves every source file unchanged. Promotion is allowed only between the same profile and judge. A comparable candidate needs a gain of at least two points, no dimension regression below minus three points, and no new unresolved major issue.

The candidate summary reads the review stored with the hash-matched checkpoint instead of the latest failed attempt. Its official publication count is the number of Han characters after removing internal workflow comments and Markdown heading lines. For a Zhihu short project, the allowed range is 90%-110% of `target_words`. Candidate formalization and Zhihu package generation both consume the same publication-authority result: a passed v2 review, matching manuscript and terminal-review hashes, allowed length, and no unresolved major issue.

The first terminal review remains full-manuscript. A later incremental review fails closed when the exact current manuscript or revision-source hash is missing. Before diffing or making any incremental model call, Runtime verifies that the saved baseline manuscript hash, baseline analysis hash, exact revision-source hash, and current-analysis hash all match their corresponding manuscript text. After local diffing, every changed manuscript must produce a non-empty review scope, and every selected window must carry an explicit selection reason with complete coverage. Any mismatch, empty scope, or unexplained scope triggers `full_fallback` with a specific reason.

Broad or structural changes, semantic changes without LTP, incomplete issue reconciliation, and uncertain NLP/window mapping force a complete review. High-risk local story flags come from content changes in the production `narrative_ledger` questions, promises, setups, payoffs, and relations, from timeline candidates, or from accepted patch-group impact metadata. Ordinary entity and event differences still expand the related-window scope but do not by themselves mean that a principal character or key event changed. In long mode, explicit chapter markers are an authoritative structure layer: chapter insertion and deletion set the corresponding scene flags, replacement sets both, and a marker-preserving reorder sets `scene_moved`, even below broad-change thresholds. The analyzer's current `units.scenes` records remain paragraph-backed, so splitting, merging, or reordering unmarked paragraphs does not create a scene-structure trigger; scene semantics without chapter markers still require authoritative patch impact metadata until a distinct scene model exists.

The broad-change thresholds are inclusive: a changed-text ratio of 20% or a selected-window ratio of 40% triggers full review. The no-LTP mechanical exception applies only when every patch group is accepted and declared mechanical, atomically replays from the exact revision source to the exact current manuscript, matches the authoritative `repair_mechanical_text()` result, and the current local analysis has full coverage. Otherwise Runtime records `unverified_mechanical_changes` and falls back. Long-manuscript comparison remains hierarchical by chapter marker and paragraph-backed stable units. Character-level `SequenceMatcher` input is capped at 8192 characters; an oversized changed region is represented as a coarse range after linear common-prefix and common-suffix trimming. Short manuscripts retain exact whole-text diff ranges.

Quality reference groups are append-only rows in `quality_reference_groups`, scoped by project and profile. Recommendation reads only active, user-confirmed learning sources plus the project's protected historical best; recommendation, confirmation, removal, and history reads make no model request. Confirmation creates a new version. Removal creates another version and does not delete the reference source, its text, analysis, or prior group versions.

Protected passages use versioned `passage.<id>` StoryState locks. Creation accepts complete contiguous paragraphs from the current candidate only. Soft protection tolerates punctuation and spacing changes; exact protection requires the original text. Runtime includes active locks in polish context and validates the returned segment locally. An unapproved change keeps the source segment and records conflict metadata. `allow_next_change` is consumed once and then deactivates that lock; removal also deactivates it without editing prose.

### Targeted revision safety

Targeted revision validates the assembled whole candidate before adoption; passing individual patches does not bypass full-candidate quality and protection gates. A protected passage's one-time `allow_next_change` permission is consumed only after that candidate is accepted. Issue ledgers use exactly `resolved`, `partially_resolved`, `unresolved`, `uncertain`, and `preserved`; mandatory issues may advance only to `resolved`, and every other mandatory state blocks promotion. Structural patch prompts contain complete linked task objects, only checks linked to those issue IDs, the full adjacent paragraphs, the local target, authoritative facts, protection summaries, allowed range, target size, and a real task-supplied seven-step position or an explicit unmarked value. Split children retain this compact targeted context and shrink only the target. Retry decisions use the actual selected-route output ceiling: larger retries require a strictly larger numeric limit, a ceiling hit splits only the current patch, malformed JSON is repaired without resending manuscript context, execution falls through the configured role fallback, and failure of both routes preserves that group and continues independent groups without creating an alternative state or checkpoint authority.

Resumable targeted repair stores exactly five artifacts under the current run's `outputs` directory: `repair-contract.json`, `patch-groups.json`, `repair-checkpoint.json`, `candidate.md`, and `repair-report.json`. Contract, groups, checkpoint, and candidate are required for resume; the report may be absent when execution stopped early. Task orchestration must write `patch-groups.json`, then the new `candidate.md`, and write its hash-bound `repair-checkpoint.json` last, so an interruption cannot make an old checkpoint authorize new group evidence or candidate text. A complete checkpoint binds the contract and groups with SHA-256 over stable canonical UTF-8 JSON and binds the candidate with SHA-256 over its exact UTF-8 text; all three hashes are required for resume. Resume is rejected when the current protected-best hash, contract manuscript hash, checkpoint source hash, or any bound artifact hash is missing, invalid, or inconsistent. These files do not update SQLite, StoryState, passage permissions, best-candidate authority, or the formal manuscript.

The explicit `short-revision` workflow accepts only issue IDs from the terminal ledger bound to the highest-scoring valid protected-best quality checkpoint. A later lower-scoring checkpoint cannot replace that authority. The workflow freezes the selected run ID and source hash, terminal review, issue ledger, read-only StoryState revision and data, passage locks, and local analysis in `repair-contract.json` before the first model call. Mechanical issues are repaired only inside the selected issue evidence and are still represented as normal atomic patch groups; semantic groups use the configured targeted revision route. Failed or cancelled groups retain their record, successful independent groups remain checkpointed, and resume reuses the same run ID while rerunning only unfinished group IDs. A changed protected best stops resume before any model call.

For a selected short-story length issue whose protected candidate is below the active platform minimum, Runtime calculates the exact Han-character deficit locally and routes it through `revision_plan`, then through the existing `draft` role once per planned scene; it never uses ordinary polish for this expansion. The frozen repair contract also captures the active seven-step causal-chain artifact. Planning receives at most 24 exact, unique paragraph-or-sentence anchors sampled across the current candidate, each with its character position and a preview capped at 160 characters; it does not receive the whole manuscript again. Every scene plan must choose from that catalogue and provide a purpose, positive Han target, entry and exit state, insertion operation, time, evidence source, transition, a list containing only trimmed non-empty fact strings, and `requires_full_review=true`; all scene targets must sum to the local deficit. Resume rebuilds the same bounded catalogue from the current checkpoint candidate and rejects a stored anchor that is no longer allowed. Each draft must satisfy its local length bound and reproduce the planned state/evidence fields before the normal patch group is applied atomically. The plan and each accepted scene draft are checkpointed, so provider failure or cancellation resumes only unfinished scenes. Invalid plans or drafts remain local rejections at `waiting_local_fix`.

An accepted expansion patch group carries `scene_inserted` and `requires_full_review`, and `repair-report.json` therefore records `review_mode=full` with `scene_inserted` in `full_review_reasons`. The targeted-revision run still stops at `waiting_confirmation`: it makes no terminal-review call and does not update the protected best, quality checkpoint, formal manuscript, StoryState, passage permissions, provider configuration, credentials, or history. The full-review marker is consumed only by the later confirmation/finalization workflow.

After all available groups are processed, the complete temporary candidate passes through local manuscript analysis and the whole-candidate gate. A failed gate leaves the run at `waiting_local_fix`; a passing gate leaves it at `waiting_confirmation`. Neither state is `completed`, neither calls terminal review, and neither writes `best-candidate.md`, `manuscript/story.md`, passage permissions, or StoryState. Only a targeted route exhaustion is recorded as `model_routes_failed`; malformed JSON, an invalid repair contract, or an atomically rejected patch is a local rejection that remains at `waiting_local_fix`. An unexpected local error writes a safe failed checkpoint and stops immediately instead of continuing other groups. User-facing events and reports explain these categories in Chinese without including raw provider or local exception text; event metadata contains only the group ID and a safe category.

The revision API exposes `POST /api/projects/{project_id}/revisions`, `GET /api/runs/{run_id}/revision`, group `adopt` and `reject` posts, `POST /api/runs/{run_id}/revision/finalize`, and the existing run `resume` endpoint. Group decisions persist `decision` and `decision_candidate_hash` in `patch-groups.json`; rejection also persists `issue_status=unresolved`. `repair-report.json` exposes only the candidate hash, gate, `review_mode`, `full_review_reasons`, `next_action`, and public group summaries such as before/after text, local checks, decision, and issue state. Internal prompts and raw provider errors are never returned.

Finalization requires every semantic or expansion group to have a hash-bound decision, replays adopted groups from the frozen source, reruns the whole-candidate gate, and atomically claims the existing `running` state before terminal review. A second finalize request cannot review or publish concurrently. After the awaited review returns, Runtime reloads the complete repair authority and rechecks the protected run/hash, StoryState revision, locks, contract hash, groups hash, candidate hash, and decisions before quality comparison or checkpoint writes. Strict promotion still requires the same profile and judge, a score gain of at least two, no dimension regression beyond three, no new unresolved major issue, and every mandatory issue resolved. Any local, review, authority, or checkpoint-write failure preserves decisions, does not alter the prior protected manuscript, formal manuscript, StoryState, or locks, and leaves the same run resumable.

Rollback does not require deleting project data. Disable the Zhihu platform profile to return future reviews to `legacy-v1`; v2 checkpoints and reference-group history remain on disk and are ignored by the legacy comparison path. Remove or deactivate passage locks separately if revisions should stop enforcing them. Do not delete `quality-checkpoint.json` merely to lower a protected score: restore a prior manuscript through the existing candidate/revision flow so the new content receives its own hash-bound review.

### Evidence-driven local analysis versions

- `learning-window-v2` invalidates local extraction caches when windowing behavior changes. It records full-text coverage ranges and multiple evidence occurrences. Old confirmed/adopted nodes remain intact; operators must not bulk-delete them during cache maintenance.
- `reference-model-window-v1` checkpoints every successful model-analysis window as a `model_claim`. Resume rebuilds the current dynamic window list and reuses only claims with the same content type, analysis version, exact window-text hash, and a still-valid Chinese result shape. A new source version can reuse unchanged windows; changed or newly split windows run again. Single-version legacy claims may be upgraded only when their index and boundaries exactly match, which preserves interrupted analyses created before checkpoint metadata existed.
- `manuscript-analysis-v2` adds advisory market comparison and a hash-bound narrative ledger. A stale text hash cannot approve an incremental review.
- Market cohorts count each confirmed linked work once per platform/ranking/category/length group. Missing or fewer than five samples disable guidance without blocking project creation.
- Rejected-node deletion is intentionally narrow: only rejected nodes with no project adoption are eligible. The transaction cascades graph evidence, edges, and revisions but never source versions.
- Narrative relation changes add both endpoints to the incremental scope. LTP absence, ambiguous mapping, broad changes, or important structural changes continue to force full review.

## Outline versions

The `outline` object inside StoryState is the authoritative formal outline. It contains content, outline version, source, candidate ID, timestamp, and content hash. `<project>/plot/outline.md` is an atomic readable copy, not a second authority. Existing projects without a StoryState outline expose the latest completed run's `outputs/planning.md` read-only as version 0; it is not migrated or rewritten until the user applies a candidate.

Outline candidates use the existing `story_candidates` table with kind `outline` and content files under `<project>/learning/candidates/`. Editing updates the candidate hash and metadata. Local comparison uses heading or paragraph blocks and standard-library sequence matching. It reports additions, removals, edits, moves, and uncertain matches without calling a model. Semantic review is explicit, uses only the configured `planning` role, sends only uncertain items and locked-fact summaries, limits the request to 30,000 characters and output to 2,048 tokens, and validates returned JSON before displaying it.

Applying selected changes or a whole candidate validates the current StoryState revision and locked facts, commits a new revision, and writes the readable outline copy. Whole-version application requires a second confirmation after a manuscript exists. Neither application nor history restoration writes `manuscript/story.md`; restoration creates a new candidate and revision instead of deleting later history. The latest active `scene_briefs` and `short_causal_chain` artifacts become stale because they depend on the previous outline, while prose and character voice artifacts remain active. `ProjectStore.load_constraints()` includes the current confirmed outline with a 30,000-character cap.

The new-project wizard lists no more than 12 confirmed learning mechanisms. Rejected, unconfirmed, missing-source, and `competitor_work` mechanisms are excluded. Options are unchecked by default, and the confirm API revalidates selected IDs before creating project adoptions.

## Learning rules and recoverable versions

Confirmed learning mechanisms remain global library records until the user adopts them into a project. Adoption updates only that project's `creative_blueprint`; it does not merge into or replace `prose_baseline`, formal outlines, or manuscripts. Removing an adoption regenerates the blueprint without deleting the source mechanism or changing existing prose.

The effective-rules endpoint presents the order used by later generation: user locks, confirmed outline and project facts, platform requirements, prose baseline, adopted blueprint mechanisms, then advisory market data. Local checks report stale artifacts, explicit mode mismatches, similar adopted mechanisms, and recorded incompatible conditions. Post-generation usage status is deterministic and advisory; unsupported semantic mechanisms remain marked for human review rather than being reported as absent.

Learning artifact restoration is append-only. Restoring an older prose, voice, or knowledge version creates a new latest version containing the historical data; it never deletes intervening history or rewrites existing manuscripts. The project-readable JSON file continues to contain only the latest version used by `ProjectStore.load_constraints()`.

Legacy model attraction summaries that used a generic `claim` field are normalized when read so saved analysis remains visible without rerunning all text windows. New synthesis responses must use the displayable opening, goal, cycle, and ending fields. Invalid shapes retry through the configured synthesis fallback instead of being marked complete with empty-looking UI placeholders.

Starting a wizard from a reference preselects only that reference's user-confirmed mechanisms. When requested, project creation uses the existing planning role to create a candidate outline after adoption. The result remains an outline candidate and requires explicit application before it becomes authoritative.

## Log interpretation

- `checkpoint_reused`: prior complete artifacts were reused; generation did not restart from zero.
- `polish_max_tokens_retry`: a token-limited polish output is retrying at a strictly larger permitted budget, or is using the legacy ordinary-polish compatibility retry.
- `model_fallback`: the primary route failed and a configured model or role fallback is running.
- `polish_circuit_opened`: a successful fallback is reused for later segments in the same pass.
- `polish_input_sized`: estimated complete input size recorded before a provider call.
- `polish_segment_split`: a recoverable relay or repeated `max_tokens` failure caused only the failed segment to be split and retried.
- `polish_output_rejected`: local validation kept the original segment.
- `revision_plan_deferred`: a valid plan exceeded the per-batch 40% limit; current and deferred scene IDs are recorded separately.
- `revision_batch_continued`: the current batch passed local handling and the next saved batch is starting under the remaining round token budget.
- `revision_plan_blocked`: the plan was invalid, truncated, or lacked deterministic checks; no scene rewrite started.
- `token_budget_exhausted`: the next polish request was blocked by the round or cumulative input-token cap.
- `quality_revision_halted`: correction stopped and `best-candidate.md` was preserved.
- `polish_checkpoint_reused`: an interrupted pass reused an identical source segment from its own checkpoint.
- `polish_resume_ready`: the current run's planning, complete draft, review, and polish checkpoint position were accepted for resume.
- `review_max_tokens_retry`: an empty token-limited Review response is retrying the same route at 8,192.
- `review_configured_fallback`: the same-route Review retry stayed empty and the Review role fallback is running.
- `review_incomplete`: neither Review route produced usable output; no editorial score was fabricated.
- `quality_assessed`: includes source, total score, dimensions, decision, and hard-fail state.
- `final_review_model_failed`: configured terminal-review routes failed; the best candidate was preserved without a fabricated score.
- `final_review_result_rejected`: a terminal-review response arrived but failed local format or score validation; the best candidate was preserved and the original validation detail remains in event metadata.
- `final_review_reconciliation_recovered`: final adjudication returned a summary object instead of itemized reconciliation; matching stable issue IDs were recovered locally and any missing IDs remain unresolved.
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
