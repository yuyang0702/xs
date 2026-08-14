# R0 — Short Post-Fix Reliability Validation

## Decision

**Development NO-GO.** The current Runtime recovers all 26 controlled high-frequency reconstructions, but this does not close production reliability:

- there are no post-`d22a28f` production short workflow starts;
- 97 historical terminal incidents across 44 residual families were not executable with exact attempt-bound evidence;
- Short Maintenance normal/window output still bypasses `execute_contract_runtime`;
- Repair coverage is mixed rather than uniform.

No Runtime or production business code was changed in R0.

## Audit baseline and scope

- Implementation baseline: `09d7cfd322f677f73d14c33b7b66e4bce05b7a47`.
- Historical corpus: read-only `data/app.db`, 123 terminal short incidents.
- Incident catalog version: `sha256:911b430c7161280f4392eb123a51c23985dc523b7852359adf0f395790c36060`.
- Exact replayable: 0; structurally reconstructable: 26; static-path-verifiable: 62; insufficient evidence: 35.
- Replay execution: temporary DB, isolated project copy, `r0-replay` logical namespace, deterministic fake provider.
- Paid LLM calls: 0.

## Incident corpus result

All 123 incidents have one manifest row. Every row preserves both stored identity and current read-time identity:

- `stored_incident_key` and `stored_historical_family` are retained when present;
- `current_incident_key` and `current_reclassified_family` are recorded separately;
- reclassification reason and catalog version are explicit;
- no historical classification is silently rewritten.

The 26 accepted high-frequency rows are exactly:

| Incident key | Historical count | Validation |
| --- | ---: | --- |
| `short-story:failed:planning.structure_drift` | 15 | Synthetic family-shaped failure followed by current Runtime; 15/15 full workflows recovered |
| `short-story:failed:parser.generated_artifact_shape` | 11 | Synthetic family-shaped transport payload through current Runtime; 11/11 full workflows recovered |

Two additional `planning.structure_drift` rows have `unknown-stage` keys and are not silently included in 26/26. They remain residual historical terminals.

The executed 26 produced 379 deterministic model-stage calls and 41 Planning attempts. The 15 structure-drift cases each created a rejected conversion audit followed by a valid exact conversion. Protocol fallback attempts were 0. Every conservative recovery field is true only because the whole workflow completed:

- `boundary_recovered=true`;
- `stage_recovered=true`;
- `workflow_recovered=true`;
- `controlled_nonterminal=false`;
- `final_terminal_outcome=WORKFLOW_RECOVERED`.

No result is inferred from parser/schema success alone.

## Fix epoch and exposure denominator

Epochs use UTC event time and keep Runtime build verification separate:

| Epoch | Boundary | Started | Completed | Stage attempts | Local normalize attempts/success | Protocol retry attempts/success | Fallback attempts/success | Controlled wait/resume | Terminal |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |
| post-`b49d87bd` | 2026-08-12 15:06:11 | 1 | 0 | 20 | 0/0 | 6/0 | 5/0 | 0 | 1 |
| post-`d22a28f` | 2026-08-13 06:05:12 | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | 0 | 0 |

The one event between `b49d87bd` and `d22a28f` is recorded as:

- `event_time_epoch=post_declared_pre_hardening`;
- `runtime_build_status=unknown_runtime`.

It is not labeled a verified post-fix production failure. The correct conclusion is: **no new terminal incident has been observed after `d22a28f`, but production exposure is insufficient.**

Coverage gaps: legacy normalize attempts are absent when no adapter audit exists; fallback success is unknown unless a legacy receipt binds `fallback_used`.

## Short Stage Coverage Matrix

The matrix is source-checked with AST assertions on whether each `_stage` call supplies `execution_spec`.

| Stage | Unified Contract Runtime | Completeness / truncation | Local normalize | Schema / Adapter / Domain | Retry / fallback | Repair re-entry | Sibling bypass | Incident evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Planning | yes | yes | yes | yes | yes / yes | partial | yes | 26 synthetic workflows |
| Causal | yes | yes | yes | yes | yes / yes | n/a | no | unknown |
| Manifest | yes | yes | yes | yes | yes / yes | yes | no | unknown |
| Draft | partial | yes | n/a for prose | partial | partial / yes | yes | yes | unknown |
| Semantic Review | yes | yes | yes | yes | yes / yes | yes | no | unknown |
| Quality | yes | yes | yes | yes | yes / yes | yes | yes | unknown |
| Maintenance | **no** | yes | after-stage only | after-stage only | manual / role-fallback | manual second attempt | yes | unknown |
| Repair | **partial** | yes | partial | partial | partial / partial | partial | yes | unknown |

Concrete source paths:

- Planning: `WorkflowService._plan_short_ir_first` → `_stage` → `execute_contract_runtime` (`workflows.py:4953`, `contract_runtime.py:803`).
- Causal: `_ensure_short_causal_chain` → `_stage` with a structured spec (`workflows.py:14102`).
- Manifest: `_generate_short_execution_fragment` and `_review_short_execution_fragment` → `_stage` with structured specs (`workflows.py:14654`, `14940`).
- Draft prose: `_draft_short_segment_task` → `_stage` without a structured spec; semantic receipts later use `_verify_draft_semantic_node` and `_verify_whole_draft_semantics` with specs (`workflows.py:23928`, `21895`, `22410`).
- Quality: `_reader_review` and structured review escalation use registered specs (`workflows.py:18937`).
- Maintenance: `_close_short_maintenance_window` and `_close_short_maintenance_authority` call `_stage_with_role_fallback` without `execution_spec`, then locally convert/adapt/merge (`workflows.py:16526`, `16935`, `27311`).
- Repair: `_repair_short_revision_semantic_group` has a structured spec, while `_repair_polish_semantic_segment` calls `_stage` without one (`workflows.py:21483`, `21768`).

## Six primary-scope unclassified incidents

| Incident id | Current family | Epoch | Typed chain | Raw binding | Result |
| --- | --- | --- | --- | --- | --- |
| `r0-b2c6ed395bad574738d3` | `unclassified.25961779f5ca5900` | pre-fix | present | ambiguous multiple candidates | static current path only |
| `r0-2f3df4e27c4d75b9306c` | `unclassified.f112d3a44e361db9` | pre-fix | present | ambiguous multiple candidates | static current path only |
| `r0-f8482e3405d5ebda0db3` | `unclassified.9d8f418526544d08` | pre-fix | present | ambiguous multiple candidates | static current path only |
| `r0-5dd22b699f99af2aa213` | `unclassified.1fc57f72f339952b` | pre-fix | present | ambiguous multiple candidates | static current path only |
| `r0-df399434efc6c2888061` | `unclassified.14a09fac45b683bd` | migration window | present | ambiguous multiple candidates | static current path only |
| `r0-69887d2c16314e257c90` | `unclassified.14a09fac45b683bd` | post-declared/pre-hardening | present | ambiguous multiple candidates | static current path only; Runtime build unknown |

These are reported individually but are not claimed as exact replays.

## Replay isolation and live parity

All executable replay writes remained below a pytest temporary root. Every test used `replay-only.db`, a separate project tree and a shortened physical run id under the `r0-replay` logical namespace. Each case compared the live DB hash before and after.

Live parity after all focused, related and full-suite tests:

| Artifact | Before | After | Result |
| --- | --- | --- | --- |
| `data/app.db` SHA-256 | `5deb7bdf...ab87` | `5deb7bdf...ab87` | identical |
| Formal artifact manifest | count 1, `d6d6984c...25dd` | unchanged | identical |
| Canon manifest | count 1, `a699c476...f59f` | unchanged | identical |
| Candidate files | count 0, empty manifest hash | unchanged | identical |
| Checkpoint files | count 0, empty manifest hash | unchanged | identical |
| Saga files | count 0, empty manifest hash | unchanged | identical |
| StoryState rows | count 6, `a62872e1...0a95` | DB byte-identical | identical |
| Story candidates | count 11, `899790c6...b8db` | DB byte-identical | identical |
| Workflow checkpoints | count 917, `be89bc1f...c9f44` | DB byte-identical | identical |

The live formal file and Canon file retain modification timestamps from before the R0 baseline. `src/novel_flywheel` has no diff from `09d7cfd`.

## Tests

- Pre-change full suite: `2336 passed, 1 skipped, 5 xfailed`.
- R0 focused: `31 passed`.
- Related Contract Runtime / generated artifact / incident / supervisor tests: `144 passed`.
- Post-change full suite: `2367 passed, 1 skipped, 5 xfailed`.
- New failures: 0.

## Residual terminal families

One family (`parser.generated_artifact_shape`) is fully closed only for the 11 synthetic high-frequency rows. `planning.structure_drift` is partially closed because two unknown-stage rows remain non-executable. Overall, 97 incidents across 44 families remain historical terminal evidence without full current-workflow execution.

## Development gate

**NO-GO.** A development phase that claims uniform Short Runtime reliability should not start from this evidence alone. Minimum closure required before changing Runtime:

1. obtain real post-`d22a28f` short workflow exposure with Runtime fingerprints;
2. add execution evidence for Maintenance normal/window and Repair sibling paths;
3. bind more legacy terminal attempts to exact raw output/receipt/checkpoint versions, or explicitly retire them as unverifiable legacy;
4. preserve replay isolation and the current live-artifact parity gate.

R0 stops here. It does not modify Runtime, Prompt, retry/fallback, incident classification, checkpoint/resume or production business behavior.
