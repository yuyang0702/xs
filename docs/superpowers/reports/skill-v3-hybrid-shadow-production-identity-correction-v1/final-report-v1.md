# Skill V3 Hybrid shadow production identity correction

`SKILL_V3_HYBRID_SHADOW_PRODUCTION_IDENTITY_CORRECTED=YES`

1. Branch/start HEAD: `r1-ptr3/planning-repair-finding-propagation-20260817` / `7f2fbcdafbdbaae221ce9ebb840c7bb57d889f72`.
2. Fix/evidence commits: implementation `c29e7da652c86a0e701dc820918a817ab8389df6`; the evidence-only seal commit is created after this content-addressed report.
3. Final HEAD/worktree target: evidence seal successor of `c29e7da652c86a0e701dc820918a817ab8389df6` with a clean worktree.
4. Original review blocker: `RESOLVED_SKILL_SOURCE_HASH_MISMATCH_AT_PRODUCTION_SHADOW_SEAM`.
5. Production resolved-source domain: SHA-256 over every regular file beneath the resolved Skill root, in sorted relative POSIX-path order, feeding each path byte sequence followed by exact file bytes.
6. Old Hybrid document domain: SHA-256 over the exact primary `SKILL.md` bytes; it is not a directory/package identity.
7. Canonical production seam identity: `resolved_source_sha256`, emitted by `SkillScanner`/`SkillGate` and compared only with the V2 sealed package identity.
8. Provenance identities: `primary_document_sha256` binds exact `SKILL.md`; `section_content_sha256` independently binds the exact selected section.
9. Data structures/schema: additive explicit package/document fields on `Skill`, `SkillReceipt`, `HybridShadowInputV1`, the Hybrid index, binding projection, and receipt; historical ambiguous V1 index storage remains readable as primary-document identity.
10. Invalid comparison replaced: package SHA is no longer compared with the single-file SHA; neither document nor section provenance was removed.
11. Four real Planning Skills passed the actual resolver -> `WorkflowService._stage` -> Hybrid shadow seam: `4/4 PASS`; resolved-source mismatch count `0`.
12. Identity negative injections A-E: `PASS`; wrong package, stale primary document, stale section, stale override/source-root, and extra identity-bearing directory file all fail closed in their own domain.
13. Override/source-root behavior: any package-byte/path-set drift invalidates stale sealed package identity even when `SKILL.md` bytes remain unchanged.
14. Materializer correction: it consumes real `SkillScanner` identities for the four production Planning Skill IDs; direct Hybrid index-hash injection `NO`.
15. Disabled production identity: Prompt/model input/Skill routing/compactor/reference/route/sampling/output cap/validator identities are `EXACT`.
16. Baseline/reference preservation: foundation and reference guidance preserved; supplement replacement `NO`; verbatim mismatch, wrong-layer section, and unresolved contradiction counts all `0`.
17. Failure observability: bounded domain-specific typed/hash-only receipts; silent failure paths `0`; production model input unchanged; no external call.
18. Tests: focused `62 passed` (`59` implementation-focused plus `3` evidence tests); related `451 passed`; final full-suite statistics are bound in `full-suite-receipt-v1.json`.
19. Regression classification: identity-correction regressions `0`; owning-source regressions `0`; remaining non-green items are historical sealed/oracle/live-parity gates.
20. Strict L3/privacy/manifest: Strict L3 `PASS`, warnings `0`, blockers `0`; privacy `PASS`; SHA manifest exact after materialization.
21. External counters: `{"CREDENTIAL_LOOKUP_COUNT": 0, "HTTP_POST_ATTEMPTS": 0, "MODEL_CALLS": 0, "NETWORK_CALLS": 0, "NEW_REAL_SAMPLE_COUNT": 0, "PAID_CALLS": 0, "REAL_NONCE_CREATED": "NO", "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0, "REAL_PROVIDER_REQUEST_ATTEMPTS": 0, "SIGNED_APPROVAL_CREATED": "NO"}`.
22. Cutovers: `SKILL_V3_PRODUCTION_CUTOVER=NO`; `PLANNING_V2_PRODUCTION_CUTOVER=NO`.
23. Full Short: `FULL_SHORT=NOT_EXECUTED`.
24. `PILOT_EXECUTION_AUTHORIZED=NO`.
25. `NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX=NOT_REVIEWED_IN_THIS_GATE`.
26. `EXACT_NEXT_GATE=SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_AND_PILOT_READINESS`.

`CANONICAL_PRODUCTION_SEAM_IDENTITY_DEFINED=YES`

`SECTION_PROVENANCE_IDENTITY_DEFINED=YES`

`HASH_DOMAIN_COLLISION_OR_CONFUSION_FIXED=YES`

`REAL_PLANNING_SKILL_SEAM_PASS=4/4`

`MATERIALIZER_USES_PRODUCTION_RESOLVED_SOURCE_IDENTITY=YES`

`IDENTITY_NEGATIVE_INJECTIONS_PASS=YES`

`FAILURE_OBSERVABILITY_PASS=YES`

`PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED=YES`

`PILOT_EXECUTION_AUTHORIZED=NO`

`NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX=NOT_REVIEWED_IN_THIS_GATE`

`EXACT_NEXT_GATE=SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_AND_PILOT_READINESS`
