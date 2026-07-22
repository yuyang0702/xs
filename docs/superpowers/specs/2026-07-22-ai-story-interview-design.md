# AI Story Interview Design

## Goal

Add a conversational story-planning interview to the existing project wizard. The planning model asks one focused question at a time, explains specialist terms when useful, and proposes structured field updates. No proposal changes the wizard until the user explicitly applies it.

## Product Behavior

- The existing Skill-driven form remains the canonical checklist.
- A wizard exposes an `AI 开书访谈` panel alongside the form.
- Starting or continuing the interview sends the current wizard schema, answers, answer policies, and recent interview history to the model bound to the `planning` role.
- The assistant returns one natural-language reply and zero or more field suggestions.
- Suggestions show the destination field, proposed value, and reason. The user chooses which suggestions to apply.
- Applying suggestions writes them as `suggestible` answers. Existing `locked` answers are never overwritten.
- Applied values immediately appear in the form and continue to participate in autosave, gap analysis, confirmation, and Skill Runtime initialization.
- Interview history survives page refresh and can resume with a draft wizard.

## Architecture

### Persistence

Add `wizard_interview_messages` to SQLite. Each row stores the wizard, role, display content, structured suggestions, suggestion status, and timestamp. API keys and full model receipts are not stored in this table.

### Interview Service

Create `WizardInterviewService` as the only component allowed to build prompts, call the planning model, validate model output, and apply suggestions. It consumes `WizardService`, `ModelGateway`, and `Database`.

The model must return JSON with this shape:

```json
{
  "message": "下一条访谈回复",
  "suggestions": [
    {"field_id": "protagonist.arc", "value": "...", "reason": "..."}
  ]
}
```

The parser accepts bare JSON or a fenced `json` block. Unknown fields, empty values, duplicate fields, and proposals targeting locked answers are removed before persistence.

### API

- `GET /api/wizards/{wizard_id}/interview` returns persisted messages.
- `POST /api/wizards/{wizard_id}/interview` accepts an optional user message, stores it, calls the planning model, and returns the assistant message.
- `POST /api/wizards/{wizard_id}/interview/{message_id}/apply` accepts selected field IDs and applies valid suggestions.

Completed wizards reject new interview turns and suggestion application.

### Frontend

The wizard becomes a responsive form-and-interview layout. The interview panel contains message history, a compact input, send button, suggestion checkboxes, and an `应用所选建议` command. It does not imitate a general chatbot: its scope is the current story wizard.

## Safety And Error Handling

- The external model receives wizard data only and no filesystem, shell, MCP, or Story tools.
- Locked answers are protected in both prompt instructions and server-side validation.
- Invalid or non-JSON model output returns an actionable error and does not mutate answers.
- Missing planning-model configuration, missing credentials, provider failures, and completed wizards return distinct API errors.
- Only explicit apply actions mutate wizard answers.

## Testing

- Database tests cover message persistence and ordering.
- Service tests cover prompt context, fenced JSON, unknown fields, locked fields, and selective application.
- API tests cover turn creation, history, application, and error translation.
- Console tests cover interview controls and static assets.
- Browser verification covers desktop and mobile layout, empty state, and disabled/busy states.

