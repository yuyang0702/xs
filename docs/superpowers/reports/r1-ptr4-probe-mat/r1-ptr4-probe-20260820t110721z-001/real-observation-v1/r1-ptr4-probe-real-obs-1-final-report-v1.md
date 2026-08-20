# R1-PTR4-PROBE-REAL-OBS-1 Final Report

Gate: `R1_PTR4_PROVIDER_CAPABILITY_PROBE_REAL_OBSERVATION_COMPLETE`

The fresh disabled single-use packet was bound to a Confirmed Authorization Patch and `ProviderCapabilityProbeSignedApprovalV1`. Signed validate-only was exact with all external counters at zero before dispatch. The authorized cohort was then reserved, executed exactly once, and terminally consumed.

## Execution identity

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Execution basis HEAD: `3a309990b65bde06aa58ee5177264c3bdecf11a2`
- Scope: `r1_ptr4_provider_capability_probe_1`
- Cohort: `r1-ptr4-probe-20260820t110721z-001`
- Window: `2026-08-20T11:22:21Z` to `2026-08-22T11:22:21Z`
- Reserved at: `2026-08-20T12:50:41Z`
- Executed/consumed at: `2026-08-20T12:53:30Z`
- Signed Approval SHA: `052b2253c078c65243805f9b021836eb12afe8e8a51cfd8dae3826f4e6713289`
- Execution Receipt SHA: `a0fb9fab1a99f64fc57ecdc362c490eb308259f3268f9ee2ef499b22b904f82c`
- Observation Receipt SHA: `665fa85e163e5f7b6cdf4b0b449533a581ba509c6c8e3cf3a3cf7a06617f1bb0`

## Real observation

The exact Boundary 12 configured-fallback request produced one pre-normalization content block with type `thinking`. The Provider terminated with `finish_reason=max_tokens` at 8,798 output tokens, exactly the requested maximum. There were zero text blocks, zero visible characters, zero tool calls, zero tool-argument bytes, one reasoning block, and zero unknown blocks. The controlled classifier is `REASONING_ONLY`.

Post-adapter visible text remained absent with zero characters and no tool arguments. The parser boundary was reached, while JSON conversion, wire-schema validation, and semantic validation were not reached successfully. This observation shows that the zero-visible terminal shape already existed before adapter normalization; no adapter content-loss hypothesis is needed for this exact response.

Provider raw content-block shape for this exact Boundary 12 probe is therefore no longer unknown: `thinking-only + max_tokens + zero-visible`. This is capability evidence, not a Production Fix and not proof that every future response will have the same shape.

## Budget and stop conditions

- Runs/model calls/network calls/paid calls: `1 / 1 / 1 / 1`
- Credential lookups/Provider client creations: `1 / 1`
- Input/output tokens reported: `29 / 8798`
- Actual cost: `USD 0.034879` (`34,879` microunits), within the `USD 5` cap
- Elapsed: `162.86` seconds, within the `1,800` second cap
- Retry: `false`
- Resume: `false`
- Second run: `false`
- Live parity: `exact`

## Verification

- PTR4 targeted suites: `39 passed`
- Python compile: passed
- Strict L3 change gate: `ok=true`, no warnings or blockers
- Full suite: first failure after `261 passed` is the unrelated historical C0B `approval_expired` clock-sensitive test; the expired authorization was not modified or re-dated
- Production diff: none
- `src/novel_flywheel/**`: unchanged
- `baml_src/**`: unchanged
- Privacy scan: pass; no raw Prompt, story, tool arguments, Provider content, credentials, or headers persisted

## Required terminal declarations

`REAL_PROVIDER_PROBE=EXECUTED_ONCE`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`PRODUCTION_FIX=NOT_IMPLEMENTED`

The cohort is consumed. No further probe, retry, resume, Full Short, Draft/Review/Maintenance, or Production Fix was executed.
