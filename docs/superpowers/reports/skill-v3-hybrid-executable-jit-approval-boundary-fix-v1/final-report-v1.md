# Skill V3 Hybrid JIT signed approval boundary — final report

1. Branch/start HEAD: `r1-ptr3/planning-repair-finding-propagation-20260817` / `f3967c9d18a9942a65703db7f3edbf4f72b16864`.
2. Fix commit: `04089881033c0a090f0a01334248d341624585d8`; evidence seal is the next commit.
3. Materialization binding HEAD: `04089881033c0a090f0a01334248d341624585d8`; final worktree is required clean after seal.
4. Original blocker: `HYBRID_EXECUTABLE_JIT_SIGNED_APPROVAL_BOUNDARY_NOT_IMPLEMENTED`.
5. Existing boundary audit: canonical hashing, nonce V2, and one-shot dispatch are reusable.
6. Old-pilot coupling: Selective V4 remains fixed to B1/A2/B2/A3/B3 and is unchanged.
7. New schema/version: `SkillV3HybridSampleJitSignedApprovalV1` / `1`.
8. Canonical fields bind identity, git, sample, model-input, route, destination, egress, caps, permission, expiry, and nonce state.
9. Strict schema validator: PASS; closed field set and no permissive defaults.
10. Domain validator: PASS; sealed lookup, next-eligible, clean git, zero-attempt and no-preexisting-nonce checks.
11. Durable store: external namespace, immutable body, atomic locked lifecycle.
12. Single-use lifecycle: UNUSED -> CONSUMED/INVALID/EXPIRED; reactivation forbidden.
13. Six-role support: CONTROL_1/HYBRID_1/CONTROL_2/HYBRID_2/CONTROL_3/HYBRID_3 = 6/6.
14. Old Selective compatibility: PASS; old source unchanged.
15. Approval->nonce ordering: exact and fail closed.
16. Negative injections: 26 classes PASS.
17. Failure observability: bounded typed hash-only receipt.
18. Silent failure path count: 0.
19. Runner boundary: one exact sample, verified approval, destination-bound nonce, one-shot dispatcher.
20. Real-dispatch readiness is implemented but not executed.
21. Model-visible sample identity: all six wire/component hashes EXACT.
22. Successor rematerialization: EXACT and inert.
23. Sample IDs and locks preserved because the fix is non-model-visible and all sealed bytes rechecked exact.
24. New successor HEAD: `04089881033c0a090f0a01334248d341624585d8`.
25. Pilot/experiment: `skill-v3-hybrid-character-heavy-v1-5e5cbfd1e6296ec8878b` / `de49d3353abe641f49dbb697d929a13bb30cc6c4fafe9bcf11f0a6d6ea19bafc`.
26. Sample IDs: sv3hs-0901efa55a2b11f3456f, sv3hs-63c2c291b989e2a3e48c, sv3hs-7725333044fdaae559a2, sv3hs-aae6112339a439d43750, sv3hs-8f00799be335c4ccaf76, sv3hs-84e695ee4e02665555cf.
27. Sample locks: edd6d501eec1c102ad30fcb5f4aa56ec0aa9ae56b1516241d58e79d72d87470c, e5c180c915d22d176e54da147b096e741259e2a304dec13c561ae81bd01e18e9, 1adfc2826f129c31d67a71cb424269c1cdd79c37f2f006d2d39f1352f2e7632a, a157b27243c6e8b178981c65f3fce9864ce8cf18361ed7df0b8a6c72be210c57, 9aa81b929e3d6564d8ab68216f8dfee3566eda4da66c79f089c3ff483380328b, 031791507f9b4c2cd70a9f3af123d6df5a1e7194e7483618d630fe5065b11b44.
28. Execution sequence: CONTROL_1, HYBRID_1, CONTROL_2, HYBRID_2, CONTROL_3, HYBRID_3.
29. Egress SHAs: 58470e41d92a1f0acad35c6b543e3a6faaa54eeaa550a20672d3d0b5c387e34c, 6aa183aca58e1fb67348d66862c023240e1f7f97bddc35bc18f360fd14291507, cb26522fe2dbd9aba30c9c45fd9cb1d18a01e2e14433a6bccb07109f19fff256, 57d3ba94669de627b01fe0ec72ae51be18d905f819ef7f40127ccb1bb99cb27a, 0ccfffe2f65bdefe74cf362d75b33e9d1c37c83cdb4a81519a471d66cc18478f, 10dea0857ebee6142a8c1b708484b8abbf8f3a5f848fd19d8bd7154a1c570d09.
30. Route/destination: `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0` / `https://lingsuan.org:443/v1/messages`.
31. Caps: 4624/sample, 27744 total, 1 request/network/HTTP/logical call per sample, 6 total.
32. Cost cap: UNKNOWN_NOT_SEALED; future user must explicitly accept actual-fee risk.
33. Capacity: PASS; safe context window remains 32768.
34. Pair identity: PASS.
35. Cross-sample contamination: 0.
36. Blind policy: unchanged; mapping hidden until vote freeze.
37. Stop-loss: first blocked/invalid/drift/failure/privacy/budget/expiry stops campaign.
38. Authorization plaintext: `docs/superpowers/reports/skill-v3-hybrid-executable-jit-approval-boundary-fix-v1/campaign-authorization-plaintext-v2.txt`.
39. Authorization text SHA-256: `4b2722488bd1843a286fb7a4902e8dd0c9d86341fcbacdc96fe47841989f5d24`.
40. Tests: focused=36 passed in 27.13s; related=79 passed in 124.09s; full=3907 passed, 41 skipped, 6 xfailed, 54 failed, 81 errors in 2224.36s.
41. Regression classification: new JIT=0; new owning source=0; historical sealed/oracle/live-parity non-green separated.
42. Strict L3/privacy: PASS / PASS; manifest exact.
43. External counters: all zero.
44. Skill V3 and Planning V2 cutovers: NO.
45. Full Short: NOT_EXECUTED.
46. PILOT_EXECUTION_AUTHORIZED=NO.
47. EXACT_NEXT_GATE=SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_AWAITING_FRESH_USER_AUTHORIZATION.

SKILL_V3_HYBRID_EXECUTABLE_JIT_SIGNED_APPROVAL_BOUNDARY_IMPLEMENTED=YES
SKILL_V3_HYBRID_CHARACTER_HEAVY_PILOT_REMATERIALIZED=YES
SKILL_V3_HYBRID_CHARACTER_HEAVY_PILOT_APPROVAL_READY=YES
PILOT_EXECUTION_AUTHORIZED=NO
SIGNED_APPROVAL_CREATED=NO
REAL_NONCE_CREATED=NO
REAL_PROVIDER_REQUEST_ATTEMPTS=0
NETWORK_CALLS=0
MODEL_CALLS=0
PAID_CALLS=0
SKILL_V3_PRODUCTION_CUTOVER=NO
PLANNING_V2_PRODUCTION_CUTOVER=NO
FULL_SHORT=NOT_EXECUTED
EXACT_NEXT_GATE=SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_AWAITING_FRESH_USER_AUTHORIZATION
