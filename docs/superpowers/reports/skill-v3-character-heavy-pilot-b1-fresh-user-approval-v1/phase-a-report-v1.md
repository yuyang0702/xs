# Skill V3 B1 fresh approval — Phase A report

`SKILL_V3_B1_DESTINATION_BOUND_FRESH_APPROVAL_AWAITING_USER_AUTHORIZATION`

- Baseline: branch `r1-ptr3/planning-repair-finding-propagation-20260817`, HEAD `c6252b587967c210f4ec2810c58fda135fd3cec4`, clean worktree.
- A1: `SEALED_VALID`; approval and nonce `CONSUMED`; logical/Provider/HTTP/network attempts `1/1/1/1`; all retry/fallback/switch/resume/second-dispatch counts `0`; no automatic B1 launch.
- Pilot order: `A1,B1,A2,B2,A3,B3`; B1 is the exact next eligible sample and no stop condition is active.
- B1: `sv3s-cd80aa5d21e790079a06`, arm `B`, pair index `1`, sequence position `2`.
- Locks: sample `167306de3459b281734a73418e4d4f2ff1d4b66d69722eb01552d845c58fc936`; parent `8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b`; component `eb1c00e0065b8080000e2ea2eb07fc2409a4442e013b06ae18508c44d25d68c8`; wire `75106c9a5ece3a400432228dfa02bef229d44a772173c1b88da361a97d206eff`.
- B1 Skill: `c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd`; compiler `verbatim-selective-skill-compiler-shadow-v1`; selector `selective-section-selector-v1`; sections/count/chars/tokens `9/2556/639`; identity, verbatim fidelity, dependency closure, wrong-layer exclusion, conflict closure, and no-truncation/no-shedding all pass.
- Non-Skill snapshot: `82ab7881d58764552de2371e08c6ffd23b2d13dc2523cc1a9c8dbb96f227c303`; all A1/B1 non-Skill model-visible bytes are identical; `PRIMARY_CHANGED_VARIABLE=SKILL_CONTEXT`; prior A1 prose/result/metadata/blind result contamination is absent.
- Route: logical role `planning_event_realization_shadow_v1`; Provider/model `lingsuan_gpt/gpt-5.6-sol`; Anthropic primary route `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`; output cap `4624`; context/input/headroom `32768/1347/17581`; capacity pass with no silent truncation.
- Dispatcher/nonce: `skill-v3-real-pilot-dispatcher-v2` / `skill-v3-pilot-durable-nonce-policy-v1`; executable single-dispatch guard pass; retry, transport retry, fallback, route switch, resume, second dispatch all disabled.
- Destination: `https://lingsuan.org:443/v1/messages`; operator `THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY`; destination SHA `356a50c853735ad87163de137457b9e95cda70dfdb24229ffef847aff38a0b21`; resolved independently from sealed B1 route, committed source, and local non-secret metadata; exactly one destination, no caller override or cross-origin redirect.
- Egress policy: `76225b4f0b47ee9de0002e0df1760b5e66e3a83e9647d75e82896281b8d246ad`; raw REF, raw distill evidence, learn-node raw evidence, A1 prose/result, other sample data, blind result, credentials, and local absolute paths are excluded.
- One-shot limits: logical/Provider/HTTP/network maximum `1/1/1/1`; cost cap `UNKNOWN_NOT_SEALED`; remaining pilot real-request budget after A1 `5`.
- Offline validation: focused B1 binding check `12/12 PASS`; related negative/adjacent tests `118 passed`; full suite not run because this packet changes no source or Runtime behavior.
- Strict L3: `PASS`, warnings `0`, blockers `0`; no source, test, core, UI, or user-visible production path changed.
- Privacy: `PASS`; no raw Prompt, story prose, Provider content, REF corpus, credential/secret, or local absolute path is present.
- SHA manifest: `16/16 EXACT` payload entries; the manifest itself is the seventeenth file.
- Phase A only: unsigned execution authorization `false`; signed approval absent; nonce `NOT_CREATED`; credential/Provider client/Provider/HTTP/network/model/paid counts all `0`; B1 not executed; no A2 advancement, cutover, or Full Short.
- Production source and `baml_src/**` diff from A1 pre-execution baseline: `0/0`.
- The exact clean Phase-A successor HEAD and final authorization sentence are reported out of band after the bounded evidence commit; no tracked file is written afterward.

This packet does not authorize execution.
