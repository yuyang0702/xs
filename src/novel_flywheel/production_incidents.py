from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


@dataclass(frozen=True)
class IncidentDefinition:
    family: str
    title: str
    known_resolution: str
    patterns: tuple[str, ...]


# This catalog records production failure families that have already occurred in
# the writing workflow.  Matchers intentionally describe root-cause boundaries,
# not one novel's names, file paths, segment numbers, or provider wording.
INCIDENT_DEFINITIONS = (
    IncidentDefinition(
        "provider.route_rejected",
        "A configured model route was rejected before producing a terminal receipt",
        "Preserve the best authority-bound checkpoint, retry the same explicit route only within the bounded protocol budget, then select the configured independent fallback through the outer recovery schedule. Probe route capability without story data when diagnosis is needed. Treat authentication, route policy, and model availability as transport reliability—not story drift—and resume only the smallest blocked receipt.",
        (
            r"protocol_route_provider_rejection",
            r"(?:http|status code)\s*(?:401|403)",
            r"(?:unauthorized|forbidden).*(?:provider|route|terminal response)",
        ),
    ),
    IncidentDefinition(
        "provider.credentials_unavailable",
        "Provider credentials are unavailable to the active runtime",
        "Verify the active console data directory, Windows credential service, provider IDs, and primary/fallback bindings; preserve the best narrative checkpoint and resume only the blocked repair after credentials are visible to the same runtime.",
        (
            r"missing[_ ]api[_ ]key",
            r"api key is missing",
            r"credentials? (?:missing|unavailable|not found)",
            r"authentication.*(?:missing|unavailable)",
        ),
    ),
    IncidentDefinition(
        "runtime.stale_console_process",
        "Active console process is older than the current source tree",
        "Compare the health runtime fingerprint before reuse; keep any old process and active task alive, start the current source on a free local port, and direct the user to the fresh runtime instead of silently executing stale recovery logic.",
        (
            r"stale (?:console|runtime|process)",
            r"runtime fingerprint.*(?:mismatch|stale|different)",
            r"old (?:console|runtime) process",
            r"source tree.*(?:older|newer).*(?:console|runtime)",
        ),
    ),
    IncidentDefinition(
        "initialization.location_backlink_missing",
        "初始化地点与人物反向链接缺失",
        "由 Runtime 对人物 locations 与地点 notable-characters 做确定性双向闭合，随后原子执行 reindex、links 和 validate。",
        (
            r"missing location backlink",
            r"missing location backlinks",
            r"地点.*缺少反向",
            r"location backlink.*missing",
        ),
    ),
    IncidentDefinition(
        "initialization.location_reference_missing",
        "初始化引用了尚不存在的地点",
        "保留人物资料，交由世界设定阶段补齐明确地点文件；无法唯一对应的 ID 不猜测，并在链接验证前停止提交。",
        (
            r"references missing location",
            r"引用的地点.*不存在",
            r"missing location\s+[\w.-]+",
        ),
    ),
    IncidentDefinition(
        "initialization.relationship_inverse_mismatch",
        "人物关系反向类型不一致",
        "按关系逆向映射核对双方档案，只修复明确且唯一的结构化关系；冲突或重复关系保持失败关闭。",
        (
            r"expects backlink type.*got",
            r"反向关系类型不一致",
            r"relationship.*backlink.*(?:mismatch|expects)",
        ),
    ),
    IncidentDefinition(
        "provider.connection_failed",
        "模型供应商连接失败",
        "保留已完成检查点，按传输错误策略重试当前最小语义任务，再使用已配置备用路由；两条路由均失败时允许原任务续跑。",
        (
            r"connecterror",
            r"all connection attempts failed",
            r"connection (?:reset|closed|terminated|refused)",
            r"network.*(?:failed|terminated|interrupted)",
        ),
    ),
    IncidentDefinition(
        "model.context_capacity_indivisible_scope",
        "模型上下文容量恢复到最小语义范围后仍未继续分层",
        "保留完整父级权威，将单个正式事件按不变量审核维度分层，并用精确事件原文投影、哈希绑定和完整覆盖回执合并；若单个维度仍超限，再按完整重叠证据窗口归并，最后重跑父段和整篇验证。",
        (
            r"单个(?:正式)?事件不可再拆分",
            r"indivisible planning event",
            r"single(?:ton)?.*event.*(?:context|capacity).*(?:overflow|limit)",
        ),
    ),
    IncidentDefinition(
        "planning.runtime_identity_echo_mismatch",
        "模型回执重复生成了错误的运行时身份字段",
        "把 authority、规划哈希、范围、窗口索引和原文哈希作为 Runtime 所有的请求信封；新鲜调用只提交不变量、当前证据 ID、连续负面引文和理由。语义载荷通过当前不可变证据校验后由 Runtime 封装并记录无正文哈希审计；历史检查点仍要求完整身份逐字段匹配。语义证据无效时只重试当前最小回执，不重写规划或正文。",
        (
            r"单事件审核窗口回执未绑定完整范围或原文哈希",
            r"facet window receipt.*(?:authority|identity|hash|range).*(?:mismatch|unbound|invalid)",
            r"planning_adaptation_runtime_identity_echo",
        ),
    ),
    IncidentDefinition(
        "planning.reviewed_dimensions_echo_conflict",
        "Planning facet dimension roles conflict with the invariant verdict",
        "Treat facet changed_dimensions as descriptive model output, not structural authority. Preserve hash-verified leaf checkpoints, merge the complete invariant map, derive structural deviations only from explicit false invariants, and reclassify known dimensions whose invariants are true as reviewed narrative scope. Keep free-form dimensions as equivalent presentation metadata. Any false invariant remains a blocking structural deviation with exact evidence and retries or repairs only its smallest authority-bound unit; this reconciliation never rewrites planning or prose and the unchanged parent validator must still pass.",
        (
            r"adaptation_receipt_conflict.*described_structural_dimensions.*raw_changed_dimensions",
            r"adaptation_receipt_conflict.*model_classification.*equivalent.*raw_changed_dimensions",
            r"planning_adaptation_reviewed_dimensions_echo",
        ),
    ),
    IncidentDefinition(
        "planning.invariant_truth_set_shape",
        "Planning facet returned an invariant truth set instead of a boolean map",
        "At the fresh facet conversion boundary, accept a list only when it contains every requested invariant name exactly once, contains no unknown value, and has no partial protected-dimension conflict; expand that closed truth set into an all-true boolean map and retain hash-only audit. A partial, duplicate, unknown, or structurally conflicting set remains invariant_shape and retries only the same authority-bound facet. Every planning receipt route uses the dedicated immutable-receipt system contract instead of the generic editorial scorecard contract; an unrelated quality scorecard must not be adapted into facet semantics. Historical checkpoints remain strict, and the resulting receipt must still pass evidence binding, parent invariant merge, dimension-role reconciliation, and the unchanged whole-plan validator.",
        (
            r"invariant_shape",
            r"planning_adaptation_facet.*closed truth set",
            r"facet.*invariant truth set",
        ),
    ),
    IncidentDefinition(
        "planning.execution_manifest_handoff_echo_mismatch",
        "Execution manifest paraphrased an accepted adjacent handoff",
        "Treat the previous accepted segment exit and its SHA-256 as Runtime-owned authority. On fresh model output, inject every exact accepted exit assertion into the next segment entry while retaining the model's additional entry assertions, record only counts and hashes, and rerun the unchanged fragment, adjacent-boundary, and whole-manifest validators. Do not normalize malformed entry-state containers or rewrite narrative content; those failures keep their normal schema-repair path. Historical checkpoints remain strict and any unrelated ownership, ordering, producer, or semantic issue still blocks the smallest affected fragment.",
        (
            r"adjacent_boundary_mismatch",
            r"planning_manifest_runtime_handoff_bound",
            r"execution manifest.*(?:paraphras|echo).*(?:adjacent|handoff|entry state)",
        ),
    ),
    IncidentDefinition(
        "model.context_capacity_preflight",
        "模型上下文容量检查触发但未完成语义分包",
        "保留完整规划、最佳候选和问题账本；先将模型选中的非连续引文安全对齐到唯一、足够长的原文片段，再移除可再生的非权威建议层，强制故事权威不得删减。无论本地预检还是供应商实际返回 context_length_exceeded/HTTP 413，剩余压力都进入同一语义所有权 splitter。审核按事件所有权递归分包，定向 JSON 补丁使用协议型输出预算，完整段重建使用当前段作用域预算，主备路由遵守同一容量合同。失败候选只消耗当前恢复尝试，随后重跑局部、相邻边界和整篇审核，通过后才继续因果链与正文。",
        (
            r"input context overflow preflight",
            r"context window.*topology=(?:compact|split)",
            r"stage_capacity_split_required",
            r"context capacity",
            r"context_length_exceeded",
            r"maximum context length",
            r"context window exceeded",
            r"(?:http|status code)\s*413",
            r"prompt (?:is )?too long",
        ),
    ),
    IncidentDefinition(
        "runtime.required_tool_output_missing",
        "受控运行缺少必需工具输出",
        "仅重试缺失的机器协议步骤并复用已保留候选；不得把协议失败转化为正文重写。",
        (
            r"controlled runtime ended without required tool output",
            r"required tool output",
            r"缺少必需.*工具输出",
        ),
    ),
    IncidentDefinition(
        "runtime.primary_error_masked",
        "运行包装清理异常遮蔽了原始业务失败",
        "在进入 CrewAI 包装层前保存原始业务异常及其回溯；若事件、追踪或内存清理随后失败，仍以原始业务错误作为任务终态，并把包装层异常保留为异常链证据，不得让通用系统错误替换可执行的恢复原因。",
        (
            r"\[errno 22\]\s*invalid argument",
            r"primary (?:workflow|pipeline) error.*(?:masked|replaced).*(?:cleanup|wrapper)",
            r"运行包装.*遮蔽.*原始.*失败",
        ),
    ),
    IncidentDefinition(
        "planning.typed_ir_scope_collision",
        "Creative planning prose was mistaken for a Runtime control field",
        "Compile every accepted segment into the versioned, content-addressed planning IR before causal-chain, manifest, drafting, split/merge, polish, revision, final-review, or promotion boundaries. Runtime-owned field envelopes are validated and masked before Markdown parsing, so headings inside opaque event narrative never gain control authority. Provider JSON and tool wrappers pass only through the registered topology adapter, which proves exact ordered event ownership, rejects partial, duplicate, conflicting, or command-bearing shapes, and records hash-only conversion audit. Legacy checkpoints that cannot prove the current Planning IR binding fail closed and regenerate from the last complete accepted authority; retain that plan on any ambiguity, and rerun local, adjacent, whole-plan, complete-draft, semantic, and quality gates without rewriting unaffected prose.",
        (
            r"owned planning field.*(?:content hash|incomplete|unmatched)",
            r"typed planning ownership.*formal event order",
            r"planning ir.*(?:corrupt|stale|incomplete|scope collision)",
            r"creative.*heading.*(?:planning|runtime).*(?:control|handoff)",
            r"nested narrative heading.*(?:handoff|control field)",
        ),
    ),
    IncidentDefinition(
        "parser.generated_artifact_shape",
        "Generated artifact presentation was indexed before safe normalization",
         "Normalize harmless Markdown or HTML wrappers at the shared parser boundary. Compare segment identities, labels, and event IDs through one offset-preserving Unicode protocol view that accepts width variants, Unicode dash/slash families, non-breaking spaces, open heading suffixes, and base-event IDs with atomic-beat suffixes without rewriting prose. Markdown plan fields rendered as peer headings or with noncanonical visible labels may be projected locally only when the segment and exact ordered event ownership remain unchanged; Runtime-owned outline evidence is retained from the current formal plan. JSON container names and nesting are an open presentation set: recursively discover leaf-most event records in a top-level event array, an event-ID mapping, or any unambiguous nested container only through exact event identity, validate every declared segment and explicit ordered ownership sequence, and derive entry/exit state without granting wrapper names authority. Reject conflicting identities, duplicate or reordered ownership, ambiguous boundaries, and unknown machine-control fields instead of guessing. A structured summary is bound to the exact retained event-owned body and may add only explicit narrative obligations or boundaries; a complete narrative realization remains a creative candidate. Both routes rerun body retention, obligation, adjacent-handoff, and whole-plan validation. Explicit SEGMENT-ONLY packets remain accepted only when identity and protocol fields are unambiguous. Descriptive references to adjacent event IDs never gain ownership. After deterministic normalization fails on a normal provider result, rewrap only the same segment and ordered event set under immutable outline and entry/exit authority; this protocol retry does not consume another semantic-repair attempt. Carry exact field or contract failures into that bounded same-scope retry. If canonical rewrap still fails, retain the best checkpoint and report planning_packet_protocol_exhausted under parser.generated_artifact_shape rather than planning.structure_drift. Validate the expected artifact count before indexing and reuse completed hash-matched packets instead of blindly repeating a generic generation failure.",
        (
            r"^list index out of range$",
            r"generated (?:planning )?(?:packet|artifact).*missing exactly one recognizable segment heading",
            r"planning repair (?:packet|candidate).*recognizable segment heading",
             r"planning repair (?:packet|candidate).*JSON packet.*(?:ambiguous|changed|lacks|missing|has no|event lacks)",
             r"planning repair (?:packet|candidate).*JSON event array.*(?:ambiguous|changed|lacks|missing|invalid)",
             r"SEGMENT-ONLY.*(?:segment identity|packet fields|event ownership)",
            r"planning_packet_summary_authority_missing",
            r"planning_packet_unknown_control_field",
            r"planning_packet_protocol_exhausted",
            r"planning packet protocol recovery exhausted",
            r"planning repair (?:packet|candidate) failed its complete (?:event|segment) contract",
            r"planning_packet_(?:field_missing|field_ambiguous|event_ownership|segment_shape)",
        ),
    ),
    IncidentDefinition(
        "model.output_truncated",
        "模型输出达到上限或疑似截断",
        "先验证输出闭合性；不完整时只增加一次可验证余量。再次触顶后进入统一语义分包协议：优先沿完整故事段边界递归拆分，再缩小到连续事件；每包绑定权威哈希、唯一有序所有权、只读邻接上下文和前序结果哈希，已验证叶子立即原子检查点。不可再拆的事件切换到已配置备用模型；仍失败则保留所有合格上游和叶子，禁止机械截断或把部分结果晋升为正式资料。所有叶子经确定性无重无漏合并和整链校验后，才允许进入下一道执行清单边界。",
        (
            r"max[_ -]?tokens",
            r"finish[_ -]?reason.*(?:length|output_limit)",
            r"output.*(?:truncated|limit)",
            r"输出.*(?:截断|上限)",
            r"字段截断",
        ),
    ),
    IncidentDefinition(
        "provider.structured_output_business_incomplete",
        "A third-party route returned a terminal but business-incomplete structured artifact",
        "Retain the last complete authority-bound checkpoint. Quarantine the exact immutable route, execution mode, contract, and schema digest; do not let a tiny capability probe clear that evidence. Retry the immutable receipt once through prompt JSON on the same route, then select the configured independent fallback. If the receipt is output-limited, expand verified headroom once and split only by semantic ownership. Re-enter canonical conversion and the unchanged domain validator before resuming the smallest blocked unit through its next authoritative boundary.",
        (
            r"structured business output remained incomplete after route recovery",
            r"normal_finish_empty_structured_output",
            r"structured[_ -]output.*(?:empty_object|underfilled|required_fields_missing)",
            r"business qualification payload.*(?:empty|incomplete|short)",
        ),
    ),
    IncidentDefinition(
        "planning.causal_chain_invalid",
        "因果链解析或正式事件覆盖不完整",
        "保留正式大纲与最佳规划；完整响应先进行一次同范围协议重试，仍不合格则进入内容寻址的语义分包任务树，只重建失败的连续事件范围并复用已验证分包。覆盖、顺序、唯一所有权、邻接状态和整链因果全部通过后才生成执行清单和正文。",
        (
            r"因果链解析失败",
            r"因果链未覆盖全部正式事件",
            r"causal chain.*(?:parse|coverage|incomplete|missing)",
        ),
    ),
    IncidentDefinition(
        "planning.recovery_latent_issue_misattributed",
        "未修改规划段的潜伏旧问题被误归因给当前修复候选",
        "按最佳规划与候选规划的实际分段哈希确定变更所有权；只把变更段、与其相交的相邻边界问题及整篇问题归因给当前候选。未修改段中新发现的问题无损并入最佳问题账本并成为后续独立修复单元，已通过段在重新核对相邻衔接与整篇结构后继续保留。",
        (
            r"未修改.*段.*(?:潜伏|既有|旧)问题.*(?:误归因|误判).*(?:候选|修复)",
            r"latent baseline issue.*(?:misattribut|introduced hard issue)",
            r"unchanged segment.*(?:issue|finding).*(?:blamed|attributed).*(?:candidate|repair)",
        ),
    ),
    IncidentDefinition(
        "planning.structure_drift",
        "规划偏离正式剧情结构",
        "从单调最佳候选恢复，按受影响的完整正式段逐段修复和即时检查点晋升；某段失败不得撤销其他已通过段。每个保留段仍须复核剧情功能、主动性、因果、顺序、结局承诺、相邻衔接和整篇一致性后才能继续。",
        (
            r"规划存在结构性偏移",
            r"规划改变了正式事件",
            r"规划调整改变了正式剧情方向或结局承诺",
            r"规划调整改变了正式事件的展示或依赖顺序",
            r"规划未能.*维持正式剧情结构",
            r"规划恢复尚未收敛",
        ),
    ),
    IncidentDefinition(
        "planning.review_evidence_semantic_mismatch",
        "规划审稿问题与所绑定的当前原文不一致",
        "把它视为审核回执协议缺陷：负面不变量必须绑定当前候选中的精确问题短语，理由必须逐字包含该短语；不匹配时只重做审核回执，不消耗规划修复预算。证据有效后，返修锚点缩到包含该短语的最小 Runtime 原文句，再复核完整事件体、相邻交接与整篇结构。",
        (
            r"没有用当前规划原文中的具体问题句证明负面判断",
            r"planning review.*(?:stale|unrelated).*(?:evidence|quote)",
            r"review reason.*does not.*selected.*plan evidence",
        ),
    ),
    IncidentDefinition(
        "planning.review_evidence_binding_invalid",
        "规划审核回执没有绑定当前规划段原文",
        "将审核回执视为协议缺陷而不是剧情缺陷；从当前候选的 Runtime 原文重新生成精确证据回执，校验原文哈希、事件归属和证据出现位置，回执通过后才恢复语义修复预算。",
        (
            r"evidence[_ ]binding",
            r"evidence_quote_unbound",
            r"回执.*没有绑定.*当前规划",
            r"规划适配回执.*准确原文",
            r"review receipt.*(?:bind|binding).*(?:current|exact).*plan",
        ),
    ),
    IncidentDefinition(
        "planning.review_protocol_route_exhausted",
        "规划回执在同一审查路由上重复出现协议不确定",
        "保留当前最佳完整规划和不可变审核权威；协议缺陷使用独立于语义修复的预算，先重试同一最小回执，耗尽后切换 review 角色配置的备用模型并重新通过同一合同、证据、局部、相邻和整篇门禁。备用路由仍不合格时才恢复最佳候选并保留可续跑检查点，不得把回执缺陷转成规划或正文重写。",
        (
            r"规划第\s*\d+\s*段分包审核回执无效.*adaptation_[a-z0-9_]+",
            r"planning adaptation.*receipt.*protocol.*(?:exhausted|uncertain)",
            r"adaptation_order_uncertain",
        ),
    ),
    IncidentDefinition(
        "planning.plan_structure_validation_failed",
        "规划设定或分段结构校验未通过",
        "先由统一规划编译边界把开放展示标签映射到封闭语义角色，并区分事件实现与独立的因果关系说明；如果身份绑定且完整的事件正文已经存在，保留全部源文本，只让事件实现承担必需字段角色，不因伴随的因果说明制造第二份互斥正文。真正的字段缺失、身份歧义或正文不完整仍保留最后完整规划和有效上游检查点，按正式事件合同只重建受影响完整段；重新核对设定、事件覆盖、顺序、入口出口和整篇因果后，只有通过下一权威边界才允许生成正文。",
        (
            r"规划稿未通过设定和分段检查",
            r"规划稿仍有设定或分段问题",
            r"planning plan.*(?:structure|segment).*validation.*failed",
        ),
    ),
    IncidentDefinition(
        "planning.event_body_integrity",
        "规划正式事件正文缺失、重复或共享归属未被正确识别",
        "先按统一事件正文边界解析并允许相邻事件 ID 绑定同一段完整执行正文；仍缺失、重复或顺序错误时，只重建受影响的完整规划段，并重新核对事件覆盖、执行者、动作、结果及相邻交接后再进入因果链。",
        (
            r"规划正式事件.*(?:只在段首清单|缺少足以核对|重复声明)",
            r"event_body_(?:missing|incomplete|duplicate|order)",
        ),
    ),
    IncidentDefinition(
        "planning.presentation_normalized_ownership_revealed",
        "规划展示格式已归一化并显露更晚阶段的事件归属问题",
        "把表格、标题、列表或卡片视为展示层，经统一 AST 编译为闭合规划字段；格式阶段通过后，将新显露的事件正文归属记为更晚验证阶段，而不是回滚格式修复。只补齐受影响完整分段的逐事件可执行正文，保持其他分段、入口、出口、正式大纲和既有创作素材不变，再依次复核相邻交接、整篇逻辑和质量。",
        (
            r"规划(?:表格|展示|格式).*(?:本地|已经|已)(?:归一化|规范化).*(?:显露|发现).*(?:事件正文|事件归属)",
            r"planning presentation.*normaliz.*(?:reveal|discover).*(?:event ownership|event body)",
        ),
    ),
    IncidentDefinition(
        "planning.packet_merge_closedness",
        "容量分包在单包通过后无法无损合并为可验证的完整规划段",
        "每个事件分包先归一化为明确的正文级事件归属，再按原始事件顺序无损合并；合并后的完整段重新执行事件正文、义务、保留度、相邻交接与整篇规划检查。若任一分包归属无法确定，保留最佳完整规划并只重试受影响分包，不把合并失败误判为模型正文失败。",
        (
            r"planning capacity split returned an incomplete artifact",
            r"packet merge.*(?:incomplete|closedness|ownership)",
            r"capacity split.*(?:merge|merged).*(?:incomplete|ownership)",
        ),
    ),
    IncidentDefinition(
        "planning.participant_identity_realization_mismatch",
        "规划参与者的规范身份与叙事文本实现不一致",
        "保留正式大纲中的规范人物身份，由项目叙事契约提供第一人称叙述者的文本实现；只在非对白叙事声部中接受经过契约绑定的自称，不根据单篇小说的人名、昵称或模型猜测扩展别名。第三人称仍按规范姓名核对，对白中的自称、未知别名和身份不一致一律失败关闭。修复后重新验证所属完整规划段和下一道整篇因果链边界，不为通过检查而把第一人称改写成第三人称姓名。",
        (
            r"participant_identity_realization_mismatch",
            r"first[-_ ]person.*participant.*(?:identity|realization).*(?:mismatch|missing)",
            r"第一人称.*(?:参与者|叙述者).*(?:身份|指代).*(?:误判|不一致|缺失)",
        ),
    ),
    IncidentDefinition(
        "planning.event_obligation_incomplete",
        "规划正式复合事件只完成了部分参与者、回应或承诺",
        "从正式大纲逐项投影事件完成清单，在调用语义审核前确定性核对明确命名的必需参与者。若缺项只对应一个哈希绑定、正文逐字匹配且事件归属唯一的正式义务，Runtime 仅把该正式原文追加到所属事件正文；来源不唯一、哈希失配或归属含糊时一律不猜。无法本地补齐时保留最佳完整规划，只重建所属完整正式段；若整段重建接近上下文安全线，则按连续正式事件所有权递归分包，精确投影各自编号或列表正文并绑定前序分包哈希，完成后无损合并。协议或传输失败单独计数，不消耗语义修复次数。候选补齐动作、回应、结果与承诺后，仍须重新通过本段、相邻边界和整篇审核，其他正式段保持不变。",
        (
            r"planning_required_participant_missing",
            r"正式复合事件.*遗漏.*(?:参与者|回应者|承诺方)",
            r"复合事件.*(?:只完成|遗漏).*(?:参与者|回应|承诺)",
        ),
    ),
    IncidentDefinition(
        "planning.atomic_beat_scope_mismatch",
        "原子节拍不属于当前正式事件",
        "先做确定性的等价实现与归属核对；确属越界时只重建拥有该节拍的完整规划段，并重新验证上下游事件顺序。",
        (
            r"原子节拍.*不属于当前事[件见]",
            r"atomic beat.*(?:not.*current event|out of scope|ownership)",
        ),
    ),
    IncidentDefinition(
        "planning.repair_anchor_collapse",
        "Planning repair anchor collapsed a complete event",
        "Runtime keeps the complete accepted plan as authority, shrinks broad model evidence only to an exact nested same-event block with sufficient semantic body, and rejects a collapsed event-body replacement. When the provider returned a beam_plan-style obligations or boundary summary rather than full prose, Runtime binds that summary to the exact retained event body and applies it as an amendment without deleting the accepted realization. The merged event then reruns retention, obligation, adjacent-handoff, and whole-plan validation. An ambiguous source body remains a packet protocol failure and retries from the last best plan before escalating to a complete affected-segment rebuild.",
        (
            r"event_body_collapsed",
            r"repair anchor.*(?:collapsed|too broad)",
            r"planning repair patch.*(?:event body|formal event|anchor)",
            r"修复锚点.*(?:事件正文|过大|收缩)",
        ),
    ),
    IncidentDefinition(
        "narrative.first_person_contract_missing",
        "First-person narrator contract missing or ambiguous",
        "Resolve the narrator from project metadata, explicit outline authority, or one unique narrator/protagonist; persist the contract and carry it through draft, split, retry, polish, targeted/manual revision, and final review. If multiple candidates remain, stop before generation and request user confirmation instead of guessing.",
        (
            r"narrator_confirmation_required",
            r"first[-_ ]person.*(?:contract|narrator).*(?:missing|ambiguous|required)",
            r"叙述者.*(?:尚未确认|无法唯一确认|需要确认)",
            r"第一人称.*(?:确认|叙述者).*(?:缺失|歧义)",
        ),
    ),
    IncidentDefinition(
        "draft.segment_integrity_failed",
        "正文分段越界、重复或完整性失败",
        "保留已验收前缀，仅返修失败的完整语义段；再次核对事件覆盖、前后交接、入口出口状态和整篇因果后继续。",
        (
            r"正文第.*段.*(?:越界|重复|正文异常)",
            r"正文第.*段.*没有通过本地检查",
            r"draft segment.*(?:out of scope|duplicate|integrity)",
        ),
    ),
    IncidentDefinition(
        "draft.split_merge_length_mismatch",
        "自动拆分或合并后的正文长度失配",
        "子任务只承担一个明确语义范围，合并父段后重新按父段目标验收；超长不截断，改为重新划分所有权或返修最小完整子段。",
        (
            r"自动拆分后的正文段.*明显超过",
            r"自动拆分.*(?:超长|长度|篇幅).*(?:失败|超过)",
            r"split.*merge.*(?:overlength|length mismatch)",
        ),
    ),
    IncidentDefinition(
        "draft.semantic_receipt_unsatisfied",
        "正文事件或入口出口状态缺少原文证据",
        "使用绑定正文哈希的精确证据重新验证；证据确实缺失时只重写对应完整段，并复核相邻交接与整篇逻辑。",
        (
            r"semantic receipt.*not satisfied",
            r"正文事件、入口或出口缺少可核对原文证据",
            r"正文语义完整性检查未通过",
        ),
    ),
    IncidentDefinition(
        "polish.local_validation_failed",
        "润色或精修候选未通过本地验证",
        "保留上一个完整合格版本，按失败证据缩小修改所有权而非删减叙事权威；通过原子节拍、视角、状态、衔接和整篇复核后才替换。",
        (
            r"正在精简要求后重新润色",
            r"精修.*无法通过本地验证",
            r"润色.*(?:本地验证|本地检查).*(?:失败|未通过)",
            r"polish.*local validation.*failed",
        ),
    ),
    IncidentDefinition(
        "review.issue_ledger_not_refreshed",
        "重新检测后问题优先级或证据未同步",
        "以最新正文哈希重建问题台账，合并同一问题的全部证据位置，重新计算未解决问题与最优先问题，不沿用过期结论。",
        (
            r"最需要处理的问题.*(?:没有|未).*更新",
            r"同一问题 id.*两个窗口",
            r"issue ledger.*(?:stale|not refreshed|evidence.*lost)",
        ),
    ),
    IncidentDefinition(
        "review.final_review_unavailable",
        "终审或语义复核暂时不可用",
        "保留已通过本地与语义检查的候选、修改决定和检查点，只重试终审边界；成功后重新核对候选哈希与完整问题台账。",
        (
            r"终审暂时不可用",
            r"语义复核暂时不可用",
            r"semantic review.*unavailable",
            r"final review.*unavailable",
        ),
    ),
)


def _normalize_component(value: str | None, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE).strip("-.")
    return normalized or fallback


def normalize_failure_text(message: str) -> str:
    text = unicodedata.normalize("NFKC", str(message or "")).strip().casefold()
    text = re.sub(r"\b[a-f0-9]{16,}\b", "<id>", text)
    text = re.sub(r"(?:[a-z]:[\\/]|/)[^\s;：:]+", "<path>", text)
    text = re.sub(r"segment[-_ ]?\d+", "segment-<n>", text)
    text = re.sub(r"第\s*\d+\s*(?:/\s*\d+\s*)?段", "第<n>段", text)
    text = re.sub(
        r"\b\d+\s*(?=(?:个|份|条|字|字符|characters?|tokens?|errors?|warnings?)\b)",
        "<n>", text,
    )
    return re.sub(r"\s+", " ", text)


_TYPED_INCIDENT_FAMILIES = {
    FailureClass.TRANSPORT: "provider.connection_failed",
    FailureClass.CREDENTIAL: "provider.credentials_unavailable",
    FailureClass.CAPABILITY: "provider.capability_mismatch",
    FailureClass.CONTEXT_CAPACITY: "model.context_capacity_preflight",
    FailureClass.OUTPUT_TRUNCATION: "model.output_truncated",
    FailureClass.SYNTAX_PROTOCOL: "parser.generated_artifact_shape",
    FailureClass.OWNERSHIP_EVIDENCE: "planning.review_evidence_binding_invalid",
    FailureClass.SEMANTIC_INVARIANT: "planning.structure_drift",
    FailureClass.QUALITY_REGRESSION: "polish.local_validation_failed",
    FailureClass.STALE_AUTHORITY: "runtime.stale_authority",
}


def classify_production_failure(
    message: str, *, workflow: str | None, stage: str | None,
    failure: ReliabilityFailure | None = None,
) -> dict[str, str]:
    normalized = normalize_failure_text(message)
    typed_family = _TYPED_INCIDENT_FAMILIES.get(
        failure.failure_class,
    ) if failure is not None else None
    definition = next((
        item for item in INCIDENT_DEFINITIONS if item.family == typed_family
    ), None) if typed_family else next((
        item for item in INCIDENT_DEFINITIONS
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in item.patterns)
    ), None)
    if definition is None:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        family = typed_family or f"unclassified.{digest}"
        title = "尚未归类的生产失败"
        resolution = "保留当前有效检查点和完整错误证据；完成根因分析后登记稳定问题家族、恢复路径与回归用例。"
    else:
        family = definition.family
        title = definition.title
        resolution = definition.known_resolution
    workflow_key = _normalize_component(workflow, "unknown-workflow")
    stage_key = _normalize_component(stage, "unknown-stage")
    result = {
        "incident_key": f"{workflow_key}:{stage_key}:{family}",
        "incident_family": family,
        "incident_title": title,
        "known_resolution": resolution,
        "normalized_failure": normalized,
    }
    if failure is not None:
        result.update({
            "failure_code": failure.code,
            "failure_class": failure.failure_class.value,
            "failure_boundary": failure.boundary,
            "failure_unit_id": failure.unit_id,
        })
    return result


def production_incident_catalog() -> list[dict[str, str]]:
    return [
        {
            "incident_family": item.family,
            "title": item.title,
            "known_resolution": item.known_resolution,
        }
        for item in INCIDENT_DEFINITIONS
    ]


def record_production_failure(
    db: Any, run_id: str, *, workflow: str | None, stage: str | None,
    raw_error: str, user_message: str, event_type: str,
    failure: ReliabilityFailure | None = None,
) -> dict[str, Any]:
    """Record a terminal incident without letting aggregation hide the failure."""
    incident = classify_production_failure(
        raw_error, workflow=workflow, stage=stage, failure=failure,
    )
    try:
        return db.record_run_failure(
            run_id, event_type, user_message, stage=stage, incident=incident,
        )
    except Exception:
        metadata: dict[str, Any] = {
            **incident, "incident_recording_degraded": True,
        }
        db.add_run_event(
            run_id, "error", event_type, user_message,
            stage=stage, metadata=metadata,
        )
        return metadata
