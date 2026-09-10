# 成功流程常规化变更合同

## Requested outcome

在不触碰已完成 campaign/run、正文、历史证据或日常原始脏目录的前提下，把成功验证所依赖的常规运行接缝纳入 Git 中的正式 API；新项目不依赖 campaign 专属 launcher、固定身份或历史证据路径。

## Evidence → Finding → Path

| Evidence | Finding | Path |
|---|---|---|
| `ab3e4471e2ade46f03750d21ac445cb2dab8265b` 及其全部祖先包含 receipt、容量、quarantine、dispatch、review、maintenance 修复 | 成功修复已在专用 worktree 的仓库历史中，不能只拣最后一个提交 | `git log --reverse 71c67177b41c25da534cc108432a19bfb7032909..ab3e4471e2ade46f03750d21ac445cb2dab8265b` |
| 外置 `resume_v6.py` SHA-256 为 `f94dc9d465a201b4b2edbfe4b6c36a51651821e6ff5ca7ae19e5644d89811fbc`，含固定 `REPO/ROOT/CAMPAIGN_HEAD`、角色映射、计数 observer 和 causal-chain monkeypatch | 它是历史 campaign 编排/取证脚本，不是可复用产品入口 | `C:\小说\real-zero-to-final-short-campaign-20260907-v1\resume_v6.py` |
| 原正式代码已有 `WorkflowService.resume_short_receipt`，但 API 路由表没有 receipt-only 路径 | 常规 API 无法调用同一原生恢复边界 | `src/novel_flywheel/workflows.py`, `src/novel_flywheel/api/runs.py` |
| campaign DB 中 `reference_analyses=0`、`learning_nodes=10`、`project_learning_artifacts=41` | 空表是分析存储路径不同造成的证据，不应伪造历史分析行 | `C:\小说\real-zero-to-final-short-campaign-20260907-v1\data\app.db` |
| 项目 metadata 使用 UUID `700309f89aa7`，章节 POV 为 `third-limited` 且 character 列为空 | POV/slug 报告是应用 UUID/外部 Story Skills schema 兼容差异，未改写生产身份 | `projects/雾港的回声-700309/project.json`, `chapters/chapter-01.md` |

## Contract

- Scope: closed-world API integration; no model-output contract change.
- Allowed change: one Pydantic request model, one API delegation route, duplicate coordinator definition removal, docs and offline regression tests.
- Protected behavior: existing WorkflowCoordinator ownership, receipt validators, operation-scope gate, dispatch accounting, run identity, checkpoints, StoryState, candidate promotion, provider routes, credentials, and all user files.
- Rollback: revert the integration commit; the pre-existing public service and external historical launcher remain unchanged.
- Authorization: implementation and local tests only; no paid Provider calls, no push, no merge, no restart of active runs.
- Resolution status: `case_fixed`. The regular API path is wired and offline verified; no claim is made that this constitutes a new live full Short.

## Verification ladder

1. Focused: 11 tests in `test_app.py`, `test_short_receipt_api.py`, `test_short_receipt_launcher.py`, and `test_workflow_coordination.py` passed.
2. Related: 667 tests in the Short workflow, models, database, task manager, and trustworthy-flow cluster passed.
3. Full suite: the first `pytest -q` collection stopped because the repository
   does not contain the environment-specific `data/app.db` required by
   `tests/test_r0_high_frequency_replay.py`.  A follow-up run excluding that
   test began but exposed additional pre-existing replay-fixture failures and
   was stopped; no full-suite PASS is claimed.

## Single-agent clean-room review

No team review was requested. The final diff is reviewed as a single-agent clean-room fallback against the baseline, this contract, the forward-risk report, and raw test output; independence is not claimed.
