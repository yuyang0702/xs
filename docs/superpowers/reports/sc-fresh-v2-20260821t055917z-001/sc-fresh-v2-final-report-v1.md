# SC-FRESH-V2 — Fresh Short Completion Canary Materialization Final Report

## Result

`SC_FRESH_SHORT_COMPLETION_APPROVAL_PACKET_READY`

`SHORT_COMPLETION_CANARY_WAITING_FOR_FINAL_USER_AUTHORIZATION`

One fresh, disabled, unused, single-use `short_completion_1` approval packet was materialized and validated offline. No Signed Approval or Confirmed Patch was generated, no ledger entry was reserved or consumed, and no real Provider, network, model, paid, or Full Short action occurred.

## Git and scope

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Sealed HEAD: `14cc675a1d510550fca18104afaf3aa9e7f18878`
- Direct parent: `d8fc9f4ddb13375c7c3d70c7d5adbdfed5298fc9`
- Start worktree: clean
- Production source diff: 0
- BAML diff: 0
- End worktree: only this unsealed fresh packet directory is untracked
- Packet seal required before final authorization: yes

## Packet identity

- Profile: `short_completion_1`
- Scope: `SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY`
- Goal: `SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED`
- Cohort: `short-completion-fresh-v2-20260821t055917z-001`
- Window: `2026-08-21T06:14:17Z` to `2026-08-23T06:14:17Z` (UTC)
- Expiry semantics: approval is valid only inside the bound window; the cohort is single-use and cannot resume or run a second time after terminal consumption.
- Canary root identity: `c230e6e1b7bf023a0a2aacdea590792f5b75aa0e7db8933431cd571df260dde8`
- Ledger identity: `35dc1a0bf347a7ec1d9b20b1f360e22b2f21dad880bbdecf6c27e675b1ccaf9f`
- Ledger state: unused, unreserved, entry count 0

## Core SHA bindings

- Plan: `d32ee3b1a8829bb2cf746af54aa2a1c0d021f3b4697a1c862d946298f8de4661`
- Candidate / Approval Request: `cbc09b8794c213e7633f2498cf80903042ef6b13675244190f99640c97869648`
- Authorization Patch Template: `f41ee0b7fe7b48d7675c948804fd587cd8f25023ca2ed0228e1d05c7ecbd1863`
- Validate-only Receipt: `3f368655a2a6d925f87a010a34ae22918e454ee61f4c26e8a00007f637ac64b7`
- Execution Preview: `603268a61f12f5315bb2b35c30dd1388bcf6b375a21785bad3f970501e14d6ab`
- Materialization Index: `6cc17b82e9abd42739303ded4c92e15bda7723eeeddd8856b5a2fd55398363cd`
- PTR3 readiness: `8006f1dc0837ba3511bd9c35571a153d97c23035a590cd810ce01d5c13a5c1c6`
- R1-D3 readiness: `2743e658019939fddfdfb9df043b6fc9f3d682bfeff8ffd41a4d806929d838d2`
- Pre-launch rehearsal: `a2db9d82e8b992dec98c537bb920b2172776985cbb4b781e1a15f3fe3ee77644`

## Runtime and lineage

- Build: `38ac099757dba906bcbe7d523fe2dd3f664193f2b5ffd3ecae559a17fdedcce4`
- Config: `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`
- Runtime: `3a3c8ec80924c2124cd84b745c1d9d2972c9dad2c48351a9f5b6d8044e75d68c`
- Launcher: `2f1ce61883d32cbc46c4d90a9cfbdaddeffdfbd293ec36658d012a25f38f1678`
- Prompt Policy: `82f73e6e9e90788feaa9cea0726e71a239960bead2b0c953ce5517e652dc736a`
- Provider descriptor definition: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`
- Route/model binding manifest: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`
- PTR9 `REASONING_ONLY_MAX_TOKENS_GUARD_V1`: bound exact
- PTR10 guard recovery validation: bound exact
- SC-IC1 `PROBE_MODULE_IMPORT_ISOLATION_V1`: exact
- SC-SUCC1 successor SHA: `4f4b02055f6f1902701d78e4ef478cf554645127f501ce271b8cc9366b425a1a`
- SC-SUCC1 definition SHA: `07341e86e4ab78217cb5efe19bc0ce5d369f35fe4eaa0d0d921e3202f188ecea`
- Historical PTR3 evidence: exact and immutable

## Budget envelope

- Maximum runs: 1
- Expected model calls: 16
- Hard model-call cap: 48
- Input-token cap: 1,000,000
- Output-token cap: 1,000,000
- Per-call output cap: 32,000
- USD cap: 20
- CNY cap: 50
- Elapsed cap: 7,200 seconds
- First terminal stop: true
- Resume after terminal: false
- Second run allowed: false

## Validation evidence

- Validate-only: exact, 38 ordered checks
- Import closure: exact; PTR4/PTR7 probe-only real entrypoints excluded from Generic Short
- Unknown or unapproved dependency: fail-closed
- Offline rehearsal: exact
- Planning: `domain_rejected -> exact_finding_propagated -> domain_passed`
- Draft: `mixed_script_rejected -> exact_finding_propagated -> draft_validation_passed`
- Stale finding count: 0 for Planning and Draft
- Config/Runtime collection profile comparison: exact
- Related offline tests: 55 passed
- Parent guard/import/successor tests: 36 passed
- Full offline business suite: 2651 passed, 39 skipped, 1 deselected, 6 xfailed
- Privacy: exact
- Live parity: exact

## Required state

`HISTORICAL_PTR3_EVIDENCE_UNCHANGED=YES`

`CURRENT_SUCCESSOR_BINDING=EXACT`

`PTR9_GUARD_BOUND=YES`

`PTR10_VALIDATION_BOUND=YES`

`SC_IC1_IMPORT_CLOSURE=EXACT`

`EXECUTION_AUTHORIZED=NO`

`SIGNED_APPROVAL=ABSENT`

`CONFIRMED_PATCH=ABSENT`

`USAGE_STATUS=UNUSED`

`LEDGER_ENTRY_COUNT=0`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`NEW_SINGLE_USE_APPROVAL_REQUIRED=YES`

`SC_FRESH_PACKET_SEAL_REQUIRED=YES`
