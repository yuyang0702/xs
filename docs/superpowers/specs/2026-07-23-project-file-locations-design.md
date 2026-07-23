# Project File Locations Design

## Goal

Make every project's working files discoverable from the console, including incomplete drafts and recovered best candidates, and allow opening those locations in Windows Explorer without accepting arbitrary filesystem paths from the browser.

## User Interface

Add a compact `文件位置` section below the active-project summary. It shows five resolved locations:

- `项目目录`: the project root.
- `正式成品`: the archived short-story manuscript or the long-story chapters directory.
- `最新草稿`: the newest run's complete `draft.md`, when present.
- `最高分候选`: the newest available `best-candidate.md`; if absent, the newest completed `polish.md` used by manuscript recovery.
- `最近运行`: the newest run directory.

Each existing location has two controls: copy the absolute path and open it in Windows Explorer. Missing artifacts display `尚未生成` and do not expose an open action.

## API

Add a read-only project-locations endpoint that returns labels, artifact kinds, existence, and resolved absolute paths. Resolution is performed by the backend from the project and run records.

Add a controlled open endpoint that accepts only an artifact-kind enum. It never accepts a client-supplied path. The backend resolves the artifact again and verifies that the target remains inside the selected project directory.

For a file, Windows Explorer opens with the file selected. For a directory, Explorer opens the directory. Missing targets return a conflict response. Non-Windows platforms return an unsupported-operation response.

## Selection Rules

Runs are inspected newest first. Draft and candidate selection only considers regular files inside each run's `outputs` directory. Candidate priority within a run is `best-candidate.md`, then `polish.md`. Formal files always remain distinct from recovered candidates so the user can see whether archival completed.

## Safety

- Reject unknown artifact kinds.
- Resolve and validate every target server-side.
- Require the target to be located under the current project root.
- Use a fixed Explorer executable and argument list without a command shell.
- Do not open anything automatically during page load.

## Verification

- API tests cover formal, draft, candidate, latest-run, and missing states.
- API tests prove arbitrary paths and unknown kinds cannot be opened.
- The operating-system launch is mocked in tests.
- Console tests verify rendering, copy, and open controls.
- Browser verification checks desktop layout, narrow layout, copy feedback, and the missing-file state.

