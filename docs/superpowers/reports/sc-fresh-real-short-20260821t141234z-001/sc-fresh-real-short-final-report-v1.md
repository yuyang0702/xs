# SC-FRESH-EXEC — Full Short Completion Canary Final Report

## Decision

`SC_FRESH_REAL_SHORT_TERMINAL`

`FINAL_CLASSIFICATION=NARROW_FIX_REQUIRED`

Exactly one authorized `SHORT_COMPLETION_SINGLE_REAL_PROVIDER_CANARY` was executed through the canonical production-mirror launcher. It stopped at the first workflow terminal. It was not retried, resumed, or followed by a code/configuration change.

- Workflow final outcome: `WORKFLOW_TERMINAL`
- Short completion goal outcome: `WORKFLOW_TERMINAL`
- Reason code: `isolated_short_workflow_terminal`
- Typed root cause: `ContractOutputLimitExhaustedError`
- Safe failure class: `output_limit`
- Formal goal `SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED`: not reached

## Required execution identity

1. Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
2. Execution starting HEAD: `373b566d99770f060a4b2e0f479dfd54bc1357d7`
3. Final HEAD before evidence sealing: `373b566d99770f060a4b2e0f479dfd54bc1357d7`; final evidence persistence identity is the evidence-only commit containing this report and its manifest.
4. Cohort: `short-completion-fresh-v2-20260821t055917z-001`
5. Window: `2026-08-21T06:14:17Z` to `2026-08-23T06:14:17Z`
6. Preflight: `exact`; 38/38 signed closure checks exact, live active run count 0, worktree clean, canary root absent, ledger unused.
7. Authorization binding: `exact`; Signed Approval `ec59a33c4f223b960df3cf98119ccd4768753f8edcc6f4fe6c1a055fc1aad9df`, Confirmed Patch `e6c029fa12100d0388a1aacbb9a6b5c2fa759e6e64ccf3901734f3d8829c5307`, signed validate-only `885488728a5466401798ae5caa4ec47688de10cf26565119a8124d6482d4ba46`.
8. Run count: `1 / 1`.
9. Network calls: `12`.
10. Provider/model calls: `12`.
11. Paid calls: `12`.
12. Provider-reported known input tokens: `6,210`; six primary receipts reported zero and are not interpreted as proof of zero actual input. Reserved input envelope: `18,363`.
13. Provider-reported output tokens: `70,992`; reserved output envelope: `99,735`.
14. Known reconciled USD cost: `0.198075`; conservative retained reservation: `0.250991`.
15. Known reconciled CNY cost: `0.157623`; conservative retained reservation: `0.283247`.
16. Elapsed: `1,304.835168 seconds`.
17. Hard-cap usage: calls `12/48`, input reservation `18,363/1,000,000`, output reservation `99,735/1,000,000`, per-call maximum requested `15,548/32,000`, USD and CNY below cap, elapsed below `7,200`; no budget stop.

## Stage progression and terminal

18. Stage progression: Planning `FAILED_TERMINAL`; Planning Repair `ENTERED`; Causal/Manifest, Draft, Draft Repair, Semantic Review, Quality, Final Review, Maintenance, Final Artifact, and Final Checkpoint `NOT_REACHED`.
19. First divergence: Boundary 1 returned `end_turn`, but its Planning `planning_semantic_v2` candidate failed semantic validation.
20. First unrecovered divergence: Planning never produced a domain-valid candidate after the sealed bounded recovery schedule. Nine conversion audits were produced: eight `semantic_validation_failed`, one `output_truncated`, zero domain-valid.
21. Terminal boundary: ordinal 12, Planning, configured fallback route fingerprint `04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31`, `finish_reason=max_tokens`, requested and reported output `8,798`, zero extractable response bytes, then `ContractOutputLimitExhaustedError`.
22. Planning: `FAILED_TERMINAL`; no first real Planning pass.
23. Draft: `NOT_REACHED`; no first real Draft entry.
24. Final Review: missing and not accepted.
25. Maintenance: not executed; closure incomplete.
26. Final Artifact: absent and unbound; manuscript SHA is null.
27. Final Checkpoint: absent and unclosed.

## PTR9, PTR3, and R1-D3 observations

28. PTR9 Guard exercised: `NO` for the exact reasoning-only predicate. Guard code/baseline was exact and enabled, but the canonical sanitized boundary only exposed `max_tokens` plus zero extractable bytes; pre-normalization reasoning shape was not available at the typed detector.
29. Negative capability written: `NO`; isolated `structured_route_qualifications` row count was `0` after the run.
30. Alternate route used: `YES`; the existing configured fallback was used six times. No route or model configuration was added or changed.

This is an evidence-based inference: because the Provider reasoning/content-block shape was unavailable at the guard decision point, the exact PTR9 predicate did not fire. The run reached the legacy output-limit terminal instead. The narrow follow-up family is to preserve the sanitized Provider output-shape receipt through normalization to the existing PTR9 guard, without changing Prompt, Model, Route, retry/fallback, or token budgets. No such fix was implemented here.

31. PTR3 exact finding propagation exercised: not evidenced by this canonical profile; targeted receipt count `0`.
32. R1-D3 Draft retry propagation exercised: `NO`; Draft was not reached.
33. `stale_finding_count`: not observed and not asserted as zero.
34. Final manuscript/artifact identity: `null` because no formal artifact exists.

## Isolation, privacy, ledger, and repository state

35. Live parity: `exact`; before and after `1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`.
36. Privacy: exact after final scan; raw Prompt, raw story, raw tool arguments, raw Provider content, credentials, and headers are excluded.
37. Official canonical evidence SHA: `0bf558fba6a6ffaff2eec512bd4711eb12422b8a16b5b91ac33b1e578a5ce028`; the file-byte SHA manifest is included in this evidence directory.
38. Ledger final state: reservation definition `a8c1f776775759d3bef9740c1e91fb16760959e966cc8bd848406830b5992223`; consumption definition `c6635e19c162a799ab725e0e0e25ea6029164abc245e411005a3bb145facab41`; consumed evidence is the official evidence SHA above.
39. Usage final state: `consumed_terminal`; it must never return to unused.
40. Worktree before evidence persistence: only the two ledger receipts and this evidence package were untracked; no unrelated or production modification existed. After sealing, worktree is required to be clean.
41. Production diff: `0`.
42. BAML diff: `0`.
43. Second run: `NOT_EXECUTED` and permanently forbidden for this cohort.
44. Resume: `NOT_EXECUTED` and forbidden after terminal.

## Stop

No automatic fix, new approval, second Canary, resume, Long workflow, Pilot, Provider probe, or production mutation was performed.

`FULL_SHORT_CANARY=EXECUTED_ONCE`  
`SHORT_WORKFLOW_COMPLETED=NO`  
`RUN_COUNT=1`  
`SECOND_RUN_EXECUTED=NO`  
`RESUME_EXECUTED=NO`  
`NO_AUTOMATIC_FIX=YES`  
`PRODUCTION_RUNTIME_CHANGED=NO`  
`BAML_CHANGED=NO`  
`SC_FRESH_REAL_SHORT_TERMINAL`
