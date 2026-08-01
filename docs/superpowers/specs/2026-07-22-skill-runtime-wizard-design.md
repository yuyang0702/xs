# Skill-driven Story Wizard and Runtime

## Goal

Reproduce the useful behavior of the installed Story Skills inside the local novel console: collect requirements interactively, let a bounded agent follow Skill instructions, manage the canonical Story Skills project layout, and run deterministic Story CLI maintenance. The runtime must remain project-scoped and must not expose arbitrary Codex, shell, filesystem, browser, or MCP access to external models.

## User Experience

Creating a project starts a resumable wizard instead of immediately creating a minimal project. The wizard discovers applicable initialization Skills, groups their questions into steps, saves every answer, and lets each answer be marked `locked`, `suggestible`, or `generated`.

The standard steps are work positioning, story core, characters, worldbuilding, plot structure, narrative rules, and dynamic Skill questions. After those steps, a planning model performs one gap analysis and asks only material follow-up questions. A final review page shows the complete story brief, locks, model-generated suggestions, enabled Skills, and files that will be created. Formal project creation starts only after confirmation.

Closing the browser does not lose a draft. A wizard can be resumed, discarded, or duplicated as a reusable template.

## Dynamic Skill Forms

The runtime accepts an optional machine-readable form definition from a Skill. When none exists, the planning model converts the Skill's requirements into a validated form schema. Generated schemas are stored outside the Skill at:

```text
data/skill-forms/<skill-name>/<content-hash>.json
```

The schema describes sections, fields, types, validation, conditional visibility, lockability, and the answer keys supplied to the Skill runtime. It cannot contain executable code. A built-in core schema guarantees that project creation remains available when schema generation fails.

A Skill content-hash change selects a new cache entry. The console shows generated schemas for review and permits local corrections without modifying the original `SKILL.md`.

## Controlled Skill Runtime

Each Skill execution is a persisted state machine with these states:

```text
pending -> gathering_input -> ready -> running -> awaiting_user -> validating -> completed
                                                        |             |
                                                        +-> failed <--+
```

The model receives the complete Skill instructions, the current story context, relevant answers, locks, and a small tool catalog. It may request one of these operations:

- `read_story_file(relative_path)`
- `list_story_entities(entity_type)`
- `request_user_input(question_schema)`
- `create_file_proposal(relative_path, content)`
- `update_file_proposal(relative_path, patch)`
- `update_registry_proposal(registry, entry)`
- `check_story_links()`
- `run_story_command(command)`
- `complete_skill(summary)`

Every argument is schema-validated. Paths must be relative, resolve inside the selected project, and match the Skill's write allowlist. The model prompt names those project-root-relative patterns and forbids adding a project title or slug prefix. Models only create proposals; the runtime applies validated proposals atomically. The tool loop is bounded by step count, elapsed time, token budget, and output size. A write-capable Skill that returns plain text before creating a proposal is prompted to continue in the same bounded tool session, and `complete_skill` is rejected until at least one proposal exists; an empty result cannot become a successful initialization.

`run_story_command` is not a shell. It only accepts the Story CLI commands `init`, `reindex`, `links`, `validate`, `wordcount`, and other explicitly registered read/maintenance subcommands with fixed argument shapes. Existing executable Skill approval and content-hash checks remain in force.

## Skill Contracts

Runtime metadata is optional and can be supplied by a sidecar manifest. It describes:

- applicable project modes and workflow phases;
- input schema location;
- readable and writable story path patterns;
- allowed Story CLI commands;
- prerequisite and follow-up Skills;
- completion artifacts and validation rules.

For legacy Skills without metadata, the program applies conservative defaults inferred from known Story Skills. Unknown Skills begin in prompt-only mode until the generated contract is reviewed and approved. The program never infers permission to run arbitrary scripts or write arbitrary files.

## Canonical Story Layout

Confirmed projects use the Story Skills schema-v2 layout:

```text
story.md
characters/_index.md
worldbuilding/_index.md
worldbuilding/locations/
worldbuilding/systems/
worldbuilding/factions/
worldbuilding/artifacts/
plot/_index.md
plot/arcs/
plot/timeline.md
continuity/state.md
continuity/questions/_index.md
continuity/promises/_index.md
continuity/locks.json
scenes/_index.md
glossary/_index.md
chapters/_index.md
```

`story-init` creates the structure and story bible. `character-management`, `worldbuilding`, and `plot-structure` then run separately, each with its own inputs, proposals, receipts, and validation. Registry and backlink maintenance is deterministic. The existing chapter flywheel reads this layout through repository methods rather than maintaining a second authoritative copy.

All project creation paths converge on this sequence after a user confirms the formal outline. The runtime passes that outline to every initialization Skill and validates stage outcomes rather than trusting a historical completed receipt. Explicit outline characters, populated registries, relationships, arcs, and timeline are deterministic completion requirements. Premise wording may be faithfully rewritten, and supporting locations, characters, and concrete details may be added when they do not contradict confirmed facts; literal name equality is not a requirement for creative additions. The `story-init` contract enumerates canonical root-relative files instead of accepting wildcard wrapper directories. Generation APIs independently enforce formal-outline and initialization readiness.

Formal outlines also contain stable `EV-xxxxxxxx` event IDs. Run-scoped planning covers every ID in outline order and records an outline anchor plus entry/exit handoff. Adjacent short-story segments may share an ID when one formal event needs several bounded writing windows, but an earlier ID cannot reappear after the plan advances. Draft and revision artifacts retain those assignments, so `planning.md` refines the formal outline into bounded work without becoming a competing source of truth. Long-form expansion is stored in `memory/book-plan.md` and remains subordinate to `plot/outline.md`.

When initialization starts, the server freezes the current active prose-baseline and creative-blueprint versions into the tracked run. It filters that snapshot by project mode, genre, POV, declared applicability, and the current Skill: character rules go to character preparation, setting methods go to worldbuilding, and structural methods go to plot preparation. The compact context excludes evidence offsets and model receipts. A completed Skill is still skipped, so only unfinished stages use the snapshot. Learning context is advisory and cannot rewrite the confirmed outline, locks, confirmed facts, POV, or identities; bootstrap proposals for `plot/outline.md` are rejected.

Before any initialization Skill writes, the server creates a versioned `memory/outline-manifest.json` bound to the confirmed outline hash. Explicit Markdown structure is authoritative for clearly named roles and chapters, local NLP contributes candidates without authority, and the planning role performs at most one evidence-backed review for that outline version. Model entries without an exact outline quote are discarded; character and location names must occur in their own quote. A missing planning binding or transient provider failure falls back to strict local findings and is recorded as a degraded review rather than changing the project contract.

All initialization Skills consume the same manifest. Completion checks require exact primary-name coverage for the confirmed cast, unique named entity files, complete registries, real arc files, a populated timeline, and manifest-backed promise, question, and constraint coverage. Aliases do not resolve an unconfirmed primary-name conflict. The console presents these checks as seven understandable material sections and excludes empty scaffolds from counts.

## Locking and Change Requests

Locks are stored in SQLite and `continuity/locks.json`. Each lock records a stable key, value, source answer, scope, creation time, and revision. Locks are included in every relevant model stage.

Before applying a proposal or accepting maintenance output, the runtime compares affected structured facts against locks. A conflict creates a change request containing the proposed value, reason, source stage, and affected artifacts. The conflicting change is not written. Only the user can approve a change request; approval revises the lock and triggers revalidation of dependent material.

## File Proposals and Validation

Models return structured proposals rather than arbitrary paths or direct writes. The runtime validates:

- the path against project containment and the Skill allowlist;
- UTF-8 text and size limits;
- required YAML frontmatter and schema version;
- entity identifiers and filename conventions;
- registry and backlink consistency;
- conflicts with locks and confirmed canon.

All proposals for one Skill execution are applied as one snapshot-protected transaction. Story CLI `reindex`, `links`, and `validate` run after application, except that bootstrap character proposals defer `links` until worldbuilding has created their forward-referenced locations. Character preflight first enforces one structured relationship per target and exact inverse types; worldbuilding treats character `locations` as a required file-and-backlink checklist. A validation failure restores the snapshot and preserves the proposals and error report for retry. The enclosing initialization run also owns a batch snapshot: if any later Skill fails, all earlier initialization writes from that run are restored and newly created managed Markdown files are removed.

If a model route stops after producing a locally complete proposal set but before calling `complete_skill`, Runtime accepts the proposal set for normal local validation instead of discarding it or calling a fallback model. If the set is incomplete, its pending proposals become `retained` before the configured fallback starts. The fallback receives only the retained path list and current deterministic gaps, and its new proposals remain a separate pending repair layer. Exact entity identity is the pair of the contract-owned entity type and normalized `name` or `title`; a repair that uses another path for the same identity reuses the first canonical path. Runtime never performs fuzzy identity matching.

An apply or route failure leaves proposal rows intact. Active fallback proposals become `failed`, retained primary proposals stay retained until validation selects or supersedes them, and the Skill execution becomes `recoverable` whenever any retained or failed proposal exists. Formal project files remain snapshot-protected. The existing execution and proposal tables expose this recovery state; no second candidate store is created.

## Existing Project Migration

Migration creates a full snapshot and a dry-run report before changing files. It maps current metadata and `outline.md` into `story.md` and `plot/`, converts `memory/canon.json` into proposed story entities and continuity records, keeps chapter files, builds registries, and reindexes search data.

Ambiguous canon remains in a migration review queue. Nothing is silently discarded. The original files are retained under a migration backup until the new project passes Story CLI validation. Failure restores the snapshot.

## Data and API

SQLite stores wizard sessions, answers, Skill form caches, Skill executions, tool events, file proposals, locks, change requests, and migration reports. Large proposal content is stored in the project run directory with hashes in SQLite.

The API supports creating/resuming a wizard, submitting a step, running gap analysis, answering follow-ups, confirming creation, monitoring each Skill execution, reviewing proposals, resolving lock conflicts, and migrating existing projects. All long operations use the existing run history and are designed for later background execution without changing their contracts.

## Console

The project page becomes a stepper with autosave and a persistent summary rail. Fields use appropriate native controls and show a three-state lock control. Dynamic Skill sections identify their source Skill and content hash. The final confirmation page shows unresolved required fields, locks, enabled Skills, generated suggestions, and planned files.

Project maintenance adds views for Skill executions, file proposals, locks, change requests, validation reports, and migration. Desktop and mobile layouts must avoid horizontal page overflow and preserve readable field labels and values.

## Failure Handling

- Schema generation failure falls back to the core form and records the failure.
- Invalid model JSON is repaired once, then the step fails visibly.
- Runtime step or budget limits stop the Skill without applying pending proposals.
- A premature text-only response is retried inside the existing bounded tool loop; if no accepted proposal is produced, the configured planning fallback may run and the stage fails without changing formal files.
- Unauthorized paths, commands, or tool names fail immediately and are recorded.
- Browser closure does not stop or lose persisted wizard state.
- Story CLI validation failure restores the project snapshot.
- Missing executable Skill approval blocks execution before any project write.
- Lock conflicts create reviewable change requests instead of partial writes.

## Testing and Acceptance

Automated tests must cover:

- form discovery, generation, validation, caching, and hash invalidation;
- wizard autosave, resume, conditional fields, follow-ups, and final confirmation;
- all three answer policies and strict lock enforcement;
- bounded runtime tool calls and rejection of unknown tools, paths, and commands;
- proposal validation, transactional application, rollback, and receipts;
- standard project initialization and each core Story Skill workflow;
- registry, backlink, timeline, promise, and question maintenance;
- Story CLI invocation through the whitelist only;
- existing-project migration, ambiguity review, and rollback;
- compatibility with short and long writing workflows;
- desktop and mobile wizard layout and accessibility basics.

## Explicit Boundaries

This runtime targets story creation and maintenance. It does not clone the complete Codex runtime and does not expose arbitrary terminal commands, arbitrary filesystem access, MCP servers, browser control, or program self-modification to external models. A future Skill that requires such a capability remains unavailable until a narrow, reviewed adapter is added.
