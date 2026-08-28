# Final complete two-evaluator blind aggregation report

Status: `SKILL_V3_MULTI_SAMPLE_COMBINED_BLIND_AGGREGATION_FROZEN`

## Baseline, freezes, and policy identity

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Start HEAD: `fdc387fa90e18745ced9b67447fd9e35e3f631a8`
- Evaluator 2 freeze commit/head: `fec3607b6ad52f3e917f3d6bcad32e7224928720`
- Combined aggregation commit/final HEAD: `SELF` (the commit containing this report; resolved in the final window status)
- Required final worktree: `CLEAN`
- Anonymous bundle definition SHA-256: `2b98b26ffa25928783b4bffc5a7c8ffcf79fd604bd74c5443eeee56d0b5ddebd`
- Anonymous bundle manifest SHA-256: `c5aedf848d9b6c74029318ecb1d051893147aa7c10f6a20f511395fe9cf29a62`
- Evaluator 1 freeze SHA-256: `45927989be4cd126dd567393da3efebe59880ec239e9716a720ea2e54b66bd3b`
- Evaluator 2 freeze SHA-256: `9c4c5ce98c78cd33c4404363476bce3a70f1b6b55be6211d82060b021f5d2dc6`
- Literary-policy SHA-256: `d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21`
- Combined literary freeze SHA-256: `c9be76be273049ec55c772298ceddb99964a1101abbc25edb2062523e93d4d4b`

## Complete vote set

- Required evaluator count: `2`
- Batch count: `3`
- Required evaluator-by-batch votes: `6`
- Evaluator 1 supplied votes: `3`
- Evaluator 2 supplied votes: `3`
- Observed total votes: `6`
- Missing required vote count: `0`
- Duplicate vote count: `0`
- Unauthorized extra vote count: `0`
- `COMBINED_REQUIRED_VOTE_SET_COMPLETE=YES`

## Combined per-dimension aggregates

`A` and `B` below name only first/second positions in each anonymous pair. They do not reveal engineering arms.

| Dimension | A_BETTER | B_BETTER | TIE | Insufficient | Variance | Aggregate |
|---|---:|---:|---:|---:|---|---|
| character_agency | 0 | 6 | 0 | 0 | NO | B_BETTER |
| causal_coherence | 0 | 6 | 0 | 0 | NO | B_BETTER |
| subtext_support | 0 | 5 | 1 | 0 | YES | B_BETTER |
| specificity | 0 | 6 | 0 | 0 | NO | B_BETTER |
| scene_pressure | 0 | 6 | 0 | 0 | NO | B_BETTER |
| setup_payoff_integrity | 0 | 5 | 1 | 0 | YES | B_BETTER |
| voice_readiness | 1 | 5 | 0 | 0 | YES | B_BETTER |
| anti_template_risk | 1 | 4 | 1 | 0 | YES | B_BETTER |

Every aggregate meets the sealed four-of-six support threshold. No aggregate remains `INCONCLUSIVE`; therefore `INCONCLUSIVE_DUE_ONLY_TO_MISSING_REQUIRED_VOTES=NO`. All three critical dimensions resolve `B_BETTER`, supported critical `A_BETTER` regression count is 0, and the sealed minimum literary support condition is satisfied. These are pair-position results only; no architecture or treatment/control conclusion is authorized before mapping reveal.

## Variance and evaluator disagreement

- Opposed-direction dimensions: `voice_readiness`, `anti_template_risk`.
- Direction/TIE variance: `subtext_support`, `setup_payoff_integrity`, `anti_template_risk`.
- Evaluator disagreement count: `4` pair-dimension judgments.
- Pair 1 contains the direct voice-direction opposition and an anti-template TIE/direction disagreement.
- Pair 2 contains TIE/direction disagreements for subtext and setup/payoff.
- Pair 3 is unanimous across both evaluators and all dimensions.
- Sample-level insufficient evidence count: `0`.
- Aggregate insufficient evidence count: `0`.

Equivalent results stayed neutral, no scalar literary score was created, and no critical regression was averaged away.

## Privacy, manifest, and call counters

- `MAPPING_CONTAMINATION=0`
- `MAPPING_REVEALED=NO`
- Privacy receipt: `privacy-scan-v1.json` — `PASS`
- Manifest: `sha256-manifest-v1.json` — `EXACT`
- `PROVIDER_REQUEST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `PROJECT_MODEL_CALLS=0`
- `PAID_CALLS=0`
- `SKILL_V3_CUTOVER=NO`
- `PLANNING_V2_CUTOVER=NO`
- `FULL_SHORT=NOT_EXECUTED`

SKILL_V3_MULTI_SAMPLE_COMBINED_BLIND_AGGREGATION_FROZEN

EXACT_NEXT_GATE=SKILL_V3_MULTI_SAMPLE_MAPPING_REVEAL_AND_ENGINEERING_DECISION

Stop. Mapping was not inspected, inferred, or reconstructed in this window.
