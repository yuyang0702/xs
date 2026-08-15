# C0B-P1.1 Canary Approval Evidence Contract Report

## Result

The three C0B-SMOKE-1 evidence gaps are closed in the Canary control plane:

- Budget ceiling refusal has an independent `CANARY_BUDGET_EXHAUSTED` controlled outcome.
- Budget-stop evidence binds the current run to an existing checkpoint and last formally accepted artifact as `exact`, `none_available`, or `unverifiable`, without creating business state.
- Validate-only now produces an ordered 25-check `C0BApprovalClosureValidationReceiptV1` over Plan, Approval, launcher, workload, source/build/config/runtime, routes, protocol, flags, price, budgets, stops, isolation, window/replay, and external authorization.

## Budget-stop behavior

The approved C0B-P1 outer ceiling remains 144 calls. The disabled C0B-SMOKE-1 Approval candidate carries a hash-bound 48-call per-run/cohort sub-ceiling. Deterministic tests prove calls 1–48 can pass and the next requested paid boundary is refused before any new delegation.

Independent typed dimensions are covered for per-run calls, cohort calls, input tokens, output tokens, USD, CNY, and elapsed seconds. The refusal receipt records the approved ceiling, already reserved amount, requested amount, remaining amount, ledger hash, checkpoint/artifact bindings, prior attempt receipt, prior typed failure, route, and requested retry/fallback action.

`CANARY_BUDGET_EXHAUSTED` is not a workflow terminal, provider failure, Runtime defect, or production incident. The local parity test observes no change to StoryState, Candidate, or workflow checkpoints; full live parity covers Canon and Saga artifacts as well.

## Validate-only receipt

The reproducible disabled-candidate receipt is `c0b-p1-1-approval-closure-validation-receipt-v1.json`:

- overall status: `exact`
- ordered checks: 25/25 exact
- validation receipt: `7dfbb36bc9ee46f732d92a897acaf43ae000a54ee432fb7ca664e2a246073fa3`
- launcher: `c4d01b4aaaeb41208db4d25578e42ffb5c889f56ffdc7dc872bd03c74a835e16`
- Approval budget definition: `b7b5a435922eee1bc9e5e6566b0de5498b984deae80d61ae8ccee6562b517cbf`
- external counters: credential/provider-client/network/model/paid = `0/0/0/0/0`
- Approval state: `disabled_candidate`; not reserved, consumed, or executed

Negative closure tests block build, execution config, runtime execution, provider descriptor, role/route binding, price manifest, Happy test-group substitution, Approval budget, stop-condition, Phase 1B, expired Approval, and replay drift.

## Test evidence

- P1.1 focused: `27 passed`.
- Canary + Runtime fingerprint related: `96 passed, 1 skipped` after the final test addition.
- Full suite: `2529 passed, 2 skipped, 5 xfailed, 1 failed` in 1097.70 seconds.
- The single failure is pre-existing live DB baseline drift in `tests/test_r0e_reports.py`. Baseline commit `fd857094` still expects `5deb7bdf…`, while the task-start DB was already `0fccb8ae…`; the same isolated assertion fails after this patch. It was not modified.
- Therefore newly introduced failures: 0.

## Production and live parity

- `src/novel_flywheel/**` diff: 0.
- `baml_src/**` diff: 0.
- `pyproject.toml` diff: 0.
- Production Build Fingerprint: `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0` (unchanged).
- Execution Config: `70a487fa8f2152e14923aa82560ace39c83a052e4556e03eb1b54ba4976bff13` (exact).
- Runtime Execution: `eb2ed19dd0b6b9a7517f6044f4a8aecb0aadfcb9f2e1303f3ba77567a8b710a5` (exact).
- Provider Descriptor manifest: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f` (unchanged).
- Role/Route Binding manifest: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e` (unchanged).
- live DB: `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3` (task-start exact).
- formal narrative manifest: `585a2c8a435ec714bc839efae4bc92a2a4a3e131198623629e15d51880956908`.
- StoryState rows: 6; Candidate rows: 11; Checkpoint rows: 917.
- Canon manifest: `d560044730a61382b401643a8159f58e07d919b601b97e931e8785b827bd84b0`.
- Candidate/checkpoint/Saga file manifests remain empty: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- production incident count was not increased; real Smoke was not run.
- Prompt, Production Route behavior, retry/fallback, and Phase 1B remain unchanged; Phase 1B is false.

No executable Approval was materialized. No credential was read, no provider client was created, no network/model/paid call occurred, and C0B-SMOKE-1 was not executed.

**C0B_P1_1_EVIDENCE_CONTRACT_READY**
