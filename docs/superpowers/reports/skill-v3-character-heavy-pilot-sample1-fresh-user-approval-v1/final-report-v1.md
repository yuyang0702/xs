# Skill V3 character-heavy pilot Sample 1 fresh user approval — sealed

`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_FRESH_USER_APPROVAL_SEALED`

1. Fresh authorization scope: `A1_ONLY / sv3s-089dd120ad568f87e7ef`; credential lookup, network access, necessary A1 request-data egress, and at most one paid Provider/model request authorized. Retry, fallback, route switch, resume, second dispatch, other samples, cutovers, and Full Short are not authorized.
2. Authorization binding/hash: `UTF-8_NFC_TRIM_OUTER_WHITESPACE_V1 / 3ee55a6aa2b5ca179c3d2518d4d7dfbf713cab4901d1999ead414deeb91dfa10`; same-conversation context identity SHA `2d2d2f22812048634289c85e77ebfbefa87bc2245d176fbebe09bc5faf9d99cd`.
3. Post-authorization drift check: `EXACT`; branch `r1-ptr3/planning-repair-finding-propagation-20260817`; HEAD `483796e46129750e35111b51bb8d1395c2a777c4`; source/baml diff `0/0`.
4. Signed approval ID: `skill-v3-a1-d1fe5c81-0aa7-4446-b323-d33fb703cdca`.
5. Signed approval canonical SHA: `c12acd0a464d7f17a2ffac40f3a5e97d8e9eba439c12b1a4b507152ffa9a0a5c`; file SHA `4c797c1ea45d38d0255570edc37e68a1ea44c3c16c8629c443a5ed0e316dd1c1`.
6. Sample ID: `sv3s-089dd120ad568f87e7ef`; sample slot/arm/index: `A1/A/1`.
7. Sample lock match: `YES`; sample lock SHA `8bc9c05794e1dbecb095a9a1b9937d9a277c5efa462b83c6b7e1e49495b862a7`.
8. Single-use: `YES`; usage status: `unused`; signed approval count: `1`.
9. Issued/expires: `2026-08-27T06:19:14Z / 2026-08-27T08:19:14Z`; policy: `TWO_HOUR_BOUNDED_WINDOW_FROM_ISSUED_AT_V1`.
10. Blanket approval: `ABSENT`.
11. Other sample approvals: `0`.
12. Real nonce created/reserved/consumed: `0/0/0`.
13. Credential lookup / Provider client / Provider requests / HTTP POST / network / model / paid calls: `0/0/0/0/0/0/0`.
14. Real sample execution: `0`.
15. Auto-advance: `NO`.
16. Exact next gate: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_REAL_EXECUTION`.

## Required state

- `CURRENT_CHAT_EXTERNAL_PERMISSION=A1_EXACT_SCOPE`
- `SIGNED_APPROVAL_CREATED=YES`
- `SIGNED_APPROVAL_COUNT=1`
- `SIGNED_APPROVAL_SINGLE_USE=YES`
- `SIGNED_APPROVAL_SAMPLE_LOCK_MATCH=YES`
- `REAL_NONCE_CREATED=NO`
- `REAL_NONCE_RESERVED=NO`
- `REAL_NONCE_CONSUMED=NO`
- `CREDENTIAL_LOOKUP_COUNT=0`
- `REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
- `REAL_PROVIDER_REQUEST_ATTEMPTS=0`
- `HTTP_POST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `REAL_SAMPLE_EXECUTION_COUNT=0`
- `AUTO_ADVANCE_TO_NEXT_SAMPLE=NO`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

Approval sealing stops here. No nonce was created and A1 was not executed.

