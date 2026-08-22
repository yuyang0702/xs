# SHORT-PLAN-V2-SLICE1-PROVENANCE-FIX — Final Report

`SHORT_PLAN_V2_SLICE1_CANONICAL_PROVENANCE_FIXED`

`SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_RESTART_READY=YES`

## Baseline and scope

- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`
- Start HEAD: `0430a7692ba1cd3b3b1d86fb5e7993967979f208`
- Implementation commits: `e4182715779a8d01b2d051daf7aab9156fa77ab8` (`Add canonical Slice 1 fixture provenance`) and `e893b3a269a1cd1f9aca1c2d29fb650a5e95b044` (`Unify canonical provenance observation`)
- Selected strategy: `EXPLICIT_CANONICAL_TEXT_PROVENANCE`
- Contract: `CANONICAL_TEXT_LF_V1`
- Fresh receipt: `EventRealizationShadowReplayReceiptV2` / version 2
- Historical receipt: `EventRealizationShadowReplayReceiptV1` / version 1, raw-byte semantics retained
- Historical replay-failure evidence diff: 0
- Original corpus fixture content diff: 0
- Production source diff: 0
- BAML diff: 0

The implementation changes only offline fixture provenance hashing, an explicit sidecar binding, the diagnostic replay CLI/receipt, tests and maintenance documentation. Planning V1, Slice 1 artifact/validator/freeze/recovery semantics, title, narrative, all 20 local derivations, Draft input, StoryState, Canon and READY are unchanged.

## Canonical contract result

The current Windows working-tree fixture is 4486 CRLF bytes with raw SHA-256 `a1442835a44471b9be5c87c4feb4ec89853a3b4348d7215185de62ced4a4fab4`. Strict UTF-8 decode plus CRLF/lone-CR to LF conversion produces 4436 bytes with canonical SHA-256 `6ff08d5e4045bd51ad992f372928e467255a07ab7c13a1ff01b7e5be2227daa6`, exactly matching the sealed expected identity.

LF and CRLF replay receipts have distinct raw diagnostics but share canonical receipt identity `6f841ab5dd86511fe1cb32145847a298eadb9c3c3a719fe0104c9f89e2fd83a5`. Raw checkout hash and elapsed time are explicitly non-identity observations.

- LF/CRLF/lone CR/mixed EOL: same canonical bytes
- Final newline: preserved; presence and absence hash differently
- Trailing spaces: preserved and identity-significant
- Unicode: no NFC/NFD normalization
- Binary/untyped: `RAW_BYTES_V1`, no newline conversion
- Invalid UTF-8 under text contract: typed `CANONICAL_TEXT_PROVENANCE_DECODE_ERROR`
- Canonical hash mismatch: typed fail before semantic case dispatch
- Parent/case identity mismatch: typed fail before semantic case dispatch
- Canonical replay smoke: V2 exact, 20/20 semantic cases, external actions zero

## Verification

- Pre-change replay baseline: 7 passed
- Focused provenance + replay: 19 passed
- Focused Slice 1 cluster: 118 passed
- Related Planning/PTR3/V1/StoryState: 167 passed in 31.58s
- Supported offline suite: 2998 passed, 41 skipped, 6 deselected, 6 xfailed, 1 warning in 2093.46s
- Strict L3: pass, warnings 0, blockers 0
- Privacy: exact, sensitive-pattern hits 0

The previous independent replay validation remains failed and immutable. This task fixes only its cross-platform provenance blocker; it does not relabel the prior run as `SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_VALIDATED` and does not authorize Phase B.

## Required markers

- `CANONICAL_PROVENANCE_EXACT=YES`
- `CROSS_PLATFORM_RECEIPT_IDENTITY=YES`
- `HISTORICAL_FAILURE_EVIDENCE_UNCHANGED=YES`
- `V1_AFFECTED=NO`
- `QUALITY_AFFECTED=NO`
- `NEW_PRODUCTION_BEHAVIOR_CHANGE=NO`
- `PRODUCTION_RUNTIME_CHANGED=NO`
- `BAML_CHANGED=NO`
- `REAL_PROVIDER_CALLS=0`
- `NETWORK_CALLS=0`
- `MODEL_CALLS=0`
- `PAID_CALLS=0`
- `NEW_FULL_SHORT_CANARY=NOT_EXECUTED`
- `SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_RESTART_READY=YES`

Next independent task: `SHORT_PLAN_V2_SLICE1_OFFLINE_REPLAY_VALIDATION_RESTART`.
