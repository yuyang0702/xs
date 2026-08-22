# R1-PTR12 V2 team-review failure evidence

This directory seals the completed fresh `TEAM_SHARDED_INDEPENDENT_REVIEW`
against reviewed HEAD `f79edfc078aecad9a0b654448416ee258c8923de`.

The review did not pass. Shard A returned `PASS`; Shards B and C returned
`HARD_FAIL`. The first frozen hard issue is
`STREAM_REASONING_USAGE_LINEAGE_MISMATCH`. The second independent hard issue,
`DIAGNOSTIC_CONTEXT_CONSTRUCTION_FAIL_OPEN`, remains open and is not part of
the first fix family.

These files are evidence only. They do not modify production source, tests,
fixtures, BAML, PTR9 behavior, historical evidence, or Phase B state. They do
not include raw Provider content, Prompt content, story prose, reasoning text,
final text, tool arguments or results, credentials, headers, private request
identifiers, or private absolute paths.

`SPLIT_REVIEW_PASS=NO`

`PHASE_B_READY=NO`

`NO_AUTOMATIC_FIX=YES`
