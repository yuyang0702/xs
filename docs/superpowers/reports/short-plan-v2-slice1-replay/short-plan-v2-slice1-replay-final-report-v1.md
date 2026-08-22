# SHORT-PLAN-V2-SLICE1-OFFLINE-REPLAY-VALIDATION — Stop Report

`SHORT_PLAN_V2_SLICE1_REPLAY_NARROW_FIX_REQUIRED`

## Baseline

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Start/End HEAD: `1046670ae81d371cda2e05a8857a942ea59c59a7`
- Initial worktree: clean
- Planning V2 design manifest: exact, 19/19
- Slice 1 implementation-plan manifest: exact, 21/21
- Slice 1 implementation evidence manifest: exact, 19/19
- PTR12 design manifest: exact, 10/10
- Production and `baml_src/**` diff from HEAD: 0

## First failing invariant

Canonical corpus provenance must reproduce the fixture SHA bound by the sealed implementation replay receipt.

- Exact case: `canonical-corpus-provenance-before-case-dispatch`
- Artifact/version: `EventRealizationShadowReplayReceiptV1` / 1
- Field: `/fixture_sha256`
- Expected from sealed receipt: `6ff08d5e4045bd51ad992f372928e467255a07ab7c13a1ff01b7e5be2227daa6`
- Actual canonical CLI result: `a1442835a44471b9be5c87c4feb4ec89853a3b4348d7215185de62ced4a4fab4`
- Git blob (LF) SHA256/bytes: `6ff08d5e4045bd51ad992f372928e467255a07ab7c13a1ff01b7e5be2227daa6` / 4436
- Current checkout (CRLF) SHA256/bytes: `a1442835a44471b9be5c87c4feb4ec89853a3b4348d7215185de62ced4a4fab4` / 4486
- Environment evidence: `core.autocrlf=true`; fixture has no explicit `eol` attribute.
- Runtime owner evidence: the replay runner hashes `fixture_path.read_bytes()` without a declared line-ending canonicalization contract.

The full 20-case corpus did execute and all cases passed. With the same injected clock, Run A and Run B were byte-for-byte identical and both receipt SHA256 values were `08b58c973e823a939cf38c9a48cab35e2bc680f30461f2e2a3407d333a6746c8`. This does not repair the sealed provenance mismatch: deterministic repetition of the checkout-specific bytes is not exact reproduction of the sealed receipt.

## Blast radius and protected behavior

- Blast radius: replay/evidence portability and provenance binding across LF/CRLF checkouts; receipt identity and downstream evidence hashes can diverge although semantic JSON is unchanged.
- V1 affected: no. Planning V1, Draft input, READY, StoryState, Canon, Prompt, route/model, retry/fallback and budgets were not invoked or modified.
- Quality affected: no narrative mutation was performed; the failure occurs at corpus provenance binding.
- Slice 1 Runtime behavior changed in this task: no.
- External actions: credential 0, provider client 0, network 0, model 0, paid 0.

## Required narrow fix family

`CROSS_PLATFORM_CANONICAL_FIXTURE_PROVENANCE_BINDING_V1`

The follow-up must choose and test one explicit source-of-truth contract: either enforce LF bytes for the fixture through repository attributes, or hash a documented canonical JSON/newline representation and version that provenance algorithm. It must update the replay receipt through a new evidence chain and add LF/CRLF equivalence regression coverage. This task did not choose or implement the fix.

## Stop decision

- `NO_AUTOMATIC_FIX=YES`
- `SLICE1_PHASE_A_VALIDATED=NO`
- `SLICE1_PHASE_B_READINESS=NOT_READY_NARROW_FIX_REQUIRED`
- `PTR12_OBSERVER_GATE_BEFORE_PHASE_B=REQUIRED`
- `PLANNING_V1_AUTHORITY_UNCHANGED=YES`
- `PLANNING_V2_SLICE1_SHADOW_ONLY=YES`
- `NEW_PRODUCTION_BEHAVIOR_CHANGE=NO`
- `REAL_PROVIDER_CALLS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `NEW_FULL_SHORT_CANARY=NOT_EXECUTED`

Focused/related/full-suite and Strict L3 were not run after the first failing invariant, as required by the immediate Stop Gate.
