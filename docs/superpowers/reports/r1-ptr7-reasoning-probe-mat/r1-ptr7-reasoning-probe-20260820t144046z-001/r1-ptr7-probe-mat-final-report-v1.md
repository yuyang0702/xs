# R1-PTR7 — Provider Reasoning Capability Probe Materialization

`R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_APPROVAL_PACKET_READY`

`R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION`

## Evidence gate

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Source HEAD: `941b1fbf9a2e9d361098e69baedfaf01c3425f6c`
- Starting worktree: clean
- PTR4 base/V1, PTR4 real observation, PTR5 and PTR6 manifests: exact
- `src/**`: unchanged
- `baml_src/**`: unchanged
- Production diff: 0
- Live parity: exact (`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`)

## Fresh packet

- Cohort: `r1-ptr7-reasoning-probe-20260820t144046z-001`
- Window: `2026-08-20T14:40:46Z` to `2026-08-22T14:40:46Z`
- Approval scope: `provider_reasoning_capability_probe`
- Candidate: disabled, unused, unreserved
- Signed Approval: absent
- Confirmed Patch: absent
- Ledger: isolated, unreserved, zero entries
- Canary root: isolated and unused
- Validate-only: exact

## Bound target

- Provider identity: `98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6`
- Route identity: `31adb8879560c60a09db4c0955237480ab836f153ff97515fc5911e9fe1d8d34`
- Route kind: `configured_fallback`
- Model identity: `fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998`
- Protocol: `anthropic`
- Parent contract identity: `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`

No Provider or model substitution is permitted.

## Capabilities under test

1. `reasoning_budget_cap`
2. `final_output_reservation`
3. `reasoning_output_token_separation`
4. `capability_bound_output_allocation`

The fixture is a non-business deterministic checksum recipe. It does not run Planning, Draft, Final Review, Maintenance, Full Short, or any production workflow. Raw Prompt, story, tool arguments and Provider content are absent from the packet.

Classification is fail closed:

- `SUPPORTED`: the parameter is accepted, enforcement is observable, reasoning stays within the requested cap, and a final artifact appears inside the unchanged total cap. Token separation must be reported before that specific capability can be supported.
- `UNSUPPORTED`: the parameter is rejected or capability is explicitly unavailable.
- `IGNORED`: the parameter is accepted but the cap is observably exceeded or reasoning-only `max_tokens` repeats.
- `UNKNOWN`: acceptance occurs without observable enforcement or separate reasoning/final token accounting.

Parameter acceptance alone never means supported.

## Budget and stop conditions

- Maximum runs: 1
- Maximum model calls: 1
- Maximum input tokens: 128,000
- Maximum output tokens: 16,000
- Maximum output tokens per call: 16,000
- Requested reasoning cap: 8,000
- Requested final reserve: 8,000
- Maximum cost: USD 5 / CNY 10
- Maximum elapsed: 1,800 seconds
- First terminal stop: true
- Retry/resume/second run: false
- Provider switch/model substitution: false

## Hashes

- Probe Definition: `b871900490c55b18de33376e24e09483b2f852e7988e80656efc97e7986bda44`
- Fixture: `15d87e12050cda4c9718b62e1234c9e50aa158f439b4c592827d5847498f404e`
- Observer Definition: `b48e877ac61d3fe7be6bb743a09d98787e4ce89f14e1830ff50539afd234cf07`
- Candidate: `fdf28472be5db33aca26933175d02b2439abaf66aeb105216c253d54d542b979`
- Patch Template: `feaf8e71f38081e5976c1274a789836dad3e450efb17aacbe43033c6edad34db`
- Validate-only: `ebb5721f5502cba87a20da9230611915f51fd59b45d6fe5b862ab4f1d69be968`
- Materialization Index: `9b6ef7b2905340b2fb843ec73c68e15911b8393d7ee86cea77c0c224a88d8646`

## Verification

- Focused offline tests: 12 passed
- Related PTR4/PTR7 canary tests: 42 passed
- Fake prelaunch: exact; all four classifications covered
- Privacy: exact, zero violations
- External actions: credential=0, provider_client=0, network=0, model=0, paid=0

`REAL_PROVIDER_PROBE=NOT_EXECUTED`

`PRODUCTION_FIX=NOT_IMPLEMENTED`

`FULL_SHORT_CANARY=NOT_EXECUTED`
