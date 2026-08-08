# Decision contract

## Change contract

Before implementation, produce:

```text
Requested outcome:
Original material MUST requirements:
Scope classification: open_world | closed_world
Operational definition:
Forbidden narrowing:
Authorization: inquiry | evaluation | design | implementation | operation
Current behavior and evidence:
Allowed changes:
Protected unchanged behavior:
Authority impact:
Selected approach:
Rejected alternatives:
Rollback path:
Focused tests:
Related tests:
Full-suite requirement:
Historical incident families checked:
Projected sibling and downstream risks:
Model-output variants and stable invariants:
Model-output topology classes:
Unseen valid variants:
Unknown-variant behavior:
Requirement-to-code/test/evidence traceability:
Resolution status: contained | case_fixed | systemically_resolved | unresolved
Why previous tests missed the production shape:
Forward-risk report:
Unresolved user decisions:
```

## Council decision

After role exchange, produce:

```text
Product conclusion:
Novel-business conclusion:
Technical conclusion:
Test conclusion:
Consensus:
Material dissent:
Lead adjudication:
Risk level: L0 | L1 | L2 | L3
Implementation authorized: yes | no | partially
```

Do not erase dissent merely because the lead selected an approach.

## Completion report

Lead with the outcome, then include only material evidence:

```text
Result:
Files and boundaries changed:
Protected behavior verified:
Regression reproduction:
Focused tests:
Related tests:
Full suite:
Historical incident projection evidence:
Non-deterministic model-output evidence:
Final diff review: independent | non-independent clean-room fallback | unavailable
Rollback status:
Remaining risk or unresolved issue:
```

Use these status meanings accurately:

- `complete`: the requested successful path works and required verification passed;
- `contained`: harmful output is blocked or rolled back, but the intended successful path still fails;
- `case_fixed`: the explicitly closed-world production case recovers, but no claim is made about unseen structural variants;
- `systemically_resolved`: an open-world/common failure mechanism recovers production and unseen structural variants and crosses the next authoritative boundary without code changes;
- `unresolved`: root cause or recovery remains incomplete;
- `blocked`: completion requires a user decision or external authority that cannot be safely inferred.
