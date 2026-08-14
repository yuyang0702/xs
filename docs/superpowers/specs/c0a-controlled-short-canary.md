# C0A — Controlled Short Canary Launcher

## Scope

C0A is a non-production, fake-boundary validation harness. It may execute the
real Short workflow, Contract Runtime, parsers, adapters, validators, artifact
writers, and registered API endpoint handler. It must not read credentials,
construct a real provider client, use the network, make a paid model call, or
change production Runtime behavior.

The launcher lives under `tools/canary/`. Its executable dependency closure is
limited to that package, the approved production source fingerprint, the Python
standard library, and third-party modules explicitly named in the plan. C0A's
approved third-party list is empty. Dynamic import/code execution and imports
from tests or the canary execution root are rejected.

## Contracts

`CanaryExperimentPlanV1` is canonical JSON bound by `plan_sha256`. Its required
top-level fields are:

- schema, version, canonicalization_version, canary_mode, runtime_mode;
- approved build, execution-config, and runtime-execution fingerprints;
- runtime fingerprint policy version and launcher hash;
- workload manifest hash and workload definitions;
- provider descriptor, role binding, and approved route definitions;
- feature flag snapshot, isolation policy, budgets, stop conditions;
- report policy, dependency manifest, and plan hash.

The plan rejects credential material, raw prompts, prose, machine-specific
absolute paths, malformed hashes, enabled Phase 1B flags, and unapproved route
descriptors.

`CanaryPlanApprovalV1` is separately canonicalized and hash-bound. It requires:

- scope, approved plan hash, approved launcher hash;
- single-use cohort ID, expiry, execution window, maximum executions;
- unused/used status and consumed evidence hash;
- explicit action authorization for credential lookup, provider-client
  creation, network access, paid calls, and fake-boundary use;
- approval hash.

C0A approvals authorize only the fake boundary. Reservation uses exclusive file
creation in a ledger outside the execution root. Successful evidence consumes
the reservation; replay, expiry, scope mismatch, plan drift, launcher drift,
and window mismatch fail closed.

`CanaryEvidencePackageV1` contains hashes and controlled states only. It records
plan/approval/launcher bindings, outcome, Runtime fingerprints, origin/executor
binding, preflight receipts, the model-boundary and budget ledgers, zero-use
counters, live parity, isolated artifact hashes, performance, and coverage
gaps. A recursive scanner rejects raw prompts, prose, credentials, endpoints,
headers, and absolute paths.

## Two-phase model boundary

The first boundary follows one of two bounded paths:

```text
PARKED -> PREFLIGHT_RUNNING -> APPROVED -> RELEASED
PARKED -> PREFLIGHT_RUNNING -> BLOCKED  -> ABORTED
```

`asyncio.Event` coordinates the worker and launcher; there is no busy wait.
Gate wait timeout is independent from provider timeout. Timeout, launcher crash,
worker cancellation, or mismatch releases waiters and yields a stable Canary
reason code. It never creates a production incident.

Before every fake model boundary, the wrapper revalidates source bytes, build,
execution config, Runtime execution, launcher, plan, approval, fixture,
workload, provider/model descriptors, role/routes, flags, origin/executor,
sidecars, root sentinel, and remaining call/token/cost/time budget. Any change
blocks before delegation.

## Budget and stop semantics

The atomic ledger reserves call count, estimated input tokens, maximum output
tokens, estimated cost, and elapsed budget before delegation. Primary,
fallback, protocol retry, repair, review, maintenance, regeneration, and resumed
calls must each reserve independently. Missing provider usage retains the
conservative reservation. A lock prevents concurrent oversell.

C0A stops on the first terminal workflow outcome, fingerprint mismatch, budget
exhaustion, network attempt, credential lookup, or provider-client creation.
Its monetary budget is exactly zero.

## Isolation and network policy

The execution root has a versioned sentinel binding stable root identity, plan
hash, namespace, and creation policy. Validation resolves the real path,
rejects reparse points/symlinks/junctions, checks bidirectional non-overlap with
live roots, and enforces isolated DB, project, log, trace, sidecar, and report
subdirectories. On Windows, execution roots over the tested safe path budget
are rejected before creation.

The fail-closed sentinel intercepts DNS and socket resolution, connection, and
send entry points for the entire application/model execution interval. Its
counter must remain zero.

## Outcome taxonomy

- `CANARY_BLOCKED_PRE_PROVIDER`: packet, fingerprint, budget, root, route, or
  policy rejected before provider delegation.
- `CANARY_STARTED`: an authorized cohort has started.
- `WORKFLOW_COMPLETED`: the workflow reached its normal completed state.
- `CONTROLLED_NONTERMINAL`: a permitted waiting/resumable state.
- `WORKFLOW_TERMINAL`: a workflow failure after an authorized start.
- `CANARY_INFRASTRUCTURE_FAILURE`: launcher/harness failure, excluded from model
  and Runtime terminal rates.

All C0A outcomes set `production_incident_counted=false`.

## Operator sequence

1. Confirm the production source, launcher, fixture, and configuration are
   stable and the live database has no active run.
2. Generate an exact fake-only Plan and single-use Approval with
   `python -m tools.canary.packet`.
3. Pass the Plan hash independently to `python -m tools.canary.launcher` with
   `--dry-run`, an unused isolated root, and an external approval ledger.
4. Accept only `WORKFLOW_COMPLETED`, exact live parity, exact per-boundary
   fingerprints/bindings, zero credential/client/network/paid counters, and a
   consumed approval bound to the evidence hash.
5. Preserve only sanitized evidence. Never promote the C0A approval to C0B.

## Rollback

Revert the three C0A commits independently. The launcher is outside production
source and no database migration is introduced. Isolated run/control/ledger
directories can be archived or removed after evidence retention; live artifacts
need no rollback because they are read-only and parity-gated.
