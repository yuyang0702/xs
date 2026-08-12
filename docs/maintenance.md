# Novel Flywheel Maintenance

## Narrative Reliability Kernel V5 operations

Planning fields now cross one `markdown-it-py` AST compiler before any local
gate. Tables, peer headings, decorated inline fields, and list cards project to
the same closed roles; JSON Schema and tool-call event records project to an
ordered, source-hashed event IR. Wrapper names are descriptive only. Duplicate
or reordered owners, competing field values, unknown machine-control keys, and
adjacent-event references never gain authority. Do not add a provider-, label-,
run-, or error-string branch to make a new packet pass; add an invariant-based
compiler topology and production-shaped regression instead.

Recovery is ordered by validation stage: transport, syntax, ownership, local
semantics, adjacent handoff, whole-story integrity, and quality. An earlier
stage may reveal a later existing defect, but a candidate cannot introduce a
same/earlier defect or expand a new boundary issue into an unchanged segment.
Event-body ownership is repaired per complete segment with two bounded attempts.
The Runtime preserves outline basis, event order, opening, handoff, and all
unaffected segment bytes. Exhaustion retains the best complete plan and never
falls back to a whole-plan rewrite for this failure family.

`workflow_node_checkpoints` version 2 stores the highest completed validation
stage. Migration is additive and idempotent: a version 1 `validated` row becomes
`promoted`; generated or failed rows remain at transport. Stage regression and
conflicting promoted output are rejected. A generated model response is still
not formal authority, and formal manuscripts remain writable only through the
existing atomic promotion journal.

The model page intentionally has no editable context-window, maximum-output, or
structured-output downgrade fields. Route capabilities are observed for the
exact protocol/base URL/auth headers/model fingerprint, expire after seven days,
and degrade to locally validated safe mode when stale. A third-party 404 means
the endpoint/protocol path must be checked; it does not prove that the model is
absent. Re-run the bounded probe after correcting the route, without replacing
the saved key or binding.

Before a production restart, run the complete offline suite and the L3 change
gate, then verify SQLite has no `queued`, `running`, or `cancelling` run. Live
acceptance may use only minimal synthetic prompts and must not include novel
content or expose credentials. Rollback is non-destructive: keep formal files
and StoryState, disable the affected route or revert the V5 feature code, and
resume from the hash-bound best candidate/checkpoint.

## Route-local structured artifacts and third-party gateways

Structured-output support is configured and probed per provider/model route. Runtime
never infers JSON Schema, JSON-object, or forced-tool support from names such as
OpenAI, Gemini, Claude, GPT, or an advertised upstream model. Missing, `auto`, and
unknown capability values are treated as `plain_text`. The saved values are
`plain_text`, `json_object`, `strict_json_schema`, and `strict_tool`; strict workflow
requirements may use only the latter two and may fall back only to another explicitly
strict saved route.

The provider connection probe uses minimal synthetic payloads and no novel content.
It first verifies the route, then distinguishes strict schema, forced tool, JSON
object, and plain text. A 404 or "API does not exist" response is not a model-removal
verdict: check whether the base URL already owns `/v1`, whether the third-party
gateway implements Chat Completions, Responses, or Anthropic Messages, whether it
requires streaming, and whether gateway-specific headers are present. Do not alter
role bindings or secrets during diagnosis. Persist a capability only after that exact
route succeeds.

Optional tool calling and strict forced-tool output are different capabilities. A
thinking route may accept a tool list and voluntarily call one while rejecting a
named `tool_choice`; record its ordinary tool support, but do not mark it
`strict_tool`. Strict workflow routing requires one forced, uniquely named tool call,
so an optional-only primary is skipped before the paid request and an explicitly
strict fallback is used.

Planning presentation repair now asks the model only for ordered creative event
narratives. Segment identity, outline basis, packet ownership, opening/closing
boundaries, hashes, retry budgets, and checkpoint identity remain Runtime-owned.
Runtime rejects unknown fields, duplicate or reordered event IDs, and incomplete
narratives, reconstructs the canonical segment from current accepted authority, and
reruns the unchanged full planning validator before downstream use. Existing
Markdown and open-wrapper readers remain read-only compatible for old checkpoints.

Operational rollback is non-destructive: change the affected model route's structured
output setting to `plain_text`. Native schema/tool parameters stop immediately while
legacy local validation remains active. Probing and capability changes do not rewrite
StoryState, outlines, formal manuscripts, historical runs, bindings, or stored keys.
See `docs/superpowers/specs/2026-08-08-route-local-structured-artifact-design.md` for
the authority boundary and acceptance contract.

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

Semantic packet recovery preserves the typed primary and fallback route failures when an indivisible packet cannot run. In particular, a credential-store identity mismatch remains `provider.credentials_unavailable` instead of being replaced by a generic packet-validation error; validated packet prefixes stay reusable and resume retries only the blocked packet after the same Windows user can read its credentials again.

The launcher also verifies a source-tree runtime fingerprint in `/api/health`. A process that points at the same data directory but loaded an older source tree is never silently reused: the launcher keeps the old process and its active task intact, reserves the next free local port, and starts the current code there. This prevents a fixed recovery path from appearing to recur merely because an already-running console still has the pre-fix code in memory.

Planning recovery keeps semantic defects separate from route-execution failures. If a repair call cannot run because the primary or configured fallback credential/binding is unavailable, the recovery checkpoint retains the best plan and records the route failure; the terminal event is `planning_adaptation_unavailable`, not a new planning-drift verdict. A later resume retries only the affected planning repair after the same runtime can resolve its credentials. Context-capacity and transport failures follow the same rule: they do not consume semantic progress or authorize partial narrative content. Provider-route exhaustion preserves both primary and fallback errors so the production incident catalog can classify the actual infrastructure family.

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

## Project trash recovery

Restore treats `project.json.id` as the project-directory identity. If an interrupted restore has already moved the directory back to its recorded original path but the database still marks it as trashed, Runtime clears only the stale trash record after confirming the ID; it does not move or rewrite project files. If matching complete project directories exist at both paths, the original directory becomes active and the trash copy remains untouched. A later delete uses a unique trash path instead of overwriting that retained copy. If the original path has no `project.json`, Runtime preserves that derived shell under `trash/restore-conflicts/` before moving the complete trash project back. Another project's directory, an unreadable `project.json`, or a missing trash directory stops recovery and reports the preserved locations; no restore path overwrites or deletes either copy.

Candidate analysis rechecks the active project registry after local analysis and before writing its cache. If the project entered trash while the request was running, the in-memory report may finish for the open page but no old project path is recreated. Learning mechanism list fields accept legacy single-text values at the read boundary; `both` becomes short and long, and stages, genres, and incompatible conditions become lists before project adoption or page rendering. The browser keeps a defensive list conversion so an old stored result cannot break the entire learning page.

The console treats market data, reference analysis, and confirmed learning methods as pre-project work. Starting another project is always available from the workbench, while project-only outline, writing, revision, and publication controls remain scoped to the selected project and are hidden behind a clear empty state when no project exists.

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

Short stories may carry an active short_causal_chain project artifact. It is a whole-story causal index, not a replacement outline and not a per-chapter template. It stores the core goal, repeatable obstacle-effort-result cycles, accidents, reversal evidence, and ending payoff. Planning may append this JSON between SHORT_CAUSAL_CHAIN_JSON_START and SHORT_CAUSAL_CHAIN_JSON_END; Runtime extracts it, saves diagnostics, and rewrites planning.md back to ordinary outline text. A missing, malformed, incomplete, or stale chain is regenerated as a separate hash-bound artifact from the final accepted plan. `short-execution-index.json` remains `causal_pending`, and drafting cannot start, until event coverage and semantic validation pass. The compact chain is then added to draft and final-review context so the manuscript can be checked for goal setup, state-changing cycles, accident, reversal evidence, and ending payoff.

Learning mechanisms with mechanism_type="causal_structure" are stored in creative_blueprint.causal_structure. They are abstract structure advice only: they cannot directly change project facts, formal outlines, or manuscripts, and must not transfer source names, settings, concrete plot packaging, or unique expression.

Reference sources are not project facts and never write StoryState. Pasted text and browser-read UTF-8 TXT content are stored under `data/references/<source-id>/` with immutable version files; SQLite stores titles, hashes, version metadata, and local-analysis results. Identical normalized content resolves to the existing source rather than creating another copy. API responses omit storage paths and expose source text only through the controlled content endpoint.

DOCX extraction uses the standard library; PDF extraction uses `pypdf`; public URLs use bounded `httpx` requests with public-address checks before every redirect. Imported page text remains untrusted data. Scanned PDFs are rejected rather than silently returning empty prose.

The typed graph lives in `learning_nodes`, `learning_edges`, `learning_evidence`, and `learning_revisions`. Project decisions and versioned derivatives live separately in `project_adoptions` and `project_learning_artifacts`. Deleting a source marks graph nodes and existing adoptions for review before deleting source versions. It never rewrites project files.

Adoption classification is Runtime-owned. The immutable `learning_nodes.node_type`
selects the mechanism, attraction, or style bucket; editable adoption data may
refine a mechanism subtype but cannot change `node_type`, `mechanism_type`,
provenance, or another classification field. Creative blueprints, compact
creative recipes, and outline-generation context all use the same classifier.
Legacy adoption JSON with a conflicting marker therefore stays in its original
node-type bucket and cannot turn a prose rule into a plot method.

SQLite is the authority for versioned learning artifacts. Sidecar JSON is a
monotonic, human-readable projection: insertion and projection are serialized
through SQLite's cross-process write transaction, the projector rereads the
latest database version before writing, and readers repair a missing, stale, or
hash-mismatched sidecar from that latest row. A delayed old writer can never
replace a newer projection. Workflow checkpoint read/validate/attempt/upsert is
likewise performed under `BEGIN IMMEDIATE`, so concurrent retries cannot lose an
attempt or both accept conflicting validated authority.

Active project artifacts are appended by `ProjectStore.load_constraints()` and therefore use the existing planning, draft, review, and polish routes. Stale artifacts are excluded. Candidate outlines and line edits stay below `<project>/learning/`; formal outlines and manuscripts are never direct targets.

`reference_analysis`, `reference_synthesis`, and `line_edit` are normal role bindings with configured fallbacks. Only explicit UI actions call them. Regression examples in `src/novel_flywheel/quality_regression.json` and all automated tests remain provider-free.

Optional LTP lifecycle endpoints are under `/api/settings/local-nlp`. Installation never runs during startup or migration. Enabled analysis launches `novel_flywheel.nlp_worker` as a bounded process, caches results by text/version hash, and returns rule-only fallback metadata on failure.

The `local-editorial` analyzer is deterministic and provider-free. Reports are cached by source version, content hash, analyzer name, and analyzer version. Current findings are advisory `review` items: exact phrase reuse, functional repetition, long dialogue-only runs, unusually regular sentence rhythm, and short checklist-style judgment chains. A source deletion cascades its versions and analysis rows, then removes only its verified directory below the reference root.

No local generative model is installed or supported by this feature. A later optional Chinese NLP backend requires an explicit Settings installation action, runs one CPU analysis job at a time outside the FastAPI process, and must fall back to these standard-library rules when absent or unhealthy.

`materials-audit` compares paragraph-aligned manuscript windows against the current project materials through the configured final-review route. Each completed window writes a source-hashed checkpoint. Restarting the check resumes the latest failed or cancelled audit, reuses unchanged windows, and rechecks windows whose manuscript, constraints, or project reference changed. If the primary route fails and its configured fallback completes a window, the remaining windows in that audit use the fallback directly; that circuit state survives a resume and resets for the next new audit. It records evidenced contradictions in `conflict-report.json` and the versioned issue ledger, but never edits prose. `materials-repair` consumes the latest completed audit, uses structural targeted polish, runs the full-manuscript terminal review, and writes `best-candidate.md`. It never replaces the formal manuscript; publication remains an explicit user action.

Short-story scene separators remain internal to drafting and are never written into the reader-visible candidate or formal manuscript. Each passed narrative-integrity artifact binds both the internal segmented draft hash and the clean publication hash, plus the exact character length and text hash of every formal segment. Targeted/manual revision reconstructs the clean manuscript's segment boundaries only when all lengths, hashes, manifest ownership, and rejoined publication bytes agree; a mutation that crosses or removes a boundary is rejected. Every accepted revision then writes fresh segment hashes, publication lengths, segment receipts, and a whole-draft receipt, so later polish, repair, resume, and promotion cannot inherit stale atomic-beat authority.

Ordinary polish classifies each failure before choosing recovery. Explicit input-context overflow is the only reason to replace the full request with the compact authority request. A provider `max_tokens`/length finish retries the same route and identical prompt with dynamically expanded output headroom; if the retry is still limited, only that source segment is split at a safe paragraph boundary. A timeout, disconnect, `502`, `504`, `524`, or other transport interruption retries the same route once and then the configured fallback once. Transport failures never establish a provider ceiling and never cause prose splitting. Authentication, missing-key, missing-provider/model, and invalid role-binding errors stop immediately, including when nested inside route-exhaustion errors. Cancellation always propagates.

Both full and compact requests carry the same lossless `PolishAuthorityPacket`: the complete source segment, event ownership, causal goal, previous accepted exit, next source entry, character and knowledge state, locked facts, ending constraints, promises/payoffs, narrative state, project style rules, protected passages, and allowed edit range. Advisory findings may be shortened, but authority fields are never sliced, and the source appears exactly once after `MANUSCRIPT SEGMENT`. An accepted checkpoint binds both the source hash and authority-packet hash. A changed outline, state, boundary, lock, style rule, or ending invalidates the old checkpoint without rewriting project files.

Safe split recovery is parent-atomic. Child outputs and child checkpoints are diagnostic until every child passes local validation and the merged parent passes length, prose, duplicate-block, locked-fact, passage-protection, and authority checks. One failed child or a rejected merged parent preserves the complete parent source and writes only a non-authorizing `accepted: false`, `status: preserved_source` parent checkpoint. Resume reuses only accepted source-and-authority hashes and retries preserved parents. Legacy checkpoints remain readable by legacy callers, but an authority-aware resume conservatively regenerates checkpoints that lack the authority hash.

Complete candidates follow layered validation. Length, production-text corruption, required literals, locked facts, protected passages, and narrative authority are hard constraints and reject immediately. Rhythm, dialogue, scene-transition, and style signals are deduplicated by family. A small advisory shift passes; a project-authorized local beat may pass with a named style allowance; actionable soft evidence receives one local repair request containing only the evidence plus the complete authority packet. It does not trigger an unrelated whole-segment rewrite. A failed local repair preserves the parent source.

Every single-request review, full-review window, incremental-review window, and final adjudication is parsed locally before it is accepted. A malformed or truncated JSON response retries only that request through the final-review role's configured fallback and records `final_review_json_fallback`. If both full-format routes remain incomplete, Runtime makes one compact recovery request, records `final_review_compact_recovery`, and never joins partial JSON fragments. Completed windows and the preserved best candidate are not discarded. If snapshot rollback itself fails, `snapshot_restore_failed` records that secondary failure without replacing the original model or validation error.

If final adjudication returns a readable reconciliation summary object instead of the required item list, Runtime recovers only issue entries whose stable IDs match the prior ledger and records `final_review_reconciliation_recovered`. Missing IDs still trigger the existing conservative evidence cap; recovery never treats an omitted issue as resolved and does not call a model again.

Candidate quality displays `effective_words` as its primary count: each Han character, contiguous Latin word, or contiguous numeric token counts once; punctuation, whitespace, and Markdown punctuation are excluded. Pure `han_characters` and total Unicode-code-point `characters` remain visible as secondary metrics and remain available in the API for compatibility.

Wizard interviews persist the user's answer before calling the planning model. Retrying the same unanswered message resumes the model call without duplicating history, and provider connection failures are returned as readable `interview_model_failed` responses.

For short stories, the project-list `Continue writing` action resumes the most recent failed or cancelled run with the same run ID. Recovery checks that run's own complete planning, draft, review, and source-hash polish checkpoints before older runs. A reusable planning-and-draft checkpoint writes `short-checkpoint.json` last and binds the exact planning and draft hashes to the complete formal-outline hash, loaded-constraints hash, StoryState revision, target length, and segment count. Lookup must match every bound value; legacy checkpoints without this fingerprint and malformed or edited artifacts are conservatively regenerated. The current run may reuse its own valid checkpoint, while cross-run lookup considers only failed or cancelled source runs; completed, running, and queued runs never seed an explicitly new run. Editorial review remains reusable only from the same source run as the accepted planning-and-draft checkpoint. Completed stages are not regenerated; `polish_resume_ready` reports the first missing or source-mismatched polish segment and the count of valid checkpoints, even when accepted checkpoints are non-contiguous. Only a missing or structurally incomplete artifact is regenerated. When no resumable run exists, the action only opens the workbench; starting a new complete story remains an explicit workbench command.

Style-sample analysis keeps failures visible in the workbench. If the planning model's first response is not the required JSON profile, the service makes one bounded formatting-repair call before rejecting it.

The legacy style-sample endpoints and files remain for compatibility, but their workbench uploader is retired. Reading `/api/projects/{id}/learning` lazily converts an existing `style-samples/profile.json` into the first `prose_baseline` version without deleting legacy files. Once migrated, `ensure_style_profile()` omits the managed `STYLE_SAMPLE` block from assembled runtime context so the baseline is not injected twice. The workbench is read-only and all later changes belong in the learning library.

Run context display is derived from existing events and receipts and stores no duplicate prompt, secret, or header data.

## Short-story model route

### Planning packet presentation compatibility

Planning recovery treats the provider's packet shape as presentation, not a
second narrative authority. In addition to the canonical Markdown segment,
the shared normalizer accepts a single complete JSON object, a single complete
top-level JSON event array, and an explicit `SEGMENT-ONLY` Markdown packet.
JSON arrays are accepted only when the whole response is one array (optionally
inside one fenced block or HTML-comment wrapper); multiple payloads, mixed
prose, missing segment identity, reordered event IDs, or missing entry/exit
state fail closed. Array event bodies may be projected from a summary, beats,
and obligation-coverage descriptions, but adjacent event IDs mentioned in
that prose are descriptive references and are removed before Runtime adds the
one explicitly owned event ID.

Every accepted projection is rendered back to the canonical segment format and
re-enters the existing event-body, obligation, retention, adjacent-handoff,
and whole-plan validators. A harmless wrapper repair therefore does not bypass
semantic or story-wide checks, and an ambiguous packet consumes only the
current smallest-scope protocol retry while the retained best plan remains
authoritative.

Planning identifiers and headings share one offset-preserving Unicode protocol
view. One-code-point NFKC width variants, Unicode dash families, Unicode slash
families, and narrow/non-breaking spaces compare canonically without rewriting
free prose. Formal IDs such as `EV‑BEAE4985‑B01` bind to the base event
`EV-BEAE4985`, while removal uses original-source offsets so adjacent narrative
text is unchanged. Root headings are recognized from segment identity rather
than a finite suffix list: `第5段计划：...`, `SEGMENT 5 ...`, `Planning Segment
5 ...`, and reversed labels such as `段规划：第5段/...` are accepted when they
declare exactly one segment. Nested self-check headings do not create another
formal segment, and a root heading that claims two segment identities fails
closed.

Capability probing uses the provider's structured-output request for JSON and requests a specific probe tool for tools. OpenAI Responses forwards that specific tool through its native `tool_choice` shape. Moonshot OpenAI Chat requests disable thinking when structured output or a specific tool is required, matching the provider's compatibility contract and the same requests used by real workflow stages. Providers that reject or ignore forced `tool_choice` are retried once with automatic tool selection, so lack of forced-choice support is not misreported as lack of tool support; unrelated tool errors remain visible.

The short-story workflow reuses complete planning, draft, and valid review checkpoints after a failed or cancelled run.

Initial short-story planning uses the complete wizard/project brief directly and does not call StoryToolbox while StoryState is still at revision 1. Those lookups are empty before a manuscript has been committed and would add a second provider round without adding evidence. Planning for an established project retains StoryToolbox access once authoritative state has advanced.

Polish receives one bounded manuscript segment and one lossless narrative-authority packet plus stage-specific compact Skills and constraints. Ordinary expression polishing cannot change plot events. Runtime rejects abnormal length changes, required-literal loss, locked-fact conflicts, and protected-passage edits, preserving the original segment.

Chinese sentence metrics split sentences inside a paragraph on supported terminal punctuation instead of treating one paragraph as one sentence. Headings and quoted dialogue are excluded from narrative short-sentence runs; dialogue-only runs and timestamp scene fragments remain separate signal families. This parser is a deterministic validation boundary, not a prose rewriter: punctuation inside the manuscript is not normalized merely to make a candidate pass. Table-driven tests cover Chinese/ASCII punctuation, multi-sentence paragraphs, dialogue, headings, and legacy one-sentence paragraphs.

Rhythm and related style signals use source-relative metrics plus up to five accepted preceding windows. The robust rolling baseline changes only soft thresholds and never weakens facts, locks, length, or protected passages. Confirmed `style-profile.md` and an active `learning/prose_baseline.json` may authorize short rhythm at named structural beats such as information reveal, relationship change, suspense payoff, emotion shift, or comic turn. Market advice and genre names cannot authorize an override. Projects without either artifact use conservative defaults; conflicting prose rules fail closed.

Ordinary polish remains sequential. The full review is compacted once, then each prose window receives only matching issues plus the lossless authority packet. After a window is accepted or preserved, Runtime derives the next prompt's handoff state from that actual output; the next original opening and previous accepted exit remain boundary authority. This does not assign seven-step structure to small polish windows and does not create another StoryState authority.

### Token budgets

| Stage or route | Output limit |
|---|---:|
| Planning | 12,288 |
| Draft | 8,192 |
| Review | 4,096 |
| Revision plan | 8,192 |
| Configured polish route | Quality-sized initial budget capped by selected model's declared ceiling and remaining context |
| Polish route without a declared ceiling | Quality-sized initial budget; one same-route expansion up to the runtime discovery bound |
| Final review | 8,192 |
| Maintenance extraction | 4,096 |

Polish output budgets are quality headroom, not a spend cap. The initial budget is derived from expected prose size. A declared route ceiling and the remaining configured context window cap that request. If the ceiling is unknown, Runtime does not make a paid probe or assume 8,192: it sends the quality-sized request, and an explicit output-limit finish retries the same route once at the larger of `current + 1,024` or `current × 2`, bounded by the 65,536 discovery limit and any known remaining context. A second output-limit finish triggers semantic paragraph splitting. Input compression is not used for output truncation. Review retains its separate JSON compatibility retry.

For input sizing, a known context window uses two thresholds. A full request at or above 75% after reserving output headroom switches to the compact authority request before the provider call. If even the authority request reaches 80%, the segment is split rather than slicing authority. With no context-window metadata, Runtime never guesses: it tries the full request first and compacts only after an explicit provider context-overflow rejection. Model reasoning is provider-internal and cannot be predicted directly; reserving the selected output budget is the conservative allowance for generated prose and hidden reasoning where a provider accounts for both under the same window.

Review starts with its normal 4,096 output limit. An empty Review response with `finish_reason=max_tokens` retries the same model route once at 8,192 with compact JSON-only instructions. If it remains empty, only the Review role's configured fallback is used. Planning is never used as an editorial-review substitute. If both Review routes fail, `review_incomplete` preserves the draft and existing polish checkpoints without creating an editorial score.

HTTP `524` means the relay reached the upstream model but timed out waiting for a response. It is not a manuscript validation error. The configured fallback handles it without modifying the formal manuscript.

Provider calls use streaming transport for Anthropic, OpenAI Chat, and OpenAI Responses protocols. Each adapter consumes provider-native SSE events and aggregates them into the existing `ModelResponse`, so workflow and browser behavior remain unchanged. OpenAI Chat retries streaming without `stream_options` when a relay rejects that optional parameter; providers that explicitly reject `stream` fall back to the existing non-streaming request. A stream that disconnects after partial output is treated as failed rather than accepting an incomplete manuscript.

## Linked project-material updates

When a character profile is saved with "retire removed settings" enabled, the application stores the before/after change under `.novel-flywheel/material-impacts/`. Saving the profile and syncing its basic StoryState fields complete before model analysis starts. A failed or interrupted analysis can be retried and does not roll back the profile edit.

The `maintenance` role compares the change with project material files only. Candidate patches must identify a project-relative file and an exact existing excerpt. The API rejects paths outside the project, model excerpts that do not exist, empty replacements, unchanged replacements, files modified since analysis, and empty selections. Applying selected patches creates a project snapshot, writes only the selected material excerpts, synchronizes affected StoryState sections, and resolves the candidate. Formal manuscripts and run candidates are outside this operation.

The initial-polish input circuit breaker is the larger of 120,000 or 20,000 per generated segment, so smaller adaptive segments can complete the manuscript. Structural correction remains capped at 60,000 per round, and correction count remains bounded by the quality route. There is no conflicting fixed cumulative cap across resumed and corrective rounds. Runtime counts every returned polish receipt before starting the next segment, including responses later rejected for output limit or excessive length. Provider-side failed calls without usage metadata cannot be counted exactly and are never assigned fabricated usage.

Structural plans contain literal checks for hard issues and preserve the model's task priority. Runtime applies no more than 40% of stable `scene-NN` scenes in one batch; valid targets beyond that limit retain their tasks and continue in later batches under the same correction-round token budget before final review. A truncated or otherwise invalid plan does not fall back to an all-scene rewrite. It halts correction, writes the best available text to `outputs/best-candidate.md`, and leaves the formal manuscript unchanged. Exact consecutive multi-paragraph duplicates are removed locally; semantic near-duplicates remain review findings.

Before a resumed quality pass rewrites `quality-report.json`, Runtime reads the existing `best_score` together with `best-candidate.md`. That pair becomes the new pass's minimum checkpoint. Lower-scoring retries may be recorded for diagnosis, but failure, provider interruption, or invalid revision planning restores the earlier higher-scoring text. The `quality_best_restored` event tells the UI which score is protected.

Revision planning compacts its Skill and constraint prompts. Malformed JSON first receives a schema-only repair request containing only the malformed output and schema identifier. Empty, truncated, semantically invalid, or still-invalid repaired plans retry through the `review` role. A valid plan that covers too many scenes is batched locally and does not spend a fallback model call. If the fallback result is also invalid, `revision_plan_blocked` stops correction. This is a role fallback, not a full-manuscript rewrite retry.

Ordinary polish targets about 1,400 characters and normally stays below 1,800, splitting only at existing paragraph boundaries. A single oversized paragraph is preserved instead of being cut mechanically. Before each provider call, Runtime estimates the complete system and user input. A known-window 75% warning or explicit context-overflow response compacts discardable advisory, Skill, and constraint material while the complete authority packet remains intact; an 80% authority-fit failure splits or preserves rather than slicing authority. Structural correction does not reuse ordinary prose chunks: each targeted `scene-NN` is sent exactly once unless an input/output capacity failure requires safe paragraph splitting. Structural candidates use a 60%-180% length contract; ordinary candidates use 70%-160%. Rejection metadata includes absolute bounds and a short candidate preview. Prompt metadata always appears before `MANUSCRIPT SEGMENT`; source prose is last.

Failure recovery is class-specific. Transport failures (`502`, `504`, `524`, timeout, disconnect) retry the same route once and then the configured fallback without splitting. Output-limit finishes expand the same route once and then split the failed parent semantically. Explicit context overflow switches to compact authority first and splits only if authority still cannot fit. Ordinary invalid output may use the configured fallback with the same full or authority prompt; hard local validation failures do not trigger another whole-segment rewrite. Authentication and configuration failures stop transparently. Polish never silently switches to the Draft role.

Rejected candidates write only a non-authorizing preserved-source checkpoint for progress display. `_load_polish_checkpoint()` ignores it, so a later resume retries the source instead of mistaking the preserved original for a completed edit.

Structural correction has two length thresholds: a preferred floor of 60% and a hard rejection floor of 50%. Candidates between them emit `polish_conditional_length` and continue only to final review; they are not auto-committed. Before executing a structural plan, Runtime also re-checks each `forbidden_text` against the full manuscript and can move that repair task to the scene that actually contains the text, logging `revision_targets_aligned`.

## Full-manuscript final review

Short manuscripts up to one 6,000-character window are sent to `final_review` in full. Longer short stories are split into paragraph-aligned 4,000-6,000 character windows with overlap. The default window pass returns only a bounded summary and evidenced issues; it does not assign the book's final score. Local narrative-ledger uncertainties or prior cross-window issues automatically select relevant windows for a separate bounded events, character-state, timeline, and promise/payoff pass. Final adjudication receives the merged evidence and performs cross-window consistency checks. This uses the existing `final_review` role and adds model calls only when local or prior evidence requires them.

Initial editorial issues receive content-derived stable IDs plus source, repair goal, and status. Revision-plan tasks preserve related `issue_ids`. Incremental adjudication must mark every prior issue exactly `resolved`, `unresolved`, or `uncertain` with evidence. Missing or invalid reconciliation, incomplete coverage, or insufficient evidence triggers the complete-review fallback. An unresolved or uncertain major issue cannot pass incrementally.

Final review uses only the `final_review` role and its configured provider fallback. It never switches to `planning`. A provider failure records `final_review_model_failed`; a model response rejected by local JSON or score validation records `final_review_result_rejected`. Both paths write `best-candidate.md` and leave the formal manuscript unchanged. A complete `zhihu-short-v2` criteria set is authoritative and is scored locally without requiring legacy `score` or `dimensions` fields. The output limit remains 8,192 tokens. A typical 20,000-character story uses several 6,000-12,000 input-token requests and roughly 40,000-70,000 cumulative input tokens.

An empty `final_review` response is treated as an incomplete report at the same recovery boundary as malformed JSON. This applies to every manuscript window, optional detail pass, and final adjudication request: Runtime tries the configured fallback for that exact request, then uses the existing compact recovery request if both full-format results remain unusable. Other provider failures keep their existing route-exhaustion behavior and are not retried again at the workflow layer.

The run detail context exposes manuscript coverage, reviewed window count, reconciliation counts, local gate reasons, compact-report recovery status, and whether detailed event/foreshadowing analysis ran from `quality-report.json`.

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

The full-candidate length gate always includes the exact Han-character count of the already accepted protected source. If that source predates the current target policy or legitimately sits just outside the configured range, a non-length repair may keep or improve its length but may not worsen the existing deviation. This prevents a one-line semantic repair from becoming impossible solely because an upstream accepted manuscript is over or under today's nominal target; ordinary configured limits remain unchanged when the source is already inside them. A selected length-deficit issue is different: Runtime calculates its expansion deficit from the platform's nominal minimum rather than the source-admissible repair range, so the dedicated draft-scene route still fills the real publication gap while unrelated revisions never invoke expansion implicitly.

For a selected short-story length issue whose protected candidate is below the active platform minimum, Runtime calculates the exact Han-character deficit locally and routes it through `revision_plan`, then through the existing `draft` role once per planned scene; it never uses ordinary polish for this expansion. The frozen repair contract also captures the active seven-step causal-chain artifact. Planning receives at most 24 exact, unique paragraph-or-sentence anchors sampled across the current candidate, each with its character position and a preview capped at 160 characters; it does not receive the whole manuscript again. Every scene plan must choose from that catalogue and provide a purpose, positive Han target, entry and exit state, insertion operation, time, evidence source, transition, a list containing only trimmed non-empty fact strings, and `requires_full_review=true`; all scene targets must sum to the local deficit. Resume rebuilds the same bounded catalogue from the current checkpoint candidate and rejects a stored anchor that is no longer allowed. Each draft must satisfy its local length bound and reproduce the planned state/evidence fields before the normal patch group is applied atomically. The plan and each accepted scene draft are checkpointed, so provider failure or cancellation resumes only unfinished scenes. Invalid plans or drafts remain local rejections at `waiting_local_fix`.

An accepted expansion patch group carries `scene_inserted` and `requires_full_review`, and `repair-report.json` therefore records `review_mode=full` with `scene_inserted` in `full_review_reasons`. The targeted-revision run still stops at `waiting_confirmation`: it makes no terminal-review call and does not update the protected best, quality checkpoint, formal manuscript, StoryState, passage permissions, provider configuration, credentials, or history. The full-review marker is consumed only by the later confirmation/finalization workflow.

After all available groups are processed, the complete temporary candidate passes through local manuscript analysis and the whole-candidate gate. A failed gate leaves the run at `waiting_local_fix`; a passing gate leaves it at `waiting_confirmation`. Neither state is `completed`, neither calls terminal review, and neither writes `best-candidate.md`, `manuscript/story.md`, passage permissions, or StoryState. Only a targeted route exhaustion is recorded as `model_routes_failed`; malformed JSON, an invalid repair contract, or an atomically rejected patch is a local rejection that remains at `waiting_local_fix`. An unexpected local error writes a safe failed checkpoint and stops immediately instead of continuing other groups. User-facing events and reports explain these categories in Chinese without including raw provider or local exception text; event metadata contains only the group ID and a safe category.

The revision API exposes `POST /api/projects/{project_id}/revisions`, `GET /api/runs/{run_id}/revision`, group `adopt` and `reject` posts, `POST /api/runs/{run_id}/revision/finalize`, and the existing run `resume` endpoint. Group decisions persist `decision` and `decision_candidate_hash` in `patch-groups.json`; rejection also persists `issue_status=unresolved`. `repair-report.json` exposes only the candidate hash, gate, `review_mode`, `full_review_reasons`, `next_action`, and public group summaries such as before/after text, local checks, decision, and issue state. Internal prompts and raw provider errors are never returned.

Finalization requires every semantic or expansion group to have a hash-bound decision, replays adopted groups from the frozen source, reruns the whole-candidate gate, and atomically claims the existing `running` state before terminal review. A second finalize request cannot review or publish concurrently. After the awaited review returns, Runtime reloads the complete repair authority and rechecks the protected run/hash, StoryState revision, locks, contract hash, groups hash, candidate hash, and decisions before quality comparison or checkpoint writes. Strict promotion still requires the same profile and judge, a score gain of at least two, no dimension regression beyond three, no new unresolved major issue, and every mandatory issue resolved. Any local, review, authority, or checkpoint-write failure preserves decisions, does not alter the prior protected manuscript, formal manuscript, StoryState, or locks, and leaves the same run resumable.

Promotion writes a run-scoped snapshot journal before changing repair artifacts; its manifest is atomically replaced and synced before production mutation. The hash-validated `outputs/candidate.md` quality checkpoint is the commit marker. Recovery handles a valid marker first: it completes SQLite and event projection without loading the journal, then discards any journal best-effort. Without a marker, a valid journal is restored; a missing, malformed, or truncated UTF-8 manifest means snapshot creation stopped before production mutation, so the partial journal is discarded without changing repair artifacts.

`quality_records.QUALITY_CHECKPOINT_LOCK` is the single process-wide reentrant writer lock. Direct checkpoint writes, complete legacy reconciliation, ordinary quality promotion, targeted protected-source reselection and comparison, targeted marker writes, and promotion recovery all use it. This prevents legacy reconciliation from changing protected authority between targeted reselection and marker creation while allowing reconciliation to call the locked writer recursively.

For a `short-revision` run, `_stage` emits fixed Chinese `review_incomplete` and `stage_failed` messages without raw exception metadata. Configured and role fallback events keep route identifiers but omit `primary_error` and `error`. Other workflows retain their existing diagnostic metadata. Internal model receipt files remain unchanged; the run-detail API does not expose them as tool receipts.

Rollback does not require deleting project data. Disable the Zhihu platform profile to return future reviews to `legacy-v1`; v2 checkpoints and reference-group history remain on disk and are ignored by the legacy comparison path. Remove or deactivate passage locks separately if revisions should stop enforcing them. Do not delete `quality-checkpoint.json` merely to lower a protected score: restore a prior manuscript through the existing candidate/revision flow so the new content receives its own hash-bound review.

### Evidence-driven local analysis versions

- `learning-window-v2` invalidates local extraction caches when windowing behavior changes. It records full-text coverage ranges and multiple evidence occurrences. Old confirmed/adopted nodes remain intact; operators must not bulk-delete them during cache maintenance.
- `reference-model-window-v2` checkpoints every successful model-analysis window as a `model_claim`. Version 2 separates prose evidence from plot hooks and requires every prose observation to name its rule category, so version 1 windows are reanalyzed instead of being reused as false prose evidence. Resume rebuilds the current dynamic window list and reuses only claims with the same content type, analysis version, exact window-text hash, and a still-valid Chinese result shape. A new source version can reuse unchanged windows; changed or newly split windows run again. Single-version legacy claims may be upgraded only when their index and boundaries exactly match, which preserves interrupted analyses created before checkpoint metadata existed.
- `manuscript-analysis-v3` adds advisory market comparison, full-text local ledger data, and a hash-bound narrative ledger. A stale text hash cannot approve an incremental review.
- Market cohorts count each confirmed linked work once per platform/ranking/category/length group. Missing or fewer than five samples disable guidance without blocking project creation.
- The selected market baseline is copied into outline generation as a bounded advisory reference and into outline comparison as non-blocking opening-signal and mechanism hints. It never overrides user locks, confirmed facts, or the formal outline, and it is omitted when the project has not explicitly enabled market guidance.
- Rejected-node deletion is intentionally narrow: only rejected nodes with no project adoption are eligible. The transaction cascades graph evidence, edges, and revisions but never source versions.
- Narrative relation changes add both endpoints to the incremental scope. LTP absence, ambiguous mapping, broad changes, or important structural changes continue to force full review.

## Outline versions

The `outline` object inside StoryState is the authoritative formal outline. It contains content, outline version, source, candidate ID, timestamp, and content hash. `<project>/plot/outline.md` is an atomic readable copy, not a second authority. Existing projects without a StoryState outline expose the latest completed run's `outputs/planning.md` read-only as version 0; it is not migrated or rewritten until the user applies a candidate.

Outline candidates use the existing `story_candidates` table with kind `outline` and content files under `<project>/learning/candidates/`. Editing updates the candidate hash and metadata. Local comparison uses heading or paragraph blocks and standard-library sequence matching. It reports additions, removals, edits, moves, and uncertain matches without calling a model. Semantic review is explicit, uses only the configured `planning` role, sends only uncertain complete change units plus the complete locked-fact authority, and validates exact returned ID coverage before displaying it. Runtime packs at most ten changes per request and lowers that count when the shared route-capacity plan requires it. It never keeps only a text prefix or the first N locked facts; an indivisible change that exceeds every configured route is retained and rejected before a lossy request is made.

Applying selected changes or a whole candidate validates the current StoryState revision and locked facts, commits a new revision, and writes the readable outline copy. Whole-version application requires a second confirmation after a manuscript exists. Neither application nor history restoration writes `manuscript/story.md`; restoration creates a new candidate and revision instead of deleting later history. The latest active `scene_briefs` and `short_causal_chain` artifacts become stale because they depend on the previous outline, while prose and character voice artifacts remain active. `ProjectStore.load_constraints()` is now an authority loader rather than a prompt compactor: it returns the complete confirmed outline, execution plan, confirmed facts, and every active learning artifact. Semantic packet builders own capacity projection; the authority layer no longer truncates at 30,000/40,000 characters or silently skips a later active artifact.

The new-project wizard lists no more than 12 confirmed learning mechanisms. Rejected, unconfirmed, missing-source, and `competitor_work` mechanisms are excluded. Reference-scoped methods are grouped by source; the user must explicitly confirm the checked set, and the confirm API revalidates selected IDs before creating project adoptions. Unfinished wizard drafts (`draft`, `gathering_input`, `ready`) can be resumed or deleted; deletion is refused after a project exists and never removes a project.

The homepage is task-first and keeps the existing detailed workbench inside a collapsible detail section. It shows one current project, one next action, and no more than three priority issues. The action is project-scoped and guarded by a generation token, so switching projects cannot cancel or display another project's run. Run start has a per-project lock, run-list failures remain visible with a reload action, and failed candidate-outline generation preserves the project for an explicit retry. The fixed local console port is `8765`; a second process using the same data directory stops with a Chinese message rather than selecting a random port.

## Learning rules and recoverable versions

Confirmed learning mechanisms remain global library records until the user adopts them into a project. Adoption updates only that project's `creative_blueprint`; it does not merge into or replace `prose_baseline`, formal outlines, or manuscripts. Removing an adoption regenerates the blueprint without deleting the source mechanism or changing existing prose.

Reference model analysis can also return up to four evidenced prose rules in the existing `reference_synthesis` response. This adds no model request. Only `reference_work` and `popular_sample` sources can create `style_rule` candidates. If synthesis omits a rule's window numbers, Runtime recovers only same-category prose evidence from completed windows; candidates still lacking real evidence are discarded without failing the otherwise valid synthesis. Each candidate remains proposed until the user confirms it. Applying a confirmed candidate appends the rule to the selected project's versioned `prose_baseline`, preserves other baseline fields, and does not modify an existing outline or manuscript. Reapplying an identical rule is idempotent and does not create another version. Rejected style candidates can be deleted with their local evidence.

Confirming the new-project wizard creates only the project and, when requested, an outline candidate. It never starts Skill initialization. The workbench routes projects without a confirmed outline back to the outline application view; both Skill initialization and short-story run APIs reject requests until a formal outline exists. Applying a candidate confirms the formal outline but still requires a separate user action in the workbench before characters, setting files, or prose generation can begin.

Initialization freezes one read-only snapshot of the active prose baseline and creative blueprint when the user starts the task. Character preparation receives only dialogue, psychology, viewpoint, narrative-distance rules and character-related methods; worldbuilding receives only setting-related methods; plot preparation receives compatible structural methods. Mode, genre, declared stage, and POV conflicts are filtered before model input. Completed Skills remain skipped, unfinished Skills share the frozen versions, and initialization cannot propose a replacement for `plot/outline.md`. Confirmed outline, locks, facts, POV, and identities remain authoritative.

Every creation route converges after formal-outline confirmation. Initialization input includes the current formal outline and its stable event map. Completed Skill records are skipped only when deterministic output checks still pass: the story bible must preserve confirmed facts, all explicitly named main characters and relationships must be covered, worldbuilding must contain useful registered detail files, and plot arcs and timeline must be populated. Premise wording may be faithfully rewritten, and supporting locations, characters, and concrete details may be added when they do not contradict confirmed facts. Incomplete legacy stages continue from existing files. `story-init` uses an explicit root-file allowlist, so a model cannot create a second title-prefixed project directory. Short and long generation endpoints reject projects without a confirmed outline or complete configured initialization stages.

Confirmed outline events receive content-derived `EV-xxxxxxxx` IDs that survive unrelated prose edits. A multi-segment short-story plan must cover every formal event in outline order and include an outline label, entry state, owned event, and exit handoff for each segment. Adjacent segments may share one event ID when a long obstacle, effort, or result needs several writing windows; an event may not reappear after the plan has moved to a later event. The draft run persists `segment-events.json`; revision story maps carry the same event IDs and handoffs. `planning.md` is therefore a run-scoped execution plan, never a second authoritative outline. Long setup writes its derived plan to `memory/book-plan.md`; chapter generation reads that plan together with `plot/outline.md`.

`/api/projects/{id}/learning` exposes a read-only prose-baseline overview containing the project-derived default genre, POV, tone, fixed local rules, and any active learned rules. The application page always renders this overview, even when no `prose_baseline` artifact exists. The legacy `perspective` metadata key remains a fallback, while current projects use `pov`.

Polish prompts, and draft prompts whose project style scope includes drafting, merge the active `learning/prose_baseline.json` rules into the runtime style profile without writing them into the user's `style-profile.md`. A migrated legacy style-sample block is removed only from the runtime copy before the same baseline is appended once, so the source file remains recoverable and the model does not receive duplicate rules. The final `skills_loaded` event is emitted after the last context-size reduction, so its recorded confirmed-context labels and character counts describe the prompt actually sent to the provider.

The effective-rules endpoint presents the order used by later generation: user locks, confirmed outline and project facts, platform requirements, prose baseline, adopted blueprint mechanisms, then advisory market data. Local checks report stale artifacts, explicit mode mismatches, similar adopted mechanisms, and recorded incompatible conditions. Post-generation usage status is deterministic and advisory; unsupported semantic mechanisms remain marked for human review rather than being reported as absent.

Learning artifact restoration is append-only. Restoring an older prose, voice, or knowledge version creates a new latest version containing the historical data; it never deletes intervening history or rewrites existing manuscripts. The project-readable JSON file continues to contain only the latest version used by `ProjectStore.load_constraints()`.

Legacy model attraction summaries that used a generic `claim` field are normalized when read so saved analysis remains visible without rerunning all text windows. New synthesis responses must use the displayable opening, goal, cycle, and ending fields. Invalid shapes retry through the configured synthesis fallback instead of being marked complete with empty-looking UI placeholders.

Starting a wizard from a reference preselects only that reference's user-confirmed mechanisms. When requested, project creation uses the existing planning role to create a candidate outline after adoption. The result remains an outline candidate and requires explicit application before it becomes authoritative.

Detached reference-analysis tasks preserve a useful error even when an upstream timeout or transport exception has an empty message. When both configured routes fail, the task error names the primary and fallback failures separately instead of degrading to `unknown error`; completed local analysis and reusable windows remain unchanged. The direct fallback window route retries once after either an unusable response or a transient request failure, so one provider wobble does not discard the current resumable analysis pass.

Learning mechanisms normalize model confidence values at the shared read boundary. Numeric values, percentages, and common Chinese or English high/medium/low labels become a bounded `0..1` score before confirmation or adoption checks, so historical model results do not expose raw conversion errors or require reanalysis.

Effective-rule warnings display the affected mechanism title beside every explanation. Local duplicate detection requires meaningful title similarity instead of allowing a shared generic usage note to dominate the comparison, preventing unrelated mechanisms from being grouped as one recommendation.

## Planning recovery V2

Planning equivalence recovery keeps one hash-bound best complete plan in
`outputs/planning-best.md` and a non-authoritative issue ledger in
`outputs/planning-recovery-state.json`. The pair is written before the first
adaptation review, so a transport interruption or truncated receipt cannot force the next
task to regenerate an already valid plan. A hash mismatch between the two files rejects the
checkpoint. Matching also requires the current formal-outline hash, segment count, and
`generation_context_sha256`; legacy failed artifacts without a context hash retain the prior
one-time compatibility path.

V2 segment receipts bind the formal outline, current event contracts, exact current segment,
previous accepted handoff, next segment entry, and generation context. They intentionally do
not bind unrelated segments through the whole-plan hash. Editing one segment therefore
invalidates that segment and only a neighbor whose bound entry or exit changed; unaffected
receipts can be locally revalidated. The whole-plan receipt still binds the current full plan
and every current segment receipt. V1 ready artifacts remain readable with their historical
whole-plan-bound hash algorithm.

Semantic recovery is monotonic. Runtime derives stable issue IDs from segment, event, and
failed invariant rather than reviewer wording. A candidate is promoted only when it resolves
at least one prior hard issue, retains no new hard issue, passes the local plan gate, and then
passes all currently invalidated segment reviews plus whole-plan review. Two targeted
complete-segment repairs are followed by at most one complete rebuild of only the remaining
affected segments. A single residual problem never authorizes a free whole-plan rebuild.
Failed, regressed, malformed, truncated, or unreviewed candidates remain diagnostic output and
cannot replace the best pair or become drafting authority.

Candidate monotonicity is attributed by actual segment bytes, not by whichever
findings happen to appear in the latest nondeterministic review. Runtime compares
the current best plan and candidate segment hashes, then makes the candidate
responsible only for changed segments, unscoped whole-plan findings, and boundary
findings whose affected segment set intersects a changed segment. A newly observed
finding bound wholly to a byte-identical segment is recorded as a latent baseline
issue: it is merged losslessly into the best issue ledger and becomes a later
independent repair unit, but it does not revoke a safe repair in another segment.
Previously known findings on unchanged text remain in the ledger even when a later
review omits them. A candidate that changes an unauthorized segment, introduces a
finding in its changed scope, or creates a changed/adjacent boundary regression is
still rejected. Every accepted granular unit is reassembled into the complete plan
and must pass adjacent and whole-plan authorization before causal-chain generation.

Order review distinguishes dependency-sensitive chronology from presentation order. A soft
non-causal reorder may be authorized while hard chronology remains a semantic failure. An
unknown dependency classification or a hard dependency without an ID from the full formal
event authority retries only the immutable receipt. This supports flashback, multiple
timelines, ensemble stories, and events that continue across adjacent writing segments without
relaxing causality, actor agency, viewpoint, entry/exit state, knowledge, relationship,
setup/payoff, or ending invariants.

## Log interpretation

- `checkpoint_reused`: prior complete artifacts were reused; generation did not restart from zero.
- `polish_input_compact_retry`: an explicit or preflight `input_context_overflow` switched to the compact request while preserving the same authority packet.
- `polish_output_limit_retry`: an `output_limit` finish is retrying the same actual route and identical prompt with more output headroom.
- `polish_transport_retry`: a `transport_interrupted` failure is retrying the same route once with the identical authority packet and budget.
- `polish_configured_fallback`: the primary route remained unusable after its allowed recovery and the configured fallback is running. Metadata retains the failure class; the short UI sentence omits route internals.
- `polish_segment_split`: an input or output capacity failure remained after its permitted retry, so only the failed parent segment is being split at a paragraph boundary. Network failures do not emit it.
- `polish_split_child_rejected`: at least one split child failed validation, so the complete parent source is retained.
- `polish_split_parent_rejected`: individually valid children failed merged-parent validation; no child checkpoint became parent authority.
- `polish_targeted_repair`: deduplicated soft evidence triggered one local repair. Metadata includes raw source/candidate metrics, rolling baseline, rule sources, evidence spans, recovery scope, and authority hash.
- `polish_style_allowance`: a named project prose rule authorized a local structural beat. Metadata names the exact rule source and authorized beat; hard constraints still apply.
- `polish_capacity_preserved`: the segment had no safe paragraph boundary or reached bounded split depth, so the parent source was retained.
- `polish_segment_preserved`: no permitted route or repair produced accepted prose; the parent source was retained with a non-authorizing checkpoint.
- `polish_segment_progress`: handled, total, and preserved-source segment counts for the current ordinary pass.
- `model_fallback`: the primary route failed and a configured model or role fallback is running.
- `polish_circuit_opened`: a successful fallback is reused for later segments in the same pass.
- `polish_input_sized`: estimated complete input size recorded before a provider call.
- `polish_output_rejected`: local validation kept the original segment.
- `polish_compact_retry`, `polish_compact_fallback`, `polish_compact_circuit_opened`, and `polish_max_tokens_retry` are retained only as historical-log UI aliases; the current ordinary state machine does not emit them.
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
- `final_review_json_fallback`: the current terminal-review request returned empty or incomplete content and is being repeated through the configured fallback model.
- `final_review_compact_recovery`: full-format terminal-review JSON remained incomplete and one compact recovery request produced a usable report.
- `final_review_reconciliation_recovered`: final adjudication returned a summary object instead of itemized reconciliation; matching stable issue IDs were recovered locally and any missing IDs remain unresolved.
- `snapshot_restore_failed`: rollback met a secondary filesystem error; the original run failure remains authoritative and the secondary error is recorded separately.
- `story_state_committed`: the candidate manuscript and authoritative state advanced together.
- `Controlled runtime ended without required tool output`: a write-capable Skill read context but did not submit an accepted proposal. Runtime prompts it to continue in the same tool session before failing; a configured planning fallback remains available, completed initialization Skills are reused, and formal files are unchanged.
- Outline material manifests collapse local-parser and planning-model labels that cite the same plot, promise, or question evidence, preferring the shorter label. Cached manifests are normalized when read so wording or parenthetical word counts cannot create false initialization gaps.
- Every initialization readiness check normalizes a matching cached outline manifest before evaluating files. Workflow start failures keep the backend's user-facing reason in the task status and toast instead of replacing it with a generic retry message.
- `recoverable` Skill execution: one or more generated file candidates were retained after a route or validation failure. `retained` identifies frozen primary-route candidates, `failed` identifies candidates from the active route that did not pass, and both remain inspectable without changing formal project files. A locally complete primary candidate set proceeds to validation without calling the configured fallback.
- Bootstrap proposal preflight checks content and entities without requiring the model to rewrite mechanical registry rows. Runtime applies the candidate set only inside its existing snapshot, runs local `reindex`, `links`, and `validate`, then repeats initialization completeness checks against the rebuilt formal files. Any remaining gap restores the snapshot and keeps the candidate execution recoverable.
- `failed`: the run stopped; formal files remain at their last committed revision.

## Safe maintenance procedure

1. Check SQLite for active `queued`, `running`, or `cancelling` runs before restart.
2. Reproduce defects from run events and receipts without making a paid request.
3. Add a focused failing test before changing workflow behavior.
4. Update this document when routing, budgets, state, recovery, or log semantics change.
5. Run the focused test and full `pytest -q` suite.
6. Restart with `start-novel-console.cmd` or the same configured data directory and port.
7. Verify the home page, project count, database path, and relevant state rows.

Outline generation keeps model creation and local refresh as separate user-visible outcomes. A
generation rejection must show the server's safe Chinese reason, including a missing confirmed
writing method. Once the server returns a candidate id, a later list-refresh failure must say that
the candidate was saved and offer a local reread; it must not ask the user to pay for generation
again.

## New feature compatibility gate

New capabilities are additive by default. They must not replace or bypass StoryState, Runtime-controlled formal writes, model routing and fallback, stage-specific Skills, candidate validation, quality gates, credential storage, project files, or run history. External projects are design references unless a scoped integration has passed overlap, prompt/Skill conflict, data ownership, migration, rollback, security, and license review.

Optional behavior should be project-scoped, disabled for existing projects, reversible, and implemented through existing contracts. A core workflow may change only when the proposal defines measurable gains in writing quality, consistency, or user control and retains the previous path as a tested fallback until comparative evidence supports removal. Generated content always remains a candidate until the existing validation, review, and commit flow accepts it.

## Generated-output parser compatibility contract

All parsers that consume model-generated, imported, or user-authored semi-structured text normalize presentation syntax before semantic validation. The mandatory compatibility matrix covers CRLF/LF, surrounding whitespace, common Markdown and HTML wrappers, fenced and unfenced blocks, full-width punctuation or digits, and documented field aliases. Unicode normalization is limited to identifiers, labels, and JSON syntax outside quoted strings; prose and JSON string values are not rewritten. Existing accepted forms remain valid and harmless wrappers are repaired locally. JSON-object consumers share `model_output.parse_json_object`. Malformed input or more than one JSON-object payload fails closed with an explicit reason; parsers never guess by silently taking the first or last object. Markdown semantic scans ignore ordinary HTML comments, fenced examples, and templates unless an owned sentinel explicitly claims the block. Every parser change carries table-driven canonical and variant cases, malformed and ambiguous fail-closed coverage, and a regression reproduction for production failures.

### Unified generated-artifact recovery boundary

Model-produced JSON now enters through `generated_artifacts.GeneratedArtifactGateway` and the versioned contract registry before planning, writing, quality, maintenance, learning, or provider-probe domain code consumes it. The strict parser remains the exact fast path. Balanced syntax damage may use JSON Repair; an unclosed container is typed as output truncation and is never locally completed. Open causal container topology is selected by one unique structural candidate, then BAML Schema-Aligned Parsing aligns only the selected cycle elements. Pydantic and the existing domain validators remain authoritative for ownership, causality, state, viewpoint, timeline, relationships, promises, and ending.

The conversion audit stores only raw/canonical SHA-256 hashes, method, transformations, quarantined paths, candidate count, and validation status. It stores neither raw output nor credentials. Descriptive metadata is open, machine-control fields are closed, and narrative invariants remain Runtime-owned. Non-owned first/last packet fields are quarantined rather than promoted. Multiple candidates, reordered/duplicate/foreign event ownership, or unknown control fields enter typed bounded recovery.

The recovery ladder is local normalization, receipt-only protocol retry, capable route fallback, smallest complete-unit regeneration, semantic split when capacity requires it, checkpoint resume, and restoration of the best validated candidate. Provider-specific aliases or regex branches are temporary compatibility bridges, not a root solution. Duplicate business parser authority may not be added outside this gateway; a source-scan regression test permits only the gateway fast path, strict transport-completeness checks, and strict hash-bound checkpoint readers. The P0–P6 decision contract and open-world verification matrix are recorded in `docs/superpowers/specs/2026-08-09-generated-artifact-recovery-v1-design.md`.

Short-plan segment headings accept canonical ATX Markdown plus standalone bold, strong, or `b` wrappers when the wrapped title itself unambiguously names a segment. Field labels and ordinary bold prose are not promoted to headings. Planning recovery validates that exactly one expected segment was parsed before indexing a generated packet; an unsupported or malformed normal-finish packet becomes a recoverable current-scope candidate failure instead of an `IndexError`, while the prior best plan and accepted sibling packets remain intact.

A Markdown planning repair packet may render `段首承接`, `本段事件`, or `段末交接` as standalone headings instead of colon fields, and may describe its event list with a noncanonical visible label. Runtime accepts those differences only when the segment number and exact ordered event IDs still match the current repair contract. It deterministically reuses the current formal outline evidence, extracts each heading-owned field only to the next peer-or-higher heading, and projects the packet back into the canonical planning block before semantic validation. Missing, repeated, ambiguous, or reordered authority remains a recoverable packet failure. The resulting field-, ownership-, body-, obligation-, and retention-level failure receipt is included in the next bounded repair attempt; it is not discarded as a generic generation failure, so the model does not blindly repeat the same malformed packet.

Event ownership may be declared by one explicit ownership field or by ordered
event/beat titles inside the semantic event section. Ownership is inferred from
stable event identity and structural position, not from one fixed visible label.
Descriptive mentions in handoffs, diagnostics, self-checks, constraints, or
later-event notes remain references only. Legitimate story events whose titles
contain words such as “核验” or “validation” are not discarded as diagnostics;
only structurally diagnostic prefixes and sections are excluded.

A planning repair packet may also arrive as one JSON object after a normal provider finish. Runtime accepts this only as a presentation variant when the object identifies exactly the expected segment, owns exactly the expected event IDs in formal order without duplicates, gives every owned event a non-empty narrative body, and supplies complete segment entry and exit state. Runtime projects those fields into the canonical planning block using the current formal segment as outline authority, then reruns event-body retention, obligation, adjacent-handoff, and whole-plan validation. Reordered, duplicate, missing, conflicting, multiple-object, or authority-incomplete JSON remains a protocol failure; it is never promoted or treated as creative permission.

Some providers instead return a `beam_plan` map whose event values contain only `resolution`, `causal_plan`, `approach`, or obligation arrays such as `obligations_fulfilled`. Runtime classifies that form as a structured repair summary, not a complete replacement event body. Segment identity and exact ordered ownership must still match. For each event, Runtime projects the exact event-owned body from the retained best planning segment, preserves that complete realization, and appends only the provider's explicit obligation and boundary amendments; packet-level entry and exit handoffs may replace their matching fields. It never fabricates prose or lowers the `event_body_collapsed` retention floor. If the retained source body is missing, duplicated, reordered, or cannot be bound to exactly one event, normalization fails closed with `planning_packet_summary_authority_missing`. A recovered packet must still pass event-body integrity, required-participant obligations, body retention, adjacent handoffs, whole-plan authorization, and the normal monotonic best-candidate gate before causal-chain generation or drafting.

Short-plan local validation derives its required event IDs from the same hierarchy-aware executable-event contracts used by planning adaptation and execution manifests. Structural Markdown headings such as `## 第 1 段` may organize nested formal events, but they are not promoted into additional story events after parser presentation metadata is removed. Their stable IDs, along with theme or writing-directive IDs, remain valid optional traceability references when a historical or model-authored plan includes them; only executable narrative-event IDs participate in mandatory coverage and chronology. A genuinely unknown ID is still rejected even when an outline contains only directives. This keeps local recovery, semantic review, and downstream execution on one event authority while preserving existing heading and field presentation variants.

Story-wide narrative integrity is a blocking workflow invariant. Any artifact that controls later causality, event ownership, character or knowledge state, chronology, relationship progression, setup/payoff, canon, or the confirmed ending is required authority rather than optional guidance. A provider output-limit finish is treated as truncation risk. The response is accepted only when an independent artifact-specific check proves closure, required coverage, order, handoffs, and applicable narrative constraints; otherwise the same route is retried with more output headroom and then the semantic unit is split. Recovery may checkpoint independently validated upstream work and retry only the missing artifact, but downstream drafting starts only after required artifacts pass format, hash, event-coverage, order, and cross-artifact consistency checks. Split and resumed calls receive the same applicable confirmed outline, StoryState facts, causal constraints, owned segment plan, prior accepted ending state, and current handoff. Degraded continuation is limited to genuinely advisory material that cannot change narrative truth; causal chains and continuity artifacts never qualify.

Project-aware prose validation is migration-free and reversible. It reads optional existing `style-profile.md` and active prose-baseline artifacts but never rewrites them, the formal outline, StoryState, or the manuscript. An old project with neither artifact keeps conservative validation. Rolling metrics and authority hashes live in run diagnostics/checkpoints only. Operational rollback therefore consists of reverting the runtime code and restarting the service; no project-data downgrade or manuscript rewrite is required. Checkpoints produced by the newer runtime may be ignored and regenerated by an older path without changing formal story files.

## Adaptive model output and internal task recovery

Stage budgets are quality headroom rather than a spend cap. The runtime sizes a request from the expected artifact, configured context window, and declared provider output ceiling. If the ceiling is unknown, ordinary production calls discover it without paid probe calls: terminal outputs establish only an observed lower bound, while repeated token-limited responses far below the requested allowance can establish a conservative route-specific suspected ceiling. Observations are isolated by provider, model, protocol/configuration fingerprint, and execution mode, so fallback output never changes the primary route profile. Timeout, disconnected stream, and missing terminal provider status are transport failures and do not lower the suspected token ceiling.

`output_limit_complete` means the provider reported its limit but the returned owned artifact independently passed completeness checks. `output_limit_expanded` is the general-stage same-route expansion event; polish emits the more specific `polish_output_limit_retry`. `stage_recoverable_partial` means the response is retained only as diagnostic evidence and is not narrative authority. `planning_task_split` and `draft_task_split` describe internal subtasks inside the same visible run; they do not create extra sidebar tasks.

Short planning first tries one quality-sized request unless the current route has a repeatedly observed stable ceiling below 75% of the predicted artifact. A proven or predicted overflow splits planning into contiguous numbered-segment batches. Each batch is hash-bound to the same brief, constraints, preceding accepted batches, and segment range. The combined plan still passes the existing whole-story event coverage and ordering gate. The causal chain is then generated or repaired as a separate artifact. `short-execution-index.json` remains `causal_pending` until that artifact is valid and becomes `ready` only after hashes bind the confirmed outline/StoryState revision, constraints, plan, causal chain, and segment count. Drafting cannot start before `ready` is written.

Short prose retains its existing owned segments. A segment that remains token-limited after same-route expansion is split into two internal causal continuations, recursively to a bounded depth. The second child receives the accepted first-child text and ending state. The combined parent segment must pass length, prose, duplication, and boundary-transition checks before its checkpoint is authoritative. `draft-checkpoints/segment-NN.json` binds the text to the plan, constraints, previous accepted segment, and event assignment. A later visible task may reuse a failed or cancelled task's longest still-valid prefix only when the execution-index StoryState revision, outline, constraints, plan, causal chain, segment count, and every preceding segment hash still match; completed/running/queued tasks are never borrowed.

A normal provider finish does not bypass the same prose gate. If an owned Chinese draft segment carries an explicit normal terminal reason and ends below the hard completeness floor, it enters `draft_task_split` with reason `normal_finish_underlength` instead of repeating one whole-segment rewrite. Missing terminal metadata is classified as unknown rather than guessed to be a normal finish, and a zero Han-character measurement does not drive splitting for non-Chinese prose. Formal event IDs are divided into contiguous child ownership ranges; the second child receives only the accepted first child and the remaining range. The failed short candidate stays diagnostic and is never checkpoint authority.

Draft transition checks use a project-scoped location catalog built from formal location names, explicit aliases, documented notable features, nested place names, and confirmed state locations. Location Markdown accepts LF/CRLF, half- or full-width frontmatter field colons, block or inline alias lists, and English or documented Chinese feature headings; fenced templates and HTML comments are ignored, malformed inline aliases add no alias, and aliases claimed by different places are removed as ambiguous. Matching applies NFKC and whitespace normalization to identifiers, including names such as `A 栋` or `Moon Base`, without rewriting prose. The checks compare canonical locations and parent roots rather than arbitrary Chinese suffix matches. A transition between two distinct known roots without time, movement, dream, memory, virtual-space, or viewpoint evidence blocks. A same-root child-location change without a recognized bridge is recorded as `draft_segment_continuity_warning`; missing, ambiguous, same-named, or undocumented locations cannot block by themselves. This behavior is genre-independent and does not require rewriting existing project files.

Draft checkpoint authority now includes the canonical location catalog. A legacy checkpoint hash remains reusable only when the current project has no canonical location entries; once formal locations exist, the catalog-aware hash is required so scene continuity cannot be bypassed by an older checkpoint format.

## Planning equivalence authorization

Short-story planning now distinguishes literal outline copying from a narratively equivalent implementation. The running plan may enrich dialogue, description, transitions, minor actions or props, scene realization, trigger method, supporting participants, local location, evidence-acquisition method, and non-dependent micro-order. It may not change event function, primary-actor agency, causal dependencies, segment entry or exit state, character knowledge or relationship state, viewpoint, dependency-sensitive chronology, setup/payoff, or the confirmed ending. This vocabulary is deliberately genre-neutral: actors may be people, groups, institutions, environments, or systems, and presentation order remains authoritative for flashbacks, nonlinear timelines, and multi-viewpoint stories.

After the existing deterministic plan gate passes, Runtime performs one hash-bound adaptation review for each formal segment and one whole-plan review. Reviewers return every protected invariant and select evidence only from Runtime-generated exact plan excerpts. Their `classification` and `changed_dimensions` values are descriptive diagnostics rather than an authorization enum: Runtime stores `raw_changed_dimensions`, recognized `canonical_dimensions`, and `unrecognized_dimensions` losslessly, then derives `structural` when any protected invariant is false, `equivalent` when all invariants hold and a change is described, and `unchanged` when all invariants hold and no change is described. Unknown Chinese, English, Unicode, genre-specific, or provider-specific dimension names never block by themselves. Bounded field or passage candidates take precedence over a complete multi-event segment. Unicode-compatible identifiers, full-width characters, string booleans, a single or array evidence ID, and comma-, full-width-comma-, semicolon-, or newline-delimited list fields normalize at the protocol boundary; prose itself is never rewritten during normalization.

Protocol failures and narrative failures have different recovery budgets. Invalid JSON, stale hashes, incomplete coverage, inconsistent affected scope, invalid evidence IDs, or a direct contradiction between a structural description and complete all-true invariant verdicts cause up to three receipt-only attempts while the plan remains immutable. Existing raw receipt files are reparsed and locally revalidated first; a receipt that failed only because an older Runtime rejected its vocabulary continues without another segment-review call. Confirmed structural drift is driven only by protected invariant failures and regenerates the affected complete plan segments with the whole failure receipt, previous accepted handoff, next entry, exact formal event contracts, and unchanged event ownership. Each affected complete segment is an independently promotable recovery unit: Runtime evaluates it against the latest best complete plan, persists every strictly improving segment immediately, and continues repairing only the remaining failing segments. A later segment that introduces a new hard issue cannot revoke an earlier segment that already passed its local, adjacent-boundary, and whole-plan checks. Repair budgets therefore follow the remaining failing scope and refresh after strict progress instead of being consumed by a prior mixed-success batch. A candidate may become the best plan only when its stable hard-issue set is a strict subset of the previous set and it introduces no new hard issue. After two no-progress targeted attempts, Runtime rebuilds only the still-affected complete segments from formal event contracts; it never authorizes a free whole-plan rewrite for one residual problem. Every accepted unit re-enters deterministic structure checks, hash-invalidated segment reviews, adjacent boundary review, and the whole-plan review before causal-chain or draft generation can continue. Failure preserves the lowest-issue complete plan and every accepted granular checkpoint; rejection alone is not reported as resolution.

A negative planning-adaptation verdict is valid only when `plan_evidence_quote` copies at least six semantic characters from one selected Runtime-owned excerpt of the current candidate and the review reason repeats that phrase verbatim. A finding copied from an older or rejected plan is therefore a receipt protocol defect: Runtime retries only the immutable review receipt, leaves the best plan and semantic-repair budget untouched, and does not create structural-drift issues until the current candidate itself supplies the quoted problem. Once valid, targeted recovery shrinks broad evidence to the smallest nested Runtime sentence containing that phrase, while complete-event retention, adjacent handoffs, and whole-plan authorization remain mandatory.

CrewAI execution preserves the first exception raised by the workflow together with its original traceback. If event, trace, memory, or other wrapper cleanup subsequently raises another exception, the cleanup error remains chained as diagnostic evidence but cannot replace the actionable workflow failure shown to the task and production-incident mechanism.

Resuming the same or a compatible prior failed short-story task reuses its hash-bound lowest-issue complete plan before any new planning call when the formal-outline hash, segment count, and stored generation-context hash still match. The deterministic local gate runs again and continues only the remaining issues; a locally clean plan proceeds to adaptation receipt validation. New artifacts store `generation_context_sha256`; the legacy production shape created before that field existed may infer the same-run context only after the other hashes and current local gate pass. A changed stored context rejects reuse and regenerates planning normally.

The same boundary rule applies downstream. Final-review `decision` accepts documented aliases and otherwise falls back to Runtime scores, hard-fail state, and unresolved mandatory issues; the raw model decision remains diagnostic. Repair-group kinds, patch operations, revision checks, and expansion insertion operations remain closed machine controls, but documented Chinese/English aliases normalize before validation. A malformed machine contract receives one contract-only retry with the candidate text, hashes, issue scope, and narrative authority unchanged. Reference-learning style categories are advisory: recognized aliases enter the style profile, while unknown categories are retained under `unrecognized_style_evidence` or `unrecognized_rules` and cannot fail an otherwise valid analysis window.

A successful review is saved as `outputs/planning-adaptations.json`. It is a derived receipt, not another StoryState or outline. The execution authority hashes this artifact, retains formal evidence for audit, and uses only the authorized current plan realization as downstream beat evidence so old and new plot implementations cannot be mixed. If a repaired plan changes, the causal chain is regenerated before the execution manifest. Full and partial checkpoints copy the artifact when their execution authority binds it; a missing or changed file invalidates that checkpoint. Older checkpoints without an adaptation hash remain readable through their original authority chain and do not require project-data migration.

Relevant events are:

- `planning_adaptation_review_started`: segment and whole-plan equivalence review has begun; metadata reports segment and formal-event counts.
- `planning_adaptation_reused`: an existing receipt matches the current outline, plan, and segment count.
- `planning_adaptation_plan_reused`: the current or a prior compatible failed task reused its hash-bound best complete plan and resumes at the remaining local or adaptation validation boundary instead of calling initial planning again.
- `planning_adaptation_receipt_retry`: one segment receipt is being reacquired without changing the plan.
- `planning_adaptation_receipt_revalidated`: a stored raw segment receipt passed the current invariant-driven validator locally; no model call or plan mutation occurred.
- `planning_adaptation_whole_receipt_retry`: the whole-plan receipt is being reacquired without changing accepted segment receipts.
- `planning_adaptation_whole_receipt_revalidated`: a stored whole-plan receipt passed the current cross-segment validator locally.
- `planning_adaptation_targeted_repair`: only the affected complete plan segments are being regenerated.
- `planning_adaptation_segment_rebuild`: two targeted attempts did not continue to reduce the issue set, so only the still-affected complete segments are rebuilt from formal event contracts.
- `planning_candidate_improved`: the candidate strictly reduced the stable hard-issue set without introducing another hard issue and became the new best plan.
- `planning_latent_issues_discovered`: a safe changed segment was retained while findings newly observed on byte-identical segments were added to the best ledger as later independent repair units; metadata binds changed and latent segment hashes and issue keys.
- `planning_candidate_rejected_regression`: the candidate made no strict progress or introduced a new hard issue; the prior best plan remains active.
- `planning_candidate_rejected`: the repair candidate was incomplete or unusable; the prior best plan remains active.
- `planning_adaptation_ready`: segment and whole-plan authorization passed; metadata records classification and recovery counts.
- `planning_adaptation_receipt_failed`: receipt protocol recovery was exhausted; plan content remains uncommitted.
- `planning_adaptation_failed`: targeted and complete-segment semantic recovery did not converge; drafting has not started and the best plan remains resumable.
- `short_revision_contract_retry`: prose remains unchanged while Runtime reacquires only a repair-group machine contract.
- `short_expansion_contract_retry`: prose and the exact length deficit remain unchanged while Runtime reacquires only an expansion-plan machine contract.

## Planning Adaptation V3 recovery and context capacity

New planning-adaptation artifacts use version 3. Local segment authority binds only the current segment's exact event realization, formal event contracts, and generation context. Neighbor openings and handoffs remain part of whole-plan continuity authority, so changing one boundary no longer forces an unrelated byte-identical segment through a second local semantic verdict. Version 1 and 2 ready artifacts remain readable under their original hash rules.

Targeted planning recovery prefers a Runtime-owned evidence patch. The current issue receipt supplies exact `plan_evidence_ids`; Runtime selects the smallest non-overlapping anchors, binds their IDs, source hashes, current plan hash, segment, and stable issue keys into one patch authority, and permits replacements only at those exact anchors. A full affected-segment result remains a compatibility fallback for older providers. If the patch changes event ownership or required segment fields, it is rejected before candidate comparison. Complete-segment rebuild remains the final bounded semantic fallback.

Composite formal events also receive a deterministic completion checklist derived from the confirmed outline. The projection preserves each event-owned source line, explicitly named participants, and whether that line carries action, reaction, outcome, or commitment work; it is derived authority, not a second outline or StoryState. Before any model review, Runtime hard-checks only events whose confirmed outline contains at least two participants with stable identity forms (for example, explicit names); role or kinship titles such as “沈大小姐” remain in the checklist but may be realized through a confirmed name or natural form of address and stay under semantic review. If the current plan omits one stable participant, Runtime records `planning_required_participant_missing`, reuses compatible hash-bound semantic issues from the current recovery checkpoint, and goes directly to a rebuild of that complete formal segment instead of spending review calls on an already deterministic omission. The rebuild prompt receives only the current segment's contracts and compact checklist, keeping the best segment last and rejected candidates diagnostic-only. The candidate cannot pass completeness while a required stable participant remains absent, and after the omission is fixed it still re-enters local review, adjacent-boundary validation, and whole-plan review. Unaffected segments remain byte-identical.

`planning-recovery-state.json` now retains complete candidate issues, introduced issues, stable keys, candidate hashes, and comparisons. Rejected records are diagnostic no-regression evidence, never StoryState or formal plot authority. A later attempt always starts from `planning-best.md`, receives only the records relevant to its current segment and event ownership, and is explicitly forbidden from inheriting rejected candidate facts. Cross-task resume copies the entire hash-bound recovery pair into the new run before review, so transport failure or task restart does not erase prior failure lessons.

Recovery comparisons additionally retain `changed_segments`, per-segment
before/after hashes, attributable issue keys, latent baseline issue keys, and the
hashes of unchanged segments where latent findings were observed. These are optional
version-1 envelope fields, so older runs remain readable without migration. On
promotion, the best ledger combines the current review for changed, boundary, and
whole-plan scope with every known issue on unchanged segments; reviewer variance can
reveal more work, but cannot make an untouched old problem disappear or blame it on
the wrong repair candidate.

If a complete-segment rebuild fixes one invariant but introduces another, the same
still-failing unit receives one second bounded rebuild attempt from the latest best
plan and the complete rejected-candidate evidence. The attempt budget belongs to that
unit; successful repairs in other segments are not replayed or revoked. Exhaustion
still preserves the best complete plan and stops before causal-chain generation.

Recovery prompts are capacity-gated. The complete ledger remains persisted, while segment prompts receive a deterministic relevant projection. Raw rejected-plan excerpts are replaced by hashes if they would exceed the repair packet budget; every stable issue identity and machine-relevant invariant remains present. Whole-plan review estimates the configured Review-role context window, or uses a conservative 32K default, and progressively changes representation from full plan to a complete structural map, evidence-hash hierarchy, and finally a full event/boundary coverage manifest. It never samples events, removes ownership, mechanically truncates authority, or lowers the requested story scope.

Local planning-adaptation review uses the same capacity contract. When the complete segment receipt approaches the safe context range, the common stage preflight invokes an explicit semantic splitter instead of throwing a terminal `topology=split` error or sending the oversized request. The splitter recursively partitions only the segment's ordered formal-event contracts. Each packet receives the exact event-owned plan blocks and parent evidence IDs instead of another copy of the complete segment; its packet hash still binds the immutable full-segment authority, ordered event IDs, dependency IDs, planning hash, and adjacent handoff authority. Packet receipts are merged in original event order and must pass the unchanged full-segment protocol, evidence, ordering, direction, boundary, and semantic checks before whole-plan review can start. Completed packets are stored under `outputs/pap/` and may be reused across compatible failed or cancelled runs only when all bound hashes and ordered IDs match; conflicting checkpoints are discarded.

Complete formal-segment rebuild uses a parallel creative packet topology. If the rebuild request reaches the capacity preflight, Runtime projects only the exact numbered/list event body owned by each contiguous packet, while retaining the packet's formal contracts, completion checklist, relevant stable issue identities, parent handoffs, and the exact preceding accepted sibling projection and hash. It recursively reduces a multi-event packet until every leaf fits; a single formal event remains indivisible and fails closed only if its already-minimal creative packet still cannot fit. Leaf results are stored under `outputs/prp/` with parent authority, ordered event IDs, predecessor hash, and exact output hash, so an interrupted or later compatible task can reuse completed leaves. Runtime then restores the original segment shell, merges event bodies in formal order, preserves the first opening and last handoff, and reruns the unchanged complete-segment validator. The ordinary recovery loop still performs local semantic review, adjacent-boundary validation, and whole-plan review before causal-chain generation. This topology never truncates the outline, contracts, failure ledger, current best plan, or requested creative output; conflicting valid checkpoints are treated as ambiguous and regenerated instead of selecting one silently.

Planning-rebuild JSON uses an open presentation contract rather than a finite wrapper-name schema. Runtime recursively discovers the leaf-most narrative record bound to each exact formal event ID, whether the record appears in a top-level array, an event-ID mapping, nested arrays, block lists, or future provider-selected containers. Container names and nesting never grant ownership. Every declared segment and explicit event-ID sequence must agree with the current packet, and discovered records must match the exact ordered ownership once each. Conflicting identities, duplicate or reordered records, ambiguous entry/exit state, and unknown machine-control fields trigger a canonical protocol retry; Runtime does not choose a convenient candidate or infer an operation from prose. A short structured summary cannot replace accepted event prose: Runtime retains the exact event-owned body and appends only auditable obligation or boundary evidence. A complete narrative body remains eligible as the creative candidate. The normalized packet then crosses the unchanged body-retention, participant-obligation, adjacent-handoff, complete-segment, and whole-plan gates. Completed hash-matched sibling packets remain reusable, so a presentation retry does not regenerate accepted work.

If a single event still exceeds the route safety range, Runtime keeps that event indivisible as narrative ownership but reviews its invariant facets separately: function/agency/causal dependency, entry/exit/knowledge/relationship state, and viewpoint/timeline/promise-ending. Facet receipts bind the same packet authority and are merged only after all ten invariants are covered exactly once. If one facet remains too large, its exact event-owned plan evidence is divided into paragraph-aligned overlapping windows. Every window binds its character range, text SHA-256, evidence IDs, facet authority, and invariant verdicts; coverage must start at character zero, end at the exact event length, and contain no gap. Completed window and facet checkpoints are reusable across tasks, while missing, duplicate, stale, hash-conflicting, or non-covering windows are regenerated. The merged facet, event packet, parent segment, adjacent boundaries, and whole plan are all revalidated. No plan prose, formal contract, failure evidence, story target, or creative scope is mechanically truncated.

The whole-story reducer records `planning_adaptation_whole_context_reduced` with its representation, estimated tokens, limit, and segment count. A reduction is valid only when it retains every ordered event ID, segment hash, opening, handoff, local receipt hash, and formal contract identity. Local receipt success never substitutes for whole-plan causality, knowledge/relationship progression, viewpoint/timeline, promise, or ending review.

Model prompts treat absent actor, viewpoint, time, location, knowledge, and relationship fields as unknown. They must not invent canon to force a verdict, merge executors with intermediaries or hidden principals, or let an earlier event consume a later reveal or state transition. This remains genre-neutral for ensemble casts, non-person actors, system or institutional events, multiple viewpoints, flashback, and multiple timelines.

The complete acceptance route is planning recovery, causal chain, execution manifest, all draft segments, merge, polish, targeted and user-selected repair compatibility, AI re-review refresh, terminal review, and final manuscript promotion. A pass at the planning boundary alone is not completion. Offline tests use production-shaped fixtures and deterministic model responses; one separately authorized real-provider run may execute only after all offline gates pass and remains a candidate until final review succeeds.

## AI re-review refresh and generated-subtask integrity

Failure containment and problem resolution are separate acceptance states. Rejecting an invalid model artifact, preserving the last accepted checkpoint, or stopping before downstream generation protects the work but does not complete the fix. A workflow defect may be reported as resolved only when its production-shaped reproduction has an executable recovery path and the recovered artifact successfully crosses the next authoritative boundary without weakening story-wide causality, character state, chronology, viewpoint, event ownership, handoffs, or ending constraints.

Every model-authored mutation re-enters one validation closure in this order: syntax and schema, event ownership and source evidence, local semantics, adjacent entry/exit handoffs, then whole-story integrity. This applies equally to initial generation, schema correction, semantic repair, complete-segment rebuild, targeted revision, split/merge, fallback, and resume. Later phases cannot rely on an earlier pass, and a recoverable schema or integrity regression introduced by semantic repair cannot become terminal merely because that repair route has a zero retry budget. Exhaustion must preserve the last accepted authority, but successful recovery—not safe stoppage—is the required completion criterion.

Composite narrative causality must be represented losslessly. When one state genuinely depends on several atomic beats, the contract must support multiple attributable producers or split the state into independently attributable assertions; Runtime must not silently select one producer or discard contributing beats to satisfy a scalar parser. Regression tests must include real provider-shaped variants, a later repair that reintroduces an earlier defect, successful bounded recovery, and continuation through the next authoritative workflow boundary. Tests that prove only rejection or rollback do not prove the problem is solved.

The terminal review keeps one checkpoint-bound issue ledger. A completed re-review must reconcile every prior stable issue ID exactly once. `resolved` and user-confirmed `preserved` items leave the actionable **最需要处理的问题** list and move to the collapsed resolved history; `unresolved`, `partially_resolved`, and `uncertain` remain actionable. Counts, default revision selection, publication blockers, and the workbench priority view all consume the same actionable projection. Missing, duplicate, unexpected, legacy-write, malformed, truncated, stale-manuscript, or incomplete reconciliation cannot replace the last valid quality checkpoint. Omission never means resolution.

Short-story authority is now assembled without fixed character slicing. Unmarked rules inside hard-rule, locked-fact, confirmed-fact, must-include, and must-avoid sections are mandatory even when they do not contain words such as “must”. Example sections remain advisory and are excluded by explicit headings or labels; ordinary temporal words such as “before” and “after” no longer cause a rule to be discarded. A pending, failed, stale, or receipt-incomplete execution manifest is never inserted into downstream system context.

New short execution manifests are version 4. Runtime first derives a non-persistent narrative-event view from the confirmed outline: a heading with concrete nested events is a structural container, while a genuinely sparse chapter/act/phase remains a fallback event. This works from Markdown hierarchy plus normalized Chinese/English structure labels and does not rewrite `plot/outline.md` or StoryState. Every event contract retains its exact source block and presentation order; a beat's `source_evidence` must occur inside that specific event block, so a chapter title or neighboring event cannot be used to justify an invented actor, action, location, or result. Version 2 and 3 manifests remain readable for existing draft, polish, repair, checkpoint inspection, and hash-bound receipts; their historical digest representations are preserved and version 3 round trips idempotently.

Version 4 represents `exit_state.produced_by` as an ordered array so a state may retain every contributing atomic beat. The shared parser also accepts one legacy beat-ID string and common comma, full-width comma, semicolon, full-width semicolon, or ideographic-comma variants when every token is a valid beat ID. It never accepts labels such as `narrative_overview` as producers. A fact that predates the current segment belongs in `entry_state` with `inherited_from`; it cannot be promoted to a newly produced exit fact. Fragment merge remaps every producer ID and computes v4 boundary hashes without selecting only the first cause.

Before manifest generation, the deterministic short-plan gate uses a bounded monotonic recovery ladder. Each of at most two model attempts receives the exact remaining local issues and the complete current best plan. Runtime evaluates candidate segment combinations and keeps the smallest changed segment set that strictly reduces the stable local-issue set without introducing a new canon, segment, event-ownership, order, duplication, or handoff problem. Unaffected valid segments remain byte-for-byte unchanged; a no-progress or regressing candidate is recorded and discarded. The lowest-issue complete plan is hash-bound in `planning-best.md` plus `planning-recovery-state.json` before every attempt, so an interrupted task resumes from that candidate instead of restarting from a worse draft. If the local issue set does not reach zero after two attempts, planning stops before prose generation. Any accepted local plan mutation invalidates a previously embedded causal chain; Runtime regenerates and validates the standalone chain from the final plan before persistence.

Manifest v4 generation is scoped by accepted formal writing segment. Each internal subtask receives one segment number, that segment's exact ordered event contracts, its accepted plan block, the whole causal artifact, the previous accepted exit and fragment hash, viewpoint/timeline authority, and the later event IDs it may not consume. Schema repairs and deterministic coverage/boundary repairs each have two independent retries. Semantic review is also segment-scoped and receives Runtime-computed `EXPECTED AUTHORITY SHA256` and `EXPECTED MANIFEST SHA256`; hash, receipt coverage, actor/action, boundary, evidence, and formal-plot failures are collected together instead of stopping at the first error. A semantic failure first authorizes a minimal fragment correction and then one complete rebuild of the affected formal segment. Each semantic mutation receives fresh bounded schema and integrity recovery and re-enters the complete validation closure instead of trusting an earlier pass. Runtime finally renumbers beats, remaps every composite producer, binds previous-exit hashes, computes exact future-beat prohibitions, and validates the merged whole-story manifest before drafting. Failed fragments remain diagnostic/checkpoint material and never become downstream authority.

Manifest review evidence is Runtime-owned rather than model-authored. Beat receipts are rebound to each already validated `source_evidence`; segment receipts select a bounded exact plan excerpt by candidate ID, with presentation-only Markdown, whitespace, line-ending, and wrapper variants mapped back to that immutable excerpt. Receipt hash, coverage, summary, or evidence-binding defects use a separate three-attempt protocol budget, keep the manifest bytes unchanged, and never consume semantic repair or trigger a complete-segment rebuild. Exhaustion records `content_status: content_valid`, emits `planning_manifest_receipt_failed`, and stops before drafting with the structurally and semantically accepted content retained. Explicit negative semantic verdicts remain eligible for the two-level fragment repair ladder. Negative beat verdicts carry `invalid_fields`, per-field verdicts, the reviewer reason, and the bounded review summary so a repair can change only the unsupported actor, action, location, state, viewpoint, timeline, knowledge, or relationship field instead of guessing from a generic actor/action label.

Draft semantic receipts now require exact prose-bound evidence for actor/action identity, viewpoint, location/time/knowledge state, scene order, causal order, entry state, and exit state. Ordinary polish, structural revision, targeted repair, user-selected short revision, split recovery, and resumed candidates use the same atomic segment contract. A changed scope that fails this review first receives an error-specific authorized repair. The first attempt keeps the smallest safe patch; the second may replace only the affected complete formal segment while preserving its entry, exit, owned beats, viewpoint, useful voice, dialogue, detail, pacing, and reasonable length. Two failed semantic repairs restore the last accepted complete segment or modification group, invalidate the rejected checkpoint, leave the selected issue unresolved, and continue only with independent work. The assembled manuscript then receives another whole-story semantic adjudication before quality review or promotion. If independently valid polished segments conflict only after assembly, Runtime deterministically isolates the conflicting segment or continuous ownership group, rebuilds each trial manuscript from the protected source plus already accepted units, first tries every one-unit rollback, and otherwise builds a monotonic safe subset from the accepted source. Every retained result must pass changed-segment, adjacent-handoff, and whole-story validation. A conflicting polish unit returns to its source text and receives a non-authorizing checkpoint; it cannot erase unrelated safe polish. Structural-revision literal checks are tracked across every batch. A newly removed required literal or an increased forbidden literal is a regression and restores only the deterministic conflicting modification scope when a whole-story-valid subset exists. A pre-existing violation that remains because another independent target failed does not erase successful groups; it stays visible for the next quality decision. When user-adopted repair groups conflict only in their final combination, Runtime tests bounded deterministic subsets against the same whole-story gate, first trying each single-group removal and then a newest-first rollback. The first passing safe subset continues; removed groups and their issue IDs return to unresolved status. If even the protected source cannot revalidate, terminal review is not called and the run remains recoverable.

`revision-integrity.json` records the segment receipts and whole-story verdict for a promoted user-selected repair. Its quality checkpoint retains the hash-bound narrative-integrity reference, and the promoted run copies the ready execution manifest so a later repair or polish round can reproduce the same atomic authority instead of silently dropping back to legacy checks.

Full short-story checkpoints are version 4. They bind the original generation context, the validated Planning IR authority and artifact hashes, plan, causal artifact, ready execution manifest plus receipt digest, segment assignments, StoryState hash, narrative-integrity artifact, and selected manuscript bytes. Cross-run recovery validates and copies the same Planning IR before saving or rebuilding downstream artifacts; deleting or editing the IR cannot silently fall back to an older Markdown interpretation. A corrupt later segment checkpoint preserves the longest valid prefix and restarts at the first invalid segment instead of discarding earlier accepted prose. The run log displays every structured issue, automatic repair attempt, context-layer size, preserved-prefix count, and restart segment rather than collapsing diagnostics to the top-level message.

Short-draft calls now use an immutable `DraftTaskContract`. It binds the full authority hash, parent and child identity, recursion depth, one current Han-character target, exact ordered event IDs, entry state, required exit state, and the preceding accepted sibling hash. The provider prompt is rebuilt from the immutable authority for every root, child, and same-scope retry; it never appends child instructions to a rendered prompt that still carries the parent target. A single formal event is retried in place instead of being split into invented halves. With two or more ordered events, child one receives the first contiguous event range and child two receives the remainder. Child two's target is `max(400, parent target - accepted child-one Han characters)`, so accepted prose is never mechanically cut to restore a fixed 50/50 allocation.

`stop`, `end_turn`, `completed`, `complete`, and output-limited returns use the same leaf validation. Missing terminal metadata is non-authoritative for an underlength result and triggers one same-scope retry instead of acceptance or a guessed split. Normal terminal metadata does not authorize overlength, underlength, duplicate, production-note, Unicode replacement-character, invalid-control-character, or continuity-invalid prose. A recoverable invalid leaf gets one fresh same-scope retry; an indivisible, zero-event, or maximum-depth task is never split into invented children. A successful semantic split records `draft_task_split_completed` with authority, child targets, child event ranges, child hashes, and the accepted parent hash. The merged parent then passes its own length, prose, duplication, and boundary gate.

Every formal-event node is also checked by an independent Review-role semantic verdict before its segment checkpoint is written. The verdict is bound to the authority, task ID, and exact prose SHA-256; every owned event, entry state, and exit state needs an exact excerpt found in that prose, outside-task event IDs must be empty, and causal order must pass. A first split child must receive this verdict before Runtime computes the residual target, binds its hash as sibling authority, or starts child two. Child verdicts, the merged parent verdict, and the root segment verdict are all retained. A malformed segment or whole-draft review receipt, stale hash, incomplete manifest, or affirmative verdict paired with an unbound evidence excerpt is treated as a reviewer-protocol defect: Runtime keeps the prose byte-for-byte unchanged and retries only the receipt once with the exact protocol issues. An explicit negative actor/action, state, viewpoint, ownership, order, continuity, promise, or ending verdict remains a genuine narrative failure and enters the semantic repair ladder. A second protocol failure stops safely; it is never disguised as prose failure. After all owned writing segments pass, a compact ordered evidence packet performs one whole-draft causal, continuity, promise, and ending adjudication. `outputs/draft-integrity.json` binds those semantic receipts together with the plan, augmented constraints (including the causal chain), StoryState, location authority, exact event order, preceding-segment hash chain, each segment text hash, and the assembled draft hash. Any missing, duplicate, reversed, corrupted, stale-authority, or invalid segment stops before polish. A structurally compatible legacy complete-segment checkpoint is not blindly trusted: the Runtime first generates and validates its missing semantic receipt, upgrades the internal checkpoint to version 2, and only then reuses it. A changed current authority regenerates the affected prefix.

Semantic-receipt recovery is extractive and capacity-aware. When a reviewer has selected valid prose but joins several excerpts with ellipses or commentary, Runtime may replace only that evidence string with one unique, contiguous, sufficiently informative span already present in both the reviewer selection and the immutable prose. Weak, short, or repeated matches are never guessed. A missing descriptive summary is synthesized only when every hash, ownership, state, viewpoint, order, and evidence invariant already passes after alignment. If model repair is still required and the request merely approaches the safe context line, the shared stage boundary removes only the reproducible advisory layer; mandatory rules, current contract, relevant prose, and hash-bound story authority remain intact. Remaining capacity pressure uses semantic splitting rather than terminal interception.

Whole-draft review uses a Merkle-style evidence projection: every full segment receipt remains persisted and is represented to the global reviewer by its SHA-256 plus ordered event/beat IDs, one extractive proof per owned item, entry/exit state, causal evidence, and summary. If that complete projection still exceeds the route capacity or the provider reports a hidden smaller window, Runtime reviews adjacent segment windows and reduces their hash-bound receipts into one global causal, continuity, commitment, and ending verdict. Direct and Map/Reduce paths re-enter the same `validate_whole_draft_receipt` authority. Draft, polish, structural correction, targeted repair, and user-selected short revision all share this boundary; no path may treat successful leaf calls as whole-story success.

Full-manuscript review remains full coverage under context pressure. Paragraph-aligned manuscript windows overlap and every window must produce bounded evidence. If ordered evidence would consume more than 45 percent of the configured final-review context window, or a conservative 32K unknown-route window, Runtime groups contiguous evidence with boundary overlap and creates regional summaries. Every regional result must echo the exact source SHA-256, covered-window list, and ordered source issue IDs. Runtime carries every source issue object forward deterministically even when the reducer reports no new issue, so reduction cannot erase a known problem. Repeated occurrences of one stable issue ID are coalesced into one issue with deduplicated `evidence_records`; every distinct excerpt, location, severity observation, action, and source window remains available. Conflicting observations remain together for global adjudication and cannot silently overwrite one another. It repeats reduction only while coverage and source identities remain exact, then performs one global adjudication across the complete ordered hierarchy. Omitted coverage or issue identity, stale source hash, non-shrinking evidence, malformed regional output, exhausted reduction depth, incomplete global JSON, or missing issue reconciliation stops promotion; it never degrades to sampling. The configured provider/model context value controls the preflight when known, while unknown routes use the conservative default without paid capability probes.

These changes add JSON run artifacts and review fields only. They do not migrate SQLite, add a second StoryState, rewrite project materials, replace a formal outline, or publish a manuscript. Operational rollback is a code rollback; old projects and formal manuscripts remain unchanged, and newer non-authorizing diagnostics may be ignored.

Run events added or tightened by this flow:

- `draft_task_scope_retry`: an invalid leaf is being regenerated with the same target and event ownership;
- `draft_task_split`: a validated semantic split has started and records its reason and owned events;
- `draft_task_split_completed`: both children and their merged parent passed;
- `draft_semantic_gate_failed`: a leaf, parent, or root segment lacks hash-bound event/entry/exit evidence;
- `semantic_receipt_protocol_retry`: a segment-level reviewer receipt is malformed or incorrectly bound, so Runtime keeps prose unchanged and retries only the receipt;
- `whole_semantic_receipt_protocol_retry`: a whole-draft reviewer receipt is malformed or incorrectly bound, so Runtime keeps the assembled draft unchanged and retries only the receipt;
- `polish_semantic_subset_restored`: independently valid polish segments conflict after assembly, so Runtime isolates the conflicting formal segment or ownership group, retains a bounded deterministic whole-story-valid subset, and invalidates only rejected checkpoints;
- `polish_whole_semantic_preserved`: no changed polish segment can survive whole-story isolation, so Runtime restores the complete accepted pre-polish draft and its verified receipts before continuing;
- `revision_checks_preserved`: a structural-revision candidate newly removes required text or increases forbidden text, so Runtime restores the complete pre-revision candidate without erasing unrelated successful groups from other runs or batches;
- `short_revision_semantic_subset_restored`: final adopted repair groups conflicted as a set; Runtime retained a whole-story-valid subset and returned the isolated issues to unresolved state before terminal review;
- `draft_whole_semantic_gate_failed`: the ordered segment evidence cannot prove whole-story causality, continuity, promises, or ending;
- `draft_integrity_passed`: the complete segment/event/hash manifest passed;
- `planning_manifest_fragment_repair`: one formal-segment manifest fragment failed schema, event evidence, ownership, order, or boundary checks and is being repaired without changing the formal outline.
- `planning_gate_candidate_improved`: the smallest necessary segment combination strictly reduced the deterministic local-issue set and became the new best plan.
- `planning_gate_candidate_rejected_regression`: a local repair made no strict progress or introduced a new issue, so Runtime restored the previous best plan.
- `planning_gate_targeted_retry`: one bounded second attempt is repairing only the remaining local issues from the current best complete plan.
- `planning_manifest_fragment_ready`: one formal-segment fragment passed deterministic and semantic validation and was checkpointed.
- `planning_manifest_ready`: all accepted fragments were Runtime-merged and the complete version 4 manifest passed whole-story coverage, order, handoff, evidence, and receipt binding.
- `planning_manifest_failed`: independent repair budgets were exhausted or the merged whole-story manifest still conflicted; drafting did not start and valid earlier fragments remain reusable.
- Short causal-chain recovery reparses and revalidates each regeneration attempt independently. Two bounded repair calls are available after the initial response; malformed or incomplete attempts are not saved, while a later valid chain continues into execution-manifest generation without changing the accepted plan.
- `draft_integrity_failed`: the assembled draft did not pass and downstream generation stopped;
- `final_review_reconciliation_recovered`: a readable legacy reconciliation shape was recovered, but any missing or invalid ID still blocks promotion.

### Durable systemic completion and forward acceptance

For an open-world or systemic change to planning, recovery, structured model output, split/resume, or narrative authority, the operational completion boundary is no longer “the current error disappeared” or “the next stage started.” The production workflow must produce at least a complete draft candidate and then validate lossless split/merge ownership, segment-level and whole-draft semantic receipts, complete-draft integrity, whole-story logic and continuity, polish, and the quality gates that precede final review. Offline deterministic gateways may supply provider-shaped responses for this proof; maintenance tests never call paid APIs. A real-provider canary is an additional, separately authorized validation, not a replacement for deterministic coverage.

An independent forward-looking gate projects the changed mechanism through the causal chain, execution manifest, drafting, split/merge, polish, targeted and manual revision, final review, and formal promotion. Every reachable boundary must have test evidence or a concrete code-level exemption. Acceptance is monotonic: protocol/schema correctness cannot justify lower prose quality, weaker causality, lost character or knowledge state, timeline/viewpoint drift, pacing damage, missed setup/payoff, an altered ending, or expansion beyond user-selected revision scope. On regression, Runtime retains the last accepted complete candidate.

This is persisted repository policy and cannot be bypassed by opening a new task, window, process, or by compacting conversational context. Localized closed-world maintenance remains risk-proportionate and does not automatically require a full paid-provider run; the complete-draft requirement applies to user-authorized systemic workflow repairs.

### Current-project real-data snapshot acceptance

Production incidents and systemic workflow changes now require two independent offline data layers. The first is a fresh private, read-only snapshot of the user-designated current project or the project that produced the incident. It retains the actual StoryState revision, locked and confirmed facts, outline and ending authority, required character/world material, affected run artifacts, receipts, checkpoints, route-capability metadata, hashes, event ownership, counts, and payload proportions. The snapshot is copied into an isolated temporary project and database before execution. Tests may mutate only that copy; they must not change the live formal manuscript, chapters, Canon, StoryState, candidates, history, references, credentials, or checkpoints.

Snapshot construction excludes credentials, secret values, raw provider errors, machine-specific absolute paths, and unrelated private sources. Its report contains only a content-addressed manifest: source revision, applicable authority/artifact hashes, snapshot time, tested boundaries, and fixture-derivation version. Reports remain outside Git or in an ignored test-artifact directory, and stale snapshots are rebuilt when the source authority changes. Automated validation still replaces only the paid network boundary; it keeps the production workflow, validators, capacity and routing decisions, checkpoint recovery, and required downstream acceptance boundaries.

The second layer is a committed sanitized isomorphic fixture. It replaces real prose and volatile identifiers while preserving schema and topology classes, ordered ownership, counts, length/token-pressure ratios, failure shape, and stable invariant assertions. This keeps CI reproducible and protects private story material. The two layers are intentionally non-substitutable: a synthetic fixture cannot prove compatibility with the user's accumulated project authority, while a private snapshot cannot provide durable, shareable regression coverage. Changes that can affect new-book initialization or first generation also require a clean new-project fixture. Failure to obtain or safely complete the current-project replay limits the result to containment or unresolved status; a separately authorized real-provider canary cannot replace either offline proof.

### Short-fiction production-length acceptance

The console recommends at most 30,000 effective Han characters for the current short-fiction workflow, but the recommendation is not a hard input or validation limit. A request above that value is not rejected solely for length; it is outside the production-length acceptance matrix until separately measured.

Offline acceptance for changes to short-fiction planning, context capacity, semantic packets, drafting, polish, review, checkpoints, resume, or formal promotion now runs complete production-shaped workflows at 13,000, 20,000, and 30,000 effective Han characters. Small fixtures still test isolated invariants, but they cannot be reported as workflow capacity evidence. Each length must use the production stage assembly, route-capacity policy, semantic ownership splitter, hash-bound packet/checkpoint merge, semantic receipts, integrity checks, polish, final review, and applicable promotion gates; only the paid provider call is replaced by a deterministic offline gateway.

The fixture prose must contain distinct ordered events, character and knowledge changes, relationship progression, promises and payoff, and a confirmed ending. Repeated filler, copied padding, an oversized irrelevant appendix, or direct writes of a finished manuscript do not satisfy this gate. Success is a complete candidate at the requested length crossing the downstream quality and narrative-authority boundaries; a preflight stop or retained checkpoint is containment only. The 13K/20K/30K rule is persisted in `AGENTS.md` and the project Skill so it remains active after a new task or compacted context.

## Historical incident business acceptance

The following matrix is the minimum end-to-end acceptance boundary for previously observed production failures. “Recovered” means the corrected artifact crossed its next authoritative boundary; a logged rejection or rollback alone is containment, not resolution.

| Incident family | Automatic resolution path | No-regression proof | Terminal behavior after exhaustion |
| --- | --- | --- | --- |
| Initialization links, inverse relationships, and forward locations | Character preflight normalizes supported roles, rejects duplicate or mismatched inverse relationships, defers forward location links until worldbuilding, then reruns reindex, links, and validate. | The initialization batch snapshot restores all earlier character, world, and plot files if a later required stage fails. | Formal project materials remain at the pre-initialization snapshot; proposals and diagnostics remain retryable. |
| Queued/start visibility and model-route failure | Task state is committed before dispatch, emits queued and started events, and exposes primary/fallback failures without raw secrets. Transient transport errors retry the same route before configured fallback. | Network retry does not split or mutate narrative scope; every returned candidate still enters its normal stage validation. | The run becomes failed with a readable reason and no false completed event; valid checkpoints remain reusable. |
| Output limits, context pressure, and automatic splitting | Output-limit responses first gain same-route headroom, then split only by semantic ownership. Known input pressure compacts advisory context or changes topology while retaining lossless authority. | Every child, merged parent, complete segment, and whole story is independently validated; no mechanical truncation is accepted. | An unsafe or exhausted split preserves the complete parent or accepted prefix and stops or continues only independent work. |
| Plan format, canon, event ownership, order, and handoffs | Two bounded local attempts use the current best plan and exact remaining issues. Runtime selects the smallest segment combination that strictly reduces the issue set. | A candidate that introduces any new local issue or makes no strict progress is discarded; unaffected valid segments remain byte-for-byte unchanged. | The hash-bound lowest-issue complete plan remains resumable and drafting does not start. |
| Shared formal-event body and event-body integrity | The parser treats adjacent event IDs joined only by presentation punctuation as one shared executable scope when the following body is complete; genuine missing, duplicate, or reordered event bodies trigger repair of only the affected complete segment. | The accepted segment must still prove every event ID, actor/action/result evidence, order, handoff, and whole-plan consistency. | The best complete plan remains resumable and drafting does not start until the affected segment passes again. |
| Plan equivalence, character agency, causality, viewpoint, and ending | Receipt-only protocol repair keeps plan text immutable; semantic repair changes affected complete segments, followed by a remaining-segment rebuild when needed. | The stable hard-issue set must strictly shrink with no introduced issue, followed by local, adjacent-boundary, and whole-plan review. | The best complete plan and ledger remain reusable; causal-chain and drafting stages do not start. |
| Causal chain and execution manifest | The chain is generated or repaired separately from the accepted final plan; manifest schema, ownership, boundary, and semantic repairs have independent budgets. Exact accepted predecessor states and their hash are Runtime-bound into fresh next-segment fragments while model-authored additional entry states are retained. | Any plan mutation invalidates the old chain. Every repair re-enters JSON/schema, event coverage, actor/action, boundary, and whole-manifest validation; malformed state containers and unrelated semantic defects are never normalized by handoff binding. | Execution index remains pending and no draft call starts; accepted plan and valid fragments remain reusable. |
| Draft length, event evidence, entry/exit state, continuity, and split merge | Same-scope rewrite precedes semantic splitting; child two waits for child-one semantic acceptance and receives its accepted ending state. | Receipts bind exact prose hashes and excerpts; merged parent, complete segment, and whole draft must preserve event order, viewpoint, states, promises, and ending. | The failed segment and dependent suffix remain retryable while the longest valid prefix is preserved. |
| Ordinary polish, structural polish, targeted repair, and user-selected repair | The smallest authorized patch is tried first, then the affected complete segment or repair group. Conflicting adopted groups are reduced to a bounded deterministic whole-story-valid subset. | Source/authority hashes, protected passages, atomic beats, actor, viewpoint, entry/exit, adjacent handoffs, whole-story semantics, prose quality, and score floors are rechecked. | The last accepted segment, group, complete draft, or protected best candidate is restored; removed issue IDs return to unresolved. |
| Re-review, hierarchical evidence, and “最需要处理的问题” | Every prior stable issue ID is reconciled; long-review evidence is reduced through complete overlapping windows with source hashes and coverage identities. | Repeated issue IDs merge every distinct location and excerpt; omission cannot erase an issue, and resolved/preserved items cannot remain actionable. | An incomplete or stale reconciliation cannot replace the last valid quality checkpoint or authorize publication. |
| Checkpoint, resume, and formal promotion | Resume reuses only hash-bound artifacts whose outline, StoryState, constraints, context, plan, causal chain, manifest, segment chain, and manuscript bytes still match. | A stale later artifact invalidates only itself and its dependent suffix; a lower-scoring or semantically regressed candidate cannot replace the protected best. | Formal files and StoryState change only after atomic terminal review and promotion; interruption leaves the prior formal work intact. |

### Production incident memory

The planning repair-anchor incident is now a separate production family. When a model binds a whole segment (or a Markdown heading plus neighboring fields) as evidence, Runtime first maps that exact evidence to the smallest nested same-event authority block that has a sufficient semantic body and no heading. It never chooses a bare event label or arbitrary sentence. A candidate that collapses the complete event body is rejected and regenerated from the last accepted plan; after targeted attempts, only the affected complete formal segment is rebuilt. The original broad evidence remains in the receipt for audit, while the derived repair anchor is recorded in the recovery trace. This preserves creative detail and prevents a narrow patch from silently deleting event execution, reactions, or results.

The first-person narrator family is likewise distinct from ordinary viewpoint drift. A project-scoped narrative contract is resolved from explicit metadata, an unambiguous outline declaration, or one unique narrator/protagonist, then hash-bound into every draft, split, retry, polish, targeted/manual revision, and final-review task. Multiple candidates stop before prose generation with a user confirmation response; no stage guesses or silently changes the narrator.

The production-shaped planning replay also exposed an event-body boundary false positive: two adjacent formal events were intentionally realized in one complete sentence, but the first ID was incorrectly reported as incomplete. The shared parser boundary now accepts this representation without weakening genuine missing/duplicate/order checks. The incident catalog includes `planning.repair_anchor_collapse`, `planning.event_body_integrity`, and `narrative.first_person_contract_missing`; each has a stable matcher, an implementable recovery path, and production-shaped regression coverage.

Every terminal task failure now receives a stable production-incident identity in the existing `run_events.metadata_json`; no SQLite schema migration or second error store is introduced. The identity contains `incident_key` (workflow + stage + root-cause family), `incident_family`, a user-readable title, the implementable known resolution, same-boundary occurrence count, cross-boundary family count, and first/last-seen timestamps. Volatile run IDs, absolute paths, segment numbers, and character/token/error counts are normalized only for unknown-message fingerprinting. Known families use explicit root-cause matchers, so different novel names or error counts do not create false new incidents.

`model.context_capacity_preflight` records requests that reached the input-capacity safety boundary before a usable model result. Its recovery is not "stop safely": Runtime must retain the current complete authority, execute the applicable semantic packet topology, persist completed packets, merge them losslessly, and cross the next authoritative review boundary. The production-shaped fixture for run `dd0d6d2d981b4316a0c81d901bd38dc1` covers a 32K unknown Review route, six planning segments, 29 formal events, and a seven-event first segment whose original request required 31,537 input-plus-output-reserve tokens. Run `d785dd5c711c4bc785caec10977cf6bb` exposed a later boundary in the same family: review splitting succeeded, but a targeted planning repair inherited the complete planning stage's 12,288-token creative reserve, so 20,407 input tokens were incorrectly preflighted as 32,695 tokens. Targeted closed-JSON patches now use a bounded protocol reserve; complete formal-segment rebuilds use a scope-aware creative reserve based on that segment's expected size. Primary and configured fallback routes compute the same contract independently, and a residual preflight or incomplete candidate is recorded in the monotonic recovery ledger instead of terminating the entire task. The best complete plan remains authoritative, and any repaired candidate must pass local, adjacent, and whole-plan checks before causal-chain generation. `model.context_capacity_indivisible_scope`, based on run `e86225d9d6664243b4d8c4e45295144f`, is a distinct root cause: the seven-event input was 24,143 tokens, but the prior singleton still carried 23,146 tokens and 20,581 authority tokens. It now recovers through exact event projection, three facet receipts, complete overlapping evidence windows when needed, bounded JSON output reserve, and final parent/whole-plan revalidation. Legacy rows stored under the generic preflight family are refined lazily from their terminal evidence without rewriting history.

Run `cde98e16c1334f3c95def6e67d0740eb` exposed the same capacity family at an earlier and previously untested boundary: the initial IR-first `PlanningSemanticDraftV2` request exceeded the configured 32K planning route before any provider call, while the stage had no semantic capacity splitter. Review and repair splitters therefore could not help because the workflow had not yet produced a plan to review. Initial semantic planning now uses one Runtime-owned, event-contiguous packet topology; every packet retains the same registered `planning_semantic_v2` contract, binds its parent/input/event authority hashes, persists a reusable checkpoint, and may recursively split only at a formal-event boundary. Runtime merges validated packets into one canonical semantic document, recompiles it to prove exact collapsed event coverage and continuation/terminal topology, and only then enters causal-chain generation. It never falls back to legacy Markdown planning or truncates story authority. Production-length acceptance now runs the complete short-fiction pipeline at 13,000, 20,000, and 30,000 effective Han characters on a 32K planning route, including a forced mid-packet transport interruption and checkpoint reuse; all three cases must reach a hash-bound formal manuscript and committed StoryState. This distinguishes the product's non-binding 30,000-character recommendation from the test obligation: shorter fixtures remain useful for local units, but they cannot authorize a workflow/capacity change.

Run `155ea4c5db31421587505dd4a00b6819` exposed this family after the first draft segment: the initial semantic receipt covered 15 atomic beats but contained nine non-contiguous evidence strings and no summary. Receipt-only retry then required 24,679 input-plus-output-reserve tokens on the conservative 32K route and crossed the 75% safety line. The production fixture `tests/fixtures/semantic_receipt_context_capacity_24679.json` requires three successive behaviors: safe local alignment of unique reviewer-selected spans, lossless shedding of only the advisory context layer, and whole-draft adjacent-window Map/Reduce if a complete global receipt still does not fit. The regression crosses the next authoritative boundary by producing a validated segment receipt and a validated global receipt; merely classifying the preflight incident is insufficient.

The same run later exposed `planning.runtime_identity_echo_mismatch`: an otherwise valid single-event facet-window verdict repeated an incorrect `authority_sha256` even though its planning hash, exact window range, text hash, invariant shape, and current evidence IDs were valid. Runtime-owned request identity is therefore no longer treated as model-authored semantics at this boundary. A fresh response contributes only the facet verdict, current evidence IDs, changed dimensions, exact negative quote when applicable, and reason; Runtime wraps that payload with authority, version, segment, event, facet, window range, and hashes, then persists only hash-based conversion and binding audit. This local binding is permitted only for the direct response to the current immutable call. Historical checkpoints never use it and still require every envelope field, receipt hash, and source hash to match. Out-of-scope evidence, incomplete invariant maps, empty reasons, and unbound negative quotes trigger one same-window receipt retry and never authorize a planning or prose rewrite. The production-shaped regression is `tests/fixtures/planning_facet_window_runtime_identity_155ea4c5.json`.

The third controlled resume crossed that identity boundary and exposed `planning.reviewed_dimensions_echo_conflict`: the state facet marked every requested invariant true but copied the complete requested invariant-name set into `changed_dimensions`. Runtime first handles that exact leaf-level review-scope echo. The next controlled resume showed the general contract problem: providers also use `changed_dimensions` for story-internal knowledge, relationship, causal, and presentation progress, while the invariant map answers the different question of whether formal authority was preserved. The parent facet reducer now preserves the raw dimension report for audit, merges the complete invariant map, derives structural deviations only from explicit false invariants, reclassifies protected dimensions with true invariants as reviewed narrative scope, and retains free-form dimensions as equivalent presentation metadata. A false invariant remains blocking and evidence-bound; it is never erased by this reconciliation. Hash-valid historical facet and facet-window checkpoints are verified in their original form before deterministic migration. The parent event receipt is always rebuilt and passed through the unchanged full adaptation validator, so this separation cannot promote a planning or prose change by itself. The production-shaped regression is `tests/fixtures/planning_facet_reviewed_dimensions_155ea4c5.json`.

The following controlled resume crossed planning adaptation and causal reduction, then exposed `planning.execution_manifest_handoff_echo_mismatch`: an execution fragment described the accepted previous exit with provider-authored wording but omitted one exact predecessor assertion. Exact adjacent state and its versioned hash are Runtime-owned authority, not a model echo task. For a fresh fragment with a structurally valid entry-state list, Runtime now injects every missing accepted predecessor assertion, keeps all additional model entry assertions, and records only the source/bound hashes and added count. The unchanged fragment validator, adjacent-boundary validator, semantic receipt, and whole-manifest validator still decide acceptance. A malformed entry container is not normalized, and unrelated event ownership, evidence, order, producer, or semantic failures still consume their existing smallest-fragment recovery path. Historical checkpoints remain byte- and hash-strict. Replaying the failed fragment from run `155ea4c5db31421587505dd4a00b6819` changes only that authority binding and reduces its boundary issue set to empty without exposing or rewriting story text.

The next controlled resume exposed a semantic-role collision in the local planning compiler before it could reuse later checkpoints. The provider returned one complete, identity-bound event-realization table and a separate causal-chain explanation for every segment. Both are valid planning material, but the old field resolver classified the causal companion as a second `event` value, reported all six otherwise complete segments as missing a required field, and then sent the model into unnecessary whole-plan repair that progressively lost event-body identity. The local gate now applies semantic precedence: a causal-chain-only label is descriptive companion material when one unambiguous event realization exists; its source span stays byte-for-byte present but does not compete for the closed event role. A label that also explicitly declares an event, beat, or narrative progression remains eligible, and two different event realizations remain ambiguous and blocking. Synthetic Chinese/English regressions cross the complete local gate, while a hash-only replay of the real `planning.md` reduces the issue set from six false required-field failures to zero without changing the plan.

The subsequent controlled resume crossed the local planning gate and the earlier facet identity/dimension repairs, then exposed `planning.invariant_truth_set_shape`. The provider twice returned `invariants` as the exact set of all three requested invariant names instead of a boolean map; its evidence IDs were inside the current 37-item authority set, but repeating the model call reproduced the same valid semantic representation. Fresh facet conversion now recognizes only a closed, complete truth-set encoding: every requested name must appear exactly once, no unknown name is allowed, and `changed_dimensions` may not contain a partial protected-field conflict. That unique form expands deterministically to an all-true map and is recorded through the existing hash-only semantic-repair audit. Partial, duplicate, unknown, missing, or conflicting sets remain `invariant_shape` and retry only the same facet. Historical facet checkpoints remain strict, and the bound result still passes evidence, parent invariant, dimension-role, segment, and whole-plan validators. Replaying the real failed response crosses the fresh facet binding boundary with no issues and no story-text mutation.

That representation conversion is no longer owned by `workflows.py`. `generated_artifacts.CONTRACT_ADAPTER_REGISTRY` is the only versioned compatibility authority: every adapter declares its source topology, canonical topology, deterministic proof obligation, and provider/narrative independence. A successful conversion is Pydantic-checked and produces a content-addressed audit containing adapter/version, topology, transformation codes, and hashes only. Unsupported, partial, duplicate, unknown, conflicting, or inference-requiring inputs remain unchanged for the authoritative domain validator and typed recovery ladder. An architecture-budget regression test fixes the reviewed registry membership and fails if the truth-set transformation returns to an inline workflow normalizer. New provider, model, genre, project, entity, prose, or error-message literals are forbidden adapter inputs.

The fifth controlled resume then crossed the truth-set conversion and reduced two whole-plan hard issues to one without modifying four unaffected segments. A subsequent immutable segment receipt repeatedly returned `adaptation_order_uncertain`; all three protocol retries used the same review model even though a configured independent fallback existed, so `review_incomplete` terminated the run and the best complete planning candidate remained unpromoted. This incident is `planning.review_protocol_route_exhausted`. Receipt recovery now has a typed, bounded route schedule independent from semantic-mutation budgets: exact local conversion and domain validation, same-route receipt-only retry, configured fallback-route adjudication, and then checkpoint/best-candidate restoration if every route remains invalid. Planning segment, event facet, overlapping facet window, regional hierarchy, hierarchy reduction, and whole-plan receipt boundaries use the same schedule and always re-enter their unchanged evidence, local, adjacent, and whole-plan validators. A production-shaped regression reproduces three primary-route `adaptation_order_uncertain` receipts, accepts only a fallback receipt that passes the same contract, and continues through the whole-plan authorization boundary.

The sixth controlled resume proved that route isolation now works in production: two planning receipt boundaries exhausted their selected route, emitted `protocol_receipt_model_fallback`, and continued on the configured independent review route through identity binding and facet-window validation. A later `state` event facet still ended with `evidence_quote_unbound`. Hash-only replay showed that the selected-route response had no informative overlap with its selected Runtime evidence and remains rejected, while the fallback response selected known evidence and contained one unique, informative extractive span but did not duplicate that quote inside its descriptive `reason`. Literal quote duplication in `reason` was redundant provider echo rather than additional authority. Evidence binding is now a second versioned planning-facet contract adapter: it may replace only a fuzzy quote that resolves to exactly one sufficiently informative location across the selected Runtime-owned evidence, records a hash-only proof, retains the independently worded model reason and attaches the exact Runtime evidence binding to its canonical representation, and then re-enters Pydantic plus the unchanged local and parent semantic validators. Weak, repeated, multi-candidate, unknown-ID, empty-reason, and low-overlap shapes remain invalid and consume the bounded minimal-receipt recovery ladder. The same registered adapter is used by direct facets, capacity-split windows, checkpoint migration after raw-hash verification, and completion preflight; no event, facet, provider, model, genre, project, or prose literal is part of the decision.

The seventh controlled resume crossed the previously blocked state facet and the whole-plan receipt, then encountered a route rejection before the review provider produced a terminal message. Both configured review routes subsequently passed zero-project-data capability probes, so the failure was neither a missing endpoint nor story-semantic drift. The remaining defect was recovery ownership: `_stage` raised before the protocol schedule could decide whether to retry or use the configured fallback, and its generic gateway path could hide an internal fallback from the outer schedule. Every planning receipt schedule now selects an explicit primary or configured-fallback route, defers raw route-error persistence, and converts execution exceptions at one shared boundary into typed, hash-only reliability failures. Connection and timeout exception types are classified independently of provider wording. Context-capacity failures still escape to the semantic splitter instead of being mistaken for retryable transport. A transient primary failure therefore retries within the bounded protocol budget and then moves to the configured independent route; exhaustion raises a typed terminal failure that preserves the best checkpoint and resumable review state. Tests cover rejection before terminal response, transport interruption, hidden-fallback prevention, safe audit persistence, transient regional/window recovery, all-route exhaustion, checkpoint reuse, and continuation through the whole-plan gate. No status-, domain-, model-, genre-, project-, or prose-specific route branch was added.

The current catalog covers the production failures already observed in initialization location references and backlinks, inverse character relationships, provider connection loss, missing controlled tool output, output-limit truncation, causal-chain parsing and coverage, planning structural drift, atomic-beat ownership, draft segment integrity, split/merge length mismatch, prose-bound semantic receipts, polish validation, stale AI issue-ledger evidence, and unavailable semantic/final review. `GET /api/projects/{project_id}/production-incidents` returns both the project's aggregated occurrences and the complete known-family catalog. Legacy terminal failure events without incident metadata are classified when read. Older failed runs that predate the unified terminal event are also represented from their stored run error plus latest error-stage event, without rewriting either row. A recurrence emits `production_incident_recognized` with **已识别为历史同类问题** and the registered recovery path before the ordinary terminal failure event.

Repository development now has a mandatory forward-incident projection gate. Every L2/L3 source change must scan the complete production-incident catalog by root-cause mechanism rather than matching only the current message, project each applicable mechanism into structurally similar call sites and later workflow stages, explain why previous offline tests missed the production shape, and cite production-shaped recovery plus next-authoritative-boundary tests. The versioned report classifies every sibling boundary as fixed and tested, tested not susceptible, or not applicable with concrete evidence. A changed model-output boundary must cite at least six materially different valid realizations, two invalid or incomplete outputs, two capacity or transport faults, and invariant-based tests; a non-model change must cite concrete exemption evidence. Strict change inspection fails when this report is absent or incomplete; containment, checkpoint retention, idealized fake-provider success, a single canned article, and a new fail-closed error do not satisfy the gate.

An L3 change spanning more than two authority-critical modules also requires a versioned split-review report bound to the SHA-256 snapshot of the final core files. Each distinct reviewer may cover no more than two core modules and must cite concrete test evidence; the report must cover every changed core path exactly once. Missing, duplicated, stale, failed, or self-inconsistent slices keep strict inspection closed. This turns the former advisory “split review required” warning into a satisfiable but non-bypassable repository gate.

Generated prose tests therefore separate deterministic authority from open creative expression. They assert event ownership, actor-action-result binding, causality, viewpoint, timeline and knowledge state, handoffs, evidence hashes, issue identity, atomic promotion, and next-boundary continuation while allowing wording, dialogue, description, rhythm, and non-dependent micro-order to vary. Deterministic parameterized, metamorphic, mutation, property-based, and pairwise cases are preferred; recorded seeds and minimized failure fixtures keep exploration reproducible. For an affected model route, at least one local integration case retains the real `_stage` prompt assembly, capacity policy, role binding, primary/fallback selection, checkpoint handling, and validators, replacing only the paid network call with a deterministic fake gateway.

Incident recognition is diagnostic memory, not automatic proof of recovery. Each catalog resolution points to the owning workflow recovery path, and every newly observed family still requires a production-shaped regression fixture plus successful continuation across the next authoritative boundary. The initialization backlink family is automatically resolved: Runtime closes explicit `characters/*.md:locations` and `worldbuilding/locations/*.md:notable-characters` references in both directions, snapshots every affected character/location/index file, then runs `reindex`, `links`, `validate`, and initialization completeness checks. Unknown IDs and malformed or duplicate fields are never guessed; the whole Skill snapshot is restored on failure.

## Outline canon and short-story production gates

Outline comparison checks the candidate against the established protagonist, primary location, and main counterpart from project requirements, character materials, and confirmed StoryState facts. Conflicts require an explicit choice before application. Keeping the project fact rewrites the candidate consistently; adopting an unlocked candidate fact records it in existing `confirmed_facts`. Locked requirements remain editable only through project materials. No second canon store is introduced. When enabled, the comparison also shows a collapsed, advisory market-reference section with the sample count, opening signals, and common mechanisms; it never blocks applying an otherwise valid outline.

When an existing project's materials and outline describe different stories, the user may create an independent project from the candidate outline. The source project, files, candidates, runs, and model bindings remain unchanged. The new project receives the candidate as its first formal outline and regenerates people and setting through the existing initialization workflow after user confirmation.

Short-story planning must expose one numbered event block per generated segment. Every block names its opening handoff, owned event, and closing handoff; both handoffs cover character location, current action, relationship state, and known information. Invalid canon, missing ownership or handoff fields, or duplicated duties receive at most two monotonic local-repair attempts before drafting. Each accepted attempt must strictly reduce the stable problem set, introduce no new problem, and preserve every unaffected valid segment; exhaustion stops before prose generation with the best complete plan retained. Draft segments receive only their owned event block, the previous segment ending and exact closing handoff, and explicit continuity instructions. Severe length drift, repeated prose, production notes, mixed-script corruption, or an unbridged location change trigger one bounded rewrite and then stop while preserving completed output. Canonical full-text analysis runs after draft, after polish, and immediately before formal publication. Only deterministic punctuation, spacing, quote, control-character, and consecutive-duplicate repairs happen locally without confirmation; semantic and structural changes retain the existing model and user-confirmation flow.

The planner is asked to emit `### 第 N 段：标题`, while the local reader also accepts `段 N`, compact or spaced `第N段`, Chinese numerals through twelve, full-width digits, and `Segment N`. Numbered headings must contain exactly one ordered copy of every segment from 1 through N; extra, duplicate, or reordered headings fail before drafting, while headings hidden in HTML comments or fenced examples are ignored. A segment ends before the next numbered segment or the next same/higher-level Markdown section, so appendices cannot contaminate event ownership. Markdown-emphasized field labels and event IDs use an NFKC comparison view without changing their prose values. Causal-chain JSON accepts bare or HTML-comment markers and unfenced, three-or-more-backtick, or tilde-fenced payloads through the shared JSON boundary; unparsed markers remain a planning-gate error and are never activated as project learning. Outline headings accept spaces or tabs, common enumeration wrappers, and trailing section punctuation; stable event identities normalize width. Entries are classified as narrative beats, structural headings, themes, or directives, and old cached events are rebuilt from visible formal-outline content. Only narrative beats participate in required coverage and chronology; sparse chapter or act headings are fallback requirements only when their own scope has no narrative beat. An accepted planning repair replaces the resumable `planning.md` and invalidates any causal chain bound to the earlier plan bytes; an editorial review is reused only from the run that supplied the selected draft checkpoint. Structural revision targets normalize integer, `第N段`, `scene-N`, and `场景N` forms while rejecting booleans and out-of-range values.

## Outline material manifest and initialization recovery

Initialization derives one hash-bound material manifest from the confirmed outline. Markdown structure provides explicit names and beats, local NLP supplies candidates only, and the planning role may confirm or add evidence-backed entries. Every model entry must quote text present in the confirmed outline; character and location names must also occur in their own quoted evidence. Unsupported or cross-attached evidence is discarded. When the planning role is unavailable, strict local findings remain usable and the run records that the model review was skipped instead of failing an otherwise valid project.

Character completion matches confirmed primary names exactly. An unconfirmed alias cannot make one profile satisfy a differently named outline character, and a protagonist profile whose name conflicts with the formal outline blocks completion. Duplicate named world files, unregistered entities, empty arcs, empty timelines, and empty promise/question registries remain incomplete.

Character proposals are normalized at the project-file boundary before Story validation. The outline-only `counterpart` role becomes the supported `deuteragonist` role in character files and registries; empty or duplicate aliases are removed, and an empty aliases field is omitted. This deterministic repair does not change character identity or story facts and does not call a model.

Character bootstrap may preserve forward `locations` references because worldbuilding owns those files and runs next. Before character proposals can complete, Runtime rejects more than one structured relationship to the same target and rejects missing or incorrect inverse relationship types; additional dynamics stay in profile prose. The character stage runs `reindex` and `validate`, while `links` resumes after worldbuilding creates every referenced location and its `notable-characters` backlinks.

Worldbuilding application owns a deterministic bidirectional reference closure after model proposals are written but before Story CLI validation. It accepts LF or CRLF frontmatter, multiline reference lists, quoted IDs, inline lists, and `field: []`, preserves the original line ending and all prose, and adds only missing reciprocal IDs. Duplicate fields, duplicate IDs, malformed list content, unknown character IDs, and unknown location IDs fail closed and restore the complete Skill snapshot. Initialization completeness also checks these reciprocals, so a stage is not skipped over hidden broken links.

Initialization stage reuse is based on deterministic material completeness rather than the presence of a copied Skill-execution row. A cloned or isolated project with complete valid files therefore skips the stage and emits that its materials are already complete. Historical execution completion remains advisory; if current material checks fail, the stage repairs or regenerates as before.

The complete initialization sequence is one batch transaction in addition to each Skill's own snapshot. If a later Skill fails, story, character, world, plot, and continuity files return to their state before initialization and newly created Markdown files from the failed batch are removed. The formal outline and prior run history are never replaced.

The project-materials API and console do not count empty registry scaffolds as usable plot, timeline, issue, or world material. Each visible section reports effective document count, missing confirmed-outline items with quoted evidence, duplicate names, and active outline canon conflicts. Internal role and status values are localized before display.

### 正式稿晋升中断恢复

短篇正式稿晋升会在写入正式稿、章节稿和 canon 前保存哈希绑定的恢复载荷。若进程在 StoryState 已提交后中断，而部分正式文件缺失或损坏，下一次任务会从该载荷确定性重建全部晋升文件、重新核对哈希后再完成收尾。只有 StoryState 已超过该日志的目标版本时，旧日志才会标记为 `superseded`；目标版本本身存在文件不一致时不得清理快照或假报成功。旧日志若没有可验证恢复载荷会停止新写作并保留现场，不会把旧快照覆盖到已提交的新 StoryState 上。

### 第八次受控续跑：证据绑定与回执路由熔断

第八次受控续跑跨过容量分包、整篇规划回执和定向修复后，主回执路由在多个独立分面上连续于终止响应前拒绝请求；配置的备用路由能够返回完整 JSON，但其中一份负向回执引用了两个已知证据 ID，证据原句只在其中一个候选中唯一出现，说明字段却没有重复粘贴该原句。旧逻辑正确拦截了 `evidence_quote_unbound`，但容量拆分在处理供应商上下文异常的 `except` 栈内继续执行，导致该新语义异常继承旧容量异常为 `__context__`，外层分类器因而误报上下文容量问题。

修复仍由三个共享边界承担，不增加事件 ID、供应商、状态码、题材或项目分支。版本 2 的唯一证据适配器现在同时接受可证明唯一的模糊证据和“精确证据＋独立说明”形态：所选 ID 必须全部已知，原句必须只在一个所选来源的一个位置出现，说明必须独立非空；Runtime 只把已证明的原句附到说明后，再交回同一 Pydantic 与领域语义验证。完全重复、跨多个来源可匹配、弱匹配、未知 ID 和空说明仍进入最小回执重生成。精确匹配函数也要求来源内唯一，避免完全相同的重复短语被误绑定。

供应商容量异常现在只在原模型调用的异常处理块中生成拆分请求，真正的语义拆分在离开该异常处理块后执行；拆分器产生的新异常不再继承陈旧的容量上下文。持久化容量事件只记录供应商错误哈希，不保存原始错误。所有不可变回执共用按“运行、角色、显式路由”隔离的标准熔断器：连续两次供应商拒绝或传输中断后开路，后续有界计划跳过同一失败路由并转向配置的独立备用路由；冷却后只放行一次半开探测，任意到达验证边界的响应都会关闭熔断。熔断不吞掉根因，终端失败仍保留原始传输或供应商拒绝类型。备用路由最多进行两次同合同、同权威、只重生成回执的有界尝试，每次结果都重新进入适配、Pydantic、证据、局部、相邻和整体验证。

离线重放只输出哈希、计数、转换码和语义错误码。生产失败回执经版本 2 适配后形成一条 `runtime_evidence_binding_attached` 审计，语义问题集从 `evidence_quote_unbound` 变为空；正文、理由和密钥均未显示或写入日志。回归覆盖重复精确证据拒绝、跨中英文唯一绑定、适配幂等、容量异常上下文隔离、哈希化容量审计、连续路由拒绝开路、跨运行隔离、冷却半开恢复、熔断根因保留、首个备用回执无效后第二个最小回执成功、检查点恢复及后续整篇门禁。

第九次受控续跑真实验证了上述适配器、熔断、半开探测、备用路由双回执和检查点恢复：旧证据绑定阻断消失，主路由只开路一次，后续同类调用被跳过，备用路由的首个无效回执由第二个最小回执修复。流程最终在事件分面窗口收到明确的 `TransportInterruptedError`。该异常在第三方适配器内部创建时仍携带上层容量异常作为 Python 上下文，字符串分类因容量标记优先而把非终止传输误报为上下文超限，触发无意义的继续分包。统一路由边界现在把 `ConnectionError`、`TimeoutError` 和 Runtime 自有的 `TransportInterruptedError` 都按明确异常类型归为传输中断；嵌套消息只用于未知异常。回归构造“容量上下文中的明确传输异常”，证明稳定码为 `protocol_route_transport_interrupted` 而不是容量错误。该次失败没有通过正式晋升门禁，正式产物数量、总字节和聚合 SHA-256 与续跑前完全一致。

第十次受控续跑继续复用了 26 个检查点并完成 10 次容量合并，显式路由熔断、备用路由和最小回执重试均按设计工作，但两个备用回执都返回了通用质量评分表，而不是当前事件分面要求的不可变真值回执。根因不是新的字段别名，而是同一个调用同时携带了通用 `review` 系统合同和更具体的用户回执合同；备用模型遵循了优先级更高的系统合同。Runtime 不会把 `decision/dimensions/hard_fail/issues` 猜成 `invariants/evidence/reason`，因为两者没有可证明的语义等价关系。

六个规划回执边界现在统一使用独立的 `IMMUTABLE_RECEIPT_SYSTEM`，由当前用户消息声明精确字段、所有权、证据和不变量；它替换通用质量评分系统合同，但仍保留分层 Skill 与故事权威上下文。该覆盖只能用于有界协议输出，并进入节点输入哈希，防止旧检查点在系统合同变化后被误复用。生产形态的质量评分表被保留为拒绝样本，不新增适配器或特殊分支；正确回执仍必须重新经过版本化适配、Pydantic、证据、局部、相邻和整篇门禁。语义拆分器抛出的新异常显式切断陈旧容量上下文，分类器也遵守 Python 的 `__suppress_context__`，因此协议/语义错误不会再次被历史容量异常污染。异常上下文分类作为独立 L3 验收切片，以单独外部基线、聚焦回归和严格门禁验证，避免跨模块累计变更掩盖该规则。该次续跑同样未通过正式晋升门禁，正式产物数量、总字节和聚合 SHA-256 与续跑前完全一致。

### Capacity packet merge closure and embedded Markdown recovery

Complete formal-segment rebuild normalizes every accepted leaf to an explicit body-level event owner before parent merge. A singleton envelope may already bind its full body to one event, but that envelope-only representation is not sufficient once siblings are combined; the normalization marker preserves all narrative text and makes ownership closed under merge. The merged segment then reruns event-body, obligation, retention, adjacent-handoff, and whole-plan validation.

Planning-rebuild JSON also accepts one complete Markdown segment nested inside an otherwise open provider wrapper. Runtime validates the embedded segment through the same canonical parser, preserves the wrapper's exact ordered ownership, and rejects multiple distinct embedded candidates instead of choosing one by traversal order. This recovery path is presentation normalization only; it never changes formal plot authority or invents narrative facts.

The production incident catalog includes packet-merge closedness as a separate family so a future recurrence is recognized before the generic capacity-split terminal error and carries the concrete leaf-normalization and lossless-merge recovery path.

## Narrative Reliability Kernel V4

Planning transport now parses Markdown through one canonical document boundary backed by `markdown-it-py`. Exact source text remains authority. Numbered items, ordinary paragraphs, nested lists, block quotes, CRLF/LF input, and unknown presentation wrappers all become non-overlapping source-mapped blocks. An unlabelled continuation inherits the preceding explicit event only until a structural heading or the next explicit event. Fenced examples and HTML blocks never gain narrative ownership. Event review, evidence selection, and capacity packets consume this common ownership map instead of independently splitting on blank lines. The production fixture from run `93075987b1374e53bb13d13ecb53bc68` proves that the Pei Yanxing response remains inside `EV-BEAE4985`, does not leak into `EV-1522AB0E`, and crosses both packet and whole-plan review.

StoryState schema 3 adds a versioned `narrative_graph` and `narrative_rule_profile` inside the existing single authority. Claims distinguish world truth, public belief, and each character's perspective; their status is known, false, or unknown and their transition records assertion, reveal, revision, retraction, forgetting, or questioning. Identity, relationship, and promise records are additive and old projects migrate idempotently without rewriting project files. A candidate containing conflicting facts, an unexplained known-to-unknown regression, a changed actual identity, or a missing claim dependency is rejected before StoryState commit. Execution-manifest version 5 can carry the same typed claim on a state assertion while versions 2-4 remain readable and hash-compatible.

Core identity, knowledge, dependency, causality, timeline, viewpoint, promise, and relationship rules cannot be disabled by a genre. Composable packs add support requirements for romance relationship regression, mystery reveals, fantasy power changes, science-fiction capabilities, historical status changes, rebirth foreknowledge, and comedy misunderstandings. A genre rule requires hash-bound dependencies or exact evidence; it never treats a genre label as permission to weaken canon.

`RecoveryController` is the shared policy boundary for transport, credentials, capabilities, context capacity, output truncation, syntax/protocol, ownership/evidence, semantic invariants, quality regression, stale authority, and unknown failures. The ladder always starts at the smallest safe action and ends by restoring the best complete candidate. Candidate comparison requires a strict hard-issue reduction, no new hard issue, byte-stable unowned scopes, and no quality-floor regression. Strict progress refreshes only the still-failing unit's budget. Protocol errors do not spend semantic-repair attempts, and provider failures do not authorize prose mutation.

Every model `_stage` now records a SQLite `workflow_node_checkpoints` envelope containing run/node identity, StoryState-bound authority hash, input/output hashes, attempt, route fingerprint, finish metadata, and status. A model return is recorded only as `generated_complete`; it is not resumable as validated narrative authority. Existing stage validators, candidate promotion, planning/draft checkpoints, and formal-write journals remain the sole promotion path. Failed observations have no output hash, and a conflicting validated envelope is rejected. This table is additive, idempotent, and removed automatically with its run.

Successful model probes are route-local observations with a seven-day expiry. Their fingerprint binds protocol, normalized base URL, authentication mode, non-secret extra headers, and actual model name. Changing a route marks the observation stale; an expired or mismatched observation degrades operational structured output to locally validated `plain_text` and tool support to `auto` until reprobed. Legacy manually stored capability data remains readable, but once a route has an observed probe, the observation owns runtime capability. A 404 is reported as `route_endpoint_not_found` with guidance to check the base URL `/v1` ownership and protocol adapter; it never declares that the model itself does not exist. Credential rejection, rate limiting, timeout, and connection failure have separate diagnostics.

New workflow exceptions carry typed failure code, class, boundary, and unit identity into the incident catalog. Typed identity takes precedence over message regex; regex remains a compatibility adapter for legacy events. This prevents new provider wording or translated error messages from fragmenting known incident families.

Planning repair packets also use a representation-neutral boundary adapter. A provider may return a top-level event array, an event-ID mapping, nested event records, or a Markdown block whose title places the segment label before the number (for example `段规划：第5段／EV-...`). Entry and exit state may be a string, list, or structured object; objects are preserved by deterministic Unicode-safe serialization and remain narrative authority. Ownership is derived only from the explicit event-ID field or event-title declarations inside the owned event field. IDs mentioned in prose, handoffs, or a next-segment reference never claim ownership. Multiple identities, duplicate candidates, reordered events, unknown machine-control fields, or incomplete narrative bodies still fail closed and trigger a canonical retry.

When deterministic adapters cannot establish a unique packet after a normal
provider finish, Runtime keeps the generated content isolated and performs one
same-segment, same-event-set canonical rewrap. The rewrap receives immutable
segment identity, ordered ownership, outline basis, entry/exit state, source
hash, and generated-packet hash. It may repair presentation only; it cannot
expand the authorized story scope. Output sizing uses the bounded protocol
budget, still honors provider output-limit expansion, and re-enters the same
normalizer plus complete packet contract. This rewrap occurs inside the current
semantic attempt, so it does not spend another targeted-repair or full-segment
rebuild attempt. If it still has no unambiguous shape, Runtime records
`planning_packet_protocol_exhausted`, preserves the best planning checkpoint,
and exits as `parser.generated_artifact_shape` instead of reporting
`planning.structure_drift`. Conversely, a canonical packet that parses but
omits participants, collapses event prose, changes ownership, or violates a
narrative invariant remains a semantic candidate failure and never receives a
presentation-only retry.

Protocol rejection is tracked separately from route availability. A normal model response that fails packet shape or semantic contract cannot be reported as “repair call unavailable” and cannot consume provider-route failure state. Only current-run credential/binding rejection or transport exhaustion emits `planning_adaptation_unavailable`; historical execution failures remain audit evidence and do not poison a later resume. A repair budget exhaustion instead reports the retained best candidate and the exact remaining packet or semantic issues.

### Event-obligation completion and automatic capability routing

Before a planning repair spends a model call, Runtime compares every missing
participant against the hash-bound obligation checklist projected from the
formal outline. If exactly one formal obligation owns the missing participant,
its source excerpt still matches the recorded SHA-256 value, and the affected
event has one unambiguous owned body, Runtime appends that exact excerpt inside
the event. It never paraphrases or invents plot facts. Ambiguous sources,
foreign event IDs, hash mismatches, or unclear ownership fail closed and keep
the best checkpoint for the normal event/segment recovery path. The repaired
candidate must still pass event-body retention, obligation, adjacent-handoff,
and whole-plan review; unaffected event bodies remain byte-for-byte unchanged.

Candidate generation failures are counted separately from accepted semantic
repair candidates. A malformed packet, failed canonical rewrap, transport
interruption, or temporarily unusable structured route therefore cannot spend
the two semantic repair opportunities. Canonical planning rewrap may continue
through enabled models whose stored probe result satisfies the required
structured protocol. Configured primary and fallback routes remain first, and
unknown or insufficient capability records are never promoted by model-name or
vendor inference. The console intentionally exposes only the probe action and
read-only detected result: context window, maximum output Token, and manual
capability downgrade controls are runtime-owned and are no longer editable.

### Canonical participant identity and narrative realization (V6)

Formal-outline participant names remain canonical identity. A ready project
narrative contract may additionally declare how that same narrator is realized
in a first-person narrative voice, such as `花穗 -> 我`, `Mara -> I`, or a
project-defined self-reference in another language. Runtime binds this typed
realization only to events that already require the canonical participant; it
does not add participants, infer nicknames from prose, or retain aliases from a
different project. Ambiguous first-person contracts and all third-person
projects produce no alternate realization, so their existing literal identity
checks are unchanged.

An alternate narrator reference counts only in the event-owned, non-dialogue
narrative voice. Chinese, Japanese, and straight double-quoted speech is masked
by a deterministic quote scanner before matching; nested and unclosed quotes
fail closed. Therefore another character saying “我” or "I" cannot satisfy the
narrator's required participation. The canonical name itself remains valid, but
unknown nicknames, mismatched canonical identities, quoted-only references, and
an omitted second participant remain blocking issues.

This is a validation correction, not a prose rewrite. Runtime must not insert a
third-person narrator name merely to pass a first-person plan. A valid plan
continues through the normal semantic planning review and the whole-story causal
chain boundary. A genuinely incomplete event retains the existing complete-
segment rebuild, monotonic best-plan checkpoint, adjacent-boundary review, and
whole-plan review. Production recurrences use the dedicated incident family
`planning.participant_identity_realization_mismatch` instead of being hidden
inside generic planning structure drift.

### Durable semantic packets for causal-chain capacity recovery

Whole-story causal-chain generation no longer uses a fixed half-by-event split.
When input preflight, provider context rejection, or a repeated output-limit
finish makes the root request unsafe, Runtime builds a content-addressed semantic
task tree. It bisects at the nearest complete planning-segment boundary first and
uses a contiguous event boundary only when one segment remains too large. A
split changes execution topology only; it never changes formal event ownership,
the confirmed ending, or the complete requested story target.

Every causal packet contains an immutable Pydantic contract binding the formal
authority hash, parent and task identity, recursion depth, exact ordered owned
event IDs, read-only neighbouring event IDs, planning segment numbers, and the
preceding accepted sibling hash. Context IDs may overlap between prompts for
continuity, but they can never appear in a packet's promoted ownership. Packet
results must contain the exact ordered coverage and at least one closed
`obstacle -> effort -> result -> state_change` cycle. Only the packet owning the
first event may supply `core_goal/opening`, and only the packet owning the last
event may supply `ending`.

Validated leaves and deterministic reductions are atomically stored under
`outputs/causal-chain-packets/` with content-addressed names and mirrored as
workflow-node validation checkpoints. Resume reuses only checkpoints whose
contract, authority, predecessor, payload hash, ownership, and local semantics
still match. The SQLite checkpoint retains the exact validated packet as a
durable mirror, so a missing or corrupt artifact is restored byte-for-byte
without another model call. A stale later packet invalidates itself and its
dependent suffix; it does not revoke an earlier validated prefix. Legacy numbered packet
files are retained for audit but are not trusted as V2 authority because they do
not bind all of these fields.

The shared stage executor now treats a second output-limited response as a
semantic-capacity signal whenever that call declares a semantic splitter. It
invokes the splitter instead of repeating the same oversized request. Complete
but invalid causal JSON receives one same-scope protocol retry and then converges
to the same packet tree. An indivisible event that remains incomplete uses the
planning role's configured fallback route. Partial text is never mechanically
truncated or promoted. Deterministic reduction must prove exact ordered coverage,
then whole-chain validation must pass before the execution manifest can become
`ready` or drafting can begin.

### Typed terminal planning boundary and owned Markdown envelopes

Planning now distinguishes an adjacent handoff from the final segment's
terminal closure. Intermediate segments must bind their exit state to the next
segment's opening; the last segment instead binds the formally confirmed ending,
the exact final event ownership, and any intentionally retained open
obligations. A missing next-segment handoff on the terminal segment can therefore
be migrated deterministically when that ending authority is complete, while an
empty intermediate handoff or an unprovable ending still fails closed.

Runtime-owned planning fields are content-addressed envelopes. Markdown
presentation scans mask each complete envelope as one atomic region before
looking for segment headings, so an authenticated outline, event body, or ending
that contains its own Markdown headings cannot split the plan or truncate the
field. The compiler still verifies the envelope role, token, and SHA-256 before
the value becomes planning authority; masking presentation does not make an
invalid envelope acceptable.

### Durable completion and IR-first rollout

Run-level provider interruptions are supervised by a durable SQLite envelope.
`waiting_provider` is an active, cancellable state with a persisted retry time;
a restart retains the wait or converts an in-flight recovery state to
`interrupted`, then resolves the stored operation inputs and resumes from
validated checkpoints. Credential and capability failures wait for user action,
while transport retry budgets are independent from the existing node-level
protocol, semantic, and quality budgets. Resume payloads contain workflow inputs
only and never provider secrets. They are closed, workflow-versioned contracts:
long chapters persist one normalized goal, targeted revisions persist the frozen
ordered issue IDs, and Skill initialization persists the accepted outline hash,
Runtime-owned answers, and the frozen learning snapshot. Validation happens
before a run is created or claimed, so an invalid payload cannot leave an orphan
`queued` writer. Startup reconstructs `initialize-skills` and rejects a stale
outline rather than replaying with changed authority. Workflow-attempt numbering
uses a SQLite immediate transaction so concurrent recovery auditing cannot lose
or duplicate an attempt. An unknown supervision contract version is not guessed;
the run moves to `waiting_user` until an explicit compatible migration exists.
Run creation or resume activation writes the run row, supervision envelope,
initial attempt, and queue event in the same immediate transaction. Worker entry
does the same for the running transition and started event. Synchronous launch
or worker-entry failures are compensated to `interrupted` with a typed,
hash-only incident record; raw provider messages, paths, response bodies, and
credential-like values are never persisted.

Worker outcomes use the same transaction boundary. Completion, provider wait,
terminal failure, and cancellation each update the run row, supervision
envelope, attempt ledger, public event, and applicable production-incident
metadata under one `BEGIN IMMEDIATE`. Policy classification is calculated
without persistence first, so a crash cannot leave `running/irrecoverable` or
`completed/running` halves. A local outcome-commit fault is retried once, then
uses a fixed hash-only degraded audit event while preserving the already-decided
business outcome: cancellation stays cancelled, exhausted work stays failed or
`waiting_user`, completion stays completed, and provider wait retains its retry
time and budgets. Only failure to write the target state rows themselves moves
both authorities to `interrupted`; that envelope stores the intended outcome so
startup can reconcile it without blindly replaying completed or cancelled work.
Startup also idempotently reconciles legacy split terminal pairs created before
this boundary existed. Provider retry is scheduled only after the durable
`waiting_provider` pair and its attempt/event ledger have committed.

New short-story planning is IR-first for every project. It generates
`PlanningSemanticDraftV2`, injects Runtime-owned event identity and terminal
topology, and renders the legacy five-field Markdown only as a compatibility
projection for downstream readers and resumable historical artifacts. The
rollout-flag API remains readable for older clients, but it cannot switch a new
production run back to provider-authored Markdown. Legacy Markdown is accepted
only through the explicit read/migration boundary. The only tolerant wrapper
conversion is the registered, versioned unique-envelope adapter; ambiguous
candidates and machine controls fail closed.

Planning adaptation and recovery also keep machine controls outside model
output. A model returns only ordered `{event_id,narrative}` realizations;
Runtime reattaches the accepted heading, ownership, outline basis, opening, and
handoff byte-for-byte. Causal packets receive explicit Runtime topology flags
for opening and ending ownership instead of inferring those roles from event-ID
shape. Execution-manifest fragments use compact, event-owned story indexes and
a protocol-sized output reserve before the provider call. Draft integrity binds
the immutable pre-run constraints hash passed by the pipeline; it never locates
that authority by splitting on a prose heading that may already exist in an old
project.

Every accepted draft segment is sealed with authority, input, output, entry,
exit, quality, and dependency hashes. Exact repeats are idempotent, and a
changed event or beat invalidates only dependent units. Existing
whole-manuscript quality candidate competition remains the promotion authority,
so sealing does not allow a locally valid segment to replace a better protected
manuscript.

Reference learning reduces all windows through resumable exact-coverage
regions. Runtime injects child manifests and hashes at every promoted level; no
fixed full-reference character truncation is used. Region capacity and dispatch
use one versioned `reference_synthesis` route plan. A viable primary/fallback
pair uses their safe common lower bound; a primary that cannot hold one semantic
packet is bypassed in favor of a viable fallback, while a primary-only binding
executes the primary directly. Region and final synthesis calls share the same
executor. Structured-output headroom and fixed prompt overhead are reserved per
route; an unknown third-party route is planned conservatively as 16K.
Both serialized character size and estimated input tokens are enforced. The
final synthesis separately reserves its actual local-candidate context, and a
large local catalog becomes a content-addressed Runtime registry instead of
being truncated. A reduction level that neither lowers packet count nor token
size is rejected within a bounded depth, so route adaptation cannot loop
forever. Validated region cache rows
are immutable under concurrent writers and bind the content purpose, focus, and
version-2 receipt contract. Every child is explicitly marked as promoted or as
having no transferable claim; a promoted child cannot yield an empty semantic
result. Promoted children have an exact one-to-one attribution ledger and must
reach Runtime-resolved non-empty semantic JSON pointers. Direct
claim/uncertainty paths are unique; shared semantics must use an acyclic typed
merged/superseded relation to one anchored child. Free-form reason text is never
accepted as coverage proof, and cyclic or missing A/B attribution fails the receipt. Project
creative recipes contain transferable mechanism/style data and
hash-only provenance. Missing blueprint/recipe sidecars or either half of an
interrupted derived-artifact write are rebuilt idempotently. Style rules remain
in the prose/style bucket and are not injected as plot-structure mechanisms.
Competitor sources remain risk-only and cannot be adopted as creative guidance.
The final synthesis is itself a `DistillationReceiptV2` region, so a semantic
claim that survives the hierarchy cannot disappear at the last model call.
Normalization is followed by the same attribution validation before the final
semantic payload is accepted.

Publication analysis compares all distinct local reference versions with
independent literal winnowing, semantic-candidate, and event-chain gates. Hard
evidence triggers only segment-scoped regeneration and a complete recheck;
review-only semantic windows never cause automatic rewriting. Originality audit
rows contain offsets and hashes, not source prose. Full operating and rollback
instructions are in
`docs/superpowers/specs/2026-08-11-durable-completion-ir-originality-r0-r6-design.md`.
The analysis cache is also bound to a text-free reference-corpus authority hash
covering every visible source/version ID, content hash, use mode,
classification, and project scope. The authority and chunk stream use the same
database snapshot, so a concurrent new version cannot be scanned under a stale
hash. These fields are bound to `manuscript-analysis-v5`; earlier analysis cache
files, or reports created against a changed corpus, are regenerated before they
can participate in a publication gate.

## R0-R6 final publication and maintenance boundaries

Short-story publication is a single-writer, recoverable promotion. Runtime
acquires the project mutation lease, compares the current reference-corpus
authority and StoryState revision before any formal write, then promotes
`manuscript/story.md`, the chapter view, the publication receipt, canon, and the
next StoryState under one snapshot-backed saga. A stale corpus retries only the
originality/publication/quality closure at most once; a persistently moving
corpus preserves the candidate and writes no formal artifact. A stale
StoryState detected before this run touches formal files is never "recovered"
from the run's older snapshot, because that would overwrite a competing valid
promotion. Candidate publication through the API uses the same project-idle,
corpus-CAS, snapshot, and rollback boundary. After acquiring its publication
lease and mutation lock, it re-resolves the current candidate and compares a
versioned authority containing the source run, project-relative source path,
exact source-byte hash, and normalized-manuscript hash; a newer run, path, or
byte-equivalent-looking source cannot be promoted under an older decision. The
publication journal's committed state is the filesystem commit point. Its
snapshot remains available until the terminal database status is durably
written and read back. Before startup finalizes a committed journal, it verifies
the exact byte hashes of the formal manuscript, chapter projection, and
publication receipt plus the receipt's source-run, manuscript, and reference
corpus bindings. A missing, changed, or mutually inconsistent committed
artifact restores the verified snapshot and records a failed publication;
only a complete write set may become `completed`. Startup otherwise
idempotently finalizes a valid committed journal or rolls back a merely
prepared journal. Provider exceptions exposed by these APIs
are stable redacted codes; only the API-owned Pydantic input contract may
produce the fixed safe 400 response, while provider/parser failures—including
`ValueError`—map to a fixed safe 502. Raw response text, paths, and credentials
are not returned or persisted.

Editorial eligibility precedes score comparison. A `passed` candidate can be
replaced only by another fully authoritative `passed` candidate; a higher-score
`conditional_pass` or `failed` candidate cannot become the protected best or a
formal manuscript. Any originality repair or other prose mutation after an
earlier quality decision creates a new hash-bound semantic integrity artifact
and reruns the applicable terminal review. Formal promotion requires
`quality-report.json`, `quality-checkpoint.json`, the selected prose, and the
terminal reviewed hash to agree exactly. A rejected post-quality mutation is
stored as a separate diagnostic candidate and never overwrites the last passing
best/checkpoint pair.

Maintenance output is an incremental proposal, not a replacement canon.
Runtime preserves confirmed and locked facts, deep-merges unmentioned character
state siblings, and accepts an existing scalar change only through an exact
typed transition (`character`, dotted `field`, `from`, `to`, and exact prose
evidence). Missing fields do not delete authority. Conflicting fact keys or
state paths receive one bounded typed repair that includes the rejected
proposal, every already-preserved safe unit, and the hash-bound authoritative
manuscript. The only implicit shape adaptations are provably unambiguous
singleton-to-list conversions for a world rule or timeline item; each writes a
versioned adapter audit.

When the complete maintenance request cannot fit the safe primary/fallback
context, `MaintenanceWindowContractV1` covers the entire publication with
ordered, overlapping, hash-bound windows. A still-large window is recursively
bisected at a prose boundary without truncation. Model receipts contain only
typed semantic deltas with unique exact evidence spans; window identity,
StoryState entry hash, coverage, ordering, deduplication, and reduction belong
to Runtime. Conflicting units are removed from the accepted projection and only
their window is repaired. The sealed reduction stores accepted envelope hashes,
coverage spans, rejection provenance, and a canonical hash, then Runtime
replays every accepted unit from the source StoryState before accepting canon.
Models cannot claim Runtime bundle/reduction versions. Per-window checkpoints
bind the contract, entry-state hash, receipts, and replayed result, allowing a
restart to reuse valid leading windows while invalidating only the changed
window and its dependent suffix.

The parser-authority invariant remains a P0 gate: all model-produced structured
objects pass through `GeneratedArtifactGateway` and the versioned contract
registry. Local `json.loads` is used only for Runtime-created, source-provenance
sealed artifacts. Adding a convenient second parser in a workflow is a release
blocker even if its functional tests pass.

Execution-manifest version 6 makes source evidence content-addressed. Planning
adaptation retains the ordered Runtime evidence catalogue (`evidence_id` plus
exact text) once per event; a beat carries only non-empty, unique, contiguous
`source_evidence_ids`. Raw evidence text is not duplicated across beats or
serialized into a version 6 manifest. The registered
`execution_manifest_evidence_reference` adapter accepts an explicit valid ID
sequence, a uniquely mappable legacy exact atom sequence, or a uniquely
extractive presentation-normalized span. It never uses actor, genre, provider,
project, or semantic similarity to choose among multiple candidates. Unknown,
cross-event, non-contiguous, conflicting, or ambiguous references remain a
protocol failure and trigger the bounded fragment recovery path. Adapter audit
contains only version, transformation codes, counts, and hashes. Historical
version 2-5 manifests remain readable through their original byte/hash
authority; they are not silently rewritten as version 6 checkpoints.

Protocol-only receipt recovery is semantically monotonic. Once an execution,
segment-draft, or whole-draft receipt has a complete positive semantic
projection and fails only its schema, coverage, identity, evidence, or hash
envelope, Runtime freezes the hash-bound semantic projection. A same-route or
fallback receipt retry may repair only protocol-owned fields. A later retry
that changes a previously proven actor, action, causality, continuity,
commitment, or ending verdict is restored to the frozen projection and records
`receipt_semantic_drift_contained`; it cannot spend a semantic-repair budget or
authorize manifest/prose regeneration. An explicit semantic-negative receipt
that was valid on its first authoritative attempt is still a semantic failure
and follows the normal smallest-scope repair ladder.
### Project-level refactor business preservation

Infrastructure convergence uses `wrap -> shadow/parity -> switch -> delete`.
Before a parser, route selector, retry loop, checkpoint reader, reducer, or task
lifecycle is replaced, the existing path supplies invariant oracles for event
ownership, character and knowledge state, causal and relationship progression,
promise/payoff and ending authority, quality outcome, recovery behavior, and
formal-promotion eligibility. The shared Runtime may improve representation,
auditing, or recovery topology, but it does not replace those business
validators.

The new path first runs against the same production-shaped input and must yield
the same canonical business result. A mismatch preserves the last accepted
artifact and old authority path, records only content hashes and a stable
failure code, and prevents the old implementation from being deleted. A change
to novel policy is handled as a separate, explicitly authorized change contract;
it is never hidden inside a refactor. Deletion requires reachability evidence,
focused parity tests, the applicable private current-project replay and sanitized
fixture, the 13K/20K/30K matrix when the complete short-fiction workflow is
reachable, and the full test suite. Formal manuscripts, Canon, StoryState, and
accepted checkpoints are never experimental parity outputs.

### Structured-output Runtime V3 rollout status

The shared Runtime now owns exact JSON parsing, syntax-only repair, registered
representation adapters, explicit primary/fallback routing, bounded
same-task protocol retry, contract-version matching, and hash-only conversion
audit. The generic Runtime never asks a model to rewrap an invalid raw candidate
and then assumes semantics stayed unchanged. Registered local adapters must
prove a unique canonical projection; otherwise the immutable original task is
rerun and revalidated. Specialized receipt repair may freeze semantics only
when Runtime already owns and compares the semantic hash.
Business modules still own their typed domain validators: moving a call into the
Runtime does not replace event ownership, source offsets, locked fields,
Chinese-output requirements, causal validation, quality gates, or promotion
eligibility. `learning_artifact` remains a read-only compatibility identity;
new reference-window model calls use the specific version-2
`reference_analysis_window` contract, while final and hierarchical distillation
use `reference_distillation_region`.

### Material-audit full authority and atomic issue-ledger commit

Material consistency auditing no longer truncates the project reference at a
fixed prefix. `MaterialAuditReferenceAuthorityV1` inventories every eligible
reference file and divides it into exact, contiguous, content-addressed spans.
Every manuscript window is compared with every reference span through the
registered `material_audit` contract. Validated packet receipts use the common
workflow-node checkpoint envelope, so restart reuses completed pairs and never
claims a partially scanned reference as complete.

This infrastructure migration intentionally preserves the existing business
meaning of each issue (`category`, `severity`, descriptive `evidence`,
`location`, old/new setting, and action). Runtime reduction removes only fully
identical issue objects; it does not reinterpret, weaken, or merge distinct
story conflicts. The final `conflict-report.json` and optional
`StoryState.issue_ledger` transition commit through `ProjectMutationJournalV1`.
A failure before durable artifact staging rolls both back; an interruption
after staging resumes the exact report/StoryState transition at startup.

Managed style analysis writes `style-samples/reference.txt`,
`style-samples/profile.json`, and `style-profile.md` under one project lock and
`ProjectSnapshot`. Analysis or deletion failure restores all pre-operation bytes
and discards the temporary snapshot. This is a transaction-safety change only;
the style extraction schema, managed block, source-length rules, and project
style scope are unchanged.

The private current-project replay remains outside the repository. Its report
contains only hashes, counts, topology, ranges, and conversion codes. On the
2026-08-12 fresh isolated copy, the 13,000-character current project completed
IR-first planning, planning adaptation, causal-chain reduction, execution
manifest generation, segmented drafting, segment and whole semantic receipts,
polish, final review, formal-promotion Saga, and StoryState commit. Ten required
authority artifacts were present, the cloned formal manuscript was 45,271
bytes, paid API calls were zero, and a complete pre/post tree-authority check
proved that the source project did not change. The replay report is stored in
the operating-system temporary directory and contains no raw prose or project
identifier. This is verified production-shaped compatibility evidence, not
permission to alter the live project and not a substitute for the committed
sanitized fixtures, the 13K/20K/30K matrix, or the frozen full suite.

The offline complete-flow matrix currently passes at 13,000, 20,000, and 30,000
effective Han characters. Each case reaches a formal manuscript and checks target
length, unique paragraphs, ending commitments, quality status, terminal-review
hash equality, planning/causal/manifest/draft/polish/final artifacts, and
StoryState commit. This evidence is rerun after later authority-critical changes;
it is not used to justify skipping the private replay or full suite.

### Mixed project-file, StoryState, and StoryMemory transactions

Project files and SQLite StoryState cannot share one database transaction, so a
plain file snapshot is not a complete rollback boundary. New mixed-authority
mutations use the versioned `ProjectMutationJournalV1` Saga: `prepared` binds the
rollback snapshot and expected StoryState revision; `artifacts_committed` binds
exact staged target bytes and the optional candidate state; `committed` proves
both authorities and leaves only idempotent terminal bookkeeping. Normal
execution and startup recovery use the same completion function.

The journal may also carry typed, idempotent StoryMemory projections. Canon
facts retain the old `INSERT OR IGNORE` behavior, while chapter-index and
chapter-state projections are content-hash bound and replayable. Long-form book
setup now commits its book plan, Canon, optional volume map, and Canon-memory
facts through this boundary. Long-chapter publication now uses the same Saga
for the chapter, Canon, voice metrics, chapter index, and chapter state. Its
existing post-publication volume audit remains a separate domain-owned second
phase: a blocked audit preserves the published chapter for repair, while a
restart after artifact staging resumes the exact memory projection and volume
audit without regenerating another chapter. The generic transaction kernel
cannot finalize a journal that declares this gate; only the long-chapter domain
owner may do so after the original audit passes.

Recovery may roll a target forward only from the snapshotted old hash or the
already-committed target hash. A third hash is an unknown concurrent edit and is
never overwritten. Failure before the target bundle is durable restores the
old files and rejects the operation-owned pending candidate. Interruption after
that point keeps the bundle and finishes the exact StoryState transition;
failure to write the terminal run status cannot roll back an accepted business
result.

Material-impact application, manual material editing, formal outline
application, material-audit report/issue-ledger publication, and long-form book
setup/chapter publication are switched consumers. The material edit additionally stages its
optional material-impact artifact, while material and outline paths both carry
an exact `LearningArtifactInvalidationV1` ledger. The ledger freezes row ID,
artifact type, version, source hash, and active-to-stale transition; its DB
update validates the entire set before changing one row and is idempotent on
restart. Readable learning sidecars are content-addressed target files, not a
second source of truth.

Proposal selection, exact excerpt checks, target hashes, material projection,
outline conflict choices, locked-fact validation, narrative graph validation,
and API success payloads remain in their original business services. A path is
switched only after normal, rollback, and restart parity tests; partial
infrastructure migration is rejected rather than silently dropping business
behavior. The detailed state machine and rollback proof are recorded in
`docs/superpowers/specs/2026-08-12-project-authority-transaction-design.md`.

The shared structured-output Runtime follows the same rule: infrastructure may
be shared, business contracts may not be collapsed. Atomic-beat, segment,
whole-story, capacity-window, and global-reducer draft receipts now have
separate registered identities. Final verdict, final-review window, regional
reduction, detail evidence, and reader simulation are separate contracts as
well. Structural revision plans are distinct from one-issue revision patches;
short StoryState maintenance is distinct from long-book setup and long-chapter
memory maintenance. Their existing prompts, domain validators, quality gates,
and promotion behavior remain authoritative while parser, route, protocol
repair, and audit mechanics converge underneath them.

## Residual architecture convergence

The final residual-convergence pass keeps business authority where it already
lives but removes competing infrastructure behavior. `SafeFailureEnvelopeV1`
is the sole public and persistent exception projection. Raw exception text may
still be inspected in memory by the incident classifier and hashed for
correlation, but API details, run errors, events, checkpoints, and sidecars
receive only a stable code, family, fixed safe message, retry guidance, and
hash. Local Pydantic/domain validation feedback may remain actionable only
after deterministic secret and path redaction.

`WorkflowCoordinator` now owns public workflow selection, project-mode guards,
and optional CrewAI wrapping for all six project workflow families. The
facade's `run_*` methods delegate to it; planning, causal, manifest, draft,
polish, revision, maintenance, quality, checkpoint, and promotion validators
remain single-copy domain authorities in `WorkflowService`. This is a modular
monolith boundary, not a second workflow engine. Material audit/repair
coordination lives in `materials_workflow.py`, and long-book setup/chapter
publication coordination lives in `long_workflow.py`; both call the existing
service validators and transactional commit helpers. The short-story and
short-revision pipelines remain the single formal-promotion authorities in
`WorkflowService` because splitting those transaction closures would duplicate
or weaken their checkpoint/quality/StoryState commit semantics.

FastAPI asynchronous durable recovery is registered through one lifespan and
is idempotent per application instance. Existing construction-time candidate
publication and project-file Saga reconciliation remains synchronous because
the project store must not be exposed before interrupted authoritative writes
are reconciled. Deprecated `on_event` registration is prohibited by source
tests.

The source tree also has a permanent UTF-8 reachability gate: Python files may
not contain Unicode Private Use characters, and an unreachable corrupted style
prompt fallback was deleted. The old `describe_error` helper was removed after
all callers crossed the typed failure boundary. The focused gates for this
architecture are `test_failure_boundary.py`, `test_workflow_coordination.py`,
`test_source_encoding.py`, and the lifespan test in `test_app.py`; they augment,
not replace, the API, task/supervisor, structured-artifact, workflow, current
project snapshot, and 13K/20K/30K complete-flow acceptance suites.
