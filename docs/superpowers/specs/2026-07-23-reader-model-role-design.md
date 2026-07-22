# Reader Model Role Design

## Goal

Allow target-reader simulation to use an independently configured provider and model without breaking existing installations.

## Behavior

- Add `reader_review` to the model-role configuration UI with the label `目标读者模拟`.
- Reader simulations use `reader_review` when that role has a saved binding.
- If `reader_review` is unbound, reader simulations use the existing `review` role.
- Editorial review continues to use `review`; reader simulation never replaces it.
- The reader stage continues to use review Skills, prompts, bounded excerpts, and read-only behavior.

## Observability

The `quality_escalated` run event records `model_role` and `fallback_used`. Its message explicitly says whether the dedicated reader model or the review-model fallback was selected. Stage receipts preserve the actual model role returned by the gateway.

## Compatibility

No database migration is required because role bindings already accept arbitrary role names. Existing projects and configurations continue through the fallback path until the user binds a reader model.

## Testing

- The console exposes the new reader role.
- A saved `reader_review` binding routes only reader simulation to that role.
- An absent binding routes reader simulation to `review` and records the fallback.

