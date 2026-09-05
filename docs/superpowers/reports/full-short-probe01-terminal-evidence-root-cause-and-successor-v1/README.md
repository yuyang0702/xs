# Probe-01 terminal and billing forensics

Status: **STOPPED — historical usage disposition unresolved; independent reviewers reject current successor dispatch eligibility.** No Provider request or credential lookup was made. No production code, test, route, model, Skill, historical evidence, or narrative authority was changed.

The six fresh offline reviewers inspected the current repository and local evidence. Exact replay of the persisted 1,735-byte entity proves that the existing Anthropic adapter recognizes a complete `message_stop` / `end_turn` response. The primary failure is **OTHER_TYPED_ROOT_CAUSE / CONTRADICTORY_PROVIDER_REPORTED_INPUT_USAGE_WITH_LOSSY_LOCAL_CLASSIFICATION**. The response reports input 48,916 at message start and 89,255 at the terminal delta. The canonical usage extractor raises `PROVIDER_REPORTED_USAGE_INPUT_CONFLICT`; the observer discards this reason and reports `probe.provider.incomplete_terminal_evidence`.

The local ledger retained 30,458 because it fell back to the synthetic 121,832-ASCII-byte request estimate (four characters per token). That value is not measured Provider usage and is below both captured input samples. Final reported input is 58,797 above the ledger, a ratio of 2.930428787. Terminal output is 9; the historical 2,974 output debit is the authorized reserve, not generated output.

The additional billing panel is attributed **USER_SUPPLIED_RELAY_DASHBOARD_EVIDENCE**. Its model and 89,255 / 9 usage match the raw response. Its 07:51:59 timestamp matches the local terminal second if UTC+08 and completion-time semantics apply. Missing request ID, route, timezone and timestamp semantics prevent a claim of exact event binding. The panel price computes to $0.089291 versus displayed $0.089292; the one-micro-dollar difference is numerically small but its cause is unproven.

Complete protocol framing does not establish which conflicting usage report is authoritative. Neither historical normalized receipts nor the panel proves a first/last/maximum-input acceptance rule. No capacity rejection appears in the captured entity, but no theoretical context ceiling or narrative success is inferred. The 2.93 ratio is not extrapolated to all requests/routes.

## Evidence map

- `baseline-binding-v1.json`, `prior-evidence-inventory-v1.json`: Master/supplement hashes, exact baseline, prior immutable evidence inventory.
- `agent-a-raw-capture-forensics-v1.json` through `agent-f-successor-campaign-v1.json`: six actual fresh reviewers, including the withdrawn classification and final disagreement resolution in `review-adjudication-v1.json`.
- `probe01-exact-replay-before-fix-v1.json`: MAIN exact replay, repeated twice; reviewer E independently repeated it three times. Both use current parser, adapter aggregation and usage extraction. Replay content type is inferred from SSE bytes, not a persisted HTTP header. Dispatcher and historical HTTP status are not retrospectively proven by this replay.
- `relay-billing-panel-evidence-v1.json`, `input-token-accounting-discrepancy-v1.json`: mechanical comparison, provenance limits and hypothesis audit.
- `successor-probe-case-set-v1.json`, `successor-budget-v1.json`: conditional planning only. Current executable set is empty. Seven cases would require replay-proven case 01; eight would require an eligible fresh replacement. Neither path is currently eligible.
- `focused-tests-v1.json`: unchanged-baseline focused suites, 86 passed. This is not a completed L3/full-suite or successor preflight claim.
- `requirements-disposition-v1.json`, `preexecution-final-report-v1.md`: requirement closure and explicit not-reached gates.

The prior campaign remains `TERMINAL_PROBE_FAILURE`, case 01 `FAILED_CONSUMED`, cases 02–08 `UNUSED`. Prior 30,458 / 2,974 accounting is preserved as historical evidence; observed raw and user-supplied billing metrics are separate. No successor authorization or nonce was created and no execution HEAD was frozen.

Next gate: **PROBE01_SOURCE_GROUNDED_USAGE_CONFLICT_RESOLUTION_AND_REPLAY_DISPOSITION**. The repair must separate typed failure provenance and conservative observed-usage accounting from acceptance, establish a source-grounded usage contract, preserve exact request/capture identities, and pass fresh successor eligibility review. A new request does not itself supply the missing semantic rule. The Master requires STOP on reviewer rejection, so no automatic restart is scheduled.
