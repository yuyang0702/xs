# SC-SUCC1-V2 — Current PTR3 Successor Evidence Rebinding / Regeneration

Gate: `SC_SUCC1_CURRENT_PTR3_SUCCESSOR_EVIDENCE_READY`

## Baseline and scope

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Parent/current task baseline HEAD: `d8fc9f4ddb13375c7c3d70c7d5adbdfed5298fc9`
- Worktree at task start: clean
- Risk level: L3; strict change gate passed with zero warnings and blockers
- Production Runtime diff: 0
- BAML diff: 0

The implementation changes only the Canary evidence binding. It does not alter
Prompt, Model, Route configuration, Retry/Fallback production policy, output
budget, validator, Canon, StoryState, READY authority, Draft, Final Review, or
Maintenance runtime behavior.

## Exact mismatch and closed lineage

Historical artifact:
`tests/fixtures/reliability/r0f/r1-ptr3-authorized-protected-source-successor-v1.json`

- Historical SHA-256: `bcba49fe1b20f1b4cb1f9284b181ede224bb860ce367870e9f3c46152cedda6c`
- Historical Git blob: `7683bc7298dca118c53f5a72cdcc4a85cba26887`
- Historical report tree: `f2c9f4a32d26f6b9ab64838fbf58aec1109ee1ba`
- Historical implementation: `a6d16638bdc55c5639979be7e2b50ffb0d927461`
- Historical expected protected-source aggregate: `ead7727bae076daefc807e1316fb2cf6caa688192f31e45dc214326db92a5f8a`
- Current actual protected-source aggregate: `71446b917737904cef05760c1c06da570bafb5677e0e91f0715958d08b999513`

The exact semantic source mismatch is two files:

1. `src/novel_flywheel/contract_runtime.py`: historical `d925037b...56ce0`, current `aab9f420...6eb4`
2. `src/novel_flywheel/models.py`: historical `ad1d4f31...3fa4`, current `20932272...03220`

Both current byte sets were introduced by sealed PTR9 commit
`7cdb7444902d0737f8cc9094992f7ef9bdb1e946`. PTR10 commit
`57915cf68bac8e825c12f1761f555e6024e1020d` is evidence-only and SC-IC1
commit `d8fc9f4ddb13375c7c3d70c7d5adbdfed5298fc9` is Canary control-plane
only; neither changes production bytes. The ancestry from PTR3 implementation,
PTR3 evidence, PTR8 parent, PTR9, PTR10, and SC-IC1 is exact. There is no
unauthorized source drift.

The old erroneous comparison was in
`tools/canary/ptr3_readiness.py::_successor_evidence`: each hash in the
historical artifact's `current_protected_sources` was compared directly with
the current worktree, raising `ptr3_successor_source_mismatch`. It compared two
authorized but different eras as if they were one snapshot.

## Fresh current successor

- Schema: `R1PTR3CurrentRuntimeSuccessorV1`
- Profile: `ptr3_successor_current_runtime_v1`
- Definition SHA-256: `07341e86e4ab78217cb5efe19bc0ce5d369f35fe4eaa0d0d921e3202f188ecea`
- File SHA-256: `4f4b02055f6f1902701d78e4ef478cf554645127f501ce271b8cc9366b425a1a`
- Build: `38ac099757dba906bcbe7d523fe2dd3f664193f2b5ffd3ecae559a17fdedcce4`
- Config: `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`
- Runtime: `3a3c8ec80924c2124cd84b745c1d9d2972c9dad2c48351a9f5b6d8044e75d68c`
- Prompt Policy: `82f73e6e9e90788feaa9cea0726e71a239960bead2b0c953ce5517e652dc736a`
- Provider descriptor: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`
- Role binding: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`

The new validator requires immutable historical evidence and a separately
sealed current successor. It verifies current production source bytes, sealed
ancestry, PTR9/PTR10/SC-IC1 parent manifests, semantic receipts, exact
Build/Config/Runtime/Prompt/Planning route-model identities, and zero external
actions. Stale evidence, unknown profiles, altered sources, broken ancestry,
wrong HEAD/fingerprints, failed semantics, and unrelated seal paths all fail
closed. No mismatch is ignored or whitelisted.

## Semantic and compatibility results

PTR3 semantic revalidation passed all 18 mapped requirements: exact same-scope
finding propagation, bounded rule/path/invariant payloads, fresh replacement,
`stale_finding_count=0`, deterministic dedupe/escaping, pre-Provider invalid and
oversize rejection, unchanged initial/first-repair contracts, active Domain
validator and merge closure, and unchanged retry/fallback and provider/route
identity semantics.

- PTR9 compatibility: PASS. Negative capability, route exclusion, alternate
  route, and typed fail-close preserve finding identity/evidence.
- PTR10 compatibility: PASS. Guard recovery invariants and source baseline stay exact.
- SC-IC1 compatibility: PASS. `PROBE_MODULE_IMPORT_ISOLATION_V1` changes only
  Canary import closure and does not change Planning repair semantics.
- Live parity: exact (DB, formal manuscript, Canon, StoryState/candidate/checkpoint counts).

## Validation

- Focused successor/semantic/Guard/import cluster: `63 passed`
- Related Short materializer/profile/verification cluster: `58 passed`
- Full offline business suite: `2651 passed, 39 skipped, 1 deselected, 6 xfailed`
- Strict L3 gate: passed; warnings 0; blockers 0
- Privacy scan: exact
- `git diff --check`: passed
- Production and BAML diff: empty

The related materializer tests used pytest temporary directories only. No Fresh
Short packet, cohort, ledger, Signed Approval, or Confirmed Patch was created in
the repository.

## Changed paths and sealing

Implementation:

- `tools/canary/ptr3_readiness.py`

Tests:

- `tests/canary/test_ptr3_successor_readiness.py`
- `tests/canary/test_sc_succ1_current_successor.py`

Support documentation:

- `docs/maintenance.md`

Evidence:

- `docs/superpowers/reports/sc-succ1/**`

The worktree is intentionally dirty with only those SC-SUCC1 paths. No commit
was created. `SC_SUCC1_SEAL_REQUIRED=YES`.

## Required declarations

`HISTORICAL_PTR3_EVIDENCE_UNCHANGED=YES`  
`CURRENT_SUCCESSOR_EVIDENCE_FRESH=YES`  
`SOURCE_LINEAGE_EXACT=YES`  
`PTR3_SEMANTICS_REVALIDATED=YES`  
`PTR9_COMPATIBILITY=PASS`  
`PTR10_COMPATIBILITY=PASS`  
`SC_IC1_COMPATIBILITY=PASS`  
`PRODUCTION_RUNTIME_CHANGED=NO`  
`BAML_CHANGED=NO`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`  
`FRESH_PACKET=NOT_MATERIALIZED`  
`SIGNED_APPROVAL=ABSENT`  
`CONFIRMED_PATCH=ABSENT`
