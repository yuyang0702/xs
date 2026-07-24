# Novel Flywheel Console

Local multi-model writing workflow for short stories and long serial novels.

## Start

Run `start-novel-console.cmd`, then open `http://127.0.0.1:8765`.

## Model tools

Each model mapping has a Tool Calling mode:

- `auto`: try native tool calling and fall back to an injected evidence package only when the provider explicitly rejects tools.
- `enabled`: require native tool calling and fail the stage if the provider rejects it.
- `disabled`: always use the injected evidence package.

Models can only use these project-scoped read tools:

- search prior chapters;
- read a bounded part of a numbered chapter;
- query canon and current character state;
- query foreshadowing, timeline, volume plans, and unresolved drift.

Models cannot pass file paths, write project files, or run commands. Each stage allows at most eight tool rounds. The deterministic flywheel remains the only writer of formal files and retains snapshots and rollback.

## Skills

Skills are scanned again for every stage. Global Skills are loaded from the configured roots, and project-specific Skills can be added under:

```text
<project>/.agents/skills/<skill-name>/SKILL.md
```

A project Skill with the same name overrides the global version on the next run; no server restart is required. Executable Skills still require approval for their current content hash.

## StoryState and safe revision

Each novel has an independent versioned StoryState. Models read the same authoritative facts and submit candidate output; only Runtime can promote a candidate to the formal manuscript. Cancelled runs, failed quality checks, invalid polish output, and stale tasks cannot overwrite the last committed manuscript.

Short-story polish uses bounded segments with adjacent boundaries, a compact story map, character state, locked facts, and stage-specific Skills. Claude primary polish starts with an 8,192 output limit because the configured relay repeatedly exhausted smaller limits before returning visible prose. Other polish routes retain dynamic limits, so ordinary segments do not inherit Claude's cost profile. Final structured review also uses 8,192 to avoid truncated JSON.

Operational details, log meanings, recovery behavior, and documentation requirements are in [`docs/maintenance.md`](docs/maintenance.md).

## Long novels

Long setup may produce `memory/volumes.json` with machine-readable boundaries. When a generated chapter reaches `end_chapter`, the flywheel runs a volume audit and writes `memory/audits/volume-NN.json`.

A failed audit keeps the completed volume-ending chapter but blocks entry into the next volume. Resolve the audit findings and mark the audit passed before continuing.

Relevant chapter retrieval uses SQLite FTS and returns bounded matching prose excerpts rather than loading the whole novel into model context.

## Skill-driven project wizard

New projects use a resumable wizard. The wizard combines a stable core form with questions from `story-init`, `character-management`, `worldbuilding`, `plot-structure`, and compatible project-form sidecars under `forms/project.json`.

Unknown initialization Skills receive a validated generated form cached by Skill content hash under `data/skill-forms`. Updating a Skill selects a new cache entry automatically. Every answer is stored as one of:

- `locked`: program-enforced and included in every later model stage;
- `suggestible`: models may recommend changes;
- `generated`: the planning model may supply the value.

Before confirmation, **检查关键缺口** adds required follow-ups for missing endings, character arcs, world rules, and long-form main arcs. Confirmation creates the Story Skills schema-v2 project layout and saves locks in SQLite and `continuity/locks.json`.

## Controlled Skill Runtime

After project creation, the console runs the selected initialization Skills through a controlled runtime. External models may read story files, list entities, request missing input, and submit file or registry proposals. They cannot write directly.

Each Skill has a path allowlist. Proposed Markdown requires YAML frontmatter, locked facts are checked before acceptance, and conflicts create change requests. Accepted proposals are applied as one snapshot-protected transaction followed by Story CLI `reindex`, `links`, and `validate`.

The runtime exposes no general shell, arbitrary path, browser, MCP, or Codex tool access. Write-capable Skill execution requires native Tool Calling; prompt fallback is rejected rather than treated as successful execution.

## Existing project migration

The workbench can preview and run migration for an older project. Migration preserves legacy files, maps the old outline and canon into the canonical structure, sends ambiguous facts to `migration-report.json`, rebuilds registries, and restores the snapshot if Story CLI validation fails.
