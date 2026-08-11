# 持久完成、IR 规划与原创性防线 R0–R6

> 警告：`planning_ir_first` 在 R6 真实金丝雀通过前默认关闭，只能按项目显式启用。持久恢复、分段封存、参考蒸馏和原创性发布门禁不依赖该开关。任何路径都不得绕过完整正文、语义、质量和正式晋升门禁。

本方案把“模型返回一次正确结果”改造成“系统持续推进到完整正文，或给出有证据的不可恢复状态”。旧 Markdown 规划仍可读取；新规划路径以版本化语义 IR 为权威，Markdown 仅是兼容视图。

## 启用与回滚一个项目

服务运行后，以下 PowerShell 会选择项目列表中的第一个项目，启用 IR-first，再读取生效范围：

```powershell
$projectId = (Invoke-RestMethod http://127.0.0.1:8000/api/projects)[0].id
$body = @{ enabled = $true; reason = "R6 controlled canary" } | ConvertTo-Json
Invoke-RestMethod -Method Put -ContentType application/json -Body $body `
  "http://127.0.0.1:8000/api/projects/$projectId/rollout-flags/planning-ir-first"
Invoke-RestMethod "http://127.0.0.1:8000/api/projects/$projectId/rollout-flags"
```

项目有活动任务时变更返回 HTTP 409，避免同一运行中途切换权威。回滚不会改写正式稿、StoryState 或旧检查点：

```powershell
$body = @{ enabled = $false; reason = "rollback after canary" } | ConvertTo-Json
Invoke-RestMethod -Method Put -ContentType application/json -Body $body `
  "http://127.0.0.1:8000/api/projects/$projectId/rollout-flags/planning-ir-first"
```

## 系统如何持续完成

| 层级 | 已落地能力 | 成功条件 | 失败处理 |
|---|---|---|---|
| R0 | SQLite 幂等迁移、版本化监督信封、并发安全运行尝试账本、项目级开关 | 任务输入和预算可在重启后重建，非法恢复载荷不会创建/认领任务 | 不持久化密钥和原始错误正文 |
| R1 | 失败分类、独立预算、等待服务状态、检查点续跑 | 传输恢复后从已验证边界继续 | 凭据/能力问题等待用户，预算耗尽才失败 |
| R2 | `PlanningSemanticDraftV2`、严格 Pydantic、唯一包装适配、终段联合合同 | 事件精确覆盖且仅末段为 terminal | 语法本地修复；歧义、多候选和控制字段拒绝 |
| R3 | 不可变分段封存、依赖失效、既有质量候选竞争 | 输入、输出、入口、出口、质量哈希闭合 | 只失效受变更事件或 beat 影响的单元 |
| R4 | 全参考版本分层蒸馏、V2 child disposition、不可变缓存、创作配方 | 每层输入覆盖完整、用途/焦点/合同哈希一致且结果可安全复用 | 单区域重跑，不截断前 100,000 字符；空语义不得冒充已提升 |
| R5 | Winnowing、语义候选、三事件链三道独立门禁 | 发布稿无硬字面或语义重包装风险 | 只重生成证据命中的正文段，再走完整门禁 |
| R6 | 完整正文金丝雀、重启/网络/未知结构/跨题材回归 | 创建或更新正式正文并提交 StoryState | 离线门禁未通过时禁止真实 API 金丝雀 |

完成监督器只管理运行级终态与恢复时机；节点级协议、语义和质量恢复继续由现有 `RecoveryController` 负责。这样不会出现两个状态机同时拥有同一重试决策。

恢复信封采用有限、版本化白名单，而不是可扩张的任意字典。长章节只允许规范化后的 `chapter_goal`；定向返修只允许冻结且去重的 `issue_ids`；初始化只允许版本、正式大纲 SHA-256、初始化答案和完整学习快照。字段名经过分隔符与 camelCase 归一化，并检查常见中英文秘密标签；`auth`、`apiKey`、`providerToken`、`accessToken`、`密钥`、`令牌` 等秘密承载字段均不能落库。验证先于 run 创建/状态认领，避免无恢复输入的孤儿活动任务。

项目开关更新、尝试序号分配和已验证蒸馏缓存写入均使用 SQLite 写事务串行化。开关与任务启动竞争时，唯一合法结果是“开关先提交后启动”或“任务先提交、开关返回 409”；不能在活动写任务中途切换规划权威。已验证缓存发生同键不同输出竞争时只允许第一份成为权威，后一份明确冲突，不能静默覆盖。

## 权威与兼容边界

模型在 IR-first 规划中只拥有标题、事件叙述和中间段出口状态。Runtime 拥有正式事件 ID、顺序、证据、相邻段拓扑和终局权威。第三方路由可以返回标准对象、`data` 包装或嵌套 `result.payload`；统一合同适配器只在恰好一个完整语义对象可证明时转换。两个完整候选、未知机器控制字段、事件重入或终段缺失都会失败关闭。

末段不是“空 handoff 特判”。`AdjacentHandoffIR | TerminalClosureIR` 是文档拓扑的判别联合：中间段必须指向下一段，最终段必须绑定正式结局、最终事件和允许保留的开放义务。悬疑开放结局、悲剧和非线性叙事使用同一合同，不依赖题材关键词。

旧项目兼容策略：

- 未启用 `planning_ir_first` 的项目继续走经过完整回归的旧规划入口。
- 启用后缺少正式事件或结局证据时失败关闭，不从自由正文猜测机器权威。
- 新 IR 同时生成旧五字段 Markdown 视图，供既有因果链、执行清单和检查点读取。
- 回滚只改变下一次运行的项目开关，不降级或改写现有产物。

## 参考资料与原创性

参考来源先按用途隔离：自有、授权、机制参考、文风参考、竞品风险。竞品不能进入项目采纳入口；创作配方仅保存可迁移机制、吸引力规则、文风规则和来源哈希，不携带原文摘录、人物名或具体情节包装。

分层蒸馏缓存键包含来源版本、内容用途、当前 focus、合同版本、层级、区域和区域输入哈希。`DistillationReceiptV2` 必须精确枚举全部 child，并逐项声明 `promoted` 或 `no_transferable_claim`；只要声明提升，聚合语义就必须非空。promoted child 必须由一一对应且不重复的结构化 attribution 覆盖：direct claim/uncertainty 分别指向 Runtime 可解析且互不相同的非空路径；多个 child 共用语义时，只能通过无环 typed merged/superseded 边传递到唯一 anchor。reason 文本、缺失 A/B、悬空关系、重复路径和循环关系都不能证明覆盖。区域按完整序列化负载和估算 Token 双容量分组；版本化 `reference_synthesis` route plan 在主备均可用时取安全共同下界，4K 主路由无法容纳一个语义包而 32K 备用可用时直接走备用，只有主路由时直接走主路由，区域与最终汇总统一经过同一 executor。预算扣除固定协议、本地候选和 4096 输出预留；未知第三方路由按保守 16K 规划。即使只有六项，只要总输入过大也会拆分，不以固定字符切片丢失 JSON；大候选目录改为内容寻址登记，不把截断片段冒充完整集合；不收敛的归并在有界层数内明确失败，不能无限重试。创作蓝图与 recipe 是同一可重建派生对：数据库或 sidecar 任一缺失都会从已采纳节点幂等补齐。`style_rule` 只进入文笔/recipe 样式层，不进入 `plot-structure.creative_methods`；吸引力规则保留在抽象剧情指导层，竞品三类节点均被排除。

所有不同内容哈希的参考版本都会进入本地原创性比较。三道门禁互不代替：

1. Winnowing 给出可复现的精确字面偏移，短场景保留全部 k-gram，长文本采用右端最小指纹。
2. 字符 n-gram 提供离线候选；配置本地语义编码器后以向量余弦补充同义改写召回。语义候选默认需要裁决，不会因宽窗口跨段而自动重写。
3. 结构化事件签名检查连续三步事件链，发现措辞不同但事件包装相同的候选。

硬证据命中后，Runtime 将偏移映射到最小正文段集合，仅修改表达、意象、场景包装和局部动作实现；正式事件顺序、因果、人物主动性、知识、关系、承诺和结局保持不变。修复后重新执行原创性、正文完整性、润色和终审门禁。审计表只存哈希、偏移、类型、严重度和来源版本，不保存参考原文或密钥。

## 验证与故障排查

离线验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_completion_supervisor.py `
  tests/test_planning_semantics.py tests/test_reference_distillation.py `
  tests/test_originality.py tests/test_workflows.py
.\.venv\Scripts\python.exe -m pytest -q
```

应检查这些证据：

- `runs/<run-id>/outputs/planning-semantic-v2.json`
- `runs/<run-id>/outputs/planning-exit-topology-v1.json`
- `runs/<run-id>/outputs/short-causal-chain.json`
- `runs/<run-id>/outputs/short-execution-index.json`
- `runs/<run-id>/outputs/draft-integrity.json`
- `runs/<run-id>/outputs/quality-checkpoint.json`
- `manuscript/story.md` 与已提交的 StoryState revision

`waiting_provider` 表示已验证进度被保留，任务会按持久时间自动继续；它不是失败。`waiting_user` 表示凭据、能力或恢复输入需要用户处理。`failed` 只用于预算耗尽或不可恢复状态。

## Evidence → Finding → Path

| Evidence | Finding | Path |
|---|---|---|
| 运行监督状态、尝试账本、检查点哈希 | 传输中断可自动继续且不重做已验证节点 | `completion_supervisor.py` → `tasks.py` → workflow checkpoint |
| IR、终段拓扑、事件 ownership hash | 最终段不再伪造 next handoff | `planning_semantics.py` → `planning_compiler.py` → causal/manifest/draft |
| 分层 child manifest 与区域输入/输出哈希 | 长参考资料不会因固定字符截断静默漏项 | `reference_distillation.py` → `learning.py` → `creative_recipe` |
| 字面偏移、语义分数、事件链签名 | 相似表达可定位到最小修复范围 | `originality.py` → `manuscript_analysis.py` → publish repair |
| 正文级离线金丝雀和正式稿哈希 | 验收以产出正文为准，不以当前错误消失为准 | full workflow → quality gate → formal promotion |

## 采用的成熟技术

设计借鉴 [Temporal durable execution](https://docs.temporal.io/) 和 [LangGraph persistence](https://docs.langchain.com/oss/javascript/langgraph/persistence) 的持久状态、幂等恢复和检查点思路；结构化边界使用项目已有的 [BAML](https://github.com/BoundaryML/baml)、`json-repair` 与 [Pydantic discriminated unions](https://docs.pydantic.dev/latest/concepts/unions/)；来源审计遵循 [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) 的可追踪思想；原创性门禁采用 Stanford 的 [Winnowing](https://theory.stanford.edu/~aiken/publications/papers/sigmod03.pdf) 与可插拔的 [Sentence Transformers semantic similarity](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html)。这些是工程原则与接口兼容，不代表项目引入 Temporal、LangGraph 或 Sentence Transformers 作为强制运行依赖。
