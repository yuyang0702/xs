# C0B-P1 — Production-Mirror Real Canary Launcher and Budget Enforcement

Source HEAD: `95531877567574374c41dc6658d08ee00836c912`
Branch: `c0b-p1/real-canary-budget-20260815`
C0B/C0C execution: **not performed**

## Decision

`C0B_SMOKE_1_READY_FOR_USER_APPROVAL`

The launcher can execute the current Production-Mirror only after a new exact,
named, single-use C0B Approval authorizes credential lookup, provider-client
construction, network, and paid calls. The checked-in Approval is deliberately
non-executable: `named_approver=null` and every external action is `false`.

No real credential was read, no production provider adapter was constructed,
no provider network was accessed, no model was called, and no paid call was
made during C0B-P1.

## Production-Mirror and protocol evidence

The current isolated metadata copy exactly matches all eight approved roles.
No production route was changed. Happy and Lingsuan remain configured through
the current `anthropic` production path; Happy's supplied OpenAI-compatible
examples do not authorize an automatic route change, so Happy and Lingsuan
protocol evidence is correctly `PARTIAL_EVIDENCE`. Doubao remains
`openai-responses`; DeepSeek remains direct official API.

Exact details are in:

- `c0b-p1-production-mirror-provider-evidence-matrix.json`;
- `c0b-p1-route-protocol-evidence-matrix-v1.json`;
- `c0b-p1-bounded-unknown-capability-matrix-v1.json`.

DeepSeek pricing/model evidence uses the official
`https://api-docs.deepseek.com/quick_start/pricing/`. Doubao Seed 2.0 Pro tiered
pricing uses the official Volcengine price page; Character uses the official
family price and retains exact-version capability limits as bounded unknown.
Lingsuan/Happy prices and identities are explicitly labeled
`USER_SUPPLIED_RELAY_CONSOLE_EVIDENCE`, not upstream-vendor proof.

## Real boundary and ordering

`GuardedCredentialStore` cannot call `KeyringSecretStore.get` until the final
authorization latch opens. `GuardedProductionGateway` lazily creates the
existing production `ModelGateway`/`ProviderRegistry` delegation only after the
latch. It contains no OpenAI, Anthropic, DeepSeek, Doubao, Happy, or Lingsuan
client implementation.

The tested sequence is exact mutable-input validation → budget reservation →
existing Runtime fingerprint preflight → exact final authorization →
credential lookup → provider-client construction → network/model delegation.
Mutable Plan, Approval, launcher, workload, source, build/config/execution
fingerprints, bindings, sidecars, route manifests, flags, and Canary root are
rechecked at every boundary.

See `c0b-p1-real-provider-boundary-v1.json` and
`c0b-p1-ordering-evidence-v1.json`.

## Call topology

The current deterministic 6K fixture records 16 normal logical model
boundaries and 36,715 estimated input / 46,197 reserved output tokens. Current
primary-route expected cost is USD 0.136066 plus CNY 0.123821, without cache
credit.

Runtime gives each boundary two primary and two configured-fallback attempts.
It does not have a workflow-global theoretical paid-call bound: planning
adaptation resets local attempt counters after each strictly improved
candidate. This report does not call 144 the Runtime theoretical maximum.

The exact C0B outer cap is 144 paid dispatches for one run. It allocates 64
normal route slots and 80 scoped recovery/quality/Maintenance/role-fallback
slots. Dispatch 145 fails before credential lookup. Resume can consume only the
same single-use Plan's remaining call/token/money/time authority and cannot
extend it.

See `c0b-p1-short-call-topology-v1.json`.

## Token, money, billing, and elapsed budgets

| Budget | Expected | Hard cap |
|---|---:|---:|
| Model calls | 16 primary | 144 paid dispatches |
| Input tokens | 36,715 | 2,000,000 |
| Output tokens | 46,197 | 2,000,000 |
| Output per dispatch | Runtime-selected | 32,000 |
| USD | $0.136066 | $60.00 |
| CNY | ¥0.123821 | ¥120.00 |
| Duration | 1,800 seconds candidate | 27,108 seconds launcher hard cap |

No FX conversion is performed. Unknown failed-call billing is treated as
chargeable, and missing/rejected/timeout/cancelled usage retains the entire
reservation. Actual input, cached input, output, and separately reported
reasoning tokens reconcile when reliable usage is present; reconciliation
never refunds Canary authority.

See `c0b-p1-canary-monetary-budget-v1.json`,
`c0b-p1-provider-billing-policy-v1.json`, and
`c0b-p1-elapsed-budget-v1.json`.

## Exact packet identities

| Identity | SHA-256 |
|---|---|
| Plan | `9895d811772f4f1b8fdc98ee073ffcf015a9cf7d05e630f8857dd3fd7d849dd8` |
| Approval Draft | `262d0057db5942919510d87cffaf714deb64d862b3d95d8709aa55ebb808fdb8` |
| Launcher | `d0b308f2e3da995a848dc25e73c30d4d17fb03ed8461ff0b031736b85539be50` |
| Workload | `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1` |
| Build | `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0` |
| Execution Config | `70a487fa8f2152e14923aa82560ace39c83a052e4556e03eb1b54ba4976bff13` |
| Runtime Execution | `eb2ed19dd0b6b9a7517f6044f4a8aecb0aadfcb9f2e1303f3ba77567a8b710a5` |
| Provider descriptor manifest | `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f` |
| Role binding manifest | `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e` |
| Price catalog | `053fbf7d5fe203257dfb200e019c0ac4bdb811f09e244db4f37c906c7667649a` |
| Call topology | `a36eb946c3dae1c1122e78789c8bcc2dd14218e5aedf3e3a3fa63f2cc0af6113` |
| Elapsed budget | `a3c32156c65c7abe4068a8af9e0f143457f8816013de6543c77410eee1df81a6` |

Machine-readable source: `c0b-p1-exact-hash-matrix-v1.json`.

## Test and parity status

- Focused Canary/fingerprint suite: `69 passed, 1 skipped`.
- Full suite first-failure audit: `1 failed, 1636 passed, 2 skipped, 5 xfailed`;
  the failure is pre-existing live DB drift. The current task-start DB hash was
  already `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`,
  while `tests/test_r0e_reports.py` still expects the historical
  `5deb7bdf811c90366ee1342de108c53355cea1c39aff72670bacd99cd5ffab87`.
  C0B-P1 does not update that baseline.
- Full suite excluding only that exact pre-existing assertion reached 86% with
  no failure before the 900-second command limit. The uncompleted
  `tests/test_workflows.py` tail was then selected from collection item 51:
  `328 passed, 50 deselected`. Combined evidence covers the full collected
  suite and shows zero newly introduced failure.
- `src/novel_flywheel/**` diff: 0.
- `baml_src/**` diff: 0.
- Production Build Fingerprint: unchanged (`bbf17e…53f0`).
- Prompt, Runtime route behavior, retry/fallback policy, and Phase1B: unchanged.
- Live DB and live projects match the task-start `0fcc…` baseline; no new
  production incident was written.
- C0B-P1 credential/provider-client/network/model/paid counts: `0/0/0/0/0`.
- Single-agent clean-room review found no unresolved blocker after tightening
  exact client/network counters, per-dispatch output cap, and validation order.

## Deliverables and approval action

The exact executable Plan is `c0b-smoke-1-plan-v1.json`. The current
`c0b-smoke-1-approval-draft-v1.json` is intentionally not executable. The
user-facing packet is `c0b-smoke-1-approval-packet-v1.json`; all 20 requested
deliverables are indexed by `c0b-p1-deliverable-index-v1.json`.

To execute later, generate a fresh Approval bound to the unchanged Plan and
launcher, set a named approver and explicit four external-action booleans,
choose a fresh execution window, and run `--real-run` once. Any byte, route,
flag, fingerprint, budget, workload, or time-window drift invalidates that
authority. This stage does not grant it.

**C0B_SMOKE_1_READY_FOR_USER_APPROVAL**
