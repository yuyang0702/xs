# R1-PTR4-V1 — Provider Capability Probe Contract Completion

## Final Gate

`R1_PTR4_V1_PROBE_CONTRACT_READY`

This gate means only that the Canary-only observation contract, hash-bound fixture descriptor, offline shape classifier, privacy controls, and evidence bindings are ready. It does not mean that Provider capability evidence has been collected or that the production root cause is closed.

## Repository identity

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Starting HEAD: `b7d3f5c9c724e2ec6a02fab0c9acc9ab6777c921`
- Starting worktree: clean
- Parent R1-PTR4 evidence canonical SHA-256: `e7806b206edbdddf21a1ea74c7d0ebbb327ccedf7216f528c281c4ac2edfdf4c`
- Parent evidence validation: exact
- Parent privacy validation: exact, zero violations

The sealed final report, boundary reconstruction, root-cause decision, evidence-availability record, SHA manifest, and privacy scan were read and rebound. The parent manifest independently recalculates to the canonical SHA above.

## Contract artifacts

- Probe Definition SHA: `6f201a3687d46d7be83f7c9797b03b26abdd346cc897f0f1ef87f0ab57ae5aee`
- Fixture SHA: `22ac37e6494de79f542596cd16d5c14b8b25229af5cc1f451957e101b1c87e64`
- Observer schema SHA: `d88652767f2d5fe72fce529cdc51c51e7897daa9b16fd869092aa20b30d7dfa3`
- Observer schema bundle SHA: `5cd49aea924877d123ed48a054c0805bfd8604b0e2cd2443d8a7cd00a7494c3a`

The fixture does not embed or guess a prompt. It references `tests/fixtures/canary/short-normal-v1.json` at sealed SHA `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1` and requires any future request reassembly to match the sealed system, user, contract, wire-schema, and tool-schema hashes. If the source is absent or differs, construction fails with `R1_PTR4_V1_PROBE_FIXTURE_NOT_AVAILABLE`.

## Boundary 12 and Provider identity binding

- Boundary: 12
- Role/stage: Planning / `planning`
- Substage: `planning-semantic-v2-segment-01-packet-000001-0`
- Semantic scope: `nested_semantic_packet`
- Contract: `planning_semantic_v2` v2
- Contract SHA: `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`
- Route: `configured_fallback`, attempt 2
- Protocol: `anthropic`
- Execution mode: `plain`
- Requested/local effective max output: 8798 / 8798
- Effective Provider max output: UNKNOWN
- Provider descriptor hash: `98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6`
- Model binding hash: `fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998`
- Boundary identity SHA: `851b447afba31d2296ebafc223ea4189464920e332693a5a03d5cf0b821675f0`

Provider/model identity is stored only as hashes. Raw Prompt, story content, tool arguments, and Provider content are never stored by this contract.

## Observer coverage

Pre-normalization records only typed/hash/shape/count metadata: provider/model hashes, route/protocol, finish reason, output tokens, requested/effective maximum output, block count and controlled type sequence, text/tool/reasoning/unknown counts, visible characters, tool-argument presence and length, partial-tool count, zero-visible, empty-content, and max-tokens status.

Post-adapter records only visible-text presence/count, tool-argument presence, parser/strict-tool/JSON/wire-schema/semantic-validation reachability, a typed output-limit classification, and a lineage receipt hash.

Offline classifications cover `TOOL_ONLY`, `TEXT_TRUNCATED`, `REASONING_ONLY`, `ZERO_VISIBLE_MAX_TOKENS`, `ADAPTER_VISIBLE_CONTENT_LOSS`, `MIXED_BLOCK_TRUNCATION`, `UNKNOWN`, and `TOOL_ARGUMENTS_TRUNCATED`. Unknown block labels are replaced by domain-separated hashes; no raw unknown label is emitted.

## Behavior unchanged proof

- Prompt unchanged: exact
- Route unchanged: exact
- Model unchanged: exact
- Retry unchanged: exact
- Fallback unchanged: exact
- Output budget unchanged: exact
- Validator unchanged: exact
- `src/novel_flywheel/**` production diff: 0 files
- `baml_src/**` diff: 0 files
- Production runtime behavior changed: false
- Live parity before/after: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` / same

The observer uses only the Python standard library plus existing project modules, preserving the established Canary launcher import closure.

## Offline verification

- Focused contract suite: 15 passed, 0 failed
- Related planning/provider/canary regression suite: 62 passed, 2 skipped, 0 failed
- Full repository suite: 261 passed, then stopped at one pre-existing clock-sensitive historical approval fixture with `approval_expired`
- Novel Development Council strict change gate: passed, 0 warnings, 0 blockers
- Privacy: exact, 0 violations
- External actions: credential lookups 0; Provider clients 0; network calls 0; model calls 0; paid model calls 0

The full-suite failure is `tests/canary/test_c0b_p12_signed_approval.py::test_candidate_and_patch_remain_non_executable`. Its historical signed-approval candidate is expired under the current clock. It is outside this task's allowed paths and was deliberately not renewed, re-dated, or modified. The failure is not attributable to this Canary-only contract change.

## Preserved root-cause status

- Boundary 1 ConnectError later recovered and is not the primary root cause.
- Boundary 3 `semantic_validation_failed` remains the first unrecovered divergence.
- Sticky output-limit remains the terminal amplifier.
- Boundary 12 remains the configured fallback max-token boundary.
- Provider raw content-block shape remains UNKNOWN.
- The historical root cause is not declared closed by this task.

## Files changed

- `tools/canary/provider_capability_probe_contract.py`
- `tests/canary/test_provider_capability_probe_contract.py`
- `docs/superpowers/reports/r1-ptr4-v1/provider-capability-probe-definition-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/provider-capability-probe-fixture-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/provider-capability-probe-observer-schema-identity-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-behavior-unchanged-proof-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-forward-risk-v2.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-offline-test-receipt-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-privacy-scan-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-sha256-manifest-v1.json`
- `docs/superpowers/reports/r1-ptr4-v1/r1-ptr4-v1-final-report-v1.md`

## Explicit stop state

`REAL_PROVIDER_PROBE = NOT_EXECUTED`

`FULL_SHORT_CANARY = NOT_EXECUTED`

`PRODUCTION_FIX = NOT_IMPLEMENTED`

`SIGNED_APPROVAL = ABSENT`

`NEW_SINGLE_USE_APPROVAL_REQUIRED = YES`

No credentials were read, no Provider client was created, no network/model/paid action occurred, and no Probe or Short was executed. Work stops at this inert contract-completion gate.
