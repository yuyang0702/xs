# Adaptive Polish Segmentation Design

## Goal

Reduce Claude relay failures caused by oversized polish requests without lowering output capacity or weakening story context. Keep polish `max_tokens` fixed at 8,192.

## Constraints

- Preserve the existing StoryState, role bindings, configured Claude fallback, Skills, validation, checkpoints, and history.
- Do not silently route polish to the Draft role or another model when both configured Claude routes fail.
- Do not mechanically rewrite prose locally.
- Preserve locked facts, chronology, character state, required ending, and segment order.
- Existing completed artifacts remain immutable. The behavior applies to new polish passes.

## Request Construction

Runtime continues to split at scene, paragraph, and sentence boundaries. The initial prose target is 1,200-1,800 Chinese characters, but it is not a fixed contract. Before each call, Runtime estimates the complete input containing:

- system and compact Skill prompts;
- style profile and relevant character fingerprints;
- authoritative facts and compact story map;
- current findings and edit permission;
- previous polished tail and next original head;
- the manuscript segment.

If the estimated input is too large, Runtime reduces only optional context first: adjacent windows, nonessential story-map detail, and findings unrelated to the current segment. It never removes the current manuscript segment, locked facts, directly relevant character state, or the current edit task. If required context is still too large, Runtime splits the manuscript segment again at the nearest paragraph boundary.

The budget is adaptive rather than a user-visible fixed token number. It should keep ordinary relay requests comfortably below the sizes that have produced repeated five-minute failures while retaining enough context for coherent prose.

## Context Continuity

Each request identifies the segment's global position and scene role. The previous polished tail and next original head are reference-only and must not appear in model output. The compact full-story map preserves global causality; authoritative state preserves facts and chronology; relevant character fingerprints preserve voice.

After merging, existing deterministic checks continue to reject missing locked facts, abnormal length changes, production text, repeated blocks, and rhythm regressions. Adjacent segments are checked for duplicated boundary text.

## Failure Recovery

A successful segment is saved immediately using the existing source-hash checkpoint format.

For recoverable relay failures such as connection errors, `502`, `504`, `524`, and timeout:

1. Try the configured primary and configured Claude fallback through the existing gateway behavior.
2. If both routes fail and the current prose segment can still be split safely, divide only that segment near its midpoint at a paragraph boundary.
3. Process the two child segments with the same authoritative context and narrower adjacent windows.
4. Save each successful child immediately.
5. If the minimum safe segment size is reached or a child still exhausts both Claude routes, stop the polish pass with its checkpoints intact.

Non-recoverable authentication, configuration, validation, and policy errors are not split or retried. No Draft-role fallback is used after configured Claude exhaustion.

## Observability

Run events record estimated input size, source characters, split depth, route, and whether a segment was adaptively split. Receipts remain the authority for actual provider token usage. Logs never contain API keys, request headers, or complete prompts.

## Testing

- Polish output budget remains exactly 8,192 for the configured Claude path.
- Large contextual prompts reduce optional context before prose is split.
- Splits occur only on safe textual boundaries and preserve order.
- A recoverable failure splits and resumes only the failed segment.
- Successful children are checkpointed and reused after interruption.
- Authentication and validation failures do not trigger recursive splitting.
- Both Claude routes failing at minimum size halts without Draft fallback.
- Existing polish validation, StoryState, and workflow tests remain green.

## Non-Goals

- Streaming transport changes.
- Provider-specific tokenizer dependencies.
- Lowering `max_tokens` or optimizing API cost.
- Rewriting existing completed manuscripts automatically.
