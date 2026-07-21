# Read-only Agent Tools for the Novel Flywheel

## Goal

Allow each external writing, review, polishing, and maintenance model to query local story knowledge while it works. Keep formal project writes under the deterministic flywheel so snapshots, validation, and rollback remain authoritative.

The implementation must support official provider APIs and third-party relays. A provider without tool-calling support must continue through an explicit prompt-mode fallback rather than stopping the workflow.

## Scope

This change adds:

- a provider-neutral model tool-call protocol;
- a bounded local agent loop;
- read-only story tools;
- relevant chapter prose retrieval;
- project-local Skill discovery;
- volume-boundary detection and volume audits;
- persisted tool-call and fallback receipts;
- focused console status for native and degraded execution.

It does not allow models to write files, execute arbitrary commands, access paths outside the selected project, or bypass the existing review and atomic-write stages.

## Architecture

### Model gateway

The workflow calls one provider-neutral gateway method with messages and tool definitions. Provider adapters translate that request into their native representation and normalize responses into either a final text result or one or more tool calls.

OpenAI-compatible relays use the OpenAI tool schema when they accept it. Anthropic adapters use Anthropic tool blocks. Provider capability is configured or learned from a rejected tool request. A capability rejection causes one retry in prompt fallback mode; authentication, quota, and ordinary model errors do not silently degrade.

### Agent loop

The gateway owns a bounded loop:

1. Send the stage instructions, current task, and available tool definitions.
2. Validate every requested tool name and argument.
3. Execute the read-only tool against the current project.
4. Append the bounded result to the conversation.
5. Repeat until the model returns final text or the call limit is reached.

The default limit is eight tool-call rounds per stage. Exceeding it fails the stage with a clear error. Every call records the model, stage, tool, sanitized arguments, result size, duration, and status. Full secrets are never written to receipts.

### Read-only tool boundary

The initial tool set is:

- `search_chapters(query, limit)`: returns ranked chapter identifiers, summaries, and bounded matching prose snippets.
- `read_chapter(chapter_number, start, length)`: returns a bounded section of one chapter.
- `get_canon(query)`: returns confirmed canon facts.
- `get_character_state(character)`: returns current and relevant historical character state.
- `get_foreshadowing(status, query)`: returns tracked setup and payoff information.
- `get_timeline(query)`: returns matching timeline entries.
- `get_volume_plan(volume_number)`: returns volume boundaries, goals, hooks, and completion conditions.
- `get_drift_findings()`: returns unresolved continuity findings.

All paths are derived from the selected `Project`; callers cannot provide filesystem paths. Results have item and character limits to control context size and cost.

## Prompt Fallback

When a provider does not support tool calling, the program builds a stage-specific evidence package before the model call. The package contains confirmed canon, recent state, unresolved drift, relevant summaries, and bounded prose snippets. Review and maintenance receive broader evidence than polishing; polishing receives the current manuscript plus only relevant voice and continuity evidence.

The stage receipt records `execution_mode: degraded_prompt_mode` and the reason. Native tool execution records `execution_mode: native_tools`. The final textual output follows the same validation path in both modes.

## Skill Discovery and Execution

Skill scanning combines global roots with `<project>/.agents/skills` at stage execution time. A newly added project Skill is visible on the next run without restarting the server. Name collisions resolve in this order: project-local, configured application roots, global roots.

Prompt Skills remain mandatory stage instructions. Executable Skills retain hash approval and subprocess gates. Model tools do not expose Skill scripts and cannot turn a prompt Skill into executable code.

## Long-form Memory

FTS retrieval returns a short matching excerpt in addition to chapter identifier and summary. The excerpt is selected around the strongest match and bounded before entering model context. Direct chapter reads are also bounded and available only through the native agent loop.

Structured maintenance output continues to update canon and chapter state. Foreshadowing, timeline, character history, and volume plans are exposed through a repository layer that can initially read existing project JSON and Markdown; missing optional data returns an empty result rather than inventing facts.

## Volume Audits

Long setup must persist machine-readable volume boundaries alongside the human-readable outline. A chapter run checks the completed chapter number against those boundaries after normal maintenance.

At a volume boundary, the workflow runs an audit before allowing the next volume to begin:

1. Build bounded summaries for the volume in chapter batches.
2. Review character arcs, chronology, canon, knowledge boundaries, unresolved setups, pacing, and promised volume outcomes.
3. Persist the audit report and drift findings.
4. Mark the volume passed or blocked.

A hard failure or score below 80 blocks the next chapter. The completed chapter remains committed because the audit evaluates the finished volume; the user can revise or explicitly resolve findings before continuing.

## Failure Handling

- Unknown tools, invalid arguments, path attempts, and oversized reads fail the current stage.
- A tool capability rejection retries once in fallback mode.
- A tool execution failure is recorded and fails the stage; it is not presented to the model as fabricated evidence.
- Formal writes keep the existing snapshot and atomic-write behavior.
- Volume audit failure blocks future progress without rolling back already accepted chapters.

## Console

Run details show the execution mode, tool-call count, fallback reason, and volume audit status. Provider configuration exposes tool support as `auto`, `enabled`, or `disabled`; `auto` is the default for relays.

No general-purpose file browser, command console, or writable model tool is added.

## Tests and Acceptance

Automated tests must demonstrate:

- provider-native tool calls normalize into the common protocol;
- unsupported providers retry once using prompt fallback;
- non-capability API errors do not degrade silently;
- invalid tools and arguments are rejected;
- model tools cannot read outside the selected project;
- tool rounds and result sizes are bounded;
- FTS context contains a relevant prose snippet, not the whole book;
- project-local Skills appear without restarting and override global Skills;
- a configured volume boundary triggers exactly one audit;
- a failed audit blocks the next volume;
- receipts distinguish native tools from fallback mode;
- existing short and long workflows continue to pass.

## Implementation Constraints

Reuse the current provider adapters, `ModelGateway`, `StoryMemory`, `SkillGate`, SQLite database, snapshots, and workflow stages. Do not add a second agent framework or a new vector database. CrewAI remains the outer flow wrapper; tool orchestration belongs to the local gateway so provider behavior stays testable and deterministic.
