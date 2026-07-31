# 润色恢复闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 普通润色遇到空正文、明显超长或输出达到上限时，改用精简提示依次重试首选和备用模型；两者都失败则保留原文并继续，且页面清楚显示完成段数与保留原文段数。

**Architecture:** 保留现有 `_polish_short_segments()`、`_stage()`、角色绑定、本地验收和来源哈希检查点为唯一工作流。只在普通润色片段调用周围增加一个精简恢复分支和当前运行内的连续异常计数；使用现有运行事件向前端提供进度，不新增数据库表、依赖或权威状态。

**Tech Stack:** Python 3.11、asyncio、pytest、原生 JavaScript、现有 SQLite 运行事件。

---

## 文件边界

- `src/novel_flywheel/workflows.py`：构造精简恢复提示、区分输出异常与致命配置错误、调用首选/备用模型、记录非授权保留原文状态和段落进度。
- `src/novel_flywheel/models.py`：提供不会自动切换备用模型的首选模型调用入口，仅供需要显式控制恢复顺序的流程使用。
- `tests/test_workflows.py`：用模拟网关覆盖恢复顺序、熔断、继续运行、立即停止错误和既有传输拆分。
- `tests/test_models.py`：验证首选模型专用入口不会偷偷调用备用模型，既有自动回退入口保持不变。
- `src/novel_flywheel/static/app.js`：把恢复事件转成简单中文状态和聚合进度，任务结束后停止忙碌状态。
- `tests/test_console.py`：锁定页面必须出现的中文提示并排除内部术语。
- `docs/maintenance.md`：记录恢复顺序、检查点语义、运行边界和排障方法。

### Task 1: 后端精简恢复顺序

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `src/novel_flywheel/workflows.py`

- [ ] **Step 1: 写输出异常进入精简首选模型的失败测试**

测试构造一个普通润色片段，模拟第一次 `_stage()` 抛出带 `finish_reason=max_tokens` 的空正文错误，第二次返回合格正文，并断言：第二次仍使用首选模型、提示只含当前片段和有限相邻上下文、没有固定 8192 输出重试、没有触发正文拆分事件。

```python
@pytest.mark.asyncio
async def test_polish_output_limit_retries_primary_with_compact_prompt(tmp_path):
    result = await service._polish_short_segments(
        "run", run_path, project, "constraints", source, "{}",
    )
    assert result == compact_success
    assert len(calls) == 2
    assert calls[1]["prefer_configured_fallback"] is False
    assert "只返回修改后的正文" in calls[1]["prompt"]
    assert not any(e["event_type"] == "polish_segment_split" for e in events)
    assert not any(e["event_type"] == "polish_max_tokens_retry" for e in events)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_workflows.py::test_polish_output_limit_retries_primary_with_compact_prompt`

Expected: FAIL；当前实现仍在 `_stage()` 中提高输出额度，之后由 `_polish_short_segments()` 拆分正文。

- [ ] **Step 3: 实现最小精简恢复入口**

在 `_polish_short_segments()` 内复用当前片段已经计算出的 `local_report`、`previous_context`、`next_context`、人物指纹、锁定事实和保护片段，增加以下同等语义的私有辅助函数；普通首选调用仍保留，只有输出异常才进入此分支。

```python
def _compact_polish_prompt(*, segment, previous_context, next_context,
                           local_findings, character_voice, locked_facts,
                           passage_locks, minimum_characters,
                           maximum_characters) -> str:
    return (... + "只返回修改后的正文，不解释、不分析。")

def _is_polish_output_error(exc: Exception) -> bool:
    return any(marker in describe_error(exc).lower() for marker in (
        "empty output", "empty manuscript", "finish_reason=max_tokens",
        "output exceeds", "明显超长",
    ))
```

精简首选重试直接调用现有 `_stage()`，通过新增的内部参数禁止 `_stage()` 自己提高到 8192；输出额度继续由现有基于 `output_source_characters` 的算法计算。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `pytest -q tests/test_workflows.py::test_polish_output_limit_retries_primary_with_compact_prompt`

Expected: PASS。

### Task 1A: 生产网关首选模型专用入口

**Files:**
- Modify: `tests/test_models.py`
- Modify: `src/novel_flywheel/models.py`

- [ ] **Step 1: 写真实网关路径的失败测试**

主模型抛出 `missing_api_key`、备用模型可成功时，调用 `complete_primary()` 必须原样抛出主模型错误，备用模型调用次数必须为 0；调用原有 `complete()` 仍应自动切换备用模型并成功。

```python
@pytest.mark.asyncio
async def test_complete_primary_never_uses_configured_fallback():
    with pytest.raises(RuntimeError, match="missing_api_key"):
        await gateway.complete_primary("polish", "system", "user")
    assert primary.calls == 1
    assert fallback.calls == 0
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_models.py -k "complete_primary"`

Expected: FAIL；当前 `ModelGateway` 没有只调用首选模型的入口。

- [ ] **Step 3: 最小重构网关**

新增 `complete_primary()`，只解析并调用角色绑定的首选提供商；让现有 `complete()` 调用它后继续使用原有自动备用逻辑。`complete_configured_fallback()` 保持不变，不增加配置或依赖。

- [ ] **Step 4: 运行网关测试并确认 GREEN**

Run: `pytest -q tests/test_models.py`

Expected: 0 failed。

### Task 2: 备用模型、保留原文与错误边界

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `src/novel_flywheel/workflows.py`

- [ ] **Step 1: 写三组失败测试**

```python
@pytest.mark.asyncio
async def test_polish_compact_primary_failure_uses_configured_fallback(tmp_path): ...

@pytest.mark.asyncio
async def test_polish_both_compact_routes_fail_preserves_source_and_continues(tmp_path): ...

@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["missing api key", "authentication failed", "invalid role binding"])
async def test_polish_fatal_configuration_error_stops_immediately(tmp_path, message): ...
```

断言备用调用设置 `prefer_configured_fallback=True`；主备失败后结果中该段保持原文且下一段仍调用；密钥、身份验证或损坏绑定错误原样抛出，不记录“保留原文并继续”。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_workflows.py -k "compact_primary_failure or both_compact_routes_fail or fatal_configuration_error"`

Expected: FAIL；当前普通润色没有完整的主备精简恢复和非授权保留状态。

- [ ] **Step 3: 实现恢复状态机和事件**

在单个普通片段内按固定顺序执行，保留既有本地验收备用模型逻辑：

```python
normal -> compact_primary -> compact_fallback -> preserve_source
```

记录中文事件：`polish_compact_retry`、`polish_compact_fallback`、`polish_segment_preserved`、`polish_segment_progress`。事件元数据包含 `segment`、`total`、`completed`、`preserved` 和内部错误信息；用户可见消息不含 `max_tokens`、路由或熔断。

新增 `_is_fatal_model_configuration_error()`，在任何保留原文判断前识别身份验证、缺失密钥和角色绑定损坏并重新抛出。502、504、524 和连接失败仍交给现有 `_split_failed_polish_segment()`，输出异常不再拆分。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `pytest -q tests/test_workflows.py -k "compact_primary_failure or both_compact_routes_fail or fatal_configuration_error"`

Expected: PASS。

### Task 3: 熔断与可继续检查点

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `src/novel_flywheel/workflows.py`

- [ ] **Step 1: 写连续异常和继续运行失败测试**

```python
@pytest.mark.asyncio
async def test_polish_two_consecutive_output_errors_skip_full_prompt_for_later_segments(tmp_path): ...

@pytest.mark.asyncio
async def test_polish_resume_reuses_accepted_segments_and_retries_preserved_segments(tmp_path): ...
```

第一组断言同一运行连续两个片段发生输出异常后，第三个片段直接从精简首选开始；新 run id 会恢复正常首选调用。第二组先让第一段成功、第二段主备失败，再次运行时断言第一段不调用模型、第二段重新尝试。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_workflows.py -k "two_consecutive_output_errors or resume_reuses_accepted"`

Expected: FAIL；当前检查点只有已接受正文，没有显式的非授权保留状态，现有熔断语义也不是连续输出异常计数。

- [ ] **Step 3: 实现运行内连续异常计数和非授权状态**

使用 `_polish_short_segments()` 当前调用栈内的局部状态，不新增持久配置。连续输出异常计数达到 2 时记录一次 `polish_compact_circuit_opened`，后续片段跳过完整提示；任一正常完整输出成功时重置连续计数。

扩展现有检查点 JSON，保存以下兼容字段：

```json
{"source_hash":"...","polished":"...","accepted":false,"status":"preserved_source"}
```

`_load_polish_checkpoint()` 只返回 `accepted` 缺失或为 `true` 的旧/新检查点；`preserved_source` 只供 `_polish_checkpoint_progress()` 和页面统计，继续运行时不能复用为润色结果。

- [ ] **Step 4: 运行测试并确认 GREEN，并回归传输拆分**

Run: `pytest -q tests/test_workflows.py -k "two_consecutive_output_errors or resume_reuses_accepted or splits_segment"`

Expected: PASS；输出异常不拆分，传输错误仍拆分。

### Task 4: 页面中文进度与结束状态

**Files:**
- Modify: `tests/test_console.py`
- Modify: `src/novel_flywheel/static/app.js`

- [ ] **Step 1: 写页面文案和状态失败测试**

```python
def test_console_explains_polish_recovery_in_plain_chinese(client):
    body = client.get("/static/app.js").text
    assert "正在精简要求后重新润色本段" in body
    assert "首选模型没有返回正文，正在使用备用模型" in body
    assert "本段未完成精修，已保留原文并继续" in body
    assert "继续运行时只处理未完成片段" in body
```

同时锁定聚合格式“已完成 2 / 4 段，其中 1 段保留原文”，并验证终态 `completed`、`failed`、`cancelled`、`interrupted` 不保留忙碌样式或继续轮询。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_console.py -k "polish_recovery or run_progress"`

Expected: FAIL；页面尚未汇总润色恢复事件。

- [ ] **Step 3: 最小扩展现有运行状态渲染**

在 `showRunDetail()` 和 `monitorRun()` 共用的事件解析逻辑中，从最新 `polish_segment_progress` 读取总段数、完成数和保留原文数；最新恢复事件决定当前中文提示。继续使用现有 `busy` 类和轮询终止判断，不增加新组件或依赖。

```javascript
function polishProgress(events) {
  const progress=[...events].reverse().find(item=>item.event_type==="polish_segment_progress");
  return progress ? `已完成 ${progress.metadata.completed} / ${progress.metadata.total} 段，其中 ${progress.metadata.preserved} 段保留原文` : "";
}
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `pytest -q tests/test_console.py -k "polish_recovery or run_progress"`

Expected: PASS。

### Task 5: 维护说明、回归与完整验证

**Files:**
- Modify: `docs/maintenance.md`
- Verify: `src/novel_flywheel/workflows.py`
- Verify: `src/novel_flywheel/static/app.js`
- Verify: `tests/test_workflows.py`
- Verify: `tests/test_console.py`

- [ ] **Step 1: 更新维护说明**

写明普通润色的“完整首选 → 精简首选 → 精简备用 → 保留原文”顺序、连续两次输出异常后的当前运行保护、非授权检查点继续运行语义、传输拆分保留，以及密钥/身份/绑定错误必须立即停止。

- [ ] **Step 2: 运行聚焦与模块测试**

Run: `pytest -q tests/test_workflows.py`

Expected: 0 failed。

Run: `pytest -q tests/test_console.py`

Expected: 0 failed。

- [ ] **Step 3: 运行完整验证**

Run: `pytest -q`

Expected: 0 failed；允许项目既有的 1 个 skip。

Run: `python -m compileall -q src tests`

Expected: exit 0。

Run: `node --check src/novel_flywheel/static/app.js`

Expected: exit 0。

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 4: 安全重启和配置核验**

先通过本地 API/数据库确认所有项目活动任务数为 0；若存在 `queued`、`running` 或 `cancelling`，不重启。为保留 Windows 凭据管理器访问，使用桌面权限运行 `start-novel-console.cmd`，随后验证页面可访问、5 个项目存在、6/6 密钥可用、10/10 角色绑定完整。

本计划不自动提交或推送，保留当前工作区中用户尚未提交的既有改动。
