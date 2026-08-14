# R0 Short Post-Fix Reliability Validation

## Scope

R0 is a read-only reliability validation stage. It replays or characterizes
historical Short workflow incidents against the current Runtime without
changing production behavior. No file under `src/novel_flywheel`, no prompt,
retry/fallback policy, parser, adapter, validator, supervisor, checkpoint, or
incident classifier may change in this stage.

Only test support, sanitized fixtures, hash-only manifests, and reports are in
scope. Every replay uses a temporary database, an isolated project, a
`r0-replay-*` run namespace, and a deterministic provider replacement.

## Fix epochs

All event times are normalized to UTC before comparison with Git commit times.

| Epoch | UTC boundary | Meaning |
| --- | --- | --- |
| `pre_fix` | before `2026-08-12T04:06:08Z` | Before V3 migration commit `5a517355` |
| `migration_window` | from `5a517355` to `b49d87bd` | Runtime convergence was in progress |
| `post_declared_pre_hardening` | from `b49d87bd` to `d22a28f` | V3 was declared complete, but the later hardening commit was absent |
| `post_hardening` | at or after `d22a28f` | Event time is after the current hardening boundary |
| `unknown_time` | timestamp cannot be proved | No epoch is inferred |

An event-time epoch never proves the deployed Runtime build. A verified
post-fix Runtime incident additionally requires a persisted source commit or
Runtime fingerprint. Otherwise `runtime_build_status` remains
`unknown_runtime`.

## Historical identity

The manifest preserves both historical storage and current read-time
classification:

- `stored_incident_key`;
- `stored_historical_family`;
- `current_reclassified_family`;
- `incident_catalog_version`;
- `reclassification_reason`.

R0 never rewrites historical database rows or silently substitutes the current
catalog identity for the stored identity.

## Replayability

- `exact_replayable`: the exact provider text is bound to the failed attempt,
  contract, and route. A raw file without attempt binding is insufficient.
- `structurally_reconstructable`: deterministic evidence proves a minimum
  isomorphic failure fixture. The fixture is always labelled synthetic.
- `static_path_verifiable`: current code proves a reachable path, but no
  executable recovery claim is made.
- `insufficient_evidence`: neither execution nor a unique static conclusion is
  justified.

Exact historical text stays outside the repository. Committed fixtures contain
only sanitized topology, hashes, codes, counts, and synthetic content.

## Recovery levels

Every executable result records these independent fields:

- `boundary_recovered`;
- `stage_recovered`;
- `workflow_recovered`;
- `controlled_nonterminal`;
- `final_terminal_outcome`.

Parser, adapter, or schema acceptance alone is not workflow recovery. The
conservative recovered/controlled metric includes only a completed workflow,
`waiting_provider`, `waiting_user`, or a resumable failure with a valid
checkpoint. If a target failure is recovered but another family terminates the
workflow, the result is `STILL_TERMINAL_DIFFERENT_FAMILY` and retains both
failure nodes.

## Post-fix exposure denominator

The report separately measures post-`b49d87bd` and post-`d22a28f` Short
production exposure:

- workflows started and completed;
- model stage attempts;
- local normalization attempts and successes;
- protocol retry attempts and successes;
- configured fallback attempts and successes;
- controlled waiting/resume outcomes;
- terminal failures.

Zero terminal incidents without sufficient started workflows and stage
attempts is reported only as: **no new terminal incident was observed, but
production exposure is insufficient**.

## Stage coverage matrix

Planning, Causal, Manifest, Draft, Semantic Review, Quality, Maintenance, and
Repair are assessed independently for completeness/truncation checks, local
normalization, schema/adapter/domain validation, retry/fallback parity,
secondary-repair re-entry, root-cause preservation, and sibling bypasses.
Missing incident evidence remains `unknown`.

## Isolation and parity

Replay output cannot enter `data/app.db`, the existing production incident
count, or any live project artifact. Before and after hashes cover the live
database, formal manuscript, StoryState, Canon, Candidate, Checkpoint, and Saga
surfaces. Paid model calls are forbidden and are guarded by fail-closed test
providers.

## Acceptance

- 123/123 manifest rows;
- 26/26 high-frequency incident results;
- every A/B incident executes through the current production Runtime boundary;
- all six current unclassified incidents receive individual evidence reports;
- paid calls are zero;
- live parity is exact;
- the full suite adds no failure;
- `src/novel_flywheel` remains unchanged.

R0 ends with evidence and a Development GO/NO-GO recommendation. It does not
authorize any Runtime repair.
