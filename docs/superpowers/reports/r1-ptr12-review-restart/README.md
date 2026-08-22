# R1-PTR12 fresh team review failure evidence

This directory seals the completed fresh `TEAM_SHARDED_INDEPENDENT_REVIEW`
against reviewed HEAD `3d3fd185ba9a6027ac6c33aa861a869e415a40c6`.

The review did not pass. Shards A, B, and C independently returned
`HARD_FAIL`. The first frozen hard issue is
`RAW_NORMALIZED_GUARD_DECISION_INPUT_BINDING`.

These files are evidence only. They do not modify production behavior, tests,
fixtures, PTR9 business predicates, historical evidence, or Phase B state.
No raw Provider content, Prompt, story text, reasoning text, tool arguments,
credentials, headers, request identifiers, or private absolute paths are
included.

`SPLIT_REVIEW_PASS=NO`

`PHASE_B_READY=NO`

`NO_AUTOMATIC_FIX=YES`
