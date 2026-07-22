# Runtime Control and Project Library Design

## Goal

Improve the local novel console so the user can verify configured models, start and stop generation safely, follow detailed progress, select common story types without losing free-form input, continue existing novels, and recover deleted projects.

## Scope

The change includes:

- Per-model connectivity and capability testing from the model configuration page.
- Background generation tasks with real cancellation.
- Persisted stage logs for workflows and initialization Skills.
- Preset-plus-custom controls for genre and sub-genre.
- A persistent project library with continue-writing actions.
- A recoverable local project trash with explicit permanent deletion.

It does not add Redis, Celery, cloud services, user accounts, or cross-device synchronization.

## Architecture

The application will use an in-process task manager backed by SQLite state. Starting generation creates a run record and an `asyncio.Task`, then returns the run ID immediately. The browser polls the run detail endpoint for status and ordered events. Cancellation sets a durable cancellation flag and cancels the active task; model HTTP requests receive cancellation through normal async propagation.

SQLite remains authoritative for run status and logs. The in-memory task map only tracks work active in the current server process. At startup, stale `queued` or `running` records are marked `interrupted` so the UI never presents abandoned work as active.

## Cancellation And Continuation

The stop button cancels the current generation run, not the novel project. Completed stage outputs and diagnostic logs remain in the run archive. The currently executing stage is discarded and cannot write partial output to formal story files.

Formal story updates occur only at existing validated stage boundaries. A later writing session starts a new run from the latest committed chapter, canon, timeline, character state, and foreshadowing state. The system does not attempt to resume a half-finished model response.

Run terminal states are `completed`, `failed`, `cancelled`, and `interrupted`. The UI labels all four states in Chinese and keeps the project available regardless of run outcome.

## Run Events And Logs

A `run_events` table stores:

- Run ID and monotonically ordered event ID.
- Timestamp and severity: `info`, `success`, `warning`, or `error`.
- Stage and event type.
- Provider, model, and Skill names when applicable.
- Human-readable message and structured metadata.

Workflow stages emit events when queued, started, completed, failed, or cancelled. Model calls record provider/model, token usage, duration, execution mode, and tool call count without recording API keys or full private prompts. Skill execution records Skill name, content hash, result, command output, and validation errors.

The existing initialization-Skills operation becomes a tracked run so errors such as Story CLI validation failures appear in the same log viewer instead of only returning HTTP 422.

## Model Testing

Each configured model row has a `Test` action using the existing probe endpoint. The result reports three independent checks:

- Basic connection and authentication.
- Structured JSON response support.
- Native Tool Calling support.

The UI shows checking, success, partial support, and failure states. Failure messages include the relevant endpoint, protocol, status category, and safe error reason, while never exposing the API key. The result also guides role usage: a model without Tool Calling may run prompt-only workflow stages but cannot run write-capable Skill Runtime stages.

## Story Type Input

Genre and sub-genre use editable comboboxes backed by local preset lists. Selecting a preset fills the same text value that the wizard already persists; typing a custom value remains valid.

Initial genre presets include fantasy, science fiction, suspense, romance, urban, historical, martial arts, realism, horror, youth, workplace, and fan fiction. Sub-genre suggestions change with the chosen genre but never restrict custom input. Existing projects and wizard drafts remain compatible because stored values stay plain strings.

## Project Library And Trash

The workbench project selector and project library list every active project, including projects whose latest run was cancelled or failed. Each item exposes continue writing, view manuscript, and move to trash.

Moving to trash records deletion metadata and moves the project directory under the application data directory's `trash` folder. The project disappears from active selectors but remains recoverable for 30 days. Restoring moves it back and preserves its ID, history, story files, snapshots, and metadata.

Permanent deletion requires a separate confirmation action from the trash view. Expired trash is not deleted automatically during ordinary writing; the trash screen offers a cleanup action for items older than 30 days so no background cleanup can surprise the user.

## API Surface

- `POST /api/providers/{provider_id}/models/{model_id}/probe` remains the model test endpoint.
- Workflow start endpoints return `202 Accepted` with a run record immediately.
- `POST /api/runs/{run_id}/cancel` requests cancellation and returns the updated run.
- `GET /api/runs/{run_id}` returns run state, receipts, and ordered events.
- `POST /api/projects/{project_id}/initialize-skills` becomes a background tracked run.
- `DELETE /api/projects/{project_id}` moves a project to trash.
- `GET /api/projects/trash` lists recoverable projects.
- `POST /api/projects/{project_id}/restore` restores a project.
- `DELETE /api/projects/{project_id}/permanent` permanently removes a trashed project after confirmation.

## UI Design

The approved layout keeps the current quiet operational style:

- Model health summaries appear in the model configuration area and current role bindings.
- The workbench places generation controls beside a live event log.
- A red square stop icon appears only while a run is queued or active.
- The project library offers continue-writing and move-to-trash actions.
- A dedicated trash view offers restore and permanent-delete actions.
- Run history rows open their detailed event log, including failures.

Polling runs only while a task is active and stops on terminal status. Controls have fixed dimensions so status text and progress updates do not shift the layout.

## Error Handling

Cancellation is idempotent. Cancelling a terminal run returns its existing state. Cancelling during an HTTP model request propagates cancellation and records a final event. If the process exits unexpectedly, startup recovery marks active runs interrupted.

Project moves use resolved paths constrained to the configured project and trash roots. Name collisions in trash use the immutable project ID. Restore refuses to overwrite an existing active directory. Permanent deletion is allowed only for records already marked trashed.

Model and Skill errors are sanitized for display. Local command stderr is retained in bounded form for diagnosis. Secrets and authorization headers are never stored in events.

## Testing

Backend tests cover task start, cancellation, cancellation before formal writes, startup interruption recovery, ordered event persistence, initialization-Skill logging, model probe results, project trash/restore/permanent deletion, and path containment.

Frontend tests cover probe controls, genre presets with custom values, active-run polling, stop-button visibility, terminal status rendering, log detail rendering, continue-writing after cancellation, and trash actions. The full existing Python suite and JavaScript syntax check must remain green.
