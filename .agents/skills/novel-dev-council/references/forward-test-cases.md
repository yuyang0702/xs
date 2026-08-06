# Forward-test cases

Use these cases to validate the Skill without revealing an expected solution to role agents.

## L0 inquiry

Request: `现在终审未通过后，问题是自动修复还是进入问题清单？`

Expected workflow property: inspect and explain only; do not spawn a full council or modify files.

## L1 narrow change

Request: `把工作台上的一个说明文案改得更清楚，不改变任何行为。`

Expected workflow property: use technical and test perspectives, preserve scope, avoid a full four-role debate unless evidence reveals behavioral impact.

## L2 feature

Request: `在项目首页增加只读摘要卡片，展示已有项目类型、目标字数和最近任务状态，不改变任务执行逻辑。`

Expected workflow property: run the full council, cover UI/API consistency and old-project defaults, keep execution and authority paths unchanged, and propose focused UI/API tests.

## L3 user-control feature

Request: `在终审问题列表中增加修改前后对照，并允许逐条采用。`

Expected workflow property: promote the request to L3 because it touches revision decisions and candidate promotion; cover UI/API/candidate hashes/user control, preserve formal-write behavior, and require end-to-end tests.

## L3 authority-critical repair

Request: `终审发现问题后直接让 AI 改正式稿，失败就继续重试。`

Expected workflow property: challenge the direct-write premise, distinguish candidate/best/formal artifacts, require bounded retries and rollback, retain user authority for semantic changes, and refuse unsafe direct promotion.

## Regression incident

Request: `修复规划恢复时的一个问题，之前每次修复都会带来新的断点续跑问题。`

Expected workflow property: require reproduction, unchanged-behavior contract, stale/partial/corrupt checkpoint cases, successful continuation through drafting, independent diff review, and a monotonic no-new-hard-issue decision.
