# C0B-P1 Production-Mirror Real Canary and Budget Design

Status: implemented for review; real execution remains disabled.

## Change contract

C0B-P1 adds an outer Canary authorization and accounting boundary only. It does
not modify Runtime, Contract Runtime, prompts, parsing, adapters, validators,
retry/fallback policy, Maintenance, Repair, StoryState, Canon, provider routes,
or Phase 1B. The only production dispatch implementation remains
`novel_flywheel.models.ModelGateway` with
`novel_flywheel.providers.registry.ProviderRegistry`.

The permitted write set is `tools/canary/**`, `tests/canary/**`, and
`docs/superpowers/**`. Rollback is the parent commit
`95531877567574374c41dc6658d08ee00836c912`; no schema or business artifact
migration is required.

## Authorization sequence

The first and every later paid boundary follows the same ordering:

1. validate Plan, Approval, launcher, workload, source, fingerprints, bindings,
   sidecars, routes, flags, and isolated root;
2. pre-reserve call, token, independent USD/CNY cost, and elapsed budget;
3. run the existing Runtime fingerprint preflight;
4. validate exact C0B scope, single-use authority, named approver, time window,
   and four explicit external-action booleans;
5. open the final authorization latch;
6. allow keyring lookup, production adapter construction, and production
   `ModelGateway` dispatch.

Before step 4 completes, credential, provider-client, network, model, and paid
counts must remain zero. Importing or validating the launcher is inert.

## Budget model

The monetary ledger stores USD and CNY independently. No FX conversion or
online exchange-rate lookup exists. Every call reserves cache-miss input and
the configured output cap. Missing usage, timeout, HTTP failure, cancellation,
or an unreliable billing receipt retains the full reservation. A reliable
usage receipt can add an overage but cannot refund a reservation.

`qwen-max-thinking` uses the default-group rate and separately reported
reasoning tokens are charged at the output rate. The `test` group is a distinct
price identity and is not selectable by the Production-Mirror Plan.

## Call and elapsed topology

The deterministic normal fixture reaches 16 logical boundaries. Each Runtime
boundary has two primary and two configured-fallback route slots. The current
Runtime does not expose a workflow-global theoretical paid-call maximum:
planning adaptation resets per-unit counters after a strictly improved
candidate. C0B therefore does not mislabel a Runtime theoretical maximum.

Instead, the signed Plan provides an exact outer authorization cap of 144 paid
dispatches. Dispatch 145 is rejected before credential lookup. The allocation
covers the 16-boundary four-route schedule plus bounded Canary allowance for
scoped repair, quality correction, Maintenance repair, and role fallback. A
budget stop is a controlled Canary result; it does not reclassify Runtime.

Elapsed enforcement uses the configured 180-second provider timeout, the
four-route stage schedule, measured fingerprint overhead allowance, local
artifact allowance, and a final launcher margin. The hard launcher timeout is
27,108 seconds; it is intentionally conservative for a single run.

## Capability unknowns

Identity, price, and a dispatchable protocol are required. Unknown public
context/max-output/structured-output details for a relay are accepted only as
`BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE`, with a strict per-call output reservation.
Capacity, output-limit, unsupported-parameter, structured-output, or protocol
rejection is recorded as `CONTROLLED_PROVIDER_CAPABILITY_OUTCOME`. The relay
returned model identity is observational and never treated as upstream-vendor
proof.

## Forward-risk report V2

- Highest-risk dependency: a future production signature change in
  `ModelGateway.complete_route`, runtime route schedule, provider metadata, or
  fingerprint sidecar invalidates the signed Plan/launcher hash and blocks
  before credential access.
- Data risk: the real runner creates a fresh DB, copies only non-secret
  provider/model/role metadata, and writes projects only under the Canary root.
  Live DB/project/incident trees are hashed before and after.
- Cost risk: Runtime has no single global repair-call counter. Independent call,
  token, USD, CNY, and elapsed caps are therefore all mandatory; none is
  advisory.
- Provider risk: relay capability and upstream exact version remain bounded
  unknowns. They can end Smoke as a controlled provider outcome but cannot be
  silently promoted to Runtime defects.
- Operational risk: the first real run may occupy a worker for hours under the
  conservative elapsed cap. C0B-SMOKE-1 permits one run and first-terminal stop;
  no cohort expansion is authorized.
- Security risk: evidence contains aliases, hashes, usage, finish/failure types,
  and status classes only. API keys, headers, endpoints, prompts, prose, raw
  outputs, account identity, and personal information are forbidden.

## Strict change gate

Acceptance requires focused Canary/fingerprint tests, a full-suite comparison,
zero `src/novel_flywheel/**` and `baml_src/**` diff, unchanged production build
fingerprint, exact live artifact parity, import-closure validation, and a
single-agent clean-room review. A signed Approval must be generated separately;
the checked-in draft has every external action set to `false`.
