# 候选大纲比较与安全应用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在学习库中提供候选大纲查看、编辑、本地比较、语义复核、逐项/整体应用和版本恢复。

**Architecture:** 新建聚焦的大纲服务，复用 StoryState candidate 与 revision 作为唯一权威状态；Learning API 只负责请求校验和调度。前端在“作品应用”中提供单层、易读的大纲版本工作区。

**Tech Stack:** Python 3.11、FastAPI、SQLite StoryState、标准库 `difflib`/`hashlib`、原生 HTML/CSS/JavaScript、pytest。

## Global Constraints

- 不修改或自动重写正式正文。
- 自动测试不得调用付费模型。
- 现有项目首次使用前保持不变。
- 本地比较优先，语义复核只在用户明确点击后调用现有 `planning` 角色。
- 候选应用必须经过 StoryState revision 检查并可恢复。

---

### Task 1: 大纲领域服务与本地比较

**Files:**
- Create: `src/novel_flywheel/outlines.py`
- Create: `tests/test_outlines.py`
- Modify: `src/novel_flywheel/story_state.py`

**Interfaces:**
- Produces: `OutlineService.current(project_id)`, `create_candidate(...)`, `list_candidates(...)`, `update_candidate(...)`, `compare(...)`, `apply(...)`, `history(...)`, `restore(...)`。

- [ ] 写失败测试，覆盖旧运行大纲读取、候选创建与查看、候选编辑、结构化变化、锁定事实阻断、整体/逐项应用和版本恢复。
- [ ] 运行 `pytest tests/test_outlines.py -q`，确认因接口不存在而失败。
- [ ] 实现最小领域服务和 StoryState candidate 查询/更新接口。
- [ ] 再次运行聚焦测试，确认通过。

### Task 2: API 与模型语义复核

**Files:**
- Modify: `src/novel_flywheel/app.py`
- Modify: `src/novel_flywheel/api/learning.py`
- Modify: `src/novel_flywheel/learning.py`
- Modify: `tests/api/test_learning.py`

**Interfaces:**
- Produces: `GET /projects/{id}/learning/outlines`、候选编辑、比较、复核、应用、放弃和恢复端点。

- [ ] 写失败 API 测试，覆盖普通中文响应、正文影响提示、revision 冲突和模型不被本地比较调用。
- [ ] 运行聚焦 API 测试确认失败。
- [ ] 接入 OutlineService；语义复核复用 `planning`，限制上下文并验证 JSON。
- [ ] 运行聚焦 API 测试确认通过。

### Task 3: 工作流集成和派生资料失效

**Files:**
- Modify: `src/novel_flywheel/projects.py`
- Modify: `src/novel_flywheel/learning.py`
- Modify: `tests/test_projects.py`
- Modify: `tests/test_learning_system.py`

**Interfaces:**
- Consumes: StoryState `outline` 字段。
- Produces: 约束中的 `Current Confirmed Outline` 和应用后的 stale 派生资料。

- [ ] 写失败测试，证明当前正式大纲进入工作流约束且正文不变。
- [ ] 实现受限长度的当前大纲加载和派生资料失效。
- [ ] 运行聚焦测试确认通过。

### Task 4: 用户界面

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`

**Interfaces:**
- Consumes: Task 2 outline API。
- Produces: 首屏大纲版本区、候选编辑器、变化选择、进度状态和历史恢复。

- [ ] 写失败控制台测试，断言易懂文案、稳定控件和无重复旧入口。
- [ ] 实现页面结构、状态管理和事件处理。
- [ ] 实现桌面/移动响应式布局，操作按钮保持稳定尺寸且无嵌套卡片。
- [ ] 运行控制台测试确认通过。

### Task 5: 创建作品时选择已确认写法

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/api/wizards.py`
- Modify: `tests/api/test_wizards.py`
- Modify: `tests/test_console.py`

**Interfaces:**
- Consumes: 最多 12 条已确认全局候选。
- Produces: 向导完成后显式 adoption，不自动采纳未勾选项。

- [ ] 写失败测试，覆盖勾选、未勾选、低置信度和已拒绝候选。
- [ ] 实现向导摘要与创建后的显式应用。
- [ ] 运行向导与控制台聚焦测试。

### Task 6: 文档和完整验证

**Files:**
- Modify: `README.md`
- Modify: `docs/maintenance.md`

**Interfaces:**
- Produces: 用户流程、数据所有权、回滚和维护说明。

- [ ] 更新文档并扫描设计/计划是否存在占位内容或矛盾。
- [ ] 运行所有相关聚焦测试。
- [ ] 运行 `pytest -q --disable-warnings`。
- [ ] 重启前确认没有活动任务，再启动控制台。
- [ ] 用浏览器检查桌面和移动视口、候选生成状态、比较、应用和恢复，检查控制台错误。
