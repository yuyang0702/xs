# R1-PTR7 — Provider Reasoning Capability Probe Final Report

`R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_EXECUTION_TERMINAL`

## Result

- Classification: `IGNORED`
- The Provider accepted the reasoning-control request at the protocol boundary (`2xx`), but the sealed behavior-level success contract was not met.
- The response again ended `max_tokens` with `16000` output tokens, one thinking block, zero final-text blocks, zero tool blocks, and zero visible characters.
- The requested reasoning cap was `8000`; the requested final reservation was `8000`. No final artifact was emitted.
- Separate reasoning/final token accounting was not reported, so `reasoning_output_token_separation=UNKNOWN`.

Capability classification:

- `reasoning_budget_cap=IGNORED`
- `final_output_reservation=IGNORED`
- `reasoning_output_token_separation=UNKNOWN`
- `capability_bound_output_allocation=IGNORED`

Under the sealed rules, parameter acceptance alone is not support. The repeated reasoning-only `max_tokens` outcome despite the requested reservation classifies the allocation control as `IGNORED`; no production change is inferred or implemented.

## Authorization and identity

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Pre-execution HEAD: `a234201917abac9e6ca68c00c0be3b77538571b2`
- Cohort: `r1-ptr7-reasoning-probe-20260820t144046z-001`
- Confirmed Patch SHA: `73ef6cbba6137a17e2cab29cfef627a4e08da9049b1470bdf795e6ddcd4ca789`
- Signed Approval SHA: `05fe2697031996e376d5922609e6c2daa6f6621cc087e3d3b4b9a39945d413ef`
- Signed validate-only SHA: `a7ca149d660fd60dad470ca52ddbc2f9018b1bfa67eba433d96e00c5e6298174`
- Observation SHA: `4c450c36ce203a718dc16475a78d6a5871f7e4cd0ed383888e34488cdb7c1fba`
- Execution receipt SHA: `ffa0c405a50e6a91f6d5685788d7003da8bdeec1f5d6b2c78dd9210f5980af99`
- Consumption receipt SHA: `83b5f4698b029d86d19bdbba6433215b4759fe96af54706b0835007ea46df7a8`

Provider/route/model identities remained the exact packet-bound hashes. Live parity was exact before and after the request: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.

## Budget and execution

- Runs: `1/1`
- Model calls: `1/1`
- Input tokens: `1690/128000`
- Output tokens: `16000/16000`
- Actual cost: `USD 0.065591` (cap `USD 5`)
- Elapsed: `146.407s/1800s`
- Credential lookup / Provider client / network / model / paid counters: `1/1/1/1/1`
- Retry: `false`
- Resume: `false`
- Second probe: `false`
- Ledger: `consumed`; offline replay check returned `operational_ledger_not_unused`

## Verification and privacy

- Focused and related offline tests: `30 passed`
- L3 strict change gate: passed
- Production diff: `0`
- `src/**` and `baml_src/**`: unchanged
- Prompt, Model, Route, Retry, Budget, and validators: unchanged
- Privacy scan: exact; raw Prompt, story, tool arguments, Provider content, credential, endpoint, headers, and Provider error text absent

`REAL_PROVIDER_PROBE=EXECUTED_ONCE`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`PRODUCTION_FIX=NOT_IMPLEMENTED`
