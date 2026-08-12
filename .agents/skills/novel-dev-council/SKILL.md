---
name: novel-dev-council
description: "Use for non-trivial requirements, feature design, implementation, bug fixes, refactors, workflow changes, review or revision behavior, StoryState, model routing, provider fallback, generated-output parsing, recovery, project files, UI/API behavior, or regression-risk work in the novel-flywheel-console repository. Organize product, novel-business, technical, and test perspectives, require cross-role challenges, preserve user authorization, and enforce project-specific no-regression gates before reporting completion."
---

# Novel Development Council

Apply this Skill only to development and maintenance of `novel-flywheel-console`. Keep it separate from the application's story-writing Skills and model roles.

## Start with project scope

1. Run `scripts/check_project_scope.py` from the repository root.
2. Stop if the script does not confirm the `novel-flywheel-console` Git root and required sentinel files.
3. Read the repository `AGENTS.md` completely. Treat it as higher-priority project policy; do not duplicate or weaken its gates.
4. Record `git status --short` before making decisions. Preserve all pre-existing user changes and untracked files.
5. For an implementation task, save a task baseline outside the repository with `scripts/inspect_change_gate.py --save-baseline <temporary-json>`. Keep that path for final inspection so pre-existing dirty files cannot satisfy the new task's gates.
6. Determine whether the user requested explanation, evaluation, design, implementation, or destructive/operational action. Never broaden that authorization.

## Classify the request

- **L0 — inquiry:** Explain or inspect existing behavior. Do not create a council or modify files.
- **L1 — narrow:** Documentation, copy, styling, or a deterministic localized fix with no authority or workflow impact. Use the focused regression gate.
- **L2 — feature:** User-visible behavior, API/UI coordination, ordinary workflow changes, or multi-file implementation. Use the full regression and integration gates; use the council only when explicitly requested.
- **L3 — authority-critical:** StoryState, formal/candidate/best manuscript promotion, model routing or fallback, token budgets, generated-output parsing, review/polish/revision, split/retry/resume/recovery, schema or migration, credentials, external integrations, or irreversible action. Use explicit rollback design and the strongest regression gate; use the council only when explicitly requested.

Read `references/project-guardrails.md` for the authoritative risk and impact checklist.

## Organize the council

Team review is opt-in. Start independent read-only role agents only when the user explicitly requests **团队评审** for the current task. Never infer that authorization from task risk, a previous task, available subagents, or this Skill. When explicitly authorized:

1. Run product, novel-business, and technical analysis independently in the first wave. Give each agent the user request and raw repository evidence, not another role's conclusion or the intended solution.
2. Give the test role the three first-wave reports and ask it to challenge assumptions, identify missing failure paths, and propose acceptance evidence.
3. Send material objections back to the relevant roles. Require a direct response: accept, reject with evidence, or revise.
4. Preserve unresolved disagreement. Do not manufacture consensus.
5. Stop after at most two challenge rounds and adjudicate as lead.

Only the lead coordinates agents. Role agents must not spawn their own councils or delegate recursively. Bound each role to the smallest evidence set needed for its assigned question; when evidence remains unavailable, return `unresolved` instead of continuing an open-ended repository investigation.

When team review was not explicitly requested, do not simulate product, business, technical, or test roles sequentially. Continue as one implementation agent and apply the regression shield directly. When team review was requested but collaboration tools are unavailable, report that the requested independent review cannot be performed; do not silently replace it with simulated consensus.

Keep every role read-only during review. The lead agent is the only writer unless it explicitly assigns non-overlapping implementation files after the plan is accepted. Read `references/roles.md` and `references/review-protocol.md` before dispatching roles.

## Establish the change contract

Before implementation, write a compact contract containing:

- requested outcome;
- current observed behavior and evidence;
- behavior that may change;
- behavior that must remain unchanged;
- affected authority, data, UI/API, model, Skill, and recovery boundaries;
- smallest safe implementation scope;
- rollback path;
- focused tests, related tests, and full-suite expectations;
- user decisions still required.

For every material user MUST, also record the original wording, whether its scope is `open_world` or `closed_world`, its operational definition, forbidden narrowing, implementation boundary, invariant test paths, and completion evidence. Treat requests covering all future/similar/common cases, different models/providers/genres, or root-cause resolution as open-world. Never reinterpret them as support for only the observed fixture without explicit user approval.

Do not implement while a material requirement, authority boundary, or destructive target remains ambiguous. Follow `references/decision-contract.md`.

## Prevent sample-specific completion claims

- Promote a repeated incident family or an explicit common/root compatibility request to a mechanism-level change. Do not use an observed key, provider, error string, or payload as the abstraction boundary.
- Let user-authorized systemic recovery override the preference for a smaller patch. A literal alias branch may supplement a canonical adapter, but it cannot be the whole fix unless a finite closed-world contract is proven.
- Distinguish `contained`, `case_fixed`, `systemically_resolved`, and `unresolved`. For open-world work, report completion only after unseen structurally different valid variants recover without code changes and cross the next authoritative boundary.
- If a supposedly resolved incident family receives a new production shape that the implementation cannot recover, downgrade it to unresolved immediately. Do not preserve the prior completion claim merely because rollback worked.

## Implement with a regression shield

When the user authorized implementation:

1. Reproduce the defect or establish the pre-change baseline. For infrastructure or project-level refactors, freeze business invariant oracles first and migrate through `wrap -> shadow/parity -> switch -> delete`; no infrastructure simplification may silently change novel semantics or formal-promotion eligibility.
2. Add or identify a failing regression test before changing behavior.
3. Make the smallest coherent patch. Do not perform drive-by refactors.
4. Re-run the focused test immediately.
5. Test the next authoritative boundary, not merely rejection or rollback.
6. Run related cluster tests, then the complete suite before restart or completion when project policy requires it.
7. For every L2/L3 source change, build a version 2 forward-risk report from the complete production-incident catalog. It must preserve the original requirement, classify its scope, state forbidden narrowing and resolution status, map every material MUST to implementation/test/evidence, name the historical families checked, project the underlying mechanisms into every structurally similar and later workflow boundary, explain why prior tests missed the production shape, and cite both production-shaped recovery tests and tests that cross the next authoritative boundary. A boundary may be marked not susceptible only with concrete code evidence. When a model-output boundary changes, cite at least six valid realizations spanning four topology classes, two valid unseen container/wrapper arrangements, two invalid/incomplete variants, two transport/capacity faults, unknown-variant behavior, and invariant-based tests; one canned response, one schema family with cosmetic variants, or an exact-prose golden is insufficient. When no model-output boundary changes, provide concrete not-applicable evidence.
8. Run `scripts/inspect_change_gate.py --baseline <temporary-json> --declared-level <L1|L2|L3> --forward-risk-report <temporary-json> --strict`, using the council's risk classification. The script may raise that level but must not lower it. Declare each valid nonstandard test with a repeated `--related-test <changed-source>=<test-path>` mapping. When more than two authority-critical modules change and the user explicitly requested team review, submit `--split-review-report <temporary-json>`: version 1, final `core_tree_sha256`, and two-or-more distinct review slices, each covering at most two core paths with a distinct reviewer, passing status, concrete evidence, and existing tests. When the user explicitly chose single-agent review, submit `--single-review-report <temporary-json>` instead: bind the final core tree, cover every core path exactly once, cite the raw request, baseline, final diff, raw test output and forward-risk report, and set `independence_claimed=false`. Never use the single-agent form when independent review was requested, and never invent reviewer identities. Stale, missing, overlapping, failed, or incomplete reports do not satisfy the gate. Resolve or explicitly account for every finding. The strict gate must fail for L2/L3 source changes when the forward-risk report is absent or incomplete.
9. Inspect the final diff from a clean context. Ask an independent test/review role only when the user explicitly requested **团队评审**.
10. Reject a candidate change that fixes one target while creating a new hard failure, widening unauthorized scope, or regressing protected behavior.

Keep the last accepted business artifact and old authority path whenever parity disagrees. Do not delete an old parser, router, retry, checkpoint, or reducer until reachability evidence, business-equivalence tests, applicable current-project and 13K/20K/30K acceptance, and the full suite all pass.

Without an explicit team-review request, rebuild context from the raw request, baseline, final diff, and raw test output and perform a single-agent clean-room self-review. Do not label it independent or describe it as a council. If the user explicitly required a genuinely independent review and it is unavailable, stop and report that boundary.

Read `references/regression-shield.md` for failure families, change sizing, and monotonic acceptance rules.

### Apply the systemic completion gate

For an open-world or systemic planning, recovery, model-output, split/resume, or narrative-authority change, do not stop after the observed failure is repaired or the next authoritative boundary passes. Require a complete draft candidate from the production workflow, then verify deterministic split/merge ownership and reconstruction, segment-level and whole-draft semantic receipts, complete-draft integrity, whole-story continuity, polish, and the applicable pre-final-review quality gates.

Treat forward-looking acceptance as an independent hard gate. Project the changed mechanism into the causal chain, execution manifest, drafting, split/merge, polish, targeted and manual revision, final review, and formal promotion. Test each reachable boundary or cite concrete code evidence that it is not susceptible. Do not accept protocol or structural success that weakens prose quality, narrative logic, character or knowledge state, timeline, viewpoint, pacing, setup/payoff, the confirmed ending, or user-selected scope.

This gate is repository-backed and survives a new window or compacted context; always reconstruct it from `AGENTS.md` and this Skill. Keep acceptance proportional for localized closed-world work: a narrow change still uses focused, related, and complete-suite evidence appropriate to its risk, and does not require paid-provider execution. Automated tests remain offline. A user-authorized systemic workflow repair must complete the offline production-shaped end-to-end proof before any separately authorized real-provider canary.

### Apply the current-project real-data snapshot gate

For every production incident and open-world or systemic workflow repair, create a fresh read-only snapshot of the user-designated current project or incident project. Preserve its actual StoryState revision, outline/ending authority, required character and world material, affected run artifacts, receipts, checkpoints, route-capability metadata, hashes, topology, counts, and payload proportions. Remove credentials, secret values, raw provider errors, absolute machine paths, and unrelated private sources. Execute the real workflow in an isolated temporary project/database copy; never write the live formal manuscript, Canon, StoryState, candidates, run history, references, credentials, or checkpoints.

Require two non-substitutable offline proofs: the private current-project snapshot must reproduce the affected shape and recover through the required downstream boundary, while a committed sanitized isomorphic fixture must preserve topology, ownership, size/pressure ratios, failure class, and invariant oracles without retaining real prose or volatile identifiers. Bind the private replay to a hash-only manifest outside the repository or in ignored test artifacts, rebuild it when source authority changes, and keep paid-provider calls separately authorized. When first-generation behavior is reachable, also test a clean new project. If the current snapshot cannot be obtained or safely completed, report `contained` or `unresolved`, never `systemically_resolved`.

### Apply the short-fiction production-length gate

Treat 30,000 effective Han characters as the recommended short-fiction operating range, not a Runtime or API hard limit. For any workflow-level change involving planning, capacity, semantic split/merge, drafting, polish, review, checkpoint/resume, or promotion, require offline complete-flow evidence at 13,000, 20,000, and 30,000 effective Han characters. Smaller fixtures remain useful unit evidence but cannot establish production short-fiction capacity.

The three runs must use the real workflow orchestration and capacity decisions with a deterministic provider replacement only at the paid network boundary. Require distinct event-owned prose, state and relationship progression, promises and payoff, and a confirmed ending; repeated filler or direct final-artifact writes do not qualify. Completion requires the full candidate to cross planning, causal chain, execution manifest, drafting, split/merge, polish, final review, and applicable formal promotion. This gate is durable repository policy and must be reconstructed after a new task or compacted context.

## Respect hard boundaries

- Never call paid model APIs from tests or maintenance checks.
- Never allow a development role or this Skill to write a formal manuscript directly.
- Never introduce a second StoryState, competing workflow, or alternate formal-write path.
- Never conflate this Codex development Skill with runtime roles such as `review`, `reader_review`, `final_review`, `polish`, or `maintenance`.
- Never overwrite unrelated user changes, delete test logs, stash, reset, commit, restart, or terminate an active run without matching user authorization.
- Treat containment and rollback as safety, not proof that the root problem is resolved.
- Convert every newly observed production failure into a stable regression fixture or explain the exact blocker.

## Deliver the result

Use the final structure in `references/decision-contract.md`. Lead with the outcome, then report:

- consensus and material dissent only when team review was explicitly requested and performed;
- exact files and boundaries affected;
- implementation and rollback decision;
- focused, related, and full test evidence;
- remaining risk and user decisions;
- whether the request is complete, safely contained, or still unresolved.

Do not describe work as complete when only a guard rejected the bad result. Local completion requires the intended successful path to cross its next authoritative boundary. Open-world or systemic workflow completion additionally requires the complete-draft and independent forward-looking acceptance defined above.

When modifying this Skill, validate it with the installed `skill-creator` `quick_validate.py` under Python UTF-8 mode (`python -X utf8 ...`) and run the repository tests covering both bundled scripts.
