# SC-STANDARD-WINDOW-1 Final Report

## Outcome

- `workflow_final_outcome`: `WORKFLOW_TERMINAL`
- `short_completion_goal_outcome`: `WORKFLOW_TERMINAL`
- Next gate: `NARROW_FIX_REQUIRED`
- Exactly one real `short-normal-v1` workflow was executed. The cohort is consumed and was not replayed.
- No production source, Prompt, route, retry/fallback policy, validator, Final Review, Maintenance, Phase 1B setting, or live business artifact was modified.

## Fresh approval identity

- Branch: `sc-fp1/semantic-feature-flag-fingerprint-20260816`
- Execution HEAD: `6b4f55782b66f431a0d72f9ef0eec7c434690c05`
- Cohort: `short-completion-1-sc-standard-window-1-20260816t111727z`
- Window: `2026-08-16T11:32:28Z` to `2026-08-18T11:32:28Z`
- Plan canonical SHA-256: `16b14b1dd3c8ae63508f63be68201b3f01fc3e14fd76b333d6fc2550a93ba2da`
- Candidate canonical SHA-256: `67bd829e50dec3547403ec9c1aa2ac8e85e90b6fb228757052af50935733f1e1`
- Confirmed Authorization Patch SHA-256: `c19cadf7923d9970b7a6ed860840a2906295d7ff9c0d60e0c47bbe6e0408e60f`
- Signed Approval SHA-256: `b479c350db642ed71863cded9eeb0c7a5d12a77fc92114971cf9b787b71281c7`
- Candidate validate-only receipt SHA-256: `7e246576d9c560e73e5a9814ae46a849ecd60d257afac848d4a516bcce70b94e`
- Signed Approval validate-only receipt SHA-256: `8fa0715333a83e88edcd60bceea39ca04ce28dae99bff95519c8922f30c2d76a`
- Pre-launch rehearsal receipt SHA-256: `9c9b7741489023c1f1d333a54a2ceb80e7bc218e0e4e3b2d9f6d190922495d3b`
- Approval Ledger identity: `c90b5240ccd4d005104d41cf93742ff7f7078a0025fb2c142614bf9a9ee52439`
- Canary root identity: `5b2c0d37064b8205dc750fac764f6f1e0c7eb7da0cf052f1f568f3e18f0e0a34`
- Reservation receipt SHA-256: `ee35a93f90f5f8fc0af0fd4a8fb7a21b4a37bb58f3573f1a4d5449cdac83a622`
- Consumption receipt SHA-256: `55e5b6b2af9a96196d6a328755cd11fdad85f93f328fc5c249500268ab2b33c0`
- Approval state: `reserved -> consumed`; consumed evidence SHA-256: `e4f229b8416d40fdde94050a9ba08ee629aebcb42ca340dd6c9540e9a5ef2601`.

## Exact preflight

- Build: `3fab2deb66d00eb5ba33d3a98292a6ef65ed11cd1a416953388b772f317b2c3f`
- Execution Config semantic fingerprint: `2725078c0b0e56b8739bcff7d395081ac904fc4fb3d706b3b736ccd8d6bc5faa`
- Runtime Execution fingerprint: `65c3d484677a35ad69d3ccae5988be5dc6bfdef49e982632518d965ebc212b3e`
- Launcher: `ee54bea7193f2ffdb56864338e9dd336956303d93ca2a05ec3fe3876756cc78e`
- Workload: `c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1`
- Workload manifest: `80a37d9270f7d0dc5f4260e391b0c53d4232c1abda4b859d8dbaf11a07a018ae`
- Candidate and Signed Approval closures were `exact`; before Signed Approval validation, credential/provider-client/network/model/paid counters were all zero.
- Materialization and subprocess semantic hashes were equal to the approved semantic fingerprint. Provenance was known but unequal, classified exactly as `equivalent_provenance_variation`.
- Each of the 22 real boundaries revalidated Runtime identity as `exact`.

## Real model boundary and budget result

- Provider calls: 22
- Paid calls: 22
- Primary calls: 18
- Configured fallback calls: 4
- Protocol receipt route-failed events: 6
- Protocol receipt fallback events: 2
- Output-limit expansion events: 2
- Draft scoped regenerations: 2
- Separate Repair-stage calls: 0
- Reported input tokens: 104,621
- Reported output tokens: 66,837
- Cached input tokens: not reported by the captured provider observations
- Reasoning tokens: not reported by the captured provider observations
- Actual USD cost: 0.329173
- Actual CNY cost: 0.102241
- Elapsed: 1,051.536930 seconds
- Budget stop: none; every total remained below the Signed Approval ceiling.

The exact 22-row ledger, including ordinal, stage, role, controlled provider/model alias, full binding hashes, Primary/Fallback, protocol, requested output ceiling, finish reason, reported usage, per-call cost, response hash, system/user Prompt hashes, and result, is in `sc-standard-window-1-model-boundary-ledger-v1.json` (ledger SHA-256 `8f3019a3551d9f7900f0b8838f628228a33724efc2d09e989e99552cfe9b0f3b`). Provider and model names were intentionally not recorded; the report uses hash-derived controlled aliases.

## First divergent node and causal chain

The first divergent node was after model boundary 20:

`Draft primary response (end_turn/completed) -> authority-aware mixed-script prose validation -> reject_unapproved_mixed_script (3 decisions)`

Runtime then followed its existing bounded recovery path:

1. Boundary 20, initial Draft: 3 mixed-script rejections.
2. Boundary 21, scope retry 1: 1 mixed-script rejection.
3. Boundary 22, scope retry 2: 2 mixed-script rejections.
4. Recovery exhausted; workflow supervision became `irrecoverable` and the outer result became `WORKFLOW_TERMINAL`.

The Provider completed all three Draft boundaries normally with `end_turn`. This terminal was not caused by transport, Gateway shape, budget exhaustion, execution fingerprint mismatch, or live isolation failure.

- Outer safe failure class: `normal_invalid_output`
- Outer exception type: `ValueError`
- Stored incident family: `unclassified.8bff54965de2f818`
- Suggested failure family (observation only): `draft_authority_aware_mixed_script_rejection_exhausted`
- First-divergence receipt SHA-256: `cd7d11361bb26c17dfce99936ba5a3c3d1c594b6a8e473946e4d69325c2c2f7f`
- Next narrow task: `R1-D2_DRAFT_MIXED_SCRIPT_REJECTION_CLOSURE`

## Artifact and completion closure

- Draft validator final status: `unverifiable_or_not_passed`
- Mixed-script exemption result: no exemption was accepted; all three Draft versions were rejected.
- Last validated upstream checkpoint: `review-execution-segment-01-initial-1`, output SHA-256 `5bbe30899d219624ae55a62e2e79dd66d0581d86ea9e6630c4f1deb9b8a3bc0d`.
- Last Draft output SHA-256: `44b53f709affff313f60f50f8cc1d7e80b27e6ddd98f0cbdc897fc1a06d40f1e`; it passed the transport boundary only and was rejected semantically.
- Formal Candidate: none.
- Final manuscript: none.
- Final Review contract: `short_formal_quality_authority v1`; not reached, verdict `missing`, binding `unknown`.
- QualityCheckpointV1: absent; closure `unclosed`.
- Maintenance: not executed; receipt and ProjectMutationJournal absent.
- Final artifact binding: `unbound`.
- Final checkpoint closure: `unclosed`.
- Automatic resumability: not proven; workflow supervision is `irrecoverable`. Validated upstream checkpoints remain diagnostic evidence but do not authorize silent resume.

## Parity, privacy, and retained gaps

- Live parity before/after SHA-256: `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9` / same; status `exact`.
- Live active run count before execution: 0.
- Production incident count: unchanged; the isolated terminal was not counted as a production incident.
- Prompt policy, route bindings, and Runtime retry/fallback topology: exact and unchanged. Each system/user Prompt is represented only by SHA-256 in the boundary ledger.
- Raw Prompt, story prose, tool arguments, Credential, Header, Provider body, absolute path, live project identifier, and real project name are not included.
- Formal evidence package SHA-256: `e4f229b8416d40fdde94050a9ba08ee629aebcb42ca340dd6c9540e9a5ef2601`.
- Retained coverage gaps: provider/model names are unavailable by privacy design; cached and reasoning token fields were not reported; relay upstream exact version, relay public max output, and packaged-runtime execution remain unknown/not exercised.

No fix was performed. The cohort is consumed and cannot be replayed.
