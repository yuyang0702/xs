# Full Short Runtime Capacity V3 design

## Change contract

- Requested outcome: migrate trustworthy historical route capability evidence,
  make every live route explicit (verified or `UNKNOWN_BLOCKED`), and eliminate
  logical/physical capacity-attempt drift without changing story authority.
- Scope: L3, open-world across providers and route identities. A model name,
  protocol, upstream vendor, observed successful budget, or stage ceiling may
  never stand in for exact route capability evidence.
- Allowed changes: additive route-capability contracts, typed capacity failure
  families, Runtime-owned physical-attempt allocation, offline tests, and
  hash-only evidence.
- Protected behavior: StoryState, Canon, formal/candidate/best manuscripts,
  confirmed outline and ending, existing business validators, Baseline Skill,
  provider/model bindings, credentials, exact replay, authority gates, normal
  Planning reasoning, and Hybrid/Selective production invisibility.
- External boundary: zero credential/secret reads, provider clients, HTTP,
  network, model/paid calls, and real Full Short executions.
- Forbidden narrowing: no bare `32768`, `372K`, request cap, price tier, model
  family, or official-upstream limit may certify a different relay route.
- Rollback: remove the additive registry consumer and restore caller ordinal
  validation. No database, project, manuscript, or binding rewrite is needed.

## Selected architecture

`RouteCapabilityRegistryV1` is a content-addressed set of exact `(role, lane)`
records. Each record binds provider, operator, destination, protocol, model,
route fingerprint, context/output limits, reasoning semantics, evidence, and a
capability SHA. Verified records require provenance for both context and output
limits. Unknown records must omit those numbers and carry blocking reason codes.

Capacity admission must call `require_dispatchable`; an `UNKNOWN_BLOCKED` route
fails before route/provider/credential resolution as
`capacity.route_capability_unknown`. Unused unknown routes remain records but do
not block an execution plan that cannot select them.

The durable observer is the only authority for physical attempt ordinals.
Contract Runtime schedule indices remain diagnostic metadata because skipped or
locally denied schedule slots are not physical dispatches. The frozen logical
identity is derived from the sealed logical-stage plan and execution policy;
each physical attempt receives a distinct identity and may vary only through a
registered recovery role, route policy, reasoning policy, bounded output
reserve, prompt overlay, and capture identity.

## Historical evidence disposition

The revised task binds the 2026-08-14 DeepSeek official-route matrix to the
archived exact-route identity contract and reasoning-accounting packet. The
composite assertion records the official source locators, retrieval date and
source hashes, so the direct `deepseek-v4-pro` route is reusable as
`VERIFIED_HISTORICAL_EVIDENCE` at 1,000,000 context tokens and 384,000 maximum
output tokens. This does not establish any relay capability.

The user-supplied screenshot bundle is hash-inventoried and represented by
privacy-safe crops. The LingSuan `gpt-5.6-sol` screenshot visibly proves a 372K
context label, but no maximum output and no independently archived
`lingsuan.top` console-to-`lingsuan.org` API operator link; the route therefore
remains `UNKNOWN_BLOCKED`. Happy Qwen and LingSuan Claude screenshots prove
only their visible identity, endpoint-family, pricing, performance, and
parameter facts. Observed request budgets prove only successful lower bounds,
never maxima. Existing `32,768` values remain stage policy ceilings rather than
provider context limits.

## Verification and stop-loss

Focused tests cover canonical hashing, missing/unknown records, exact identity
drift, no guessed values, and Runtime-owned attempt ordinals. The generated V3
fault campaign covers all Master scenarios through the registered Runtime
boundary. Related Runtime/capacity tests and the full suite follow before any
authorization artifact may be created.

If any Exact READY required route remains `UNKNOWN_BLOCKED`, the exact plan and
Full Short dry run remain blocked with
`FULL_SHORT_ROUTE_CAPABILITY_OR_WORKLOAD_POLICY_DECISION_REQUIRED`. This is an
honest readiness stop, not permission to probe a provider or guess a limit.
