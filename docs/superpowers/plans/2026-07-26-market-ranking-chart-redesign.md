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
- 榜单作品默认按榜单分组，并可切换为按热度排序的综合浏览。

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

### Task 3: 榜单作品分组与综合浏览

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `state.market.works` 中的 `ranking_name`、`rank`、`metrics` 与作品字段。
- Produces: `#market-work-mode` 分段选择器，以及分组表格行或综合排序表格行。

- [ ] **Step 1: 写失败测试**

断言页面包含 `market-work-mode`，脚本包含 `grouped`、`combined`、`market-ranking-group` 与综合热度排序函数。

- [ ] **Step 2: 验证测试失败**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_console.py`

Expected: FAIL，缺少视图切换与分组结构。

- [ ] **Step 3: 实现视图切换**

默认 `grouped`：按榜单名称分组，组内按原排名和标题排序。`combined`：提取每条记录 `metrics` 中最大数值作为浏览排序值，有数值的降序，无数值的置后，并以榜单、原排名和标题保证稳定顺序；第一列显示连续序号，作品信息旁保留“原榜第 N 名”。

- [ ] **Step 4: 实现分组样式与响应式布局**

为榜单组标题、分段控件和原榜排名增加紧凑样式；移动端保持表格横向滚动，不压缩作品标题。

- [ ] **Step 5: 验证**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: 全部通过，并在浏览器中验证两种模式切换。

### Task 4: 热门词详情收起与日期排名

**Files:**
- Modify: `src/novel_flywheel/market.py`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/test_market.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: 统计周期内 `market_entries` 与 `market_snapshots.captured_at`。
- Produces: 热门词证据作品的 `daily_best`、`period_best`，以及可收起的详情面板。

- [ ] **Step 1: 写失败测试**

构造同一天多次快照和跨日快照，断言同日取最好名次，周期最高保留日期与榜单；前端契约断言关闭按钮、重复点击切换和 `Escape` 处理存在。

- [ ] **Step 2: 实现日期排名聚合**

按北京时间日期聚合每部作品的最低排名；最新有数据日期作为 `daily_best`，统计周期内最低排名作为 `period_best`，并以榜单名稳定处理并列。

- [ ] **Step 3: 实现详情收起交互**

详情顶部使用关闭图标按钮；重复点击当前词、点击关闭图标或按 `Escape` 时隐藏详情并移除选中态，点击其他词时替换详情和选中态。

- [ ] **Step 4: 验证**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: 全部通过，并在浏览器验证展开、切换和三种收起方式。
