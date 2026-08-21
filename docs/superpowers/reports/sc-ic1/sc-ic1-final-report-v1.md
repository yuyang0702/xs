# SC-IC1 — Canary Import Closure Repair Final Report

## Final Gate

`SC_IC1_CANARY_IMPORT_CLOSURE_REPAIRED`

The Fresh Short generic Canary import closure is repaired with `PROBE_MODULE_IMPORT_ISOLATION_V1`. The generic launcher no longer treats the unreachable PTR4/PTR7 standalone real-probe executables as part of its static import graph, and it still approves zero third-party dependencies. Explicit PTR4 and PTR7 scopes retain validation of their own executable and dependency set. Unknown profiles, missing/unapproved dependencies, and a newly reachable excluded probe fail closed.

## Baseline and Scope

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- HEAD: `7cdb7444902d0737f8cc9094992f7ef9bdb1e946`
- Production diff: `0`
- `baml_src/**` diff: `0`
- Prompt/Model/Route/Retry/Fallback/Budget/Validator changes: `0`
- Production Runtime changes: `0`

SC-IC1 changed only:

- `tools/canary/hash_manifest.py`
- `tests/canary/test_hash_manifest.py`
- `tests/canary/test_sc_ic1_import_closure.py`
- `docs/maintenance.md`
- `docs/superpowers/reports/sc-ic1/**`

The six pre-existing untracked `docs/superpowers/reports/r1-ptr10/**` files were preserved and not modified.

## Root Cause and Repair

Before repair, Fresh Short called `validate_import_closure(tools/canary)`, which recursively scanned every Canary Python file. This incorrectly included `provider_reasoning_capability_probe_real.py`; its legitimate probe-only `httpx` import then failed the generic zero-third-party closure.

The repair defines three exact scopes:

- `generic_canary_launcher_v1`: excludes both standalone real-probe executables and approves no third-party package.
- `r1_ptr4_provider_capability_probe_1`: includes the PTR4 real probe, excludes PTR7, and approves no third-party package.
- `r1_ptr7_provider_reasoning_capability_probe_1`: includes the PTR7 real probe, excludes PTR4, and records `httpx` only for this explicit scope.

This is not a whitelist bypass. Included modules are AST-checked; if one imports an excluded executable, validation stops with `excluded_module_reachable`. Unknown profiles stop with `import_closure_profile_unknown`, and undeclared dependencies remain `dependency_not_approved`.

## Validation

- Hash-manifest unit suite: `12 passed`
- Focused Fresh Short/launcher cluster: `18 passed`
- Related probe/Short regression cluster: `51 passed`
- Full offline business suite: `2651 passed, 39 skipped, 1 deselected, 6 xfailed`
- Syntax compilation: passed
- `git diff --check`: passed
- Import-time network sentinel: `0`
- Fresh Short base validate-only import closure: `exact`
- Production import graph: unchanged
- Privacy scan: exact

## Independent Next Blocker Disclosure

SC-IC1 fixes the launcher import-closure blocker only. When the full historical Short materialization tests continue beyond this repaired boundary, they stop at `ptr3_successor_source_mismatch`: the sealed PTR9 implementation changed production source bytes while the historical PTR3 successor fixture still binds the earlier source baseline. That parent-evidence mismatch is independent of SC-IC1 and was not altered, bypassed, or concealed. Therefore no Fresh packet was materialized in this task.

The historical PTR4 materialization test also retains its independent `R1_PTR4_PROBE_MAT_NO_GO_PROBE_DEFINITION_INCOMPLETE` gate; its explicit import scope is nevertheless validated by the new closure tests.

## Required Explicit Status

- `REAL_PROVIDER_CALLS=0`
- `CREDENTIAL_CALLS=0`
- `PROVIDER_CLIENT_CALLS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `FULL_SHORT_CANARY=NOT_EXECUTED`
- `FRESH_PACKET=NOT_MATERIALIZED`
- `SIGNED_APPROVAL=ABSENT`
- `CONFIRMED_PATCH=ABSENT`
- `PRODUCTION_RUNTIME=UNCHANGED`

Completed and stopped. No Provider, Short Canary, approval, or Fresh packet was executed or materialized.
