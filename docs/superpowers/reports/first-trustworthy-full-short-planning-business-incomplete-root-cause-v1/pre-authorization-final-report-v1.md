# First Trustworthy Full Short — Planning business-incomplete final report

## Disposition

The narrow runtime defect is corrected and the production-shaped offline Full Short closes, but the master gate is **not complete**. The historical provider response and converted JSON were deliberately retained as hashes only. Consequently the mandatory post-fix replay of the exact captured bytes cannot be performed, independently verified, or reconstructed without guessing.

`PRIMARY_ROOT_CAUSE=PLANNING_PLAIN_ROUTE_MODEL_VISIBLE_REQUIRED_FIELD_CONTRACT_OMITTED_WITH_GENERIC_GATE_PREEMPTING_TYPED_RECOVERY_AND_UNCLOSED_LOCAL_REJECTION`

`TRUSTWORTHY_FULL_SHORT_READINESS=NO`

`FULL_SHORT_PRODUCTION_SHAPED_DRY_RUN=PASS`

`FINAL_HEAD_BINDING_CLOSED=NO`

`FINAL_AUTHORIZATION_READY=NO`

`FULL_SHORT_EXECUTION_AUTHORIZED=NO`

`EXACT_NEXT_GATE=FIRST_TRUSTWORTHY_FULL_SHORT_CAPTURED_RESPONSE_REPLAY_REQUIREMENT_DISPOSITION`

## Baseline and real failure binding

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Actual `START_HEAD`: `a91aa04d6c9a0c7d5d1d7541d4e6734ad328d6d2`
- Reviewed implementation HEAD: `a62bb88d400338f6daafffb4623495f4b73b0945`
- Real-run ledger file SHA-256: `1ee6b2a76f8bbd068700aefb6216dcb1e86dd1b31159a39f5868348c27a0dee0`
- Conversion-audit file SHA-256: `532b8a238c9410c2e5b97fdf38d51f076400a61f53147cc1bc7ae5c863d11be5`
- Raw payload SHA-256 recorded by the historical audit: `e5170ab88e06704345041047f6210ff3e94f16a065e3b84d110f1e4558e6aaad`
- Canonical JSON SHA-256 recorded by the historical audit: `1db94ca61b00af660c59de0c76674888a729b638b163dcaf9baae4fa3be776d3`
- Planning schema SHA-256 at failure: `f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7`
- Provider result: `end_turn`, 3,230 output tokens of 3,724 requested, 5,004 visible characters, transport complete.
- Conversion: one `exact_json` candidate, zero transformations, zero quarantined paths.
- Failure ordering: candidate detection passed; generic required-field completeness failed; Pydantic/domain validation and typed finding extraction were not reached.
- No Planning receipt, final artifact, checkpoint, completion, StoryState/Canon/READY promotion, retry, fallback, resume, or second dispatch occurred.

Evidence of truncation: **NO**. Evidence of provider conversion loss: **NO**. The retained metadata cannot prove byte identity, but it contains no cap, transport, transformation, or quarantine signal supporting either hypothesis.

## Independent review results

Initial Provider/Structured Output reviewer:

- Proved only that a nonempty subset of `{initial_state, segments}` was absent; the exact missing member is unrecoverable from hash-only evidence.
- Classified the response as a closed, nonempty, structurally undercomplete top-level JSON mapping—not byte-sparse truncation.
- Found the weak mapping normalizer plus generic pre-domain gate prevented typed Planning recovery.
- Recommended explicit plain-route root requirements and authoritative typed finding propagation, without schema weakening, provider-specific repair, or cap expansion.

Initial Business Completeness/Authority reviewer:

- Confirmed `initial_state` and `segments` are model-owned sealed business invariants and cannot be safely synthesized locally.
- Confirmed the business gate was correct to reject the artifact, but the model-visible plain-route contract and failure ownership were misaligned.
- Found the old dry-run oracle always emitted complete roots, creating the fixture realism blind spot.
- Confirmed authority remained unpromoted and recovery must stay same-session, typed, bounded, and fail-closed.

Fresh final Reviewer A result: `DELTA_PASS`. Fresh final Reviewer B result: `DELTA_PASS`. Both independently accepted the implemented delta and both retained the historical captured-byte replay blocker.

## Business contract ownership and alignment

| Field/invariant | Ownership | Schema | Plain-route prompt before fix | Validator | Downstream required | Real status |
|---|---|---:|---:|---:|---:|---|
| `initial_state` | model-owned | yes | type/schema implied, literal root not salient | yes | yes | unknown individually; part of proven missing subset |
| `segments` | model-owned | yes | segment rules explicit, root skeleton not explicit | yes | yes | unknown individually; part of proven missing subset |
| segment ordinal/continuity | model-owned | yes | yes | yes | yes | unavailable without bytes |
| continuation `exit_state` | model-owned | yes | yes | yes | yes | unavailable without bytes |
| terminal segment omission of `exit_state` | model-owned | yes | yes | yes | yes | unavailable without bytes |
| typed finding paths | local-derived | no | not model output | yes | recovery required | not reached before fix |
| StoryState/Canon/READY promotion | authority-derived | no | not model output | authority gate | yes | not promoted |

The exact failed invariant is: `PlanningSemanticDraftV2` must contain both model-owned top-level roots `initial_state` and `segments`. At least one was absent. Weakening or locally deriving either would materially violate the existing business contract, so neither was done.

## Root-cause classification

- H1 prompt business requirement not explicit: `SUPPORTED` for the plain-route root skeleton.
- H2 structured schema too weak: `NOT_SUPPORTED`; both roots were schema-required.
- H3 validator overstrict/wrong layer: `PARTIALLY_SUPPORTED`; strictness was correct, but the generic gate owned the error before authoritative typed domain findings.
- H4 provider truncation/capacity: `NOT_SUPPORTED`.
- H5 structured-output conversion loss: `NOT_SUPPORTED` by retained evidence.
- H6 model compliance failure with clear contract: `PARTIALLY_SUPPORTED`; executable schema was clear, model-visible plain-route salience was incomplete.
- H7 offline fixture blind spot: `SUPPORTED`.
- H8 multi-factor: `SUPPORTED` and chosen as the bounded primary mechanism expressed above.

## Narrow fix

- Made the required Planning roots and nested continuation/terminal rules explicit in the plain-route model-visible contract. `MODEL_VISIBLE_CONTRACT_CHANGED=YES`; intended literary/business semantics are unchanged.
- Routed missing required roots through authoritative Pydantic/domain finding extraction before the generic backstop.
- Preserved the existing bounded Planning recovery envelope; did not add an unbounded retry, new route, fallback, model, provider, or output-token allowance.
- Closed a locally rejected attempt in the durable offline session and allowed only the already-authorized same-session continuation. Restart remains fail-closed.
- Added value-free/hash-only rejection diagnostics, truthful call accounting, safe tail observation, and current-HEAD/JUnit/cap validation.
- Expanded the dry-run with a one-shot structurally valid but business-incomplete Planning fixture at the lowest mock transport seam.

Targeted repair disposition: one typed, same-scope Planning repair already allowed by the sealed recovery design is represented and counted. Multi-finding beyond scope, incomplete repair, no-progress repair, restart, fallback widening, and unapproved redispatch remain fail-closed.

## Replay and validation

Exact captured real response replay: `UNAVAILABLE_HISTORICAL_BYTES_NOT_PERSISTED`. Synthetic exhaustive replay of the only provable missing-root equivalence classes (`initial_state`, `segments`, both) correctly rejects each case, emits value-free typed findings, and performs no authority promotion. This evidence is deliberately **not** represented as captured-byte replay.

Planning response matrix: synthetic matrix `PASS`; mandatory exact-real case `BLOCKED`. It covers complete valid, each missing root, both missing roots, malformed optional data, locally derivable omission, duplicates, inconsistent references, minimal complete, near-cap complete/incomplete, provider-style sparse valid, repairable omission, over-broad repair, still-incomplete repair, no-progress repair, and exact finding propagation.

`DRY_RUN_FIXTURE_REALISM_GAP=THE_PREVIOUS_FAKE_PLANNING_ORACLE_ALWAYS_EMITTED_BUSINESS_COMPLETE_ROOTS_AND_NEVER_INJECTED_A_STRUCTURALLY_VALID_REQUIRED_ROOT_OMISSION_AT_THE_REAL_LOCAL_VALIDATION_BOUNDARY`

`REALISTIC_STRUCTURED_OUTPUT_FAILURE_INJECTION=PASS`

Production-shaped Full Short rerun:

- Normal: `PASS`, 70 physical requests / 70 logical completed stages.
- Injected: `PASS`, 71 physical requests / 70 logical completed stages / one local typed rejection.
- Both produce the same final artifact SHA-256: `0dc997a7770cbd267f7ae97c41da5a311f6e630236323f7266cdd56064d36133`.
- All Draft, style/reference, Final Review, Maintenance, completion, and authority-chain integration assertions pass.
- Determinism: `PASS`.
- Production baseline Skill identity: `PASS`.
- Hybrid model-visible leak count: `0`.
- `baml_src/**` task diff: `0`.

## Tests and gates

- Focused Planning/Full Short recovery cluster: `270 passed`, `0 failed`, `0 errors`.
- Production-length flows: `3 passed` for 13K/20K/30K.
- Related rerun: `4 passed`, `7 failed`; all seven are pre-`START_HEAD` stale fakes/authority or legacy Planning/Draft behavior. Task-owned regressions: `0`.
- Full offline suite: `4008 passed, 41 skipped, 6 xfailed, 189 failed, 199 errors`. JUnit aggregates the 41 skipped and 6 xfailed as 47 skipped. Non-green families are historical sealed approval/hash/live-parity/oracle gates and stale workflow fakes. New owning-source regressions: `0`.
- Privacy: `PASS`; raw Prompt, story, provider content, rejected payload, and credential values persisted: `0`.
- Production isolation: `PASS`; credential/provider/network/model/paid counters: `0`.
- Strict L3: `FAIL_CONTAINED_OPEN_WORLD_REQUIREMENT_UNRESOLVED`, with zero tool blockers and two warnings. The council correctly refuses to call containment “systemically resolved” while mandatory historical-byte replay is impossible. This status was not rewritten to manufacture a green result.

## Planned execution envelope if the blocker is dispositioned later

- Discovered logical stage-call plan: `70`.
- Physical provider/HTTP/network hard cap: `71` (exactly one counted Planning repair allowance).
- Normal discovered output-token total: `249386`.
- Planning repair output-token cap: `3724`.
- Total output-token hard cap: `253110`.
- Per-call output-token hard cap: `8328`.
- Elapsed hard cap: `36000` seconds.
- Monetary cap state: `UNKNOWN_NOT_SEALED`.

These values are offline-derived only and do not authorize execution.

## Commits, authorization, and stop state

Source/test work is contained in the commit range `3fb7327098d23466328d7f182d4ce8f1a3d27e19` through `a62bb88d400338f6daafffb4623495f4b73b0945`; the complete list is recorded in `source-commit-range-v1.json`. The evidence-seal commit and manifest SHA are reported after the final seal.

- `FINAL_EXECUTION_HEAD=ABSENT_NOT_FROZEN_FOR_EXECUTION`
- External authorization path/kind: `ABSENT_NOT_MATERIALIZED`.
- `FINAL_AUTHORIZATION_TEXT_SHA256=ABSENT_NOT_MATERIALIZED`
- `REAL_FULL_SHORT_AUTHORIZATION_PREFLIGHT=NOT_RUN_READINESS_BLOCKED`
- `POST_AUTH_HEAD_DRIFT_REJECTED=NOT_RUN_READINESS_BLOCKED`
- `POST_AUTH_GIT_COMMIT_COUNT=NOT_APPLICABLE_NO_AUTHORIZATION`
- No signed approval and no real nonce were created.

`CREDENTIAL_LOOKUP_COUNT=0`

`PROVIDER_CLIENT_CREATION_COUNT=0`

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`

`HTTP_POST_ATTEMPTS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`REAL_SAMPLE_EXECUTION_COUNT=0`

`FULL_SHORT_EXECUTION_COUNT=0`

`FULL_SHORT=NOT_EXECUTED`

No consumed authorization was reused, no new authorization was materialized, and no real Full Short was executed.
