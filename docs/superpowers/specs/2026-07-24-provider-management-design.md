# Provider Management Design

## Goal

Allow users to edit and delete existing model providers from the "模型与 API" page.

## Scope

- Edit provider name, protocol, Base URL, and optionally API Key.
- Preserve internal authentication, timeout, and extra-header settings without exposing new controls.
- Keep the existing API Key when the edit form leaves it blank.
- Delete a provider after explicit browser confirmation.
- Rely on the existing SQLite cascade to delete that provider's model mappings.
- Remove role bindings that use the deleted provider as primary and clear it from fallback-only bindings.
- Refresh provider choices and role-binding choices after every change.

Model editing and deletion are outside this change.

## Backend

Add `PUT /api/providers/{provider_id}`. The registry validates the same fields used during creation, preserves the provider ID and enabled state, updates the database row, and updates the secret only when a non-empty key is supplied. Missing providers return `404`.

Keep the existing `DELETE /api/providers/{provider_id}` route. Missing providers are treated as an idempotent delete. Related role-binding cleanup happens in the same database transaction.

## Frontend

Each configured provider gets Edit and Delete commands. Edit reuses the existing provider form, changes its heading and submit label, and adds Cancel. Delete uses `confirm()` and then reloads application state.

The API Key field is required when creating a provider and optional while editing one.

## Verification

- API tests cover editing without replacing the secret, editing with a new secret, invalid edits, missing providers, and cascading model deletion.
- Existing provider, role-binding, and full test suites remain green.
- Browser verification covers create-to-edit state, cancel, update, and delete confirmation.
