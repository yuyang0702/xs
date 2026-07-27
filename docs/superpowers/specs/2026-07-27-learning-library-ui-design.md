# Learning Library UI Design

## Goal

Turn the learning library from one long technical page into a calm, task-based workspace that a writer can understand without knowing internal field names.

## Information Architecture

The page has three views:

1. **资料与分析**: import, browse references, edit classification, run local/model analysis, and read results.
2. **候选写法**: review compact mechanism summaries, expand evidence only when needed, confirm/adopt/reject/delete.
3. **作品应用**: choose a project and read the active creative blueprint and other learning artifacts in plain Chinese.

The current view is kept in local page state. Existing APIs, model roles, stored learning nodes, and project artifacts remain authoritative.

## Reference Actions

- Remove the duplicate receipt action named `提炼可学习写法` for ordinary reference works.
- Keep `本地诊断` and `本地提炼` beside each selected reference.
- Explain them directly above the actions:
  - 本地诊断 scans the full text for possible problems and asks the user to review them.
  - 本地提炼 scans the full text for reusable writing methods and creates candidates for user confirmation.
- Both descriptions state that they are local, consume no model tokens, and do not rewrite the source.

## Candidate Mechanisms

- Each mechanism starts as a compact summary row: name, status, hit count, structural coverage, confidence, and available actions.
- Explanations, representative evidence, and all evidence locations live inside one `查看详情` disclosure.
- Rejected mechanisms never show confirm, adopt, or reject again.
- Protected rejected mechanisms show the reason and a `从作品中移除` action; removable mechanisms show deletion.

## Project Artifacts

- The application view uses one plain-language heading, `当前作品的创作设置`; it does not repeat the tab name as an eyebrow and title.
- Outline versions and active writing rules are separate sections with their own headings, so the page does not read as one uninterrupted column.
- Adoption reviews keep the decision buttons beside the summary and collapse the full rule list behind `查看具体规则`.
- The collapsed review summary states how many rules need review and that the item is still used by the project.
- Artifacts render as a single readable column, not a two-column raw table.
- Artifact summaries are collapsed by default and show Chinese title, version, and state.
- Known narrative fields use Chinese labels, including goal, incident, effort, escalation, result, state change, ending, and opening.
- Internal identifiers, provenance, validation flags, and unknown fields are hidden under `技术详情`.
- Empty fields are omitted from the normal reading view.

## Responsive Behavior

- Desktop content uses a stable readable width and avoids large empty columns.
- At 850 px and below, master-detail content becomes one column.
- At 600 px and below, review actions become full-width rows, detailed rules stay collapsed by default, and no horizontal scrolling is introduced.
