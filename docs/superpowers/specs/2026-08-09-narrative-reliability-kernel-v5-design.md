# Narrative Reliability Kernel V5

## Change contract

- Requested outcome: complete P0-P6 as one reversible implementation so the current production planning failure and structurally similar future provider, parser, capacity, recovery, checkpoint, and cross-genre failures recover automatically instead of merely stopping safely.
- Original MUST requirements: use mature or scientifically justified techniques instead of accumulating regexes and branches; support third-party OpenAI-compatible, Gemini-backed, and Claude-backed routes by observed capability rather than brand; automatically manage structured-output mode, context, output headroom, retry, split, and fallback; preserve story logic and prose quality across genres; locate configured credentials again when an initial path lookup is wrong; use bounded real-provider acceptance only after offline gates; never rewrite an existing formal manuscript; do not commit or push Git.
- Scope classification: `open_world`.
- Operational definition: the original production-shaped payloads and unseen structurally different valid variants normalize to one typed authority contract, recover the smallest failing unit, retain accepted work across interruption, and cross the next authoritative boundary without fixture-, provider-, label-, or error-string-specific branches.
- Forbidden narrowing: no run-ID, project-name, provider-brand, endpoint-string, table-label, event-count, exact wording, or one-fixture branch; fail-closed containment is not recovery; a new abstraction that leaves the legacy implementations authoritative is incomplete.
- Authorization: L3 implementation, additive/idempotent schema migration, necessary maintained development dependencies, bounded real-provider calls after offline verification, and restart only when no run is queued, running, or cancelling. Formal manuscripts, Git commit/push, secret disclosure, and active-run termination are outside authorization.
- Current evidence: production run `4e79a0f402ad49a486a0122dafe24bc4` returned a valid Markdown field table that the legacy line-label parser rejected; a later representation repair revealed 29 event-body ownership gaps and the flat issue-set comparator rejected that stage progress. Earlier run `93075987b1374e53bb13d13ecb53bc68` lost an unnumbered continuation at an event projection boundary. Current code still contains parallel `_short_plan_*` parsers, a flat `RecoveryCandidate.issue_keys` comparator, and only generated/validated checkpoint states.
- Allowed changes: provider routing and probing, capacity observation, generated-artifact parsing, typed planning IR, validation issues, recovery policies, workflow node states, additive SQLite schema, run diagnostics, UI/API diagnostics, tests, documentation, and time-bounded legacy delegation/deletion.
- Protected unchanged behavior: StoryState remains the only story-fact authority; confirmed outline, causal chain, execution manifest, accepted candidates, formal manuscripts, project files, runtime story Skills, credentials, model bindings, and historical runs remain preserved; only Runtime may promote formal work; unaffected prose remains byte-identical.
- Authority impact: current candidates, protected best candidates, derived planning/receipt artifacts, provider capability observations, workflow checkpoints, incident records, and UI diagnostics change. Formal manuscripts are read-only. StoryState schema changes, if any, are additive and idempotent.
- Selected mature patterns: markdown-it-py token/AST parsing with table support; Pydantic typed intermediate representations and JSON Schema 2020-12 contracts; explicit staged validation DAG; Saga-style bounded compensation to the protected best candidate; idempotent hash-bound SQLite node envelopes; route-fingerprint capability negotiation; deterministic parameterized, metamorphic, property-based, and state-machine tests.
- Rejected alternatives: regex or alias accumulation, provider-specific primary branches, unbounded retries, whole-plan rewrites for local faults, disabling semantic gates, mechanical truncation, a second StoryState, direct formal writes, and an all-at-once Temporal/LangGraph migration.
- Rollback: immutable source outputs and formal files, versioned additive readers, project-scoped V5 feature switch during dual-read, old workflow entry point as a tested fallback until equivalence proof, and rejection of stale/conflicting V5 checkpoints. Legacy parser authority is deleted only after the dual-read gate passes.
- Convergence budget: inventory every `_short_plan_*` parser and call site; make the planning compiler the single field/ownership boundary; retain at most thin compatibility delegates during dual-read; remove the delegates and duplicate authoritative parsing after equivalence, production recovery, and downstream continuation pass.
- Focused tests: production table fields, existing Markdown variants, Planning IR/source spans, stage-reveal candidate comparison, event ownership, checkpoint transitions, route capability invalidation, and capacity splitting.
- Related tests: planning adaptation/workflow, execution manifest, StoryState, provider probe/registry, production incidents, drafting, split/merge, polish, targeted/manual revision, final review, API/UI diagnostics, and migrations.
- Full suite: `.venv/Scripts/python.exe -X utf8 -m pytest -q` before any live acceptance or restart.
- Model-output coverage: at least six valid realizations across table, heading-owned, inline-label, list/card, JSON/schema, and tool-call topologies; two unseen wrapper/container arrangements; malformed/ambiguous and duplicate/reordered ownership cases; output truncation and disconnected transport. Stable oracles are ordered event ownership, source and authority hashes, entry/exit state, exact evidence, no duplicate ownership, monotonic stage progress, unchanged-scope hashes, quality floors, and next-boundary continuation.
- Unknown-variant behavior: normalize an unambiguous invariant-complete artifact locally; request only the canonical immutable receipt when machine control is unknown; never guess between multiple candidates; preserve the best complete artifact on exhaustion.
- Resolution status before implementation: `unresolved`.
- Why previous tests missed production: parser and ownership tests exercised sibling helpers independently, did not include field-as-table topology at the top-level local gate, compared raw issue sets rather than validation-stage progress, and stopped before the production artifact crossed causal-chain and drafting boundaries.
- Unresolved user decisions: none.

## Validation closure

Every generated mutation follows `transport -> syntax -> ownership -> local semantics -> adjacent handoff -> whole-story integrity -> quality -> atomic promotion`. A repaired earlier stage may reveal later-stage issues without being blamed for introducing them, but it never becomes downstream authority until the complete closure passes.

## P0-P6 rollout

- P0 freezes the task baseline, records both production incidents, captures the failing field-table regression, inventories competing boundaries, and records this contract.
- P1 completes route-fingerprint capability observations, typed endpoint diagnostics, automatic structured-output negotiation, adaptive headroom, semantic splitting, and provider-safe retry/fallback.
- P2 makes one AST-based artifact/compiler framework and typed Planning IR authoritative, including Markdown tables, headings, inline fields, lists, JSON/schema, tools, source spans, Unicode label normalization, and ambiguity safety.
- P3 replaces flat issue comparison with staged issue graphs, explicit event realization ownership, unit/stage recovery budgets, smallest-unit patches, complete-unit rebuild, and best-candidate compensation.
- P4 persists versioned validation-stage checkpoints, deterministic invalidation/resume, core cross-genre invariants, additive genre packs, and whole-story/quality closure.
- P5 runs time-bounded dual-read equivalence, delegates then removes duplicate legacy parser authority, simplifies the provider UI to read-only automatic diagnostics, and completes incident-memory projection across later stages.
- P6 runs focused, related, production-shaped, metamorphic/stateful, and full-suite verification; then performs bounded real-provider acceptance, checks active runs, restarts only when safe, and proves continuation through causal chain, manifest, drafting, merge, polish, review, and formal-promotion candidate boundaries without rewriting an existing formal manuscript.

## Implementation closure — 2026-08-09

- Resolution status: `systemically_resolved`. The legacy line-oriented planning parser is no longer an independent authority; generated planning artifacts cross one typed compiler/IR boundary, and recovery progresses through explicit validation stages with smallest-complete-unit compensation.
- Offline evidence: the complete suite finished with `1713 passed, 1 skipped`; the final launcher/provider/checkpoint/compiler/recovery acceptance cluster finished with `56 passed`. Python byte-compilation and `git diff --check` also passed.
- Production-shaped evidence: the recorded field-table incident is normalized, only the affected event segment is repaired, unaffected segments remain byte-identical, and the recovered plan continues through causal-chain construction. Duplicate, reordered, ambiguous, unknown-control, alternate Markdown, structured JSON, tool-argument, Unicode, metamorphic, and property-generated variants are covered.
- Real-provider evidence: after the offline gates, four bounded third-party routes were probed through the actual Windows credential context. The current planning route connected as `plain_text` with tool calling available; the GPT and Claude routes connected with `strict_tool`; the Gemini route connected as `plain_text` without tool calling. These observed route-local capabilities were cached with a seven-day TTL. No secret value, header, or generated prose was persisted by the acceptance probe.
- Runtime evidence: the formal database contained no queued, running, or cancelling run before startup. The current source then started on port `8765`; `/api/health` returned the expected service and data/runtime fingerprints, all seven configured providers reported credentials visible in the real process, and the read-only capability diagnostics were available through `/api/providers`.
- Protection evidence: no existing formal manuscript or project narrative file was rewritten, no active task was interrupted, and no Git commit or push was performed.
- Review note: the strict change gate reported no blocker and one procedural L3 split-review warning because P0-P6 necessarily changes more than two authority-critical modules. No multi-agent review was authorized, so the required single-agent clean-room review was performed from the original requirement, task baseline, complete diff/stat, production fixtures, forward-risk report, and test/live evidence. The warning remains recorded rather than being bypassed.
- Remaining external risk: a third-party platform can still rate-limit, time out, change a compatibility endpoint, or become unavailable. Route fingerprints, TTL expiry, typed diagnostics, bounded retry/fallback, semantic splitting, best-candidate preservation, and resumable checkpoints contain those failures; they cannot make an external platform permanently available.

## Terminal-boundary production closure — 2026-08-11

The controlled production run exposed two later defects after the original V5
closure. First, local event repairs were compared against the earliest defect in
the whole plan, so a syntax defect in an unchanged terminal segment suppressed
valid ownership progress in earlier changed segments. Candidate comparison now
receives an immutable changed-segment scope and source event ownership; defects
outside that scope remain latent while any new local, adjacent, or whole-plan
defect inside the mutation scope still blocks promotion.

Second, the V1 segment schema represented every exit as a non-empty successor
handoff. A final segment with complete ordered event realizations and a formally
confirmed ending therefore could never satisfy the same shape. The compiler now
has a versioned discriminated exit topology: intermediate segments use
`AdjacentHandoffIR`, while exactly the last segment uses `TerminalClosureIR`
bound to the formal ending hash, exact terminal event ownership, terminal event
evidence hash, and explicitly retained open-obligation IDs. This is a topology
rule for one, two, or N segments, not a genre, project, provider, or fixed-index
exception. Legacy display Markdown receives the exact formal terminal evidence
only as a deterministic compatibility projection; missing intermediate
handoffs, missing ending authority, incorrect terminal ownership, multiple
terminal exits, and ambiguous migration remain closed.

Runtime-owned field envelopes are extracted atomically before any Markdown
heading scan. Their bodies may contain arbitrary headings and multiline ending
evidence without becoming segment boundaries; the compiler independently checks
role, token, and SHA-256 before the value becomes authority. Events-only repair
continues to own only the event body, and packet merge reattaches the immutable
parent boundary after leaf merge rather than accepting a child-authored exit.

Regression evidence includes 1/2/5/N exit topologies, intermediate and terminal
misuse, exact final-event ownership, retained open obligations, CRLF/LF owned
heading bodies, the real events-only terminal response shape, mixed-stage
six-segment monotonic promotion with unchanged latent defects, causal-chain
continuation, and the complete workflow/full-repository suites. Rollback remains
the prior complete plan and its hash-bound recovery state; no formal manuscript,
StoryState, credential, provider binding, or Git history is changed by this
migration.
