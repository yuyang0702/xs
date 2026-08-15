# PA-STRICT-TOOL-OBS-1 Final Canary Materialization

## Change Contract

- Scope classification: `closed_world`.
- Current state: R1-PA1 instrumentation is present and the draft Canary A is
  non-executable. No exact real-provider Whole fallback shape has been captured.
- Allowed changes: Canary control-plane contracts, offline materializer,
  validate-only logic, tests, generated approval artifacts, and the final report.
- Protected surfaces: `src/novel_flywheel`, Prompt, model request, output budget,
  Contract Runtime, parser/adapter/validator behavior, route/provider/model,
  retry/fallback, Whole fallback, Phase 1B, checkpoints, formal artifacts, and
  incident classification.
- Authority impact: no business authority is read for mutation and no business
  authority is written. Live database and project trees are hash-compared before
  and after materialization.
- External-effect policy: credential lookup, provider-client creation, network,
  model calls, and paid calls are forbidden and must remain zero.
- Outcome: create one inert, single-use, hash-bound approval package whose only
  future observation goal is `TARGET_STRICT_TOOL_SHAPE_OBSERVED`.
- Rollback: revert the Canary-control commits. No production data rollback is
  required because materialization is offline and read-only.
- Resolution status: `case_fixed` for approval-materialization only. The
  underlying planning-adaptation failure remains unresolved.

## Exact target

The target is the equality tuple:

`review / planning_adaptation_whole_receipt / planning_adaptation_whole@1 /
review / configured_fallback / strict-tool`.

Prompt text is not a selector. Non-target strict-tool boundaries may only
increment `excluded_not_target`; they may not persist full tool shape.

## Evidence and privacy contract

The request declaration, provider raw snapshot, adapter-normalized projection,
and Gateway uniqueness decision must share `shape_correlation_sha256`.
Missing or partial provider snapshots remain unknown and cannot be interpreted
as zero tool calls. Evidence is hash/shape/count-only: prompts, prose, raw tool
arguments, unknown tool names, full responses, credentials, headers, full
provider request IDs, absolute paths, project/entity names are forbidden.

## Dual outcome and stop contract

Observation success and workflow outcome are independent. Exact target capture
sets `observation_goal_outcome=TARGET_STRICT_TOOL_SHAPE_OBSERVED` even if the
workflow later terminates. The future launcher must stop after exact target
capture, the first workflow terminal, identity/config/source/route/privacy or
isolation mismatch, target observation unavailability, budget exhaustion,
controlled provider outcome, or approval expiry. If the target is not reached,
the only outcome is `TARGET_NOT_REACHED`; no automatic second run is allowed.

## Materialization versus execution

This change implements materialization and offline validation only. The Approval
Candidate keeps every external authorization and `execution_authorized` false.
The patch is explicitly a template, not an authorization. The command preview
binds a future `PAStrictToolObs1SignedApprovalV1` placeholder and remains
`do_not_execute=true`. No Signed Approval is created in this phase.

## Budget candidate

- maximum runs: 1
- expected model calls: 11
- maximum total model calls: 24
- maximum input tokens: 500,000
- maximum output tokens: 500,000
- maximum output tokens per call: 32,000
- maximum USD cost: 10.00
- maximum CNY cost: 25.00
- maximum elapsed: 7,200 seconds

These are approval ceilings only and do not change Runtime retry count or output
budget behavior. `NOVEL_STRICT_TOOL_SHAPE_TRACE_V1=true`,
`NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1=false`, and Phase 1B remains false.

