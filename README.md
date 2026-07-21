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

## Long novels

Long setup may produce `memory/volumes.json` with machine-readable boundaries. When a generated chapter reaches `end_chapter`, the flywheel runs a volume audit and writes `memory/audits/volume-NN.json`.

A failed audit keeps the completed volume-ending chapter but blocks entry into the next volume. Resolve the audit findings and mark the audit passed before continuing.

Relevant chapter retrieval uses SQLite FTS and returns bounded matching prose excerpts rather than loading the whole novel into model context.
