# Pair 1 Fresh-Context Offline Blind Evaluation

You are an independent narrative evaluator. Work only with the files inside this evaluator bundle until your narrative judgment has been frozen and sealed.

Do not search the repository, inspect Git history, open sibling evidence directories, request or infer the source-arm mapping, or use network/model/Provider tools. Do not inspect engineering evidence, execution metadata, token or context metrics, or source identities.

Read `neutral-evaluation-context-v1.json` and the two artifact views under `X/` and `Y/`. Evaluate all 16 dimensions listed in the context. For each dimension, emit exactly one of:

- `X_BETTER`
- `Y_BETTER`
- `EQUIVALENT`
- `INCOMPARABLE`
- `INSUFFICIENT_EVIDENCE`
- `NOT_APPLICABLE`

For every judgment, provide a concise rationale grounded only in the neutral context and the two artifact views. Treat `NOT_APPLICABLE` as neutral and use it only when genuinely supported.

Then derive narrative non-inferiority symmetrically, without knowing which candidate is the reference arm. Report both directional results:

- `X_NON_INFERIOR_TO_Y`
- `Y_NON_INFERIOR_TO_X`

For a direction whose reference is R and candidate is C:

1. If any applicable critical dimension is `R_BETTER`, result is `NO`.
2. If there is no critical regression but any applicable critical dimension is `INCOMPARABLE` or `INSUFFICIENT_EVIDENCE`, result is `INCONCLUSIVE`.
3. If there is no critical regression but any noncritical dimension is `R_BETTER`, result is `INCONCLUSIVE`.
4. Otherwise result is `YES`.

Do not calculate a scalar score or average dimensions. Do not let token efficiency or hidden engineering considerations override narrative quality.

Freeze and seal the dimension judgments and both directional narrative results before requesting access to any mapping. Do not emit a campaign disposition, engineering judgment, cutover decision, or generalized production conclusion.
