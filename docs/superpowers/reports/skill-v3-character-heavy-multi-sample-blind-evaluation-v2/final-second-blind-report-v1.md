# Final second blind evaluator report

Status: `SKILL_V3_SECOND_INDEPENDENT_BLIND_EVALUATION_FROZEN`

## Binding

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Start HEAD: `fdc387fa90e18745ced9b67447fd9e35e3f631a8`
- Anonymous bundle definition SHA-256: `2b98b26ffa25928783b4bffc5a7c8ffcf79fd604bd74c5443eeee56d0b5ddebd`
- Literary-policy SHA-256: `d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21`
- Evaluator 2 freeze SHA-256: `9c4c5ce98c78cd33c4404363476bce3a70f1b6b55be6211d82060b021f5d2dc6`
- Required evaluator count: 2
- Batch count: 3
- Required evaluator-by-batch votes: 6
- Evaluator 1 expected votes: 3
- Evaluator 2 expected and observed votes: 3

## Evaluator 2 batch relations

| Anonymous pair | character_agency | causal_coherence | subtext_support | specificity | scene_pressure | setup_payoff_integrity | voice_readiness | anti_template_risk |
|---|---|---|---|---|---|---|---|---|
| blind-pair-1 | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | A_BETTER |
| blind-pair-2 | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER |
| blind-pair-3 | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER | B_BETTER |

`anti_template_risk` in blind-pair-1 is the sole opposed local direction in evaluator 2: the second-listed artifact exposes literal scene-structure labels. No scalar literary score was created.

## Independence and privacy

- `SECOND_INDEPENDENT_JUDGMENTS_FROZEN=YES`
- `FIRST_BLIND_JUDGMENTS_READ_BEFORE_SECOND_FREEZE=NO`
- `MAPPING_REVEALED=NO`
- `LITERARY_POLICY_DRIFT=NO`
- `MAPPING_CONTAMINATION=0`
- `PROVIDER_REQUEST_ATTEMPTS=0`
- `NETWORK_CALLS=0`
- `PROJECT_MODEL_CALLS=0`
- `PAID_CALLS=0`

Evaluator 1 evidence may be read only after the freeze commit containing this evidence root.
