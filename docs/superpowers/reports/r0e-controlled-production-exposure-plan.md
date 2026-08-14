# R0E Controlled Production Exposure Plan

Status: **design only**. `RuntimeBuildFingerprintV1` is not implemented, so all
real-provider execution is `BLOCKED_BY_FINGERPRINT`. R0E paid calls are zero.

## Isolation and frozen behavior

Use a dedicated canary database, a new canary-only project root, and a run
namespace that cannot be discovered by the live production incident scan. Do
not copy live credentials into fixtures or reports. `NOVEL_SHORT_CANONICAL_V2`
and the project `short_canonical_v2` flag remain false. The canary launcher must
refuse to start unless the run artifact freezes and later exposes the exact
verified fingerprint, provider/model route IDs, budgets, prompt hashes, ordered
attempts, and feature-flag snapshot.

The separately approved launcher may replace only the paid network boundary.
It may not change prompts, validators, retry/fallback schedules, Completion
Supervisor policy, Maintenance/Repair behavior, checkpoint/resume, or Runtime.

## Workload mixture

Each stratum is reported separately; weights are never silently treated as the
production distribution.

1. ordinary new short workflow at common target length;
2. 13K, 20K, and 30K effective-Han production-length workflows;
3. high input-pressure workflow that reaches semantic split/capacity policy;
4. Maintenance normal path;
5. Maintenance window path;
6. provider output-limit/normal-incomplete and primary/fallback route recovery;
7. controlled waiting/checkpoint/resume continuation.

Deterministic fault-injection coverage and structural reachability remain
separate denominators from real-provider exposure. Real canary exposure remains
separate from production-distribution exposure.

## Provider, model, tokens, and money

Provider and model are intentionally `TBD`: the approval task must select them
and freeze the exact route fingerprints before price or token claims are made.
For each run record input tokens, output tokens, thinking tokens when exposed,
requested and actual output budgets, currency, published unit price snapshot,
and the exact formula:

`cost = input_tokens * input_unit_price + output_tokens * output_unit_price`

No report may infer price from a model family name. Establish hard per-run and
campaign token, call, time, and currency caps before launch. R0's deterministic
26-run corpus used 379 calls, or 14.5769 calls per recovered workflow; planning
uses that only for budgeting, never as a claim about provider behavior.

## Zero-failure sample sizes

For a one-sided 95% bound with zero terminal failures:

`p_upper = 1 - 0.05 ** (1 / N)` (approximately `3/N`).

| Runs | Exact upper bound | Calls at R0 average (ceil) | Hard cap at 20/run |
| ---: | ---: | ---: | ---: |
| 59 | 4.95% | 861 | 1,180 |
| 99 | 2.98% | 1,444 | 1,980 |
| 299 | 1.00% | 4,359 | 5,980 |

Unless the workload weights are proved to match production, the only valid
claim is a **canary-mixture terminal-rate bound**, not a production terminal-rate
bound. A non-zero failure is reported directly; the zero-failure bound is not
used.

## Stop conditions

Stop before the first paid call if the fingerprint is missing/unverified, flags
are not both false, the target is not the isolated canary project/DB, live
artifact hashes drift, or the provider/model/budget/price snapshot is incomplete.
Stop the campaign on any credential/prose/prompt leak, unexpected formal write,
unclassified terminal, Candidate/checkpoint mismatch, causal-chain loss,
attempt-order change, timeout-policy change, cost/token/time cap breach, or live
incident-count change. A controlled `waiting_provider` or `waiting_user` is not
automatically a defect; compare it with the cited Supervisor policy.

## Acceptance and reporting

Report started/completed workflows, model attempts, local normalization,
protocol retries, fallback attempts, controlled waits/resumes, terminal outcomes,
and coverage gaps per workload stratum and fingerprint. Never merge fingerprints,
model versions, or workload mixtures into one denominator. A future canary does
not authorize Runtime modification; findings return to a separate development
gate.
