# Segment 2 transport exact replay — pre-authorization final report

Branch `r1-ptr3/planning-repair-finding-propagation-20260817`; START_HEAD `0c975f076ca245dd847c5205b1e040c23ae54f2a`; reviewed source HEAD `fc5cb3f42c13561c2861adc346555ee9e6e2e92a`.

The immutable Segment 1 transport SHA is `4bb0489d3ed9d4cacefa495b5627931c21d2ef0878402da32572121350914879`; its exact replay produced Contract Runtime input SHA `82ec9df51e775b4f65eabf0abc475d57735fe32152e03f620f32191c914ff76a`. The immutable Segment 2 transport SHA is `59afe3d76435b3d2651da53c05f0bd96ea347a669474d3384f43acb7b64c2d7b`.

Segment 2 contains 3,719 valid SSE events and terminates cleanly at `message_stop` with `stop_reason=max_tokens`. It has no provider error event and no complete final artifact: the sole content block is thinking. The production guard raises `ReasoningOnlyFinalArtifactUnavailableError`, wraps it as `FinalArtifactCapabilityExhaustedError`, and now maps it to `output_truncation` while durably closing the pre-contract attempt. No Contract Runtime input is fabricated.

The systemic repair validates terminal capture state before any local replay, keeps parser/adapter/business failures out of the generic transport family, persists only bounded failure projections, and preserves authority mutation until a validated stage receipt. The recovery policy is `EXACT_REPLAY_ONLY`: a complete-valid capture may replay locally with the same call/capture identity and no nonce or dispatch; explicit provider error, proven pre-response failure, and ambiguous completion all fail closed with zero redispatch. The sealed workflow has 70 logical stages and physical/provider/HTTP/network hard caps of 71.

The offline production-shaped normal, business-incomplete, and adapter-fault runs all completed every required stage and produced the same artifact SHA `0dc997a7770cbd267f7ae97c41da5a311f6e630236323f7266cdd56064d36133`. Genuine provider-unavailable and ambiguous-completion injections failed closed without authority mutation or redispatch. The 13K/20K/30K matrix passed.

Three final independent reviews passed. Strict L3 passed with zero warnings and zero blockers. Privacy, determinism, production isolation, Baseline Skill identity, and Hybrid model invisibility passed. All task-owned regression counts are zero; the 28 non-green workflow tests reproduce at START_HEAD and are documented fixture/contract drift outside this change.

This evidence seal authorizes no external action. A new authorization must be materialized outside Git only after the final evidence commit and must bind the resulting final HEAD. The runner must stop at disabled-actions preflight before credential lookup, approval activation, nonce consumption, or network access.

PRIMARY_ROOT_CAUSE=TRANSPORT_COMPLETE_REASONING_ONLY_MAX_TOKENS_WITHOUT_FINAL_ARTIFACT; PRE_CONTRACT_DURABLE_REJECTION_TRANSITION_MISSING; MODEL_ROUTES_EXHAUSTED_UNKNOWN_CHILDREN_DEFAULTED_TO_TRANSPORT
SEGMENT_1_EXACT_REPLAY=PASS
SEGMENT_2_EXACT_REPLAY=PASS_TYPED_REJECTION
FULL_SHORT_TRANSPORT_RECOVERY_POLICY=EXACT_REPLAY_ONLY
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
EXACT_NEXT_GATE=FINAL_EVIDENCE_COMMIT_THEN_NEW_EXTERNAL_AUTHORIZATION_PREFLIGHT

