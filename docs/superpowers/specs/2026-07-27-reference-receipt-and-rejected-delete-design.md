# Reference Receipt And Rejected Delete Design

## Goal

Make the reference import result readable at a glance and allow rejected learning mechanisms to be deleted unless they are still actively adopted by a project.

## Import Receipt

- Lead with the saved state and the system classification.
- Show practical use in one compact summary.
- Put classification evidence and non-uses in a collapsed detail section.
- Use one clear primary next-step action with a plain cost/no-write note.

## Rejected Mechanisms

- Protect a rejected mechanism only while a project adoption has status `adopted` or `review_source_metadata_changed`.
- Historical adoption rows with status `rejected` do not block deletion.
- Expose `deletable` and a plain-language `delete_reason` to the UI.
- Disable selection and deletion for protected records before the user acts.
- Offer an explicit removal action for protected rejected records. Removing updates every affected creative blueprint but never rewrites generated prose.
- Report exact skipped reasons during batch deletion.

## Safety

Deletion remains limited to rejected mechanism nodes. Active project adoptions, formal manuscripts, source TXT files, and model settings are unchanged.
