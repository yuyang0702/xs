# Captured Response Disposition and Skill Source Truth — Pre-Authorization Final Report

Branch `r1-ptr3/planning-repair-finding-propagation-20260817`; START_HEAD `2005a80fc7f261d3c479d93b5ed5ad0d38b56812`; implementation HEAD `d08a125e665bbb536952dcaa82476abbe5d390b0`.

Historical raw/canonical response bytes were not found in any legitimate durable location. The surviving hashes, conversion audit, business-incomplete receipt and ledger identity support the prior root cause, but they do not constitute an exact-byte replay. The failed call is permanently marked `NON_REPLAYABLE_EXACT_BYTES_MISSING`.

Prospective capture is now enforced at `TRANSPORT_RESPONSE_BODY_BYTES` and `CONTRACT_RUNTIME_INPUT_BYTES`, using worktree-external exclusive-create crash-safe storage and ledger-anchored receipts. Replay verifies all identities and re-enters the real adapter, PTR9 guard, Contract Runtime, wire schema, business completeness and domain validators without provider dispatch. The 18-case failure matrix passed.

Planning revalidation passed at 70 physical / 70 logical calls and at 71 physical / 70 logical calls with exactly one local business-incomplete rejection. Both runs and their independent third-copy replays produced artifact `0dc997a7770cbd267f7ae97c41da5a311f6e630236323f7266cdd56064d36133`. Every Full Short model stage has model-visible business requirements and structurally-valid/business-incomplete negative coverage.

The current Planning and Draft Skills resolve from the global root because neither repo nor current project overrides exist. This is expected fallback, not a resolver defect. The API/UI now distinguishes global, repo, project, effective source, source kind, fallback and exact package/document hashes. Runtime resolution and model-visible Skill bytes are unchanged; Selective/Hybrid remain inactive.

Focused: 99 passed. Related: 358 passed. Full suite: 4022 passed, 41 skipped, 6 xfailed, 226 failed, 199 errors. `tests.test_workflows` has the exact same 30 non-green test names as the pre-final-contract baseline; all other non-green families are historical sealed approval/hash/live-parity/oracle gates. New capture, business, Skill display and owning-source regression counts are zero.

Strict L3: `PASS`. Three independent final reviews: PASS.

HISTORICAL_CAPTURED_RESPONSE_REPLAY_REQUIREMENT_DISPOSITION=RETROSPECTIVELY_UNSATISFIABLE_FORENSIC_REQUIREMENT_WITH_PROSPECTIVE_REPLACEMENT
HISTORICAL_RAW_RESPONSE_BYTES_UNAVAILABLE_PROVEN=YES
HISTORICAL_RAW_BYTE_REPLAY_PERFORMED=NO
PROSPECTIVE_RESPONSE_CAPTURE_REPLAY=ENFORCED
SKILL_RUNTIME_EFFECTIVE_SOURCE=GLOBAL_FALLBACK_EXPECTED
SKILL_PAGE_SOURCE_TRUTH_DISPOSITION=RUNTIME_GLOBAL_FALLBACK_IS_EXPECTED
SKILL_PAGE_EFFECTIVE_SOURCE_DISPLAY=PASS
TRUSTWORTHY_FULL_SHORT_READINESS=YES
FULL_SHORT_PRODUCTION_SHAPED_DRY_RUN=PASS
FINAL_HEAD_BINDING_CLOSED=NO
FINAL_AUTHORIZATION_READY=NO
FULL_SHORT_EXECUTION_AUTHORIZED=NO
CREDENTIAL_LOOKUP_COUNT=0
REAL_PROVIDER_REQUEST_ATTEMPTS=0
NETWORK_CALLS=0
MODEL_CALLS=0
PAID_CALLS=0
FULL_SHORT=NOT_EXECUTED
EXACT_NEXT_GATE=FINAL_EVIDENCE_SEAL_THEN_EXTERNAL_AUTHORIZATION_MATERIALIZATION
