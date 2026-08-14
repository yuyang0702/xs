# C0B-P0 — Real-provider Approval Packet Closure

Date: 2026-08-14—2026-08-15  
Source HEAD: `ae00d8460b66ffdca1bbf02d567a2b577e9799d3`  
Runtime mode in scope: `git_workspace`  
Production/provider execution: **not performed**

## Executive decision

`GIT_WORKSPACE_C0B_PACKET_STATUS = NO-GO`

`PACKAGED_C0B_PACKET_STATUS = NO-GO`

`REAL_PROVIDER_CANARY_EXECUTED = false`

The Production-Mirror route cannot be priced or capability-verified because six
proxy/internal model aliases and one partially verified fallback lack exact supplier,
version, capability or billing evidence. A DeepSeek-only Reduced-Risk candidate can be
hashed and priced from official public material, but it is still not executable:

1. the current launcher accepts only `C0A_FAKE_DRY_RUN` and calls
   `run_c0a_dry_run`;
2. the proposed maximum call count and elapsed time are conservative candidates,
   not an exact derivation from every legal attempt transition;
3. real-provider cost estimation/enforcement is not implemented in the launcher
   boundary;
4. account-specific failed-call, retry, cache and thinking-token billing terms have
   not been verified;
5. no named approver has signed and every external-action authorization remains
   `false`.

An exact hash proves the identity of a candidate. It does **not** prove the candidate
is safe, affordable, approved, or executable.

## Safety boundary observed

This task read only non-secret provider/model/role metadata from the local database,
using SQLite read-only immutable/query-only mode. It queried public documentation.
It did not read API keys or credentials, create a provider client, call a provider API,
make a model request, consume an approval, or alter Runtime/Prompt/Route/Retry/Fallback.

| Counter | Result |
|---|---:|
| Credential lookups | 0 |
| Provider clients created | 0 |
| Provider API calls | 0 |
| Model calls | 0 |
| Paid calls | 0 |
| C0B executions | 0 |
| C0C executions | 0 |

Public documentation retrieval is recorded as evidence research and is not counted as
a Provider API/model action.

## 1. Provider / Model Evidence Matrix

The machine-readable matrix is
`c0b-p0-provider-model-evidence-matrix.json`. Local probes are retained only as local
observations; they are not promoted into supplier capability or price proof.

| Internal route member | Roles | Actual supplier/model | Capability | Pricing | Status |
|---|---|---|---|---|---|
| `happy/qwen-3.7-plus` | Draft primary | Unknown | Unknown | Unknown | User evidence required |
| `happy/qwen-max-thinking` | Draft fallback | Unknown | Unknown | Unknown | User evidence required |
| `lingsuan_gpt/gpt-5.6-sol` | Planning/Final Review/Maintenance primary; Review fallback | Unknown | Unknown; local probe is stale after route change | Unknown | User evidence required |
| `deepseek/deepseek-v4-pro` | Review primary; Planning/Final Review/Maintenance fallback | DeepSeek / `DeepSeek-V4-Pro-0813` | 1M context, 384K max output, JSON/tool/Anthropic supported | Official USD schedule verified | Verified official |
| `doubao/doubao-seed-character-260628` | Reader Review primary | Volcengine Ark / exact version unverified publicly | Exact limits unverified | Exact version price unverified | User evidence required |
| `doubao/doubao-seed-2-0-pro-260215` | Reader Review fallback | Volcengine Ark / `doubao-seed-2-0-pro` version `260215` | Exact public limits incomplete | CNY tiered price verified | Partial; user evidence required |
| `lingsuan_sonnet/claude-sonnet-5` | Polish primary; Line Edit fallback | Unknown | Unknown; local probe is stale after route change | Unknown | User evidence required |
| `happy/claude-opus-4-5` | Line Edit primary; Polish fallback | Unknown | Unknown | Unknown | User evidence required |

No Alibaba, Anthropic, OpenAI or other vendor's public same-name price was substituted
for a Happy or Lingsuan proxy price.

## 2. Internal alias to actual provider/model mapping

Only two supplier boundaries are directly identifiable from the configured endpoint:

- `deepseek` reaches `api.deepseek.com`; the exact internal ID also exists in official
  DeepSeek documentation. Mapping is verified.
- `doubao` reaches `ark.cn-beijing.volces.com`; the supplier is Volcengine Ark.
  The Pro `260215` version is found in the official API Explorer, but the Character
  `260628` version was not closed by acceptable public evidence.

`happy` reaches a unified gateway and `lingsuan_gpt` / `lingsuan_sonnet` reach a
Lingsuan gateway. Their internal aliases do not prove the upstream supplier, upstream
model version, limits or account price. Those fields remain `unknown`.

## 3. Pricing evidence manifest

Accepted official sources and exact locator hashes are in the evidence matrix.

- DeepSeek Models & Pricing provides the exact `deepseek-v4-pro` capability and
  pricing schedule. For a candidate execution after 2026-08-16 16:00 UTC, the budget
  uses peak cache-miss rates: USD 1.32 per 1M input tokens and USD 3.96 per 1M output
  tokens. No cache hit is assumed.
- Volcengine's official price page provides Doubao Seed 2.0 Pro tiers: CNY 3.2/16,
  4.8/24, and 9.6/48 per 1M input/output tokens for the documented context bands.
- Volcengine's product page gives only generic Character-family starting prices. It
  does not exact-bind `doubao-seed-character-260628`; it is therefore insufficient.
- Happy's public page does not provide exact upstream/version/limits/account price.
- No acceptable public Lingsuan evidence was found for the configured aliases.

Unknown billing items are not assigned a zero value.

## 4. Capability evidence manifest

DeepSeek official material closes these fields for `deepseek-v4-pro`:

- exact ID and current version;
- 1,000,000-token context;
- 384,000-token maximum output;
- JSON Output, Tool Calls, Responses and Anthropic support.

For all proxy aliases, successful local capability probes prove only what was observed
through that route at that time. They do not prove the upstream model identity, stable
limits or billing contract. Two Lingsuan probe records also carry `route_changed` stale
reasons and cannot be treated as current supplier proof.

## 5. Unresolved evidence checklist

### User-supplied provider evidence

Provide a dated console export, contract page, billing schedule or screenshot from the
actual account for each listed route. Credentials and secret values must be redacted.

| Provider aliases | Exact material required | Blocks |
|---|---|---|
| `happy/qwen-3.7-plus`, `happy/qwen-max-thinking`, `happy/claude-opus-4-5` | Alias-to-upstream supplier and model/version mapping; protocol route; context/max output; structured/tool capability; input/output/cache/thinking/other prices; currency/unit/effective date; failed-call and retry billing | Draft, Polish, Line Edit primary/fallback; Production-Mirror Option A |
| `lingsuan_gpt/gpt-5.6-sol`, `lingsuan_sonnet/claude-sonnet-5` | Same fields, plus evidence applicable to the current route rather than the stale capability probe | Planning, Review, Final Review, Polish, Line Edit, Maintenance primary/fallback; Option A |
| `doubao-seed-character-260628` | Exact official console version record; context/max output; JSON/tool capability; full version-specific price schedule and billing semantics | Reader Review primary; Option A |
| `doubao-seed-2-0-pro-260215` | Exact official console capability/limit record and account billing semantics; public tiered price can remain supporting evidence | Reader Review fallback; Option A |
| `deepseek-v4-pro` account | Account-specific confirmation for failed calls, retries, cache accounting, thinking tokens and any surcharge/discount | Final cost-enforcement closure for Option B |

### Repository evidence or implementation required before approval

These cannot be supplied by a price screenshot:

1. an approved implementation phase must add a C0B real-provider launcher path; the
   current code at `tools/canary/launcher.py:63-68` requires C0A scope/mode, and
   `tools/canary/launcher.py:128` invokes only `run_c0a_dry_run`;
2. a deterministic derivation or instrumentation must prove maximum legal model call
   count across retry, fallback, regeneration and scoped repair;
3. the hard elapsed cap must be derived from the same transition graph and enforced;
4. a real usage/cost estimator must replace the zero default seen at
   `tools/canary/gate.py:142` for the C0B path;
5. budget and first-terminal stop tests must demonstrate fail-closed behavior without
   executing a paid call during the approval-building phase.

This report does not authorize or implement any of those changes.

## 6. Option A — Production-Mirror

Option A mirrors the current safe role graph, including every primary and fallback.
The config and route identity were hashed, but no executable Plan or Approval was
generated because the evidence matrix is incomplete.

| Identity | SHA-256 |
|---|---|
| Build | `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0` |
| Execution config | `ddcfe8d5ac317d708f9eb591759a29042b28b9accc3a6230c9bbf249e3f13639` |
| Runtime execution | `bb226eb81ca876d52f4cac70e75739f85a9609b61ce8ae4de07ab148ee7fb35b` |
| Provider descriptor manifest | `b93615e5c48a8673ca33c84ea06a17c335d642b8f3c959dff2e28238fb8af2dc` |
| Role binding manifest | `af762d9752768e2945212ac37c881652fb09cba343ea3f544385e9faac964f10` |

Decision: `NO_GO_MISSING_PROVIDER_EVIDENCE`.

## 7. Option B — Reduced-Risk

Option B rebinds all eight Short roles, in an isolated canary configuration only, to
direct `deepseek/deepseek-v4-pro` and disables fallback. No production route is changed.
This is deliberately **not** a production mirror.

The provider capability and public price schedule are verified. The generated Plan
and Approval Draft have exact hashes, but both are labeled non-executable because the
launcher, attempt cap, elapsed cap and account billing closure are incomplete.

Decision: `CANDIDATE_NON_EXECUTABLE`.

## 8. C0B-SMOKE-1 budget

The following is a conservative, reproducible candidate—not an approved exact budget.

| Field | Candidate | Exact for approval? |
|---|---:|---|
| Runs | 1 | Yes |
| Workload | `short-normal-v1` | Yes |
| C0A estimated input | 36,708 tokens | Yes as prior estimate, not a hard bound |
| Hard calls | 100 | **No**—legal attempt topology unproven |
| Hard input | 2,000,000 tokens | Candidate ceiling |
| Hard output | 2,000,000 tokens | Candidate ceiling |
| Worst-case price | USD 1.32/M cache-miss input + USD 3.96/M output | Official scheduled peak price |
| Worst-case formula | `2 * 1.32 + 2 * 3.96` | Reproducible |
| Maximum cost candidate | USD 10.56 | **Not approved**; account billing details open |
| Elapsed cap | 3,780 seconds | **No**—attempt topology/enforcement unproven |
| First terminal stop | `true` | Required but no real launcher enforcement yet |

Because calls and elapsed time are not exact, this section does not satisfy the C0B
approval gate even though the token arithmetic is reproducible.

## 9. C0B-PILOT-5 future draft

No five-run approval is issued. A purely arithmetic 5x example would be 500 candidate
calls, 10M input, 10M output and USD 52.80 at the same peak cache-miss schedule. It is
not a budget because four workload identities and their attempt/token/time bounds are
not defined. C0B-SMOKE-1 authority, if later granted and consumed, must not be extended
to C0B-PILOT-5.

## 10. Exact hash / fingerprint matrix

`c0b-p0-exact-hash-matrix.json` records Option A and Option B separately. Key Option B
candidate identities are:

| Identity | SHA-256 |
|---|---|
| Candidate Plan | `97cbebae95633250d0b1e17d7e5be806f394bb7b5f5f14cd448454d44fb44fac` |
| Candidate Approval Draft | `85ae2ee4ce9accea6ab62447c830d1ebb1545c877926605196e6be1517eb3514` |
| Launcher | `2f9a6e2c052f05ae811444de7772c5ca29afda9166dd8b8d60af85be61b5e3f1` |
| Workload manifest | `80a37d9270f7d0dc5f4260e391b0c53d4232c1abda4b859d8dbaf11a07a018ae` |
| Build | `bbf17ef072856d2c8bfc56281ce0469dc1ac323fcab6b2bde1c8ce08845253f0` |
| Execution config | `f7a13e99168f6dc2b0d75feede9b08b57545676d368ffd4e499ed6add4f3c659` |
| Runtime execution | `2791c5dc8d477f57152b1270dc8b2a6003d9910681a485873b4d6e0069ed7190` |
| Provider descriptor manifest | `e26569aea69bcd4819c71fdab210349aa1c0bd514f1abb623321503f98fb2e65` |
| Role binding manifest | `fbbb248b96b40147e6e3980b287bc2f7660cfcae08197b94d0cf75dddd7f23fb` |
| Isolation root identity | `2e8dd9e616a3264bd8f33919413585616704ed51c7771198ec48b9e3defa966f` |
| Stop conditions | `6110748fccad91a841b4b9715bc8ef0e3ec17874820c64344896d6cf9919dc31` |

C0A Fake Plan, Fake Approval, Fake provider descriptor and Fake route binding were not
reused. Build and Launcher identities were reused only after current bytes were
re-verified. Any candidate-field change requires rehashing.

## 11. New C0B Approval Packet Draft

Files:

- `c0b-smoke-1-canary-plan-candidate-non-executable.json`
- `c0b-smoke-1-approval-draft-non-executable.json`
- `c0b-p0-approval-packet-v2.json`

The schema-valid Approval Draft remains unused and all actions are false. The enclosing
packet includes every requested approval field, but clearly marks call/time limits as
non-exact, cost as candidate-only, approver as `null`, and consumption status as
`NOT_APPROVED_NOT_CONSUMABLE`.

No signature should be applied to this draft. Once all evidence and launcher/budget
gates close, generate a new Plan and Approval with a fresh window, cohort, hashes and
named approver.

## 12. User approval summary

There is currently nothing safe to approve for execution. To make a future packet
approvable, the user must provide the exact supplier/contract evidence listed above
and separately authorize an implementation phase for the C0B launcher/budget gate.
After those are verified, the user will need to review and sign a newly generated
single-use packet containing:

- exact Option A or Option B route choice;
- exact Plan/Launcher/Build/Config/Execution hashes;
- exact calls, tokens, currency, money and elapsed caps;
- a fresh UTC execution window and expiry;
- a named approver;
- explicit `true` values for credential lookup, provider client creation, network and
  paid model calls only if the user intends to execute C0B.

No such authorization is inferred from C0A or this report.

## 13. Final conclusion

### Verification record

- Candidate Plan and Approval Draft passed the existing
  `CanaryExperimentPlanV1` / `CanaryPlanApprovalV1` validators with embedded digest
  recomputation; time-window enforcement was intentionally disabled because this was
  an offline draft check, not an execution.
- Focused Canary/fingerprint tests: `51 passed, 1 skipped`.
- Full suite: `2485 passed, 2 skipped, 5 xfailed`; no failure.
- `git diff --check`: pass.
- Git status contains only the seven new files under `docs/superpowers/reports`.
- `src/novel_flywheel`, `baml_src`, and `tools/canary` diffs: empty.
- Current live `data/app.db` SHA-256 is
  `5deb7bdf811c90366ee1342de108c53355cea1c39aff72670bacd99cd5ffab87`;
  its last-write time remains `2026-08-12T16:12:48.1669180Z`, before C0B-P0 began.
  No live database/project mutation path was invoked. Because the pre-task external
  baseline file did not retain a usable tree snapshot, this report does not fabricate
  a new before/after combined parity claim.

### Decision

`C0B_PACKET_NO_GO_MISSING_EVIDENCE`

Exact gaps:

1. Happy and Lingsuan alias-to-upstream mapping, limits, capability and pricing;
2. exact Doubao Character evidence and remaining Doubao Pro capability/billing fields;
3. DeepSeek account-specific billing semantics;
4. C0B real-provider launcher path and non-zero cost enforcement;
5. exact legal call-count and elapsed-time derivation/enforcement;
6. named approver and explicit new external-action authorization.

Alternative: Option B can remove the unverified proxy/fallback routes, but it cannot
remove blockers 3–6 and cannot be executed by the present C0A-only launcher.

**C0B_PACKET_NO_GO_MISSING_EVIDENCE**
