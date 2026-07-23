# Per-Role Fallback Model Design

## Goal

Let each model role select an optional fallback model in the local console while preserving the program's existing role-based fallback when no explicit fallback is configured.

## Configuration UI

Each role-binding row contains:

- role name;
- required primary-model selector;
- optional fallback-model selector;
- one Save button.

The fallback selector starts with `使用程序默认回退`. Existing saved fallback bindings are restored when the page loads. The primary and fallback selections cannot refer to the same provider/model pair; the page rejects that combination before saving. On narrow screens, the controls stack vertically using the existing responsive layout.

## Persistence And Validation

The existing `PUT /api/role-bindings/{role}` contract remains authoritative and receives all four fields:

- `primary_provider_id`;
- `primary_model_id`;
- `fallback_provider_id`;
- `fallback_model_id`.

Choosing the default option sends both fallback fields as `null`, which also clears a previously saved explicit fallback. The API rejects partial fallback pairs and identical primary/fallback pairs. Both selected models must resolve to enabled providers with available API keys before the binding is saved.

No database migration is required because the role-binding table already stores nullable fallback provider and model IDs.

## Runtime Priority

Model execution follows this order:

1. Execute the role's primary model.
2. If it fails and the same role has an explicit fallback binding, execute that fallback model with the same prompt, tools, and output budget.
3. If no explicit fallback exists, or the explicit fallback also fails, retain the workflow's current program-default role fallback. Examples include `polish -> draft` and `final_review -> planning`.
4. If the program-default fallback also fails, fail the stage normally.

Cancellation is never treated as a model failure and never triggers fallback. Tool-capability degradation on one model remains separate from changing models: the configured adapter may first use its existing prompt-mode degradation, and only an actual failed completion triggers model fallback.

## Observability

A successful explicit fallback records the actual provider/model in the existing stage receipt and adds fallback metadata identifying the failed primary model. Run logs distinguish:

- explicit fallback selected for the same role;
- no explicit fallback, so the program-default role was used;
- explicit fallback failed, so the program-default role was used.

API keys and prompt bodies are never included in logs.

## Compatibility

Existing bindings have null fallback fields and therefore keep their current behavior. Existing projects, run artifacts, and provider definitions are unchanged. Saving only a primary model through an older client continues to clear/use the program default because fallback fields are optional.

## Testing

- The console renders and restores primary and fallback selectors for every role.
- Saving a fallback persists all four binding fields; selecting the default clears both fallback fields.
- The API rejects partial and identical fallback pairs.
- Plain and tool-enabled gateway calls use the explicit fallback after a primary failure.
- With no explicit fallback, workflow-level default behavior remains unchanged.
- Cancellation does not trigger fallback.
- The full existing test suite remains green.
