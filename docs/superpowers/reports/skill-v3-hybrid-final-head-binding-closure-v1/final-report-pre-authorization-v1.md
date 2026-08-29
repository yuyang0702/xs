# Skill V3 Hybrid final-HEAD binding closure — pre-authorization seal

The prior runner rejection was correct. The old authorization was bound to
`fb71c56218d2dfd0e6308aa1f9303e4e17e35e41`, then the evidence seal commit
advanced the repository to `e3ebf54571aae6b165c03763c14c5f233ae0f07e`.
Exact HEAD equality therefore failed as designed.

This change preserves exact equality and moves only the final executable
authorization materialization step. After this report, its helper, tests, and
all other pre-authorization evidence are committed, the helper must run once
against that new final clean HEAD. It reuses the existing canonical renderer,
exact authorization validator, and real transport preflight; it exclusively
creates the UTF-8 authorization plus a hash-only receipt under the configured
worktree-external runtime data root. No Git write or commit is permitted after
that point.

The six-sample experiment is unchanged: pilot
`skill-v3-hybrid-character-heavy-v1-5e5cbfd1e6296ec8878b`, experiment lock
`de49d3353abe641f49dbb697d929a13bb30cc6c4fafe9bcf11f0a6d6ea19bafc`,
sequence `CONTROL_1, HYBRID_1, CONTROL_2, HYBRID_2, CONTROL_3, HYBRID_3`,
provider/model `lingsuan_gpt / gpt-5.6-sol`, Anthropic protocol, route
fingerprint `30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0`,
and destination `https://lingsuan.org:443/v1/messages`. Per-sample output is
4624 tokens, total output is 27744 tokens, and the campaign permits at most one
request/network/HTTP POST per sample and six total only after a future fresh
user authorization. The monetary cap remains `UNKNOWN_NOT_SEALED`.

Focused tests passed 9/9. Related tests passed 137 with one historical sealed
hash oracle failure caused by the intentional maintenance documentation change.
The full offline suite produced 3959 passed, 41 skipped, 6 xfailed, 55 failed,
and 81 errors; compared with the prior sealed baseline, passes increased by 9
while failures and errors were unchanged. New final-HEAD binding regressions and
new owning-source regressions are both zero. Production and BAML source diffs
are zero. Privacy passes.

This in-repository report is deliberately pre-authorization evidence. The
actual final execution HEAD, external authorization SHA-256, post-materialization
HEAD equality, timestamp, and zero post-auth Git writes/commits are recorded in
the worktree-external receipt created only after the final seal commit.

`PILOT_EXECUTION_AUTHORIZED=NO`

`CREDENTIAL_LOOKUP_COUNT=0`

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT=NOT_EXECUTED`
