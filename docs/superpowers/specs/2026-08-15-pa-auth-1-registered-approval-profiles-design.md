# PA-AUTH-1 Registered Canary Approval Profiles

## Change Contract

- Requested outcome: add one fail-closed Approval Profile registry shared by
  Candidate, Patch, Signed Approval, validate-only, launcher, real runner and
  single-use ledger; retain exact C0B compatibility and add PA strict-tool
  observation support without executing a Canary.
- Scope classification: `closed_world`. The registry contains exactly two
  approved profiles: `c0b_smoke_1` and `pa_strict_tool_obs_1`.
- Authorization: implementation only. Real approver materialization, credential
  access, provider construction, network, paid calls, cohort reservation and
  execution are excluded.
- Current evidence: the PA plan/candidate is valid as inert material, but the
  only executable Signed Approval schema, closure and runner dispatch are
  C0B-specific. Offline launcher validation returns
  `approval_schema_mismatch` before Provider access.
- Allowed paths: `tools/canary/**`, `tests/canary/**`,
  `tests/fixtures/canary/**`, and `docs/superpowers/**`.
- Protected paths: `src/novel_flywheel/**`, `baml_src/**`, `pyproject.toml`,
  Production/Contract Runtime, adapters, Prompt, route, retry/fallback,
  planning adaptation, strict-tool decision, output budget, StoryState, Canon,
  Maintenance, Repair and Phase 1B.
- Authority impact: Canary approval authority changes. Formal manuscript,
  candidate promotion, StoryState, Canon, SQLite business rows, checkpoints,
  incidents and provider bindings remain read-only and byte-parity protected.
- Selected pattern: a finite, immutable `CanaryApprovalProfileV1` registry plus
  profile-specific validators behind generic deterministic dispatch. Scope and
  schema are registry data; launcher and ledger do not add scope string branches.
- Rejected alternative: adding `if scope == PA...` to launcher/runner, adapting
  the PA document to C0B schemas, or accepting arbitrary profile strings.
- Rollback: revert the PA-AUTH-1 commits. Historical C0B artifacts and hashes are
  not migrated or rewritten.
- Resolution target: `case_fixed`, because the user approved exactly two finite
  Canary profiles; no claim is made for arbitrary future Canary types.

## Material MUST traceability

1. Exact two-profile registry: immutable registry definition and registry tests.
2. Three distinct PA document types: PA contract module and mutation tests.
3. Deterministic profile-aware signing: generic dispatcher plus source/plan
   binding tests.
4. Launcher/runner dispatch: profile resolver and fake paid-boundary tests.
5. Profile-aware ledger: profile + signed hash + cohort reservation receipts,
   replay/cross-profile/consume tests.
6. PA validate-only: 28 ordered offline checks and zero-external-action tests.
7. C0B compatibility: existing C0B suites plus cross-profile rejection tests.
8. No business change: protected-path diff, runtime characterization, live hash,
   incident-count and full-suite parity evidence.
9. New PA material: new launcher-bound plan, candidate, patch template, window,
   cohort, receipt and preview; no Signed Approval.

## Stable invariants

- Unknown schema/profile/scope fails closed with a stable reason code.
- Candidate and Patch are never executable or reservable.
- Signed Approval copies every protected field from Candidate; only the reviewed
  authorization fields originate from the confirmed Patch.
- C0B and PA schemas cannot cross plans or scopes.
- Ledger replay identity includes registered profile and exact Signed Approval.
- PA runner flags are strict-tool trace on, budget lineage off and Phase 1B off.
- No model-output representation or acceptance boundary changes.

