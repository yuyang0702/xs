# 榜单题材分布图改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将榜单题材分布改为全宽、可比较、文字不截断的分组占比条与图例布局。

**Architecture:** 保留 `/api/market/dashboard` 返回的 `rankings` 数据，不修改后端。`renderMarketRankings` 生成可点击的占比色块和完整图例，CSS 负责全宽布局、稳定颜色、窄屏换行和可聚焦状态。

**Tech Stack:** 原生 JavaScript、CSS、FastAPI 静态资源契约测试、浏览器交互验证。

## Global Constraints

- 不新增依赖。
- 题材颜色在所有榜单中保持一致。
- 色块与图例均可触发当前分类筛选。
- 移动端不缩小字体，图例自动换行。

---

### Task 1: 图表结构与交互

**Files:**
- Modify: `src/novel_flywheel/static/app.js:412`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `renderMarketRankings(rankings)`，其中每项为 `{name, categories}`。
- Produces: `.market-ranking-row`、`.market-ranking-segment`、`.market-ranking-legend-item`，通过 `data-market-category-filter` 复用现有分类筛选。

- [ ] **Step 1: 写失败测试**

在 `test_console_contains_skill_wizard_controls` 中断言脚本包含 `market-ranking-segment`、`market-ranking-legend-item`、`data-market-category-filter` 和题材悬停提示字段。

- [ ] **Step 2: 验证测试失败**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_console.py`

Expected: FAIL，缺少新的榜单图表结构。

- [ ] **Step 3: 实现最小渲染**

将每个榜单渲染为标题、全宽占比条和完整图例。为每个题材建立稳定颜色映射；色块仅在占比足够时显示百分比，`title` 显示题材、作品数和占比。色块与图例使用按钮并绑定分类筛选。

- [ ] **Step 4: 验证测试通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_console.py`

Expected: PASS。

### Task 2: 响应式视觉样式

**Files:**
- Modify: `src/novel_flywheel/static/app.css:177`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: Task 1 生成的榜单行、色块和图例类名。
- Produces: 桌面全宽横条、可换行图例、窄屏单列布局和清晰的焦点状态。

- [ ] **Step 1: 写失败测试**

断言样式表包含 `.market-ranking-track`、`.market-ranking-legend`、`.market-ranking-segment:focus-visible` 和移动端图例规则。

- [ ] **Step 2: 验证测试失败**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_console.py`

Expected: FAIL，缺少新样式。

- [ ] **Step 3: 实现样式**

删除旧的固定 28px 文本色块规则；增加最小 36px 高度的全宽占比条、12px 标签、自动换行图例、稳定间距和 800px 以下的两列/单列响应式规则。

- [ ] **Step 4: 完整验证**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: 全部通过。

- [ ] **Step 5: 浏览器验证与提交**

在桌面与窄屏视口检查文字不截断、图例不重叠、点击分类可更新筛选；随后运行 `git diff --check` 并提交前端、测试和计划文档。
