# Targeted Revision and Token Control

## Problem

Truncated 4,096-token revision plans triggered an all-segment fallback. Every review issue was then applied to every segment, increasing token use and creating new story conflicts across correction rounds.

## Implementation

1. Raise revision-plan output to 8,192.
2. Give every scene a stable `scene-NN` id.
3. Require deterministic literal checks and limit targets to 40% of scenes.
4. Fail closed on invalid/truncated plans; preserve `best-candidate.md`.
5. Rewrite only targeted scenes and reuse same-pass interruption checkpoints by exact source hash.
6. Remove exact consecutive duplicate paragraph blocks locally.
7. Stop before the next request at 120,000 initial, 60,000 structural-round, or 220,000 cumulative polish input tokens.
8. Emit distinct plan-blocked, token-budget, checkpoint, and quality-halted events.
9. Compact revision-planning context and retry an invalid/truncated planning result once with the review role before failing closed.

## Verification

- Unit tests cover scene ids, plan scope/check validation, and duplicate removal.
- Workflow tests cover no-rewrite plan failure, per-round and cumulative token stops, candidate preservation, same-pass checkpoint reuse, and output budgets.
- No automated test calls a paid provider.
