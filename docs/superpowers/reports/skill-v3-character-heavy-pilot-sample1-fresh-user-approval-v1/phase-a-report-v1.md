# Skill V3 character-heavy pilot Sample 1 fresh user approval — Phase A

`SKILL_V3_SAMPLE1_FRESH_USER_APPROVAL_AWAITING_USER_AUTHORIZATION`

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. HEAD: `483796e46129750e35111b51bb8d1395c2a777c4`
3. Worktree: `STARTING_CLEAN; PHASE_A_EVIDENCE_ONLY_AFTER_MATERIALIZATION`
4. Pilot ID: `skill-v3-character-heavy-multi-sample-v1-4d47410b0144360d`
5. A1 sample ID: `sv3s-089dd120ad568f87e7ef`
6. Sample lock SHA: `8bc9c05794e1dbecb095a9a1b9937d9a277c5efa462b83c6b7e1e49495b862a7`
7. Parent experiment lock SHA: `8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b`
8. Next eligibility: `A1 / PASS`; already executed/sealed/approved: `NO/NO/NO`; stop condition: `INACTIVE`; auto-advance: `NO`
9. A Skill context: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE`; SHA `7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc`
10. Non-Skill snapshot SHA: `82ab7881d58764552de2371e08c6ffd23b2d13dc2523cc1a9c8dbb96f227c303`
11. Reference-derived provenance SHA: `41b9fe2c61e20cd68429f3451994c90bc0e450beb97cf7bf400b5e77a82620df`
12. Provider: `HASH_ONLY_PROVIDER_DESCRIPTOR`; SHA `121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f`
13. Model: `HASH_ONLY_MODEL_BINDING`; SHA `5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff`
14. Route fingerprint: `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`; protocol/client: `anthropic / AnthropicAdapter`
15. Max output tokens: `4624`; model context limit: `32768`; A input estimate: `1440`; headroom: `17488`
16. One-shot caps: logical/provider/HTTP/network `1/1/1/1`; pilot total real-request cap `6`
17. Cost cap: A1 `UNKNOWN`; pilot `UNKNOWN`; no web price lookup performed
18. Egress: a future authorized A1 request necessarily includes the exact sealed A1 system/context packet, authority/task/story slice, frozen non-Skill guidance, A-arm Skill context, and structured output contract. `STORY_DATA_EGRESS_REQUIRED=YES`
19. Raw REF / distill / learn-node / project style sample planning visibility: `NO/NO/NO/NO`
20. Retry/fallback/route-switch/resume/second-dispatch: `NO/NO/NO/NO/NO`; single-dispatch guard: `PASS`
21. Unsigned approval packet SHA256: `e39a654b28b006eff1301bbd4f951f3a44584107dea63a87616ca5f188c9be52`
22. Privacy: `PASS`; matches `0`; raw Prompt/story, credentials, secret Provider URL, signed approval, and real nonce persisted: `0`
23. Signed approval count: `0`
24. Real nonce created/reserved/consumed: `0/0/0`
25. Credential lookup / Provider client / Provider requests / HTTP POST / network / model / paid / real sample execution: `0/0/0/0/0/0/0/0`
26. Exact authorization sentence requested from the user (this sentence in evidence is a request template, not authorization):

    `我明确授权本次 A1（sv3s-089dd120ad568f87e7ef）执行所需的凭据读取、网络访问、必要请求数据外发，以及最多 1 次付费 Provider/模型请求；不授权重试、fallback、route switch、第二次请求，也不授权其他样本、Skill V3 cutover 或 Full Short。`

27. Status: `SKILL_V3_SAMPLE1_FRESH_USER_APPROVAL_AWAITING_USER_AUTHORIZATION`

## Phase A boundary

- `CURRENT_CHAT_EXTERNAL_PERMISSION=ABSENT`
- `UNSIGNED_APPROVAL_PACKET_EXECUTION_AUTHORIZED=false`
- `SIGNED_APPROVAL_CREATED=NO`
- `REAL_EXECUTION_NONCE_CREATED=NO`
- `REAL_EXECUTION_NONCE_RESERVED=NO`
- `REAL_EXECUTION_NONCE_CONSUMED=NO`
- `CREDENTIAL_LOOKUP_COUNT=0`
- `REAL_PROVIDER_CLIENT_CREATION_COUNT=0`
- `REAL_PROVIDER_REQUEST_ATTEMPTS=0`
- `HTTP_POST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `REAL_SAMPLE_EXECUTION_COUNT=0`
- `AUTO_ADVANCE_TO_NEXT_SAMPLE=NO`
- `PAIR2_TO_5_EXECUTION_ALLOWED=NO`
- `SKILL_V3_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `PLANNING_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`
- `FULL_SHORT_CANARY=NOT_EXECUTED`

Phase A stops here. Phase B requires a new explicit user message in this same Codex conversation.

