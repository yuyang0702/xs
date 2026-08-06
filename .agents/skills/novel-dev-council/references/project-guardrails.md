# Project guardrails

Read `AGENTS.md` as the complete authority. Use this file as a routing checklist, not a replacement.

## Separate development and runtime Skills

`novel-dev-council` governs development of the console repository. It must never be injected into the application's story generation, planning, polish, review, revision, or maintenance prompts. Do not register council roles as provider/model bindings and do not use the application's CrewAI workflow to simulate this council.

## Authority impact map

For every L2 or L3 request, mark each boundary as `changed`, `read-only`, or `not involved`:

- formal manuscript;
- current candidate;
- protected best candidate;
- StoryState revision and locked facts;
- confirmed outline, causal chain, execution manifest, and narrative receipts;
- revision decisions and terminal issue ledger;
- project metadata and files;
- SQLite schema and rows;
- provider/model role bindings and fallback;
- runtime story Skills and context packets;
- run events, checkpoints, resume, and rollback;
- UI state and API contract;
- credential and private-source handling.

If a changed boundary lacks a single writer, validation rule, rollback path, and stale-state rule, the proposal is incomplete.

## Automatic L3 triggers

Promote the request to L3 when it touches any of these:

- Runtime-controlled formal writes or candidate promotion;
- StoryState, locked facts, canon, timeline, causality, promises, or ending;
- generated-output parser contracts or machine-control fields;
- split, retry, fallback, cancellation, resume, recovery, or context compaction;
- model role binding, provider protocol, output/context budget, or paid calls;
- schema, migration, project import/export, or historical compatibility;
- credentials, private references, URL retrieval, external code, or license obligations;
- deletion, overwrite, restart, termination, or another irreversible action.

## User-control matrix

- A question or diagnosis authorizes read-only inspection only.
- An evaluation authorizes a recommendation only.
- A design request may create or update design artifacts but does not authorize implementation unless clearly included.
- An implementation request authorizes scoped, reversible code and test changes required for that behavior.
- A semantic manuscript, schema, destructive, paid, external-write, restart, or active-run action still requires its own matching authority.

## Existing-project compatibility

Prefer additive, project-scoped, disabled-by-default, reversible behavior. Preserve old projects, files, routes, bindings, history, and formal outputs. Require an idempotent migration test for schema or state changes and retain the old path as a tested fallback until comparative evidence justifies removal.

## Operational safety

Before restart, inspect active runs. Do not restart while any run is `queued`, `running`, or `cancelling` without explicit authorization. Never expose secrets or raw headers in reports, fixtures, or role messages.
