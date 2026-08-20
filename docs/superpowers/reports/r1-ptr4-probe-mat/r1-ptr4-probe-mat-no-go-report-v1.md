# R1-PTR4-PROBE-MAT — Materialization NO-GO

## Final Gate

`R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE`

No executable approval packet was materialized. Parent evidence and the hash-only Boundary 12 identity are exact, but the formal probe definition does not contain an executable sanitized fixture or deterministic request derivation. Creating one here would invent probe semantics, which the request explicitly forbids.

A second fail-closed constraint confirms that a READY packet would be dishonest: the reusable `ProviderContentBlockShapeSnapshotV1` schema fixes `substage=planning_repair_patch`, and its capture gate requires the `planning_repair_patch` v1 target. Boundary 12 is `planning_semantic_v2` v2. Reusing that observer unchanged would record a false target; making it represent Boundary 12 requires separately authorized production observability work outside this materialization pass.

## Required report fields

| # | Field | Result |
|---:|---|---|
| 1 | Branch | `r1-ptr3/planning-repair-finding-propagation-20260817` |
| 2 | Starting HEAD / parent evidence commit | `ddcc0965ba8cbf6accb932d8898a77232ee8a13c` |
| 3 | Evidence commit | commit containing this report; final response supplies the immutable hash |
| 4 | Exact files changed | four NO-GO evidence files under `docs/superpowers/reports/r1-ptr4-probe-mat/**` |
| 5 | Production source diff | `0` |
| 6 | PTR4 parent evidence | exact; manifest mismatch `0`; privacy violations `0` |
| 7 | Formal probe definition SHA | `7833ef2a448830056ecea2969c5b595f86157b8764ec3adb2cca9ece74828636` |
| 8 | Target Boundary | `12`, identity SHA `b3680d9e9949016ad4ab01446ddfbbfa0b6ec4df8cc60a95384f1edd35941357` |
| 9 | Role/stage/substage | `planning` / `planning` / `planning-semantic-v2-segment-01-packet-000001-0` |
| 10 | Contract | `planning_semantic_v2` v2; SHA `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7` |
| 11 | Provider/protocol/model | descriptor `98190f8a…05a6`; `anthropic`; binding `fa876d17…0998` |
| 12 | Route kind | explicit `configured_fallback`; historical route attempt 2 |
| 13 | Request/tool schema | wire schema SHA `6098e362b6370cbb0d63710f56f355561af549188e1eeaa5d267862f290c95be`; tool/required-tool absent in plain mode |
| 14 | Adapter identity | `AnthropicAdapter`, diagnostic id `anthropic`, version 1; source SHA `7786c0ae46ceeaced450a4d30a09a4c669969bff2be61ca88a6231f36ec4ecf5` |
| 15 | Parser identity | `novel_flywheel.model_output.parse_json_object`; source SHA `37d7af8aa7402fab0afe7ea900f5918982ff63629cfd5b9c03cc62be1946c043` |
| 16 | Strict-tool path | not reached; execution mode `plain` |
| 17 | Observer definition | `ProviderContentBlockShapeSnapshotV1`; schema SHA `3a4582e2ce6dbefa67bd6af4a922704fe963783c8b74faebbea7670e7784db83`; incompatible target literal |
| 18 | Adapter-lineage definition | not executable for Boundary 12; no exact existing receipt contract |
| 19 | Probe fixture/input SHA | absent; blocker |
| 20 | Probe success definition | provider block shape plus adapter/parser loss classification after one natural response; defined semantically, not executable without input |
| 21 | Outer budget | formal contract is stricter than supplied caps: exactly one Provider/model/network/paid call; no retry/expansion/resume/second run |
| 22 | Plan SHA | absent |
| 23 | Candidate SHA | absent |
| 24 | Patch Template SHA | absent |
| 25 | Validate-only Receipt SHA | absent; `overall_status=exact` was not and cannot be asserted |
| 26 | Execution Preview SHA | absent |
| 27 | Materialization Index SHA | absent |
| 28 | Cohort | not allocated |
| 29 | Execution window | not allocated |
| 30 | Ledger identity/path/entry count | not created / not created / `0` |
| 31 | Canary root | not created |
| 32 | Pre-launch Rehearsal SHA | absent; fake rehearsal not executed because the executable observer/input contract is incomplete |
| 33 | Privacy/live parity | privacy scan exact, violations `0`; live parity `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` exact |
| 34 | External counters | credential/provider-client/network/model/paid = `0/0/0/0/0` |
| 35 | Tests | focused offline suite: `135 passed, 2 skipped`; initial invalid test path ran no tests and caused no action |
| 36 | Final Gate | `R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE` |

## Parent and target evidence

The PTR4 manifest canonical SHA recomputes to `e7806b206edbdddf21a1ea74c7d0ebbb327ccedf7216f528c281c4ac2edfdf4c`, with no file mismatch. Its privacy scan is exact with zero violations. The root-cause Gate remains `R1_PTR4_PROVIDER_CAPABILITY_EVIDENCE_REQUIRED`.

Boundary 12 is uniquely hash-bound as configured fallback, protocol `anthropic`, execution mode `plain`, local requested/effective output budget `8,798`, `finish_reason=max_tokens`, adapter-visible characters `0`, parser reached, strict tool not reached, and Provider shape `UNKNOWN`. The Provider effective maximum remains unknown.

## Why materialization stopped

The parent contract says to use “production Planning request assembly with sanitized isomorphic authority/payload proportions matching the nested packet.” It supplies the historical nested-packet input hash and system/user hashes, but no sanitized fixture bytes, no fixture SHA, no derivation version, and no deterministic assembly input. Repository search found no fixture bound to the PTR4 nested-packet input SHA or the formal probe contract. Hashes prove identity but cannot reconstruct input content.

The exact typed observer is also target-restricted. `safe_capture_provider_content_block_snapshot` returns no snapshot unless the active diagnostic context is Planning `planning_repair_patch` v1, while Boundary 12 is `planning_semantic_v2` v2. A canary wrapper that invents a repair context, monkeypatches the Provider response, or classifies `provider_state` with a new ad-hoc schema would violate the requested target and observability rules.

To unblock a future materialization, a separately reviewed task must supply both:

1. A committed or private hash-bound sanitized isomorphic fixture plus deterministic derivation/version and exact request assembly contract.
2. An authorized observer/adapter-lineage contract that can truthfully capture `planning_semantic_v2` before and after adapter normalization without changing Prompt, Route/Model, budget, parser semantics, or Provider response.

No Plan, Candidate, Authorization Patch Template, Validate-only Receipt, Execution Preview, Materialization Index, Cohort, window, Ledger, Canary root, or fake rehearsal was created. In particular:

`REAL_PROVIDER_PROBE=NOT_EXECUTED`

`PROVIDER_CAPABILITY_EVIDENCE=NOT_EXECUTED`

`SIGNED_APPROVAL=ABSENT`

`CONFIRMED_PATCH=ABSENT`

`PRODUCTION_FIX=NOT_IMPLEMENTED`

`EXTERNAL_ACTIONS=0`

`R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE`
