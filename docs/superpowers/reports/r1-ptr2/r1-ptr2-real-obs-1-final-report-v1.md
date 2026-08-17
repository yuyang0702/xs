# R1-PTR2-REAL-OBS-1 Final Report

## Outcome

`R1_PTR2_REAL_OBSERVATION_BLOCKED_SIGNED_APPROVAL_CONTRACT`

The user authorization was materialized into an exact Confirmed Authorization
Patch and an exact `PlanningRepairObservationSignedApprovalV1`. The required
formal launcher validate-only then failed closed before any Provider boundary:

```text
outcome=CANARY_BLOCKED_PRE_PROVIDER
reason_code=validate_only_profile_not_supported
provider_boundary_entered=false
network_call_count=0
```

The Profile declares `planning_repair_observation_closure_v1`, but the launcher
validate-only dispatcher has no handler for that profile. The authorization
requires an exact signed validate-only result before Credential lookup, so no
`--real-run` command was issued.

## Authorization evidence

- Confirmed Patch domain SHA-256:
  `885176ec6e96b0749e0c94ffe9bcd3e53994f54a079ada45b7744cc92de52a92`
- Signed Approval domain SHA-256:
  `18e50ab7daf4eb5baa883382e19cade8971fe6d450152acea4bb55f58279a645`
- Signed validation receipt SHA-256:
  `2209e14fdc52effde2378a31053e43a95ad396032199aaa6a8fefc78894a8f1e`
- Typed contract materialization: exact
- Signed source binding: exact
- Signed Plan binding: exact
- Ledger: unreserved; Cohort: unused; business entries: zero

## Execution and evidence

- Final observation outcome: `NOT_EXECUTED`
- Target exercised: unknown / not executed
- Credential lookups: 0
- Provider clients: 0
- Provider/network/model/paid calls: 0 / 0 / 0 / 0
- Input/output tokens: 0 / 0
- USD/CNY cost: 0 / 0
- Canary root created: no
- Production incident counted: no
- Workflow terminal counted: no
- Domain rule/path/invariant evidence: absent because execution did not start
- Finding propagation: not observed
- Fallback shape: not observed
- Output-limit evidence: not observed
- Four real observer receipt SHAs: absent because execution did not start

The production repair budget policy remains
`a4afb20d6c93a9586f8b5f96b3457b1bc1eecfe22458fefcbdde956b2395325a`,
sequence `1977, 1977, 1977, 3954`, counterfactual disabled.

Because the stop occurred before the first Provider boundary, budget reserve,
Provider-client creation, and Provider dispatch after the unattained goal are
all zero. This is not evidence that the Planning target is absent or fixed.

## Bound identity and parity

- Build: `6a813386e6e0200c2a8f41a118748702f3eecd3d86117ec5cb7d58d341387d6e`
- Config: `2c362e4b864a0640e95bd13c219c6dc84ac961b36b7a93fc254d5027589e722b`
- Runtime: `8e3fc9d5fb271ee62f835ebc27165bf0b32254bf3c1f43e2d4b121a6d514413b`
- Prompt policy: `ebc77e335347f7c6927bd7d081f6be30e3f6e544e4167ddd9c49ec8441b388fd`
- Request manifest: `7f4d224c1c81e98e0b1b95b217414b8678b08ab8ca949cb399837236e363b852`
- Route/model: `b6a011ffe8991685ec8bbe88db629290fb8af6bfd8a798a9a0badf35434a760e`
- Provider: `63dd3656c56f6770bb35114d4c864ec8880780e5866ce33e2226d238cbf56e7f`
- Feature flags: `8de583b519cae87fd6114d24558ba49f2f964f33d6bf244bebba9a8f6f3e410c`
- Domain validator: `77111523e334421e7165af4af5fe59176ddd2e575ebb5fe7d2429e9cab05477a`
- Target filter: `3e7e25963eea65e85cabf20dc4da160e16448594981d8129956d018d0fd9a9e3`
- Observation Goal: `d9f4b956d9b9dd6906889830eb4e9d9dc3284c431a14c90124df6d798e91dd71`

Privacy remains hash-only; no Prompt, story, payload, tool arguments, Provider
response, Credential, header, or endpoint was captured. Live parity remains
exact at
`1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9`;
the live database SHA-256 remains
`0fccb8aeca27731c297104622804ed689edfe3d33509a399ddf149240e4376e3`.

Evidence canonical SHA-256:
`65af39170b02e2acb7a102e65b6c29bf871639ceac39add525f328681fbb9e68`.

## Stop

No second observation, replacement approval, production fix, Prompt/model/
route/budget/retry adjustment, Short Completion, Pilot, Phase 1B, or long-form
work was started.
