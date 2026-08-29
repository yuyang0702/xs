# Skill V3 Hybrid real-campaign execution-boundary closure — final report

Branch/start HEAD: `r1-ptr3/planning-repair-finding-propagation-20260817` / `f555f4fd6c8aa18569777d65e50f89fc8b04fb51`.
Source successor HEAD: `fb71c56218d2dfd0e6308aa1f9303e4e17e35e41`. Evidence seal commit follows this report.
Worktree before evidence: clean.
Source-derived mapped execution steps: 35; unmapped required steps: 0.
Fake-only real-path blockers: 0.
Canonical authorization validator: PASS, exact bytes only.
Campaign permission lifecycle: PASS, durable/single-create/expiry/scope/restart.
Six-sample order: CONTROL_1, HYBRID_1, CONTROL_2, HYBRID_2, CONTROL_3, HYBRID_3.
Sample IDs: sv3hs-0901efa55a2b11f3456f, sv3hs-63c2c291b989e2a3e48c, sv3hs-7725333044fdaae559a2, sv3hs-aae6112339a439d43750, sv3hs-8f00799be335c4ccaf76, sv3hs-84e695ee4e02665555cf.
Sample locks: edd6d501eec1c102ad30fcb5f4aa56ec0aa9ae56b1516241d58e79d72d87470c, e5c180c915d22d176e54da147b096e741259e2a304dec13c561ae81bd01e18e9, 1adfc2826f129c31d67a71cb424269c1cdd79c37f2f006d2d39f1352f2e7632a, a157b27243c6e8b178981c65f3fce9864ce8cf18361ed7df0b8a6c72be210c57, 9aa81b929e3d6564d8ab68216f8dfee3566eda4da66c79f089c3ff483380328b, 031791507f9b4c2cd70a9f3af123d6df5a1e7194e7483618d630fe5065b11b44.
Offline approval IDs: offline-hybrid-jit-1-9e7f3ab6a2c3da4c, offline-hybrid-jit-2-a3b0e0ae0f185e71, offline-hybrid-jit-3-5be282c49581666a, offline-hybrid-jit-4-db0422332657b621, offline-hybrid-jit-5-2c5f641eff32b874, offline-hybrid-jit-6-f7d6caca6d5dac22.
Offline nonce IDs: sv3n-acb9547b2eb8c332cc80934116bd8bf3, sv3n-3ce538ec7189e947d5d8a67e612c1248, sv3n-a0071ff6702676e2112e9e1ae72380ce, sv3n-f517d3eb95653ef9673a0b23c6817209, sv3n-6f6826bd338ecd2d8555eec73e42fb92, sv3n-8beab13e40638aa44634a89a400ca7e5.
Approval before nonce: PASS. Restart safety: PASS. Single-use/concurrency: PASS.
Stop-on-first-failure matrix: PASS. Transport/destination readiness: PASS.
Real local terminal pipeline dry run: PASS. Campaign completion/blind policy: PASS.
Model-visible identity: EXACT; source changed only in dormant canary orchestration.
Sample IDs/locks remain unchanged because no model-visible byte changed.
Pilot/experiment: `skill-v3-hybrid-character-heavy-v1-5e5cbfd1e6296ec8878b` / `de49d3353abe641f49dbb697d929a13bb30cc6c4fafe9bcf11f0a6d6ea19bafc`.
Provider/model/route: `lingsuan_gpt` / `gpt-5.6-sol` / `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`.
Destination/operator: `https://lingsuan.org:443/v1/messages` / `THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY`.
Egress SHAs: 58470e41d92a1f0acad35c6b543e3a6faaa54eeaa550a20672d3d0b5c387e34c, 6aa183aca58e1fb67348d66862c023240e1f7f97bddc35bc18f360fd14291507, cb26522fe2dbd9aba30c9c45fd9cb1d18a01e2e14433a6bccb07109f19fff256, 57d3ba94669de627b01fe0ec72ae51be18d905f819ef7f40127ccb1bb99cb27a, 0ccfffe2f65bdefe74cf362d75b33e9d1c37c83cdb4a81519a471d66cc18478f, 10dea0857ebee6142a8c1b708484b8abbf8f3a5f848fd19d8bd7154a1c570d09.
Caps: 4624 output/sample, 27744 total; one request/HTTP/network per sample, six total.
Cost cap: UNKNOWN_NOT_SEALED; actual-fee acceptance is required in final authorization.
Elapsed cap: 10 hours. Blind mapping stays hidden until vote freeze.
Stop-loss: first blocked/invalid/drift/failure/privacy/budget/expiry stops.
Final authorization: `docs/superpowers/reports/skill-v3-hybrid-real-campaign-execution-boundary-closure-v1/campaign-authorization-final-plaintext-v1.txt`.
FINAL_AUTHORIZATION_TEXT_SHA256=98aac2b004b1f9241dcd1c05d2185ddd099396cdbde0fdd336b963751c7dcbf2
Focused tests: 44 passed in 57.34s. Related tests: 108 passed, 1 historical sealed oracle failed in 133.18s. Full suite: 3950 passed, 41 skipped, 6 xfailed, 55 failed, 81 errors in 2305.47s.
Strict L3: PASS. Privacy: PASS. Manifest: EXACT.
DESIGN_READY=YES
SHADOW_READY=YES
EXPERIMENT_MATERIALIZED=YES
EXECUTION_BOUNDARY_READY=YES
USER_AUTHORIZATION_READY=YES
SKILL_V3_HYBRID_REAL_CAMPAIGN_EXECUTION_BOUNDARY_CLOSED=YES
PILOT_EXECUTION_AUTHORIZED=NO
REAL_PROVIDER_REQUEST_ATTEMPTS=0
REAL_NETWORK_CALLS=0
REAL_MODEL_CALLS=0
PAID_CALLS=0
SKILL_V3_PRODUCTION_CUTOVER=NO
PLANNING_V2_PRODUCTION_CUTOVER=NO
FULL_SHORT=NOT_EXECUTED
EXACT_NEXT_GATE=SKILL_V3_HYBRID_REAL_CAMPAIGN_AWAITING_ONE_FINAL_FRESH_USER_AUTHORIZATION
