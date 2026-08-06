# Review protocol

## Round 0: evidence packet

The lead prepares only neutral evidence:

- exact user request and authorization level;
- current Git status and pre-existing changes;
- relevant files, tests, design documents, and observed behavior;
- known constraints from `AGENTS.md`;
- unknown facts that require investigation.

Do not include a preferred solution in first-wave prompts.

## Round 1: independent analysis

Run product, novel-business, and technical roles independently. Do not expose their reports to one another before all three have returned.

Do not let a role spawn more agents. Give it a bounded question and require a result after inspecting the most relevant call path, contract, and tests. Missing evidence becomes an explicit uncertainty rather than an unlimited search.

For L1 work, use only technical and test passes unless risk discovery promotes it to L2 or L3.

## Round 2: adversarial test review

Give the test role all first-wave reports and the neutral evidence packet. Require it to:

- identify conflicting assumptions;
- propose counterexamples and production-shaped failures;
- distinguish a test that proves containment from one that proves successful recovery;
- challenge oversized or cross-boundary implementation plans;
- identify missing unchanged-behavior assertions.

## Round 3: rebuttal

Return each material objection to the responsible role. Accept only one of these responses:

- `accepted`: revise the recommendation;
- `rejected`: cite stronger repository evidence;
- `unresolved`: identify the missing evidence or user decision.

Do not accept vague agreement, repeated summaries, or authority-by-role.

## Round 4: lead adjudication

The lead produces:

- facts established by code or tests;
- consensus recommendations;
- dissent and its consequences;
- selected approach and rejected alternatives;
- change contract and test ladder;
- implementation authorization status.

The lead may stop and request user direction only when a missing choice materially changes behavior, data, cost, or recovery.

## Post-implementation challenge

After code changes, give an independent reviewer the user request, baseline behavior, final diff, and raw test output. Do not provide the intended fix or the implementer's reasoning. Ask the reviewer to find:

- an untested path;
- a newly widened mutation scope;
- a stale or partial authority path;
- a UI/API disagreement;
- a false success state;
- a rollback that contains but does not resolve the problem.

The lead resolves findings or reports them as remaining risk. Limit debate to two substantive cycles.
