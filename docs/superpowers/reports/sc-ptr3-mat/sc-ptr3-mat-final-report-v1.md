# SC-PTR3-MAT Final Report V1

## Outcome

- Gate: `SHORT_COMPLETION_PTR3_APPROVAL_PACKET_READY`
- Next state: `SHORT_COMPLETION_CANARY_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`
- `REAL_PROVIDER_CALLS=0`
- `FULL_SHORT_CANARY=NOT_EXECUTED`
- `SIGNED_APPROVAL=ABSENT`
- `CONFIRMED_PATCH=ABSENT`
- `NEW_SINGLE_USE_APPROVAL_REQUIRED=YES`

## 1. Branch, HEAD, and commits

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Parent evidence HEAD: `ab458a016caaed2148432c8c67b27734c61fe3ed`
- Successor binding implementation: `5d528f1b4d59929955a2ec2bbfb2f9509ed8beca`
- Independent rehearsal: `b478a153424650154ac4d6d692693793a365e5bc`
- Packet materialization: `54c545f5cbba5c2530480d5fd3536664072699df`
- Report/evidence commit is intentionally recorded by Git after this report is created.

## 2. Canary-only diff

The implementation changes only `tools/canary/**`, `tests/canary/**`, and `docs/**`. There is no change under `src/**` or `baml_src/**`. Historical R1-D3 evidence, prior SC packets, PTR2 packets, and consumed cohorts were not rewritten. The materializer now resolves current state through the hash-bound PTR3 protected-source successor instead of requiring current source bytes to equal the historical sealed R1-D3 manifest.

## 3. PTR3 parent evidence status

`exact`. Evidence commit `ab458a016caaed2148432c8c67b27734c61fe3ed`; successor baseline `bcba49fe1b20f1b4cb1f9284b181ede224bb860ce367870e9f3c46152cedda6c`; report `8ec3607d3072defdd18f3bf74fdcd601f5eacfcf57eed68f7daff9bcef864664`; test receipt `c5d118b4e7545822cfdbe1afad7a6b83b7f8b6817af68c62bcd1f461639d46af`.

## 4–16. Collected identities

| Item | SHA-256 / status |
|---|---|
| Production Build | `e97060b725a6978f7770c18ec4feb46dd88dc326609355a19d24a1741bcc8bf6` |
| Execution Config semantic | `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b` |
| Runtime Execution | `47c4806b9dd97baac1f982e90481f5ad491f89acad33c23d0408c1d946549f60` |
| Launcher | `0eda89a41138ed8996999b1e57b58b8ee03bc1a862ff50f1c1281840a8415faa` |
| Prompt Policy | `c341eb13abace08e1f658b1aa1be728de71a5ffc3d32991e493e43ef35fdfabe` |
| Planning initial request | `fc1836df086e66b86e4d4c0cfe3c554b53d51fc012f405da2fa3cd8bc94b6c3d` |
| Planning first repair request | `00c48c9f2269ed7eb1625755c5fd621669988731e2f2ee2ed0d726b03e3e1b89` |
| Planning retry-after-domain-failure contract | `a12c2ad5512371e205a0b63ba1190329ee204a204a3c52462b8b4565e51fe94e` |
| PTR3 readiness | `efe2ab7808905d74ca4212e3b8db0646f3c0252f55ac2449d6ef2261e391f943` (`exact`) |
| R1-D3 successor readiness | `63c35701c9edc960010874d4d4f4e13d257561461e007bbdbe0735d5048e6fcc` (`exact`) |
| Planning Domain validator | `949715c9d33f553db9949357cfa78b9fdfc6f7a0c94bff907e9fdf30ca69344f` |
| Draft validator | `7e9f52cf3c5600423c6abe63a7de6d8449db81bfcd7260585da5d8b59e22fdac` |
| Mixed-script policy | `11c8a15e84c7c76154b60b047f9048468c93d60ee6c383b5b66dadd2c1066d1d` |
| PTR3 finding contract | `e4c016c5b6fc78093f5842dea1879192da3557c872277abcb38f21af11bb1071` |
| PTR3 finding bounds policy | `ada8f3fde14da93567e76a13d0411cf532e6d7118b981d0ca41af788797eb140` |
| Draft retry-only contract | `d86985951d9518cf9512c83591b62a1e6b9b11478d562b4e378a1cf30bcfe03f` |

Observer behavior is enabled only through the approved diagnostic flags: `NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1=true` and `NOVEL_RELIABILITY_TRACE=true`. PA output-budget lineage, strict-tool trace, Short Canonical V2, project Short Canonical V2, and Phase 1B remain false.

## 17–22. Fresh packet objects

| Object | Canonical identity / status |
|---|---|
| Final Plan | `516149d6b9335810a31a0964aabaa73cb02477370ad2d9995ac86be659ad39f4` |
| Final Approval Candidate | `447392d2c0f822067be93438f76a608d815dce88f7ef1fe9e68eaccc79ca46d4` |
| Authorization Patch Template | `60fa7025358d2d217c86e8e98b6356469659375a5adfbd9cd8332c875a3e301c`; template only |
| Validate-only Receipt | `4d16c0ae22d3ea808339588fca30c094d1fffd11c85d9ee75859d3754e8c7bd5`; `overall_status=exact` |
| Execution Preview | inert; `execution_performed=false` |
| Materialization Index | `c5ed4f9f43fda277c839367d00325c61ff4a2754b5d436af8344a97080f7b89e` |

All objects are under `docs/superpowers/reports/sc-ptr3-mat/materialization-v1/`.

## 23–28. Single-use state and rehearsal

- Cohort: `short-completion-ptr3-20260817t091500z-002`; unused.
- Execution window: `2026-08-17T08:53:52Z` through `2026-08-19T08:53:52Z`.
- Ledger identity: `1ec2bbb0aad905caa44b4049d6da902bfb25069aeefae6c794783ad2b4fecb6c`.
- Ledger identity definition/path binding: `18f49680f3c8c912eba1778c02f4fd855fdf8d821b65360551c2fb6812bdad9b`; initial entry count `0`; approval `unreserved`.
- Canary stable root identity: `956b434d1b5591569fa52fbf3d520fc0ca6c53b0588da84581d83e78bf62c078`.
- Pre-launch rehearsal: `aa049a6dd11fa3d96472d04a5a57ddfb3600dc53fb3c19f3895ee0ef9b9cdab1`; independent subprocess; fake boundary count `2`; status `exact`.
- Planning fake sequence: `domain_rejected -> exact_finding_propagated -> domain_passed`; stale findings `0`.
- Draft fake sequence: `mixed_script_rejected -> exact_finding_propagated -> draft_validation_passed`; stale findings `0`.
- Candidate: `execution_authorized=false`, `named_approver=USER_CONFIRMATION_REQUIRED`, `usage_status=unused`; Signed Approval and Confirmed Patch are absent.

## 29. Budgets

- Runs `1`; expected calls `16`; maximum total model calls `48`.
- Input tokens `1,000,000`; output tokens `1,000,000`; per-call output `32,000`.
- USD `20.00`; CNY `50.00`; elapsed `7,200` seconds.
- `first_terminal_stop=true`, `resume_after_terminal=false`, `second_run_allowed=false`.

## 30. Semantic parity

Prompt/request, Route/model, retry/fallback, and production output budget are all `exact`. The independent subprocess produced the same Config semantic and Runtime Execution identities as materialization. Existing Planning and Draft retry caps were not changed.

## 31. Tests

- Focused predecessor set: `63 passed`.
- Materializer and independent semantic rehearsal: `25 passed`.
- Final combined focused/related suite: `233 passed`.
- Full suite: `2910 passed, 41 skipped, 6 xfailed, 4 failed, 0 errors` in `1611.24s`.
- The four failures are all permitted pre-existing families: two historical approval-window expirations, one historical R1-D3 sealed-manifest fail-closed mismatch, and one stale R0 live DB oracle. No new failure or error family was introduced.

## 32. Privacy

`exact`, violation count `0`. The packet and report contain hashes, shapes, counts, typed outcomes, and controlled aliases only. No Prompt/story/tool-argument/provider-response original text, credentials, Headers, project names, character names, or absolute paths were materialized.

## 33. Live parity

Before and after observation SHA are both `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`. Live DB SHA remains `0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`. No live DB, project, StoryState, Canon, Candidate, Checkpoint, Saga, or production incident counter was changed.

## 34. Known residuals

- Historical Call 7 original Domain failure primary root cause remains unclosed.
- Historical Call 9/10 terminal-amplifier shape remains unclosed.
- `planning.repair_scope_mutation_not_proven` remains residual.
- Provider hidden ceiling / zero-visible output-limit remains unclosed.
- R1-D3 real Draft retry convergence has not been observed with a real Provider.
- `draft.retry_scope_too_broad` remains residual.
- The fresh Planning and Draft paths were rehearsed with deterministic fake boundaries, not production exposure.

## 35. External counters

Credential lookups `0`; Provider clients `0`; network calls `0`; model calls `0`; paid model calls `0`. No execution was performed.

## 36. Final Gate

`SHORT_COMPLETION_PTR3_APPROVAL_PACKET_READY`

`SHORT_COMPLETION_CANARY_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION`

This gate authorizes no execution. A new single-use final user authorization is required before any Signed Approval can be materialized; this task stops here.
