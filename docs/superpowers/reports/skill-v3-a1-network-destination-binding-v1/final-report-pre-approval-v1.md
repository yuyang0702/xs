# Skill V3 A1 destination binding — pre-approval final report

Status: `SKILL_V3_A1_DESTINATION_BOUND_FRESH_APPROVAL_AWAITING_USER_AUTHORIZATION`

## Baseline and blocked result

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Baseline HEAD: `97bb0019360cedd3033f61809171bd407cd69606`
- Destination implementation commit: `143ac0fce07aa955f40712c90001e0fbc9c5ee07`
- Prior V2 result: `BLOCKED_PRE_DISPATCH`; sealed 25-entry manifest exact.
- Prior Approval V2 remains historical `unused`, but it is destination-unbound and cannot authorize a future dispatch.
- Prior nonce/provider/network/model/paid counts: all `0`; A1 remains `NOT_EXECUTED` and next eligible.

## Concrete destination and risk

- Provider/model: `lingsuan_gpt` / `gpt-5.6-sol`
- Route fingerprint: `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`
- Destination: `https://lingsuan.org:443/v1/messages`
- Origin SHA256: `356a50c853735ad87163de137457b9e95cda70dfdb24229ffef847aff38a0b21`
- Operator classification: `THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY`.
- The future one-shot request includes sealed system/context, task and authority context, story slice, project guidance, A-arm Skill context, output contract, and request metadata.
- `RAW_REF_CORPUS_EGRESS=NO`; raw distill excerpts, learn-node evidence, unrelated project data, other samples, historical blind results, credentials, and local paths are excluded.
- The remote operator/Provider may process, retain, or log submitted data under its own policies; no external privacy or ownership claim was verified.

Exactly one origin is allowed. Redirect following, environment proxy mounts, caller/environment base-URL override, fallback, route switch, retry, resume, second dispatch, and alternate destinations are disabled or fail closed.

## Enforcement and validation

Approval V3 binds origin, origin hash, path, operator class, egress-policy hash, and false redirect/proxy flags. Durable nonce V2 binds the same origin/path and egress hash. The dispatcher checks destination before nonce reservation, credential lookup, Provider-client creation, and network access, then checks the adapter target again.

- Negative destination matrix: `17/17 PASS`
- Focused tests: `23 passed`
- Adjacent tests: `119 passed`
- Strict L3: `PASS`, warnings `0`, blockers `0`
- `src/** diff=0`; `baml_src/** diff=0`; A1 wire/model/Skill/non-Skill identities exact.
- Privacy scan: `PASS`; no secret or raw prompt/story/Provider content persisted.

## Pre-approval terminal state

`APPROVAL_V3=NOT_CREATED`

`REAL_EXECUTION_NONCE_CREATED=NO`

`CREDENTIAL_LOOKUP_COUNT=0`

`REAL_PROVIDER_CLIENT_CREATION_COUNT=0`

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`

`HTTP_POST_ATTEMPTS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`REAL_SAMPLE_EXECUTION_COUNT=0`

The exact clean destination-successor HEAD is produced by the evidence seal commit and must be reported out of band after that commit; embedding a commit's own hash in a tracked pre-approval artifact would be self-referential.
